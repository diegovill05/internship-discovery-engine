"""Tests for active_check.py — all network-free via injected mock sessions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from internship_engine.active_check import (
    ActiveCheckResult,
    check_active,
)
from internship_engine.models import ActiveStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session(status_code: int, text: str = "") -> MagicMock:
    """Return a session whose GET always returns the given status + text."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    session = MagicMock()
    session.get.return_value = resp
    return session


def _timeout_session() -> MagicMock:
    session = MagicMock()
    session.get.side_effect = requests.exceptions.Timeout()
    return session


def _error_session(msg: str = "connection refused") -> MagicMock:
    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError(msg)
    return session


_URL = "https://example.com/job/1"


# ---------------------------------------------------------------------------
# HTTP 404 / 410 → INACTIVE
# ---------------------------------------------------------------------------


class TestGoneCodes:
    def test_404_returns_inactive(self):
        result = check_active(_URL, _mock_session(404))
        assert result.status == ActiveStatus.INACTIVE
        assert "404" in result.reason

    def test_410_returns_inactive(self):
        result = check_active(_URL, _mock_session(410))
        assert result.status == ActiveStatus.INACTIVE
        assert "410" in result.reason


# ---------------------------------------------------------------------------
# HTTP 403 / 429 → UNKNOWN
# ---------------------------------------------------------------------------


class TestBlockedCodes:
    def test_403_returns_unknown(self):
        result = check_active(_URL, _mock_session(403))
        assert result.status == ActiveStatus.UNKNOWN
        assert "403" in result.reason

    def test_429_returns_unknown(self):
        result = check_active(_URL, _mock_session(429))
        assert result.status == ActiveStatus.UNKNOWN
        assert "429" in result.reason


# ---------------------------------------------------------------------------
# HTTP 5xx → UNKNOWN
# ---------------------------------------------------------------------------


class TestServerErrors:
    def test_500_returns_unknown(self):
        result = check_active(_URL, _mock_session(500))
        assert result.status == ActiveStatus.UNKNOWN
        assert "500" in result.reason

    def test_503_returns_unknown(self):
        result = check_active(_URL, _mock_session(503))
        assert result.status == ActiveStatus.UNKNOWN


# ---------------------------------------------------------------------------
# HTTP 200 with closed signals → INACTIVE
# ---------------------------------------------------------------------------


class TestClosedSignals:
    @pytest.mark.parametrize(
        "signal",
        [
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
        ],
    )
    def test_signal_in_body_returns_inactive(self, signal: str):
        html = f"<html><body><p>{signal}</p></body></html>"
        result = check_active(_URL, _mock_session(200, html))
        assert result.status == ActiveStatus.INACTIVE
        # reason mentions the matched signal (may be a substring of the param)
        assert "closed signal" in result.reason

    def test_signal_detection_is_case_insensitive(self):
        html = "<html><body>Position Has Been Filled</body></html>"
        result = check_active(_URL, _mock_session(200, html))
        assert result.status == ActiveStatus.INACTIVE

    def test_first_matching_signal_reported(self):
        html = "<p>no longer available and job closed</p>"
        result = check_active(_URL, _mock_session(200, html))
        assert result.status == ActiveStatus.INACTIVE


# ---------------------------------------------------------------------------
# HTTP 200, no closed signals → ACTIVE
# ---------------------------------------------------------------------------


class TestActive:
    def test_clean_page_returns_active(self):
        html = "<html><body><h1>Software Intern</h1><p>Apply now!</p></body></html>"
        result = check_active(_URL, _mock_session(200, html))
        assert result.status == ActiveStatus.ACTIVE

    def test_apply_button_detected_in_reason(self):
        html = '<button type="submit">Apply Now</button>'
        result = check_active(_URL, _mock_session(200, html))
        assert result.status == ActiveStatus.ACTIVE
        assert "apply" in result.reason.lower()

    def test_no_apply_button_still_active(self):
        html = "<html><body><p>Great internship role.</p></body></html>"
        result = check_active(_URL, _mock_session(200, html))
        assert result.status == ActiveStatus.ACTIVE
        assert "no closed signals" in result.reason


# ---------------------------------------------------------------------------
# Network errors → UNKNOWN
# ---------------------------------------------------------------------------


class TestNetworkErrors:
    def test_timeout_returns_unknown(self):
        result = check_active(_URL, _timeout_session())
        assert result.status == ActiveStatus.UNKNOWN
        assert "timed out" in result.reason.lower()

    def test_connection_error_returns_unknown(self):
        result = check_active(_URL, _error_session())
        assert result.status == ActiveStatus.UNKNOWN
        assert "request failed" in result.reason.lower()


# ---------------------------------------------------------------------------
# Unexpected 2xx (e.g. 201, 204) → UNKNOWN
# ---------------------------------------------------------------------------


class TestUnexpectedCodes:
    def test_201_returns_unknown(self):
        result = check_active(_URL, _mock_session(201))
        assert result.status == ActiveStatus.UNKNOWN

    def test_204_returns_unknown(self):
        result = check_active(_URL, _mock_session(204))
        assert result.status == ActiveStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class TestReturnType:
    def test_returns_active_check_result(self):
        result = check_active(_URL, _mock_session(200, "some content"))
        assert isinstance(result, ActiveCheckResult)

    def test_uses_fresh_session_when_none_given(self):
        """Calling without a session should not raise (may fail to connect)."""
        # We can't easily intercept the real session here, but we can verify
        # that the function handles the ConnectionError gracefully.
        import unittest.mock as mock

        with mock.patch("requests.Session") as MockSession:
            ms = MagicMock()
            ms.get.side_effect = requests.exceptions.ConnectionError("refused")
            MockSession.return_value = ms
            result = check_active("https://example.com/job/99")
        assert result.status == ActiveStatus.UNKNOWN
