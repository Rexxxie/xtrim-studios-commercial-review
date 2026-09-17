# Data quality report — raw extracts

Phase 1 deliverable. Every raw file profiled column by column, then the specific defects found. Nulls count **every** spelling of missing found in this export: `''`, `' '`, `'NA'`, `'N/A'`, `'n/a'`, `'null'`, `'NULL'`, `'None'`, `'none'`, `'-'`, `'--'`, `'#N/A'`, `'unknown'`, `'UNKNOWN'`, `'Unknown'`, `'tbd'`.

*value_shapes* = number of distinct formats a column's values take (digits → 9, letters → A); a date column with 5 shapes is written 5 different ways. *parses_as_type_pct* = share of non-null values that match the inferred type cleanly.

Full profile: `column_profile.csv` / `column_profile.xlsx`. How each defect was handled: `../cleaning_report/CLEANING_DECISIONS.md` and `../warehouse/WAREHOUSE_DECISIONS.md`.

## Summary by file

| File | Rows | Columns | Columns with nulls | Worst null rate | Defects found |
|---|---:|---:|---:|---:|---:|
| clients_export.csv | 2,082 | 11 | 9 | 37.3% (notes) | 7 |
| bookings_2023.csv | 977 | 12 | 8 | 38.2% (notes) | 5 |
| bookings_2024.csv | 955 | 13 | 8 | 37.6% (notes) | 4 |
| bookings_2025_H1.xlsx | 387 | 13 | 13 | 55.0% (Notes) | 4 |
| crew.csv | 140 | 7 | 4 | 21.4% (email) | 3 |
| crew_timesheets.csv | 15,156 | 9 | 4 | 17.8% (approved_by) | 5 |
| merch_products.csv | 137 | 11 | 6 | 16.1% (size_run) | 3 |
| merch_orders.csv | 44,495 | 15 | 7 | 44.9% (client_id) | 5 |
| merch_refunds.csv | 8,888 | 6 | 2 | 21.1% (processed_by) | 3 |
| web_sessions_2023.csv | 62,868 | 16 | 6 | 98.6% (transaction_id) | 3 |
| web_sessions_2024.csv | 88,414 | 17 | 7 | 98.7% (transaction_id) | 3 |
| web_sessions_2025_H1.tsv | 51,764 | 17 | 7 | 98.7% (transaction_id) | 2 |
| marketing_spend.csv | 4,048 | 7 | 1 | 3.2% (currency) | 3 |
| fx_rates.csv | 1,860 | 4 | 0 | 0.0% (to_currency) | 2 |

## Data dictionary claims that are false

1. `clients_export.csv` is unique on `client_id` — **false** (58 repeat rows, 124 re-keyed duplicates).
2. `email` is always populated — **false**.
3. `signup_date` is ISO — **false** (three formats).
4. Booking dates are DD/MM/YYYY in both files — **false** (2024 is month-first).
5. The 2025 workbook header is on row 1 and the Pivot tab is current — **false** (row 5; Pivot is stale).
6. `timesheets.booking_id` is always valid — **false** (319 orphans).
7. `hours_worked` is capped at 12 — **false** (1,046 rows at 14h, 129 at an impossible 26h).
8. `day_rate_charged` is 1.5x on overtime days — **false** (the multiplier is independent of the flag).
9. Product validity windows do not overlap — **false** (29 overlapping pairs, 7 inverted).
10. `order_ts` is all UTC — **false** (four formats, ~5% epoch ms).
11. `refund_amount` is always positive — **false** (4,277 negative).
12. `transaction_id` joins an order for every conversion — **false** (68.2%).
13. Bot filtering is applied upstream — **false** (23,054 bot sessions, 11.4%).
14. `fx_rates.csv` covers every calendar day — **false** (weekdays only, 35 weekdays missing).
15. `marketing_spend.campaign_name` matches `utm_campaign` — **false** (case and separators differ; `always_on`).

## clients_export.csv

**Defects found**

