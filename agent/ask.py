"""Command line for one warehouse question.

    python -m agent.ask "What is open pipeline by source system?"

With no OPENROUTER_KEY, or with --offline, this uses the scripted provider.
"""

from __future__ import annotations

import sys

if __name__ == "__main__" and sys.version_info[:2] != (3, 12):
    running = ".".join(str(part) for part in sys.version_info[:3])
    print(
        f"Python {running} cannot run this checkout. Use Python 3.12. "
        "See the Run section in README.md.",
        file=sys.stderr,
    )
    sys.exit(1)

import argparse

from agent.sql_tool import WarehouseError
from agent.workflow import ask


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agent.ask")
    parser.add_argument("question", nargs="+", help="Sales pipeline question")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the scripted provider even if OPENROUTER_KEY is set",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    question = " ".join(args.question).strip()
    try:
        result = ask(question, offline=True if args.offline else None)
    except (WarehouseError, RuntimeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(result.answer)
    print(
        f"model={result.model} latency_ms={result.latency_ms:.1f} "
        f"rows={result.rows_returned} trace={result.trace_path}"
    )
    for statement in result.sql:
        print(f"sql={statement}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
