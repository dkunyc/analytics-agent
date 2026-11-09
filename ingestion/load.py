"""Load the synthetic CRM fixture into DuckDB with dlt and check merge reruns.

No credentials. No network call to Salesforce or HubSpot.
"""

from __future__ import annotations

import os
import sys

# Set before importing dlt so telemetry stays off for this offline check.
os.environ["RUNTIME__DLTHUB_TELEMETRY"] = "false"
for _key in list(os.environ):
    if _key.startswith(
        (
            "OPENROUTER_",
            "LANGFUSE_",
            "OTEL_",
            "SALESFORCE_",
            "HUBSPOT_",
            "SOURCES__",
            "DESTINATION__",
            "SECRETS__",
        )
    ):
        os.environ.pop(_key, None)

import dlt
import duckdb

from ingestion.config import DATASET_NAME, DB_PATH, PIPELINE_NAME, PIPELINES_DIR
from ingestion.fixture import fixture_tables, opportunity_stage_update
from ingestion.source import synthetic_crm


def fail(message: str) -> None:
    sys.exit(message)


def pipeline() -> dlt.Pipeline:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIPELINES_DIR.mkdir(parents=True, exist_ok=True)
    return dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        pipelines_dir=str(PIPELINES_DIR),
        destination=dlt.destinations.duckdb(str(DB_PATH)),
        dataset_name=DATASET_NAME,
        dev_mode=False,
        progress=None,
    )


def load(tables: dict) -> None:
    pipeline().run(synthetic_crm(tables))


def connect() -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        fail(f"missing {DB_PATH}")
    return duckdb.connect(str(DB_PATH), read_only=True)


def assert_no_duplicates(tables: dict) -> None:
    con = connect()
    try:
        for name, rows in tables.items():
            total, distinct_ids, bad_origin = con.execute(
                f"""
                select
                    count(*),
                    count(distinct source_id),
                    count(*) filter (where data_origin <> 'synthetic')
                from {DATASET_NAME}.{name}
                """
            ).fetchone()
            if total != len(rows) or distinct_ids != len(rows) or bad_origin:
                fail(
                    f"{name}: rows={total} distinct_source_id={distinct_ids} "
                    f"non_synthetic={bad_origin} expected={len(rows)}"
                )
            print(f"{name} rows={total} distinct_source_id={distinct_ids}")
    finally:
        con.close()


def stage_of(source_id: str) -> str:
    con = connect()
    try:
        row = con.execute(
            f"""
            select stage
            from {DATASET_NAME}.salesforce_opportunity
            where source_id = ?
            """,
            [source_id],
        ).fetchone()
    finally:
        con.close()
    if row is None:
        fail(f"missing opportunity {source_id}")
    return str(row[0])


def main() -> None:
    original = fixture_tables()
    print(f"dlt merge into {DB_PATH} dataset={DATASET_NAME}", flush=True)
    load(original)
    assert_no_duplicates(original)
    load(original)
    assert_no_duplicates(original)
    print("rerun kept one row per source_id", flush=True)

    load(opportunity_stage_update())
    assert_no_duplicates(original)
    updated = stage_of("sf-opp-100")
    if updated != "Proposal":
        fail(f"sf-opp-100 stage after merge={updated!r}, expected 'Proposal'")
    print("merge updated sf-opp-100 stage to Proposal without a new row", flush=True)

    load(original)
    assert_no_duplicates(original)
    restored = stage_of("sf-opp-100")
    if restored != "Qualification":
        fail(f"sf-opp-100 stage after restore={restored!r}, expected 'Qualification'")
    print("merge restored sf-opp-100 stage to Qualification", flush=True)
    print("ingestion ok")


if __name__ == "__main__":
    main()
