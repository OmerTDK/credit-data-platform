.DEFAULT_GOAL := help

.PHONY: help install lint lint-sql test generate dbt-parse dbt-run dbt-test dbt-build-staging ci docker-build docker-test

help: ## List available targets
	@grep -E '^[a-zA-Z][a-zA-Z0-9_-]*:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "%-16s %s\n", $$1, $$2}'

install: ## Install dependencies into .venv
	uv sync

lint: ## Ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

lint-sql: ## SQLFluff lint dbt SQL (duckdb dialect, dbt templater)
	mkdir -p data/local
	uv run sqlfluff lint models seeds snapshots tests/dbt

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

dbt-build-dwh: ## Build and test the DWH dimensional layer and its ancestors
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt build --select \
		+dim_date +dim_product +dim_loan +dim_borrower +dim_loan_current_state \
		+fct_loan_origination +fct_payment +fct_loan_state_event +fct_loan_lifecycle

validate-ecl-params: ## Validate ECL seed parameters before dbt build
	uv run python -m ecl_backtest.validate_parameters

dbt-build-risk: ## Build risk mart models and their ancestors
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt build --select \
		+mart_risk_roll_rate_matrix +mart_risk_vintage_curve +mart_risk_prepayment_speed

dbt-build-ecl: validate-ecl-params ## Build ECL marts and their ancestors (incl. mart_risk)
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt build --select \
		+mart_finance_ecl_allowance +mart_finance_ecl_summary

ci: lint lint-sql generate test dbt-parse dbt-build-staging dbt-build-dwh dbt-build-risk dbt-build-ecl ## Run the full CI suite locally

docker-build: ## Build the project image
	docker build -t credit-data-platform .

docker-test: ## Run the test suite inside the image
	docker run --rm credit-data-platform
