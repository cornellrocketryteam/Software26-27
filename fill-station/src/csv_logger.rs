use crate::command::{ActuatorState, AdcReadings, UmbilicalReadings};
use crate::hardware::Hardware;
use crate::operating_runtime::{OutputDiagnostic, RoutingMode, Sample, route_sensors};
use fill_station::telemetry_clock::{
    FrameMetadata, PublisherClock, kernel_time_quality, sample_age,
};
use smol::Timer;
use smol::fs::{self, OpenOptions};
use smol::io::AsyncWriteExt;
use smol::lock::Mutex;
use std::sync::{Arc, atomic::Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tracing::{error, info};

const LEGACY_HEADER: &str = "Loop,Timestamp_ms,Igniter1_Active,Igniter2_Active,\
SV1_Open,SV1_Cont,SV2_Open,SV2_Cont,SV3_Open,SV3_Cont,SV4_Open,SV4_Cont,SV5_Open,SV5_Cont,\
MAV_Open,MAV_Pulse_US,\
ADC1_0_Raw,ADC1_0_Scaled,ADC1_1_Raw,ADC1_1_Scaled,ADC1_2_Raw,ADC1_2_Scaled,ADC1_3_Raw,ADC1_3_Scaled,\
ADC2_0_Raw,ADC2_0_Scaled,ADC2_1_Raw,ADC2_1_Scaled,ADC2_2_Raw,ADC2_2_Scaled,ADC2_3_Raw,ADC2_3_Scaled,\
FSW_Connected,FSW_Mode,FSW_Pressure,FSW_Temp,FSW_Altitude,FSW_Lat,FSW_Lon,FSW_Sats,FSW_Timestamp,\
FSW_MagX,FSW_MagY,FSW_MagZ,FSW_AccelX,FSW_AccelY,FSW_AccelZ,FSW_GyroX,FSW_GyroY,FSW_GyroZ,\
FSW_PT3,FSW_PT4,FSW_RTD,FSW_SV_Open,FSW_MAV_Open,\
QD_Enabled,QD_Direction,Availability_Version,Configured_Devices_Mask,Valid_Readings_Mask\n";

const EXTRA_HEADER: &str = "CSV_Schema_Version,Operating_Profile,FSW_Enabled,PT1_PSI,PT1_Valid,PT2_PSI,PT2_Valid,PT3_PSI,PT3_Valid,PT4_PSI,PT4_Valid,LC1_Scaled,LC1_Valid,LC2_Raw,LC2_Voltage,LC2_Valid,SV2_Profile_Open,MAV_Profile_Open,BV_Commanded_Open,CSV_Session_Hi,CSV_Session_Lo,CSV_Sequence,CSV_Monotonic_ms,CSV_Unix_ms,CSV_Unix_Valid,CSV_Time_Quality,CSV_Time_Generation,ADC1_Sample_Age_ms,ADC1_Sample_Age_Valid,ADC2_Sample_Age_ms,ADC2_Sample_Age_Valid,FSW_Receive_Age_ms,FSW_Receive_Age_Valid";
const DIAGNOSTIC_HEADER: &str = "IG1_Output_Active,IG1_Continuity,IG1_Output_Valid,IG1_Continuity_Valid,IG2_Output_Active,IG2_Continuity,IG2_Output_Valid,IG2_Continuity_Valid,QD_Release_Energized,QD_Continuity,QD_Output_Valid,QD_Continuity_Valid";
fn csv_header() -> String {
    format!(
        "{},{},{}\n",
        LEGACY_HEADER.trim_end(),
        EXTRA_HEADER,
        DIAGNOSTIC_HEADER
    )
}

struct CsvHardware {
    mode: RoutingMode,
    diagnostics: [OutputDiagnostic; 3],
    igniters: [Option<bool>; 2],
    valves: [(Option<bool>, Option<bool>); 5],
    mav_open: Option<bool>,
    mav_pulse: Option<u32>,
    configured_mask: u32,
    ball_valve: Option<bool>,
}
fn finite(value: f32) -> Option<f64> {
    value.is_finite().then_some(f64::from(value))
}
fn render_row(
    loop_count: u64,
    adc: &AdcReadings,
    umb: &UmbilicalReadings,
    hw: &CsvHardware,
    frame: FrameMetadata,
    captured: Instant,
) -> String {
    let sample = |s: crate::command::ChannelReading| Sample {
        raw: s.raw,
        voltage: s.voltage,
        scaled: s.scaled,
    };
    let routed = route_sensors(
        hw.mode,
        adc.adc1.map(sample),
        adc.adc1_valid,
        adc.adc2.map(sample),
        adc.adc2_valid,
    );
    let fsw_connected = hw.mode.fsw_enabled() && umb.connected;
    let mut values = vec![loop_count.to_string(), adc.timestamp_ms.to_string()];
    values.extend(hw.igniters.map(csv_value));
    for (open, cont) in hw.valves {
        values.extend([csv_value(open), csv_value(cont)]);
    }
    values.extend([csv_value(hw.mav_open), csv_value(hw.mav_pulse)]);
    for (adc_index, (valid, channels)) in [(adc.adc1_valid, adc.adc1), (adc.adc2_valid, adc.adc2)]
        .into_iter()
        .enumerate()
    {
        for (channel_index, ch) in channels.into_iter().enumerate() {
            values.push(csv_value(valid.then_some(ch.raw)));
            values.push(
                if valid
                    && !(hw.mode == RoutingMode::HybridTest && adc_index == 1 && channel_index == 2)
                {
                    ch.scaled
                        .filter(|v| v.is_finite())
                        .map(|v| format!("{v:.4}"))
                        .unwrap_or_default()
                } else {
                    String::new()
                },
            );
        }
    }
    if fsw_connected {
        let t = &umb.telemetry;
        let fields = format!(
            "true,{},{:.2},{:.2},{:.2},{:.6},{:.6},{},{:.3},{:.2},{:.2},{:.2},{:.4},{:.4},{:.4},{:.4},{:.4},{:.4},{:.2},{:.2},{:.2},{},{}",
            t.flight_mode,
            t.pressure,
            t.temp,
            t.altitude,
            t.latitude,
            t.longitude,
            t.num_satellites,
            t.gps_time,
            t.mag_x,
            t.mag_y,
            t.mag_z,
            t.accel_x,
            t.accel_y,
            t.accel_z,
            t.gyro_x,
            t.gyro_y,
            t.gyro_z,
            t.pt3,
            t.pt4,
            t.rtd,
            t.sv_open,
            t.mav_open
        );
        values.extend(fields.split(',').map(str::to_owned));
    } else {
        values.extend(std::iter::repeat_n("N/A".to_string(), 23));
    }
    let mut mask = u32::from(routed.pressures[0].is_some())
        | (u32::from(routed.pressures[1].is_some()) << 1)
        | (u32::from(routed.load_cell_1.is_some()) << 2);
    if hw.mode == RoutingMode::HybridTest {
        mask |= (u32::from(routed.pressures[2].is_some()) << 3)
            | (u32::from(routed.pressures[3].is_some()) << 4);
    }
    values.extend([
        "N/A".into(),
        "N/A".into(),
        "1".into(),
        hw.configured_mask.to_string(),
        mask.to_string(),
    ]);
    let name = match hw.mode {
        RoutingMode::Legacy => "legacy",
        RoutingMode::Hybrid => "hybrid",
        RoutingMode::HybridTest => "hybrid-test",
    };
    values.extend(["3".into(), name.into(), hw.mode.fsw_enabled().to_string()]);
    for i in 0..4 {
        let value = if i < 2 || hw.mode == RoutingMode::HybridTest {
            routed.pressures[i]
        } else if fsw_connected {
            finite(if i == 2 {
                umb.telemetry.pt3
            } else {
                umb.telemetry.pt4
            })
        } else {
            None
        };
        values.extend([csv_value(value), value.is_some().to_string()]);
    }
    values.extend([
        csv_value(routed.load_cell_1),
        routed.load_cell_1.is_some().to_string(),
        csv_value(routed.load_cell_2.map(|v| v.raw)),
        csv_value(routed.load_cell_2.map(|v| v.voltage)),
        routed.load_cell_2.is_some().to_string(),
    ]);
    let (sv2, mav) = if hw.mode == RoutingMode::HybridTest {
        (hw.valves[1].0, hw.mav_open)
    } else {
        (
            fsw_connected.then_some(umb.telemetry.sv_open),
            fsw_connected.then_some(umb.telemetry.mav_open),
        )
    };
    values.extend([csv_value(sv2), csv_value(mav), csv_value(hw.ball_valve)]);
    values.extend([
        frame.session_hi.to_string(),
        frame.session_lo.to_string(),
        frame.sequence.to_string(),
        frame.monotonic_ms.to_string(),
        frame.unix_ms.to_string(),
        frame.unix_valid.to_string(),
        (frame.quality as u32).to_string(),
        frame.time_generation.to_string(),
    ]);
    for previous in [
        adc.adc1_captured,
        adc.adc2_captured,
        if fsw_connected {
            umb.last_telem_instant
        } else {
            None
        },
    ] {
        let (age, valid) = sample_age(captured, previous);
        values.extend([
            if valid {
                age.to_string()
            } else {
                String::new()
            },
            valid.to_string(),
        ]);
    }
    for diagnostic in hw.diagnostics {
        values.extend([
            csv_value(diagnostic.output),
            csv_value(diagnostic.continuity),
            diagnostic.output.is_some().to_string(),
            diagnostic.continuity.is_some().to_string(),
        ]);
    }
    values.join(",") + "\n"
}

async fn open_log_file(log_dir: &str, timestamp: u64) -> std::io::Result<smol::fs::File> {
    let mut index = 0u64;
    loop {
        let suffix = if index == 0 {
            String::new()
        } else {
            format!("_{index}")
        };
        let filename = format!("{log_dir}/fill_station_log_{timestamp}{suffix}.csv");
        match OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&filename)
            .await
        {
            Ok(f) => {
                info!("Created CSV log: {}", filename);
                return Ok(f);
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                index = match index.checked_add(1) {
                    Some(n) => n,
                    None => {
                        return Err(std::io::Error::other("CSV filename counter exhausted"));
                    }
                };
            }
            Err(e) => {
                return Err(e);
            }
        }
    }
}

