"""Unit tests for internship_engine.categorization."""

from __future__ import annotations

import pytest

from internship_engine.categorization import categorize
from internship_engine.models import Category, JobPosting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _posting(title: str, description: str = "") -> JobPosting:
    return JobPosting(
        title=title,
        company="Acme Corp",
        location="New York, NY",
        description=description,
        posting_url="https://example.com/job/1",
    )


# ---------------------------------------------------------------------------
# Title-based matching
# ---------------------------------------------------------------------------


class TestCategorizeByTitle:
    def test_software_engineer(self):
        assert categorize(_posting("Software Engineer Intern")) == Category.SOFTWARE

    def test_backend_engineer(self):
        assert categorize(_posting("Backend Engineer Intern")) == Category.SOFTWARE

    def test_frontend_engineer(self):
        assert categorize(_posting("Frontend Engineer Intern")) == Category.SOFTWARE

    def test_web_developer(self):
        assert categorize(_posting("Web Developer Intern")) == Category.SOFTWARE

    def test_data_science(self):
        assert categorize(_posting("Data Science Intern")) == Category.DATA

    def test_machine_learning(self):
        assert categorize(_posting("Machine Learning Engineer")) == Category.DATA

    def test_data_analyst(self):
        assert categorize(_posting("Data Analyst Intern")) == Category.DATA

    def test_product_manager(self):
        assert categorize(_posting("Product Manager Intern")) == Category.PRODUCT

    def test_program_manager(self):
        assert categorize(_posting("Program Manager Intern")) == Category.PRODUCT

    def test_ux_design(self):
        assert categorize(_posting("UX Designer Intern")) == Category.DESIGN

    def test_graphic_designer(self):
        assert categorize(_posting("Graphic Designer Intern")) == Category.DESIGN

    def test_finance(self):
        assert categorize(_posting("Finance Intern")) == Category.FINANCE

    def test_marketing(self):
        assert categorize(_posting("Marketing Intern")) == Category.MARKETING

    def test_seo(self):
        assert categorize(_posting("SEO Specialist Intern")) == Category.MARKETING

    def test_other_when_no_match(self):
        assert categorize(_posting("Office Coordinator")) == Category.OTHER

    def test_other_for_generic_title(self):
        assert categorize(_posting("Summer Intern")) == Category.OTHER


# ---------------------------------------------------------------------------
# Description-based matching
# ---------------------------------------------------------------------------


class TestCategorizeByDescription:
    def test_keyword_in_description_only(self):
        p = _posting("Summer Intern", description="Working on machine learning models.")
        assert categorize(p) == Category.DATA

    def test_description_overrides_ambiguous_title(self):
        p = _posting("Research Intern", description="Deep learning and computer vision.")
        assert categorize(p) == Category.DATA


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestCategorizeEdgeCases:
    def test_case_insensitive_title(self):
        assert categorize(_posting("BACKEND ENGINEER INTERN")) == Category.SOFTWARE

    def test_case_insensitive_description(self):
        p = _posting("Intern", description="MACHINE LEARNING pipeline.")
        assert categorize(p) == Category.DATA

    def test_data_beats_software_when_data_science_present(self):
        # "Data Science Engineer" — DATA keywords appear earlier in the registry
        p = _posting("Data Science Engineer Intern")
        assert categorize(p) == Category.DATA

    def test_product_manager_not_confused_with_software(self):
        # "Product Manager" should NOT fall through to SOFTWARE
        assert categorize(_posting("Product Manager Intern")) == Category.PRODUCT

    def test_empty_title_and_description(self):
        p = _posting("", description="")
        assert categorize(p) == Category.OTHER
