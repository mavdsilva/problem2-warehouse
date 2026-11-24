SELECT c.platform,
       c.campaign_name,
       DATE_TRUNC('week', s.spend_date)::date AS week_start,
       SUM(s.impressions) AS impressions,
       SUM(s.clicks) AS clicks,
       SUM(s.clicks)::numeric / NULLIF(SUM(s.impressions), 0) AS ctr,
       SUM(s.ad_spend) / NULLIF(SUM(s.clicks), 0) AS cpc
FROM daily_ad_spend AS s
JOIN campaigns AS c USING (campaign_id)
GROUP BY c.platform, c.campaign_name, DATE_TRUNC('week', s.spend_date)::date
ORDER BY week_start, c.platform, c.campaign_name;

WITH attributed_orders AS (
    SELECT o.order_pk, picked.campaign_id,
           SUM(oi.quantity * oi.unit_price) AS net_revenue
    FROM orders AS o
    JOIN order_items AS oi USING (order_pk)
    JOIN customers AS cu USING (customer_id)
    LEFT JOIN LATERAL (
        SELECT l.campaign_id
        FROM leads AS l
        WHERE l.customer_id = cu.customer_id
          AND l.lead_created_at <= o.order_date
        ORDER BY l.lead_created_at DESC, l.lead_pk DESC
        LIMIT 1
    ) AS picked ON TRUE
    WHERE o.order_status IN ('PAID', 'SHIPPED')
    GROUP BY o.order_pk, picked.campaign_id
)
SELECT c.platform, c.campaign_name,
       COALESCE(SUM(a.net_revenue), 0) AS net_revenue,
       RANK() OVER (PARTITION BY c.platform ORDER BY COALESCE(SUM(a.net_revenue), 0) DESC) AS revenue_rank
FROM campaigns AS c
LEFT JOIN attributed_orders AS a ON a.campaign_id = c.campaign_id
GROUP BY c.campaign_id, c.platform, c.campaign_name
ORDER BY c.platform, revenue_rank, c.campaign_name;

SELECT c.platform, c.campaign_name,
       COUNT(DISTINCT l.lead_pk) AS leads,
       COUNT(DISTINCT l.lead_pk) FILTER (WHERE converted.lead_pk IS NOT NULL) AS leads_converted_within_14d,
       (COUNT(DISTINCT l.lead_pk) FILTER (WHERE converted.lead_pk IS NOT NULL))::numeric
           / NULLIF(COUNT(DISTINCT l.lead_pk), 0) AS conversion_rate_14d
FROM campaigns AS c
LEFT JOIN leads AS l ON l.campaign_id = c.campaign_id
LEFT JOIN LATERAL (
    SELECT l0.lead_pk
    FROM orders AS o
    JOIN leads AS l0 ON l0.customer_id = o.customer_id
    WHERE l0.lead_pk = l.lead_pk
      AND o.order_status IN ('PAID', 'SHIPPED')
      AND o.order_date >= l.lead_created_at
      AND o.order_date < l.lead_created_at + INTERVAL '14 days'
    LIMIT 1
) AS converted ON TRUE
GROUP BY c.campaign_id, c.platform, c.campaign_name
ORDER BY c.platform, c.campaign_name;

SELECT o.order_id, o.order_date, o.order_status, cu.customer_id,
       COALESCE(c.platform || ' / ' || c.campaign_name, 'Unattributed') AS attributed_campaign,
       o.order_total
FROM orders AS o
JOIN customers AS cu USING (customer_id)
LEFT JOIN LATERAL (
    SELECT l.campaign_id
    FROM leads AS l
    WHERE l.customer_id = cu.customer_id
      AND l.lead_created_at <= o.order_date
    ORDER BY l.lead_created_at DESC, l.lead_pk DESC
    LIMIT 1
) AS picked ON TRUE
LEFT JOIN campaigns AS c ON c.campaign_id = picked.campaign_id
ORDER BY o.order_date, o.order_id;

WITH bounds AS (
    SELECT MIN(spend_date) AS first_day, MAX(spend_date) AS last_day
    FROM daily_ad_spend
),
date_spine AS (
    SELECT spine.generated_day::date AS spend_date
    FROM bounds,
         GENERATE_SERIES(first_day::timestamp, last_day::timestamp, INTERVAL '1 day') AS spine(generated_day)
    WHERE first_day IS NOT NULL
),
platforms AS (
    SELECT DISTINCT platform FROM campaigns
),
platform_day AS (
    SELECT p.platform, d.spend_date, COALESCE(SUM(s.ad_spend), 0) AS daily_spend
    FROM platforms AS p
    CROSS JOIN date_spine AS d
    LEFT JOIN campaigns AS c ON c.platform = p.platform
    LEFT JOIN daily_ad_spend AS s
      ON s.campaign_id = c.campaign_id AND s.spend_date = d.spend_date
    GROUP BY p.platform, d.spend_date
)
SELECT platform, spend_date, daily_spend,
       SUM(daily_spend) OVER (
           PARTITION BY platform ORDER BY spend_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
       ) AS running_spend,
       AVG(daily_spend) OVER (
           PARTITION BY platform ORDER BY spend_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
       ) AS moving_avg_7d
FROM platform_day
ORDER BY platform, spend_date;

