# Architecture

Phase 0 runs a headless warehouse slice on one machine, and `python -m agent.ask` answers one question against it. The V1 frontend direction is LibreChat. That frontend is not installed, configured, or called here.

Checked 2026-11-08 from the public docs and repositories linked below. Nothing in this file was executed except the local Python checks in the root README.

## What runs

Ingestion, transformation, checks, and the question command are separate modules:

- `ingestion/` loads synthetic CRM rows with dlt into DuckDB. It does not call a model or a chat UI.
- `warehouse/` is the dbt project. It reads the dlt schema and builds `pipeline_items`.
- `scripts/smoke.py` runs those steps in order. `scripts/eval_check.py` runs the offline SQL fixture. `scripts/ask_check.py` runs the ask workflow with the scripted provider.
- `python -m agent.ask` answers one question. `agent.workflow.ask` is the same function a later UI can call. The model, or the offline script, may call `query_warehouse`. That tool opens a read-only DuckDB connection, allows one `SELECT` or `WITH`, and enforces a row cap, a byte cap, and a wall-clock interrupt. Writes, DDL, extra statements, and file readers are rejected in that module before execution. The prompt lists stored spellings for low-cardinality columns, read from the warehouse. A null or empty tool result is not reported as an empty pipeline.

There is no chat or browser dependency in that path.

## V1 direction

Planned, not deployed:

- LibreChat is the frontend, self-hosted. Model choice goes through OpenRouter's OpenAI-compatible API so the model can be switched without writing a new client.
- Code execution, if added, is a separate sandbox service. It is not a shell on the operator's computer.
- LLM traces and evals are the job intended for Langfuse.
- Backend request traces are a separate OpenTelemetry export.
- Browser monitoring is a separate frontend signal. The intended meaning is below and is still pending.

Headless jobs stay runnable without LibreChat. A later UI can call `agent.workflow.ask`. This repo does not start that UI.

## Traces are separate

These are different producers. This repo does not connect them, and it does not claim one end-to-end span.

| Producer | What the official docs say it covers | This repo |
| --- | --- | --- |
| Headless workflow | Not a LibreChat feature. The ask command, plus the load and dbt runs. | `agent.ask` appends `traces/ask.jsonl` with the question, SQL, rows returned, answer, model, latency, and tokens when the provider reports them. When `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` are set, the same trace is posted as OTLP/HTTP JSON to `{LANGFUSE_BASE_URL}/api/public/otel/v1/traces` with `x-langfuse-ingestion-version: 4`. The legacy `/api/public/ingestion` trace API is not used. Keys are not written to the file or the error text. dlt telemetry stays off for the smoke check. This is not a LibreChat span. |
| LibreChat Langfuse | GenAI traces and feedback scores for LibreChat conversations. Temporary chats are untraced unless opted in. | No project, no keys, no export. |
| LibreChat backend OpenTelemetry | API, HTTP, MongoDB, Mongoose, Redis, and outbound calls, plus optional log export. Disabled unless `OTEL_TRACING_ENABLED` is set. The docs tell you to use Langfuse for prompt and model traces, not this pipeline. | No collector. |
| LibreChat browser RUM | Browser telemetry to a HyperDX-compatible OTLP collector. `RUM_ENABLED` defaults to false. `RUM_PROVIDER` currently documents `hyperdx` only. | Not enabled and not run. |

LibreChat can send `traceparent` to origins listed in `RUM_TRACE_PROPAGATION_TARGETS`. That is browser-to-LibreChat propagation. It does not include the Python warehouse process. Langfuse conversation traces are not warehouse traces. Do not join them by time and call the result one request.

Langfuse is not a complete real-user-monitoring backend. Frontend errors and page performance need the browser path, or another frontend product. That choice is not made here. LibreChat's documented RUM provider is HyperDX-compatible OTLP, which is a different backend from Langfuse.

Our offline eval files stay local. `scripts/ask_check.py` runs the scripted provider and does not send `agent/evals/ask.json` or `agent/evals/baseline.json` to Langfuse. LibreChat's documented Langfuse use is conversation traces and feedback scores, not loading those files.

## OpenRouter

LibreChat's documented variable is `OPENROUTER_KEY`, used as `apiKey` on a custom endpoint whose `baseURL` is `https://openrouter.ai/api/v1`. `models.fetch: true` asks LibreChat to load OpenRouter's model list. The docs say a `402` comes from OpenRouter when the account cannot pay for the request.

The docs also say not to name the LibreChat key `OPENROUTER_API_KEY`, because that name reroutes LibreChat's built-in OpenAI endpoint as well.

The headless command uses that key name and base URL. It reads `OPENROUTER_KEY` and the model from `OPENROUTER_MODEL` or `agent/config.yml`. It does not read `OPENROUTER_API_KEY`. If the key is unset, or `AGENT_PROVIDER=offline`, the command uses the scripted provider and does not call the network. No key is stored in this repo. The offline check does not call OpenRouter. Zero data retention and a key spend cap are future settings on the OpenRouter account. They are not enabled here and were not verified.

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
- No OpenRouter key, credit, spend cap, or zero-data-retention setting exists here. The headless client can use a key the operator exports. This repo does not contain one, and the offline check does not call OpenRouter.
- No Langfuse project is created here. Headless runs always write a local trace and post it to Langfuse only when the operator sets the three Langfuse variables. There is no shared span with LibreChat.
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
- [Langfuse OpenTelemetry](https://langfuse.com/integrations/native/opentelemetry)
