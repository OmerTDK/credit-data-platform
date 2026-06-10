# Calibration sources — all four products

Where every number in `src/loanbook/calibration.py` comes from. Two classes of
parameter:

- **Anchored** — taken directly from a published statistic, cited below.
- **Stylized** — interpolated to be consistent with the published aggregates
  (e.g. per-band values whose mix-weighted average must land near a published
  overall figure). Stylized values are labeled as such; none of them claim to
  be fitted.

An empirical fit against loan-level public performance data (Fannie Mae
single-family style, or the Kaggle LendingClub loan file) is a **documented
open interface** — `load_calibration_from_loan_performance_data` — and is
intentionally unimplemented. No fitted calibration has been run.

Realized values quoted below come from the default run (`--seed 42
--cohorts 24 --loans-per-cohort 500`, cohorts 2022-01..2023-12, as-of
2024-12) unless a test-population horizon is stated.

## Shared parameters

### Score bands — anchored

VantageScore 4.0 risk tiers as used in TransUnion's industry reporting:
subprime 300–600, near prime 601–660, prime 661–720, prime plus 721–780,
super prime 781–850.

- VantageScore, "The Complete Guide to Your VantageScore":
  <https://vantagescore.com/consumers/blog/the-complete-guide-to-your-vantagescore>
- CNBC Select summary of the TransUnion/VantageScore tier definitions:
  <https://www.cnbc.com/select/borrower-risk-profiles-based-on-credit-score/>

### Delinquency buckets and default thresholds — anchored

Bucket semantics (30/60/90+ days past due as 1/2/3 payments behind) follow the
New York Fed Consumer Credit Panel delinquency-status definitions. Default
thresholds follow the FFIEC Uniform Retail Credit Classification policy:
**closed-end** retail loans are classified Loss and charged off at **120
cumulative days past due (4 missed monthly payments)**; **open-end** retail
credit is charged off at **180 days past due (6 missed minimum payments)** —
the months between 90 and 180 days stay in the 90+ bucket.

- NY Fed Quarterly Report on Household Debt and Credit (status definitions):
  <https://www.newyorkfed.org/medialibrary/interactives/householdcredit/data/pdf/HHDC_2025Q1>
- FFIEC Uniform Retail Credit Classification and Account Management Policy
  (Federal Register, June 12, 2000):
  <https://www.federalregister.gov/documents/2000/06/12/00-14704/uniform-retail-credit-classification-and-account-management-policy>
- OCC Bulletin 2000-20 (implementation):
  <https://www.occ.treas.gov/news-issuances/bulletins/2000/bulletin-2000-20.html>

Applying the closed-end 120-day default to mortgages is a **stylized
simplification**: real mortgage resolution runs through a foreclosure pipeline
that takes far longer (GSE loan-performance data tracks D180 and
foreclosure-specific outcomes). The longer "stay" probabilities in the
mortgage roll matrix approximate that pipeline; the terminal threshold is not
product-specific in this model.

### Borrower attributes — anchored region mix, stylized age/income

- `region_mix` uses the four US census regions at approximate 2020 Census
  population shares (NE 17%, MW 21%, S 38%, W 24%):
  <https://www.census.gov/library/stories/state-by-state.html>
- `age_band_mix` and `income_band_mix` are **stylized**, skewed toward the
  25–44 and middle-income cohorts that dominate consumer borrowing.

### Product mix — anchored direction, stylized weights

The default book mix by **account count** is `credit_card` 0.55,
`personal_loan` 0.20, `auto_loan` 0.17, `mortgage` 0.08 — **stylized** so the
generated book is card-heavy by count and mortgage-heavy by balance, the
qualitative composition of US household debt in the NY Fed Quarterly Report
on Household Debt and Credit (Q3 2025: mortgage $13.07T of $18.59T total
balances ≈ 70%, credit cards $1.23T, auto $1.66T — while card accounts far
outnumber every other product).

- NY Fed Q3 2025 press release:
  <https://www.newyorkfed.org/newsevents/news/research/2025/20251105>
- Report data: <https://www.newyorkfed.org/medialibrary/interactives/householdcredit/data/pdf/hhdc_2025q3.pdf>

Realized composition for the default run: count share card 55.0%, personal
19.8%, auto 17.3%, mortgage 7.9%; open-balance share at the as-of month
mortgage 87%, auto 8%, card 3%, personal 2%. The mortgage balance share
overshoots the NY Fed 70% because the synthetic book carries no student-loan
or HELOC balances.

## Personal loans

### Delinquency levels — anchored targets, stylized roll rates

