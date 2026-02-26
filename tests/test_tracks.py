"""Tests for tracks.py — scoring, filtering, and query helpers."""

from __future__ import annotations

from internship_engine.models import JobPosting
from internship_engine.tracks import (
    Track,
    best_tracks,
    filter_by_track,
    score_all_tracks,
    score_track,
    track_match_label,
    track_query_terms,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _posting(
    title: str = "Software Intern",
    description: str = "",
    company: str = "Acme",
    location: str = "New York, NY",
    posting_url: str = "https://example.com/job/1",
) -> JobPosting:
    return JobPosting(
        title=title,
        company=company,
        location=location,
        description=description,
        posting_url=posting_url,
    )


# ---------------------------------------------------------------------------
# score_track — Track.ALL
# ---------------------------------------------------------------------------


class TestScoreTrackAll:
    def test_all_always_returns_one(self):
        assert score_track(_posting(title="Totally Unrelated Role"), Track.ALL) == 1

    def test_all_never_returns_zero(self):
        assert score_track(_posting(title="Cashier at Store"), Track.ALL) == 1


# ---------------------------------------------------------------------------
# score_track — SWE
# ---------------------------------------------------------------------------


class TestScoreTrackSWE:
    def test_strong_title_keyword_scores_high(self):
        p = _posting(title="Software Engineer Intern")
        assert score_track(p, Track.SWE) >= 10

    def test_strong_description_keyword_scores_lower_than_title(self):
        p_title = _posting(title="Software Developer Intern")
        p_desc = _posting(title="Intern", description="software developer role")
        assert score_track(p_title, Track.SWE) > score_track(p_desc, Track.SWE)

    def test_weak_title_keyword_gives_partial_score(self):
        p = _posting(title="Python Intern")
        assert 0 < score_track(p, Track.SWE) < 10

    def test_unrelated_posting_scores_zero(self):
        p = _posting(title="Marketing Assistant", description="social media sales")
        assert score_track(p, Track.SWE) == 0

    def test_full_stack_keyword_in_title(self):
        p = _posting(title="Full Stack Intern")
        assert score_track(p, Track.SWE) >= 10

    def test_devops_keyword(self):
        p = _posting(title="DevOps Intern")
        assert score_track(p, Track.SWE) >= 10


# ---------------------------------------------------------------------------
# score_track — CYBER
# ---------------------------------------------------------------------------


class TestScoreTrackCyber:
    def test_security_analyst_in_title(self):
        p = _posting(title="Security Analyst Intern")
        assert score_track(p, Track.CYBER) >= 10

    def test_cybersecurity_in_description(self):
        p = _posting(title="Intern", description="cybersecurity team")
        assert score_track(p, Track.CYBER) >= 5

    def test_weak_security_keyword_in_title(self):
        p = _posting(title="Security Intern")
        score = score_track(p, Track.CYBER)
        assert 0 < score < 10

    def test_soc_analyst_in_title(self):
        p = _posting(title="SOC Analyst Intern")
        assert score_track(p, Track.CYBER) >= 10


# ---------------------------------------------------------------------------
# score_track — IT
# ---------------------------------------------------------------------------


class TestScoreTrackIT:
    def test_help_desk_in_title(self):
        p = _posting(title="Help Desk Intern")
        assert score_track(p, Track.IT) >= 10

    def test_it_support_in_description(self):
        p = _posting(title="Tech Intern", description="it support and helpdesk")
        assert score_track(p, Track.IT) >= 5

    def test_desktop_support_in_title(self):
        p = _posting(title="Desktop Support Intern")
        assert score_track(p, Track.IT) >= 10


# ---------------------------------------------------------------------------
# score_track — DATA
# ---------------------------------------------------------------------------


class TestScoreTrackData:
    def test_data_analyst_in_title(self):
        p = _posting(title="Data Analyst Intern")
        assert score_track(p, Track.DATA) >= 10

    def test_machine_learning_in_title(self):
        p = _posting(title="Machine Learning Intern")
        assert score_track(p, Track.DATA) >= 10

    def test_sql_in_description(self):
        p = _posting(title="Analytics Intern", description="must know SQL and Tableau")
        assert score_track(p, Track.DATA) >= 3


# ---------------------------------------------------------------------------
# Negative keywords
# ---------------------------------------------------------------------------


class TestNegativeKeywords:
    def test_sales_keyword_reduces_score(self):
        p_clean = _posting(title="Software Engineer Intern")
        p_neg = _posting(title="Software Engineer Intern", description="sales quota")
        assert score_track(p_clean, Track.SWE) > score_track(p_neg, Track.SWE)

    def test_pure_sales_posting_scores_zero(self):
        p = _posting(title="Sales Intern", description="marketing and retail sales")
        assert score_track(p, Track.SWE) == 0

    def test_score_never_negative(self):
        p = _posting(
            title="Sales Marketing Insurance Real Estate Retail",
            description="cashier barista restaurant hospitality",
        )
        for track in (Track.SWE, Track.CYBER, Track.IT, Track.DATA):
            assert score_track(p, track) >= 0


# ---------------------------------------------------------------------------
# score_all_tracks
# ---------------------------------------------------------------------------


class TestScoreAllTracks:
    def test_returns_all_non_all_tracks(self):
        p = _posting(title="Software Intern")
        result = score_all_tracks(p)
        for t in Track:
            if t != Track.ALL:
                assert t in result

    def test_all_not_in_result(self):
        p = _posting(title="Software Intern")
        assert Track.ALL not in score_all_tracks(p)


# ---------------------------------------------------------------------------
# best_tracks / track_match_label
# ---------------------------------------------------------------------------


class TestBestTracks:
    def test_swe_posting_returns_swe(self):
        p = _posting(title="Software Engineer Intern")
        assert Track.SWE in best_tracks(p)

    def test_unrelated_returns_empty(self):
        p = _posting(title="Cashier at Restaurant", description="retail sales")
        assert best_tracks(p) == []

    def test_multi_track_posting(self):
        p = _posting(
            title="Security Data Analyst Intern",
            description="cybersecurity analytics sql machine learning",
        )
        tracks = best_tracks(p)
        assert Track.CYBER in tracks or Track.DATA in tracks


class TestTrackMatchLabel:
    def test_single_match(self):
        p = _posting(title="Software Engineer Intern")
        label = track_match_label(p)
        assert "swe" in label

    def test_no_match_returns_empty_string(self):
        p = _posting(title="Cashier at Store", description="retail customer service")
        assert track_match_label(p) == ""

    def test_multi_match_pipe_separated(self):
        p = _posting(
            title="Security Analyst Intern",
            description="data analytics sql cybersecurity",
        )
        label = track_match_label(p)
        parts = label.split("|")
        assert len(parts) >= 1
        assert all(pt in ("cyber", "it", "swe", "data") for pt in parts)


# ---------------------------------------------------------------------------
# filter_by_track
# ---------------------------------------------------------------------------


class TestFilterByTrack:
    def _swe_posting(self, n: int = 1) -> JobPosting:
        return _posting(
            title="Software Engineer Intern",
            posting_url=f"https://example.com/{n}",
        )

    def _unrelated_posting(self, n: int = 99) -> JobPosting:
        return _posting(
            title="Cashier Retail Intern",
            description="sales customer service",
            posting_url=f"https://example.com/{n}",
        )

    def test_all_track_is_no_op(self):
        postings = [self._swe_posting(), self._unrelated_posting()]
        assert filter_by_track(postings, Track.ALL) == postings

    def test_swe_filter_keeps_swe(self):
        p = self._swe_posting()
        result = filter_by_track([p], Track.SWE)
        assert p in result

    def test_swe_filter_drops_unrelated(self):
        p = self._unrelated_posting()
        result = filter_by_track([p], Track.SWE)
        assert p not in result

    def test_empty_input_returns_empty(self):
        assert filter_by_track([], Track.SWE) == []

    def test_mixed_batch(self):
        swe = self._swe_posting(1)
        unrelated = self._unrelated_posting(2)
        result = filter_by_track([swe, unrelated], Track.SWE)
        assert swe in result
        assert unrelated not in result


# ---------------------------------------------------------------------------
# track_query_terms
# ---------------------------------------------------------------------------


class TestTrackQueryTerms:
    def test_all_returns_empty(self):
        assert track_query_terms(Track.ALL) == []

    def test_swe_returns_nonempty(self):
        terms = track_query_terms(Track.SWE)
        assert len(terms) == 1
        assert "software engineer" in terms[0].lower()

    def test_cyber_returns_security_terms(self):
        terms = track_query_terms(Track.CYBER)
        assert any("security" in t.lower() for t in terms)

    def test_data_returns_data_terms(self):
        terms = track_query_terms(Track.DATA)
        assert any("data" in t.lower() for t in terms)

    def test_it_returns_it_terms(self):
        terms = track_query_terms(Track.IT)
        assert any("IT" in t or "help desk" in t.lower() for t in terms)
