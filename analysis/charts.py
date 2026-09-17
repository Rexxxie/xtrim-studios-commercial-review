"""Static charts for the memo and the deck, drawn from analysis/tables/*.csv only.

    python analysis/charts.py

Palette: validated categorical slots (blue, orange, aqua) on a light surface; gray for
de-emphasis; status red only where a value means "loss". One y-axis per chart.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
T = ROOT / "analysis" / "tables"
OUT = ROOT / "charts"
F = json.loads((ROOT / "analysis" / "findings.json").read_text())

SURFACE, INK, INK2, MUTED, GRID, BASE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GRAY, CRITICAL = "#c3c2b7", "#d03b3b"

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"], "font.size": 11,
    "axes.facecolor": SURFACE, "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": BASE, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.titlesize": 14, "axes.titleweight": "semibold",
    "axes.titlecolor": INK, "axes.titlelocation": "left", "legend.frameon": False, "legend.fontsize": 10,
})


def bn(x, _=None):
    """NGN axis formatter: 1.2B / 350M / 45K."""
    a = abs(x)
    if a >= 1e9:
        return f"₦{x / 1e9:.1f}B"
    if a >= 1e6:
        return f"₦{x / 1e6:.0f}M"
    if a >= 1e3:
        return f"₦{x / 1e3:.0f}K"
    return f"₦{x:.0f}"


def fig(w=10, h=5.2):
    f, ax = plt.subplots(figsize=(w, h), dpi=200)
    return f, ax


def finish(f, ax, name, title, subtitle=None, source="Source: Xtrim Studios warehouse (core.*), NGN."):
    ax.set_title(title, pad=26 if subtitle else 12)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=INK2, fontsize=10.5, va="bottom")
    f.text(0.01, 0.01, source, color=MUTED, fontsize=8.5)
    f.tight_layout(rect=(0, 0.03, 1, 1))
    f.savefig(OUT / f"{name}.png")
    plt.close(f)


def hgrid(ax):
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)


def vgrid(ax):
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)


def main():
    OUT.mkdir(exist_ok=True)

    # 01 quarterly revenue, production + merch
    r = pd.read_csv(T / "revenue_by_quarter.csv")
    f, ax = fig()
    x = range(len(r))
    ax.bar(x, r.production_revenue_ngn, width=0.6, color=BLUE, label="Production", edgecolor=SURFACE, linewidth=1.5)
    ax.bar(x, r.merch_net_revenue_ngn, width=0.6, bottom=r.production_revenue_ngn, color=ORANGE, label="Merch (net of refunds)",
           edgecolor=SURFACE, linewidth=1.5)
    for i in [0, 7, len(r) - 1]:
        ax.text(i, r.total_ngn[i] * 1.02, bn(r.total_ngn[i]), ha="center", va="bottom", color=INK, fontsize=10)
    ax.set_xticks(list(x), r.quarter)
    ax.yaxis.set_major_formatter(mt.FuncFormatter(bn))
    hgrid(ax)
    ax.legend(loc="upper left", ncol=2)
    ax.set_ylim(0, r.total_ngn.max() * 1.15)
    finish(f, ax, "01_revenue_by_quarter", "Revenue by quarter",
           f"Production carries the business; merch is {F['revenue']['merch_share_pct_all']}% of revenue. Q4 is always the peak.")

    # 02 naira vs dollar revenue, yearly small multiples (one scale per panel)
    yr = pd.read_csv(T / "revenue_by_year.csv")
    labels = ["2023", "2024", "H1 2025"]
    f, (a1, a2) = plt.subplots(1, 2, figsize=(10, 5), dpi=200)
    a1.bar(labels, yr.total, color=[BLUE, BLUE, GRAY], width=0.55)
    a2.bar(labels, yr.usd, color=[ORANGE, ORANGE, GRAY], width=0.55)
    for i, v in enumerate(yr.total):
        a1.text(i, v * 1.02, bn(v), ha="center", fontsize=10.5, color=INK)
    for i, v in enumerate(yr.usd):
        a2.text(i, v * 1.02, f"${v / 1e6:.1f}M", ha="center", fontsize=10.5, color=INK)
    a1.yaxis.set_major_formatter(mt.FuncFormatter(bn))
    a2.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"${v / 1e6:.0f}M"))
    a1.set_title("In naira", fontsize=12, pad=8)
    a2.set_title("The same revenue in US dollars", fontsize=12, pad=8)
    for x_ in (a1, a2):
        hgrid(x_)
        x_.set_ylim(0, x_.get_ylim()[1] * 1.08)
    f.suptitle("Busier in naira, poorer in dollars", x=0.01, ha="left", fontsize=14, fontweight="semibold", color=INK)
    f.text(0.01, 0.905, f"Revenue grew {F['revenue']['growth_ngn_2024_vs_2023_pct']}% in naira from 2023 to 2024 but fell "
           f"{abs(F['revenue']['growth_usd_2024_vs_2023_pct'])}% in dollars. H1 2025 (gray) is a half year.",
           color=INK2, fontsize=10.5)
    f.text(0.01, 0.01, "Dollar value = each quarter's naira revenue at that quarter's average USD rate (core.fx_daily).",
           color=MUTED, fontsize=8.5)
    f.tight_layout(rect=(0, 0.03, 1, 0.88))
    f.savefig(OUT / "02_naira_vs_dollar_revenue.png")
    plt.close(f)

    # 03 share of revenue vs share of jobs
    s = pd.read_csv(T / "revenue_by_service.csv").sort_values("revenue_share_pct")
    f, ax = fig(10, 5.6)
    y = range(len(s))
    ax.barh([i + 0.2 for i in y], s.revenue_share_pct, height=0.36, color=BLUE, label="Share of revenue")
    ax.barh([i - 0.2 for i in y], s.job_share_pct, height=0.36, color=ORANGE, label="Share of jobs")
    for i, (rv, jb) in enumerate(zip(s.revenue_share_pct, s.job_share_pct)):
        ax.text(rv + 0.4, i + 0.2, f"{rv:.1f}%", va="center", fontsize=9, color=INK2)
        ax.text(jb + 0.4, i - 0.2, f"{jb:.1f}%", va="center", fontsize=9, color=INK2)
    ax.set_yticks(list(y), s.service_name)
    ax.xaxis.set_major_formatter(mt.PercentFormatter(decimals=0))
    vgrid(ax)
    ax.legend(loc="lower right")
    finish(f, ax, "03_service_share", "Which service lines carry the business",
           f"TVC and Music Video: {F['services']['tvc_mv_revenue_share_pct']}% of revenue from "
           f"{F['services']['tvc_mv_job_share_pct']}% of jobs. Studio Rental: {F['services']['studio_rental_job_share_pct']}% of jobs, "
           f"{F['services']['studio_rental_revenue_share_pct']}% of revenue.",
           source="Source: core.fct_booking, non-cancelled jobs 2023 – H1 2025. 'Unknown' = service type never recorded.")

    # 04 labour margin by service
    m = pd.read_csv(T / "margin_by_service.csv").sort_values("labour_margin_pct", ascending=False)
    f, ax = fig(10, 5.6)
    colors = [CRITICAL if v < 0 else BLUE for v in m.labour_margin_pct]
    ax.barh(m.service_name, m.labour_margin_pct, color=colors, height=0.55)
    for i, (v, lj, j) in enumerate(zip(m.labour_margin_pct, m.loss_jobs, m.jobs)):
        lab = f"{v:.1f}%" + (f"   ({lj} of {j} jobs lose money)" if lj else "")
        ax.text(max(v, 0) + 1.2, i, lab, va="center", fontsize=9.5, color=INK)
    ax.axvline(0, color=BASE, lw=1)
    ax.set_xlim(min(m.labour_margin_pct.min() - 5, -10), 135)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.xaxis.set_major_formatter(mt.PercentFormatter(decimals=0))
    vgrid(ax)
    ax.invert_yaxis()
    finish(f, ax, "04_margin_by_service", "Margin after crew labour, by service line",
           "Studio Rental loses money on crew cost alone. Red marks a loss.",
           source="Margin = (net revenue − crew day rates) / net revenue. Non-cancelled jobs. Other costs (rent, kit) are not in the data.")

    # 05 seasonality
    j = pd.read_csv(T / "jobs_by_month_2023_2024.csv")
    f, ax = fig()
    cols = [BLUE if mn in (11, 12) else GRAY for mn in j.month]
    ax.bar(j.month_name, j.avg_jobs_per_year, color=cols, width=0.62)
    for i, v in enumerate(j.avg_jobs_per_year):
        if j.month[i] in (1, 11, 12):
            ax.text(i, v + 1.5, f"{v:.0f}", ha="center", fontsize=10, color=INK)
    hgrid(ax)
    ax.set_ylabel("Jobs per month (average of 2023 and 2024)")
    finish(f, ax, "05_seasonality", "November and December are the crunch",
           f"December averages {F['capacity']['busiest_month_jobs_2yr'] / 2:.0f} jobs a year against "
           f"{F['capacity']['quietest_month_jobs_2yr'] / 2:.0f} in January.",
           source="Source: core.fct_booking, non-cancelled jobs by shoot date, full years 2023–2024.")

    # 06 double bookings by month
    d = pd.read_csv(T / "double_bookings_by_month.csv")
    dm = d[d.year.isin([2023, 2024])].groupby("month").double_booked_crew_days.sum().reset_index()
    dm["name"] = pd.to_datetime(dm.month, format="%m").dt.strftime("%b")
    f, ax = fig()
    ax.bar(dm.name, dm.double_booked_crew_days, color=[BLUE if mn in (11, 12) else GRAY for mn in dm.month], width=0.62)
    hgrid(ax)
    ax.set_ylabel("Crew-days logged on two jobs at once")
    finish(f, ax, "06_double_bookings", "Where capacity actually breaks: crew booked on two jobs the same day",
           f"{F['capacity']['double_booked_crew_days_total']} double-booked crew-days in total; "
           f"{F['capacity']['double_booked_nov_dec_share_pct']}% fall in November and December.",
           source="Source: core.fct_crew_day, 2023–2024. Utilisation never passed 85% in any week (peak "
                  f"{F['capacity']['peak_utilisation_pct']}%).")

    # 07 FX rates
    fx = pd.read_csv(T / "fx_daily_usd_gbp.csv", parse_dates=["rate_date"])
    f, ax = fig()
    for cur, c in [("USD", BLUE), ("GBP", ORANGE)]:
        z = fx[fx.from_currency == cur]
        ax.plot(z.rate_date, z.rate, color=c, lw=2, label=f"Naira per 1 {cur}")
    ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"₦{v:,.0f}"))
    hgrid(ax)
    ax.legend(loc="upper left")
    for dt, lab in [("2023-06-14", "Jun 2023 devaluation"), ("2024-01-29", "Jan 2024 devaluation")]:
        ax.axvline(pd.Timestamp(dt), color=BASE, lw=1)
        ax.text(pd.Timestamp(dt), ax.get_ylim()[1] * 0.97, " " + lab, fontsize=9, color=INK2, va="top")
    finish(f, ax, "07_fx_rates", "The naira lost 90% of its value against the dollar",
           f"₦{F['fx']['usd_rate_2023_01_01']:,.0f} per dollar on 1 Jan 2023; ₦{F['fx']['usd_rate_2025_06_30']:,.0f} on 30 Jun 2025.",
           source="Source: core.fx_daily (fx_rates.csv, gaps filled with the last published rate; 7 decimal-point typos corrected).")

    # 08 FX gain by year
    q5 = pd.read_csv(T / "fx_exposure_foreign_jobs.csv")
    g = q5[q5.invoice_currency.isna() & q5.year.notna()]
    f, ax = fig(9, 5)
    labels = ["2023", "2024", "H1 2025"]
    ax.bar(labels, g.value_at_2023_01_01_rate_ngn, color=GRAY, width=0.55, label="Worth at Jan 2023 rates")
    ax.bar(labels, g.devaluation_gain_ngn, bottom=g.value_at_2023_01_01_rate_ngn, color=BLUE, width=0.55,
           label="Extra naira from devaluation", edgecolor=SURFACE, linewidth=1.5)
    for i, (b, t) in enumerate(zip(g.value_at_2023_01_01_rate_ngn, g.devaluation_gain_ngn)):
        ax.text(i, b + t + g.value_at_shoot_date_rate_ngn.max() * 0.015, bn(t) + " from FX", ha="center", fontsize=10, color=INK)
    ax.yaxis.set_major_formatter(mt.FuncFormatter(bn))
    hgrid(ax)
    ax.legend(loc="upper left")
    finish(f, ax, "08_fx_gain", "Dollar and pound jobs: most of their naira value is devaluation",
           f"{F['fx']['foreign_jobs']} USD/GBP jobs; {bn(F['fx']['devaluation_gain_ngn'])} "
           f"({F['fx']['devaluation_share_of_foreign_value_pct']}%) of their value came from the weaker naira.",
           source="Each job valued at its shoot-date rate vs the 1 Jan 2023 rate. Non-cancelled jobs.")

    # 09 postponed share
    st = pd.read_csv(T / "production_revenue_by_status.csv")
    pp = st[st.status == "Postponed"]
    f, ax = fig(9, 4.8)
    ax.bar(["2023", "2024", "H1 2025"], pp.share_of_year_revenue_pct, color=BLUE, width=0.5)
    for i, v in enumerate(pp.share_of_year_revenue_pct):
        ax.text(i, v + 0.3, f"{v:.1f}%", ha="center", fontsize=11, color=INK)
    ax.yaxis.set_major_formatter(mt.PercentFormatter(decimals=0))
    hgrid(ax)
    finish(f, ax, "09_postponed_share", "More booked work is slipping",
           "Share of each year's production revenue sitting in Postponed jobs.",
           source="Source: core.fct_booking status at export (mid-2025).")

    # 10 merch by collection
    c = pd.read_csv(T / "merch_by_collection.csv").sort_values("net_ngn")
    f, ax = fig(10, 5.2)
    ax.barh(c.collection, c.cogs_ngn, color=GRAY, height=0.55, label="Cost of goods")
    ax.barh(c.collection, c.contribution_margin_ngn, left=c.cogs_ngn, color=BLUE, height=0.55, label="Contribution",
            edgecolor=SURFACE, linewidth=1.5)
    for i, (n, pct) in enumerate(zip(c.net_ngn, c.contribution_margin_pct)):
        ax.text(n + c.net_ngn.max() * 0.01, i, f"{pct:.0f}% margin", va="center", fontsize=9.5, color=INK)
    ax.xaxis.set_major_formatter(mt.FuncFormatter(bn))
    ax.set_xlim(0, c.net_ngn.max() * 1.18)
    vgrid(ax)
    ax.legend(loc="lower right")
    finish(f, ax, "10_merch_collections", "No merch drop lost money",
           f"Every collection clears 57% contribution after refunds and cost of goods. Merch contributed "
           f"{bn(F['merch']['contribution_ngn'])} in total.",
           source="Net revenue after refunds, non-cancelled orders; 190 quantity-9999 placeholder lines excluded.")

    # 11 refund reasons
    rr = pd.read_csv(T / "refunds_by_reason.csv").sort_values("refunds")
    f, ax = fig(9.5, 4.8)
    ax.barh(rr.reason, rr.share_of_refunds_pct, color=BLUE, height=0.55)
    for i, v in enumerate(rr.share_of_refunds_pct):
        ax.text(v + 0.3, i, f"{v:.1f}%", va="center", fontsize=10, color=INK)
    ax.xaxis.set_major_formatter(mt.PercentFormatter(decimals=0))
    vgrid(ax)
    finish(f, ax, "11_refund_reasons", "Why customers ask for refunds",
           f"Changed mind, damaged and wrong size are {F['merch']['top3_reasons_share_pct']}% of refunds. No SKU is refunded at 2x the store rate.",
           source=f"Source: core.fct_refund, {F['merch']['refund_rows']:,} refunds.")

    # 12 spend vs tracked revenue by channel
    ch = pd.read_csv(T / "channel_totals.csv")
    ch = ch[ch.spend_ngn > 0].sort_values("spend_ngn")
    f, ax = fig(10, 5.2)
    y = range(len(ch))
    ax.barh([i + 0.2 for i in y], ch.spend_ngn, height=0.36, color=ORANGE, label="Ad spend")
    ax.barh([i - 0.2 for i in y], ch.revenue_ngn, height=0.36, color=BLUE, label="Revenue the website tracked")
    for i, (sp, rv) in enumerate(zip(ch.spend_ngn, ch.revenue_ngn)):
        ro = rv / sp
        ax.text(sp + ch.spend_ngn.max() * 0.01, i + 0.2, bn(sp), va="center", fontsize=9, color=INK2)
        lab = f"{bn(rv)}  ·  ₦{ro:.2f} back per ₦1" if rv > 0 else "not measurable (no tracking source)"
        ax.text(rv + ch.spend_ngn.max() * 0.01, i - 0.2, lab, va="center", fontsize=9, color=INK)
    ax.set_yticks(list(y), ch.channel_name)
    ax.xaxis.set_major_formatter(mt.FuncFormatter(bn))
    ax.set_xlim(0, ch.spend_ngn.max() * 1.45)
    vgrid(ax)
    ax.legend(loc="lower right")
    finish(f, ax, "12_channel_spend_vs_revenue", "Ads do not pay back through the web shop",
           f"{bn(F['marketing']['ad_spend_total_ngn'])} spent; paid channels tracked ₦{F['marketing']['blended_paid_roas']:.2f} "
           "of shop revenue per ₦1. Their effect on production bookings is not recorded anywhere.",
           source="Human sessions only (bots removed). Revenue = what the analytics tool recorded on converting sessions, 2023 – H1 2025.")

    # 13 where the money went, per year
    yq = pd.read_csv(T / "yearly_money_flow.csv")
    yq["revenue"] = yq.production_revenue_ngn + yq.merch_net_revenue_ngn
    parts = [("labour_cost_ngn", "Crew labour", ORANGE), ("ad_spend_ngn", "Ad spend", AQUA),
             ("merch_cogs_ngn", "Merch cost of goods", YELLOW), ("revenue_minus_known_cost_ngn", "Left after recorded costs", BLUE)]
    f, ax = fig(10, 4.6)
    labels = ["2023", "2024", "H1 2025"]
    left = [0] * len(yq)
    for col, lab, colr in parts:
        share = 100 * yq[col] / yq.revenue
        ax.barh(labels, share, left=left, color=colr, height=0.5, label=lab, edgecolor=SURFACE, linewidth=2)
        for i, v in enumerate(share):
            if v >= 6:
                ax.text(left[i] + v / 2, i, f"{v:.0f}%", ha="center", va="center", fontsize=10,
                        color="white" if colr in (BLUE, ORANGE) else INK)
        left = [a + b for a, b in zip(left, share)]
    ax.xaxis.set_major_formatter(mt.PercentFormatter(decimals=0))
    ax.set_xlim(0, 100)
    ax.invert_yaxis()
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=4)
    finish(f, ax, "13_where_the_money_went", "Where each naira of revenue went",
           "Recorded costs take under a quarter of revenue, so the cash squeeze sits in what these systems do not record.",
           source="Revenue = production (non-cancelled) + merch net. Rent, equipment, salaries, tax and overheads are not in the data.")
    print("charts written:", len(list(OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
