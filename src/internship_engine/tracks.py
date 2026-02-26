"""Track-based scoring and filtering for internship postings.

A *track* is a high-level domain (cyber, IT, SWE, data) used to filter
postings by relevance.  Each posting is scored against keyword lists; only
postings meeting the minimum threshold are kept.

``Track.ALL`` is a special no-op value that passes every posting.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from internship_engine.models import JobPosting


# ---------------------------------------------------------------------------
# Track enum
# ---------------------------------------------------------------------------


class Track(str, Enum):
    """Target domain track for filtering internship postings."""

    CYBER = "cyber"
    IT = "it"
    SWE = "swe"
    DATA = "data"
    ALL = "all"


# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

# Points: strong keyword in title = +10, in description = +5
#         weak keyword in title   = +3,  in description = +1
_TRACK_KEYWORDS: dict[Track, dict[str, list[str]]] = {
    Track.CYBER: {
        "strong": [
            "cybersecurity",
            "cyber security",
            "information security",
            "infosec",
            "soc analyst",
            "soc intern",
            "penetration test",
            "pentest",
            "security analyst",
            "security engineer",
            "network security",
            "vulnerability",
            "threat intelligence",
            "malware",
            "forensics",
            "incident response",
            "security operations",
            "ethical hacking",
        ],
        "weak": ["security", "cyber", "firewall", "compliance", "audit"],
    },
    Track.IT: {
        "strong": [
            "help desk",
            "helpdesk",
            "desktop support",
            "it support",
            "systems administrator",
            "sysadmin",
            "network administrator",
            "it analyst",
            "it technician",
            "it specialist",
            "service desk",
            "information technology intern",
        ],
        "weak": [
            "it intern",
            "tech support",
            "systems",
            "network",
            "infrastructure",
            "windows",
            "active directory",
            "hardware",
            "troubleshoot",
        ],
    },
    Track.SWE: {
        "strong": [
            "software engineer",
            "software developer",
            "swe intern",
            "backend engineer",
            "frontend engineer",
            "full stack",
            "fullstack",
            "web developer",
            "application developer",
            "mobile developer",
            "ios developer",
            "android developer",
            "devops",
            "site reliability",
            "platform engineer",
        ],
        "weak": [
            "developer",
            "programmer",
            "coding",
            "python",
            "java",
            "javascript",
            "react",
            "node",
            "backend",
            "frontend",
            "api",
            "kubernetes",
            "docker",
        ],
    },
    Track.DATA: {
        "strong": [
            "data analyst",
            "data scientist",
            "data engineer",
            "business intelligence",
            "bi analyst",
            "machine learning",
            "ml engineer",
            "analytics engineer",
            "data analytics",
            "data science",
            "quantitative analyst",
        ],
        "weak": [
            "data",
            "analytics",
            "sql",
            "etl",
            "tableau",
            "power bi",
            "pandas",
            "numpy",
            "statistics",
            "reporting",
            "dashboard",
        ],
    },
}

# Keywords that suggest a non-technical role; each hit applies a penalty
_NEGATIVE_KEYWORDS: list[str] = [
    "sales",
    "marketing",
    "real estate",
    "insurance",
    "retail",
    "cashier",
    "barista",
    "social media manager",
    "customer service",
    "store",
    "restaurant",
    "hospitality",
]

_MIN_SCORE: int = 3
_TITLE_STRONG_SCORE: int = 10  # instant pass threshold (score from title alone)
_PENALTY: int = 3  # points deducted per negative keyword hit


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_track(posting: JobPosting, track: Track) -> int:
    """Score *posting* against *track*'s keyword lists.

    Returns a non-negative integer; higher means stronger match.
    ``Track.ALL`` always returns 1 (unconditional pass).
    """
    if track == Track.ALL:
        return 1

    kws = _TRACK_KEYWORDS[track]
    title = posting.title.lower()
    desc = (posting.description or "").lower()
    full_text = title + " " + desc

    score = 0
    for kw in kws.get("strong", []):
        if kw in title:
            score += 10
        elif kw in desc:
            score += 5

    for kw in kws.get("weak", []):
        if kw in title:
            score += 3
        elif kw in desc:
            score += 1

    for kw in _NEGATIVE_KEYWORDS:
        if kw in full_text:
            score -= _PENALTY

    return max(0, score)


def score_all_tracks(posting: JobPosting) -> dict[Track, int]:
    """Return a score for every non-ALL track."""
    return {t: score_track(posting, t) for t in Track if t != Track.ALL}


def best_tracks(
    posting: JobPosting, *, min_score: int = _MIN_SCORE
) -> list[Track]:
    """Return the tracks for which *posting* meets *min_score*."""
    return [t for t, s in score_all_tracks(posting).items() if s >= min_score]


def track_match_label(
    posting: JobPosting, *, min_score: int = _MIN_SCORE
) -> str:
    """Return a pipe-separated string of matching track names.

    Returns ``""`` when no track matches.  Example: ``"cyber|it"``.
    """
    matched = best_tracks(posting, min_score=min_score)
    if not matched:
        return ""
    return "|".join(t.value for t in matched)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def filter_by_track(
    postings: list[JobPosting],
    track: Track,
    *,
    min_score: int = _MIN_SCORE,
) -> list[JobPosting]:
    """Return postings whose score for *track* is >= *min_score*.

    ``Track.ALL`` is a no-op — all postings are returned unchanged.
    """
    if track == Track.ALL:
        return postings
    return [p for p in postings if score_track(p, track) >= min_score]


# ---------------------------------------------------------------------------
# Quality query helpers
# ---------------------------------------------------------------------------

_TRACK_QUERY_TEMPLATES: dict[Track, str] = {
    Track.CYBER: (
        '("intern" OR "internship") (cybersecurity OR "information security"'
        ' OR SOC OR "security analyst" OR "network security"'
        ' OR "penetration test")'
    ),
    Track.IT: (
        '("intern" OR "internship") ("IT" OR "help desk" OR "systems"'
        ' OR "desktop support" OR "network")'
    ),
    Track.SWE: (
        '("intern" OR "internship") ("software engineer" OR SWE OR backend'
        ' OR frontend OR "full stack" OR developer)'
    ),
    Track.DATA: (
        '("intern" OR "internship") (data OR analytics OR "data analyst"'
        ' OR "business intelligence" OR SQL OR "machine learning")'
    ),
}


def track_query_terms(track: Track) -> list[str]:
    """Return keyword strings to inject into search queries for *track*.

    Returns an empty list for ``Track.ALL`` (let the user's own keywords drive
    the query, or fall back to default internship terms).
    """
    if track == Track.ALL:
        return []
    template = _TRACK_QUERY_TEMPLATES.get(track, "")
    return [template] if template else []
