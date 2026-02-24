"""Unit tests for internship_engine.deduplication."""

from __future__ import annotations

import pytest

from internship_engine.deduplication import DuplicateFilter, compute_hash
from internship_engine.models import JobPosting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _posting(
    title: str = "Software Engineer Intern",
    company: str = "Acme Corp",
    url: str = "https://example.com/job/1",
    **kwargs,
) -> JobPosting:
    return JobPosting(
        title=title,
        company=company,
        location="Remote",
        url=url,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# compute_hash — output properties
# ---------------------------------------------------------------------------


class TestComputeHashOutput:
    def test_returns_string(self):
        assert isinstance(compute_hash(_posting()), str)

    def test_length_is_64_chars(self):
        # SHA-256 produces a 64-char hex digest
        assert len(compute_hash(_posting())) == 64

    def test_contains_only_hex_characters(self):
        h = compute_hash(_posting())
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# compute_hash — stability
# ---------------------------------------------------------------------------


class TestComputeHashStability:
    def test_same_posting_same_hash(self):
        p = _posting()
        assert compute_hash(p) == compute_hash(p)

    def test_two_identical_postings_same_hash(self):
        assert compute_hash(_posting()) == compute_hash(_posting())

    def test_whitespace_normalised_in_title(self):
        p1 = _posting(title="Software Engineer Intern ")
        p2 = _posting(title="software engineer intern")
        assert compute_hash(p1) == compute_hash(p2)

    def test_case_normalised_in_company(self):
        p1 = _posting(company="ACME CORP")
        p2 = _posting(company="acme corp")
        assert compute_hash(p1) == compute_hash(p2)

    def test_case_normalised_in_url(self):
        p1 = _posting(url="HTTPS://EXAMPLE.COM/JOB/1")
        p2 = _posting(url="https://example.com/job/1")
        assert compute_hash(p1) == compute_hash(p2)


# ---------------------------------------------------------------------------
# compute_hash — uniqueness
# ---------------------------------------------------------------------------


class TestComputeHashUniqueness:
    def test_different_url_gives_different_hash(self):
        p1 = _posting(url="https://example.com/job/1")
        p2 = _posting(url="https://example.com/job/2")
        assert compute_hash(p1) != compute_hash(p2)

    def test_different_company_gives_different_hash(self):
        p1 = _posting(company="Acme Corp")
        p2 = _posting(company="Globex Inc")
        assert compute_hash(p1) != compute_hash(p2)

    def test_different_title_gives_different_hash(self):
        p1 = _posting(title="Software Engineer Intern")
        p2 = _posting(title="Data Science Intern")
        assert compute_hash(p1) != compute_hash(p2)

    def test_description_change_does_not_change_hash(self):
        # Description is intentionally excluded from the hash
        p1 = _posting(description="Original description.")
        p2 = _posting(description="Totally different description!")
        assert compute_hash(p1) == compute_hash(p2)

    def test_posted_date_change_does_not_change_hash(self):
        from datetime import date

        p1 = _posting(posted_date=date(2024, 1, 1))
        p2 = _posting(posted_date=date(2025, 6, 15))
        assert compute_hash(p1) == compute_hash(p2)


# ---------------------------------------------------------------------------
# DuplicateFilter — basic behaviour
# ---------------------------------------------------------------------------


class TestDuplicateFilterIsNew:
    def test_first_posting_is_new(self):
        df = DuplicateFilter()
        assert df.is_new(_posting()) is True

    def test_second_occurrence_is_not_new(self):
        df = DuplicateFilter()
        p = _posting()
        df.is_new(p)
        assert df.is_new(p) is False

    def test_different_posting_is_new(self):
        df = DuplicateFilter()
        df.is_new(_posting(url="https://example.com/1"))
        assert df.is_new(_posting(url="https://example.com/2")) is True

    def test_seen_count_increments_for_unique(self):
        df = DuplicateFilter()
        df.is_new(_posting(url="https://example.com/1"))
        df.is_new(_posting(url="https://example.com/2"))
        assert df.seen_count == 2

    def test_seen_count_unchanged_for_duplicate(self):
        df = DuplicateFilter()
        p = _posting()
        df.is_new(p)
        df.is_new(p)
        assert df.seen_count == 1


# ---------------------------------------------------------------------------
# DuplicateFilter — filter_new
# ---------------------------------------------------------------------------


class TestDuplicateFilterFilterNew:
    def test_removes_duplicates_within_batch(self):
        df = DuplicateFilter()
        p1 = _posting(url="https://example.com/1")
        p2 = _posting(url="https://example.com/2")
        result = df.filter_new([p1, p2, p1])
        assert result == [p1, p2]

    def test_removes_duplicates_across_batches(self):
        df = DuplicateFilter()
        p = _posting()
        df.filter_new([p])
        result = df.filter_new([p])
        assert result == []

    def test_preserves_order(self):
        df = DuplicateFilter()
        postings = [_posting(url=f"https://example.com/{i}") for i in range(5)]
        assert df.filter_new(postings) == postings

    def test_empty_input_returns_empty(self):
        assert DuplicateFilter().filter_new([]) == []


# ---------------------------------------------------------------------------
# DuplicateFilter — initial_hashes seeding
# ---------------------------------------------------------------------------


class TestDuplicateFilterInitialHashes:
    def test_seeded_hash_treated_as_seen(self):
        p = _posting()
        h = compute_hash(p)
        df = DuplicateFilter(initial_hashes={h})
        assert df.is_new(p) is False

    def test_unseeded_hash_treated_as_new(self):
        df = DuplicateFilter(initial_hashes={"deadbeef" * 8})
        assert df.is_new(_posting()) is True

    def test_initial_hashes_contribute_to_seen_count(self):
        df = DuplicateFilter(initial_hashes={"a" * 64, "b" * 64})
        assert df.seen_count == 2


# ---------------------------------------------------------------------------
# DuplicateFilter — hashes() snapshot
# ---------------------------------------------------------------------------


class TestDuplicateFilterHashes:
    def test_returns_frozenset(self):
        df = DuplicateFilter()
        df.is_new(_posting())
        assert isinstance(df.hashes(), frozenset)

    def test_snapshot_contains_recorded_hash(self):
        df = DuplicateFilter()
        p = _posting()
        df.is_new(p)
        assert compute_hash(p) in df.hashes()

    def test_snapshot_is_immutable(self):
        df = DuplicateFilter()
        snapshot = df.hashes()
        with pytest.raises((AttributeError, TypeError)):
            snapshot.add("new_hash")  # type: ignore[attr-defined]

    def test_snapshot_does_not_reflect_later_additions(self):
        df = DuplicateFilter()
        snapshot_before = df.hashes()
        df.is_new(_posting())
        assert snapshot_before == frozenset()  # snapshot unchanged
