use rumqttc::{Client, MqttOptions, QoS};
use smol::Timer;
use smol::lock::Mutex;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tracing::{debug, error, info, warn};

use crate::command::{ActuatorState, AdcReadings, UmbilicalReadings};
use crate::hardware::Hardware;
use crate::operating_runtime::{RoutingMode, Sample, OutputDiagnostic, route_sensors};
// From the lib crate so the nanopb static library (linked into the lib) comes along
use fill_station::telemetry_pb::{self, TelemetryPayload};
use fill_station::telemetry_clock::{PublisherClock, kernel_time_quality, sample_age};

// ============================================================================
// MQTT CONFIGURATION
// ============================================================================

/// IP address of the EMQX MQTT broker
const BROKER_HOST: &str = "192.168.1.206";

/// MQTT broker port
const BROKER_PORT: u16 = 1883;

use crate::telemetry_rate::{self, Outcome, Stats};

/// MQTT topic — unit_id 0 = Fill Station. Protobuf payloads use "rats/pb/",
/// separate from the JSON "rats/raw/" topics (see ground-station/emqx_rule_fill_station.sql)
const MQTT_TOPIC: &str = "rats/pb/0";

/// JSON copy of each payload for reading in an MQTT client (debug-json feature)
#[cfg(feature = "debug-json")]
const MQTT_DEBUG_TOPIC: &str = "rats/debug/0";

/// MQTT client identifier
const CLIENT_ID: &str = "fill-station";

// ============================================================================
// MQTT PUBLISHER TASK
// ============================================================================

