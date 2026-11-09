select
    source_system,
    source_id,
    company_source_id,
    stage,
    cast(amount as double) as amount,
    cast(is_open as boolean) as is_open,
    extracted_at
from {{ source('crm', 'hubspot_deal') }}