- Mixed encoding: raw Windows-1252, UTF-8 and double-encoded UTF-8 in one file; a plain `pd.read_csv` raises UnicodeDecodeError.
- Mojibake in names (`AndrÃ©` for `André`), repaired rather than stripped.
- `client_id` is not unique: 58 exact repeat rows; IDs spelled `XT-00123`, `xt123`, `123`, `XT00123`, `' XT-00123 '`.
- 124 fuzzy duplicates: the same client re-keyed at id + 2000 with a typo'd name and a `+1` email alias.
- `email` is not always populated (dictionary says it is); `type` has 9 spellings of 2 values.
- `signup_date` mixes ISO, DD/MM/YYYY and DD-Mon-YYYY (dictionary says ISO only).
- Phones: 590 of the 1,900 deduplicated clients have 8 or 9 digits (not a valid Nigerian mobile).

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| client_id | 0.0% |  | 2,061 | text | 100% | 3 | XT-01787 ¦ XT-00025 ¦ 1749 ¦ XT01076 |
| client_name | 0.0% |  | 1,346 | text | 100% | 39 | Novo NGO ¦   Novo Media ¦ delta rise foods ¦ Delta Rise Telecom |
| type | 6.9% | '-' x16; 'NULL' x14; '--' x13; 'unknown' x10; 'N/A' x10; '' x10; 'UNKNOWN' x9; 'tbd' x9... | 9 | text | 100% | 2 | Corporate ¦ CORP ¦ corporate ¦ B2B |
| email | 8.7% | 'None' x18; '' x17; 'N/A' x16; 'NULL' x16; '-' x15; 'null' x14; 'n/a' x14; 'UNKNOWN' x1... | 1,575 | text | 100% | 6 | novo.ngo@company.ng ¦ novo.media@outlook.com ¦ delta.rise.foods@gmail.com ¦ delta.rise.telecom@outlook.com |
| phone | 12.6% | '-' x23; 'NULL' x23; 'UNKNOWN' x23; 'unknown' x21; 'N/A' x21; 'tbd' x21; 'NA' x19; ' ' ... | 1,820 | text | 100% | 6 | +234 806909416 ¦ 08092129171 ¦ 08077298936 ¦ +234 803361175 |
| city | 6.0% | 'n/a' x12; 'NULL' x10; 'NA' x10; 'unknown' x10; 'tbd' x9; 'None' x9; 'UNKNOWN' x9; '' x... | 296 | text | 100% | 6 | Lag ¦ lag ¦ PORTHARCOURT ¦ Abuja |
| country | 5.2% | '--' x14; 'tbd' x11; 'None' x9; 'unknown' x9; '#N/A' x9; '-' x8; '' x8; 'N/A' x7; ' ' x... | 10 | text | 100% | 2 | Nigeria ¦ NG ¦ United Kingdom ¦ UAE |
| billing_currency | 10.8% | '-' x20; 'unknown' x19; 'null' x19; '' x19; '--' x18; ' ' x17; 'N/A' x17; '#N/A' x16; '... | 3 | text | 100% | 1 | NGN ¦ USD ¦ GBP |
| signup_date | 4.3% | '' x10; 'n/a' x9; 'UNKNOWN' x9; 'None' x9; '-' x8; 'null' x8; 'NA' x7; '#N/A' x6; 'tbd'... | 1,453 | date | 93% | 4 | 27-Dec-2023 ¦ 2022-10-01 ¦ 20/12/2021 ¦ 26/07/2021 |
| acquisition_channel | 14.9% | 'None' x31; 'null' x26; '' x25; 'tbd' x25; '--' x25; 'unknown' x24; 'N/A' x24; ' ' x22;... | 139 | text | 100% | 4 | Agency Partner ¦ Email ¦ TikTok ¦    Google    |
| notes | 37.3% | '' x776 | 7 | text | 100% | 6 | invoice to accounts dept ¦ VIP - handle w/ care ¦ Discount agreed, see email ¦ prefers whatsapp |

## bookings_2023.csv

**Defects found**

- Dates are day-first (531 values can only be read day-first, 0 only month-first).
- Money strings: `₦1,250,000.00`, `NGN 1250000`, `6.83M`, `GBP 1,320.00`, `₦ 1 250 000.00`, `NGN1,250,000.00/-`.
- Currency blank on many rows; USD/GBP jobs hidden inside the amount text.
- 330 raw spellings (case, spacing, abbreviations) of 8 service lines across the 2023 and 2024 files (`documentary`, `Short-Film`, `EVENT COVERAGE`); statuses `Complete`, `Done`, `delivered`.
- 19 duplicate booking rows (IDs differ only by case, spacing and hyphen).

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| booking_id | 0.0% |  | 958 | text | 100% | 3 | BK-01030 ¦ BK-01264 ¦ BK01708 ¦ BK-01297 |
| client_id | 0.0% |  | 853 | text | 100% | 3 | xt250 ¦ xt-01810 ¦ XT-01368 ¦ 1734 |
| service_type | 5.6% | 'N/A' x8; 'None' x7; 'null' x6; 'UNKNOWN' x6; 'tbd' x5; '' x4; 'NA' x4; '#N/A' x3; '--'... | 201 | text | 100% | 12 |  Commercial  ¦ Short Film ¦ Short-Film ¦ Corporate Documentary |
| shoot_date | 0.0% |  | 379 | date | 100% | 2 | 04/02/2023 ¦ 24-May-2023 ¦ 29/10/2023 ¦ 09/06/2023 |
| shoot_days | 4.8% | ' ' x6; 'null' x5; '#N/A' x5; 'UNKNOWN' x5; '-' x4; '--' x4; 'unknown' x4; '' x3; 'N/A'... | 10 | decimal | 100% | 2 | 1 ¦ 3 ¦ 1.0 ¦ 2.0 |
| location_city | 8.2% | 'None' x10; 'unknown' x9; '#N/A' x9; 'NA' x8; 'UNKNOWN' x7; 'NULL' x6; 'n/a' x6; '-' x5... | 182 | text | 100% | 6 | Accra   ¦ Johannesburg ¦ Lag ¦ Ikeja, Lagos |
| gross_amount | 0.0% |  | 950 | money | 100% | 28 | 6.83M ¦ 8,878,000.00 ¦ 12,897,000 ¦ 9,323,000 |
| discount_pct | 26.3% | '' x257 | 12 | text | 100% | 3 | 0 ¦ 0.00 ¦ 0% ¦ 10 |
| currency | 10.5% | 'unknown' x14; '#N/A' x11; 'tbd' x10; 'NA' x9; 'None' x9; 'n/a' x8; 'NULL' x8; 'null' x... | 3 | text | 100% | 1 | NGN ¦ GBP ¦ USD |
| status | 2.9% | '#N/A' x3; 'n/a' x3; ' ' x3; 'tbd' x3; 'N/A' x2; 'unknown' x2; 'null' x2; '-' x2; 'UNKN... | 27 | text | 100% | 3 | Complete ¦ delivered ¦ COMPLETE ¦ Done |
| lead_source | 15.9% | 'tbd' x15; 'None' x14; 'unknown' x14; 'null' x14; ' ' x13; '#N/A' x13; 'n/a' x12; 'N/A'... | 105 | text | 100% | 4 | Repeat Client ¦ Agency Partner ¦ tiktok ¦ WALK-IN |
| notes | 38.2% | '' x373 | 8 | text | 100% | 7 | drone denied by airport authority ¦ client rescheduled once ¦ location permit paid by client ¦ RAW files delivered on 2 x 1TB SSD |

