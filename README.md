# analytics-agent

Phase 0 is a headless warehouse slice for a personal analytics lab. `python -m agent.ask` answers one question against that warehouse. The V1 frontend direction is LibreChat with OpenRouter. That frontend is documented in [docs/architecture.md](docs/architecture.md) and is not installed here.

The primary data is a synthetic B2B sales pipeline: Salesforce-shaped accounts, contacts, leads, opportunities, events, and tasks, plus HubSpot-shaped companies, contacts, deals, sample activities, and sample signup events. Signup is not a HubSpot object in this repo. Contact creation is not a signup. Records are not matched across systems by name or email.

A smaller synthetic jaffle-style shop (customers, orders, payments) is still built. It is not the dbt Labs jaffle_shop project and it is not a download of upstream data.

## Implemented

- dlt 1.32.0 merges the synthetic CRM fixture into local DuckDB and checks that a rerun does not duplicate `source_id`
- dbt models `pipeline_items` and tests relationships, the open-pipeline amount, and that signups are not contacts
- The jaffle example, its revenue test, and an offline eval fixture
- `python -m agent.ask` answers one question through one read-only SQL tool. With no `OPENROUTER_KEY`, or with `AGENT_PROVIDER=offline`, it uses a scripted provider and does not call the network
- A trace with the question, SQL, rows returned, answer, model, latency, and tokens when the provider reports them. It is appended to gitignored `traces/ask.jsonl`. When `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` are all set, the same trace is posted to Langfuse as OTLP JSON
- GitHub Actions runs the same checks with no secrets
- An intake issue template with a required human-review checkbox

`pipeline_items` open amount on this fixture is 80000 (Salesforce 62000, HubSpot 18000). One sample signup has no HubSpot contact id. Jaffle `successful_revenue` is 78.50: payment amounts whose status is `success`.

## Run on a Mac

Check the interpreter before creating a virtual environment. This checkout was tested with Python 3.12.3. `dbt-core==1.11.17` publishes `Requires-Python: >=3.10` (universal wheel, not yanked). Python 3.9.6 cannot install that pin. pip then stops, so `import duckdb` fails with `ModuleNotFoundError`.

On macOS, `python3` is often 3.9.6 from the system or the Xcode command-line tools. A venv made from it carries that version and an old pip (21.2.4 in the reported `.venv/lib/python3.9` environment). Upgrading pip inside that 3.9 environment does not make the pin installable. Leave `.venv` where it is.

```bash
python3.12 --version
```

Continue only when that command prints Python 3.12.x. If `python3.12` is not found, install Python 3.12 from python.org or Homebrew (`brew install python@3.12`) and check the version again. Do not remove an existing `.venv`. If `.venv312` is already present, pick another new directory name instead of replacing it.

Commands below run from the repo root.

### Offline

No API key.

```bash
python3.12 -m venv .venv312
source .venv312/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/preflight.py
python scripts/smoke.py
python scripts/eval_check.py
python scripts/ask_check.py
python -m agent.ask "What is open pipeline by source system?"
```

`python scripts/ask_check.py` forces the scripted provider. It does not call OpenRouter, even when `OPENROUTER_KEY` is already exported. The scripted questions are `agent/evals/ask.json`. The provider uses each question's SQL, runs it through the warehouse tool, and does not read the expected rows.

`python -m agent.ask` uses that provider when `OPENROUTER_KEY` is unset. Force it when a key is already in the shell:

```bash
python -m agent.ask --offline "What is open pipeline by source system?"
```

`AGENT_PROVIDER=offline` does the same thing. The command prints the answer, `model=offline-stub`, latency, rows returned, the trace path, and the SQL. The trace is one JSON line in `traces/ask.jsonl`. Do not put secrets in the question.

A write is rejected before it runs:

```bash
python -m agent.sql_tool "delete from pipeline_items"
python -m agent.sql_tool "select round(sum(amount), 2) as open_amount from pipeline_items where is_open"
```

The delete command exits non-zero and prints `rejected:`. The select still returns 80000.

`python scripts/preflight.py` exits before the warehouse checks when the interpreter is not 3.12. If a setup still fails, these commands show which interpreter and pip were used:

