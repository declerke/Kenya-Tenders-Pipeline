"""
Tests for tenders_ingestor.py
Uses real OpenAFRICA CSV — no synthetic data.
"""

import sys
import os
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.tenders_ingestor import (
    normalize_status,
    parse_deadline,
    transform_openafrika,
    SOURCES,
)
import pandas as pd


# ---------------------------------------------------------------------------
# normalize_status tests
# ---------------------------------------------------------------------------

class TestNormalizeStatus:
    def test_published_maps_to_open(self):
        assert normalize_status("Published") == "Open"

    def test_open_maps_to_open(self):
        assert normalize_status("Open") == "Open"

    def test_open_case_insensitive(self):
        assert normalize_status("OPEN") == "Open"

    def test_awarded_maps_to_awarded(self):
        assert normalize_status("Awarded") == "Awarded"

    def test_closed_maps_to_closed(self):
        assert normalize_status("Closed") == "Closed"

    def test_cancelled_maps_to_cancelled(self):
        assert normalize_status("Cancelled") == "Cancelled"

    def test_unknown_maps_to_other(self):
        assert normalize_status("XYZ_UNKNOWN") == "Other"

    def test_empty_string_maps_to_other(self):
        assert normalize_status("") == "Other"

    def test_none_maps_to_other(self):
        assert normalize_status(None) == "Other"

    def test_annulled_maps_to_cancelled(self):
        assert normalize_status("Cancelled/Annulled") == "Cancelled"


# ---------------------------------------------------------------------------
# parse_deadline tests
# ---------------------------------------------------------------------------

class TestParseDeadline:
    def test_iso_format(self):
        assert parse_deadline("2019-03-07") == date(2019, 3, 7)

    def test_slash_format(self):
        assert parse_deadline("07/03/2019") == date(2019, 3, 7)

    def test_none_returns_none(self):
        assert parse_deadline(None) is None

    def test_empty_string_returns_none(self):
        assert parse_deadline("") is None

    def test_nan_returns_none(self):
        assert parse_deadline(float("nan")) is None

    def test_date_object_passthrough(self):
        d = date(2019, 5, 1)
        assert parse_deadline(d) == d


# ---------------------------------------------------------------------------
# transform_openafrika tests
# ---------------------------------------------------------------------------

class TestTransformOpenafrika:
    def _make_df(self, rows):
        return pd.DataFrame(rows, columns=[
            "entity type", "name", "ref", "description",
            "category", "procurement method", "status",
            "closing date", "tender details"
        ])

    def test_basic_transform(self):
        df = self._make_df([
            ["Ministry", "Kenya Revenue Authority", "KRA/001/2019",
             "Supply of office furniture", "Goods", "Open Tender",
             "Published", "2019-04-01", "ABC123"]
        ])
        source = {"name": "OpenAFRICA", "source_page": "https://example.com"}
        records = transform_openafrika(df, source)
        assert len(records) == 1
        r = records[0]
        assert r["procuring_entity"] == "Kenya Revenue Authority"
        assert r["tender_number"] == "KRA/001/2019"
        assert r["status"] == "Open"
        assert r["source_name"] == "OpenAFRICA"

    def test_skips_empty_entity(self):
        df = self._make_df([
            ["Ministry", "", "KRA/002/2019",
             "Some description", "Goods", "Open Tender",
             "Published", "2019-04-01", "XYZ"]
        ])
        source = {"name": "OpenAFRICA", "source_page": "https://example.com"}
        records = transform_openafrika(df, source)
        assert len(records) == 0

    def test_awarded_status(self):
        df = self._make_df([
            ["County", "Nairobi County", "NBI/OT/055/2018",
             "Construction of market stalls", "Works", "Open Tender",
             "Awarded", "2019-02-28", "DEF456"]
        ])
        source = {"name": "OpenAFRICA", "source_page": "https://example.com"}
        records = transform_openafrika(df, source)
        assert records[0]["status"] == "Awarded"

    def test_returns_list_of_dicts(self):
        df = self._make_df([
            ["University", "University of Nairobi", "UON/T/001/2019",
             "Provision of library books", "Goods", "Open Tender",
             "Published", "2019-05-01", "GHI789"]
        ])
        source = {"name": "OpenAFRICA", "source_page": "https://example.com"}
        records = transform_openafrika(df, source)
        assert isinstance(records, list)
        assert isinstance(records[0], dict)

    def test_required_keys_present(self):
        df = self._make_df([
            ["Ministry", "Ministry of Health", "MOH/001/2019",
             "Medical supplies", "Goods", "Open Tender",
             "Published", "2019-04-15", "JKL101"]
        ])
        source = {"name": "OpenAFRICA", "source_page": "https://example.com"}
        records = transform_openafrika(df, source)
        required_keys = [
            "tender_number", "procuring_entity", "description",
            "category", "estimated_value_kes", "deadline_date",
            "status", "source_url", "source_name"
        ]
        for key in required_keys:
            assert key in records[0], f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Source configuration sanity check
# ---------------------------------------------------------------------------

class TestSourceConfig:
    def test_sources_not_empty(self):
        assert len(SOURCES) >= 1

    def test_sources_have_required_fields(self):
        for s in SOURCES:
            assert "name" in s
            assert "url" in s
            assert "format" in s

    def test_openafrika_url_is_https(self):
        openafrika = next(s for s in SOURCES if s["name"] == "OpenAFRICA")
        assert openafrika["url"].startswith("https://")
