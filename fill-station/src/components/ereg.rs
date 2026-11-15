use anyhow::{bail, Result};
use super::pwm::{PulseConfig, PulseOutput, PwmConnection};
use std::sync::atomic::{AtomicU32, Ordering};
use tracing::info;

// Configuration depending on if ethanol or nitrous and their angle ranges may be different
#[derive(Debug, Clone, Copy)]
pub struct EregConfig {
    pub period_us: u32,
    pub min_pulse_us: u32,
    pub max_pulse_us: u32,
    pub min_angle_deg: f32,
    pub max_angle_deg: f32,
}

impl EregConfig {
    /// Servo timing shared with the MAV (330 Hz, 800-2200 us) over 0-90 degrees.
    /// Used for E-REGs declared in the hardware profile.
    // TODO: confirm the E-REG angle range that maps onto that pulse range.
    pub const DEFAULT: Self = Self {
        period_us: 1_000_000 / super::mav::FREQUENCY_HZ,
        min_pulse_us: super::mav::MIN_US,
        max_pulse_us: super::mav::MAX_US,
        min_angle_deg: 0.0,
        max_angle_deg: 90.0,
    };

    fn validate(&self) -> Result<()> {
        if self.period_us == 0
            || self.min_pulse_us >= self.max_pulse_us
            || self.max_pulse_us >= self.period_us
        {
            bail!("invalid E-REG pulse config: {:?}", self);
        }
        if !self.min_angle_deg.is_finite()
            || !self.max_angle_deg.is_finite()
            || self.min_angle_deg >= self.max_angle_deg
        {
            bail!("invalid E-REG angle config: {:?}", self);
        }
        Ok(())
    }
}

/// E-REG actuator driven by a configured PWM output (same scheme as `Mav`).
pub struct Ereg {
    name: String,
    pwm: PulseOutput,
    safe_pulse_us: u32,
    config: EregConfig,
    pulse_us: AtomicU32,
}

impl Ereg {
    /// Initialize the E-REG on the PWM controller whose platform device name is
    /// `device_addr` (e.g. "23040000.pwm"). Exports the channel, sets the period,
    /// parks the actuator at `min_pulse_us` and enables output.
    pub async fn new(device_addr: &str, channel_nr: u32, name: &str, config: EregConfig) -> Result<Self> {
        let timing = PulseConfig { period_ns: config.period_us * 1000,
            min_pulse_us: config.min_pulse_us, max_pulse_us: config.max_pulse_us,
            safe_pulse_us: config.min_pulse_us };
        let ereg = Self::with_pwm(&PwmConnection::Epwm { device: device_addr.to_owned(), channel: channel_nr }, name, config, timing).await?;
        ereg.enable().await?;
        Ok(ereg)
    }

    pub async fn with_pwm(connection: &PwmConnection, name: &str, config: EregConfig, timing: PulseConfig) -> Result<Self> {
        config.validate()?;
        let pwm = PulseOutput::new(connection, timing).await?;
        info!("E-REG '{}' initialized on {:?}, parked at {} us", name, connection, timing.safe_pulse_us);
        Ok(Self { name: name.to_owned(), pwm, config, safe_pulse_us: timing.safe_pulse_us,
            pulse_us: AtomicU32::new(timing.safe_pulse_us) })
    }

    pub async fn enable(&self) -> Result<()> { self.pwm.enable().await }
    pub async fn enable_native(&self) -> Result<()> { self.pwm.enable_native().await }

    /// Park at the configured safe pulse without changing the angle calibration.
    pub async fn park_safe(&self) -> Result<()> {
        self.set_pulse_width(self.safe_pulse_us).await
    }

    /// Set a pulse width in microseconds, clamped to the configured range.
    async fn set_pulse_width(&self, pulse_us: u32) -> Result<()> {
        let pulse = pulse_us.clamp(self.config.min_pulse_us, self.config.max_pulse_us);

        self.pwm.set_pulse_us(pulse).await?;

        self.pulse_us.store(pulse, Ordering::Relaxed);
        Ok(())
    }

