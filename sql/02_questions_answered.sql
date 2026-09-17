-- ============================================================================
-- Xtrim Studios — SQL exercises, answered against core.* (PostgreSQL 17).
-- Each query is preceded by its question. `-- @q NN` markers let run_queries.py
-- execute them one by one and save the results to results/qNN.csv.
-- All money is NGN.
-- ============================================================================

-- @q 01
-- Q1. Quarterly revenue in NGN, split production vs merch, 2023Q1 → 2025Q2.
--     Production = fct_booking (exclude Cancelled). Merch = fct_merch_line net of refunds.
--     One row per quarter, three columns. Must tie to your dashboard exactly.
WITH quarters AS (
    SELECT DISTINCT year_quarter FROM core.dim_date
    WHERE date_key BETWEEN DATE '2023-01-01' AND DATE '2025-06-30'
), production AS (
    SELECT d.year_quarter, SUM(b.net_amount_ngn) AS ngn
    FROM core.fct_booking b JOIN core.dim_date d ON d.date_key = b.shoot_date
    WHERE NOT b.is_cancelled GROUP BY 1
), merch AS (
    SELECT d.year_quarter, SUM(m.net_ngn) AS ngn
    FROM core.fct_merch_line m JOIN core.dim_date d ON d.date_key = m.order_date_lagos
    GROUP BY 1
)
SELECT q.year_quarter AS quarter,
       ROUND(COALESCE(p.ngn, 0), 0) AS production_revenue_ngn,
       ROUND(COALESCE(m.ngn, 0), 0) AS merch_net_revenue_ngn
FROM quarters q LEFT JOIN production p USING (year_quarter) LEFT JOIN merch m USING (year_quarter)
ORDER BY 1;

-- @q 02
-- Q2. Revenue and job count by service line by year, with YoY growth %.
--     Show the share of total each line represents. Which one grew and shrank?
--     (2025 covers January–June only, so 2025 YoY compares H1 2025 with H1 2024.)
WITH base AS (
    SELECT s.service_name, d.year, d.month, b.net_amount_ngn
    FROM core.fct_booking b
    JOIN core.dim_service s USING (service_key)
    JOIN core.dim_date d ON d.date_key = b.shoot_date
    WHERE NOT b.is_cancelled
), yearly AS (
    SELECT service_name, year, COUNT(*) AS jobs, SUM(net_amount_ngn) AS revenue_ngn,
           SUM(net_amount_ngn) FILTER (WHERE month <= 6) AS h1_revenue_ngn
    FROM base GROUP BY 1, 2
)
SELECT service_name, year, jobs,
       ROUND(revenue_ngn, 0) AS revenue_ngn,
       ROUND(100 * revenue_ngn / SUM(revenue_ngn) OVER (PARTITION BY year), 1) AS share_of_year_pct,
       CASE WHEN year < 2025
            THEN ROUND(100 * (revenue_ngn / NULLIF(LAG(revenue_ngn) OVER w, 0) - 1), 1) END AS yoy_growth_pct,
       CASE WHEN year = 2025
            THEN ROUND(100 * (revenue_ngn / NULLIF(LAG(h1_revenue_ngn) OVER w, 0) - 1), 1) END AS h1_vs_h1_growth_pct
FROM yearly
WINDOW w AS (PARTITION BY service_name ORDER BY year)
ORDER BY year, revenue_ngn DESC;

