"""dlt source for the local synthetic fixture.

This is not `salesforce_source` or `hubspot` from dlt verified sources. Those
connectors need credentials and are not called here.
"""

from __future__ import annotations

from typing import Any

import dlt

from ingestion.fixture import fixture_tables


def make_table(table_name: str, rows: list[dict[str, Any]]) -> Any:
    @dlt.resource(
        name=table_name,
        write_disposition="merge",
        primary_key=["source_system", "source_id"],
        columns={"extracted_at": {"data_type": "timestamp"}},
    )
    def table() -> Any:
        yield rows

    return table()


@dlt.source(name="synthetic_b2b_crm")
def synthetic_crm(tables: dict[str, list[dict[str, Any]]] | None = None) -> list[Any]:
    data = fixture_tables() if tables is None else tables
    return [make_table(name, rows) for name, rows in data.items()]
