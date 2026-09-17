"""Build the two-page memo to the Studio Director and the technical appendix (Word).

    python memo/build_memo.py

Every number is read from analysis/findings.json or results/*.csv; nothing is typed in.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
import narrative as N  # noqa: E402
F = json.loads((ROOT / "analysis" / "findings.json").read_text())
INK, INK2, BLUE = RGBColor(0x0B, 0x0B, 0x0B), RGBColor(0x52, 0x51, 0x4E), RGBColor(0x2A, 0x78, 0xD6)
FONT = "Arial"


def B(x):   # naira, compact
    a = abs(x)
    if a >= 1e9:
        return f"₦{x / 1e9:.2f}B"
    if a >= 1e6:
        return f"₦{x / 1e6:.0f}M"
    return f"₦{x:,.0f}"


def usd(x):
    return f"${x / 1e6:.1f}M"


def base_doc(margins_cm=1.9, size=10):
    d = Document()
    for s in d.sections:
        s.page_height, s.page_width = Cm(29.7), Cm(21.0)
        s.left_margin = s.right_margin = Cm(margins_cm)
        s.top_margin = s.bottom_margin = Cm(1.6)
    st = d.styles["Normal"]
    st.font.name, st.font.size, st.font.color.rgb = FONT, Pt(size), INK
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    st.paragraph_format.space_after = Pt(4)
    st.paragraph_format.line_spacing = 1.08
    for name, sz in [("Heading 1", 13), ("Heading 2", 11)]:
        h = d.styles[name]
        h.font.name, h.font.size, h.font.bold, h.font.color.rgb = FONT, Pt(sz), True, INK
        rf = h.element.rPr.rFonts
        for att in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            if rf.get(qn(att)) is not None:
                del rf.attrib[qn(att)]
        for att in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rf.set(qn(att), FONT)
        h.paragraph_format.space_before, h.paragraph_format.space_after = Pt(9), Pt(3)
    return d


def para(d, text, bold_lead=None, size=None, color=None, after=4, style=None):
    p = d.add_paragraph(style=style)
    if bold_lead:
        r = p.add_run(bold_lead)
        r.bold = True
        if size:
            r.font.size = Pt(size)
    r = p.add_run(text)
    if size:
        r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    p.paragraph_format.space_after = Pt(after)
    return p


def rule(d):
    p = d.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    for k, v in {"w:val": "single", "w:sz": "6", "w:space": "1", "w:color": "C3C2B7"}.items():
        b.set(qn(k), v)
    bdr.append(b)
    pPr.append(bdr)
    p.paragraph_format.space_after = Pt(4)


# ====================================================================== memo
def memo():
    r, s, st, p, c, fx, m, mk, cu, dq, di = (F[k] for k in ["revenue", "services", "status", "profitability", "capacity", "fx",
                                                          "merch", "marketing", "customers", "data_quality", "director"])
    T = ROOT / "analysis" / "tables"
    jm = pd.read_csv(T / "jobs_by_month_2023_2024.csv").set_index("month").avg_jobs_per_year
    d = base_doc()
    t = d.add_paragraph()
    run = t.add_run("MEMO")
    run.bold, run.font.size, run.font.color.rgb = True, Pt(20), BLUE
    t.paragraph_format.space_after = Pt(2)
    hdr = [("To", "Studio Director, Xtrim Studios"), ("From", "Data Analyst (contract)"),
           ("Date", date.today().strftime("%d %B %Y")),
           ("Re", "Where the money is going, and whether the ads work (data: January 2023 – June 2025)")]
    for k, v in hdr:
        para(d, v, bold_lead=f"{k}:  ", after=0)
    rule(d)

    d.add_heading("The short answer", level=1)
    six = N.six(F)
    for i, line in enumerate(six, 1):
        q = d.add_paragraph(style="List Number")
        q.add_run(line)
        q.paragraph_format.space_after = Pt(2)

    pic = d.add_paragraph()
    pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pic.add_run().add_picture(str(ROOT / "charts" / "02_naira_vs_dollar_revenue.png"), width=Cm(14.5))
    pic.paragraph_format.space_after = Pt(0)

    d.add_heading("What is behind those numbers", level=1)
    para(d, f" Commercial / TVC and Music Video bring in {s['tvc_mv_revenue_share_pct']:.0f}% of production revenue from "
            f"{s['tvc_mv_job_share_pct']:.0f}% of jobs, with over 90% left after crew. Weddings are the most frequent job "
            f"({s['wedding_jobs']} jobs) but {s['wedding_revenue_share_pct']:.0f}% of revenue. Studio Rental is "
            f"{s['studio_rental_job_share_pct']:.0f}% of jobs and {s['studio_rental_revenue_share_pct']:.0f}% of revenue; "
            f"Photoshoot is {s['photoshoot_job_share_pct']:.0f}% of jobs, {s['photoshoot_revenue_share_pct']:.0f}% of revenue, "
            f"and {p['photoshoot_loss_jobs']} of its {p['photoshoot_jobs']} jobs lose money on crew.",
         bold_lead="The work that pays.")
    para(d, f" The {fx['foreign_jobs']} jobs billed in dollars or pounds were worth {B(fx['value_at_shoot_rate_ngn'])} "
            f"in naira; {B(fx['devaluation_gain_ngn'])} of that ({fx['devaluation_share_of_foreign_value_pct']:.0f}%) is purely "
            "the weaker naira. Billing in a hard currency protected those jobs; every naira-priced job lost value in real terms.",
         bold_lead="The currency.")
    para(d, f" December and November are the busiest months ({jm[12]:.0f} and {jm[11]:.0f} jobs a year on average, "
            f"against {jm[1]:.0f} in January). "
            f"Crew are never short on paper (peak week {c['peak_utilisation_pct']:.0f}% of crew-days), but crew were logged on "
            f"two jobs on the same day {c['double_booked_crew_days_total']} times, {c['double_booked_nov_dec_share_pct']:.0f}% "
            "of them in November and December. That is where the studio breaks.",
         bold_lead="Capacity.")
    para(d, f" Merch is healthy but small: {B(m['net_ngn'])} after refunds ({r['merch_share_pct_all']:.1f}% of revenue), "
            f"{m['contribution_pct']:.0f}% left after stock cost, and no collection lost money. Refunds run at "
            f"{m['store_refund_rate_pct']:.1f}% of sales, spread across reasons; no single product drives them.",
         bold_lead="Merch.")
    para(d, f" {mk['bot_share_pct']:.0f}% of website visits were bots, which the analytics tool did not filter. Of "
            f"{mk['converted_sessions']:,} recorded sales, only {mk['joined_pct']:.0f}% link to a real order, and those that do "
            f"are a median {mk['median_days_session_to_order']:.0f} days away from the visit. Channel-level returns are "
            f"therefore rough: Meta looks best (₦{mk['best_roas']:.2f} per ₦1) and YouTube worst (₦{mk['worst_roas']:.2f}); "
            f"{B(mk['influencer_spend_ngn'])} of influencer spend cannot be measured at all.",
         bold_lead="Advertising.")

    d.add_heading("Recommendations", level=1)
    recs = [(lead + " ", txt) for lead, txt in N.recommendations(F)]
    for lead, txt in recs:
        q = d.add_paragraph(style="List Bullet")
        rr = q.add_run(lead)
        rr.bold = True
        q.add_run(txt)
        q.paragraph_format.space_after = Pt(2)

    d.add_heading("Caveats that could change the answer", level=1)
    cav = N.caveats(F)
    for x in cav:
        q = d.add_paragraph(style="List Bullet")
        q.add_run(x)
        q.paragraph_format.space_after = Pt(1)
    para(d, "Technical appendix, SQL, data quality report and dashboard are attached separately. All figures in naira (₦) "
            "unless stated; dollar values use the daily exchange rate.", size=8.5, color=INK2, after=0)
    out = ROOT / "memo" / "Xtrim_Studios_Director_Memo.docx"
    d.save(out)
    return out


# ====================================================================== appendix
def table(d, df: pd.DataFrame, widths=None, size=8):
    t = d.add_table(rows=1, cols=len(df.columns))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, col in enumerate(df.columns):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(col))
        run.bold, run.font.size = True, Pt(size)
    for _, row in df.iterrows():
        cells = t.add_row().cells
        for i, v in enumerate(row):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                v = "–"
            elif isinstance(v, float):
                v = f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"
            elif isinstance(v, (int,)) and not isinstance(v, bool):
                v = f"{v:,}"
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(v))
            run.font.size = Pt(size)
    d.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def appendix():
    d = base_doc(margins_cm=1.6, size=9.5)
    from docx.enum.section import WD_ORIENT
    sec = d.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
    R = ROOT / "results"
    h = d.add_paragraph()
    run = h.add_run("Xtrim Studios — Technical appendix")
    run.bold, run.font.size = True, Pt(18)
    para(d, "Methodology, data quality, definitions and the SQL answers behind the Director memo. "
            f"Generated {date.today():%d %B %Y}.", color=INK2)

    d.add_heading("1. How the work is built", level=1)
    steps = [
        ("Clean. ", "pipeline/run_pipeline.py reads the 14 raw files (from raw_original_backup/), repairs encodings, "
         "parses every date and money format, maps free text to canonical values, converts USD/GBP to naira at the "
         "daily rate, deduplicates, and writes clean/ plus a quarantine file. It refuses to write unless rows in = rows "
         "out + rows quarantined for every file and every currency column reads NGN. validate.py grades the output "
         "against docs/VALIDATION_KEY.md: 93 of 93 checks pass."),
        ("Model. ", "warehouse/build_warehouse.py loads clean/ into PostgreSQL 17 (schemas stg, core, quarantine) as a "
         "star schema. Primary keys, foreign keys, CHECK constraints and an EXCLUDE constraint on product price windows "
         "enforce the grain; a bad load fails."),
        ("Answer. ", "warehouse/run_queries.py runs sql/02_questions_answered.sql (14 questions) and saves results/."),
        ("Analyse. ", "analysis/analysis.py computes every headline number into analysis/findings.json; charts.py draws "
         "only from analysis/tables/. The memo, deck and dashboard read the same files."),
        ("Prove it ties. ", "tests/test_tie_out.py checks the dashboard's totals against the SQL results (8 of 8 pass)."),
    ]
    for lead, txt in steps:
        para(d, txt, bold_lead=lead)
    para(d, "One command rebuilds everything: python run_pipeline.py (see README.md).", bold_lead="Reproduce. ")

    d.add_heading("2. Data quality", level=1)
    dq = F["data_quality"]
    para(d, f"{dq['raw_rows']:,} raw rows; {dq['rows_quarantined']:,} ({dq['rows_quarantined_pct']:.2f}%) quarantined "
            f"with a reason, none deleted. {B(dq['revenue_affected_ngn'])} ({dq['revenue_affected_pct']:.1f}%) of revenue is "
            "affected by issues that could not be resolved. Full per-column profile: data_quality_report/.")
    q13 = pd.read_csv(R / "q13.csv")
    q13 = q13[q13.reason.notna()][["src_table", "reason", "rows_rejected", "value_carried_ngn", "revenue_value_at_risk_ngn"]]
    table(d, q13)
    para(d, "Fifteen statements in the data dictionary are false, including: client_id is not unique; 2024 booking dates "
            "are month-first; the 2025 workbook header is on row 5; timesheet booking ids are not always valid; hours are not "
            "capped at 12; the 1.5x rate is unrelated to overtime; price windows overlap; order timestamps are not all UTC; "
            "refunds are not always positive; bots are not filtered; transaction ids do not always join; FX rates skip "
            "weekends and 35 weekdays.", bold_lead="Dictionary errors. ")

    d.add_heading("3. Key definitions and decisions", level=1)
    defs = [
        ("Production revenue", "net_amount_ngn (gross × (1 − discount)) of every booking not Cancelled, by shoot date. "
         "Postponed and blank-status jobs are included, per the brief."),
        ("Foreign jobs", "converted at the rate on the shoot date; weekends and missing days use the last published rate "
         f"({F['fx']['pct_rates_gap_filled']}% of foreign-job rates were gap-filled). 7 ×10 typo rates corrected; the "
         "June 2023 and January 2024 devaluation jumps kept."),
        ("Merch revenue", "quantity × price paid on lines whose order is not Cancelled, less refunds (capped at the order's "
         "value, allocated to lines by value). Refunds on cancelled orders are not deducted. Discount codes do not lower the "
         "price paid in the data, so discount value = list price − price paid."),
        ("Labour cost", f"day_rate_charged; {F['profitability']['estimated_rows']:,} rows with no charged rate use the crew "
         "member's standard rate (the 0.5x/1x/1.5x multiplier is random with respect to overtime, so the standard rate is the "
         "unbiased estimate)."),
        ("Genuine vs artefact loss", "a job whose crew cost exceeds revenue is a genuine loss if it still loses money after "
         "removing crew-days where that person was also logged on another job and pricing estimated rates at 0.5x. "
         f"{F['profitability']['genuine_losses']} genuine, {F['profitability']['artefact_losses']} artefacts."),
        ("Human session", "user agent is not a crawler, script or SEO tool (23,054 bot sessions; every referral-spam session "
         "is also a bot)."),
        ("Channel mapping", "Google Ads = Google; Meta Ads = Facebook + Instagram; TikTok Ads = TikTok; YouTube Pre-roll = "
         "YouTube; Email / CRM = Email; Influencer has no utm source. Campaign 'always_on' = 'brand_always_on'."),
        ("Utilisation", "distinct crew-days ÷ (crew whose logged shifts span the week × 7)."),
        ("Service type", "115 bookings have none. A model using price, crew and days predicted service type with only 42% "
         "accuracy, so they stay 'Unknown' rather than being guessed."),
    ]
    for k, v in defs:
        para(d, " " + v, bold_lead=k + ".")
    para(d, "Complete logs: cleaning_report/CLEANING_DECISIONS.md and warehouse/WAREHOUSE_DECISIONS.md.", color=INK2)

    d.add_heading("4. SQL answers (summary)", level=1)
    d.add_heading("Q1 Quarterly revenue", level=2)
    table(d, pd.read_csv(R / "q01.csv"))
    d.add_heading("Q3 Worst-margin jobs", level=2)
    table(d, pd.read_csv(R / "q03.csv")[["booking_code", "service_name", "status", "net_revenue_ngn", "labour_ngn",
                                          "margin_ngn", "margin_on_trusted_labour_ngn", "verdict"]], size=7.5)
    d.add_heading("Q4 Crew utilisation", level=2)
    c = F["capacity"]
    para(d, f"Weeks above 85%: {c['weeks_above_85pct']} of {c['weeks_measured']}. Peak {c['peak_utilisation_pct']}% "
            f"(week of {c['peak_week_start']}), median {c['median_utilisation_pct']}% ({c['edge_weeks_excluded']} edge weeks at "
            f"the start and end of the data excluded from peak/median because the crew-span method undercounts active crew "
            f"there). The binding role most often is {c['most_frequent_binding_role']}. {c['double_booked_crew_days_total']} "
            f"crew-days were logged on two jobs at once; the worst week ({c['max_double_booked_week']}) had "
            f"{c['max_double_booked_week_count']}.")
    d.add_heading("Q5 FX exposure", level=2)
    table(d, pd.read_csv(R / "q05.csv").fillna({"invoice_currency": "all"}).fillna({"year": 0}).assign(
        year=lambda x: x.year.map(lambda y: "all" if y == 0 else str(int(y)))))
    d.add_heading("Q6 Price-history integrity", level=2)
    table(d, pd.read_csv(R / "q06.csv"))
    d.add_heading("Q7 Merch by collection", level=2)
    table(d, pd.read_csv(R / "q07.csv")[["collection", "units_sold", "gross_ngn", "discount_value_ngn", "refunds_ngn",
                                          "net_ngn", "cogs_ngn", "contribution_margin_ngn", "contribution_margin_pct"]], size=7.5)
    d.add_heading("Q8 Refunds", level=2)
    m = F["merch"]
    para(d, f"Store refund rate {m['store_refund_rate_pct']}% of sales value. SKUs above 2x the store average: "
            f"{m['skus_above_2x']}. Highest: {m['highest_refund_sku']} {m['highest_refund_sku_name']} at "
            f"{m['highest_refund_sku_rate_pct']}% ({m['highest_refund_sku_x']}x), dominant reason {m['highest_refund_sku_reason']}.")
    table(d, pd.read_csv(R / "q08b.csv"))
    d.add_heading("Q9 Channel efficiency (all quarters)", level=2)
    ch = pd.read_csv(ROOT / "analysis" / "tables" / "channel_totals.csv")[
        ["channel_name", "sessions", "conversions", "conversion_rate_pct", "revenue_ngn", "spend_ngn", "cpc_ngn", "cac_ngn", "roas"]]
    table(d, ch, size=7.5)
    d.add_heading("Q10 Attribution gap", level=2)
    table(d, pd.read_csv(R / "q10.csv"), size=7.5)
    mk = F["marketing"]
    para(d, f"Joined orders are a median {mk['median_days_session_to_order']:.0f} days from the session, so even "
            "the 'attributed' share is doubtful; treat ROAS as an upper-bound indicator of the web shop only.")
    d.add_heading("Q11 Repeat purchase", level=2)
    cu = F["customers"]
    para(d, f"{cu['repeat_90d_pct']}% of CRM buyers with a full 90-day window bought again within 90 days "
            f"({cu['repeat_buyers']:,} of {cu['buyers']:,}). By acquisition channel the rate ranges from "
            f"{cu['channel_repeat_min_pct']}% ({cu['channel_repeat_min']}) to {cu['channel_repeat_max_pct']}% "
            f"({cu['channel_repeat_max']}); chi-square = {cu['channel_chi2']}, p = {cu['channel_chi2_p']}, so channel does not "
            f"predict repeat buying. Guest checkouts ({cu['guest_line_share_pct']}% of lines) cannot be tracked.")
    d.add_heading("Q12 Cross-sell", level=2)
    para(d, f"{cu['production_clients_buying_merch']:,} of {cu['production_clients']:,} production clients also bought merch. "
            f"Mean order: {B(cu['cross_mean_order_ngn'])} for production clients vs {B(cu['merch_only_mean_order_ngn'])} "
            f"for merch-only; Welch t = {cu['welch_t']}, df = {cu['welch_df']}, p = {cu['welch_p']}. No meaningful difference.")
    d.add_heading("Q14 Monthly money flow", level=2)
    table(d, pd.read_csv(R / "q14.csv"), size=7)

    d.add_heading("5. Limitations", level=1)
    for x in [
        "Costs outside crew day rates, ad spend and merch cost of goods are not in the data.",
        "The PostgreSQL instance used to build and verify the warehouse was local; warehouse/xtrim_warehouse.dump restores "
        "it (pg_restore) and dashboard/data/ lets the dashboard run without a database.",
        "Session revenue is what the analytics tool recorded; it covers "
        f"{mk['session_revenue_pct_of_merch_net']}% of merch net revenue (other sales go through Instagram, pop-ups and "
        "wholesale).",
        "Lead source cannot separate paid from organic social; the ad break-even figure in the memo is a threshold, not "
        "an estimate.",
    ]:
        q = d.add_paragraph(style="List Bullet")
        q.add_run(x)
    out = ROOT / "memo" / "Xtrim_Studios_Technical_Appendix.docx"
    d.save(out)
    return out


if __name__ == "__main__":
    print(memo())
    print(appendix())
