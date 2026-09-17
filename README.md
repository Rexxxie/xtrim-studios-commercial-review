# Xtrim Studios — commercial performance review (finished project)

Everything the brief asked for, rebuilt from the raw files with one command. All money is Nigerian naira (₦).

## Start here

| If you want… | Open |
|---|---|
| The presentation | `presentation/Xtrim_Studios_Commercial_Review.pptx` (PDF copy beside it) |
| The 2-page memo to the Director | `memo/Xtrim_Studios_Director_Memo.docx` (PDF copy beside it) |
| The technical appendix | `memo/Xtrim_Studios_Technical_Appendix.docx` (PDF copy beside it) |
| The dashboard | `streamlit run dashboard/app.py` (Production · Merch · Acquisition tabs, filters, data-quality tile) |
| The SQL answers | `sql/02_questions_answered.sql`, results in `results/q01.csv` … `q14.csv` |
| The data quality report (Phase 1) | `data_quality_report/DATA_QUALITY_REPORT.md` (+ `column_profile.xlsx`) |
| The cleaned datasets | `clean/` (same 14 filenames, every money column in NGN) |
| What was thrown away and why | `cleaning_report/quarantine_rejected_rows.csv`, `cleaning_report/CLEANING_DECISIONS.md` |

## The answer in brief

- Revenue grew 31% in naira (₦7.07B in 2023 → ₦9.24B in 2024) but fell 56% in dollars ($8.0M → $3.6M); the naira lost 90% against the dollar.
- ₦5.96B (30%) of production revenue is in jobs not yet completed, including ₦1.60B on 175 jobs from 2023–2024 still marked Invoiced. Postponed work rose from 5.9% to 13.8% of revenue.
- Studio Rental loses money on crew cost alone (−5.3% margin); 182 jobs cost ₦140M more in crew than they earned (147 genuine, 35 caused by bad timesheet data).
- ₦860M of ads returned ₦0.35 of tracked web-shop revenue per ₦1. They break even only if 6.7% of the ₦6.56B of bookings credited to Google/Instagram/TikTok came from paid ads — nothing records that.
- Merch is healthy but small (₦1.38B net, 61% contribution, no drop lost money).
- Recorded costs (crew, ads, merch stock) are only 17% of 2024 revenue: the cash squeeze is in costs these systems don't capture and in unpaid invoices.

## Folder map

```
done/
  run_pipeline.py          one command: rebuilds everything below from the raw files
  pipeline/                cleaning code (run_pipeline.py, validate.py, maps, parsers)
  clean/                   cleaned datasets, all NGN
  cleaning_report/         decisions log, quarantine, currency conversion audit, missing values
  data_quality_report/     Phase 1 per-file, per-column profile + defects + false dictionary claims
  sql/01_schema.sql        PostgreSQL star schema (stg / core / quarantine)
  sql/02_questions_answered.sql   the 14 SQL questions, answered against core.*
  warehouse/               loader, query runner, extract exporter, decisions log, xtrim_warehouse.dump
  results/                 output of every SQL question
  analysis/                analysis.py → findings.json + tables/, charts.py, narrative.py
  charts/                  13 charts used in the memo and deck
  dashboard/               Streamlit app + metrics + data extracts (runs without a database)
  memo/                    Director memo + technical appendix (Word + PDF) and their builder
  presentation/            PowerPoint deck (+ PDF) and its builder
  tests/                   tie-out tests: dashboard numbers == SQL answers
```

## Verification

- Cleaning: **93 / 93** checks against `docs/VALIDATION_KEY.md` pass (`pipeline/validate.py`).
- Row accounting: for every file, rows in = rows out + rows quarantined (2,445 quarantined, none deleted).
- Warehouse: primary keys, foreign keys, CHECKs and an EXCLUDE constraint on price windows all hold on load.
- Dashboard: **8 / 8** tie-out tests pass (`python -m pytest tests`).
- Full rebuild from the raw files runs end to end in about 5 minutes.

## Rebuild or run it yourself

Requirements: Python 3.12 with pandas, numpy, scipy, openpyxl, matplotlib, psycopg2-binary, pyarrow,
streamlit, plotly, python-docx, python-pptx, pytest; PostgreSQL 17.

```bash
# 1. a PostgreSQL database for the warehouse (any server works; set XTRIM_DSN if not the default)
initdb -D ~/xtrim_pg -U xtrim --auth=trust -E UTF8 --locale=en_US.UTF-8
pg_ctl -D ~/xtrim_pg -o "-p 55432" -l ~/xtrim_pg/log start
createdb -h localhost -p 55432 -U xtrim xtrim

# 2. everything else
python run_pipeline.py                     # reads ../xtrim_studios_project/raw_original_backup
python run_pipeline.py --raw /path/to/raw  # or any folder with the 14 original files

# just look at the warehouse without rebuilding
pg_restore -h localhost -p 55432 -U xtrim -d xtrim warehouse/xtrim_warehouse.dump

# the dashboard needs no database
streamlit run dashboard/app.py
```

PostgreSQL binaries from the EDB installer live in `/Library/PostgreSQL/17/bin`.

## Notes on the source data

- The original raw files are in `../xtrim_studios_project/raw_original_backup/` (byte-for-byte originals). The
  project's own `raw/` folder was overwritten with cleaned files by an earlier cleaning pass; this project reads
  the backup, never `raw/`.
- `fx_rates.csv` in `clean/` still names USD/GBP/EUR because it is the conversion table (naira per unit). Every
  other money value is naira. In the warehouse, `core.fct_booking.invoice_currency` labels which jobs were invoiced
  in USD/GBP (amounts are still naira) so the FX question can be answered.
