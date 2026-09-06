terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "current" {}

resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "pubsub.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

resource "google_sql_database_instance" "ledger_db" {
  name             = "ledger-db"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier    = var.db_tier
    edition = "ENTERPRISE"

    ip_configuration {
      ipv4_enabled = true
    }

    backup_configuration {
      enabled = true
    }
  }

  deletion_protection = true

  depends_on = [google_project_service.services]
}

resource "google_sql_database" "ledger" {
  name     = "ledger"
  instance = google_sql_database_instance.ledger_db.name
}

resource "google_sql_user" "postgres" {
  name     = "postgres"
  instance = google_sql_database_instance.ledger_db.name
  password = var.db_password
}

resource "google_artifact_registry_repository" "ledger" {
  location      = var.region
  repository_id = "ledger-api"
  format        = "DOCKER"

  depends_on = [google_project_service.services]
}

# The full connection string is held as one secret rather than just the
# password, so Cloud Run never sees a plaintext DATABASE_URL.
resource "google_secret_manager_secret" "database_url" {
  secret_id = "database-url"

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = "postgresql://${google_sql_user.postgres.name}:${var.db_password}@/${google_sql_database.ledger.name}?host=/cloudsql/${google_sql_database_instance.ledger_db.connection_name}"
}

resource "google_secret_manager_secret" "jwt_secret_key" {
  secret_id = "jwt-secret-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_version" "jwt_secret_key" {
  secret      = google_secret_manager_secret.jwt_secret_key.id
  secret_data = var.jwt_secret_key
}

# Dedicated least-privilege runtime identity: the service runs as this account,
# not the default compute service account. It holds only Cloud SQL Client, read
# access to its own two secrets (its database-url and the JWT signing key), and
# publish on its own transaction-events topic.
resource "google_service_account" "cloud_run" {
  account_id   = "ledger-api-runtime"
  display_name = "Ledger API Runtime"
}

resource "google_project_iam_member" "cloud_run_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_secret_manager_secret_iam_member" "cloud_run_database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_secret_manager_secret_iam_member" "cloud_run_jwt" {
  secret_id = google_secret_manager_secret.jwt_secret_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_cloud_run_v2_service" "ledger_api" {
  name     = "ledger-api"
  location = var.region

  template {
    service_account = google_service_account.cloud_run.email

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/ledger-api/ledger-api:latest"

      ports {
        container_port = 8080
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "JWT_SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_secret_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "ENVIRONMENT"
        value = "production"
      }

      env {
        name  = "PUBSUB_TOPIC"
        value = data.google_pubsub_topic.transactions.id
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.ledger_db.connection_name]
      }
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.ledger_api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# transaction-events is a shared topic owned by platform-infrastructure; the
# ledger publishes transaction.recorded onto it. Referenced here, not created here.
data "google_pubsub_topic" "transactions" {
  name = "transaction-events"
}

resource "google_pubsub_subscription" "transactions_sub" {
  name  = "transaction-events-sub"
  topic = data.google_pubsub_topic.transactions.id

  ack_deadline_seconds = 20

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

resource "google_pubsub_topic_iam_member" "cloud_run_publish" {
  topic  = data.google_pubsub_topic.transactions.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Keyless CI deploy: GitHub Actions authenticates via Workload Identity
# Federation and impersonates a dedicated least-privilege deploy service account,
# so no service-account key is stored in the repository. The pool and provider are
# shared and owned by platform-infrastructure; this repo references the pool (its
# name composed from the project number) and contributes only its own deploy
# account and binding.
locals {
  wif_pool_name = "projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/github-actions"
}

resource "google_service_account" "deploy" {
  account_id   = "ledger-deploy"
  display_name = "Ledger API Deploy"
}

resource "google_project_iam_member" "deploy_roles" {
  for_each = toset([
    "roles/run.admin",
    "roles/artifactregistry.writer",
    "roles/iam.serviceAccountUser",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

# Only the ledger-api repository may impersonate the deploy service account.
resource "google_service_account_iam_member" "deploy_wif" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${local.wif_pool_name}/attribute.repository/${var.github_owner}/${var.github_repo}"
}

# Destination for Cloud SQL database exports used in the backup and restore drill.
resource "google_storage_bucket" "backups" {
  name                        = "${var.project_id}-backups"
  location                    = var.region
  uniform_bucket_level_access = true

  depends_on = [google_project_service.services]
}

resource "google_storage_bucket_iam_member" "cloud_sql_backup_writer" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_sql_database_instance.ledger_db.service_account_email_address}"
}
