"""Unit tests for internship_engine.sources.brave_search.

All tests are network-free:
- BraveSearchSource is tested by injecting a mock requests.Session.
- 429 retry behaviour is tested with an injectable sleep_fn.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from internship_engine.sources.brave_search import (
    _PAGE_SIZE,
    BraveSearchConfig,
    BraveSearchSource,
)
from internship_engine.sources.google_search import RawSearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(max_results: int = 10) -> BraveSearchConfig:
    return BraveSearchConfig(api_key="test-brave-key", max_results=max_results)


def _make_web_results(
    n: int, url_prefix: str = "https://example.com/job/"
) -> list[dict]:
    """Build Brave API web result items."""
    return [
        {
            "url": f"{url_prefix}{i}",
            "title": f"Job {i}",
            "description": f"Snippet {i}",
        }
        for i in range(1, n + 1)
    ]


def _mock_session(web_results: list[dict], status_code: int = 200) -> MagicMock:
    """Return a session whose GET returns a Brave-shaped API response."""
    session = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status.return_value = None
    response.json.return_value = {"web": {"results": web_results}}
    session.get.return_value = response
    return session


def _mock_session_empty() -> MagicMock:
    session = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {}
    session.get.return_value = response
    return session


# ---------------------------------------------------------------------------
# X-Subscription-Token header
# ---------------------------------------------------------------------------


class TestBraveSessionHeaders:
    def test_default_session_sets_subscription_token(self):
        session = BraveSearchSource._default_session("my-secret-key")
        assert session.headers["X-Subscription-Token"] == "my-secret-key"

    def test_default_session_sets_accept_json(self):
        session = BraveSearchSource._default_session("k")
        assert session.headers["Accept"] == "application/json"


# ---------------------------------------------------------------------------
# BraveSearchSource.fetch — result parsing
# ---------------------------------------------------------------------------


class TestBraveSearchSourceFetch:
    def test_returns_list_of_raw_results(self):
        source = BraveSearchSource(
            _config(), session=_mock_session(_make_web_results(3))
        )
        results = source.fetch([], [], [])
        assert isinstance(results, list)
        assert all(isinstance(r, RawSearchResult) for r in results)

    def test_result_fields_populated(self):
        source = BraveSearchSource(
            _config(), session=_mock_session(_make_web_results(1))
        )
        result = source.fetch([], [], [])[0]
        assert result.url == "https://example.com/job/1"
        assert result.title == "Job 1"
        assert result.snippet == "Snippet 1"

    def test_capped_by_max_results(self):
        source = BraveSearchSource(
            _config(max_results=3),
            session=_mock_session(_make_web_results(20)),
        )
        results = source.fetch([], [], [])
        assert len(results) <= 3

    def test_empty_api_response_returns_empty_list(self):
        source = BraveSearchSource(_config(), session=_mock_session_empty())
        assert source.fetch([], [], []) == []

    def test_deduplicates_by_url_across_queries(self):
        shared_items = _make_web_results(2)
        source = BraveSearchSource(
            _config(max_results=20),
            session=_mock_session(shared_items),
        )
        results = source.fetch(["New York", "Austin"], [], [])
        urls = [r.url for r in results]
        assert len(urls) == len(set(urls)), "Duplicate URLs found"

    def test_no_results_when_url_missing(self):
        bad_items = [{"title": "No URL", "description": "..."}]
        source = BraveSearchSource(_config(), session=_mock_session(bad_items))
        assert source.fetch([], [], []) == []

    def test_one_query_per_location(self):
        session = _mock_session(_make_web_results(1))
        source = BraveSearchSource(_config(max_results=20), session=session)
        source.fetch(["New York", "Austin", "Boston"], [], [])
        assert session.get.call_count >= 3


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestBraveSearchPagination:
    def test_paginates_when_max_results_exceeds_page_size(self):
        """When max_results > PAGE_SIZE, multiple requests should be made."""
        # First call returns a full page, second call returns partial
        page1 = _make_web_results(_PAGE_SIZE, url_prefix="https://a.com/")
        page2 = _make_web_results(5, url_prefix="https://b.com/")

        session = MagicMock()
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.raise_for_status.return_value = None
        resp1.json.return_value = {"web": {"results": page1}}

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.raise_for_status.return_value = None
        resp2.json.return_value = {"web": {"results": page2}}

        session.get.side_effect = [resp1, resp2]

        source = BraveSearchSource(
            _config(max_results=25), session=session, sleep_fn=lambda _: None
        )
        results = source.fetch([], [], [])
        assert session.get.call_count == 2
        assert len(results) == 25

    def test_stops_on_empty_page(self):
        session = MagicMock()
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.raise_for_status.return_value = None
        resp1.json.return_value = {"web": {"results": _make_web_results(3)}}

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.raise_for_status.return_value = None
        resp2.json.return_value = {"web": {"results": []}}

        session.get.side_effect = [resp1, resp2]

        source = BraveSearchSource(
            _config(max_results=30), session=session, sleep_fn=lambda _: None
        )
        results = source.fetch([], [], [])
        # Should stop after seeing empty second page
        assert len(results) == 3

    def test_offset_param_sent_on_second_page(self):
        session = _mock_session(_make_web_results(_PAGE_SIZE))
        source = BraveSearchSource(
            _config(max_results=25), session=session, sleep_fn=lambda _: None
        )
        source.fetch([], [], [])
        # Second call should have offset parameter
        calls = session.get.call_args_list
        assert len(calls) >= 2
        second_call_params = (
            calls[1][1].get("params") or calls[1][0][1]
            if len(calls[1]) > 1
            else calls[1].kwargs.get("params", {})
        )
        assert second_call_params.get("offset") == _PAGE_SIZE


# ---------------------------------------------------------------------------
# HTTP 429 retry with exponential backoff
# ---------------------------------------------------------------------------


class TestBraveSearch429Retry:
    def test_retries_on_429_then_succeeds(self):
        """429 → backoff → success on second attempt."""
        session = MagicMock()

        resp_429 = MagicMock()
        resp_429.status_code = 429

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.raise_for_status.return_value = None
        resp_ok.json.return_value = {"web": {"results": _make_web_results(2)}}

        session.get.side_effect = [resp_429, resp_ok]

        sleep_calls = []
        source = BraveSearchSource(
            _config(), session=session, sleep_fn=lambda s: sleep_calls.append(s)
        )
        results = source.fetch([], [], [])

        assert len(results) == 2
        assert session.get.call_count == 2
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == pytest.approx(1.0)

    def test_exponential_backoff_timing(self):
        """429 → 429 → 429 → gives up after 3 retries."""
        session = MagicMock()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        session.get.return_value = resp_429

        sleep_calls = []
        source = BraveSearchSource(
            _config(), session=session, sleep_fn=lambda s: sleep_calls.append(s)
        )
        results = source.fetch([], [], [])

        assert results == []
        # 3 retries → 3 sleep calls with exponential backoff
        assert len(sleep_calls) == 3
        assert sleep_calls[0] == pytest.approx(1.0)
        assert sleep_calls[1] == pytest.approx(2.0)
        assert sleep_calls[2] == pytest.approx(4.0)

    def test_429_exhausted_returns_empty(self):
        session = MagicMock()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        session.get.return_value = resp_429

        source = BraveSearchSource(_config(), session=session, sleep_fn=lambda _: None)
        assert source.fetch([], [], []) == []


# ---------------------------------------------------------------------------
# Other error handling
# ---------------------------------------------------------------------------


class TestBraveSearchErrorHandling:
    def test_http_error_returns_empty_gracefully(self):
        from requests.exceptions import HTTPError

        session = MagicMock()
        response = MagicMock()
        response.status_code = 403
        response.raise_for_status.side_effect = HTTPError(response=response)
        session.get.return_value = response

        source = BraveSearchSource(_config(), session=session)
        assert source.fetch([], [], []) == []

    def test_timeout_returns_empty_gracefully(self):
        from requests.exceptions import Timeout

        session = MagicMock()
        session.get.side_effect = Timeout()
        source = BraveSearchSource(_config(), session=session)
        assert source.fetch([], [], []) == []

    def test_connection_error_returns_empty(self):
        from requests.exceptions import ConnectionError as ReqConnError

        session = MagicMock()
        session.get.side_effect = ReqConnError()
        source = BraveSearchSource(_config(), session=session)
        assert source.fetch([], [], []) == []


# ---------------------------------------------------------------------------
# BraveSearchConfig defaults
# ---------------------------------------------------------------------------


class TestBraveSearchConfig:
    def test_default_max_results(self):
        cfg = BraveSearchConfig(api_key="k")
        assert cfg.max_results == 10

    def test_default_posted_within_days_is_none(self):
        cfg = BraveSearchConfig(api_key="k")
        assert cfg.posted_within_days is None