## bookings_2024.csv

**Defects found**

- Columns renamed by the new ERP (`booking_ref`, `customer_id`, `date_of_shoot`, `amount_gross`).
- Dates are MONTH-first (526 only month-first, 0 only day-first); the dictionary says DD/MM.
- `vat_applied` has 14 spellings of true/false; `discount_pct` mixes `0.15`, `15` and `15%`.
- 18 duplicate rows, 7 of which disagree only on `vat_applied`.

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| booking_ref | 0.0% |  | 937 | text | 100% | 3 | 2112 ¦ BK-02483 ¦ BK-02401 ¦ BK-02040 |
| customer_id | 0.0% |  | 852 | text | 100% | 3 | XT-00434 ¦  XT-00894  ¦ XT00112 ¦ XT-00010 |
| service_type | 5.5% | '-' x6; 'NA' x6; 'null' x5; '#N/A' x5; 'n/a' x4; 'NULL' x4; '' x4; 'UNKNOWN' x4; ' ' x3... | 203 | text | 100% | 11 | photo-shoot ¦ Commercial / TVC ¦ CORPORATE DOCUMENTARY ¦   commercial - tvc  |
| date_of_shoot | 0.0% |  | 394 | date | 100% | 2 | 04/11/2024 ¦ 09/03/2024 ¦ 08/04/2024 ¦ 03/09/2024 |
| shoot_days | 4.1% | ' ' x6; 'N/A' x5; '-' x5; 'NA' x4; 'null' x4; '#N/A' x3; 'tbd' x3; 'n/a' x2; 'NULL' x2;... | 10 | decimal | 100% | 2 | 1 ¦ 1.0 ¦ 2 ¦ 4 |
| location_city | 7.3% | 'tbd' x8; 'NULL' x7; '' x6; 'None' x6; 'n/a' x5; '#N/A' x5; 'null' x5; '--' x5; 'unknow... | 168 | text | 100% | 6 | Lag ¦ Lagos ¦ london ¦ Enugu |
| amount_gross | 0.0% |  | 928 | money | 100% | 27 | 2.11M ¦ ₦43,292,000.00 ¦ 8,100 ¦ 40930000.00 |
| discount_pct | 23.5% | '' x224 | 12 | text | 100% | 3 | 0.00 ¦ 0 ¦ 0.15 ¦ 0% |
| currency | 12.5% | 'UNKNOWN' x11; 'null' x11; ' ' x11; 'NA' x10; 'N/A' x10; '--' x9; '#N/A' x9; '-' x8; 'N... | 3 | text | 100% | 1 | NGN ¦ GBP ¦ USD |
| status | 2.3% | 'None' x4; 'UNKNOWN' x3; 'unknown' x2; 'null' x2; '--' x2; 'tbd' x2; '#N/A' x2; '' x1; ... | 27 | text | 100% | 3 | Invoiced ¦ delivered ¦ CANCELLED ¦ INVOICED |
| lead_source | 16.5% | 'NULL' x16; 'n/a' x15; ' ' x14; '#N/A' x13; 'tbd' x13; 'None' x13; '--' x11; 'UNKNOWN' ... | 107 | text | 100% | 4 |  Instagram ¦ Walk-in ¦ Referral ¦ GOOGLE |
| vat_applied | 0.0% |  | 14 | boolean | 100% | 2 | N ¦ t ¦ no ¦ Y |
| notes | 37.6% | '' x359 | 8 | text | 100% | 7 | drone denied by airport authority ¦ client rescheduled once ¦ Overtime: crew stayed till 2am,
billed s ¦ half payment received, balance pending |

## bookings_2025_H1.xlsx

**Defects found**

