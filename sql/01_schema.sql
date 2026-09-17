-- Xtrim Studios warehouse (PostgreSQL 17)
-- Layers: stg (raw text, as exported) -> core (conformed star) -> quarantine (every rejected row).
-- Every money column in core is Nigerian naira (NGN). The only currency codes stored are the
-- FX conversion table itself and the label saying which currency a booking was invoiced in.

DROP SCHEMA IF EXISTS stg CASCADE;
DROP SCHEMA IF EXISTS core CASCADE;
DROP SCHEMA IF EXISTS quarantine CASCADE;
CREATE SCHEMA stg;
CREATE SCHEMA core;
CREATE SCHEMA quarantine;
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- needed for EXCLUDE on (text =, daterange &&)

-- ============================================================ STAGING (TEXT, untouched)
CREATE TABLE stg.merch_products (
    sku TEXT, product_name TEXT, category TEXT, collection TEXT, colour TEXT, size_run TEXT,
    unit_cost_ngn TEXT, list_price_ngn TEXT, valid_from TEXT, valid_to TEXT, active TEXT,
    _src_row INT
);

-- ========================================================== DIMENSIONS
CREATE TABLE core.dim_date (
    date_key DATE PRIMARY KEY, year INT, quarter INT, year_quarter TEXT, month INT, month_name TEXT,
    iso_year INT, iso_week INT, week_start DATE, day_of_week INT, is_weekend BOOLEAN,
    is_peak_season BOOLEAN
);

CREATE TABLE core.dim_client (
    client_key BIGSERIAL PRIMARY KEY,
    client_id INT UNIQUE NOT NULL,           -- surviving CRM id after dedupe (XT-00042 -> 42)
    client_code TEXT UNIQUE NOT NULL,        -- XT-00042
    merged_from INT[],                       -- duplicate ids folded into this client
    client_name TEXT NOT NULL, client_type TEXT, email TEXT, phone TEXT,
    city TEXT, country TEXT, billing_currency CHAR(3) NOT NULL CHECK (billing_currency = 'NGN'),
    signup_date DATE, acquisition_channel TEXT,
    match_confidence NUMERIC(4,3), dq_flags TEXT
);

CREATE TABLE core.dim_service (
    service_key SMALLSERIAL PRIMARY KEY, service_name TEXT UNIQUE NOT NULL, category TEXT NOT NULL
);

CREATE TABLE core.dim_crew (
    crew_key BIGSERIAL PRIMARY KEY, crew_id INT UNIQUE NOT NULL, crew_code TEXT UNIQUE NOT NULL,
    full_name TEXT, role TEXT NOT NULL, standard_day_rate_ngn NUMERIC(14,2) NOT NULL,
    employment_type TEXT, is_active BOOLEAN NOT NULL
);

-- SCD-2, resolved to non-overlapping windows (the raw file overlaps; see Q6)
CREATE TABLE core.dim_product (
    product_key BIGSERIAL PRIMARY KEY, sku TEXT NOT NULL, product_name TEXT, category TEXT,
    collection TEXT, colour TEXT, unit_cost_ngn NUMERIC(12,2), list_price_ngn NUMERIC(12,2),
    valid_from DATE NOT NULL, valid_to DATE NOT NULL, is_current BOOLEAN NOT NULL,
    CONSTRAINT product_window_valid CHECK (valid_to >= valid_from),
    EXCLUDE USING gist (sku WITH =, daterange(valid_from, valid_to, '[]') WITH &&)
);

-- One row per marketing channel. Session utm_source groups and ad-spend channel names both
-- resolve here (the mapping table the brief asks for).
CREATE TABLE core.dim_channel (
    channel_key SMALLSERIAL PRIMARY KEY, channel_name TEXT UNIQUE NOT NULL,
    spend_channel_name TEXT,                 -- name in marketing_spend.csv, NULL if no spend
    session_groups TEXT[] NOT NULL,          -- utm_source groups that land here
    utm_source_variants TEXT[] NOT NULL,     -- raw utm_source spellings seen
    is_paid BOOLEAN NOT NULL
);

CREATE TABLE core.fx_daily (                 -- gap-filled: most recent earlier published rate
    rate_date DATE, from_currency CHAR(3), to_currency CHAR(3) CHECK (to_currency = 'NGN'),
    rate NUMERIC(14,6) NOT NULL, is_filled BOOLEAN NOT NULL, source_rate_date DATE NOT NULL,
    is_corrected BOOLEAN NOT NULL, original_rate NUMERIC(14,6),
    PRIMARY KEY (rate_date, from_currency, to_currency)
);

-- ================================================================== FACTS
CREATE TABLE core.fct_booking (              -- grain: one booking
    booking_key BIGSERIAL PRIMARY KEY,
    booking_id INT UNIQUE NOT NULL,          -- BK-01001 -> 1001
    booking_code TEXT UNIQUE NOT NULL,
    client_key BIGINT REFERENCES core.dim_client,
    service_key SMALLINT NOT NULL REFERENCES core.dim_service,
    shoot_date DATE NOT NULL REFERENCES core.dim_date,
    shoot_days SMALLINT CHECK (shoot_days BETWEEN 1 AND 30),
    location_city TEXT, status TEXT NOT NULL, lead_source TEXT, vat_applied BOOLEAN,
    invoice_currency CHAR(3) NOT NULL,       -- currency the client was invoiced in (label only)
    fx_rate NUMERIC(14,6) NOT NULL,          -- NGN per unit of invoice_currency on shoot date (1 for NGN)
    fx_rate_filled BOOLEAN NOT NULL,
    gross_amount_ngn NUMERIC(16,2) NOT NULL CHECK (gross_amount_ngn >= 0),
    discount_pct NUMERIC(5,4) NOT NULL CHECK (discount_pct BETWEEN 0 AND 1),
    net_amount_ngn NUMERIC(18,2) NOT NULL,
    is_cancelled BOOLEAN NOT NULL,
    source_file TEXT NOT NULL, dq_flags TEXT
);

