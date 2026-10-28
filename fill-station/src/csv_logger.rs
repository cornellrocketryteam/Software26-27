use smol::Timer;
use smol::fs::{self, OpenOptions};
use smol::io::AsyncWriteExt;
use smol::lock::Mutex;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tracing::{error, info};

use crate::command::{AdcReadings, UmbilicalReadings};
use crate::hardware::Hardware;

pub async fn start_logging(
    _hardware: Arc<Mutex<Hardware>>,
    adc_readings: Arc<Mutex<AdcReadings>>,
    umbilical_readings: Arc<Mutex<UmbilicalReadings>>,
) {
    info!("Starting CSV Logger task...");

    // Create logs directory if it doesn't exist
    #[cfg(target_os = "linux")]
    let log_dir = "/tmp/data";
    #[cfg(not(target_os = "linux"))]
    let log_dir = "logs";

    fs::create_dir_all(log_dir).await.ok();

    // Create filename with timestamp
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();

    let mut filename = format!("{}/fill_station_log_{}.csv", log_dir, timestamp);
    let mut file_index = 1;

    // Ensure we create a new file instead of re-using one
    while std::path::Path::new(&filename).exists() {
        filename = format!(
            "{}/fill_station_log_{}_{}.csv",
            log_dir, timestamp, file_index
        );
        file_index += 1;
    }

    let mut file = match OpenOptions::new()
        .create(true) // this creates the file if it doesn't exist
        .write(true)
        .truncate(true) // Ensure we start with a clean file
        .open(&filename)
        .await
    {
        Ok(f) => {
            info!("Created log file: {}", filename);
            f
        }
        Err(e) => {
            error!("Failed to create log file: {}", e);
            return;
        }
    };

    // Write Header
    let header = "Loop,Timestamp_ms,Igniter1_Active,Igniter2_Active,\
SV1_Open,SV1_Cont,SV2_Open,SV2_Cont,SV3_Open,SV3_Cont,SV4_Open,SV4_Cont,SV5_Open,SV5_Cont,\
MAV_Open,MAV_Pulse_US,\
ADC1_0_Raw,ADC1_0_Scaled,ADC1_1_Raw,ADC1_1_Scaled,ADC1_2_Raw,ADC1_2_Scaled,ADC1_3_Raw,ADC1_3_Scaled,\
ADC2_0_Raw,ADC2_0_Scaled,ADC2_1_Raw,ADC2_1_Scaled,ADC2_2_Raw,ADC2_2_Scaled,ADC2_3_Raw,ADC2_3_Scaled,\
FSW_Connected,FSW_Mode,FSW_Pressure,FSW_Temp,FSW_Altitude,FSW_Lat,FSW_Lon,FSW_Sats,FSW_Timestamp,\
FSW_MagX,FSW_MagY,FSW_MagZ,FSW_AccelX,FSW_AccelY,FSW_AccelZ,FSW_GyroX,FSW_GyroY,FSW_GyroZ,\
FSW_PT3,FSW_PT4,FSW_RTD,FSW_SV_Open,FSW_MAV_Open,\
QD_Enabled,QD_Direction,Availability_Version,Configured_Devices_Mask,Valid_Readings_Mask\n";

    if let Err(e) = file.write_all(header.as_bytes()).await {
        error!("Failed to write header to log file: {}", e);
        return;
    }

    let mut loop_count: u64 = 0;

    // Run at 100Hz
    let interval = Duration::from_millis(10);

    loop {
        let start_time = std::time::Instant::now();
        loop_count += 1;

        // 1. Gather ADC Data
        let (adc_timestamp, adc1_valid, adc2_valid, valid_readings_mask, adc1, adc2) = {
            let reading = adc_readings.lock().await;
            (
                reading.timestamp_ms,
                reading.adc1_valid,
                reading.adc2_valid,
                reading.valid_readings_mask(),
                reading.adc1,
                reading.adc2,
            )
        };

        // 2. Gather Hardware Data (SV, MAV, Igniters)
        // We lock hardware briefly
        let (ig1_active, ig2_active, sv_states, mav_open, mav_pulse, configured_devices_mask) = {
            let hw = _hardware.lock().await;
            let ig1 = match hw.igniter("ig1") {
                Some(d) => Some(d.is_igniting().await),
                None => None,
            };
            let ig2 = match hw.igniter("ig2") {
                Some(d) => Some(d.is_igniting().await),
                None => None,
            };
            let mut valves = Vec::new();
            for role in ["sv1", "sv2", "sv3", "sv4", "sv5"] {
                valves.push(match hw.solenoid(role) {
                    Some(d) => (d.is_open().await.ok(), d.check_continuity().await.ok()),
                    None => (None, None),
                });
            }
            (
                csv_value(ig1),
                csv_value(ig2),
                valves,
                csv_value(hw.mav().map(|d| d.is_open())),
                csv_value(hw.mav().map(|d| d.pulse_width_us())),
                hw.configured_devices_mask,
            )
        };

        // Format CSV Line
        let mut line = format!(
            "{},{},{},{},",
            loop_count, adc_timestamp, ig1_active, ig2_active
        );

        // Append SVs
        for (open, cont) in sv_states {
            line.push_str(&format!("{},{},", csv_value(open), csv_value(cont)));
        }

        // Append MAV
        line.push_str(&format!("{},{},", mav_open, mav_pulse));

        // Empty columns distinguish unavailable readings from a measured zero.
        for (valid, channels) in [(adc1_valid, adc1), (adc2_valid, adc2)] {
            for ch in channels {
                if valid {
                    line.push_str(&format!(
                        "{},{},",
                        ch.raw,
                        ch.scaled.map(|v| format!("{:.4}", v)).unwrap_or_default()
                    ));
                } else {
                    line.push_str(",,");
                }
            }
        }

        // 3. Gather FSW telemetry
        {
            let umb = umbilical_readings.lock().await;
            if umb.connected {
                let t = &umb.telemetry;
                line.push_str(&format!(
                    "true,{},{:.2},{:.2},{:.2},{:.6},{:.6},{},{:.3},{:.2},{:.2},{:.2},{:.4},{:.4},{:.4},{:.4},{:.4},{:.4},{:.2},{:.2},{:.2},{},{}",
                    t.flight_mode, t.pressure, t.temp, t.altitude,
                    t.latitude, t.longitude, t.num_satellites, t.gps_time,
                    t.mag_x, t.mag_y, t.mag_z,
                    t.accel_x, t.accel_y, t.accel_z,
                    t.gyro_x, t.gyro_y, t.gyro_z,
                    t.pt3, t.pt4, t.rtd,
                    t.sv_open, t.mav_open,
                ));
            } else {
                // 23 FSW columns: connected + 20 telemetry fields + 2 valve states
                let nas = std::iter::repeat("N/A")
                    .take(23)
                    .collect::<Vec<_>>()
                    .join(",");
                line.push_str(&nas);
            }
        }

        {
            let hw = _hardware.lock().await;
            let (enabled, direction) = match hw.qd_stepper() {
                Some(d) => (Some(d.is_enabled().await), Some(d.get_direction().await)),
                None => (None, None),
            };
            line.push_str(&format!(
                ",{},{},1,{},{}",
                csv_value(enabled),
                csv_value(direction),
                configured_devices_mask,
                valid_readings_mask
            ));
        }

        line.push('\n');

        // Write to file
        if let Err(e) = file.write_all(line.as_bytes()).await {
            error!("Failed to write to log file: {}", e);
        }

        // Sync to disk every 10 seconds (1000 samples) to prevent data loss on power cycle
        if loop_count % 1000 == 0 {
            if let Err(e) = file.sync_all().await {
                error!("Failed to sync log file: {}", e);
            }
        }

        // Sleep
        let elapsed = start_time.elapsed();
        if elapsed < interval {
            Timer::after(interval - elapsed).await;
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