- Header is on sheet row 5, not row 1 (dictionary is wrong).
- 6 monthly subtotal rows, a GRAND TOTAL row, 13 blank spacer rows and a footer note inside the data.
- Shoot dates mix Excel serial numbers, DD/MM/YYYY, DD-Mon-YY and 'Month DD, YYYY'.
- The Pivot tab is stale (dictionary says it is current); the footer admits 'figures exclude USD/GBP jobs'.

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| Booking Ref | 5.2% | '' x20 | 367 | text | 100% | 4 | BK-02896 ¦ bk2897 ¦ BK-02898 ¦ bk2899 |
| Client ID | 5.4% | '' x21 | 353 | text | 100% | 3 | XT-00442 ¦  XT-00349  ¦ XT-01652 ¦ XT-01872 |
| Client Name | 5.4% | '' x21 | 303 | text | 100% | 19 | Damilola Mohammed ¦  Blue Ivy Agency  ¦ Aisha Chen ¦  Musa Achebe  |
| Service | 8.0% | '' x27; '-' x2; ' ' x1; 'UNKNOWN' x1 | 49 | text | 100% | 9 | SHORT FILM ¦ PHOTOSHOOT ¦ Short Film ¦ music_video |
| Shoot Date | 5.4% | '' x21 | 240 | integer | 64% | 4 | 02-Jan-25 ¦ 03/01/2025 ¦ 04-Jan-25 ¦ 45661 |
| Days | 5.4% | '' x21 | 5 | integer | 100% | 1 | 1 ¦ 2 ¦ 3 ¦ 4 |
| City | 9.6% | '' x24; '--' x3; 'tbd' x3; 'UNKNOWN' x2; ' ' x2; '-' x2; 'unknown' x1 | 41 | text | 100% | 4 | Ikeja, Lagos ¦ Ibadan ¦ london ¦ Abuja, FCT |
| Gross Amount | 3.6% | '' x14 | 372 | money | 100% | 22 | 20824000 ¦ 2625000.00 ¦ 17,100.00 ¦ 16306000 |
| Disc % | 30.8% | '' x119 | 5 | text | 100% | 2 | 0% ¦ 5% ¦ 0 ¦ 15% |
| Ccy | 17.3% | '' x45; 'tbd' x5; '--' x5; 'unknown' x4; ' ' x3; 'UNKNOWN' x3; '-' x2 | 3 | text | 100% | 1 | NGN ¦ GBP ¦ USD |
| Status | 5.4% | '' x21 | 27 | text | 100% | 3 | postponed ¦ Complete ¦ Done ¦ COMPLETE |
| Lead Source | 25.8% | '' x74; '--' x7; 'unknown' x5; '-' x5; ' ' x4; 'UNKNOWN' x3; 'tbd' x2 | 7 | text | 100% | 3 | Walk-in ¦ Instagram ¦ Repeat Client ¦ Google |
| Notes | 55.0% | '' x213 | 4 | text | 100% | 4 | client provided own
location ¦ URGENT - chase invoice ¦ reshoot requested ¦ paid via transfer |

## crew.csv

**Defects found**

- Day rates written 17 different ways (`₦ 156 000.00`, `76.0K`, `271,000.00 NGN`); 13 blank.
- `is_active` has 14 spellings of true/false; 7 blank roles; names with mojibake (`NÃƒÂºria`).
- 20 rows share a name and 108 share an email, but are different people (different id, role, rate).

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| crew_id | 0.0% |  | 140 | text | 100% | 3 | CR-00001 ¦ CR-00002 ¦ CR-00003 ¦ CR-00004 |
| full_name | 0.0% |  | 133 | text | 100% | 17 | Renée Chen ¦ Kelechi Mohammed ¦ NÃºria Okafor ¦ Grace Adeyemi |
| role | 5.0% | 'n/a' x3; 'N/A' x2; 'unknown' x1; 'tbd' x1 | 47 | text | 100% | 5 | art director ¦ Grip ¦ Art Director ¦ Editor  |
| day_rate_ngn | 9.3% | 'N/A' x4; 'tbd' x2; 'null' x2; 'unknown' x1; '#N/A' x1; 'None' x1; '--' x1; 'UNKNOWN' x1 | 123 | money | 100% | 9 | ₦ 156 000.00 ¦ 76.0K ¦ NGN 49,000.00 ¦ 158,000 |
| employment_type | 9.3% | 'NULL' x4; 'NA' x4; 'null' x2; ' ' x1; 'n/a' x1; 'unknown' x1 | 2 | text | 100% | 1 | Freelance ¦ Staff |
| is_active | 0.0% |  | 14 | boolean | 100% | 2 | no ¦ t ¦ TRUE ¦ Y |
| email | 21.4% | 'tbd' x6; 'null' x4; 'NULL' x4; 'n/a' x3; '-' x3; 'unknown' x2; ' ' x2; '' x2; 'UNKNOWN... | 36 | text | 100% | 5 | kelechi@xtrimstudios.com ¦ núria@xtrimstudios.com ¦ zainab@xtrimstudios.com ¦ tunde@xtrimstudios.com |

## crew_timesheets.csv

**Defects found**

- 319 rows (2.1%) reference booking ids that exist nowhere (dictionary says always valid).
- 129 rows log 26 hours in a day (impossible); 1,046 rows log 14h, so the '12-hour cap' is false.
- Hours written as `9h`, `6 hrs`, `12`, `10.0`; 223 exact duplicate rows.
- The 0.5x / 1x / 1.5x day-rate multiplier is unrelated to the overtime flag (dictionary says 1.5x = overtime).
- 1,020 rows have no charged day rate; 1,311 have no role.

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| timesheet_id | 0.0% |  | 14,933 | integer | 100% | 1 | 7071 ¦ 11091 ¦ 5339 ¦ 10644 |
| booking_id | 0.0% |  | 6,319 | text | 100% | 3 | BK-02063 ¦ BK-02644 ¦ BK-01803 ¦ BK-02575 |
| crew_id | 0.0% |  | 838 | text | 100% | 3 | CR00088 ¦ CR-00137 ¦ cr-00137 ¦ cr83 |
| work_date | 0.0% |  | 2,164 | date | 100% | 3 | 2024-03-22 ¦ 2024-10-29 ¦ 21/11/2023 ¦ 2024-10-07 |
| hours_worked | 6.1% | 'NULL' x86; 'unknown' x81; ' ' x80; 'null' x72; 'n/a' x70; 'tbd' x68; '-' x64; 'UNKNOWN... | 28 | text | 100% | 4 | 9.0 ¦ 6 hrs ¦ 12 ¦ 10.0 |
| role_on_job | 9.0% | 'n/a' x115; 'NULL' x104; 'NA' x103; ' ' x103; '#N/A' x100; 'None' x99; 'null' x98; '' x... | 428 | text | 100% | 5 | Director of Photography ¦ Drone Operator ¦ Gaffer       ¦ Colorist |
| day_rate_charged | 7.0% | '#N/A' x89; 'N/A' x87; 'n/a' x85; 'None' x85; '--' x82; 'NA' x79; '' x75; 'unknown' x72... | 2,240 | money | 100% | 9 | ₦368,000.00 ¦ ₦235,000.00 ¦ 235,000 ¦ ₦120,000.00 |
| overtime | 0.0% |  | 14 | boolean | 100% | 2 | f ¦ No ¦ FALSE ¦ True |
| approved_by | 17.8% | 'NA' x215; 'n/a' x210; '-' x208; ' ' x206; 'NULL' x205; '--' x203; '' x197; 'null' x195... | 7 | text | 100% | 3 | Tunde Adeyemi ¦ n.okafor ¦ t. adeyemi ¦ N. Okafor |

