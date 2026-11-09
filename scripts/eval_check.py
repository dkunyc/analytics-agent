"""Offline baseline check. Runs fixture SQL against the local DuckDB file.

This does not call a model. Run scripts/smoke.py first so the warehouse exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import preflight

duckdb = preflight.require_import("duckdb")

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "warehouse" / "target" / "warehouse.duckdb"
FIXTURE = ROOT / "agent" / "evals" / "baseline.json"


def values_match(actual: object, expected: object) -> bool:
    if isinstance(expected, bool):
        return actual == expected
    if isinstance(expected, (int, float)):
        if actual is None:
            return False
        try:
            return abs(float(actual) - float(expected)) <= 1e-9
        except (TypeError, ValueError):
            return False
    return actual == expected


def main() -> None:
    if not DB_PATH.exists():
        sys.exit(f"missing {DB_PATH}. Run: python scripts/smoke.py")
    fixture = json.loads(FIXTURE.read_text())
    cases = fixture["cases"]
    con = duckdb.connect(str(DB_PATH), read_only=True)
    failed = 0
    try:
        for case in cases:
            case_id = case["id"]
            row = con.execute(case["sql"]).fetchone()
            actual = None if row is None else row[0]
            ok = values_match(actual, case["expected"])
            status = "pass" if ok else "fail"
            print(
                f"{status} {case_id} category={case['category']} "
                f"actual={actual!r} expected={case['expected']!r}"
            )
            failed += not ok
    finally:
        con.close()
    if failed:
        sys.exit(f"eval failed {failed} of {len(cases)}")
    print(f"eval ok {len(cases)} cases")


if __name__ == "__main__":
    main()
