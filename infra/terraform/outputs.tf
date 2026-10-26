output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "keycloak_url" {
  value       = var.deploy_keycloak ? google_cloud_run_v2_service.keycloak[0].uri : null
  description = "Compare with var.keycloak_public_url — KC_HOSTNAME must match the URL clients actually use, or redirect validation fails."
}

output "database_private_ip" {
  value     = google_sql_database_instance.main.private_ip_address
  sensitive = true
}

output "private_media_bucket" {
  value = google_storage_bucket.private_media.name
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${local.name}"
}

output "secret_ids" {
  description = "Terraform creates these containers empty. Write the values with `gcloud secrets versions add` so no credential enters Terraform state."
  value       = { for k, v in google_secret_manager_secret.app : k => v.secret_id }
}

output "task_queues" {
  value = { for k, v in google_cloud_tasks_queue.work : k => v.name }
}
