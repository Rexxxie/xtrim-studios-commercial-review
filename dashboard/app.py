"""Xtrim Studios commercial dashboard.

    streamlit run dashboard/app.py

Three tabs (Production, Merch, Acquisition), one filter row that scopes everything, and a data
quality tile that is always visible. Reads dashboard/data/*.parquet (exported from the warehouse).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics as M  # noqa: E402

BLUE, ORANGE, AQUA, GRAY, CRITICAL = "#2a78d6", "#eb6834", "#1baf7a", "#c3c2b7", "#d03b3b"
INK2, MUTED, GRID = "#52514e", "#898781", "#e1e0d9"

st.set_page_config(page_title="Xtrim Studios — Commercial Dashboard", page_icon="🎬", layout="wide")


def ngn(v: float) -> str:
    a = abs(v)
    if a >= 1e9:
        return f"₦{v / 1e9:,.2f}B"
    if a >= 1e6:
        return f"₦{v / 1e6:,.1f}M"
    if a >= 1e3:
        return f"₦{v / 1e3:,.0f}K"
    return f"₦{v:,.0f}"


def style(fig: go.Figure, height=360, legend=True) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)", font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13),
                      showlegend=legend, legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0), bargap=0.35,
                      hoverlabel=dict(font_size=13))
    fig.update_xaxes(showgrid=False, linecolor=GRAY)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


@st.cache_data
def data():
    return M.load()


D = data()

# ------------------------------------------------------------------ header + filters
st.title("Xtrim Studios — commercial performance")
st.caption("2023 Q1 → 2025 Q2 · all money in Nigerian naira (NGN) · source: cleaned warehouse (core.*)")

c1, c2, c3 = st.columns([2, 3, 3])
with c1:
    rng = st.date_input("Date range", value=(pd.Timestamp("2023-01-01"), pd.Timestamp("2025-06-30")),
                        min_value=pd.Timestamp("2023-01-01"), max_value=pd.Timestamp("2025-06-30"))
with c2:
    services = st.multiselect("Service line (Production tab)", M.SERVICES, default=M.SERVICES)
with c3:
    channels = st.multiselect("Channel (Acquisition tab)", M.CHANNELS, default=M.CHANNELS)
start, end = (rng if isinstance(rng, tuple) and len(rng) == 2 else (pd.Timestamp("2023-01-01"), pd.Timestamp("2025-06-30")))
F = M.Filters(pd.Timestamp(start), pd.Timestamp(end), services or M.SERVICES, channels or M.CHANNELS)

dq = M.data_quality(D, F)
with st.container(border=True):
    q1, q2, q3 = st.columns([1, 1, 2])
    q1.metric("⚠️ Rows quarantined", f"{dq['rows_quarantined']:,}", f"{dq['rows_quarantined_pct']:.2f}% of raw rows",
              delta_color="off")
    q2.metric("Revenue affected by unresolved issues", ngn(dq["revenue_affected_ngn"]),
              f"{dq['revenue_affected_pct']:.1f}% of revenue", delta_color="off")
    q3.markdown("**Data quality** (whole dataset, not filtered). Quarantined rows are kept, never deleted: duplicates, "
                "orphan IDs, Excel subtotal rows, 9999-quantity placeholders. *Revenue affected* = quarantined order lines and "
                "refunds, plus bookings with no service type or status.")
    with q3.expander("Rows quarantined by reason"):
        st.dataframe(dq["by_table"], hide_index=True, use_container_width=True)

tab_p, tab_m, tab_a = st.tabs(["🎥 Production", "👕 Merch", "📣 Acquisition"])

# ------------------------------------------------------------------ production
with tab_p:
    svc = M.service_summary(D, F)
    pq = M.production_by_quarter(D, F)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Production revenue", ngn(svc.revenue_ngn.sum()))
    k2.metric("Jobs (not cancelled)", f"{int(svc.jobs.sum()):,}")
    k3.metric("Margin after crew labour", f"{100 * (svc.revenue_ngn.sum() - svc.labour_ngn.sum()) / max(svc.revenue_ngn.sum(), 1):.1f}%")
    k4.metric("Jobs where crew cost > revenue", f"{int(svc.loss_jobs.sum()):,}")

    a, b = st.columns(2)
    with a:
        st.subheader("Revenue by quarter")
        fig = go.Figure(go.Bar(x=pq.index, y=pq.values, marker_color=BLUE,
                               hovertemplate="%{x}<br>₦%{y:,.0f}<extra></extra>"))
        st.plotly_chart(style(fig, legend=False), use_container_width=True)
    with b:
        st.subheader("Margin after crew labour, by service")
        s2 = svc.sort_values("labour_margin_pct")
        fig = go.Figure(go.Bar(y=s2.service_name, x=s2.labour_margin_pct, orientation="h",
                               marker_color=[CRITICAL if v < 0 else BLUE for v in s2.labour_margin_pct],
                               text=[f"{v:.1f}%" for v in s2.labour_margin_pct], textposition="outside",
                               customdata=s2[["jobs", "loss_jobs"]].values,
                               hovertemplate="%{y}<br>%{x:.1f}% margin<br>%{customdata[0]} jobs, %{customdata[1]} lose money<extra></extra>"))
        st.plotly_chart(style(fig, legend=False), use_container_width=True)
    a, b = st.columns(2)
    with a:
        st.subheader("Jobs per month")
        jm = M.jobs_by_month(D, F)
        fig = go.Figure(go.Bar(x=jm.shoot_date, y=jm.jobs, marker_color=[BLUE if m in (11, 12) else GRAY for m in jm.shoot_date.dt.month],
                               hovertemplate="%{x|%b %Y}<br>%{y} jobs<extra></extra>"))
        st.plotly_chart(style(fig, legend=False), use_container_width=True)
        st.caption("November and December highlighted: the peak season.")
    with b:
        st.subheader("Revenue by job status")
        sm = M.status_mix(D, F)
        fig = go.Figure(go.Bar(y=sm.status, x=sm.net_amount_ngn, orientation="h", marker_color=BLUE,
                               hovertemplate="%{y}<br>₦%{x:,.0f}<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(style(fig, legend=False), use_container_width=True)
        st.caption("Invoiced, In Production and Postponed revenue is booked but not yet banked.")
    with st.expander("Table: service lines"):
        st.dataframe(svc.round(1), hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ merch
with tab_m:
    col = M.collection_summary(D, F)
    mq = M.merch_by_quarter(D, F)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Merch net revenue", ngn(mq.sum()))
    k2.metric("Contribution after cost of goods", ngn(col.contribution_ngn.sum()))
    k3.metric("Refund rate (value)", f"{100 * col.refunds_ngn.sum() / max(col.gross_ngn.sum(), 1):.1f}%")
    k4.metric("Units sold", f"{int(col.units.sum()):,}")
    a, b = st.columns(2)
    with a:
        st.subheader("Net revenue by quarter")
        fig = go.Figure(go.Bar(x=mq.index, y=mq.values, marker_color=ORANGE, hovertemplate="%{x}<br>₦%{y:,.0f}<extra></extra>"))
        st.plotly_chart(style(fig, legend=False), use_container_width=True)
    with b:
        st.subheader("Contribution by collection")
        c2_ = col.sort_values("net_ngn")
        fig = go.Figure()
        fig.add_bar(y=c2_.collection, x=c2_.cogs_ngn, orientation="h", name="Cost of goods", marker_color=GRAY,
                    hovertemplate="%{y}<br>COGS ₦%{x:,.0f}<extra></extra>")
        fig.add_bar(y=c2_.collection, x=c2_.contribution_ngn, orientation="h", name="Contribution", marker_color=BLUE,
                    hovertemplate="%{y}<br>Contribution ₦%{x:,.0f}<extra></extra>")
        fig.update_layout(barmode="stack")
        st.plotly_chart(style(fig), use_container_width=True)
    a, b = st.columns(2)
    with a:
        st.subheader("Refunds by reason")
        rr = M.refund_reasons(D, F).sort_values("refunds")
        fig = go.Figure(go.Bar(y=rr.reason, x=rr.share_pct, orientation="h", marker_color=BLUE,
                               text=[f"{v:.1f}%" for v in rr.share_pct], textposition="outside",
                               hovertemplate="%{y}<br>%{x:.1f}% of refunds<extra></extra>"))
        st.plotly_chart(style(fig, legend=False), use_container_width=True)
    with b:
        st.subheader("Collections")
        st.dataframe(col.round(1), hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ acquisition
with tab_a:
    ch = M.channel_summary(D, F)
    tq = M.traffic_quality(D, F)
    at = M.attribution(D, F)
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Human sessions", f"{int(ch.sessions.sum()):,}", f"{tq['bots']:,} bot sessions removed (all channels)",
              delta_color="off")
    k2.metric("Conversion rate", f"{100 * ch.conversions.sum() / max(ch.sessions.sum(), 1):.2f}%")
    k3.metric("Ad spend", ngn(ch.spend_ngn.sum()))
    paid = ch[(ch.spend_ngn > 0) & (ch.sessions > 0)]
    k4.metric("Paid ROAS (tracked)", f"{paid.revenue_ngn.sum() / paid.spend_ngn.sum():.2f}" if len(paid) else "–")
    k5.metric("Conversions joined to a real order", f"{at['joined_pct']:.1f}%" if at["converted"] else "–",
              f"{ngn(at['unattributed_revenue_ngn'])} unattributed", delta_color="off")
    a, b = st.columns(2)
    with a:
        st.subheader("Ad spend vs tracked revenue")
        c3_ = ch[ch.spend_ngn > 0]
        fig = go.Figure()
        fig.add_bar(x=c3_.channel_name, y=c3_.spend_ngn, name="Ad spend", marker_color=ORANGE,
                    hovertemplate="%{x}<br>Spend ₦%{y:,.0f}<extra></extra>")
        fig.add_bar(x=c3_.channel_name, y=c3_.revenue_ngn, name="Tracked revenue", marker_color=BLUE,
                    hovertemplate="%{x}<br>Revenue ₦%{y:,.0f}<extra></extra>")
        st.plotly_chart(style(fig), use_container_width=True)
        st.caption("Influencer has spend but no tracking source, so its return cannot be measured.")
    with b:
        st.subheader("ROAS by quarter")
        cq = M.channel_by_quarter(D, F)
        cq = cq[cq.spend_ngn > 0]
        fig = go.Figure()
        palette = {"Google": BLUE, "Meta": ORANGE, "TikTok": AQUA, "YouTube": "#eda100", "Email": "#e87ba4"}
        for name in [c for c in M.CHANNELS if c in set(cq.channel_name)]:
            z = cq[cq.channel_name == name]
            if z.revenue_ngn.sum() == 0:
                continue
            fig.add_scatter(x=z.quarter, y=z.roas, name=name, mode="lines+markers",
                            line=dict(width=2, color=palette.get(name, GRAY)),
                            hovertemplate=name + "<br>%{x}: ₦%{y:.2f} per ₦1<extra></extra>")
        fig.add_hline(y=1, line_color=MUTED, line_width=1, annotation_text="break-even", annotation_position="top left")
        st.plotly_chart(style(fig), use_container_width=True)
        st.caption("Values above the break-even line return more tracked revenue than they cost.")
    st.subheader("Channel table")
    st.dataframe(ch.round(2), hide_index=True, use_container_width=True)
