# Validation Key — open only after Phase 2

These are the true values, taken from the source-of-truth before the data was degraded.
If your cleaned layer lands on these, your pipeline works. If it doesn't, the gap tells
you which defect you missed.

Tolerances are given where a defensible cleaning rule could legitimately change the
answer. Where no tolerance is given, the number is exact.

---

## Entity counts

| Check | Target |
|---|---|
| Distinct real clients after dedupe | **1,900** (from ~2,082 exported rows) |
| Exact duplicate client rows in the export | ~66 |
| Fuzzy duplicate client pairs (same person, different ID) | ~113 — accept 100–125 |
| Distinct bookings after dedupe | **2,261** |
| — 2023 | 958 |
| — 2024 | 937 |
| — 2025 H1 | 366 |
| Duplicate booking rows injected | ~19 in 2023, ~18 in 2024 |
| Crew members | **140** |
| Distinct SKUs | **45** (not 130 — that file is one row *per price period*) |
| Unique merch order lines after dedupe | **43,709** (from 44,495 rows) |
| Refund rows | 8,888, of which ~174 are orphans with no matching order |
| Total web sessions across all three files | **203,046** |
| Ad spend rows after removing the double-upload | ~3,930 (from 4,048) |

## Canonical value sets

| Field | True cardinality |
|---|---|
| Service line | **8** — Wedding Film, Music Video, Commercial / TVC, Corporate Documentary, Photoshoot, Event Coverage, Short Film, Studio Rental |
| Booking status | **5** — Completed, Cancelled, Postponed, In Production, Invoiced |
| Product category | **10** |
| Collections / drops | **7** |
| Crew roles | **10** |
| Marketing channels | **6** |
| `utm_source` after normalisation | **8** groups — google, instagram, facebook/meta, tiktok, youtube, email, direct, referral/other |

## Bookings

| Check | Target |
|---|---|
| Non-cancelled bookings | **2,058** |
| Non-cancelled NGN bookings | 1,742 |
| Gross NGN revenue, NGN-billed jobs only, non-cancelled | **₦15,429,968,000** (±0.5%) |
| Net of discount, same population | **₦15,249,025,550** (±0.5%) |
| Foreign-currency non-cancelled jobs | 178 USD, 138 GBP |
| Busiest month of the year by job count | **December**, then November |
| Bookings by service, non-cancelled | Wedding Film 444 · Photoshoot 403 · Event Coverage 303 · Music Video 280 · Studio Rental 201 · Commercial / TVC 178 · Corporate Documentary 161 · Short Film 88 |

> If Wedding Film is not your #1 by volume, your date parsing or your service-name
> mapping is broken. If your monthly curve peaks in **February or March**, you parsed the
> 2024 US-format dates as day-first.

## Sessions

| Check | Target |
|---|---|
| Sessions with a bot/crawler user agent | ~23,054 (11.4% of all rows) |
| Referral-spam burst | **5,200 sessions**, September 8–21 2024, three `.xyz`/`.ru`/`.top` sources, all duration 0 |
| Human sessions after both filters | **179,992** (±1% depending on your bot rule) |
| Conversions whose `transaction_id` joins to a real order | ~70% — the rest are unattributable, and the dictionary's claim that it always joins is false |
| True conversion rate on human sessions | ~2.1% |

## Timesheets

| Check | Target |
|---|---|
| Rows referencing a booking that doesn't exist | ~2% — quarantine, don't drop |
| Rows with `hours_worked` = 26 | ~1% — impossible, the policy cap claim in the dictionary is also false |
| Duplicate timesheet rows | ~224 |

## Known lies in the data dictionary

You should have caught at least these:

1. `clients_export.csv` is **not** unique on `client_id`, and `email` is **not** always populated.
2. `bookings_2024.csv` is **month-first**, not day-first as documented.
3. The 2025 Excel header is on **row 5**, not row 1, and the Pivot tab is stale.
4. `merch_products.csv` validity windows **do** overlap, and some have `valid_to < valid_from`.
5. `merch_orders.order_ts` is **not** all UTC — 2023 is naive, 2024 is Z, 2025 carries +01:00, and ~5% are epoch milliseconds.
6. `merch_refunds.refund_amount` is **not** always positive — roughly half are negative.
7. `timesheets.booking_id` is **not** always valid.
8. `fx_rates.csv` covers **weekdays only** and is missing ~6% of those.
9. Bot traffic is **not** filtered upstream.
10. `marketing_spend.campaign_name` does **not** cleanly match `utm_campaign` — casing and separators differ.

## Traps that don't announce themselves

- `clients_export.csv` is **cp1252-encoded**. A naive `pd.read_csv` raises `UnicodeDecodeError`.
- Some names are **mojibake** (`André` → `AndrÃ©`) — a double-encoding artefact you must repair, not strip.
- `marketing_spend.csv` is **semicolon-delimited with comma decimals** in ~70% of rows.
- `web_sessions_2025_H1.tsv` is **tab-delimited** despite sitting beside two CSVs.
- IDs appear as `XT-00123`, `xt123`, `123`, `XT00123` and `" XT-00123 "` — all the same client.
- Money strings include `₦1,250,000.00`, `NGN 1250000`, `1.25M`, `₦ 1 250 000.00`, `NGN1,250,000.00/-` and `(45,000)` for negatives.
- Nulls are spelled: empty, `NA`, `N/A`, `n/a`, `null`, `NULL`, `None`, `-`, `--`, `#N/A`, `unknown`, `UNKNOWN`, `tbd`, and a single space.
- ~6% of `merch_orders.product_name` **disagrees with its own `sku`**. Trust the SKU.
- One FX rate in ~250 is a fat-finger 10× outlier. Median-filter or you'll book a phantom windfall.
- The FX series contains two real devaluation jumps (June 2023, January 2024). Do **not** smooth those away — they are the answer to analysis question 4.
