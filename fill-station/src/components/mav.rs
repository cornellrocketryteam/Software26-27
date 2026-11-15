use super::pwm::{PulseConfig, PulseOutput, PwmConnection};
use anyhow::Result;
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use tracing::{info, warn};

// Servo constants mirror the FSW MAV driver (`fsw/src/actuator.rs` `Mav`) so
// both MAVs travel the same distance. Keep the two in sync.
// Servo: ProModeler DS2685BLHV.
pub const FREQUENCY_HZ: u32 = 330;
pub const MIN_US: u32 = 800;
pub const MAX_US: u32 = 2200;
pub const OPEN_US: u32 = 1950;
pub const CLOSE_US: u32 = 883;

/// MAV (Mechanically Actuated Valve) servo driven by a configured PWM output.
pub struct Mav {
    name: String,
    pwm: PulseOutput,
    config: PulseConfig,
    state_open: AtomicBool,
    pulse_us: AtomicU32,
    /// Bumped on every open/close so a pending timed auto-close can tell
    /// whether it has been superseded.
    generation: AtomicU64,
}

#[cfg(all(test, not(target_os = "linux")))]
mod tests {
    use super::*;
    #[test]
    fn superseded_timed_close_keeps_the_latest_mav_command() {
        smol::block_on(async {
            let mav = Mav::new("23040000.pwm", 1, "test").await.unwrap();
            assert_eq!(mav.pulse_width_us(), CLOSE_US);
            let old = mav.open().await.unwrap();
            let latest = mav.open().await.unwrap();
            assert!(!mav.close_if_generation(old).await.unwrap());
            assert!(mav.is_open());
            assert_eq!(mav.pulse_width_us(), OPEN_US);
            assert!(mav.close_if_generation(latest).await.unwrap());
            assert!(!mav.is_open());
            assert_eq!(mav.pulse_width_us(), CLOSE_US);
        });
    }
}

impl Mav {
    /// Initialize the MAV on the PWM controller whose platform device name is
    /// `device_addr` (e.g. "23040000.pwm" for epwm4). The pwmchip number is
    /// assigned by probe order, so it is looked up rather than hardcoded.
    ///
    /// Exports the channel, sets the 330 Hz period, closes the valve and enables output.
    pub async fn new(device_addr: &str, channel_nr: u32, name: &str) -> Result<Self> {
        let mav = Self::with_pwm(
            &PwmConnection::Epwm {
                device: device_addr.to_owned(),
                channel: channel_nr,
            },
            name,
            PulseConfig::mav(),
        )
        .await?;
        mav.enable().await?;
        Ok(mav)
    }

    pub async fn with_pwm(
        connection: &PwmConnection,
        name: &str,
        config: PulseConfig,
    ) -> Result<Self> {
        let pwm = PulseOutput::new(connection, config).await?;
        let mav = Self {
            name: name.to_owned(),
            pwm,
            config,
            state_open: AtomicBool::new(false),
            pulse_us: AtomicU32::new(config.safe_pulse_us),
            generation: AtomicU64::new(0),
        };
        info!(
            "MAV '{}' initialized on {:?}, parked at {} us",
            name, connection, config.safe_pulse_us
        );
        Ok(mav)
    }

    pub async fn enable(&self) -> Result<()> {
        self.pwm.enable().await
    }
    pub async fn enable_native(&self) -> Result<()> {
        self.pwm.enable_native().await
    }

    /// Set pulse width in microseconds, clamped to MIN_US..MAX_US (same as FSW).
    pub async fn set_pulse_width_us(&self, us: u32) -> Result<()> {
        let clamped = us.clamp(self.config.min_pulse_us, self.config.max_pulse_us);
        if clamped != us {
            warn!(
                "MAV '{}' pulse width {} us clamped to {} us",
                self.name, us, clamped
            );
        }

        self.pwm.set_pulse_us(clamped).await?;

        self.pulse_us.store(clamped, Ordering::Relaxed);
        Ok(())
    }

    /// Open valve to OPEN_US. Returns the generation of this open, which a
    /// timed auto-close passes to `close_if_generation`.
    pub async fn open(&self) -> Result<u64> {
        self.set_pulse_width_us(OPEN_US).await?;
        self.state_open.store(true, Ordering::Relaxed);
        Ok(self.generation.fetch_add(1, Ordering::SeqCst) + 1)
    }

    /// Close valve to CLOSE_US. Cancels any pending timed auto-close.
    pub async fn close(&self) -> Result<()> {
        self.generation.fetch_add(1, Ordering::SeqCst);
        self.set_pulse_width_us(CLOSE_US).await?;
        self.state_open.store(false, Ordering::Relaxed);
        Ok(())
    }

    /// Close only if no open/close has happened since the open that returned `generation`.
    pub async fn close_if_generation(&self, generation: u64) -> Result<bool> {
        if self.generation.load(Ordering::SeqCst) != generation {
            return Ok(false);
        }
        self.close().await?;
        Ok(true)
    }

    pub fn is_open(&self) -> bool {
        self.state_open.load(Ordering::Relaxed)
    }

    /// Last commanded pulse width in microseconds.
    pub fn pulse_width_us(&self) -> u32 {
        self.pulse_us.load(Ordering::Relaxed)
    }
}
