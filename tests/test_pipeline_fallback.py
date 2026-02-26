"""Tests for the extractor-fallback-snippet behaviour in the CLI pipeline.

All tests are network-free.  The Extractor and search source are replaced
with lightweight test doubles so we only exercise the fallback logic in
_make_posting() and the location-filter bypass in cmd_run().
"""

from __future__ import annotations

import argparse
from datetime import date
from unittest.mock import MagicMock, patch

from internship_engine.cli import _make_posting
from internship_engine.extractor import ExtractionResult
from internship_engine.models import DatePostedConfidence, JobPosting
from internship_engine.sources.google_search import RawSearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw(
    url: str = "https://example.com/job/1",
    title: str = "Software Intern",
    snippet: str = "Great internship at Acme in New York.",
) -> RawSearchResult:
    return RawSearchResult(url=url, title=title, snippet=snippet)


def _ext_ok(**kwargs) -> ExtractionResult:
    """Successful extraction with full data."""
    defaults = {
        "title": "Extracted Title",
        "company": "Extracted Co",
        "location": "New York, NY",
        "description": "Extracted description.",
        "date_posted": date(2024, 6, 1),
        "date_posted_confidence": DatePostedConfidence.EXACT,
        "blocked": False,
    }
    defaults.update(kwargs)
    return ExtractionResult(**defaults)


def _ext_blocked() -> ExtractionResult:
    """Blocked extraction — all fields at defaults."""
    return ExtractionResult(blocked=True)


# ---------------------------------------------------------------------------
# _make_posting: successful extraction
# ---------------------------------------------------------------------------


class TestMakePostingSuccessful:
    def test_title_from_extraction(self):
        p = _make_posting(_raw(), _ext_ok(), "brave")
        assert p.title == "Extracted Title"

    def test_title_falls_back_to_search_result(self):
        p = _make_posting(_raw(title="Search Title"), _ext_ok(title=""), "brave")
        assert p.title == "Search Title"

    def test_company_from_extraction(self):
        p = _make_posting(_raw(), _ext_ok(), "brave")
        assert p.company == "Extracted Co"

    def test_location_from_extraction(self):
        p = _make_posting(_raw(), _ext_ok(), "brave")
        assert p.location == "New York, NY"

    def test_description_from_extraction(self):
        p = _make_posting(_raw(), _ext_ok(), "brave")
        assert p.description == "Extracted description."

    def test_date_posted_from_extraction(self):
        p = _make_posting(_raw(), _ext_ok(), "brave")
        assert p.date_posted == date(2024, 6, 1)
        assert p.date_posted_confidence == DatePostedConfidence.EXACT

    def test_source_name_stored(self):
        p = _make_posting(_raw(), _ext_ok(), "google")
        assert p.source == "google"

    def test_posting_url_always_from_search_result(self):
        raw = _raw(url="https://indeed.com/job/123")
        p = _make_posting(raw, _ext_ok(), "brave")
        assert p.posting_url == "https://indeed.com/job/123"


# ---------------------------------------------------------------------------
# _make_posting: blocked extraction
# ---------------------------------------------------------------------------


class TestMakePostingBlocked:
    def test_title_falls_back_to_search_result(self):
        raw = _raw(title="Indeed: Software Intern")
        p = _make_posting(raw, _ext_blocked(), "brave")
        assert p.title == "Indeed: Software Intern"

    def test_company_is_unknown_when_blocked(self):
        p = _make_posting(_raw(), _ext_blocked(), "brave")
        assert p.company == "Unknown"

    def test_location_is_unknown_when_blocked(self):
        p = _make_posting(_raw(), _ext_blocked(), "brave")
        assert p.location == "Unknown"

    def test_description_uses_snippet_when_blocked(self):
        raw = _raw(snippet="Python intern at Acme, New York.")
        p = _make_posting(raw, _ext_blocked(), "brave")
        assert p.description == "Python intern at Acme, New York."

    def test_date_posted_is_none_when_blocked(self):
        p = _make_posting(_raw(), _ext_blocked(), "brave")
        assert p.date_posted is None

    def test_date_confidence_is_unknown_when_blocked(self):
        p = _make_posting(_raw(), _ext_blocked(), "brave")
        assert p.date_posted_confidence == DatePostedConfidence.UNKNOWN

    def test_posting_url_from_search_result_when_blocked(self):
        raw = _raw(url="https://linkedin.com/jobs/view/999")
        p = _make_posting(raw, _ext_blocked(), "brave")
        assert p.posting_url == "https://linkedin.com/jobs/view/999"

    def test_returns_job_posting_instance(self):
        p = _make_posting(_raw(), _ext_blocked(), "brave")
        assert isinstance(p, JobPosting)


