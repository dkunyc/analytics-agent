# analytics-agent

Phase 0 is a headless warehouse slice for a personal analytics lab. It runs on one machine with no API key. The V1 frontend direction is LibreChat with OpenRouter. That stack is documented in [docs/architecture.md](docs/architecture.md) and is not installed here.

The primary data is a synthetic B2B sales pipeline: Salesforce-shaped accounts, contacts, leads, opportunities, events, and tasks, plus HubSpot-shaped companies, contacts, deals, sample activities, and sample signup events. Signup is not a HubSpot object in this repo. Contact creation is not a signup. Records are not matched across systems by name or email.

A smaller synthetic jaffle-style shop (customers, orders, payments) is still built. It is not the dbt Labs jaffle_shop project and it is not a download of upstream data.

## Implemented

- dlt 1.32.0 merges the synthetic CRM fixture into local DuckDB and checks that a rerun does not duplicate `source_id`
- dbt models `pipeline_items` and tests relationships, the open-pipeline amount, and that signups are not contacts
- The jaffle example, its revenue test, and an offline eval fixture (no model call)
- GitHub Actions runs the same checks with no secrets
- An intake issue template with a required human-review checkbox

`pipeline_items` open amount on this fixture is 80000 (Salesforce 62000, HubSpot 18000). Jaffle `successful_revenue` is 78.50: payment amounts whose status is `success`.

## Run

Verified with Python 3.12. If `python3 -m venv` reports that ensurepip is unavailable, install the distro `python3-venv` package and create the environment again. GitHub Actions uses `setup-python`, which already includes it.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/smoke.py
python scripts/eval_check.py
```

`python -m ingestion.load` is the ingestion step alone. `scripts/smoke.py` deletes generated state, runs that load, then `dbt seed` and `dbt build`, and checks both amounts.

`warehouse/target/warehouse.duckdb` is generated and gitignored. Do not commit it. No environment variables are required. `.env.example` lists names reserved for later, with no values.

Source coverage and the links behind it are in [ingestion/README.md](ingestion/README.md).

## Planned, not running

Details, licenses, and blockers are in [docs/architecture.md](docs/architecture.md).

- **LibreChat and OpenRouter.** V1 model switching is a LibreChat custom endpoint. The documented key name is `OPENROUTER_KEY`. No LibreChat process and no key are in this repo. Zero data retention and a key spend cap are future OpenRouter account settings, not enabled and not verified.
- **Code interpreter.** A separate Apache-2.0 sandbox service, not access to the operator's computer. Not deployed.
- **Traces.** Headless jobs, LibreChat Langfuse conversation traces, LibreChat backend OpenTelemetry, and LibreChat browser RUM are separate. None are connected. There is no end-to-end span.
- **Langfuse.** Intended for LLM traces and, later, evals. Not installed. It is not a browser real-user-monitoring backend.
- **Browser monitoring.** Intended, and still pending a running frontend: page errors, performance, and correlation with that frontend's request traces. Not browser automation and not session replay. Prompt, contact, replay, and secret capture stay off in that intended default. Not verified.
- **MCP tools.** Not in this repo.
- **Live Salesforce and HubSpot.** Auth, limits, incremental reads, and deletes wait for an explicit sandbox. See [ingestion/README.md](ingestion/README.md).
- **Question review.** Record categories, outcomes, errors, and latency or cost when a trace exists; turn repeated failures into eval cases after human review. That loop is not collected telemetry yet.

`agent/prompts/analyst.md` and `agent/config.yml` are placeholders. The offline baseline is `agent/evals/baseline.json`.
