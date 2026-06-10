"""Generator parameters anchored to published consumer-credit statistics.

Every anchor is cited in docs/calibration-sources.md, per product. Parameters
marked stylized there are interpolations consistent with the published
aggregates, not fitted values. Empirical fitting against loan-level
performance data (Fannie Mae style) is a documented open interface — see
load_calibration_from_loan_performance_data.
"""

from dataclasses import dataclass, field

from loanbook.products import ProductType


@dataclass(frozen=True)
class ScoreBand:
    name: str
    score_min: int
    score_max: int


SCORE_BANDS: tuple[ScoreBand, ...] = (
    ScoreBand("subprime", 300, 600),
    ScoreBand("near_prime", 601, 660),
    ScoreBand("prime", 661, 720),
    ScoreBand("prime_plus", 721, 780),
    ScoreBand("super_prime", 781, 850),
)

SCORE_BAND_BY_NAME: dict[str, ScoreBand] = {band.name: band for band in SCORE_BANDS}


@dataclass(frozen=True)
class AmortizingProductCalibration:
    """Stochastic parameters of one installment product, in one auditable place."""

    annual_interest_rate_by_band: dict[str, float]
    interest_rate_noise_half_width: float
    term_months_mix: dict[int, float]
    amount_min_cents: int
    amount_max_cents: int
    amount_log_median_cents: float
    amount_log_sigma: float
    amount_rounding_cents: int
    monthly_delinquency_entry_hazard_by_band: dict[str, float]
    delinquent_roll_probabilities: dict[str, dict[str, float]]
    monthly_prepayment_rate_by_band: dict[str, float]
    recovery_rate_on_defaulted_balance: float
    recovery_lag_months: int


@dataclass(frozen=True)
class RevolvingProductCalibration:
    """Stochastic parameters of the revolving card product."""

    annual_interest_rate_by_band: dict[str, float]
    interest_rate_noise_half_width: float
    credit_limit_cents_by_band: dict[str, int]
    target_utilization_by_band: dict[str, float]
    spend_replenishment_min: float
    spend_replenishment_max: float
    pay_in_full_probability_by_band: dict[str, float]
    minimum_payment_principal_rate: float
    minimum_payment_floor_cents: int
    monthly_delinquency_entry_hazard_by_band: dict[str, float]
    delinquent_roll_probabilities: dict[str, dict[str, float]]
    recovery_rate_on_charged_off_balance: float
    recovery_lag_months: int


def _personal_loan_calibration() -> AmortizingProductCalibration:
    return AmortizingProductCalibration(
        annual_interest_rate_by_band={
            "subprime": 0.249,
            "near_prime": 0.179,
            "prime": 0.129,
            "prime_plus": 0.099,
            "super_prime": 0.075,
        },
        # The ±150bp pricing noise makes adjacent band rate ranges overlap at
        # the boundary (prime_plus 8.4-11.4% vs super_prime 6.0-9.0%).
        # Intentional: real rate sheets show cross-band dispersion from
        # risk-based pricing add-ons, so band is not perfectly recoverable
        # from rate (ADR-0002).
        interest_rate_noise_half_width=0.015,
        term_months_mix={36: 0.7, 60: 0.3},
        amount_min_cents=100_000,
        amount_max_cents=4_000_000,
        amount_log_median_cents=1_000_000.0,
        amount_log_sigma=0.55,
        amount_rounding_cents=2_500,
        monthly_delinquency_entry_hazard_by_band={
            "subprime": 0.070,
            "near_prime": 0.034,
            "prime": 0.012,
            "prime_plus": 0.005,
            "super_prime": 0.002,
        },
        delinquent_roll_probabilities={
            "dpd_30": {"cure": 0.35, "stay": 0.25, "roll_deeper": 0.40},
            "dpd_60": {"cure": 0.20, "stay": 0.25, "roll_deeper": 0.55},
            "dpd_90_plus": {"cure": 0.10, "stay": 0.20, "roll_deeper": 0.70},
        },
        monthly_prepayment_rate_by_band={
            "subprime": 0.0134,
            "near_prime": 0.0184,
            "prime": 0.0237,
            "prime_plus": 0.0270,
            "super_prime": 0.0293,
        },
        recovery_rate_on_defaulted_balance=0.08,
        recovery_lag_months=6,
    )


