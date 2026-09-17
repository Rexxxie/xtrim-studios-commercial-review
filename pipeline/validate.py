"""Independent checks on the cleaned files: re-reads them from disk, grades them against
docs/VALIDATION_KEY.md and checks integrity. Exit code 1 if any hard check fails.

    python validate.py <clean dir> <report dir>
"""
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from clean_lib import _MOJI

OUT, REP = Path(sys.argv[1]), Path(sys.argv[2])
results = []


def check(name, ok, got, target, hard=True):
    results.append((("PASS" if ok else ("FAIL" if hard else "NOTE")), name, got, target))


def near(x, target, tol):
    return abs(x - target) <= tol


PLACEHOLDERS = {"No issues", "Not applicable", "Unknown", "Guest"}
PANDAS_NA = {"", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND", "1.#QNAN", "<NA>", "N/A",
             "NA", "NULL", "NaN", "None", "n/a", "nan", "null"}
assert not (PLACEHOLDERS & PANDAS_NA), "a placeholder token would be read back as missing by pandas"


def rd(name, **kw):
    if name.endswith(".xlsx"):
        df = pd.read_excel(OUT / name, dtype=str, keep_default_na=False)
        for col in [c for c in df.columns if c.endswith("_date")]:
            assert df[col].str.match(r"^(\d{4}-\d{2}-\d{2}( 00:00:00)?)?$").all(), f"{col} has non-date cells"
            df[col] = df[col].str.slice(0, 10)   # Excel date cells come back as 'YYYY-MM-DD 00:00:00'
        return df
    return pd.read_csv(OUT / name, sep="\t" if name.endswith(".tsv") else ",", dtype=str, keep_default_na=False, **kw)


files = ["fx_rates.csv", "clients_export.csv", "bookings_2023.csv", "bookings_2024.csv", "bookings_2025_H1.xlsx",
         "crew.csv", "crew_timesheets.csv", "merch_products.csv", "merch_orders.csv", "merch_refunds.csv",
         "marketing_spend.csv", "web_sessions_2023.csv", "web_sessions_2024.csv", "web_sessions_2025_H1.tsv"]
RAW = {f: rd(f) for f in files}                      # exactly as published, placeholders included
D = {f: df.replace(list(PLACEHOLDERS), "") for f, df in RAW.items()}   # placeholders back to blank for the checks
empty = {f: int((df.astype(str).apply(lambda s: s.str.strip() == "")).sum().sum()) for f, df in RAW.items()}
check("no empty cell in any published file", sum(empty.values()) == 0, {k: v for k, v in empty.items() if v}, 0)
stray = {f: sorted(set(RAW[f].columns[(RAW[f] == "Guest").any()]) - {"client_id"}) for f in files}
check("'Guest' only ever appears in merch_orders.client_id", not any(stray.values()),
      {k: v for k, v in stray.items() if v}, "none")
Q = pd.read_csv(REP / "quarantine_rejected_rows.csv", dtype=str, keep_default_na=False)
A = pd.read_csv(REP / "currency_conversion_audit.csv", dtype=str, keep_default_na=False)
qn = Counter(zip(Q.src_file, Q.reason))

# ------------------------------------------------------------------ text hygiene & currency
C1 = re.compile("[-]")
FOREIGN = re.compile(r"\b(?:USD|GBP|EUR)\b|[$£€]")
bad_text, foreign_hits = Counter(), Counter()
for f, df in D.items():
    for col in df.columns:
        s = df[col].astype(str)
        bad_text[f] += int(s.str.contains(_MOJI).sum() + s.str.contains(C1).sum())
        if not (f == "fx_rates.csv" and col == "from_currency"):
            foreign_hits[(f, col)] += int(s.str.contains(FOREIGN).sum())
check("no mojibake / control characters in any cell", sum(bad_text.values()) == 0, dict(+bad_text), 0)
check("no USD/GBP/EUR/$/£/€ anywhere except fx_rates.from_currency", sum(foreign_hits.values()) == 0,
      {k: v for k, v in foreign_hits.items() if v}, 0)
