/**
 * Cloud Run services.
 *
 * All model work is queued rather than awaited in a request handler, so the API's
 * request timeout can stay short. That is a deliberate consequence of ADR-013: Cloud
 * Run's request timeout is a constraint we route around rather than raise.
 */

locals {
  # Secrets the API and workers mount. DATABASE_URL is NOT a plaintext env value:
  # a Cloud Run revision's environment is readable by anyone with run.viewer, and a
  # database DSN there is a credential sitting in deployment metadata.
  app_secret_env = {
    DATABASE_URL              = "database-url"
    MODEL_API_KEY             = "model-api-key"
    ATELIER_API_CLIENT_SECRET = "keycloak-api-client-secret"
  }

  worker_secret_env = {
    DATABASE_URL  = "database-url"
    MODEL_API_KEY = "model-api-key"
  }

  common_env = {
    ENVIRONMENT      = var.environment
    GCS_BUCKET       = google_storage_bucket.private_media.name
    GCS_PUBLIC_BUCKET = google_storage_bucket.public_derivatives.name
    KEYCLOAK_ISSUER  = "${var.keycloak_public_url}/realms/${var.app_name}"
    KEYCLOAK_CLIENT_ID = "${var.app_name}-mobile"
    KEYCLOAK_AUDIENCE  = "${var.app_name}-api"
  }
}

# --- API ---------------------------------------------------------------------

resource "google_cloud_run_v2_service" "api" {
  name     = "${local.name}-api"
  location = var.region
  labels   = local.labels

  # Only the load balancer should reach it directly.
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.api.email

    scaling {
      # Production keeps a warm floor so the p95 latency target is not fighting
      # cold starts; non-production scales to zero to cost nothing idle.
      min_instance_count = var.environment == "prod" ? var.api_min_instances : 0
      max_instance_count = var.api_max_instances
    }

    vpc_access {
      connector = google_vpc_access_connector.main.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${local.name}/api:${var.api_image_tag}"

      resources {
        limits = {
          cpu    = var.api_cpu
          memory = var.api_memory
        }
        # Billed per request rather than always-on, except where a warm floor is
        # configured above.
        cpu_idle = var.environment != "prod"
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.app_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.app[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get { path = "/healthz" }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 10
      }

      liveness_probe {
        http_get { path = "/healthz" }
        period_seconds = 30
      }
    }

    # Model work is queued, so no request should ever need longer than this.
    timeout = "60s"

    # Keep per-instance concurrency aligned with the database pool: 80 concurrent
    # requests against a pool of 10 would queue inside the process instead of
    # shedding load where it is visible.
    max_instance_request_concurrency = var.api_concurrency
  }

  depends_on = [google_project_service.required]
}

# --- Workers -----------------------------------------------------------------
# Same image, different entrypoint. Workers share the API's SQLAlchemy models, so a
# separate package would only have to import this one back — see ADR-003.

resource "google_cloud_run_v2_service" "worker" {
  for_each = toset(["media", "ai", "moderation", "notifications", "reconcile"])

  name     = "${local.name}-worker-${each.key}"
  location = var.region
  labels   = merge(local.labels, { queue = each.key })

  # Reached only by Cloud Tasks, never from the internet.
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.worker.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.worker_max_instances[each.key]
    }

    vpc_access {
      connector = google_vpc_access_connector.main.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image   = "${var.region}-docker.pkg.dev/${var.project_id}/${local.name}/api:${var.api_image_tag}"
      command = ["python", "-m", "app.workers.runner"]
      args    = ["--queue", each.key]

      resources {
        limits = {
          # Media work is the only CPU-bound class; the rest are IO-bound and a
          # larger allocation would be idle.
          cpu    = each.key == "media" ? "2" : "1"
          memory = each.key == "media" ? "2Gi" : "512Mi"
        }
      }

      dynamic "env" {
        for_each = merge(local.common_env, { WORKER_QUEUE = each.key })
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.worker_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.app[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }

    # Media and AI jobs are long; the queue's own retry config bounds them.
    timeout = "900s"

    # One job at a time per instance. Concurrency here would make a single slow job
    # delay unrelated ones on the same instance, and progress reporting lies.
    max_instance_request_concurrency = 1
  }

  depends_on = [google_project_service.required]
}

