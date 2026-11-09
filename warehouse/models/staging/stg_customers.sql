select
    cast(customer_id as integer) as customer_id,
    cast(first_name as varchar) as first_name,
    cast(last_name as varchar) as last_name
from {{ ref('raw_customers') }}
