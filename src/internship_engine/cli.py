"""CLI entry point for the Internship Discovery Engine.

Registered as the ``internship-engine`` console script via pyproject.toml.

Subcommands
-----------
run              Fetch, filter, deduplicate, and display new postings.
list-categories  Print all recognised category names.

Usage examples
--------------
$ internship-engine list-categories
$ internship-engine run --location "New York, NY" --category software
$ internship-engine run --source brave --keyword Python --max-results 20
$ internship-engine run --source google --location "San Francisco, CA"
$ internship-engine run --no-remote --posted-within-days 7
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from internship_engine import __version__


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="internship-engine",
        description="Discover and track internship opportunities.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- run --------------------------------------------------------------
    run_parser = subparsers.add_parser(
        "run",
        help="Fetch, filter, and display new internship postings.",
        description=(
            "Fetch new postings via a search provider (Brave or Google),\n"
            "extract structured data, apply location / category / dedup\n"
            "filters, and print a summary."
        ),
    )
    run_parser.add_argument(
        "--source",
        choices=["brave", "google"],
        default="brave",
        help="Search provider to use (default: brave).",
    )
    run_parser.add_argument(
        "--location",
        action="append",
        dest="locations",
        metavar="LOC",
        default=[],
        help=(
            "Allowed location (case-insensitive substring). "
            "Repeat for multiple locations.  Omit to accept all."
        ),
    )
    run_parser.add_argument(
        "--no-remote",
        action="store_true",
        default=False,
        help="Exclude fully-remote postings.",
    )
    run_parser.add_argument(
        "--keyword",
        action="append",
        dest="keywords",
        metavar="KW",
        default=[],
        help="Extra keyword to include in every search query (repeatable).",
    )
    run_parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        metavar="CAT",
        default=[],
        help=(
            "Filter results to this category and include the name in queries. "
            "Repeat for multiple categories.  Omit to show all."
        ),
    )
    run_parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        metavar="N",
        help="Maximum number of search results to fetch (default: 10).",
    )
    run_parser.add_argument(
        "--posted-within-days",
        type=int,
        default=None,
        metavar="DAYS",
        help=(
            "Only include postings whose date is within DAYS days of today. "
            "Applied only when date_posted_confidence is EXACT."
        ),
    )

    # --- list-categories --------------------------------------------------
    subparsers.add_parser(
        "list-categories",
        help="Print all known category names.",
    )

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    """Fetch → extract → filter → deduplicate → print summary."""
    # Lazy imports keep startup fast when other subcommands are used
    from internship_engine.categorization import categorize
    from internship_engine.config import get_settings
    from internship_engine.deduplication import DuplicateFilter
    from internship_engine.extractor import Extractor
    from internship_engine.location_filter import LocationFilter
    from internship_engine.models import DatePostedConfidence, JobPosting

    settings = get_settings()

    # ── Build the search source ───────────────────────────────────────────
    source, source_name = _build_source(args, settings)
    if source is None:
        return 1  # credential error already printed

    # ── Fetch raw search results ──────────────────────────────────────────
    raw_results = source.fetch(
        locations=args.locations,
        keywords=args.keywords,
        categories=args.categories,
    )

    if not raw_results:
        print("No search results returned. Check your API credentials and query.")
        return 0

    # ── Extract + normalise ───────────────────────────────────────────────
    extractor = Extractor()
    loc_filter = LocationFilter(
        allowed_locations=tuple(args.locations),
        include_remote=not args.no_remote,
    )
    dup_filter = DuplicateFilter()
    cutoff: date | None = (
        date.today() - timedelta(days=args.posted_within_days)
        if args.posted_within_days is not None
        else None
    )

    postings: list[JobPosting] = []

    for result in raw_results:
        ext = extractor.fetch_and_extract(result.url)

        # Build JobPosting — fall back to search snippet when extraction failed
        posting = JobPosting(
            title=ext.title or result.title,
            company=ext.company,
            location=ext.location,
            description=ext.description,
            posting_url=result.url,
            apply_url=ext.apply_url,
            date_posted=ext.date_posted,
            date_posted_confidence=ext.date_posted_confidence,
            source=source_name,
        )

        # ── Date filter (only when confidence is EXACT) ───────────────────
        if (
            cutoff is not None
            and posting.date_posted_confidence == DatePostedConfidence.EXACT
            and posting.date_posted is not None
            and posting.date_posted < cutoff
        ):
            continue

        # ── Location filter ───────────────────────────────────────────────
        if not loc_filter.matches(posting):
            continue

        # ── Deduplication ─────────────────────────────────────────────────
        if not dup_filter.is_new(posting):
            continue

        # ── Categorisation ────────────────────────────────────────────────
        category = categorize(posting)
        posting = posting.model_copy(update={"category": category})

        # ── Category filter ───────────────────────────────────────────────
        if args.categories and category.value not in args.categories:
            continue

        postings.append(posting)

    # ── Print summary ─────────────────────────────────────────────────────
    _print_summary(postings)
    return 0


def _build_source(args: argparse.Namespace, settings):
    """Return ``(source_instance, source_name)`` or ``(None, ...)`` on error."""
    if args.source == "brave":
        from internship_engine.sources.brave_search import (
            BraveSearchConfig,
            BraveSearchSource,
        )

        if not settings.brave_api_key:
            print(
                "Error: IE_BRAVE_API_KEY must be set.\n"
                "Get an API key at https://brave.com/search/api/ and add it\n"
                "to your .env file or set it as a GitHub Actions secret."
            )
            return None, "brave"

        config = BraveSearchConfig(
            api_key=settings.brave_api_key,
            max_results=args.max_results,
            posted_within_days=args.posted_within_days,
        )
        return BraveSearchSource(config), "brave"

    # args.source == "google"
    from internship_engine.sources.google_search import (
        GoogleSearchConfig,
        GoogleSearchSource,
    )

    if not settings.google_api_key or not settings.google_cse_id:
        print(
            "Error: IE_GOOGLE_API_KEY and IE_GOOGLE_CSE_ID must be set.\n"
            "Copy .env.example to .env and fill in your credentials."
        )
        return None, "google"

    config = GoogleSearchConfig(
        api_key=settings.google_api_key,
        cse_id=settings.google_cse_id,
        max_results=args.max_results,
        posted_within_days=args.posted_within_days,
    )
    return GoogleSearchSource(config), "google"


def _print_summary(postings: list) -> None:
    """Print a human-readable table of matched postings."""
    if not postings:
        print("No postings matched the given filters.")
        return

    print(f"\nFound {len(postings)} posting(s):\n")
    header = f"  {'#':<3}  {'Category':<12}  {'Title':<40}  {'Company':<25}  {'Location':<25}  Date"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for i, p in enumerate(postings, start=1):
        cat = p.category.value if p.category else "?"
        title = (p.title[:38] + "..") if len(p.title) > 40 else p.title
        company = (p.company[:23] + "..") if len(p.company) > 25 else p.company
        loc = (p.location[:23] + "..") if len(p.location) > 25 else p.location
        date_str = str(p.date_posted) if p.date_posted else "unknown"
        conf_marker = "" if p.date_posted_confidence.value == "exact" else "~"
        print(
            f"  {i:<3}  {cat:<12}  {title:<40}  {company:<25}  {loc:<25}  {conf_marker}{date_str}"
        )
        print(f"       {p.posting_url}")
        print()


def cmd_list_categories(_args: argparse.Namespace) -> int:
    """Print all :class:`~internship_engine.models.Category` values."""
    from internship_engine.models import Category

    for cat in Category:
        print(cat.value)
    return 0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    "run": cmd_run,
    "list-categories": cmd_list_categories,
}


def main(argv: list[str] | None = None) -> None:
    """Parse *argv* and dispatch to the appropriate command handler."""
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(0)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()