WITH ranked_leads AS (
    SELECT cu.phone_normalized, l.lead_id, l.lead_created_at, l.lead_pk,
           ROW_NUMBER() OVER (
               PARTITION BY cu.phone_normalized ORDER BY l.lead_created_at, l.lead_pk
           ) AS keep_rank,
           COUNT(*) OVER (PARTITION BY cu.phone_normalized) AS phone_lead_count
    FROM leads AS l
    JOIN customers AS cu USING (customer_id)
    WHERE cu.phone_normalized IS NOT NULL
)
SELECT phone_normalized, lead_id, lead_created_at, keep_rank,
       CASE WHEN keep_rank = 1 THEN 'KEEP' ELSE 'DUPLICATE_OF_EARLIEST' END AS disposition
FROM ranked_leads
WHERE phone_lead_count > 1
ORDER BY phone_normalized, keep_rank;

WITH RECURSIVE category_rollup AS (
    SELECT category_id AS descendant_id, category_id AS ancestor_id,
           ARRAY[category_id] AS visited
    FROM categories
    UNION ALL
    SELECT r.descendant_id, parent.parent_category_id,
           r.visited || parent.parent_category_id
    FROM category_rollup AS r
    JOIN categories AS parent ON parent.category_id = r.ancestor_id
    WHERE parent.parent_category_id IS NOT NULL
      AND NOT parent.parent_category_id = ANY(r.visited)
),
descendant_revenue AS (
    SELECT p.category_id AS descendant_id,
           SUM(oi.quantity * oi.unit_price) AS net_revenue
    FROM order_items AS oi
    JOIN orders AS o USING (order_pk)
    JOIN products AS p USING (product_id)
    WHERE o.order_status IN ('PAID', 'SHIPPED')
      AND p.category_id IS NOT NULL
    GROUP BY p.category_id
)
SELECT ancestor.category_id, ancestor.category_name, ancestor.category_path,
       COALESCE(SUM(dr.net_revenue), 0) AS rolled_up_net_revenue
FROM category_rollup AS r
JOIN categories AS ancestor ON ancestor.category_id = r.ancestor_id
LEFT JOIN descendant_revenue AS dr ON dr.descendant_id = r.descendant_id
GROUP BY ancestor.category_id, ancestor.category_name, ancestor.category_path
ORDER BY ancestor.category_path;

WITH attributed_net_orders AS (
    SELECT o.order_pk, o.customer_id, o.order_date, picked.campaign_id,
           SUM(oi.quantity * oi.unit_price) AS net_revenue
    FROM orders AS o
    JOIN order_items AS oi USING (order_pk)
    LEFT JOIN LATERAL (
        SELECT l.campaign_id
        FROM leads AS l
        WHERE l.customer_id = o.customer_id
          AND l.lead_created_at <= o.order_date
        ORDER BY l.lead_created_at DESC, l.lead_pk DESC
        LIMIT 1
    ) AS picked ON TRUE
    WHERE o.order_status IN ('PAID', 'SHIPPED')
    GROUP BY o.order_pk, o.customer_id, o.order_date, picked.campaign_id
),
first_net_order AS (
    SELECT DISTINCT ON (customer_id) customer_id, order_pk, order_date, campaign_id
    FROM attributed_net_orders
    ORDER BY customer_id, order_date, order_pk
),
monthly_revenue AS (
    SELECT campaign_id, DATE_TRUNC('month', order_date)::date AS month_start,
           SUM(net_revenue) AS net_revenue
    FROM attributed_net_orders
    WHERE campaign_id IS NOT NULL
    GROUP BY campaign_id, DATE_TRUNC('month', order_date)::date
),
monthly_new_customers AS (
    SELECT campaign_id, DATE_TRUNC('month', order_date)::date AS month_start,
           COUNT(*) AS new_customers
    FROM first_net_order
    WHERE campaign_id IS NOT NULL
    GROUP BY campaign_id, DATE_TRUNC('month', order_date)::date
),
monthly_spend AS (
    SELECT campaign_id, DATE_TRUNC('month', spend_date)::date AS month_start,
           SUM(ad_spend) AS ad_spend
    FROM daily_ad_spend
    GROUP BY campaign_id, DATE_TRUNC('month', spend_date)::date
),
campaign_months AS (
    SELECT campaign_id, month_start FROM monthly_spend
    UNION
    SELECT campaign_id, month_start FROM monthly_revenue
    UNION
    SELECT campaign_id, month_start FROM monthly_new_customers
)
SELECT c.platform, c.campaign_name, cm.month_start,
       COALESCE(s.ad_spend, 0) AS ad_spend,
       COALESCE(n.new_customers, 0) AS new_customers,
       COALESCE(r.net_revenue, 0) AS net_revenue,
       s.ad_spend / NULLIF(n.new_customers, 0) AS cac,
       r.net_revenue / NULLIF(s.ad_spend, 0) AS roas
FROM campaign_months AS cm
JOIN campaigns AS c USING (campaign_id)
LEFT JOIN monthly_spend AS s USING (campaign_id, month_start)
LEFT JOIN monthly_new_customers AS n USING (campaign_id, month_start)
LEFT JOIN monthly_revenue AS r USING (campaign_id, month_start)
ORDER BY c.platform, c.campaign_name, cm.month_start;