def _auto_loan_calibration() -> AmortizingProductCalibration:
    return AmortizingProductCalibration(
        annual_interest_rate_by_band={
            "subprime": 0.189,
            "near_prime": 0.139,
            "prime": 0.099,
            "prime_plus": 0.075,
            "super_prime": 0.064,
        },
        interest_rate_noise_half_width=0.015,
        term_months_mix={36: 0.05, 48: 0.10, 60: 0.22, 72: 0.33, 84: 0.30},
        amount_min_cents=400_000,
        amount_max_cents=12_000_000,
        amount_log_median_cents=2_800_000.0,
        amount_log_sigma=0.35,
        amount_rounding_cents=10_000,
        monthly_delinquency_entry_hazard_by_band={
            "subprime": 0.042,
            "near_prime": 0.018,
            "prime": 0.006,
            "prime_plus": 0.0025,
            "super_prime": 0.0010,
        },
        delinquent_roll_probabilities={
            "dpd_30": {"cure": 0.38, "stay": 0.25, "roll_deeper": 0.37},
            "dpd_60": {"cure": 0.22, "stay": 0.25, "roll_deeper": 0.53},
            "dpd_90_plus": {"cure": 0.10, "stay": 0.20, "roll_deeper": 0.70},
        },
        monthly_prepayment_rate_by_band={
            "subprime": 0.0150,
            "near_prime": 0.0180,
            "prime": 0.0210,
            "prime_plus": 0.0240,
            "super_prime": 0.0260,
        },
        recovery_rate_on_defaulted_balance=0.45,
        recovery_lag_months=3,
    )


def _mortgage_calibration() -> AmortizingProductCalibration:
    return AmortizingProductCalibration(
        annual_interest_rate_by_band={
            "subprime": 0.0775,
            "near_prime": 0.0715,
            "prime": 0.0675,
            "prime_plus": 0.0645,
            "super_prime": 0.0625,
        },
        interest_rate_noise_half_width=0.0025,
        term_months_mix={180: 0.1, 360: 0.9},
        amount_min_cents=5_000_000,
        amount_max_cents=150_000_000,
        amount_log_median_cents=32_000_000.0,
        amount_log_sigma=0.45,
        amount_rounding_cents=100_000,
        monthly_delinquency_entry_hazard_by_band={
            "subprime": 0.012,
            "near_prime": 0.005,
            "prime": 0.002,
            "prime_plus": 0.0008,
            "super_prime": 0.0004,
        },
        delinquent_roll_probabilities={
            "dpd_30": {"cure": 0.45, "stay": 0.30, "roll_deeper": 0.25},
            "dpd_60": {"cure": 0.30, "stay": 0.30, "roll_deeper": 0.40},
            "dpd_90_plus": {"cure": 0.15, "stay": 0.30, "roll_deeper": 0.55},
        },
        monthly_prepayment_rate_by_band={
            "subprime": 0.0043,
            "near_prime": 0.0051,
            "prime": 0.0060,
            "prime_plus": 0.0069,
            "super_prime": 0.0078,
        },
        recovery_rate_on_defaulted_balance=0.70,
        recovery_lag_months=12,
    )


