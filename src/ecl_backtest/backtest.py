"""IFRS 9 ECL backtest: modeled vs realized loss over historical periods.

Iterates quarterly as_of_dates (2022-Q1 through 2023-Q4) and computes:
- Modeled ECL per loan at each as_of_date, using the SAME roll-rate-derived PD
  term structure the dbt ECL model uses (int_ecl_pd_term_structure).
- Realized loss (principal_writeoff_amount) observed 12 months later.

Outputs coverage_ratio = sum(realized) / sum(modeled) and bias by segment.
Results written to data/local/ecl_backtest_results_{run_date}.csv.

Why Python: the backtest loops over multiple historical as_of_dates — a
temporal iteration that cannot be expressed as set-based SQL without collapsing
to a single cutoff date.

PD methodology: PDs come from int_ecl_pd_term_structure, keyed by
(product_type, score_band, delinquency_bucket). Stage 1 uses the 12-month PD,
Stage 2 uses the lifetime PD, Stage 3 uses PD = 1.0. This mirrors the dbt ECL
model exactly, so the backtest validates the deployed Markov PD methodology and
the EAD/LGD parameterisation against realized losses — not a disconnected proxy.
"""

import datetime
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEEDS_DIR = REPO_ROOT / "seeds"
OUTPUT_DIR = REPO_ROOT / "data" / "local"
DUCKDB_FILE = OUTPUT_DIR / "credit_platform.duckdb"

BACKTEST_QUARTERS = [
    datetime.date(2022, 1, 1),
    datetime.date(2022, 4, 1),
    datetime.date(2022, 7, 1),
    datetime.date(2022, 10, 1),
    datetime.date(2023, 1, 1),
    datetime.date(2023, 4, 1),
    datetime.date(2023, 7, 1),
    datetime.date(2023, 10, 1),
]

MONTHS_FORWARD = 12


def load_seed(filename: str) -> pd.DataFrame:
    path = SEEDS_DIR / filename
    return pd.read_csv(path)


def load_dwh_data(connection: duckdb.DuckDBPyConnection) -> dict[str, pd.DataFrame]:
    fct_payment = connection.execute(
        "SELECT loan_id, product_type, report_month, months_on_book, "
        "ending_balance_amount, delinquency_bucket, loan_status, "
        "principal_writeoff_amount, recovery_amount "
        "FROM dwh.fct_payment"
    ).df()
    dim_loan = connection.execute(
        "SELECT loan_id, product_type, score_band, term_months, "
        "credit_limit_amount, interest_rate "
        "FROM dwh.dim_loan"
    ).df()
    pd_term_structure = connection.execute(
        "SELECT product_type, score_band, starting_bucket, "
        "CAST(pd_12m AS DOUBLE) AS pd_12m, "
        "CAST(pd_lifetime AS DOUBLE) AS pd_lifetime "
        "FROM int.int_ecl_pd_term_structure"
    ).df()
    return {
        "fct_payment": fct_payment,
        "dim_loan": dim_loan,
        "pd_term_structure": pd_term_structure,
    }


def model_pd(stage: int, pd_12m: float, pd_lifetime: float) -> float:
    """Return the PD the dbt ECL model applies for this stage.

    Stage 1 -> 12-month PD; Stage 2 -> lifetime PD; Stage 3 -> 1.0. Mirrors the
    horizon logic in int_ecl_components so the backtest uses the deployed PDs.
    """
    if stage == 3:
        return 1.0
    if stage == 2:
        return pd_lifetime
    return pd_12m


def assign_stage(delinquency_bucket: str, loan_status: str) -> int:
    if delinquency_bucket in ("dpd_90_plus", "default") or loan_status in (
        "defaulted",
        "recovery_complete",
    ):
        return 3
    if delinquency_bucket in ("dpd_30", "dpd_60"):
        return 2
    return 1


def compute_ead(row: pd.Series, ccf_rate: float) -> float:
    balance = row["ending_balance_amount"]
    if row["product_type"] == "credit_card":
        credit_limit = row.get("credit_limit_amount") or 0.0
        return max(0.0, balance + ccf_rate * (credit_limit - balance))
    return max(0.0, balance)


