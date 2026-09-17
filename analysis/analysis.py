"""Phase 4 analysis: every headline number, computed from the warehouse (core.*).

    python analysis/analysis.py

Writes analysis/findings.json (every number quoted in the memo, deck and dashboard) and
analysis/tables/*.csv (the tables beneath every chart). Nothing here is typed in by hand:
if a number appears in a deliverable, it comes from this file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis"
TABLES = OUT / "tables"
DSN = os.environ.get("XTRIM_DSN", "host=localhost port=55432 dbname=xtrim user=xtrim")
F: dict = {}


def q(con, sql: str) -> pd.DataFrame:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql_query(sql, con)


def save(name: str, df: pd.DataFrame):
    df.to_csv(TABLES / f"{name}.csv", index=False)
    return df


def r0(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else int(round(float(x)))


def r1(x, n=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def main():
    TABLES.mkdir(parents=True, exist_ok=True)
    con = psycopg2.connect(DSN)

    # ============================================================ 1. revenue mix and trend
    q1 = pd.read_csv(ROOT / "results" / "q01.csv")
    usd = q(con, """
        SELECT d.year_quarter AS quarter, AVG(f.rate) AS usd_rate
        FROM core.fx_daily f JOIN core.dim_date d ON d.date_key = f.rate_date
        WHERE f.from_currency = 'USD' AND f.rate_date BETWEEN '2023-01-01' AND '2025-06-30' GROUP BY 1""")
    const = q(con, """
        WITH base AS (SELECT from_currency, rate FROM core.fx_daily WHERE rate_date = '2023-01-01')
        SELECT d.year_quarter AS quarter,
               SUM(CASE WHEN b.invoice_currency = 'NGN' THEN b.net_amount_ngn
                        ELSE b.net_amount_ngn / b.fx_rate * base.rate END) AS production_constant_fx_ngn
        FROM core.fct_booking b JOIN core.dim_date d ON d.date_key = b.shoot_date
        LEFT JOIN base ON base.from_currency = b.invoice_currency
        WHERE NOT b.is_cancelled GROUP BY 1""")
    rev = q1.merge(usd, on="quarter").merge(const, on="quarter")
    rev["total_ngn"] = rev.production_revenue_ngn + rev.merch_net_revenue_ngn
    rev["merch_share_pct"] = 100 * rev.merch_net_revenue_ngn / rev.total_ngn
    rev["total_usd_equivalent"] = rev.total_ngn / rev.usd_rate
    rev["ngn_index"] = 100 * rev.total_ngn / rev.total_ngn.iloc[:4].mean()          # 2023 quarterly average = 100
    rev["usd_index"] = 100 * rev.total_usd_equivalent / rev.total_usd_equivalent.iloc[:4].mean()
    save("revenue_by_quarter", rev.round(2))

    yr = rev.assign(year=rev.quarter.str[:4]).groupby("year").agg(
        production=("production_revenue_ngn", "sum"), merch=("merch_net_revenue_ngn", "sum"),
        total=("total_ngn", "sum"), usd=("total_usd_equivalent", "sum")).reset_index()
    h1 = rev[rev.quarter.str[-1].isin(["1", "2"])].assign(year=lambda d: d.quarter.str[:4]).groupby("year").agg(
        total=("total_ngn", "sum"), usd=("total_usd_equivalent", "sum")).reset_index()
    save("revenue_by_year", yr.round(0))
    F["revenue"] = {
        "total_ngn_2023": r0(yr.total[0]), "total_ngn_2024": r0(yr.total[1]), "total_ngn_h1_2025": r0(yr.total[2]),
        "production_ngn_2023": r0(yr.production[0]), "production_ngn_2024": r0(yr.production[1]),
        "production_ngn_h1_2025": r0(yr.production[2]),
        "merch_ngn_2023": r0(yr.merch[0]), "merch_ngn_2024": r0(yr.merch[1]), "merch_ngn_h1_2025": r0(yr.merch[2]),
        "growth_ngn_2024_vs_2023_pct": r1(100 * (yr.total[1] / yr.total[0] - 1)),
        "usd_equiv_2023": r0(yr.usd[0]), "usd_equiv_2024": r0(yr.usd[1]), "usd_equiv_h1_2025": r0(yr.usd[2]),
        "growth_usd_2024_vs_2023_pct": r1(100 * (yr.usd[1] / yr.usd[0] - 1)),
        "growth_ngn_h1_2025_vs_h1_2024_pct": r1(100 * (h1.total[2] / h1.total[1] - 1)),
        "growth_usd_h1_2025_vs_h1_2024_pct": r1(100 * (h1.usd[2] / h1.usd[1] - 1)),
        "merch_share_pct_all": r1(100 * rev.merch_net_revenue_ngn.sum() / rev.total_ngn.sum()),
        "total_ngn_all": r0(rev.total_ngn.sum()),
        "usd_rate_avg_2023": r1(q(con, "SELECT AVG(rate) r FROM core.fx_daily WHERE from_currency='USD' AND rate_date BETWEEN '2023-01-01' AND '2023-12-31'").r[0]),
        "usd_rate_avg_2024": r1(q(con, "SELECT AVG(rate) r FROM core.fx_daily WHERE from_currency='USD' AND rate_date BETWEEN '2024-01-01' AND '2024-12-31'").r[0]),
        "usd_rate_avg_h1_2025": r1(q(con, "SELECT AVG(rate) r FROM core.fx_daily WHERE from_currency='USD' AND rate_date BETWEEN '2025-01-01' AND '2025-06-30'").r[0]),
        "constant_fx_production_all_ngn": r0(rev.production_constant_fx_ngn.sum()),
    }

    svc = q(con, """
        SELECT s.service_name, COUNT(*) AS jobs, SUM(b.net_amount_ngn) AS revenue_ngn,
               AVG(b.net_amount_ngn) AS avg_job_ngn
        FROM core.fct_booking b JOIN core.dim_service s USING (service_key)
        WHERE NOT b.is_cancelled GROUP BY 1 ORDER BY revenue_ngn DESC""")
    svc["revenue_share_pct"] = 100 * svc.revenue_ngn / svc.revenue_ngn.sum()
    svc["job_share_pct"] = 100 * svc.jobs / svc.jobs.sum()
    save("revenue_by_service", svc.round(2))
    s = svc.set_index("service_name")
    top2 = s.loc[["Commercial / TVC", "Music Video"]]
    F["services"] = {
        "tvc_mv_revenue_share_pct": r1(top2.revenue_share_pct.sum()), "tvc_mv_job_share_pct": r1(top2.job_share_pct.sum()),
        "wedding_jobs": r0(s.loc["Wedding Film", "jobs"]), "wedding_revenue_share_pct": r1(s.loc["Wedding Film", "revenue_share_pct"]),
        "studio_rental_job_share_pct": r1(s.loc["Studio Rental", "job_share_pct"]),
        "studio_rental_revenue_share_pct": r1(s.loc["Studio Rental", "revenue_share_pct"]),
        "photoshoot_job_share_pct": r1(s.loc["Photoshoot", "job_share_pct"]),
        "photoshoot_revenue_share_pct": r1(s.loc["Photoshoot", "revenue_share_pct"]),
        "unknown_service_jobs": r0(s.loc["Unknown", "jobs"]), "unknown_service_revenue_ngn": r0(s.loc["Unknown", "revenue_ngn"]),
        "non_cancelled_jobs": r0(svc.jobs.sum()),
        "production_revenue_all_ngn": r0(svc.revenue_ngn.sum()),
    }

    status = q(con, """
        SELECT EXTRACT(YEAR FROM shoot_date)::int AS year, status, COUNT(*) AS jobs, SUM(net_amount_ngn) AS revenue_ngn
        FROM core.fct_booking WHERE NOT is_cancelled GROUP BY 1, 2 ORDER BY 1, 2""")
    status["share_of_year_revenue_pct"] = 100 * status.revenue_ngn / status.groupby("year").revenue_ngn.transform("sum")
    save("production_revenue_by_status", status.round(2))
    open_ = status[status.status.isin(["Invoiced", "In Production", "Postponed", "Unknown"])]
    F["status"] = {
        "not_completed_revenue_ngn_all": r0(open_.revenue_ngn.sum()),
        "not_completed_share_pct_all": r1(100 * open_.revenue_ngn.sum() / status.revenue_ngn.sum()),
        "invoiced_ngn_all": r0(status[status.status == "Invoiced"].revenue_ngn.sum()),
        "postponed_ngn_all": r0(status[status.status == "Postponed"].revenue_ngn.sum()),
        "in_production_ngn_all": r0(status[status.status == "In Production"].revenue_ngn.sum()),
        "postponed_jobs_all": r0(status[status.status == "Postponed"].jobs.sum()),
        "postponed_share_2023_pct": r1(status[(status.year == 2023) & (status.status == "Postponed")].share_of_year_revenue_pct.iloc[0]),
        "postponed_share_2024_pct": r1(status[(status.year == 2024) & (status.status == "Postponed")].share_of_year_revenue_pct.iloc[0]),
        "postponed_share_h1_2025_pct": r1(status[(status.year == 2025) & (status.status == "Postponed")].share_of_year_revenue_pct.iloc[0]),
        "invoiced_2023_jobs": r0(status[(status.year == 2023) & (status.status == "Invoiced")].jobs.iloc[0]),
        "invoiced_2023_ngn": r0(status[(status.year == 2023) & (status.status == "Invoiced")].revenue_ngn.iloc[0]),
        "invoiced_2023_2024_ngn": r0(status[(status.year < 2025) & (status.status == "Invoiced")].revenue_ngn.sum()),
        "invoiced_2023_2024_jobs": r0(status[(status.year < 2025) & (status.status == "Invoiced")].jobs.sum()),
        "cancelled_jobs": r0(q(con, "SELECT COUNT(*) n FROM core.fct_booking WHERE is_cancelled").n[0]),
        "cancelled_gross_ngn": r0(q(con, "SELECT SUM(net_amount_ngn) n FROM core.fct_booking WHERE is_cancelled").n[0]),
    }

    # ============================================================ 2. job-level profitability
    jobs = q(con, """
        WITH clash AS (SELECT crew_key, work_date FROM core.fct_crew_day GROUP BY 1, 2 HAVING COUNT(DISTINCT booking_key) > 1),
        l AS (
            SELECT f.booking_key, SUM(f.labour_cost_ngn) AS labour_ngn,
                   SUM(CASE WHEN c.crew_key IS NOT NULL THEN 0 WHEN f.rate_is_estimated THEN 0.5 * f.labour_cost_ngn
                            ELSE f.labour_cost_ngn END) AS trusted_min_labour_ngn,
                   COUNT(*) AS crew_rows, COUNT(DISTINCT f.work_date) AS work_days
            FROM core.fct_crew_day f LEFT JOIN clash c USING (crew_key, work_date) GROUP BY 1)
        SELECT b.booking_code, s.service_name, b.status, b.is_cancelled, b.shoot_date, b.net_amount_ngn,
               COALESCE(l.labour_ngn, 0) AS labour_ngn, COALESCE(l.trusted_min_labour_ngn, 0) AS trusted_min_labour_ngn,
               COALESCE(l.crew_rows, 0) AS crew_rows, l.work_days
        FROM core.fct_booking b JOIN core.dim_service s USING (service_key) LEFT JOIN l USING (booking_key)""")
    live = jobs[~jobs.is_cancelled].copy()
    live["margin_ngn"] = live.net_amount_ngn - live.labour_ngn
    live["loss"] = live.margin_ngn < 0
    live["genuine_loss"] = live.loss & (live.net_amount_ngn - live.trusted_min_labour_ngn < 0)
    live["artefact_loss"] = live.loss & ~live.genuine_loss
    live["no_timesheets"] = live.crew_rows == 0
    save("job_margins", live)
    by = live.groupby("service_name").agg(
        jobs=("booking_code", "size"), revenue_ngn=("net_amount_ngn", "sum"), labour_ngn=("labour_ngn", "sum"),
        loss_jobs=("loss", "sum"), genuine_losses=("genuine_loss", "sum"), artefact_losses=("artefact_loss", "sum"),
        jobs_without_timesheets=("no_timesheets", "sum")).reset_index()
    by["labour_margin_ngn"] = by.revenue_ngn - by.labour_ngn
    by["labour_margin_pct"] = 100 * by.labour_margin_ngn / by.revenue_ngn
    by["loss_job_share_pct"] = 100 * by.loss_jobs / by.jobs
    by = by.sort_values("labour_margin_pct")
    save("margin_by_service", by.round(2))
    b_ = by.set_index("service_name")
    canc = jobs[jobs.is_cancelled]
    F["profitability"] = {
        "worst_service": by.service_name.iloc[0], "worst_service_margin_pct": r1(by.labour_margin_pct.iloc[0]),
        "studio_rental_margin_pct": r1(b_.loc["Studio Rental", "labour_margin_pct"]),
        "studio_rental_loss_jobs": r0(b_.loc["Studio Rental", "loss_jobs"]), "studio_rental_jobs": r0(b_.loc["Studio Rental", "jobs"]),
        "studio_rental_labour_minus_revenue_ngn": r0(-b_.loc["Studio Rental", "labour_margin_ngn"]),
        "photoshoot_margin_pct": r1(b_.loc["Photoshoot", "labour_margin_pct"]),
        "photoshoot_loss_jobs": r0(b_.loc["Photoshoot", "loss_jobs"]), "photoshoot_jobs": r0(b_.loc["Photoshoot", "jobs"]),
        "best_service": by.service_name.iloc[-1], "best_service_margin_pct": r1(by.labour_margin_pct.iloc[-1]),
        "loss_jobs": r0(live.loss.sum()), "genuine_losses": r0(live.genuine_loss.sum()), "artefact_losses": r0(live.artefact_loss.sum()),
        "loss_jobs_total_loss_ngn": r0(-live.loc[live.loss, "margin_ngn"].sum()),
        "overall_labour_margin_pct": r1(100 * (live.net_amount_ngn.sum() - live.labour_ngn.sum()) / live.net_amount_ngn.sum()),
        "labour_total_ngn": r0(q(con, "SELECT SUM(labour_cost_ngn) n FROM core.fct_crew_day").n[0]),
        "labour_on_cancelled_jobs_ngn": r0(canc.labour_ngn.sum()),
        "cancelled_jobs_with_crew": r0((canc.crew_rows > 0).sum()),
        "estimated_labour_ngn": r0(q(con, "SELECT SUM(labour_cost_ngn) n FROM core.fct_crew_day WHERE rate_is_estimated").n[0]),
        "estimated_rows": r0(q(con, "SELECT COUNT(*) n FROM core.fct_crew_day WHERE rate_is_estimated").n[0]),
        "live_jobs_without_timesheets": r0(live.no_timesheets.sum()),
    }

    # ============================================================ 3. seasonality and capacity
    month = q(con, """
        SELECT d.year, d.month, COUNT(*) AS jobs FROM core.fct_booking b JOIN core.dim_date d ON d.date_key = b.shoot_date
        WHERE NOT b.is_cancelled GROUP BY 1, 2 ORDER BY 1, 2""")
    full = month[month.year.isin([2023, 2024])].groupby("month").jobs.sum().reset_index()
    full["avg_jobs_per_year"] = full.jobs / 2
    full["month_name"] = pd.to_datetime(full.month, format="%m").dt.strftime("%b")
    save("jobs_by_month_2023_2024", full)
    save("jobs_by_year_month", month)
    q4 = pd.read_csv(ROOT / "results" / "q04.csv")
    q4["week_start"] = pd.to_datetime(q4.week_start)
    edge = q4.active_crew < 0.9 * q4.active_crew.max()
    core_weeks = q4[~edge]
    save("crew_utilisation_weekly", q4.sort_values("week_start"))
    clash_m = q(con, """
        WITH clash AS (SELECT crew_key, work_date FROM core.fct_crew_day GROUP BY 1, 2 HAVING COUNT(DISTINCT booking_key) > 1)
        SELECT d.year, d.month, COUNT(*) AS double_booked_crew_days
        FROM clash c JOIN core.dim_date d ON d.date_key = c.work_date GROUP BY 1, 2 ORDER BY 1, 2""")
    long_days = q(con, """
        SELECT d.month, COUNT(*) FILTER (WHERE f.hours_worked > 12) AS over_12h, COUNT(f.hours_worked) AS with_hours
        FROM core.fct_crew_day f JOIN core.dim_date d ON d.date_key = f.work_date GROUP BY 1 ORDER BY 1""")
    long_days["over_12h_pct"] = 100 * long_days.over_12h / long_days.with_hours
    save("double_bookings_by_month", clash_m)
    save("long_days_by_month", long_days.round(2))
    cm = clash_m[clash_m.year.isin([2023, 2024])].groupby("month").double_booked_crew_days.sum()
    busiest = core_weeks.sort_values("utilisation", ascending=False).iloc[0]
    roles = q4[~edge].binding_role.value_counts()
    F["capacity"] = {
        "busiest_month": full.sort_values("jobs").month_name.iloc[-1], "second_month": full.sort_values("jobs").month_name.iloc[-2],
        "busiest_month_jobs_2yr": r0(full.jobs.max()), "quietest_month": full.sort_values("jobs").month_name.iloc[0],
        "quietest_month_jobs_2yr": r0(full.jobs.min()),
        "weeks_above_85pct": r0((q4.utilisation > 0.85).sum()), "weeks_measured": r0(len(q4)),
        "peak_utilisation_pct": r1(100 * busiest.utilisation), "peak_week_start": str(busiest.week_start.date()),
        "peak_week_crew_days": r0(busiest.crew_days_booked), "peak_week_active_crew": r0(busiest.active_crew),
        "median_utilisation_pct": r1(100 * core_weeks.utilisation.median()),
        "edge_weeks_excluded": r0(edge.sum()),
        "double_booked_crew_days_total": r0(clash_m.double_booked_crew_days.sum()),
        "double_booked_nov_dec_share_pct": r1(100 * cm.loc[[11, 12]].sum() / cm.sum()),
        "max_double_booked_week": str(q4.sort_values("double_booked_crew_days").week_start.iloc[-1].date()),
        "max_double_booked_week_count": r0(q4.double_booked_crew_days.max()),
        "most_frequent_binding_role": roles.index[0], "binding_role_weeks": r0(roles.iloc[0]),
        "max_role_utilisation_pct": r1(100 * core_weeks.binding_role_utilisation.max()),
        "over_12h_rows_pct": r1(100 * long_days.over_12h.sum() / long_days.with_hours.sum()),
    }

    # ============================================================ 4. FX
    q5 = pd.read_csv(ROOT / "results" / "q05.csv")
    tot = q5[q5.year.isna()].iloc[0]
    fxy = q5[q5.invoice_currency.isna() & q5.year.notna()]
    fx_series = q(con, """
        SELECT rate_date, from_currency, rate, is_filled, is_corrected FROM core.fx_daily
        WHERE from_currency IN ('USD','GBP') ORDER BY 1, 2""")
    save("fx_daily_usd_gbp", fx_series)
    ngn_jobs = q(con, """
        WITH base AS (SELECT rate FROM core.fx_daily WHERE rate_date = '2023-01-01' AND from_currency = 'USD')
        SELECT EXTRACT(YEAR FROM b.shoot_date)::int AS year, SUM(b.net_amount_ngn) AS ngn,
               SUM(b.net_amount_ngn / f.rate) AS usd_at_shoot_date, SUM(b.net_amount_ngn / base.rate) AS usd_at_2023_01_01
        FROM core.fct_booking b JOIN core.fx_daily f ON f.rate_date = b.shoot_date AND f.from_currency = 'USD'
        CROSS JOIN base WHERE NOT b.is_cancelled AND b.invoice_currency = 'NGN' GROUP BY 1 ORDER BY 1""")
    ngn_jobs["usd_lost"] = ngn_jobs.usd_at_2023_01_01 - ngn_jobs.usd_at_shoot_date
    save("fx_exposure_foreign_jobs", q5)
    save("fx_ngn_jobs_usd_erosion", ngn_jobs.round(2))
    rates = q(con, """SELECT from_currency, MIN(rate) FILTER (WHERE rate_date='2023-01-01') AS start_rate,
                              MIN(rate) FILTER (WHERE rate_date='2025-06-30') AS end_rate FROM core.fx_daily GROUP BY 1""").set_index("from_currency")
    F["fx"] = {
        "foreign_jobs": r0(tot.jobs), "value_at_shoot_rate_ngn": r0(tot.value_at_shoot_date_rate_ngn),
        "value_at_2023_rate_ngn": r0(tot.value_at_2023_01_01_rate_ngn), "devaluation_gain_ngn": r0(tot.devaluation_gain_ngn),
        "devaluation_share_of_foreign_value_pct": r1(100 * tot.devaluation_gain_ngn / tot.value_at_shoot_date_rate_ngn),
        "pct_rates_gap_filled": r1(tot.pct_rates_gap_filled),
        "gain_2023_ngn": r0(fxy[fxy.year == 2023].devaluation_gain_ngn.iloc[0]),
        "gain_2024_ngn": r0(fxy[fxy.year == 2024].devaluation_gain_ngn.iloc[0]),
        "gain_h1_2025_ngn": r0(fxy[fxy.year == 2025].devaluation_gain_ngn.iloc[0]),
        "usd_rate_2023_01_01": r1(rates.loc["USD", "start_rate"], 2), "usd_rate_2025_06_30": r1(rates.loc["USD", "end_rate"], 2),
        "gbp_rate_2023_01_01": r1(rates.loc["GBP", "start_rate"], 2), "gbp_rate_2025_06_30": r1(rates.loc["GBP", "end_rate"], 2),
        "naira_lost_vs_usd_pct": r1(100 * (1 - rates.loc["USD", "start_rate"] / rates.loc["USD", "end_rate"])),
        "ngn_jobs_usd_value_lost": r0(ngn_jobs.usd_lost.sum()),
        "ngn_jobs_usd_value_lost_share_pct": r1(100 * ngn_jobs.usd_lost.sum() / ngn_jobs.usd_at_2023_01_01.sum()),
        "fx_rates_corrected": r0(q(con, "SELECT COUNT(*) n FROM core.fx_daily WHERE is_corrected AND NOT is_filled").n[0]),
    }

    # ============================================================ 5. merch unit economics
    q7 = pd.read_csv(ROOT / "results" / "q07.csv")
    save("merch_by_collection", q7)
    cq = q(con, """
        SELECT p.collection, d.year_quarter, SUM(m.net_ngn) AS net_ngn, SUM(m.cogs_ngn) AS cogs_ngn,
               SUM(m.net_ngn) - SUM(m.cogs_ngn) AS contribution_ngn
        FROM core.fct_merch_line m JOIN core.dim_product p USING (product_key)
        JOIN core.dim_date d ON d.date_key = m.order_date_lagos WHERE m.is_revenue GROUP BY 1, 2 ORDER BY 1, 2""")
    save("merch_by_collection_quarter", cq)
    sku = q(con, """
        SELECT p.sku, MIN(p.product_name) AS product_name, MIN(p.collection) AS collection,
               SUM(m.net_ngn) AS net_ngn, SUM(m.cogs_ngn) AS cogs_ngn, SUM(m.net_ngn) - SUM(m.cogs_ngn) AS contribution_ngn,
               SUM(m.quantity) AS units
        FROM core.fct_merch_line m JOIN core.dim_product p USING (product_key) WHERE m.is_revenue GROUP BY 1 ORDER BY contribution_ngn""")
    save("merch_by_sku", sku)
    below_cost = q(con, """
        SELECT COUNT(*) AS lines, SUM(m.quantity * (p.unit_cost_ngn - m.unit_price_ngn)) AS shortfall_ngn
        FROM core.fct_merch_line m JOIN core.dim_product p USING (product_key)
        WHERE m.is_revenue AND m.quantity > 0 AND m.unit_price_ngn < p.unit_cost_ngn""")
    q8 = pd.read_csv(ROOT / "results" / "q08.csv")
    q8b = pd.read_csv(ROOT / "results" / "q08b.csv")
    save("refund_rate_by_sku", q8)
    save("refunds_by_reason", q8b)
    merch_tot = q(con, """
        SELECT SUM(gross_ngn) FILTER (WHERE is_revenue) AS gross, SUM(refunded_ngn) AS refunds, SUM(net_ngn) AS net,
               SUM(cogs_ngn) FILTER (WHERE is_revenue) AS cogs, SUM(discount_ngn) FILTER (WHERE is_revenue) AS discount,
               SUM(gross_ngn) FILTER (WHERE order_status = 'Pending') AS pending,
               SUM(gross_ngn) FILTER (WHERE NOT is_revenue) AS cancelled,
               COUNT(*) FILTER (WHERE NOT is_revenue) AS cancelled_lines, COUNT(*) AS lines,
               SUM(gross_ngn) FILTER (WHERE quantity < 0) AS negative_qty_value
        FROM core.fct_merch_line""").iloc[0]
    order_refund_rate = q(con, """
        SELECT COUNT(DISTINCT r.order_id)::numeric / (SELECT COUNT(DISTINCT order_id) FROM core.fct_merch_line) AS rate
        FROM core.fct_refund r""").rate[0]
    F["merch"] = {
        "gross_ngn": r0(merch_tot.gross), "refunds_ngn": r0(merch_tot.refunds), "net_ngn": r0(merch_tot.net),
        "cogs_ngn": r0(merch_tot.cogs), "contribution_ngn": r0(merch_tot.net - merch_tot.cogs),
        "contribution_pct": r1(100 * (merch_tot.net - merch_tot.cogs) / merch_tot.net),
        "discount_vs_list_ngn": r0(merch_tot.discount), "pending_gross_ngn": r0(merch_tot.pending),
        "pending_share_of_net_pct": r1(100 * merch_tot.pending / merch_tot.net),
        "cancelled_gross_ngn": r0(merch_tot.cancelled), "cancelled_lines": r0(merch_tot.cancelled_lines),
        "cancelled_line_share_pct": r1(100 * merch_tot.cancelled_lines / merch_tot.lines),
        "collections_losing_money": int((q7.contribution_margin_ngn < 0).sum()),
        "collection_quarters_losing_money": int((cq.contribution_ngn < 0).sum()),
        "skus_losing_money": int((sku.contribution_ngn < 0).sum()),
        "top_collection": q7.sort_values("contribution_margin_ngn").collection.iloc[-1],
        "top_collection_contribution_ngn": r0(q7.contribution_margin_ngn.max()),
        "lowest_margin_collection": q7.sort_values("contribution_margin_pct").collection.iloc[0],
        "lowest_margin_collection_pct": r1(q7.contribution_margin_pct.min()),
        "highest_margin_collection": q7.sort_values("contribution_margin_pct").collection.iloc[-1],
        "highest_margin_collection_pct": r1(q7.contribution_margin_pct.max()),
        "qty_9999_lines": r0(q7.qty_9999_lines_excluded_storewide.iloc[0]),
        "store_refund_rate_pct": r1(q8.store_avg_refund_rate_pct.iloc[0], 2),
        "skus_above_2x": int(q8.above_2x_store_avg.sum()),
        "highest_refund_sku": q8.sku.iloc[0], "highest_refund_sku_name": q8.product_name.iloc[0],
        "highest_refund_sku_rate_pct": r1(q8.refund_rate_pct.iloc[0], 2), "highest_refund_sku_x": r1(q8.x_store_avg.iloc[0], 2),
        "highest_refund_sku_reason": q8.dominant_reason.iloc[0],
        "top_reason": q8b.reason.iloc[0], "top_reason_share_pct": r1(q8b.share_of_refunds_pct.iloc[0]),
        "top3_reasons_share_pct": r1(q8b.share_of_refunds_pct.iloc[:3].sum()),
        "refund_rows": r0(q8b.refunds.sum()), "orders_with_refund_pct": r1(100 * order_refund_rate),
        "lines_sold_below_cost": r0(below_cost.lines[0]), "below_cost_shortfall_ngn": r0(below_cost.shortfall_ngn[0]),
    }

    # ============================================================ 6. marketing efficiency
    q9 = pd.read_csv(ROOT / "results" / "q09.csv")
    save("channel_quarter", q9)
    ch = q9.groupby("channel_name").agg(sessions=("sessions", "sum"), conversions=("conversions", "sum"),
                                         revenue_ngn=("revenue_ngn", "sum"), spend_ngn=("spend_ngn", "sum"),
                                         clicks=("clicks", "sum")).reset_index()
    ch["conversion_rate_pct"] = 100 * ch.conversions / ch.sessions.replace(0, np.nan)
    ch["cac_ngn"] = (ch.spend_ngn / ch.conversions.replace(0, np.nan)).where(ch.spend_ngn > 0)
    ch["roas"] = ch.revenue_ngn / ch.spend_ngn.replace(0, np.nan)
    ch["cpc_ngn"] = ch.spend_ngn / ch.clicks.replace(0, np.nan)
    sess = q(con, """
        SELECT COUNT(*) AS all_sessions, COUNT(*) FILTER (WHERE is_bot) AS bots, COUNT(*) FILTER (WHERE is_spam) AS spam,
               COUNT(*) FILTER (WHERE NOT is_bot) AS human, COUNT(*) FILTER (WHERE NOT is_bot AND converted) AS conv,
               COUNT(*) FILTER (WHERE converted) AS conv_all
        FROM core.fct_session""").iloc[0]
    attributed = q(con, """
        SELECT c.channel_name, SUM(o.order_net) AS attributed_order_net_ngn
        FROM core.fct_session s JOIN core.dim_channel c USING (channel_key)
        JOIN (SELECT order_id, SUM(net_ngn) AS order_net FROM core.fct_merch_line GROUP BY 1) o USING (order_id)
        WHERE NOT s.is_bot GROUP BY 1""")
    ch = ch.merge(attributed, on="channel_name", how="left")
    ch["attributed_roas"] = ch.attributed_order_net_ngn / ch.spend_ngn.replace(0, np.nan)
    save("channel_totals", ch.round(3))
    q10 = pd.read_csv(ROOT / "results" / "q10.csv").set_index("scope")
    h = q10.loc["human converted sessions"]
    paid = ch[ch.spend_ngn > 0]
    measurable = paid[paid.sessions > 0]
    spend_total = r0(ch.spend_ngn.sum())
    lag = q(con, """
        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(EXTRACT(EPOCH FROM (m.order_ts - s.session_start_utc)) / 86400)) AS med_days
        FROM core.fct_session s JOIN (SELECT order_id, MIN(order_ts) AS order_ts FROM core.fct_merch_line GROUP BY 1) m USING (order_id)""").med_days[0]
    F["marketing"] = {
        "sessions_all": r0(sess.all_sessions), "bot_sessions": r0(sess.bots), "bot_share_pct": r1(100 * sess.bots / sess.all_sessions),
        "spam_sessions": r0(sess.spam), "human_sessions": r0(sess.human), "human_conversions": r0(sess.conv),
        "conversion_rate_pct": r1(100 * sess.conv / sess.human, 2),
        "naive_conversion_rate_pct": r1(100 * sess.conv_all / sess.all_sessions, 2),
        "ad_spend_total_ngn": spend_total,
        "session_revenue_total_ngn": r0(ch.revenue_ngn.sum()),
        "paid_channel_session_revenue_ngn": r0(measurable.revenue_ngn.sum()),
        "paid_measurable_spend_ngn": r0(measurable.spend_ngn.sum()),
        "blended_paid_roas": r1(measurable.revenue_ngn.sum() / measurable.spend_ngn.sum(), 2),
        "influencer_spend_ngn": r0(ch.set_index("channel_name").loc["Influencer", "spend_ngn"]),
        "best_roas_channel": measurable.sort_values("roas").channel_name.iloc[-1],
        "best_roas": r1(measurable.roas.max(), 2),
        "worst_roas_channel": measurable.sort_values("roas").channel_name.iloc[0], "worst_roas": r1(measurable.roas.min(), 2),
        "lowest_cac_channel": measurable.sort_values("cac_ngn").channel_name.iloc[0], "lowest_cac_ngn": r0(measurable.cac_ngn.min()),
        "highest_cac_channel": measurable.sort_values("cac_ngn").channel_name.iloc[-1], "highest_cac_ngn": r0(measurable.cac_ngn.max()),
        "free_channel_conversions_share_pct": r1(100 * ch[ch.spend_ngn == 0].conversions.sum() / ch.conversions.sum()),
        "converted_sessions": r0(h.converted_sessions), "joined_pct": r1(h.pct_joined),
        "unattributed_revenue_ngn": r0(h.unattributed_revenue_ngn),
        "unattributed_share_of_session_revenue_pct": r1(h.unattributed_share_of_session_revenue_pct),
        "unattributed_pct_of_merch_net": r1(h.unattributed_as_pct_of_merch_net_revenue),
        "session_revenue_pct_of_merch_net": r1(100 * ch.revenue_ngn.sum() / merch_tot.net),
        "median_days_session_to_order": r1(lag),
        "ad_spend_monthly_avg_ngn": r0(spend_total / 30),
    }

    lead = q(con, """
        SELECT COALESCE(lead_source, 'Unknown') AS lead_source, COUNT(*) AS jobs, SUM(net_amount_ngn) AS revenue_ngn
        FROM core.fct_booking WHERE NOT is_cancelled GROUP BY 1 ORDER BY revenue_ngn DESC""")
    lead["share_pct"] = 100 * lead.revenue_ngn / lead.revenue_ngn.sum()
    save("production_by_lead_source", lead.round(2))
    social = lead[lead.lead_source.isin(["Google", "Instagram", "TikTok"])]
    ad3 = q(con, """SELECT SUM(a.spend_ngn) s FROM core.fct_ad_spend a JOIN core.dim_channel c USING (channel_key)
                   WHERE c.channel_name IN ('Google', 'Meta', 'TikTok')""").s[0]
    camp = q(con, "SELECT campaign, SUM(spend_ngn) AS spend_ngn FROM core.fct_ad_spend GROUP BY 1 ORDER BY 2 DESC")
    save("spend_by_campaign", camp)
    merch_camps = ["harmattan_drop", "lagos_nights_launch", "black_friday", "blackfriday24", "retarget_q4"]
    F["marketing"].update({
        "google_ig_tiktok_lead_revenue_ngn": r0(social.revenue_ngn.sum()),
        "google_ig_tiktok_lead_share_pct": r1(100 * social.revenue_ngn.sum() / lead.revenue_ngn.sum()),
        "google_meta_tiktok_spend_ngn": r0(ad3),
        "breakeven_share_of_social_leads_pct": r1(100 * ad3 / social.revenue_ngn.sum()),
        "merch_campaign_spend_ngn": r0(camp[camp.campaign.isin(merch_camps)].spend_ngn.sum()),
        "production_campaign_spend_ngn": r0(camp[~camp.campaign.isin(merch_camps)].spend_ngn.sum()),
        "merch_contribution_vs_merch_campaign_spend": r1(
            (merch_tot.net - merch_tot.cogs) / camp[camp.campaign.isin(merch_camps)].spend_ngn.sum(), 2),
        "unknown_lead_source_revenue_ngn": r0(lead[lead.lead_source == "Unknown"].revenue_ngn.sum()),
    })

    # ============================================================ 7. retention and cross-sell
    q11 = pd.read_csv(ROOT / "results" / "q11.csv")
    chn = q11[q11.cut == "acquisition_channel"]
    chi2, p_chi, _, _ = stats.chi2_contingency(np.c_[chn.repeat_buyers, chn.buyers - chn.repeat_buyers])
    q12 = pd.read_csv(ROOT / "results" / "q12.csv")
    t, dfree = q12.welch_t.iloc[0], q12.welch_df.iloc[0]
    p_t = 2 * stats.t.sf(abs(t), dfree)
    allw = q11[q11.cut == "all_full_window"].iloc[0]
    pm = q12.set_index("segment")
    F["customers"] = {
        "repeat_90d_pct": r1(allw.repeat_90d_pct), "repeat_buyers": r0(allw.repeat_buyers), "buyers": r0(allw.buyers),
        "channel_repeat_min_pct": r1(chn.repeat_90d_pct.min()), "channel_repeat_max_pct": r1(chn.repeat_90d_pct.max()),
        "channel_repeat_min": chn.sort_values("repeat_90d_pct").grp.iloc[0],
        "channel_repeat_max": chn.sort_values("repeat_90d_pct").grp.iloc[-1],
        "channel_chi2": r1(chi2, 2), "channel_chi2_p": r1(p_chi, 4),
        "production_clients": r0(pm.production_clients_total.iloc[0]),
        "production_clients_buying_merch": r0(pm.loc["production_and_merch", "clients"]),
        "cross_mean_order_ngn": r0(pm.loc["production_and_merch", "mean_order_net_ngn"]),
        "merch_only_mean_order_ngn": r0(pm.loc["merch_only", "mean_order_net_ngn"]),
        "welch_t": r1(t, 3), "welch_df": r1(dfree), "welch_p": r1(p_t, 3),
        "guest_line_share_pct": r1(q(con, "SELECT 100.0 * AVG((client_key IS NULL)::int) p FROM core.fct_merch_line").p[0]),
    }
    save("repeat_by_cohort_and_channel", q11)
    save("cross_sell_test", q12.assign(welch_p=p_t))

    # ============================================================ 8. the Director's question
    q14 = pd.read_csv(ROOT / "results" / "q14.csv")
    save("monthly_money_flow", q14)
    yq = q14.assign(year=q14.month.str[:4]).groupby("year").sum(numeric_only=True).reset_index()
    yq["known_cost_pct"] = 100 * (yq.labour_cost_ngn + yq.ad_spend_ngn + yq.merch_cogs_ngn) / (yq.production_revenue_ngn + yq.merch_net_revenue_ngn)
    yq["jobs"] = yq.year.astype(int).map(month.groupby("year").jobs.sum())
    save("yearly_money_flow", yq)
    y = yq.set_index("year")
    F["director"] = {
        "jobs_2023": r0(y.loc["2023", "jobs"]), "jobs_2024": r0(y.loc["2024", "jobs"]), "jobs_h1_2025": r0(y.loc["2025", "jobs"]),
        "jobs_h1_2024": r0(month[(month.year == 2024) & (month.month <= 6)].jobs.sum()),
        "labour_2023": r0(y.loc["2023", "labour_cost_ngn"]), "labour_2024": r0(y.loc["2024", "labour_cost_ngn"]),
        "ads_2023": r0(y.loc["2023", "ad_spend_ngn"]), "ads_2024": r0(y.loc["2024", "ad_spend_ngn"]),
        "known_cost_pct_2023": r1(y.loc["2023", "known_cost_pct"]), "known_cost_pct_2024": r1(y.loc["2024", "known_cost_pct"]),
        "known_cost_pct_h1_2025": r1(y.loc["2025", "known_cost_pct"]),
        "revenue_minus_known_cost_all_ngn": r0(q14.revenue_minus_known_cost_ngn.sum()),
        "ads_all_ngn": r0(q14.ad_spend_ngn.sum()), "labour_all_ngn": r0(q14.labour_cost_ngn.sum()),
        "cogs_all_ngn": r0(q14.merch_cogs_ngn.sum()),
    }

    # ============================================================ 9. data quality tile
    q13 = pd.read_csv(ROOT / "results" / "q13.csv")
    grand = q13[q13.src_table.isna()].iloc[0]
    flagged = q(con, """
        SELECT (SELECT SUM(net_amount_ngn) FROM core.fct_booking b JOIN core.dim_service s USING (service_key)
                WHERE NOT is_cancelled AND (s.service_name = 'Unknown' OR b.status = 'Unknown')) AS booking_unresolved,
               (SELECT SUM(revenue_ngn) FROM core.fct_session WHERE converted AND order_id IS NULL) AS unattributed""").iloc[0]
    total_rev = rev.total_ngn.sum()
    raw_rows = 1860 + 2082 + 977 + 955 + 387 + 140 + 15156 + 137 + 44495 + 8888 + 4048 + 62868 + 88414 + 51764
    F["data_quality"] = {
        "raw_rows": raw_rows, "rows_quarantined": r0(grand.rows_rejected),
        "rows_quarantined_pct": r1(100 * grand.rows_rejected / raw_rows, 2),
        "quarantined_revenue_at_risk_ngn": r0(grand.revenue_value_at_risk_ngn),
        "unresolved_booking_revenue_ngn": r0(flagged.booking_unresolved),
        "revenue_affected_ngn": r0(grand.revenue_value_at_risk_ngn + flagged.booking_unresolved),
        "revenue_affected_pct": r1(100 * (grand.revenue_value_at_risk_ngn + flagged.booking_unresolved) / total_rev, 2),
        "total_revenue_ngn": r0(total_rev),
    }
    save("data_quality_tile", q13)

    (OUT / "findings.json").write_text(json.dumps(F, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    con.close()
    print(json.dumps(F, indent=1, default=str))


if __name__ == "__main__":
    main()
