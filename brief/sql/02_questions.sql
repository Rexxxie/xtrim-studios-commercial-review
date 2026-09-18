-- ============================================================================
-- Xtrim Studios — SQL exercises. Answer each against core.*, never against raw.
-- Write the query below its question. Keep the comment.
-- ============================================================================

-- Q1. Quarterly revenue in NGN, split production vs merch, 2023Q1 → 2025Q2.
--     Production = fct_booking (exclude Cancelled). Merch = fct_merch_line net of refunds.
--     One row per quarter, three columns. Must tie to your dashboard exactly.


-- Q2. Revenue and job count by service line by year, with YoY growth %.
--     Show the share of total each line represents. Which one grew and shrank?


-- Q3. Job-level profitability.
--     Labour cost per booking from fct_crew_day, margin = net_amount_ngn - labour.
--     Return the 20 worst-margin jobs. Flag which are genuine losses vs data artefacts
--     (rate outliers, orphaned timesheets, impossible hours) in a separate column.


-- Q4. Crew utilisation by ISO week.
--     crew-days booked / (active crew x 7). Find every week above 85%.
--     Bonus: which single role is the binding constraint?


-- Q5. FX exposure.
--     For USD- and GBP-billed jobs: value each at the FX rate on its shoot date, then at
--     the 2023-01-01 rate. The difference is your devaluation gain/loss. Split by year.
--     Use core.fx_daily and report what fraction of your rates were gap-filled.


-- Q6. Product price-history integrity.
--     Prove dim_product has no overlapping windows per SKU (the EXCLUDE constraint should
--     make this trivial — show the query you used on the *raw* data to find the
--     overlaps before you resolved them, and how many there were).


-- Q7. Merch unit economics by collection.
--     Units sold, gross, discount value, refunds, net, COGS, contribution margin.
--     Which drops lost money? Exclude the 9999-quantity outliers and say how many there were.


-- Q8. Refund rate by SKU and by reason.
--     Which SKU has a refund rate more than 2x the store average, and what's the
--     dominant reason for it?


-- Q9. Channel efficiency by quarter.
--     Join fct_ad_spend to fct_session via dim_channel. Sessions, conversions, revenue,
--     spend, CPC, CAC, ROAS. Human sessions only.


-- Q10. Attribution gap.
--      Of all converted sessions, what % have a transaction_id that joins to a real
--      order? Express the unattributed revenue in NGN and as a share of merch revenue.
--      This is the number that invalidates a naive ROAS. Quantify it.


-- Q11. Repeat purchase behaviour.
--      Cohort merch buyers by first-purchase month. What share buys again within 90 days?
--      Does acquisition channel predict repeat rate?


-- Q12. Cross-sell.
--      How many production clients also bought merch? Do they spend more per order than
--      merch-only customers? Test whether the difference is meaningful, don't just eyeball it.


-- Q13. Data quality summary — the query that powers the dashboard tile.
--      From quarantine.rejected_rows: rows rejected by source table and reason, plus the
--      NGN value at risk. One row per (src_table, reason).


-- Q14. The Director's question, as a single query.
--      Monthly: production revenue, merch net revenue, labour cost, ad spend,
--      and the gap between revenue and known cost. Show me where the money went.
