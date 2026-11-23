-- Additive source-frame ingestion. Keep the hypertable partitioned by arrival time.
-- Apply after 001, before installing the new EMQX action. No historical backfill.
BEGIN;
ALTER TABLE public.telemetry_data
    ADD COLUMN IF NOT EXISTS broker_arrival_ms NUMERIC,
    ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_metadata_version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS publisher_session_hi NUMERIC,
    ADD COLUMN IF NOT EXISTS publisher_session_lo NUMERIC,
    ADD COLUMN IF NOT EXISTS publisher_sequence NUMERIC,
    ADD COLUMN IF NOT EXISTS source_monotonic_ms NUMERIC,
    ADD COLUMN IF NOT EXISTS source_unix_ms NUMERIC,
    ADD COLUMN IF NOT EXISTS source_unix_valid BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS source_time_quality BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_time_generation BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS adc1_sample_age_ms NUMERIC,
    ADD COLUMN IF NOT EXISTS adc1_sample_age_valid BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS adc2_sample_age_ms NUMERIC,
    ADD COLUMN IF NOT EXISTS adc2_sample_age_valid BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS fsw_receive_age_ms NUMERIC,
    ADD COLUMN IF NOT EXISTS fsw_receive_age_valid BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS source_identity_valid BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS source_event_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS time_provenance TEXT NOT NULL DEFAULT 'legacy-arrival';
-- Set the default separately: old rows retain NULL, not fabricated receipt time.
ALTER TABLE public.telemetry_data ALTER COLUMN received_at SET DEFAULT clock_timestamp();

CREATE SCHEMA IF NOT EXISTS ground_telemetry_private;
REVOKE ALL ON SCHEMA ground_telemetry_private FROM PUBLIC;
CREATE TABLE IF NOT EXISTS ground_telemetry_private.source_receipts (
    unit_id SMALLINT NOT NULL,
    session_hi NUMERIC NOT NULL,
    session_lo NUMERIC NOT NULL,
    sequence NUMERIC NOT NULL,
    first_arrival_time TIMESTAMPTZ NOT NULL,
    payload_sha256 BYTEA NOT NULL,
    PRIMARY KEY (unit_id, session_hi, session_lo, sequence)
);
REVOKE ALL ON ground_telemetry_private.source_receipts FROM PUBLIC;

CREATE OR REPLACE FUNCTION ground_telemetry_private.is_uint64(value NUMERIC)
RETURNS BOOLEAN LANGUAGE SQL IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT value IS NOT NULL AND value >= 0 AND value <= 18446744073709551615
           AND value = trunc(value);
$$;
REVOKE ALL ON FUNCTION ground_telemetry_private.is_uint64(NUMERIC) FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.ingest_telemetry_source_metadata()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    fingerprint BYTEA;
    existing_fingerprint BYTEA;
    canonical_frame JSONB;
