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


class JobPosting(BaseModel):
    """Immutable representation of a single internship / job posting.

    Fields
    ------
    title:       Role title as scraped from the source.
    company:     Hiring company name.
    location:    Raw location string (e.g. "New York, NY" or "Remote").
    description: Full job description text (optional).
    url:         Canonical link to the posting.  Used as part of dedup key.
    posted_date: Publication date when known.
    source:      Identifier for the data source (e.g. "linkedin", "handshake").
    category:    Assigned category; None until categorization is run.
    is_remote:   True when the posting is fully remote.  Auto-inferred from
                 *location* if not supplied explicitly.
    """

    model_config = ConfigDict(frozen=True)

    title: str
    company: str
    location: str
    description: str = ""
    url: str
    posted_date: Optional[date] = None
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
