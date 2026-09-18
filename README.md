# Xtrim Studios — Commercial Performance Review

**An end-to-end analytics project: 14 messy source files → cleaning pipeline → PostgreSQL star schema → SQL answers → dashboard, memo and board deck.**

`Python (pandas)` · `PostgreSQL 17` · `SQL` · `Streamlit` · `pytest` · `python-docx / python-pptx`

---

## The brief

Xtrim Studios is a cinematography house — weddings, music videos, TVCs, corporate work — that also runs a merch line and spends real money on paid ads. Nobody had ever looked at the three sides of the business together. The Studio Director's question:

> *"We're busier than ever and there's less money in the bank. Where is it going? And is the ad spend actually doing anything?"*

What I was handed: a dump of every system the studio uses — an ERP migrated mid-2025, merch CSV exports, web analytics from three different tools depending on the year, and FX rates in a spreadsheet. ~282,000 rows across 14 files, no data engineer, and a data dictionary that turned out to be wrong in 11 specific places.

**Scope:** 2023 → H1 2025. All money is reported in Nigerian naira (₦).

The brief I worked from is in [`brief/`](brief/), unedited — including the data dictionary it warns you not to trust, and the validation key used to score the cleaning.

---

## The answer

**1. The growth is an illusion created by the exchange rate.**
Revenue grew **31% in naira** (₦7.07B → ₦9.24B) and fell **56% in dollars** ($8.04M → $3.58M) over the same period. The naira lost **90%** against the dollar (₦464.6 → ₦4,730.61 per USD). Job volume was flat: 870 jobs in 2023, 854 in 2024.

**2. ₦5.96B of revenue — 30% of the production book — is in jobs that never completed.**
That includes **₦1.60B across 175 jobs from 2023–2024 still sitting at "Invoiced"**. Postponed work rose from 5.9% of revenue in 2023 to 11.6% in 2024 to 13.8% in H1 2025. This is the cash gap, and it is a collections problem, not a demand problem.

**3. Studio Rental loses money before overheads.**
It runs a **−5.3% margin on crew cost alone**. Across all service lines, **182 jobs cost ₦140M more in crew than they billed** — 147 of them genuine, 35 caused by broken timesheet data (which is itself a finding).

**4. The ad spend cannot be shown to work.**
₦860M of ads returned **₦0.35 of tracked web-shop revenue per ₦1 spent**. They only break even if **6.7%** of the ₦6.56B of bookings credited to Google/Instagram/TikTok were actually driven by paid ads — and nothing in any system records that. 11.4% of all web sessions were bots; 31% of tracked session revenue can't be attributed to any channel at all.

**5. Merch is healthy but too small to matter yet.**
₦1.38B net at **61% contribution margin**, no collection and no SKU losing money. It is 6.6% of total revenue.

**6. The costs that explain the squeeze aren't in these systems.**
Everything recorded — crew, ads, merch stock — is only **17% of 2024 revenue**. The rest of the cost base is invisible to the data, so the honest answer to "where is it going" is: into unbilled/uncollected invoices, and into costs nobody is capturing.

Charts behind each of these: [`charts/`](charts/). Full reasoning: the memo and technical appendix below.

---

## Deliverables

| If you want… | Open |
|---|---|
| **The board deck** | [`presentation/Xtrim_Studios_Commercial_Review.pdf`](presentation/Xtrim_Studios_Commercial_Review.pdf) (PPTX beside it) |
| **The 2-page memo to the Director** | [`memo/Xtrim_Studios_Director_Memo.pdf`](memo/Xtrim_Studios_Director_Memo.pdf) (DOCX beside it) |
| **The technical appendix** — every assumption and sensitivity | [`memo/Xtrim_Studios_Technical_Appendix.pdf`](memo/Xtrim_Studios_Technical_Appendix.pdf) |
| **The dashboard** | `streamlit run dashboard/app.py` — Production · Merch · Acquisition, with filters and a live data-quality tile |
| **The SQL** | [`sql/02_questions_answered.sql`](sql/02_questions_answered.sql) — 14 questions, answered against the star schema |
| **The query results** | [`results/`](results/) — `q01.csv` … `q14.csv` |
| **The data quality report** | [`data_quality_report/DATA_QUALITY_REPORT.md`](data_quality_report/DATA_QUALITY_REPORT.md) |
| **Every cleaning decision + its evidence** | [`cleaning_report/CLEANING_DECISIONS.md`](cleaning_report/CLEANING_DECISIONS.md) |
| **Every modelling decision** | [`warehouse/WAREHOUSE_DECISIONS.md`](warehouse/WAREHOUSE_DECISIONS.md) |
| **The original brief** — the problem as handed over | [`brief/`](brief/) — brief, data dictionary, validation key, starter SQL |
| **What was rejected and why** | [`cleaning_report/quarantine_rejected_rows.csv`](cleaning_report/quarantine_rejected_rows.csv) — 2,445 rows, none deleted |

