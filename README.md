# Kenya Tenders Pipeline

Government procurement intelligence for Kenya — a production-grade civic tech data pipeline that ingests real tender data from OpenAFRICA, applies spaCy NLP enrichment, and surfaces insights through an interactive Streamlit dashboard.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Apache Airflow 3.0                               │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────┐   ┌──────────────┐  │
│  │  ingest_    │──▶│  run_nlp_    │──▶│ run_dbt_ │──▶│  run_dbt_   │  │
│  │  tenders    │   │  enrichment  │   │  models  │   │   tests     │  │
│  └─────────────┘   └──────────────┘   └──────────┘   └──────────────┘  │
└───────────────────────────────────────────┬─────────────────────────────┘
                                            │
  OpenAFRICA CKAN API                       ▼
  ke_tenders_list.csv ──▶  raw.tenders (PostgreSQL 15)
                                            │
                           spaCy en_core_web_sm
                           NER + keywords + sector_tag
                                            │
                           dbt-postgres models
                           stg → fct → marts
                                            │
                           Streamlit Dashboard ◀── psycopg2
                           4 pages (Overview / Entity / Sector / Active)
```

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| NLP engine | spaCy en_core_web_sm | Free, runs locally, no API key, production-grade NER for English government text |
| Sector classification | Rule-based keyword matching | Deterministic, auditable, no model hallucination risk for civic data |
| Dashboard UX | Streamlit with sidebar filters | Rapid iteration, built-in caching, native DataFrame rendering for procurement search |
| Data source | OpenAFRICA CKAN API | Structured CSV endpoint, 6,796 real Kenya government procurement records, reproducible URL |
| Value column | NULL for most rows | Source CSV does not publish estimated values — honesty preferred over synthetic data |
| Status normalisation | CASE-based in dbt staging | Centralised — raw CSV uses "Published" which maps to Open; single source of truth in stg_tenders |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Ingestion | Python 3.11, requests, pandas, psycopg2 |
| NLP Enrichment | spaCy 3.7 (en_core_web_sm) |
| Storage | PostgreSQL 15 |
| Transformation | dbt-postgres 1.8 |
| Orchestration | Apache Airflow 3.0 (Docker, LocalExecutor) |
| Dashboard | Streamlit 1.35, Plotly 5.22 |
| Containerisation | Docker Compose 3.9 |
| Security | pip-audit (GitHub Actions weekly) |
| Local dev | uv venv, uv pip install |

---

## Data Schema

### `raw.tenders` (source table)

| Column | Type | Description |
|---|---|---|
| tender_id | SERIAL PK | Auto-increment |
| tender_number | VARCHAR(200) | Reference number (e.g. KRA/OT/004/2018-2019) |
| procuring_entity | VARCHAR(500) | Government entity name |
| description | TEXT | Tender description |
| category | VARCHAR(200) | Goods / Works / Consultancy Services / Non Consultancy Services |
| estimated_value_kes | NUMERIC(15,2) | Estimated contract value in KES (NULL if not published) |
| deadline_date | DATE | Closing date |
| status | VARCHAR(50) | Open / Closed / Awarded / Cancelled / Other |
| source_url | TEXT | Dataset page URL |
| source_name | VARCHAR(100) | OpenAFRICA |
| scraped_at | TIMESTAMPTZ | Ingestion timestamp |
| entities_orgs | JSONB | spaCy ORG entities extracted from description |
| entities_locations | JSONB | spaCy GPE/LOC entities |
| keywords | JSONB | Top 5 content keywords (nouns + proper nouns) |
| sector_tag | VARCHAR(100) | Rule-based sector: IT/Software, Infrastructure, Healthcare, Education, Security, Consulting, Supplies, Other |

### dbt Models

| Model | Type | Description |
|---|---|---|
| `stg_tenders` | View | Cleaned raw data — normalised status, filtered nulls |
| `fct_tenders` | Table | Enriched fact table + `days_to_deadline` + `is_high_value` flag |
| `mart_by_entity` | Table | Per-entity aggregates (tender count, value, status breakdown) |
| `mart_by_sector` | Table | Per-sector aggregates (count, value, open/closed split) |
| `mart_active_tenders` | Table | Open tenders ordered by deadline urgency |

---

## Pipeline Flow

```
1. ingest_tenders
   └── Fetches ke_tenders_list.csv from OpenAFRICA S3
   └── Normalises status, parses dates
   └── Upserts to raw.tenders (ON CONFLICT DO NOTHING)

2. run_nlp_enrichment
   └── Loads spaCy en_core_web_sm
   └── Processes all rows WHERE sector_tag IS NULL
   └── Extracts ORG, GPE, MONEY entities + top-5 keywords
   └── Applies rule-based sector classification
   └── UPDATEs raw.tenders enriched columns

3. run_dbt_models
   └── dbt run → builds 5 models
   └── stg_tenders (view) → fct_tenders → 3 mart tables

4. run_dbt_tests
   └── not_null, unique, accepted_values tests across all models

5. log_summary
   └── Logs status × sector_tag breakdown to Airflow task logs
