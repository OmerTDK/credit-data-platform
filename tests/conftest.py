"""Pytest configuration for the credit-data-platform suite.

``src/orchestration/definitions.py`` loads ``@dbt_assets`` from
``target/manifest.json`` at import time, so the manifest must exist before
pytest collects ``tests/test_orchestration_*.py``. A fresh checkout (CI, or a
clean local clone) has no manifest until dbt parses the project. Generate it
once here, before collection, so the suite is self-sufficient and cannot pass
locally on a stale manifest while failing in clean CI.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def pytest_configure(config) -> None:  # noqa: ARG001 - pytest hook signature
    manifest = _REPO_ROOT / "target" / "manifest.json"
    if manifest.exists():
        return
    env = {**os.environ, "DBT_PROFILES_DIR": "."}
    # dbt parse (not run/build) — generates the manifest only; deps first so the
    # Elementary package is present for compilation.
    subprocess.run(["uv", "run", "dbt", "deps"], cwd=_REPO_ROOT, env=env, check=True)
    subprocess.run(["uv", "run", "dbt", "parse"], cwd=_REPO_ROOT, env=env, check=True)
