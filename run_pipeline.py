"""Rebuild everything from the raw files with one command.

    python run_pipeline.py                      # raw files from ../xtrim_studios_project/raw_original_backup
    python run_pipeline.py --raw path/to/raw    # any folder holding the 14 original files

Steps: clean -> validate -> data quality profile -> PostgreSQL warehouse -> SQL answers ->
analysis -> charts -> dashboard extracts -> memo + appendix -> deck -> tie-out tests.
Needs a PostgreSQL server reachable through XTRIM_DSN (default: localhost:55432, db xtrim, user xtrim).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def step(name: str, args: list[str], cwd: Path = ROOT):
    t = time.time()
    print(f"\n=== {name}", flush=True)
    subprocess.run(args, cwd=cwd, check=True)
    print(f"--- {name} done in {time.time() - t:.0f}s", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=ROOT.parent / "xtrim_studios_project" / "raw_original_backup")
    ap.add_argument("--skip-docs", action="store_true", help="skip memo, appendix and deck")
    a = ap.parse_args()
    raw = a.raw.resolve()
    if not (raw / "clients_export.csv").exists():
        sys.exit(f"raw files not found in {raw}")

    step("1. clean", [PY, "run_pipeline.py", "--src", str(raw), "--out", str(ROOT / "clean"),
                      "--report", str(ROOT / "cleaning_report")], cwd=ROOT / "pipeline")
    step("2. validate against docs/VALIDATION_KEY.md", [PY, "validate.py", str(ROOT / "clean"), str(ROOT / "cleaning_report")],
         cwd=ROOT / "pipeline")
    step("3. data quality profile (raw)", [PY, "data_quality_report/profile_raw.py", "--raw", str(raw)])
    step("4. load PostgreSQL warehouse", [PY, "warehouse/build_warehouse.py", "--clean", "clean",
                                          "--report", "cleaning_report", "--raw", str(raw)])
    step("5. SQL answers", [PY, "warehouse/run_queries.py"])
    step("6. analysis", [PY, "analysis/analysis.py"])
    step("7. charts", [PY, "analysis/charts.py"])
    step("8. dashboard extracts + warehouse dump", [PY, "warehouse/export_extracts.py"])
    if not a.skip_docs:
        step("9. memo and technical appendix", [PY, "memo/build_memo.py"])
        step("10. deck", [PY, "presentation/build_deck.py"])
    step("11. tie-out tests", [PY, "-m", "pytest", "tests", "-q"])
    print("\nAll steps passed.")


if __name__ == "__main__":
    main()
