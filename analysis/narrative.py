"""The words shared by the memo and the deck: the six-sentence answer, the recommendations and the
caveats. Built from findings.json and analysis tables only, so both documents say the same thing."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
T = ROOT / "analysis" / "tables"


def findings() -> dict:
    return json.loads((ROOT / "analysis" / "findings.json").read_text())


def B(x):
    a = abs(x)
    if a >= 1e9:
        return f"₦{x / 1e9:.2f}B"
    if a >= 1e6:
        return f"₦{x / 1e6:.0f}M"
    return f"₦{x:,.0f}"


def usd(x):
    return f"${x / 1e6:.1f}M"


def six(F=None) -> list[str]:
    F = F or findings()
    r, st, p, mk, di = F["revenue"], F["status"], F["profitability"], F["marketing"], F["director"]
    return [
        f"Revenue grew {r['growth_ngn_2024_vs_2023_pct']:.0f}% in naira, from {B(r['total_ngn_2023'])} in 2023 to "
        f"{B(r['total_ngn_2024'])} in 2024, but the dollar went from an average of ₦{r['usd_rate_avg_2023']:,.0f} to "
        f"₦{r['usd_rate_avg_2024']:,.0f}, so that revenue was worth {usd(r['usd_equiv_2023'])} in 2023 "
        f"and only {usd(r['usd_equiv_2024'])} in 2024.",
        f"{B(st['not_completed_revenue_ngn_all'])} ({st['not_completed_share_pct_all']:.0f}%) of the production work booked "
        f"since January 2023 had not reached Completed when the data was exported, including "
        f"{B(st['invoiced_2023_2024_ngn'])} on {st['invoiced_2023_2024_jobs']} jobs from 2023–2024 still marked Invoiced.",
        f"Postponed work has more than doubled, from {st['postponed_share_2023_pct']}% of revenue in 2023 to "
        f"{st['postponed_share_h1_2025_pct']}% in the first half of 2025.",
        f"Studio Rental loses money on crew cost alone ({p['studio_rental_margin_pct']}% margin; "
        f"{p['studio_rental_loss_jobs']} of {p['studio_rental_jobs']} jobs), and across the business "
        f"{p['loss_jobs']} jobs cost {B(p['loss_jobs_total_loss_ngn'])} more in crew than they earned.",
        f"The {B(mk['ad_spend_total_ngn'])} spent on ads brought back ₦{mk['blended_paid_roas']:.2f} of tracked web-shop "
        f"revenue per ₦1; they pay for themselves only if at least {mk['breakeven_share_of_social_leads_pct']}% of the "
        f"{B(mk['google_ig_tiktok_lead_revenue_ngn'])} of bookings credited to Google, Instagram and TikTok came from a paid ad, "
        "and no system records whether they did.",
        f"Crew, ads and merch stock take only {di['known_cost_pct_2024']}% of 2024 revenue, so the missing cash sits in what "
        "these systems do not record (dollar-priced kit and software, rent, salaries, tax) and in unpaid invoices, which is "
        "where finance should look first.",
    ]


def recommendations(F=None) -> list[tuple[str, str]]:
    F = F or findings()
    st = F["status"]
    ch = pd.read_csv(T / "channel_totals.csv").set_index("channel_name")
    yt_email = ch.loc[["YouTube", "Email"], "spend_ngn"].sum()
    return [
        ("Collect before you grow.", f"Chase the {B(st['invoiced_2023_2024_ngn'])} of 2023–2024 invoices this quarter, take a "
         "deposit at booking, and charge for postponements."),
        ("Price in dollars where you can.", "Quote Commercial, Music Video and international clients in USD or with an "
         "exchange-rate clause; it is the one lever that grew in value as the naira fell."),
        ("Fix or drop loss-making jobs.", "Set a minimum price or a crew cap for Studio Rental and Photoshoot so no job "
         "costs more in crew than it earns."),
        ("Test the ads before spending more.", "Add 'which ad?' and tracked links to the booking form, give influencers "
         f"codes, and pause YouTube and Email (the weakest measured returns, {B(yt_email)} of spend so far) for eight weeks "
         "to see whether bookings move."),
        ("Book November–December crew in September.", "Double bookings cluster in the peak; confirm freelancers early."),
    ]


def caveats(F=None) -> list[str]:
    F = F or findings()
    dq, s, mk, m = F["data_quality"], F["services"], F["marketing"], F["merch"]
    return [
        "No rent, equipment, salary, tax or bank data was provided. The cash explanation is an inference from what is "
        "missing, not a measurement; the bank statement would confirm or overturn it.",
        "Job status is a snapshot from mid-2025. 'Invoiced' is read as billed but unpaid; if finance marks paid invoices "
        "differently, the uncollected figure falls.",
        f"{dq['revenue_affected_pct']:.1f}% of revenue ({B(dq['revenue_affected_ngn'])}) is touched by data problems that "
        f"could not be resolved, mostly {s['unknown_service_jobs']} non-cancelled jobs with no service type. "
        f"{B(mk['unknown_lead_source_revenue_ngn'])} of bookings have no lead source.",
        f"Merch revenue counts Pending orders ({B(m['pending_gross_ngn'])}); if they never ship, merch revenue is that much lower.",
    ]
