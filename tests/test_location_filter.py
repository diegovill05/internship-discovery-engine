"""Unit tests for internship_engine.location_filter."""

from __future__ import annotations

from internship_engine.location_filter import LocationFilter, apply_location_filter
from internship_engine.models import JobPosting

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _posting(location: str, suffix: str = "1") -> JobPosting:
    return JobPosting(
        title="Software Engineer Intern",
        company="Acme Corp",
        location=location,
        posting_url=f"https://example.com/job/{suffix}",
    )


# ---------------------------------------------------------------------------
# LocationFilter.matches — default (no restrictions)
# ---------------------------------------------------------------------------


class TestLocationFilterDefaults:
    def test_empty_filter_allows_any_location(self):
        f = LocationFilter()
        assert f.matches(_posting("New York, NY")) is True
        assert f.matches(_posting("Austin, TX")) is True
        assert f.matches(_posting("Tokyo, Japan")) is True

    def test_remote_allowed_by_default(self):
        f = LocationFilter()
        assert f.matches(_posting("Remote")) is True

    def test_remote_substring_in_hybrid_location(self):
        # "Remote / New York" → is_remote inferred True → passes with default filter
        f = LocationFilter()
        assert f.matches(_posting("Remote / New York")) is True


# ---------------------------------------------------------------------------
# LocationFilter.matches — remote flag
# ---------------------------------------------------------------------------


class TestLocationFilterRemoteFlag:
    def test_remote_excluded_when_flag_false(self):
        f = LocationFilter(include_remote=False)
        assert f.matches(_posting("Remote")) is False

    def test_non_remote_passes_when_remote_excluded(self):
        f = LocationFilter(include_remote=False)
        assert f.matches(_posting("New York, NY")) is True

    def test_remote_excluded_even_with_allowed_locations(self):
        # include_remote=False takes precedence; the posting is remote, so it fails
        f = LocationFilter(allowed_locations=("Remote",), include_remote=False)
        assert f.matches(_posting("Remote")) is False

    def test_hybrid_remote_posting_excluded_when_flag_false(self):
        f = LocationFilter(include_remote=False)
        assert f.matches(_posting("Remote / New York")) is False


# ---------------------------------------------------------------------------
# LocationFilter.matches — allowed_locations filtering
# ---------------------------------------------------------------------------


class TestLocationFilterAllowedLocations:
    def test_single_location_match(self):
        f = LocationFilter(allowed_locations=("New York",))
        assert f.matches(_posting("New York, NY")) is True

    def test_single_location_no_match(self):
        f = LocationFilter(allowed_locations=("New York",))
        assert f.matches(_posting("Chicago, IL")) is False

    def test_case_insensitive_match(self):
        f = LocationFilter(allowed_locations=("new york",))
        assert f.matches(_posting("New York, NY")) is True

    def test_case_insensitive_filter_vs_uppercase_location(self):
        f = LocationFilter(allowed_locations=("NEW YORK",))
        assert f.matches(_posting("new york, ny")) is True

    def test_multiple_allowed_locations_first_matches(self):
        f = LocationFilter(allowed_locations=("New York", "San Francisco"))
        assert f.matches(_posting("New York, NY")) is True

    def test_multiple_allowed_locations_second_matches(self):
        f = LocationFilter(allowed_locations=("New York", "San Francisco"))
        assert f.matches(_posting("San Francisco, CA")) is True

    def test_multiple_allowed_locations_none_match(self):
        f = LocationFilter(allowed_locations=("New York", "San Francisco"))
        assert f.matches(_posting("Chicago, IL")) is False

    def test_substring_match_within_longer_string(self):
        f = LocationFilter(allowed_locations=("York",))
        assert f.matches(_posting("New York, NY")) is True

    def test_remote_bypasses_allowed_locations(self):
        # Remote posting passes regardless of allowed_locations when include_remote=True
        f = LocationFilter(allowed_locations=("New York",), include_remote=True)
        assert f.matches(_posting("Remote")) is True


# ---------------------------------------------------------------------------
# apply_location_filter
# ---------------------------------------------------------------------------


class TestApplyLocationFilter:
    def test_filters_correctly(self):
        f = LocationFilter(allowed_locations=("New York",), include_remote=True)
        postings = [
            _posting("New York, NY", "1"),
            _posting("Chicago, IL", "2"),
            _posting("Remote", "3"),
        ]
        result = apply_location_filter(postings, f)
        assert len(result) == 2
        assert postings[0] in result
        assert postings[2] in result
        assert postings[1] not in result

    def test_empty_input_returns_empty(self):
        f = LocationFilter()
        assert apply_location_filter([], f) == []

    def test_all_pass_with_empty_filter(self):
        f = LocationFilter()
        postings = [_posting("New York, NY", "1"), _posting("Remote", "2")]
        assert apply_location_filter(postings, f) == postings

    def test_none_pass_when_all_excluded(self):
        f = LocationFilter(allowed_locations=("London",), include_remote=False)
        postings = [_posting("New York, NY", "1"), _posting("Remote", "2")]
        assert apply_location_filter(postings, f) == []

    def test_preserves_order(self):
        f = LocationFilter(allowed_locations=("New York", "Austin"))
        postings = [
            _posting("Austin, TX", "3"),
            _posting("New York, NY", "1"),
            _posting("Austin, TX", "2"),
        ]
        result = apply_location_filter(postings, f)
        assert result == postings  # all pass and order is maintained
