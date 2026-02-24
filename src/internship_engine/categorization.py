"""Keyword-based job posting categorization.

The categorizer performs a greedy, ordered scan of ``_CATEGORY_KEYWORDS``.
The first category whose keyword list contains a match (substring, case-
insensitive) against the combined title + description wins.  This keeps
the logic deterministic and easy to extend.
"""

from __future__ import annotations

from internship_engine.models import Category, JobPosting

# ---------------------------------------------------------------------------
# Keyword registry
# ---------------------------------------------------------------------------
# Keys are tried in insertion order (Python 3.7+), so place more-specific
# categories before generic ones to get the most precise label.

_CATEGORY_KEYWORDS: dict[Category, list[str]] = {
    Category.DATA: [
        "data science",
        "machine learning",
        "deep learning",
        "artificial intelligence",
        "computer vision",
        "natural language",
        "nlp",
        "research scientist",
        "ml engineer",
        "data engineer",
        "data analyst",
        "analytics",
        "data",
    ],
    Category.PRODUCT: [
        "product manager",
        "product management",
        "product owner",
        "program manager",
    ],
    Category.DESIGN: [
        "user experience",
        "user interface",
        "ux researcher",
        "ux designer",
        "ui designer",
        "graphic designer",
        "visual designer",
        "design",
    ],
    Category.FINANCE: [
        "quantitative",
        "investment banking",
        "financial analyst",
        "accounting",
        "finance",
        "trading",
        "quant",
    ],
    Category.MARKETING: [
        "digital marketing",
        "content marketing",
        "growth marketing",
        "seo",
        "copywriting",
        "social media",
        "marketing",
    ],
    # SOFTWARE is intentionally last so that DATA / PRODUCT / DESIGN roles
    # that mention "engineer" are not misclassified.
    Category.SOFTWARE: [
        "software engineer",
        "software developer",
        "backend",
        "frontend",
        "front-end",
        "back-end",
        "fullstack",
        "full-stack",
        "full stack",
        "devops",
        "site reliability",
        "sre",
        "platform engineer",
        "mobile developer",
        "ios developer",
        "android developer",
        "web developer",
        "api developer",
        "infrastructure engineer",
        "developer",
        "engineer",
    ],
}


def categorize(posting: JobPosting) -> Category:
    """Return the best-matching :class:`Category` for *posting*.

    Matching is performed on the lower-cased concatenation of
    ``title`` and ``description``.  Returns :attr:`Category.OTHER`
    when no keyword matches.
    """
    haystack = f"{posting.title} {posting.description}".lower()

    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in haystack:
                return category

    return Category.OTHER
