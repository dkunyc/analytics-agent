"""Reject an untested interpreter before imports that need installed packages."""

from __future__ import annotations

import sys

TESTED = (3, 12)


def require_tested_python() -> None:
    if sys.version_info[:2] == TESTED:
        return
    running = ".".join(str(part) for part in sys.version_info[:3])
    sys.exit(
        "\n".join(
            [
                f"Python {running} cannot run this checkout.",
                "The tested interpreter is Python 3.12.",
                "dbt-core==1.11.17 publishes Requires-Python: >=3.10.",
                "Python 3.9.6 is outside that range, so pip reports",
                "No matching distribution found for dbt-core==1.11.17",
                "and duckdb is never installed.",
                "On macOS, python3 is often 3.9.6. Leave the existing .venv in place.",
                "Check `python3.12 --version`, then create .venv312 with that interpreter.",
                "The Run section in README.md has the commands.",
                f"This interpreter: {sys.executable}",
            ]
        )
    )


def require_import(module_name: str):
    require_tested_python()
    try:
        return __import__(module_name)
    except ModuleNotFoundError:
        sys.exit(
            f"{module_name} is not installed for {sys.executable}. "
            "The dependency install did not finish. Use the Python 3.12 "
            "environment in README.md and run "
            "python -m pip install -r requirements.txt"
        )


if __name__ == "__main__":
    require_tested_python()
    print(f"python ok {sys.version.split()[0]} {sys.executable}")
