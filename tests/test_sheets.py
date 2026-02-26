"""Tests for the Google Sheets export module.

All tests are network-free.  The gspread client and worksheet are replaced
with lightweight fakes so no real API calls are made.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from internship_engine.deduplication import compute_hash
from internship_engine.models import Category, DatePostedConfidence, JobPosting
from internship_engine.sheets import (
    _HASH_COL_INDEX,
    COLUMNS,
    _posting_to_row,
    ensure_header,
    export_postings,
    upsert_rows,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_posting(
    title: str = "Software Intern",
    company: str = "Acme Corp",
    location: str = "New York, NY",
    posting_url: str = "https://acme.example.com/jobs/1",
    *,
    category: Category | None = Category.SOFTWARE,
    date_posted: date | None = date(2024, 6, 1),
    date_posted_confidence: DatePostedConfidence = DatePostedConfidence.EXACT,
    apply_url: str | None = "https://acme.example.com/apply/1",
    source: str = "brave",
) -> JobPosting:
    return JobPosting(
        title=title,
        company=company,
        location=location,
        posting_url=posting_url,
        category=category,
        date_posted=date_posted,
        date_posted_confidence=date_posted_confidence,
        apply_url=apply_url,
        source=source,
    )


def _fake_worksheet(rows: list[list[str]] | None = None) -> MagicMock:
    """Return a mock worksheet that reports *rows* from get_all_values()."""
    ws = MagicMock()
    ws.get_all_values.return_value = rows if rows is not None else []
    return ws


# ---------------------------------------------------------------------------
# ensure_header
# ---------------------------------------------------------------------------


class TestEnsureHeader:
    def test_inserts_header_when_sheet_is_empty(self):
        ws = _fake_worksheet([])
        ensure_header(ws)
        ws.insert_row.assert_called_once_with(COLUMNS, 1)

    def test_no_op_when_header_already_correct(self):
        ws = _fake_worksheet([COLUMNS])
        ensure_header(ws)
        ws.insert_row.assert_not_called()

    def test_no_op_when_sheet_has_header_and_data(self):
        data_row = ["2024-06-01", "software", "Intern"] + [""] * 7 + ["abc"]
        ws = _fake_worksheet([COLUMNS, data_row])
        ensure_header(ws)
        ws.insert_row.assert_not_called()

    def test_raises_on_mismatched_header(self):
        ws = _fake_worksheet([["Wrong", "Header", "Row"]])
        with pytest.raises(ValueError, match="header mismatch"):
            ensure_header(ws)


# ---------------------------------------------------------------------------
# _posting_to_row
# ---------------------------------------------------------------------------


class TestPostingToRow:
    def test_correct_column_count(self):
        p = _make_posting()
        row = _posting_to_row(p, "abc123", "2024-06-01")
        assert len(row) == len(COLUMNS)

    def test_added_at_in_first_column(self):
        p = _make_posting()
        row = _posting_to_row(p, "abc123", "2024-06-01")
        assert row[COLUMNS.index("Added At")] == "2024-06-01"

    def test_hash_in_last_column(self):
        p = _make_posting()
        h = compute_hash(p)
        row = _posting_to_row(p, h, "2024-06-01")
        assert row[_HASH_COL_INDEX] == h

    def test_category_value_string(self):
        p = _make_posting(category=Category.DATA)
        row = _posting_to_row(p, "h", "2024-01-01")
        assert row[COLUMNS.index("Category")] == "data"

    def test_category_empty_when_none(self):
        p = _make_posting(category=None)
        row = _posting_to_row(p, "h", "2024-01-01")
        assert row[COLUMNS.index("Category")] == ""

    def test_date_posted_as_iso_string(self):
        p = _make_posting(date_posted=date(2024, 5, 15))
        row = _posting_to_row(p, "h", "2024-01-01")
        assert row[COLUMNS.index("Date Posted")] == "2024-05-15"

    def test_date_posted_empty_when_none(self):
        p = _make_posting(date_posted=None)
        row = _posting_to_row(p, "h", "2024-01-01")
        assert row[COLUMNS.index("Date Posted")] == ""

    def test_date_confidence_value(self):
        p = _make_posting(date_posted_confidence=DatePostedConfidence.UNKNOWN)
        row = _posting_to_row(p, "h", "2024-01-01")
        assert row[COLUMNS.index("Date Confidence")] == "unknown"

    def test_apply_url_present(self):
        p = _make_posting(apply_url="https://apply.example.com")
        row = _posting_to_row(p, "h", "2024-01-01")
        assert row[COLUMNS.index("Apply URL")] == "https://apply.example.com"

    def test_apply_url_empty_when_none(self):
        p = _make_posting(apply_url=None)
        row = _posting_to_row(p, "h", "2024-01-01")
        assert row[COLUMNS.index("Apply URL")] == ""

    def test_posting_url(self):
        p = _make_posting(posting_url="https://example.com/job/42")
        row = _posting_to_row(p, "h", "2024-01-01")
        assert row[COLUMNS.index("Posting URL")] == "https://example.com/job/42"

    def test_source(self):
        p = _make_posting(source="google")
        row = _posting_to_row(p, "h", "2024-01-01")
        assert row[COLUMNS.index("Source")] == "google"


# ---------------------------------------------------------------------------
# upsert_rows
# ---------------------------------------------------------------------------


class TestUpsertRows:
    def test_appends_new_posting(self):
        p = _make_posting()
        ws = _fake_worksheet([COLUMNS])  # header only, no data rows
        count = upsert_rows(ws, [p], added_at=date(2024, 6, 1))
        assert count == 1
        ws.append_row.assert_called_once()

    def test_appended_row_has_correct_hash(self):
        p = _make_posting()
        ws = _fake_worksheet([COLUMNS])
        upsert_rows(ws, [p], added_at=date(2024, 6, 1))
        appended_row = ws.append_row.call_args[0][0]
        assert appended_row[_HASH_COL_INDEX] == compute_hash(p)

    def test_skips_duplicate_hash(self):
        p = _make_posting()
        h = compute_hash(p)
        existing = [COLUMNS, ["2024-01-01"] + [""] * (_HASH_COL_INDEX - 1) + [h]]
        ws = _fake_worksheet(existing)
        count = upsert_rows(ws, [p], added_at=date(2024, 6, 2))
        assert count == 0
        ws.append_row.assert_not_called()

    def test_appends_only_new_among_mixed_batch(self):
        p1 = _make_posting(title="Old Intern", posting_url="https://ex.com/1")
        p2 = _make_posting(title="New Intern", posting_url="https://ex.com/2")
        h1 = compute_hash(p1)
        existing = [COLUMNS, ["2024-01-01"] + [""] * (_HASH_COL_INDEX - 1) + [h1]]
        ws = _fake_worksheet(existing)
        count = upsert_rows(ws, [p1, p2], added_at=date(2024, 6, 1))
        assert count == 1
        ws.append_row.assert_called_once()
        appended_row = ws.append_row.call_args[0][0]
        assert appended_row[_HASH_COL_INDEX] == compute_hash(p2)

    def test_no_duplicates_within_same_batch(self):
        """The same posting passed twice must only be appended once."""
        p = _make_posting()
        ws = _fake_worksheet([COLUMNS])
        count = upsert_rows(ws, [p, p], added_at=date(2024, 6, 1))
        assert count == 1

    def test_empty_postings_list(self):
        ws = _fake_worksheet([COLUMNS])
        count = upsert_rows(ws, [], added_at=date(2024, 6, 1))
        assert count == 0
        ws.append_row.assert_not_called()

    def test_added_at_uses_today_when_not_supplied(self):
        p = _make_posting()
        ws = _fake_worksheet([COLUMNS])
        today = date.today().isoformat()
        upsert_rows(ws, [p])
        appended_row = ws.append_row.call_args[0][0]
        assert appended_row[COLUMNS.index("Added At")] == today

    def test_append_row_uses_user_entered_input(self):
        p = _make_posting()
        ws = _fake_worksheet([COLUMNS])
        upsert_rows(ws, [p], added_at=date(2024, 6, 1))
        _, kwargs = ws.append_row.call_args
        assert kwargs.get("value_input_option") == "USER_ENTERED"

    def test_returns_count_for_multiple_new_postings(self):
        p1 = _make_posting(title="Intern A", posting_url="https://ex.com/1")
        p2 = _make_posting(title="Intern B", posting_url="https://ex.com/2")
        ws = _fake_worksheet([COLUMNS])
        count = upsert_rows(ws, [p1, p2], added_at=date(2024, 6, 1))
        assert count == 2


# ---------------------------------------------------------------------------
# export_postings (integration of build_client, ensure_header, upsert_rows)
# ---------------------------------------------------------------------------


_FAKE_PKEY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA...\n"
    "-----END RSA PRIVATE KEY-----\n"
)
_BCF = "internship_engine.sheets.build_client_from_env"


class TestExportPostings:
    _SA_JSON = json.dumps(
        {
            "type": "service_account",
            "project_id": "test-project",
            "private_key_id": "key-id",
            "private_key": _FAKE_PKEY,
            "client_email": "test@test-project.iam.gserviceaccount.com",
            "client_id": "123456789",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )

    def _make_settings(self, sheet_id="sheet123", tab="Postings"):
        from internship_engine.config import reset_settings

        reset_settings()
        settings = MagicMock()
        settings.sheet_id = sheet_id
        settings.sheet_tab = tab
        settings.google_service_account_json = self._SA_JSON
        return settings

    def _mock_client(self, ws: MagicMock) -> MagicMock:
        client = MagicMock()
        spreadsheet = MagicMock()
        spreadsheet.worksheet.return_value = ws
        client.open_by_key.return_value = spreadsheet
        return client

    def test_opens_correct_sheet_id(self):
        ws = _fake_worksheet([COLUMNS])
        client = self._mock_client(ws)
        settings = self._make_settings(sheet_id="MY_SHEET_ID")

        with patch(_BCF, return_value=client):
            export_postings(settings, [], sheet_id="MY_SHEET_ID")

        client.open_by_key.assert_called_once_with("MY_SHEET_ID")

    def test_opens_correct_tab(self):
        ws = _fake_worksheet([COLUMNS])
        client = self._mock_client(ws)
        settings = self._make_settings(tab="Internships")

        with patch(_BCF, return_value=client):
            export_postings(settings, [], tab_name="Internships")

        client.open_by_key.return_value.worksheet.assert_called_once_with("Internships")

    def test_raises_when_no_sheet_id(self):
        settings = self._make_settings(sheet_id=None)
        with pytest.raises(ValueError, match="No Google Sheet ID"):
            export_postings(settings, [])

    def test_appends_new_postings(self):
        p = _make_posting()
        ws = _fake_worksheet([COLUMNS])
        client = self._mock_client(ws)
        settings = self._make_settings()

        with patch(_BCF, return_value=client):
            count = export_postings(settings, [p])

        assert count == 1
        ws.append_row.assert_called_once()

    def test_falls_back_to_settings_sheet_id(self):
        ws = _fake_worksheet([COLUMNS])
        client = self._mock_client(ws)
        settings = self._make_settings(sheet_id="SETTINGS_SHEET")

        with patch(_BCF, return_value=client):
            export_postings(settings, [])

        client.open_by_key.assert_called_once_with("SETTINGS_SHEET")

    def test_falls_back_to_settings_tab(self):
        ws = _fake_worksheet([COLUMNS])
        client = self._mock_client(ws)
        settings = self._make_settings(tab="MyTab")

        with patch(_BCF, return_value=client):
            export_postings(settings, [])

        client.open_by_key.return_value.worksheet.assert_called_once_with("MyTab")
