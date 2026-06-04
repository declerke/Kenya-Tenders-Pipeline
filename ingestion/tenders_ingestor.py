"""
Kenya Tenders Ingestor
Source: TendersKenya.co.ke — live Kenya government & NGO procurement listings
Scrapes listing pages (requests + BeautifulSoup), no login required.
"""

import logging
import os
import time
from datetime import date, datetime

import psycopg2
import requests
from bs4 import BeautifulSoup
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://www.tenderskenya.co.ke"
LISTING_URL = BASE_URL + "/document-type/tenders?page={page}"
PAGES_TO_SCRAPE = 20
REQUEST_DELAY = 1.0  # seconds between page requests
SOURCE_NAME = "TendersKenya"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
                tender_id           SERIAL PRIMARY KEY,
                tender_number       VARCHAR(200),
                procuring_entity    VARCHAR(500) NOT NULL,
                description         TEXT,
                category            VARCHAR(200),
                estimated_value_kes NUMERIC(15,2),
                deadline_date       DATE,
                status              VARCHAR(50),
                source_url          TEXT,
                source_name         VARCHAR(100),
                scraped_at          TIMESTAMPTZ DEFAULT NOW(),
                entities_orgs       JSONB,
                entities_locations  JSONB,
                keywords            JSONB,
                sector_tag          VARCHAR(100)
            );
        """)
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


def parse_date(text: str) -> date | None:
    if not text:
        return None
    text = text.strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def derive_status(close_date: date | None) -> str:
    if close_date is None:
        return "Open"
    return "Open" if close_date >= date.today() else "Closed"


def slug_from_url(url: str) -> str:
    """Extract the slug portion from a tenderskenya.co.ke tender URL."""
    return url.rstrip("/").split("/tender/")[-1] if "/tender/" in url else url


def scrape_page(page: int) -> list[dict]:
    url = LISTING_URL.format(page=page)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("Failed to fetch page %d: %s", page, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("div.card.h-100")
    records = []

    for card in cards:
        title_a = card.select_one("a.tenderbox_title")
        if not title_a:
            continue

        title = title_a.get_text(strip=True)
        tender_url = title_a.get("href", "")
        if not tender_url.startswith("http"):
            tender_url = BASE_URL + tender_url
        slug = slug_from_url(tender_url)

        # Footer contains company, type, dates
        footer_a = card.select_one(".card-footer.tenderbox_footer a.d-block")
        if not footer_a:
            continue

        paragraphs = footer_a.find_all("p", recursive=False)

        # Company: first orange span in the first <p>
        company = "Not Disclosed"
        if paragraphs:
            span = paragraphs[0].find("span", class_="text-orange-1")
            if span:
                raw = span.get_text(strip=True)
                if raw and "login" not in raw.lower():
                    company = raw

        # Type: second <p>'s orange span
        tender_type = None
        if len(paragraphs) > 1:
            span = paragraphs[1].find("span", class_="text-orange-1")
            if span:
                tender_type = span.get_text(strip=True) or None

        # Dates: search all <p> for "Open:" and "Close:" text
        open_date = close_date = None
        for p in paragraphs:
            text = p.get_text(" ", strip=True)
            if text.startswith("Open:"):
                date_span = p.find("span", class_=lambda c: c != "typcn" if c else True)
                if date_span:
                    open_date = parse_date(date_span.get_text(strip=True))
            elif text.startswith("Close:"):
                date_span = p.find_all("span")
                # Last span is the date value
                for s in reversed(date_span):
                    val = s.get_text(strip=True)
                    if val and not val.startswith("typcn"):
                        close_date = parse_date(val)
                        break

        if not title or not slug:
            continue

        records.append({
            "tender_number": slug[:200],
            "procuring_entity": company[:500],
            "description": title,
            "category": tender_type,
            "estimated_value_kes": None,
            "deadline_date": close_date,
            "status": derive_status(close_date),
            "source_url": tender_url,
            "source_name": SOURCE_NAME,
        })

    log.info("Page %d: parsed %d cards → %d valid records", page, len(cards), len(records))
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

    log.info("Upserted %d new rows into raw.tenders.", inserted)
    return inserted


def run_ingestion() -> int:
    conn = get_db_conn()
    try:
        ensure_schema(conn)

        # One-time cleanup: remove legacy OpenAFRICA historical data
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raw.tenders WHERE source_name = 'OpenAFRICA'")
            deleted = cur.rowcount
            conn.commit()
        if deleted:
            log.info("Removed %d legacy OpenAFRICA rows.", deleted)

        all_records: list[dict] = []
        for page in range(1, PAGES_TO_SCRAPE + 1):
            records = scrape_page(page)
            if not records:
                log.info("Page %d returned no records — stopping early.", page)
                break
            all_records.extend(records)
            if page < PAGES_TO_SCRAPE:
                time.sleep(REQUEST_DELAY)

        log.info("Scraped %d total records across %d pages.", len(all_records), min(page, PAGES_TO_SCRAPE))

        total_inserted = upsert_records(conn, all_records)
        log.info("Ingestion complete. Total new rows: %d", total_inserted)
        return total_inserted
    finally:
        conn.close()


if __name__ == "__main__":
    run_ingestion()
