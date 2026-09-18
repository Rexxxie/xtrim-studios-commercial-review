# Xtrim Studios — Commercial Performance Review (2023 → H1 2025)

**Role:** Data Analyst (contract), reporting to the Studio Director
**Stack:** Python (pandas) → PostgreSQL → dashboard (Streamlit / Power BI / Metabase — your call)
**Difficulty:** Nightmare mode. Nothing in `raw/` is clean. Some of it is actively lying to you.

---

## 1. The situation

Xtrim Studios is a cinematography house that shoots weddings, music videos, TVCs and
corporate work. Three years ago it launched a merch line (tees, hoodies, prints) sold
through the website and Instagram, and it now spends real money on paid ads.

Nobody has ever looked at the three sides of the business together. The Director's
questions are simple to ask and painful to answer:

> "We're busier than ever and there's less money in the bank. Where is it going?
> And is the ad spend actually doing anything, or are we just funding Meta's yacht?"

You have been given a dump of every system the studio uses. The production side lives in
an ERP that was migrated mid-2025. The merch store exports CSVs. Web analytics comes from
three different tools depending on the year. Finance keeps FX rates in a spreadsheet.

There is no data engineer. There is no documentation you can trust. There is you.

---

## 2. What's in the box

```
raw/
  clients_export.csv          CRM dump           ~2,100 rows
  bookings_2023.csv           production jobs    ~980 rows
  bookings_2024.csv           production jobs    ~955 rows   (schema drifted)
  bookings_2025_H1.xlsx       production jobs    ~370 rows   (hand-maintained)
  crew.csv                    crew roster        140 rows
  crew_timesheets.csv         shoot-day labour   ~15,000 rows
  merch_products.csv          SKU + price history ~130 rows
  merch_orders.csv            order line items   ~44,500 rows
  merch_refunds.csv           refunds            ~8,900 rows
  web_sessions_2023.csv       web analytics      ~63,000 rows
  web_sessions_2024.csv       web analytics      ~88,000 rows
  web_sessions_2025_H1.tsv    web analytics      ~52,000 rows
  marketing_spend.csv         ad spend by day    ~4,000 rows
  fx_rates.csv                USD/GBP/EUR → NGN  ~1,900 rows

docs/DATA_DICTIONARY.md       what Ops says the columns mean
docs/VALIDATION_KEY.md        self-grading targets — open only when you're done cleaning
sql/                          staging DDL + the questions you must answer in SQL
```

**Total ~45 MB, ~215,000 rows.** Big enough that sloppy row-by-row cleaning will hurt.

---

## 3. Known problems (the handover call, transcribed)

These are the things Ops actually admitted to. There is more they didn't mention.

- *"The CRM export opens fine in Excel but one of the devs said it breaks in Python."*
- *"Bola left in March 2025, some entries were keyed by the intern."*
- *"The ERP migrated 15/04/2025 and booking refs restarted at random."*
- *"Studio Rental jobs get logged as 'Studio' sometimes. Same thing."*
- *"USD and GBP invoices are not converted anywhere. Ask finance for rates."*
- *"The pivot tab in the Excel file is from May, don't use it."*
- *"We changed web analytics tools twice. The 2023 timestamps are UTC, after that I
  think they're Lagos time, but don't quote me."*
- *"Ignore rows where the client name is blank, those were test entries."*
- *"Somebody double-submitted a batch of ad spend rows in one of the uploads."*

---

## 4. Workstreams

### Phase 1 — Ingestion & profiling
Load every file without silently dropping rows. Produce a **data quality report**: per
file, per column — null rate (counting *all* the ways null is spelled here), distinct
values, type inference, and the specific defects you found. This report is a deliverable,
not scratch work.

### Phase 2 — Cleaning & conformance
Build a reproducible `clean/` layer. Requirements:

- One canonical date type. Beware: **2023 bookings are day-first, 2024 bookings are
  month-first, and the 2025 Excel is Excel serial numbers.** Get this wrong and your
  seasonality analysis inverts.
- One canonical money type. Parse every currency string variant, and convert non-NGN
  amounts using `fx_rates.csv` — which only has weekdays and has gaps. Decide and
  *document* your fill rule.
- Collapse the free-text mess: 8 real services hiding behind ~50 spellings; 5 real
  statuses; ~30 `utm_source` values that are really 8 channels.
