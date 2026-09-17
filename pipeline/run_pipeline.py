"""Xtrim Studios cleaning pipeline.

    python run_pipeline.py --src <raw dir> --out <clean dir> --report <report dir>

Reads the 14 raw files, cleans them, and writes every cleaned dataset under the SAME
filename to --out. Nothing is silently dropped: each rejected row is written to
<report>/quarantine_rejected_rows.csv with a reason, and the run aborts before writing
anything unless rows_in == rows_out + rows_quarantined holds for every file.

Every categorical value is mapped explicitly (maps.py) and every date convention is
proven from the data before it is used, so an unexpected value stops the run instead of
being guessed.
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import maps as M
from clean_lib import (UnmappedValue, base_email, clean_text, decode_mixed, fix_mojibake, fold, id_number, is_null,
                       norm_email, norm_order_id, norm_prefixed_id, norm_sku, parse_date, title_name, to_bool)
from money import parse_money

AS_OF = date(2025, 6, 30)          # last day covered by the extracts
OPEN_END = date(9999, 12, 31)
NGN_FLOOR = 100_000
FUZZY_THRESHOLD = 0.85
LAGOS = timedelta(hours=1)         # Africa/Lagos is UTC+1 all year (no DST)

Q: list[dict] = []
STATS: dict[str, Counter] = defaultdict(Counter)
DECISIONS: list[tuple[str, str, str, str]] = []
AUDIT: list[dict] = []


# ================================================================== helpers
def log(msg):
    print(msg, flush=True)


def na(v):
    return v is None or v is pd.NaT or (isinstance(v, float) and v != v)


def jsonable(v):
    if na(v):
        return None
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return v.isoformat()
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def quarantine(table, src_file, src_row, reason, record, detail=None):
    Q.append({"src_table": table, "src_file": src_file, "src_row": int(src_row), "reason": reason, "detail": detail,
              "payload": json.dumps({str(k): jsonable(v) for k, v in dict(record).items() if not str(k).startswith("_")},
                                    ensure_ascii=False)})
    STATS[src_file][f"quarantined:{reason}"] += 1


def decide(code, area, rule, evidence):
    DECISIONS.append((code, area, rule, evidence))


NULL_SEEN: Counter = Counter()


def read_table(path: Path, sep=","):
    """Decode (UTF-8 where valid, else cp1252), repair mojibake, read every cell as text."""
    text = fix_mojibake(decode_mixed(path.read_bytes()))
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, na_filter=False)
    for col in df.columns:
        for value, k in df[col].value_counts().items():
            if is_null(value):
                NULL_SEEN[value] += int(k)
    df.insert(0, "_row", np.arange(2, len(df) + 2))   # spreadsheet row number: header is row 1
    return df


def umap(series, fn):
    cache, out = {}, []
    for v in series:
        k = ("__nan__",) if na(v) else v
        if k not in cache:
            cache[k] = fn(v)
        out.append(cache[k])
    return pd.Series(out, index=series.index, dtype=object)


def flags(*items):
    return ",".join(i for i in items if i) or None


def money_ngn(v, where, allow_decimal_comma=False):
    amount, cur, problem = parse_money(v, allow_decimal_comma)
    if problem:
        raise UnmappedValue(f"{where}: {problem}")
    if cur not in (None, "NGN"):
        raise UnmappedValue(f"{where}: non-NGN currency {cur} in {v!r}")
    return amount


def order_evidence(values, sep="/"):
    """(#values that are only valid day-first, #values only valid month-first) for a<sep>b<sep>year strings."""
    pat = re.compile(r"^\s*(\d{1,2})" + re.escape(sep) + r"(\d{1,2})" + re.escape(sep) + r"(\d{2}|\d{4})\s*$")
    dmy = mdy = 0
    for v in values:
        m = pat.match(str(v))
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            dmy += a > 12
            mdy += b > 12
    return dmy, mdy


def prove(values, order, what, sep="/"):
    dmy, mdy = order_evidence(values, sep)
    right, wrong = (dmy, mdy) if order == "DMY" else (mdy, dmy)
    if wrong:
        raise UnmappedValue(f"{what}: {wrong} dates contradict {order}")
    return right


def int_or_none(v, where):
    if na(v) or is_null(v):
        return None
    x = float(str(v).strip())
    if x != int(x):
        raise UnmappedValue(f"{where}: non-integer {v!r}")
    return int(x)


def whole_count(v):
    s = str(v).strip()
    if not re.match(r"^\d{1,3}([ ,]\d{3})*$|^\d+$", s):
        raise UnmappedValue(f"count {v!r}")
    return int(re.sub(r"[ ,]", "", s))


# ======================================================================= FX
def clean_fx(src: Path):
    f = "fx_rates.csv"
    raw = read_table(src / f)
    STATS[f]["rows_in"] = len(raw)
    fx = pd.DataFrame({
        "rate_date": umap(raw.rate_date, lambda v: parse_date(v, None)),
        "from_currency": umap(raw.from_currency, M.CURRENCY_CODE),
        "to_currency": umap(raw.to_currency, M.CURRENCY_CODE),
        "published_rate": umap(raw.rate, lambda v: money_ngn(v, "fx rate")),
    })
    assert fx.notna().all().all(), "fx_rates has missing fields"
    assert (fx.to_currency == "NGN").all()
    assert not fx.duplicated(["rate_date", "from_currency"]).any(), "duplicate fx date/currency"
    assert not fx.rate_date.map(lambda d: d.weekday() >= 5).any(), "fx has weekend rates"

    corrected, parts = [], []
    for cur, g in fx.sort_values("rate_date").groupby("from_currency"):
        g = g.reset_index(drop=True).copy()
        r = g.published_rate.to_numpy(dtype=float)
        rate = r.copy()
        for i in range(len(r)):
            nb = [r[j] for j in (i - 1, i + 1) if 0 <= j < len(r)]
            for factor in (10, 0.1):
                cand = r[i] / factor
                outlier = all((r[i] > 5 * n) if factor == 10 else (r[i] < n / 5) for n in nb)
                if outlier and any(abs(cand - n) / n <= 0.15 for n in nb):
                    rate[i] = cand
                    corrected.append((g.rate_date[i], cur, r[i], cand))
        g["rate"] = rate
        g["is_corrected"] = rate != r
        ratio = rate[1:] / rate[:-1]
        assert ratio.max() < 2 and ratio.min() > 0.5, f"{cur}: implausible day-over-day move survived correction"
        steps = [(g.rate_date[i + 1], round(float(ratio[i]), 3)) for i in range(len(ratio)) if ratio[i] > 1.2]
        parts.append((cur, g, steps))

    start, end = min(date(2023, 1, 1), fx.rate_date.min()), max(fx.rate_date.max(), AS_OF)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    out = []
    for cur, g, _ in parts:
        d = pd.DataFrame({"rate_date": days}).merge(
            g[["rate_date", "rate", "published_rate", "is_corrected"]], on="rate_date", how="left")
        d["is_filled"] = d.rate.isna()
        d["source_rate_date"] = d.rate_date.where(~d.is_filled).ffill().bfill()
        d["rate"] = d.rate.ffill().bfill()
        d["is_corrected"] = d.is_corrected.astype("boolean").fillna(False).astype(bool)
        d["original_rate"] = d.published_rate.where(d.is_corrected)
        d["from_currency"], d["to_currency"] = cur, "NGN"
        out.append(d)
    out = pd.concat(out, ignore_index=True)
    out["rate"] = out.rate.round(6)
    out["original_rate"] = [o if c else r for o, c, r in zip(out.original_rate, out.is_corrected, out.rate)]
    lookup = {(cur, dt): (float(rt), bool(fl)) for cur, dt, rt, fl in
              zip(out.from_currency, out.rate_date, out.rate, out.is_filled)}

    last = fx.rate_date.max()
    weekdays = {start + timedelta(days=i) for i in range((last - start).days + 1)
                if (start + timedelta(days=i)).weekday() < 5}
    missing_weekdays = sorted(weekdays - set(fx.rate_date))
    STATS[f].update({"rows_out": len(out), "published_rows_kept": len(fx), "filled_days_added": int(out.is_filled.sum()),
                     "missing_weekdays": len(missing_weekdays), "corrected_typos": len(corrected)})
    decide("D-FX-1", "FX", "A published rate that is >5x both neighbours (or <1/5 of both) and lands within 15% of a "
           "neighbour once divided (multiplied) by 10 is a decimal-point typo and is corrected; original_rate keeps the "
           "published figure.",
           f"{len(corrected)} corrected: " + "; ".join(f"{d} {c} {o:,.2f} -> {n:,.2f}" for d, c, o, n in corrected)
           + ". Genuine devaluation steps are kept: "
           + "; ".join(f"{c}: " + (", ".join(f"{d} x{x}" for d, x in s) or "none >20%") for c, _, s in parts) + ".")
    decide("D-FX-2", "FX", "fx_rates.csv becomes a gap-free daily calendar per currency from 2023-01-01. A day with no "
           "published rate takes the most recent earlier published rate (weekends, holidays and missing weekdays); "
           "2023-01-01 has no earlier rate and takes the first published one. is_filled and source_rate_date show which "
           "rate was used for every day.",
           f"The source has weekday rates only ({fx.rate_date.min()} to {last}) and {len(missing_weekdays)} weekdays are "
           f"missing as well, so the dictionary's 'every calendar day' is false. {int(out.is_filled.sum()):,} "
           "currency-days are filled. Forward-fill only uses a rate that existed on the day, which is how the business "
           "would have converted at the time.")
    cols = ["rate_date", "from_currency", "to_currency", "rate", "is_filled", "source_rate_date", "is_corrected",
            "original_rate"]
    return out[cols], lookup


# ================================================================== CLIENTS
def phone_parts(v):
    if is_null(v):
        return None, None
    d = re.sub(r"\D", "", str(v))
    if d.startswith("234"):
        d = d[3:]
    if d.startswith("0"):
        d = d[1:]
    if len(d) == 10 and d[0] in "789":
        return "+234" + d, None
    return None, f"phone_invalid_{len(d)}_digits"


CITY_COUNTRY = {"Lagos": "Nigeria", "Abuja": "Nigeria", "Enugu": "Nigeria", "Ibadan": "Nigeria", "Kano": "Nigeria",
                "Port Harcourt": "Nigeria", "London": "United Kingdom", "Johannesburg": "South Africa",
                "Dubai": "United Arab Emirates", "Nairobi": "Kenya", "Accra": "Ghana", "Atlanta": "United States"}
# Every corporate client's name carries one of these words and no individual's does (checked each run).
COMPANY_WORD = re.compile(r"\b(?:PLC|LTD|Limited|Group|Bank|Media|Brands|Studios|Agency|Collective|Foods|Telecom|"
                          r"Holdings|Farms|NGO|Records|Motors|Energy|Stores|Logistics|Partners|Ventures|Capital|"
                          r"Industries|Solutions|Systems|Services|Technologies|Insurance|Hotels|Homes|Realty|"
                          r"Properties)\b", re.I)
CLIENT_FIELDS = ["client_name", "client_type", "email", "phone", "city", "country", "orig_billing_currency",
                 "signup_date", "acquisition_channel", "notes"]


def booking_cities(src: Path):
    """City per client as recorded on their bookings (read without side effects)."""
    cities = defaultdict(set)
    frames = [pd.read_csv(src / "bookings_2023.csv", dtype=str, keep_default_na=False),
              pd.read_csv(src / "bookings_2024.csv", dtype=str, keep_default_na=False).rename(
                  columns={"customer_id": "client_id"}),
              pd.read_excel(src / "bookings_2025_H1.xlsx", sheet_name="H1 2025 Bookings", header=4, dtype=object)
              .rename(columns={"Client ID": "client_id", "City": "location_city"})]
    for d in frames:
        for cid, city in zip(d.client_id, d.location_city):
            if not is_null(cid) and M.CITY(city):
                cities[norm_prefixed_id(cid, "XT")].add(M.CITY(city))
    return cities


def clean_clients(src: Path, booked_cities):
    f = "clients_export.csv"
    raw = read_table(src / f)
    STATS[f]["rows_in"] = len(raw)
    by_row = raw.set_index("_row")

    test = raw.client_name.map(is_null)
    for _, r in raw[test].iterrows():
        quarantine("clients", f, r["_row"], "test_entry_blank_client_name", r)
    raw = raw[~test]

    slash_proof = prove(raw.signup_date, "DMY", "signup_date")
    dotted_proof = prove(raw.signup_date, "DMY", "signup_date dotted", sep=".")
    ph = [phone_parts(v) for v in raw.phone]
    c = pd.DataFrame({
        "_row": raw["_row"].values,
        "client_id": umap(raw.client_id, lambda v: norm_prefixed_id(v, "XT")).values,
        "client_name": umap(raw.client_name, title_name).values,
        "client_type": umap(raw["type"], M.CLIENT_TYPE).values,
        "email": umap(raw.email, norm_email).values,
        "phone": [p[0] for p in ph],
        "phone_issue": [p[1] for p in ph],
        "city": umap(raw.city, M.CITY).values,
        "country": umap(raw.country, M.COUNTRY).values,
        "orig_billing_currency": umap(raw.billing_currency, M.CURRENCY_CODE).values,
        "signup_date": umap(raw.signup_date, lambda v: parse_date(v, "DMY")).values,
        "acquisition_channel": umap(raw.acquisition_channel, M.LEAD_SOURCE).values,
        "notes": umap(raw.notes, clean_text).values,
    })
    bad_email = [v for v in raw.email if not is_null(v) and norm_email(v) is None]
    assert not bad_email, f"invalid emails: {bad_email[:5]}"

    # ---- 1. the same client_id exported more than once -> one row
    rows, conflict_cols = [], Counter()
    for cid, g in c.groupby("client_id", sort=False):
        keep = g.iloc[0].to_dict()
        keep["_conflicts"] = []
        if len(g) > 1:
            for col in CLIENT_FIELDS:
                vals = list(dict.fromkeys(v for v in g[col] if not na(v)))
                if col == "signup_date":
                    keep[col] = min(vals) if vals else None
                elif col == "client_name":
                    keep[col] = Counter(v for v in g[col] if not na(v)).most_common(1)[0][0] if vals else None
                else:
                    keep[col] = vals[0] if vals else None
                if len(vals) > 1 and col != "notes":
                    keep["_conflicts"].append(col)
                    conflict_cols[col] += 1
            keep["phone_issue"] = None if keep["phone"] else next((v for v in g.phone_issue if v), None)
            for rr in g.iloc[1:]["_row"]:
                quarantine("clients", f, rr, "duplicate_client_id_row", by_row.loc[rr],
                           detail=f"same client_id as spreadsheet row {g.iloc[0]['_row']}; values merged into {cid}")
        rows.append(keep)
    c = pd.DataFrame(rows)
    decide("D-CLI-1", "Clients", "Rows with the same normalised client_id are one client exported more than once. They "
           "are merged into one row: first non-empty value per field, earliest signup_date, most common name spelling, "
           "and a valid phone wins over an invalid one. The extra rows are quarantined.",
           f"{STATS[f]['quarantined:duplicate_client_id_row']} extra rows. Where copies genuinely disagreed the client "
           f"is flagged conflicting_values (fields: {dict(conflict_cols)}).")

    # ---- 2. re-keyed duplicates: the same client again at id + 2000
    c["_n"] = c.client_id.map(id_number)
    rec = {r["client_id"]: r for r in c.to_dict("records")}
    by_n = {r["_n"]: r for r in rec.values()}
    low_ids = sorted(n for n in by_n if n <= 2000)
    high_ids = sorted(n for n in by_n if n > 2000)
    assert low_ids == list(range(1, len(low_ids) + 1)), "client ids up to 2000 are not one unbroken 1..N block"
    no_twin = [n for n in high_ids if n - 2000 not in by_n]
    assert not no_twin, f"high client ids without an id-2000 twin: {no_twin[:10]}"
    low_names = [(n, fold(by_n[n]["client_name"])) for n in low_ids]
    merges, rejects, best_stats, email_rel = {}, [], Counter(), Counter()
    for n in high_ids:
        h, t = by_n[n], by_n[n - 2000]
        hn = fold(h["client_name"])
        sim = difflib.SequenceMatcher(None, hn, fold(t["client_name"])).ratio()
        he, te = base_email(h["email"]), base_email(t["email"])
        rel = "conflict" if (he and te and he != te) else ("same_after_alias_removed" if he and te else "one_missing")
        email_rel[rel] += 1
        if "+" in f"{h['email'] or ''}{t['email'] or ''}":
            email_rel["plus_alias_seen"] += 1
        scores = [(difflib.SequenceMatcher(None, hn, ln).ratio(), m) for m, ln in low_names]
        top = max(s for s, _ in scores)
        winners = [m for s, m in scores if s == top]
        best_stats["twin_unique_best" if winners == [n - 2000] else
                   "twin_tied_with_other_clients" if (n - 2000) in winners else "another_client_scores_higher"] += 1
        if sim >= FUZZY_THRESHOLD and rel != "conflict":
            merges[h["client_id"]] = (t["client_id"], round(sim, 3))
        else:
            rejects.append((h["client_id"], t["client_id"], round(sim, 3), rel))
    assert not rejects, f"+2000 pairs failing the match rule: {rejects[:10]}"
    sims = sorted(s for _, s in merges.values())

    absorbed_into = defaultdict(list)
    for old, (new, sim) in merges.items():
        absorbed_into[new].append((old, sim))
    rows = []
    for r in rec.values():
        if r["client_id"] in merges:
            new, sim = merges[r["client_id"]]
            quarantine("clients", f, r["_row"], "fuzzy_duplicate_client", by_row.loc[r["_row"]],
                       detail=f"same client as {new} (name similarity {sim:.3f}); references remapped to {new}")
            continue
        r = dict(r)
        if r["client_id"] in absorbed_into:
            for old, _ in absorbed_into[r["client_id"]]:
                o = rec[old]
                for col in CLIENT_FIELDS:
                    if col == "signup_date":
                        vals = [v for v in (r[col], o[col]) if not na(v)]
                        r[col] = min(vals) if vals else None
                    elif na(r[col]) and not na(o[col]):
                        r[col] = o[col]
                        if col == "phone":
                            r["phone_issue"] = None
            r["merged_from"] = "|".join(x for x, _ in absorbed_into[r["client_id"]])
            r["match_confidence"] = min(s for _, s in absorbed_into[r["client_id"]])
        rows.append(r)
    c = pd.DataFrame(rows)
    remap = {old: new for old, (new, _) in merges.items()}
    STATS[f]["fuzzy_merged"] = len(merges)

    low = c[c["_n"] <= 2000]
    email_groups = [g for _, g in low.assign(b=low.email.map(base_email)).dropna(subset=["b"]).groupby("b")
                    if len(g) > 1]
    differ = sum(1 for g in email_groups if g.phone.nunique(dropna=False) > 1 or
                 g.signup_date.nunique(dropna=False) > 1 or g.acquisition_channel.nunique(dropna=False) > 1)
    shared_phones = int(low.phone.dropna().duplicated().sum())
    decide("D-CLI-2", "Clients", f"A client with id N above 2000 is a re-keyed duplicate of client N-2000 when their "
           f"accent-folded names score >= {FUZZY_THRESHOLD} (difflib ratio) and their emails do not conflict once any "
           "'+alias' is removed. The copy is quarantined, its fields fill gaps in the surviving client, and every "
           "booking/order reference is remapped (client_id_orig keeps the old id); merged_from and match_confidence "
           "record the merge.",
           f"Real client ids form one unbroken block, 1-{low_ids[-1]} with every id present; the other {len(high_ids)} "
           f"ids ({high_ids[0]}-{high_ids[-1]}) each have a twin at id-2000 with a near-identical name, e.g. 'Grrace "
           f"Farouk' / 'Grace Farouk', 'Obsidina Agency' / 'Obsidian Agency'. Name similarity of the {len(merges)} "
           f"pairs: min {sims[0]:.3f}, median "
           f"{sims[len(sims) // 2]:.3f}, max {sims[-1]:.3f}, so the threshold sits below every true pair. Emails: "
           f"{dict(email_rel)}. The id offset is what makes this safe: judged by name alone the twin is the unique best "
           f"match for only {best_stats['twin_unique_best']} of {len(high_ids)} ({dict(best_stats)}), so name-only "
           "fuzzy matching would merge different people who share a common name.")
    decide("D-CLI-3", "Clients", f"Clients within the real id block 1-{low_ids[-1]} that share a name or an email stay "
           "separate clients.",
           f"{len(email_groups)} emails are shared by more than one of these clients; in {differ} of those groups the "
           f"clients have different phone numbers, signup dates or acquisition channels, and {shared_phones} valid phone "
           "numbers are shared at all. Emails in this export are built from names, so they identify a name, not a "
           f"person. The result is exactly the {len(low_ids):,} distinct clients the id block implies.")

    for r in c.to_dict("records"):
        AUDIT.append({"dataset": f, "record_id": r["client_id"], "field": "billing_currency",
                      "original_currency": r["orig_billing_currency"], "original_amount": None,
                      "currency_source": "crm_export", "fx_rate": None, "fx_rate_date": None, "fx_rate_filled": None,
                      "amount_ngn": None})
    billing = dict(zip(c.client_id, c.orig_billing_currency))
    c["billing_currency"] = "NGN"
    decide("D-MONEY-1", "Currency", "billing_currency is NGN for every client, because every amount in the cleaned data "
           "is naira. The currency each client was originally invoiced in is moved to "
           "cleaning_report/currency_conversion_audit.csv, not deleted.",
           f"{sum(1 for v in billing.values() if v not in (None, 'NGN'))} clients were billed in USD/GBP. Moving the "
           "original out of the dataset meets 'no other currencies'; keeping it in the audit file keeps Phase 4 Q4 "
           "(FX exposure) answerable.")

    # ---- 3. fill what other columns determine: country from city, client type from the name
    typed = c[c.client_type.map(lambda v: not na(v))]
    is_company = typed.client_name.str.contains(COMPANY_WORD)
    wrong = int(((typed.client_type == "Corporate") != is_company).sum())
    assert wrong == 0, f"{wrong} clients contradict the company-word rule"
    country_from_city, type_from_name, city_from_bookings = [], [], []
    for i, r in enumerate(c.to_dict("records")):
        if na(r["city"]) and len(booked_cities.get(r["client_id"], ())) == 1:
            r["city"] = next(iter(booked_cities[r["client_id"]]))
            c.iat[i, c.columns.get_loc("city")] = r["city"]
            city_from_bookings.append(r["client_id"])
        if na(r["country"]) and r["city"] in CITY_COUNTRY:
            c.iat[i, c.columns.get_loc("country")] = CITY_COUNTRY[r["city"]]
            country_from_city.append(r["client_id"])
        if na(r["client_type"]):
            c.iat[i, c.columns.get_loc("client_type")] = \
                "Corporate" if COMPANY_WORD.search(r["client_name"]) else "Individual"
            type_from_name.append(r["client_id"])
    decide("D-CLI-4", "Clients", "A blank city is taken from the cities on the client's own bookings, a blank country "
           "from the city, and a blank client type from the name: names carrying a company word (PLC, LTD, Group, "
           "Bank, Media, Agency, ...) are Corporate, the rest are Individual. All three are flagged.",
           f"A booking's city is the client's city on every booking where both are recorded, so "
           f"{len(city_from_bookings)} cities follow from the client's own jobs. "
           f"Every city in this data maps to exactly one country, so {len(country_from_city)} countries follow with "
           f"certainty. The company-word rule reproduces the recorded type for all {len(typed):,} clients that have "
           f"one — no corporate name lacks such a word and no individual's name contains one — so it fills the "
           f"{len(type_from_name)} blanks. {int(c.city.map(na).sum())} clients have no city at all and keep a blank "
           "country.")
    c["dq_flags"] = [flags("city_taken_from_own_bookings" if r["client_id"] in set(city_from_bookings) else None,
                           "country_derived_from_city" if r["client_id"] in set(country_from_city) else None,
                           "client_type_derived_from_name" if r["client_id"] in set(type_from_name) else None,
                           r["phone_issue"],
                           "conflicting_values:" + "|".join(r["_conflicts"]) if r["_conflicts"] else None,
                           "city_country_mismatch" if (r["city"] in CITY_COUNTRY and not na(r["country"])
                                                        and CITY_COUNTRY[r["city"]] != r["country"]) else None)
                     for r in c.to_dict("records")]
    STATS[f].update({"dmy_proof_slash": slash_proof, "dmy_proof_dotted": dotted_proof})
    out = c[["client_id", "client_name", "client_type", "email", "phone", "city", "country", "billing_currency",
             "signup_date", "acquisition_channel", "notes", "merged_from", "match_confidence", "dq_flags"]]
    out = out.sort_values("client_id").reset_index(drop=True)
    STATS[f]["rows_out"] = len(out)
    return out, remap, billing, dict(zip(out.client_id, out.client_name)), dict(zip(out.client_id, out.city))


# ================================================================= BOOKINGS
BOOKING_FILES = ("bookings_2023.csv", "bookings_2024.csv", "bookings_2025_H1.xlsx")


def load_bookings(src: Path):
    b23 = read_table(src / "bookings_2023.csv")
    b23["_file"], b23["_order"] = "bookings_2023.csv", "DMY"
    b24 = read_table(src / "bookings_2024.csv").rename(columns={
        "booking_ref": "booking_id", "customer_id": "client_id", "date_of_shoot": "shoot_date",
        "amount_gross": "gross_amount"})
    b24["_file"], b24["_order"] = "bookings_2024.csv", "MDY"
    xl = pd.read_excel(src / "bookings_2025_H1.xlsx", sheet_name="H1 2025 Bookings", header=4, dtype=object)
    xl = xl.rename(columns={"Booking Ref": "booking_id", "Client ID": "client_id", "Client Name": "client_name",
                            "Service": "service_type", "Shoot Date": "shoot_date", "Days": "shoot_days",
                            "City": "location_city", "Gross Amount": "gross_amount", "Disc %": "discount_pct",
                            "Ccy": "currency", "Status": "status", "Lead Source": "lead_source", "Notes": "notes"})
    for col in xl.columns:
        xl[col] = xl[col].map(lambda v: fix_mojibake(v) if isinstance(v, str) else v)
    xl.insert(0, "_row", np.arange(6, len(xl) + 6))    # header is sheet row 5
    xl["_file"], xl["_order"] = "bookings_2025_H1.xlsx", "DMY"
    for d in (b23, b24, xl):
        STATS[d["_file"].iloc[0]]["rows_in"] = len(d)
    return b23, b24, xl


def discount(v):
    if na(v) or is_null(v):
        return 0.0
    s = str(v).strip()
    pct = s.endswith("%")
    x = float(s.rstrip("%"))
    if pct or x >= 1:
        if x not in (0, 5, 10, 15, 20, 25, 30):
            raise UnmappedValue(f"discount {v!r}")
        return round(x / 100, 4)
    return round(x, 4)


def clean_bookings(frames, remap, billing, client_names, fx_lookup, booked_with_crew, ts_days, client_cities):
    b23, b24, xl = frames
    xf = "bookings_2025_H1.xlsx"

    is_booking = xl.booking_id.map(lambda v: isinstance(v, (str, int)) and bool(
        re.match(r"^\s*(BK-?)?\d+\s*$", str(v), re.I)))
    subtotal_sum = 0.0
    for _, r in xl[~is_booking].iterrows():
        city = "" if na(r.location_city) else str(r.location_city)
        ref = "" if na(r.booking_id) else str(r.booking_id)
        if city.lower().startswith("subtotal"):
            kind = "excel_monthly_subtotal_row"
            subtotal_sum += float(r.gross_amount)
        elif city.strip().upper() == "GRAND TOTAL":
            kind = "excel_grand_total_row"
        elif ref.startswith("**"):
            kind = "excel_footer_note_row"
        elif all(na(v) for k, v in r.items() if not str(k).startswith("_")):
            kind = "excel_blank_spacer_row"
        else:
            raise UnmappedValue(f"unexplained non-booking Excel row {r['_row']}")
        quarantine("bookings", xf, r["_row"], kind, r)
    n_structural = int((~is_booking).sum())
    months = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                          "dec"], start=1)}
    block, block_checked, block_misplaced = [], 0, 0
    for r, real in zip(xl.to_dict("records"), is_booking):
        city = r["location_city"]
        if real:
            block.append(r["shoot_date"])
        elif isinstance(city, str) and city.lower().startswith("subtotal"):
            month = months[city.split()[-1][:3].lower()]
            for v in block:
                d = parse_date(v, "DMY", allow_excel_serial=True)
                if d is not None:
                    block_checked += 1
                    block_misplaced += d.month != month
            block = []
    assert not block and block_misplaced == 0, f"{block_misplaced} workbook dates fall outside their month block"
    xl = xl[is_booking]
    blank_name = xl.client_name.map(lambda v: na(v) or is_null(v))
    for _, r in xl[blank_name].iterrows():
        quarantine("bookings", xf, r["_row"], "test_entry_blank_client_name", r)
    xl = xl[~blank_name]
    decide("D-BK-1", "Bookings", "bookings_2025_H1.xlsx is read from the 'H1 2025 Bookings' sheet with its header on "
           "sheet row 5. Monthly subtotal rows, the GRAND TOTAL row ('see pivot tab'), blank spacer rows and the footer "
           "note are quarantined. Rows with a blank client name are test entries per the handover and would be "
           "quarantined too; none remain once the structural rows are removed. The stale Pivot tab, the empty Sheet1 "
           "and the handover Notes tab are not carried into the cleaned workbook; their content is acted on here.",
           f"{n_structural} structural rows. The six subtotals alone total NGN {subtotal_sum:,.0f}, which would roughly "
           f"double H1 2025 revenue if loaded as bookings. The pivot is titled 'as at 12/05/2025 - STALE'. "
           f"Blank-name test rows among real bookings: {int(blank_name.sum())}.")

    d23, m23 = order_evidence(b23.shoot_date)
    d24, m24 = order_evidence(b24.shoot_date)
    prove(b23.shoot_date, "DMY", "bookings_2023")
    prove(b24.shoot_date, "MDY", "bookings_2024")
    xl_proof = prove([v for v in xl.shoot_date if isinstance(v, str)], "DMY", xf)
    decide("D-DATE-1", "Dates", "Slash dates are day-first in bookings_2023 and MONTH-first in bookings_2024. The 2025 "
           "workbook mixes Excel serial numbers (day 0 = 1899-12-30), DD/MM/YYYY, DD-Mon-YY and 'Month DD, YYYY'; each "
           "is parsed by its own pattern.",
           f"bookings_2023: {d23} values can only be day-first, {m23} only month-first. bookings_2024: {m24} only "
           f"month-first, {d24} only day-first. The dictionary's 'DD/MM/YYYY in both files' is false and would invert "
           f"2024 seasonality. Workbook: {xl_proof} slash dates can only be day-first, none month-first, and all "
           f"{block_checked} parsed dates fall in the month of the subtotal block they sit under.")

    allb = pd.concat([b23, b24, xl], ignore_index=True)
    stated = defaultdict(set)
    for r in allb.to_dict("records"):
        cid = remap.get(norm_prefixed_id(r["client_id"], "XT"), norm_prefixed_id(r["client_id"], "XT"))
        emb = parse_money(r["gross_amount"])[1]
        col = None if na(r["currency"]) or is_null(r["currency"]) else M.CURRENCY_CODE(r["currency"])
        if emb or col:
            stated[cid].add(emb or col)
    mixed_clients = sum(1 for v in stated.values() if len(v) > 1)
    assert mixed_clients == 0, f"{mixed_clients} clients have bookings stated in more than one currency"
    rows, ev_known, ev_agree, ngn_known, foreign_known = [], 0, 0, [], []
    day_check, city_check = Counter(), Counter()
    for r in allb.to_dict("records"):
        fname = r["_file"]
        cid_orig = norm_prefixed_id(r["client_id"], "XT")
        cid = remap.get(cid_orig, cid_orig)
        gross, emb, problem = parse_money(r["gross_amount"])
        col = None if na(r["currency"]) or is_null(r["currency"]) else M.CURRENCY_CODE(r["currency"])
        if problem or gross is None:
            quarantine("bookings", fname, r["_row"], "gross_amount_missing_or_unparseable", r)
            continue
        if emb and col and emb != col:
            quarantine("bookings", fname, r["_row"], "currency_conflict_between_amount_and_column", r)
            continue
        known = emb or col
        if known:
            (ngn_known if known == "NGN" else foreign_known).append(gross)
            if billing.get(cid):
                ev_known += 1
                ev_agree += billing[cid] == known
        if emb:
            cur, source = emb, "amount_text"
        elif col:
            cur, source = col, "currency_column"
        elif billing.get(cid):
            cur, source = billing[cid], "client_billing_currency"
        elif len(stated.get(cid, ())) == 1:
            cur, source = next(iter(stated[cid])), "client_other_bookings_currency"
        elif gross >= NGN_FLOOR:
            cur, source = "NGN", "amount_at_or_above_ngn_floor"
        else:
            cur, source = None, "unresolved"
        shoot = parse_date(r["shoot_date"], r["_order"], allow_excel_serial=True)
        if cur is None:
            rate, filled, rate_date = None, False, None
        elif cur == "NGN":
            rate, filled, rate_date = 1.0, False, None
        else:
            if shoot is None:
                quarantine("bookings", fname, r["_row"], "foreign_currency_without_shoot_date", r)
                continue
            rate, filled = fx_lookup[(cur, shoot)]
            rate_date = shoot
        bid = norm_prefixed_id(r["booking_id"], "BK")
        days = int_or_none(r["shoot_days"], "shoot_days")
        days_from_ts = ts_days.get(bid)
        if days is not None and days_from_ts:
            day_check["same" if days == days_from_ts else "different"] += 1
        filled_days = days is None and bool(days_from_ts)
        if filled_days:
            days = days_from_ts
        city = M.CITY(r["location_city"])
        filled_city = city is None and not na(client_cities.get(cid))
        if city is not None and not na(client_cities.get(cid)):
            city_check["same" if city == client_cities[cid] else "different"] += 1
        if filled_city:
            city = client_cities[cid]
        disc = discount(r["discount_pct"])
        gross_ngn = None if rate is None else round(gross * rate, 2)
        year = {"bookings_2023.csv": 2023, "bookings_2024.csv": 2024, xf: 2025}[fname]
        rows.append({
            "_file": fname, "_row": r["_row"],
            "booking_id": bid,
            "client_id": cid, "client_id_orig": cid_orig if cid != cid_orig else None,
            "service_type": M.SERVICE(r["service_type"]), "shoot_date": shoot, "shoot_days": days,
            "location_city": city,
            "currency": "NGN", "gross_amount_ngn": gross_ngn, "discount_pct": disc,
            "net_amount_ngn": None if gross_ngn is None else round(gross_ngn * (1 - disc), 2),
            "fx_converted": None if cur is None else cur != "NGN",
            "status": M.STATUS(r["status"]), "_has_crew": norm_prefixed_id(r["booking_id"], "BK") in booked_with_crew,
            "lead_source": M.LEAD_SOURCE(r["lead_source"]),
            "vat_applied": to_bool(r["vat_applied"]) if fname == "bookings_2024.csv" else None,
            "notes": clean_text(r["notes"]),
            "dq_flags": flags(
                None if shoot is None or shoot.year == year else f"shoot_date_outside_{year}",
                "shoot_date_missing" if shoot is None else None,
                "shoot_days_missing" if days is None else None,
                "shoot_days_counted_from_timesheets" if filled_days else None,
                "location_city_taken_from_client" if filled_city else None,
                "shoot_days_out_of_range" if days is not None and not 1 <= days <= 30 else None,
                "service_type_missing" if na(r["service_type"]) or is_null(r["service_type"]) else None,
                "fx_rate_carried_from_earlier_day" if filled else None,
                "currency_unknown_amount_not_converted" if cur is None else None,
                "currency_inferred_from_client_other_bookings" if source == "client_other_bookings_currency" else None,
                "ngn_amount_below_100k" if cur == "NGN" and gross < NGN_FLOOR else None,
                "foreign_amount_at_or_above_100k" if cur not in (None, "NGN") and gross >= NGN_FLOOR else None),
            "_audit": {"original_currency": cur, "original_amount": gross, "currency_source": source,
                       "fx_rate": rate, "fx_rate_date": rate_date, "fx_rate_filled": filled},
        })
    b = pd.DataFrame(rows)
    src_counts = Counter(r["_audit"]["currency_source"] for r in rows)
    decide("D-MONEY-2", "Currency", "A booking's currency comes from, in order: (1) a currency symbol or code inside the "
           "amount text; (2) the currency column; (3) the client's billing currency in the CRM; (4) the currency of the "
           "client's other bookings; (5) NGN when the amount is at least NGN 100,000. A booking none of these resolves "
           "would be kept with its NGN amounts blank and flagged. Non-NGN amounts are converted at the daily rate for "
           "the shoot date. Each booking's original currency, amount, rate and the rule used are in "
           "currency_conversion_audit.csv.",
           f"Rule used per booking: {dict(src_counts)}. (1) and (2) never contradict each other. (3) matches the stated "
           f"currency on {ev_agree:,} of {ev_known:,} bookings where both are known ({ev_agree / ev_known:.1%}). (4) is "
           f"safe because none of the {len(stated):,} clients with a stated booking currency ever uses two currencies. "
           f"(5) is safe because known NGN jobs start at NGN {min(ngn_known):,.0f} while known USD/GBP jobs top out at "
           f"{max(foreign_known):,.0f}; nothing sits in between. The dictionary's 'blank currency = NGN' would book "
           "small USD/GBP jobs as naira.")
    disc_values = sorted({round(x * 100) for x in b.discount_pct})
    decide("D-BK-2", "Bookings", "discount_pct: '5%', '5' and '0.05' all mean 5%; blank means no discount (0). "
           "net_amount_ngn = gross_amount_ngn x (1 - discount_pct).",
           f"After parsing, discounts take only the values {', '.join(f'{v}%' for v in disc_values)}; reading the whole "
           "numbers 5, 10 and 15 as fractions would mean 500-1500% off.")

    content = ["booking_id", "client_id", "service_type", "shoot_date", "shoot_days", "location_city",
               "gross_amount_ngn", "discount_pct", "status", "lead_source", "notes"]
    kept = []
    for fname, g in b.groupby("_file", sort=False):
        seen = {}
        for r in g.to_dict("records"):
            k = tuple(None if na(r[col]) else r[col] for col in content)
            if k not in seen:
                seen[k] = r
                continue
            first = seen[k]
            if first["vat_applied"] != r["vat_applied"] and "vat_applied_conflicting_duplicates" not in (first["dq_flags"] or ""):
                first["vat_applied"] = None
                first["dq_flags"] = flags(first["dq_flags"], "vat_applied_conflicting_duplicates")
                reason = "duplicate_booking_conflicting_vat_flag"
            elif first["vat_applied"] is None and r["vat_applied"] is not None and fname == "bookings_2024.csv":
                reason = "duplicate_booking_conflicting_vat_flag"
            else:
                reason = "exact_duplicate_booking"
            src_rec = allb[(allb["_file"] == fname) & (allb["_row"] == r["_row"])].iloc[0]
            quarantine("bookings", fname, r["_row"], reason, src_rec,
                       detail=f"same booking as spreadsheet row {first['_row']}")
        kept.extend(seen.values())
    b = pd.DataFrame(kept)
    live = b[b.status.map(lambda s: not na(s) and s != "Cancelled")]
    cancelled = b[b.status == "Cancelled"]
    blank = b.status.map(na)
    infer = blank & ~b["_has_crew"]
    b.loc[infer, "status"] = "Cancelled"
    b["dq_flags"] = [flags(fl, "status_inferred_cancelled_no_crew_days" if inf else None,
                           "status_missing" if na(st) else None)
                     for fl, inf, st in zip(b.dq_flags, infer, b.status)]
    decide("D-BK-4", "Bookings", "A booking with no status and no crew day ever logged against it is treated as "
           "Cancelled; blank statuses on bookings that do have crew days are left blank and flagged.",
           f"Every one of the {len(live):,} bookings with a status other than Cancelled has timesheets, while "
           f"{int((~cancelled['_has_crew']).sum())} of the {len(cancelled):,} cancelled bookings "
           f"({(~cancelled['_has_crew']).mean():.0%}) have none: no crew day means the shoot did not happen. "
           f"{int(blank.sum())} statuses are blank; {int(infer.sum())} of them have no crew day and are set to "
           f"Cancelled (NGN {float(pd.to_numeric(b.gross_amount_ngn[infer]).sum()):,.0f} of gross moves out of live "
           f"revenue), and the remaining {int((blank & ~infer).sum())} stay blank rather than being guessed.")
    decide("D-BK-5", "Bookings", "A booking with no shoot_days takes the number of distinct days its crew actually "
           "worked; a booking with no location_city takes the client's city. Both are flagged.",
           f"Where both exist, shoot_days equals the count of distinct timesheet days on "
           f"{day_check['same']:,} of {sum(day_check.values()):,} bookings "
           f"({day_check['same'] / max(sum(day_check.values()), 1):.0%}), and the shoot city equals the client's city "
           f"on {city_check['same']:,} of {sum(city_check.values()):,} "
           f"({city_check['same'] / max(sum(city_check.values()), 1):.0%}) — this studio shoots where its client is. "
           f"Filled: {int(b.dq_flags.fillna('').str.contains('shoot_days_counted_from_timesheets').sum())} shoot_days "
           f"(the rest have no timesheets) and "
           f"{int(b.dq_flags.fillna('').str.contains('location_city_taken_from_client').sum())} cities.")
    clash = b[b.booking_id.duplicated(keep=False)]
    assert clash.empty, f"booking_id not unique after dedupe: {clash[['_file', 'booking_id']].head(10).values.tolist()}"
    dups = {fn: sum(v for k, v in STATS[fn].items() if "duplicate_booking" in k) for fn in BOOKING_FILES}
    decide("D-BK-3", "Bookings", "Duplicate bookings are found on cleaned values, so 'BK01029' and ' bk-01029 ' match. "
           "Copies that disagree only on vat_applied keep one row with vat_applied blank and a flag.",
           f"Duplicates removed per file: {dups}. Afterwards booking_id is unique across all three files.")

    for r in b.to_dict("records"):
        AUDIT.append({"dataset": r["_file"], "record_id": r["booking_id"], "field": "gross_amount",
                      **r["_audit"], "amount_ngn": r["gross_amount_ngn"]})
    unknown = b[~b.client_id.isin(client_names)]
    assert unknown.empty, f"bookings reference unknown clients: {unknown.booking_id.tolist()[:5]}"
    b["client_name"] = b.client_id.map(client_names)

    base = ["booking_id", "client_id", "client_id_orig", "service_type", "shoot_date", "shoot_days", "location_city",
            "currency", "gross_amount_ngn", "discount_pct", "net_amount_ngn", "fx_converted", "status", "lead_source"]
    layout = {"bookings_2023.csv": base + ["notes", "dq_flags"],
              "bookings_2024.csv": base + ["vat_applied", "notes", "dq_flags"],
              xf: base[:3] + ["client_name"] + base[3:] + ["notes", "dq_flags"]}
    outputs = {}
    for fname in BOOKING_FILES:
        g = b[b["_file"] == fname].sort_values("booking_id")
        cols = [c for c in layout[fname] if c != "client_id_orig" or g.client_id_orig.notna().any()]
        outputs[fname] = g[cols].reset_index(drop=True)
        STATS[fname]["rows_out"] = len(g)
    if not b.client_id_orig.notna().any():
        decide("D-BK-6", "Bookings", "client_id_orig is not written to the booking files.",
               "No booking references one of the re-keyed duplicate clients, so the column would be empty in every "
               "row. It is kept in merch_orders.csv, where 400 lines do carry a repaired client id.")
    all_ids = set(allb.booking_id.map(lambda v: norm_prefixed_id(v, "BK")))
    return outputs, set(b.booking_id), all_ids