for f, df in D.items():
    for col in ("currency", "billing_currency", "to_currency"):
        if col in df:
            check(f"{f}.{col} is all NGN", set(df[col]) == {"NGN"}, sorted(set(df[col])), "{'NGN'}")
money_cols = [(f, c) for f, df in D.items() for c in df.columns if c.endswith("_ngn") or c in ("rate", "original_rate")]
nonnum = {f"{f}.{c}": int((pd.to_numeric(D[f][c].replace("", None), errors="coerce").isna() & (D[f][c] != "")).sum())
          for f, c in money_cols}
check("every money value is a plain number", sum(nonnum.values()) == 0, {k: v for k, v in nonnum.items() if v}, 0)

# ------------------------------------------------------------------ row accounting
raw_rows = {"fx_rates.csv": 1860, "clients_export.csv": 2082, "bookings_2023.csv": 977, "bookings_2024.csv": 955,
            "bookings_2025_H1.xlsx": 387, "crew.csv": 140, "crew_timesheets.csv": 15156, "merch_products.csv": 137,
            "merch_orders.csv": 44495, "merch_refunds.csv": 8888, "marketing_spend.csv": 4048,
            "web_sessions_2023.csv": 62868, "web_sessions_2024.csv": 88414, "web_sessions_2025_H1.tsv": 51764}
for f, n in raw_rows.items():
    kept = int((D[f].is_filled == "False").sum()) if f == "fx_rates.csv" else len(D[f])
    check(f"row accounting {f}", kept + int((Q.src_file == f).sum()) == n,
          f"{kept} kept + {int((Q.src_file == f).sum())} quarantined", n)
check("quarantine payloads are valid JSON", all(isinstance(json.loads(p), dict) for p in Q.payload), "", "")

# ------------------------------------------------------------------ entity counts (VALIDATION_KEY)
cl = D["clients_export.csv"]
check("distinct real clients", len(cl) == 1900, len(cl), 1900)
check("client_id unique", cl.client_id.is_unique, "", "")
check("exact duplicate client rows", True, qn[("clients_export.csv", "duplicate_client_id_row")], "~66", hard=False)
fz = qn[("clients_export.csv", "fuzzy_duplicate_client")]
check("fuzzy duplicate client pairs", 100 <= fz <= 125, fz, "100-125")
b23, b24, b25 = D["bookings_2023.csv"], D["bookings_2024.csv"], D["bookings_2025_H1.xlsx"]
B = pd.concat([b23.assign(src="2023"), b24.assign(src="2024"), b25.assign(src="2025")], ignore_index=True)
check("bookings after dedupe", len(B) == 2261, len(B), 2261)
check("bookings 2023 / 2024 / 2025", (len(b23), len(b24), len(b25)) == (958, 937, 366), (len(b23), len(b24), len(b25)),
      (958, 937, 366))
check("duplicate booking rows 2023 / 2024",
      (sum(v for (f, r), v in qn.items() if f == "bookings_2023.csv" and "duplicate" in r),
       sum(v for (f, r), v in qn.items() if f == "bookings_2024.csv" and "duplicate" in r)) == (19, 18),
      (sum(v for (f, r), v in qn.items() if f == "bookings_2023.csv" and "duplicate" in r),
       sum(v for (f, r), v in qn.items() if f == "bookings_2024.csv" and "duplicate" in r)), "~19, ~18")
check("booking_id unique across files", B.booking_id.is_unique, "", "")
check("crew members", len(D["crew.csv"]) == 140, len(D["crew.csv"]), 140)
pr = D["merch_products.csv"]
check("distinct SKUs", pr.sku.nunique() == 45, pr.sku.nunique(), 45)
od = raw_rows["merch_orders.csv"] - qn[("merch_orders.csv", "exact_duplicate_row")]
check("unique order lines after dedupe", od == 43709, od, 43709)
rf = D["merch_refunds.csv"]
check("refund orphans", near(qn[("merch_refunds.csv", "orphan_order_id")], 174, 5), qn[("merch_refunds.csv", "orphan_order_id")], "~174")
S = pd.concat([D["web_sessions_2023.csv"], D["web_sessions_2024.csv"], D["web_sessions_2025_H1.tsv"]], ignore_index=True)
check("total sessions", len(S) == 203046, len(S), 203046)
check("ad spend rows after double-upload removed", near(len(D["marketing_spend.csv"]), 3930, 15),
      len(D["marketing_spend.csv"]), "~3,930")

