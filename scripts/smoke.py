"""Load synthetic CRM data, build the warehouse, and check two analytical results.

No API key. No model call. The DuckDB file is created under warehouse/target
and is gitignored.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import preflight

duckdb = preflight.require_import("duckdb")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.config import DB_PATH, OPEN_PIPELINE_AMOUNT, PIPELINES_DIR  # noqa: E402

WAREHOUSE = ROOT / "warehouse"
EXPECTED_REVENUE = 78.50

SECRET_PREFIXES = (
    "OPENROUTER_",
    "LANGFUSE_",
    "OTEL_",
    "RUM_",
    "SALESFORCE_",
    "HUBSPOT_",
    "SOURCES__",
    "DESTINATION__",
    "SECRETS__",
    "LIBRECHAT_",
    "CODEAPI_",
)


def dbt_executable() -> str:
    sibling = Path(sys.executable).with_name("dbt")
    if sibling.exists():
        return str(sibling)
    found = shutil.which("dbt")
    if found:
        return found
    sys.exit(
        "dbt is not installed. From the repo root: "
        "python3 -m venv .venv && source .venv/bin/activate && "
        "pip install -r requirements.txt"
    )


def child_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(SECRET_PREFIXES)
    }
    env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
    env["DBT_PROFILES_DIR"] = str(WAREHOUSE)
    env["RUNTIME__DLTHUB_TELEMETRY"] = "false"
    return env


def run_dbt(args: list[str]) -> None:
    cmd = [
        dbt_executable(),
        *args,
        "--project-dir",
        str(WAREHOUSE),
        "--profiles-dir",
        str(WAREHOUSE),
        "--no-version-check",
    ]
    print("+", " ".join(cmd), flush=True)
    try:
        subprocess.run(cmd, cwd=WAREHOUSE, env=child_env(), check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)


def remove_generated_database() -> None:
    for path in (DB_PATH, Path(str(DB_PATH) + ".wal")):
        path.unlink(missing_ok=True)
    shutil.rmtree(PIPELINES_DIR, ignore_errors=True)


def run_ingestion() -> None:
    cmd = [sys.executable, "-m", "ingestion.load"]
    print("+", " ".join(cmd), flush=True)
    try:
        subprocess.run(cmd, cwd=ROOT, env=child_env(), check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)


def assert_value(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    expected: float,
    label: str,
) -> None:
    row = con.execute(sql).fetchone()
    actual = None if row is None else row[0]
    print(f"{label}={actual}")
    if actual is None or abs(float(actual) - expected) > 1e-9:
        relations = con.execute(
            """
            select table_schema, table_name
            from information_schema.tables
            order by 1, 2
            """
        ).fetchall()
        print(f"expected {label}={expected}", file=sys.stderr)
        print(f"relations={relations}", file=sys.stderr)
        sys.exit(1)


def assert_revenue(con: duckdb.DuckDBPyConnection) -> None:
    assert_value(
        con,
        "select round(sum(successful_revenue), 2) from customer_orders",
        EXPECTED_REVENUE,
        "successful_revenue",
    )


def main() -> None:
    remove_generated_database()
    run_ingestion()
    run_dbt(["seed", "--full-refresh"])
    run_dbt(["build"])
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        assert_value(
            con,
            "select round(sum(case when is_open then amount else 0 end), 2) from pipeline_items",
            OPEN_PIPELINE_AMOUNT,
            "open_pipeline_amount",
        )
        assert_revenue(con)
    finally:
        con.close()
    print("smoke ok")


if __name__ == "__main__":
    main()
