"""Brave Web Search API source.

Authentication
--------------
One environment variable (or .env entry) is required:

    IE_BRAVE_API_KEY   — Subscription token from https://brave.com/search/api/

The same variable is picked up automatically when injected via
GitHub Actions secrets.

Query construction
------------------
Reuses :func:`~internship_engine.sources.google_search.build_queries` so
that query logic is shared across providers.

Pagination
----------
The Brave API supports an ``offset`` parameter.  Each page returns up to
20 results.  The source paginates until ``max_results`` is reached or no
more results are available.

Rate limiting
-------------
HTTP 429 responses trigger exponential-backoff retries (up to 3 attempts).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

from internship_engine.sources.google_search import RawSearchResult, build_queries

logger = logging.getLogger(__name__)

# Brave Web Search API endpoint
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

# Results per page (API max is 20)
_PAGE_SIZE = 20

# Retry configuration for HTTP 429 rate limiting
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0  # seconds


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class BraveSearchConfig:
    """Configuration bundle for :class:`BraveSearchSource`."""

    api_key: str
    max_results: int = 10
    posted_within_days: int | None = None


# ---------------------------------------------------------------------------
# Source class
# ---------------------------------------------------------------------------


class BraveSearchSource:
    """Fetches raw search results from the Brave Web Search API.

    Parameters
    ----------
    config:
        :class:`BraveSearchConfig` with credentials and request options.
    session:
        Optional ``requests.Session``.  A new session is created when *None*.
        Pass a mock session in tests to avoid real network calls.
    sleep_fn:
        Callable used for backoff delays.  Defaults to :func:`time.sleep`.
        Override in tests to avoid real delays.
    """

    def __init__(
        self,
        config: BraveSearchConfig,
        session: requests.Session | None = None,
        sleep_fn=time.sleep,
    ) -> None:
        self._config = config
        self._session = session or self._default_session(config.api_key)
        self._sleep = sleep_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        locations: list[str],
        keywords: list[str],
        categories: list[str],
    ) -> list[RawSearchResult]:
        """Run queries and return deduplicated search results.

        Shares the same interface as
        :meth:`~internship_engine.sources.google_search.GoogleSearchSource.fetch`
        so both providers are interchangeable from the CLI pipeline.
        """
        queries = build_queries(locations, keywords, categories)

        seen_urls: set[str] = set()
        results: list[RawSearchResult] = []

        for q in queries:
            if len(results) >= self._config.max_results:
                break
            for item in self._paginate(q):
                url = (item.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append(
                    RawSearchResult(
                        url=url,
                        title=(item.get("title") or "").strip(),
                        snippet=(item.get("description") or "").strip(),
                    )
                )
                if len(results) >= self._config.max_results:
                    break

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _paginate(self, query: str) -> list[dict]:
        """Return all web result items for *query*, paginating as needed."""
        items: list[dict] = []
        offset = 0

        while len(items) < self._config.max_results:
            batch = self._search(query, offset=offset)
            if not batch:
                break
            items.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break  # last page
            offset += _PAGE_SIZE

        return items[: self._config.max_results]

    def _search(self, query: str, offset: int = 0) -> list[dict]:
        """Execute a single API request with 429-retry logic.

        Returns the ``web.results`` list from the Brave response, or ``[]``.
        """
        params: dict[str, str | int] = {
            "q": query,
            "count": _PAGE_SIZE,
        }
        if offset > 0:
            params["offset"] = offset

        backoff = _INITIAL_BACKOFF
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = self._session.get(_BRAVE_URL, params=params, timeout=15)
                if resp.status_code == 429:
                    if attempt < _MAX_RETRIES:
                        logger.warning(
                            "Brave API 429 rate-limited; retrying in %.1fs"
                            " (attempt %d/%d)",
                            backoff,
                            attempt + 1,
                            _MAX_RETRIES,
                        )
                        self._sleep(backoff)
                        backoff *= 2
                        continue
                    logger.warning(
                        "Brave API 429 rate-limited; exhausted %d retries",
                        _MAX_RETRIES,
                    )
                    return []

                resp.raise_for_status()
                data = resp.json()
                return data.get("web", {}).get("results", [])

            except requests.exceptions.Timeout:
                logger.warning("Brave Search API timed out for query: %r", query)
                return []
            except requests.exceptions.HTTPError as exc:
                logger.warning(
                    "Brave Search API HTTP error %s for query: %r",
                    exc.response.status_code,
                    query,
                )
                return []
            except requests.exceptions.RequestException as exc:
                logger.warning("Brave Search API request failed: %s", exc)
                return []

        return []  # pragma: no cover – unreachable but satisfies linters

    # ------------------------------------------------------------------
    # Session factory
    # ------------------------------------------------------------------

    @staticmethod
    def _default_session(api_key: str) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            }
        )
        return session
