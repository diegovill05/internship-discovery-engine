"""Unit tests for internship_engine.extractor.

All tests are purely in-process; no network calls are made.
- parse_html() is a pure function tested with fixture HTML strings.
- Extractor.fetch_and_extract() is tested by injecting a mock requests.Session.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from internship_engine.extractor import (
    Extractor,
    ExtractionResult,
    parse_html,
    _find_job_posting_schema,
    _parse_company,
    _parse_location,
    _parse_date,
)
from internship_engine.models import DatePostedConfidence


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

_FULL_POSTING_HTML = """
<html><head><title>SWE Intern – Acme</title></head><body>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Software Engineer Intern",
  "description": "Build amazing things with us.",
  "datePosted": "2024-06-01",
  "employmentType": "INTERN",
  "hiringOrganization": {
    "@type": "Organization",
    "name": "Acme Corp"
  },
  "jobLocation": {
    "@type": "Place",
    "address": {
      "@type": "PostalAddress",
      "addressLocality": "San Francisco",
      "addressRegion": "CA",
      "addressCountry": "US"
    }
  },
  "url": "https://jobs.acme.com/apply/swe-intern"
}
</script>
</body></html>
"""

_MINIMAL_POSTING_HTML = """
<html><body>
<script type="application/ld+json">
{"@type": "JobPosting", "title": "Data Intern", "hiringOrganization": {"name": "Globex"}}
</script>
</body></html>
"""

_GRAPH_POSTING_HTML = """
<html><body>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {"@type": "WebPage", "name": "Careers"},
    {
      "@type": "JobPosting",
      "title": "Product Manager Intern",
      "datePosted": "2024-07-15T09:00:00",
      "hiringOrganization": {"name": "Initech"},
      "jobLocation": {
        "@type": "Place",
        "address": {"addressLocality": "Austin", "addressRegion": "TX", "addressCountry": "US"}
      }
    }
  ]
}
</script>
</body></html>
"""

_ARRAY_POSTING_HTML = """
<html><body>
<script type="application/ld+json">
[
  {"@type": "BreadcrumbList"},
  {
    "@type": "JobPosting",
    "title": "Finance Intern",
    "hiringOrganization": "Umbrella Corp",
    "datePosted": "2024-08-20"
  }
]
</script>
</body></html>
"""

_REMOTE_POSTING_HTML = """
<html><body>
<script type="application/ld+json">
{
  "@type": "JobPosting",
  "title": "ML Engineer Intern",
  "hiringOrganization": {"name": "DeepMind"},
  "jobLocationType": "TELECOMMUTE",
  "datePosted": "2024-09-01"
}
</script>
</body></html>
"""

_NO_JSON_LD_HTML = """
<html><body><h1>Software Engineer Intern</h1><p>Apply here.</p></body></html>
"""

_MALFORMED_JSON_LD_HTML = """
<html><body>
<script type="application/ld+json">{ this is: not valid json }</script>
<script type="application/ld+json">{"@type": "JobPosting", "title": "Valid Intern"}</script>
</body></html>
"""

_APPLY_URL_HTML = """
<html><body>
<script type="application/ld+json">
{
  "@type": "JobPosting",
  "title": "Design Intern",
  "hiringOrganization": {"name": "Figma"},
  "url": "https://apply.figma.com/jobs/123"
}
</script>
</body></html>
"""

_BLOCKED_HTML = ""  # empty body simulates a blocked/empty response


# ---------------------------------------------------------------------------
# parse_html — full schema
# ---------------------------------------------------------------------------


class TestParseHtmlFullSchema:
    def test_title_extracted(self):
        r = parse_html(_FULL_POSTING_HTML)
        assert r.title == "Software Engineer Intern"

    def test_company_extracted(self):
        r = parse_html(_FULL_POSTING_HTML)
        assert r.company == "Acme Corp"

    def test_location_extracted(self):
        r = parse_html(_FULL_POSTING_HTML)
        assert r.location == "San Francisco, CA"

    def test_description_extracted(self):
        r = parse_html(_FULL_POSTING_HTML)
        assert r.description == "Build amazing things with us."

    def test_date_posted_extracted(self):
        r = parse_html(_FULL_POSTING_HTML)
        assert r.date_posted == date(2024, 6, 1)

    def test_date_confidence_is_exact(self):
        r = parse_html(_FULL_POSTING_HTML)
        assert r.date_posted_confidence == DatePostedConfidence.EXACT

    def test_employment_type_extracted(self):
        r = parse_html(_FULL_POSTING_HTML)
        assert r.employment_type == "INTERN"

    def test_apply_url_when_different_from_source(self):
        r = parse_html(_FULL_POSTING_HTML, source_url="https://jobs.acme.com/swe-intern")
        assert r.apply_url == "https://jobs.acme.com/apply/swe-intern"

    def test_apply_url_none_when_same_as_source(self):
        r = parse_html(_FULL_POSTING_HTML, source_url="https://jobs.acme.com/apply/swe-intern")
        assert r.apply_url is None

    def test_not_blocked(self):
        assert parse_html(_FULL_POSTING_HTML).blocked is False


# ---------------------------------------------------------------------------
# parse_html — minimal schema (missing optional fields)
# ---------------------------------------------------------------------------


class TestParseHtmlMinimalSchema:
    def test_title_present(self):
        assert parse_html(_MINIMAL_POSTING_HTML).title == "Data Intern"

    def test_company_present(self):
        assert parse_html(_MINIMAL_POSTING_HTML).company == "Globex"

    def test_location_empty_when_absent(self):
        assert parse_html(_MINIMAL_POSTING_HTML).location == ""

    def test_date_none_when_absent(self):
        assert parse_html(_MINIMAL_POSTING_HTML).date_posted is None

    def test_date_confidence_unknown_when_absent(self):
        assert parse_html(_MINIMAL_POSTING_HTML).date_posted_confidence == DatePostedConfidence.UNKNOWN


# ---------------------------------------------------------------------------
# parse_html — @graph schema
# ---------------------------------------------------------------------------


class TestParseHtmlGraphSchema:
    def test_title_from_graph(self):
        assert parse_html(_GRAPH_POSTING_HTML).title == "Product Manager Intern"

    def test_company_from_graph(self):
        assert parse_html(_GRAPH_POSTING_HTML).company == "Initech"

    def test_location_from_graph(self):
        assert parse_html(_GRAPH_POSTING_HTML).location == "Austin, TX"

    def test_date_from_graph_with_time_component(self):
        r = parse_html(_GRAPH_POSTING_HTML)
        assert r.date_posted == date(2024, 7, 15)
        assert r.date_posted_confidence == DatePostedConfidence.EXACT


# ---------------------------------------------------------------------------
# parse_html — array of schemas
# ---------------------------------------------------------------------------


class TestParseHtmlArraySchema:
    def test_title_from_array(self):
        assert parse_html(_ARRAY_POSTING_HTML).title == "Finance Intern"

    def test_company_string_value(self):
        # hiringOrganization as a plain string
        assert parse_html(_ARRAY_POSTING_HTML).company == "Umbrella Corp"


# ---------------------------------------------------------------------------
# parse_html — remote via jobLocationType
# ---------------------------------------------------------------------------


class TestParseHtmlRemote:
    def test_location_is_remote(self):
        assert parse_html(_REMOTE_POSTING_HTML).location == "Remote"


# ---------------------------------------------------------------------------
# parse_html — no JSON-LD present
# ---------------------------------------------------------------------------


class TestParseHtmlNoJsonLd:
    def test_returns_empty_result(self):
        r = parse_html(_NO_JSON_LD_HTML)
        assert r.title == ""
        assert r.company == ""
        assert r.date_posted is None

    def test_not_blocked(self):
        # Missing schema ≠ blocked; blocked is only for HTTP-level failures
        assert parse_html(_NO_JSON_LD_HTML).blocked is False


# ---------------------------------------------------------------------------
# parse_html — malformed JSON-LD (skips bad block, uses good one)
# ---------------------------------------------------------------------------


class TestParseHtmlMalformedJsonLd:
    def test_skips_malformed_uses_valid(self):
        r = parse_html(_MALFORMED_JSON_LD_HTML)
        assert r.title == "Valid Intern"


# ---------------------------------------------------------------------------
# parse_html — empty / blocked body
# ---------------------------------------------------------------------------


class TestParseHtmlEmptyBody:
    def test_empty_html_returns_defaults(self):
        r = parse_html(_BLOCKED_HTML)
        assert r.title == ""
        assert r.blocked is False  # parse_html never sets blocked

    def test_html_without_script_tag(self):
        r = parse_html("<html><body></body></html>")
        assert r.date_posted is None


# ---------------------------------------------------------------------------
# parse_html — apply_url edge cases
# ---------------------------------------------------------------------------


class TestParseHtmlApplyUrl:
    def test_apply_url_present_when_different(self):
        r = parse_html(_APPLY_URL_HTML, source_url="https://figma.com/careers/design-intern")
        assert r.apply_url == "https://apply.figma.com/jobs/123"

    def test_apply_url_none_when_absent(self):
        r = parse_html(_MINIMAL_POSTING_HTML)
        assert r.apply_url is None


# ---------------------------------------------------------------------------
# _parse_date — unit tests for the date parser
# ---------------------------------------------------------------------------


class TestParseDateFunction:
    def test_iso_date(self):
        d, c = _parse_date("2024-06-01")
        assert d == date(2024, 6, 1)
        assert c == DatePostedConfidence.EXACT

    def test_iso_datetime(self):
        d, c = _parse_date("2024-07-15T09:00:00")
        assert d == date(2024, 7, 15)
        assert c == DatePostedConfidence.EXACT

    def test_iso_datetime_z(self):
        d, c = _parse_date("2024-08-20T00:00:00Z")
        assert d == date(2024, 8, 20)
        assert c == DatePostedConfidence.EXACT

    def test_none_input(self):
        d, c = _parse_date(None)
        assert d is None
        assert c == DatePostedConfidence.UNKNOWN

    def test_empty_string(self):
        d, c = _parse_date("")
        assert d is None
        assert c == DatePostedConfidence.UNKNOWN

    def test_unparseable_string(self):
        d, c = _parse_date("two weeks ago")
        assert d is None
        assert c == DatePostedConfidence.UNKNOWN

    def test_non_string_input(self):
        d, c = _parse_date(20240601)  # type: ignore[arg-type]
        assert d is None
        assert c == DatePostedConfidence.UNKNOWN


# ---------------------------------------------------------------------------
# Extractor.fetch_and_extract — mock session tests
# ---------------------------------------------------------------------------


def _mock_session(status_code: int = 200, text: str = _FULL_POSTING_HTML) -> MagicMock:
    """Build a mock requests.Session whose GET returns the given response."""
    session = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if status_code >= 400:
        from requests.exceptions import HTTPError

        response.raise_for_status.side_effect = HTTPError(response=response)
    else:
        response.raise_for_status.return_value = None
    session.get.return_value = response
    return session


class TestExtractorFetchAndExtract:
    def test_success_returns_extraction(self):
        ext = Extractor(session=_mock_session())
        result = ext.fetch_and_extract("https://example.com/job")
        assert result.title == "Software Engineer Intern"
        assert result.company == "Acme Corp"
        assert not result.blocked

    def test_404_returns_blocked(self):
        ext = Extractor(session=_mock_session(status_code=404))
        result = ext.fetch_and_extract("https://example.com/job")
        assert result.blocked is True

    def test_500_returns_blocked(self):
        ext = Extractor(session=_mock_session(status_code=500))
        result = ext.fetch_and_extract("https://example.com/job")
        assert result.blocked is True

    def test_timeout_returns_blocked(self):
        from requests.exceptions import Timeout

        session = MagicMock()
        session.get.side_effect = Timeout()
        ext = Extractor(session=session)
        result = ext.fetch_and_extract("https://example.com/job")
        assert result.blocked is True

    def test_connection_error_returns_blocked(self):
        from requests.exceptions import ConnectionError as ReqConnError

        session = MagicMock()
        session.get.side_effect = ReqConnError()
        ext = Extractor(session=session)
        result = ext.fetch_and_extract("https://example.com/job")
        assert result.blocked is True

    def test_no_json_ld_returns_empty_non_blocked(self):
        ext = Extractor(session=_mock_session(text=_NO_JSON_LD_HTML))
        result = ext.fetch_and_extract("https://example.com/job")
        assert result.title == ""
        assert result.blocked is False

    def test_empty_body_returns_empty_non_blocked(self):
        ext = Extractor(session=_mock_session(text=""))
        result = ext.fetch_and_extract("https://example.com/job")
        assert result.blocked is False
