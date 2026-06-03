{{ config(materialized='table', schema='marts') }}

/*
  fct_tenders — enriched fact table with derived analytics columns
*/

WITH stg AS (
    SELECT * FROM {{ ref('stg_tenders') }}
)

SELECT
    tender_id,
    tender_number,
    procuring_entity,
    description,
    category,
    estimated_value_kes,
    deadline_date,
    status,
    source_url,
    source_name,
    scraped_at,
    entities_orgs,
    entities_locations,
    keywords,
    sector_tag,

    -- Days until deadline (negative = already past)
    CASE
        WHEN deadline_date IS NOT NULL
        THEN (deadline_date - CURRENT_DATE)
        ELSE NULL
    END                                                AS days_to_deadline,

    -- High-value flag: over KES 10 million
    CASE
        WHEN estimated_value_kes > 10000000 THEN TRUE
        ELSE FALSE
    END                                                AS is_high_value

FROM stg