pub async fn start_logging(
    hardware: Arc<Mutex<Hardware>>,
    adc_readings: Arc<Mutex<AdcReadings>>,
    umbilical_readings: Arc<Mutex<UmbilicalReadings>>,
    actuator_state: Arc<ActuatorState>,
) {
    info!("Starting CSV Logger task...");
    #[cfg(target_os = "linux")]
    let log_dir = "/var/log/fill-station";
    #[cfg(not(target_os = "linux"))]
    let log_dir = "logs";
    if let Err(e) = fs::create_dir_all(log_dir).await {
        error!("Cannot create CSV directory: {}", e);
        return;
    }
    let mut clock = match PublisherClock::new() {
        Ok(c) => c,
        Err(e) => {
            error!("Cannot create CSV session: {}", e);
            return;
        }
    };
    // A pre-epoch clock does not prevent logging; row timestamps carry validity.
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let mut file = match open_log_file(log_dir, timestamp).await {
        Ok(file) => file,
        Err(e) => {
            error!("Cannot create CSV log: {}", e);
            return;
        }
    };
    if let Err(e) = file.write_all(csv_header().as_bytes()).await {
        error!("Cannot write CSV header: {}", e);
        return;
    }
    let interval = Duration::from_millis(10);
    loop {
        let start = Instant::now();
        let adc = adc_readings.lock().await.clone();
        let umb = umbilical_readings.lock().await.clone();
        let hw = {
            let hw = hardware.lock().await;
            let diagnostics = hw.output_diagnostics().await;
            let igniters = [diagnostics[0].output, diagnostics[1].output];
            let mut valves = [(None, None); 5];
            for (i, role) in ["sv1", "sv2", "sv3", "sv4", "sv5"].iter().enumerate() {
                if i == 4 && hw.quick_disconnect("sv5").is_some() {
                    valves[i] = (diagnostics[2].output, diagnostics[2].continuity);
                } else if let Some(d) = hw.solenoid(role) {
                    valves[i] = (d.is_open().await.ok(), d.check_continuity().await.ok());
                }
            }
            CsvHardware {
                mode: hw.routing_mode,
                diagnostics,
                igniters,
                valves,
                mav_open: hw.mav().map(|d| d.is_open()),
                mav_pulse: hw.mav().map(|d| d.pulse_width_us()),
                configured_mask: hw.configured_devices_mask,
                ball_valve: hw
                    .has_role("ball_valve")
                    .then(|| actuator_state.ball_valve_open.load(Ordering::Relaxed)),
            }
        };
        let (frame, captured) = match clock.capture(kernel_time_quality()) {
            Ok(f) => f,
            Err(e) => {
                error!("CSV clock stopped: {}", e);
                return;
            }
        };
        let line = render_row(frame.sequence, &adc, &umb, &hw, frame, captured);
        if let Err(e) = file.write_all(line.as_bytes()).await {
            error!("CSV write failed: {}", e);
            return;
        }
        // Best-effort periodic sync, not a guarantee of power-loss durability.
        if frame.sequence % 1000 == 0 {
            if let Err(e) = file.sync_all().await {
                error!("CSV sync failed: {}", e);
            }
        }
        let remaining = interval.saturating_sub(start.elapsed());
        if !remaining.is_zero() {
            Timer::after(remaining).await;
        }
    }
}
fn csv_value<T: std::fmt::Display>(value: Option<T>) -> String {
    value.map(|v| v.to_string()).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn missing_is_empty_but_false_and_zero_remain_values() {
        assert_eq!(csv_value::<bool>(None), "");
        assert_eq!(csv_value(Some(false)), "false");
        assert_eq!(csv_value(Some(0)), "0");
    }
}

