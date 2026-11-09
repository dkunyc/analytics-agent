# Ingestion

`python -m ingestion.load` uses real [dlt](https://github.com/dlt-hub/dlt) 1.32.0 to merge the synthetic fixture into `warehouse/target/warehouse.duckdb`, schema `crm_raw`. The merge key is `source_system` plus `source_id`. DuckDB is a supported dlt destination for `merge`. A second load of the same ids does not add rows; a later load can replace a column on the same id.

This package does not import the Salesforce or HubSpot verified sources and does not send credentials. Live auth, API limits, incremental cursors, and deletion behavior are not claimed from this run.

The fixture is synthetic. `Northwind Lab` appears in both systems on purpose and is not a shared identity. Emails use `example.com` and are not a join key. `signup_event.source_system` is `sample`, `mapping_status` is `undecided`, and one signup has no contact id. One HubSpot contact has no signup.

## Verified sources, not executed

Checked against [dlt-hub/verified-sources](https://github.com/dlt-hub/verified-sources) commit `1ae1f65725af5daa3f1ce274db999d2ce662dd4e` (2026-11-06) and the docs pages linked below. This repo does not vendor those connectors.

### Salesforce

Docs: [Salesforce verified source](https://dlthub.com/docs/dlt-ecosystem/verified-sources/salesforce).

`salesforce_source` lists `account`, `contact`, `lead`, `opportunity`, `task`, and `event`, plus other sObjects this lab does not model. The documented default picks a cursor per sObject. `SystemModstamp` and `LastModifiedDate` use `merge` on `Id`. With `include_deleted=True` (the documented default), `IsDeleted` is the hard-delete column. The same page documents gaps: records purged from the recycle bin between runs can remain in the destination, and some formula or sharing changes do not move `SystemModstamp`.

Those objects are represented here only as synthetic tables. The incremental SOQL, Bulk API, and delete propagation were not run.

### HubSpot

Docs: [HubSpot verified source](https://dlthub.com/docs/dlt-ecosystem/verified-sources/hubspot).

That page's companies example still shows `write_disposition="replace"`. The source file at the commit above sets `write_disposition="merge"` and `primary_key="id"` for every object in `ALL_OBJECTS`. `crm_objects` pages the CRM endpoint; that function does not take an incremental cursor. `hubspot_events_for_objects` is a separate resource: web analytics events, `write_disposition="append"`, incremental on `occurredAt`.

`settings.py` at that commit endpoints: contact, company, deal, product, ticket, quote, and owner. Also in the source: deal and ticket pipelines (`merge`) and a properties resource (`replace`). Property history is `append` and only when `include_history=True`.

Not in that endpoint map: engagements or other CRM activities, form submissions, custom behavioral events, and a signup object. `hubspot_activity` in this repo is a synthetic stand-in, not a load from that connector. Mapping a real signup to a form submission, a custom event, contact creation, or something else is undecided. Contact creation is not treated as a signup.

Official docs and the commit disagree on replace versus merge for CRM objects. A sandbox setup has to pin a connector revision instead of assuming either description.

## Deferred

- Installing or running `dlt init salesforce` or `dlt init hubspot`
- Credentials, `secrets.toml`, and external writes
- HubSpot activity, form, and signup mappings
- Salesforce delete and incremental edge cases listed in the Salesforce doc