BEGIN
    -- Server receipt time is neither caller-supplied nor a measurement timestamp.
    NEW.received_at := clock_timestamp();
    NEW.source_metadata_version := COALESCE(NEW.source_metadata_version, 0);
    NEW.source_unix_valid := COALESCE(NEW.source_unix_valid, false);
    NEW.source_time_quality := COALESCE(NEW.source_time_quality, 0);
    NEW.source_time_generation := COALESCE(NEW.source_time_generation, 0);
    NEW.adc1_sample_age_valid := COALESCE(NEW.adc1_sample_age_valid, false)
        AND ground_telemetry_private.is_uint64(NEW.adc1_sample_age_ms);
    NEW.adc2_sample_age_valid := COALESCE(NEW.adc2_sample_age_valid, false)
        AND ground_telemetry_private.is_uint64(NEW.adc2_sample_age_ms);
    NEW.fsw_receive_age_valid := COALESCE(NEW.fsw_receive_age_valid, false)
        AND ground_telemetry_private.is_uint64(NEW.fsw_receive_age_ms);
    NEW.source_event_time := NULL;
    NEW.source_identity_valid := false;
    NEW.time_provenance := 'legacy-arrival';
    IF NEW.source_metadata_version = 0 THEN RETURN NEW; END IF;
    IF NEW.source_metadata_version <> 1 OR NEW.unit_id <> 0 THEN
        NEW.time_provenance := 'unsupported-source';
        RETURN NEW;
    END IF;

    -- Canonical integer scale: 1 and 1.0 are the same exact uint64 value.
    IF ground_telemetry_private.is_uint64(NEW.publisher_session_hi) THEN NEW.publisher_session_hi := trunc(NEW.publisher_session_hi); END IF;
    IF ground_telemetry_private.is_uint64(NEW.publisher_session_lo) THEN NEW.publisher_session_lo := trunc(NEW.publisher_session_lo); END IF;
    IF ground_telemetry_private.is_uint64(NEW.publisher_sequence) THEN NEW.publisher_sequence := trunc(NEW.publisher_sequence); END IF;
    IF ground_telemetry_private.is_uint64(NEW.source_monotonic_ms) THEN NEW.source_monotonic_ms := trunc(NEW.source_monotonic_ms); END IF;
    IF ground_telemetry_private.is_uint64(NEW.source_unix_ms) THEN NEW.source_unix_ms := trunc(NEW.source_unix_ms); END IF;
    IF ground_telemetry_private.is_uint64(NEW.adc1_sample_age_ms) THEN NEW.adc1_sample_age_ms := trunc(NEW.adc1_sample_age_ms); END IF;
    IF ground_telemetry_private.is_uint64(NEW.adc2_sample_age_ms) THEN NEW.adc2_sample_age_ms := trunc(NEW.adc2_sample_age_ms); END IF;
    IF ground_telemetry_private.is_uint64(NEW.fsw_receive_age_ms) THEN NEW.fsw_receive_age_ms := trunc(NEW.fsw_receive_age_ms); END IF;

    NEW.source_identity_valid :=
        ground_telemetry_private.is_uint64(NEW.publisher_session_hi)
        AND ground_telemetry_private.is_uint64(NEW.publisher_session_lo)
        AND (NEW.publisher_session_hi <> 0 OR NEW.publisher_session_lo <> 0)
        AND ground_telemetry_private.is_uint64(NEW.publisher_sequence)
        AND NEW.publisher_sequence >= 1
        AND ground_telemetry_private.is_uint64(NEW.source_monotonic_ms)
        AND NEW.source_time_generation BETWEEN 1 AND 4294967295;
    IF NOT NEW.source_identity_valid THEN
        NEW.time_provenance := 'invalid-source-identity';
        RETURN NEW;
    END IF;

    IF NEW.source_time_quality = 0 AND NOT NEW.source_unix_valid THEN
        NEW.time_provenance := 'source-unsynchronized';
    ELSIF NEW.source_time_quality = 1 AND NEW.source_unix_valid
          AND ground_telemetry_private.is_uint64(NEW.source_unix_ms)
          AND NEW.source_unix_ms <= 253402300799999 THEN
        -- Explicit UI/export bound through year 9999; retain raw values outside it.
        NEW.source_event_time := to_timestamp(floor(NEW.source_unix_ms / 1000)::double precision)
            + mod(NEW.source_unix_ms, 1000)::double precision * interval '1 millisecond';
        NEW.time_provenance := 'source-kernel-reference-unknown';
    ELSE
        NEW.time_provenance := 'invalid-source-time';
    END IF;

    -- Frozen v1 protobuf-field inventory, after availability normalization.
    -- Never hash the entire row: later schema columns/arrival times must not
    -- change the identity of an already receipted v1 source frame.
    SELECT jsonb_object_agg(key, value) INTO canonical_frame
    FROM jsonb_each(to_jsonb(NEW))
    WHERE key = ANY (ARRAY[
        'sync_word', 'flight_mode', 'pressure', 'temp', 'altitude',
        'latitude', 'longitude', 'num_satellites', 'gps_time', 'mag_x',
        'mag_y', 'mag_z', 'accel_x', 'accel_y', 'accel_z',
        'gyro_x', 'gyro_y', 'gyro_z', 'pt3', 'pt4',
        'rtd', 'sv_2_open', 'mav_open', 'ms_since_boot_cfc', 'ssa_drogue_deployed',
        'ssa_main_deployed', 'cmd_n1', 'cmd_n2', 'cmd_n3', 'cmd_n4',
        'cmd_a1', 'cmd_a2', 'cmd_a3', 'airbrake_deployment', 'predicted_apogee',
        'h_acc', 'v_acc', 'vel_n', 'vel_e', 'vel_d',
        'g_speed', 's_acc', 'head_acc', 'fix_type', 'head_mot',
        'blims_brakeline_diff', 'blims_phase_id', 'blims_pid_p', 'blims_pid_i', 'blims_bearing',
        'blims_upwind_lat', 'blims_upwind_lon', 'blims_downwind_lat', 'blims_downwind_lon', 'blims_wind_from_deg',
        'pt_1_pressure', 'pt_2_pressure', 'ball_valve_open', 'sv_1_open', 'load_cell',
        'ignition', 'qd_state', 'ms_since_boot_fill', 'availability_version', 'configured_devices_mask',
        'valid_readings_mask', 'source_metadata_version', 'publisher_session_hi', 'publisher_session_lo', 'publisher_sequence',
        'source_monotonic_ms', 'source_unix_ms', 'source_unix_valid', 'source_time_quality', 'adc1_sample_age_ms',
        'adc1_sample_age_valid', 'adc2_sample_age_ms', 'adc2_sample_age_valid', 'fsw_receive_age_ms', 'fsw_receive_age_valid',
        'source_time_generation'
    ]);
    fingerprint := sha256(convert_to(canonical_frame::text, 'UTF8'));
    INSERT INTO ground_telemetry_private.source_receipts
        (unit_id, session_hi, session_lo, sequence, first_arrival_time, payload_sha256)
    VALUES (NEW.unit_id, NEW.publisher_session_hi, NEW.publisher_session_lo,
            NEW.publisher_sequence, NEW.time, fingerprint)
    ON CONFLICT (unit_id, session_hi, session_lo, sequence) DO NOTHING;
    IF NOT FOUND THEN
        SELECT payload_sha256 INTO existing_fingerprint
        FROM ground_telemetry_private.source_receipts
        WHERE unit_id = NEW.unit_id AND session_hi = NEW.publisher_session_hi
          AND session_lo = NEW.publisher_session_lo AND sequence = NEW.publisher_sequence;
        IF existing_fingerprint IS DISTINCT FROM fingerprint THEN
            RAISE EXCEPTION 'conflicting payload for existing source-frame identity'
                USING ERRCODE = '23505';
        END IF;
        RETURN NULL; -- Exact duplicate; do not update history or a live value.
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.ingest_telemetry_source_metadata() FROM PUBLIC;

