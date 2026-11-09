"""Model providers for the ask workflow.

OfflineProvider is deterministic and does not use the network.
OpenRouterProvider calls the OpenAI-compatible chat completions API.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from agent.offline import NO_SCRIPT, render_tool_payload, scripted_sql
from agent.trace import redact

TOOL_NAME = "query_warehouse"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ModelTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens: dict[str, int] | None = None


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def _last_tool_payload(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                return {"error": content}
            if isinstance(parsed, dict):
                return parsed
    return {"error": "missing tool result"}


class OfflineProvider:
    model = "offline-stub"

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        del tools
        if any(message.get("role") == "tool" for message in messages):
            return ModelTurn(content=render_tool_payload(_last_tool_payload(messages)))
        sql = scripted_sql(_last_user_text(messages))
        if sql is None:
            return ModelTurn(content=NO_SCRIPT)
        return ModelTurn(
            tool_calls=[
                ToolCall(id="offline-call-1", name=TOOL_NAME, arguments={"sql": sql})
            ]
        )


class OpenRouterProvider:
    def __init__(self, api_key: str, model: str, base_url: str, timeout_s: float) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        url = self.base_url + "/chat/completions"
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            status = exc.code
            hint = ""
            if status == 401:
                hint = " Check OPENROUTER_KEY."
            elif status == 402:
                hint = " The OpenRouter account could not pay for the request."
            raise RuntimeError(
                redact(f"OpenRouter returned HTTP {status}.{hint} {detail}".strip())
            ) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(redact(f"OpenRouter request failed: {exc.reason}")) from None
        try:
            parsed = json.loads(raw)
            message = parsed["choices"][0]["message"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("OpenRouter returned an unexpected response") from exc
        content = message.get("content")
        if isinstance(content, list):
            content = json.dumps(content)
        elif content is not None and not isinstance(content, str):
            content = str(content)
        tool_calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = function.get("name") or ""
            arguments = function.get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append(
                ToolCall(
                    id=str(call.get("id") or "call"),
                    name=str(name),
                    arguments=arguments,
                )
            )
        usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
        tokens = None
        if usage:
            tokens = {
                "prompt": int(usage.get("prompt_tokens") or 0),
                "completion": int(usage.get("completion_tokens") or 0),
                "total": int(usage.get("total_tokens") or 0),
            }
        return ModelTurn(content=content, tool_calls=tool_calls, tokens=tokens)
