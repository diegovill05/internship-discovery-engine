"""Google Custom Search JSON API source.

Authentication
--------------
Two environment variables (or .env entries) are required:

    IE_GOOGLE_API_KEY   — API key from Google Cloud Console
    IE_GOOGLE_CSE_ID    — Programmable Search Engine ID

Query construction
------------------
Queries are assembled from:
  1. Explicit ``keywords`` passed by the caller.
  2. Category names (e.g. "software", "data") when provided.
  3. Internship/co-op terms — defaults to ["internship", "intern"].
  4. One location string per query (one query is emitted per location;
     no location means a single query with no geo-restriction).

Pagination
----------
The API returns at most 10 results per request.  When ``max_results``
exceeds 10 the source makes multiple paginated requests (using the
``start`` parameter) up to the API's hard ceiling of 100 results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

# Default terms appended to every query so results are internship-focused.
_DEFAULT_TERMS: list[str] = ["internship", "intern", "co-op"]

# Google Custom Search API endpoint
_CSE_URL = "https://www.googleapis.com/customsearch/v1"

# API returns at most 10 items per request; max start index is 91 (→ 100 results)
_PAGE_SIZE = 10
_MAX_START = 91


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawSearchResult:
    """A single result item returned by the Google Custom Search API."""

    url: str
    title: str
    snippet: str


@dataclass
class GoogleSearchConfig:
    """Configuration bundle for :class:`GoogleSearchSource`."""

    api_key: str
    cse_id: str
    max_results: int = 10
    posted_within_days: int | None = None


# ---------------------------------------------------------------------------
# Query builder (pure function — easily unit-tested)
# ---------------------------------------------------------------------------


def build_queries(
    locations: list[str],
    keywords: list[str],
    categories: list[str],
    terms: list[str] | None = None,
) -> list[str]:
    """Return a list of Google search query strings.

    One query is produced per location (or a single query when
    ``locations`` is empty).  Each query has the form::

        [keywords] [categories] [terms] [location]

    Parameters
    ----------
    locations:
        Geographic filters (e.g. ["New York, NY", "San Francisco, CA"]).
        Pass an empty list for a location-agnostic search.
    keywords:
        Free-form keyword tokens (e.g. ["Python", "React"]).
    categories:
        Category names contributed to the query (e.g. ["software", "data"]).
    terms:
        Internship / co-op terms.  Defaults to ``["internship", "intern"]``
        when *None*.

    Returns
    -------
    list[str]
        One query string per location, or a single string when no locations
        are given.  Never returns an empty list.
    """
    effective_terms = terms if terms is not None else _DEFAULT_TERMS[:2]

    base_tokens: list[str] = []
    if keywords:
        base_tokens.extend(keywords)
    if categories:
        base_tokens.extend(categories)
    base_tokens.extend(effective_terms)

    base = " ".join(base_tokens)

    if not locations:
        return [base]

    return [f"{base} {loc}" for loc in locations]


# ---------------------------------------------------------------------------
# Source class
# ---------------------------------------------------------------------------


class GoogleSearchSource:
    """Fetches raw search results from the Google Custom Search JSON API.

    Parameters
    ----------
    config:
        :class:`GoogleSearchConfig` with credentials and request options.
    session:
        Optional ``requests.Session`` to use.  A new session with sensible
        defaults is created when *None* (the typical production path).
        Pass a mock session in tests to avoid real network calls.
    """

    def __init__(
        self,
        config: GoogleSearchConfig,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config
        self._session = session or self._default_session()

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

        Parameters
        ----------
        locations:
            Location strings to restrict results (one query per entry).
        keywords:
            Free-form keyword tokens included in every query.
        categories:
            Category names included in every query.

        Returns
        -------
        list[RawSearchResult]
            Unique results across all queries, capped at
            ``config.max_results`` total entries.
        """
        queries = build_queries(locations, keywords, categories)

        seen_urls: set[str] = set()
        results: list[RawSearchResult] = []

        for q in queries:
            if len(results) >= self._config.max_results:
                break
            for item in self._paginate(q):
                url = item.get("link", "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append(
                    RawSearchResult(
                        url=url,
                        title=item.get("title", "").strip(),
                        snippet=item.get("snippet", "").strip(),
                    )
                )
                if len(results) >= self._config.max_results:
                    break

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _paginate(self, query: str) -> list[dict]:
        """Yield all items for *query*, paginating up to ``max_results``."""
        items: list[dict] = []
        start = 1

        while start <= _MAX_START and len(items) < self._config.max_results:
            batch = self._search(query, start=start)
            if not batch:
                break
            items.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break  # last page
            start += _PAGE_SIZE

        return items[: self._config.max_results]

    def _search(self, query: str, start: int = 1) -> list[dict]:
        """Execute a single API request; return the ``items`` list or []."""
        params: dict[str, str | int] = {
            "key": self._config.api_key,
            "cx": self._config.cse_id,
            "q": query,
            "num": _PAGE_SIZE,
        }
        if start > 1:
            params["start"] = start

        try:
            resp = self._session.get(_CSE_URL, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json().get("items", [])
        except requests.exceptions.Timeout:
            logger.warning("Google Search API timed out for query: %r", query)
        except requests.exceptions.HTTPError as exc:
            logger.warning("Google Search API HTTP error %s for query: %r", exc.response.status_code, query)
        except requests.exceptions.RequestException as exc:
            logger.warning("Google Search API request failed: %s", exc)

        return []

    # ------------------------------------------------------------------
    # Session factory
    # ------------------------------------------------------------------

    @staticmethod
    def _default_session() -> requests.Session:
        session = requests.Session()
        session.headers.update({"Accept": "application/json"})
        return session