```

---

## dbt Models Table

| Model | Materialisation | Key Columns | Row Scope |
|---|---|---|---|
| stg_tenders | View | all raw columns, normalised status | All non-null entities |
| fct_tenders | Table | + days_to_deadline, is_high_value | All staging rows |
| mart_by_entity | Table | tender_count, total/avg value, open/closed/awarded | Entities ≥ 2 tenders |
| mart_by_sector | Table | tender_count, total/avg value, open_count | All sectors |
| mart_active_tenders | Table | tender details + days_to_deadline | Open + non-expired |

---

## Test Coverage

| Module | Tests | Coverage |
|---|---|---|
| `test_ingestor.py` | 24 pytest tests | normalize_status (10), parse_deadline (6), transform (5), source config (3) |
| `test_nlp_enricher.py` | 24 pytest tests | classify_sector (13), SECTOR_RULES structure (3), extract_nlp_features (8) |
| dbt schema tests | 21 schema tests | not_null, unique, accepted_values across 5 models |
| **Total** | **69 tests** | |

---

## Setup & Running

### Prerequisites
- Docker Desktop
- Python 3.11 + uv (`pip install uv`)

### Local development

```bash
git clone https://github.com/declerke/Kenya-Tenders-Pipeline
cd Kenya-Tenders-Pipeline
uv venv .venv
source .venv/Scripts/activate  # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### Start the full stack

```bash
docker-compose build
docker-compose up -d
```

Services:
- Airflow UI: http://localhost:8083 (admin / admin123)
- Streamlit: http://localhost:8501
- App DB: localhost:5434
- Airflow meta DB: localhost:5439

### Trigger the pipeline

```bash
# Reserialize DAGs (first run only)
docker-compose exec airflow-scheduler airflow dags reserialize

# Trigger a manual DAG run
docker-compose exec airflow-scheduler airflow dags trigger kenya_tenders_pipeline
```

### Verify data

```bash
docker-compose exec postgres psql -U postgres -d tenders_db \
  -c "SELECT status, sector_tag, COUNT(*) FROM raw.tenders GROUP BY status, sector_tag ORDER BY COUNT(*) DESC;"
```

### Run tests

```bash
docker-compose exec airflow-scheduler bash -c "cd /opt/airflow && python -m pytest tests/ -v"
```

---

## Sample Output

After running the pipeline, `raw.tenders` contains records like:

| tender_number | procuring_entity | description | status | sector_tag | keywords |
|---|---|---|---|---|---|
| ODPP/OT/004/2018-2019 | Office of the Director of Public Prosecutions | SUPPLY AND DELIVERY OF FURNITURE | Open | Supplies | ["furniture", "supply", "delivery"] |
| KNH/T/102/2018-2019 | Kenyatta National Hospital | SUPPLY OF MEDICAL LABORATORY REAGENTS | Open | Healthcare | ["reagent", "laboratory", "supply"] |
| EU/PQS/24/2019-2021 | Egerton University | PREQUALIFICATION OF SUPPLIERS FOR COMPUTERS AND ACCESSORIES | Open | IT/Software | ["computer", "supplier", "accessory"] |
| CGE/EOI/002/2018-2019 | Embu County | OFFICE SPACE LEASE FOR EMBU COUNTY REVENUE AUTHORITY | Open | Other | ["office", "space", "lease"] |
| 710884,1 | Kilifi County | SUPPLY, INSTALLATION, TESTING & COMMISSIONING OF SOLAR POWERED 15M HIGHMAST | Open | Infrastructure | ["highmast", "solar", "installation"] |

---

## Skills Demonstrated

- **NLP Engineering** — spaCy Named Entity Recognition, keyword extraction pipeline, rule-based sector classification at scale
- **Civic Tech / Government Data** — parsing and normalising Kenya government procurement records from OpenAFRICA
- **Airflow 3.0 Orchestration** — 5-task DAG, LocalExecutor, daily schedule, task-level error handling
- **dbt-postgres** — staging views, fact tables, analytics marts, schema tests (not_null, unique, accepted_values)
- **PostgreSQL 15** — JSONB columns, ON CONFLICT upsert, schema-level organisation (raw / staging / marts)
- **Streamlit Dashboard** — multi-page app, `@st.cache_data`, interactive filters, Plotly visualisations
- **Docker Compose** — multi-service orchestration, port isolation for parallel projects, health checks
- **Python Testing** — 48 pytest unit tests covering ingestion and NLP with real model

---

## Project Stats

| Metric | Value |
|---|---|
| Tenders ingested | 6,796 (real Kenya government procurement records, 2018-2019) |
| NLP enrichment | 6,796 / 6,796 rows enriched (100%) |
| Procuring entities | 229 unique government entities (≥2 tenders) |
| Sources | 1 (OpenAFRICA CKAN API — ke_tenders_list.csv) |
| Sectors classified | 8 (Infrastructure 3,517 · Supplies 1,041 · Consulting 829 · IT/Software 707 · Healthcare 363 · Education 91 · Security 101 · Other 147) |
| Open tenders | 5,535 |
| Awarded tenders | 1,261 |
| dbt models | 5 (5/5 PASS) |
| dbt tests | 21 (21/21 PASS) |
| pytest tests | 48 (48/48 PASS) |
| Airflow tasks | 5 |
| Streamlit pages | 4 |
| Docker services | 7 (postgres · postgres-airflow · airflow-init · airflow-dag-processor · airflow-scheduler · airflow-webserver · streamlit) |

---

## License

MIT License — see [LICENSE](LICENSE) for details.
