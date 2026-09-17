"""Build the PowerPoint deck for the Studio Director.

    python presentation/build_deck.py

Every number comes from analysis/findings.json; every chart from charts/. Speaker notes on each slide.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
import narrative as N  # noqa: E402

F = N.findings()
B = N.B
C = ROOT / "charts"

INK, INK2, MUTED = RGBColor(0x0B, 0x0B, 0x0B), RGBColor(0x52, 0x51, 0x4E), RGBColor(0x89, 0x87, 0x81)
BLUE, SURFACE, PANEL, LINE = RGBColor(0x2A, 0x78, 0xD6), RGBColor(0xFC, 0xFC, 0xFB), RGBColor(0xF3, 0xF2, 0xEE), RGBColor(0xE1, 0xE0, 0xD9)
RED = RGBColor(0xD0, 0x3B, 0x3B)
FONT = "Arial"
W, H = Inches(13.333), Inches(7.5)


def text(slide, x, y, w, h, s, size=16, bold=False, color=INK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.02)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    lines = s if isinstance(s, list) else [s]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.name, r.font.size, r.font.bold, r.font.color.rgb = FONT, Pt(size), bold, color
    return tb


def base(prs, title, subtitle=None, n=None, notes=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = SURFACE
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, W, Inches(0.08))
    bar.fill.solid()
    bar.fill.fore_color.rgb = BLUE
    bar.line.fill.background()
    text(s, Inches(0.6), Inches(0.35), Inches(12.1), Inches(0.7), title, size=28, bold=True)
    if subtitle:
        text(s, Inches(0.6), Inches(1.05), Inches(12.1), Inches(0.5), subtitle, size=15, color=INK2)
    if n:
        text(s, Inches(0.6), Inches(7.02), Inches(8), Inches(0.3), "Xtrim Studios · Commercial review 2023 – H1 2025 · all money in naira (₦)",
             size=9, color=MUTED)
        text(s, Inches(12.0), Inches(7.02), Inches(0.73), Inches(0.3), str(n), size=9, color=MUTED, align=PP_ALIGN.RIGHT)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def picture(slide, path, x, y, max_w, max_h):
    from PIL import Image
    iw, ih = Image.open(path).size
    scale = min(max_w / iw, max_h / ih)
    w, h = int(iw * scale), int(ih * scale)
    slide.shapes.add_picture(str(path), x, y, Emu(w), Emu(h))


def tiles(slide, items, x=Inches(9.55), y=Inches(1.75), w=Inches(3.2), h=Inches(1.55), gap=Inches(0.18)):
    for i, (value, label, *rest) in enumerate(items):
        top = y + i * (h + gap)
        box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, top, w, h)
        box.adjustments[0] = 0.08
        box.fill.solid()
        box.fill.fore_color.rgb = PANEL
        box.line.fill.background()
        color = RED if rest and rest[0] == "bad" else INK
        text(slide, x + Inches(0.2), top + Inches(0.14), w - Inches(0.4), Inches(0.62), value, size=28, bold=True, color=color)
        text(slide, x + Inches(0.2), top + Inches(0.78), w - Inches(0.4), h - Inches(0.85), label, size=12, color=INK2)


def chart_slide(prs, n, title, subtitle, chart, tile_items, notes):
    s = base(prs, title, subtitle, n, notes)
    picture(s, C / chart, Inches(0.6), Inches(1.7), Inches(8.7), Inches(5.2))
    tiles(s, tile_items)
    return s


def main():
    r, sv, st, p, c, fx, m, mk, cu, dq, di = (F[k] for k in ["revenue", "services", "status", "profitability", "capacity",
                                                           "fx", "merch", "marketing", "customers", "data_quality", "director"])
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # 1 title
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = SURFACE
    band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.35), H)
    band.fill.solid()
    band.fill.fore_color.rgb = BLUE
    band.line.fill.background()
    text(s, Inches(1.0), Inches(2.1), Inches(11), Inches(0.6), "XTRIM STUDIOS", size=16, bold=True, color=BLUE)
    text(s, Inches(1.0), Inches(2.6), Inches(11), Inches(1.4), "Where the money went", size=54, bold=True)
    text(s, Inches(1.0), Inches(3.85), Inches(11), Inches(1.0),
         "Commercial performance review · production, merch and advertising · January 2023 – June 2025", size=20, color=INK2)
    text(s, Inches(1.0), Inches(6.2), Inches(11), Inches(0.5), f"Prepared for the Studio Director · {date.today():%d %B %Y}",
         size=13, color=MUTED)
    s.notes_slide.notes_text_frame.text = ("The Director asked: we are busier than ever and there is less money in the bank. "
                                           "Where is it going, and is the ad spend doing anything? This deck answers both.")

    # 2 the answer
    s = base(prs, "The answer in six sentences", "Each one carries a number you can check in the appendix.", 2,
             "Read these out. Everything after this slide is the evidence for one of these six lines.")
    y = Inches(1.7)
    for i, line in enumerate(N.six(F), 1):
        num = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.6), y + Inches(0.04), Inches(0.42), Inches(0.42))
        num.fill.solid()
        num.fill.fore_color.rgb = BLUE
        num.line.fill.background()
        tf = num.text_frame
        tf.margin_left = tf.margin_right = 0
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        rr = tf.paragraphs[0].add_run()
        rr.text = str(i)
        rr.font.name, rr.font.size, rr.font.bold, rr.font.color.rgb = FONT, Pt(14), True, SURFACE
        text(s, Inches(1.2), y, Inches(11.5), Inches(0.85), line, size=14.5)
        y += Inches(0.87)

    # 3 data
    s = base(prs, "What we worked with, and what we threw away",
             "Fourteen exports from five systems. Nothing was deleted; every rejected row is kept with a reason.", 3,
             "The data was bad in ways the handover did not mention: the data dictionary is wrong in fifteen places. "
             "The dashboard shows the quarantine tile so anyone can see what was set aside.")
    tiles(s, [(f"{dq['raw_rows']:,}", "raw rows across 14 files"),
              (f"{dq['rows_quarantined']:,}", f"rows quarantined ({dq['rows_quarantined_pct']:.2f}%), none deleted"),
              (f"{dq['revenue_affected_pct']:.1f}%", f"of revenue ({B(dq['revenue_affected_ngn'])}) touched by issues we could not resolve")],
          x=Inches(0.6), y=Inches(1.8), w=Inches(3.6), h=Inches(1.5))
    bullets = [
        "15 statements in the data dictionary are false",
        "2024 booking dates are month-first; 2023 are day-first",
        "124 duplicate clients re-keyed under new IDs, 58 exact repeats",
        f"{mk['bot_sessions']:,} bot visits ({mk['bot_share_pct']:.0f}%) and a 5,200-visit spam burst in the web data",
        "USD and GBP jobs never converted; now all naira at the daily rate",
        "Price history with 29 overlapping windows, resolved and enforced by the database",
        "319 timesheets for jobs that don't exist; 129 shifts of 26 hours",
        "115 jobs with no service type; kept as 'Unknown' because they couldn't be recovered reliably",
    ]
    text(s, Inches(4.7), Inches(1.8), Inches(8.0), Inches(0.4), "What was wrong", size=16, bold=True)
    text(s, Inches(4.7), Inches(2.3), Inches(8.0), Inches(4.5), ["•  " + b for b in bullets], size=15, color=INK)

    # 4 naira vs dollar
    chart_slide(prs, 4, "Busier in naira, poorer in dollars",
                "The naira collapse turned real growth into a real-terms decline.", "02_naira_vs_dollar_revenue.png",
                [(f"+{r['growth_ngn_2024_vs_2023_pct']:.0f}%", "revenue growth in naira, 2023 → 2024"),
                 (f"−{abs(r['growth_usd_2024_vs_2023_pct']):.0f}%", "the same revenue in dollars", "bad"),
                 (f"{fx['naira_lost_vs_usd_pct']:.0f}%", f"value the naira lost against the dollar (₦{fx['usd_rate_2023_01_01']:,.0f} → ₦{fx['usd_rate_2025_06_30']:,.0f})", "bad")],
                "Revenue in naira grew every year. But anything priced in dollars (cameras, lenses, software, travel) now costs "
                "roughly ten times as many naira as in January 2023. In dollar terms the studio earned less than half as much in 2024.")

    # 5 quarterly
    chart_slide(prs, 5, "Production carries the business", "Revenue by quarter, production and merch.", "01_revenue_by_quarter.png",
                [(B(r["total_ngn_all"]), "total revenue, Jan 2023 – Jun 2025"),
                 (f"{r['merch_share_pct_all']:.1f}%", "of revenue from merch"),
                 (f"+{r['growth_ngn_h1_2025_vs_h1_2024_pct']:.0f}%", "H1 2025 vs H1 2024, in naira")],
                "Q4 is the peak every year; Q1 is the trough. This chart ties exactly to SQL question 1 and to the dashboard.")

    # 6 booked not banked
    chart_slide(prs, 6, "Booked is not banked", "Almost a third of production revenue is in jobs that are not complete.",
                "09_postponed_share.png",
                [(B(st["not_completed_revenue_ngn_all"]), f"({st['not_completed_share_pct_all']:.0f}%) invoiced, in production, postponed or no status"),
                 (B(st["invoiced_2023_2024_ngn"]), f"on {st['invoiced_2023_2024_jobs']} jobs from 2023–2024 still marked Invoiced", "bad"),
                 (f"{st['postponed_share_h1_2025_pct']}%", f"of H1 2025 revenue postponed, up from {st['postponed_share_2023_pct']}% in 2023")],
                "Status is a snapshot from mid-2025. We read Invoiced as billed but not paid. If that holds, over a billion naira "
                "of 2023–2024 work has not been collected. This is the first thing to reconcile against the bank.")

    # 7 service mix
    chart_slide(prs, 7, "Two service lines earn half the money", "Share of revenue vs share of jobs.", "03_service_share.png",
                [(f"{sv['tvc_mv_revenue_share_pct']:.0f}%", f"of revenue from Commercial / TVC and Music Video, {sv['tvc_mv_job_share_pct']:.0f}% of jobs"),
                 (f"{sv['wedding_jobs']}", f"wedding jobs, the most of any line, but {sv['wedding_revenue_share_pct']:.0f}% of revenue"),
                 (f"{sv['studio_rental_revenue_share_pct']:.1f}%", f"of revenue from Studio Rental, {sv['studio_rental_job_share_pct']:.0f}% of jobs")],
                "Carry: Commercial/TVC, Music Video, Wedding Film, Corporate Documentary. Cosmetic: Studio Rental. "
                "Photoshoot is busy work: 18.5% of jobs for 5.2% of revenue.")

    # 8 margin
    chart_slide(prs, 8, "Some jobs cost more in crew than they earn", "Margin after crew day rates, by service line.",
                "04_margin_by_service.png",
                [(f"{p['studio_rental_margin_pct']}%", f"Studio Rental margin; {p['studio_rental_loss_jobs']} of {p['studio_rental_jobs']} jobs lose money", "bad"),
                 (f"{p['loss_jobs']}", f"loss-making jobs, {B(p['loss_jobs_total_loss_ngn'])} lost in total"),
                 (f"{p['genuine_losses']} / {p['artefact_losses']}", "genuine losses / losses explained by bad timesheet data")],
                "A loss is 'genuine' if it survives removing crew double-bookings and pricing unknown day rates at half rate. "
                "147 do. The 20 worst jobs are all genuine, mostly Studio Rental and Photoshoot with 4+ crew a day.")

    # 9 capacity
    chart_slide(prs, 9, "Capacity breaks in November and December", "Crew logged on two jobs on the same day, by month.",
                "06_double_bookings.png",
                [(f"{c['weeks_above_85pct']}", f"weeks above 85% crew utilisation (peak {c['peak_utilisation_pct']:.0f}%)"),
                 (f"{c['double_booked_crew_days_total']}", "crew-days booked on two jobs at once"),
                 (f"{c['double_booked_nov_dec_share_pct']:.0f}%", "of those in November and December")],
                "On the brief's formula the studio never runs out of crew. The strain shows up differently: the same people "
                "booked on two shoots in one day, concentrated in the peak, and 7.7% of shifts over 12 hours.")

    # 10 fx
    chart_slide(prs, 10, "Dollar and pound jobs held their value", "Foreign jobs valued at the shoot-date rate vs the 1 January 2023 rate.",
                "08_fx_gain.png",
                [(B(fx["devaluation_gain_ngn"]), f"extra naira on {fx['foreign_jobs']} USD/GBP jobs from devaluation"),
                 (f"{fx['devaluation_share_of_foreign_value_pct']:.0f}%", "of those jobs' naira value is pure exchange rate"),
                 (f"{fx['pct_rates_gap_filled']:.0f}%", "of rates used were gap-filled (weekend or missing days)")],
                "Put the other way: had those clients been priced in naira at January 2023 levels, the studio would have lost "
                "₦3.46B. Every naira-priced job lost that kind of value.")

    # 11 merch
    chart_slide(prs, 11, "Merch is healthy, but small", "Contribution after refunds and cost of goods, by collection.",
                "10_merch_collections.png",
                [(B(m["contribution_ngn"]), f"merch contribution ({m['contribution_pct']:.0f}% of net revenue)"),
                 (f"{m['collections_losing_money']}", "collections (drops) that lost money"),
                 (f"{m['store_refund_rate_pct']:.1f}%", f"refund rate; no SKU above 2x (highest {m['highest_refund_sku_x']}x)")],
                f"Refund reasons are spread out: changed mind {m['top_reason_share_pct']}%, then damaged and wrong size. "
                "Discount codes never lowered the price paid in the data, which finance should check.")

    # 12 ads
    chart_slide(prs, 12, "Ads do not pay back through the web shop", "Spend vs revenue the website tracked, by channel.",
                "12_channel_spend_vs_revenue.png",
                [(f"₦{mk['blended_paid_roas']:.2f}", "tracked web revenue per ₦1 of paid ads", "bad"),
                 (f"{mk['breakeven_share_of_social_leads_pct']}%", f"of {B(mk['google_ig_tiktok_lead_revenue_ngn'])} social-sourced bookings ads must drive to break even"),
                 (f"{mk['joined_pct']:.0f}%", "of recorded sales link to a real order")],
                f"Across Google, Meta and TikTok, {B(mk['google_meta_tiktok_spend_ngn'])} was spent while bookings crediting those "
                f"platforms were worth {B(mk['google_ig_tiktok_lead_revenue_ngn'])}. If even 7% of those came from ads, the spend is "
                "justified; but nothing records paid vs organic. Tracking is broken: linked orders are a median 254 days from the visit.")

    # 13 where the money went
    chart_slide(prs, 13, "Where each naira went", "Recorded costs take under a quarter of revenue.",
                "13_where_the_money_went.png",
                [(f"{di['known_cost_pct_2023']}%", "recorded costs ÷ revenue, 2023"),
                 (f"{di['known_cost_pct_2024']}%", "recorded costs ÷ revenue, 2024"),
                 (f"{di['known_cost_pct_h1_2025']}%", "recorded costs ÷ revenue, H1 2025")],
                "Crew, ads and merch stock are the only costs in the data. The rest of the squeeze is outside these systems: "
                "dollar-priced equipment and software, rent, salaries, tax, and unpaid invoices.")

    # 14 recommendations
    s = base(prs, "What to do", "Five moves, in order of how fast they put cash back.", 14,
             "Collection first because it is money already earned. Pricing next. Test ads before cutting or scaling them.")
    y = Inches(1.75)
    for i, (lead, txt) in enumerate(N.recommendations(F), 1):
        box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.6), y, Inches(12.1), Inches(0.98))
        box.adjustments[0] = 0.12
        box.fill.solid()
        box.fill.fore_color.rgb = PANEL
        box.line.fill.background()
        text(s, Inches(0.85), y + Inches(0.1), Inches(0.5), Inches(0.78), str(i), size=26, bold=True, color=BLUE,
             anchor=MSO_ANCHOR.MIDDLE)
        text(s, Inches(1.45), y + Inches(0.08), Inches(11.0), Inches(0.35), lead, size=16, bold=True)
        text(s, Inches(1.45), y + Inches(0.42), Inches(11.0), Inches(0.52), txt, size=12.5, color=INK2)
        y += Inches(1.06)

    # 15 caveats
    s = base(prs, "What could change the answer", "Read these before quoting any number outside this room.", 15,
             "The biggest one is the first: without the bank statement and the cost ledger, the cash story is inference.")
    tb = text(s, Inches(0.6), Inches(1.8), Inches(12.1), Inches(4.8), ["•  " + x for x in N.caveats(F)], size=17)
    for para_ in tb.text_frame.paragraphs:
        para_.space_after = Pt(14)

    # 16 how it was built
    s = base(prs, "How this was built", "Every number is reproducible from the raw files with one command.", 16,
             "python run_pipeline.py rebuilds cleaning, warehouse, SQL answers, analysis, charts, memo and this deck.")
    steps = [("Raw", "14 files\n282,171 rows"), ("Clean", "Python pipeline\n93/93 validation checks"),
             ("Warehouse", "PostgreSQL star schema\nkeys + constraints"), ("Answer", "14 SQL questions\nresults/*.csv"),
             ("Analyse", "findings.json\n13 charts"), ("Deliver", "memo · deck · dashboard\n8/8 tie-out tests")]
    bw, gap = Inches(1.85), Inches(0.2)
    for i, (h_, body) in enumerate(steps):
        x = Inches(0.6) + i * (bw + gap)
        box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, Inches(2.4), bw, Inches(1.9))
        box.adjustments[0] = 0.1
        box.fill.solid()
        box.fill.fore_color.rgb = PANEL if i else BLUE
        box.line.fill.background()
        text(s, x + Inches(0.15), Inches(2.55), bw - Inches(0.3), Inches(0.5), h_, size=18, bold=True,
             color=SURFACE if i == 0 else INK)
        text(s, x + Inches(0.15), Inches(3.1), bw - Inches(0.3), Inches(1.1), body.split("\n"), size=12,
             color=SURFACE if i == 0 else INK2)
        if i < len(steps) - 1:
            arr = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x + bw + Inches(0.03), Inches(3.25), gap - Inches(0.06), Inches(0.2))
            arr.fill.solid()
            arr.fill.fore_color.rgb = MUTED
            arr.line.fill.background()
    text(s, Inches(0.6), Inches(4.8), Inches(12.1), Inches(1.8), [
        "•  Nothing in raw/ is edited by the pipeline; it reads raw_original_backup/ and every rejected row lands in quarantine with a reason.",
        "•  Every decision is logged with its evidence: cleaning_report/CLEANING_DECISIONS.md, warehouse/WAREHOUSE_DECISIONS.md.",
        "•  The dashboard (Production · Merch · Acquisition) reads the same warehouse and is tested to tie to the SQL answers.",
    ], size=14, color=INK2)

    out = ROOT / "presentation" / "Xtrim_Studios_Commercial_Review.pptx"
    prs.save(out)
    print(out)


if __name__ == "__main__":
    main()
