"""Dagster orchestration for the credit-data-platform dbt project.

Exposes the dbt project as software-defined assets and adds asset-check quality
gates (Stage 1/2 ECL positivity, referential integrity, volume sanity).
"""