TransUnion Q3 2025 Credit Industry Insights Report, unsecured personal loans:
60+ DPD borrower delinquency **3.52%** overall, **11.4%** for subprime.

- <https://newsroom.transunion.com/q3-2025-ciir/>

The per-band monthly entry hazards and the cure/stay/roll-deeper
probabilities per bucket are **stylized**: monotone in risk band, early-stage
delinquency mostly curing and late-stage mostly rolling forward (the
qualitative pattern in the NY Fed transition data), scaled so the generated
book's point-in-time 60+ DPD share sits near the TransUnion figure. Realized
for the default run: **3.25%** of active personal loans 60+ DPD at the as-of
month (anchor 3.52%).

### Lifetime defaults — anchored target, stylized per band

Marketplace personal loans (LendingClub public loan file, 2007–2020Q3,
completed loans): **19.36% charged off** vs 80.64% fully paid. Charge-off
rates rise monotonically as grade worsens.

- Sandoval Serrano et al., "Loan Default Prediction: A Complete Revision of
  LendingClub", Revista mexicana de economía y finanzas (2023):
  <https://www.scielo.org.mx/scielo.php?script=sci_arttext&pid=S1665-53462023000300001>
- Grade→default monotonicity in the same public dataset:
  <https://emmanuel-r8.github.io/project/lendingclub/lendingclub/dataset.html>

Realized lifetime (fully observed test population, 36–60-month terms):
subprime 40.1%, near prime 27.5%, prime 9.4%, prime plus 4.7%, super prime
1.6% — monotone, mix-consistent with the ~19% uncensored LendingClub figure.

### Interest rates — anchored bounds, stylized per band

- Average 24-month personal loan rate at commercial banks: ~11.4% (2025
  readings). FRED series TERMCBPER24NS (Fed G.19 source data):
  <https://fred.stlouisfed.org/series/TERMCBPER24NS>
- Marketplace pricing exceeds 30% APR at the riskiest grades (LendingClub
  July 2019 rate grid): <https://emmanuel-r8.github.io/project/lendingclub/lendingclub/dataset.html>

`annual_interest_rate_by_band` (7.5%–24.9% plus ±1.5% within-band noise) is
**stylized** between those bounds; the realized mix-weighted average (15.6%)
sits above the bank-loan G.19 average deliberately, because the configured
origination mix is marketplace-style.

### Loan amounts and terms — anchored

- Average unsecured personal loan debt per borrower: **$11,724** (TransUnion
  Q3 2025 CIIR): <https://newsroom.transunion.com/q3-2025-ciir/>
- LendingClub loans ranged $1,000–$40,000 with 36- or 60-month terms (public
  loan file): <https://www.kaggle.com/datasets/wordsforthewise/lending-club>

Amounts are lognormal with median $10,000 and sigma 0.55 (realized mean
$11,526, near the TransUnion per-borrower figure), clipped to
$1,000–$40,000, rounded to $25. The 70/30 term mix between 36 and 60 months
is **stylized** around the LendingClub two-term structure.

### Prepayment — anchored direction, stylized speeds

Prepayment is more frequent than default in online consumer lending (Li, Li,
Yao, Wen 2019, *Emerging Markets Finance and Trade* 55(1), 118–132):

- <https://www.tandfonline.com/doi/full/10.1080/1540496X.2018.1479251>

`monthly_prepayment_rate_by_band` is **stylized**: single monthly mortality
(SMM) values equivalent to 15%–30% annual CPR, increasing with credit quality.
SMM = 1 − (1 − CPR)^(1/12), the standard dv01 definition:
<https://dv01.freshdesk.com/support/solutions/articles/42000052036-cpr-calculation>

### Recoveries — stylized

8% of the balance at charge-off, received as a lump sum 6 months after
default. Unsecured consumer LGD is high (recoveries thin); the parameter is
stylized pending the empirical calibration hook.

## Auto loans

### Amounts and terms — anchored

Experian State of the Automotive Finance Market: average loan amount
**$41,720 new / $26,144 used** (Q1 2025); average term **68.9 months new /
67.7 used**, with ~32% of new loans at 73+ months.

- <https://www.experian.com/blogs/ask-experian/average-car-loan-interest-rates-by-credit-score/>
- <https://www.experian.com/blogs/ask-experian/what-is-the-average-length-of-a-car-loan/>
- TransUnion Q3 2025 CIIR average auto balance per consumer $24,602:
  <https://newsroom.transunion.com/q3-2025-ciir/>

