import os
from datetime import date
from typing import Any

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


CREATE_FEATURES = """
CREATE TABLE ml_lead_conversion_features AS
WITH lead_features AS (
    SELECT l.lead_pk,
           l.lead_id,
           l.lead_created_at,
           c.platform,
           l.campaign_id,
           EXTRACT(HOUR FROM (l.lead_created_at AT TIME ZONE 'Asia/Kolkata'))::integer AS lead_hour_ist,
           EXTRACT(ISODOW FROM (l.lead_created_at AT TIME ZONE 'Asia/Kolkata'))::integer AS lead_weekday_ist,
           (cu.phone_normalized ~ '^\\+91[6-9][0-9]{9}$') AS is_valid_phone,
           (cu.email_normalized ~* '^[A-Z0-9._%%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}$') AS is_valid_email,
           (COUNT(o.order_pk) FILTER (
               WHERE o.order_status IN ('PAID', 'SHIPPED')
                 AND o.order_date < l.lead_created_at
           ))::integer AS prior_orders_count,
           (EXTRACT(EPOCH FROM (
               l.lead_created_at - MAX(o.order_date) FILTER (
                   WHERE o.order_status IN ('PAID', 'SHIPPED')
                     AND o.order_date < l.lead_created_at
               )
           )) / 86400.0)::double precision AS days_since_last_order,
           EXISTS (
               SELECT 1
               FROM orders AS future_order
               WHERE future_order.customer_id = l.customer_id
                 AND future_order.order_status IN ('PAID', 'SHIPPED')
                 AND future_order.order_date >= l.lead_created_at
                 AND future_order.order_date < l.lead_created_at + INTERVAL '14 days'
           )::integer AS ordered_within_14d
    FROM leads AS l
    JOIN customers AS cu USING (customer_id)
    LEFT JOIN campaigns AS c USING (campaign_id)
    LEFT JOIN orders AS o ON o.customer_id = l.customer_id
    GROUP BY l.lead_pk, l.lead_id, l.lead_created_at, c.platform, l.campaign_id,
             cu.phone_normalized, cu.email_normalized, l.customer_id
)
SELECT lead_id, lead_created_at, platform, campaign_id, lead_hour_ist, lead_weekday_ist,
       COALESCE(is_valid_phone, FALSE) AS is_valid_phone,
       COALESCE(is_valid_email, FALSE) AS is_valid_email,
       prior_orders_count,
       days_since_last_order,
       ordered_within_14d,
       CASE WHEN lead_created_at < %s::date THEN 'train' ELSE 'test' END AS split
FROM lead_features
"""


def main() -> None:
    load_dotenv()
    cutoff_text = os.getenv("ML_TEST_CUTOFF", "2025-10-01")
    cutoff = date.fromisoformat(cutoff_text)
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS ml_lead_conversion_features")
            cursor.execute(CREATE_FEATURES, (cutoff,))
            cursor.execute(
                "ALTER TABLE ml_lead_conversion_features ADD PRIMARY KEY (lead_id)"
            )
            cursor.execute(
                """
                SELECT ordered_within_14d, COUNT(*)
                FROM ml_lead_conversion_features
                GROUP BY ordered_within_14d
                ORDER BY ordered_within_14d
                """
            )
            balance = cursor.fetchall()
            total = sum(int(count) for _, count in balance)
            print("Feature rows: {:,}".format(total))
            for label, count in balance:
                percent = (100.0 * count / total) if total else 0.0
                print("ordered_within_14d={}: {:,} ({:.2f}%)".format(label, count, percent))
            cursor.execute(
                "SELECT split, COUNT(*) FROM ml_lead_conversion_features GROUP BY split ORDER BY split"
            )
            print("Time split cutoff: {}".format(cutoff.isoformat()))
            for split_name, count in cursor.fetchall():
                print("{}: {:,}".format(split_name, count))
            cursor.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT lead_id)
                FROM ml_lead_conversion_features
                """
            )
            rows, distinct_leads = cursor.fetchone()
            if rows != distinct_leads:
                raise RuntimeError("Feature table does not contain exactly one row per lead")


if __name__ == "__main__":
    main()
