"""Settings for the headless ask command.

Reads agent/config.yml. Environment variables override the model, the provider,
and the trace path. Secrets are read from the environment and are not stored here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from ingestion.config import DB_PATH, ROOT

CONFIG_PATH = Path(__file__).resolve().parent / "config.yml"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class Settings:
    model: str
    base_url: str
    key_env: str
    model_env: str
    provider_env: str
    row_limit: int
    timeout_ms: int
    max_bytes: int
    trace_path: Path
    openrouter_timeout_s: float
    langfuse_timeout_s: float
    db_path: Path

    def env_value(self, name: str) -> str:
        return os.environ.get(name, "").strip()


def _positive_int(block: dict, key: str, default: int) -> int:
    value = block.get(key, default)
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"headless_workflow.{key} must be an integer") from exc
    if number <= 0:
        raise ValueError(f"headless_workflow.{key} must be positive")
    return number


def _positive_float(block: dict, key: str, default: float) -> float:
    value = block.get(key, default)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"headless_workflow.{key} must be a number") from exc
    if number <= 0:
        raise ValueError(f"headless_workflow.{key} must be positive")
    return number


def load_settings() -> Settings:
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    if not isinstance(raw, dict) or not isinstance(raw.get("headless_workflow"), dict):
        raise ValueError(f"{CONFIG_PATH} is missing headless_workflow")
    block = raw["headless_workflow"]
    trace_raw = os.environ.get("AGENT_TRACE_PATH", "").strip() or str(
        block.get("trace_path") or "traces/ask.jsonl"
    )
    trace_path = Path(trace_raw)
    if not trace_path.is_absolute():
        trace_path = ROOT / trace_path
    base_url = (
        os.environ.get("OPENROUTER_BASE_URL", "").strip()
        or str(block.get("openrouter_base_url") or DEFAULT_BASE_URL)
    ).rstrip("/")
    model = str(block.get("model") or "openai/gpt-4o-mini").strip()
    if not model:
        raise ValueError("headless_workflow.model is empty")
    return Settings(
        model=model,
        base_url=base_url,
        key_env=str(block.get("openrouter_key_env") or "OPENROUTER_KEY"),
        model_env=str(block.get("openrouter_model_env") or "OPENROUTER_MODEL"),
        provider_env=str(block.get("provider_env") or "AGENT_PROVIDER"),
        row_limit=_positive_int(block, "sql_row_limit", 200),
        timeout_ms=_positive_int(block, "sql_timeout_ms", 5000),
        max_bytes=_positive_int(block, "sql_max_bytes", 50000),
        trace_path=trace_path,
        openrouter_timeout_s=_positive_float(block, "openrouter_timeout_s", 60),
        langfuse_timeout_s=_positive_float(block, "langfuse_timeout_s", 5),
        db_path=DB_PATH,
    )
