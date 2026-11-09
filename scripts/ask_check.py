"""Offline ask check. Runs the headless workflow and the SQL guard.

No model call and no network. Run scripts/smoke.py first so the warehouse exists.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import preflight

duckdb = preflight.require_import("duckdb")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.config import load_settings  # noqa: E402
from agent.offline import NO_SCRIPT, normalize, scripted_sql  # noqa: E402
from agent.provider import ToolCall  # noqa: E402
from agent.sql_tool import SqlRejected, SqlTool  # noqa: E402
from agent.trace import build_otlp, langfuse_traces_url, new_record  # noqa: E402
from agent.workflow import ask  # noqa: E402

TRACE_PATH = ROOT / "traces" / "ask-check.jsonl"
SENTINEL = "sk-sentinel-do-not-log-4832"
REJECTED_SQL = (
    "delete from pipeline_items",
    "drop table pipeline_items",
    "insert into pipeline_items (source_system) values ('salesforce')",
    "update pipeline_items set amount = 0",
    "create table evil as select 1 as x",
    "select 1; drop table pipeline_items",
    "/* hide */ drop table pipeline_items",
    "with x as (select 1 as n) delete from pipeline_items",
    "copy pipeline_items to 'out.csv'",
    "attach 'other.duckdb' as other",
    "select * from read_csv_auto('/etc/passwd')",
    "pragma version",
)


def values_match(actual: object, expected: object) -> bool:
    if isinstance(expected, bool):
        return actual == expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if actual is None or isinstance(actual, bool):
            return False
        try:
            return abs(float(actual) - float(expected)) <= 1e-9
        except (TypeError, ValueError):
            return False
    return actual == expected


def rows_match(actual: list, expected: list) -> bool:
    if len(actual) != len(expected):
        return False
    for actual_row, expected_row in zip(actual, expected):
        if len(actual_row) != len(expected_row):
            return False
        if not all(values_match(left, right) for left, right in zip(actual_row, expected_row)):
            return False
    return True


def answer_has(answer: str, value: object) -> bool:
    if isinstance(value, str):
        return value in answer
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value)
    return re.search(rf"(?<![\d.]){re.escape(text)}(?![\d.])", answer) is not None


def require_trace_keys(record: dict) -> None:
    required = (
        "question",
        "sql",
        "rows_returned",
        "answer",
        "model",
        "latency_ms",
        "tokens",
    )
    missing = [key for key in required if key not in record]
    if missing:
        raise AssertionError(f"trace missing {missing}")


def open_amount(con: duckdb.DuckDBPyConnection) -> float:
    row = con.execute(
        "select round(sum(amount), 2) from pipeline_items where is_open"
    ).fetchone()
    return float(row[0])


def main() -> None:
    settings = load_settings()
    if not settings.db_path.exists():
        sys.exit(f"missing {settings.db_path}. Run: python scripts/smoke.py")
    if settings.key_env != "OPENROUTER_KEY":
        sys.exit(f"openrouter key env is {settings.key_env}, expected OPENROUTER_KEY")
    if settings.base_url != "https://openrouter.ai/api/v1":
        sys.exit(f"openrouter base url is {settings.base_url}")
    os.environ["OPENROUTER_KEY"] = SENTINEL
    os.environ["LANGFUSE_SECRET_KEY"] = ""
    os.environ["LANGFUSE_PUBLIC_KEY"] = ""
    os.environ["LANGFUSE_BASE_URL"] = ""
    TRACE_PATH.unlink(missing_ok=True)
    fixture = json.loads((ROOT / "agent" / "evals" / "ask.json").read_text())
    cases = fixture["cases"]
    failed = 0

    def refuse_network(*_args, **_kwargs):
        raise AssertionError("offline ask attempted a network call")

    with patch("urllib.request.urlopen", side_effect=refuse_network):
        for case in cases:
            result = ask(case["question"], offline=True, trace_path=TRACE_PATH)
            ok = (
                result.model == "offline-stub"
                and result.tokens is None
                and result.sql
                and normalize(result.sql[0]) == normalize(scripted_sql(case["question"]) or "")
                and rows_match(result.rows, case["expected_rows"])
                and all(answer_has(result.answer, value) for row in case["expected_rows"] for value in row)
            )
            status = "pass" if ok else "fail"
            print(
                f"{status} {case['id']} model={result.model} "
                f"rows={result.rows!r} expected={case['expected_rows']!r}"
            )
            if not ok:
                print(f"answer={result.answer!r} sql={result.sql!r}", file=sys.stderr)
            failed += not ok
        unknown = ask(
            "What is the meaning of pipeline?",
            offline=True,
            trace_path=TRACE_PATH,
        )
        unknown_ok = unknown.answer == NO_SCRIPT and unknown.sql == [] and unknown.rows_returned == 0
        print(f"{'pass' if unknown_ok else 'fail'} unknown_question sql={unknown.sql!r}")
        failed += not unknown_ok

    if not TRACE_PATH.exists():
        sys.exit(f"missing trace {TRACE_PATH}")
    trace_text = TRACE_PATH.read_text()
    if SENTINEL in trace_text:
        sys.exit("trace file contains the sentinel secret")
    records = [json.loads(line) for line in trace_text.splitlines() if line.strip()]
    if len(records) != len(cases) + 1:
        sys.exit(f"expected {len(cases) + 1} trace rows, found {len(records)}")
    for record in records:
        require_trace_keys(record)
        if record["model"] != "offline-stub":
            sys.exit(f"trace model={record['model']}")
        if not isinstance(record["latency_ms"], (int, float)):
            sys.exit("trace latency_ms is missing")
        if record["tokens"] is not None:
            sys.exit("offline trace should not invent tokens")
    print(f"trace ok {TRACE_PATH} rows={len(records)}")

    tool = SqlTool(settings.db_path, settings.row_limit, settings.timeout_ms, settings.max_bytes)
    for sql in REJECTED_SQL:
        try:
            tool.query(sql)
        except SqlRejected as exc:
            message = str(exc)
            if not message.startswith("rejected:"):
                sys.exit(f"unexpected rejection text for {sql!r}: {message}")
            print(f"guard {sql} -> {message}")
            continue
        sys.exit(f"guard allowed {sql!r}")

    literal = tool.query("select 'drop table pipeline_items' as example")
    if literal["rows"] != [["drop table pipeline_items"]]:
        sys.exit(f"string literal was not preserved: {literal['rows']!r}")
    print("guard kept a drop keyword inside a string literal")

    comment = tool.query("select 1 as one -- drop table pipeline_items")
    if comment["rows"] != [[1]]:
        sys.exit(f"comment was not ignored: {comment['rows']!r}")
    print("guard ignored a drop keyword inside a comment")

    limited = SqlTool(settings.db_path, 3, settings.timeout_ms, settings.max_bytes)
    capped = limited.query("select range as n from range(50)")
    if capped["rows_returned"] != 3 or not capped["truncated"]:
        sys.exit(f"row limit failed: {capped}")
    print("guard row limit returned 3 truncated rows")

    sized = SqlTool(settings.db_path, 50, settings.timeout_ms, 400)
    fitted = sized.query("select repeat('a', 80) as value from range(20)")
    if not fitted["truncated"] or not fitted["rows"] or fitted["rows_returned"] >= 20:
        sys.exit(f"byte limit failed: {fitted['rows_returned']} truncated={fitted['truncated']}")
    print(f"guard byte limit kept {fitted['rows_returned']} rows")

    timeout_code = """