-- @q 03
-- Q3. Job-level profitability.
--     Labour cost per booking from fct_crew_day, margin = net_amount_ngn - labour.
--     Return the 20 worst-margin jobs. Flag which are genuine losses vs data artefacts
--     (rate outliers, orphaned timesheets, impossible hours) in a separate column.
--     Orphaned timesheets cannot attach to any job (they sit in quarantine) and charged rates
--     have no outliers (every rate is exactly 0.5x, 1x or 1.5x the crew member's standard rate),
--     so the artefacts that can inflate a job's labour are:
--       * suspect crew-days: the same crew member logged on another job on the same date;
--       * labour priced at an estimated rate (charged rate never recorded);
--       * impossible 26-hour entries.
--     Verdict: a loss is genuine if the job still loses money after removing suspect crew-days
--     and pricing estimated rows at the cheapest possible multiplier (0.5x); otherwise the loss
--     depends on data we cannot trust.
WITH clash AS (
    SELECT crew_key, work_date FROM core.fct_crew_day GROUP BY 1, 2 HAVING COUNT(DISTINCT booking_key) > 1
), rows AS (
    SELECT f.booking_key, f.labour_cost_ngn, f.rate_is_estimated, f.hours_flag,
           (cl.crew_key IS NOT NULL) AS suspect_day
    FROM core.fct_crew_day f LEFT JOIN clash cl USING (crew_key, work_date)
), labour AS (
    SELECT booking_key,
           SUM(labour_cost_ngn) AS labour_ngn,
           COUNT(*) AS crew_rows,
           COUNT(*) FILTER (WHERE suspect_day) AS suspect_rows,
           SUM(labour_cost_ngn) FILTER (WHERE suspect_day) AS suspect_labour_ngn,
           SUM(labour_cost_ngn) FILTER (WHERE rate_is_estimated) AS estimated_labour_ngn,
           COUNT(*) FILTER (WHERE hours_flag = 'impossible_26h_blanked') AS impossible_hours_rows,
           SUM(CASE WHEN suspect_day THEN 0 WHEN rate_is_estimated THEN 0.5 * labour_cost_ngn
                    ELSE labour_cost_ngn END) AS minimum_trusted_labour_ngn
    FROM rows GROUP BY 1
), jobs AS (
    SELECT b.booking_code, s.service_name, b.status, b.shoot_date, b.is_cancelled,
           b.net_amount_ngn, l.*,
           b.net_amount_ngn - l.labour_ngn AS margin_ngn,
           b.net_amount_ngn - l.minimum_trusted_labour_ngn AS margin_on_trusted_labour_ngn
    FROM core.fct_booking b
    JOIN labour l USING (booking_key)
    JOIN core.dim_service s USING (service_key)
)
SELECT booking_code, service_name, status, shoot_date, crew_rows,
       ROUND(net_amount_ngn, 0) AS net_revenue_ngn, ROUND(labour_ngn, 0) AS labour_ngn,
       ROUND(margin_ngn, 0) AS margin_ngn,
       ROUND(margin_on_trusted_labour_ngn, 0) AS margin_on_trusted_labour_ngn,
       CASE WHEN margin_ngn >= 0 THEN 'profitable'
            WHEN margin_on_trusted_labour_ngn < 0 THEN 'genuine_loss'
            ELSE 'data_artefact' END AS verdict,
       CONCAT_WS('; ',
           CASE WHEN suspect_rows > 0 THEN suspect_rows || ' crew-days also logged on another job (NGN '
                || TO_CHAR(suspect_labour_ngn, 'FM999,999,999') || ')' END,
           CASE WHEN estimated_labour_ngn > 0 THEN 'NGN ' || TO_CHAR(estimated_labour_ngn, 'FM999,999,999')
                || ' at estimated rates' END,
           CASE WHEN impossible_hours_rows > 0 THEN impossible_hours_rows || ' impossible 26h entries' END,
           CASE WHEN is_cancelled THEN 'job was cancelled: crew cost with no revenue' END,
           CASE WHEN service_name = 'Unknown' THEN 'service type never recorded' END
       ) AS evidence
FROM jobs
ORDER BY margin_ngn
LIMIT 20;

-- @q 04
-- Q4. Crew utilisation by ISO week.
--     crew-days booked / (active crew x 7). Find every week above 85%.
--     Bonus: which single role is the binding constraint?
--     Active crew in a week = crew whose first and last logged shift span that week
--     (is_active in dim_crew is a 2025 snapshot and would understate 2023 capacity).
--     A crew-day is one crew member working on one date, however many jobs.
WITH crew_days AS (
    SELECT DISTINCT f.crew_key, f.work_date, c.role
    FROM core.fct_crew_day f JOIN core.dim_crew c USING (crew_key)
), span AS (
    SELECT crew_key, MIN(work_date) AS first_day, MAX(work_date) AS last_day FROM crew_days GROUP BY 1
), weeks AS (
    SELECT DISTINCT d.iso_year, d.iso_week, d.week_start
    FROM core.dim_date d WHERE d.date_key BETWEEN DATE '2023-01-02' AND DATE '2025-06-29'
), weekly AS (
    SELECT w.iso_year, w.iso_week, w.week_start,
           (SELECT COUNT(*) FROM crew_days cd WHERE cd.work_date BETWEEN w.week_start AND w.week_start + 6) AS crew_days_booked,
           (SELECT COUNT(*) FROM span s WHERE s.first_day <= w.week_start + 6 AND s.last_day >= w.week_start) AS active_crew,
           (SELECT COUNT(*) FROM (SELECT crew_key, work_date FROM core.fct_crew_day
                                  WHERE work_date BETWEEN w.week_start AND w.week_start + 6
                                  GROUP BY 1, 2 HAVING COUNT(DISTINCT booking_key) > 1) x) AS double_booked_crew_days
    FROM weeks w
), role_week AS (
    SELECT c.role, d.week_start, COUNT(*) AS crew_days,
           (SELECT COUNT(*) FROM span s JOIN core.dim_crew c2 USING (crew_key)
            WHERE c2.role = c.role AND s.first_day <= d.week_start + 6 AND s.last_day >= d.week_start) AS active_in_role
    FROM crew_days c JOIN core.dim_date d ON d.date_key = c.work_date
    GROUP BY 1, 2
), binding AS (
    SELECT DISTINCT ON (week_start) week_start, role AS binding_role,
           ROUND(crew_days::numeric / (active_in_role * 7), 3) AS binding_role_utilisation
    FROM role_week ORDER BY week_start, crew_days::numeric / (active_in_role * 7) DESC
)
SELECT w.iso_year, w.iso_week, w.week_start, w.crew_days_booked, w.active_crew,
       ROUND(w.crew_days_booked::numeric / (w.active_crew * 7), 3) AS utilisation,
       w.crew_days_booked::numeric / (w.active_crew * 7) > 0.85 AS above_85pct,
       w.double_booked_crew_days, b.binding_role, b.binding_role_utilisation
FROM weekly w LEFT JOIN binding b USING (week_start)
ORDER BY utilisation DESC, week_start;

-- @q 05
-- Q5. FX exposure.
--     For USD- and GBP-billed jobs: value each at the FX rate on its shoot date, then at
--     the 2023-01-01 rate. The difference is your devaluation gain/loss. Split by year.
--     Use core.fx_daily and report what fraction of your rates were gap-filled.
--     (2023-01-01 was a Sunday with no published rate; fx_daily carries the first published
--     rate, 2023-01-02, onto it and flags it as filled.)
WITH base_rate AS (
    SELECT from_currency, rate AS rate_2023_01_01, is_filled AS base_filled
    FROM core.fx_daily WHERE rate_date = DATE '2023-01-01'
), jobs AS (
    SELECT EXTRACT(YEAR FROM b.shoot_date)::int AS year, b.invoice_currency,
           b.net_amount_ngn AS at_shoot_date_rate_ngn,
           b.net_amount_ngn / b.fx_rate * br.rate_2023_01_01 AS at_2023_01_01_rate_ngn,
           b.fx_rate_filled
    FROM core.fct_booking b JOIN base_rate br ON br.from_currency = b.invoice_currency
    WHERE NOT b.is_cancelled AND b.invoice_currency IN ('USD', 'GBP')
)
SELECT year, invoice_currency, COUNT(*) AS jobs,
       ROUND(SUM(at_shoot_date_rate_ngn), 0) AS value_at_shoot_date_rate_ngn,
       ROUND(SUM(at_2023_01_01_rate_ngn), 0) AS value_at_2023_01_01_rate_ngn,
       ROUND(SUM(at_shoot_date_rate_ngn - at_2023_01_01_rate_ngn), 0) AS devaluation_gain_ngn,
       ROUND(100.0 * AVG(fx_rate_filled::int), 1) AS pct_rates_gap_filled
FROM jobs
GROUP BY ROLLUP (year, invoice_currency)
ORDER BY year NULLS LAST, invoice_currency NULLS LAST;

-- @q 06
-- Q6. Product price-history integrity.
--     Prove dim_product has no overlapping windows per SKU (the EXCLUDE constraint should
--     make this trivial — show the query you used on the *raw* data to find the
--     overlaps before you resolved them, and how many there were).
WITH raw AS (                          -- stg.merch_products is the raw file, all text
    SELECT _src_row,
           'XT-' || SUBSTRING(UPPER(REGEXP_REPLACE(sku, '[^A-Za-z0-9]', '', 'g')) FROM 3 FOR 3) || '-' ||
               LPAD(REGEXP_REPLACE(SUBSTRING(UPPER(REGEXP_REPLACE(sku, '[^A-Za-z0-9]', '', 'g')) FROM 6), '^0+', ''), 3, '0') AS sku,
           CASE WHEN valid_from ~ '^\d{4}-\d{2}-\d{2}$' THEN valid_from::date
                WHEN valid_from ~ '^\d{1,2}/\d{1,2}/\d{4}$' THEN TO_DATE(valid_from, 'DD/MM/YYYY') END AS vf,
           CASE WHEN valid_to ~ '^\d{4}-\d{2}-\d{2}$' THEN valid_to::date
                WHEN valid_to ~ '^\d{1,2}/\d{1,2}/\d{4}$' THEN TO_DATE(valid_to, 'DD/MM/YYYY') END AS vt
    FROM stg.merch_products
), windows AS (                        -- open end = current; an inverted window is read as its swap
    SELECT _src_row, sku, LEAST(vf, COALESCE(vt, DATE '9999-12-31')) AS lo,
           GREATEST(vf, COALESCE(vt, DATE '9999-12-31')) AS hi, vt < vf AS inverted
    FROM raw
), overlap_pairs AS (
    SELECT a.sku, a._src_row AS row_a, b._src_row AS row_b
    FROM windows a JOIN windows b ON a.sku = b.sku AND a._src_row < b._src_row
                                   AND daterange(a.lo, a.hi, '[]') && daterange(b.lo, b.hi, '[]')
)
SELECT 'raw: overlapping window pairs' AS check_name, COUNT(*)::text AS result FROM overlap_pairs
UNION ALL SELECT 'raw: SKUs with at least one overlap', COUNT(DISTINCT sku)::text FROM overlap_pairs
UNION ALL SELECT 'raw: windows with valid_to < valid_from', COUNT(*)::text FROM windows WHERE inverted
UNION ALL SELECT 'raw: SKU spellings -> SKUs', (SELECT COUNT(DISTINCT sku) FROM stg.merch_products)::text || ' -> ' ||
                                               (SELECT COUNT(DISTINCT sku) FROM raw)::text
UNION ALL SELECT 'core: overlapping window pairs',
       (SELECT COUNT(*) FROM core.dim_product a JOIN core.dim_product b
          ON a.sku = b.sku AND a.product_key < b.product_key
         AND daterange(a.valid_from, a.valid_to, '[]') && daterange(b.valid_from, b.valid_to, '[]'))::text
UNION ALL SELECT 'core: gaps between consecutive versions',
       (SELECT COUNT(*) FROM (SELECT valid_from, LAG(valid_to) OVER (PARTITION BY sku ORDER BY valid_from) AS prev_to
                              FROM core.dim_product) x WHERE prev_to IS NOT NULL AND valid_from <> prev_to + 1)::text
UNION ALL SELECT 'core: SKUs without exactly one current version',
       (SELECT COUNT(*) FROM (SELECT sku FROM core.dim_product GROUP BY sku
                              HAVING COUNT(*) FILTER (WHERE is_current) <> 1) x)::text
UNION ALL SELECT 'core: EXCLUDE constraint present',
       (SELECT COUNT(*) FROM pg_constraint WHERE conrelid = 'core.dim_product'::regclass AND contype = 'x')::text;

-- @q 07
-- Q7. Merch unit economics by collection.
--     Units sold, gross, discount value, refunds, net, COGS, contribution margin.
--     Which drops lost money? Exclude the 9999-quantity outliers and say how many there were.
--     (The 9999 lines never reach core — they sit in quarantine; the count is shown per row.)
WITH lines AS (
    SELECT p.collection, m.*
    FROM core.fct_merch_line m JOIN core.dim_product p USING (product_key)
    WHERE m.is_revenue
), outliers AS (
    SELECT COUNT(*) AS n FROM quarantine.rejected_rows WHERE reason = 'placeholder_quantity_9999'
)
SELECT collection,
       SUM(quantity) AS units_sold,
       ROUND(SUM(list_value_ngn), 0) AS list_value_ngn,
       ROUND(SUM(discount_ngn), 0) AS discount_value_ngn,
       ROUND(SUM(gross_ngn), 0) AS gross_ngn,
       ROUND(SUM(refunded_ngn), 0) AS refunds_ngn,
       ROUND(SUM(net_ngn), 0) AS net_ngn,
       ROUND(SUM(cogs_ngn), 0) AS cogs_ngn,
       ROUND(SUM(net_ngn) - SUM(cogs_ngn), 0) AS contribution_margin_ngn,
       ROUND(100 * (SUM(net_ngn) - SUM(cogs_ngn)) / NULLIF(SUM(net_ngn), 0), 1) AS contribution_margin_pct,
       SUM(net_ngn) - SUM(cogs_ngn) < 0 AS lost_money,
       (SELECT n FROM outliers) AS qty_9999_lines_excluded_storewide
FROM lines
GROUP BY collection
ORDER BY contribution_margin_ngn;

-- @q 08
-- Q8. Refund rate by SKU and by reason.
--     Which SKU has a refund rate more than 2x the store average, and what's the
--     dominant reason for it?
--     Refunds are recorded per order. Refund rate = refunded value / gross value of the lines
--     it is allocated to (Returned orders; Cancelled-order refunds reverse sales that were
--     never counted). A refund's reason is attributed to every SKU on its order in
--     proportion to line value.
WITH sku_rate AS (
    SELECT p.sku, MIN(p.product_name) AS product_name, SUM(m.gross_ngn) AS gross_ngn, SUM(m.refunded_ngn) AS refunded_ngn
    FROM core.fct_merch_line m JOIN core.dim_product p USING (product_key)
    WHERE m.is_revenue GROUP BY 1
), store AS (
    SELECT SUM(refunded_ngn) / SUM(gross_ngn) AS store_rate FROM sku_rate
), line_share AS (
    SELECT m.order_id, p.sku, m.gross_ngn / SUM(m.gross_ngn) OVER (PARTITION BY m.order_id) AS share
    FROM core.fct_merch_line m JOIN core.dim_product p USING (product_key)
    WHERE m.is_revenue AND m.gross_ngn > 0
), reason_sku AS (
    SELECT ls.sku, COALESCE(r.reason, 'Unknown') AS reason, SUM(r.counted_ngn * ls.share) AS ngn
    FROM core.fct_refund r JOIN line_share ls USING (order_id)
    WHERE r.counted_ngn > 0 GROUP BY 1, 2
), dominant AS (
    SELECT DISTINCT ON (sku) sku, reason AS dominant_reason,
           ROUND(100 * ngn / SUM(ngn) OVER (PARTITION BY sku), 1) AS dominant_reason_share_pct
    FROM reason_sku ORDER BY sku, ngn DESC
)
SELECT s.sku, s.product_name, ROUND(s.gross_ngn, 0) AS gross_ngn, ROUND(s.refunded_ngn, 0) AS refunded_ngn,
       ROUND(100 * s.refunded_ngn / s.gross_ngn, 2) AS refund_rate_pct,
       ROUND(100 * st.store_rate, 2) AS store_avg_refund_rate_pct,
       ROUND(s.refunded_ngn / s.gross_ngn / st.store_rate, 2) AS x_store_avg,
       s.refunded_ngn / s.gross_ngn > 2 * st.store_rate AS above_2x_store_avg,
       d.dominant_reason, d.dominant_reason_share_pct
FROM sku_rate s CROSS JOIN store st LEFT JOIN dominant d USING (sku)
ORDER BY refund_rate_pct DESC;

-- @q 08b
-- Q8 (by reason): store-wide refunds by reason.
SELECT COALESCE(reason, 'Unknown') AS reason, COUNT(*) AS refunds,
       ROUND(SUM(refund_amount_ngn), 0) AS refund_amount_ngn,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS share_of_refunds_pct,
       COUNT(*) FILTER (WHERE order_status = 'Returned') AS on_returned_orders,
       COUNT(*) FILTER (WHERE order_status = 'Cancelled') AS on_cancelled_orders
FROM core.fct_refund GROUP BY 1 ORDER BY refunds DESC;

-- @q 09
-- Q9. Channel efficiency by quarter.
--     Join fct_ad_spend to fct_session via dim_channel. Sessions, conversions, revenue,
--     spend, CPC, CAC, ROAS. Human sessions only.
--     Human = not is_bot (every spam session is also a bot). Revenue = revenue the analytics
--     tool recorded on converted sessions. CAC = spend / conversions.
WITH sess AS (
    SELECT s.channel_key, d.year_quarter, COUNT(*) AS sessions,
           COUNT(*) FILTER (WHERE s.converted) AS conversions,
           SUM(s.revenue_ngn) AS revenue_ngn
    FROM core.fct_session s JOIN core.dim_date d ON d.date_key = s.session_date_lagos
    WHERE NOT s.is_bot GROUP BY 1, 2
), spend AS (
    SELECT a.channel_key, d.year_quarter, SUM(a.spend_ngn) AS spend_ngn, SUM(a.clicks) AS clicks
    FROM core.fct_ad_spend a JOIN core.dim_date d ON d.date_key = a.spend_date GROUP BY 1, 2
)
SELECT c.channel_name, COALESCE(se.year_quarter, sp.year_quarter) AS quarter,
       COALESCE(se.sessions, 0) AS sessions, COALESCE(se.conversions, 0) AS conversions,
       ROUND(100.0 * se.conversions / NULLIF(se.sessions, 0), 2) AS conversion_rate_pct,
       ROUND(COALESCE(se.revenue_ngn, 0), 0) AS revenue_ngn,
       ROUND(COALESCE(sp.spend_ngn, 0), 0) AS spend_ngn, sp.clicks,
       ROUND(sp.spend_ngn / NULLIF(sp.clicks, 0), 2) AS cpc_ngn,
       ROUND(sp.spend_ngn / NULLIF(se.conversions, 0), 0) AS cac_ngn,
       ROUND(se.revenue_ngn / NULLIF(sp.spend_ngn, 0), 2) AS roas
FROM sess se FULL JOIN spend sp USING (channel_key, year_quarter)
JOIN core.dim_channel c ON c.channel_key = COALESCE(se.channel_key, sp.channel_key)
ORDER BY c.channel_key, quarter;

-- @q 10
-- Q10. Attribution gap.
--      Of all converted sessions, what % have a transaction_id that joins to a real
--      order? Express the unattributed revenue in NGN and as a share of merch revenue.
--      This is the number that invalidates a naive ROAS. Quantify it.
WITH conv AS (
    SELECT s.*, NOT s.is_bot AS human FROM core.fct_session s WHERE s.converted
), merch AS (
    SELECT SUM(net_ngn) AS merch_net_ngn FROM core.fct_merch_line
)
SELECT scope,
       COUNT(*) AS converted_sessions,
       COUNT(*) FILTER (WHERE transaction_id IS NOT NULL) AS with_transaction_id,
       COUNT(*) FILTER (WHERE order_id IS NOT NULL) AS joined_to_real_order,
       ROUND(100.0 * COUNT(*) FILTER (WHERE order_id IS NOT NULL) / COUNT(*), 1) AS pct_joined,
       ROUND(SUM(revenue_ngn), 0) AS session_revenue_ngn,
       ROUND(SUM(revenue_ngn) FILTER (WHERE order_id IS NULL), 0) AS unattributed_revenue_ngn,
       ROUND(100 * SUM(revenue_ngn) FILTER (WHERE order_id IS NULL) / SUM(revenue_ngn), 1) AS unattributed_share_of_session_revenue_pct,
       ROUND(100 * SUM(revenue_ngn) FILTER (WHERE order_id IS NULL) / MAX(m.merch_net_ngn), 1) AS unattributed_as_pct_of_merch_net_revenue
FROM (SELECT 'all converted sessions' AS scope, * FROM conv
      UNION ALL SELECT 'human converted sessions', * FROM conv WHERE human) x
CROSS JOIN merch m
GROUP BY scope ORDER BY scope;

-- @q 11
-- Q11. Repeat purchase behaviour.
--      Cohort merch buyers by first-purchase month. What share buys again within 90 days?
--      Does acquisition channel predict repeat rate?
--      Buyers = CRM clients (guest checkouts carry a one-off guest e-mail and cannot be tracked).
--      A repeat = a different order placed 1–90 days after the first. Cohorts from 2025-04 on
--      have not had a full 90 days of observation before 2025-06-30 and are marked.
WITH orders AS (
    SELECT client_key, order_id, MIN(order_ts) AS ts
    FROM core.fct_merch_line WHERE client_key IS NOT NULL AND is_revenue GROUP BY 1, 2
), firsts AS (
    SELECT DISTINCT ON (client_key) client_key, order_id AS first_order, ts AS first_ts
    FROM orders ORDER BY client_key, ts, order_id
), buyer AS (
    SELECT f.client_key, DATE_TRUNC('month', f.first_ts AT TIME ZONE 'Africa/Lagos')::date AS cohort_month,
           EXISTS (SELECT 1 FROM orders o WHERE o.client_key = f.client_key AND o.order_id <> f.first_order
                   AND o.ts > f.first_ts AND o.ts <= f.first_ts + INTERVAL '90 days') AS repeat_90d,
           f.first_ts + INTERVAL '90 days' <= TIMESTAMPTZ '2025-07-01 00:00:00+01' AS full_window
    FROM firsts f
)
SELECT 'cohort' AS cut, TO_CHAR(cohort_month, 'YYYY-MM') AS grp, COUNT(*) AS buyers,
       COUNT(*) FILTER (WHERE repeat_90d) AS repeat_buyers,
       ROUND(100.0 * COUNT(*) FILTER (WHERE repeat_90d) / COUNT(*), 1) AS repeat_90d_pct,
       BOOL_AND(full_window) AS full_90d_observed
FROM buyer GROUP BY cohort_month
UNION ALL
SELECT 'acquisition_channel', COALESCE(c.acquisition_channel, 'Unknown'), COUNT(*),
       COUNT(*) FILTER (WHERE repeat_90d),
       ROUND(100.0 * COUNT(*) FILTER (WHERE repeat_90d) / COUNT(*), 1), BOOL_AND(full_window)
FROM buyer b JOIN core.dim_client c USING (client_key)
WHERE b.full_window GROUP BY 2
UNION ALL
SELECT 'all_full_window', 'all', COUNT(*), COUNT(*) FILTER (WHERE repeat_90d),
       ROUND(100.0 * COUNT(*) FILTER (WHERE repeat_90d) / COUNT(*), 1), TRUE
FROM buyer WHERE full_window
ORDER BY 1, 2;

-- @q 12
-- Q12. Cross-sell.
--      How many production clients also bought merch? Do they spend more per order than
--      merch-only customers? Test whether the difference is meaningful, don't just eyeball it.
--      Welch's t-test on order value (net of refunds, non-cancelled orders, CRM clients).
--      Degrees of freedom by Welch–Satterthwaite; the p-value is computed from t and df in
--      analysis/analysis.py (Postgres has no t distribution function).
WITH prod_clients AS (
    SELECT DISTINCT client_key FROM core.fct_booking WHERE NOT is_cancelled AND client_key IS NOT NULL
), orders AS (
    SELECT client_key, order_id, SUM(net_ngn) AS order_net_ngn
    FROM core.fct_merch_line WHERE client_key IS NOT NULL AND is_revenue GROUP BY 1, 2
), labelled AS (
    SELECT o.*, CASE WHEN p.client_key IS NOT NULL THEN 'production_and_merch' ELSE 'merch_only' END AS segment
    FROM orders o LEFT JOIN prod_clients p USING (client_key)
), stats AS (
    SELECT segment, COUNT(DISTINCT client_key) AS clients, COUNT(*) AS orders,
           AVG(order_net_ngn) AS mean_order, VAR_SAMP(order_net_ngn) AS var_order,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY order_net_ngn) AS median_order
    FROM labelled GROUP BY 1
), t AS (
    SELECT a.mean_order - b.mean_order AS diff,
           (a.mean_order - b.mean_order) / SQRT(a.var_order / a.orders + b.var_order / b.orders) AS t_stat,
           POWER(a.var_order / a.orders + b.var_order / b.orders, 2) /
             (POWER(a.var_order / a.orders, 2) / (a.orders - 1) + POWER(b.var_order / b.orders, 2) / (b.orders - 1)) AS df
    FROM stats a, stats b WHERE a.segment = 'production_and_merch' AND b.segment = 'merch_only'
)
SELECT s.segment, s.clients, s.orders, ROUND(s.mean_order, 0) AS mean_order_net_ngn,
       ROUND(s.median_order::numeric, 0) AS median_order_net_ngn, ROUND(SQRT(s.var_order), 0) AS sd_order_net_ngn,
       (SELECT COUNT(*) FROM prod_clients) AS production_clients_total,
       ROUND(t.diff, 0) AS diff_in_means_ngn, ROUND(t.t_stat, 3) AS welch_t, ROUND(t.df, 1) AS welch_df
