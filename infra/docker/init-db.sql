-- Database initialisation, run once on first container start.

-- Vector search lives in the primary database (ADR-0005).
CREATE EXTENSION IF NOT EXISTS vector;

-- ULIDs are generated in application code, but gen_random_uuid() is useful in
-- migrations and fixtures.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- The application connects as a NON-SUPERUSER.
--
-- This is not tidiness: PostgreSQL Row-Level Security does not apply to
-- superusers, so connecting as one would silently disable tenant isolation —
-- the single most damaging failure a multi-tenant platform can have.
-- See docs/architecture/adr/0008-multi-tenancy-rls.md.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
        CREATE ROLE neura_app LOGIN PASSWORD 'neura_app';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE neura TO neura_app;
GRANT USAGE, CREATE ON SCHEMA public TO neura_app;

-- Future tables and sequences are usable by the app role without another grant.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO neura_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO neura_app;