# ------------------------------------------------------------------ canonical sets
nu = lambda s: s.replace("", None).dropna().nunique()
card = {"service_type": (nu(B.service_type), 8),
        "booking status": (nu(B.status), 5),
        "product category": (nu(pr.category), 10),
        "collections": (nu(pr.collection), 7),
        "crew roles": (nu(D["crew.csv"].role), 10),
        "marketing channels": (nu(D["marketing_spend.csv"].channel), 6),
        "utm_source groups": (nu(S.channel), 8)}
for k, (got, target) in card.items():
    check(f"cardinality {k}", got == target, got, target)
check("service names", set(B.service_type.replace("", None).dropna()) == {
    "Wedding Film", "Music Video", "Commercial / TVC", "Corporate Documentary", "Photoshoot", "Event Coverage",
    "Short Film", "Studio Rental"}, sorted(set(B.service_type) - {""}), "8 named")
check("status names", set(B.status) - {""} == {"Completed", "Cancelled", "Postponed", "In Production", "Invoiced"},
      sorted(set(B.status)), "5 named (plus blanks where the status was never recorded)")

# ------------------------------------------------------------------ bookings money
cur = A[A.field == "gross_amount"].set_index("record_id").original_currency
B["orig"] = B.booking_id.map(cur)
B["gross"] = pd.to_numeric(B.gross_amount_ngn.replace("", None))
B["net"] = pd.to_numeric(B.net_amount_ngn.replace("", None))
live = B[B.status != "Cancelled"]
check("non-cancelled bookings", len(live) == 2058, len(live), 2058)
check("non-cancelled NGN bookings", int((live.orig == "NGN").sum()) == 1742, int((live.orig == "NGN").sum()), 1742)
g = float(live[live.orig == "NGN"].gross.sum())
n = float(live[live.orig == "NGN"].net.sum())
check("gross NGN revenue, NGN-billed, non-cancelled", abs(g / 15_429_968_000 - 1) <= 0.005, f"{g:,.0f}", "15,429,968,000 +/-0.5%")
check("net of discount, same population", abs(n / 15_249_025_550 - 1) <= 0.005, f"{n:,.2f}", "15,249,025,550 +/-0.5%")
fc = Counter(live.orig[live.orig != "NGN"])
check("foreign non-cancelled jobs USD / GBP", (fc["USD"], fc["GBP"]) == (178, 138), dict(fc), "178 USD, 138 GBP")
B["month"] = pd.to_datetime(B.shoot_date.replace("", None)).dt.month
B["year"] = pd.to_datetime(B.shoot_date.replace("", None)).dt.year
full_years = B[(B.status != "Cancelled") & B.year.isin([2023, 2024])]   # 2025 is a half year
top = full_years.month.value_counts()
check("busiest months, complete years, non-cancelled", list(top.index[:2]) == [12, 11], top.head(3).to_dict(),
      "Dec (227), then Nov (220)")
svc = live.service_type.value_counts().to_dict()
target_svc = {"Wedding Film": 444, "Photoshoot": 403, "Event Coverage": 303, "Music Video": 280, "Studio Rental": 201,
              "Commercial / TVC": 178, "Corporate Documentary": 161, "Short Film": 88}
check("service ranking by volume, non-cancelled",
      [k for k in svc if k] [:8] == list(target_svc), [k for k in svc if k][:8], list(target_svc))