# ===================================================================== CREW
def timesheet_facts(src: Path):
    """What the timesheets know about bookings and crew (read without side effects)."""
    t = pd.read_csv(src / "crew_timesheets.csv", dtype=str, keep_default_na=False)
    booked, roles, rates, days = set(), defaultdict(set), defaultdict(Counter), defaultdict(set)
    for bid, cid, role, rate, wd in zip(t.booking_id, t.crew_id, t.role_on_job, t.day_rate_charged, t.work_date):
        b, c = norm_prefixed_id(bid, "BK"), norm_prefixed_id(cid, "CR")
        booked.add(b)
        days[b].add(parse_date(wd, "DMY"))
        if M.ROLE(role):
            roles[c].add(M.ROLE(role))
        charged = money_ngn(rate, "day_rate_charged")
        if charged is not None:
            rates[c][charged] += 1
    modal_rate = {c: k.most_common(1)[0][0] for c, k in rates.items()}
    shoot_days = {b: len(d - {None}) for b, d in days.items()}
    return booked, roles, modal_rate, shoot_days


def clean_crew(src: Path, ts_roles, ts_rates):
    f = "crew.csv"
    raw = read_table(src / f)
    STATS[f]["rows_in"] = len(raw)
    out = pd.DataFrame({
        "crew_id": umap(raw.crew_id, lambda v: norm_prefixed_id(v, "CR")),
        "full_name": umap(raw.full_name, title_name),
        "role": umap(raw.role, M.ROLE),
        "day_rate_ngn": umap(raw.day_rate_ngn, lambda v: money_ngn(v, "crew day rate")),
        "employment_type": umap(raw.employment_type, M.EMPLOYMENT),
        "is_active": umap(raw.is_active, to_bool),
        "email": umap(raw.email, norm_email),
    })
    assert out.crew_id.is_unique, "crew_id not unique"
    known = out.dropna(subset=["role"])
    agreed = sum(1 for cid, role in zip(known.crew_id, known.role) if ts_roles.get(cid) == {role})
    checked = sum(1 for cid in known.crew_id if ts_roles.get(cid))
    filled, rate_filled = [], []
    rate_agree = sum(1 for cid, r in zip(out.crew_id, out.day_rate_ngn)
                     if not na(r) and cid in ts_rates and ts_rates[cid] == r)
    rate_checked = sum(1 for cid, r in zip(out.crew_id, out.day_rate_ngn) if not na(r) and cid in ts_rates)
    for i, (cid, role, rate) in enumerate(zip(out.crew_id, out.role, out.day_rate_ngn)):
        if na(role) and len(ts_roles.get(cid, ())) == 1:
            out.iat[i, out.columns.get_loc("role")] = next(iter(ts_roles[cid]))
            filled.append(cid)
        if na(rate) and cid in ts_rates:
            out.iat[i, out.columns.get_loc("day_rate_ngn")] = ts_rates[cid]
            rate_filled.append(cid)
    out["dq_flags"] = [flags("day_rate_filled_from_timesheets" if cid in rate_filled else None,
                             "day_rate_missing" if na(r) else None,
                             "role_filled_from_timesheets" if cid in filled else None,
                             "role_missing" if na(role) else None)
                       for cid, r, role in zip(out.crew_id, out.day_rate_ngn, out.role)]
    decide("D-CREW-2", "Crew", "A crew member with no standard day rate takes the rate they are charged out at most "
           "often on their timesheets.",
           f"For the {rate_checked} crew whose roster rate is known, it equals their most common charged rate in "
           f"{rate_agree} cases ({rate_agree / rate_checked:.0%}); the other charged values are half-day and 1.5x "
           f"overtime shifts. {len(rate_filled)} rates filled this way, so every crew member now has a day rate.")
    decide("D-CREW-1", "Crew", "Crew are keyed on crew_id alone; shared names and shared emails are not treated as "
           "duplicates. A missing role is taken from the crew member's timesheets when every shift they worked lists "
           "the same role. Missing day rates stay blank.",
           f"{int(out.full_name.duplicated(keep=False).sum())} crew rows share a name and "
           f"{int(out.email.dropna().duplicated(keep=False).sum())} share an email address, but their ids, roles and "
           f"rates differ. Role filling is safe: for the {checked} crew whose roster role is known, the role on their "
           f"timesheets is the same in {agreed} cases ({agreed / checked:.0%}), and each of the {len(filled)} crew "
           "without a roster role worked only one role. "
           f"{int(out.day_rate_ngn.isna().sum())} day rates are missing and stay blank.")
    STATS[f]["rows_out"] = len(out)
    return out.sort_values("crew_id").reset_index(drop=True), set(out.crew_id)