## merch_products.csv

**Defects found**

- One row per SKU per price period: 137 rows, 45 SKUs, 57 SKU spellings.
- Validity windows overlap (29 overlapping pairs across 19 SKUs), 7 have valid_to < valid_from, 8 gaps.
- Double-encoded collection names (`Anniversary Ã¢â‚¬â„¢05`); blanks in category, collection, colour and cost.

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| sku | 0.0% |  | 57 | text | 100% | 1 | XT-MUG-003 ¦ XT-LIM-045 ¦ XT-HOO-037 ¦ XT-LEN-034 |
| product_name | 0.0% |  | 82 | text | 100% | 15 | Harmattan Drop Mug ¦ Behind The Lens Limited Print ¦ Anniversary â€™05 Hoodie ¦ Anniversary â€™05 Lens Cloth |
| category | 2.9% | 'n/a' x1; 'tbd' x1; 'NULL' x1; '#N/A' x1 | 45 | text | 100% | 4 | Mug ¦ Limited Print ¦ Hoodie ¦ Lens Cloth |
| collection | 12.4% | '' x5; 'NA' x2; 'null' x2; 'None' x1; 'unknown' x1; 'UNKNOWN' x1; 'tbd' x1; 'N/A' x1; '... | 36 | text | 100% | 8 |    Harmattan Drop   ¦ Behind The Lens ¦    Anniversary â€™05   ¦   Behind The Lens |
| colour | 9.5% | 'UNKNOWN' x2; 'None' x2; 'n/a' x2; '#N/A' x2; 'null' x1; 'NULL' x1; 'tbd' x1; '-' x1; '... | 7 | text | 100% | 2 | Black ¦ Navy ¦ Sand ¦ Forest |
| size_run | 16.1% | '' x22 | 5 | text | 100% | 4 | S-XXL ¦ S,M,L,XL,XXL ¦ OS ¦ s-xxl |
| unit_cost_ngn | 12.4% | 'unknown' x3; '#N/A' x3; 'NULL' x2; '--' x2; 'UNKNOWN' x2; 'N/A' x2; 'None' x1; '' x1; ... | 96 | money | 100% | 10 | 4,800.00 ¦ 27200.00 ¦ ₦12,400.00 ¦ ₦1,300.00 |
| list_price_ngn | 0.0% |  | 133 | money | 100% | 9 | 11,000.00 NGN ¦ ₦ 71 300.00 ¦ 51300.00 ¦ NGN 5,800.00 |
| valid_from | 0.0% |  | 127 | date | 100% | 2 | 2024-02-02 ¦ 2022-11-14 ¦ 2023-06-25 ¦ 2025-03-25 |
| valid_to | 12.4% | '' x17 | 117 | date | 100% | 2 | 26/10/2023 ¦ 2024-05-01 ¦ 2025-11-21 ¦ 2024-01-21 |
| active | 0.0% |  | 14 | boolean | 100% | 2 | N ¦ Yes ¦ False ¦ FALSE |

## merch_orders.csv

**Defects found**

