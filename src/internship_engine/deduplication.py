"""Deduplication hashing system for job postings.

A posting's identity is defined by three canonical fields:
  title + company + posting_url  (all lowercased and stripped)

This makes the hash robust to minor whitespace / capitalisation differences
while still uniquely identifying a posting across repeated fetches.

Typical usage
-------------
>>> df = DuplicateFilter()
>>> new_postings = df.filter_new(fetched_postings)
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from internship_engine.models import JobPosting

logger = logging.getLogger(__name__)

# Separator unlikely to appear in normal field values
_SEP = "\x00"


def compute_hash(posting: JobPosting) -> str:
    """Return a stable 64-character SHA-256 hex digest for *posting*.

    The digest is derived exclusively from ``title``, ``company``, and
    ``posting_url`` — the fields that together uniquely identify a role at a
    company.  Description and dates are intentionally excluded so that
    minor editorial changes to a posting do not produce a new hash.

    Parameters
    ----------
    posting:
        The :class:`~internship_engine.models.JobPosting` to hash.

    Returns
    -------
    str
        A 64-character lowercase hex string (SHA-256).
    """
    canonical = _SEP.join(
        [
            posting.title.lower().strip(),
            posting.company.lower().strip(),
            posting.posting_url.lower().strip(),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DuplicateFilter:
    """Stateful filter that tracks seen postings by their content hash.

    Hashes are stored in memory and can be seeded from a persisted set
    (e.g. loaded from disk) via ``initial_hashes``.

    Parameters
    ----------
    initial_hashes:
        Optional set of already-seen hash strings.  Postings whose hash
        appears in this set are treated as duplicates on the first call.
    """

    def __init__(self, initial_hashes: set[str] | None = None) -> None:
        self._seen: set[str] = set(initial_hashes or ())

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def seen_count(self) -> int:
        """Total number of unique hashes recorded so far."""
        return len(self._seen)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def is_new(self, posting: JobPosting) -> bool:
        """Return *True* and record the hash if *posting* has not been seen.

        Returns *False* (without re-recording) when a posting with the
        same canonical hash has already been processed.
        """
        h = compute_hash(posting)
        if h in self._seen:
            return False
        self._seen.add(h)
        return True

    def filter_new(self, postings: list[JobPosting]) -> list[JobPosting]:
        """Return only the postings not yet seen, recording each one.

        Preserves the relative order of *postings*.
        """
        return [p for p in postings if self.is_new(p)]

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def hashes(self) -> frozenset[str]:
        """Return an immutable snapshot of all seen hashes.

        Useful for serialising the filter state between runs.
        """
        return frozenset(self._seen)


# ---------------------------------------------------------------------------
# File-based persistence
# ---------------------------------------------------------------------------


def load_hashes(path: Path) -> set[str]:
    """Read previously-seen hashes from *path* (one hex digest per line).

    Returns an empty set when the file does not exist or is unreadable.
    Blank lines and lines that are not 64-character hex strings are skipped.
    """
    if not path.is_file():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read hash file %s: %s", path, exc)
        return set()
    hashes: set[str] = set()
    for line in text.splitlines():
        h = line.strip()
        if len(h) == 64:
            hashes.add(h)
    return hashes


def save_hashes(path: Path, hashes: frozenset[str] | set[str]) -> None:
    """Write *hashes* to *path*, one hex digest per line.

    Creates parent directories if they do not exist.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(sorted(hashes)) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Could not write hash file %s: %s", path, exc)
