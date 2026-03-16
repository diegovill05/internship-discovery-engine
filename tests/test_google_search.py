"""Unit tests for internship_engine.sources.google_search.

All tests are network-free:
- build_queries() is a pure function tested directly.
- GoogleSearchSource is tested by injecting a mock requests.Session.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from internship_engine.sources.google_search import (
    ATS_DOMAINS,
    GoogleSearchConfig,
    GoogleSearchSource,
    RawSearchResult,
    build_queries,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(max_results: int = 10) -> GoogleSearchConfig:
    return GoogleSearchConfig(
        api_key="test-key",
        cse_id="test-cse-id",
        max_results=max_results,
    )


def _make_items(n: int, url_prefix: str = "https://example.com/job/") -> list[dict]:
    return [
        {"title": f"Job {i}", "link": f"{url_prefix}{i}", "snippet": f"Snippet {i}"}
        for i in range(1, n + 1)
    ]


def _mock_session(items: list[dict]) -> MagicMock:
    """Return a session whose GET always returns an API response with *items*."""
    session = MagicMock()
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"items": items}
    session.get.return_value = response
    return session


def _mock_session_empty() -> MagicMock:
    session = MagicMock()
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {}  # no "items" key
    session.get.return_value = response
    return session


# ---------------------------------------------------------------------------
# build_queries — pure function
# ---------------------------------------------------------------------------


class TestBuildQueries:
    def test_single_location(self):
        queries = build_queries(["New York, NY"], [], [])
        assert len(queries) == 1
        assert "New York, NY" in queries[0]

    def test_multiple_locations_produce_multiple_queries(self):
        queries = build_queries(["New York", "San Francisco"], [], [])
        assert len(queries) == 2
        assert "New York" in queries[0]
        assert "San Francisco" in queries[1]

    def test_no_locations_produces_single_query(self):
        queries = build_queries([], ["Python"], ["software"])
        assert len(queries) == 1

    def test_keywords_included(self):
        queries = build_queries([], ["Python", "Django"], [])
        assert "Python" in queries[0]
        assert "Django" in queries[0]

    def test_categories_included(self):
        queries = build_queries([], [], ["software", "data"])
        assert "software" in queries[0]
        assert "data" in queries[0]

    def test_default_terms_included(self):
        queries = build_queries([], [], [])
        q = queries[0].lower()
        assert "internship" in q or "intern" in q

    def test_custom_terms_override_defaults(self):
        queries = build_queries([], [], [], terms=["co-op"])
        assert "co-op" in queries[0]
        assert "internship" not in queries[0]

    def test_empty_terms_list(self):
        queries = build_queries([], ["Python"], [], terms=[])
        # No terms — only keyword in query
        assert "Python" in queries[0]

    def test_location_appended_to_base(self):
        queries = build_queries(["Austin, TX"], ["Python"], ["software"])
        q = queries[0]
        assert q.endswith("Austin, TX")
        assert "Python" in q
        assert "software" in q

    def test_returns_list_not_empty(self):
        queries = build_queries([], [], [])
        assert isinstance(queries, list)
        assert len(queries) >= 1

    def test_query_is_string(self):
        for q in build_queries(["NYC"], ["Go"], ["software"]):
            assert isinstance(q, str)

    def test_default_terms_skipped_when_keywords_provided(self):
        """When keywords are supplied, default terms should not be appended."""
        queries = build_queries([], ["cybersecurity"], [])
        q = queries[0]
        assert "cybersecurity" in q
        assert "internship" not in q
        assert "intern" not in q

    def test_default_terms_added_when_no_keywords(self):
        """When no keywords are given, default terms are appended."""
        queries = build_queries([], [], [])
        q = queries[0].lower()
        assert "internship" in q or "intern" in q


# ---------------------------------------------------------------------------
# build_queries — ATS domain targeting
# ---------------------------------------------------------------------------


_TINY_ATS: dict[str, list[str]] = {
    "greenhouse": ["boards.greenhouse.io"],
    "lever": ["jobs.lever.co"],
}


class TestBuildQueriesAts:
    def test_ats_none_returns_only_generic(self):
        queries = build_queries([], [], [], ats_domains=None)
        assert len(queries) == 1
        assert "site:" not in queries[0]

    def test_ats_empty_dict_returns_only_generic(self):
        queries = build_queries([], [], [], ats_domains={})
        assert len(queries) == 1
        assert "site:" not in queries[0]

    def test_ats_queries_prepended_before_generic(self):
        queries = build_queries([], [], [], ats_domains=_TINY_ATS)
        ats_qs = [q for q in queries if "site:" in q]
        generic_qs = [q for q in queries if "site:" not in q]
        assert len(ats_qs) == 2  # one per domain
        assert len(generic_qs) == 1
        # ATS must come first
        first_ats_idx = queries.index(ats_qs[0])
        first_generic_idx = queries.index(generic_qs[0])
        assert first_ats_idx < first_generic_idx

    def test_each_ats_query_contains_site_operator(self):
        queries = build_queries([], [], [], ats_domains=_TINY_ATS)
        ats_qs = [q for q in queries if "site:" in q]
        domains = {"boards.greenhouse.io", "jobs.lever.co"}
        for q in ats_qs:
            assert any(f"site:{d}" in q for d in domains)

    def test_ats_queries_include_base_terms(self):
        queries = build_queries([], [], [], ats_domains=_TINY_ATS)
        for q in queries:
            # All queries should have default terms (no keywords given)
            assert "internship" in q.lower() or "intern" in q.lower()

    def test_ats_with_locations_produces_cross_product(self):
        queries = build_queries(
            ["NYC", "Austin"], [], [], ats_domains=_TINY_ATS
        )
        ats_qs = [q for q in queries if "site:" in q]
        generic_qs = [q for q in queries if "site:" not in q]
        # 2 domains × 2 locations = 4 ATS queries
        assert len(ats_qs) == 4
        # 2 generic (one per location)
        assert len(generic_qs) == 2

    def test_ats_with_keywords_preserves_keywords(self):
        queries = build_queries(
            [], ["cybersecurity"], [], ats_domains=_TINY_ATS
        )
        for q in queries:
            assert "cybersecurity" in q

    def test_ats_domains_constant_has_expected_platforms(self):
        assert "workday" in ATS_DOMAINS
        assert "greenhouse" in ATS_DOMAINS
        assert "lever" in ATS_DOMAINS
        assert "smartrecruiters" in ATS_DOMAINS


# ---------------------------------------------------------------------------
# GoogleSearchSource.fetch — injected session
# ---------------------------------------------------------------------------


class TestGoogleSearchSourceFetch:
    def test_returns_list_of_raw_results(self):
        source = GoogleSearchSource(_config(), session=_mock_session(_make_items(3)))
        results = source.fetch([], [], [])
        assert isinstance(results, list)
        assert all(isinstance(r, RawSearchResult) for r in results)

    def test_result_fields_populated(self):
        source = GoogleSearchSource(_config(), session=_mock_session(_make_items(1)))
        result = source.fetch([], [], [])[0]
        assert result.url == "https://example.com/job/1"
        assert result.title == "Job 1"
        assert result.snippet == "Snippet 1"

    def test_capped_by_max_results(self):
        source = GoogleSearchSource(
            _config(max_results=3), session=_mock_session(_make_items(10))
        )
        results = source.fetch([], [], [])
        assert len(results) <= 3

    def test_empty_api_response_returns_empty_list(self):
        source = GoogleSearchSource(_config(), session=_mock_session_empty())
        assert source.fetch([], [], []) == []

    def test_deduplicates_by_url_across_queries(self):
        # Two locations → two queries, but items share the same URLs
        shared_items = _make_items(2)
        source = GoogleSearchSource(
            _config(max_results=20),
            session=_mock_session(shared_items),
        )
        results = source.fetch(["New York", "Austin"], [], [])
        urls = [r.url for r in results]
        assert len(urls) == len(set(urls)), "Duplicate URLs found"

    def test_http_error_returns_empty_gracefully(self):
        from requests.exceptions import HTTPError

        session = MagicMock()
        response = MagicMock()
        response.status_code = 403
        response.raise_for_status.side_effect = HTTPError(response=response)
        session.get.return_value = response

        source = GoogleSearchSource(_config(), session=session)
        results = source.fetch([], [], [])
        assert results == []

    def test_timeout_returns_empty_gracefully(self):
        from requests.exceptions import Timeout

        session = MagicMock()
        session.get.side_effect = Timeout()
        source = GoogleSearchSource(_config(), session=session)
        assert source.fetch([], [], []) == []

    def test_one_query_per_location(self):
        session = _mock_session(_make_items(1))
        source = GoogleSearchSource(_config(max_results=20), session=session)
        source.fetch(["New York", "Austin", "Boston"], [], [])
        # 3 locations → at least 3 GET calls (one per query, plus possible pagination)
        assert session.get.call_count >= 3

    def test_no_results_when_items_missing_link(self):
        bad_items = [{"title": "No link", "snippet": "..."}]  # missing "link"
        source = GoogleSearchSource(_config(), session=_mock_session(bad_items))
        assert source.fetch([], [], []) == []

    def test_ats_domains_produces_more_queries(self):
        """When ats_domains is passed, more GET requests are made."""
        session = _mock_session(_make_items(1))
        source = GoogleSearchSource(_config(max_results=50), session=session)
        # Without ATS: 1 query → 1 GET
        source.fetch([], [], [])
        calls_without = session.get.call_count

        session.reset_mock()
        source.fetch([], [], [], ats_domains=_TINY_ATS)
        calls_with = session.get.call_count

        assert calls_with > calls_without

    def test_ats_domains_none_unchanged_behavior(self):
        """ats_domains=None should behave identically to no argument."""
        session = _mock_session(_make_items(3))
        source = GoogleSearchSource(_config(), session=session)
        r1 = source.fetch([], [], [])
        session.reset_mock()
        r2 = source.fetch([], [], [], ats_domains=None)
        assert len(r1) == len(r2)


# ---------------------------------------------------------------------------
# GoogleSearchConfig defaults
# ---------------------------------------------------------------------------


class TestGoogleSearchConfig:
    def test_default_max_results(self):
        cfg = GoogleSearchConfig(api_key="k", cse_id="c")
        assert cfg.max_results == 10

    def test_default_posted_within_days_is_none(self):
        cfg = GoogleSearchConfig(api_key="k", cse_id="c")
        assert cfg.posted_within_days is None
