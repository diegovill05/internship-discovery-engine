"""HTML extractor for structured job-posting data.

Strategy
--------
1. Fetch the URL with ``requests`` (retry on transient errors, short timeout).
2. Search every ``<script type="application/ld+json">`` block for a JSON-LD
   object whose ``@type`` is ``"JobPosting"`` (including nested ``@graph``
   arrays).  The ``@type`` value may be a string, a list, or use a
   ``schema:`` / full-URL prefix.
3. Parse the canonical schema.org JobPosting fields into an
   :class:`ExtractionResult`.
4. When no JSON-LD is found, fall back to ``<meta>`` / Open Graph tags
   for basic title, description, and company (site name).
5. If the page is unreachable or contains no structured data, return an
   :class:`ExtractionResult` with ``blocked=True`` so the caller can fall
   back to the raw search-result metadata.

Date confidence
---------------
``date_posted_confidence`` is set to:
- ``EXACT``     — ``datePosted`` was present *and* parsed successfully.
- ``UNKNOWN``   — ``datePosted`` was absent, empty, or unparseable.
  (``ESTIMATED`` is reserved for future heuristic date inference.)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from internship_engine.models import DatePostedConfidence

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; InternshipDiscoveryBot/0.1; "
    "+https://github.com/example/internship-discovery-engine)"
)
_TIMEOUT = 10  # seconds per request
_RETRY_TOTAL = 3
_RETRY_BACKOFF = 0.4
_RETRY_ON_STATUS = [429, 500, 502, 503, 504]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """HTTP response metadata captured during :meth:`Extractor.fetch_and_extract`.

    Allows downstream consumers (e.g. active-check) to reuse the
    already-fetched page instead of making a second HTTP request.
    """

    status_code: int = 0
    html: str = ""
    final_url: str = ""
    error: str = ""


@dataclass
class ExtractionResult:
    """Data extracted from a single job-posting page.

    All string fields default to ``""``; date/url fields default to ``None``.
    When ``blocked`` is True the page was inaccessible and all other fields
    carry their default empty values.
    """

    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    date_posted: Optional[date] = None
    date_posted_confidence: DatePostedConfidence = DatePostedConfidence.UNKNOWN
    apply_url: Optional[str] = None
    employment_type: str = ""
    blocked: bool = False
    fetch_result: Optional[FetchResult] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_html(html: str, source_url: str = "") -> ExtractionResult:
    """Extract job-posting fields from *html* without making any network calls.

    This is the pure, synchronous, easily-testable core of the extractor.

    Parameters
    ----------
    html:
        Raw HTML string of the job-posting page.
    source_url:
        The URL from which the HTML was fetched.  Used to avoid treating
        the posting URL itself as a separate apply URL.

    Returns
    -------
    ExtractionResult
        Populated from the first JSON-LD ``JobPosting`` block found.  When
        no JSON-LD is present, falls back to ``<meta>`` / Open Graph tags.
        Returns an empty result (all defaults) if neither source provides
        data.
    """
    schema, soup = _find_job_posting_schema(html)

    if schema is not None:
        date_posted, confidence = _parse_date(schema.get("datePosted"))
        apply_url = _parse_apply_url(schema, source_url)

        return ExtractionResult(
            title=_text(schema.get("title")),
            company=_parse_company(schema),
            location=_parse_location(schema),
            description=_text(schema.get("description")),
            date_posted=date_posted,
            date_posted_confidence=confidence,
            apply_url=apply_url,
            employment_type=_text(schema.get("employmentType")),
        )

    # No JSON-LD — try meta / Open Graph tags as a lightweight fallback
    return _fallback_from_meta(soup)


class Extractor:
    """Fetches a URL and extracts structured job data from its HTML.

    Parameters
    ----------
    session:
        Optional ``requests.Session``.  A new session with retry logic and a
        descriptive User-Agent is created when *None*.  Pass a mock session
        in tests to avoid real network calls.
    """

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or _make_session()

    def fetch_and_extract(self, url: str) -> ExtractionResult:
        """Fetch *url* and return an :class:`ExtractionResult`.

        On any network / HTTP error the result has ``blocked=True`` and all
        other fields are empty defaults — the caller should fall back to
        search-result metadata in that case.

        Parameters
        ----------
        url:
            The job-posting URL to fetch.
        """
        try:
            resp = self._session.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            logger.warning("Extractor timed out fetching %s", url)
            return ExtractionResult(
                blocked=True,
                fetch_result=FetchResult(error="timeout"),
            )
        except requests.exceptions.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            logger.warning(
                "Extractor received HTTP %s for %s",
                code,
                url,
            )
            return ExtractionResult(
                blocked=True,
                fetch_result=FetchResult(
                    status_code=code,
                    html=exc.response.text if exc.response is not None else "",
                    final_url=(
                        str(exc.response.url) if exc.response is not None else url
                    ),
                ),
            )
        except requests.exceptions.RequestException as exc:
            logger.warning("Extractor request failed for %s: %s", url, exc)
            return ExtractionResult(
                blocked=True,
                fetch_result=FetchResult(error=str(exc)),
            )

        fetch_result = FetchResult(
            status_code=resp.status_code,
            html=resp.text,
            final_url=str(resp.url),
        )
        result = parse_html(resp.text, source_url=url)
        result.fetch_result = fetch_result
        return result


# ---------------------------------------------------------------------------
# JSON-LD helpers
# ---------------------------------------------------------------------------


def _find_job_posting_schema(
    html: str,
) -> tuple[dict | None, BeautifulSoup]:
    """Return ``(schema, soup)`` from *html*.

    *schema* is the first JSON-LD ``JobPosting`` object found, or ``None``.
    The :class:`BeautifulSoup` instance is always returned so callers can
    attempt meta-tag fallback without re-parsing.
    """
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue

        found = _extract_job_posting(data)
        if found is not None:
            return found, soup

    return None, soup


def _is_job_posting(type_value: object) -> bool:
    """Return True when *type_value* represents a ``JobPosting`` type.

    Accepts the following forms used in real-world JSON-LD:

    * ``"JobPosting"``
    * ``["JobPosting"]`` or ``["JobPosting", "OtherType"]``
    * ``"schema:JobPosting"``
    * ``"https://schema.org/JobPosting"``
    """
    if isinstance(type_value, list):
        return any(_is_job_posting(item) for item in type_value)
    if not isinstance(type_value, str):
        return False
    # Strip known prefixes, then compare
    normalized = type_value
    for prefix in ("https://schema.org/", "http://schema.org/", "schema:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized == "JobPosting"


def _extract_job_posting(data: object) -> dict | None:
    """Recursively search *data* for a JobPosting dict."""
    if isinstance(data, dict):
        if _is_job_posting(data.get("@type")):
            return data
        # Check @graph array (common pattern)
        for item in data.get("@graph", []):
            result = _extract_job_posting(item)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _extract_job_posting(item)
            if result is not None:
                return result
    return None


# ---------------------------------------------------------------------------
# Meta / Open Graph fallback
# ---------------------------------------------------------------------------


def _fallback_from_meta(soup: BeautifulSoup) -> ExtractionResult:
    """Build an :class:`ExtractionResult` from ``<meta>`` / OG tags.

    Called only when no JSON-LD ``JobPosting`` was found.  Extracts:

    * **title** — ``og:title``, falling back to the ``<title>`` element.
    * **description** — ``og:description``, then ``<meta name="description">``.
    * **company** — ``og:site_name``.

    All other fields keep their empty/default values.  Because this data
    is not from a structured schema, ``date_posted_confidence`` stays
    ``UNKNOWN``.
    """
    title = _meta_content(soup, property="og:title")
    if not title:
        tag = soup.find("title")
        title = tag.get_text(strip=True) if tag else ""

    description = _meta_content(soup, property="og:description")
    if not description:
        description = _meta_content(soup, name="description")

    company = _meta_content(soup, property="og:site_name")

    return ExtractionResult(
        title=title,
        company=company,
        description=description,
    )


def _meta_content(soup: BeautifulSoup, **attrs: str) -> str:
    """Return the ``content`` attribute of the first matching ``<meta>`` tag."""
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        return str(tag["content"]).strip()
    return ""


# ---------------------------------------------------------------------------
# Field-level parsers
# ---------------------------------------------------------------------------


def _text(value: object) -> str:
    """Coerce *value* to a stripped string, or return ''."""
    if value is None:
        return ""
    return str(value).strip()


def _parse_company(schema: dict) -> str:
    org = schema.get("hiringOrganization", {})
    if isinstance(org, str):
        return org.strip()
    if isinstance(org, dict):
        return _text(org.get("name"))
    return ""


def _parse_location(schema: dict) -> str:
    """Extract a human-readable location string from a JobPosting schema."""
    loc = schema.get("jobLocation")

    # Remote-work indicator takes priority
    job_loc_type = _text(schema.get("jobLocationType")).upper()
    if job_loc_type == "TELECOMMUTE":
        return "Remote"

    if loc is None:
        return ""
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    if isinstance(loc, str):
        return loc.strip()

    address = loc.get("address", {})
    if isinstance(address, str):
        return address.strip()
    if not isinstance(address, dict):
        return ""

    locality = _text(address.get("addressLocality"))
    region = _text(address.get("addressRegion"))
    country = _text(address.get("addressCountry"))

    parts: list[str] = []
    if locality:
        parts.append(locality)
    if region:
        parts.append(region)
    # Only append country when it adds information (omit "US" when city+state present)
    if country and not parts:
        parts.append(country)
    elif country and country not in ("US", "USA", "United States"):
        parts.append(country)

    return ", ".join(parts)


def _parse_date(
    date_str: object,
) -> tuple[Optional[date], DatePostedConfidence]:
    """Parse a schema.org datePosted string into a (date, confidence) pair.

    Uses :func:`datetime.fromisoformat` (Python 3.11+) which accepts all
    ISO 8601 variants including timezone designators and the ``Z`` suffix.
    Returns ``(None, UNKNOWN)`` for any unparseable or non-string input.
    """
    if not date_str or not isinstance(date_str, str):
        return None, DatePostedConfidence.UNKNOWN

    raw = date_str.strip()
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed.date(), DatePostedConfidence.EXACT
    except ValueError:
        pass

    logger.debug("Could not parse datePosted %r", date_str)
    return None, DatePostedConfidence.UNKNOWN


def _parse_apply_url(schema: dict, source_url: str) -> Optional[str]:
    """Return an explicit apply URL if it differs meaningfully from source_url."""
    apply = _text(schema.get("url"))
    if apply and apply.rstrip("/") != source_url.rstrip("/"):
        return apply
    return None


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------


def _make_session() -> requests.Session:
    """Return a requests.Session with retry logic and a polite User-Agent."""
    session = requests.Session()
    retry = Retry(
        total=_RETRY_TOTAL,
        backoff_factor=_RETRY_BACKOFF,
        status_forcelist=_RETRY_ON_STATUS,
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
    )
    return session