---

## How it works

```
raw files (not in repo)
      │
      ▼
profile_raw.py ──────────────► data_quality_report/   per-column profile, defects, false dictionary claims
      │
      ▼
pipeline/run_pipeline.py ────► clean/                 14 cleaned datasets, every money column in NGN
      │                        cleaning_report/        decisions log, quarantine, FX audit
      ▼
pipeline/validate.py                                   93 hard checks against the brief's validation key
      │
      ▼
warehouse/build_warehouse.py ► PostgreSQL              star schema: stg / core / quarantine
      │                                                PKs, FKs, CHECKs, EXCLUDE on price windows
      ▼
warehouse/run_queries.py ────► results/                the 14 SQL answers
      │
      ▼
analysis/analysis.py ────────► findings.json, tables/  every number the narrative uses
analysis/charts.py ──────────► charts/                 13 charts
      │
      ├──► dashboard/  (Parquet extracts — runs with no database)
      ├──► memo/       (Word + PDF, numbers injected from findings.json)
      └──► presentation/ (PowerPoint + PDF)
      │
      ▼
tests/  tie-out: dashboard numbers == SQL answers == findings.json
```

One command rebuilds all of it: `python run_pipeline.py`.

---

## The hard parts

The interesting work was in the cleaning, and every rule below is logged with the evidence that justified it in [`cleaning_report/CLEANING_DECISIONS.md`](cleaning_report/CLEANING_DECISIONS.md).

**Duplicate clients hidden behind re-keyed IDs.** The CRM export claimed to be unique on `client_id`; it wasn't. 58 rows were straight re-exports. Another **124 were the same client re-keyed at `id + 2000`** with slightly misspelled names (*"Grrace Farouk"* / *"Grace Farouk"*). Matching on name alone would have been wrong — the twin is the unique best name match for only 25 of the 124 pairs — so the merge keys on the ID offset *and* name similarity ≥ 0.85 *and* non-conflicting emails. Result: exactly the 1,900 distinct clients the ID block implies, with every booking and order reference remapped.

**FX rates with decimal-point typos, in a currency that genuinely collapsed.** You cannot just cap outliers: the naira really did move 62% in a day. The rule corrects a rate only when it is >5× both neighbours *and* lands within 15% of a neighbour once divided by 10 — **7 typos corrected, every genuine devaluation step kept**. The source also only had weekday rates, so the table is forward-filled into a gap-free daily calendar (**888 filled currency-days**, each flagged with the rate date actually used).

**Dates that lie about their format.** `bookings_2023.csv` is day-first, `bookings_2024.csv` is month-first, despite the dictionary saying both are DD/MM/YYYY. The 2025 workbook's header is on row 5, not row 1, and its "current" Pivot tab is stale. Order timestamps arrive in four formats, ~5% as epoch milliseconds.

**A cost multiplier that doesn't exist.** The dictionary says `day_rate_charged` is 1.5× on overtime days. It isn't — the multiplier (0.5× / 1× / 1.5×) is statistically unrelated to the overtime flag, to hours, and to everything else in the data. So for the 1,020 rows with no charged rate, the standard day rate is used as the unbiased estimate (expected multiplier 0.997) and flagged `rate_is_estimated`, rather than inventing a number.

**Traffic that isn't people.** 23,054 bot sessions (11.4%) and 5,200 spam sessions removed before any conversion rate is computed — which moves the conversion rate from a naive 1.9% to a real 2.14%.

