-- Sales items only. Email and person names stay in the source tables.
-- organization_source_id is meaningful only together with source_system.

select
    source_system,
    source_id as item_source_id,
    account_source_id as organization_source_id,
    stage,
    amount,
    is_open,
    extracted_at
from {{ ref('stg_salesforce_opportunity') }}

union all

select
    source_system,
    source_id as item_source_id,
    company_source_id as organization_source_id,
    stage,
    amount,
    is_open,
    extracted_at
from {{ ref('stg_hubspot_deal') }}
