output "cloud_run_url" {
  description = "Live API URL"
  value       = google_cloud_run_v2_service.ledger_api.uri
}

output "cloud_sql_connection" {
  description = "Cloud SQL connection name for Cloud Run"
  value       = google_sql_database_instance.ledger_db.connection_name
}

output "artifact_registry" {
  description = "Docker image registry path"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/ledger-api"
}

output "deploy_service_account" {
  description = "Repository-scoped Workload Identity deploy service account email"
  value       = google_service_account.deploy.email
}

output "backups_bucket" {
  description = "Cloud Storage bucket for database exports"
  value       = google_storage_bucket.backups.name
}
