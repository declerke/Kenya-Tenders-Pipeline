{{ config(materialized='table', schema='marts') }}

/*
  mart_active_tenders — open tenders with future or unknown deadlines
*/

WITH base AS (
    SELECT * FROM {{ ref('fct_tenders') }}
)

SELECT
    tender_id,
    tender_number,
    procuring_entity,
    description,
    category,
    estimated_value_kes,
    deadline_date,
    days_to_deadline,
    sector_tag,
    source_url,
    source_name

FROM base
WHERE
    status = 'Open'
    AND (deadline_date IS NULL OR deadline_date >= CURRENT_DATE)

ORDER BY
    CASE WHEN deadline_date IS NULL THEN 1 ELSE 0 END,
    deadline_date ASC
