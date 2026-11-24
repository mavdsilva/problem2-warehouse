#!/usr/bin/env python
import argparse
import os
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv



def connect() -> Any:
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "marketing_warehouse"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
    )


CAMPAIGNS: Tuple[Tuple[str, str], ...] = (
    ("Meta", "Summer Linen Prospecting"),
    ("Meta", "Festive Retargeting"),
    ("Google", "Search - Shirts"),
    ("Google", "Brand Defense"),
    ("Email", "Welcome Series"),
    ("Meta", "New Customer Lookalike"),
    ("Google", "Performance Max"),
    ("Email", "Winback"),
)
CATEGORIES: Tuple[str, ...] = (
    "Men > Shirts > Linen",
    "Men > Trousers > Cotton",
    "Women > Dresses > Occasion",
    "Women > Tops > Casual",
    "Home > Bedding > Cotton",
)
STATUSES: Tuple[str, ...] = ("PAID", "SHIPPED", "PENDING", "CANCELED", "CANCELLED", "REFUNDED")
PAYMENT_MODES: Tuple[str, ...] = ("UPI", "CARD", "COD", "NETBANKING")
STATES: Tuple[str, ...] = ("Maharashtra", "Karnataka", "Delhi", "Tamil Nadu", "Gujarat")
FIRST_NAMES: Tuple[str, ...] = ("Aarav", "Aditi", "Kabir", "Meera", "Rohan", "Isha", "Dev", "Anaya")
LAST_NAMES: Tuple[str, ...] = ("Shah", "Rao", "Kapoor", "Iyer", "Mehta", "Das", "Nair", "Singh")


def random_legacy_date(rng: random.Random, value: date) -> str:
    if rng.random() < 0.003:
        return "31/02/2025"
    if rng.random() < 0.08:
        return value.strftime("%d-%m-%Y")
    return value.isoformat()


def random_phone(rng: random.Random, customer_no: int) -> str:
    digits = "%010d" % (6000000000 + customer_no % 3999999999)
    style = rng.randrange(5)
    if style == 0:
        return "+91 " + digits[:5] + " " + digits[5:]
    if style == 1:
        return "0" + digits
    if style == 2:
        return digits[:5] + " " + digits[5:]
    if style == 3:
        return "+91" + digits
    return "555-ABCD"


def build_row(
    rng: random.Random,
    row_no: int,
    lead_pool: List[Dict[str, str]],
    daily_metrics: Dict[Tuple[Tuple[str, str], date], Tuple[float, int, int]],
) -> Tuple[object, ...]:
    has_lead = rng.random() < 0.78
    lead: Optional[Dict[str, str]] = rng.choice(lead_pool) if has_lead else None
    campaign = (
        (lead["platform"], lead["campaign_name"])
        if lead
        else rng.choice(CAMPAIGNS)
    )
    record_day = date(2024, 1, 1) + timedelta(days=rng.randrange(731))
    spend, impressions, clicks = daily_metrics[(campaign, record_day)]
    lead_id = lead["id"] if lead else (None if rng.random() < 0.72 else "")
    if lead is not None and rng.random() < 0.004:
        lead_id = None
    lead_name = lead["name"] if lead else None
    lead_phone = lead["phone"] if lead else None
    lead_email = lead["email"] if lead else None
    lead_created = lead["created"] if lead else None
    if lead is not None and rng.random() < 0.002:
        lead_created = "not-a-timestamp"

    has_order = lead is not None and rng.random() < 0.58
    order_id = "ORD-%07d" % row_no if has_order else None
    if has_order and rng.random() < 0.006:
        order_id = None
    order_day_text: Optional[str] = None
    qty: Optional[str] = None
    order_total: Optional[float] = None
    unit_price: Optional[float] = None
    gst: Optional[str] = None
    sku: Optional[str] = None
    product_name: Optional[str] = None
    category_path: Optional[str] = None
    payment_mode: Optional[str] = None
    order_status: Optional[str] = None
    if has_order:
        lead_day = datetime.fromisoformat(lead["created"].replace("Z", "+00:00")).date()
        order_day = min(lead_day + timedelta(days=rng.randint(0, 35)), date(2025, 12, 31))
        order_day_text = order_day.isoformat()
        if rng.random() < 0.004:
            order_day_text = "2025-99-42"
        qty = str(rng.randint(1, 5))
        if rng.random() < 0.012:
            qty = rng.choice(("0", "-2", "many", ""))
        unit_price = round(rng.uniform(399, 6999), 2)
        order_total = round(unit_price * max(1, int(qty)) if qty.isdigit() else unit_price, 2)
        gst = rng.choice(("5", "12", "18", "18.0", "GST"))
        product_no = rng.randint(1, 160)
        sku = "SKU-%03d" % product_no
        product_name = "Meridian " + (
            "Linen Shirt",
            "Cotton Trouser",
            "Everyday Dress",
            "Soft Top",
            "Cotton Sheet",
        )[product_no % 5]
        category_path = CATEGORIES[product_no % len(CATEGORIES)]
        if rng.random() < 0.005:
            sku = None
        if rng.random() < 0.03:
            category_path = " " + category_path.replace(" > ", "  > ") + " "
        payment_mode = rng.choice(PAYMENT_MODES)
        order_status = rng.choice(STATUSES)
        if rng.random() < 0.025:
            order_status = "CANCELED"

    if lead is None and rng.random() < 0.018:
        campaign = ("", campaign[1])
    return (
        random_legacy_date(rng, record_day),
        campaign[0],
        campaign[1],
        spend,
        str(impressions) if rng.random() > 0.004 else "unknown",
        str(clicks),
        lead_id,
        lead_name,
        lead_phone,
        lead_email,
        lead_created,
        order_id,
        order_day_text,
        lead["state"] if lead else None,
        sku,
        product_name,
        category_path,
        qty,
        unit_price,
        gst,
        order_total,
        payment_mode,
        order_status,
    )


