# ML feature table data dictionary

`ml_lead_conversion_features` has exactly one row for each row in `leads`. The builder verifies `COUNT(*) = COUNT(DISTINCT lead_id)` before committing its transaction.

| Column | PostgreSQL type | Meaning / construction |
|---|---|---|
| `lead_id` | `varchar(50)` | Source lead key; one output row per key. |
| `lead_created_at` | `timestamptz` | Timestamp for the prediction point and time split. |
| `platform` | `varchar(30)` nullable | Platform of the lead's campaign; null when campaign is missing. |
| `campaign_id` | `bigint` nullable | Campaign foreign key associated with the lead. |
| `lead_hour_ist` | `integer` | Hour of lead creation in `Asia/Kolkata`, 0–23. |
| `lead_weekday_ist` | `integer` | ISO weekday in India time, Monday=1 through Sunday=7. |
| `is_valid_phone` | `boolean` | True when normalized phone matches `+91` and ten valid Indian mobile digits. Null normalized phone is false. |
| `is_valid_email` | `boolean` | True when the normalized email matches the simple address validation pattern. Missing/invalid email is false. |
| `prior_orders_count` | `integer` | Count of this customer's `PAID`/`SHIPPED` orders with `order_date < lead_created_at`. |
| `days_since_last_order` | `double precision` nullable | Elapsed days from the latest prior net order to lead creation; null when no prior net order exists. |
| `ordered_within_14d` | `integer` | Target: 1 if a `PAID`/`SHIPPED` order occurs at or after lead creation and before lead creation + 14 days; otherwise 0. |
| `split` | `text` | `train` when lead date is before `ML_TEST_CUTOFF`; `test` on/after cutoff. |

## Class balance and missing values

The builder prints the exact target counts and percentages for every run. Balance depends on the loaded source and generator seed, so it is intentionally measured from the produced table rather than copied as a stale constant. It also prints the exact train/test row counts and cutoff.

- Invalid or missing phone/email: represented as `FALSE`, not dropped.
- Missing campaign: platform and campaign ID remain `NULL`; the lead can still have other valid features.
- No historical order: `prior_orders_count` is `0`; `days_since_last_order` is `NULL` (there is no fabricated age or sentinel).
- All feature rows remain present even if an input attribute is missing. Invalid required lead identifiers/timestamps are excluded from `leads` during ETL and are visible in `migration_rejects`.

## Leakage prevention

The prediction point is `lead_created_at`. Every predictor is available by that time: timestamps are converted to IST, phone/email validation uses normalized customer attributes, and historical orders strictly satisfy `order_date < lead_created_at`. The 14-day target is generated separately with a forward-looking existence check and is not included in the predictors. The train/test assignment is chronological, not random. Do not use the target or post-lead order fields as model inputs.

The simple label treats no qualifying order in the warehouse as a negative. In an operational model, only score leads whose full 14-day outcome window has matured; this generated dataset deliberately bounds lead creation dates to leave a follow-up window in the sample.
