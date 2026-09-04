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

resource "google_secret_manager_secret" "db_password" {
  secret_id = "db-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = var.db_password
}

resource "google_service_account" "cloud_run" {
  account_id   = "ledger-api-runner"
  display_name = "Ledger API Cloud Run"
}

resource "google_secret_manager_secret_iam_member" "cloud_run_access" {
  secret_id = google_secret_manager_secret.db_password.id
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
        name  = "DATABASE_URL"
        value = "postgresql://postgres:${var.db_password}@/${google_sql_database.ledger.name}?host=/cloudsql/${google_sql_database_instance.ledger_db.connection_name}"
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

resource "google_pubsub_topic" "transactions" {
  name = "transaction-events"

  depends_on = [google_project_service.services]
}

resource "google_pubsub_subscription" "transactions_sub" {
  name  = "transaction-events-sub"
  topic = google_pubsub_topic.transactions.id

  ack_deadline_seconds = 20

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

resource "google_pubsub_topic_iam_member" "cloud_run_publish" {
  topic  = google_pubsub_topic.transactions.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_service_account" "github_deploy" {
  account_id   = "github-deploy"
  display_name = "GitHub Actions Deploy"
}

resource "google_project_iam_member" "github_deploy_roles" {
  for_each = toset([
    "roles/run.admin",
    "roles/artifactregistry.writer",
    "roles/cloudbuild.builds.builder",
    "roles/iam.serviceAccountUser",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.github_deploy.email}"
}
