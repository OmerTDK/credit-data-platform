"""Generator parameters anchored to published consumer-credit statistics.

Every anchor is cited in docs/calibration-sources.md. Parameters marked
stylized there are interpolations consistent with the published aggregates,
not fitted values. Empirical fitting against loan-level performance data
(Fannie Mae style) is a documented open interface — see
load_calibration_from_loan_performance_data.
"""

from dataclasses import dataclass, field


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
class Calibration:
    """All stochastic parameters of the generator, in one auditable place."""

    origination_mix_by_band: dict[str, float] = field(
        default_factory=lambda: {
            "subprime": 0.20,
            "near_prime": 0.25,
            "prime": 0.30,
            "prime_plus": 0.15,
            "super_prime": 0.10,
        }
    )
    annual_interest_rate_by_band: dict[str, float] = field(
        default_factory=lambda: {
            "subprime": 0.249,
            "near_prime": 0.179,
            "prime": 0.129,
            "prime_plus": 0.099,
            "super_prime": 0.075,
        }
    )
    interest_rate_noise_half_width: float = 0.015
    monthly_delinquency_entry_hazard_by_band: dict[str, float] = field(
        default_factory=lambda: {
            "subprime": 0.055,
            "near_prime": 0.028,
            "prime": 0.012,
            "prime_plus": 0.005,
            "super_prime": 0.002,
        }
    )
    delinquent_roll_probabilities: dict[str, dict[str, float]] = field(
        default_factory=lambda: {
            "dpd_30": {"cure": 0.35, "stay": 0.25, "roll_deeper": 0.40},
            "dpd_60": {"cure": 0.20, "stay": 0.25, "roll_deeper": 0.55},
            "dpd_90_plus": {"cure": 0.10, "stay": 0.20, "roll_deeper": 0.70},
        }
    )
    monthly_prepayment_rate_by_band: dict[str, float] = field(
        default_factory=lambda: {
            "subprime": 0.0134,
            "near_prime": 0.0184,
            "prime": 0.0237,
            "prime_plus": 0.0270,
            "super_prime": 0.0293,
        }
    )
    recovery_rate_on_defaulted_balance: float = 0.08
    recovery_lag_months: int = 6
    term_months_mix: dict[int, float] = field(default_factory=lambda: {36: 0.7, 60: 0.3})
    loan_amount_min_cents: int = 100_000
    loan_amount_max_cents: int = 4_000_000
    loan_amount_log_median_cents: float = 1_000_000.0
    loan_amount_log_sigma: float = 0.55
    loan_amount_rounding_cents: int = 2_500
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

    Documented interface only: which public dataset to fit against (and
    whether the fitting belongs in this repo or a notebook) is an open
    question pending with Omer. No fitted calibration has been run, so this
    deliberately refuses rather than pretending.

    Args:
        source_path: Path to a loan-level performance extract.

    Raises:
        NotImplementedError: Always, until the empirical calibration lands.
    """
    raise NotImplementedError(
        f"Empirical calibration from {source_path!r} has not been run yet. "
        "Use default_calibration() — anchors documented in docs/calibration-sources.md."
    )