- `order_ts` is not all UTC: naive (2023), `Z` (2024), `+01:00` (2025), and ~5% epoch milliseconds.
- 786 exact duplicate lines; 190 lines with quantity 9999 (placeholder); 280 lines with quantity -1.
- 713 lines carry client ids 8,001-9,998 that are not in the CRM (400 repaired from the same order, 313 quarantined).
- 2,502 lines (5.8%) have a product_name that disagrees with the SKU; the SKU is right.
- Discount codes do not lower the price paid.

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| order_id | 0.0% |  | 33,389 | text | 100% | 2 | ORD512816 ¦ ord-505759 ¦ ORD520224 ¦ ORD524354 |
| line_no | 0.0% |  | 6 | integer | 100% | 1 | 1 ¦ 2 ¦ 5 ¦ 3 |
| order_ts | 0.0% |  | 30,200 | timestamp | 100% | 4 | 2024-03-23T23:54:20Z ¦ 2023-08-27 19:16:10 ¦ 2024-11-18T11:21:13Z ¦ 2025-02-26T08:46:21+01:00 |
| client_id | 44.9% | '' x19973 | 8,013 | text | 100% | 3 | XT-00483 ¦ xt114 ¦ XT-00816 ¦ XT-01341 |
| customer_email | 7.9% | 'n/a' x281; 'None' x265; '#N/A' x264; 'UNKNOWN' x262; 'unknown' x260; 'NA' x254; 'N/A' ... | 19,512 | text | 100% | 5 | guest18591@mail.com ¦ sarah.achebe@yahoo.com ¦ emeka.adeyemi@gmail.com ¦ UCHE.DLAMINI@GMAIL.COM |
| sku | 0.0% |  | 180 | text | 100% | 2 | XT-LEN-019 ¦ XT-STI-013 ¦ XT-LIM-002 ¦ XT-TEE-038 |
| product_name | 0.0% |  | 1,722 | text | 100% | 25 | 35mm Club Lens Cloth ¦ 35mm Club Sticker Pack ¦ Harmattan Drop Limited Print ¦ Anniversary ’05 Tee |
| size | 15.0% | 'NULL' x510; 'UNKNOWN' x501; 'NA' x498; 'unknown' x483; 'N/A' x480; 'None' x477; '#N/A'... | 10 | text | 100% | 2 | m ¦ L ¦ XXL ¦ S |
| quantity | 0.0% |  | 14 | decimal | 100% | 4 | 2.0 ¦ 1 ¦ 2 ¦ 3 |
| unit_price | 0.0% |  | 4,816 | money | 100% | 15 | 5,000 ¦ ₦2,400.00 ¦ 148200.00 ¦ ₦23,700.00 |
| discount_code | 38.0% | '' x16898 | 12 | text | 100% | 2 | BLACKFRI ¦ blackfri ¦ FREESHIP ¦ lagos10 |
| shipping_country | 7.0% | 'unknown' x253; '--' x247; '' x238; 'NULL' x237; 'NA' x233; 'None' x227; 'null' x225; '... | 11 | text | 100% | 2 | Nigeria ¦ nigeria ¦ Ghana ¦ NG |
| payment_method | 5.0% | ' ' x182; 'UNKNOWN' x170; 'n/a' x169; '' x167; '--' x166; 'tbd' x161; 'NULL' x161; '#N/... | 10 | text | 100% | 2 | flutterwave ¦ bank transfer ¦ paystack ¦ Bank Transfer |
| sales_channel | 4.0% | '#N/A' x146; 'tbd' x132; 'N/A' x132; ' ' x130; 'NULL' x129; 'NA' x127; 'unknown' x126; ... | 10 | text | 100% | 4 | Wholesale ¦ instagram ¦ website ¦ Pop Up Shop |
| order_status | 0.0% |  | 12 | text | 100% | 1 | Fulfilled ¦ DELIVERED ¦ shipped ¦ delivered |

## merch_refunds.csv

**Defects found**

- `refund_amount` is not always positive: 4,277 written as `(45,000)` or with a minus sign.
- Refund dates mix day-first and month-first; 57 cannot be resolved and are left blank.
- 174 refunds reference orders that do not exist; 405 refund ids are shared by different refunds.

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| refund_id | 0.0% |  | 8,447 | text | 100% | 1 | RF-47555 ¦ RF-66009 ¦ RF-34467 ¦ RF-35668 |
| order_id | 0.0% |  | 7,395 | text | 100% | 2 | ORD501244 ¦ 528881 ¦ 519012 ¦ ORD525016 |
| refund_date | 0.0% |  | 2,251 | date | 100% | 2 | 2023-04-07 ¦ 2025-07-27 ¦ 30/11/2024 ¦ 03/26/2025 |
| refund_amount | 0.0% |  | 6,300 | money | 100% | 33 | ₦44,100.00 ¦ 19,300.00 NGN ¦ NGN 26,100.00 ¦ (63,600.00) |
| reason | 11.8% | '' x877; 'Unknown' x174 | 9 | text | 100% | 3 | Duplicate order ¦ changed mind ¦ wrong size ¦ Changed mind |
| processed_by | 21.1% | '' x1873 | 4 | text | 100% | 2 | auto ¦ ops ¦ SUPPORT ¦ support@xtrimstudios.com |

## web_sessions_2023.csv

**Defects found**

