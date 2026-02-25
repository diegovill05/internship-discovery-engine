"""Project configuration system.

Settings are loaded from environment variables (prefix ``IE_``) and,
optionally, a ``.env`` file in the working directory.

Example .env
------------
IE_REMOTE_INCLUDED=true
IE_ALLOWED_LOCATIONS=New York,San Francisco,Austin
IE_TARGET_CATEGORIES=software,data
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    All fields can be overridden via environment variables with the
    ``IE_`` prefix (case-insensitive), e.g. ``IE_REMOTE_INCLUDED=false``.

    List-valued fields must be supplied as a JSON array from the
    environment, e.g. ``IE_ALLOWED_LOCATIONS=["New York","Austin"]``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="IE_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Location filtering -------------------------------------------
    allowed_locations: Annotated[
        list[str],
        Field(
            default_factory=list,
            description=(
                "Locations to include (case-insensitive substring match). "
                "Empty list means all locations are accepted."
            ),
        ),
    ]

    remote_included: bool = Field(
        default=True,
        description="Whether to include fully-remote postings.",
    )

    # --- Categorization -----------------------------------------------
    target_categories: Annotated[
        list[str],
        Field(
            default_factory=lambda: ["software", "data", "product"],
            description="Category names of interest (used for downstream filtering).",
        ),
    ]

    # --- Search provider API keys -------------------------------------
    brave_api_key: str = Field(
        default="",
        description="Brave Search API subscription token (IE_BRAVE_API_KEY).",
    )

    google_api_key: str = Field(
        default="",
        description="Google Custom Search JSON API key (IE_GOOGLE_API_KEY).",
    )

    google_cse_id: str = Field(
        default="",
        description="Google Programmable Search Engine ID (IE_GOOGLE_CSE_ID).",
    )

    # --- Deduplication ------------------------------------------------
    seen_hashes_path: Path = Field(
        default=Path(".cache/seen_hashes.txt"),
        description="File path used to persist seen posting hashes between runs.",
    )


# ---------------------------------------------------------------------------
# Module-level singleton with lazy initialisation
# ---------------------------------------------------------------------------

_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the application-wide Settings singleton.

    Instantiated lazily on first call so that tests can patch environment
    variables before the object is constructed.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Discard the cached singleton.

    Intended for use in tests that need to vary environment variables
    between test cases.
    """
    global _settings
    _settings = None
