# Problem 2: The Marketing Warehouse

A runnable PostgreSQL warehouse migration for Meridian Threads. The project creates a messy legacy extract, audits its defects, migrates clean records into a strict 3NF schema, runs eight analytics queries, demonstrates index plans, and builds a time-split conversion feature table.

## Requirements

- Python 3.9 or later
- PostgreSQL 12 or later (the performance example uses `INCLUDE`)
- Python packages in `requirements.txt`
- A PostgreSQL role permitted to create tables and indexes in the selected database

## Start here (PowerShell)

From this directory:

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with the connection details for an existing database. The defaults connect to `localhost:5432`, database `marketing_warehouse`, user `postgres`, password `postgres`. Create that database once if necessary:

```powershell
createdb -U postgres marketing_warehouse
```

Run the end-to-end workflow:

```powershell
python scripts/generate_legacy_data.py
psql -d marketing_warehouse -f sql/01_audit.sql
python scripts/migrate_to_3nf.py
psql -d marketing_warehouse -f sql/03_queries.sql
psql -d marketing_warehouse -f sql/04_performance.sql
python scripts/build_ml_dataset.py
```

The generator replaces `marketing_sales_master`; migration replaces the normalized table contents and reject log; the ML builder replaces its output table. Run commands from the project root so `.env` is found. `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` are read by all Python scripts. The test split cutoff is configurable with `ML_TEST_CUTOFF` (default `2025-10-01`).

To choose a different source size or deterministic seed:

```powershell
python scripts/generate_legacy_data.py --rows 50000 --seed 2025
```

## Source audit: six findings

`sql/01_audit.sql` returns evidence for each finding and explains its business consequence:

1. Dates are stored as text and include invalid formats, making time filters unsafe.
2. Campaign/day spend repeats on order rows, inflating spend and distorting ROAS.
3. Phones have country-code, leading-zero, whitespace, and invalid-value variants, fragmenting customer history.
4. Status spelling is inconsistent (`CANCELED` / `CANCELLED`) and may create divergent cancellation totals.
5. Quantity is text and includes zero, negative, and nonnumeric values, undermining line revenue and GST.
6. Natural keys such as lead ID, order ID, and product SKU can be absent, preventing dependable entity resolution and referential integrity.

## Warehouse ERD

```text
                         +------------------+
                         |    campaigns     |
                         | campaign_id (PK) |
                         +---+----------+---+
                             |          |
                   +---------v--+   +---v----------------+
                   |   leads    |   |   daily_ad_spend   |
                   | lead_pk PK |   | campaign/date (UQ) |
                   +-----+------+   +--------------------+
                         |
                   +-----v------+
                   | customers  |
                   |customer PK |
                   +---+-----+--+
                       |     |
                 +-----v+   +-v----------+
                 |orders|   |            |
                 | PK   |   |            |
                 +--+---+   |            |
                    |       |            |
              +-----v-------v--+   +-----v----------+
              |  order_items   |   |   products     |
              | order/product  |   | product_id PK  |
              +----------------+   +----+-----------+
                                        |
                                  +-----v-----------+
                                  |   categories    |
                                  | parent self-FK  |
                                  +-----------------+

                 +---------------------+
                 | migration_rejects  |
                 | legacy row + reason|
                 +---------------------+
```

### Normalization

- **1NF:** each table stores atomic values; item-level products and quantities are not embedded in order text.
- **2NF:** order-item facts depend on the complete order/product row, not just one part of its key.
- **3NF:** campaign, customer, product, and category descriptions live with their own keys; orders and leads reference those entities rather than repeating their descriptive attributes.

## Design decisions and assumptions

- Categories are stored as one row per full path segment, with `parent_category_id` linking parent and child. `category_path` makes the hierarchy idempotent and readable.
- A campaign is identified by the `(platform, campaign_name)` pair. A daily spend fact is unique by `(campaign_id, spend_date)`.
- Repeated campaign/day spend is collapsed using the maximum observed value (and the metrics from that same row); exact duplicates therefore count once. This avoids summing a repeated daily snapshot as if it were new spend. If conflicting snapshots occur, the maximum is deterministic but should be investigated as a source defect.
- Phones normalize to `+91` plus ten valid Indian mobile digits; invalid phones become `NULL`. Customer matching prefers normalized phone, then normalized email, then the lead ID as a fallback key.
- `CANCELED` is standardized to `CANCELLED`. Net revenue includes `PAID` and `SHIPPED` orders and is calculated before GST as `quantity * unit_price`.
- A malformed field is recorded in `migration_rejects` with its source row and reason. Valid independent facts from that row can still migrate; malformed item facts do not create an order item.
- Orders are tied to the customer resolved from the row's lead ID. A row without a valid lead/customer key cannot migrate as an order.
- Attribution always uses the customer's most recent lead at or before order timestamp; no matching lead results in `Unattributed`.
- The sample dates span 2024–2025 for reproducible time-based analytics. The generator is deterministic for a given seed.

## ML feature table

`scripts/build_ml_dataset.py` creates `ml_lead_conversion_features`, one row per loaded lead. It reports positive/negative class counts and percentages plus train/test row counts. The split is based on `lead_created_at` relative to `ML_TEST_CUTOFF`; `lead_hour_ist` and `lead_weekday_ist` use `Asia/Kolkata`.

All predictors are computed at lead creation time. Prior orders use `order_date < lead_created_at`; the label alone looks forward 14 days. The complete feature list, null treatment, and leakage safeguards are documented in [docs/data_dictionary.md](docs/data_dictionary.md).

## Performance proof

`sql/04_performance.sql` runs `EXPLAIN (ANALYZE, BUFFERS)` before and after:

1. `orders_order_date_idx` for a narrow order-date range.
2. `leads_customer_created_idx` for the latest-lead-per-customer attribution lookup.

It also demonstrates a low-selectivity `campaigns(platform)` index that can be unhelpful on a small table. PostgreSQL may choose a sequential scan even after an index is added; plan choice depends on table size, statistics, cache state, and data distribution. Plan interpretation and the method for capturing environment-specific output are in [docs/explain_plans.md](docs/explain_plans.md).

## Known limits

- This is a teaching-scale batch loader, not a streaming or incremental ETL. Migration truncates and rebuilds the warehouse.
- The source schema does not identify a customer on an order independently of its lead ID; rows lacking that relationship are rejected.
- `order_total` is retained from the source order header and is not reconciled to item totals; GST treatment of order totals is source-defined.
- Status values outside the known mapping, invalid dates, and invalid money values are rejected rather than guessed.
- Phone normalization intentionally targets Indian mobile numbers and is not a general international-number parser.
- The performance script's plan shape and timing are workload-dependent; there is no portable fixed speedup.

## Next steps

- Compare source and warehouse totals by campaign/day and quantify conflicting daily snapshots before production use.
- Add a durable source-to-warehouse lineage key and explicit order-to-lead attribution snapshot if historical attribution must not change when new leads arrive.
- Add automated integration tests against a disposable PostgreSQL instance and CI checks for migration reconciliation.
- Replace full refresh with checkpointed, idempotent incremental ingestion for production volumes.
