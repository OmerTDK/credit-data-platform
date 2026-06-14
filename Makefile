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

dbt-build-dwh: ## Build and test the intermediate + DWH dimensional layer
	mkdir -p data/local
	DBT_PROFILES_DIR=. uv run dbt build --select staging intermediate dwh

ci: lint lint-sql generate test dbt-parse dbt-build-staging dbt-build-dwh ## Run the full CI suite locally

docker-build: ## Build the project image
	docker build -t credit-data-platform .

docker-test: ## Run the test suite inside the image
	docker run --rm credit-data-platform
