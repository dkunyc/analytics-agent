select
    customers.customer_id,
    customers.first_name,
    customers.last_name,
    count(orders.order_id) as order_count,
    count(
        case when orders.status = 'completed' then 1 end
    ) as completed_order_count,
    coalesce(sum(orders.successful_revenue), 0) as successful_revenue
from {{ ref('stg_customers') }} as customers
left join {{ ref('fct_orders') }} as orders
    on customers.customer_id = orders.customer_id
group by
    customers.customer_id,
    customers.first_name,
    customers.last_name