    // Question: do we want to set this as an angle or as a position like it was in the old actuator, but the equations use angles?
    pub async fn set_angle_degrees(&self, angle_deg: f32) -> Result<()> {
        if !angle_deg.is_finite() {
            bail!("E-REG '{}' angle is not finite: {}", self.name, angle_deg);
        }
        let config = &self.config;

        let angle = angle_deg.clamp(config.min_angle_deg, config.max_angle_deg);
        let fraction = (angle - config.min_angle_deg) / (config.max_angle_deg - config.min_angle_deg);
        let pulse_span = (config.max_pulse_us - config.min_pulse_us) as f32;
        let pulse = config.min_pulse_us as f32 + fraction * pulse_span;

        self.set_pulse_width((pulse + 0.5) as u32).await
    }

    /// Last commanded pulse width in microseconds.
    pub fn pulse_width_us(&self) -> u32 {
        self.pulse_us.load(Ordering::Relaxed)
    }

}

// E-REG controller -- based on the equations from the slides 
pub struct EregController {
    kp0: f32,
    a: f32,
    theta0: f32,
    b: f32,
}
#[derive(Debug)]
pub enum EregError {
    InvalidCommand,
    ActuatorFailure,
}

impl EregController {
    pub fn new(kp0: f32, a: f32, theta0: f32, b: f32) -> Self {
        Self { kp0, a, theta0, b }
    }

    pub fn calculate_gain(&self, pressure: f32) -> Option<f32> {
        if !pressure.is_finite() || pressure <= 0.0 {
            return None;
        }

        let kp = self.kp0 + self.a / pressure;

        if kp.is_finite() {
            Some(kp)
        } else {
            None
        }
    }

    pub fn calculate_feedforward(
        &self,
        pressure: f32,
    ) -> Option<f32> {
        if !pressure.is_finite() || pressure <= 0.0 {
            return None;
        }

        let feedforward = self.theta0 + self.b / pressure;

        if feedforward.is_finite() {
            Some(feedforward)
        } else {
            None
        }
    }

    pub fn calculate_command(
        &self,
        pressure: f32,
        pressure_error: f32,
    ) -> Option<f32> {
        if !pressure_error.is_finite() {
            return None;
        }

        let kp = self.calculate_gain(pressure)?;
        let feedforward = self.calculate_feedforward(pressure)?;

        let command = kp * pressure_error + feedforward;

        if command.is_finite() {
            Some(command)
        } else {
            None
        }
    }

    pub async fn command_actuator(
        &self,
        ereg: &Ereg,
        pressure: f32,
        pressure_error: f32,
    ) -> Result<f32, EregError> {
        // angle value
        let angle = self
            .calculate_command(pressure, pressure_error)
            .ok_or(EregError::InvalidCommand)?;

        ereg.set_angle_degrees(angle)
            .await
            .map_err(|_| EregError::ActuatorFailure)?;

        Ok(angle)
    }
}

#[cfg(all(test, not(target_os = "linux")))]
mod tests {
    use super::*;
    #[test]
    fn angle_mapping_and_shutdown_use_the_configured_pulses() {
        smol::block_on(async {
            let timing = PulseConfig { period_ns: 20_000_000, min_pulse_us: 900,
                max_pulse_us: 2100, safe_pulse_us: 1000 };
            let config = EregConfig { period_us: 20_000, min_pulse_us: 900,
                max_pulse_us: 2100, ..EregConfig::DEFAULT };
            let ereg = Ereg::with_pwm(&PwmConnection::Pru { subsystem: 0, core: 1, bit: 12 },
                "test", config, timing).await.unwrap();
            assert_eq!(ereg.pulse_width_us(), 1000);
            ereg.set_angle_degrees(-10.0).await.unwrap();
            assert_eq!(ereg.pulse_width_us(), 900);
            ereg.set_angle_degrees(45.0).await.unwrap();
            assert_eq!(ereg.pulse_width_us(), 1500);
            ereg.set_angle_degrees(100.0).await.unwrap();
            assert_eq!(ereg.pulse_width_us(), 2100);
            assert!(ereg.set_angle_degrees(f32::NAN).await.is_err());
            assert_eq!(ereg.pulse_width_us(), 2100);
            ereg.park_safe().await.unwrap();
            assert_eq!(ereg.pulse_width_us(), 1000);
        });
    }
}