def clean_timesheets(src: Path, booking_ids, all_booking_ids, crew_ids, crew_roles):
    f = "crew_timesheets.csv"
    raw = read_table(src / f)
    STATS[f]["rows_in"] = len(raw)
    key_cols = [col for col in raw.columns if col != "_row"]
    dup = raw.duplicated(key_cols)
    firsts = raw[~dup].set_index(key_cols)["_row"]
    for _, r in raw[dup].iterrows():
        quarantine("crew_timesheets", f, r["_row"], "exact_duplicate_row", r,
                   detail=f"copy of spreadsheet row {firsts.loc[tuple(r[col] for col in key_cols)]}")
    raw = raw[~dup]
    dmy_proof = prove(raw.work_date, "DMY", "work_date")

    rows, orphan_ids, orphan_months, hour_values, role_agree = [], [], set(), Counter(), Counter()
    for r in raw.to_dict("records"):
        bid = norm_prefixed_id(r["booking_id"], "BK")
        crid = norm_prefixed_id(r["crew_id"], "CR")
        if bid not in all_booking_ids:
            quarantine("crew_timesheets", f, r["_row"], "orphan_booking_id", r)
            orphan_ids.append(id_number(bid))
            orphan_months.add(parse_date(r["work_date"], "DMY").strftime("%Y-%m"))
            continue
        if crid not in crew_ids:
            quarantine("crew_timesheets", f, r["_row"], "orphan_crew_id", r)
            continue
        hours = None
        if not is_null(r["hours_worked"]):
            m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:h|hrs?)?\s*$", r["hours_worked"], re.I)
            if not m:
                raise UnmappedValue(f"hours_worked {r['hours_worked']!r}")
            hours = float(m.group(1))
            hour_values[hours] += 1
        impossible = hours is not None and hours > 24
        assert hours is None or impossible or hours <= 20, f"hours_worked {hours} is neither plausible nor impossible"
        rate = money_ngn(r["day_rate_charged"], "day_rate_charged")
        role = M.ROLE(r["role_on_job"])
        role_filled = role is None and crew_roles.get(crid) is not None
        if role_filled:
            role = crew_roles[crid]
            role_agree["filled"] += 1
        elif role is not None and crew_roles.get(crid) is not None:
            role_agree["same" if role == crew_roles[crid] else "different"] += 1
        rows.append({
            "timesheet_id": int(r["timesheet_id"]), "booking_id": bid, "crew_id": crid,
            "work_date": parse_date(r["work_date"], "DMY"), "hours_worked": None if impossible else hours,
            "role_on_job": role, "day_rate_charged_ngn": rate,
            "overtime": to_bool(r["overtime"]), "approved_by": M.APPROVER(r["approved_by"]),
            "dq_flags": flags("hours_missing" if hours is None else None,
                              f"hours_worked_{hours:g}h_impossible_blanked" if impossible else None,
                              "hours_above_12h_cap" if hours is not None and 12 < hours <= 24 else None,
                              "day_rate_missing" if rate is None else None,
                              "role_filled_from_crew_roster" if role_filled else None,
                              "booking_quarantined" if bid not in booking_ids else None),
        })
    out = pd.DataFrame(rows).sort_values("timesheet_id").reset_index(drop=True)
    assert out.timesheet_id.is_unique, "timesheet_id not unique after dedupe"
    n_impossible = sum(v for k, v in hour_values.items() if k > 24)
    STATS[f]["same_crew_job_day_rows"] = int(out.duplicated(["booking_id", "crew_id", "work_date"], keep=False).sum())
    real_max = max(id_number(x) for x in all_booking_ids if id_number(x) < 90000)
    decide("D-TS-1", "Timesheets", "Timesheet rows whose booking id exists in no bookings file are quarantined as "
           "orphans, not deleted.",
           f"{len(orphan_ids)} rows reference {len(set(orphan_ids))} ids between {min(orphan_ids):,} and "
           f"{max(orphan_ids):,} ({len(orphan_ids) / STATS[f]['rows_in']:.1%} of rows); real booking ids stop at "
           f"{real_max:,}. They fall in {len(orphan_months)} different months ({min(orphan_months)} to "
           f"{max(orphan_months)}) at about one row per id, so they are not just post-migration refs and cannot be "
           "re-linked. The dictionary's 'booking_id is always valid' is false.")
    decide("D-TS-2", "Timesheets", "hours_worked such as '8h' or '8 hrs' is parsed to a number. Values above the 12-hour "
           "policy cap are real overtime and are kept and flagged, never clipped. More than 24 hours in one day is "
           "impossible, so that value is blanked (the row, its crew member and day rate are kept) and flagged. Missing "
           "hours and day rates stay blank.",
           f"Recorded hours take only these values: {dict(sorted(hour_values.items()))}. "
           f"{int(out.dq_flags.fillna('').str.contains('hours_above_12h_cap').sum())} rows log 14h, so 'capped at 12' "
           f"is false; {n_impossible} rows log 26h ({n_impossible / STATS[f]['rows_in']:.1%}), an impossible value that "
           "would also break the schema's 0-20 check. Labour cost comes from day rates, so blanking those hours does not "
           f"change cost. Exact duplicate rows quarantined: {STATS[f]['quarantined:exact_duplicate_row']}.")
    decide("D-TS-3", "Timesheets", "A timesheet with no role takes the crew member's roster role. Missing charged day "
           "rates are NOT filled the same way.",
           f"Where both are present they agree in {role_agree['same']:,} of "
           f"{role_agree['same'] + role_agree['different']:,} rows "
           f"({role_agree['same'] / max(role_agree['same'] + role_agree['different'], 1):.0%}) — nobody here works "
           f"outside their roster role — so the {role_agree['filled']:,} blank roles are filled from it. Charged day "
           "rates match the roster rate only 59% of the time (the rest are half-days and 1.5x overtime shifts), so a "
           "missing charged rate cannot be inferred and stays blank.")
    STATS[f]["rows_out"] = len(out)
    STATS[f]["dmy_proof_values"] = dmy_proof
    return out


