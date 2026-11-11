"""Schema text and stored categorical values, read from the warehouse.

Values are not hard-coded. A column is listed when it is text or boolean,
is not an identifier or a person name, and has at most 12 distinct values.
"""

from __future__ import annotations

import re
from typing import Any

from agent.sql_tool import SqlFailed, SqlRejected, SqlTool, WarehouseError

_SCHEMA_SQL = """
select table_schema, table_name, column_name, data_type
from information_schema.columns
where (
    table_schema = 'main'
    and table_name in (
        'pipeline_items', 'customer_orders', 'fct_orders',
        'stg_customers', 'stg_orders', 'stg_payments'
    )
) or (
    table_schema = 'crm_raw' and table_name = 'signup_event'
)
order by table_schema, table_name, ordinal_position
""".strip()
_FALLBACK_SCHEMA = """
Tables:
main.pipeline_items(source_system, item_source_id, organization_source_id, stage, amount, is_open, extracted_at)
main.customer_orders(customer_id, first_name, last_name, order_count, completed_order_count, successful_revenue)
main.fct_orders(order_id, customer_id, ordered_at, status, payment_count, successful_revenue)
crm_raw.signup_event(source_system, source_id, mapping_status, hubspot_contact_source_id, occurred_at, channel, data_origin)
""".strip()
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SKIP_NAMES = {"first_name", "last_name", "full_name", "email", "name"}
_MAX_DISTINCT = 12


def _categorical(column: str, data_type: str) -> bool:
    kind = data_type.upper()
    if not any(token in kind for token in ("CHAR", "VARCHAR", "TEXT", "STRING", "BOOLEAN", "BOOL")):
        return False
    if column.endswith("_id") or column in _SKIP_NAMES:
        return False
    return bool(_IDENT.fullmatch(column))


def _schema_rows(tool: SqlTool) -> list[tuple[str, str, str, str]]:
    result = tool.query(_SCHEMA_SQL)
    rows = []
    for schema, table, column, data_type in result["rows"]:
        if str(column).startswith("_dlt"):
            continue
        if not (_IDENT.fullmatch(str(schema)) and _IDENT.fullmatch(str(table))):
            continue
        rows.append((str(schema), str(table), str(column), str(data_type)))
    return rows


def _stored_values(tool: SqlTool, rows: list[tuple[str, str, str, str]]) -> dict[str, list[str]]:
    branches = []
    for schema, table, column, data_type in rows:
        if not _categorical(column, data_type):
            continue
        relation = f"{schema}.{table}"
        branches.append(
            "("
            f"select '{relation}' as relation_name, '{column}' as column_name, "
            f"cast({column} as varchar) as stored_value "
            f"from {schema}.{table} "
            f"where {column} is not null "
            "group by 1, 2, 3 order by 3 "
            f"limit {_MAX_DISTINCT + 1}"
            ")"
        )
    if not branches:
        return {}
    result = tool.query(" union all ".join(branches))
    grouped: dict[str, list[str]] = {}
    for relation, column, value in result["rows"]:
        if value is None:
            continue
        grouped.setdefault(f"{relation}.{column}", []).append(str(value))
    stored = {}
    for key, values in grouped.items():
        unique = list(dict.fromkeys(values))
        if len(unique) > _MAX_DISTINCT:
            continue
        stored[key] = unique
    return stored


def describe_warehouse(tool: SqlTool) -> tuple[str, dict[str, list[str]]]:
    """Return the prompt section and a map of relation.column to stored spellings."""
    try:
        rows = _schema_rows(tool)
    except (SqlRejected, SqlFailed, WarehouseError):
        return _FALLBACK_SCHEMA, {}
    if not rows:
        return _FALLBACK_SCHEMA, {}
    grouped: dict[str, list[str]] = {}
    for schema, table, column, data_type in rows:
        grouped.setdefault(f"{schema}.{table}", []).append(f"{column} {data_type}")
    try:
        stored = _stored_values(tool, rows)
    except (SqlRejected, SqlFailed, WarehouseError):
        stored = {}
    lines = ["Tables:"]
    for name in sorted(grouped):
        lines.append(f"{name}({', '.join(grouped[name])})")
    if stored:
        lines.append("")
        lines.append("Stored values (copy these spellings exactly; filters are case-sensitive):")
        for key in sorted(stored):
            lines.append(f"{key}: {', '.join(stored[key])}")
    return "\n".join(lines), stored


def string_literals(sql: str) -> list[str]:
    found: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        if sql[i] != "'":
            i += 1
            continue
        i += 1
        chars: list[str] = []
        while i < n:
            if sql[i] == "'" and i + 1 < n and sql[i + 1] == "'":
                chars.append("'")
                i += 2
                continue
            if sql[i] == "'":
                i += 1
                break
            chars.append(sql[i])
            i += 1
        found.append("".join(chars))
    return found


def empty_result(payload: dict[str, Any]) -> bool:
    if payload.get("error"):
        return False
    rows = payload.get("rows") or []
    if not rows:
        return True
    return all(all(cell is None for cell in row) for row in rows)


def warn_if_empty(payload: dict[str, Any], sql: str, stored: dict[str, list[str]]) -> dict[str, Any]:
    if not empty_result(payload):
        return payload
    notes = []
    for literal in string_literals(sql):
        for key, values in stored.items():
            for value in values:
                if literal != value and literal.lower() == value.lower():
                    notes.append(f"{literal!r} is not stored in {key}; use {value!r}")
    warning = (
        "This result is null or empty. That is not evidence the metric is zero. "
        "Filters are case-sensitive."
    )
    if notes:
        warning += " " + " ".join(notes) + "."
    warning += " Retry with a stored value. Do not tell the user the pipeline is empty."
    updated = dict(payload)
    updated["warning"] = warning
    return updated
