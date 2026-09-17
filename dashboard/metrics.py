"""Metric definitions shared by the dashboard and its tie-out test.

Every function takes the extracts plus a Filters object and returns a DataFrame or a number.
Definitions match sql/02_questions_answered.sql exactly (tests/test_tie_out.py proves it).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
SERVICES = ["Wedding Film", "Photoshoot", "Event Coverage", "Music Video", "Studio Rental", "Commercial / TVC",
            "Corporate Documentary", "Short Film", "Unknown"]
CHANNELS = ["Google", "Meta", "TikTok", "YouTube", "Email", "Influencer", "Direct", "Referral / Other"]


@dataclass
class Filters:
    start: pd.Timestamp = pd.Timestamp("2023-01-01")
    end: pd.Timestamp = pd.Timestamp("2025-06-30")
    services: list[str] = field(default_factory=lambda: list(SERVICES))
    channels: list[str] = field(default_factory=lambda: list(CHANNELS))


def load(data_dir: Path = DATA) -> dict[str, pd.DataFrame]:
    return {p.stem: pd.read_parquet(p) for p in data_dir.glob("*.parquet")}


def _in(df, col, f: Filters):
    return df[(df[col] >= f.start) & (df[col] <= f.end)]


def quarter(s: pd.Series) -> pd.Series:
    return s.dt.year.astype(str) + "Q" + s.dt.quarter.astype(str)


# ------------------------------------------------------------------ production
def live_bookings(d, f: Filters):
    b = _in(d["bookings"], "shoot_date", f)
    return b[~b.is_cancelled & b.service_name.isin(f.services)]


def production_by_quarter(d, f):
    b = live_bookings(d, f)
    return b.groupby(quarter(b.shoot_date)).net_amount_ngn.sum().rename("production_revenue_ngn")


def service_summary(d, f):
    b = live_bookings(d, f)
    c = d["crew_days"]
    lab = c.groupby("booking_code").labour_cost_ngn.sum()
    b = b.assign(labour_ngn=b.booking_code.map(lab).fillna(0))
    b["loss"] = b.net_amount_ngn < b.labour_ngn
    out = b.groupby("service_name").agg(jobs=("booking_code", "size"), revenue_ngn=("net_amount_ngn", "sum"),
                                        labour_ngn=("labour_ngn", "sum"), loss_jobs=("loss", "sum")).reset_index()
    out["labour_margin_pct"] = 100 * (out.revenue_ngn - out.labour_ngn) / out.revenue_ngn
    out["revenue_share_pct"] = 100 * out.revenue_ngn / out.revenue_ngn.sum()
    return out.sort_values("revenue_ngn", ascending=False)


def jobs_by_month(d, f):
    b = live_bookings(d, f)
    return b.groupby(b.shoot_date.dt.to_period("M").dt.to_timestamp()).size().rename("jobs").reset_index()


def status_mix(d, f):
    b = live_bookings(d, f)
    return b.groupby("status").net_amount_ngn.sum().sort_values(ascending=False).reset_index()


# ------------------------------------------------------------------ merch
def merch_lines(d, f):
    return _in(d["merch_lines"], "order_date_lagos", f)


def merch_by_quarter(d, f):
    m = merch_lines(d, f)
    return m.groupby(quarter(m.order_date_lagos)).net_ngn.sum().rename("merch_net_revenue_ngn")


def collection_summary(d, f):
    m = merch_lines(d, f)
    m = m[m.is_revenue]
    out = m.groupby("collection").agg(units=("quantity", "sum"), gross_ngn=("gross_ngn", "sum"),
                                      refunds_ngn=("refunded_ngn", "sum"), net_ngn=("net_ngn", "sum"),
                                      cogs_ngn=("cogs_ngn", "sum")).reset_index()
    out["contribution_ngn"] = out.net_ngn - out.cogs_ngn
    out["margin_pct"] = 100 * out.contribution_ngn / out.net_ngn
    out["refund_rate_pct"] = 100 * out.refunds_ngn / out.gross_ngn
    return out.sort_values("net_ngn", ascending=False)


def refund_reasons(d, f):
    r = _in(d["refunds"], "order_date_lagos", f)
    out = r.groupby("reason").agg(refunds=("refund_key", "size"), amount_ngn=("refund_amount_ngn", "sum")).reset_index()
    out["share_pct"] = 100 * out.refunds / out.refunds.sum()
    return out.sort_values("refunds", ascending=False)


# ------------------------------------------------------------------ acquisition
def human_sessions(d, f):
    s = _in(d["sessions"], "session_date_lagos", f)
    return s[~s.is_bot & s.channel_name.isin(f.channels)]


def channel_summary(d, f):
    s = human_sessions(d, f)
    a = _in(d["ad_spend"], "spend_date", f)
    a = a[a.channel_name.isin(f.channels)]
    ses = s.groupby("channel_name").agg(sessions=("converted", "size"), conversions=("converted", "sum"),
                                        revenue_ngn=("revenue_ngn", "sum"), joined=("joins_order", "sum"))
    sp = a.groupby("channel_name").agg(spend_ngn=("spend_ngn", "sum"), clicks=("clicks", "sum"))
    out = ses.join(sp, how="outer").fillna(0).reset_index()
    out["conversion_rate_pct"] = 100 * out.conversions / out.sessions.where(out.sessions > 0)
    out["cpc_ngn"] = out.spend_ngn / out.clicks.where(out.clicks > 0)
    out["cac_ngn"] = (out.spend_ngn / out.conversions.where(out.conversions > 0)).where(out.spend_ngn > 0)
    out["roas"] = out.revenue_ngn / out.spend_ngn.where(out.spend_ngn > 0)
    out["order"] = out.channel_name.map({c: i for i, c in enumerate(CHANNELS)})
    return out.sort_values("order").drop(columns="order")


def channel_by_quarter(d, f):
    s = human_sessions(d, f)
    a = _in(d["ad_spend"], "spend_date", f)
    a = a[a.channel_name.isin(f.channels)]
    ses = s.groupby([quarter(s.session_date_lagos).rename("quarter"), "channel_name"]).agg(
        sessions=("converted", "size"), conversions=("converted", "sum"), revenue_ngn=("revenue_ngn", "sum"))
    sp = a.groupby([quarter(a.spend_date).rename("quarter"), "channel_name"]).agg(spend_ngn=("spend_ngn", "sum"))
    out = ses.join(sp, how="outer").fillna(0).reset_index()
    out["roas"] = out.revenue_ngn / out.spend_ngn.where(out.spend_ngn > 0)
    return out


def attribution(d, f):
    s = _in(d["sessions"], "session_date_lagos", f)
    s = s[~s.is_bot & s.converted & s.channel_name.isin(f.channels)]
    un = s[~s.joins_order]
    return {"converted": len(s), "joined": int(s.joins_order.sum()),
            "joined_pct": 100 * s.joins_order.mean() if len(s) else float("nan"),
            "unattributed_revenue_ngn": float(un.revenue_ngn.sum())}


def traffic_quality(d, f):
    s = _in(d["sessions"], "session_date_lagos", f)
    return {"sessions": len(s), "bots": int(s.is_bot.sum()), "spam": int(s.is_spam.sum()),
            "human": int((~s.is_bot).sum())}


# ------------------------------------------------------------------ data quality tile
RAW_ROWS = 282171   # rows across all 14 raw files (header and structural rows included for the workbook)


def data_quality(d, f):
    q = d["quarantine"]
    b = live_bookings(d, Filters())
    unresolved = b[(b.service_name == "Unknown") | (b.status == "Unknown")].net_amount_ngn.sum()
    total = production_by_quarter(d, Filters()).sum() + merch_by_quarter(d, Filters()).sum()
    at_risk = q.loc[q.revenue_affected, "value_ngn"].sum()
    return {"rows_quarantined": len(q), "rows_quarantined_pct": 100 * len(q) / RAW_ROWS,
            "revenue_affected_ngn": float(at_risk + unresolved),
            "revenue_affected_pct": 100 * (at_risk + unresolved) / total,
            "by_table": q.groupby(["src_table", "reason"]).size().rename("rows").reset_index()}
