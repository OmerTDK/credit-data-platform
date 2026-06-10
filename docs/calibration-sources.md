# Calibration sources — personal loans

Where every number in `src/loanbook/calibration.py` comes from. Two classes of
parameter:

- **Anchored** — taken directly from a published statistic, cited below.
- **Stylized** — interpolated to be consistent with the published aggregates
  (e.g. per-band values whose mix-weighted average must land near a published
  overall figure). Stylized values are labeled as such; none of them claim to
  be fitted.

An empirical fit against loan-level public performance data (Fannie Mae
single-family style, or the Kaggle LendingClub loan file) is a **documented
open interface** — `load_calibration_from_loan_performance_data` — and is an
open question pending with Omer. No fitted calibration has been run.

## Score bands — anchored

VantageScore 4.0 risk tiers as used in TransUnion's industry reporting:
subprime 300–600, near prime 601–660, prime 661–720, prime plus 721–780,
super prime 781–850.

- VantageScore, "The Complete Guide to Your VantageScore":
  <https://vantagescore.com/consumers/blog/the-complete-guide-to-your-vantagescore>
- CNBC Select summary of the TransUnion/VantageScore tier definitions:
  <https://www.cnbc.com/select/borrower-risk-profiles-based-on-credit-score/>

## Delinquency buckets and the default threshold — anchored

Bucket semantics (30/60/90+ days past due as 1/2/3 payments behind) follow the
New York Fed Consumer Credit Panel delinquency-status definitions. Default at
**4 missed monthly payments (~120 days past due)** follows the FFIEC Uniform
Retail Credit Classification policy: closed-end retail loans are classified
Loss and charged off at 120 cumulative days past due.

- NY Fed Quarterly Report on Household Debt and Credit (status definitions):
  <https://www.newyorkfed.org/medialibrary/interactives/householdcredit/data/pdf/HHDC_2025Q1>
- FFIEC Uniform Retail Credit Classification and Account Management Policy
  (Federal Register, June 12, 2000):
  <https://www.federalregister.gov/documents/2000/06/12/00-14704/uniform-retail-credit-classification-and-account-management-policy>
- OCC Bulletin 2000-20 (implementation):
  <https://www.occ.treas.gov/news-issuances/bulletins/2000/bulletin-2000-20.html>

## Delinquency levels — anchored targets, stylized roll rates

TransUnion Q3 2025 Credit Industry Insights Report, unsecured personal loans:
60+ DPD borrower delinquency **3.52%** overall, **11.4%** for subprime.

- <https://newsroom.transunion.com/q3-2025-ciir/>

The per-band monthly entry hazards (`monthly_delinquency_entry_hazard_by_band`)
and the cure/stay/roll-deeper probabilities per bucket
(`delinquent_roll_probabilities`) are **stylized**: chosen monotone in risk
band, with early-stage delinquency mostly curing and late-stage mostly rolling
forward (the qualitative pattern in the NY Fed transition data), and scaled so
the generated book's point-in-time 60+ DPD share and subprime gradient sit
near the TransUnion figures.

Realized values for the default run (`--seed 42 --cohorts 24
--loans-per-cohort 500`, cohorts 2022-01..2023-12, as-of 2024-12): 60+ DPD
share of active loans at the as-of month **2.83%** (anchor 3.52%); loans ever
charged off by band, censored at 12–36 months on book: subprime 31.8%,
near prime 16.0%, prime 5.9%, prime plus 2.0%, super prime 1.1% —
monotone, with the censored overall rate consistent with the ~19% uncensored
LendingClub lifetime figure.

## Lifetime defaults — anchored target, stylized per band

Marketplace personal loans (LendingClub public loan file, 2007–2020Q3,
completed loans): **19.36% charged off** vs 80.64% fully paid. Charge-off
rates rise monotonically as grade worsens.

- Sandoval Serrano et al., "Loan Default Prediction: A Complete Revision of
  LendingClub", Revista mexicana de economía y finanzas (2023):
  <https://www.scielo.org.mx/scielo.php?script=sci_arttext&pid=S1665-53462023000300001>
- Grade→default monotonicity in the same public dataset:
  <https://emmanuel-r8.github.io/project/lendingclub/lendingclub/dataset.html>

Per-band lifetime default emerges from the entry hazards and roll rates above
(no separate parameter); the parameter scaling targets an uncensored lifetime
charge-off rate in the mid-to-high teens for the configured origination mix.

## Interest rates — anchored bounds, stylized per band

- Average 24-month personal loan rate at commercial banks: ~11.4% (2025
  readings). FRED series TERMCBPER24NS (Fed G.19 source data):
  <https://fred.stlouisfed.org/series/TERMCBPER24NS>
- Marketplace pricing exceeds 30% APR at the riskiest grades (LendingClub
  July 2019 rate grid): <https://emmanuel-r8.github.io/project/lendingclub/lendingclub/dataset.html>

`annual_interest_rate_by_band` (7.5%–24.9% plus ±1.5% within-band noise) is
**stylized** between those bounds; the mix-weighted average (~15.6%) sits
above the bank-loan G.19 average deliberately, because the configured
origination mix is marketplace-style (more near-prime/subprime than bank
books).

## Loan amounts and terms — anchored

- Average unsecured personal loan debt per borrower: **$11,724** (TransUnion
  Q3 2025 CIIR): <https://newsroom.transunion.com/q3-2025-ciir/>
- LendingClub loans ranged $1,000–$40,000 with 36- or 60-month terms (public
  loan file): <https://www.kaggle.com/datasets/wordsforthewise/lending-club>

Amounts are lognormal with median $10,000 and sigma 0.55 (mean ≈ $11,600,
matching the TransUnion per-borrower figure), clipped to $1,000–$40,000,
rounded to $25. The 70/30 term mix between 36 and 60 months is **stylized**
around the LendingClub two-term structure.

## Prepayment — anchored direction, stylized speeds

Prepayment is more frequent than default in online consumer lending (Li, Li,
Yao, Wen 2019, *Emerging Markets Finance and Trade* 55(1), 118–132):

- <https://www.tandfonline.com/doi/full/10.1080/1540496X.2018.1479251>

`monthly_prepayment_rate_by_band` is **stylized**: single monthly mortality
(SMM) values equivalent to 15%–30% annual CPR, increasing with credit quality
(better-score borrowers refinance more easily). SMM = 1 − (1 − CPR)^(1/12),
the standard dv01 definition:
<https://dv01.freshdesk.com/support/solutions/articles/42000052036-cpr-calculation>

## Recoveries — stylized

8% of the balance at charge-off, received as a lump sum 6 months after
default. Unsecured consumer LGD is high (recoveries thin); the parameter is
stylized pending the empirical calibration hook.

## Borrower attributes — anchored region mix, stylized age/income

- `region_mix` uses the four US census regions at approximate 2020 Census
  population shares (NE 17%, MW 21%, S 38%, W 24%):
  <https://www.census.gov/library/stories/state-by-state.html> (regional
  pages; e.g. the Midwest states sum to ≈68.99M of ≈331.4M, 21%).
- `age_band_mix` and `income_band_mix` are **stylized**, skewed toward the
  25–44 and middle-income cohorts that dominate marketplace borrowing.
