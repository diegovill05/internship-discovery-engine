"""Lightweight check for whether a job posting URL is still active.

Strategy
--------
1. GET the URL (follow redirects, short timeout).
2. HTTP 404/410          → INACTIVE
3. HTTP 403/429          → UNKNOWN  (blocked, not conclusive)
4. HTTP ≥500             → UNKNOWN  (server error)
5. HTTP 200, page text contains a *closed signal*  → INACTIVE
6. HTTP 200, no closed signals                     → ACTIVE
   (if an "apply" element is also detected the reason notes it)

Timeout / connection errors return UNKNOWN to avoid false positives.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

from internship_engine.models import ActiveStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Closed-posting signal patterns (case-insensitive substring match)
# ---------------------------------------------------------------------------

_CLOSED_SIGNALS: tuple[str, ...] = (
    "no longer available",
    "position has been filled",
    "job closed",
    "not accepting applications",
    "requisition closed",
    "this posting has expired",
    "job listing is no longer",
    "job has been filled",
    "position is no longer available",
    "this job is no longer",
    "listing has been removed",
    "role has been filled",
)

# Apply-presence heuristic — boosts confidence of ACTIVE verdict
_APPLY_SIGNALS: tuple[str, ...] = (
    "apply now",
    "apply for this",
    "submit application",
    "apply online",
    'type="submit"',
)

# HTTP status codes that unambiguously mean "gone"
_GONE_CODES: frozenset[int] = frozenset({404, 410})

# HTTP status codes that are blocked/rate-limited (inconclusive)
_BLOCKED_CODES: frozenset[int] = frozenset({401, 403, 429})


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ActiveCheckResult:
    """Result of a single active-check request.

    Parameters
    ----------
    status:
        One of :class:`~internship_engine.models.ActiveStatus`.
    reason:
        Human-readable explanation (e.g. ``"HTTP 404"`` or
        ``"closed signal: 'position has been filled'"``.
    """

    status: ActiveStatus
    reason: str = field(default="")

    def __bool__(self) -> bool:  # pragma: no cover
        return self.status == ActiveStatus.ACTIVE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_active(
    url: str,
    session: requests.Session | None = None,
    *,
    timeout: float = 8.0,
) -> ActiveCheckResult:
    """Return an :class:`ActiveCheckResult` for *url*.

    Parameters
    ----------
    url:
        The posting URL to check.
    session:
        Optional pre-configured ``requests.Session``.  A fresh session is
        created if not provided.  Pass a mock session in tests.
    timeout:
        Request timeout in seconds (default 8).

    Returns
    -------
    ActiveCheckResult
        Never raises; all exceptions are caught and mapped to UNKNOWN.
    """
    s = session or requests.Session()
    try:
        resp = s.get(url, timeout=timeout, allow_redirects=True)
    except requests.exceptions.Timeout:
        logger.debug("active_check: timeout for %s", url)
        return ActiveCheckResult(ActiveStatus.UNKNOWN, "request timed out")
    except requests.exceptions.RequestException as exc:
        logger.debug("active_check: request failed for %s: %s", url, exc)
        return ActiveCheckResult(ActiveStatus.UNKNOWN, f"request failed: {exc}")

    code = resp.status_code

    if code in _GONE_CODES:
        return ActiveCheckResult(ActiveStatus.INACTIVE, f"HTTP {code}")

    if code in _BLOCKED_CODES:
        return ActiveCheckResult(
            ActiveStatus.UNKNOWN, f"HTTP {code} — page blocked"
        )

    if code >= 500:
        return ActiveCheckResult(
            ActiveStatus.UNKNOWN, f"HTTP {code} server error"
        )

    if code == 200:
        html_lower = resp.text.lower()
        for signal in _CLOSED_SIGNALS:
            if signal in html_lower:
                return ActiveCheckResult(
                    ActiveStatus.INACTIVE,
                    f"closed signal: '{signal}'",
                )

        # Apply heuristic: note it in the reason, but don't block on absence
        has_apply = any(sig in html_lower for sig in _APPLY_SIGNALS)
        reason = (
            "apply button detected"
            if has_apply
            else "no closed signals found"
        )
        return ActiveCheckResult(ActiveStatus.ACTIVE, reason)

    # Unexpected 2xx/3xx after redirect
    return ActiveCheckResult(ActiveStatus.UNKNOWN, f"HTTP {code}")
