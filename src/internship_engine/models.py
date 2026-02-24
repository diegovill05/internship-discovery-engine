"""Core data models for the Internship Discovery Engine."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Category(str, Enum):
    """High-level category assigned to a job posting."""

    SOFTWARE = "software"
    DATA = "data"
    PRODUCT = "product"
    DESIGN = "design"
    FINANCE = "finance"
    MARKETING = "marketing"
    OTHER = "other"


class DatePostedConfidence(str, Enum):
    """Confidence level for the ``date_posted`` field.

    EXACT
        The date was explicitly present in a structured schema (JSON-LD
        ``datePosted``) and is trustworthy.
    ESTIMATED
        The date was inferred (e.g. from snippet text "Posted 3 days ago")
        and may be approximate.
    UNKNOWN
        No date information was available; ``date_posted`` will be ``None``.
    """

    EXACT = "exact"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class JobPosting(BaseModel):
    """Immutable representation of a single internship / job posting.

    Fields
    ------
    title:                  Role title as scraped from the source.
    company:                Hiring company name.
    location:               Raw location string (e.g. "New York, NY" or "Remote").
    description:            Full job description text (optional).
    posting_url:            Canonical URL of the listing page. Used as dedup key.
    apply_url:              Separate apply link when it differs from posting_url.
    date_posted:            Publication date when known.
    date_posted_confidence: Reliability of date_posted (EXACT / ESTIMATED / UNKNOWN).
    source:                 Identifier for the data source (e.g. "google").
    category:               Assigned category; None until categorization is run.
    is_remote:              True when fully remote. Auto-inferred from location.
    """

    model_config = ConfigDict(frozen=True)

    title: str
    company: str
    location: str
    description: str = ""
    posting_url: str
    apply_url: Optional[str] = None
    date_posted: Optional[date] = None
    date_posted_confidence: DatePostedConfidence = DatePostedConfidence.UNKNOWN
    source: str = ""
    category: Optional[Category] = None
    is_remote: bool = False

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("title", "company", "location", mode="before")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _infer_remote(self) -> "JobPosting":
        """Mark the posting as remote when 'remote' appears in the location."""
        if not self.is_remote and "remote" in self.location.lower():
            object.__setattr__(self, "is_remote", True)
        return self
