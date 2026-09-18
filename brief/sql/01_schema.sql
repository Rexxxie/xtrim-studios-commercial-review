-- Xtrim Studios warehouse
-- Staging is deliberately all-TEXT: never let Postgres guess a type on data this dirty.
-- Load raw -> stg (COPY), clean in Python or SQL -> core, then build the star.

CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS quarantine;

-- ============================================================ STAGING (TEXT)

CREATE TABLE stg.clients (
    client_id TEXT, client_name TEXT, type TEXT, email TEXT, phone TEXT, city TEXT,
    country TEXT, billing_currency TEXT, signup_date TEXT, acquisition_channel TEXT,
    notes TEXT, _src_file TEXT DEFAULT 'clients_export.csv', _loaded_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE stg.bookings (
    booking_id TEXT, client_id TEXT, service_type TEXT, shoot_date TEXT, shoot_days TEXT,
    location_city TEXT, gross_amount TEXT, discount_pct TEXT, currency TEXT, status TEXT,
    lead_source TEXT, vat_applied TEXT, notes TEXT,
    _src_file TEXT, _src_row INT, _loaded_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE stg.crew (
    crew_id TEXT, full_name TEXT, role TEXT, day_rate_ngn TEXT, employment_type TEXT,
    is_active TEXT, email TEXT
);

CREATE TABLE stg.crew_timesheets (
    timesheet_id TEXT, booking_id TEXT, crew_id TEXT, work_date TEXT, hours_worked TEXT,
    role_on_job TEXT, day_rate_charged TEXT, overtime TEXT, approved_by TEXT
);

CREATE TABLE stg.merch_products (
    sku TEXT, product_name TEXT, category TEXT, collection TEXT, colour TEXT, size_run TEXT,
    unit_cost_ngn TEXT, list_price_ngn TEXT, valid_from TEXT, valid_to TEXT, active TEXT
);

CREATE TABLE stg.merch_orders (
    order_id TEXT, line_no TEXT, order_ts TEXT, client_id TEXT, customer_email TEXT, sku TEXT,
    product_name TEXT, size TEXT, quantity TEXT, unit_price TEXT, discount_code TEXT,
    shipping_country TEXT, payment_method TEXT, sales_channel TEXT, order_status TEXT
);

CREATE TABLE stg.merch_refunds (
    refund_id TEXT, order_id TEXT, refund_date TEXT, refund_amount TEXT, reason TEXT,
    processed_by TEXT
);

CREATE TABLE stg.web_sessions (
    session_id TEXT, ts_raw TEXT, visitor_id TEXT, source TEXT, medium TEXT, campaign TEXT,
    gclid TEXT, device TEXT, country TEXT, landing_page TEXT, page_views TEXT,
    duration_seconds TEXT, user_agent TEXT, new_visitor TEXT, converted TEXT,
    transaction_id TEXT, revenue TEXT, _src_file TEXT, _ts_format TEXT
);

CREATE TABLE stg.marketing_spend (
    spend_date TEXT, channel TEXT, campaign_name TEXT, impressions TEXT, clicks TEXT,
    spend TEXT, currency TEXT
);

CREATE TABLE stg.fx_rates (
    rate_date TEXT, from_currency TEXT, rate TEXT, to_currency TEXT
);

-- ========================================================== CONFORMED / CORE

CREATE TABLE core.dim_date (
    date_key DATE PRIMARY KEY, year INT, quarter INT, month INT, month_name TEXT,
    week INT, day_of_week INT, is_weekend BOOLEAN, is_peak_season BOOLEAN
);

CREATE TABLE core.dim_client (
    client_key BIGSERIAL PRIMARY KEY,
    client_id INT UNIQUE NOT NULL,           -- resolved surviving ID after dedupe
    merged_from INT[],                       -- duplicate IDs folded in
    client_name TEXT NOT NULL, client_type TEXT, email TEXT, phone TEXT,
    city TEXT, country TEXT, billing_currency CHAR(3),
    signup_date DATE, acquisition_channel TEXT,
    match_confidence NUMERIC(4,3)            -- your fuzzy-match score
);

CREATE TABLE core.dim_service (
    service_key SMALLSERIAL PRIMARY KEY, service_name TEXT UNIQUE NOT NULL, category TEXT
);

CREATE TABLE core.dim_crew (
    crew_key BIGSERIAL PRIMARY KEY, crew_id INT UNIQUE NOT NULL, full_name TEXT,
    role TEXT, standard_day_rate_ngn NUMERIC(14,2), employment_type TEXT, is_active BOOLEAN
);

-- SCD-2, resolved to NON-OVERLAPPING windows. The raw file is not this.
CREATE TABLE core.dim_product (
    product_key BIGSERIAL PRIMARY KEY, sku TEXT NOT NULL, product_name TEXT, category TEXT,
    collection TEXT, colour TEXT, unit_cost_ngn NUMERIC(12,2), list_price_ngn NUMERIC(12,2),
    valid_from DATE NOT NULL, valid_to DATE NOT NULL, is_current BOOLEAN,
    CONSTRAINT product_window_valid CHECK (valid_to >= valid_from),
    EXCLUDE USING gist (sku WITH =, daterange(valid_from, valid_to, '[]') WITH &&)
);

CREATE TABLE core.dim_channel (
    channel_key SMALLSERIAL PRIMARY KEY, channel_name TEXT UNIQUE NOT NULL,
    utm_source_variants TEXT[], is_paid BOOLEAN
);

CREATE TABLE core.fx_daily (            -- gap-filled; document your fill rule
    rate_date DATE, from_currency CHAR(3), to_currency CHAR(3),
    rate NUMERIC(14,6) NOT NULL, is_filled BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (rate_date, from_currency, to_currency)
);

-- ================================================================== FACTS

CREATE TABLE core.fct_booking (              -- grain: one booking
    booking_key BIGSERIAL PRIMARY KEY,
    booking_id INT UNIQUE NOT NULL,
    client_key BIGINT REFERENCES core.dim_client,
    service_key SMALLINT REFERENCES core.dim_service,
    shoot_date DATE REFERENCES core.dim_date,
    shoot_days SMALLINT CHECK (shoot_days BETWEEN 1 AND 30),
    location_city TEXT, status TEXT, lead_source TEXT,
    currency CHAR(3) NOT NULL,
    gross_amount NUMERIC(16,2) CHECK (gross_amount >= 0),
    discount_pct NUMERIC(5,4) CHECK (discount_pct BETWEEN 0 AND 1),
    net_amount NUMERIC(16,2),
    fx_rate NUMERIC(14,6), net_amount_ngn NUMERIC(18,2),
    source_file TEXT
);

CREATE TABLE core.fct_crew_day (             -- grain: one crew member, one job, one day
    crew_day_key BIGSERIAL PRIMARY KEY,
    booking_key BIGINT REFERENCES core.fct_booking,
    crew_key BIGINT REFERENCES core.dim_crew,
    work_date DATE, hours_worked NUMERIC(5,2) CHECK (hours_worked BETWEEN 0 AND 20),
    role_on_job TEXT, day_rate_charged_ngn NUMERIC(14,2), is_overtime BOOLEAN
);

CREATE TABLE core.fct_merch_line (           -- grain: one order line
    order_line_key BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL, line_no SMALLINT NOT NULL,
    order_ts TIMESTAMPTZ NOT NULL,           -- normalised to UTC
    client_key BIGINT REFERENCES core.dim_client,
    product_key BIGINT REFERENCES core.dim_product,
    quantity INT, unit_price_ngn NUMERIC(12,2), gross_ngn NUMERIC(14,2),
    discount_code TEXT, sales_channel TEXT, payment_method TEXT, order_status TEXT,
    refunded_ngn NUMERIC(14,2) DEFAULT 0,
    UNIQUE (order_id, line_no)
);

CREATE TABLE core.fct_session (              -- grain: one session
    session_id TEXT PRIMARY KEY,
    session_start_utc TIMESTAMPTZ NOT NULL, session_date_lagos DATE NOT NULL,
    visitor_id TEXT, channel_key SMALLINT REFERENCES core.dim_channel,
    campaign TEXT, device TEXT, country TEXT, landing_page TEXT,
    page_views INT, duration_seconds INT,
    is_bot BOOLEAN NOT NULL, is_spam BOOLEAN NOT NULL,
    converted BOOLEAN, order_id BIGINT, revenue_ngn NUMERIC(14,2)
);

CREATE TABLE core.fct_ad_spend (             -- grain: day x channel x campaign
    spend_date DATE, channel_key SMALLINT REFERENCES core.dim_channel,
    campaign TEXT, impressions BIGINT, clicks BIGINT, spend_ngn NUMERIC(14,2),
    PRIMARY KEY (spend_date, channel_key, campaign)
);

-- ============================================================== QUARANTINE
-- Nothing gets deleted. Everything you reject lands here with a reason.
CREATE TABLE quarantine.rejected_rows (
    id BIGSERIAL PRIMARY KEY, src_table TEXT NOT NULL, src_file TEXT, src_row INT,
    reason TEXT NOT NULL, payload JSONB NOT NULL, rejected_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON core.fct_booking (shoot_date);
CREATE INDEX ON core.fct_merch_line (order_ts);
CREATE INDEX ON core.fct_session (session_date_lagos);
CREATE INDEX ON quarantine.rejected_rows (src_table, reason);