- Deduplicate. There are exact duplicate rows **and** fuzzy duplicate clients (same
  person, typo'd name, `+1` email alias, different ID). Handle both. Justify your
  matching threshold.
- Resolve referential integrity: orders and timesheets reference IDs that don't exist.
  Quarantine them, don't delete them — and report the leakage.
- Bots and referral spam are in the session data and will wreck every rate you compute.

### Phase 3 — Modelling (SQL)
Load clean data into Postgres as a star schema: `dim_client`, `dim_service`, `dim_product`,
`dim_crew`, `dim_date`, `dim_channel`, and facts `fct_booking`, `fct_merch_order_line`,
`fct_crew_day`, `fct_session`, `fct_ad_spend`. Every question in `sql/02_questions.sql`
must be answered with a query against this model, not against the raw files.

The product price history is a slowly-changing dimension that was maintained badly —
overlapping validity windows, gaps, and at least one range where `valid_to < valid_from`.
You must resolve it to a non-overlapping history before it can be joined.

### Phase 4 — Analysis
Answer these, with numbers and a written interpretation:

1. **Revenue mix and trend.** Production vs merch, by quarter, in constant NGN. Which
   service lines carry the business and which are cosmetic?
2. **Job-level profitability.** Join timesheets to bookings to get labour cost per job.
   Which service line has the worst margin? (Hint: check for jobs where labour cost
   exceeds revenue — they exist, and some are data errors, not real losses. Distinguish.)
3. **Seasonality and capacity.** When does the studio break? Model crew utilisation and
   find the weeks where it exceeded available crew-days.
4. **The FX question.** How much revenue was lost to naira devaluation on foreign jobs
   priced in NGN-equivalent terms across 2023–2025?
5. **Merch unit economics.** Net revenue after refunds and discounts, by SKU and by drop.
   Which drops lost money? What's the refund rate by reason, and is one SKU driving it?
6. **Marketing efficiency.** Map `utm_source` → spend channel (the names don't match —
   build the mapping table). Compute CAC, ROAS and blended conversion rate per channel
   per quarter. Then quantify how much of the "conversion" volume you can't attribute
   because `transaction_id` doesn't join to any order.
7. **The Director's question.** Answer it in six sentences, with a number in each.

### Phase 5 — Dashboard
One dashboard, three tabs: **Production**, **Merch**, **Acquisition**. Filters for date
range, service line and channel. Include a visible **data quality tile** showing rows
quarantined and % of revenue affected by unresolved issues. If a stakeholder can't see
what you threw away, they can't trust the rest.

### Phase 6 — Write-up
A 2-page memo to the Director. No jargon, no methodology dump — findings, the
recommendation, and the caveats that would change the answer. Attach the technical
appendix separately.

---

## 5. Rubric

| Area | Weight | What "excellent" looks like |
|---|---|---|
| Data quality handling | 25% | Defects found, quantified, and handled with a stated rule — not silently dropped |
| Cleaning reproducibility | 15% | `python run_pipeline.py` rebuilds everything from `raw/`. No manual Excel steps |
| SQL modelling | 20% | Correct grain on every fact, working SCD resolution, no fan-out on joins |
| Analytical rigour | 20% | Conclusions survive a hostile follow-up question; uncertainty stated |
| Dashboard | 10% | Answers a question in under 10 seconds without explanation |
| Communication | 10% | The memo is readable by someone who hates spreadsheets |

**Automatic fail:** a headline number you can't reproduce, or a chart whose totals don't
tie to the table beneath it.

---

## 6. Suggested timeline

| Day | Focus |
|---|---|
| 1 | Ingestion, profiling, data quality report |
| 2–3 | Cleaning layer + dedupe + FX + quarantine logic |
| 4 | Postgres load, star schema, SCD resolution |
| 5 | Analysis questions 1–4 |
| 6 | Questions 5–7 + dashboard |
| 7 | Memo, README, code cleanup |

---

## 7. Stretch goals

- Fuzzy client matching with `recordlinkage` or `rapidfuzz` — report precision/recall
  against a manually labelled sample of 100 pairs.
- Great Expectations or `pandera` suite that fails the build on regression.
- Cohort retention for merch buyers (repeat purchase within 90 days).
- Attribution comparison: last-click vs first-click vs linear on the session data.
- Forecast Q3–Q4 2025 bookings and state your prediction interval.

---

## 8. Ground rules

1. Never edit anything in `raw/`. Ever.
2. Every cleaning decision goes in a decisions log with a one-line rationale.
3. When the data is ambiguous, pick a rule, document it, and quantify the impact of
   being wrong. "It was unclear" is not a finding.
4. Open `docs/VALIDATION_KEY.md` only after Phase 2 is finished. It's your marking
   scheme, not your instructions.

Good luck. The intern was not careful.
