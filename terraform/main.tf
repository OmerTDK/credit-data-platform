# ------------------------------------------------------------------------------
# Credit Data Platform — BigQuery Infrastructure
#
# Provisions the BigQuery datasets and IAM bindings for the production target.
# Uses the BigQuery Sandbox (free tier, personal Google account).
#
# Usage:
#   cd terraform
#   terraform init
#   terraform plan -var="project_id=your-gcp-project-id"
#   terraform apply -var="project_id=your-gcp-project-id"
#
# The GCP project must already exist. See docs/adr/0013-bigquery-terraform.md.
# ------------------------------------------------------------------------------

terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.37"
    }
  }
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "project_id" {
  description = "GCP project ID (BigQuery Sandbox project)"
  type        = string
}

variable "region" {
  description = "BigQuery dataset location"
  type        = string
  default     = "EU"
}

variable "dbt_service_account_email" {
  description = "Service account email for dbt CI runs (created separately or via console)"
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# BigQuery datasets — one per dbt schema
# ---------------------------------------------------------------------------

locals {
  datasets = {
    stg          = "Staging layer: cleaned and typed source views"
    int          = "Intermediate layer: business logic transformations"
    dwh          = "Data warehouse: conformed dimensions and facts"
    mart_risk    = "Risk mart: roll rates, vintage curves, prepayment"
    mart_finance = "Finance mart: IFRS 9 ECL allowance and summary"
    elementary   = "Elementary observability: test results and anomalies"
  }
}

resource "google_bigquery_dataset" "datasets" {
  for_each = local.datasets

  dataset_id                      = each.key
  friendly_name                   = each.key
  description                     = each.value
  location                        = var.region
  delete_contents_on_destroy      = false
  default_table_expiration_ms     = 5184000000
  default_partition_expiration_ms = 5184000000

  labels = {
    managed_by = "terraform"
    project    = "credit-data-platform"
  }
}

# ---------------------------------------------------------------------------
# IAM: grant the dbt service account BigQuery Data Editor + Job User
# ---------------------------------------------------------------------------

resource "google_bigquery_dataset_iam_member" "dbt_bq_data_editor" {
  for_each   = var.dbt_service_account_email != "" ? local.datasets : {}
  project    = var.project_id
  dataset_id = google_bigquery_dataset.datasets[each.key].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${var.dbt_service_account_email}"
}

resource "google_project_iam_member" "dbt_bq_job_user" {
  count   = var.dbt_service_account_email != "" ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${var.dbt_service_account_email}"
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "dataset_ids" {
  description = "Created BigQuery dataset IDs"
  value       = { for k, v in google_bigquery_dataset.datasets : k => v.dataset_id }
}

output "dataset_locations" {
  description = "BigQuery dataset locations"
  value       = { for k, v in google_bigquery_dataset.datasets : k => v.location }
}
