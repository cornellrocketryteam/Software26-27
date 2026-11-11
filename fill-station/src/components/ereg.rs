use anyhow::{bail, Result};
#[cfg(any(target_os = "linux", target_os = "android"))]
use anyhow::Context;
#[cfg(any(target_os = "linux", target_os = "android"))]
use std::fs;
use std::path::PathBuf;
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

/// E-REG actuator driven by a Linux sysfs PWM channel (same scheme as `Mav`).
pub struct Ereg {
    name: String,
    #[allow(dead_code)]
    pwm_path: PathBuf,
    config: EregConfig,
    pulse_us: AtomicU32,
}

impl Ereg {
    /// Initialize the E-REG on the PWM controller whose platform device name is
    /// `device_addr` (e.g. "23040000.pwm"). Exports the channel, sets the period,
    /// parks the actuator at `min_pulse_us` and enables output.
    #[cfg(any(target_os = "linux", target_os = "android"))]
    pub async fn new(device_addr: &str, channel_nr: u32, name: &str, config: EregConfig) -> Result<Self> {
        config.validate()?;

        let chip_path = super::mav::find_pwmchip(device_addr)?;
        let pwm_path = chip_path.join(format!("pwm{}", channel_nr));

        if !pwm_path.exists() {
            info!("Exporting PWM {} channel {}", chip_path.display(), channel_nr);
            let export = chip_path.join("export");
            smol::unblock(move || fs::write(export, channel_nr.to_string()))
                .await
                .context("Failed to export PWM channel")?;
        }

        // The sysfs entry can take a moment to appear after export
        if !pwm_path.exists() {
            smol::Timer::after(std::time::Duration::from_millis(100)).await;
        }

        let ereg = Self {
            name: name.to_string(),
            pwm_path,
            config,
            pulse_us: AtomicU32::new(config.min_pulse_us),
        };

        // Linux rejects duty_cycle > period, so set period before duty and
        // keep output disabled while reconfiguring.
        ereg.write_file("enable", "0").await.context("Failed to disable PWM")?;
        let period_ns = config.period_us * 1000;
        ereg.write_file("period", &period_ns.to_string()).await.context("Failed to set period")?;
        ereg.set_pulse_width(config.min_pulse_us).await?;
        ereg.write_file("enable", "1").await.context("Failed to enable PWM")?;

        info!("E-REG '{}' initialized on {} (period {} us, parked at {} us)",
              name, ereg.pwm_path.display(), config.period_us, config.min_pulse_us);

        Ok(ereg)
    }

    #[cfg(not(any(target_os = "linux", target_os = "android")))]
    pub async fn new(device_addr: &str, channel_nr: u32, name: &str, config: EregConfig) -> Result<Self> {
        config.validate()?;
        info!("E-REG '{}' mocked for non-Linux platform ({} ch {}, period {} us)",
              name, device_addr, channel_nr, config.period_us);
        Ok(Self {
            name: name.to_string(),
            pwm_path: PathBuf::from("/tmp/mock_ereg"),
            config,
            pulse_us: AtomicU32::new(config.min_pulse_us),
        })
    }

    /// Set a pulse width in microseconds, clamped to the configured range.
    async fn set_pulse_width(&self, pulse_us: u32) -> Result<()> {
        let pulse = pulse_us.clamp(self.config.min_pulse_us, self.config.max_pulse_us);

        #[cfg(any(target_os = "linux", target_os = "android"))]
        self.write_file("duty_cycle", &(pulse * 1000).to_string())
            .await
            .context("Failed to set duty cycle")?;

        #[cfg(not(any(target_os = "linux", target_os = "android")))]
        info!("[Mock] E-REG '{}' set to {} us", self.name, pulse);

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

    #[cfg(any(target_os = "linux", target_os = "android"))]
    async fn write_file(&self, file: &str, content: &str) -> Result<()> {
        let path = self.pwm_path.join(file);
        let content = content.to_string();
        smol::unblock(move || fs::write(path, content)).await?;
        Ok(())
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
