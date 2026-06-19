"""Validate ECL seed parameters before dbt build.

Asserts:
- Scenario weights sum to 1.0.
- All LGD rates in [0, 1].
- All CCF rates in [0, 1].

Exits non-zero on any violation so Makefile can gate the dbt build.
"""

import sys
from pathlib import Path

import pandas as pd

SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "seeds"

WEIGHT_TOLERANCE = 0.0001


def load_seed(filename: str) -> pd.DataFrame:
    path = SEEDS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Seed file not found: {path}")
    return pd.read_csv(path)


def validate_scenario_weights(scenario_weights: pd.DataFrame) -> list[str]:
    violations = []
    total = scenario_weights["scenario_weight"].sum()
    if abs(total - 1.0) > WEIGHT_TOLERANCE:
        violations.append(
            f"Scenario weights sum to {total:.6f}, expected 1.0 (tolerance {WEIGHT_TOLERANCE})"
        )
    return violations


def validate_lgd_rates(lgd_params: pd.DataFrame) -> list[str]:
    violations = []
    out_of_range = lgd_params[(lgd_params["lgd_rate"] < 0.0) | (lgd_params["lgd_rate"] > 1.0)]
    for _, row in out_of_range.iterrows():
        violations.append(f"LGD rate {row['lgd_rate']} for {row['product_type']} is outside [0, 1]")
    return violations


def validate_ccf_rates(ead_params: pd.DataFrame) -> list[str]:
    violations = []
    out_of_range = ead_params[(ead_params["ccf_rate"] < 0.0) | (ead_params["ccf_rate"] > 1.0)]
    for _, row in out_of_range.iterrows():
        violations.append(f"CCF rate {row['ccf_rate']} for {row['product_type']} is outside [0, 1]")
    return violations


def run_validation() -> list[str]:
    scenario_weights = load_seed("ecl_scenario_weights.csv")
    lgd_params = load_seed("ecl_lgd_parameters.csv")
    ead_params = load_seed("ecl_ead_parameters.csv")

    return (
        validate_scenario_weights(scenario_weights)
        + validate_lgd_rates(lgd_params)
        + validate_ccf_rates(ead_params)
    )


def main() -> None:
    violations = run_validation()
    if violations:
        for violation in violations:
            print(f"VIOLATION: {violation}", file=sys.stderr)
        sys.exit(1)
    print("ECL parameter validation passed.")


if __name__ == "__main__":
    main()
