"""Synthetic B2B CRM rows. These are not exports and not live API records.

The same company name appears in Salesforce and HubSpot on purpose. That is not
a cross-system identity. Emails are example.com addresses and are not a join key.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

EXTRACTED_AT = datetime(2026, 3, 1, 15, 0, tzinfo=timezone.utc)
UPDATED_AT = EXTRACTED_AT + timedelta(minutes=5)

SALESFORCE = "salesforce"
HUBSPOT = "hubspot"
SAMPLE = "sample"


def _row(source_system: str, source_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "data_origin": "synthetic",
        "source_system": source_system,
        "source_id": source_id,
        "extracted_at": EXTRACTED_AT,
        **fields,
    }


def fixture_tables() -> dict[str, list[dict[str, Any]]]:
    return {
        "salesforce_account": [
            _row(SALESFORCE, "sf-acct-northwind", name="Northwind Lab"),
            _row(SALESFORCE, "sf-acct-harbor", name="Harbor Goods"),
        ],
        "salesforce_contact": [
            _row(
                SALESFORCE,
                "sf-con-quinn",
                account_source_id="sf-acct-northwind",
                full_name="Quinn Adler",
                email="quinn.adler@example.com",
            ),
            _row(
                SALESFORCE,
                "sf-con-riley",
                account_source_id="sf-acct-harbor",
                full_name="Riley Cho",
                email="riley.cho@example.com",
            ),
        ],
        "salesforce_lead": [
            _row(
                SALESFORCE,
                "sf-lead-samir",
                company_name="Paper Kite",
                full_name="Samir Patel",
                email="samir.patel@example.com",
                status="open",
            ),
            _row(
                SALESFORCE,
                "sf-lead-noah",
                company_name="Lumen Yard",
                full_name="Noah Berg",
                email="noah.berg@example.com",
                status="open",
            ),
        ],
        "salesforce_opportunity": [
            _row(
                SALESFORCE,
                "sf-opp-100",
                account_source_id="sf-acct-northwind",
                stage="Qualification",
                amount=40000,
                is_open=True,
            ),
            _row(
                SALESFORCE,
                "sf-opp-101",
                account_source_id="sf-acct-northwind",
                stage="Closed Won",
                amount=15000,
                is_open=False,
            ),
            _row(
                SALESFORCE,
                "sf-opp-102",
                account_source_id="sf-acct-harbor",
                stage="Proposal",
                amount=22000,
                is_open=True,
            ),
        ],
        "salesforce_event": [
            _row(
                SALESFORCE,
                "sf-evt-1",
                related_object="opportunity",
                related_source_id="sf-opp-100",
                subject="Discovery call",
            ),
            _row(
                SALESFORCE,
                "sf-evt-2",
                related_object="account",
                related_source_id="sf-acct-harbor",
                subject="Quarterly review",
            ),
        ],
        "salesforce_task": [
            _row(
                SALESFORCE,
                "sf-task-1",
                related_object="opportunity",
                related_source_id="sf-opp-102",
                subject="Send proposal",
                status="open",
            ),
            _row(
                SALESFORCE,
                "sf-task-2",
                related_object="account",
                related_source_id="sf-acct-northwind",
                subject="Confirm billing contact",
                status="open",
            ),
        ],
        "hubspot_company": [
            _row(HUBSPOT, "hs-co-northwind", name="Northwind Lab"),
            _row(HUBSPOT, "hs-co-pine", name="Pine Relay"),
        ],
        "hubspot_contact": [
            _row(
                HUBSPOT,
                "hs-con-quinn",
                company_source_id="hs-co-northwind",
                full_name="Quinn Adler",
                email="quinn.adler.hs@example.com",
            ),
            _row(
                HUBSPOT,
                "hs-con-mina",
                company_source_id="hs-co-pine",
                full_name="Mina Okada",
                email="mina.okada@example.com",
            ),
        ],
        "hubspot_deal": [
            _row(
                HUBSPOT,
                "hs-deal-10",
                company_source_id="hs-co-northwind",
                stage="appointmentscheduled",
                amount=18000,
                is_open=True,
            ),
            _row(
                HUBSPOT,
                "hs-deal-11",
                company_source_id="hs-co-pine",
                stage="closedwon",
                amount=9000,
                is_open=False,
            ),
        ],
        # Not a HubSpot verified-source resource. Sample activities only.
        "hubspot_activity": [
            _row(
                HUBSPOT,
                "hs-act-1",
                related_object="deal",
                related_source_id="hs-deal-10",
                activity_type="meeting",
            ),
            _row(
                HUBSPOT,
                "hs-act-2",
                related_object="company",
                related_source_id="hs-co-pine",
                activity_type="call",
            ),
        ],
        # Business-defined sample. Not a HubSpot object and not contact creation.
        "signup_event": [
            {
                "data_origin": "synthetic",
                "source_system": SAMPLE,
                "source_id": "sample-signup-1",
                "extracted_at": EXTRACTED_AT,
                "mapping_status": "undecided",
                "hubspot_contact_source_id": "hs-con-quinn",
                "occurred_at": datetime(2026, 1, 12, 16, 0, tzinfo=timezone.utc),
                "channel": "sample_only",
            },
            {
                "data_origin": "synthetic",
                "source_system": SAMPLE,
                "source_id": "sample-signup-2",
                "extracted_at": EXTRACTED_AT,
                "mapping_status": "undecided",
                "hubspot_contact_source_id": None,
                "occurred_at": datetime(2026, 2, 2, 18, 30, tzinfo=timezone.utc),
                "channel": "sample_only",
            },
        ],
    }


def opportunity_stage_update() -> dict[str, list[dict[str, Any]]]:
    """Same entities, with one open opportunity stage changed, for the merge check."""
    tables = fixture_tables()
    matched = 0
    for row in tables["salesforce_opportunity"]:
        if row["source_id"] == "sf-opp-100":
            row["stage"] = "Proposal"
            row["extracted_at"] = UPDATED_AT
            matched += 1
    if matched != 1:
        raise RuntimeError("expected exactly one sf-opp-100 row to update")
    return tables
