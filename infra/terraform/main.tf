/**
 * LUXish infrastructure on GCP (ADR-013).
 *
 * Deliberately a single flat configuration rather than a module hierarchy: there are
 * three near-identical environments and one team, so modules would add indirection
 * without removing duplication. Revisit if a fourth environment or a second team
 * appears.
 *
 * What this does NOT yet cover, so nobody assumes it does: Cloud CDN and custom
 * domains, Cloud Armor, per-service IAM beyond the service accounts below,
 * Memorystore (not yet justified — ADR-013), monitoring alert policies, and backup
 * schedules beyond Cloud SQL's built-in retention. Each is tracked in ROADMAP.md.
 */

terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Configured per environment via `-backend-config`. Never commit a bucket name
  # that identifies a real project.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  name = "${var.app_name}-${var.environment}"

  # Applied to everything billable so cost can be split by environment.
  labels = {
    app         = var.app_name
    environment = var.environment
    managed_by  = "terraform"
  }
}

# --- APIs --------------------------------------------------------------------

resource "google_project_service" "required" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudtasks.googleapis.com",
    "storage.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "vpcaccess.googleapis.com",
  ])

  service = each.value

  # Leave the APIs enabled on destroy; disabling them can break unrelated
  # resources in a shared project.
  disable_on_destroy = false
}

# --- Networking --------------------------------------------------------------
# Cloud SQL is reached over a private IP, so it needs no public surface at all.

resource "google_compute_network" "main" {
  name                    = local.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required]
}

resource "google_compute_subnetwork" "main" {
  name          = local.name
  network       = google_compute_network.main.id
  region        = var.region
  ip_cidr_range = var.subnet_cidr
}

resource "google_compute_global_address" "private_services" {
  name          = "${local.name}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main.id
}

resource "google_service_networking_connection" "private_vpc" {
  network                 = google_compute_network.main.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

# Cloud Run is serverless and has no VPC presence of its own; this connector is
# how it reaches the private Cloud SQL IP.
resource "google_vpc_access_connector" "main" {
  name          = substr("${local.name}-vpc", 0, 25) # name is capped at 25 chars
  region        = var.region
  subnet { name = google_compute_subnetwork.main.name }
  min_instances = 2
  max_instances = var.environment == "prod" ? 10 : 3
  depends_on    = [google_project_service.required]
}

# --- Database ----------------------------------------------------------------

resource "google_sql_database_instance" "main" {
  name             = local.name
  database_version = "POSTGRES_16"
  region           = var.region

  # Guard against a `terraform destroy` taking production data with it.
  deletion_protection = var.environment == "prod"

  settings {
    tier              = var.db_tier
    availability_type = var.environment == "prod" ? "REGIONAL" : "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = var.db_disk_gb
    disk_autoresize   = true
    user_labels       = local.labels

    ip_configuration {
      # No public IP. Everything reaches it through the VPC connector.
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = var.environment == "prod" ? 7 : 1
      backup_retention_settings {
        retained_backups = var.environment == "prod" ? 30 : 7
      }
    }

    maintenance_window {
      day          = 2 # Tuesday
      hour         = 4
      update_track = "stable"
    }

    database_flags {
      # Surface slow queries so the capacity assumptions can be replaced with
      # measurements rather than re-argued.
      name  = "log_min_duration_statement"
      value = "500"
    }
  }

  depends_on = [google_service_networking_connection.private_vpc]
}

resource "google_sql_database" "app" {
  name     = var.app_name
  instance = google_sql_database_instance.main.name
}

# Keycloak keeps its own database on the same instance. Separate databases, never a
# shared schema: a realm import must not be able to reach application tables.
resource "google_sql_database" "keycloak" {
  name     = "keycloak"
  instance = google_sql_database_instance.main.name
}

# One role per consumer. A separate database is not isolation on its own: in
# PostgreSQL every role can CONNECT to every database by default, so sharing a role
# between the app and Keycloak would mean a Keycloak compromise reaching application
# tables — exactly what the separate databases above exist to prevent.
#
# `special = false` because some drivers mishandle percent-escaping in a DSN.
resource "random_password" "db_app" {
  length  = 32
  special = false
}

resource "random_password" "db_keycloak" {
  length  = 32
  special = false
}

resource "google_sql_user" "app" {
  name     = var.app_name
  instance = google_sql_database_instance.main.name
  password = random_password.db_app.result
}

resource "google_sql_user" "keycloak" {
  name     = "keycloak"
  instance = google_sql_database_instance.main.name
  password = random_password.db_keycloak.result
}

# --- Object storage ----------------------------------------------------------
# Two buckets, because the access rules differ absolutely. Private originals are
# never public; derivatives are served through the CDN. A single bucket with mixed
# ACLs is how private wardrobe photos end up in a shared cache.

resource "google_storage_bucket" "private_media" {
  name                        = "${local.name}-media-private"
  location                    = var.storage_location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels

  versioning { enabled = true }

  cors {
    # Direct device-to-storage upload via a short-lived signed URL.
    origin          = var.allowed_upload_origins
    method          = ["PUT", "POST", "HEAD"]
    response_header = ["Content-Type", "Content-MD5", "x-goog-resumable"]
    max_age_seconds = 3600
  }

  lifecycle_rule {
    # Originals are read rarely after processing but must stay retrievable.
    condition { age = 90 }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    # Abandoned multipart uploads otherwise accumulate silently.
    condition { days_since_noncurrent_time = 30 }
    action { type = "Delete" }
  }
}

resource "google_storage_bucket" "public_derivatives" {
  name                        = "${local.name}-media-public"
  location                    = var.storage_location
  uniform_bucket_level_access = true
  labels                      = local.labels
}

# --- Queues ------------------------------------------------------------------
# One queue per class so a notification storm cannot starve media processing, and
# so each can be paused independently during an incident.

resource "google_cloud_tasks_queue" "work" {
  for_each = {
    media         = { max_concurrent = 50, max_rate = 100 }
    ai            = { max_concurrent = 20, max_rate = 20 }
    moderation    = { max_concurrent = 10, max_rate = 50 }
    notifications = { max_concurrent = 30, max_rate = 200 }
    reconcile     = { max_concurrent = 5, max_rate = 10 }
  }

  name     = "${local.name}-${each.key}"
  location = var.region

  rate_limits {
    max_concurrent_dispatches = each.value.max_concurrent
    max_dispatches_per_second = each.value.max_rate
  }

  retry_config {
    max_attempts       = 5
    min_backoff        = "10s"
    max_backoff        = "600s"
    max_doublings      = 4
    max_retry_duration = "3600s"
  }

  depends_on = [google_project_service.required]
}

# --- Secrets -----------------------------------------------------------------
# Terraform creates the containers; the values are written out of band so no
# credential ever reaches state or version control.

resource "google_secret_manager_secret" "app" {
  for_each = toset([
    "database-url",
    "keycloak-db-password",
    "model-api-key",
    "keycloak-api-client-secret",
    "google-oauth-client-id",
    "google-oauth-client-secret",
  ])

  secret_id = "${local.name}-${each.value}"
  labels    = local.labels
  replication { auto {} }
  depends_on = [google_project_service.required]
}

# --- Service accounts --------------------------------------------------------
# Least privilege, and distinct per deployable so a compromised worker cannot do
# what the API can.

resource "google_service_account" "api" {
  account_id   = substr("${local.name}-api", 0, 30)
  display_name = "LUXish API (${var.environment})"
}

resource "google_service_account" "worker" {
  account_id   = substr("${local.name}-worker", 0, 30)
  display_name = "LUXish workers (${var.environment})"
}

resource "google_service_account" "keycloak" {
  account_id   = substr("${local.name}-kc", 0, 30)
  display_name = "Keycloak (${var.environment})"
}

resource "google_project_iam_member" "sql_client" {
  for_each = {
    api      = google_service_account.api.email
    worker   = google_service_account.worker.email
    keycloak = google_service_account.keycloak.email
  }
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${each.value}"
}

# Only the API mints signed upload URLs, so only the API needs to create tokens —
# the workers read and write objects but never sign on a user's behalf.
#
# Scoped to the API's OWN service account, not the project. A project-level grant of
# serviceAccountTokenCreator would let the API impersonate every service account in
# the project, including the workers' and Keycloak's, which is a privilege-escalation
# path out of the API container. Signing a URL only requires self-impersonation.
resource "google_service_account_iam_member" "api_self_sign" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.api.email}"
}