def create_lead_pool(rng: random.Random, count: int) -> List[Dict[str, str]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    pool: List[Dict[str, str]] = []
    phone_by_customer: Dict[int, str] = {}
    for index in range(count):
        customer_no = index if rng.random() > 0.05 else max(0, index - rng.randint(1, min(index, 100) or 1))
        phone = phone_by_customer.setdefault(customer_no, random_phone(rng, customer_no + 1))
        created_at = start + timedelta(days=rng.randrange(700), minutes=rng.randrange(1440))
        campaign = rng.choice(CAMPAIGNS)
        pool.append(
            {
                "id": "LEAD-%06d" % index,
                "name": rng.choice(FIRST_NAMES) + " " + rng.choice(LAST_NAMES),
                "phone": phone,
                "email": "customer%05d@example.in" % customer_no,
                "created": created_at.isoformat(),
                "platform": campaign[0],
                "campaign_name": campaign[1],
                "state": rng.choice(STATES),
            }
        )
    return pool


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=50000, help="number of source records (default: 50000)")
    parser.add_argument("--seed", type=int, default=2025, help="deterministic random seed")
    args = parser.parse_args()
    if args.rows < 1:
        parser.error("--rows must be positive")

    rng = random.Random(args.seed)
    lead_pool = create_lead_pool(rng, max(1000, args.rows // 4))
    daily_metrics: Dict[Tuple[Tuple[str, str], date], Tuple[float, int, int]] = {}
    first_day = date(2024, 1, 1)
    for campaign_index, campaign in enumerate(CAMPAIGNS):
        for day_index in range(731):
            metric_rng = random.Random(args.seed + campaign_index * 100000 + day_index)
            impressions = metric_rng.randint(1000, 90000)
            clicks = metric_rng.randint(20, max(21, impressions // 8))
            daily_metrics[(campaign, first_day + timedelta(days=day_index))] = (
                round(500 + metric_rng.random() * 14500, 2),
                impressions,
                clicks,
            )
    rows = [
        build_row(rng, index + 1, lead_pool, daily_metrics)
        for index in range(args.rows)
    ]
    columns = (
        "record_date, platform, campaign_name, ad_spend, impressions, clicks, lead_id, "
        "lead_name, lead_phone, lead_email, lead_created_at, order_id, order_date, "
        "customer_state, product_sku, product_name, category_path, qty, unit_price, "
        "gst_percent, order_total, payment_mode, order_status"
    )
    ddl = """
        DROP TABLE IF EXISTS marketing_sales_master;
        CREATE TABLE marketing_sales_master (
            id SERIAL PRIMARY KEY,
            record_date VARCHAR(30),
            platform VARCHAR(30),
            campaign_name VARCHAR(200),
            ad_spend FLOAT,
            impressions VARCHAR(20),
            clicks VARCHAR(20),
            lead_id VARCHAR(50),
            lead_name VARCHAR(200),
            lead_phone VARCHAR(20),
            lead_email VARCHAR(200),
            lead_created_at VARCHAR(40),
            order_id VARCHAR(50),
            order_date VARCHAR(30),
            customer_state VARCHAR(100),
            product_sku VARCHAR(50),
            product_name VARCHAR(255),
            category_path VARCHAR(500),
            qty VARCHAR(20),
            unit_price FLOAT,
            gst_percent VARCHAR(10),
            order_total FLOAT,
            payment_mode VARCHAR(30),
            order_status VARCHAR(30)
        )
    """
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(ddl)
            execute_values(
                cursor,
                "INSERT INTO marketing_sales_master (" + columns + ") VALUES %s",
                rows,
                page_size=1000,
            )
            cursor.execute("SELECT COUNT(*) FROM marketing_sales_master")
            print("marketing_sales_master rows: {:,}".format(cursor.fetchone()[0]))


if __name__ == "__main__":
    main()