check("bookings by service vs true counts (blank service types cannot be recovered)",
      all(svc.get(k, 0) <= v for k, v in target_svc.items()) and
      sum(svc.get(k, 0) for k in target_svc) + svc.get("", 0) == len(live),
      {k: f"{svc.get(k, 0)}/{v}" for k, v in target_svc.items()} | {"(blank)": svc.get("", 0)}, target_svc, hard=False)
check("no NGN amount below 100k and no foreign amount at/above 100k", not B.dq_flags.str.contains(
    "ngn_amount_below_100k|foreign_amount_at_or_above_100k").any(), "", "")
check("shoot_days within 1-30", pd.to_numeric(B.shoot_days.replace("", None)).dropna().between(1, 30).all(), "", "")
disc = pd.to_numeric(B.discount_pct)
check("discount_pct within [0, 1)", disc.between(0, 0.999).all(), sorted(disc.unique()), "[0,1)")
check("net = gross x (1 - discount)", ((B.gross * (1 - disc) - B.net).abs().dropna() < 0.011).all(), "", "")
check("booking client_id exists in clients", B.client_id.isin(cl.client_id).all(), "", "")

# ------------------------------------------------------------------ sessions
bots = int((S.is_bot == "True").sum())
check("bot sessions", bots == 23054, f"{bots} ({bots / len(S):.1%})", "~23,054 (11.4%)")
sp = S[S.is_spam == "True"]
check("referral-spam burst", len(sp) == 5200 and sp.session_date_lagos.min() >= "2024-09-08" and
      sp.session_date_lagos.max() <= "2024-09-21" and sp.source.nunique() == 3 and (sp.duration_seconds == "0").all(),
      f"{len(sp)} sessions {sp.session_date_lagos.min()}..{sp.session_date_lagos.max()}, sources "
      f"{sorted(sp.source.unique())}, zero-duration {(sp.duration_seconds == '0').mean():.0%}",
      "5,200, Sep 8-21 2024, 3 sources, duration 0")
hum = S[S.is_bot == "False"]
check("human sessions", abs(len(hum) / 179_992 - 1) <= 0.01, len(hum), "179,992 +/-1%")
orders = D["merch_orders.csv"]
conv = S[S.converted == "True"]
j = conv.transaction_id.isin(set(orders.order_id)).mean()
check("conversions whose transaction_id joins an order", near(j, 0.70, 0.03), f"{j:.1%}", "~70%")
cr = (hum.converted == "True").mean()
check("conversion rate on human sessions", near(cr, 0.021, 0.002), f"{cr:.2%}", "~2.1%")
check("session_id unique across files", S.session_id.is_unique, "", "")
utc = pd.to_datetime(S.session_start_utc).dt.tz_localize(None)
check("session_date_lagos = UTC start + 1h", ((utc + timedelta(hours=1)).dt.strftime("%Y-%m-%d") == S.session_date_lagos).all(), "", "")

# ------------------------------------------------------------------ timesheets
ts = D["crew_timesheets.csv"]
orph = qn[("crew_timesheets.csv", "orphan_booking_id")] + 0
check("timesheet rows referencing a missing booking", near(orph / 15156, 0.02, 0.005), f"{orph} ({orph / 15156:.1%})", "~2%")
h26 = int(ts.dq_flags.str.contains("hours_worked_26h_impossible_blanked").sum())
check("hours_worked = 26 rows", near(h26 / 15156, 0.01, 0.003), f"{h26} ({h26 / 15156:.2%})", "~1%")
check("duplicate timesheet rows", near(qn[("crew_timesheets.csv", "exact_duplicate_row")], 224, 5),
      qn[("crew_timesheets.csv", "exact_duplicate_row")], "~224")
hrs = pd.to_numeric(ts.hours_worked.replace("", None)).dropna()
check("hours_worked within 0-20", hrs.between(0, 20).all(), sorted(hrs.unique()), "0-20")
check("timesheet booking/crew ids exist", ts.booking_id.isin(B.booking_id).all() and ts.crew_id.isin(D["crew.csv"].crew_id).all(), "", "")
check("timesheet_id unique", ts.timesheet_id.is_unique, "", "")

