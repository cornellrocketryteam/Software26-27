use crate::components::umbilical::FswTelemetry;
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicBool, AtomicI16};
use std::time::Instant;

/// Last commanded state of fill-station actuators that we can't read back from
/// hardware. Updated by the command handler, read by the MQTT publisher (and
/// anything else that wants the most recent intent).
///
/// `qd_state`: -1 = retracted, 0 = unknown/initial, 1 = extended.
#[derive(Debug)]
pub struct ActuatorState {
    pub ball_valve_open: AtomicBool,
    pub qd_state: AtomicI16,
}

impl Default for ActuatorState {
    fn default() -> Self {
        Self {
            ball_valve_open: AtomicBool::new(false),
            qd_state: AtomicI16::new(0),
        }
    }
}

/// All supported commands for the fill station
#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "command", rename_all = "snake_case")]
pub enum Command {
    /// Fire igniters and send launch command to FSW simultaneously
    Launch,
    GetHardwareAvailability,
    Ignite,
    /// Query continuity for a specific igniter (1 or 2)
    GetIgniterContinuity {
        id: u8,
    },
    /// Start streaming ADC readings to this client
    StartAdcStream,
    /// Stop streaming ADC readings to this client
    StopAdcStream,
    /// Open or close a solenoid valve
    ActuateValve {
        /// Name of the valve ("SV1".."SV5")
        valve: String,
        /// True to open the valve, False to close it.
        /// The server handles the correct GPIO level based on NO/NC configuration.
        open: bool,
    },
    /// Open fill-station MAV. With `duration_ms`, auto-closes after that long.
    MavOpen {
        #[serde(default)]
        duration_ms: Option<u64>,
    },
    /// Close fill-station MAV
    MavClose,
    /// Query fill-station MAV state
    GetMavState,

    // Ball Valve Commands
    #[serde(rename = "bv_open")]
    BVOpen,
    #[serde(rename = "bv_close")]
    BVClose,
    #[serde(rename = "bv_signal")]
    BVSignal {
        state: String,
    }, // "high" or "low"
    #[serde(rename = "bv_on_off")]
    BVOnOff {
        state: String,
    }, // "high" or "low"

    /// Get state of a solenoid valve (actuation and continuity)
    GetValveState {
        /// Name of the valve ("SV1".."SV5")
        valve: String,
    },
    /// Move QD stepper a specific number of steps in a given direction
    QdMove {
        steps: u32,
        direction: bool,
    },
    /// Retract QD using preset steps (CW)
    QdRetract,
    /// Extend QD using preset steps (CCW)
    QdExtend,
    /// Query last-commanded ball valve state
    GetBallValveState,
    /// Query last-commanded QD position state
    GetQdState,

    /// Client heartbeat to indicate connection is alive
    Heartbeat,

    // FSW Umbilical Commands
    /// Send launch command to FSW
    FswLaunch,
    /// Trigger drogue deploy on FSW (test only)
    FswTriggerDrogue,
    /// Trigger main deploy on FSW (test only)
    FswTriggerMain,
    /// Open MAV on FSW
    FswOpenMav,
    /// Close MAV on FSW
    FswCloseMav,
    /// Open SV on FSW
    FswOpenSv,
    /// Close SV on FSW
    FswCloseSv,
    /// Safe all actuators on FSW
    FswSafe,
    /// Reset FRAM on FSW
    FswResetFram,
    /// Dump FRAM contents on FSW
    FswDumpFram,
    /// Wipe FRAM snapshot ring and reboot FSW
    FswWipeFramReboot,
    /// Reboot FSW
    FswReboot,
    /// Dump flash memory on FSW
    FswDumpFlash,
    /// Wipe flash memory on FSW
    FswWipeFlash,
    /// Query flash info on FSW
    FswFlashInfo,
    /// Trigger payload event N1 on FSW
    FswPayloadN1,
    /// Trigger payload event N2 on FSW
    FswPayloadN2,
    /// Trigger payload event N3 on FSW
    FswPayloadN3,
    /// Trigger payload event N4 on FSW
    FswPayloadN4,
    /// Trigger payload event A1 on FSW
    FswPayloadA1,
    /// Trigger payload event A2 on FSW
    FswPayloadA2,
    /// Trigger payload event A3 on FSW
    FswPayloadA3,
    /// Start streaming FSW telemetry to this client
    StartFswStream,
    /// Stop streaming FSW telemetry to this client
    StopFswStream,
    /// Arm the FSW key (allow Startup → Standby transition)
    FswKeyArm,
    /// Disarm the FSW key (force Standby → Startup)
    FswKeyDisarm,
    FswSetBlimsTarget {
        upwind_lat: f32,
        upwind_lon: f32,
        downwind_lat: f32,
        downwind_lon: f32,
    },
}

