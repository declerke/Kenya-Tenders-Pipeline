"""
NLP Enricher — spaCy en_core_web_sm
Applies Named Entity Recognition, keyword extraction, and rule-based sector
classification to all raw.tenders rows that have not yet been enriched.
"""

import json
import logging
import os

import psycopg2
import spacy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sector classification rules (case-insensitive substring matching)
# ---------------------------------------------------------------------------
SECTOR_RULES: dict[str, list[str]] = {
    "IT/Software": [
        "software", "system", "ict", "digital", "database",
        "network", "server", "website", "application", "computer",
        "it ", "information technology", "cyber", "e-government",
    ],
    "Infrastructure": [
        "road", "construction", "building", "civil", "bridge",
        "water", "sanitation", "renovation", "works", "contractor",
        "drainage", "flood", "street", "power", "solar", "electricity",
        "highmast", "dam", "irrigation", "borehole",
    ],
    "Healthcare": [
        "medical", "health", "hospital", "pharmacy", "equipment",
        "clinical", "laboratory", "reagent", "drug", "medicine",
        "ambulance", "vaccine", "therapeutic", "surgical", "iv fluid",
    ],
    "Education": [
        "school", "university", "training", "education", "curriculum",
        "learning", "college", "academic", "library", "research",
        "scholarship", "bursary",
    ],
    "Security": [
        "security", "guard", "surveillance", "cctv", "access control",
        "alarm", "police", "detective", "manned", "patrol",
    ],
    "Consulting": [
        "consultancy", "advisory", "audit", "assessment", "survey",
        "feasibility", "evaluation", "review", "study", "baseline",
        "environmental", "impact assessment",
    ],
    "Supplies": [
        "supply", "stationery", "printing", "fuel", "uniforms",
        "food", "cleaning", "provision", "catering", "consumables",
        "furniture", "toner", "cartridge", "tyres", "lubricants",
        "cereals", "grocery",
    ],
}


def classify_sector(text: str) -> str:
    if not text:
        return "Other"
    lower = text.lower()
    for sector, keywords in SECTOR_RULES.items():
        if any(kw in lower for kw in keywords):
            return sector
    return "Other"


def extract_nlp_features(nlp, text: str) -> dict:
    """Run spaCy pipeline and return enrichment dict."""
    if not text or not text.strip():
        return {
            "entities_orgs": [],
            "entities_locations": [],
            "entities_money": [],
            "keywords": [],
        }

    doc = nlp(text[:1000])  # cap at 1000 chars for performance

    orgs = list({ent.text.strip() for ent in doc.ents if ent.label_ == "ORG"})
    locs = list({ent.text.strip() for ent in doc.ents if ent.label_ in ("GPE", "LOC")})
    money = list({ent.text.strip() for ent in doc.ents if ent.label_ == "MONEY"})

    # Top-5 content keywords: nouns + proper nouns, no stopwords, no short tokens
    kw_candidates = [
        token.lemma_.lower()
        for token in doc
        if token.pos_ in ("NOUN", "PROPN")
        and not token.is_stop
        and not token.is_punct
        and len(token.text) > 2
    ]
    # Deduplicate preserving order, then take first 5
    seen = set()
    keywords = []
    for kw in kw_candidates:
        if kw not in seen:
            seen.add(kw)
            keywords.append(kw)
        if len(keywords) == 5:
            break

    return {
        "entities_orgs": orgs,
        "entities_locations": locs,
        "entities_money": money,
        "keywords": keywords,
    }


def get_db_conn():
    return psycopg2.connect(
        host=os.getenv("APP_DB_HOST", "postgres"),
        port=int(os.getenv("APP_DB_PORT", 5432)),
        dbname=os.getenv("APP_DB_NAME", "tenders_db"),
        user=os.getenv("APP_DB_USER", "postgres"),
        password=os.getenv("APP_DB_PASSWORD", "postgres"),
    )


def run_enrichment() -> int:
    log.info("Loading spaCy model en_core_web_sm …")
    nlp = spacy.load("en_core_web_sm")

    conn = get_db_conn()
    enriched_count = 0

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tender_id, description, category
                FROM raw.tenders
                WHERE sector_tag IS NULL
                ORDER BY tender_id
            """)
            rows = cur.fetchall()

        log.info("Found %d rows to enrich.", len(rows))

        for tender_id, description, category in rows:
            combined_text = " ".join(filter(None, [description, category]))
            features = extract_nlp_features(nlp, combined_text)
            sector = classify_sector(combined_text)

            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE raw.tenders
                    SET
                        entities_orgs      = %s::jsonb,
                        entities_locations = %s::jsonb,
                        keywords           = %s::jsonb,
                        sector_tag         = %s
                    WHERE tender_id = %s
                """, (
                    json.dumps(features["entities_orgs"]),
                    json.dumps(features["entities_locations"]),
                    json.dumps(features["keywords"]),
                    sector,
                    tender_id,
                ))
            conn.commit()
            enriched_count += 1

        log.info("NLP enrichment complete. %d rows updated.", enriched_count)
        return enriched_count

    finally:
        conn.close()


if __name__ == "__main__":
    run_enrichment()
