"""Phase 1 data quality report: profile every raw file, column by column.

    python data_quality_report/profile_raw.py --raw <raw dir>

For each file and column: rows, null count and null rate (counting every spelling of null found in
this export), distinct values, inferred type and how cleanly values parse as it, number of distinct
value *shapes* (a proxy for mixed formats), and examples. Writes column_profile.csv,
column_profile.xlsx and DATA_QUALITY_REPORT.md (the profile plus the defects found per file).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
from clean_lib import decode_mixed  # noqa: E402
from money import parse_money  # noqa: E402

NULL_SPELLINGS = ["", " ", "NA", "N/A", "n/a", "null", "NULL", "None", "none", "-", "--", "#N/A", "unknown", "UNKNOWN",
                  "Unknown", "tbd"]
NULLS = set(NULL_SPELLINGS)
BOOL = {"true", "false", "t", "f", "yes", "no", "y", "n", "1", "0"}
DATE_PATTERNS = [r"^\d{4}-\d{2}-\d{2}$", r"^\d{1,2}/\d{1,2}/\d{4}$", r"^\d{1,2}-[A-Za-z]{3}-\d{2,4}$",
                 r"^[A-Za-z]+ \d{1,2}, \d{4}$", r"^\d{1,2}\.\d{1,2}\.\d{4}$"]
TS_PATTERNS = [r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})?$", r"^1[5-7]\d{11}$"]

FILES = [
    ("clients_export.csv", ","), ("bookings_2023.csv", ","), ("bookings_2024.csv", ","), ("bookings_2025_H1.xlsx", None),
    ("crew.csv", ","), ("crew_timesheets.csv", ","), ("merch_products.csv", ","), ("merch_orders.csv", ","),
    ("merch_refunds.csv", ","), ("web_sessions_2023.csv", ","), ("web_sessions_2024.csv", ","),
    ("web_sessions_2025_H1.tsv", "\t"), ("marketing_spend.csv", ";"), ("fx_rates.csv", ","),
]

# Defects found per file. Counts come from the pipeline's decisions log and quarantine file.
DEFECTS = {
    "clients_export.csv": [
        "Mixed encoding: raw Windows-1252, UTF-8 and double-encoded UTF-8 in one file; a plain `pd.read_csv` raises UnicodeDecodeError.",
        "Mojibake in names (`AndrÃ©` for `André`), repaired rather than stripped.",
        "`client_id` is not unique: 58 exact repeat rows; IDs spelled `XT-00123`, `xt123`, `123`, `XT00123`, `' XT-00123 '`.",
        "124 fuzzy duplicates: the same client re-keyed at id + 2000 with a typo'd name and a `+1` email alias.",
        "`email` is not always populated (dictionary says it is); `type` has 9 spellings of 2 values.",
        "`signup_date` mixes ISO, DD/MM/YYYY and DD-Mon-YYYY (dictionary says ISO only).",
        "Phones: 590 of the 1,900 deduplicated clients have 8 or 9 digits (not a valid Nigerian mobile).",
    ],
    "bookings_2023.csv": [
        "Dates are day-first (531 values can only be read day-first, 0 only month-first).",
        "Money strings: `₦1,250,000.00`, `NGN 1250000`, `6.83M`, `GBP 1,320.00`, `₦ 1 250 000.00`, `NGN1,250,000.00/-`.",
        "Currency blank on many rows; USD/GBP jobs hidden inside the amount text.",
        "330 raw spellings (case, spacing, abbreviations) of 8 service lines across the 2023 and 2024 files (`documentary`, `Short-Film`, `EVENT COVERAGE`); statuses `Complete`, `Done`, `delivered`.",
        "19 duplicate booking rows (IDs differ only by case, spacing and hyphen).",
    ],
    "bookings_2024.csv": [
        "Columns renamed by the new ERP (`booking_ref`, `customer_id`, `date_of_shoot`, `amount_gross`).",
        "Dates are MONTH-first (526 only month-first, 0 only day-first); the dictionary says DD/MM.",
        "`vat_applied` has 14 spellings of true/false; `discount_pct` mixes `0.15`, `15` and `15%`.",
        "18 duplicate rows, 7 of which disagree only on `vat_applied`.",
    ],
    "bookings_2025_H1.xlsx": [
        "Header is on sheet row 5, not row 1 (dictionary is wrong).",
        "6 monthly subtotal rows, a GRAND TOTAL row, 13 blank spacer rows and a footer note inside the data.",
        "Shoot dates mix Excel serial numbers, DD/MM/YYYY, DD-Mon-YY and 'Month DD, YYYY'.",
        "The Pivot tab is stale (dictionary says it is current); the footer admits 'figures exclude USD/GBP jobs'.",
    ],
    "crew.csv": [
        "Day rates written 17 different ways (`₦ 156 000.00`, `76.0K`, `271,000.00 NGN`); 13 blank.",
        "`is_active` has 14 spellings of true/false; 7 blank roles; names with mojibake (`NÃƒÂºria`).",
        "20 rows share a name and 108 share an email, but are different people (different id, role, rate).",
    ],
    "crew_timesheets.csv": [
        "319 rows (2.1%) reference booking ids that exist nowhere (dictionary says always valid).",
        "129 rows log 26 hours in a day (impossible); 1,046 rows log 14h, so the '12-hour cap' is false.",
        "Hours written as `9h`, `6 hrs`, `12`, `10.0`; 223 exact duplicate rows.",
        "The 0.5x / 1x / 1.5x day-rate multiplier is unrelated to the overtime flag (dictionary says 1.5x = overtime).",
        "1,020 rows have no charged day rate; 1,311 have no role.",
    ],
    "merch_products.csv": [
        "One row per SKU per price period: 137 rows, 45 SKUs, 57 SKU spellings.",
        "Validity windows overlap (29 overlapping pairs across 19 SKUs), 7 have valid_to < valid_from, 8 gaps.",
        "Double-encoded collection names (`Anniversary Ã¢â‚¬â„¢05`); blanks in category, collection, colour and cost.",
    ],
    "merch_orders.csv": [
        "`order_ts` is not all UTC: naive (2023), `Z` (2024), `+01:00` (2025), and ~5% epoch milliseconds.",
        "786 exact duplicate lines; 190 lines with quantity 9999 (placeholder); 280 lines with quantity -1.",
        "713 lines carry client ids 8,001-9,998 that are not in the CRM (400 repaired from the same order, 313 quarantined).",
        "2,502 lines (5.8%) have a product_name that disagrees with the SKU; the SKU is right.",
        "Discount codes do not lower the price paid.",
    ],
    "merch_refunds.csv": [
        "`refund_amount` is not always positive: 4,277 written as `(45,000)` or with a minus sign.",
        "Refund dates mix day-first and month-first; 57 cannot be resolved and are left blank.",
        "174 refunds reference orders that do not exist; 405 refund ids are shared by different refunds.",
    ],
    "web_sessions_2023.csv": [
        "Timestamps are epoch ms of Lagos wall-clock time (the handover said UTC).",
        "Bot traffic is not filtered upstream: user agents include Googlebot, SemrushBot, curl, python-requests.",
        "utm_source has ~24 spellings of 8 channels (`ig`, `fb`, `meta`, `(direct)`, `google.com`).",
    ],
    "web_sessions_2024.csv": [
        "Column names changed again; timestamps are naive Lagos time.",
        "Referral-spam burst: 5,200 sessions, 8–21 September 2024, from `buy-traffic.ru`, `free-seo-tools.xyz`, `seo-monitor.top`, all 0 seconds.",
        "Revenue spelled `0`, `0.00`, `NA` and blank for the same meaning.",
    ],
    "web_sessions_2025_H1.tsv": [
        "Tab-delimited with CRLF line endings, despite sitting beside two CSVs.",
        "Only 68.2% of converted sessions (all files) carry a transaction_id that joins a real order (dictionary says every one joins).",
    ],
    "marketing_spend.csv": [
        "Semicolon-delimited; ~70% of spend values use a decimal comma (`13039,20`); impressions with space thousands (`49 235`).",
        "117 exact duplicate rows from a double-submitted upload.",
        "Currency blank or lower-case; campaign names differ in case and separators from utm_campaign.",
    ],
    "fx_rates.csv": [
        "Weekdays only, and 35 weekdays are missing too (dictionary says every calendar day).",
        "7 rates are 10x decimal-point typos (one in ~250); the June 2023 and January 2024 devaluation jumps are real.",
    ],
}


def read_raw(raw: Path, name: str, sep):
    if name.endswith(".xlsx"):
        df = pd.read_excel(raw / name, sheet_name="H1 2025 Bookings", header=4, dtype=object)
        return df.map(lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))
    text = decode_mixed((raw / name).read_bytes())
    import io
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, na_filter=False)


def shape(v: str) -> str:
    return re.sub(r"[A-Za-z]+", "A", re.sub(r"\d+", "9", v))


def infer(values: pd.Series):
    v = values.astype(str).str.strip()
    n = len(v)
    if n == 0:
        return "empty", 0.0
    low = v.str.lower()
    tests = {
        "boolean": low.isin(BOOL).mean(),
        "integer": v.str.fullmatch(r"-?\d+").mean(),
        "decimal": v.str.fullmatch(r"-?\d+\.\d+|-?\d+,\d{1,2}").mean(),
        "timestamp": pd.concat([v.str.fullmatch(p) for p in TS_PATTERNS], axis=1).any(axis=1).mean(),
        "date": pd.concat([v.str.fullmatch(p) for p in DATE_PATTERNS], axis=1).any(axis=1).mean(),
    }
    money = v.map(lambda x: parse_money(x, allow_decimal_comma=True)[0] is not None).mean()
    if money > 0.9 and v.str.contains(r"[₦$£€]|NGN|USD|GBP|[kKmM]$|,", regex=True).mean() > 0.05:
        tests["money"] = money
    best = max(tests, key=tests.get)
    if tests[best] < 0.5:
        return "text", 1.0
    if best in ("integer", "decimal") and tests["integer"] + tests["decimal"] > 0.5:
        return ("decimal" if tests["decimal"] > 0 else "integer"), tests["integer"] + tests["decimal"]
    return best, tests[best]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, required=True)
    a = ap.parse_args()
    rows = []
    for name, sep in FILES:
        df = read_raw(a.raw, name, sep)
        for col in df.columns:
            s = df[col]
            is_null = s.isin(NULLS)
            spellings = s[is_null].map(lambda x: repr(x)).value_counts()
            non = s[~is_null]
            typ, parse = infer(non)
            shapes = non.astype(str).str.strip().map(shape).nunique()
            rows.append({
                "file": name, "column": col, "rows": len(s), "nulls": int(is_null.sum()),
                "null_rate_pct": round(100 * is_null.mean(), 2),
                "null_spellings": "; ".join(f"{k} x{v}" for k, v in spellings.items()),
                "distinct_non_null": int(non.nunique()), "inferred_type": typ,
                "parses_as_type_pct": round(100 * parse, 1), "value_shapes": int(shapes),
                "examples": " | ".join(non.drop_duplicates().astype(str).head(4).map(lambda x: x[:40])),
            })
        print(f"  profiled {name}: {len(df):,} rows x {len(df.columns)} columns")
    prof = pd.DataFrame(rows)
    prof.to_csv(HERE / "column_profile.csv", index=False)
    with pd.ExcelWriter(HERE / "column_profile.xlsx") as xw:
        prof.to_excel(xw, sheet_name="column_profile", index=False)
        pd.DataFrame([(f, d) for f, ds in DEFECTS.items() for d in ds], columns=["file", "defect"]).to_excel(
            xw, sheet_name="defects", index=False)

    md = ["# Data quality report — raw extracts", "",
          "Phase 1 deliverable. Every raw file profiled column by column, then the specific defects found. "
          "Nulls count **every** spelling of missing found in this export: "
          + ", ".join(f"`{x!r}`" for x in NULL_SPELLINGS) + ".", "",
          "*value_shapes* = number of distinct formats a column's values take (digits → 9, letters → A); a date "
          "column with 5 shapes is written 5 different ways. *parses_as_type_pct* = share of non-null values that "
          "match the inferred type cleanly.", "",
          "Full profile: `column_profile.csv` / `column_profile.xlsx`. How each defect was handled: "
          "`../cleaning_report/CLEANING_DECISIONS.md` and `../warehouse/WAREHOUSE_DECISIONS.md`.", "",
          "## Summary by file", "", "| File | Rows | Columns | Columns with nulls | Worst null rate | Defects found |",
          "|---|---:|---:|---:|---:|---:|"]
    for name, _ in FILES:
        p = prof[prof.file == name]
        worst = p.sort_values("null_rate_pct").iloc[-1]
        md.append(f"| {name} | {p.rows.iloc[0]:,} | {len(p)} | {(p.nulls > 0).sum()} | "
                  f"{worst.null_rate_pct:.1f}% ({worst.column}) | {len(DEFECTS[name])} |")
    md += ["", "## Data dictionary claims that are false", "",
           "1. `clients_export.csv` is unique on `client_id` — **false** (58 repeat rows, 124 re-keyed duplicates).",
           "2. `email` is always populated — **false**.",
           "3. `signup_date` is ISO — **false** (three formats).",
           "4. Booking dates are DD/MM/YYYY in both files — **false** (2024 is month-first).",
           "5. The 2025 workbook header is on row 1 and the Pivot tab is current — **false** (row 5; Pivot is stale).",
           "6. `timesheets.booking_id` is always valid — **false** (319 orphans).",
           "7. `hours_worked` is capped at 12 — **false** (1,046 rows at 14h, 129 at an impossible 26h).",
           "8. `day_rate_charged` is 1.5x on overtime days — **false** (the multiplier is independent of the flag).",
           "9. Product validity windows do not overlap — **false** (29 overlapping pairs, 7 inverted).",
           "10. `order_ts` is all UTC — **false** (four formats, ~5% epoch ms).",
           "11. `refund_amount` is always positive — **false** (4,277 negative).",
           "12. `transaction_id` joins an order for every conversion — **false** (68.2%).",
           "13. Bot filtering is applied upstream — **false** (23,054 bot sessions, 11.4%).",
           "14. `fx_rates.csv` covers every calendar day — **false** (weekdays only, 35 weekdays missing).",
           "15. `marketing_spend.campaign_name` matches `utm_campaign` — **false** (case and separators differ; `always_on`).",
           ""]
    for name, _ in FILES:
        p = prof[prof.file == name]
        md += [f"## {name}", "", "**Defects found**", ""] + [f"- {d}" for d in DEFECTS[name]] + [
            "", "| Column | Null rate | Null spellings | Distinct | Inferred type | Parses | Shapes | Examples |",
            "|---|---:|---|---:|---|---:|---:|---|"]
        for r in p.itertuples():
            ex = r.examples.replace("|", "¦")
            sp = r.null_spellings if len(r.null_spellings) < 90 else r.null_spellings[:87] + "..."
            md.append(f"| {r.column} | {r.null_rate_pct:.1f}% | {sp} | {r.distinct_non_null:,} | {r.inferred_type} | "
                      f"{r.parses_as_type_pct:.0f}% | {r.value_shapes} | {ex} |")
        md.append("")
    (HERE / "DATA_QUALITY_REPORT.md").write_text("\n".join(md))
    print("report written")


if __name__ == "__main__":
    main()
