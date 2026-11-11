"""Local JSONL traces, and an optional Langfuse OTLP export.

The JSONL file is the record that always exists. Langfuse is used only when
LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_BASE_URL are all set.
The export is one OTLP/HTTP JSON request to /api/public/otel/v1/traces.
Secrets are removed before either destination is written.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_ENV = (
    "OPENROUTER_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)


def secret_values() -> list[str]:
    found = []
    for name in _SECRET_ENV:
        value = os.environ.get(name, "").strip()
        if len(value) >= 8:
            found.append(value)
    return found


def redact(text: str) -> str:
    for secret in secret_values():
        text = text.replace(secret, "[redacted]")
    return text


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    return value


def new_record(
    *,
    question: str,
    sql: list[str],
    rows_returned: int,
    answer: str,
    model: str,
    latency_ms: float,
    tokens: dict[str, int] | None,
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    record = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "question": question,
        "sql": sql,
        "rows_returned": rows_returned,
        "answer": answer,
        "model": model,
        "latency_ms": round(latency_ms, 1),
        "tokens": tokens,
        "calls": calls,
    }
    return _redact_value(record)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def langfuse_traces_url(base_url: str) -> str:
    root = base_url.strip().rstrip("/")
    suffix = "/api/public/otel/v1/traces"
    if root.endswith(suffix):
        return root
    if root.endswith("/api/public/otel"):
        return root + "/v1/traces"
    return root + suffix


def _attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _span(
    *,
    trace_id: str,
    span_id: str,
    parent_id: str | None,
    name: str,
    start_ns: str,
    end_ns: str,
    attributes: list[dict[str, Any]],
) -> dict[str, Any]:
    span = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
        "attributes": attributes,
        "status": {"code": 1},
    }
    if parent_id:
        span["parentSpanId"] = parent_id
    return span


def build_otlp(record: dict[str, Any], *, started: float, ended: float) -> dict[str, Any]:
    trace_id = record["id"]
    root_id = uuid.uuid4().hex[:16]
    start_ns = str(int(started * 1_000_000_000))
    end_ns = str(int(ended * 1_000_000_000))
    if end_ns <= start_ns:
        end_ns = str(int(start_ns) + 1)
    shared = [
        _attr("langfuse.trace.name", "agent.ask"),
        _attr("langfuse.trace.metadata.model", record["model"]),
        _attr("langfuse.trace.metadata.rows_returned", str(record["rows_returned"])),
        _attr("langfuse.trace.metadata.latency_ms", str(record["latency_ms"])),
        _attr("langfuse.trace.metadata.sql", json.dumps(record["sql"])),
    ]
    spans = [
        _span(
            trace_id=trace_id,
            span_id=root_id,
            parent_id=None,
            name="agent.ask",
            start_ns=start_ns,
            end_ns=end_ns,
            attributes=[
                *shared,
                _attr("langfuse.observation.type", "agent"),
                _attr("langfuse.observation.input", record["question"]),
                _attr("langfuse.observation.output", record["answer"]),
                _attr("langfuse.observation.metadata.model", record["model"]),
                _attr("langfuse.observation.metadata.rows_returned", record["rows_returned"]),
            ],
        )
    ]
    generation_attributes = [
        *shared,
        _attr("langfuse.observation.type", "generation"),
        _attr("langfuse.observation.model.name", record["model"]),
        _attr("gen_ai.request.model", record["model"]),
        _attr("langfuse.observation.input", record["question"]),
        _attr("langfuse.observation.output", record["answer"]),
    ]
    tokens = record.get("tokens")
    if isinstance(tokens, dict):
        usage = {
            "input": int(tokens.get("prompt") or 0),
            "output": int(tokens.get("completion") or 0),
            "total": int(tokens.get("total") or 0),
        }
        generation_attributes.append(
            _attr("langfuse.observation.usage_details", json.dumps(usage))
        )
        generation_attributes.append(_attr("gen_ai.usage.input_tokens", usage["input"]))
        generation_attributes.append(_attr("gen_ai.usage.output_tokens", usage["output"]))
    spans.append(
        _span(
            trace_id=trace_id,
            span_id=uuid.uuid4().hex[:16],
            parent_id=root_id,
            name="generation",
            start_ns=start_ns,
            end_ns=end_ns,
            attributes=generation_attributes,
        )
    )
    for call in record.get("calls") or []:
        output = (
            call["error"]
            if call.get("error")
            else json.dumps({"rows_returned": call.get("rows_returned", 0)})
        )
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=uuid.uuid4().hex[:16],
                parent_id=root_id,
                name="query_warehouse",
                start_ns=start_ns,
                end_ns=end_ns,
                attributes=[
                    *shared,
                    _attr("langfuse.observation.type", "tool"),
                    _attr("langfuse.observation.input", call.get("sql", "")),
                    _attr("langfuse.observation.output", output),
                    _attr("langfuse.observation.metadata.rows_returned", call.get("rows_returned", 0)),
                ],
            )
        )
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [_attr("service.name", "analytics-agent")]
                },
                "scopeSpans": [{"scope": {"name": "agent.ask"}, "spans": spans}],
            }
        ]
    }


def _langfuse_env() -> tuple[str, str, str] | None:
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    base = os.environ.get("LANGFUSE_BASE_URL", "").strip()
    if not (public and secret and base):
        return None
    return public, secret, base


def export_langfuse(record: dict[str, Any], *, started: float, ended: float, timeout_s: float) -> None:
    keys = _langfuse_env()
    if keys is None:
        return
    public, secret, base = keys
    token = base64.b64encode(f"{public}:{secret}".encode()).decode()
    payload = build_otlp(record, started=started, ended=ended)
    request = urllib.request.Request(
        langfuse_traces_url(base),
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "x-langfuse-ingestion-version": "4",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(redact(f"HTTP {exc.code} {detail}".strip())) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(redact(f"{exc.reason}")) from None


def write_trace(
    path: Path,
    record: dict[str, Any],
    *,
    started: float,
    ended: float,
    langfuse_timeout_s: float,
) -> None:
    append_jsonl(path, record)
    try:
        export_langfuse(
            record,
            started=started,
            ended=ended,
            timeout_s=langfuse_timeout_s,
        )
    except Exception as exc:
        print(f"langfuse export failed: {redact(str(exc))}", file=sys.stderr)