FROM stats s CROSS JOIN t ORDER BY s.segment DESC;

-- @q 13
-- Q13. Data quality summary — the query that powers the dashboard tile.
--      From quarantine.rejected_rows: rows rejected by source table and reason, plus the
--      NGN value at risk. One row per (src_table, reason).
SELECT src_table, reason, COUNT(*) AS rows_rejected,
       ROUND(COALESCE(SUM(value_ngn), 0), 0) AS value_carried_ngn,
       ROUND(COALESCE(SUM(value_ngn) FILTER (WHERE revenue_affected), 0), 0) AS revenue_value_at_risk_ngn,
       BOOL_OR(revenue_affected) AS affects_revenue
FROM quarantine.rejected_rows
GROUP BY ROLLUP (src_table, reason)
ORDER BY src_table NULLS LAST, rows_rejected DESC;

-- @q 14
-- Q14. The Director's question, as a single query.
--      Monthly: production revenue, merch net revenue, labour cost, ad spend,
--      and the gap between revenue and known cost. Show me where the money went.
--      Known cost = crew labour (by work date) + ad spend + merch cost of goods.
WITH months AS (
    SELECT DISTINCT DATE_TRUNC('month', date_key)::date AS month FROM core.dim_date
    WHERE date_key BETWEEN DATE '2023-01-01' AND DATE '2025-06-30'
), prod AS (
    SELECT DATE_TRUNC('month', shoot_date)::date AS month, SUM(net_amount_ngn) AS v
    FROM core.fct_booking WHERE NOT is_cancelled GROUP BY 1
), merch AS (
    SELECT DATE_TRUNC('month', order_date_lagos)::date AS month, SUM(net_ngn) AS v,
           SUM(cogs_ngn) FILTER (WHERE is_revenue) AS cogs
    FROM core.fct_merch_line GROUP BY 1
), labour AS (
    SELECT DATE_TRUNC('month', work_date)::date AS month, SUM(labour_cost_ngn) AS v
    FROM core.fct_crew_day GROUP BY 1
), ads AS (
    SELECT DATE_TRUNC('month', spend_date)::date AS month, SUM(spend_ngn) AS v FROM core.fct_ad_spend GROUP BY 1
)
SELECT TO_CHAR(m.month, 'YYYY-MM') AS month,
       ROUND(COALESCE(p.v, 0), 0) AS production_revenue_ngn,
       ROUND(COALESCE(me.v, 0), 0) AS merch_net_revenue_ngn,
       ROUND(COALESCE(l.v, 0), 0) AS labour_cost_ngn,
       ROUND(COALESCE(a.v, 0), 0) AS ad_spend_ngn,
       ROUND(COALESCE(me.cogs, 0), 0) AS merch_cogs_ngn,
       ROUND(COALESCE(p.v, 0) + COALESCE(me.v, 0) - COALESCE(l.v, 0) - COALESCE(a.v, 0) - COALESCE(me.cogs, 0), 0)
           AS revenue_minus_known_cost_ngn,
       ROUND(100 * (COALESCE(l.v, 0) + COALESCE(a.v, 0) + COALESCE(me.cogs, 0))
             / NULLIF(COALESCE(p.v, 0) + COALESCE(me.v, 0), 0), 1) AS known_cost_pct_of_revenue
FROM months m
LEFT JOIN prod p USING (month) LEFT JOIN merch me USING (month)
LEFT JOIN labour l USING (month) LEFT JOIN ads a USING (month)
ORDER BY m.month;
