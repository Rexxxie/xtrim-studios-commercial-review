# Xtrim Studios - cleaning decisions log

Every rule applied to the raw extracts, the evidence behind it, and what it changed. All numbers are computed by the pipeline on each run.

## Row accounting

| File | Rows in | Rows out | Quarantined |
|---|---:|---:|---:|
| fx_rates.csv | 1,860 | 1,860 published + 888 filled days | 0 |
| clients_export.csv | 2,082 | 1,900 | 182 |
| bookings_2023.csv | 977 | 958 | 19 |
| bookings_2024.csv | 955 | 937 | 18 |
| bookings_2025_H1.xlsx | 387 | 366 | 21 |
| crew.csv | 140 | 140 | 0 |
| crew_timesheets.csv | 15,156 | 14,614 | 542 |
| merch_products.csv | 137 | 137 | 0 |
| merch_orders.csv | 44,495 | 43,206 | 1,289 |
| merch_refunds.csv | 8,888 | 8,631 | 257 |
| marketing_spend.csv | 4,048 | 3,931 | 117 |
| web_sessions_2023.csv | 62,868 | 62,868 | 0 |
| web_sessions_2024.csv | 88,414 | 88,414 | 0 |
| web_sessions_2025_H1.tsv | 51,764 | 51,764 | 0 |

For every file, rows in = rows out + quarantined; the pipeline refuses to write otherwise. Quarantined rows are in quarantine_rejected_rows.csv (src_row is the spreadsheet row number; header = row 1, or row 5 in the Excel sheet).

## Decisions

