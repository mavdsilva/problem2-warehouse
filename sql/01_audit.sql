SELECT id, record_date
FROM marketing_sales_master
WHERE record_date IS NULL
   OR BTRIM(record_date) !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
ORDER BY id
LIMIT 25;

SELECT record_date, platform, campaign_name, COUNT(*) AS source_rows,
       MIN(ad_spend) AS minimum_spend, MAX(ad_spend) AS maximum_spend,
       SUM(ad_spend) AS inflated_raw_sum
FROM marketing_sales_master
WHERE record_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
GROUP BY record_date, platform, campaign_name
HAVING COUNT(*) > 1
ORDER BY source_rows DESC
LIMIT 25;

SELECT lead_phone, COUNT(DISTINCT lead_id) AS lead_ids
FROM marketing_sales_master
WHERE NULLIF(BTRIM(lead_phone), '') IS NOT NULL
GROUP BY lead_phone
ORDER BY lead_ids DESC, lead_phone
LIMIT 25;

SELECT UPPER(BTRIM(order_status)) AS raw_status, COUNT(*) AS row_count
FROM marketing_sales_master
WHERE NULLIF(BTRIM(order_status), '') IS NOT NULL
GROUP BY UPPER(BTRIM(order_status))
ORDER BY row_count DESC;

SELECT id, order_id, qty
FROM marketing_sales_master
WHERE qty IS NOT NULL
  AND CASE
          WHEN BTRIM(qty) ~ '^[0-9]+$' THEN BTRIM(qty)::numeric <= 0
          ELSE TRUE
      END
ORDER BY id
LIMIT 25;

SELECT COUNT(*) FILTER (WHERE NULLIF(BTRIM(lead_id), '') IS NULL) AS missing_lead_id,
       COUNT(*) FILTER (WHERE NULLIF(BTRIM(order_id), '') IS NULL
                          AND (order_date IS NOT NULL OR product_sku IS NOT NULL)) AS missing_order_id,
       COUNT(*) FILTER (WHERE NULLIF(BTRIM(product_sku), '') IS NULL
                          AND order_id IS NOT NULL) AS missing_product_sku
FROM marketing_sales_master;
