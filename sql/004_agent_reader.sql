-- Read-only role for the agent's SQL tool (Phase 5.4), layer 2 of the defence in depth.
-- Local development password; a real deployment would provision the role and secret outside the repo.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_reader') THEN
        CREATE ROLE agent_reader LOGIN PASSWORD 'agent_reader'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT CONNECTION LIMIT 10;
    END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM agent_reader;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO agent_reader;
GRANT SELECT ON figures, documents TO agent_reader;

ALTER ROLE agent_reader SET default_transaction_read_only = on;
ALTER ROLE agent_reader SET statement_timeout = '2s';
ALTER ROLE agent_reader SET idle_in_transaction_session_timeout = '5s';
