"""Export the star schema to Parquet extracts so the dashboard runs without a database.

    python warehouse/export_extracts.py

Each extract is a straight SELECT over core.* / quarantine.* (joins to dimensions only, no
aggregation), so every number the dashboard shows is computed from the same rows as the SQL
answers. Also writes a pg_dump of the whole warehouse to warehouse/xtrim_warehouse.dump.
"""
import os
import subprocess
import warnings
from pathlib import Path

import pandas as pd
import psycopg2

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dashboard" / "data"
DSN = os.environ.get("XTRIM_DSN", "host=localhost port=55432 dbname=xtrim user=xtrim")
PG_BIN = os.environ.get("PG_BIN", "/Library/PostgreSQL/17/bin")

EXTRACTS = {
    "bookings": """
        SELECT b.booking_code, b.shoot_date, s.service_name, b.status, b.is_cancelled, b.invoice_currency,
               b.net_amount_ngn::float8 AS net_amount_ngn, b.gross_amount_ngn::float8 AS gross_amount_ngn,
               b.location_city, b.lead_source, b.dq_flags
        FROM core.fct_booking b JOIN core.dim_service s USING (service_key)""",
    "crew_days": """
        SELECT b.booking_code, f.work_date, s.service_name, c.role, c.crew_code, f.hours_worked::float8 AS hours_worked,
               f.labour_cost_ngn::float8 AS labour_cost_ngn, f.rate_is_estimated, b.is_cancelled
        FROM core.fct_crew_day f JOIN core.fct_booking b USING (booking_key)
        JOIN core.dim_service s USING (service_key) JOIN core.dim_crew c USING (crew_key)""",
    "merch_lines": """
        SELECT m.order_id, m.line_no, m.order_date_lagos, p.sku, p.product_name, p.collection, p.category,
               m.quantity, m.gross_ngn::float8 AS gross_ngn, m.refunded_ngn::float8 AS refunded_ngn,
               m.net_ngn::float8 AS net_ngn, m.cogs_ngn::float8 AS cogs_ngn, m.discount_ngn::float8 AS discount_ngn,
               m.is_revenue, m.order_status, m.sales_channel, (m.client_key IS NULL) AS is_guest
        FROM core.fct_merch_line m JOIN core.dim_product p USING (product_key)""",
    "refunds": """
        SELECT r.refund_key, r.order_id, r.refund_date, r.refund_amount_ngn::float8 AS refund_amount_ngn,
               r.counted_ngn::float8 AS counted_ngn, COALESCE(r.reason, 'Unknown') AS reason, r.order_status,
               o.order_date_lagos
        FROM core.fct_refund r
        JOIN (SELECT order_id, MIN(order_date_lagos) AS order_date_lagos FROM core.fct_merch_line GROUP BY 1) o USING (order_id)""",
    "sessions": """
        SELECT s.session_date_lagos, c.channel_name, s.utm_group, s.device, s.is_bot, s.is_spam, s.converted,
               (s.order_id IS NOT NULL) AS joins_order, s.revenue_ngn::float8 AS revenue_ngn
        FROM core.fct_session s JOIN core.dim_channel c USING (channel_key)""",
    "ad_spend": """
        SELECT a.spend_date, c.channel_name, a.campaign, a.impressions, a.clicks, a.spend_ngn::float8 AS spend_ngn
        FROM core.fct_ad_spend a JOIN core.dim_channel c USING (channel_key)""",
    "quarantine": """
        SELECT src_table, reason, value_ngn::float8 AS value_ngn, revenue_affected FROM quarantine.rejected_rows""",
    "fx_usd": """
        SELECT rate_date, rate::float8 AS rate FROM core.fx_daily WHERE from_currency = 'USD'""",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = psycopg2.connect(DSN)
    for name, sql in EXTRACTS.items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = pd.read_sql_query(sql, con)
        for c in df.columns:
            if c.endswith("_date") or c.endswith("_date_lagos"):
                df[c] = pd.to_datetime(df[c])
        df.to_parquet(OUT / f"{name}.parquet", index=False)
        print(f"  {name:<12} {len(df):>8,} rows")
    con.close()
    dump = ROOT / "warehouse" / "xtrim_warehouse.dump"
    subprocess.run([f"{PG_BIN}/pg_dump", "-h", "localhost", "-p", "55432", "-U", "xtrim", "-d", "xtrim",
                    "-Fc", "-f", str(dump)], check=True)
    print(f"  pg_dump -> {dump.name} ({dump.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
