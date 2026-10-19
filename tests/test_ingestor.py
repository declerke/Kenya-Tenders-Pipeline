"""Unit tests for the current TendersKenya HTML ingestion flow."""

from datetime import date, timedelta
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion import tenders_ingestor


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Jan 02, 2099", date(2099, 1, 2)),
        ("February 3, 2099", date(2099, 2, 3)),
        ("04 Mar 2099", date(2099, 3, 4)),
        ("2099-04-05", date(2099, 4, 5)),
    ],
)
def test_parse_date_supported_formats(value, expected):
    assert tenders_ingestor.parse_date(value) == expected


@pytest.mark.parametrize("value", [None, "", "not a date"])
def test_parse_date_returns_none_for_empty_or_invalid_values(value):
    assert tenders_ingestor.parse_date(value) is None


def test_derive_status_uses_the_tender_deadline():
    today = date.today()

    assert tenders_ingestor.derive_status(None) == "Open"
    assert tenders_ingestor.derive_status(today + timedelta(days=1)) == "Open"
    assert tenders_ingestor.derive_status(today - timedelta(days=1)) == "Closed"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.tenderskenya.co.ke/tender/office-furniture/", "office-furniture"),
        ("https://example.test/other/path", "https://example.test/other/path"),
    ],
)
def test_slug_from_url(url, expected):
    assert tenders_ingestor.slug_from_url(url) == expected


def test_scrape_page_parses_current_tender_card_without_network():
    deadline = date.today() + timedelta(days=30)
    response = Mock()
    response.text = f"""
        <div class="card h-100">
          <a class="tenderbox_title" href="/tender/medical-supplies">Medical supplies</a>
          <div class="card-footer tenderbox_footer">
            <a class="d-block">
              <p>Entity: <span class="text-orange-1">Ministry of Health</span></p>
              <p>Type: <span class="text-orange-1">Goods</span></p>
              <p>Open: <span class="typcn"></span><span>Jan 01, 2099</span></p>
              <p>Close: <span class="typcn"></span><span>{deadline.isoformat()}</span></p>
            </a>
          </div>
        </div>
    """

    with patch.object(tenders_ingestor.requests, "get", return_value=response) as get:
        records = tenders_ingestor.scrape_page(3)

    get.assert_called_once_with(
        tenders_ingestor.LISTING_URL.format(page=3),
        headers=tenders_ingestor.HEADERS,
        timeout=30,
    )
    response.raise_for_status.assert_called_once_with()
    assert records == [
        {
            "tender_number": "medical-supplies",
            "procuring_entity": "Ministry of Health",
            "description": "Medical supplies",
            "category": "Goods",
            "estimated_value_kes": None,
            "deadline_date": deadline,
            "status": "Open",
            "source_url": "https://www.tenderskenya.co.ke/tender/medical-supplies",
            "source_name": "TendersKenya",
        }
    ]


def test_scrape_page_skips_cards_without_source_footer():
    response = Mock()
    response.text = """
        <div class="card h-100">
          <a class="tenderbox_title" href="/tender/incomplete">Incomplete record</a>
        </div>
    """

    with patch.object(tenders_ingestor.requests, "get", return_value=response):
        assert tenders_ingestor.scrape_page(1) == []
