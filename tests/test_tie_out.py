"""Tie-out: the dashboard's numbers must equal the SQL answers and the findings file exactly.

    python -m pytest tests -q
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
import metrics as M  # noqa: E402

D = M.load()
F = M.Filters()
R = ROOT / "results"
FIND = json.loads((ROOT / "analysis" / "findings.json").read_text())


def close(a, b, tol=1.0):
    return abs(float(a) - float(b)) <= tol


def test_q1_quarterly_revenue_ties():
    q1 = pd.read_csv(R / "q01.csv").set_index("quarter")
    prod, merch = M.production_by_quarter(D, F), M.merch_by_quarter(D, F)
    for qtr, row in q1.iterrows():
        assert close(prod.get(qtr, 0), row.production_revenue_ngn), qtr
        assert close(merch.get(qtr, 0), row.merch_net_revenue_ngn), qtr


def test_service_totals_tie():
    svc = M.service_summary(D, F).set_index("service_name")
    t = pd.read_csv(ROOT / "analysis" / "tables" / "margin_by_service.csv").set_index("service_name")
    for name, row in t.iterrows():
        assert svc.loc[name, "jobs"] == row.jobs
        assert close(svc.loc[name, "revenue_ngn"], row.revenue_ngn, 0.5)
        assert close(svc.loc[name, "labour_ngn"], row.labour_ngn, 0.5)
        assert svc.loc[name, "loss_jobs"] == row.loss_jobs


def test_collections_tie_to_q7():
    q7 = pd.read_csv(R / "q07.csv").set_index("collection")
    col = M.collection_summary(D, F).set_index("collection")
    for name, row in q7.iterrows():
        assert col.loc[name, "units"] == row.units_sold
        assert close(col.loc[name, "net_ngn"], row.net_ngn)
        assert close(col.loc[name, "cogs_ngn"], row.cogs_ngn)


def test_channels_tie_to_q9():
    q9 = pd.read_csv(R / "q09.csv").groupby("channel_name")[["sessions", "conversions", "revenue_ngn", "spend_ngn"]].sum()
    ch = M.channel_summary(D, F).set_index("channel_name")
    for name, row in q9.iterrows():
        assert ch.loc[name, "sessions"] == row.sessions
        assert ch.loc[name, "conversions"] == row.conversions
        assert close(ch.loc[name, "revenue_ngn"], row.revenue_ngn, 5)
        assert close(ch.loc[name, "spend_ngn"], row.spend_ngn, 5)


def test_attribution_ties_to_q10():
    q10 = pd.read_csv(R / "q10.csv").set_index("scope").loc["human converted sessions"]
    at = M.attribution(D, F)
    assert at["converted"] == q10.converted_sessions and at["joined"] == q10.joined_to_real_order
    assert close(at["unattributed_revenue_ngn"], q10.unattributed_revenue_ngn)


def test_data_quality_tile_ties():
    dq = M.data_quality(D, F)
    f = FIND["data_quality"]
    assert dq["rows_quarantined"] == f["rows_quarantined"]
    assert close(dq["revenue_affected_ngn"], f["revenue_affected_ngn"], 5)
    assert M.RAW_ROWS == f["raw_rows"]


def test_traffic_counts():
    tq = M.traffic_quality(D, F)
    assert tq["sessions"] == 203046 and tq["human"] == FIND["marketing"]["human_sessions"]
    assert tq["bots"] == FIND["marketing"]["bot_sessions"] and tq["spam"] == 5200


def test_every_money_value_is_ngn():
    b = D["bookings"]
    assert b.net_amount_ngn.notna().all()
    for name, df in D.items():
        for c in df.columns:
            if df[c].dtype == object:
                assert not df[c].astype(str).str.contains(r"\$|£|€|\bUSD\b|\bGBP\b|\bEUR\b", regex=True).any() \
                    or c == "invoice_currency", (name, c)