- Timestamps are epoch ms of Lagos wall-clock time (the handover said UTC).
- Bot traffic is not filtered upstream: user agents include Googlebot, SemrushBot, curl, python-requests.
- utm_source has ~24 spellings of 8 channels (`ig`, `fb`, `meta`, `(direct)`, `google.com`).

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| session_id | 0.0% |  | 62,868 | text | 100% | 1 | S000000001 ¦ S000000002 ¦ S000000003 ¦ S000000004 |
| ts_epoch_ms | 0.0% |  | 62,781 | integer | 100% | 1 | 1672616049000 ¦ 1672597616000 ¦ 1672597375000 ¦ 1672605400000 |
| user_pseudo_id | 0.0% |  | 45,156 | text | 100% | 1 | u052233 ¦ u021137 ¦ u040199 ¦ u085834 |
| utm_source | 3.4% | '' x2114 | 29 | text | 100% | 4 | meta ¦ ig ¦ (direct) ¦ google.com |
| utm_medium | 15.2% | 'none' x4799; '' x4776 | 11 | text | 100% | 3 | organic ¦ cpc ¦ ppc ¦ referral |
| utm_campaign | 14.1% | '' x8871 | 12 | text | 100% | 8 | wedding season 24 ¦ Retarget-Q4 ¦ brand_always_on ¦ harmattan_drop |
| device_category | 0.0% |  | 8 | text | 100% | 1 | Desktop ¦ smartphone ¦ Mobile ¦ desktop |
| country | 1.0% | '' x644 | 8 | text | 100% | 2 | Canada ¦ Nigeria ¦ United Kingdom ¦ Kenya |
| landing_page | 0.0% |  | 14 | text | 100% | 7 | /rates ¦ /shop/harmattan-drop ¦ /portfolio/ ¦ /shop?utm_source=ig |
| pageviews | 0.0% |  | 9 | integer | 100% | 1 | 2 ¦ 4 ¦ 3 ¦ 1 |
| session_duration_sec | 0.0% |  | 1,251 | integer | 100% | 1 | 34 ¦ 81 ¦ 242 ¦ 186 |
| user_agent | 0.0% |  | 12 | text | 100% | 11 | Mozilla/5.0 (Macintosh; Intel Mac OS X 1 ¦ Mozilla/5.0 (Linux; Android 13; SM-A536E ¦ Mozilla/5.0 (iPhone; CPU iPhone OS 16_6  ¦ Mozilla/5.0 (Windows NT 10.0; Win64; x64 |
| is_new_user | 0.0% |  | 14 | boolean | 100% | 2 | no ¦ 1 ¦ Yes ¦ f |
| converted | 0.0% |  | 14 | boolean | 100% | 2 | False ¦ f ¦ no ¦ 0 |
| transaction_id | 98.6% | '' x61993 | 860 | text | 100% | 1 | ORD527190 ¦ ORD510611 ¦ ORD505862 ¦ ORD525317 |
| revenue | 49.1% | '' x15505; 'NA' x15372 | 889 | decimal | 100% | 2 | 0 ¦ 0.00 ¦ 158000.0 ¦ 68000.0 |

## web_sessions_2024.csv

**Defects found**

- Column names changed again; timestamps are naive Lagos time.
- Referral-spam burst: 5,200 sessions, 8–21 September 2024, from `buy-traffic.ru`, `free-seo-tools.xyz`, `seo-monitor.top`, all 0 seconds.
- Revenue spelled `0`, `0.00`, `NA` and blank for the same meaning.

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| session_id | 0.0% |  | 88,414 | text | 100% | 1 | S000062869 ¦ S000062870 ¦ S000062871 ¦ S000062872 |
| session_start | 0.0% |  | 87,626 | timestamp | 100% | 1 | 2024-01-01 07:44:13 ¦ 2024-01-01 08:42:37 ¦ 2024-01-01 20:24:23 ¦ 2024-01-01 17:49:23 |
| visitor_id | 0.0% |  | 54,252 | text | 100% | 1 | u009623 ¦ u004510 ¦ u058439 ¦ u013794 |
| source | 3.1% | '' x2757 | 32 | text | 100% | 6 | twitter ¦ tiktok ¦ linkedin ¦ Google |
| medium | 14.6% | '' x6525; 'none' x6368 | 11 | text | 100% | 3 | (none) ¦ email ¦ cpc ¦ organic_social |
| campaign | 19.4% | '' x17113 | 12 | text | 100% | 8 | brand_always_on ¦ harmattan_drop ¦ lagos_nights_launch ¦ Retarget-Q4 |
| gclid | 70.9% | '' x62698 | 25,716 | text | 100% | 1 | Cj0KCQ7789193336 ¦ Cj0KCQ8394644625 ¦ Cj0KCQ2634327247 ¦ Cj0KCQ9884147501 |
| device | 0.0% |  | 8 | text | 100% | 1 | MOBILE ¦ Tablet ¦ smartphone ¦ mobile |
| country | 6.8% | '' x6026 | 8 | text | 100% | 2 | Kenya ¦ NG ¦ Nigeria ¦ Ghana |
| landing_page | 0.0% |  | 14 | text | 100% | 7 | /booking ¦ /blog/5-tips-for-your-wedding-film ¦ /commercial ¦ / |
| page_views | 0.0% |  | 9 | integer | 100% | 1 | 4 ¦ 2 ¦ 1 ¦ 6 |
| duration_seconds | 0.0% |  | 1,333 | integer | 100% | 1 | 102 ¦ 106 ¦ 70 ¦ 108 |
| user_agent | 0.0% |  | 12 | text | 100% | 11 | Mozilla/5.0 (Macintosh; Intel Mac OS X 1 ¦ Mozilla/5.0 (iPhone; CPU iPhone OS 16_6  ¦ Mozilla/5.0 (Windows NT 10.0; Win64; x64 ¦ Mozilla/5.0 (Linux; Android 13; SM-A536E |
| new_visitor | 0.0% |  | 14 | boolean | 100% | 2 | TRUE ¦ Yes ¦ FALSE ¦ True |
| converted | 0.0% |  | 14 | boolean | 100% | 2 | 0 ¦ False ¦ FALSE ¦ no |
| transaction_id | 98.7% | '' x87296 | 1,096 | text | 100% | 1 | ORD516458 ¦ ORD509736 ¦ ORD504417 ¦ ORD514084 |
| revenue_ngn | 49.2% | '' x21912; 'NA' x21590 | 1,050 | decimal | 100% | 2 | 0.00 ¦ 0 ¦ 38800.0 ¦ 129100.0 |

## web_sessions_2025_H1.tsv

**Defects found**

- Tab-delimited with CRLF line endings, despite sitting beside two CSVs.
- Only 68.2% of converted sessions (all files) carry a transaction_id that joins a real order (dictionary says every one joins).

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| session_id | 0.0% |  | 51,764 | text | 100% | 1 | S000146083 ¦ S000146084 ¦ S000146085 ¦ S000146086 |
| session_start_iso | 0.0% |  | 51,649 | timestamp | 100% | 1 | 2025-01-01T05:10:02+01:00 ¦ 2025-01-01T09:07:45+01:00 ¦ 2025-01-01T18:21:23+01:00 ¦ 2025-01-01T18:20:27+01:00 |
| visitor_id | 0.0% |  | 39,293 | text | 100% | 1 | u042637 ¦ u008053 ¦ u067710 ¦ u049852 |
| source | 3.4% | '' x1758 | 29 | text | 100% | 4 | direct ¦ twitter ¦ behance ¦ GOOGLE |
| medium | 15.3% | '' x3988; 'none' x3935 | 11 | text | 100% | 3 | ppc ¦ (none) ¦ paid ¦ Social |
| campaign | 14.4% | '' x7447 | 12 | text | 100% | 8 | harmattan_drop ¦ black_friday ¦ Retarget-Q4 ¦ brand_always_on |
| gclid | 69.3% | '' x35871 | 15,893 | text | 100% | 1 | Cj0KCQ1602541579 ¦ Cj0KCQ3873541618 ¦ Cj0KCQ1863070723 ¦ Cj0KCQ5401010118 |
| device | 0.0% |  | 8 | text | 100% | 1 | smartphone ¦ MOBILE ¦ Desktop ¦ desktop |
| country | 1.0% | '' x504 | 8 | text | 100% | 2 | United States ¦ NG ¦ Nigeria ¦ United Kingdom |
| landing_page | 0.0% |  | 14 | text | 100% | 7 | / ¦ /rates ¦ /portfolio/ ¦ /shop |
| page_views | 0.0% |  | 9 | integer | 100% | 1 | 9 ¦ 1 ¦ 4 ¦ 2 |
| duration_seconds | 0.0% |  | 1,245 | integer | 100% | 1 | 238 ¦ 0 ¦ 307 ¦ 19 |
| user_agent | 0.0% |  | 12 | text | 100% | 11 | Mozilla/5.0 (Linux; Android 13; SM-A536E ¦ Mozilla/5.0 (iPhone; CPU iPhone OS 16_6  ¦ Mozilla/5.0 (Macintosh; Intel Mac OS X 1 ¦ Mozilla/5.0 (Windows NT 10.0; Win64; x64 |
| new_visitor | 0.0% |  | 14 | boolean | 100% | 2 | 1 ¦ 0 ¦ t ¦ N |
| converted | 0.0% |  | 14 | boolean | 100% | 2 | FALSE ¦ False ¦ No ¦ 0 |
| transaction_id | 98.7% | '' x51091 | 664 | text | 100% | 1 | ORD504288 ¦ ORD510703 ¦ ORD510187 ¦ ORD502166 |
| revenue_ngn | 49.3% | '' x12835; 'NA' x12701 | 741 | decimal | 100% | 2 | 0.00 ¦ 0 ¦ 167500.0 ¦ 71000.0 |

## marketing_spend.csv

**Defects found**

- Semicolon-delimited; ~70% of spend values use a decimal comma (`13039,20`); impressions with space thousands (`49 235`).
- 117 exact duplicate rows from a double-submitted upload.
- Currency blank or lower-case; campaign names differ in case and separators from utm_campaign.

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| date | 0.0% |  | 1,467 | date | 100% | 2 | 03/06/2024 ¦ 19/04/2023 ¦ 06/06/2024 ¦ 29/03/2025 |
| channel | 0.0% |  | 6 | text | 100% | 4 | Email / CRM ¦ Google Ads ¦ TikTok Ads ¦ YouTube Pre-roll |
| campaign_name | 0.0% |  | 13 | text | 100% | 8 | HARMATTAN_DROP ¦ showreel_push ¦ wedding_season_23 ¦ lagos_nights_launch |
| impressions | 0.0% |  | 3,877 | integer | 69% | 2 | 49 235 ¦ 15991 ¦ 18915 ¦ 83245 |
| clicks | 0.0% |  | 1,842 | integer | 100% | 1 | 1615 ¦ 390 ¦ 173 ¦ 797 |
| spend | 0.0% |  | 3,931 | decimal | 100% | 2 | 541994.30 ¦ 157502.52 ¦ 13039,20 ¦ 92534,78 |
| currency | 3.2% | '' x130 | 3 | text | 100% | 1 | ngn ¦ NGN ¦ N |

## fx_rates.csv

**Defects found**

- Weekdays only, and 35 weekdays are missing too (dictionary says every calendar day).
- 7 rates are 10x decimal-point typos (one in ~250); the June 2023 and January 2024 devaluation jumps are real.

| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |
|---|---:|---|---:|---|---:|---:|---|
| rate_date | 0.0% |  | 620 | date | 100% | 1 | 2023-01-02 ¦ 2023-01-03 ¦ 2023-01-04 ¦ 2023-01-05 |
| from_currency | 0.0% |  | 3 | text | 100% | 1 | USD ¦ GBP ¦ EUR |
| rate | 0.0% |  | 1,857 | money | 100% | 2 | 464.6037 ¦ 568.0400 ¦ 508.9167 ¦ 464.0890 |
| to_currency | 0.0% |  | 1 | text | 100% | 1 | NGN |