resource "google_storage_bucket_iam_member" "private_media" {
  for_each = {
    api    = google_service_account.api.email
    worker = google_service_account.worker.email
  }
  bucket = google_storage_bucket.private_media.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${each.value}"
}

# --- Container registry ------------------------------------------------------

resource "google_artifact_registry_repository" "main" {
  location      = var.region
  repository_id = local.name
  format        = "DOCKER"
  labels        = local.labels

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions { keep_count = 20 }
  }

  depends_on = [google_project_service.required]
}

# Terraform generates the database credentials, so it writes them to Secret Manager
# itself; the externally issued ones (Meta key, Google OAuth secret, Keycloak client
# secret) stay empty containers populated out of band.
#
# Being precise about the consequence: a Terraform-generated password necessarily
# exists in Terraform state. The state bucket must therefore be private, versioned
# and encrypted, and treated as a secret store in its own right. What this does buy
# is that the credential is no longer in a Cloud Run revision's environment, where
# anyone with run.viewer could read it.
resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.app["database-url"].id
  secret_data = "postgresql+asyncpg://${google_sql_user.app.name}:${random_password.db_app.result}@${google_sql_database_instance.main.private_ip_address}:5432/${google_sql_database.app.name}"
}

resource "google_secret_manager_secret_version" "keycloak_db_password" {
  secret      = google_secret_manager_secret.app["keycloak-db-password"].id
  secret_data = random_password.db_keycloak.result
}

# Cloud Run cannot read a secret it has no grant for, and a missing grant surfaces
# as a start-up failure rather than anything diagnostic. Each service account gets
# accessor only on the secrets it actually mounts.
locals {
  secret_access = {
    "api:database-url"                = { secret = "database-url", sa = google_service_account.api.email }
    "api:model-api-key"               = { secret = "model-api-key", sa = google_service_account.api.email }
    "api:keycloak-api-client-secret"  = { secret = "keycloak-api-client-secret", sa = google_service_account.api.email }
    "worker:database-url"             = { secret = "database-url", sa = google_service_account.worker.email }
    "worker:model-api-key"            = { secret = "model-api-key", sa = google_service_account.worker.email }
    "keycloak:keycloak-db-password"   = { secret = "keycloak-db-password", sa = google_service_account.keycloak.email }
    "keycloak:google-oauth-client-id" = { secret = "google-oauth-client-id", sa = google_service_account.keycloak.email }
    "keycloak:google-oauth-secret"    = { secret = "google-oauth-client-secret", sa = google_service_account.keycloak.email }
  }
}

resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = local.secret_access

  secret_id = google_secret_manager_secret.app[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.sa}"
}
