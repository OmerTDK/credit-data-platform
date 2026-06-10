"""Tests for the `python -m loanbook` command-line interface."""

import subprocess
import sys
from pathlib import Path

import pytest

from loanbook.__main__ import main


class TestGenerateCommand:
    def test_generates_landing_zone_into_output_dir(self, tmp_path: Path) -> None:
        exit_code = main(
            [
                "generate",
                "--seed",
                "42",
                "--cohorts",
                "2",
                "--loans-per-cohort",
                "10",
                "--start-month",
                "2022-01",
                "--as-of-month",
                "2023-01",
                "--output-dir",
                str(tmp_path),
            ]
        )
        assert exit_code == 0
        assert (tmp_path / "loans" / "loans.parquet").is_file()
        assert (tmp_path / "borrowers" / "borrowers.parquet").is_file()
        assert any((tmp_path / "monthly_performance").iterdir())

    def test_summary_reports_row_counts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(
            [
                "generate",
                "--seed",
                "42",
                "--cohorts",
                "2",
                "--loans-per-cohort",
                "10",
                "--output-dir",
                str(tmp_path),
            ]
        )
        summary = capsys.readouterr().out
        assert "loans: 20" in summary
        assert "borrowers: 20" in summary
        assert "monthly_performance:" in summary

    def test_seed_is_required(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            main(["generate", "--output-dir", str(tmp_path)])

    def test_module_is_executable(self, tmp_path: Path) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "loanbook",
                "generate",
                "--seed",
                "7",
                "--cohorts",
                "1",
                "--loans-per-cohort",
                "5",
                "--output-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert (tmp_path / "loans" / "loans.parquet").is_file()