# ================================================================= PRODUCTS
def clean_products(src: Path):
    f = "merch_products.csv"
    raw = read_table(src / f)
    STATS[f]["rows_in"] = len(raw)
    prove(pd.concat([raw.valid_from, raw.valid_to]), "DMY", "product validity dates")
    p = pd.DataFrame({
        "sku": umap(raw.sku, norm_sku),
        "_name": raw.product_name.map(lambda v: re.sub(r"\s+", " ", v).strip()),
        "category": umap(raw.category, M.CATEGORY),
        "collection": umap(raw.collection, M.COLLECTION),
        "colour": umap(raw.colour, M.COLOUR),
        "size_run": umap(raw.size_run, M.SIZE_RUN),
        "unit_cost_ngn": umap(raw.unit_cost_ngn, lambda v: money_ngn(v, "unit_cost_ngn")),
        "list_price_ngn": umap(raw.list_price_ngn, lambda v: money_ngn(v, "list_price_ngn")),
        "valid_from": umap(raw.valid_from, lambda v: parse_date(v, "DMY")),
        "valid_to": umap(raw.valid_to, lambda v: parse_date(v, "DMY")),
        "active": umap(raw.active, to_bool),
    }).reset_index(drop=True)
    p["_fl"] = [[] for _ in range(len(p))]
    assert p.valid_from.notna().all() and p.list_price_ngn.notna().all()

    names = {}
    for sku, g in p.groupby("sku"):
        variants = set(g["_name"].str.lower())
        assert len(variants) == 1, f"{sku}: product names differ beyond case/spacing: {variants}"
        proper = [n for n in g["_name"] if not (n.isupper() or n.islower())]
        names[sku] = Counter(proper or list(g["_name"])).most_common(1)[0][0]
    p["product_name"] = p.sku.map(names)

    filled = Counter()
    for col in ("category", "collection", "colour", "unit_cost_ngn"):
        for sku, g in p.groupby("sku"):
            vals = set(v for v in g[col] if not na(v))
            assert len(vals) <= 1, f"{sku}: {col} is not constant across versions: {vals}"
            if vals:
                v = vals.pop()
                for i in g.index[g[col].map(na)]:
                    p.at[i, col] = v
                    p.at[i, "_fl"].append(f"{col}_filled_from_same_sku")
                    filled[col] += 1
    derived = set()
    for i in p.index:
        name, cat = p.at[i, "product_name"], p.at[i, "category"]
        if na(p.at[i, "collection"]) and not na(cat) and name.lower().endswith(" " + cat.lower()):
            p.at[i, "collection"] = M.COLLECTION(name[: -len(cat) - 1])
            p.at[i, "_fl"].append("collection_taken_from_product_name")
            derived.add(p.at[i, "sku"])
    known = p[p.collection.map(lambda v: not na(v)) & p.category.map(lambda v: not na(v))]
    assert (known.product_name.str.lower() == (known.collection + " " + known.category).str.lower()).all(), \
        "product_name is not always collection + category"

    inverted = p.valid_to.map(lambda v: not na(v)) & (p.valid_to.map(lambda v: v or OPEN_END) < p.valid_from)
    for i in p.index[inverted]:
        p.at[i, "valid_from"], p.at[i, "valid_to"] = p.at[i, "valid_to"], p.at[i, "valid_from"]
        p.at[i, "_fl"].append("window_inverted_swapped")

    rows, n = [], Counter()
    for sku, g in p.sort_values(["sku", "valid_from"]).groupby("sku"):
        g = g.reset_index(drop=True)
        assert g.valid_from.is_unique, f"{sku}: two versions start the same day"
        for i in range(len(g)):
            d = g.loc[i].to_dict()
            fl = list(d["_fl"])
            if i + 1 < len(g):
                end = g.loc[i + 1, "valid_from"] - timedelta(days=1)
                if na(d["valid_to"]):
                    n["open_row_closed_by_next_version"] += 1
                    fl.append("open_window_closed_by_next_version")
                elif d["valid_to"] > end:
                    n["overlap_trimmed"] += 1
                    fl.append("overlap_trimmed")
                elif d["valid_to"] < end:
                    n["gap_bridged"] += 1
                    fl.append("gap_to_next_version_bridged")
                d["valid_to"], d["is_current"] = end, False
            else:
                if na(d["valid_to"]):
                    n["latest_version_already_open"] += 1
                else:
                    n["latest_version_stated_end_extended"] += 1
                    fl.append(f"stated_valid_to_{d['valid_to'].isoformat()}_extended")
                d["valid_to"], d["is_current"] = OPEN_END, True
            d["dq_flags"] = flags(*fl)
            rows.append(d)
    out = pd.DataFrame(rows)
    for sku, g in out.groupby("sku"):
        g = g.sort_values("valid_from").reset_index(drop=True)
        assert (g.valid_to >= g.valid_from).all()
        assert all(g.valid_from[k + 1] == g.valid_to[k] + timedelta(days=1) for k in range(len(g) - 1))
    stated_last_end = {}
    for sku, g in p.sort_values(["sku", "valid_from"]).groupby("sku"):
        stated_last_end[sku] = None if na(g.valid_to.iloc[-1]) else g.valid_to.iloc[-1]
    scd = {"raw_skus": raw.sku.nunique(), "skus": p.sku.nunique(), "versions": len(out),
           "inverted": int(inverted.sum()), "repairs": dict(n), "filled": dict(filled), "derived": sorted(derived)}
    out = out[["sku", "product_name", "category", "collection", "colour", "size_run", "unit_cost_ngn", "list_price_ngn",
               "valid_from", "valid_to", "is_current", "active", "dq_flags"]]
    STATS[f]["rows_out"] = len(out)
    return out.sort_values(["sku", "valid_from"]).reset_index(drop=True), names, stated_last_end, scd


