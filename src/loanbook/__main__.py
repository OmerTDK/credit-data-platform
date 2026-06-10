"""Command-line entry point: python -m loanbook generate --seed 42 ..."""

import argparse
import sys
import time
from pathlib import Path

from loanbook.generate import (
    DEFAULT_COHORT_COUNT,
    DEFAULT_LOANS_PER_COHORT,
    GeneratorConfig,
    generate_loan_book,
)
from loanbook.months import parse_month
from loanbook.output import write_loan_book

DEFAULT_OUTPUT_DIR = "data/landing"
DEFAULT_START_MONTH_TEXT = "2022-01"
BYTES_PER_MEGABYTE = 1_000_000


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the loanbook command-line interface.

    Returns:
        Parser with the `generate` subcommand and its options wired to the
        generator defaults.
    """
    parser = argparse.ArgumentParser(
        prog="loanbook",
        description=(
            "Seeded synthetic credit-book generator "
            "(personal loans, auto loans, mortgages, credit cards)."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate_parser = subparsers.add_parser(
        "generate", help="Generate the loan book into a parquet landing zone."
    )
    generate_parser.add_argument("--seed", type=int, required=True)
    generate_parser.add_argument("--cohorts", type=int, default=DEFAULT_COHORT_COUNT)
    generate_parser.add_argument("--loans-per-cohort", type=int, default=DEFAULT_LOANS_PER_COHORT)
    generate_parser.add_argument(
        "--start-month",
        type=parse_month,
        default=parse_month(DEFAULT_START_MONTH_TEXT),
        help="First origination cohort, YYYY-MM.",
    )
    generate_parser.add_argument(
        "--as-of-month",
        type=parse_month,
        default=None,
        help="Observation cutoff, YYYY-MM. Defaults to 12 months after the last cohort.",
    )
    generate_parser.add_argument("--output-dir", type=Path, default=Path(DEFAULT_OUTPUT_DIR))
    return parser


def run_generate(arguments: argparse.Namespace) -> int:
    """Generate the loan book and write it to the parquet landing zone.

    Args:
        arguments: Parsed `generate` subcommand arguments.

    Returns:
        Process exit code: 0 on success.

    Raises:
        ValueError: If the parsed arguments form an invalid GeneratorConfig.
    """
    config = GeneratorConfig(
        seed=arguments.seed,
        cohort_count=arguments.cohorts,
        loans_per_cohort=arguments.loans_per_cohort,
        start_month=arguments.start_month,
        as_of_month=arguments.as_of_month,
    )
    started_at = time.perf_counter()
    book = generate_loan_book(config)
    written_files = write_loan_book(book, arguments.output_dir)
    elapsed_seconds = time.perf_counter() - started_at
    total_bytes = sum(file.stat().st_size for file in written_files)
    print(f"loans: {len(book.loans)}")
    print(f"borrowers: {len(book.borrowers)}")
    print(f"monthly_performance: {len(book.monthly_performance)}")
    print(f"files: {len(written_files)} ({total_bytes / BYTES_PER_MEGABYTE:.1f} MB)")
    print(f"seconds: {elapsed_seconds:.1f}")
    print(f"landing_dir: {arguments.output_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the requested command.

    Args:
        argv: Argument list to parse; None means sys.argv.

    Returns:
        Process exit code: 0 on success.

    Raises:
        ValueError: If the parsed command has no handler.
    """
    arguments = build_parser().parse_args(argv)
    if arguments.command == "generate":
        return run_generate(arguments)
    raise ValueError(f"Unknown command: {arguments.command}")


if __name__ == "__main__":
    sys.exit(main())
