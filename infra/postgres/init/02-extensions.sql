-- citext backs case-insensitive email uniqueness.
-- pgvector is deliberately NOT enabled: ADR-004 defers vector retrieval until a
-- measured trigger fires, and the Meta Model API has no embeddings endpoint.
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