Amounts are **stylized** as a single new/used blend: lognormal median
$28,000, sigma 0.35 (realized mean $29,661), clipped $4,000–$120,000, rounded
to $100. The term mix {36: 5%, 48: 10%, 60: 22%, 72: 33%, 84: 30%} is
**stylized** to reproduce the published ~69-month average and ~30% share of
73+-month terms.

### Interest rates — anchored bounds, stylized per band

Experian Q1 2025 average APR by score tier: new 5.18% (super prime) to 15.81%
(deep subprime); used 6.82% to 21.58%.

- <https://www.experian.com/blogs/ask-experian/average-car-loan-interest-rates-by-credit-score/>

`annual_interest_rate_by_band` (6.4%–18.9% ±1.5% noise) is **stylized** as a
new/used blend inside those bounds, monotone in band.

### Delinquency — anchored target, stylized hazards and rolls

TransUnion Q3 2025 CIIR: auto 60+ DPD account-level delinquency **1.45%**.

- <https://newsroom.transunion.com/q3-2025-ciir/>

Entry hazards and rolls are **stylized** below the personal-loan hazards
(secured collateral disciplines payment behavior), scaled so the default
book realizes **1.38%** of active auto loans 60+ DPD at the as-of month.
Realized lifetime default (fully observed test population): subprime 26.5%,
near prime 11.7%, prime 3.3%, prime plus 2.0%, super prime 0.0%.

### Prepayment and recovery — stylized

SMM 1.5%–2.6% monthly (≈17%–27% CPR), increasing with credit quality —
trade-ins and refinancing turn auto loans over faster than personal loans.
Recovery on default: 45% of the defaulted balance 3 months after charge-off
(repossession proceeds; secured LGD well below unsecured). Both stylized.

## Mortgages

### Amounts and terms — anchored

- MBA Weekly Applications Survey: average purchase loan size **$467,300**
  (May 2026 reading, all-time survey high):
  <https://www.mba.org/news-and-research/newsroom/news/2026/05/06/mortgage-applications-decrease-in-latest-mba-weekly-survey>
- TransUnion Q3 2025 CIIR average mortgage balance per consumer **$268,060**:
  <https://newsroom.transunion.com/q3-2025-ciir/>
- The 30-year fixed dominates US purchase originations (~90% share; 15-year a
  single-digit share): Urban Institute data summarized at
  <https://www.thetruthaboutmortgage.com/mortgage-originations-by-product-type-whats-most-popular/>,
  Freddie Mac on the 30-year FRM:
  <https://sf.freddiemac.com/articles/insights/why-americas-homebuyers-communities-rely-on-the-30-year-fixed-rate-mortgage>

Amounts are **stylized** between the outstanding-balance and new-origination
anchors: lognormal median $320,000, sigma 0.45 (realized mean $359,327),
clipped $50,000–$1,500,000, rounded to $1,000. Term mix {360: 90%, 180: 10%}
is **anchored** to the 30-year dominance.

### Interest rates — anchored level, stylized spread

Freddie Mac Primary Mortgage Market Survey: 30-year FRM averaged **6.15%**
(Dec 2025) to **6.48%** (Jun 2026); 15-year 5.44%–5.79%.

- <https://www.freddiemac.com/pmms>

`annual_interest_rate_by_band` (6.25%–7.75% ±0.25% noise) is **stylized**
around the PMMS level with a modest credit spread — mortgage pricing varies
far less by score than consumer credit (LLPA-style add-ons), hence the
narrower band spread and noise.

### Delinquency — anchored target, stylized hazards and rolls

TransUnion Q3 2025 CIIR: mortgage 60+ DPD consumer-level delinquency
**1.36%**.

- <https://newsroom.transunion.com/q3-2025-ciir/>

Entry hazards are **stylized** lowest of all products; the roll matrix gives
mortgages the highest cure and "stay" probabilities of any product to
approximate the long loss-mitigation/foreclosure pipeline. Realized
point-in-time 60+ DPD in the default run is **0.1%** — far below the anchor,
and documented as such: the default book is at most 36 months on book, and
mortgage delinquency ramps with seasoning that a young book does not have.
The anchor shaped the hazards' order of magnitude; it is not reproduced
point-in-time by a young book. Realized lifetime default over a fully
observed 30-year test population: subprime 22.4%, near prime 11.2%, prime
4.2%, prime plus 1.3%, super prime 1.4%.

### Prepayment and recovery — anchored convention, stylized speeds