CREATE TABLE core.fct_crew_day (             -- grain: one timesheet row = one crew member, one job, one day
    crew_day_key BIGSERIAL PRIMARY KEY,
    timesheet_id INT UNIQUE NOT NULL,
    booking_key BIGINT NOT NULL REFERENCES core.fct_booking,
    crew_key BIGINT NOT NULL REFERENCES core.dim_crew,
    work_date DATE NOT NULL REFERENCES core.dim_date,
    hours_worked NUMERIC(5,2) CHECK (hours_worked BETWEEN 0 AND 20),
    role_on_job TEXT, day_rate_charged_ngn NUMERIC(14,2),        -- NULL where never recorded
    labour_cost_ngn NUMERIC(14,2) NOT NULL,                      -- charged rate, or standard rate estimate
    rate_is_estimated BOOLEAN NOT NULL,
    is_overtime BOOLEAN, hours_flag TEXT, dq_flags TEXT
);

CREATE TABLE core.fct_merch_line (           -- grain: one order line
    order_line_key BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL, line_no SMALLINT NOT NULL,
    order_ts TIMESTAMPTZ NOT NULL,           -- UTC
    order_date_lagos DATE NOT NULL REFERENCES core.dim_date,
    client_key BIGINT REFERENCES core.dim_client,               -- NULL = guest checkout
    product_key BIGINT NOT NULL REFERENCES core.dim_product,
    quantity INT NOT NULL, unit_price_ngn NUMERIC(12,2) NOT NULL,
    list_value_ngn NUMERIC(14,2) NOT NULL,   -- quantity x list price in force that day
    gross_ngn NUMERIC(14,2) NOT NULL,        -- quantity x price paid
    discount_ngn NUMERIC(14,2) NOT NULL,     -- list_value - gross (negative = paid above list)
    cogs_ngn NUMERIC(14,2) NOT NULL,
    discount_code TEXT, sales_channel TEXT, payment_method TEXT, order_status TEXT NOT NULL,
    is_revenue BOOLEAN NOT NULL,             -- FALSE for Cancelled lines
    refunded_ngn NUMERIC(14,2) NOT NULL DEFAULT 0,             -- refunds allocated to this line
    net_ngn NUMERIC(14,2) NOT NULL,          -- gross - refunded (0 when not revenue)
    dq_flags TEXT,
    UNIQUE (order_id, line_no)
);

CREATE TABLE core.fct_refund (               -- grain: one refund
    refund_key TEXT PRIMARY KEY, refund_id TEXT NOT NULL, order_id BIGINT NOT NULL,
    refund_date DATE, refund_amount_ngn NUMERIC(14,2) NOT NULL CHECK (refund_amount_ngn >= 0),
    counted_ngn NUMERIC(14,2) NOT NULL,      -- part deducted from recognised revenue
    reason TEXT, processed_by TEXT, order_status TEXT, dq_flags TEXT
);

CREATE TABLE core.fct_session (              -- grain: one session
    session_id TEXT PRIMARY KEY,
    session_start_utc TIMESTAMPTZ NOT NULL,
    session_date_lagos DATE NOT NULL REFERENCES core.dim_date,
    visitor_id TEXT, channel_key SMALLINT NOT NULL REFERENCES core.dim_channel,
    utm_group TEXT NOT NULL, utm_source TEXT, medium TEXT,
    campaign TEXT, device TEXT, country TEXT, landing_page TEXT,
    page_views INT, duration_seconds INT, is_new_visitor BOOLEAN,
    is_bot BOOLEAN NOT NULL, is_spam BOOLEAN NOT NULL,
    converted BOOLEAN NOT NULL, transaction_id TEXT, order_id BIGINT, revenue_ngn NUMERIC(14,2) NOT NULL,
    source_file TEXT NOT NULL
);

CREATE TABLE core.fct_ad_spend (             -- grain: day x channel x campaign
    spend_date DATE NOT NULL REFERENCES core.dim_date,
    channel_key SMALLINT NOT NULL REFERENCES core.dim_channel,
    campaign TEXT NOT NULL, session_campaign TEXT,
    impressions BIGINT, clicks BIGINT, spend_ngn NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (spend_date, channel_key, campaign)
);

-- ============================================================== QUARANTINE
CREATE TABLE quarantine.rejected_rows (
    id BIGSERIAL PRIMARY KEY, src_table TEXT NOT NULL, src_file TEXT, src_row INT,
    reason TEXT NOT NULL, detail TEXT, payload JSONB NOT NULL,
    value_ngn NUMERIC(18,2),                 -- money carried by the row, in NGN (NULL if none)
    revenue_affected BOOLEAN NOT NULL,       -- TRUE when the row's value is missing from revenue totals
    rejected_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON core.fct_booking (shoot_date);
CREATE INDEX ON core.fct_crew_day (booking_key);
CREATE INDEX ON core.fct_crew_day (work_date);
CREATE INDEX ON core.fct_merch_line (order_id);
CREATE INDEX ON core.fct_merch_line (order_date_lagos);
CREATE INDEX ON core.fct_refund (order_id);
CREATE INDEX ON core.fct_session (session_date_lagos);
CREATE INDEX ON core.fct_session (order_id);
CREATE INDEX ON quarantine.rejected_rows (src_table, reason);