# ---------------------------------------------------------------------------
# _make_posting: non-blocked but partially empty extraction
# ---------------------------------------------------------------------------


class TestMakePostingPartialExtraction:
    def test_empty_company_stays_empty_when_not_blocked(self):
        """If extraction succeeded but company was missing, keep empty string."""
        p = _make_posting(_raw(), _ext_ok(company=""), "brave")
        assert p.company == ""

    def test_empty_description_stays_empty_when_not_blocked(self):
        """Snippet is NOT used when extraction succeeded but description was empty."""
        raw = _raw(snippet="Fallback snippet")
        p = _make_posting(raw, _ext_ok(description=""), "brave")
        assert p.description == ""


# ---------------------------------------------------------------------------
# Location-filter bypass for blocked postings
# ---------------------------------------------------------------------------


class TestLocationFilterBypass:
    """cmd_run must not drop blocked postings even when location filters are set."""

    def _run_cmd(self, locations: list[str], raw_results, ext_result) -> list:
        """Run cmd_run with mocked source and extractor; return captured postings."""
        captured: list[JobPosting] = []

        args = argparse.Namespace(
            source="brave",
            locations=locations,
            no_remote=False,
            keywords=[],
            categories=[],
            max_results=10,
            posted_within_days=None,
            export="none",
            sheet_id=None,
            sheet_tab=None,
        )

        mock_source = MagicMock()
        mock_source.fetch.return_value = raw_results

        mock_extractor = MagicMock()
        mock_extractor.fetch_and_extract.return_value = ext_result

        def capture_summary(postings):
            captured.extend(postings)

        with (
            patch(
                "internship_engine.cli._build_source",
                return_value=(mock_source, "brave"),
            ),
            patch(
                "internship_engine.extractor.Extractor",
                return_value=mock_extractor,
            ),
            patch("internship_engine.deduplication.DuplicateFilter") as mock_dup,
            patch("internship_engine.cli._print_summary", side_effect=capture_summary),
        ):
            mock_dup.return_value.is_new.return_value = True
            from internship_engine.cli import cmd_run
            from internship_engine.config import reset_settings

            reset_settings()
            cmd_run(args)

        return captured

    def test_blocked_posting_survives_location_filter(self):
        """Blocked postings are kept even when a location filter is active."""
        raw = _raw(url="https://indeed.com/job/1", title="SW Intern", snippet="snippet")
        postings = self._run_cmd(["San Francisco"], [raw], _ext_blocked())
        assert len(postings) == 1
        assert postings[0].company == "Unknown"

    def test_non_blocked_posting_dropped_by_location_filter(self):
        """Non-blocked postings with mismatched location are still dropped."""
        raw = _raw(url="https://company.com/job/1")
        ext = _ext_ok(location="Austin, TX")
        postings = self._run_cmd(["San Francisco"], [raw], ext)
        assert len(postings) == 0

    def test_non_blocked_matching_location_passes_filter(self):
        """Non-blocked postings with matching location still pass."""
        raw = _raw(url="https://company.com/job/1")
        ext = _ext_ok(location="San Francisco, CA")
        postings = self._run_cmd(["San Francisco"], [raw], ext)
        assert len(postings) == 1

    def test_blocked_posting_no_location_filter_also_passes(self):
        """Blocked postings with no location restrictions always pass."""
        raw = _raw(url="https://indeed.com/job/2")
        postings = self._run_cmd([], [raw], _ext_blocked())
        assert len(postings) == 1