# --- Keycloak ----------------------------------------------------------------

/**
 * Cloud Run is an imperfect host for Keycloak and this configuration is a
 * considered compromise, not a recommendation.
 *
 * Keycloak's own documentation discourages everything scale-to-zero implies:
 * a single instance is "susceptible to availability issues", startup "will not be
 * instantaneous", and embedded Infinispan "does not gracefully handle multiple
 * members joining or leaving concurrently" — with simultaneous departures able to
 * cause data loss. On Kubernetes it requires a StatefulSet's serial handling;
 * "using a deployment is not supported or recommended".
 *
 * So: min = max = 1. Pinning to exactly one instance avoids clustering altogether,
 * which removes the data-loss risk, at the cost of a brief gap during a deploy and
 * no redundancy. That is acceptable while sign-in volume is low and unacceptable at
 * the scale-target scenario.
 *
 * The production answer is a GKE StatefulSet with jdbc-ping discovery and a distinct
 * cache cluster name. Tracked in ROADMAP.md rather than pretended away here.
 */
resource "google_cloud_run_v2_service" "keycloak" {
  count = var.deploy_keycloak ? 1 : 0

  name     = "${local.name}-keycloak"
  location = var.region
  labels   = local.labels
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.keycloak.email

    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }

    vpc_access {
      connector = google_vpc_access_connector.main.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      # >= 26.8.1 is a floor: it fixed 22 CVEs, three in identity brokering.
      image = "quay.io/keycloak/keycloak:${var.keycloak_version}"

      # `start`, not `start-dev` — the latter forces local-only caches and is
      # documented as development-only. `--optimized` skips the build step, which
      # the image already performed.
      args = ["start", "--optimized"]

      resources {
        limits = { cpu = "2", memory = "2Gi" }
        # A JVM must not be throttled between requests.
        cpu_idle = false
      }

      # Keycloak's own database role, not the application's. Sharing one would mean
      # a Keycloak compromise reaching application tables, since in PostgreSQL every
      # role can CONNECT to every database by default.
      env {
        name = "KC_DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app["keycloak-db-password"].secret_id
            version = "latest"
          }
        }
      }

      dynamic "env" {
        for_each = {
          KC_DB          = "postgres"
          KC_DB_URL      = "jdbc:postgresql://${google_sql_database_instance.main.private_ip_address}:5432/${google_sql_database.keycloak.name}"
          KC_DB_USERNAME = google_sql_user.keycloak.name

          KC_HOSTNAME       = var.keycloak_public_url
          KC_HTTP_ENABLED   = "true"
          KC_HEALTH_ENABLED = "true"

          # Without this, origin checking returns 403 on every proxied request.
          # The old `proxy` option was removed in Keycloak 26.0.
          KC_PROXY_HEADERS = "xforwarded"

          # jdbc-ping discovers peers through the database, so two clusters sharing
          # this instance would silently merge without distinct names.
          KC_CACHE_EMBEDDED_CLUSTER_NAME = local.name
        }
        content {
          name  = env.key
          value = env.value
        }
      }

      # Health lives on the management port, not the HTTP port.
      startup_probe {
        http_get {
          path = "/health/started"
          port = 9000
        }
        initial_delay_seconds = 20
        period_seconds        = 10
        failure_threshold     = 30
      }

      liveness_probe {
        http_get {
          path = "/health/live"
          port = 9000
        }
        period_seconds = 30
      }
    }

    timeout = "300s"
  }

  depends_on = [google_project_service.required]
}

# --- Access ------------------------------------------------------------------

# Cloud Tasks authenticates as the worker service account; nothing else may invoke.
resource "google_cloud_run_v2_service_iam_member" "worker_invoker" {
  for_each = google_cloud_run_v2_service.worker

  name     = each.value.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.worker.email}"
}