def _credit_card_calibration() -> RevolvingProductCalibration:
    return RevolvingProductCalibration(
        annual_interest_rate_by_band={
            "subprime": 0.279,
            "near_prime": 0.249,
            "prime": 0.225,
            "prime_plus": 0.205,
            "super_prime": 0.185,
        },
        interest_rate_noise_half_width=0.015,
        credit_limit_cents_by_band={
            "subprime": 250_000,
            "near_prime": 500_000,
            "prime": 800_000,
            "prime_plus": 1_100_000,
            "super_prime": 1_500_000,
        },
        target_utilization_by_band={
            "subprime": 0.75,
            "near_prime": 0.50,
            "prime": 0.32,
            "prime_plus": 0.18,
            "super_prime": 0.08,
        },
        spend_replenishment_min=0.5,
        spend_replenishment_max=1.5,
        pay_in_full_probability_by_band={
            "subprime": 0.05,
            "near_prime": 0.15,
            "prime": 0.35,
            "prime_plus": 0.55,
            "super_prime": 0.75,
        },
        minimum_payment_principal_rate=0.01,
        minimum_payment_floor_cents=3_000,
        monthly_delinquency_entry_hazard_by_band={
            "subprime": 0.015,
            "near_prime": 0.007,
            "prime": 0.003,
            "prime_plus": 0.0012,
            "super_prime": 0.0005,
        },
        delinquent_roll_probabilities={
            "dpd_30": {"cure": 0.30, "stay": 0.25, "roll_deeper": 0.45},
            "dpd_60": {"cure": 0.18, "stay": 0.25, "roll_deeper": 0.57},
            "dpd_90_plus": {"cure": 0.08, "stay": 0.22, "roll_deeper": 0.70},
        },
        recovery_rate_on_charged_off_balance=0.08,
        recovery_lag_months=6,
    )


@dataclass(frozen=True)
class Calibration:
    """All stochastic parameters of the generator, grouped per product."""

    product_mix: dict[str, float] = field(
        default_factory=lambda: {
            ProductType.CREDIT_CARD.value: 0.55,
            ProductType.PERSONAL_LOAN.value: 0.20,
            ProductType.AUTO_LOAN.value: 0.17,
            ProductType.MORTGAGE.value: 0.08,
        }
    )
    amortizing_products: dict[str, AmortizingProductCalibration] = field(
        default_factory=lambda: {
            ProductType.PERSONAL_LOAN.value: _personal_loan_calibration(),
            ProductType.AUTO_LOAN.value: _auto_loan_calibration(),
            ProductType.MORTGAGE.value: _mortgage_calibration(),
        }
    )
    credit_card: RevolvingProductCalibration = field(default_factory=_credit_card_calibration)
    origination_mix_by_band: dict[str, float] = field(
        default_factory=lambda: {
            "subprime": 0.20,
            "near_prime": 0.25,
            "prime": 0.30,
            "prime_plus": 0.15,
            "super_prime": 0.10,
        }
    )
    age_band_mix: dict[str, float] = field(
        default_factory=lambda: {
            "18-24": 0.10,
            "25-34": 0.30,
            "35-44": 0.25,
            "45-54": 0.18,
            "55-64": 0.12,
            "65+": 0.05,
        }
    )
    income_band_mix: dict[str, float] = field(
        default_factory=lambda: {
            "under_25k": 0.08,
            "25k_to_50k": 0.22,
            "50k_to_75k": 0.28,
            "75k_to_100k": 0.20,
            "over_100k": 0.22,
        }
    )
    region_mix: dict[str, float] = field(
        default_factory=lambda: {
            "northeast": 0.17,
            "midwest": 0.21,
            "south": 0.38,
            "west": 0.24,
        }
    )


def default_calibration() -> Calibration:
    """The published-statistics-anchored parameter set used by the generator."""
    return Calibration()


def load_calibration_from_loan_performance_data(source_path: str) -> Calibration:
    """Fit a Calibration from loan-level performance data (Fannie Mae style).

    Empirical calibration is intentionally unimplemented; see
    docs/calibration-sources.md for the planned data sources. No fitted
    calibration has been run, so this deliberately refuses rather than
    pretending.

    Args:
        source_path: Path to a loan-level performance extract.

    Raises:
        NotImplementedError: Always, until the empirical calibration lands.
    """
    raise NotImplementedError(
        f"Empirical calibration from {source_path!r} has not been run yet. "
        "Use default_calibration() — anchors documented in docs/calibration-sources.md."
    )