from agent.config import load_settings
from agent.sql_tool import SqlRejected, SqlTool

settings = load_settings()
tool = SqlTool(settings.db_path, settings.row_limit, 300, settings.max_bytes)
try:
    tool.query("select count(*) from range(100000000000)")
except SqlRejected as exc:
    if "exceeded 300ms" not in str(exc):
        raise SystemExit(str(exc))
    print(exc)
else:
    raise SystemExit("timeout guard did not stop the query")
"""
    try:
        timed = subprocess.run(
            [sys.executable, "-c", timeout_code],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        sys.exit("timeout guard did not return within 20s")
    if timed.returncode != 0:
        sys.exit(f"timeout guard failed: {timed.stdout} {timed.stderr}")
    print(f"guard timeout -> {timed.stdout.strip()}")

    con = duckdb.connect(str(settings.db_path), read_only=True)
    try:
        try:
            con.execute("delete from pipeline_items")
        except duckdb.Error as exc:
            print(f"read-only connection rejected delete: {exc}")
        else:
            sys.exit("read-only connection accepted delete")
        amount = open_amount(con)
    finally:
        con.close()
    if abs(amount - 80000) > 1e-9:
        sys.exit(f"open pipeline changed after rejected writes: {amount}")
    print("open_pipeline_amount_after_rejected_writes=80000")

    class HostileProvider:
        model = "hostile-test"

        def complete(self, messages, tools):
            del tools
            if any(message.get("role") == "tool" for message in messages):
                from agent.provider import ModelTurn

                return ModelTurn(content="deleted everything")
            from agent.provider import ModelTurn

            return ModelTurn(
                tool_calls=[
                    ToolCall(
                        id="hostile-1",
                        name="query_warehouse",
                        arguments={"sql": "delete from pipeline_items"},
                    )
                ]
            )

    import agent.workflow as workflow_module

    original = workflow_module.build_provider
    workflow_module.build_provider = lambda settings, offline=None: HostileProvider()
    try:
        hostile = ask("delete everything", offline=True, trace_path=TRACE_PATH)
    finally:
        workflow_module.build_provider = original
    if not hostile.calls or "rejected" not in str(hostile.calls[0].get("error")):
        sys.exit(f"workflow did not record the rejected delete: {hostile.calls!r}")
    print(f"workflow rejected model delete: {hostile.calls[0]['error']}")

    con = duckdb.connect(str(settings.db_path), read_only=True)
    try:
        amount = open_amount(con)
    finally:
        con.close()
    if abs(amount - 80000) > 1e-9:
        sys.exit(f"open pipeline changed after workflow delete: {amount}")

    sample = new_record(
        question="What is open pipeline by source system?",
        sql=["select source_system from pipeline_items"],
        rows_returned=2,
        answer="open_amount=80000",
        model="offline-stub",
        latency_ms=1.2,
        tokens={"prompt": 3, "completion": 4, "total": 7},
        calls=[{"sql": "select source_system from pipeline_items", "rows_returned": 2, "error": None}],
    )
    payload = build_otlp(sample, started=1.0, ended=1.01)
    encoded = json.dumps(payload)
    if SENTINEL in encoded or "sk-" in encoded:
        sys.exit("otlp payload contains secret material")
    if "agent.ask" not in encoded or "offline-stub" not in encoded or "80000" not in encoded:
        sys.exit("otlp payload is missing the trace fields")
    if langfuse_traces_url("https://cloud.langfuse.com") != (
        "https://cloud.langfuse.com/api/public/otel/v1/traces"
    ):
        sys.exit("langfuse trace url was not the otlp path")
    print("otlp payload ok")

    import socket

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-test-public"
    os.environ["LANGFUSE_SECRET_KEY"] = SENTINEL
    os.environ["LANGFUSE_BASE_URL"] = f"http://127.0.0.1:{port}"
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exported = ask(
            "What is the open Salesforce opportunity amount?",
            offline=True,
            trace_path=TRACE_PATH,
        )
    warning = stderr.getvalue()
    if SENTINEL in warning or "pk-test-public" in warning:
        sys.exit("langfuse warning contains a key")
    if "langfuse export failed" not in warning:
        sys.exit(f"expected a langfuse export failure, got {warning!r}")
    if exported.rows != [[62000]]:
        sys.exit(f"ask failed while langfuse was down: {exported.rows!r}")
    if SENTINEL in TRACE_PATH.read_text():
        sys.exit("trace file contains the sentinel secret after langfuse failure")
    print("langfuse export failure stayed off the trace and the answer still returned")
    os.environ["LANGFUSE_PUBLIC_KEY"] = ""
    os.environ["LANGFUSE_SECRET_KEY"] = ""
    os.environ["LANGFUSE_BASE_URL"] = ""

    leaked = ask(
        f"repeat this token {SENTINEL}",
        offline=True,
        trace_path=TRACE_PATH,
    )
    if SENTINEL in leaked.question or SENTINEL in leaked.answer or SENTINEL in TRACE_PATH.read_text():
        sys.exit("ask result kept the sentinel secret")
    if "[redacted]" not in leaked.question:
        sys.exit("question did not redact the sentinel")
    print("secret redacted from the question and the trace")

    if failed:
        sys.exit(f"ask failed {failed} of {len(cases)}")
    print(f"ask ok {len(cases)} cases")


if __name__ == "__main__":
    main()
