
use embassy_rp::pwm::Pwm;
use embedded_hal::pwm::SetDutyCycle;

// Configuration depending on if ethanol or nitrous and their angle ranges may be different 
pub struct EregConfig {
    pub period_us: u16,
    pub min_pulse_us: u16,
    pub max_pulse_us: u16,
    pub min_angle_deg: f32,
    pub max_angle_deg: f32,
}

// E-REG actuator.
pub struct Ereg<'a> {
    pwm: Pwm<'a>,
    config: EregConfig,
}

impl<'a> Ereg<'a> {
    pub fn new(pwm: Pwm<'a>, config: EregConfig) -> Self {
        Self { pwm, config }
    }

    // Set a pulse width in microseconds.
    fn set_pulse_width(&mut self, pulse_us: u16) -> bool {
        let config = &self.config;

        if config.period_us == 0
            || config.min_pulse_us >= config.max_pulse_us
            || config.max_pulse_us >= config.period_us
        {
            return false;
        }

        let pulse = pulse_us.clamp(
            config.min_pulse_us,
            config.max_pulse_us,
        );

        self.pwm
            .set_duty_cycle_fraction(pulse, config.period_us)
            .is_ok()
    }

    // Question: do we want to set this as an angle or as a position like it was in the old actuator, but the equations use angles?
    pub fn set_angle_degrees(&mut self, angle_deg: f32) -> bool {
        let config = &self.config;

        if !angle_deg.is_finite()
            || !config.min_angle_deg.is_finite()
            || !config.max_angle_deg.is_finite()
            || config.min_angle_deg >= config.max_angle_deg
        {
            return false;
        }

        let angle = angle_deg.clamp(
            config.min_angle_deg,
            config.max_angle_deg,
        );

        let angle_span =
            config.max_angle_deg - config.min_angle_deg;

        let pulse_span =
            (config.max_pulse_us - config.min_pulse_us) as f32;

        let fraction =
            (angle - config.min_angle_deg) / angle_span;

        let pulse = config.min_pulse_us as f32
            + fraction * pulse_span;

        self.set_pulse_width((pulse + 0.5) as u16)
    }
}

// E-REG controller -- based on the equations from the slides 
pub struct EregController {
    kp0: f32,
    a: f32,
    theta0: f32,
    b: f32,
}
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

    pub fn command_actuator(
    &self,
    ereg: &mut Ereg,
    pressure: f32,
    pressure_error: f32,
) -> Result<f32, EregError> {
    //angle value 
    let angle = self
        .calculate_command(pressure, pressure_error)
        .ok_or(EregError::InvalidCommand)?;

    if !ereg.set_angle_degrees(angle) {
        return Err(EregError::ActuatorFailure);
    }

    Ok(angle)
}
}
