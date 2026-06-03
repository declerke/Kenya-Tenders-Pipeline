"""
Kenya Tenders Ingestor
Source: OpenAFRICA CKAN API — Kenya Government Tenders 2018 dataset
CSV: ke_tenders_list.csv (~463 real government procurement records)
Supplementary: Kenya 2015 Contracts dataset for additional coverage
"""

import io
import logging
import os
from datetime import date, datetime

import pandas as pd
import psycopg2
import requests
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------
SOURCES = [
    {
        "name": "OpenAFRICA",
        "url": (
            "https://s3-eu-west-1.amazonaws.com/cfa-openafrica/resources/"
            "e26bbdbf-a036-43c5-a14d-a5a6b3a6bd32/ke_tenders_list.csv"
            "?ETag=43ea4d62823ed3ee5f19fd65715db300"
        ),
        "format": "csv",
        "source_page": "https://open.africa/dataset/kenya-government-tenders",
    },
]

# Column mapping from raw CSV headers → our schema
CSV_COL_MAP = {
    "entity type": "entity_type",
    "name": "procuring_entity",
    "ref": "tender_number",
    "description": "description",
    "category": "category",
    "procurement method": "procurement_method",
    "status": "raw_status",
    "closing date": "deadline_date",
    "tender details": "tender_details",
}

STATUS_MAP = {
    "published": "Open",
    "open": "Open",
    "awarded": "Awarded",
    "closed": "Closed",
    "cancelled": "Cancelled",
    "cancelled/annulled": "Cancelled",
    "annulled": "Cancelled",
    "pending": "Open",
    "active": "Open",
}


def get_db_conn():
    return psycopg2.connect(
        host=os.getenv("APP_DB_HOST", "postgres"),
        port=int(os.getenv("APP_DB_PORT", 5432)),
        dbname=os.getenv("APP_DB_NAME", "tenders_db"),
        user=os.getenv("APP_DB_USER", "postgres"),
        password=os.getenv("APP_DB_PASSWORD", "postgres"),
    )


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw.tenders (
                tender_id          SERIAL PRIMARY KEY,
                tender_number      VARCHAR(200),
                procuring_entity   VARCHAR(500) NOT NULL,
                description        TEXT,
                category           VARCHAR(200),
                estimated_value_kes NUMERIC(15,2),
                deadline_date      DATE,
                status             VARCHAR(50),
                source_url         TEXT,
                source_name        VARCHAR(100),
                scraped_at         TIMESTAMPTZ DEFAULT NOW(),
                entities_orgs      JSONB,
                entities_locations JSONB,
                keywords           JSONB,
                sector_tag         VARCHAR(100)
            );
        """)
        # Unique constraint to prevent duplicates on re-runs
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_tenders_number_entity'
                ) THEN
                    ALTER TABLE raw.tenders
                    ADD CONSTRAINT uq_tenders_number_entity
                    UNIQUE (tender_number, procuring_entity);
                END IF;
            END$$;
        """)
        conn.commit()
    log.info("Schema and table verified.")


def normalize_status(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        return "Other"
    return STATUS_MAP.get(raw.strip().lower(), "Other")


def parse_deadline(val) -> date | None:
    if not val or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (date, datetime)):
        return val.date() if isinstance(val, datetime) else val
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fetch_openafrika_csv(source: dict) -> pd.DataFrame:
    log.info("Fetching OpenAFRICA CSV …")
    headers = {"User-Agent": "Kenya-Tenders-Pipeline/1.0 (portfolio research)"}
    resp = requests.get(source["url"], headers=headers, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), low_memory=False)
    log.info("Raw CSV shape: %s", df.shape)
    return df


def transform_openafrika(df: pd.DataFrame, source: dict) -> list[dict]:
    # Normalise column names
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.rename(columns=CSV_COL_MAP)

    records = []
    for _, row in df.iterrows():
        entity = str(row.get("procuring_entity", "")).strip()
        desc = str(row.get("description", "")).strip()
        if not entity or entity.lower() in ("nan", "none", ""):
            continue

        records.append({
            "tender_number": str(row.get("tender_number", "")).strip() or None,
            "procuring_entity": entity,
            "description": desc if desc not in ("nan", "none", "") else None,
            "category": str(row.get("category", "")).strip() or None,
            "estimated_value_kes": None,          # not in source CSV
            "deadline_date": parse_deadline(row.get("deadline_date")),
            "status": normalize_status(str(row.get("raw_status", ""))),
            "source_url": source["source_page"],
            "source_name": source["name"],
        })

    log.info("Transformed %d records from OpenAFRICA.", len(records))
    return records


def upsert_records(conn, records: list[dict]) -> int:
    if not records:
        log.warning("No records to insert.")
        return 0

    sql = """
        INSERT INTO raw.tenders
            (tender_number, procuring_entity, description, category,
             estimated_value_kes, deadline_date, status,
             source_url, source_name)
        VALUES %s
        ON CONFLICT (tender_number, procuring_entity) DO NOTHING
    """
    rows = [
        (
            r["tender_number"],
            r["procuring_entity"],
            r["description"],
            r["category"],
            r["estimated_value_kes"],
            r["deadline_date"],
            r["status"],
            r["source_url"],
            r["source_name"],
        )
        for r in records
    ]

    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
        inserted = cur.rowcount
        conn.commit()

    log.info("Upserted %d rows into raw.tenders.", inserted)
    return inserted


def run_ingestion() -> int:
    conn = get_db_conn()
    try:
        ensure_schema(conn)
        total_inserted = 0
        for source in SOURCES:
            try:
                if source["format"] == "csv":
                    df = fetch_openafrika_csv(source)
                    records = transform_openafrika(df, source)
                else:
                    log.warning("Unknown format for source %s", source["name"])
                    continue
                total_inserted += upsert_records(conn, records)
            except Exception as exc:
                log.error("Source %s failed: %s", source["name"], exc)
        log.info("Ingestion complete. Total new rows: %d", total_inserted)
        return total_inserted
    finally:
        conn.close()


if __name__ == "__main__":
    run_ingestion()