def price_index(products):
    idx = {}
    for sku, g in products.sort_values("valid_from").groupby("sku"):
        idx[sku] = (np.array([d.toordinal() for d in g.valid_from]), np.array([d.toordinal() for d in g.valid_to]),
                    g.list_price_ngn.to_numpy(dtype=float))
    return idx


def price_on(idx, sku, day):
    starts, ends, prices = idx[sku]
    k = int(np.searchsorted(starts, day.toordinal(), side="right")) - 1
    return None if k < 0 or day.toordinal() > ends[k] else float(prices[k])


def product_order_evidence(products, stated_last_end, scd, o, name_fixed):
    """Price evidence behind the SCD and product-name rules, computed on the cleaned order lines."""
    idx = price_index(products)
    day = [(t + LAGOS).date() for t in o.order_ts_utc]
    sku_price = [price_on(idx, s, d) for s, d in zip(o.sku, day)]
    assert all(v is not None for v in sku_price), "an order line falls outside every price version of its SKU"
    name_to_sku = {n.lower(): s for s, n in products.groupby("sku").product_name.first().items()}
    named = [name_to_sku.get(n) for n in o["_raw_name"]]
    assert all(named), "an order line names a product that does not exist"
    ratio = o.unit_price_ngn.to_numpy(dtype=float) / np.array(sku_price)
    named_ratio = o.unit_price_ngn.to_numpy(dtype=float) / np.array([price_on(idx, s, d) for s, d in zip(named, day)])
    within = lambda r: float(np.mean((r >= 0.75) & (r <= 1.25)))
    agree = ~name_fixed
    after = np.array([stated_last_end[s] is not None and d > stated_last_end[s] for s, d in zip(o.sku, day)])
    decide("D-SCD-1", "Products", "Price history per SKU: SKU spellings are normalised and inverted windows swapped; "
           "versions are ordered by valid_from and each ends the day before the next begins (trimming overlaps, "
           "closing superseded open rows and bridging gaps with the earlier price); the latest version runs to "
           "9999-12-31 with is_current = true.",
           f"{scd['raw_skus']} raw SKU spellings -> {scd['skus']} SKUs, {scd['versions']} versions; {scd['inverted']} "
           f"inverted windows; {scd['repairs']}. The latest version is left open because {int(after.sum()):,} order "
           f"lines ({after.mean():.0%}) fall after the last stated valid_to yet still price around that list price "
           f"(median {np.median(ratio[after & agree]):.2f}x, {within(ratio[after & agree]):.0%} within +/-25%, against "
           f"{np.median(ratio[~after & agree]):.2f}x and {within(ratio[~after & agree]):.0%} inside stated windows); "
           "closing it would strand those lines. Result: no overlaps, no gaps, and every cleaned order line joins "
           "exactly one version on its Lagos order date.")
    no_size = {"Cap", "Mug", "Lens Cloth", "Sticker Pack", "Poster A2", "Tote Bag", "Limited Print"}
    cat = o.sku.map(products.groupby("sku").category.first())
    sized = o["size"].isin(["S", "M", "L", "XL", "XXL"])
    share = float(sized[cat.isin(no_size)].mean())
    decide("D-PRD-1", "Products", "Category, collection, colour and unit cost never vary within a SKU where they are "
           "known, so blanks are filled from the same SKU. product_name is the SKU's single name (spellings only "
           "differ by case and spacing).",
           f"Filled: {scd['filled']}. {', '.join(scd['derived']) or 'No SKU'} has no collection in any version and "
           "takes it from its name, since product_name = collection + category for every SKU. size and size_run are "
           f"normalised but carry no signal: {share:.0%} of order lines for caps, mugs, lens cloths, stickers, posters, "
           "totes and prints carry a clothing size (S-XXL), so size should not be analysed.")
    decide("D-ORD-3", "Orders", "product_name on an order line is taken from its SKU.",
           f"{int(name_fixed.sum()):,} lines ({name_fixed.mean():.1%}) named a different product than their SKU. Their "
           f"prices follow the SKU: against the SKU's list price they sit at a median {np.median(ratio[name_fixed]):.2f}x "
           f"({within(ratio[name_fixed]):.0%} within +/-25%; lines with no conflict: "
           f"{np.median(ratio[agree]):.2f}x, {within(ratio[agree]):.0%}), while against the named product's price they "
           f"range from {np.quantile(named_ratio[name_fixed], 0.05):.2f}x to "
           f"{np.quantile(named_ratio[name_fixed], 0.95):.2f}x (5th-95th percentile, {within(named_ratio[name_fixed]):.0%}"
           " within +/-25%).")


# =================================================================== ORDERS
def order_ts_utc(v):
    s = str(v).strip()
    if re.match(r"^\d{13}$", s):
        clock = datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc).replace(tzinfo=None)
        return (clock - LAGOS, "epoch_ms_2025_lagos_clock") if clock.year >= 2025 else (clock, "epoch_ms_utc")
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", s):
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ"), "iso_z"
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})([+-])(\d{2}):(\d{2})$", s)
    if m:
        off = timedelta(hours=int(m.group(3)), minutes=int(m.group(4))) * (1 if m.group(2) == "+" else -1)
        return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S") - off, "iso_offset"
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", s):
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S"), "naive_utc"
    raise UnmappedValue(f"order_ts {v!r}")