SMM 0.43%–0.78% monthly (≈5%–9% CPR), increasing with credit quality. The
level is **stylized** around the 100% PSA convention (~6% CPR after ramp; the
ramp itself is not modeled):
<https://en.wikipedia.org/wiki/PSA_prepayment_model>. Recovery on default:
70% of the defaulted balance 12 months after default (foreclosure on real
collateral, long resolution) — stylized.

## Credit cards

### Credit limits — anchored bracket, stylized per band

- TransUnion Q3 2025 CIIR: average **new-account** credit line $5,797:
  <https://newsroom.transunion.com/q3-2025-ciir/>
- CFPB per-card averages by tier: subprime ≈ $2,566, super-prime ≈ $10,396
  per card (cited via SmartAsset's summary of CFPB data):
  <https://smartasset.com/credit-cards/the-average-credit-card-limit>

`credit_limit_cents_by_band` ($2,500 / $5,000 / $8,000 / $11,000 / $15,000)
is **stylized** inside that bracket; the realized mix-weighted average limit
is $7,318, between the TransUnion new-account line and the CFPB per-card
averages.

### Interest rates — anchored level, stylized per band

Fed G.19 consumer credit: average rate on credit card accounts **assessed
interest** 22.30% (Nov 2025); ~21% across all accounts.

- <https://www.federalreserve.gov/releases/g19/current/>
- FRED series TERMCBCCINTNS:
  <https://fred.stlouisfed.org/series/TERMCBCCINTNS>

`annual_interest_rate_by_band` (18.5%–27.9% ±1.5% noise) is **stylized**
around that level; the realized mix-weighted average APR is 23.5%, slightly
above the G.19 figure because the configured mix is risk-heavier than the
national card book.

### Utilization — anchored gradient, stylized targets

Experian: average utilization ~29% overall (Q3 2024), **80.7%** in the
lowest score range (300–579) and **7.1%** in the 800–850 range.

- <https://www.experian.com/blogs/ask-experian/credit-education/score-basics/credit-utilization-rate/>

`target_utilization_by_band` (0.75 / 0.50 / 0.32 / 0.18 / 0.08) is
**stylized** on that gradient. Realized mean utilization of active cards at
the as-of month: subprime 0.74, near prime 0.45, prime 0.22, prime plus
0.09, super prime 0.02 — the best bands realize below target because
transactor months end at zero balance.

### Minimum payment rule — anchored formula, stylized floor

Large issuers most commonly set the minimum as **interest plus 1% of the
balance**, with a fixed dollar floor around $25–$35.

- Experian, "How Are Credit Card Minimum Payments Calculated?":
  <https://www.experian.com/blogs/ask-experian/how-is-your-credit-card-minimum-payment-calculated/>
- Chase explainer (same formula family):
  <https://www.chase.com/personal/credit-cards/education/basics/how-to-calculate-your-minimum-credit-card-payment>

`minimum_payment_principal_rate` = 1% plus the month's interest, floor $30 —
formula **anchored**, floor **stylized** mid-range.

### Transactor / revolver split — anchored definitions, stylized shares

The Fed's revolver/transactor classification (transactor = no revolving
balance over the trailing 12 months; transactors held ~7% of balances but
~40% of purchase volume):

- <https://www.federalreserve.gov/econres/notes/feds-notes/the-effects-of-the-covid-19-shutdown-on-the-consumer-credit-card-market-revolvers-versus-transactors-20201021.html>
- CFPB Data Point: Credit Card Revolvers:
  <https://www.consumerfinance.gov/data-research/research-reports/data-point-credit-card-revolvers/>

`pay_in_full_probability_by_band` (5%–75%, rising with score) is **stylized**
to be consistent with the utilization gradient above — no published per-band
transactor share was used.

### Delinquency and charge-off — anchored targets, stylized hazards

- TransUnion Q3 2025 CIIR: credit card 90+ DPD borrower-level delinquency
  **2.37%**: <https://newsroom.transunion.com/q3-2025-ciir/>
- Charge-off at 180 days follows the FFIEC open-end rule cited under shared
  parameters.

Entry hazards and rolls are **stylized**; the 90+ bucket carries a high
"stay" probability because an account spends up to three months at 90–180
days before charge-off. Realized point-in-time 90+ DPD share of active cards
in the default run: **1.34%** — below the anchor for the same young-book
seasoning reason as mortgages (the anchor reflects a seasoned national
portfolio). Realized charge-off rates after 84 months on book (test
population): subprime 38.5%, near prime 18.8%, prime 9.3%, prime plus 3.6%,
super prime 0.9%.

### Recoveries — stylized

8% of the charged-off balance, 6 months after charge-off — same thin
unsecured recovery assumption as personal loans, pending the empirical
calibration hook.
