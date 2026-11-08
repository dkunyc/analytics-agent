"""Paths shared by the dlt load and the offline smoke check."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "warehouse" / "target" / "warehouse.duckdb"
PIPELINES_DIR = ROOT / "ingestion" / ".dlt_state"
DATASET_NAME = "crm_raw"
PIPELINE_NAME = "b2b_crm"

# Open Salesforce opportunities plus the open HubSpot deal in the synthetic fixture.
# Kept in sync with warehouse/tests/assert_open_pipeline_amount.sql and the eval fixture.
OPEN_PIPELINE_AMOUNT = 80000