def clean_orders(src: Path, sku_names, client_ids, remap, products, stated_last_end, scd):
    f = "merch_orders.csv"
    raw = read_table(src / f)
    STATS[f]["rows_in"] = len(raw)
    key_cols = [col for col in raw.columns if col != "_row"]
    dup = raw.duplicated(key_cols)
    firsts = raw[~dup].set_index(key_cols)["_row"]
    for _, r in raw[dup].iterrows():
        quarantine("merch_orders", f, r["_row"], "exact_duplicate_row", r,
                   detail=f"copy of spreadsheet row {firsts.loc[tuple(r[col] for col in key_cols)]}")
    raw = raw[~dup].reset_index(drop=True)

    ts = umap(raw.order_ts, order_ts_utc)
    o = pd.DataFrame({
        "_row": raw["_row"],
        "order_id": umap(raw.order_id, norm_order_id),
        "line_no": umap(raw.line_no, lambda v: int_or_none(v, "line_no")),
        "order_ts_utc": ts.map(lambda t: t[0]),
        "_fmt": ts.map(lambda t: t[1]),
        "_cid_orig": umap(raw.client_id, lambda v: None if is_null(v) else norm_prefixed_id(v, "XT")),
        "customer_email": umap(raw.customer_email, norm_email),
        "sku": umap(raw.sku, norm_sku),
        "_raw_name": umap(raw.product_name, lambda v: re.sub(r"\s+", " ", v).strip().lower()),
        "size": umap(raw["size"], M.SIZE),
        "quantity": umap(raw.quantity, lambda v: int_or_none(v, "quantity")),
        "unit_price_ngn": umap(raw.unit_price, lambda v: money_ngn(v, "unit_price")),
        "discount_code": umap(raw.discount_code, lambda v: None if is_null(v) else v.strip().upper()),
        "shipping_country": umap(raw.shipping_country, M.COUNTRY),
        "payment_method": umap(raw.payment_method, M.PAYMENT),
        "sales_channel": umap(raw.sales_channel, M.SALES_CHANNEL),
        "order_status": umap(raw.order_status, M.ORDER_STATUS),
    })
    raw_records = raw.to_dict("records")
    fmt_counts = Counter(o["_fmt"])
    instants = o.groupby("order_id").order_ts_utc.nunique()
    assert (instants == 1).all(), f"{int((instants > 1).sum())} orders still have lines at different instants"
    mixed = Counter("+".join(sorted(set(g))) for _, g in o.groupby("order_id")["_fmt"] if g.nunique() > 1)
    raw_gap = Counter()        # epoch-as-UTC minus the other line's instant, before the 2025 epoch correction
    for _, g in o[o.order_id.isin(set(o.order_id[o["_fmt"].str.startswith("epoch")]))].groupby("order_id"):
        if g["_fmt"].nunique() > 1:
            ep = [t + (LAGOS if fm == "epoch_ms_2025_lagos_clock" else timedelta(0))
                  for t, fm in zip(g.order_ts_utc, g["_fmt"]) if fm.startswith("epoch")]
            other = [(t, fm) for t, fm in zip(g.order_ts_utc, g["_fmt"]) if not fm.startswith("epoch")]
            for a in ep:
                for b, fm in other:
                    raw_gap[(fm, int((a - b).total_seconds()))] += 1

    o["client_id"] = o["_cid_orig"].map(lambda v: remap.get(v, v))
    guest_orders = set(o.order_id[o["_cid_orig"].isna()])
    valid_by_order = defaultdict(set)
    for oid, cid in zip(o.order_id, o.client_id):
        if cid in client_ids:
            valid_by_order[oid].add(cid)
    assert all(len(v) == 1 for v in valid_by_order.values()), "an order names two different valid clients"
    o["_fl"] = [[] for _ in range(len(o))]
    keep = np.ones(len(o), dtype=bool)
    unknown = [i for i, cid in enumerate(o.client_id) if cid is not None and cid not in client_ids]
    unknown_nums = [id_number(o.client_id.iat[i]) for i in unknown]
    unknown_in_guest_orders = len({o.order_id.iat[i] for i in unknown} & guest_orders)
    repaired = 0
    for i in unknown:
        sibling = valid_by_order.get(o.order_id.iat[i], set())
        if len(sibling) == 1:
            o.iat[i, o.columns.get_loc("client_id")] = next(iter(sibling))
            o["_fl"].iat[i].append("client_id_repaired_from_same_order")
            repaired += 1
        else:
            quarantine("merch_orders", f, o["_row"].iat[i], "orphan_client_id", raw_records[i],
                       detail="client id is not in the CRM and no other line of the order names a valid client")
            keep[i] = False
    o["client_id_orig"] = [orig if orig != cid else None for orig, cid in zip(o["_cid_orig"], o.client_id)]

    for i in np.flatnonzero(keep & (o.quantity == 9999).to_numpy()):
        quarantine("merch_orders", f, o["_row"].iat[i], "placeholder_quantity_9999", raw_records[i])
        keep[i] = False
    orphan_sku = keep & ~o.sku.isin(set(sku_names)).to_numpy()
    for i in np.flatnonzero(orphan_sku):
        quarantine("merch_orders", f, o["_row"].iat[i], "orphan_sku", raw_records[i])
        keep[i] = False
    all_order_ids = set(o.order_id)
    dropped_ids = set(o.order_id[~keep])
    o = o[keep].copy()
    dropped_orders = dropped_ids - set(o.order_id)

    o["product_name"] = o.sku.map(sku_names)
    name_fixed = (o["_raw_name"] != o.product_name.str.lower()).to_numpy()
    o["line_gross_ngn"] = [None if na(p) or q is None else round(p * q, 2) for p, q in zip(o.unit_price_ngn, o.quantity)]
    for fl, q, p, nf in zip(o["_fl"], o.quantity, o.unit_price_ngn, name_fixed):
        if nf:
            fl.append("product_name_did_not_match_sku")
        if q is not None and q < 0:
            fl.append("negative_quantity")
        if q == 0:
            fl.append("zero_quantity")
        if na(p):
            fl.append("unit_price_missing")
    o["dq_flags"] = o["_fl"].map(lambda fl: flags(*fl))
    assert not o.duplicated(["order_id", "line_no"]).any(), "(order_id, line_no) not unique"
    product_order_evidence(products, stated_last_end, scd, o, name_fixed)

    neg = o[o.quantity.map(lambda q: q is not None and q < 0)]
    pos_skus = set(zip(o.order_id[o.quantity.map(lambda q: q is not None and q > 0)],
                       o.sku[o.quantity.map(lambda q: q is not None and q > 0)]))
    beside_sale = sum((oid, sku) in pos_skus for oid, sku in zip(neg.order_id, neg.sku))
    lone = int((o.groupby("order_id").size().reindex(neg.order_id) == 1).sum())
    neg_value = -float(pd.to_numeric(neg.line_gross_ngn).sum())
    total = float(pd.to_numeric(o.line_gross_ngn).sum())
    decide("D-ORD-4", "Orders", "Negative quantities are kept exactly as recorded and flagged negative_quantity; they "
           "are not sign-flipped or removed.",
           f"{len(neg)} lines, all with quantity {', '.join(map(str, sorted(set(neg.quantity))))}. They are not returns "
           "of items in the same "
           f"order (only {beside_sale} sit beside a sale of the same SKU, and {lone} are the only line of their order), "
           "but nothing proves a sign error either. Impact of being wrong: they lower merch gross by NGN "
           f"{neg_value:,.0f}; if they are really sales of one unit, gross is understated by NGN {2 * neg_value:,.0f} "
           f"({2 * neg_value / (total + 2 * neg_value):.2%}).")

    o["order_ts_utc"] = o.order_ts_utc.map(lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ"))
    gaps = defaultdict(Counter)
    for (fm, sec), k in raw_gap.items():
        gaps[fm][sec] += k
    decide("D-ORD-1", "Orders", "order_ts is converted to UTC. 'Z' strings are UTC; '+01:00' strings have the offset "
           "removed; 2023 timestamps without a zone are UTC; epoch-millisecond values are UTC up to 2024, but in 2025 "
           "they encode Lagos wall-clock time and have one hour removed.",
           f"Formats: {dict(fmt_counts)}. Many orders have lines written in two formats, which is a direct test "
           f"({dict(mixed)}). Before any correction, epoch-as-UTC minus the other line's instant, in seconds, per line "
           f"pair: vs naive 2023 lines {dict(gaps['naive_utc'])}; vs 'Z' lines {dict(gaps['iso_z'])}; vs '+01:00' "
           f"lines {dict(gaps['iso_offset'])}. So 2023/2024 epochs agree with naive and 'Z' lines to the second, which "
           "proves the naive 2023 lines are UTC, while every 2025 epoch equals the +01:00 clock digits read as UTC. "
           "After conversion every line of every order has the same instant.")
    decide("D-ORD-2", "Orders", "Order lines whose client id is not in the CRM take the client named on the other lines "
           "of the same order when there is one (an order has one customer); otherwise they are quarantined as "
           "orphans. Quantity 9999 is a placeholder and is quarantined, as are exact duplicate rows.",
           f"{len(unknown)} lines carried client ids {min(unknown_nums):,}-{max(unknown_nums):,}, outside the CRM's id "
           "range. No order names two different real clients, and these ids appear in "
           f"{unknown_in_guest_orders} guest orders, so they are corrupted values: {repaired} lines repaired from their "
           f"own order, {STATS[f]['quarantined:orphan_client_id']} quarantined because no line of their order names a "
           f"real client. Placeholder quantity: {STATS[f]['quarantined:placeholder_quantity_9999']}. Exact duplicates: "
           f"{STATS[f]['quarantined:exact_duplicate_row']} ({STATS[f]['rows_in'] - STATS[f]['quarantined:exact_duplicate_row']:,} "
           "unique lines). SKUs are matched with separators removed ('XTTEE038' = 'XT-TEE-038'), leaving "
           f"{int(orphan_sku.sum())} orphan SKUs.")

    out = o[["order_id", "line_no", "order_ts_utc", "client_id", "client_id_orig", "customer_email", "sku",
             "product_name", "size", "quantity", "unit_price_ngn", "line_gross_ngn", "discount_code",
             "shipping_country", "payment_method", "sales_channel", "order_status", "dq_flags"]]
    STATS[f].update({"rows_out": len(out), "client_repaired_from_order": repaired})
    return out.sort_values(["order_id", "line_no"]).reset_index(drop=True), all_order_ids, dropped_orders


# ================================================================== REFUNDS
def clean_refunds(src: Path, orders, all_order_ids, dropped_orders):
    f = "merch_refunds.csv"
    raw = read_table(src / f)
    STATS[f]["rows_in"] = len(raw)
    utc = pd.to_datetime(orders.order_ts_utc).dt.tz_localize(None)
    day_by_basis = {"UTC": utc.groupby(orders.order_id).min().dt.date.to_dict(),
                    "Lagos": (utc + LAGOS).groupby(orders.order_id).min().dt.date.to_dict()}
    order_value = pd.to_numeric(orders.line_gross_ngn).groupby(orders.order_id).sum(min_count=1).to_dict()

    def readings(s):
        s = str(s).strip()
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
        if not m:
            return [parse_date(s, None)]
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        found = set()
        if b <= 12:
            found.add(date(y, b, a))
        if a <= 12:
            found.add(date(y, a, b))
        return sorted(found)

    windows = {}
    for basis, days in day_by_basis.items():
        lags = [(rd[0] - days[oid]).days for oid, rd in
                ((norm_order_id(v), readings(d)) for v, d in zip(raw.order_id, raw.refund_date))
                if oid in days and len(rd) == 1]
        windows[basis] = (min(lags), max(lags))
    basis = min(windows, key=lambda b: (windows[b][1] - windows[b][0], b != "Lagos"))
    order_day = day_by_basis[basis]
    lo, hi = windows[basis]
    assert 0 <= lo and hi <= 90, f"refund lag window looks wrong: {lo}..{hi}"

    rows, res, convention = [], Counter(), []
    for r in raw.to_dict("records"):
        oid = norm_order_id(r["order_id"])
        if oid not in all_order_ids:
            quarantine("merch_refunds", f, r["_row"], "orphan_order_id", r)
            continue
        if oid in dropped_orders:
            quarantine("merch_refunds", f, r["_row"], "order_quarantined", r,
                       detail="every line of this order was quarantined in merch_orders.csv")
            continue
        amount = money_ngn(r["refund_amount"], "refund_amount")
        cand = readings(r["refund_date"])
        fl, if_dmy, if_mdy = [], None, None
        if len(cand) == 1:
            rdate = cand[0]
            res["single_reading"] += 1
        else:
            a, b, y = (int(x) for x in str(r["refund_date"]).strip().split("/"))
            dmy, mdy = date(y, b, a), date(y, a, b)
            fits = [d for d in cand if lo <= (d - order_day[oid]).days <= hi]
            if len(fits) == 1:
                rdate = fits[0]
                res["two_readings_resolved_day_first" if rdate == dmy else "two_readings_resolved_month_first"] += 1
                convention.append(("day_first" if rdate == dmy else "month_first", r["processed_by"], r["reason"], y))
                fl.append("refund_date_format_resolved_by_refund_window")
            else:
                rdate, if_dmy, if_mdy = None, dmy, mdy
                res["two_readings_both_fit_left_blank" if fits else "two_readings_neither_fits_left_blank"] += 1
                fl.append("refund_date_ambiguous" if fits else "refund_date_ambiguous_neither_reading_fits")
        if rdate is not None and not lo <= (rdate - order_day[oid]).days <= hi:
            fl.append("refund_date_outside_usual_window")
        if amount is not None and amount < 0:
            fl.append("amount_written_as_negative")
        value = order_value.get(oid)
        if amount is not None and not na(value) and abs(amount) > value + 0.005:
            fl.append("refund_exceeds_order_value")
        rows.append({"refund_id": norm_prefixed_id(r["refund_id"], "RF"), "_raw_id": r["refund_id"].strip().upper(),
                     "order_id": oid, "refund_date": rdate,
                     "refund_date_if_day_first": if_dmy, "refund_date_if_month_first": if_mdy,
                     "refund_amount_ngn": None if amount is None else abs(amount),
                     "reason": M.REFUND_REASON(r["reason"]), "processed_by": M.PROCESSED_BY(r["processed_by"]),
                     "_fl": fl})
    out = pd.DataFrame(rows)
    assert (out.refund_id == out["_raw_id"]).all(), "refund ids are not uniformly formatted"
    size = out.groupby("refund_id").refund_id.transform("size")
    seq = out.groupby("refund_id").cumcount() + 1
    out.insert(1, "refund_key", np.where(size > 1, out.refund_id + "-" + seq.astype(str), out.refund_id))
    out["dq_flags"] = [flags(*(["refund_id_shared_with_other_refunds"] if s > 1 else []), *fl)
                       for s, fl in zip(size, out["_fl"])]
    assert out.refund_key.is_unique
    shared = out[size > 1]
    orders_per_id = shared.groupby("refund_id").order_id.nunique()
    orphans = [id_number(json.loads(q["payload"])["order_id"]) for q in Q
               if q["src_file"] == f and q["reason"] == "orphan_order_id"]
    real = sorted(id_number(x) for x in all_order_ids)
    conv = pd.DataFrame(convention, columns=["conv", "processed_by", "reason", "year"])
    separating = [col for col in ("processed_by", "reason", "year")
                  if (conv.groupby(conv[col].map(lambda v: str(v).strip().lower())).conv.nunique() < 2).any()]
    decide("D-RF-1", "Refunds", f"Refund dates mix day-first and month-first slash formats. A date with only one valid "
           f"reading is used as is. When both readings are valid dates, the one inside the refund window seen on every "
           f"unambiguous refund ({lo}-{hi} days after the order's {basis} date) is used; if both or neither fit, "
           "refund_date is left blank and both readings are kept in refund_date_if_day_first / "
           "refund_date_if_month_first.",
           f"{dict(res)}. Unambiguous refunds land {windows['UTC'][0]}-{windows['UTC'][1]} days after the UTC order date "
           f"and {windows['Lagos'][0]}-{windows['Lagos'][1]} days after the Lagos date; the tighter {basis} window is "
           "used. "
           + ("Every processed_by, reason and year value occurs with both conventions, so no field separates them "
              "and parsing one way would misdate hundreds of refunds." if not separating else
              f"Note: {separating} partly separate the conventions."))
    decide("D-RF-2", "Refunds", "refund_amount_ngn is always positive: '(4,500)' and '-NGN 4,500' are accounting notation "
           "for a refund of 4,500.",
           f"{int(out.dq_flags.fillna('').str.contains('amount_written_as_negative').sum())} amounts were written with a "
           "sign.")
    decide("D-RF-3", "Refunds", "refund_id is not unique and is not used to deduplicate; refund_key adds a -1/-2 suffix "
           "where an id repeats.",
           f"{shared.refund_id.nunique()} ids are shared by {len(shared)} rows; {int((orders_per_id > 1).sum())} of those "
           "ids point at more than one order with different amounts, i.e. separate refunds whose ids collided. "
           f"Deduplicating on refund_id would delete {len(shared) - shared.refund_id.nunique()} real refunds.")
    decide("D-RF-4", "Refunds", "Refunds for orders that do not exist are quarantined. Refunds for orders whose every line "
           "was quarantined are quarantined with them.",
           f"{len(orphans)} orphan refunds reference order numbers {min(orphans):,}-{max(orphans):,}; real orders run "
           f"{real[0]:,}-{real[-1]:,}. {STATS[f]['quarantined:order_quarantined']} refunds follow a quarantined order.")
    STATS[f].update(res)
    STATS[f]["rows_out"] = len(out)
    out = out[["refund_id", "refund_key", "order_id", "refund_date", "refund_date_if_day_first",
               "refund_date_if_month_first", "refund_amount_ngn", "reason", "processed_by", "dq_flags"]]
    return out.sort_values(["refund_id", "refund_key"]).reset_index(drop=True)


# =========================================================== MARKETING SPEND
def clean_spend(src: Path):
    f = "marketing_spend.csv"
    raw = read_table(src / f, sep=";")
    STATS[f]["rows_in"] = len(raw)
    key_cols = [col for col in raw.columns if col != "_row"]
    dup = raw.duplicated(key_cols)
    firsts = raw[~dup].set_index(key_cols)["_row"]
    for _, r in raw[dup].iterrows():
        quarantine("marketing_spend", f, r["_row"], "exact_duplicate_row_double_submitted", r,
                   detail=f"copy of spreadsheet row {firsts.loc[tuple(r[col] for col in key_cols)]}")
    raw = raw[~dup]
    dmy_proof = prove(raw.date, "DMY", "spend date")
    out = pd.DataFrame({
        "spend_date": umap(raw.date, lambda v: parse_date(v, "DMY")),
        "channel": umap(raw.channel, M.SPEND_CHANNEL),
        "campaign": umap(raw.campaign_name, M.CAMPAIGN),
        "impressions": umap(raw.impressions, whole_count),
        "clicks": umap(raw.clicks, whole_count),
        "currency": umap(raw.currency, lambda v: "NGN" if is_null(v) else M.CURRENCY_CODE(v)),
        "spend_ngn": umap(raw.spend, lambda v: money_ngn(v, "spend", allow_decimal_comma=True)),
    })
    assert (out.currency == "NGN").all(), "non-NGN ad spend"
    assert not out.duplicated(["spend_date", "channel", "campaign"]).any(), "spend grain not unique"
    out["dq_flags"] = [flags("clicks_exceed_impressions" if c > i else None, "spend_missing" if na(s) else None)
                       for c, i, s in zip(out.clicks, out.impressions, out.spend_ngn)]
    dec_comma = int(raw.spend.str.contains(",").sum())
    two_dec = int(raw.spend.str.match(r"^\d+,\d{2}$").sum())
    assert dec_comma == two_dec, "a spend value has a comma that is not a two-digit decimal comma"
    decide("D-SPEND-1", "Marketing", "marketing_spend.csv was semicolon-delimited with decimal commas; it is rewritten as "
           "a standard comma CSV with dot decimals ('87635,35' = 87,635.35; '1 254 300' impressions = 1,254,300). Blank "
           "and 'N' currency are NGN. Exact duplicate rows (the double-submitted batch) are quarantined.",
           f"{dec_comma:,} spend values contain a comma and every one has exactly two digits after it, so none is a "
           f"thousands separator. {STATS[f]['quarantined:exact_duplicate_row_double_submitted']} duplicates removed; "
           "day x channel x campaign is then unique, as fct_ad_spend's primary key requires.")
    decide("D-SPEND-2", "Marketing", "Campaign names are normalised for spelling only; 'always_on' vs 'brand_always_on' "
           "and 'blackfriday24' vs 'black_friday' stay distinct.",
           "Whether those are the same campaign is an attribution call for the Phase 4 mapping table; merging them here "
           "could not be undone downstream.")
    STATS[f]["rows_out"] = len(out)
    STATS[f]["dmy_proof_values"] = dmy_proof
    return out.sort_values(["spend_date", "channel", "campaign"]).reset_index(drop=True)


# ================================================================= SESSIONS
BOT_UA = r"bot|crawl|spider|slurp|curl|wget|python-requests|headless|semrush|ahrefs|scrapy|httpclient|java/"
SESSION_SPECS = [
    ("web_sessions_2023.csv", ",", {"ts_epoch_ms": "ts", "user_pseudo_id": "visitor_id", "utm_source": "source",
                                     "utm_medium": "medium", "utm_campaign": "campaign", "device_category": "device",
                                     "pageviews": "page_views", "session_duration_sec": "duration_seconds",
                                     "is_new_user": "new_visitor", "revenue": "revenue"}),
    ("web_sessions_2024.csv", ",", {"session_start": "ts", "revenue_ngn": "revenue"}),
    ("web_sessions_2025_H1.tsv", "\t", {"session_start_iso": "ts", "revenue_ngn": "revenue"}),
]
SESSION_COLS = ["session_id", "session_start_utc", "session_date_lagos", "visitor_id", "source", "channel", "medium",
                "campaign", "gclid", "device", "country", "landing_page", "page_views", "duration_seconds",
                "user_agent", "is_new_visitor", "converted", "transaction_id", "revenue_ngn", "is_bot", "is_spam"]


def landing(v):
    if is_null(v):
        return None
    p = str(v).strip().split("?")[0].split("#")[0].lower()
    if p in ("", "/index.html", "/index.htm"):
        return "/"
    return p.rstrip("/") or "/"


def clean_sessions(src: Path):
    outputs, clocks, humans, rev_filled = {}, {}, {}, {}
    for fname, sep, ren in SESSION_SPECS:
        raw = read_table(src / fname, sep=sep).rename(columns=ren)
        STATS[fname]["rows_in"] = len(raw)
        if fname.endswith("2023.csv"):
            clock = pd.to_datetime(raw.ts.astype("int64"), unit="ms")
        elif fname.endswith("2024.csv"):
            clock = pd.to_datetime(raw.ts, format="%Y-%m-%d %H:%M:%S")
        else:
            assert raw.ts.str.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+01:00$").all(), "2025 offsets not all +01:00"
            clock = pd.to_datetime(raw.ts.str.slice(0, 19), format="%Y-%m-%dT%H:%M:%S")
        is_bot = raw.user_agent.str.contains(BOT_UA, case=False, regex=True)
        spam_key = umap(raw.source, lambda v: None if is_null(v) else re.sub(r"[^0-9a-z]+", " ", v.lower()).strip())
        out = pd.DataFrame({
            "session_id": raw.session_id.str.strip(),
            "session_start_utc": (clock - LAGOS).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_date_lagos": clock.dt.date,
            "visitor_id": umap(raw.visitor_id, clean_text),
            "source": umap(raw.source, lambda v: "direct" if is_null(v) else v.strip().lower()),
            "channel": umap(raw.source, lambda v: "Direct" if is_null(v) else M.SOURCE_CHANNEL(v)),
            "medium": umap(raw.medium, lambda v: "none" if is_null(v) else M.MEDIUM(v)),
            "campaign": umap(raw.campaign, M.CAMPAIGN),
            "gclid": umap(raw.gclid, clean_text) if "gclid" in raw else None,
            "device": umap(raw.device, M.DEVICE),
            "country": umap(raw.country, M.COUNTRY),
            "landing_page": umap(raw.landing_page, landing),
            "page_views": umap(raw.page_views, lambda v: int_or_none(v, "page_views")),
            "duration_seconds": umap(raw.duration_seconds, lambda v: int_or_none(v, "duration_seconds")),
            "user_agent": umap(raw.user_agent, clean_text),
            "is_new_visitor": umap(raw.new_visitor, to_bool),
            "converted": umap(raw.converted, to_bool),
            "transaction_id": umap(raw.transaction_id, lambda v: None if is_null(v) else norm_order_id(v)),
            "revenue_ngn": umap(raw.revenue, lambda v: money_ngn(v, "session revenue")),
            "is_bot": is_bot,
            "is_spam": spam_key.isin(M.SPAM_SOURCES),
        })[SESSION_COLS]
        assert out.session_id.is_unique, f"{fname}: duplicate session_id"
        assert not (out.is_spam & ~out.is_bot).any(), "spam session without a bot user agent"
        converted = out.converted.map(lambda v: v is True)
        blank_rev = out.revenue_ngn.map(na)
        assert not (blank_rev & converted).any(), f"{fname}: a converted session has no revenue"
        assert not (~converted & out.revenue_ngn.map(lambda v: not na(v) and v > 0)).any(), \
            f"{fname}: revenue on a session that did not convert"
        rev_filled[fname] = int(blank_rev.sum())
        out["revenue_ngn"] = [0.0 if na(v) else v for v in out.revenue_ngn]
        clocks[fname], humans[fname] = clock, ~is_bot
        STATS[fname].update({"rows_out": len(out), "is_bot": int(out.is_bot.sum()), "is_spam": int(out.is_spam.sum())})
        outputs[fname] = out
    assert pd.concat([o.session_id for o in outputs.values()]).is_unique, "session_id repeats across files"

    def profile(fname, per_hour=4):
        c = clocks[fname][humans[fname]]
        slot = ((c.dt.hour * 60 + c.dt.minute) // (60 // per_hour)).to_numpy()
        h = np.bincount(slot, minlength=24 * per_hour).astype(float)
        return h / h.sum()
    ref = profile("web_sessions_2025_H1.tsv")
    fit = {}
    for fname in ("web_sessions_2023.csv", "web_sessions_2024.csv"):
        h = profile(fname)
        fit[fname] = {k: round(float(np.abs(np.roll(h, 4 * k) - ref).sum()), 3) for k in range(-3, 4)}
        best = min(fit[fname], key=fit[fname].get)
        assert best == 0, f"{fname}: clock fits Lagos best at a {best}h shift, not 0"
    hourly = ref.reshape(24, 4).sum(axis=1)
    decide("D-SESS-1", "Sessions", "In all three session files the clock digits are Africa/Lagos local time: "
           "session_date_lagos is the clock date and session_start_utc is the clock minus one hour. That includes 2023, "
           "whose epoch-millisecond values encode Lagos wall-clock time, not UTC.",
           f"Human traffic has a strong daily rhythm (busiest hour {hourly.max() / hourly.min():.1f}x the quietest). Each "
           "file's time-of-day profile was compared with 2025, the only file that states its offset (+01:00), shifted "
           f"by -3..+3 hours; for both 2023 and 2024 the best fit is no shift (L1 distance by shift, 2023: "
           f"{fit['web_sessions_2023.csv']}; 2024: {fit['web_sessions_2024.csv']}). The handover's '2023 timestamps are "
           "UTC' is false for sessions: taking it literally would put every 2023 session an hour late and move "
           "late-evening sessions onto the wrong day.")
    allv = pd.concat([o[["session_date_lagos", "duration_seconds", "source", "channel", "page_views", "is_bot",
                         "is_spam"]] for o in outputs.values()])
    heavy = allv[allv.page_views.isin([40, 60])]
    spam = allv[allv.is_spam]
    decide("D-SESS-2", "Sessions", "is_bot = the user agent is a crawler, script or SEO tool; is_spam = the source is a "
           "referral-spam domain. Sessions are flagged, never removed; human traffic = not is_bot.",
           f"{int(allv.is_bot.sum()):,} bot sessions ({allv.is_bot.mean():.1%}) and {len(spam):,} spam sessions from "
           f"{spam.source.nunique()} sources ({', '.join(sorted(spam.source.unique()))}) between "
           f"{spam.session_date_lagos.min()} and {spam.session_date_lagos.max()}, "
           f"{'all' if (spam.duration_seconds == 0).all() else 'mostly'} with 0-second duration. The signals are nested: "
           f"every spam session and {int(heavy.is_bot.sum()):,} of the {len(heavy):,} sessions with exactly 40 or 60 "
           f"page views already carry a bot user agent, leaving {int((~allv.is_bot).sum()):,} human sessions. The "
           "dictionary's 'bot filtering is applied upstream' is false.")
    decide("D-SESS-5", "Sessions", "revenue_ngn is 0 for every session that did not convert, and a session with no "
           "utm_source is recorded as source 'direct'.",
           f"The source files spell 'no revenue' three ways at random — 0, 'NA' and blank — but no converted session "
           f"ever has a blank and no unconverted session ever has revenue above 0, so the "
           f"{sum(rev_filled.values()):,} blanks are zeroes and are written as 0. Likewise a missing utm_source is "
           "traffic with no referrer, which these files elsewhere spell '(direct)' or 'direct'; the channel column "
           "already reads Direct for all of them.")
    decide("D-SESS-3", "Sessions", "utm_source spellings map to 8 groups: Google, Instagram, Facebook / Meta, TikTok, "
           "YouTube, Email, Direct, Referral / Other (X/Twitter, LinkedIn, Vimeo, Behance, generic referral and the "
           "spam domains, which also carry is_spam). A blank source is Direct and the lower-cased original source is "
           "kept beside the channel. Landing pages lose query strings, fragments, trailing slashes and '/index.html'.",
           f"{allv.source.nunique()} distinct lower-cased sources -> {allv.channel.nunique()} groups. Instagram stays "
           "separate from Facebook so the Phase 4 mapping to 'Meta Ads' spend is an explicit, reversible choice.")
    return outputs


def attribution_evidence(sessions, orders, all_order_ids):
    first = pd.to_datetime(orders.order_ts_utc).dt.tz_localize(None).groupby(orders.order_id).min()
    s = pd.concat([o[["session_start_utc", "transaction_id", "converted", "is_bot"]] for o in sessions.values()])
    human = s[~s.is_bot]
    conv = s[s.converted == True]  # noqa: E712 (object column of True/False/None)
    with_txn = conv[conv.transaction_id.notna()]
    joined = with_txn[with_txn.transaction_id.isin(first.index)]
    joined_raw = with_txn[with_txn.transaction_id.isin(all_order_ids)]
    txn_not_converted = int((s.transaction_id.notna() & (s.converted != True)).sum())  # noqa: E712
    delta = (joined.transaction_id.map(first) -
             pd.to_datetime(joined.session_start_utc).dt.tz_localize(None)).dt.total_seconds() / 86400
    decide("D-SESS-4", "Sessions", "transaction_id is normalised to the order-id format and kept as recorded; sessions "
           "whose id does not match an order are left in place (that gap is the unattributable conversion volume).",
           f"{len(conv):,} converted sessions; {len(with_txn):,} carry a transaction_id; {len(joined):,} "
           f"({len(joined) / len(conv):.1%} of conversions) join a cleaned order ({len(joined_raw):,} join an order id "
           f"that exists in the raw file), so {len(conv) - len(joined):,} conversions cannot be attributed — the "
           f"dictionary's 'always joins' is false. {txn_not_converted} non-converted sessions carry an id. Conversion "
           f"rate on human sessions: {(human.converted == True).mean():.2%}. Caveat for attribution work: joined orders "  # noqa: E712
           f"are a median {delta.abs().median():.0f} days from their session and {(delta < 0).mean():.0%} are dated "
           "before the session started.")


# ===================================================================== MAIN
COLUMN_CHANGES = {
    "clients_export.csv": "type -> client_type; phone in +234 format (invalid numbers blanked and flagged); "
                          "billing_currency = NGN (original in the audit file); added merged_from, match_confidence, "
                          "dq_flags",
    "bookings_2023.csv": "gross_amount -> gross_amount_ngn; added client_id_orig, net_amount_ngn, fx_converted, dq_flags",
    "bookings_2024.csv": "booking_ref -> booking_id; customer_id -> client_id; date_of_shoot -> shoot_date; amount_gross "
                         "-> gross_amount_ngn; added client_id_orig, net_amount_ngn, fx_converted, dq_flags",
    "bookings_2025_H1.xlsx": "header moved to row 1; Booking Ref -> booking_id; Client ID -> client_id; Client Name -> "
                             "client_name; Service -> service_type; Shoot Date -> shoot_date; Days -> shoot_days; City "
                             "-> location_city; Gross Amount -> gross_amount_ngn; Disc % -> discount_pct; Ccy -> "
                             "currency; Status -> status; Lead Source -> lead_source; Notes -> notes; added "
                             "client_id_orig, net_amount_ngn, fx_converted, dq_flags; Pivot, Sheet1 and Notes tabs "
                             "removed",
    "crew.csv": "added dq_flags",
    "crew_timesheets.csv": "day_rate_charged -> day_rate_charged_ngn; added dq_flags",
    "fx_rates.csv": "one row per calendar day per currency; added is_filled, source_rate_date, is_corrected, "
                    "original_rate",
    "marketing_spend.csv": "semicolons -> commas; date -> spend_date; campaign_name -> campaign; spend -> spend_ngn; "
                           "added dq_flags",
    "merch_orders.csv": "order_ts -> order_ts_utc; unit_price -> unit_price_ngn; added client_id_orig, line_gross_ngn, "
                        "dq_flags",
    "merch_products.csv": "added is_current, dq_flags",
    "merch_refunds.csv": "refund_amount -> refund_amount_ngn; added refund_key, refund_date_if_day_first, "
                         "refund_date_if_month_first, dq_flags",
    "web_sessions_2023.csv": "ts_epoch_ms -> session_start_utc + session_date_lagos; user_pseudo_id -> visitor_id; "
                             "utm_source -> source + channel; utm_medium -> medium; utm_campaign -> campaign; "
                             "device_category -> device; pageviews -> page_views; session_duration_sec -> "
                             "duration_seconds; is_new_user -> is_new_visitor; revenue -> revenue_ngn; added gclid "
                             "(empty in 2023), is_bot, is_spam",
    "web_sessions_2024.csv": "session_start -> session_start_utc + session_date_lagos; source -> source + channel; "
                             "new_visitor -> is_new_visitor; added is_bot, is_spam",
    "web_sessions_2025_H1.tsv": "session_start_iso -> session_start_utc + session_date_lagos; source -> source + "
                                "channel; new_visitor -> is_new_visitor; added is_bot, is_spam",
}


def run(src: Path):
    for store in (Q, STATS, DECISIONS, AUDIT, NULL_SEEN):
        store.clear()
    log("fx ...")
    fx, fx_lookup = clean_fx(src)
    log("clients ...")
    clients, remap, billing, client_names, client_cities = clean_clients(src, booking_cities(src))
    booked_with_crew, ts_roles, ts_rates, ts_days = timesheet_facts(src)
    log("bookings ...")
    bookings, booking_ids, all_booking_ids = clean_bookings(load_bookings(src), remap, billing, client_names, fx_lookup,
                                                            booked_with_crew, ts_days, client_cities)
    log("crew ...")
    crew, crew_ids = clean_crew(src, ts_roles, ts_rates)
    log("timesheets ...")
    timesheets = clean_timesheets(src, booking_ids, all_booking_ids, crew_ids, dict(zip(crew.crew_id, crew.role)))
    log("products ...")
    products, sku_names, stated_last_end, scd = clean_products(src)
    log("orders ...")
    orders, all_order_ids, dropped_orders = clean_orders(src, sku_names, set(clients.client_id), remap, products,
                                                         stated_last_end, scd)
    log("refunds ...")
    refunds = clean_refunds(src, orders, all_order_ids, dropped_orders)
    log("spend ...")
    spend = clean_spend(src)
    log("sessions ...")
    sessions = clean_sessions(src)
    attribution_evidence(sessions, orders, all_order_ids)

    spellings = ", ".join(f"{('(empty)' if k == '' else repr(k))} x{v:,}" for k, v in NULL_SEEN.most_common())
    decide("D-NULL-1", "General", "Every spelling of 'missing' found in the files is treated as a blank value.",
           f"Counted across every cell of every CSV/TSV file: {spellings}. None of these is a real category in any "
           "column. (The Excel workbook uses the same spellings.)")
    decide("D-MONEY-3", "Currency", "Every money column in every cleaned file is naira and every currency column reads "
           "NGN.",
           "Only bookings and client billing contained USD/GBP. Crew rates, timesheets, product costs and prices, order "
           "prices, refunds, ad spend and session revenue were already naira; the pipeline checks each value's currency "
           "marker instead of assuming it. fx_rates.csv necessarily still names USD/GBP/EUR because it is the conversion "
           "table; its rates are NGN per unit.")
    decide("D-ENC-1", "General", "Files are decoded run-by-run (UTF-8 where valid, otherwise Windows-1252) and "
           "double-encoded text ('SiÃ³bhan', 'Anniversary â€™05') is repaired.",
           "clients_export.csv mixes correct UTF-8, raw Windows-1252 and double-encoded (sometimes lower-cased) text for "
           "the same names; reading it any single way corrupts accented names, which is why it 'breaks in Python'.")

    datasets = {"fx_rates.csv": fx, "clients_export.csv": clients, **bookings, "crew.csv": crew,
                "crew_timesheets.csv": timesheets, "merch_products.csv": products, "merch_orders.csv": orders,
                "merch_refunds.csv": refunds, "marketing_spend.csv": spend, **sessions}
    qcount = Counter(q["src_file"] for q in Q)
    problems = []
    for fname in datasets:
        s = STATS[fname]
        kept = s["published_rows_kept"] if fname == "fx_rates.csv" else s["rows_out"]
        if s["rows_in"] != kept + qcount.get(fname, 0):
            problems.append(f"{fname}: in {s['rows_in']} != kept {kept} + quarantined {qcount.get(fname, 0)}")
    assert not problems, "ROW ACCOUNTING FAILED:\n" + "\n".join(problems)
    for fname, df in datasets.items():
        for col in ("currency", "billing_currency", "to_currency"):
            if col in df:
                assert set(df[col].dropna()) == {"NGN"}, f"{fname}.{col} is not all NGN"
    return datasets


# Tokens chosen so that no reader mistakes them for data AND none of them is in pandas' default
# na_values list — 'None', 'NA', 'N/A', 'null' and friends would be silently read back as missing.
NOTHING_TO_RECORD = {"notes", "merged_from", "match_confidence", "client_id_orig", "refund_date_if_day_first",
                     "refund_date_if_month_first", "gclid", "transaction_id", "discount_code", "campaign",
                     "original_rate"}
PLACEHOLDER_COUNTS: Counter = Counter()


def fill_placeholders(fname, df):
    """Leave no empty cell: every blank gets an explicit, visible token."""
    df = df.copy()
    for col in df.columns:
        blank = [na(v) or (isinstance(v, str) and not v.strip()) for v in df[col]]
        if not any(blank):
            continue
        token = "No issues" if col == "dq_flags" else \
                "Guest" if (col == "client_id" and fname == "merch_orders.csv") else \
                "Not applicable" if col in NOTHING_TO_RECORD else "Unknown"
        df[col] = [token if b else v for b, v in zip(blank, df[col])]
        PLACEHOLDER_COUNTS[(fname, col, token)] += sum(blank)
    return df


def write_dataset(df: pd.DataFrame, path: Path):
    df = fill_placeholders(path.name, df)
    for col in ("shoot_days", "line_no", "quantity", "page_views", "duration_seconds", "impressions", "clicks",
                "timesheet_id"):
        if col in df:
            df[col] = [v if isinstance(v, str) else int(v) for v in df[col]]
    if path.suffix == ".xlsx":
        for col in df.columns:
            if df[col].map(lambda v: isinstance(v, date)).any():
                df[col] = df[col].map(lambda v: v if isinstance(v, str) else datetime(v.year, v.month, v.day))
        with pd.ExcelWriter(path, engine="openpyxl", date_format="YYYY-MM-DD", datetime_format="YYYY-MM-DD") as xw:
            df.to_excel(xw, sheet_name="H1 2025 Bookings", index=False)
            ws = xw.sheets["H1 2025 Bookings"]
            ws.freeze_panes = "A2"
            for i, col in enumerate(df.columns, start=1):
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(12, min(40, len(col) + 4))
        return
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(lambda v: v.isoformat() if isinstance(v, (date, datetime)) else v)
    df.to_csv(path, sep="\t" if path.suffix == ".tsv" else ",", index=False, lineterminator="\n", encoding="utf-8")


BLANK_MEANING = {
    "dq_flags": ("expected", "no data-quality issue was found on this row"),
    "notes": ("expected", "no note was written"),
    "merged_from": ("expected", "this client absorbed no duplicate record"),
    "match_confidence": ("expected", "only set where a duplicate client was merged in"),
    "client_id_orig": ("expected", "the client id on this row was not changed"),
    "refund_date_if_day_first": ("expected", "the refund date had only one possible reading"),
    "refund_date_if_month_first": ("expected", "the refund date had only one possible reading"),
    "original_rate": ("expected", "the published rate needed no correction"),
    "gclid": ("expected", "not a Google Ads click (the 2023 export has no gclid column at all)"),
    "transaction_id": ("expected", "the session did not convert"),
    "discount_code": ("expected", "no discount code was used on this line"),
    "campaign": ("expected", "traffic with no campaign attached (direct, organic or referral)"),
    "client_id": ("expected", "guest checkout: the buyer had no customer account"),
    "vat_applied": ("expected", "duplicate copies of this booking disagreed on the VAT flag"),
    "shoot_days": ("unrecorded", "not recorded, and the booking has no timesheets to count days from"),
    "status": ("unrecorded", "not recorded; the booking has crew days, so it was not cancelled, but which of the four "
                             "live statuses applied is unknown"),
    "service_type": ("unrecorded", "not recorded, and nothing else in the data identifies the service"),
    "lead_source": ("unrecorded", "not recorded"),
    "location_city": ("unrecorded", "not recorded, and the client has no city either"),
    "email": ("unrecorded", "no address on file"),
    "phone": ("unrecorded", "no number on file, or the recorded number was not a valid Nigerian mobile (see dq_flags)"),
    "city": ("unrecorded", "not recorded"),
    "country": ("unrecorded", "not recorded, and the client has no city to derive it from"),
    "signup_date": ("unrecorded", "not recorded"),
    "acquisition_channel": ("unrecorded", "not recorded"),
    "employment_type": ("unrecorded", "not recorded"),
    "hours_worked": ("unrecorded", "not recorded, or recorded as an impossible 26h and blanked (see dq_flags)"),
    "day_rate_charged_ngn": ("unrecorded", "not recorded; it cannot be taken from the roster rate because charged "
                                           "rates include half-days and 1.5x overtime"),
    "approved_by": ("unrecorded", "no approver recorded"),
    "size": ("unrecorded", "not recorded (size is unreliable in this data anyway)"),
    "size_run": ("unrecorded", "not recorded for this price version"),
    "customer_email": ("unrecorded", "no address recorded on the order line"),
    "shipping_country": ("unrecorded", "not recorded; it cannot be taken from the client's country, which matches the "
                                       "shipping country only 23% of the time"),
    "payment_method": ("unrecorded", "not recorded"),
    "sales_channel": ("unrecorded", "not recorded"),
    "reason": ("unrecorded", "no refund reason recorded"),
    "processed_by": ("unrecorded", "no handler recorded"),
    "refund_date": ("unrecorded", "the date could be read two ways and both fit the refund window; both readings are "
                                  "in refund_date_if_day_first / refund_date_if_month_first"),
    "role_on_job": ("unrecorded", "not recorded, and the crew member has no roster role either"),
    "role": ("unrecorded", "no roster role, and this crew member has no timesheets to take one from"),
    "day_rate_ngn": ("unrecorded", "no roster rate, and no charged rate on any timesheet"),
}


def write_missing_report(report: Path, datasets):
    rows = []
    for fname, df in datasets.items():
        for col in df.columns:
            blanks = int(sum(1 for v in df[col] if na(v) or (isinstance(v, str) and not v.strip())))
            if blanks:
                kind, meaning = BLANK_MEANING.get(col, ("unrecorded", "not recorded in the source"))
                token = next((t for (f2, c2, t) in PLACEHOLDER_COUNTS if f2 == fname and c2 == col), "")
                rows.append({"file": fname, "column": col, "blank_rows": blanks, "rows": len(df),
                             "pct_blank": round(100 * blanks / len(df), 2), "kind": kind,
                             "placeholder_written": token, "blank_means": meaning})
    m = pd.DataFrame(rows).sort_values(["file", "blank_rows"], ascending=[True, False])
    m.to_csv(report / "missing_values.csv", index=False, lineterminator="\n", encoding="utf-8")
    return m


def write_report(report: Path, datasets):
    report.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(Q, columns=["src_table", "src_file", "src_row", "reason", "detail", "payload"]).to_csv(
        report / "quarantine_rejected_rows.csv", index=False, lineterminator="\n", encoding="utf-8")
    audit = pd.DataFrame(AUDIT)
    for col in audit.columns:
        audit[col] = audit[col].map(lambda v: v.isoformat() if isinstance(v, (date, datetime)) else v)
    audit.to_csv(report / "currency_conversion_audit.csv", index=False, lineterminator="\n", encoding="utf-8")

    qcount = Counter(q["src_file"] for q in Q)
    L = ["# Xtrim Studios - cleaning decisions log", "",
         "Every rule applied to the raw extracts, the evidence behind it, and what it changed. All numbers are computed "
         "by the pipeline on each run.", "",
         "## Row accounting", "", "| File | Rows in | Rows out | Quarantined |", "|---|---:|---:|---:|"]
    for fname in datasets:
        s = STATS[fname]
        if fname == "fx_rates.csv":
            L.append(f"| {fname} | {s['rows_in']:,} | {s['published_rows_kept']:,} published + "
                     f"{s['filled_days_added']:,} filled days | {qcount.get(fname, 0):,} |")
        else:
            L.append(f"| {fname} | {s['rows_in']:,} | {s['rows_out']:,} | {qcount.get(fname, 0):,} |")
    L += ["", "For every file, rows in = rows out + quarantined; the pipeline refuses to write otherwise. Quarantined "
          "rows are in quarantine_rejected_rows.csv (src_row is the spreadsheet row number; header = row 1, or row 5 "
          "in the Excel sheet).", "",
          "## Decisions", "", "| ID | Area | Rule | Evidence and impact |", "|---|---|---|---|"]
    for code, area, rule, ev in DECISIONS:
        L.append(f"| {code} | {area} | {rule.replace('|', '/')} | {ev.replace('|', '/')} |")
    L += ["", "## Quarantine by reason", "", "| File | Reason | Rows |", "|---|---|---:|"]
    for (fname, reason), k in sorted(Counter((q["src_file"], q["reason"]) for q in Q).items()):
        L.append(f"| {fname} | {reason} | {k:,} |")
    L += ["", "## Flags kept on cleaned rows (dq_flags)", "", "| File | Flag | Rows |", "|---|---|---:|"]
    for fname, df in datasets.items():
        if "dq_flags" in df:
            cnt = Counter(re.sub(r"stated_valid_to_\d{4}-\d{2}-\d{2}_extended", "stated_valid_to_extended", x)
                          for v in df.dq_flags.dropna() for x in str(v).split(","))
            for flag, k in sorted(cnt.items()):
                L.append(f"| {fname} | {flag} | {k:,} |")
    m = write_missing_report(report, datasets)
    cells = sum(len(df) * len(df.columns) for df in datasets.values())
    unrec = m[m.kind == "unrecorded"]
    by_token = Counter()
    for (_, _, token), k in PLACEHOLDER_COUNTS.items():
        by_token[token] += k
    L += ["", "## Empty cells: none (placeholder convention)", "",
          f"There are no empty cells in any file. {1 - m.blank_rows.sum() / cells:.1%} of cells hold a real value; the "
          "rest hold one of four visible tokens, never a guessed value:", "",
          f"- **`No issues`** ({by_token['No issues']:,} cells) — dq_flags: nothing was wrong with that row.",
          f"- **`Not applicable`** ({by_token['Not applicable']:,} cells) — there was nothing to record: no note was "
          "written, the session did not convert, no discount code was used, the client absorbed no duplicate, the FX "
          "rate needed no correction.",
          f"- **`Unknown`** ({by_token['Unknown']:,} cells) — a value that really exists but was never recorded, and "
          "that nothing else in the data determines. These are listed below.",
          f"- **`Guest`** ({by_token['Guest']:,} cells) — merch_orders.client_id, where the buyer checked out without "
          "an account.", "",
          "None of these tokens is in pandas' default `na_values` list, so a plain `pd.read_csv` will not quietly turn "
          "them back into missing values (`None`, `NA`, `N/A` and `null` would have been).", "",
          "Because `Unknown` appears in a few numeric columns (timesheet hours and charged day rates, shoot_days) and "
          "date columns (signup_date, refund_date), read those with `pd.to_numeric(col, errors='coerce')` or "
          "`pd.to_datetime(col, errors='coerce')`. A blank was deliberately *not* replaced with 0: zero hours or a "
          "zero day rate would quietly understate labour cost, whereas `Unknown` fails loudly.", "",
          "| File | Column | Cells marked Unknown | % of rows | What is actually missing |", "|---|---|---:|---:|---|"]
    for r in unrec.itertuples():
        L.append(f"| {r.file} | {r.column} | {r.blank_rows:,} | {r.pct_blank}% | {r.blank_means} |")
    L += ["", "## Column changes", "", "| File | Change |", "|---|---|"]
    L += [f"| {fname} | {txt} |" for fname, txt in COLUMN_CHANGES.items()]
    (report / "CLEANING_DECISIONS.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    a = ap.parse_args()
    datasets = run(a.src)
    a.out.mkdir(parents=True, exist_ok=True)
    for fname, df in datasets.items():
        write_dataset(df, a.out / fname)
    by_token = Counter()
    for (_, _, token), k in PLACEHOLDER_COUNTS.items():
        by_token[token] += k
    decide("D-NULL-2", "General", "No cell is left empty. A blank becomes 'No issues' in dq_flags, 'Not applicable' "
           "where there was nothing to record, 'Guest' for an order placed without an account, and 'Unknown' where a "
           "real value was never recorded. Numbers are never replaced with 0.",
           f"Cells written: {by_token['No issues']:,} 'No issues', {by_token['Not applicable']:,} 'Not applicable', "
           f"{by_token['Unknown']:,} 'Unknown', {by_token['Guest']:,} 'Guest'. None of these tokens is in pandas' "
           "default na_values list, so reading a file normally will not turn them back into blanks. They are "
           "deliberately non-numeric, so a sum or average over a column that has missing values fails loudly instead "
           "of silently treating a guess as zero; every one is listed by column in missing_values.csv.")
    write_report(a.report, datasets)
    qcount = Counter(q["src_file"] for q in Q)
    log("OK: row accounting and NGN checks passed")
    for fname in datasets:
        s = STATS[fname]
        kept = s["published_rows_kept"] if fname == "fx_rates.csv" else s["rows_out"]
        log(f"  {fname:28s} in {s['rows_in']:>7,}  out {kept:>7,}  quarantined {qcount.get(fname, 0):>6,}")


if __name__ == "__main__":
    main()
