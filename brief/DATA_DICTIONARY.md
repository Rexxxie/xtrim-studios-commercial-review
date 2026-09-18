# Xtrim Studios — Data Dictionary

> Maintained by Ops. Last reviewed: *(blank)*.
> **Treat this as a claim, not a fact.** Parts of it were written before the 2024 system
> change and never updated. Where the data disagrees with this document, the data wins —
> but you must say so in your quality report. At least four statements below are wrong.

---

## clients_export.csv
CRM export. One row per client. *(Ops believes this is unique on `client_id`.)*

| Column | Type | Notes |
|---|---|---|
| client_id | text | Format `XT-#####`. Primary key. |
| client_name | text | Company name or individual's full name |
| type | text | `Corporate` or `Individual` |
| email | text | Always populated |
| phone | text | Nigerian mobile format |
| city | text | Shoot base city, not necessarily billing city |
| country | text | ISO country name |
| billing_currency | text | `NGN`, `USD` or `GBP` |
| signup_date | date | ISO format `YYYY-MM-DD` |
| acquisition_channel | text | How they found us |
| notes | text | Free text. May contain line breaks. |

---

## bookings_2023.csv / bookings_2024.csv
One row per production job. **The 2024 file was produced by the new ERP and the column
names changed** (`booking_id`→`booking_ref`, `client_id`→`customer_id`,
`shoot_date`→`date_of_shoot`, `gross_amount`→`amount_gross`, plus a new `vat_applied`).

| Column | Type | Notes |
|---|---|---|
| booking_id / booking_ref | text | `BK-#####` |
| client_id / customer_id | text | FK to clients |
| service_type | text | One of 8 service lines |
| shoot_date / date_of_shoot | date | Day the shoot started. **DD/MM/YYYY in both files.** |
| shoot_days | int | Billable shoot days |
| location_city | text | |
| gross_amount / amount_gross | numeric | Before discount, in `currency` |
| discount_pct | numeric | Fraction, e.g. `0.10` for 10% |
| currency | text | Defaults to NGN when blank |
| status | text | `Completed`, `Cancelled`, `Postponed`, `In Production`, `Invoiced` |
| lead_source | text | |
| vat_applied | bool | 2024 only. 7.5% VAT flag |

## bookings_2025_H1.xlsx
Hand-maintained since the migration. Sheet `H1 2025 Bookings`. Header is on row 1.
Contains monthly subtotal rows. The `Pivot` tab is generated automatically and is current.

---

## crew.csv / crew_timesheets.csv

| Column | Type | Notes |
|---|---|---|
| crew_id | text | `CR-#####` |
| full_name | text | |
| role | text | 10 standard roles |
| day_rate_ngn | numeric | Standard rate in NGN |
| employment_type | text | `Freelance` or `Staff` |
| is_active | bool | |
| timesheet_id | int | PK |
| booking_id | text | FK to bookings. **Always valid.** |
| work_date | date | |
| hours_worked | numeric | Hours on that shoot day. Capped at 12 by policy. |
| role_on_job | text | May differ from the crew member's standard role |
| day_rate_charged | numeric | Actual rate billed. 1.5× for overtime days, 0.5× for half days |
| overtime | bool | |
| approved_by | text | |

> Labour cost for a job = sum of `day_rate_charged` across its timesheet rows.

---

## merch_products.csv
Price history, one row per SKU per price period.

| Column | Type | Notes |
|---|---|---|
| sku | text | `XT-CCC-###` |
| product_name | text | `{collection} {category}` |
| category | text | 10 categories |
| collection | text | The drop it belongs to |
| colour, size_run | text | |
| unit_cost_ngn | numeric | Landed cost |
| list_price_ngn | numeric | Price during the validity window |
| valid_from / valid_to | date | **Non-overlapping windows per SKU.** Blank `valid_to` = current |
| active | bool | |

## merch_orders.csv
One row per order line.

| Column | Type | Notes |
|---|---|---|
| order_id | text | `ORD######` |
| line_no | int | 1-based within order |
| order_ts | timestamp | ISO 8601, **all in UTC** |
| client_id | text | FK to clients. Blank for guest checkout |
| customer_email | text | |
| sku | text | FK to products |
| product_name | text | Denormalised copy of the product name |
| size | text | |
| quantity | int | Units. Negative = return line |
| unit_price | numeric | Price paid per unit, NGN |
| discount_code | text | Blank if none |
| shipping_country, payment_method, sales_channel | text | |
| order_status | text | |

## merch_refunds.csv
| Column | Type | Notes |
|---|---|---|
| refund_id | text | `RF-#####` |
| order_id | text | FK to orders |
| refund_date | date | |
| refund_amount | numeric | **Always positive.** |
| reason | text | Free text, roughly 6 categories |
| processed_by | text | |

---

## web_sessions_*.{csv,tsv}
One row per session. Column names changed twice; the 2025 file is tab-separated.

| 2023 | 2024 / 2025 | Notes |
|---|---|---|
| ts_epoch_ms | session_start / session_start_iso | 2023 = epoch ms UTC; 2024 = naive local (Africa/Lagos, UTC+1); 2025 = ISO with offset |
| user_pseudo_id | visitor_id | Cookie ID, resets on cookie clear |
| utm_source / utm_medium / utm_campaign | source / medium / campaign | Free text, unnormalised |
| device_category | device | |
| session_duration_sec | duration_seconds | 0 for bounces |
| converted | converted | |
| transaction_id | transaction_id | **Joins to `merch_orders.order_id` for every conversion.** |
| revenue | revenue_ngn | NGN |
| — | gclid | 2024+ only, present on paid clicks |

> Bot filtering is applied upstream by the analytics tool. No further filtering needed.

---

## marketing_spend.csv
Semicolon-delimited (exported from the European reporting portal). Decimal separator is a
comma in some rows. One row per day per channel per campaign.

| Column | Type | Notes |
|---|---|---|
| date | date | DD/MM/YYYY |
| channel | text | 6 channels |
| campaign_name | text | Matches `utm_campaign` in the session data |
| impressions, clicks | int | |
| spend | numeric | |
| currency | text | Always NGN |

## fx_rates.csv
| Column | Type | Notes |
|---|---|---|
| rate_date | date | Every calendar day 2023-01-01 → 2025-07-05 |
| from_currency | text | USD, GBP, EUR |
| rate | numeric | Units of `to_currency` per 1 `from_currency` |
| to_currency | text | Always NGN |
