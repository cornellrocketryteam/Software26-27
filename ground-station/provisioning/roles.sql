-- Executed only inside the local database container. The password is read from
-- its private environment, never passed in command arguments or immutable data.
\getenv ground_ingest_password CRT_INGEST_PASSWORD
\getenv ground_reader_password CRT_READER_PASSWORD
BEGIN;
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ground_ingest') THEN
        CREATE ROLE ground_ingest LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ground_reader') THEN
        CREATE ROLE ground_reader LOGIN;
    END IF;
END $$;
SELECT format('ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD %L', role_name, role_password)
FROM (VALUES ('ground_ingest', :'ground_ingest_password'), ('ground_reader', :'ground_reader_password')) AS credentials(role_name, role_password)
\gexec
\unset ground_ingest_password
\unset ground_reader_password
GRANT CONNECT ON DATABASE telemetry TO ground_ingest, ground_reader;
GRANT USAGE ON SCHEMA public TO ground_ingest, ground_reader;
REVOKE ALL ON telemetry_data FROM ground_ingest, ground_reader;
GRANT INSERT ON telemetry_data TO ground_ingest;
GRANT SELECT ON telemetry_data TO ground_reader;
ALTER ROLE ground_reader SET default_transaction_read_only = on;
COMMIT;