```bash
python3 --version
python3 -c 'import sys; print(sys.executable)'
.venv/bin/python3 --version
.venv/bin/python3 -m pip --version
python3.12 --version
```

GitHub Actions uses `setup-python` with Python 3.12. On Debian or Ubuntu, `python3 -m venv` can report that ensurepip is unavailable until the distro `python3-venv` package is installed.

`python -m ingestion.load` is the ingestion step alone. `scripts/smoke.py` deletes generated state, runs that load, then `dbt seed` and `dbt build`, and checks both amounts.

`warehouse/target/warehouse.duckdb` is generated and gitignored. Do not commit it. The warehouse checks need no environment variables. `.env.example` lists names only.

Source coverage and the links behind it are in [ingestion/README.md](ingestion/README.md).

### OpenRouter

Use the same `.venv312`. Export the key in the shell. Do not commit it.

```bash
source .venv312/bin/activate
export OPENROUTER_KEY="paste the key here"
export OPENROUTER_MODEL="openai/gpt-4o-mini"
python -m agent.ask "What is open pipeline by source system?"
```

`OPENROUTER_MODEL` is optional. When it is unset, the model is `headless_workflow.model` in `agent/config.yml` (`openai/gpt-4o-mini` in this checkout). The client posts to `https://openrouter.ai/api/v1/chat/completions`. `model=` in the output is that model name, and the trace includes token counts when OpenRouter returns them.

This command does not read `OPENROUTER_API_KEY`. LibreChat documents that name as also rerouting its built-in OpenAI endpoint.

### Langfuse

Use the same `.venv312`. Set all three variables. `LANGFUSE_BASE_URL` is the origin only, such as `https://cloud.langfuse.com` or a self-hosted host.

```bash
source .venv312/bin/activate
export LANGFUSE_PUBLIC_KEY="paste the public key here"
export LANGFUSE_SECRET_KEY="paste the secret key here"
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"
python -m agent.ask "What is open pipeline by source system?"
```

The command still appends `traces/ask.jsonl`. It also POSTs an OTLP JSON trace to `$LANGFUSE_BASE_URL/api/public/otel/v1/traces` with the header `x-langfuse-ingestion-version: 4`. If that export fails, the answer is still printed and the error goes to stderr without the keys. Unset the three variables to keep the trace on disk only.

A later UI can call `agent.workflow.ask` instead of the command. That function does not import a chat frontend.

## Planned, not running

Details, licenses, and blockers are in [docs/architecture.md](docs/architecture.md).

- **LibreChat.** V1 model switching in the UI is still a LibreChat custom endpoint. No LibreChat process is in this repo. The headless client is separate and already reads `OPENROUTER_KEY`. Zero data retention and a key spend cap are future OpenRouter account settings, not enabled and not verified.
- **Code interpreter.** A separate Apache-2.0 sandbox service, not access to the operator's computer. Not deployed.
- **Traces.** The ask command writes its own trace. LibreChat Langfuse conversation traces, LibreChat backend OpenTelemetry, and LibreChat browser RUM are separate. None of those are connected to the ask trace. There is no end-to-end span.
- **Langfuse.** Used for the ask trace when the three variables above are set. Not a browser real-user-monitoring backend. This repo does not create a Langfuse project.
- **Browser monitoring.** Intended, and still pending a running frontend: page errors, performance, and correlation with that frontend's request traces. Not browser automation and not session replay. Prompt, contact, replay, and secret capture stay off in that intended default. Not verified.
- **MCP tools.** Not in this repo.
- **Live Salesforce and HubSpot.** Auth, limits, incremental reads, and deletes wait for an explicit sandbox. See [ingestion/README.md](ingestion/README.md).
- **Question review.** Record categories, outcomes, errors, and latency or cost when a trace exists; turn repeated failures into eval cases after human review. The ask command now records a local trace. Copying a failure into an eval fixture still waits for that review.

`agent/prompts/analyst.md` is the headless system prompt. `agent/config.yml` selects the model and the SQL limits. The offline baseline is `agent/evals/baseline.json`. The ask cases are `agent/evals/ask.json`.
