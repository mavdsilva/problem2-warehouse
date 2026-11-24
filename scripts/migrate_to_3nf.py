#!/usr/bin/env python
import json
import os
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from dotenv import load_dotenv


def connect() -> Any:
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "marketing_warehouse"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
    )


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT / "sql" / "02_schema_3nf.sql"
DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y")
STATUS_MAP = {
    "PAID": "PAID",
    "SHIPPED": "SHIPPED",
    "PENDING": "PENDING",
    "CANCELED": "CANCELLED",
    "CANCELLED": "CANCELLED",
    "REFUNDED": "REFUNDED",
}
def parse_date(value: Any) -> Optional[date]:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass
    return None


def parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    parsed: Optional[datetime]
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        for fmt in DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                pass
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_money(value: Any, allow_zero: bool = True) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        return None
    return result


def parse_int(value: Any, minimum: int = 0) -> Optional[int]:
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if result >= minimum else None


def normalize_phone(value: Any) -> Optional[str]:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if digits.startswith("0091"):
        digits = digits[4:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return None


def normalize_email(value: Any) -> Optional[str]:
    if value is None:
        return None
    email = str(value).strip().lower()
    if re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", email):
        return email
    return None


def normalize_campaign(value: Any) -> Optional[str]:
    if value is None:
        return None
    result = re.sub(r"\s+", " ", str(value)).strip()
    return result or None


def reject(cursor: Any, row: Dict[str, Any], reason: str) -> None:
    cursor.execute(
        "INSERT INTO migration_rejects (legacy_id, reason, source_row) VALUES (%s, %s, %s::jsonb)",
        (row["id"], reason, json.dumps(row, default=str)),
    )


def upsert_campaign(cursor: Any, platform: Any, campaign_name: Any) -> Optional[int]:
    platform_value = normalize_campaign(platform)
    campaign_value = normalize_campaign(campaign_name)
    if platform_value is None or campaign_value is None:
        return None
    cursor.execute(
        """
        INSERT INTO campaigns (platform, campaign_name) VALUES (%s, %s)
        ON CONFLICT (platform, campaign_name) DO UPDATE SET campaign_name = EXCLUDED.campaign_name
        RETURNING campaign_id
        """,
        (platform_value, campaign_value),
    )
    return int(cursor.fetchone()[0])


def upsert_customer(
    cursor: Any, lead_id: str, phone: Optional[str], email: Optional[str], state: Any
) -> int:
    key = "phone:" + phone if phone else ("email:" + email if email else "lead:" + lead_id)
    cursor.execute(
        """
        INSERT INTO customers (customer_key, phone_normalized, email_normalized, customer_state)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (customer_key) DO UPDATE SET
            phone_normalized = COALESCE(customers.phone_normalized, EXCLUDED.phone_normalized),
            email_normalized = COALESCE(customers.email_normalized, EXCLUDED.email_normalized),
            customer_state = COALESCE(customers.customer_state, EXCLUDED.customer_state)
        RETURNING customer_id
        """,
        (key, phone, email, str(state).strip() if state else None),
    )
    return int(cursor.fetchone()[0])


def upsert_category(cursor: Any, raw_path: Any) -> Optional[int]:
    if raw_path is None:
        return None
    parts = [re.sub(r"\s+", " ", part).strip() for part in str(raw_path).split(">")]
    if not parts or any(not part for part in parts):
        return None
    parent_id: Optional[int] = None
    path_parts: List[str] = []
    category_id: Optional[int] = None
    for part in parts:
        path_parts.append(part)
        path = " > ".join(path_parts)
        cursor.execute(
            """
            INSERT INTO categories (category_name, category_path, parent_category_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (category_path) DO UPDATE SET category_name = EXCLUDED.category_name
            RETURNING category_id
            """,
            (part, path, parent_id),
        )
        category_id = int(cursor.fetchone()[0])
        parent_id = category_id
    return category_id


def upsert_product(
    cursor: Any, sku: Any, product_name: Any, category_id: Optional[int], unit_price: Optional[Decimal]
) -> Optional[int]:
    sku_value = str(sku).strip() if sku is not None else ""
    name_value = str(product_name).strip() if product_name is not None else ""
    if not sku_value or not name_value:
        return None
    cursor.execute(
        """
        INSERT INTO products (product_sku, product_name, category_id, list_unit_price)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (product_sku) DO UPDATE SET
            product_name = EXCLUDED.product_name,
            category_id = COALESCE(products.category_id, EXCLUDED.category_id),
            list_unit_price = COALESCE(products.list_unit_price, EXCLUDED.list_unit_price)
        RETURNING product_id
        """,
        (sku_value, name_value, category_id, unit_price),
    )
    return int(cursor.fetchone()[0])


def source_totals(cursor: Any) -> Tuple[int, Decimal, int, Decimal]:
    cursor.execute(
        """
        SELECT COUNT(*),
               COALESCE(SUM(ad_spend::numeric), 0),
               COUNT(DISTINCT NULLIF(BTRIM(order_id), ''))
        FROM marketing_sales_master
        """
    )
    count, spend, order_count = cursor.fetchone()
    cursor.execute(
        """
        SELECT COALESCE(SUM(order_total::numeric), 0)
        FROM (
            SELECT order_id, MAX(order_total) AS order_total
            FROM marketing_sales_master
            WHERE NULLIF(BTRIM(order_id), '') IS NOT NULL AND order_total IS NOT NULL
            GROUP BY order_id
        ) unique_orders
        """
    )
    return int(count), Decimal(spend), int(order_count), Decimal(cursor.fetchone()[0])


def main() -> None:
    load_dotenv()
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError("Expected schema file at {}".format(SCHEMA_FILE))
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
            cursor.execute("SELECT to_regclass('public.marketing_sales_master')")
            if cursor.fetchone()[0] is None:
                raise RuntimeError("marketing_sales_master is missing; run generate_legacy_data.py first")
            before_rows, raw_spend, legacy_order_count, legacy_order_total = source_totals(cursor)
            cursor.execute(
                """
                TRUNCATE TABLE order_items, orders, leads, customers, daily_ad_spend,
                    products, categories, campaigns, migration_rejects
                RESTART IDENTITY CASCADE
                """
            )
            cursor.execute("SELECT * FROM marketing_sales_master ORDER BY id")
            column_names = [description[0] for description in cursor.description]
            source_rows = [dict(zip(column_names, values)) for values in cursor.fetchall()]

            campaign_cache: Dict[Tuple[str, str], int] = {}
            spend_by_day: Dict[Tuple[int, date], Tuple[Decimal, int, int]] = {}
            customer_by_lead: Dict[str, int] = {}
            seen_leads = set()
            order_by_external_id: Dict[str, Tuple[int, int, datetime]] = {}

            for row in source_rows:
                campaign_name = normalize_campaign(row["campaign_name"])
                platform = normalize_campaign(row["platform"])
                campaign_id: Optional[int] = None
                if platform and campaign_name:
                    campaign_key = (platform, campaign_name)
                    if campaign_key not in campaign_cache:
                        campaign_id_value = upsert_campaign(cursor, platform, campaign_name)
                        if campaign_id_value is None:
                            raise RuntimeError("Validated campaign could not be inserted")
                        campaign_cache[campaign_key] = campaign_id_value
                    campaign_id = campaign_cache[campaign_key]
                elif row["ad_spend"] is not None or row["lead_id"] or row["order_id"]:
                    reject(cursor, row, "Missing platform or campaign name")

                spend_date = parse_date(row["record_date"])
                amount = parse_money(row["ad_spend"])
                if spend_date is None:
                    reject(cursor, row, "Invalid record_date; daily spend was not loaded")
                elif amount is None:
                    reject(cursor, row, "Invalid or negative ad_spend; daily spend was not loaded")
                elif campaign_id is not None:
                    impressions = parse_int(row["impressions"])
                    clicks = parse_int(row["clicks"])
                    if impressions is None or clicks is None:
                        reject(cursor, row, "Invalid impressions or clicks; invalid metric treated as zero")
                    metrics = (amount, impressions or 0, clicks or 0)
                    key = (campaign_id, spend_date)
                    current = spend_by_day.get(key)
                    if current is None or metrics[0] > current[0]:
                        spend_by_day[key] = metrics

                raw_lead_id = str(row["lead_id"]).strip() if row["lead_id"] is not None else ""
                if raw_lead_id and raw_lead_id not in seen_leads:
                    created_at = parse_timestamp(row["lead_created_at"])
                    if created_at is None:
                        reject(cursor, row, "Invalid lead_created_at; lead was not loaded")
                    else:
                        phone = normalize_phone(row["lead_phone"])
                        email = normalize_email(row["lead_email"])
                        customer_id = upsert_customer(cursor, raw_lead_id, phone, email, row["customer_state"])
                        cursor.execute(
                            """
                            INSERT INTO leads (lead_id, customer_id, campaign_id, lead_created_at, lead_name)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (lead_id) DO NOTHING
                            RETURNING lead_pk
                            """,
                            (
                                raw_lead_id,
                                customer_id,
                                campaign_id,
                                created_at,
                                str(row["lead_name"]).strip() if row["lead_name"] else None,
                            ),
                        )
                        if cursor.fetchone() is None:
                            cursor.execute("SELECT customer_id FROM leads WHERE lead_id = %s", (raw_lead_id,))
                            customer_id = int(cursor.fetchone()[0])
                        customer_by_lead[raw_lead_id] = customer_id
                        seen_leads.add(raw_lead_id)
                elif not raw_lead_id and any(
                    row[key] for key in ("lead_name", "lead_phone", "lead_email", "lead_created_at")
                ):
                    reject(cursor, row, "Missing lead_id; lead was not loaded")

                raw_order_id = str(row["order_id"]).strip() if row["order_id"] is not None else ""
                if not raw_order_id:
                    if row["order_date"] or row["product_sku"] or row["qty"]:
                        reject(cursor, row, "Missing order_id; order and item were not loaded")
                    continue
                order_date = parse_timestamp(row["order_date"])
                customer_id = customer_by_lead.get(raw_lead_id)
                if order_date is None:
                    reject(cursor, row, "Invalid order_date; order and item were not loaded")
                    continue
                if customer_id is None:
                    reject(cursor, row, "Order has no valid lead/customer key")
                    continue
                status_text = normalize_campaign(row["order_status"])
                status = STATUS_MAP.get(status_text.upper()) if status_text else None
                total = parse_money(row["order_total"])
                if status is None or total is None:
                    reject(cursor, row, "Invalid order_status or order_total; order was not loaded")
                    continue

                if raw_order_id in order_by_external_id:
                    order_pk, first_customer_id, first_order_date = order_by_external_id[raw_order_id]
                    if first_customer_id != customer_id or first_order_date != order_date:
                        reject(cursor, row, "Conflicting customer or date for duplicate order_id")
                        continue
                else:
                    cursor.execute(
                        """
                        INSERT INTO orders (order_id, customer_id, order_date, order_status, order_total, payment_mode)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (order_id) DO NOTHING
                        RETURNING order_pk
                        """,
                        (
                            raw_order_id,
                            customer_id,
                            order_date,
                            status,
                            total,
                            normalize_campaign(row["payment_mode"]),
                        ),
                    )
                    inserted = cursor.fetchone()
                    if inserted is None:
                        cursor.execute(
                            "SELECT order_pk, customer_id, order_date FROM orders WHERE order_id = %s",
                            (raw_order_id,),
                        )
                        existing = cursor.fetchone()
                        if existing is None:
                            reject(cursor, row, "Could not resolve duplicate order_id")
                            continue
                        order_pk = int(existing[0])
                        if int(existing[1]) != customer_id or existing[2] != order_date:
                            reject(cursor, row, "Conflicting customer or date for duplicate order_id")
                            continue
                    else:
                        order_pk = int(inserted[0])
                    order_by_external_id[raw_order_id] = (order_pk, customer_id, order_date)

                quantity = parse_int(row["qty"], minimum=1)
                unit_price = parse_money(row["unit_price"])
                gst = parse_money(row["gst_percent"])
                if gst is not None and gst > Decimal("100.00"):
                    gst = None
                category_id = upsert_category(cursor, row["category_path"])
                product_id = upsert_product(
                    cursor, row["product_sku"], row["product_name"], category_id, unit_price
                )
                if quantity is None or unit_price is None or gst is None or product_id is None:
                    reject(cursor, row, "Invalid or missing order item quantity, price, GST, SKU, or product")
                    continue
                cursor.execute(
                    """
                    INSERT INTO order_items (order_pk, product_id, quantity, unit_price, gst_percent)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (order_pk, product_id) DO UPDATE SET
                        quantity = order_items.quantity + EXCLUDED.quantity
                    """,
                    (order_pk, product_id, quantity, unit_price, gst),
                )

            for (campaign_id, spend_date), (amount, impressions, clicks) in spend_by_day.items():
                cursor.execute(
                    """
                    INSERT INTO daily_ad_spend (campaign_id, spend_date, ad_spend, impressions, clicks)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (campaign_id, spend_date, amount, impressions, clicks),
                )
            cursor.execute("ANALYZE")
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM leads),
                    (SELECT COUNT(*) FROM orders),
                    (SELECT COUNT(*) FROM order_items),
                    (SELECT COUNT(*) FROM daily_ad_spend),
                    (SELECT COUNT(*) FROM migration_rejects),
                    (SELECT COALESCE(SUM(ad_spend), 0) FROM daily_ad_spend),
                    (SELECT COALESCE(SUM(order_total), 0) FROM orders)
                """
            )
            after = cursor.fetchone()
            after_spend = Decimal(after[5])
            print("Legacy source rows: {:,}".format(before_rows))
            print("Distinct source order IDs: {:,}; loaded warehouse orders: {:,}".format(legacy_order_count, after[1]))
            print("Warehouse: {:,} leads, {:,} orders, {:,} order items, {:,} campaign-days".format(*after[:4]))
            print("Rejected field/record issues: {:,}".format(after[4]))
            print("Legacy raw spend row-sum: {:,.2f}".format(raw_spend))
            print("Warehouse deduplicated spend: {:,.2f}".format(after_spend))
            print(
                "Spend difference explained: {:,.2f} removed by collapsing repeated campaign/day spend rows "
                "(and excluding rows with invalid dates, spend, or campaign keys).".format(raw_spend - after_spend)
            )
            print("Legacy unique-order value (source MAX per order_id): {:,.2f}".format(legacy_order_total))
            print("Warehouse order_total sum: {:,.2f}".format(Decimal(after[6])))
            print(
                "Order-value difference reflects invalid order records, missing customer keys, and invalid dates; "
                "valid orders retain the source order_total."
            )


if __name__ == "__main__":
    main()