pub async fn start_mqtt_publisher(
    _hardware: Arc<Mutex<Hardware>>,
    adc_readings: Arc<Mutex<AdcReadings>>,
    umbilical_readings: Arc<Mutex<UmbilicalReadings>>,
    actuator_state: Arc<ActuatorState>,
) {
    let configured_rate = std::env::var("FILL_STATION_MQTT_HZ");
    let publish_rate = match configured_rate {
        Ok(ref value) => telemetry_rate::parse_rate(Some(value)),
        Err(std::env::VarError::NotPresent) => telemetry_rate::parse_rate(None),
        Err(_) => Err("non-Unicode MQTT rate"),
    }.unwrap_or_else(|reason| {
        warn!("Invalid MQTT rate configuration ({}); using 10 Hz", reason);
        10
    });
    info!(
        "Starting MQTT publisher task ({}:{}, topic: {}, rate: {} Hz)",
        BROKER_HOST, BROKER_PORT, MQTT_TOPIC, publish_rate
    );

    let routing_mode = _hardware.lock().await.routing_mode;
    let mut source_clock = match PublisherClock::new() {
        Ok(clock) => clock,
        Err(error) => {
            error!("MQTT disabled: cannot create unique publisher session: {}", error);
            return;
        }
    };
    let mut mqttoptions = MqttOptions::new(CLIENT_ID, BROKER_HOST, BROKER_PORT);
    mqttoptions.set_keep_alive(Duration::from_secs(30));

    let (client, mut connection) = Client::new(mqttoptions, 10);

    // Spawn a dedicated OS thread for the MQTT event loop.
    // This handles CONNECT, CONNACK, PINGREQ/PINGRESP, and auto-reconnection.
    std::thread::spawn(move || {
        for notification in connection.iter() {
            match notification {
                Ok(event) => {
                    debug!("MQTT event: {:?}", event);
                }
                Err(e) => {
                    error!("MQTT connection error: {} — will auto-reconnect", e);
                    // Sleep briefly to avoid busy-looping on persistent errors
                    std::thread::sleep(Duration::from_secs(2));
                }
            }
        }
        warn!("MQTT event loop exited");
    });

    info!("MQTT event loop started on background thread");

    let boot_time = Instant::now();
    let mut last_time_generation = 0;
    let interval = telemetry_rate::interval(publish_rate);
    let mut stats = Stats::default();
    let mut stats_start = Instant::now();

    loop {
        let start = Instant::now();
        let ms_since_boot_fill = boot_time.elapsed().as_millis() as u64;

        // 1. Gather ADC data
        let (routed, valid_readings_mask, adc1_captured, adc2_captured) = {
            let adc = adc_readings.lock().await;
            let sample = |s: crate::command::ChannelReading| Sample {
                raw:s.raw, voltage:s.voltage, scaled:s.scaled,
            };
            let routed = route_sensors(routing_mode, adc.adc1.map(sample), adc.adc1_valid,
                adc.adc2.map(sample), adc.adc2_valid);
            let mask = u32::from(routed.pressures[0].is_some())
                | (u32::from(routed.pressures[1].is_some()) << 1)
                | (u32::from(routed.load_cell_1.is_some()) << 2);
            (routed, mask, adc.adc1_captured, adc.adc2_captured)
        };
        let pt_1_pressure = routed.pressures[0].unwrap_or(0.0);
        let pt_2_pressure = routed.pressures[1].unwrap_or(0.0);
        let load_cell = routed.load_cell_1.unwrap_or(0.0);

        // 2. Gather FSW telemetry from umbilical
        let (fsw_connected, telemetry, fsw_captured) = {
            let umb = umbilical_readings.lock().await;
            (umb.connected && routing_mode.fsw_enabled(), umb.telemetry,
                if umb.connected && routing_mode.fsw_enabled() { umb.last_telem_instant } else { None })
        };

        // 3a. Gather last-commanded ball valve state.
        let ball_valve_open = actuator_state
            .ball_valve_open
            .load(std::sync::atomic::Ordering::Relaxed);
        // Deprecated motor-position field 62 stays zero/unknown. Never encode
        // the new solenoid QD's release command as a stepper position.
        let qd_state: i32 = 0;

        // 3. Gather hardware state (SV1, igniters)
        let (sv_1_open, ignition, configured_devices_mask, diagnostics) = {
            let hw = _hardware.lock().await;
            let sv1 = match hw.solenoid("sv1") {
                Some(sv) => sv.is_open().await.unwrap_or(false),
                None => false,
            };
            let diagnostics=hw.output_diagnostics().await;
            let ignition=diagnostics[0].output.unwrap_or(false) || diagnostics[1].output.unwrap_or(false);
            (sv1, ignition, hw.configured_devices_mask, diagnostics)
        };

        // 4. Build payload
        // Assembly time is distinct from ADC sample/FSW receive time. Stamp once
        // before serialization/queueing; MQTT reconnect does not restamp bytes.
        let (source, captured) = match source_clock.capture(kernel_time_quality()) {
            Ok(frame) => frame,
            Err(error) => {
                error!("MQTT publisher stopped rather than reusing metadata identity: {}", error);
                return;
            }
        };
        if source.sequence == 1 {
            info!("MQTT publisher session {} (profile {:?}); match this ID when selecting a Grafana session",
                source.session_id(), routing_mode);
        }
        if source.time_generation != last_time_generation {
            info!("MQTT source clock generation {}: quality {:?}, UNIX valid {} (reference accuracy unverified)",
                  source.time_generation, source.quality, source.unix_valid);
            last_time_generation = source.time_generation;
        }
        let (adc1_age, adc1_age_valid) = sample_age(captured, adc1_captured);
        let (adc2_age, adc2_age_valid) = sample_age(captured, adc2_captured);
        let (fsw_age, fsw_age_valid) = sample_age(captured, fsw_captured);
        let mut payload = if fsw_connected {
            TelemetryPayload {
                sync_word: 0,
                flight_mode: telemetry.flight_mode,
                pressure: telemetry.pressure as f64,
                temp: telemetry.temp as f64,
                altitude: telemetry.altitude as f64,
                latitude: telemetry.latitude as f64,
                longitude: telemetry.longitude as f64,
                num_satellites: telemetry.num_satellites,
                gps_time: telemetry.gps_time as f64,
                mag_x: telemetry.mag_x as f64,
                mag_y: telemetry.mag_y as f64,
                mag_z: telemetry.mag_z as f64,
                accel_x: telemetry.accel_x as f64,
                accel_y: telemetry.accel_y as f64,
                accel_z: telemetry.accel_z as f64,
                gyro_x: telemetry.gyro_x as f64,
                gyro_y: telemetry.gyro_y as f64,
                gyro_z: telemetry.gyro_z as f64,
                pt3: telemetry.pt3 as f64,
                pt4: telemetry.pt4 as f64,
                rtd: telemetry.rtd as f64,
                sv_2_open: telemetry.sv_open,
                mav_open: telemetry.mav_open,
                ms_since_boot_cfc: telemetry.ms_since_boot_cfc,
                ssa_drogue_deployed: telemetry.ssa_drogue_deployed.into(),
                ssa_main_deployed: telemetry.ssa_main_deployed.into(),
                cmd_n1: telemetry.cmd_n1.into(),
                cmd_n2: telemetry.cmd_n2.into(),
                cmd_n3: telemetry.cmd_n3.into(),
                cmd_n4: telemetry.cmd_n4.into(),
                cmd_a1: telemetry.cmd_a1.into(),
                cmd_a2: telemetry.cmd_a2.into(),
                cmd_a3: telemetry.cmd_a3.into(),
                airbrake_deployment: telemetry.airbrake_deployment as f64,
                predicted_apogee: telemetry.predicted_apogee as f64,
                h_acc: telemetry.h_acc,
                v_acc: telemetry.v_acc,
                vel_n: telemetry.vel_n,
                vel_e: telemetry.vel_e,
                vel_d: telemetry.vel_d,
                g_speed: telemetry.g_speed,
                s_acc: telemetry.s_acc,
                head_acc: telemetry.head_acc,
                fix_type: telemetry.fix_type.into(),
                head_mot: telemetry.head_mot,
                blims_brakeline_diff: telemetry.blims_brakeline_diff as f64,
                blims_phase_id: telemetry.blims_phase_id.into(),
                blims_pid_p: telemetry.blims_pid_p as f64,
                blims_pid_i: telemetry.blims_pid_i as f64,
                blims_bearing: telemetry.blims_bearing as f64,
                blims_upwind_lat: telemetry.blims_upwind_lat as f64,
                blims_upwind_lon: telemetry.blims_upwind_lon as f64,
                blims_downwind_lat: telemetry.blims_downwind_lat as f64,
                blims_downwind_lon: telemetry.blims_downwind_lon as f64,
                blims_wind_from_deg: telemetry.blims_wind_from_deg as f64,
                pt_1_pressure,
                pt_2_pressure,
                ball_valve_open,
                sv_1_open,
                load_cell,
                ignition,
                qd_state: qd_state.into(),
                ms_since_boot_fill,
                availability_version: 1,
                configured_devices_mask,
                valid_readings_mask,
                ..Default::default()
            }
        } else {
            // FSW not connected — still publish fill station data with zeroed FSW fields
            TelemetryPayload {
                pt_1_pressure,
                pt_2_pressure,
                ball_valve_open,
                sv_1_open,
                load_cell,
                ignition,
                qd_state: qd_state.into(),
                ms_since_boot_fill,
                availability_version: 1,
                configured_devices_mask,
                valid_readings_mask,
                ..Default::default()
            }
        };

        if routing_mode == RoutingMode::HybridTest {
            payload.pt3 = routed.pressures[2].unwrap_or(0.0);
            payload.pt4 = routed.pressures[3].unwrap_or(0.0);
            payload.valid_readings_mask |= (u32::from(routed.pressures[2].is_some()) << 3)
                | (u32::from(routed.pressures[3].is_some()) << 4);
            let hw = _hardware.lock().await;
            payload.sv_2_open = match hw.solenoid("sv2") {
                Some(sv) => sv.is_open().await.unwrap_or(false), None => false,
            };
            payload.mav_open = hw.mav().is_some_and(|mav| mav.is_open());
        }

        (payload.source_metadata_version, payload.operating_profile) = routing_mode.telemetry_identity();
        if routing_mode == RoutingMode::HybridTest {
            if let Some(lc2) = routed.load_cell_2 {
                payload.load_cell_2_raw = i32::from(lc2.raw);
                payload.load_cell_2_voltage = f64::from(lc2.voltage);
                payload.load_cell_2_valid = true;
            }
        }
        if payload.source_metadata_version == 3 { apply_output_diagnostics(&mut payload, diagnostics); }
        payload.publisher_session_hi = source.session_hi;
        payload.publisher_session_lo = source.session_lo;
        payload.publisher_sequence = source.sequence;
        payload.source_monotonic_ms = source.monotonic_ms;
        payload.source_unix_ms = source.unix_ms;
        payload.source_unix_valid = source.unix_valid;
        payload.source_time_quality = source.quality as u32;
        payload.source_time_generation = source.time_generation;
        payload.adc1_sample_age_ms = adc1_age;
        payload.adc1_sample_age_valid = adc1_age_valid;
        payload.adc2_sample_age_ms = adc2_age;
        payload.adc2_sample_age_valid = adc2_age_valid;
        payload.fsw_receive_age_ms = fsw_age;
        payload.fsw_receive_age_valid = fsw_age_valid;

        // 5. Serialize (nanopb protobuf) and publish
        let outcome = match telemetry_pb::encode(&payload) {
            Some(bytes) => match client.try_publish(MQTT_TOPIC, QoS::AtMostOnce, false, bytes) {
                Ok(()) => Outcome::Queued,
                Err(e) => {
                    warn!("MQTT publish failed (broker may be offline): {}", e);
                    Outcome::Rejected
                }
            },
            None => {
                error!("Failed to encode MQTT payload with nanopb");
                Outcome::EncodingFailed
            }
        };

        #[cfg(feature = "debug-json")]
        match serde_json::to_string(&payload) {
            Ok(json) => {
                if let Err(e) = client.try_publish(MQTT_DEBUG_TOPIC, QoS::AtMostOnce, false, json) {
                    warn!("MQTT debug publish failed (broker may be offline): {}", e);
                }
            }
            Err(e) => {
                error!("Failed to serialize debug MQTT payload: {}", e);
            }
        }

        // 6. Sleep for remainder of interval
        let elapsed = start.elapsed();
        stats.record(outcome, elapsed, interval);
        let window = stats_start.elapsed();
        if window >= Duration::from_secs(10) {
            info!("MQTT publisher window: target_hz={} window_ms={} attempts={} queued={} rejected={} encoding_failed={} queued_hz={:.2} work_overruns={} max_work_us={} last_sequence={}; queued is local acceptance, not delivery",
                publish_rate, window.as_millis(), stats.attempted, stats.queued,
                stats.rejected, stats.encoding_failed, stats.queued as f64 / window.as_secs_f64(),
                stats.overruns, stats.max_work.as_micros(), source.sequence);
            stats = Stats::default();
            stats_start = Instant::now();
        }
        let elapsed = start.elapsed();
        if elapsed < interval {
            Timer::after(interval - elapsed).await;
        }
    }
}

