"""Scripted SQL for offline mode.

The map is agent/evals/ask.json. This module reads the question and the SQL
only. It does not read the expected values, and it does not call a network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent.sql_tool import format_cell

FIXTURE = Path(__file__).resolve().parent / "evals" / "ask.json"
NO_SCRIPT = "Offline mode has no script for that question, so no warehouse query was run."


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def cases() -> list[dict]:
    payload = json.loads(FIXTURE.read_text())
    found = payload.get("cases")
    if not isinstance(found, list):
        raise ValueError(f"{FIXTURE} is missing cases")
    return found


def scripted_sql(question: str) -> str | None:
    wanted = normalize(question)
    for case in cases():
        if normalize(str(case.get("question", ""))) == wanted:
            sql = case.get("sql")
            if isinstance(sql, str) and sql.strip():
                return sql.strip()
    return None


def render_tool_payload(payload: dict) -> str:
    error = payload.get("error")
    if error:
        return f"The warehouse rejected the query: {error}"
    columns = list(payload.get("columns") or [])
    rows = list(payload.get("rows") or [])
    if not rows:
        return "The warehouse returned no rows."
    lines = []
    for row in rows:
        pairs = [
            f"{column}={format_cell(value)}"
            for column, value in zip(columns, row)
        ]
        lines.append(", ".join(pairs))
    if payload.get("truncated"):
        lines.append("truncated=true")
    return "\n".join(lines)
