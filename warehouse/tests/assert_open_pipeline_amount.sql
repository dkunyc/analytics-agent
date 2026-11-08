-- Open pipeline is the synthetic open opportunities plus the open deal.
select *
from (
    select
        round(sum(case when is_open then amount else 0 end), 2) as open_amount,
        round(
            sum(case when is_open and source_system = 'salesforce' then amount else 0 end),
            2
        ) as salesforce_open,
        round(
            sum(case when is_open and source_system = 'hubspot' then amount else 0 end),
            2
        ) as hubspot_open,
        count(*) as item_count
    from {{ ref('pipeline_items') }}
) as totals
where open_amount != 80000
    or salesforce_open != 62000
    or hubspot_open != 18000
    or item_count != 5
