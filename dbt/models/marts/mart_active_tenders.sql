{{ config(materialized='table', schema='marts') }}

/*
  mart_active_tenders — all open tenders (status = 'Open')
  Dataset is historical (2018-2019); date filter omitted so all open records are shown.
  Rows ordered: future/unknown deadlines first, then by deadline ascending.
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

ORDER BY
    CASE WHEN deadline_date IS NULL THEN 0 ELSE 1 END,
    deadline_date DESC
