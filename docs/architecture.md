# Architecture

Phase 0 runs a headless warehouse slice on one machine. The V1 frontend direction is LibreChat. That frontend is not installed, configured, or called here.

Checked 2026-11-08 from the public docs and repositories linked below. Nothing in this file was executed except the local Python checks in the root README.

## What runs

Ingestion, transformation, and checks are separate modules:

- `ingestion/` loads synthetic CRM rows with dlt into DuckDB. It does not call a model or a chat UI.
- `warehouse/` is the dbt project. It reads the dlt schema and builds `pipeline_items`.
- `scripts/smoke.py` runs those steps in order. `agent/` holds placeholders and an offline eval fixture. No workflow runner dispatches them.

There is no chat or browser dependency in that path.

## V1 direction

Planned, not deployed:

- LibreChat is the frontend, self-hosted. Model choice goes through OpenRouter's OpenAI-compatible API so the model can be switched without writing a new client.
- Code execution, if added, is a separate sandbox service. It is not a shell on the operator's computer.
- LLM traces and evals are the job intended for Langfuse.
- Backend request traces are a separate OpenTelemetry export.
- Browser monitoring is a separate frontend signal. The intended meaning is below and is still pending.

Headless jobs stay runnable without LibreChat. A later UI may call them. This repo does not define that call.

## Traces are separate

These are different producers. This repo does not connect them, and it does not claim one end-to-end span.

| Producer | What the official docs say it covers | This repo |
| --- | --- | --- |
| Headless workflow | Not a LibreChat feature. Our loads and dbt runs. | No OpenTelemetry SDK. dlt telemetry is turned off for the smoke check. |
| LibreChat Langfuse | GenAI traces and feedback scores for LibreChat conversations. Temporary chats are untraced unless opted in. | No project, no keys, no export. |
| LibreChat backend OpenTelemetry | API, HTTP, MongoDB, Mongoose, Redis, and outbound calls, plus optional log export. Disabled unless `OTEL_TRACING_ENABLED` is set. The docs tell you to use Langfuse for prompt and model traces, not this pipeline. | No collector. |
| LibreChat browser RUM | Browser telemetry to a HyperDX-compatible OTLP collector. `RUM_ENABLED` defaults to false. `RUM_PROVIDER` currently documents `hyperdx` only. | Not enabled and not run. |

LibreChat can send `traceparent` to origins listed in `RUM_TRACE_PROPAGATION_TARGETS`. That is browser-to-LibreChat propagation. It does not include the Python warehouse process. Langfuse conversation traces are not warehouse traces. Do not join them by time and call the result one request.

Langfuse is not a complete real-user-monitoring backend. Frontend errors and page performance need the browser path, or another frontend product. That choice is not made here. LibreChat's documented RUM provider is HyperDX-compatible OTLP, which is a different backend from Langfuse.

Our offline eval file stays local. LibreChat's documented Langfuse use is conversation traces and feedback scores, not loading `agent/evals/baseline.json`.

## OpenRouter

LibreChat's documented variable is `OPENROUTER_KEY`, used as `apiKey` on a custom endpoint whose `baseURL` is `https://openrouter.ai/api/v1`. `models.fetch: true` asks LibreChat to load OpenRouter's model list. The docs say a `402` comes from OpenRouter when the account cannot pay for the request.

The docs also say not to name the LibreChat key `OPENROUTER_API_KEY`, because that name reroutes LibreChat's built-in OpenAI endpoint as well.

No key is set. Zero data retention and a key spend cap are future settings on the OpenRouter account. They are not enabled here and were not verified.

## Code interpreter

LibreChat does not execute code inside the chat process. The documented service is [LibreChat-AI/code-interpreter](https://github.com/LibreChat-AI/code-interpreter) (the older `ClickHouse/code-interpreter` URL redirects there), Apache-2.0, self-hosted. LibreChat itself is MIT and self-hosted: [LibreChat-AI/LibreChat](https://github.com/LibreChat-AI/LibreChat). The public LibreChat demo is a different service with its own terms. This lab does not use that demo.

The code-interpreter README describes an API, workers, a file server, and a tool-call server, with Redis queues and S3-compatible storage. Workers isolate code with NsJail, or with a libkrun microVM when KVM is enabled. The LibreChat docs say memory, CPU, upload size, quotas, and network access are set on that deployment. `LOCAL_MODE=true` is an authentication-free mode and must not be exposed. Outside local mode, the current open-source service expects JWT authentication. LibreChat points at it with `LIBRECHAT_CODE_BASEURL`.

NsJail-only mode shares the host kernel. The service README calls that suitable for local development, not for untrusted code. MicroVM mode is the stronger option and needs KVM. Neither mode is access to a person's Mac, home directory, or credentials. The remote-bridge and stateful profiles are additional deployment choices and are not part of this lab.

This repository does not install Docker images, Helm charts, Redis, object storage, or the code API. Sandbox execution remains a future adapter with a constrained service boundary.

## Browser monitoring

The lab's intended meaning, still pending confirmation against a running frontend, is:

- frontend errors
- page performance
- correlation with the frontend's own request traces

It does not mean browser automation, a recording of the desktop, or session replay.

LibreChat documents a RUM feature that is off by default. When a page is sampled it describes a `page-load-diagnostics` event (navigation timing and a normalized route, not a raw conversation id) plus lifecycle and route-change events. These switches are separate, default off, and the docs say the first three can collect prompts, responses, or payloads:

- `RUM_SESSION_REPLAY_ENABLED` (default false)
- `RUM_CONSOLE_CAPTURE` (default false)
- `RUM_ADVANCED_NETWORK_CAPTURE` (default false)

`RUM_CLIENT_LOGS` (client warnings and errors, proxy mode only) also defaults to false. Whether the default-off RUM feature, once enabled with those switches left off, actually covers frontend errors is not verified. This lab's intended default is to leave session replay, console capture, and payload capture off, and not to record typed prompts, contacts, or secrets. That policy is not enforced by software in this repo because the frontend is not running.

## Blockers

- No LibreChat process, compose file, or database is in this repo.
- No OpenRouter key, credit, spend cap, or zero-data-retention setting exists here.
- No Langfuse project and no OpenTelemetry collector. Headless runs emit no spans.
- No HyperDX or other RUM collector. Browser behavior was not observed.
- Code interpreter is a separate deploy with its own auth, Redis, and object storage. It is not standing.
- Trace correlation across the headless jobs and LibreChat would be new work. It is not implemented, so there is no end-to-end trace to show.

## Sources

- [LibreChat OpenRouter](https://www.librechat.ai/docs/configuration/librechat_yaml/ai_endpoints/openrouter)
- [LibreChat environment variables](https://www.librechat.ai/docs/configuration/dotenv) (OpenRouter key name, Langfuse, backend OpenTelemetry, browser RUM)
- [LibreChat Langfuse tracing](https://www.librechat.ai/docs/configuration/langfuse)
- [LibreChat logging](https://www.librechat.ai/docs/configuration/logging)
- [LibreChat code interpreter configuration](https://www.librechat.ai/docs/configuration/tools/code_interpreter)
- [Code interpreter repository](https://github.com/LibreChat-AI/code-interpreter)
- [LibreChat repository](https://github.com/LibreChat-AI/LibreChat)
