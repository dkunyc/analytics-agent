select 'opportunity_account' as link, opportunity.source_id
from {{ source('crm', 'salesforce_opportunity') }} as opportunity
left join {{ source('crm', 'salesforce_account') }} as account
    on opportunity.account_source_id = account.source_id
    and account.source_system = 'salesforce'
where account.source_id is null

union all

select 'contact_account' as link, contact.source_id
from {{ source('crm', 'salesforce_contact') }} as contact
left join {{ source('crm', 'salesforce_account') }} as account
    on contact.account_source_id = account.source_id
    and account.source_system = 'salesforce'
where account.source_id is null

union all

select 'deal_company' as link, deal.source_id
from {{ source('crm', 'hubspot_deal') }} as deal
left join {{ source('crm', 'hubspot_company') }} as company
    on deal.company_source_id = company.source_id
    and company.source_system = 'hubspot'
where company.source_id is null

union all

select 'hubspot_contact_company' as link, contact.source_id
from {{ source('crm', 'hubspot_contact') }} as contact
left join {{ source('crm', 'hubspot_company') }} as company
    on contact.company_source_id = company.source_id
    and company.source_system = 'hubspot'
where company.source_id is null

union all

select 'salesforce_event' as link, event.source_id
from {{ source('crm', 'salesforce_event') }} as event
left join {{ source('crm', 'salesforce_opportunity') }} as opportunity
    on event.related_object = 'opportunity'
    and event.related_source_id = opportunity.source_id
left join {{ source('crm', 'salesforce_account') }} as account
    on event.related_object = 'account'
    and event.related_source_id = account.source_id
where opportunity.source_id is null
    and account.source_id is null

union all

select 'salesforce_task' as link, task.source_id
from {{ source('crm', 'salesforce_task') }} as task
left join {{ source('crm', 'salesforce_opportunity') }} as opportunity
    on task.related_object = 'opportunity'
    and task.related_source_id = opportunity.source_id
left join {{ source('crm', 'salesforce_account') }} as account
    on task.related_object = 'account'
    and task.related_source_id = account.source_id
where opportunity.source_id is null
    and account.source_id is null

union all

select 'hubspot_activity' as link, activity.source_id
from {{ source('crm', 'hubspot_activity') }} as activity
left join {{ source('crm', 'hubspot_deal') }} as deal
    on activity.related_object = 'deal'
    and activity.related_source_id = deal.source_id
left join {{ source('crm', 'hubspot_company') }} as company
    on activity.related_object = 'company'
    and activity.related_source_id = company.source_id
where deal.source_id is null
    and company.source_id is null

union all

select 'signup_contact' as link, signup.source_id
from {{ source('crm', 'signup_event') }} as signup
left join {{ source('crm', 'hubspot_contact') }} as contact
    on signup.hubspot_contact_source_id = contact.source_id
    and contact.source_system = 'hubspot'
where signup.hubspot_contact_source_id is not null
    and contact.source_id is null
