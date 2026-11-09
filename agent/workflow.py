"""Ask one warehouse question.

`ask` is the function a later UI can call. It does not import a chat frontend.
The model may call query_warehouse. That call is the only warehouse access.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.config import Settings, load_settings
from agent.provider import (
    TOOL_NAME,
    ModelTurn,
    OfflineProvider,
    OpenRouterProvider,
    ToolCall,
)
from agent.sql_tool import SqlFailed, SqlRejected, SqlTool, WarehouseError
from agent.trace import new_record, redact, write_trace

MAX_TOOL_ROUNDS = 4
_SCHEMA_TABLES = (
    "pipeline_items",
    "customer_orders",
    "fct_orders",
    "stg_customers",
    "stg_orders",
    "stg_payments",
)
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
_TOOL_RULES = """
Use query_warehouse for every number. Pass one SELECT or WITH statement.
The tool rejects writes, DDL, multiple statements, and file reads.
Open pipeline is the sum of pipeline_items.amount where is_open is true.
Keep Salesforce and HubSpot apart. Do not join them on names or emails.
A signup with a null hubspot_contact_source_id is not a HubSpot contact.
successful_revenue comes from customer_orders or fct_orders, not from pipeline_items.
If the tool returns an error or no rows, say so. Do not invent rows.
""".strip()
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Run one read-only SELECT or WITH query on the local DuckDB warehouse.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "One SELECT or WITH statement.",
                    }
                },
                "required": ["sql"],
            },
        },
    }
]


@dataclass
class AskResult:
    question: str
    answer: str
    sql: list[str]
    rows_returned: int
    calls: list[dict[str, Any]]
    model: str
    latency_ms: float
    tokens: dict[str, int] | None
    trace_path: str
    rows: list[list[Any]] = field(default_factory=list)


def build_provider(settings: Settings, *, offline: bool | None) -> OfflineProvider | OpenRouterProvider:
    forced = settings.env_value(settings.provider_env).lower()
    if offline is True or forced == "offline":
        return OfflineProvider()
    key = settings.env_value(settings.key_env)
    if forced == "openrouter" or key:
        if not key:
            raise RuntimeError(
                f"{settings.key_env} is empty. Export it, or set "
                f"{settings.provider_env}=offline."
            )
        model = settings.env_value(settings.model_env) or settings.model
        return OpenRouterProvider(
            api_key=key,
            model=model,
            base_url=settings.base_url,
            timeout_s=settings.openrouter_timeout_s,
        )
    return OfflineProvider()


def _schema_text(tool: SqlTool) -> str:
    try:
        result = tool.query(_SCHEMA_SQL)
    except (SqlRejected, SqlFailed, WarehouseError):
        return _FALLBACK_SCHEMA
    grouped: dict[str, list[str]] = {}
    for schema, table, column, data_type in result["rows"]:
        if str(column).startswith("_dlt"):
            continue
        grouped.setdefault(f"{schema}.{table}", []).append(f"{column} {data_type}")
    if not grouped:
        return _FALLBACK_SCHEMA
    lines = ["Tables:"]
    for name in sorted(grouped):
        lines.append(f"{name}({', '.join(grouped[name])})")
    return "\n".join(lines)


def _system_prompt(schema_text: str) -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / "analyst.md"
    policy = prompt_path.read_text().strip()
    return f"{policy}\n\n{schema_text}\n\n{_TOOL_RULES}"


def _assistant_message(turn: ModelTurn) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": turn.content or ""}
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in turn.tool_calls
        ]
    return message


def _run_tool(tool: SqlTool, call: ToolCall) -> dict[str, Any]:
    if call.name != TOOL_NAME:
        return {"error": "unknown tool"}
    sql = call.arguments.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        return {"error": "query_warehouse requires a sql string"}
    try:
        return tool.query(sql)
    except SqlRejected as exc:
        return {"error": str(exc), "sql": sql}
    except SqlFailed as exc:
        return {"error": str(exc), "sql": sql}


def _add_tokens(
    total: dict[str, int] | None, turn: ModelTurn
) -> dict[str, int] | None:
    if not turn.tokens:
        return total
    if total is None:
        total = {"prompt": 0, "completion": 0, "total": 0}
    for key in total:
        total[key] += int(turn.tokens.get(key) or 0)
    return total


def ask(
    question: str,
    *,
    offline: bool | None = None,
    trace_path: str | Path | None = None,
) -> AskResult:
    text = question.strip()
    if not text:
        raise ValueError("question is empty")
    settings = load_settings()
    destination = Path(trace_path) if trace_path is not None else settings.trace_path
    if not destination.is_absolute():
        destination = settings.trace_path.parent / destination
    provider = build_provider(settings, offline=offline)
    tool = SqlTool(
        settings.db_path,
        settings.row_limit,
        settings.timeout_ms,
        settings.max_bytes,
    )
    if not settings.db_path.exists():
        raise WarehouseError(f"missing {settings.db_path}. Run: python scripts/smoke.py")
    started = time.time()
    perf = time.perf_counter()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(_schema_text(tool))},
        {"role": "user", "content": text},
    ]
    calls: list[dict[str, Any]] = []
    rows: list[list[Any]] = []
    tokens: dict[str, int] | None = None
    answer = "The model stopped without an answer."
    for _ in range(MAX_TOOL_ROUNDS):
        turn = provider.complete(messages, TOOLS)
        tokens = _add_tokens(tokens, turn)
        if not turn.tool_calls:
            if turn.content and turn.content.strip():
                answer = turn.content.strip()
            break
        messages.append(_assistant_message(turn))
        for call in turn.tool_calls:
            payload = _run_tool(tool, call)
            sql = call.arguments.get("sql") if isinstance(call.arguments.get("sql"), str) else ""
            error = payload.get("error")
            if error:
                calls.append({"sql": sql, "rows_returned": 0, "error": str(error)})
            else:
                calls.append(
                    {
                        "sql": sql,
                        "rows_returned": int(payload.get("rows_returned") or 0),
                        "error": None,
                    }
                )
                rows = list(payload.get("rows") or [])
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(payload, ensure_ascii=False),
                }
            )
    ended = time.time()
    latency_ms = (time.perf_counter() - perf) * 1000
    record = new_record(
        question=text,
        sql=[call["sql"] for call in calls if call["sql"]],
        rows_returned=sum(call["rows_returned"] for call in calls),
        answer=answer,
        model=provider.model,
        latency_ms=latency_ms,
        tokens=tokens,
        calls=calls,
    )
    write_trace(
        destination,
        record,
        started=started,
        ended=ended,
        langfuse_timeout_s=settings.langfuse_timeout_s,
    )
    return AskResult(
        question=record["question"],
        answer=redact(answer),
        sql=record["sql"],
        rows_returned=record["rows_returned"],
        calls=record["calls"],
        model=record["model"],
        latency_ms=record["latency_ms"],
        tokens=record["tokens"],
        trace_path=str(destination),
        rows=rows,
    )
