"""
Airflow 3.0 DAG — kenya_tenders_pipeline
5 tasks: ingest → NLP enrich → dbt run → dbt test → log summary
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

log = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
    "email_on_failure": False,
    "email_on_retry": False,
}

DBT_PROJECT_DIR = "/opt/airflow/dbt"
DBT_PROFILES_DIR = "/opt/airflow/dbt"


# ---------------------------------------------------------------------------
# Task functions
# ---------------------------------------------------------------------------

def ingest_tenders(**kwargs):
    import sys
    sys.path.insert(0, "/opt/airflow")
    from ingestion.tenders_ingestor import run_ingestion
    inserted = run_ingestion()
    log.info("Ingestion task complete. Rows inserted: %d", inserted)
    return inserted


def run_nlp_enrichment(**kwargs):
    import sys
    sys.path.insert(0, "/opt/airflow")
    from ingestion.nlp_enricher import run_enrichment
    enriched = run_enrichment()
    log.info("NLP enrichment task complete. Rows enriched: %d", enriched)
    return enriched


def run_dbt_models(**kwargs):
    result = subprocess.run(
        ["dbt", "run",
         "--project-dir", DBT_PROJECT_DIR,
         "--profiles-dir", DBT_PROFILES_DIR],
        capture_output=True, text=True, check=False,
    )
    log.info("dbt run stdout:\n%s", result.stdout)
    if result.returncode != 0:
        log.error("dbt run stderr:\n%s", result.stderr)
        raise RuntimeError(f"dbt run failed with code {result.returncode}")
    log.info("dbt models complete.")


def run_dbt_tests(**kwargs):
    result = subprocess.run(
        ["dbt", "test",
         "--project-dir", DBT_PROJECT_DIR,
         "--profiles-dir", DBT_PROFILES_DIR],
        capture_output=True, text=True, check=False,
    )
    log.info("dbt test stdout:\n%s", result.stdout)
    if result.returncode != 0:
        log.error("dbt test stderr:\n%s", result.stderr)
        raise RuntimeError(f"dbt test failed with code {result.returncode}")
    log.info("dbt tests complete.")


def log_summary(**kwargs):
    import sys
    sys.path.insert(0, "/opt/airflow")
    import psycopg2

    conn = psycopg2.connect(
        host=os.getenv("APP_DB_HOST", "postgres"),
        port=int(os.getenv("APP_DB_PORT", 5432)),
        dbname=os.getenv("APP_DB_NAME", "tenders_db"),
        user=os.getenv("APP_DB_USER", "postgres"),
        password=os.getenv("APP_DB_PASSWORD", "postgres"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT status, sector_tag, COUNT(*) AS cnt
                FROM raw.tenders
                GROUP BY status, sector_tag
                ORDER BY cnt DESC
            """)
            rows = cur.fetchall()

        log.info("=== Pipeline Summary ===")
        log.info("%-15s %-25s %s", "Status", "Sector", "Count")
        log.info("-" * 50)
        for status, sector, cnt in rows:
            log.info("%-15s %-25s %d", status or "NULL", sector or "NULL", cnt)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM raw.tenders")
            total = cur.fetchone()[0]
        log.info("Total tenders in raw.tenders: %d", total)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

with DAG(
    dag_id="kenya_tenders_pipeline",
    default_args=DEFAULT_ARGS,
    description="Kenya government procurement intelligence pipeline",
    schedule="0 6 * * *",  # daily at 06:00 UTC
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["kenya", "procurement", "civic-tech"],
) as dag:

    t1 = PythonOperator(
        task_id="ingest_tenders",
        python_callable=ingest_tenders,
    )

    t2 = PythonOperator(
        task_id="run_nlp_enrichment",
        python_callable=run_nlp_enrichment,
    )

    t3 = PythonOperator(
        task_id="run_dbt_models",
        python_callable=run_dbt_models,
    )

    t4 = PythonOperator(
        task_id="run_dbt_tests",
        python_callable=run_dbt_tests,
    )

    t5 = PythonOperator(
        task_id="log_summary",
        python_callable=log_summary,
    )

    t1 >> t2 >> t3 >> t4 >> t5
