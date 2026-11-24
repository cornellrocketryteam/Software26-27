-- Fill Station rule (unit_id 0): payload is nanopb-encoded protobuf, not JSON.
-- Published on "rats/pb/0" rather than "rats/raw/0" so the JSON rule
-- (emqx_rule.sql, "rats/raw/+") never sees protobuf bytes.
SELECT
    -- Decode the protobuf payload into a map; fields are read from `payload` below
    schema_decode('telemetry', payload, 'TelemetryPayload') as payload,

    -- Top-Level Packet Info
    timestamp as broker_arrival_ms,
    payload.sync_word as sync_word,

    -- Shared Telemetry (Rust 'Packet' Struct)
    payload.flight_mode as flight_mode,
    payload.pressure as pressure,
    payload.temp as temp,
    payload.altitude as altitude,
    payload.latitude as latitude,
    payload.longitude as longitude,
    payload.num_satellites as num_satellites,
    payload.gps_time as gps_time, -- ms since midnight UTC (was `timestamp` in the old JSON)
    payload.mag_x as mag_x,
    payload.mag_y as mag_y,
    payload.mag_z as mag_z,
    payload.accel_x as accel_x,
    payload.accel_y as accel_y,
    payload.accel_z as accel_z,
    payload.gyro_x as gyro_x,
    payload.gyro_y as gyro_y,
    payload.gyro_z as gyro_z,
    payload.pt3 as pt3,
    payload.pt4 as pt4,
    payload.rtd as rtd,
    payload.sv_2_open as sv_2_open,
    payload.mav_open as mav_open,
    payload.ms_since_boot_cfc as ms_since_boot_cfc,

    -- Event Flags
    payload.ssa_drogue_deployed as ssa_drogue_deployed,
    payload.ssa_main_deployed as ssa_main_deployed,
    payload.cmd_n1 as cmd_n1,
    payload.cmd_n2 as cmd_n2,
    payload.cmd_n3 as cmd_n3,
    payload.cmd_n4 as cmd_n4,
    payload.cmd_a1 as cmd_a1,
    payload.cmd_a2 as cmd_a2,
    payload.cmd_a3 as cmd_a3,

    -- Airbrake & Control States
    payload.airbrake_deployment as airbrake_deployment,
    payload.predicted_apogee as predicted_apogee,

    -- Advanced GPS / U-Blox Metrics
    payload.h_acc as h_acc,
    payload.v_acc as v_acc,
    payload.vel_n as vel_n,
    payload.vel_e as vel_e,
    payload.vel_d as vel_d,
    payload.g_speed as g_speed,
    payload.s_acc as s_acc,
    payload.head_acc as head_acc,
    payload.fix_type as fix_type,
    payload.head_mot as head_mot,

    -- BLiMS Outputs
    payload.blims_brakeline_diff as blims_brakeline_diff,
    payload.blims_phase_id as blims_phase_id,
    payload.blims_pid_p as blims_pid_p,
    payload.blims_pid_i as blims_pid_i,
    payload.blims_bearing as blims_bearing,

    -- BLiMS Config
    payload.blims_upwind_lat as blims_upwind_lat,
    payload.blims_upwind_lon as blims_upwind_lon,
    payload.blims_downwind_lat as blims_downwind_lat,
    payload.blims_downwind_lon as blims_downwind_lon,
    payload.blims_wind_from_deg as blims_wind_from_deg,

    -- Fill Station Specific (Umbilical)
    payload.pt_1_pressure as pt_1_pressure,
    payload.pt_2_pressure as pt_2_pressure,
    payload.ball_valve_open as ball_valve_open,
    payload.sv_1_open as sv_1_open,
    payload.load_cell as load_cell,
    payload.ignition as ignition,
    payload.qd_state as qd_state,
    payload.ms_since_boot_fill as ms_since_boot_fill,

    -- Missing metadata marks legacy publishers; preserve their interpretation.
    CASE WHEN is_null(payload.availability_version) THEN 0 ELSE payload.availability_version END as availability_version,
    CASE WHEN is_null(payload.configured_devices_mask) THEN 0 ELSE payload.configured_devices_mask END as configured_devices_mask,
    CASE WHEN is_null(payload.valid_readings_mask) THEN 0 ELSE payload.valid_readings_mask END as valid_readings_mask,

    -- Source-frame contract v1; uint64 values cross the SQL driver as exact decimal text.
    -- Missing fields remain legacy. Never convert session/sequence through float.
    CASE WHEN is_null(payload.source_metadata_version) THEN 0 ELSE payload.source_metadata_version END as source_metadata_version,
    CASE WHEN is_null(payload.publisher_session_hi) THEN '0' ELSE str(payload.publisher_session_hi) END as publisher_session_hi,
    CASE WHEN is_null(payload.publisher_session_lo) THEN '0' ELSE str(payload.publisher_session_lo) END as publisher_session_lo,
    CASE WHEN is_null(payload.publisher_sequence) THEN '0' ELSE str(payload.publisher_sequence) END as publisher_sequence,
    CASE WHEN is_null(payload.source_monotonic_ms) THEN '0' ELSE str(payload.source_monotonic_ms) END as source_monotonic_ms,
    CASE WHEN is_null(payload.source_unix_ms) THEN '0' ELSE str(payload.source_unix_ms) END as source_unix_ms,
    CASE WHEN is_null(payload.source_unix_valid) THEN false ELSE payload.source_unix_valid END as source_unix_valid,
    CASE WHEN is_null(payload.source_time_quality) THEN 0 ELSE payload.source_time_quality END as source_time_quality,
    CASE WHEN is_null(payload.adc1_sample_age_ms) THEN '0' ELSE str(payload.adc1_sample_age_ms) END as adc1_sample_age_ms,
    CASE WHEN is_null(payload.adc1_sample_age_valid) THEN false ELSE payload.adc1_sample_age_valid END as adc1_sample_age_valid,
    CASE WHEN is_null(payload.adc2_sample_age_ms) THEN '0' ELSE str(payload.adc2_sample_age_ms) END as adc2_sample_age_ms,
    CASE WHEN is_null(payload.adc2_sample_age_valid) THEN false ELSE payload.adc2_sample_age_valid END as adc2_sample_age_valid,
    CASE WHEN is_null(payload.fsw_receive_age_ms) THEN '0' ELSE str(payload.fsw_receive_age_ms) END as fsw_receive_age_ms,
    CASE WHEN is_null(payload.fsw_receive_age_valid) THEN false ELSE payload.fsw_receive_age_valid END as fsw_receive_age_valid,
    CASE WHEN is_null(payload.source_time_generation) THEN 0 ELSE payload.source_time_generation END as source_time_generation,

    CASE WHEN is_null(payload.load_cell_2_raw) THEN 0 ELSE payload.load_cell_2_raw END as load_cell_2_raw,
    CASE WHEN is_null(payload.load_cell_2_voltage) THEN 0 ELSE payload.load_cell_2_voltage END as load_cell_2_voltage,
    CASE WHEN is_null(payload.load_cell_2_valid) THEN false ELSE payload.load_cell_2_valid END as load_cell_2_valid,
    CASE WHEN is_null(payload.operating_profile) THEN 0 ELSE payload.operating_profile END as operating_profile,

    CASE WHEN is_null(payload.ig1_output_active) THEN false ELSE payload.ig1_output_active END as ig1_output_active,
    CASE WHEN is_null(payload.ig1_continuity) THEN false ELSE payload.ig1_continuity END as ig1_continuity,
    CASE WHEN is_null(payload.ig1_output_valid) THEN false ELSE payload.ig1_output_valid END as ig1_output_valid,
    CASE WHEN is_null(payload.ig1_continuity_valid) THEN false ELSE payload.ig1_continuity_valid END as ig1_continuity_valid,
    CASE WHEN is_null(payload.ig2_output_active) THEN false ELSE payload.ig2_output_active END as ig2_output_active,
    CASE WHEN is_null(payload.ig2_continuity) THEN false ELSE payload.ig2_continuity END as ig2_continuity,
    CASE WHEN is_null(payload.ig2_output_valid) THEN false ELSE payload.ig2_output_valid END as ig2_output_valid,
    CASE WHEN is_null(payload.ig2_continuity_valid) THEN false ELSE payload.ig2_continuity_valid END as ig2_continuity_valid,
    CASE WHEN is_null(payload.qd_release_energized) THEN false ELSE payload.qd_release_energized END as qd_release_energized,
    CASE WHEN is_null(payload.qd_continuity) THEN false ELSE payload.qd_continuity END as qd_continuity,
    CASE WHEN is_null(payload.qd_output_valid) THEN false ELSE payload.qd_output_valid END as qd_output_valid,
    CASE WHEN is_null(payload.qd_continuity_valid) THEN false ELSE payload.qd_continuity_valid END as qd_continuity_valid,

    -- Unit ID routing (Dynamically grabbed from topic "rats/pb/0")
    int(nth(3, split(topic, '/'))) as unit_id

FROM
    "rats/pb/0"
