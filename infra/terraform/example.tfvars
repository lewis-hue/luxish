# Copy per environment. Never commit a filled-in copy — *.tfvars is gitignored
# except this example.
project_id          = "your-gcp-project-id"
environment         = "dev"
region              = "europe-west1"
api_image_tag       = "sha-0000000"
keycloak_public_url = "https://auth.dev.example.com"
