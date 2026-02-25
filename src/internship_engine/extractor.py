"""HTML extractor for structured job-posting data.

Strategy
--------
1. Fetch the URL with ``requests`` (retry on transient errors, short timeout).
2. Search every ``<script type="application/ld+json">`` block for a JSON-LD
   object whose ``@type`` is ``"JobPosting"`` (including nested ``@graph``
   arrays).
3. Parse the canonical schema.org JobPosting fields into an
   :class:`ExtractionResult`.
4. If the page is unreachable or contains no structured data, return an
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
# Result dataclass
# ---------------------------------------------------------------------------


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
        Populated from the first JSON-LD ``JobPosting`` block found, or an
        empty result (all defaults) if no suitable schema is present.
    """
    schema = _find_job_posting_schema(html)
    if schema is None:
        return ExtractionResult()

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
            return ExtractionResult(blocked=True)
        except requests.exceptions.HTTPError as exc:
            logger.warning(
                "Extractor received HTTP %s for %s",
                exc.response.status_code,
                url,
            )
            return ExtractionResult(blocked=True)
        except requests.exceptions.RequestException as exc:
            logger.warning("Extractor request failed for %s: %s", url, exc)
            return ExtractionResult(blocked=True)

        return parse_html(resp.text, source_url=url)


# ---------------------------------------------------------------------------
# JSON-LD helpers
# ---------------------------------------------------------------------------


def _find_job_posting_schema(html: str) -> dict | None:
    """Return the first JSON-LD JobPosting object found in *html*, or None."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue

        found = _extract_job_posting(data)
        if found is not None:
            return found

    return None


def _extract_job_posting(data: object) -> dict | None:
    """Recursively search *data* for a JobPosting dict."""
    if isinstance(data, dict):
        if data.get("@type") == "JobPosting":
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
