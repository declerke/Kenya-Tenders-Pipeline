{{ config(materialized='view', schema='staging') }}

/*
  stg_tenders — clean and standardise raw.tenders
  - Cast types
  - Normalise status to Open/Closed/Awarded/Cancelled/Other
  - Drop rows missing both procuring_entity and description
*/

WITH source AS (
    SELECT *
    FROM raw.tenders
),

cleaned AS (
    SELECT
        tender_id,

        NULLIF(TRIM(tender_number), '')                          AS tender_number,
        TRIM(procuring_entity)                                   AS procuring_entity,
        NULLIF(TRIM(COALESCE(description, '')), '')              AS description,
        NULLIF(TRIM(COALESCE(category, '')), '')                 AS category,
        estimated_value_kes,
        deadline_date,

        CASE UPPER(TRIM(COALESCE(status, '')))
            WHEN 'OPEN'        THEN 'Open'
            WHEN 'PUBLISHED'   THEN 'Open'
            WHEN 'ACTIVE'      THEN 'Open'
            WHEN 'CLOSED'      THEN 'Closed'
            WHEN 'EXPIRED'     THEN 'Closed'
            WHEN 'AWARDED'     THEN 'Awarded'
            WHEN 'CANCELLED'   THEN 'Cancelled'
            WHEN 'ANNULLED'    THEN 'Cancelled'
            WHEN 'OTHER'       THEN 'Other'
            ELSE               'Other'
        END                                                      AS status,

        source_url,
        source_name,
        scraped_at,
        entities_orgs,
        entities_locations,
        keywords,
        COALESCE(sector_tag, 'Other')                           AS sector_tag

    FROM source
    WHERE
        -- Must have at least one of procuring_entity or description
        NOT (
            (procuring_entity IS NULL OR TRIM(procuring_entity) = '')
            AND
            (description IS NULL OR TRIM(description) = '')
        )
)

SELECT * FROM cleaned
