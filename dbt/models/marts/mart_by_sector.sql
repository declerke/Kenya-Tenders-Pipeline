{{ config(materialized='table', schema='marts') }}

/*
  mart_by_sector — aggregated metrics per NLP-classified sector
*/

WITH base AS (
    SELECT * FROM {{ ref('fct_tenders') }}
)

SELECT
    COALESCE(sector_tag, 'Other')                                  AS sector_tag,
    COUNT(*)                                                        AS tender_count,
    COALESCE(SUM(estimated_value_kes), 0)                          AS total_value_kes,
    ROUND(AVG(estimated_value_kes)::NUMERIC, 2)                    AS avg_value_kes,
    COUNT(*) FILTER (WHERE status = 'Open')                        AS open_count,
    COUNT(*) FILTER (WHERE status = 'Closed')                      AS closed_count,
    COUNT(*) FILTER (WHERE status = 'Awarded')                     AS awarded_count

FROM base
GROUP BY sector_tag
ORDER BY tender_count DESC
