{{ config(materialized='table', schema='marts') }}

/*
  mart_by_entity — aggregated metrics per procuring entity
  Only includes entities with 2 or more tenders
*/

WITH base AS (
    SELECT * FROM {{ ref('fct_tenders') }}
)

SELECT
    procuring_entity,
    COUNT(*)                                                        AS tender_count,
    COALESCE(SUM(estimated_value_kes), 0)                          AS total_value_kes,
    ROUND(AVG(estimated_value_kes)::NUMERIC, 2)                    AS avg_value_kes,
    COUNT(*) FILTER (WHERE status = 'Open')                        AS open_count,
    COUNT(*) FILTER (WHERE status = 'Closed')                      AS closed_count,
    COUNT(*) FILTER (WHERE status = 'Awarded')                     AS awarded_count,
    COUNT(*) FILTER (WHERE status = 'Cancelled')                   AS cancelled_count,
    MAX(scraped_at)                                                 AS last_seen

FROM base
GROUP BY procuring_entity
HAVING COUNT(*) >= 2
ORDER BY tender_count DESC
