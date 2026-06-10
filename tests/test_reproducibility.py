"""Same seed must mean byte-identical parquet output; different seed must not."""

import hashlib
from datetime import date
from pathlib import Path

from loanbook.generate import GeneratorConfig, generate_loan_book
from loanbook.output import write_loan_book


def config_with_seed(seed: int) -> GeneratorConfig:
    return GeneratorConfig(
        seed=seed,
        cohort_count=3,
        loans_per_cohort=30,
        start_month=date(2022, 1, 1),
        as_of_month=date(2023, 6, 1),
    )


def generate_and_hash_files(seed: int, landing_dir: Path) -> dict[str, str]:
    book = generate_loan_book(config_with_seed(seed))
    written_files = write_loan_book(book, landing_dir)
    return {
        str(file.relative_to(landing_dir)): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in written_files
    }


class TestByteIdenticalReproducibility:
    def test_same_seed_produces_byte_identical_parquet(self, tmp_path: Path) -> None:
        first_run = generate_and_hash_files(42, tmp_path / "first")
        second_run = generate_and_hash_files(42, tmp_path / "second")
        assert first_run == second_run
        assert len(first_run) > 2

    def test_different_seed_produces_different_parquet(self, tmp_path: Path) -> None:
        seed_42_hashes = generate_and_hash_files(42, tmp_path / "seed42")
        seed_43_hashes = generate_and_hash_files(43, tmp_path / "seed43")
        assert seed_42_hashes["loans/loans.parquet"] != seed_43_hashes["loans/loans.parquet"]
