-- Extend v2 to profile1; v1 and existing v2/profile2 fingerprints stay unchanged.
-- Apply after 004 and before deploying the normal-Hybrid v2/profile1 producer.
BEGIN;
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
    NEW.load_cell_2_valid := COALESCE(NEW.load_cell_2_valid, false)
        AND NEW.source_metadata_version = 2 AND NEW.unit_id = 0;
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
    IF NEW.source_metadata_version NOT IN (1, 2) OR NEW.unit_id <> 0 THEN
        NEW.time_provenance := 'unsupported-source';
        RETURN NEW;
    END IF;

    IF NEW.source_metadata_version = 2 THEN
        IF NEW.availability_version IS DISTINCT FROM 1 OR NEW.operating_profile NOT IN (1, 2) OR NEW.operating_profile IS NULL
           OR NEW.load_cell_2_raw IS NULL OR NEW.load_cell_2_raw NOT BETWEEN -32768 AND 32767
           OR NEW.load_cell_2_voltage IS NULL
           OR NEW.load_cell_2_voltage IN ('NaN'::double precision,'Infinity'::double precision,'-Infinity'::double precision) THEN
            RAISE EXCEPTION 'Invalid v2 LC2 measurement or operating profile' USING ERRCODE = '22023';
        END IF;
    END IF;

    IF NEW.source_metadata_version = 2 AND NEW.operating_profile = 2 THEN
        -- In test mode these fields are local, unlike the v1 FSW-owned fields.
        IF (NEW.valid_readings_mask & 8) = 0 THEN NEW.pt3 := NULL; END IF;
        IF (NEW.valid_readings_mask & 16) = 0 THEN NEW.pt4 := NULL; END IF;
        IF (NEW.configured_devices_mask & 32) = 0 THEN NEW.sv_2_open := NULL; END IF;
        IF (NEW.configured_devices_mask & 512) = 0 THEN NEW.mav_open := NULL; END IF;
    END IF;

    IF NEW.source_metadata_version = 2 AND NEW.operating_profile = 1 THEN
        IF NEW.load_cell_2_raw <> 0 OR NEW.load_cell_2_voltage <> 0 OR NEW.load_cell_2_valid THEN
            RAISE EXCEPTION 'Normal Hybrid has no LC2 measurement' USING ERRCODE = '22023';
        END IF;
        IF NOT NEW.fsw_receive_age_valid THEN
            NEW.pt3 := NULL; NEW.pt4 := NULL; NEW.rtd := NULL;
            NEW.sv_2_open := NULL; NEW.mav_open := NULL; NEW.flight_mode := NULL;
        END IF;
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
        NEW.load_cell_2_valid := false;
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
    IF NEW.source_metadata_version = 2 THEN
        canonical_frame := canonical_frame || jsonb_build_object(
            'load_cell_2_raw', NEW.load_cell_2_raw,
            'load_cell_2_voltage', NEW.load_cell_2_voltage,
            'load_cell_2_valid', NEW.load_cell_2_valid,
            'operating_profile', NEW.operating_profile);
    END IF;
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


COMMIT;