-- PostgreSQL orders same-event triggers by name. Run after 001's
-- fill_hardware_availability, so the fingerprint uses the normalized observation.
DROP TRIGGER IF EXISTS source_frame_ingestion ON public.telemetry_data;
CREATE TRIGGER source_frame_ingestion BEFORE INSERT ON public.telemetry_data
FOR EACH ROW EXECUTE FUNCTION public.ingest_telemetry_source_metadata();

CREATE INDEX IF NOT EXISTS idx_telemetry_source_sequence ON public.telemetry_data
    (unit_id, publisher_session_hi, publisher_session_lo, publisher_sequence DESC)
    WHERE source_identity_valid;
CREATE INDEX IF NOT EXISTS idx_telemetry_source_event_time ON public.telemetry_data
    (unit_id, source_event_time DESC) WHERE source_event_time IS NOT NULL;

-- One head per session, never an unproven global ordering of random session IDs.
CREATE OR REPLACE VIEW public.telemetry_latest_in_session AS
SELECT DISTINCT ON (unit_id, publisher_session_hi, publisher_session_lo) d.*
FROM public.telemetry_data AS d WHERE source_identity_valid
ORDER BY unit_id, publisher_session_hi, publisher_session_lo, publisher_sequence DESC;

-- Fallback is explicit through provenance; unknown-time rows remain inspectable.
CREATE OR REPLACE VIEW public.telemetry_event_history AS
SELECT COALESCE(d.source_event_time, d.time) AS display_time, d.*
FROM public.telemetry_data AS d;
COMMIT;