/// Response sent back to WebSocket clients after command execution
#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum CommandResponse {
    Success,
    Error,
    DeviceUnavailable {
        devices: Vec<String>,
    },
    HardwareAvailability {
        availability_version: u32,
        configured_devices_mask: u32,
    },
    /// ADC reading data
    AdcData {
        timestamp_ms: u64,
        valid: bool,
        adc1_valid: bool,
        adc2_valid: bool,
        valid_readings_mask: u32,
        availability_version: u32,
        configured_devices_mask: u32,
        adc1: [ChannelReading; 4],
        adc2: [ChannelReading; 4],
    },
    /// Solenoid valve state
    ValveState {
        valve: String,
        open: bool,
        continuity: bool,
    },
    /// Igniter continuity state
    IgniterContinuity {
        id: u8,
        continuity: bool,
    },
    /// FSW telemetry data from umbilical
    FswTelemetry {
        timestamp_ms: u64,
        connected: bool,
        flight_mode: String,
        telemetry: FswTelemetry,
    },
    /// Fill-station MAV state (last commanded)
    MavState {
        open: bool,
        pulse_width_us: u32,
    },
    /// Last-commanded ball valve state
    BallValveState {
        open: bool,
    },
    /// Last-commanded QD state (-1 retracted, 0 unknown, 1 extended)
    QdState {
        state: i16,
    },
}

/// Single ADC channel reading with all relevant data
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct ChannelReading {
    pub raw: i16,
    pub voltage: f32,
    pub scaled: Option<f32>, // Some channels have pressure sensor scaling
}

/// Shared ADC readings accessible across tasks
#[derive(Debug, Clone)]
pub struct AdcReadings {
    pub timestamp_ms: u64,
    pub valid: bool,
    pub adc1_valid: bool,
    pub adc2_valid: bool,
    pub adc1: [ChannelReading; 4],
    pub adc2: [ChannelReading; 4],
}

impl Default for AdcReadings {
    fn default() -> Self {
        Self {
            timestamp_ms: 0,
            valid: false,
            adc1_valid: false,
            adc2_valid: false,
            adc1: [ChannelReading {
                raw: 0,
                voltage: 0.0,
                scaled: None,
            }; 4],
            adc2: [ChannelReading {
                raw: 0,
                voltage: 0.0,
                scaled: None,
            }; 4],
        }
    }
}

/// Shared FSW telemetry readings from umbilical, accessible across tasks.
///
/// `connected` is derived from telemetry freshness: the safety monitor sets it
/// true iff `last_telem_instant` is within `TELEM_FRESHNESS_MS`. The serial
/// port being open is *not* sufficient — a hung FSW with a live USB CDC port
/// would otherwise read as connected forever.
#[derive(Debug, Clone)]
pub struct UmbilicalReadings {
    pub timestamp_ms: u64,
    pub connected: bool,
    pub telemetry: FswTelemetry,
    /// Monotonic instant of the most recent successful `$TELEM` parse.
    /// `None` means no telemetry has been received since boot/last reconnect.
    pub last_telem_instant: Option<Instant>,
}

impl Default for UmbilicalReadings {
    fn default() -> Self {
        Self {
            timestamp_ms: 0,
            connected: false,
            telemetry: FswTelemetry::default(),
            last_telem_instant: None,
        }
    }
}

#[cfg(test)]
mod availability_tests {
    use super::*;
    #[test]
    fn independent_adc_validity_maps_to_readings() {
        let mut readings = AdcReadings::default();
        readings.adc1_valid = true;
        assert_eq!(readings.valid_readings_mask(), 3);
        readings.adc1_valid = false;
        readings.adc2_valid = true;
        assert_eq!(readings.valid_readings_mask(), 4);
    }
}

impl AdcReadings {
    pub fn valid_readings_mask(&self) -> u32 {
        (if self.adc1_valid { 3 } else { 0 }) | (if self.adc2_valid { 4 } else { 0 })
    }
}
impl Command {
    pub fn required_roles(&self) -> Vec<&str> {
        match self {
            Self::Launch | Self::Ignite => vec!["ig1", "ig2"],
            Self::GetIgniterContinuity { id: 1 } => vec!["ig1"],
            Self::GetIgniterContinuity { id: 2 } => vec!["ig2"],
            Self::ActuateValve { valve, .. } | Self::GetValveState { valve } => {
                match valve.to_ascii_lowercase().as_str() {
                    "sv1" => vec!["sv1"],
                    "sv2" => vec!["sv2"],
                    "sv3" => vec!["sv3"],
                    "sv4" => vec!["sv4"],
                    "sv5" => vec!["sv5"],
                    _ => vec![],
                }
            }
            Self::MavOpen { .. } | Self::MavClose | Self::GetMavState => vec!["mav"],
            Self::BVOpen
            | Self::BVClose
            | Self::BVSignal { .. }
            | Self::BVOnOff { .. }
            | Self::GetBallValveState => vec!["ball_valve"],
            Self::QdMove { .. } | Self::QdRetract | Self::QdExtend | Self::GetQdState => {
                vec!["qd_stepper"]
            }
            _ => vec![],
        }
    }
}
