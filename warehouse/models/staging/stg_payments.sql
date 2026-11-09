select
    cast(payment_id as integer) as payment_id,
    cast(order_id as integer) as order_id,
    cast(method as varchar) as method,
    cast(amount as double) as amount,
    cast(status as varchar) as status
from {{ ref('raw_payments') }}
