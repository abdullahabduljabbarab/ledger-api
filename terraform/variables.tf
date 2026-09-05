variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "ledger-api-507618"
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "europe-west2"
}

variable "db_tier" {
  description = "Cloud SQL machine tier"
  type        = string
  default     = "db-custom-1-3840"
}

variable "db_password" {
  description = "Database password. Stored in Secret Manager and injected into Cloud Run, never set as a plaintext env var."
  type        = string
  sensitive   = true
}

variable "jwt_secret_key" {
  description = "HS256 signing key for JWTs. Stored in Secret Manager and injected into Cloud Run."
  type        = string
  sensitive   = true
}