def compute_modeled_ecl_at_date(
    as_of_date: datetime.date,
    payments: pd.DataFrame,
    loans: pd.DataFrame,
    lgd_params: pd.DataFrame,
    ead_params: pd.DataFrame,
    pd_term_structure: pd.DataFrame,
) -> pd.DataFrame:
    snapshot = payments[payments["report_month"] <= pd.Timestamp(as_of_date)]
    if snapshot.empty:
        return pd.DataFrame()

    latest_idx = snapshot.groupby("loan_id")["months_on_book"].idxmax()
    current_state = snapshot.loc[latest_idx].copy()
    current_state = current_state.merge(
        loans[["loan_id", "score_band", "credit_limit_amount"]],
        on="loan_id",
    )

    lgd_map = lgd_params.set_index("product_type")["lgd_rate"].to_dict()
    ccf_map = ead_params.set_index("product_type")["ccf_rate"].to_dict()

    current_state["stage"] = current_state.apply(
        lambda r: assign_stage(r["delinquency_bucket"], r["loan_status"]), axis=1
    )

    unknown_product_types = set(current_state["product_type"]) - set(ccf_map)
    if unknown_product_types:
        raise ValueError(
            f"Unknown product types in CCF map: {sorted(unknown_product_types)}. "
            f"Add them to ecl_ead_parameters.csv."
        )
    current_state["ead"] = current_state.apply(
        lambda r: compute_ead(r, ccf_map[r["product_type"]]), axis=1
    )

    lgd_series = current_state["product_type"].map(lgd_map)
    missing_lgd = current_state.loc[lgd_series.isna(), "product_type"].unique()
    if len(missing_lgd) > 0:
        raise ValueError(
            f"Unknown product types in LGD map: {sorted(missing_lgd)}. "
            f"Add them to ecl_lgd_parameters.csv."
        )
    current_state["lgd"] = lgd_series

    # Join the model's PD term structure on (product_type, score_band, bucket).
    # Stage 3 buckets (dpd_90_plus, default) have no PD row but get PD = 1.0 in
    # model_pd. Segments with no observed transitions have no PD row either; left
    # join leaves NaN, which fillna(0.0) maps to no modeled loss for that loan.
    current_state = current_state.merge(
        pd_term_structure,
        how="left",
        left_on=["product_type", "score_band", "delinquency_bucket"],
        right_on=["product_type", "score_band", "starting_bucket"],
    )
    current_state["pd_12m"] = current_state["pd_12m"].fillna(0.0)
    current_state["pd_lifetime"] = current_state["pd_lifetime"].fillna(0.0)

    current_state["pd"] = current_state.apply(
        lambda r: model_pd(r["stage"], r["pd_12m"], r["pd_lifetime"]), axis=1
    )
    current_state["ecl"] = current_state["pd"] * current_state["lgd"] * current_state["ead"]

    return current_state[
        ["loan_id", "product_type", "score_band", "stage", "ead", "lgd", "pd", "ecl"]
    ]


def compute_realized_loss(
    as_of_date: datetime.date,
    payments: pd.DataFrame,
    horizon_months: int = MONTHS_FORWARD,
) -> pd.DataFrame:
    cutoff = pd.Timestamp(as_of_date)
    future_end = cutoff + pd.DateOffset(months=horizon_months)
    future = payments[
        (payments["report_month"] > cutoff) & (payments["report_month"] <= future_end)
    ]
    realized = future.groupby("loan_id")["principal_writeoff_amount"].sum().reset_index()
    realized.columns = ["loan_id", "realized_loss"]
    return realized


def run_backtest() -> pd.DataFrame:
    if not DUCKDB_FILE.exists():
        raise FileNotFoundError(f"DuckDB file not found: {DUCKDB_FILE}. Run 'make ci' first.")

    lgd_params = load_seed("ecl_lgd_parameters.csv")
    ead_params = load_seed("ecl_ead_parameters.csv")

    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        data = load_dwh_data(connection)

    payments = data["fct_payment"].copy()
    payments["report_month"] = pd.to_datetime(payments["report_month"])
    loans = data["dim_loan"]
    pd_term_structure = data["pd_term_structure"]

    all_results = []

    for as_of_date in BACKTEST_QUARTERS:
        modeled = compute_modeled_ecl_at_date(
            as_of_date, payments, loans, lgd_params, ead_params, pd_term_structure
        )
        if modeled.empty:
            continue

        realized = compute_realized_loss(as_of_date, payments)
        merged = modeled.merge(realized, on="loan_id", how="left")
        merged["realized_loss"] = merged["realized_loss"].fillna(0.0)
        merged["as_of_date"] = as_of_date
        all_results.append(merged)

    if not all_results:
        return pd.DataFrame()

    return pd.concat(all_results, ignore_index=True)


def summarize_backtest(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return pd.DataFrame()

    summary = (
        results.groupby(["product_type", "score_band", "stage"])
        .agg(
            total_modeled_ecl=("ecl", "sum"),
            total_realized_loss=("realized_loss", "sum"),
            loan_count=("loan_id", "nunique"),
        )
        .reset_index()
    )
    summary["coverage_ratio"] = summary["total_realized_loss"] / summary[
        "total_modeled_ecl"
    ].replace(0, float("nan"))
    summary["bias"] = summary["total_realized_loss"] - summary["total_modeled_ecl"]
    return summary


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_date = datetime.date.today().isoformat()

    results = run_backtest()
    summary = summarize_backtest(results)

    output_path = OUTPUT_DIR / f"ecl_backtest_results_{run_date}.csv"
    summary.to_csv(output_path, index=False)

    print(f"Backtest complete. Results written to {output_path}")
    if not summary.empty:
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
