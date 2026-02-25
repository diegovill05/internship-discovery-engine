"""Unit tests for internship_engine.sources.google_search.

All tests are network-free:
- build_queries() is a pure function tested directly.
- GoogleSearchSource is tested by injecting a mock requests.Session.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from internship_engine.sources.google_search import (
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