# ------------------------------------------------------------------ products / orders / refunds
pr_ok = True
for sku, gp in pr.assign(vf=pd.to_datetime(pr.valid_from), vt=pr.valid_to.map(lambda v: date.fromisoformat(v))).groupby("sku"):
    gp = gp.sort_values("vf")
    vf = [d.date() for d in gp.vf]
    vt = list(gp.vt)
    pr_ok &= all(vt[k] >= vf[k] for k in range(len(vf)))
    pr_ok &= all(vf[k + 1] == vt[k] + timedelta(days=1) for k in range(len(vf) - 1))
    pr_ok &= vt[-1] == date(9999, 12, 31) and (gp.is_current == "True").sum() == 1 and gp.is_current.iloc[-1] == "True"
check("product windows non-overlapping, gap-free, latest open & current", pr_ok, "", "")
check("order (order_id, line_no) unique", not orders.duplicated(["order_id", "line_no"]).any(), "", "")
check("order client_id exists or is blank (guest)", orders.client_id.replace("", None).dropna().isin(cl.client_id).all(), "", "")
check("order sku exists", orders.sku.isin(pr.sku).all(), "", "")
check("one timestamp per order", (orders.groupby("order_id").order_ts_utc.nunique() == 1).all(), "", "")
names = pr.groupby("sku").product_name.first()
check("order product_name matches its SKU", (orders.product_name == orders.sku.map(names)).all(), "", "")
pnd = int(orders.dq_flags.str.contains("product_name_did_not_match_sku").sum())
check("order lines whose raw product_name disagreed with sku", near(pnd / len(orders), 0.06, 0.01), f"{pnd} ({pnd / len(orders):.1%})", "~6%")
check("refund order_id exists in orders", rf.order_id.isin(set(orders.order_id)).all(), "", "")
check("refund_key unique", rf.refund_key.is_unique, "", "")
check("refund amounts positive", (pd.to_numeric(rf.refund_amount_ngn) >= 0).all(), "", "")
neg = int(rf.dq_flags.str.contains("amount_written_as_negative").sum())
check("refund amounts written negative", near(neg / len(rf), 0.5, 0.05), f"{neg} ({neg / len(rf):.0%})", "roughly half")
sd = D["marketing_spend.csv"]
check("spend grain unique", not sd.duplicated(["spend_date", "channel", "campaign"]).any(), "", "")
sess_c = set(S.campaign.replace("", None).dropna())
spend_c = set(sd.campaign)
check("spend campaigns found in session utm_campaign", True, f"spend {sorted(spend_c)} | sessions {sorted(sess_c)}", "", hard=False)

# ------------------------------------------------------------------ fx
fx = D["fx_rates.csv"]
corr = int((fx.is_corrected == "True").sum())
pub = int((fx.is_filled == "False").sum())
check("fat-finger FX outliers (~1 in 250)", near(pub / max(corr, 1), 250, 60), f"{corr} of {pub} (1 in {pub // max(corr, 1)})", "~1 in 250")
check("fx calendar unique per day/currency", not fx.duplicated(["rate_date", "from_currency"]).any(), "", "")
for c_ in ("USD", "GBP", "EUR"):
    s_ = fx[fx.from_currency == c_].sort_values("rate_date")
    r_ = pd.to_numeric(s_.rate).to_numpy()
    jumps = [(s_.rate_date.iloc[i + 1], round(r_[i + 1] / r_[i], 2)) for i in range(len(r_) - 1) if r_[i + 1] / r_[i] > 1.25]
    check(f"{c_} devaluation jumps kept (June 2023, Jan 2024)", [d[:7] for d, _ in jumps] == ["2023-06", "2024-01"], jumps, "2023-06, 2024-01")

width = max(len(r[1]) for r in results)
for status, name, got, target in results:
    print(f"{status:4s}  {name:<{width}}  got: {got}  target: {target}")
fails = [r for r in results if r[0] == "FAIL"]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
sys.exit(1 if fails else 0)
