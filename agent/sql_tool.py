"""The one warehouse tool.

A read-only DuckDB connection, one SELECT or WITH statement, a row cap,
a byte cap, and a wall-clock interrupt. Writes and DDL are rejected here,
before execution. Callers do not receive a writable connection.
"""

from __future__ import annotations

import json
import math
import re
import sys
import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

_FORBIDDEN = re.compile(
    r"\b("
    r"insert|update|delete|drop|create|alter|copy|attach|detach|"
    r"install|load|export|import|call|grant|revoke|truncate|merge|"
    r"vacuum|checkpoint|begin|commit|rollback|pragma|set|execute|"
    r"prepare|analyze|describe|summarize|rename"
    r")\b"
    r"|\breplace\s+into\b",
    re.IGNORECASE,
)
_FILE_READER = re.compile(
    r"\b("
    r"read_csv|read_csv_auto|read_parquet|read_json|read_json_auto|"
    r"read_json_objects|read_ndjson|read_text|read_blob|read_xlsx|"
    r"parquet_scan|csv_scan|json_scan|iceberg_scan|delta_scan|"
    r"sqlite_scan|postgres_scan|mysql_scan|glob"
    r")\s*\(",
    re.IGNORECASE,
)
_FROM_STRING = re.compile(r"\b(?:from|join)\s+['\"]", re.IGNORECASE)
_SELECT_ONLY = "rejected: only a single read-only SELECT or WITH is allowed"


class SqlRejected(Exception):
    """The statement was not executed."""


class SqlFailed(Exception):
    """The statement was allowed and DuckDB returned an error."""


class WarehouseError(Exception):
    """The local warehouse file is not available."""


def _scan(sql: str) -> tuple[str, str]:
    """Return structure (comments and quotes blanked) and readable (comments blanked)."""
    structure: list[str] = []
    readable: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            while i < n and sql[i] != "\n":
                structure.append(" ")
                readable.append(" ")
                i += 1
            continue
        if ch == "/" and nxt == "*":
            while i < n and not (sql[i] == "*" and i + 1 < n and sql[i + 1] == "/"):
                structure.append("\n" if sql[i] == "\n" else " ")
                readable.append("\n" if sql[i] == "\n" else " ")
                i += 1
            if i < n:
                structure.append(" ")
                readable.append(" ")
                i += 1
            if i < n and sql[i] == "/":
                structure.append(" ")
                readable.append(" ")
                i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            structure.append(" ")
            readable.append(ch)
            i += 1
            while i < n:
                if sql[i] == quote and i + 1 < n and sql[i + 1] == quote:
                    structure.extend("  ")
                    readable.append(quote)
                    readable.append(quote)
                    i += 2
                    continue
                structure.append(" ")
                readable.append(sql[i])
                i += 1
                if readable[-1] == quote:
                    break
            continue
        structure.append(ch)
        readable.append(ch)
        i += 1
    return "".join(structure), "".join(readable)


def guard_sql(sql: str) -> str:
    """Return the stripped statement, or raise SqlRejected without executing it."""
    if not isinstance(sql, str) or "\x00" in sql:
        raise SqlRejected(_SELECT_ONLY)
    text = sql.strip()
    if not text:
        raise SqlRejected(_SELECT_ONLY)
    structure, readable = _scan(text)
    body = structure.strip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in body:
        raise SqlRejected("rejected: only one statement is allowed")
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", body)
    if not tokens or tokens[0].lower() not in {"select", "with"}:
        raise SqlRejected(_SELECT_ONLY)
    if _FORBIDDEN.search(body) or _FILE_READER.search(body) or _FROM_STRING.search(readable):
        raise SqlRejected(_SELECT_ONLY)
    stripped = text[:-1].rstrip() if text.endswith(";") else text
    if ";" in _scan(stripped)[0]:
        raise SqlRejected("rejected: only one statement is allowed")
    return stripped


def format_cell(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return str(int(value))
        return format(value, "g")
    return str(value)


def _cell(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value.is_integer():
            return int(value)
        return value
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _fit(columns: list[str], rows: list[list[Any]], max_bytes: int) -> tuple[list[list[Any]], bool]:
    kept: list[list[Any]] = []
    truncated = False
    for row in rows:
        trial = kept + [row]
        payload = {"columns": columns, "rows": trial, "rows_returned": len(trial), "truncated": False}
        size = len(json.dumps(payload, ensure_ascii=False).encode())
        if size > max_bytes:
            truncated = True
            break
        kept = trial
    if not kept and rows:
        raise SqlRejected(f"rejected: result exceeded {max_bytes} bytes")
    return kept, truncated or len(kept) < len(rows)


class SqlTool:
    def __init__(self, db_path: Path, row_limit: int, timeout_ms: int, max_bytes: int) -> None:
        if row_limit <= 0 or timeout_ms <= 0 or max_bytes <= 0:
            raise ValueError("sql limits must be positive")
        self.db_path = db_path
        self.row_limit = row_limit
        self.timeout_ms = timeout_ms
        self.max_bytes = max_bytes

    def query(self, sql: str) -> dict[str, Any]:
        statement = guard_sql(sql)
        if not self.db_path.exists():
            raise WarehouseError(
                f"missing {self.db_path}. Run: python scripts/smoke.py"
            )
        wrapped = (
            "select * from (\n"
            f"{statement}\n"
            f") as _agent_rows limit {self.row_limit + 1}"
        )
        con = duckdb.connect(str(self.db_path), read_only=True)
        finished = threading.Event()
        interrupted = threading.Event()

        def interrupt_if_late() -> None:
            if not finished.wait(self.timeout_ms / 1000):
                interrupted.set()
                try:
                    con.interrupt()
                except Exception:
                    return

        watcher = threading.Thread(target=interrupt_if_late, daemon=True)
        watcher.start()
        try:
            try:
                cursor = con.execute(wrapped)
                columns = [item[0] for item in cursor.description]
                fetched = cursor.fetchmany(self.row_limit + 1)
            except Exception as exc:
                if interrupted.is_set() or "interrupt" in str(exc).lower():
                    raise SqlRejected(f"rejected: query exceeded {self.timeout_ms}ms") from exc
                message = " ".join(str(exc).split())
                raise SqlFailed(f"sql error: {message[:500]}") from exc
        finally:
            finished.set()
            watcher.join(timeout=1)
            con.close()

        hit_row_cap = len(fetched) > self.row_limit
        rows = [[_cell(value) for value in row] for row in fetched[: self.row_limit]]
        rows, hit_byte_cap = _fit(columns, rows, self.max_bytes)
        return {
            "columns": columns,
            "rows": rows,
            "rows_returned": len(rows),
            "truncated": hit_row_cap or hit_byte_cap,
        }


def main(argv: list[str] | None = None) -> int:
    from agent.config import load_settings

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print('usage: python -m agent.sql_tool "select ..."', file=sys.stderr)
        return 2
    settings = load_settings()
    tool = SqlTool(
        settings.db_path,
        settings.row_limit,
        settings.timeout_ms,
        settings.max_bytes,
    )
    try:
        result = tool.query(" ".join(args))
    except (SqlRejected, SqlFailed, WarehouseError) as exc:
        print(exc)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
