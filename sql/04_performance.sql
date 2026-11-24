ANALYZE orders;
ANALYZE leads;


DROP INDEX IF EXISTS orders_order_date_idx;
\echo 'BEFORE INDEX 1: order date range'
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*), SUM(order_total)
FROM orders
WHERE order_date >= TIMESTAMPTZ '2025-03-01 00:00:00+00'
  AND order_date < TIMESTAMPTZ '2025-03-08 00:00:00+00';

CREATE INDEX IF NOT EXISTS orders_order_date_idx ON orders (order_date);
ANALYZE orders;


\echo 'AFTER INDEX 1: order date range'
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*), SUM(order_total)
FROM orders
WHERE order_date >= TIMESTAMPTZ '2025-03-01 00:00:00+00'
  AND order_date < TIMESTAMPTZ '2025-03-08 00:00:00+00';


DROP INDEX IF EXISTS leads_customer_created_idx;
\echo 'BEFORE INDEX 2: latest lead by customer'
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.order_id, latest.campaign_id
FROM orders AS o
LEFT JOIN LATERAL (
    SELECT l.campaign_id
    FROM leads AS l
    WHERE l.customer_id = o.customer_id
      AND l.lead_created_at <= o.order_date
    ORDER BY l.lead_created_at DESC, l.lead_pk DESC
    LIMIT 1
) AS latest ON TRUE
WHERE o.order_date >= TIMESTAMPTZ '2025-03-01 00:00:00+00'
  AND o.order_date < TIMESTAMPTZ '2025-03-08 00:00:00+00';

CREATE INDEX leads_customer_created_idx
    ON leads (customer_id, lead_created_at DESC, lead_pk DESC)
    INCLUDE (campaign_id);
ANALYZE leads;


\echo 'AFTER INDEX 2: latest lead by customer'
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.order_id, latest.campaign_id
FROM orders AS o
LEFT JOIN LATERAL (
    SELECT l.campaign_id
    FROM leads AS l
    WHERE l.customer_id = o.customer_id
      AND l.lead_created_at <= o.order_date
    ORDER BY l.lead_created_at DESC, l.lead_pk DESC
    LIMIT 1
) AS latest ON TRUE
WHERE o.order_date >= TIMESTAMPTZ '2025-03-01 00:00:00+00'
  AND o.order_date < TIMESTAMPTZ '2025-03-08 00:00:00+00';

CREATE INDEX IF NOT EXISTS campaigns_platform_unhelpful_idx ON campaigns (platform);
ANALYZE campaigns;
\echo 'UNHELPFUL INDEX EXAMPLE: low-selectivity platform filter'
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*)
FROM campaigns
WHERE platform = 'Meta';
