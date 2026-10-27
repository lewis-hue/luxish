-- Keycloak needs its own database. The API and Keycloak share a server locally but
-- never a schema: a realm import must not be able to touch application tables.
CREATE DATABASE keycloak OWNER luxish;
