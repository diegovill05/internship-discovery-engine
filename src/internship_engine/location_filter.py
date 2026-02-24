"""Location filtering for job postings.

Filtering rules (evaluated in order):
1. If ``include_remote`` is True, postings whose ``is_remote`` flag is set
   always pass regardless of ``allowed_locations``.
2. If ``allowed_locations`` is empty, all remaining (non-remote) postings pass.
3. Otherwise a posting passes only when its ``location`` string contains at
   least one of the ``allowed_locations`` entries (case-insensitive substring).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from internship_engine.models import JobPosting


@dataclass(frozen=True)
class LocationFilter:
    """Immutable value object that describes which locations to accept.

    Parameters
    ----------
    allowed_locations:
        Tuple of location strings used as case-insensitive substring
        patterns against ``JobPosting.location``.  An empty tuple means
        "accept any location".
    include_remote:
        When *True* (default), remote postings always pass regardless of
        ``allowed_locations``.
    """

    allowed_locations: tuple[str, ...] = field(default_factory=tuple)
    include_remote: bool = True

    def matches(self, posting: JobPosting) -> bool:
        """Return *True* if *posting* should be included.

        Parameters
        ----------
        posting:
            The :class:`~internship_engine.models.JobPosting` to evaluate.
        """
        if posting.is_remote:
            return self.include_remote

        if not self.allowed_locations:
            return True

        location_lower = posting.location.lower()
        return any(loc.lower() in location_lower for loc in self.allowed_locations)


def apply_location_filter(
    postings: list[JobPosting],
    location_filter: LocationFilter,
) -> list[JobPosting]:
    """Return the subset of *postings* that pass *location_filter*.

    Parameters
    ----------
    postings:
        Input list of :class:`~internship_engine.models.JobPosting` objects.
    location_filter:
        :class:`LocationFilter` instance defining the acceptance criteria.
    """
    return [p for p in postings if location_filter.matches(p)]
