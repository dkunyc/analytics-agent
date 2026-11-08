-- A passing warehouse has a HubSpot contact with no signup and a signup with no contact.
select 'every_hubspot_contact_has_a_signup' as problem
where (
    select count(*)
    from {{ source('crm', 'hubspot_contact') }} as contact
    where not exists (
        select 1
        from {{ source('crm', 'signup_event') }} as signup
        where signup.hubspot_contact_source_id = contact.source_id
    )
) = 0

union all

select 'every_signup_has_a_contact' as problem
where (
    select count(*)
    from {{ source('crm', 'signup_event') }}
    where hubspot_contact_source_id is null
) = 0

union all

select 'signup_labeled_as_hubspot_object' as problem
from {{ source('crm', 'signup_event') }}
where source_system = 'hubspot'
    or mapping_status <> 'undecided'
    or data_origin <> 'synthetic'
