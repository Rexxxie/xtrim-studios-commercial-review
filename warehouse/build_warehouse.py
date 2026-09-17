"""Load the cleaned layer into the PostgreSQL star schema.

    python warehouse/build_warehouse.py --clean clean --report cleaning_report --raw <raw dir>

Reads the cleaned files (never raw, except the product price file that Q6 must inspect
before resolution), builds every dimension and fact, and loads them with COPY. Postgres
enforces the grain: primary keys, foreign keys, the SCD EXCLUDE constraint and CHECKs make
a bad load fail instead of producing a quietly wrong warehouse.

Warehouse-level decisions are appended to warehouse/WAREHOUSE_DECISIONS.md.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
from clean_lib import norm_prefixed_id  # noqa: E402
from money import parse_money  # noqa: E402

DSN = os.environ.get("XTRIM_DSN", "host=localhost port=55432 dbname=xtrim user=xtrim")
DECISIONS: list[tuple[str, str, str]] = []

UNKNOWN = "Unknown"
NA = "Not applicable"

SERVICE_CATEGORY = {
    "Wedding Film": "Film", "Music Video": "Film", "Commercial / TVC": "Film",
    "Corporate Documentary": "Film", "Short Film": "Film", "Event Coverage": "Coverage",
    "Photoshoot": "Stills", "Studio Rental": "Rental", UNKNOWN: "Unknown",
}

# channel_name, spend channel in marketing_spend.csv, session utm groups, is_paid
CHANNELS = [
    ("Google", "Google Ads", ["Google"], True),
    ("Meta", "Meta Ads", ["Facebook / Meta", "Instagram"], True),
    ("TikTok", "TikTok Ads", ["TikTok"], True),
    ("YouTube", "YouTube Pre-roll", ["YouTube"], True),
    ("Email", "Email / CRM", ["Email"], True),
    ("Influencer", "Influencer", [], True),
    ("Direct", None, ["Direct"], False),
    ("Referral / Other", None, ["Referral / Other"], False),
]
# spend campaign -> session campaign spelling (only where they differ)
CAMPAIGN_MAP = {"always_on": "brand_always_on"}


def decide(code, rule, evidence):
    DECISIONS.append((code, rule, evidence))


def read(clean: Path, name: str) -> pd.DataFrame:
    p = clean / name
    if name.endswith(".xlsx"):
        df = pd.read_excel(p, dtype=str).fillna("")
        for c in df.columns:
            df[c] = df[c].str.replace(r" 00:00:00$", "", regex=True)
        return df
    return pd.read_csv(p, dtype=str, keep_default_na=False, sep="\t" if name.endswith(".tsv") else ",")


def nn(s: pd.Series) -> pd.Series:
    """Cleaned-layer tokens -> real nulls for loading."""
    return s.replace({UNKNOWN: None, NA: None, "": None})


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(nn(s), errors="coerce")


def boolean(s: pd.Series) -> pd.Series:
    return nn(s).map({"True": True, "False": False})


def code_to_int(s: pd.Series) -> pd.Series:
    return nn(s).str.replace(r"\D", "", regex=True).astype("Int64")


def pg_array(values) -> str | None:
    if not values:
        return None
    return "{" + ",".join('"' + str(v).replace('"', '\\"') + '"' for v in values) + "}"


def copy(cur, table: str, df: pd.DataFrame):
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N", lineterminator="\n")
    buf.seek(0)
    cur.copy_expert(f"COPY {table} ({','.join(df.columns)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


# ------------------------------------------------------------------ builders
def build_dim_date(start="2021-01-01", end="2026-12-31") -> pd.DataFrame:
    d = pd.DataFrame({"date_key": pd.date_range(start, end, freq="D")})
    iso = d.date_key.dt.isocalendar()
    out = pd.DataFrame({
        "date_key": d.date_key.dt.date,
        "year": d.date_key.dt.year, "quarter": d.date_key.dt.quarter,
        "year_quarter": d.date_key.dt.year.astype(str) + "Q" + d.date_key.dt.quarter.astype(str),
        "month": d.date_key.dt.month, "month_name": d.date_key.dt.strftime("%b"),
        "iso_year": iso.year.astype(int), "iso_week": iso.week.astype(int),
        "week_start": (d.date_key - pd.to_timedelta(d.date_key.dt.weekday, unit="D")).dt.date,
        "day_of_week": d.date_key.dt.weekday + 1, "is_weekend": d.date_key.dt.weekday >= 5,
        "is_peak_season": d.date_key.dt.month.isin([11, 12]),
    })
    return out


def build(clean: Path, report: Path, raw: Path):
    T: dict[str, pd.DataFrame] = {}

    # ---------------------------------------------------------------- dim_date
    T["core.dim_date"] = build_dim_date()
    decide("W-DATE-1", "dim_date spans 2021-01-01 to 2026-12-31; is_peak_season = November and December.",
           "Signup dates start in 2021; product windows run into 2026. November and December are the two busiest "
           "months by job count in both complete years (see analysis).")

    # --------------------------------------------------------------- dim_client
    c = read(clean, "clients_export.csv")
    dim_client = pd.DataFrame({
        "client_key": np.arange(1, len(c) + 1),
        "client_id": code_to_int(c.client_id),
        "client_code": c.client_id,
        "merged_from": nn(c.merged_from).map(lambda v: None if v is None else pg_array(
            [int("".join(ch for ch in x if ch.isdigit())) for x in v.split(";")])),
        "client_name": c.client_name, "client_type": nn(c.client_type), "email": nn(c.email),
        "phone": nn(c.phone), "city": nn(c.city), "country": nn(c.country),
        "billing_currency": c.billing_currency, "signup_date": nn(c.signup_date),
        "acquisition_channel": nn(c.acquisition_channel), "match_confidence": num(c.match_confidence),
        "dq_flags": nn(c.dq_flags.replace("No issues", "")),
    })
    assert (c.billing_currency == "NGN").all()
    T["core.dim_client"] = dim_client
    client_key = dict(zip(c.client_id, dim_client.client_key))

    # -------------------------------------------------------------- dim_service
    services = list(SERVICE_CATEGORY)
    T["core.dim_service"] = pd.DataFrame({"service_key": np.arange(1, len(services) + 1), "service_name": services,
                                          "category": [SERVICE_CATEGORY[s] for s in services]})
    service_key = {s: i + 1 for i, s in enumerate(services)}

    # ----------------------------------------------------------------- dim_crew
    cr = read(clean, "crew.csv")
    T["core.dim_crew"] = pd.DataFrame({
        "crew_key": np.arange(1, len(cr) + 1), "crew_id": code_to_int(cr.crew_id), "crew_code": cr.crew_id,
        "full_name": cr.full_name, "role": cr.role, "standard_day_rate_ngn": num(cr.day_rate_ngn),
        "employment_type": nn(cr.employment_type), "is_active": boolean(cr.is_active),
    })
    crew_key = dict(zip(cr.crew_id, T["core.dim_crew"].crew_key))
    crew_rate = dict(zip(cr.crew_id, num(cr.day_rate_ngn)))

    # -------------------------------------------------------------- dim_product
    p = read(clean, "merch_products.csv")
    p = p.sort_values(["sku", "valid_from"]).reset_index(drop=True)
    T["core.dim_product"] = pd.DataFrame({
        "product_key": np.arange(1, len(p) + 1), "sku": p.sku, "product_name": p.product_name,
        "category": p.category, "collection": p.collection, "colour": nn(p.colour),
        "unit_cost_ngn": num(p.unit_cost_ngn), "list_price_ngn": num(p.list_price_ngn),
        "valid_from": p.valid_from, "valid_to": p.valid_to, "is_current": boolean(p.is_current),
    })
    prod = T["core.dim_product"].copy()
    prod["vf"] = pd.to_datetime(prod.valid_from)
    prod["vt"] = pd.to_datetime(prod.valid_to.replace("9999-12-31", "2262-04-11"))

    # --------------------------------------------------------------- stg product
    rp = pd.read_csv(raw / "merch_products.csv", dtype=str, keep_default_na=False)
    rp["_src_row"] = np.arange(2, len(rp) + 2)
    T["stg.merch_products"] = rp

    # -------------------------------------------------------------- dim_channel
    s_frames = []
    for f in ["web_sessions_2023.csv", "web_sessions_2024.csv", "web_sessions_2025_H1.tsv"]:
        df = read(clean, f)
        df["source_file"] = f
        s_frames.append(df)
    s = pd.concat(s_frames, ignore_index=True)
    variants = s.groupby("channel").source.apply(lambda x: sorted(set(x)))
    ch_rows, group_to_key, spend_to_key = [], {}, {}
    for i, (name, spend_name, groups, paid) in enumerate(CHANNELS, start=1):
        v = sorted({x for g in groups for x in variants.get(g, [])})
        ch_rows.append({"channel_key": i, "channel_name": name, "spend_channel_name": spend_name,
                        "session_groups": pg_array(groups) or "{}", "utm_source_variants": pg_array(v) or "{}",
                        "is_paid": paid})
        for g in groups:
            group_to_key[g] = i
        if spend_name:
            spend_to_key[spend_name] = i
    T["core.dim_channel"] = pd.DataFrame(ch_rows)
    assert set(s.channel) <= set(group_to_key), set(s.channel) - set(group_to_key)
    decide("W-CH-1", "Session utm groups and ad-spend channels resolve to one dim_channel: Google Ads = Google; "
                     "Meta Ads = Facebook / Meta + Instagram (one ad platform, one budget); TikTok Ads = TikTok; "
                     "YouTube Pre-roll = YouTube; Email / CRM = Email; Influencer has spend but no utm source of "
                     "its own; Direct and Referral / Other have sessions but no spend.",
           "marketing_spend.csv has 6 channel names, the session files 8 utm groups; no utm_source spelling "
           "identifies influencer traffic, so Influencer ROAS cannot be measured from sessions and is reported "
           "as spend only.")

    # ------------------------------------------------------------------ fx_daily
    fx = read(clean, "fx_rates.csv")
    T["core.fx_daily"] = pd.DataFrame({
        "rate_date": fx.rate_date, "from_currency": fx.from_currency, "to_currency": fx.to_currency,
        "rate": num(fx.rate), "is_filled": boolean(fx.is_filled), "source_rate_date": fx.source_rate_date,
        "is_corrected": boolean(fx.is_corrected), "original_rate": num(fx.original_rate),
    })

    # --------------------------------------------------------------- fct_booking
    frames = []
    for f in ["bookings_2023.csv", "bookings_2024.csv", "bookings_2025_H1.xlsx"]:
        df = read(clean, f)
        df["source_file"] = f
        frames.append(df)
    b = pd.concat(frames, ignore_index=True)
    audit = pd.read_csv(report / "currency_conversion_audit.csv", dtype=str, keep_default_na=False)
    ab = audit[audit.dataset.str.startswith("bookings")].set_index("record_id")
    assert ab.index.is_unique and set(b.booking_id) == set(ab.index)
    b["invoice_currency"] = b.booking_id.map(ab.original_currency)
    b["fx_rate"] = b.booking_id.map(ab.fx_rate).astype(float)
    b["fx_rate_filled"] = b.booking_id.map(ab.fx_rate_filled).map({"True": True, "False": False})
    chk = (b.booking_id.map(ab.amount_ngn).astype(float) - num(b.gross_amount_ngn)).abs()
    assert (chk < 0.01).all(), "audit amount != booking gross"
    fct_booking = pd.DataFrame({
        "booking_key": np.arange(1, len(b) + 1), "booking_id": code_to_int(b.booking_id),
        "booking_code": b.booking_id, "client_key": b.client_id.map(client_key).astype("Int64"),
        "service_key": b.service_type.map(service_key), "shoot_date": b.shoot_date,
        "shoot_days": num(b.shoot_days).astype("Int64"), "location_city": nn(b.location_city),
        "status": b.status, "lead_source": nn(b.lead_source), "vat_applied": boolean(b.get("vat_applied", pd.Series(dtype=str)).reindex(b.index).fillna("")),
        "invoice_currency": b.invoice_currency, "fx_rate": b.fx_rate, "fx_rate_filled": b.fx_rate_filled,
        "gross_amount_ngn": num(b.gross_amount_ngn), "discount_pct": num(b.discount_pct),
        "net_amount_ngn": num(b.net_amount_ngn), "is_cancelled": b.status == "Cancelled",
        "source_file": b.source_file, "dq_flags": nn(b.dq_flags.replace("No issues", "")),
    })
    assert fct_booking.client_key.notna().all() and fct_booking.service_key.notna().all()
    T["core.fct_booking"] = fct_booking
    booking_key = dict(zip(b.booking_id, fct_booking.booking_key))
    decide("W-BK-1", "Booking money is stored in NGN only. invoice_currency and fx_rate record how a USD/GBP job "
                     "was converted (rate on the shoot date), so the FX question can be answered without keeping "
                     "foreign-currency amounts in the fact.",
           f"{(b.invoice_currency != 'NGN').sum()} bookings were invoiced in USD/GBP "
           f"({dict(Counter(b.invoice_currency))}).")
    decide("W-BK-2", "Production revenue = net_amount_ngn of every booking whose status is not Cancelled, dated "
                     "by shoot_date. Postponed and blank-status jobs count, matching the brief's definition.",
           f"{(b.status == 'Postponed').sum()} Postponed and {(b.status == UNKNOWN).sum()} blank-status bookings "
           "are included; the sensitivity is reported in the analysis.")

    # -------------------------------------------------------------- fct_crew_day
    t = read(clean, "crew_timesheets.csv")
    rate = num(t.day_rate_charged_ngn)
    std = t.crew_id.map(crew_rate)
    fct_crew_day = pd.DataFrame({
        "crew_day_key": np.arange(1, len(t) + 1), "timesheet_id": num(t.timesheet_id).astype(int),
        "booking_key": t.booking_id.map(booking_key), "crew_key": t.crew_id.map(crew_key),
        "work_date": t.work_date, "hours_worked": num(t.hours_worked), "role_on_job": nn(t.role_on_job),
        "day_rate_charged_ngn": rate, "labour_cost_ngn": rate.fillna(std),
        "rate_is_estimated": rate.isna(), "is_overtime": boolean(t.overtime),
        "hours_flag": np.select([t.dq_flags.str.contains("26h"), t.dq_flags.str.contains("above_12h"),
                                 t.dq_flags.str.contains("hours_missing")],
                                ["impossible_26h_blanked", "above_12h_policy_cap", "hours_missing"], None),
        "dq_flags": nn(t.dq_flags.replace("No issues", "")),
    })
    assert fct_crew_day.booking_key.notna().all() and fct_crew_day.crew_key.notna().all()
    assert fct_crew_day.labour_cost_ngn.notna().all()
    T["core.fct_crew_day"] = fct_crew_day
    known = t[rate.notna()]
    ratio = (num(known.day_rate_charged_ngn) / known.crew_id.map(crew_rate)).round(2)
    mult = ratio.value_counts(normalize=True).sort_index()
    ot = pd.crosstab(ratio, known.overtime, normalize="columns").round(3)
    decide("W-TS-1", "Labour cost of a timesheet row = day_rate_charged_ngn; where the charged rate was never "
                     "recorded it is estimated at the crew member's standard day rate and rate_is_estimated is TRUE.",
           f"{rate.isna().sum()} rows ({rate.isna().mean():.1%}) have no charged rate. Where it is recorded the "
           f"charged rate is 0.5x / 1x / 1.5x the standard rate in {mult.round(3).to_dict()} of rows, and that multiplier "
           f"is unrelated to the overtime flag (share by overtime flag: {ot.to_dict()}) or to hours, so the "
           "multiplier cannot be recovered; the standard rate is the unbiased estimate (expected multiplier "
           f"{(mult * mult.index).sum():.3f}). The dictionary's '1.5x for overtime days' is false.")

    # --------------------------------------------------- fct_merch_line + refunds
    o = read(clean, "merch_orders.csv")
    o["ts"] = pd.to_datetime(o.order_ts_utc, utc=True)
    o["date_lagos"] = (o.ts + pd.Timedelta(hours=1)).dt.tz_localize(None).dt.normalize()
    o["qty"] = num(o.quantity).astype(int)
    o["price"] = num(o.unit_price_ngn)
    o["_i"] = np.arange(len(o))
    m = o[["_i", "sku", "date_lagos"]].merge(prod[["product_key", "sku", "vf", "vt", "list_price_ngn", "unit_cost_ngn"]],
                                             on="sku", how="left")
    m = m[(m.date_lagos >= m.vf) & (m.date_lagos <= m.vt)].set_index("_i").sort_index()
    assert m.index.is_unique and len(m) == len(o), "every order line must hit exactly one product version"
    o["product_key"] = m.product_key
    o["list_value"] = o.qty * m.list_price_ngn
    o["gross"] = o.qty * o.price
    assert (o.gross - num(o.line_gross_ngn)).abs().max() < 0.01
    o["cogs"] = o.qty * m.unit_cost_ngn
    o["is_revenue"] = o.order_status != "Cancelled"
    o["order_num"] = code_to_int(o.order_id).astype(int)

    rf = read(clean, "merch_refunds.csv")
    rf["amt"] = num(rf.refund_amount_ngn)
    rf["order_num"] = code_to_int(rf.order_id).astype(int)
    order_status = o.groupby("order_num").order_status.agg(lambda x: "|".join(sorted(set(x))))
    rf["order_status"] = rf.order_num.map(order_status)
    assert rf.order_status.notna().all()
    rec = o[o.is_revenue].groupby("order_num").gross.sum()
    pos = o[o.is_revenue].assign(g=lambda d: d.gross.clip(lower=0)).groupby("order_num").g.sum()
    # refunds on cancelled orders reverse money that is not in revenue; refunds on revenue orders are
    # deducted, capped at the order's recognised value
    rf = rf.sort_values(["order_num", "refund_date", "refund_key"]).reset_index(drop=True)
    rf["on_revenue"] = rf.order_num.isin(rec.index)
    cap = rf.order_num.map(pos).fillna(0)
    rf["cum_before"] = rf.groupby("order_num").amt.cumsum() - rf.amt
    rf["counted"] = np.where(rf.on_revenue, np.clip(cap - rf.cum_before, 0, rf.amt), 0.0)
    over = rf[rf.on_revenue & (rf.counted < rf.amt)]
    counted_by_order = rf.groupby("order_num").counted.sum()
    o["refunded"] = 0.0
    rv = o.is_revenue & (o.gross > 0)
    share = o.loc[rv, "gross"] / o.loc[rv, "order_num"].map(pos)
    o.loc[rv, "refunded"] = (share * o.loc[rv, "order_num"].map(counted_by_order).fillna(0)).round(6)
    assert abs(o.refunded.sum() - rf.counted.sum()) < 1, (o.refunded.sum(), rf.counted.sum())
    o["net"] = np.where(o.is_revenue, o.gross - o.refunded, 0.0)
    T["core.fct_merch_line"] = pd.DataFrame({
        "order_line_key": np.arange(1, len(o) + 1), "order_id": o.order_num, "line_no": num(o.line_no).astype(int),
        "order_ts": o.order_ts_utc, "order_date_lagos": o.date_lagos.dt.date,
        "client_key": o.client_id.map(client_key).astype("Int64"), "product_key": o.product_key.astype(int),
        "quantity": o.qty, "unit_price_ngn": o.price, "list_value_ngn": o.list_value.round(2),
        "gross_ngn": o.gross.round(2), "discount_ngn": (o.list_value - o.gross).round(2), "cogs_ngn": o.cogs.round(2),
        "discount_code": nn(o.discount_code), "sales_channel": nn(o.sales_channel),
        "payment_method": nn(o.payment_method), "order_status": o.order_status, "is_revenue": o.is_revenue,
        "refunded_ngn": o.refunded.round(2), "net_ngn": pd.Series(o.net).round(2),
        "dq_flags": nn(o.dq_flags.replace("No issues", "")),
    })
    assert (o.client_id.isin(["Guest"]) | o.client_id.isin(client_key)).all()
    T["core.fct_refund"] = pd.DataFrame({
        "refund_key": rf.refund_key, "refund_id": rf.refund_id, "order_id": rf.order_num,
        "refund_date": nn(rf.refund_date), "refund_amount_ngn": rf.amt, "counted_ngn": rf.counted.round(2),
        "reason": nn(rf.reason), "processed_by": nn(rf.processed_by), "order_status": rf.order_status,
        "dq_flags": nn(rf.dq_flags.replace("No issues", "")),
    })

    by_code = o.groupby(o.discount_code).apply(lambda d: (d.price / (d.list_value / d.qty)).median(),
                                              include_groups=False).round(3)
    pend = o[o.order_status == "Pending"]
    decide("W-MER-1", "Merch revenue = quantity x unit_price (the price paid) on every line whose order is not "
                      "Cancelled, less refunds. Pending, Shipped, Fulfilled, Delivered and Returned lines count.",
           f"Cancelled lines are excluded ({(~o.is_revenue).sum():,} lines, NGN {o.loc[~o.is_revenue, 'gross'].sum():,.0f}). "
           f"Pending lines are kept ({len(pend):,} lines, NGN {pend.gross.sum():,.0f}); excluding them would lower "
           "merch revenue by that amount - reported as a sensitivity.")
    decide("W-MER-2", "Refunds on Cancelled orders are not deducted (the sale was never counted). Refunds on other "
                      "orders are deducted, capped at the order's recognised value, and allocated to its lines in "
                      "proportion to line value.",
           f"Refunds by order status: {dict(Counter(rf.order_status))}; every refund belongs to a Cancelled or "
           f"Returned order. {len(over)} refunds exceed what is left of their order's value; "
           f"NGN {(over.amt - over.counted).sum():,.0f} above the cap is not deducted.")
    decide("W-MER-3", "Discount value = list value (quantity x list price in force on the order's Lagos date, from "
                      "the resolved SCD) minus price paid. Discount codes are carried as attributes but no "
                      "percentage is inferred from their names.",
           f"Median price-paid / list-price ratio by code: {by_code.to_dict()}. Codes do not lower the price "
           "paid, so either they were not honoured or the discount was never written to the export; applying "
           "name-implied percentages would invent a deduction the data does not show.")
    decide("W-MER-4", "Each order line joins the product version whose validity window contains the order's "
                      "Africa/Lagos calendar date.",
           f"All {len(o):,} lines match exactly one version (asserted on every run).")

    # ----------------------------------------------------------------- fct_session
    order_ids = set(o.order_id)
    tx = nn(s.transaction_id)
    s_order = tx.where(tx.isin(order_ids)).map(lambda v: None if v is None or pd.isna(v) else int(v[3:]))
    T["core.fct_session"] = pd.DataFrame({
        "session_id": s.session_id, "session_start_utc": s.session_start_utc,
        "session_date_lagos": s.session_date_lagos, "visitor_id": nn(s.visitor_id),
        "channel_key": s.channel.map(group_to_key), "utm_group": s.channel, "utm_source": nn(s.source),
        "medium": nn(s.medium), "campaign": nn(s.campaign), "device": nn(s.device), "country": nn(s.country),
        "landing_page": nn(s.landing_page), "page_views": num(s.page_views).astype("Int64"),
        "duration_seconds": num(s.duration_seconds).astype("Int64"), "is_new_visitor": boolean(s.is_new_visitor),
        "is_bot": boolean(s.is_bot), "is_spam": boolean(s.is_spam), "converted": boolean(s.converted),
        "transaction_id": tx, "order_id": s_order.astype("Int64"), "revenue_ngn": num(s.revenue_ngn),
        "source_file": s.source_file,
    })

    # --------------------------------------------------------------- fct_ad_spend
    sp = read(clean, "marketing_spend.csv")
    assert (sp.currency == "NGN").all()
    T["core.fct_ad_spend"] = pd.DataFrame({
        "spend_date": sp.spend_date, "channel_key": sp.channel.map(spend_to_key), "campaign": sp.campaign,
        "session_campaign": sp.campaign.map(lambda v: CAMPAIGN_MAP.get(v, v)),
        "impressions": num(sp.impressions).astype("Int64"), "clicks": num(sp.clicks).astype("Int64"),
        "spend_ngn": num(sp.spend_ngn),
    })
    sess_c, spend_c = set(s.campaign) - {NA}, set(sp.campaign)
    decide("W-CH-2", "Ad-spend campaign names map to session campaign names by exact match, except "
                     "'always_on' = 'brand_always_on'.",
           f"Spend-only campaigns before mapping: {sorted(spend_c - sess_c)}; session-only: {sorted(sess_c - spend_c)}. "
           "'blackfriday24' and 'black_friday' exist on both sides with their own spend and sessions, so they "
           "stay separate.")

    # ------------------------------------------------------------- quarantine
    q = pd.read_csv(report / "quarantine_rejected_rows.csv", dtype=str, keep_default_na=False)
    gross_by_bk = dict(zip(b.booking_id, num(b.gross_amount_ngn)))
    val, affected = [], []
    for r in q.itertuples():
        pl = json.loads(r.payload)
        v, hit = None, False
        if r.src_table == "bookings" and r.reason in ("exact_duplicate_booking", "duplicate_booking_conflicting_vat_flag"):
            v = gross_by_bk.get(norm_prefixed_id(pl.get("booking_id") or pl.get("booking_ref"), "BK"))
        elif r.src_table == "crew_timesheets":
            v = parse_money(pl.get("day_rate_charged"))[0]
        elif r.src_table == "merch_orders":
            qty = pd.to_numeric(pl.get("quantity"), errors="coerce")
            price = parse_money(pl.get("unit_price"))[0]
            if r.reason == "placeholder_quantity_9999":
                v, hit = price, True            # true quantity unknown: at least one unit of value is missing
            elif price is not None and qty == qty:
                v = float(qty) * price
                hit = r.reason == "orphan_client_id"
        elif r.src_table == "merch_refunds":
            amt = parse_money(pl.get("refund_amount"))[0]
            v, hit = (abs(amt) if amt is not None else None), True
        elif r.src_table == "marketing_spend":
            v = parse_money(pl.get("spend"), allow_decimal_comma=True)[0]
        val.append(v)
        affected.append(hit)
    T["quarantine.rejected_rows"] = pd.DataFrame({
        "src_table": q.src_table, "src_file": q.src_file, "src_row": num(q.src_row).astype("Int64"),
        "reason": q.reason, "detail": nn(q.detail), "payload": q.payload,
        "value_ngn": pd.Series(val, dtype=float).round(2), "revenue_affected": affected,
    })
    decide("W-Q-1", "quarantine.rejected_rows.value_ngn is the money a rejected row carries; revenue_affected marks "
                    "rows whose value is genuinely missing from revenue (orphan-client order lines, 9999-quantity "
                    "placeholders valued at one unit, orphan and quarantined-order refunds). Duplicates and Excel "
                    "subtotal rows are not revenue at risk: their value is already counted once.",
           f"{len(q):,} rejected rows loaded.")
    return T


LOAD_ORDER = ["stg.merch_products", "core.dim_date", "core.dim_client", "core.dim_service", "core.dim_crew",
              "core.dim_product", "core.dim_channel", "core.fx_daily", "core.fct_booking", "core.fct_crew_day",
              "core.fct_merch_line", "core.fct_refund", "core.fct_session", "core.fct_ad_spend",
              "quarantine.rejected_rows"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--schema", type=Path, default=HERE.parent / "sql" / "01_schema.sql")
    a = ap.parse_args()

    T = build(a.clean, a.report, a.raw)
    con = psycopg2.connect(DSN)
    with con, con.cursor() as cur:
        cur.execute(a.schema.read_text())
        for name in LOAD_ORDER:
            copy(cur, name, T[name])
            cur.execute(f"SELECT count(*) FROM {name}")
            n = cur.fetchone()[0]
            assert n == len(T[name]), (name, n, len(T[name]))
            print(f"  {name:<28} {n:>9,} rows")
        for seq_table, col in [("core.dim_client", "client_key"), ("core.dim_service", "service_key"),
                               ("core.dim_crew", "crew_key"), ("core.dim_product", "product_key"),
                               ("core.dim_channel", "channel_key"), ("core.fct_booking", "booking_key"),
                               ("core.fct_crew_day", "crew_day_key"), ("core.fct_merch_line", "order_line_key")]:
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{seq_table}','{col}'), (SELECT max({col}) FROM {seq_table}))")
        cur.execute("ANALYZE")
    con.close()

    lines = ["# Warehouse decisions", "",
             "Decisions taken when loading the cleaned layer into the star schema. Cleaning decisions are in "
             "`cleaning_report/CLEANING_DECISIONS.md`.", "", "| ID | Rule | Evidence and impact |", "|---|---|---|"]
    lines += [f"| {c} | {r} | {e} |" for c, r, e in DECISIONS]
    (HERE / "WAREHOUSE_DECISIONS.md").write_text("\n".join(lines) + "\n")
    print("warehouse loaded")


if __name__ == "__main__":
    main()
