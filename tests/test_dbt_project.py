"""Verify the dbt project parses cleanly with the committed dev profile."""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dbt_parse_succeeds() -> None:
    completed = subprocess.run(
        ["uv", "run", "dbt", "parse"],
        cwd=REPO_ROOT,
        env={**os.environ, "DBT_PROFILES_DIR": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        f"dbt parse failed (exit {completed.returncode}):\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
