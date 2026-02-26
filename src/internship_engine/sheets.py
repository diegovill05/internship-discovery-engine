"""Google Sheets export for the Internship Discovery Engine.

Usage
-----
After the pipeline produces a filtered list of
:class:`~internship_engine.models.JobPosting` objects, call
:func:`export_postings` (or use the lower-level helpers) to
append new rows to a master Google Sheet.

Authentication
--------------
A Google service account JSON key string must be available in the environment
variable ``GOOGLE_SERVICE_ACCOUNT_JSON``.  The sheet must be shared with the
service account's email address (editor access).

Column order
------------
Added At | Category | Title | Company | Location | Date Posted |
Date Confidence | Apply URL | Posting URL | Source | Hash |
Status | Status Reason | Track Match

Auto-migration
--------------
If an existing sheet has the 11-column legacy header (before Status/Status Reason/
Track Match were added), :func:`ensure_header` appends the missing columns rather
than raising an error.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import TYPE_CHECKING

from internship_engine.deduplication import compute_hash

if TYPE_CHECKING:
    import gspread

    from internship_engine.config import Settings
    from internship_engine.models import JobPosting

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column definitions (order matters — must match sheet header)
# ---------------------------------------------------------------------------

COLUMNS: list[str] = [
    "Added At",
    "Category",
    "Title",
    "Company",
    "Location",
    "Date Posted",
    "Date Confidence",
    "Apply URL",
    "Posting URL",
    "Source",
    "Hash",
    "Status",
    "Status Reason",
    "Track Match",
]

_HASH_COL_INDEX = COLUMNS.index("Hash")  # 0-based


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


def build_client_from_env(settings: Settings) -> gspread.Client:
    """Create an authenticated gspread client from the service-account JSON string.

    Parameters
    ----------
    settings:
        Application settings — reads ``google_service_account_json``.

    Returns
    -------
    gspread.Client
        A client authorised with the service account credentials.

    Raises
    ------
    ValueError
        If the ``GOOGLE_SERVICE_ACCOUNT_JSON`` env var is absent or empty.
    json.JSONDecodeError
        If the value is not valid JSON.
    """
    import gspread
    from google.oauth2.service_account import Credentials

    if not settings.google_service_account_json:
        raise ValueError(
            "GOOGLE_SERVICE_ACCOUNT_JSON environment variable is required "
            "for Google Sheets export but is not set."
        )

    info = json.loads(settings.google_service_account_json)
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


# ---------------------------------------------------------------------------
# Sheet helpers
# ---------------------------------------------------------------------------


def ensure_header(worksheet: gspread.Worksheet) -> None:
    """Ensure the first row of *worksheet* contains exactly :data:`COLUMNS`.

    Three behaviours:

    * **Empty sheet** — the full header is inserted as row 1.
    * **Exact match** — no-op.
    * **Prefix match** — the existing header is a valid leading subset of
      :data:`COLUMNS` (e.g. the legacy 11-column layout).  Missing columns are
      appended to row 1 via individual ``update_cell`` calls (auto-migration).
    * **Mismatch** — ``ValueError`` is raised.

    Parameters
    ----------
    worksheet:
        The target worksheet object.
    """
    existing = worksheet.get_all_values()
    if not existing:
        worksheet.insert_row(COLUMNS, 1)
        logger.debug("Inserted header row into empty sheet.")
        return

    existing_header = existing[0]

    if existing_header == COLUMNS:
        return  # already correct

    # Auto-migration: append missing columns if existing header is a prefix
    n = len(existing_header)
    if 0 < n < len(COLUMNS) and existing_header == COLUMNS[:n]:
        missing = COLUMNS[n:]
        for i, col_name in enumerate(missing):
            worksheet.update_cell(1, n + 1 + i, col_name)
        logger.info(
            "Auto-migrated sheet header: appended %d column(s): %s",
            len(missing),
            missing,
        )
        return

    raise ValueError(
        f"Sheet header mismatch.\n"
        f"  Expected: {COLUMNS}\n"
        f"  Found:    {existing_header}\n"
        "Please fix the sheet header or clear the sheet before running."
    )


def upsert_rows(
    worksheet: gspread.Worksheet,
    postings: list[JobPosting],
    *,
    added_at: date | None = None,
) -> int:
    """Append postings not yet present in *worksheet*.

    Deduplication is based on the ``Hash`` column value, which is computed
    with :func:`~internship_engine.deduplication.compute_hash`.  Rows whose
    hash already exists anywhere in the sheet are silently skipped.

    Parameters
    ----------
    worksheet:
        The target worksheet (header row must already be present).
    postings:
        List of :class:`~internship_engine.models.JobPosting` objects to write.
    added_at:
        Date to record in the "Added At" column.  Defaults to today.

    Returns
    -------
    int
        Number of rows actually appended.
    """
    today_str = (added_at or date.today()).isoformat()

    # Collect existing hashes (column is 0-based _HASH_COL_INDEX)
    all_values = worksheet.get_all_values()
    existing_hashes: set[str] = set()
    for row in all_values[1:]:  # skip header
        if len(row) > _HASH_COL_INDEX:
            h = row[_HASH_COL_INDEX].strip()
            if h:
                existing_hashes.add(h)

    appended = 0
    for posting in postings:
        h = compute_hash(posting)
        if h in existing_hashes:
            logger.debug(
                "Skipping duplicate posting hash %s (%s)", h[:12], posting.title
            )
            continue

        row = _posting_to_row(posting, h, today_str)
        worksheet.append_row(row, value_input_option="USER_ENTERED")
        existing_hashes.add(h)
        appended += 1
        logger.debug("Appended posting: %s @ %s", posting.title, posting.company)

    return appended


# ---------------------------------------------------------------------------
# High-level convenience
# ---------------------------------------------------------------------------


def export_postings(
    settings: Settings,
    postings: list[JobPosting],
    *,
    sheet_id: str | None = None,
    tab_name: str | None = None,
) -> int:
    """Build a client, open the sheet, ensure header, and upsert all postings.

    Parameters
    ----------
    settings:
        Application settings (used for credentials and default sheet/tab).
    postings:
        Postings to export.
    sheet_id:
        Google Sheet ID override (falls back to ``settings.sheet_id``).
    tab_name:
        Worksheet tab name override (falls back to ``settings.sheet_tab``).

    Returns
    -------
    int
        Number of rows appended (0 if all were duplicates).

    Raises
    ------
    ValueError
        If no sheet ID is available or credentials are missing.
    """
    sid = sheet_id or settings.sheet_id
    if not sid:
        raise ValueError(
            "No Google Sheet ID supplied.  Pass --sheet-id or set IE_SHEET_ID."
        )

    tab = tab_name or settings.sheet_tab

    client = build_client_from_env(settings)
    spreadsheet = client.open_by_key(sid)
    worksheet = spreadsheet.worksheet(tab)

    ensure_header(worksheet)
    return upsert_rows(worksheet, postings)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _posting_to_row(posting: JobPosting, h: str, added_at: str) -> list[str]:
    """Convert a posting to a list of cell values matching :data:`COLUMNS`."""
    return [
        added_at,
        posting.category.value if posting.category else "",
        posting.title,
        posting.company,
        posting.location,
        str(posting.date_posted) if posting.date_posted else "",
        posting.date_posted_confidence.value,
        posting.apply_url or "",
        posting.posting_url,
        posting.source,
        h,
        posting.active_status.value,
        posting.active_reason,
        posting.track_match,
    ]