**Nothing is silently dropped.** For every file, `rows in = rows out + rows quarantined`, asserted on each run; the pipeline refuses to write if it doesn't hold. All 2,445 rejected rows are kept in the quarantine file with their original spreadsheet row number, loaded into the warehouse, and the money they carry is quantified: **6.87% of total revenue is touched by unresolved data issues**, and that figure is shown on the dashboard rather than buried.

---

## Verification

Every claim in the deck and memo is reproducible, and the repo proves it three ways:

| Check | Result |
|---|---|
| Cleaning validated against the brief's validation key (`pipeline/validate.py`) | **93 / 93 pass** |
| Row accounting — in = out + quarantined, every file | **holds** (2,445 quarantined, 0 deleted) |
| Warehouse integrity — PKs, FKs, CHECKs, EXCLUDE on overlapping price windows | **all hold on load** |
| Tie-out tests — dashboard == SQL results == `findings.json` (`pytest tests`) | **8 / 8 pass** |
| Full rebuild from raw files | **~5 minutes, end to end** |

The memo, appendix and deck read their numbers from `analysis/findings.json`, so no figure is ever typed by hand into a document.

---

## Running it

### Just look at the results

No database and no raw data needed:

```bash
pip install streamlit plotly pandas pyarrow
streamlit run dashboard/app.py
```

The dashboard runs off the Parquet extracts in `dashboard/data/`. The SQL answers are already in `results/`, and the charts in `charts/`.

### Explore the warehouse

`warehouse/xtrim_warehouse.dump` is the loaded database:

```bash
createdb -h localhost -p 55432 -U xtrim xtrim
pg_restore -h localhost -p 55432 -U xtrim -d xtrim warehouse/xtrim_warehouse.dump
```

Then run anything in `sql/02_questions_answered.sql` against it.

### Rebuild everything from the raw files

Requires Python 3.12 (`pandas`, `numpy`, `scipy`, `openpyxl`, `matplotlib`, `psycopg2-binary`, `pyarrow`, `streamlit`, `plotly`, `python-docx`, `python-pptx`, `pytest`) and a reachable PostgreSQL 17 (`XTRIM_DSN`, default `localhost:55432`, db `xtrim`, user `xtrim`).

```bash
python run_pipeline.py --raw /path/to/raw     # folder holding the 14 original files
python run_pipeline.py --raw /path/to/raw --skip-docs   # skip the memo and deck
```

---

## Repo map

```
brief/                   the brief as handed over: data dictionary, validation key, starter SQL
run_pipeline.py          one command: rebuilds everything below from the raw files
pipeline/                cleaning code — clean_lib, money/FX, column maps, validate
clean/                   the 14 cleaned datasets, all money in NGN
cleaning_report/         decisions log, quarantine, currency conversion audit, missing values
data_quality_report/     Phase 1 per-column profile, defects, false dictionary claims
sql/01_schema.sql        PostgreSQL star schema (stg / core / quarantine)
sql/02_questions_answered.sql   the 14 questions, answered
warehouse/               loader, query runner, extract exporter, decisions log, .dump
results/                 q01.csv … q14.csv
analysis/                analysis.py → findings.json + tables/, charts.py, narrative.py
charts/                  the 13 charts used in the memo and deck
dashboard/               Streamlit app + metrics + Parquet extracts (no database needed)
memo/                    Director memo + technical appendix (Word + PDF) and their builder
presentation/            PowerPoint deck (+ PDF) and its builder
tests/                   tie-out tests
```

---

## Notes

- **The raw source files are not in this repo** — only the cleaned outputs. Point `--raw` at a folder holding the 14 originals to rebuild from scratch.
- The brief, its data dictionary and its validation key are in [`brief/`](brief/); `pipeline/validate.py` encodes the key as 93 hard checks.
- `clean/fx_rates.csv` still names USD/GBP/EUR because it *is* the conversion table (naira per unit). Every other money value in `clean/` is naira. In the warehouse, `core.fct_booking.invoice_currency` records which jobs were originally invoiced in USD/GBP so the FX question stays answerable.
- This is a training brief with a synthetic dataset — the defects were planted so the cleaning could be scored objectively against a known answer key. I worked it end to end as if the engagement were real: profiling, cleaning, modelling, analysis, and delivery to a non-technical Director.