#[cfg(test)]
mod profile_csv_tests {
    use super::*;
    use fill_station::telemetry_clock::TimeQuality;
    #[test]
    fn files_do_not_overwrite_on_epoch_collision_and_have_parseable_rows() {
        smol::block_on(async {
            let (metadata, _) = PublisherClock::new()
                .unwrap()
                .capture(TimeQuality::Unknown)
                .unwrap();
            let path = std::env::temp_dir().join(format!(
                "crt-csv-{:016x}{:016x}",
                metadata.session_hi, metadata.session_lo
            ));
            struct Cleanup(std::path::PathBuf);
            impl Drop for Cleanup {
                fn drop(&mut self) {
                    let _ = std::fs::remove_dir_all(&self.0);
                }
            }
            std::fs::create_dir(&path).unwrap();
            let _cleanup = Cleanup(path.clone());
            let mut first = open_log_file(path.to_str().unwrap(), 0).await.unwrap();
            let (adc, umb, hw, frame) = fixture(RoutingMode::HybridTest);
            let contents = csv_header() + &render_row(1, &adc, &umb, &hw, frame, Instant::now());
            first.write_all(contents.as_bytes()).await.unwrap();
            first.sync_all().await.unwrap();
            drop(first);
            let second = open_log_file(path.to_str().unwrap(), 0).await.unwrap();
            drop(second);
            assert_eq!(
                std::fs::read_to_string(path.join("fill_station_log_0.csv")).unwrap(),
                contents
            );
            assert!(path.join("fill_station_log_0_1.csv").is_file());
            let rows: Vec<_> = contents.lines().collect();
            assert_eq!(rows[0].split(',').count(), rows[1].split(',').count());
        });
    }
    #[test]
    fn zero_is_valid_and_disconnected_remote_values_are_absent() {
        let (mut adc, mut umb, hw, frame) = fixture(RoutingMode::Hybrid);
        adc.adc1[0].scaled = Some(0.0);
        umb.connected = false;
        let names = csv_header();
        let row = render_row(1, &adc, &umb, &hw, frame, Instant::now());
        let values: std::collections::BTreeMap<_, _> = names
            .trim_end()
            .split(',')
            .zip(row.trim_end().split(','))
            .collect();
        assert_eq!(values["PT1_PSI"], "0");
        assert_eq!(values["PT1_Valid"], "true");
        assert_eq!(values["PT3_PSI"], "");
        assert_eq!(values["SV2_Profile_Open"], "");
        assert_eq!(values["FSW_Receive_Age_Valid"], "false");
    }
    fn fixture(mode: RoutingMode) -> (AdcReadings, UmbilicalReadings, CsvHardware, FrameMetadata) {
        let mut adc = AdcReadings::default();
        adc.adc1_valid = true;
        adc.adc2_valid = true;
        for i in 0..4 {
            adc.adc1[i] = crate::command::ChannelReading {
                raw: 100 + i as i16,
                voltage: 0.1 + i as f32,
                scaled: Some(1000.0 + i as f32),
            };
            adc.adc2[i] = crate::command::ChannelReading {
                raw: 200 + i as i16,
                voltage: 0.2 + i as f32,
                scaled: Some(2000.0 + i as f32),
            };
        }
        let mut umb = UmbilicalReadings::default();
        umb.connected = true;
        umb.telemetry.pt3 = 30.0;
        umb.telemetry.pt4 = 40.0;
        umb.telemetry.sv_open = false;
        umb.telemetry.mav_open = false;
        let hw = CsvHardware {
            mode,
            diagnostics: [
                OutputDiagnostic {
                    output: Some(false),
                    continuity: Some(true),
                },
                OutputDiagnostic::default(),
                OutputDiagnostic {
                    output: Some(true),
                    continuity: None,
                },
            ],
            igniters: [Some(false); 2],
            valves: [(Some(true), Some(false)); 5],
            mav_open: Some(true),
            mav_pulse: Some(1000),
            configured_mask: 1855,
            ball_valve: Some(false),
        };
        let frame = FrameMetadata {
            session_hi: 1,
            session_lo: 2,
            sequence: 1,
            monotonic_ms: 0,
            unix_ms: 0,
            unix_valid: false,
            quality: TimeQuality::Unknown,
            time_generation: 1,
        };
        (adc, umb, hw, frame)
    }
    fn fields(mode: RoutingMode) -> std::collections::BTreeMap<String, String> {
        let (adc, umb, hw, frame) = fixture(mode);
        let row = render_row(1, &adc, &umb, &hw, frame, std::time::Instant::now());
        let names = csv_header();
        let keys: Vec<_> = names.trim_end().split(',').collect();
        let values: Vec<_> = row.trim_end().split(',').collect();
        assert_eq!(keys.len(), values.len());
        assert!(names.starts_with(LEGACY_HEADER.trim_end()));
        keys.into_iter()
            .zip(values)
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }
    #[test]
    fn test_stand_uses_local_channels_and_raw_uncalibrated_lc2() {
        let f = fields(RoutingMode::HybridTest);
        assert_eq!(f["PT3_PSI"], "1002");
        assert_eq!(f["PT4_PSI"], "1003");
        assert_eq!(f["LC2_Raw"], "202");
        assert_eq!(f["ADC2_2_Scaled"], "");
        assert_eq!(f["LC2_Voltage"], "2.2");
        assert_eq!(f["LC2_Valid"], "true");
        assert_eq!(f["FSW_Enabled"], "false");
        assert_eq!(f["FSW_PT3"], "N/A");
        assert_eq!(f["SV2_Profile_Open"], "true");
        assert_eq!(f["MAV_Profile_Open"], "true");
        assert_eq!(f["BV_Commanded_Open"], "false");
    }
    #[test]
    fn diagnostic_columns_keep_known_false_distinct_from_missing() {
        let f = fields(RoutingMode::HybridTest);
        assert_eq!(f["CSV_Schema_Version"], "3");
        assert_eq!(f["IG1_Output_Active"], "false");
        assert_eq!(f["IG1_Output_Valid"], "true");
        assert_eq!(f["IG2_Output_Active"], "");
        assert_eq!(f["IG2_Output_Valid"], "false");
        assert_eq!(f["QD_Release_Energized"], "true");
        assert_eq!(f["QD_Continuity"], "");
        assert_eq!(f["QD_Continuity_Valid"], "false");
    }
    #[test]
    fn hybrid_keeps_fsw_ownership_and_lc2_absent() {
        let f = fields(RoutingMode::Hybrid);
        assert_eq!(f["PT3_PSI"], "30");
        assert_eq!(f["SV2_Profile_Open"], "false");
        assert_eq!(f["LC2_Raw"], "");
        assert_eq!(f["LC2_Valid"], "false");
    }
    #[test]
    fn invalid_samples_are_empty_and_clock_identity_is_csv_specific() {
        let (mut adc, mut umb, hw, frame) = fixture(RoutingMode::HybridTest);
        adc.adc1_valid = false;
        adc.adc2[2].voltage = f32::NAN;
        umb.connected = false;
        let names = csv_header();
        let row = render_row(1, &adc, &umb, &hw, frame, std::time::Instant::now());
        let f: std::collections::BTreeMap<_, _> = names
            .trim_end()
            .split(',')
            .zip(row.trim_end().split(','))
            .collect();
        assert_eq!(f["PT1_PSI"], "");
        assert_eq!(f["PT3_Valid"], "false");
        assert_eq!(f["LC2_Voltage"], "");
        assert_eq!(f["CSV_Unix_Valid"], "false");
        assert_eq!(f["CSV_Sequence"], "1");
        assert_eq!(f["CSV_Session_Hi"], "1");
    }
}
