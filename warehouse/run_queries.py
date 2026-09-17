"""Run every query in sql/02_questions_answered.sql and save results/qNN.csv."""
import os
import re
import sys
from pathlib import Path

import pandas as pd
import psycopg2

ROOT = Path(__file__).resolve().parent.parent
DSN = os.environ.get("XTRIM_DSN", "host=localhost port=55432 dbname=xtrim user=xtrim")


def main():
    sql = (ROOT / "sql" / "02_questions_answered.sql").read_text()
    parts = re.split(r"^-- @q (\w+)\s*$", sql, flags=re.M)
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    con = psycopg2.connect(DSN)
    for qid, body in zip(parts[1::2], parts[2::2]):
        df = pd.read_sql_query(body, con)
        df.to_csv(out / f"q{qid}.csv", index=False)
        print(f"q{qid}: {len(df)} rows")
    con.close()


if __name__ == "__main__":
    sys.exit(main())
