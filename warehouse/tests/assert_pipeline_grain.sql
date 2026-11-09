select source_system, item_source_id
from {{ ref('pipeline_items') }}
group by source_system, item_source_id
having count(*) > 1
