# EXPLAIN ANALYZE guide and plan observations

Run `python scripts/generate_legacy_data.py`, `python scripts/migrate_to_3nf.py`, and then `psql -d marketing_warehouse -f sql/04_performance.sql`. The SQL file labels five measured plans: before/after the order-date index, before/after the customer/latest-lead index, and the low-selectivity example.

## Results from this environment

No PostgreSQL server was available to execute this repository during file generation, so this document does not invent measured times, buffer counts, or claim to contain captured plans. The SQL script is the reproducible capture: save its complete `psql` output alongside the database version, row counts, and hardware when performing the run.

## What to compare in the captured plans

For the date-range aggregate, inspect whether the before plan scans the full `orders` table and whether the after plan uses `orders_order_date_idx` for the one-week range. For a small table or broad interval, PostgreSQL can correctly keep a sequential scan. Compare actual rows and `Buffers` as well as `Execution Time`; planner cost alone is an estimate, not observed runtime.

For attribution, the composite `leads_customer_created_idx (customer_id, lead_created_at DESC, lead_pk DESC) INCLUDE (campaign_id)` aligns with the lateral lookup's customer equality, timestamp cutoff, descending latest-first order, and returned campaign ID. An index or index-only scan may replace repeated scans/sorts when visibility-map and cache conditions permit.

The example `campaigns_platform_unhelpful_idx` targets a low-cardinality field on a tiny dimension table. PostgreSQL is likely to prefer a sequential scan because reading the table directly is cheaper than traversing the index and fetching rows. This is intentional evidence that indexes should be justified by plans and workload, not added indiscriminately.

## Reproducibility notes

- `EXPLAIN ANALYZE` executes the statement; use it on a representative non-production copy.
- The script runs `ANALYZE` after index creation. For repeatable comparisons, use the same data, statistics, server settings, and cache conditions.
- Timings vary with PostgreSQL version, storage, cache state, table size, and competing load; no fixed speedup is promised.
- Index creation in the script is persistent. Re-running it drops and recreates the order-date index and drops/recreates the lead index to ensure genuine before/after comparisons.