| ID | Area | Rule | Evidence and impact |
|---|---|---|---|
| D-FX-1 | FX | A published rate that is >5x both neighbours (or <1/5 of both) and lands within 15% of a neighbour once divided (multiplied) by 10 is a decimal-point typo and is corrected; original_rate keeps the published figure. | 7 corrected: 2023-03-30 EUR 5,730.88 -> 573.09; 2023-06-14 EUR 10,862.97 -> 1,086.30; 2024-12-16 EUR 40,004.61 -> 4,000.46; 2025-01-06 EUR 40,931.59 -> 4,093.16; 2023-09-21 GBP 13,746.78 -> 1,374.68; 2024-01-19 GBP 16,748.27 -> 1,674.83; 2024-02-21 USD 20,202.96 -> 2,020.30. Genuine devaluation steps are kept: EUR: 2023-06-14 x1.62, 2024-01-29 x1.333; GBP: 2023-06-14 x1.62, 2024-01-29 x1.357; USD: 2023-06-14 x1.62, 2024-01-29 x1.364. |
| D-FX-2 | FX | fx_rates.csv becomes a gap-free daily calendar per currency from 2023-01-01. A day with no published rate takes the most recent earlier published rate (weekends, holidays and missing weekdays); 2023-01-01 has no earlier rate and takes the first published one. is_filled and source_rate_date show which rate was used for every day. | The source has weekday rates only (2023-01-02 to 2025-07-04) and 35 weekdays are missing as well, so the dictionary's 'every calendar day' is false. 888 currency-days are filled. Forward-fill only uses a rate that existed on the day, which is how the business would have converted at the time. |
| D-CLI-1 | Clients | Rows with the same normalised client_id are one client exported more than once. They are merged into one row: first non-empty value per field, earliest signup_date, most common name spelling, and a valid phone wins over an invalid one. The extra rows are quarantined. | 58 extra rows. Where copies genuinely disagreed the client is flagged conflicting_values (fields: {'phone': 12}). |
| D-CLI-2 | Clients | A client with id N above 2000 is a re-keyed duplicate of client N-2000 when their accent-folded names score >= 0.85 (difflib ratio) and their emails do not conflict once any '+alias' is removed. The copy is quarantined, its fields fill gaps in the surviving client, and every booking/order reference is remapped (client_id_orig keeps the old id); merged_from and match_confidence record the merge. | Real client ids form one unbroken block, 1-1900 with every id present; the other 124 ids (2073-3894) each have a twin at id-2000 with a near-identical name, e.g. 'Grrace Farouk' / 'Grace Farouk', 'Obsidina Agency' / 'Obsidian Agency'. Name similarity of the 124 pairs: min 0.875, median 0.957, max 1.000, so the threshold sits below every true pair. Emails: {'same_after_alias_removed': 98, 'plus_alias_seen': 49, 'one_missing': 26}. The id offset is what makes this safe: judged by name alone the twin is the unique best match for only 25 of 124 ({'twin_tied_with_other_clients': 99, 'twin_unique_best': 25}), so name-only fuzzy matching would merge different people who share a common name. |
| D-CLI-3 | Clients | Clients within the real id block 1-1900 that share a name or an email stay separate clients. | 252 emails are shared by more than one of these clients; in 252 of those groups the clients have different phone numbers, signup dates or acquisition channels, and 0 valid phone numbers are shared at all. Emails in this export are built from names, so they identify a name, not a person. The result is exactly the 1,900 distinct clients the id block implies. |
| D-MONEY-1 | Currency | billing_currency is NGN for every client, because every amount in the cleaned data is naira. The currency each client was originally invoiced in is moved to cleaning_report/currency_conversion_audit.csv, not deleted. | 260 clients were billed in USD/GBP. Moving the original out of the dataset meets 'no other currencies'; keeping it in the audit file keeps Phase 4 Q4 (FX exposure) answerable. |
| D-CLI-4 | Clients | A blank city is taken from the cities on the client's own bookings, a blank country from the city, and a blank client type from the name: names carrying a company word (PLC, LTD, Group, Bank, Media, Agency, ...) are Corporate, the rest are Individual. All three are flagged. | A booking's city is the client's city on every booking where both are recorded, so 78 cities follow from the client's own jobs. Every city in this data maps to exactly one country, so 89 countries follow with certainty. The company-word rule reproduces the recorded type for all 1,783 clients that have one — no corporate name lacks such a word and no individual's name contains one — so it fills the 117 blanks. 34 clients have no city at all and keep a blank country. |
| D-BK-1 | Bookings | bookings_2025_H1.xlsx is read from the 'H1 2025 Bookings' sheet with its header on sheet row 5. Monthly subtotal rows, the GRAND TOTAL row ('see pivot tab'), blank spacer rows and the footer note are quarantined. Rows with a blank client name are test entries per the handover and would be quarantined too; none remain once the structural rows are removed. The stale Pivot tab, the empty Sheet1 and the handover Notes tab are not carried into the cleaned workbook; their content is acted on here. | 21 structural rows. The six subtotals alone total NGN 2,926,828,849, which would roughly double H1 2025 revenue if loaded as bookings. The pivot is titled 'as at 12/05/2025 - STALE'. Blank-name test rows among real bookings: 0. |
| D-DATE-1 | Dates | Slash dates are day-first in bookings_2023 and MONTH-first in bookings_2024. The 2025 workbook mixes Excel serial numbers (day 0 = 1899-12-30), DD/MM/YYYY, DD-Mon-YY and 'Month DD, YYYY'; each is parsed by its own pattern. | bookings_2023: 531 values can only be day-first, 0 only month-first. bookings_2024: 526 only month-first, 0 only day-first. The dictionary's 'DD/MM/YYYY in both files' is false and would invert 2024 seasonality. Workbook: 40 slash dates can only be day-first, none month-first, and all 366 parsed dates fall in the month of the subtotal block they sit under. |
| D-MONEY-2 | Currency | A booking's currency comes from, in order: (1) a currency symbol or code inside the amount text; (2) the currency column; (3) the client's billing currency in the CRM; (4) the currency of the client's other bookings; (5) NGN when the amount is at least NGN 100,000. A booking none of these resolves would be kept with its NGN amounts blank and flagged. Non-NGN amounts are converted at the daily rate for the shoot date. Each booking's original currency, amount, rate and the rule used are in currency_conversion_audit.csv. | Rule used per booking: {'currency_column': 925, 'amount_text': 1246, 'client_billing_currency': 116, 'client_other_bookings_currency': 10, 'amount_at_or_above_ngn_floor': 1}. (1) and (2) never contradict each other. (3) matches the stated currency on 1,955 of 1,955 bookings where both are known (100.0%). (4) is safe because none of the 1,279 clients with a stated booking currency ever uses two currencies. (5) is safe because known NGN jobs start at NGN 156,000 while known USD/GBP jobs top out at 39,300; nothing sits in between. The dictionary's 'blank currency = NGN' would book small USD/GBP jobs as naira. |
| D-BK-2 | Bookings | discount_pct: '5%', '5' and '0.05' all mean 5%; blank means no discount (0). net_amount_ngn = gross_amount_ngn x (1 - discount_pct). | After parsing, discounts take only the values 0%, 5%, 10%, 15%; reading the whole numbers 5, 10 and 15 as fractions would mean 500-1500% off. |
| D-BK-4 | Bookings | A booking with no status and no crew day ever logged against it is treated as Cancelled; blank statuses on bookings that do have crew days are left blank and flagged. | Every one of the 2,013 bookings with a status other than Cancelled has timesheets, while 154 of the 199 cancelled bookings (77%) have none: no crew day means the shoot did not happen. 49 statuses are blank; 4 of them have no crew day and are set to Cancelled (NGN 75,684,000 of gross moves out of live revenue), and the remaining 45 stay blank rather than being guessed. |
| D-BK-5 | Bookings | A booking with no shoot_days takes the number of distinct days its crew actually worked; a booking with no location_city takes the client's city. Both are flagged. | Where both exist, shoot_days equals the count of distinct timesheet days on 2,060 of 2,060 bookings (100%), and the shoot city equals the client's city on 2,125 of 2,125 (100%) — this studio shoots where its client is. Filled: 74 shoot_days (the rest have no timesheets) and 169 cities. |
| D-BK-3 | Bookings | Duplicate bookings are found on cleaned values, so 'BK01029' and ' bk-01029 ' match. Copies that disagree only on vat_applied keep one row with vat_applied blank and a flag. | Duplicates removed per file: {'bookings_2023.csv': 19, 'bookings_2024.csv': 18, 'bookings_2025_H1.xlsx': 0}. Afterwards booking_id is unique across all three files. |
| D-BK-6 | Bookings | client_id_orig is not written to the booking files. | No booking references one of the re-keyed duplicate clients, so the column would be empty in every row. It is kept in merch_orders.csv, where 400 lines do carry a repaired client id. |
| D-CREW-2 | Crew | A crew member with no standard day rate takes the rate they are charged out at most often on their timesheets. | For the 127 crew whose roster rate is known, it equals their most common charged rate in 127 cases (100%); the other charged values are half-day and 1.5x overtime shifts. 13 rates filled this way, so every crew member now has a day rate. |
| D-CREW-1 | Crew | Crew are keyed on crew_id alone; shared names and shared emails are not treated as duplicates. A missing role is taken from the crew member's timesheets when every shift they worked lists the same role. Missing day rates stay blank. | 20 crew rows share a name and 108 share an email address, but their ids, roles and rates differ. Role filling is safe: for the 133 crew whose roster role is known, the role on their timesheets is the same in 133 cases (100%), and each of the 7 crew without a roster role worked only one role. 0 day rates are missing and stay blank. |
| D-TS-1 | Timesheets | Timesheet rows whose booking id exists in no bookings file are quarantined as orphans, not deleted. | 319 rows reference 316 ids between 90,015 and 99,977 (2.1% of rows); real booking ids stop at 3,261. They fall in 30 different months (2023-01 to 2025-06) at about one row per id, so they are not just post-migration refs and cannot be re-linked. The dictionary's 'booking_id is always valid' is false. |
| D-TS-2 | Timesheets | hours_worked such as '8h' or '8 hrs' is parsed to a number. Values above the 12-hour policy cap are real overtime and are kept and flagged, never clipped. More than 24 hours in one day is impossible, so that value is blanked (the row, its crew member and day rate are kept) and flagged. Missing hours and day rates stay blank. | Recorded hours take only these values: {6.0: 808, 8.0: 4200, 9.0: 2771, 10.0: 2729, 12.0: 2030, 14.0: 1046, 26.0: 129}. 1046 rows log 14h, so 'capped at 12' is false; 129 rows log 26h (0.9%), an impossible value that would also break the schema's 0-20 check. Labour cost comes from day rates, so blanking those hours does not change cost. Exact duplicate rows quarantined: 223. |
| D-TS-3 | Timesheets | A timesheet with no role takes the crew member's roster role. Missing charged day rates are NOT filled the same way. | Where both are present they agree in 13,303 of 13,303 rows (100%) — nobody here works outside their roster role — so the 1,311 blank roles are filled from it. Charged day rates match the roster rate only 59% of the time (the rest are half-days and 1.5x overtime shifts), so a missing charged rate cannot be inferred and stays blank. |
| D-SCD-1 | Products | Price history per SKU: SKU spellings are normalised and inverted windows swapped; versions are ordered by valid_from and each ends the day before the next begins (trimming overlaps, closing superseded open rows and bridging gaps with the earlier price); the latest version runs to 9999-12-31 with is_current = true. | 57 raw SKU spellings -> 45 SKUs, 137 versions; 7 inverted windows; {'open_row_closed_by_next_version': 11, 'latest_version_stated_end_extended': 39, 'gap_bridged': 8, 'latest_version_already_open': 6, 'overlap_trimmed': 10}. The latest version is left open because 10,672 order lines (25%) fall after the last stated valid_to yet still price around that list price (median 1.04x, 91% within +/-25%, against 0.97x and 94% inside stated windows); closing it would strand those lines. Result: no overlaps, no gaps, and every cleaned order line joins exactly one version on its Lagos order date. |
| D-PRD-1 | Products | Category, collection, colour and unit cost never vary within a SKU where they are known, so blanks are filled from the same SKU. product_name is the SKU's single name (spellings only differ by case and spacing). | Filled: {'category': 4, 'collection': 15, 'colour': 13, 'unit_cost_ngn': 17}. XT-TEE-030 has no collection in any version and takes it from its name, since product_name = collection + category for every SKU. size and size_run are normalised but carry no signal: 68% of order lines for caps, mugs, lens cloths, stickers, posters, totes and prints carry a clothing size (S-XXL), so size should not be analysed. |
| D-ORD-3 | Orders | product_name on an order line is taken from its SKU. | 2,502 lines (5.8%) named a different product than their SKU. Their prices follow the SKU: against the SKU's list price they sit at a median 0.99x (93% within +/-25%; lines with no conflict: 0.99x, 94%), while against the named product's price they range from 0.07x to 12.03x (5th-95th percentile, 12% within +/-25%). |
| D-ORD-4 | Orders | Negative quantities are kept exactly as recorded and flagged negative_quantity; they are not sign-flipped or removed. | 280 lines, all with quantity -1. They are not returns of items in the same order (only 12 sit beside a sale of the same SKU, and 128 are the only line of their order), but nothing proves a sign error either. Impact of being wrong: they lower merch gross by NGN 7,237,600; if they are really sales of one unit, gross is understated by NGN 14,475,200 (0.79%). |
| D-ORD-1 | Orders | order_ts is converted to UTC. 'Z' strings are UTC; '+01:00' strings have the offset removed; 2023 timestamps without a zone are UTC; epoch-millisecond values are UTC up to 2024, but in 2025 they encode Lagos wall-clock time and have one hour removed. | Formats: {'iso_z': 17468, 'naive_utc': 14479, 'iso_offset': 9710, 'epoch_ms_utc': 1587, 'epoch_ms_2025_lagos_clock': 465}. Many orders have lines written in two formats, which is a direct test ({'epoch_ms_utc+naive_utc': 350, 'epoch_ms_utc+iso_z': 469, 'epoch_ms_2025_lagos_clock+iso_offset': 240}). Before any correction, epoch-as-UTC minus the other line's instant, in seconds, per line pair: vs naive 2023 lines {0: 679}; vs 'Z' lines {0: 984}; vs '+01:00' lines {3600: 504}. So 2023/2024 epochs agree with naive and 'Z' lines to the second, which proves the naive 2023 lines are UTC, while every 2025 epoch equals the +01:00 clock digits read as UTC. After conversion every line of every order has the same instant. |
| D-ORD-2 | Orders | Order lines whose client id is not in the CRM take the client named on the other lines of the same order when there is one (an order has one customer); otherwise they are quarantined as orphans. Quantity 9999 is a placeholder and is quarantined, as are exact duplicate rows. | 713 lines carried client ids 8,001-9,998, outside the CRM's id range. No order names two different real clients, and these ids appear in 0 guest orders, so they are corrupted values: 400 lines repaired from their own order, 313 quarantined because no line of their order names a real client. Placeholder quantity: 190. Exact duplicates: 786 (43,709 unique lines). SKUs are matched with separators removed ('XTTEE038' = 'XT-TEE-038'), leaving 0 orphan SKUs. |
| D-RF-1 | Refunds | Refund dates mix day-first and month-first slash formats. A date with only one valid reading is used as is. When both readings are valid dates, the one inside the refund window seen on every unambiguous refund (0-45 days after the order's Lagos date) is used; if both or neither fit, refund_date is left blank and both readings are kept in refund_date_if_day_first / refund_date_if_month_first. | {'single_reading': 7419, 'two_readings_resolved_day_first': 725, 'two_readings_resolved_month_first': 430, 'two_readings_both_fit_left_blank': 57}. Unambiguous refunds land 1-46 days after the UTC order date and 0-45 days after the Lagos date; the tighter Lagos window is used. Every processed_by, reason and year value occurs with both conventions, so no field separates them and parsing one way would misdate hundreds of refunds. |
| D-RF-2 | Refunds | refund_amount_ngn is always positive: '(4,500)' and '-NGN 4,500' are accounting notation for a refund of 4,500. | 4277 amounts were written with a sign. |
| D-RF-3 | Refunds | refund_id is not unique and is not used to deduplicate; refund_key adds a -1/-2 suffix where an id repeats. | 405 ids are shared by 827 rows; 405 of those ids point at more than one order with different amounts, i.e. separate refunds whose ids collided. Deduplicating on refund_id would delete 422 real refunds. |
| D-RF-4 | Refunds | Refunds for orders that do not exist are quarantined. Refunds for orders whose every line was quarantined are quarantined with them. | 174 orphan refunds reference order numbers 900,537-999,615; real orders run 500,001-529,145. 83 refunds follow a quarantined order. |
| D-SPEND-1 | Marketing | marketing_spend.csv was semicolon-delimited with decimal commas; it is rewritten as a standard comma CSV with dot decimals ('87635,35' = 87,635.35; '1 254 300' impressions = 1,254,300). Blank and 'N' currency are NGN. Exact duplicate rows (the double-submitted batch) are quarantined. | 2,756 spend values contain a comma and every one has exactly two digits after it, so none is a thousands separator. 117 duplicates removed; day x channel x campaign is then unique, as fct_ad_spend's primary key requires. |
| D-SPEND-2 | Marketing | Campaign names are normalised for spelling only; 'always_on' vs 'brand_always_on' and 'blackfriday24' vs 'black_friday' stay distinct. | Whether those are the same campaign is an attribution call for the Phase 4 mapping table; merging them here could not be undone downstream. |
| D-SESS-1 | Sessions | In all three session files the clock digits are Africa/Lagos local time: session_date_lagos is the clock date and session_start_utc is the clock minus one hour. That includes 2023, whose epoch-millisecond values encode Lagos wall-clock time, not UTC. | Human traffic has a strong daily rhythm (busiest hour 16.9x the quietest). Each file's time-of-day profile was compared with 2025, the only file that states its offset (+01:00), shifted by -3..+3 hours; for both 2023 and 2024 the best fit is no shift (L1 distance by shift, 2023: {-3: 0.515, -2: 0.364, -1: 0.197, 0: 0.04, 1: 0.191, 2: 0.359, 3: 0.507}; 2024: {-3: 0.504, -2: 0.359, -1: 0.193, 0: 0.039, 1: 0.196, 2: 0.364, 3: 0.511}). The handover's '2023 timestamps are UTC' is false for sessions: taking it literally would put every 2023 session an hour late and move late-evening sessions onto the wrong day. |
| D-SESS-2 | Sessions | is_bot = the user agent is a crawler, script or SEO tool; is_spam = the source is a referral-spam domain. Sessions are flagged, never removed; human traffic = not is_bot. | 23,054 bot sessions (11.4%) and 5,200 spam sessions from 3 sources (buy-traffic.ru, free-seo-tools.xyz, seo-monitor.top) between 2024-09-08 and 2024-09-21, all with 0-second duration. The signals are nested: every spam session and 8,887 of the 8,887 sessions with exactly 40 or 60 page views already carry a bot user agent, leaving 179,992 human sessions. The dictionary's 'bot filtering is applied upstream' is false. |
| D-SESS-5 | Sessions | revenue_ngn is 0 for every session that did not convert, and a session with no utm_source is recorded as source 'direct'. | The source files spell 'no revenue' three ways at random — 0, 'NA' and blank — but no converted session ever has a blank and no unconverted session ever has revenue above 0, so the 99,915 blanks are zeroes and are written as 0. Likewise a missing utm_source is traffic with no referrer, which these files elsewhere spell '(direct)' or 'direct'; the channel column already reads Direct for all of them. |
| D-SESS-3 | Sessions | utm_source spellings map to 8 groups: Google, Instagram, Facebook / Meta, TikTok, YouTube, Email, Direct, Referral / Other (X/Twitter, LinkedIn, Vimeo, Behance, generic referral and the spam domains, which also carry is_spam). A blank source is Direct and the lower-cased original source is kept beside the channel. Landing pages lose query strings, fragments, trailing slashes and '/index.html'. | 24 distinct lower-cased sources -> 8 groups. Instagram stays separate from Facebook so the Phase 4 mapping to 'Meta Ads' spend is an explicit, reversible choice. |
| D-SESS-4 | Sessions | transaction_id is normalised to the order-id format and kept as recorded; sessions whose id does not match an order are left in place (that gap is the unattributable conversion volume). | 3,851 converted sessions; 2,666 carry a transaction_id; 2,625 (68.2% of conversions) join a cleaned order (2,666 join an order id that exists in the raw file), so 1,226 conversions cannot be attributed — the dictionary's 'always joins' is false. 0 non-converted sessions carry an id. Conversion rate on human sessions: 2.14%. Caveat for attribution work: joined orders are a median 254 days from their session and 50% are dated before the session started. |
| D-NULL-1 | General | Every spelling of 'missing' found in the files is treated as a blank value. | Counted across every cell of every CSV/TSV file: (empty) x455,315, 'NA' x51,542, 'none' x15,102, 'NULL' x1,919, ' ' x1,869, 'n/a' x1,866, '#N/A' x1,861, 'unknown' x1,856, 'None' x1,856, '--' x1,836, 'UNKNOWN' x1,832, 'null' x1,825, 'N/A' x1,809, 'tbd' x1,787, '-' x1,775, 'Unknown' x174. None of these is a real category in any column. (The Excel workbook uses the same spellings.) |
| D-MONEY-3 | Currency | Every money column in every cleaned file is naira and every currency column reads NGN. | Only bookings and client billing contained USD/GBP. Crew rates, timesheets, product costs and prices, order prices, refunds, ad spend and session revenue were already naira; the pipeline checks each value's currency marker instead of assuming it. fx_rates.csv necessarily still names USD/GBP/EUR because it is the conversion table; its rates are NGN per unit. |
| D-ENC-1 | General | Files are decoded run-by-run (UTF-8 where valid, otherwise Windows-1252) and double-encoded text ('SiÃ³bhan', 'Anniversary â€™05') is repaired. | clients_export.csv mixes correct UTF-8, raw Windows-1252 and double-encoded (sometimes lower-cased) text for the same names; reading it any single way corrupts accented names, which is why it 'breaks in Python'. |
| D-NULL-2 | General | No cell is left empty. A blank becomes 'No issues' in dq_flags, 'Not applicable' where there was nothing to record, 'Guest' for an order placed without an account, and 'Unknown' where a real value was never recorded. Numbers are never replaced with 0. | Cells written: 60,979 'No issues', 476,729 'Not applicable', 33,157 'Unknown', 19,524 'Guest'. None of these tokens is in pandas' default na_values list, so reading a file normally will not turn them back into blanks. They are deliberately non-numeric, so a sum or average over a column that has missing values fails loudly instead of silently treating a guess as zero; every one is listed by column in missing_values.csv. |

## Quarantine by reason

| File | Reason | Rows |
|---|---|---:|
| bookings_2023.csv | exact_duplicate_booking | 19 |
| bookings_2024.csv | duplicate_booking_conflicting_vat_flag | 7 |
| bookings_2024.csv | exact_duplicate_booking | 11 |
| bookings_2025_H1.xlsx | excel_blank_spacer_row | 13 |
| bookings_2025_H1.xlsx | excel_footer_note_row | 1 |
| bookings_2025_H1.xlsx | excel_grand_total_row | 1 |
| bookings_2025_H1.xlsx | excel_monthly_subtotal_row | 6 |
| clients_export.csv | duplicate_client_id_row | 58 |
| clients_export.csv | fuzzy_duplicate_client | 124 |
| crew_timesheets.csv | exact_duplicate_row | 223 |
| crew_timesheets.csv | orphan_booking_id | 319 |
| marketing_spend.csv | exact_duplicate_row_double_submitted | 117 |
| merch_orders.csv | exact_duplicate_row | 786 |
| merch_orders.csv | orphan_client_id | 313 |
| merch_orders.csv | placeholder_quantity_9999 | 190 |
| merch_refunds.csv | order_quarantined | 83 |
| merch_refunds.csv | orphan_order_id | 174 |

## Flags kept on cleaned rows (dq_flags)

| File | Flag | Rows |
|---|---|---:|
| clients_export.csv | city_taken_from_own_bookings | 78 |
| clients_export.csv | client_type_derived_from_name | 117 |
| clients_export.csv | conflicting_values:phone | 12 |
| clients_export.csv | country_derived_from_city | 89 |
| clients_export.csv | phone_invalid_8_digits | 121 |
| clients_export.csv | phone_invalid_9_digits | 469 |
| bookings_2023.csv | currency_inferred_from_client_other_bookings | 4 |
| bookings_2023.csv | fx_rate_carried_from_earlier_day | 46 |
| bookings_2023.csv | location_city_taken_from_client | 78 |
| bookings_2023.csv | service_type_missing | 54 |
| bookings_2023.csv | shoot_days_counted_from_timesheets | 39 |
| bookings_2023.csv | shoot_days_missing | 7 |
| bookings_2023.csv | status_inferred_cancelled_no_crew_days | 2 |
| bookings_2023.csv | status_missing | 25 |
| bookings_2024.csv | currency_inferred_from_client_other_bookings | 3 |
| bookings_2024.csv | fx_rate_carried_from_earlier_day | 69 |
| bookings_2024.csv | location_city_taken_from_client | 69 |
| bookings_2024.csv | service_type_missing | 51 |
| bookings_2024.csv | shoot_days_counted_from_timesheets | 35 |
| bookings_2024.csv | shoot_days_missing | 2 |
| bookings_2024.csv | status_inferred_cancelled_no_crew_days | 2 |
| bookings_2024.csv | status_missing | 20 |
| bookings_2024.csv | vat_applied_conflicting_duplicates | 7 |
| bookings_2025_H1.xlsx | currency_inferred_from_client_other_bookings | 3 |
| bookings_2025_H1.xlsx | fx_rate_carried_from_earlier_day | 22 |
| bookings_2025_H1.xlsx | location_city_taken_from_client | 22 |
| bookings_2025_H1.xlsx | service_type_missing | 10 |
| crew.csv | day_rate_filled_from_timesheets | 13 |
| crew.csv | role_filled_from_timesheets | 7 |
| crew_timesheets.csv | day_rate_missing | 1,020 |
| crew_timesheets.csv | hours_above_12h_cap | 1,046 |
| crew_timesheets.csv | hours_missing | 901 |
| crew_timesheets.csv | hours_worked_26h_impossible_blanked | 129 |
| crew_timesheets.csv | role_filled_from_crew_roster | 1,311 |
| merch_products.csv | category_filled_from_same_sku | 4 |
| merch_products.csv | collection_filled_from_same_sku | 15 |
| merch_products.csv | collection_taken_from_product_name | 2 |
| merch_products.csv | colour_filled_from_same_sku | 13 |
| merch_products.csv | gap_to_next_version_bridged | 8 |
| merch_products.csv | open_window_closed_by_next_version | 11 |
| merch_products.csv | overlap_trimmed | 10 |
| merch_products.csv | stated_valid_to_extended | 39 |
| merch_products.csv | unit_cost_ngn_filled_from_same_sku | 17 |
| merch_products.csv | window_inverted_swapped | 7 |
| merch_orders.csv | client_id_repaired_from_same_order | 400 |
| merch_orders.csv | negative_quantity | 280 |
| merch_orders.csv | product_name_did_not_match_sku | 2,502 |
| merch_refunds.csv | amount_written_as_negative | 4,277 |
| merch_refunds.csv | refund_date_ambiguous | 57 |
| merch_refunds.csv | refund_date_format_resolved_by_refund_window | 1,155 |
| merch_refunds.csv | refund_exceeds_order_value | 83 |
| merch_refunds.csv | refund_id_shared_with_other_refunds | 827 |

## Empty cells: none (placeholder convention)

There are no empty cells in any file. 89.1% of cells hold a real value; the rest hold one of four visible tokens, never a guessed value:

- **`No issues`** (60,979 cells) — dq_flags: nothing was wrong with that row.
- **`Not applicable`** (476,729 cells) — there was nothing to record: no note was written, the session did not convert, no discount code was used, the client absorbed no duplicate, the FX rate needed no correction.
- **`Unknown`** (33,157 cells) — a value that really exists but was never recorded, and that nothing else in the data determines. These are listed below.
- **`Guest`** (19,524 cells) — merch_orders.client_id, where the buyer checked out without an account.

None of these tokens is in pandas' default `na_values` list, so a plain `pd.read_csv` will not quietly turn them back into missing values (`None`, `NA`, `N/A` and `null` would have been).

Because `Unknown` appears in a few numeric columns (timesheet hours and charged day rates, shoot_days) and date columns (signup_date, refund_date), read those with `pd.to_numeric(col, errors='coerce')` or `pd.to_datetime(col, errors='coerce')`. A blank was deliberately *not* replaced with 0: zero hours or a zero day rate would quietly understate labour cost, whereas `Unknown` fails loudly.

| File | Column | Cells marked Unknown | % of rows | What is actually missing |
|---|---|---:|---:|---|
| bookings_2023.csv | lead_source | 155 | 16.18% | not recorded |
| bookings_2023.csv | service_type | 54 | 5.64% | not recorded, and nothing else in the data identifies the service |
| bookings_2023.csv | status | 25 | 2.61% | not recorded; the booking has crew days, so it was not cancelled, but which of the four live statuses applied is unknown |
| bookings_2023.csv | shoot_days | 7 | 0.73% | not recorded, and the booking has no timesheets to count days from |
| bookings_2023.csv | location_city | 1 | 0.1% | not recorded, and the client has no city either |
| bookings_2024.csv | lead_source | 157 | 16.76% | not recorded |
| bookings_2024.csv | service_type | 51 | 5.44% | not recorded, and nothing else in the data identifies the service |
| bookings_2024.csv | status | 20 | 2.13% | not recorded; the booking has crew days, so it was not cancelled, but which of the four live statuses applied is unknown |
| bookings_2024.csv | shoot_days | 2 | 0.21% | not recorded, and the booking has no timesheets to count days from |
| bookings_2025_H1.xlsx | lead_source | 79 | 21.58% | not recorded |
| bookings_2025_H1.xlsx | service_type | 10 | 2.73% | not recorded, and nothing else in the data identifies the service |
| bookings_2025_H1.xlsx | location_city | 1 | 0.27% | not recorded, and the client has no city either |
| clients_export.csv | phone | 810 | 42.63% | no number on file, or the recorded number was not a valid Nigerian mobile (see dq_flags) |
| clients_export.csv | acquisition_channel | 265 | 13.95% | not recorded |
| clients_export.csv | email | 146 | 7.68% | no address on file |
| clients_export.csv | signup_date | 68 | 3.58% | not recorded |
| clients_export.csv | city | 34 | 1.79% | not recorded |
| crew.csv | email | 30 | 21.43% | no address on file |
| crew.csv | employment_type | 13 | 9.29% | not recorded |
| crew_timesheets.csv | approved_by | 2,606 | 17.83% | no approver recorded |
| crew_timesheets.csv | hours_worked | 1,030 | 7.05% | not recorded, or recorded as an impossible 26h and blanked (see dq_flags) |
| crew_timesheets.csv | day_rate_charged_ngn | 1,020 | 6.98% | not recorded; it cannot be taken from the roster rate because charged rates include half-days and 1.5x overtime |
| merch_orders.csv | size | 6,465 | 14.96% | not recorded (size is unreliable in this data anyway) |
| merch_orders.csv | customer_email | 3,402 | 7.87% | no address recorded on the order line |
| merch_orders.csv | shipping_country | 3,044 | 7.05% | not recorded; it cannot be taken from the client's country, which matches the shipping country only 23% of the time |
| merch_orders.csv | payment_method | 2,143 | 4.96% | not recorded |
| merch_orders.csv | sales_channel | 1,705 | 3.95% | not recorded |
| merch_products.csv | size_run | 22 | 16.06% | not recorded for this price version |
| merch_refunds.csv | processed_by | 1,684 | 19.51% | no handler recorded |
| merch_refunds.csv | reason | 870 | 10.08% | no refund reason recorded |
| merch_refunds.csv | refund_date | 57 | 0.66% | the date could be read two ways and both fit the refund window; both readings are in refund_date_if_day_first / refund_date_if_month_first |
| web_sessions_2023.csv | country | 644 | 1.02% | not recorded, and the client has no city to derive it from |
| web_sessions_2024.csv | country | 6,026 | 6.82% | not recorded, and the client has no city to derive it from |
| web_sessions_2025_H1.tsv | country | 504 | 0.97% | not recorded, and the client has no city to derive it from |

## Column changes

| File | Change |
|---|---|
| clients_export.csv | type -> client_type; phone in +234 format (invalid numbers blanked and flagged); billing_currency = NGN (original in the audit file); added merged_from, match_confidence, dq_flags |
| bookings_2023.csv | gross_amount -> gross_amount_ngn; added client_id_orig, net_amount_ngn, fx_converted, dq_flags |
| bookings_2024.csv | booking_ref -> booking_id; customer_id -> client_id; date_of_shoot -> shoot_date; amount_gross -> gross_amount_ngn; added client_id_orig, net_amount_ngn, fx_converted, dq_flags |
| bookings_2025_H1.xlsx | header moved to row 1; Booking Ref -> booking_id; Client ID -> client_id; Client Name -> client_name; Service -> service_type; Shoot Date -> shoot_date; Days -> shoot_days; City -> location_city; Gross Amount -> gross_amount_ngn; Disc % -> discount_pct; Ccy -> currency; Status -> status; Lead Source -> lead_source; Notes -> notes; added client_id_orig, net_amount_ngn, fx_converted, dq_flags; Pivot, Sheet1 and Notes tabs removed |
| crew.csv | added dq_flags |
| crew_timesheets.csv | day_rate_charged -> day_rate_charged_ngn; added dq_flags |
| fx_rates.csv | one row per calendar day per currency; added is_filled, source_rate_date, is_corrected, original_rate |
| marketing_spend.csv | semicolons -> commas; date -> spend_date; campaign_name -> campaign; spend -> spend_ngn; added dq_flags |
| merch_orders.csv | order_ts -> order_ts_utc; unit_price -> unit_price_ngn; added client_id_orig, line_gross_ngn, dq_flags |
| merch_products.csv | added is_current, dq_flags |
| merch_refunds.csv | refund_amount -> refund_amount_ngn; added refund_key, refund_date_if_day_first, refund_date_if_month_first, dq_flags |
| web_sessions_2023.csv | ts_epoch_ms -> session_start_utc + session_date_lagos; user_pseudo_id -> visitor_id; utm_source -> source + channel; utm_medium -> medium; utm_campaign -> campaign; device_category -> device; pageviews -> page_views; session_duration_sec -> duration_seconds; is_new_user -> is_new_visitor; revenue -> revenue_ngn; added gclid (empty in 2023), is_bot, is_spam |
| web_sessions_2024.csv | session_start -> session_start_utc + session_date_lagos; source -> source + channel; new_visitor -> is_new_visitor; added is_bot, is_spam |
| web_sessions_2025_H1.tsv | session_start_iso -> session_start_utc + session_date_lagos; source -> source + channel; new_visitor -> is_new_visitor; added is_bot, is_spam |
