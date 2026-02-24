"""CLI entry point skeleton.

Registered as the ``internship-engine`` console script via pyproject.toml.

Subcommands
-----------
run              Fetch and process new postings (not yet implemented).
list-categories  Print all recognised category names.
version          Print the package version and exit.

Usage examples
--------------
$ internship-engine --help
$ internship-engine list-categories
$ internship-engine run --location "New York" --location "Remote"
$ internship-engine run --no-remote --category software --category data
"""

from __future__ import annotations

import argparse
import sys

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
        description="Fetch new postings from configured sources and apply filters.",
    )
    run_parser.add_argument(
        "--location",
        action="append",
        dest="locations",
        metavar="LOC",
        default=[],
        help=(
            "Allowed location (case-insensitive substring). "
            "Repeat to allow multiple locations. "
            "Omit to accept all locations."
        ),
    )
    run_parser.add_argument(
        "--no-remote",
        action="store_true",
        default=False,
        help="Exclude remote postings from results.",
    )
    run_parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        metavar="CAT",
        default=[],
        help=(
            "Only show postings in this category. "
            "Repeat to allow multiple categories. "
            "Omit to show all categories."
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
    """Placeholder handler for the ``run`` subcommand."""
    print("The 'run' command is not yet implemented.")
    print(f"  locations : {args.locations or '(all)'}")
    print(f"  no-remote : {args.no_remote}")
    print(f"  categories: {args.categories or '(all)'}")
    return 0


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
    """Parse *argv* and dispatch to the appropriate command handler.

    Exits with the handler's return code, or 0 when no subcommand is given
    (help is printed instead).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(0)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()
