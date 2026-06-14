.DEFAULT_GOAL := help

.PHONY: help install lint lint-sql test generate dbt-parse dbt-run dbt-test dbt-build-staging ci docker-build docker-test dagster-materialize dagster-dev elementary-report security dbt-build-semantic semantic-validate semantic-query evidence-install evidence-sources evidence-build

help: ## List available targets
	@grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "%-16s %s\n", $$1, $$2}'

install: ## Install dependencies into .venv
	uv sync

lint: ## Ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

lint-sql: ## SQLFluff lint dbt SQL (duckdb dialect, dbt templater) + Evidence source SQL (raw templater)
	mkdir -p data/local
	uv run sqlfluff lint models seeds snapshots tests/dbt
	uv run sqlfluff lint bi/sources/credit_platform --dialect duckdb --templater raw

test: ## Run the test suite
	uv run pytest -v

generate: ## Generate the synthetic loan book into data/landing
	uv run python -m loanbook generate --seed 42 --cohorts 24 --loans-per-cohort 500

dbt-parse: ## Validate that the dbt project parses
	DBT_PROFILES_DIR=. uv run dbt parse

dbt-run: ## Run dbt models against the local DuckDB dev target
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt run

dbt-test: ## Run dbt tests against the local DuckDB dev target
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt test

dbt-build-staging: ## Build and test the staging layer against the local DuckDB dev target
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt build --select staging

# Scoped builds exclude tag:elementary — Elementary's anomaly/schema tests need
# the full Elementary model layer, which is built only in the complete dbt build
# the Dagster materialization runs (make dagster-materialize).
dbt-build-dwh: ## Build and test the DWH dimensional layer and its ancestors
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt build --exclude tag:elementary --select \
		+dim_date +dim_product +dim_loan +dim_borrower +dim_loan_current_state \
		+fct_loan_origination +fct_payment +fct_loan_state_event +fct_loan_lifecycle

validate-ecl-params: ## Validate ECL seed parameters before dbt build
	uv run python -m ecl_backtest.validate_parameters

dbt-build-risk: ## Build risk mart models and their ancestors
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt build --exclude tag:elementary --select \
		+mart_risk_roll_rate_matrix +mart_risk_vintage_curve +mart_risk_prepayment_speed

dbt-build-ecl: validate-ecl-params ## Build ECL marts and their ancestors (incl. mart_risk)
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt build --exclude tag:elementary --select \
		+mart_finance_ecl_allowance +mart_finance_ecl_summary

# Semantic layer (MetricFlow). The time spine backs metric_time aggregation; the
# semantic models / metrics are YAML, so they need no table build of their own.
dbt-build-semantic: ## Build the MetricFlow time spine and the semantic-layer backing facts/marts
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt build --exclude tag:elementary --select \
		+metricflow_time_spine +fct_loan_origination +fct_loan_lifecycle +fct_payment \
		+mart_risk_vintage_curve +mart_risk_prepayment_speed

semantic-validate: ## Validate the MetricFlow semantic manifest against the DuckDB warehouse
	DBT_PROFILES_DIR=. uv run mf validate-configs

semantic-query: ## Smoke-query the headline governed metrics through MetricFlow
	DBT_PROFILES_DIR=. uv run mf query --metrics origination_volume,default_rate,avg_balance
	DBT_PROFILES_DIR=. uv run mf query --metrics default_rate --group-by loan__credit_tier

# Evidence dashboard (BI-as-code). npm-based, so it is NOT part of `make ci`
# (the Python CI is network-free). The query layer IS covered in CI via
# tests/test_evidence_dashboard.py. These targets prove the static site builds.
evidence-install: ## Install the Evidence (Node) dependencies
	cd bi && npm install --no-audit --no-fund

evidence-sources: ## Extract Evidence source queries from the DuckDB warehouse
	cd bi && npm run sources

evidence-build: ## Build the Evidence static site into bi/build (runs sources first)
	cd bi && npm run sources && npm run build

dagster-materialize: ## Materialize all dbt assets via Dagster (DbtCliResource) and run the asset-check gates
	mkdir -p data/local
	ELEMENTARY_CAPTURE=1 DBT_PROFILES_DIR=. uv run python -m orchestration.materialize

dagster-dev: ## Launch the Dagster UI to browse the asset graph and checks
	DBT_PROFILES_DIR=. uv run dagster dev -m orchestration.definitions

elementary-report: ## Generate the Elementary observability HTML report from the dbt run/test results
	mkdir -p data/local artifacts
	CREDIT_PLATFORM_DUCKDB="$(CURDIR)/data/local/credit_platform.duckdb" \
		DBT_PROFILES_DIR=. uv run edr report \
		--project-dir . --profiles-dir . --profile-target dev \
		--file-path artifacts/elementary_report.html --open-browser false

security: ## Run the security scanners (bandit SAST + pip-audit dependency CVEs)
	uv run bandit -r src -c pyproject.toml
	uv run pip-audit

ci: lint lint-sql generate test dbt-parse dbt-build-staging dbt-build-dwh dbt-build-risk dbt-build-ecl dbt-build-semantic semantic-validate dagster-materialize ## Run the full CI suite locally

docker-build: ## Build the project image
	docker build -t credit-data-platform .

docker-test: ## Run the test suite inside the image
	docker run --rm credit-data-platform