fn apply_output_diagnostics(payload: &mut TelemetryPayload, diagnostics:[OutputDiagnostic;3]) {
    (payload.ig1_output_active,payload.ig1_continuity,payload.ig1_output_valid,payload.ig1_continuity_valid) = diagnostics[0].wire_values();
    (payload.ig2_output_active,payload.ig2_continuity,payload.ig2_output_valid,payload.ig2_continuity_valid) = diagnostics[1].wire_values();
    (payload.qd_release_energized,payload.qd_continuity,payload.qd_output_valid,payload.qd_continuity_valid) = diagnostics[2].wire_values();
}
#[cfg(test)]
mod output_diagnostic_tests {
    use super::*;
    #[test]
    fn payload_preserves_unknown_vs_false_and_uses_explicit_qd_release_field() {
        let mut payload=TelemetryPayload::default();
        apply_output_diagnostics(&mut payload,[OutputDiagnostic {output:Some(false),continuity:Some(true)},
            OutputDiagnostic::default(),OutputDiagnostic {output:Some(true),continuity:None}]);
        assert!(!payload.ig1_output_active && payload.ig1_output_valid && payload.ig1_continuity_valid);
        assert!(payload.ig1_continuity && !payload.ig2_output_valid && !payload.ig2_continuity_valid);
        assert!(payload.qd_release_energized && payload.qd_output_valid && !payload.qd_continuity_valid);
        assert_eq!(payload.qd_state,0);
    }
}
