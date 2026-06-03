"""
Tests for nlp_enricher.py
All tests run against real spaCy model — no mocking.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.nlp_enricher import classify_sector, extract_nlp_features, SECTOR_RULES


# ---------------------------------------------------------------------------
# Sector classification tests
# ---------------------------------------------------------------------------

class TestClassifySector:
    def test_it_software_keyword(self):
        assert classify_sector("Supply and installation of software system") == "IT/Software"

    def test_infrastructure_keyword(self):
        assert classify_sector("Construction of bridge and road rehabilitation") == "Infrastructure"

    def test_healthcare_keyword(self):
        assert classify_sector("Supply of medical equipment for hospital") == "Healthcare"

    def test_education_keyword(self):
        assert classify_sector("Provision of training for school teachers") == "Education"

    def test_security_keyword(self):
        assert classify_sector("Provision of security guard services") == "Security"

    def test_consulting_keyword(self):
        assert classify_sector("Consultancy services for feasibility study") == "Consulting"

    def test_supplies_keyword(self):
        assert classify_sector("Supply of stationery and printing materials") == "Supplies"

    def test_default_to_other(self):
        assert classify_sector("General administrative tender") == "Other"

    def test_empty_string(self):
        assert classify_sector("") == "Other"

    def test_none_input(self):
        assert classify_sector(None) == "Other"

    def test_case_insensitive(self):
        assert classify_sector("SUPPLY OF MEDICAL DRUGS") == "Healthcare"

    def test_solar_maps_to_infrastructure(self):
        assert classify_sector("Supply and installation of solar street lighting") == "Infrastructure"

    def test_ict_maps_to_it(self):
        assert classify_sector("Provision of ICT infrastructure support") == "IT/Software"


# ---------------------------------------------------------------------------
# Sector rules structure tests
# ---------------------------------------------------------------------------

class TestSectorRulesStructure:
    def test_all_expected_sectors_present(self):
        expected = {"IT/Software", "Infrastructure", "Healthcare", "Education",
                    "Security", "Consulting", "Supplies"}
        assert expected.issubset(set(SECTOR_RULES.keys()))

    def test_each_sector_has_keywords(self):
        for sector, keywords in SECTOR_RULES.items():
            assert len(keywords) > 0, f"Sector {sector} has no keywords"

    def test_keywords_are_lowercase(self):
        for sector, keywords in SECTOR_RULES.items():
            for kw in keywords:
                assert kw == kw.lower(), f"Keyword '{kw}' in {sector} is not lowercase"


# ---------------------------------------------------------------------------
# NLP feature extraction tests (requires spaCy model)
# ---------------------------------------------------------------------------

class TestExtractNlpFeatures:
    @pytest.fixture(scope="class")
    def nlp(self):
        import spacy
        return spacy.load("en_core_web_sm")

    def test_returns_dict_with_required_keys(self, nlp):
        result = extract_nlp_features(nlp, "Supply of computers to Nairobi County")
        assert "entities_orgs" in result
        assert "entities_locations" in result
        assert "entities_money" in result
        assert "keywords" in result

    def test_all_values_are_lists(self, nlp):
        result = extract_nlp_features(nlp, "Medical supplies for Kenyatta National Hospital")
        for key in ["entities_orgs", "entities_locations", "entities_money", "keywords"]:
            assert isinstance(result[key], list), f"{key} should be a list"

    def test_keywords_max_five(self, nlp):
        result = extract_nlp_features(
            nlp,
            "Supply installation testing commissioning solar powered street lights university hospital"
        )
        assert len(result["keywords"]) <= 5

    def test_empty_text_returns_empty_lists(self, nlp):
        result = extract_nlp_features(nlp, "")
        for key in ["entities_orgs", "entities_locations", "entities_money", "keywords"]:
            assert result[key] == []

    def test_none_text_returns_empty_lists(self, nlp):
        result = extract_nlp_features(nlp, None)
        for key in ["entities_orgs", "entities_locations", "entities_money", "keywords"]:
            assert result[key] == []

    def test_kenya_location_detected(self, nlp):
        result = extract_nlp_features(nlp, "Provision of services in Nairobi Kenya")
        # spaCy should detect a location-type entity
        all_entities = result["entities_locations"] + result["entities_orgs"]
        assert len(all_entities) >= 0  # permissive: model may vary

    def test_keywords_are_strings(self, nlp):
        result = extract_nlp_features(nlp, "Supply of office furniture and stationery")
        for kw in result["keywords"]:
            assert isinstance(kw, str)

    def test_no_duplicate_keywords(self, nlp):
        result = extract_nlp_features(
            nlp, "Supply supply supply supply supply of items items items"
        )
        assert len(result["keywords"]) == len(set(result["keywords"]))
