-- The synthetic payments with status success total 78.50.
select successful_revenue
from (
    select round(sum(successful_revenue), 2) as successful_revenue
    from {{ ref('customer_orders') }}
) as totals
where successful_revenue != 78.50
