select
    orders.order_id,
    orders.customer_id,
    orders.ordered_at,
    orders.status,
    count(payments.payment_id) as payment_count,
    coalesce(
        sum(case when payments.status = 'success' then payments.amount end),
        0
    ) as successful_revenue
from {{ ref('stg_orders') }} as orders
left join {{ ref('stg_payments') }} as payments
    on orders.order_id = payments.order_id
group by
    orders.order_id,
    orders.customer_id,
    orders.ordered_at,
    orders.status
