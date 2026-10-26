variable "project_id" {
  description = "GCP project id. Do not commit a real one — pass per environment."
  type        = string
}

variable "environment" {
  description = "dev | staging | prod. Drives HA, backups, warm instances and deletion protection."
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "app_name" {
  description = "Resource name prefix. Independent of the display brand (ADR-002)."
  type        = string
  default     = "atelier"
}

variable "region" {
  description = "Primary region. Keep the database, Cloud Run and the bucket colocated — cross-region egress is both slow and billed."
  type        = string
  default     = "europe-west1"
}

variable "storage_location" {
  description = "Media bucket location. May be multi-region for durability."
  type        = string
  default     = "EU"
}

variable "subnet_cidr" {
  type    = string
  default = "10.8.0.0/20"
}

# --- database ---------------------------------------------------------------

variable "db_tier" {
  description = "Cloud SQL machine type. db-f1-micro is viable for dev only."
  type        = string
  default     = "db-custom-2-7680"
}

variable "db_disk_gb" {
  type    = number
  default = 50
}

# --- api --------------------------------------------------------------------

variable "api_image_tag" {
  description = "Immutable image tag. Never 'latest' — a rollback must be addressable."
  type        = string
}

variable "api_cpu" {
  type    = string
  default = "1"
}

variable "api_memory" {
  type    = string
  default = "512Mi"
}

variable "api_min_instances" {
  description = "Warm floor in production, so the p95 target is not fighting cold starts."
  type        = number
  default     = 2
}

variable "api_max_instances" {
  description = "At 729 peak RPS (capacity scenario D) and 80 concurrent requests per instance, ~10 instances suffice. The headroom here is for a retry storm, not for steady load."
  type        = number
  default     = 30
}

variable "api_concurrency" {
  description = "Requests per instance. Keep aligned with the database pool size, or load queues inside the process instead of shedding where it is visible."
  type        = number
  default     = 40
}

variable "worker_max_instances" {
  description = "Per queue class. Media is CPU-bound and scales widest; reconcile is deliberately narrow because financial writes must be serialised, not parallelised."
  type        = map(number)
  default = {
    media         = 20
    ai            = 10
    moderation    = 5
    notifications = 10
    reconcile     = 2
  }
}

# --- keycloak ---------------------------------------------------------------

variable "deploy_keycloak" {
  description = "Deploy Keycloak on Cloud Run. See the comment on the resource: this is a compromise, and GKE is the production answer."
  type        = bool
  default     = true
}

variable "keycloak_version" {
  description = "Floor is 26.8.1 — it fixed 22 CVEs, three in identity brokering."
  type        = string
  default     = "26.8.1"
  validation {
    condition     = can(regex("^2[6-9]\.", var.keycloak_version))
    error_message = "Keycloak must be 26.x or newer; earlier versions carry known identity-brokering CVEs."
  }
}

variable "keycloak_public_url" {
  description = "External URL Keycloak is served on. Required: hostname-strict defaults true and must not be disabled."
  type        = string
}

# --- storage ----------------------------------------------------------------

variable "allowed_upload_origins" {
  description = "CORS origins permitted to PUT to a signed upload URL."
  type        = list(string)
  default     = ["*"]
}
