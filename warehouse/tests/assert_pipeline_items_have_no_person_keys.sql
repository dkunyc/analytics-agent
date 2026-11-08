select columns.column_name
from information_schema.columns as columns
where columns.table_schema = 'main'
    and columns.table_name = 'pipeline_items'
    and columns.column_name in ('email', 'full_name', 'name')
    and (select count(*) from {{ ref('pipeline_items') }}) >= 0
