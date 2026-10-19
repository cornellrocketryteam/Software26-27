use rumqttc::{Client, MqttOptions, QoS};
use smol::Timer;
use std::sync::Arc;
use std::time::{Duration, Instant};
use smol::lock::Mutex;
use tracing::{info, warn, error, debug};

use crate::hardware::Hardware;
use crate::command::{ActuatorState, AdcReadings, UmbilicalReadings};
// From the lib crate so the nanopb static library (linked into the lib) comes along
use fill_station::telemetry_pb::{self, TelemetryPayload};

// ============================================================================
// MQTT CONFIGURATION
// ============================================================================

/// IP address of the EMQX MQTT broker
const BROKER_HOST: &str = "192.168.1.206";

/// MQTT broker port
const BROKER_PORT: u16 = 1883;

/// Publish rate in Hz
const PUBLISH_RATE_HZ: u64 = 10;

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
    info!("Starting MQTT publisher task ({}:{}, topic: {}, rate: {} Hz)",
          BROKER_HOST, BROKER_PORT, MQTT_TOPIC, PUBLISH_RATE_HZ);

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
    let interval = Duration::from_millis(1000 / PUBLISH_RATE_HZ);

    loop {
        let start = Instant::now();
        let ms_since_boot_fill = boot_time.elapsed().as_millis() as u64;

        // 1. Gather ADC data
        let (pt_1_pressure, pt_2_pressure, load_cell) = {
            let adc = adc_readings.lock().await;
            if adc.valid {
                (
                    adc.adc1[0].scaled.unwrap_or(0.0) as f64, // PT1 (ADC1 Ch0)
                    adc.adc1[1].scaled.unwrap_or(0.0) as f64, // PT2 (ADC1 Ch1)
                    adc.adc2[1].scaled.unwrap_or(0.0) as f64, // Load cell
                )
            } else {
                (0.0, 0.0, 0.0)
            }
        };

        // 2. Gather FSW telemetry from umbilical
        let (fsw_connected, telemetry) = {
            let umb = umbilical_readings.lock().await;
            (umb.connected, umb.telemetry)
        };

        // 3a. Gather last-commanded actuator state (ball valve, QD)
        let ball_valve_open = actuator_state.ball_valve_open.load(std::sync::atomic::Ordering::Relaxed);
        let qd_state = actuator_state.qd_state.load(std::sync::atomic::Ordering::Relaxed);

        // 3. Gather hardware state (SV1, igniters)
        let (sv_1_open, ignition) = {
            #[cfg(any(target_os = "linux", target_os = "android"))]
            {
                let hw = _hardware.lock().await;
                let sv1 = hw.sv1.is_open().await.unwrap_or(false);
                let ig = hw.ig1.is_igniting().await;
                (sv1, ig)
            }
            #[cfg(not(any(target_os = "linux", target_os = "android")))]
            {
                (false, false)
            }
        };

        // 4. Build payload
        let payload = if fsw_connected {
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
                ..Default::default()
            }
        };

        // 5. Serialize (nanopb protobuf) and publish
        match telemetry_pb::encode(&payload) {
            Some(bytes) => {
                if let Err(e) = client.try_publish(MQTT_TOPIC, QoS::AtMostOnce, false, bytes) {
                    warn!("MQTT publish failed (broker may be offline): {}", e);
                }
            }
            None => {
                error!("Failed to encode MQTT payload with nanopb");
            }
        }

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
        if elapsed < interval {
            Timer::after(interval - elapsed).await;
        }
    }
}
