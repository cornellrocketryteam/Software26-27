use crate::components::{
    ads1015::Ads1015,
    ball_valve::BallValve,
    igniter::Igniter,
    mav::Mav,
    qd_stepper::QdStepper,
    solenoid_valve::{LinePull, SolenoidValve},
};
use anyhow::{Context, Result, bail};
#[cfg(any(target_os = "linux", target_os = "android"))]
use async_gpiod::Chip;
use serde::Deserialize;
use std::collections::BTreeMap;
include!(concat!(env!("OUT_DIR"), "/hardware_config.rs"));

pub const DEVICE_ROLES: [&str; 12] = [
    "ig1",
    "ig2",
    "adc1",
    "adc2",
    "sv1",
    "sv2",
    "sv3",
    "sv4",
    "sv5",
    "mav",
    "ball_valve",
    "qd_stepper",
];

#[derive(Debug, Deserialize)]
pub struct HardwareConfig {
    pub version: u32,
    pub profile: String,
    pub configured_devices_mask: u32,
    pub devices: Vec<DeviceConfig>,
}
#[derive(Debug, Deserialize)]
pub struct DeviceConfig {
    pub id: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub role: Option<String>,
    #[serde(default)]
    pub connections: BTreeMap<String, GpioConnection>,
    #[serde(default)]
    pub settings: BTreeMap<String, serde_json::Value>,
    pub bus: Option<String>,
    pub address: Option<u16>,
    pub pwm: Option<PwmConnection>,
}
#[derive(Debug, Deserialize)]
pub struct GpioConnection {
    pub chip: String,
    pub line: u32,
}
#[derive(Debug, Deserialize)]
pub struct PwmConnection {
    pub device: String,
    pub channel: u32,
}
impl HardwareConfig {
    pub fn parse(json: &str) -> Result<Self> {
        let config: Self = serde_json::from_str(json)?;
        if config.version != 1 {
            bail!("unsupported hardware configuration version");
        }
        Ok(config)
    }
    pub fn missing_roles(&self, required: &[&str]) -> Vec<String> {
        required
            .iter()
            .filter(|role| {
                !self
                    .devices
                    .iter()
                    .any(|d| d.role.as_deref() == Some(**role))
            })
            .map(|s| (*s).to_owned())
            .collect()
    }
}

#[derive(Default)]
pub struct Hardware {
    pub configured_devices_mask: u32,
    roles: BTreeMap<String, String>,
    pub igniters: BTreeMap<String, Igniter>,
    pub solenoids: BTreeMap<String, SolenoidValve>,
    pub adcs: BTreeMap<String, Ads1015>,
    pub mavs: BTreeMap<String, Mav>,
    pub ball_valves: BTreeMap<String, BallValve>,
    pub steppers: BTreeMap<String, QdStepper>,
}
impl Hardware {
    pub async fn new() -> Result<Self> {
        Self::from_config(HardwareConfig::parse(HARDWARE_CONFIG_JSON)?).await
    }
    pub async fn from_config(config: HardwareConfig) -> Result<Self> {
        let mut hw = Self {
            configured_devices_mask: config.configured_devices_mask,
            ..Self::default()
        };
        #[cfg(any(target_os = "linux", target_os = "android"))]
        let mut chips = BTreeMap::new();
        #[cfg(any(target_os = "linux", target_os = "android"))]
        for d in &config.devices {
            for pin in d.connections.values() {
                if !chips.contains_key(&pin.chip) {
                    chips.insert(pin.chip.clone(), Chip::new(&pin.chip).await?);
                }
            }
        }
        for d in config.devices {
            let connection = |port: &str| -> Result<_> {
                let pin = d
                    .connections
                    .get(port)
                    .with_context(|| format!("{} lacks {}", d.id, port))?;
                #[cfg(any(target_os = "linux", target_os = "android"))]
                {
                    Ok((&chips[&pin.chip], pin.line))
                }
                #[cfg(not(any(target_os = "linux", target_os = "android")))]
                {
                    Ok((&(), pin.line))
                }
            };
            match d.kind.as_str() {
                "igniter" => {
                    let (a, b) = connection("continuity")?;
                    let (c, e) = connection("signal")?;
                    hw.igniters
                        .insert(d.id.clone(), Igniter::new(a, b, c, e).await?);
                }
                "solenoid_valve" => {
                    let (a, b) = connection("control")?;
                    let (c, e) = connection("sense")?;
                    let pull = if d.settings.get("valve_type").and_then(|v| v.as_str())
                        == Some("normally_open")
                    {
                        LinePull::NormallyOpen
                    } else {
                        LinePull::NormallyClosed
                    };
                    hw.solenoids
                        .insert(d.id.clone(), SolenoidValve::new(a, b, c, e, pull).await?);
                }
                "ads1015" => {
                    hw.adcs.insert(
                        d.id.clone(),
                        Ads1015::new(
                            d.bus.as_deref().context("missing ADC bus")?,
                            d.address.context("missing ADC address")?,
                        )?,
                    );
                }
                "mav_servo" => {
                    let pwm = d.pwm.as_ref().context("missing PWM")?;
                    hw.mavs.insert(
                        d.id.clone(),
                        Mav::new(&pwm.device, pwm.channel, &d.id).await?,
                    );
                }
                "ball_valve" => {
                    let (a, b) = connection("on_off")?;
                    let (c, e) = connection("signal")?;
                    hw.ball_valves
                        .insert(d.id.clone(), BallValve::new(a, b, c, e, &d.id).await?);
                }
                "qd_stepper" => {
                    let (a, b) = connection("step")?;
                    let (c, e) = connection("direction")?;
                    let (f, g) = connection("enable")?;
                    hw.steppers
                        .insert(d.id.clone(), QdStepper::new(a, b, c, e, f, g, &d.id).await?);
                }
                other => bail!("unsupported device type {}", other),
            }
            if let Some(role) = d.role {
                hw.roles.insert(role, d.id);
            }
        }
        Ok(hw)
    }
    pub fn has_role(&self, role: &str) -> bool {
        self.roles.contains_key(role)
    }
    pub fn missing_roles(&self, roles: &[&str]) -> Vec<String> {
        roles
            .iter()
            .filter(|r| !self.has_role(r))
            .map(|r| (*r).to_owned())
            .collect()
    }
    pub fn igniter(&self, role: &str) -> Option<&Igniter> {
        self.igniters.get(self.roles.get(role)?)
    }
    pub fn solenoid(&self, role: &str) -> Option<&SolenoidValve> {
        self.solenoids.get(self.roles.get(role)?)
    }
    pub fn adc_mut(&mut self, role: &str) -> Option<&mut Ads1015> {
        self.adcs.get_mut(self.roles.get(role)?)
    }
    pub fn mav(&self) -> Option<&Mav> {
        self.mavs.get(self.roles.get("mav")?)
    }
    pub fn ball_valve(&self) -> Option<&BallValve> {
        self.ball_valves.get(self.roles.get("ball_valve")?)
    }
    pub fn qd_stepper(&self) -> Option<&QdStepper> {
        self.steppers.get(self.roles.get("qd_stepper")?)
    }
    pub async fn shutdown(&self) {
        for (id, d) in &self.igniters {
            if let Err(e) = d.set_actuated(false).await {
                tracing::error!("Shutdown {}: {}", id, e);
            }
        }
        for (id, d) in &self.solenoids {
            if let Err(e) = d.set_open(false).await {
                tracing::error!("Shutdown {}: {}", id, e);
            }
        }
        for (id, d) in &self.ball_valves {
            if let Err(e) = d.close_sequence().await {
                tracing::error!("Shutdown {}: {}", id, e);
            }
        }
        for (id, d) in &self.mavs {
            if let Err(e) = d.close().await {
                tracing::error!("Shutdown {}: {}", id, e);
            }
        }
        for (id, d) in &self.steppers {
            if let Err(e) = d.disable().await {
                tracing::error!("Shutdown {}: {}", id, e);
            }
        }
    }
}
#[cfg(test)]
mod configuration_tests {
    use super::*;
    #[test]
    fn configured_roles_do_not_include_unbound_extra_instances() {
        let config = HardwareConfig::parse(r#"{"version":1,"profile":"liquid","configured_devices_mask":1,"devices":[{"id":"firing","type":"igniter","role":"ig1","connections":{},"settings":{}},{"id":"extra","type":"igniter","role":null,"connections":{},"settings":{}}]}"#).unwrap();
        assert_eq!(config.missing_roles(&["ig1", "ig2"]), vec!["ig2"]);
        assert_eq!(config.configured_devices_mask, 1);
    }
    #[cfg(not(any(target_os = "linux", target_os = "android")))]
    #[test]
    fn extra_actuators_initialize_and_participate_in_shutdown() {
        smol::block_on(async {
            let config=HardwareConfig::parse(r#"{"version":1,"profile":"liquid","configured_devices_mask":0,"devices":[{"id":"spare_igniter","type":"igniter","role":null,"connections":{"continuity":{"chip":"gpiochip1","line":1},"signal":{"chip":"gpiochip1","line":2}},"settings":{}},{"id":"spare_valve","type":"solenoid_valve","role":null,"connections":{"control":{"chip":"gpiochip1","line":3},"sense":{"chip":"gpiochip1","line":4}},"settings":{"valve_type":"normally_open"}}]}"#).unwrap();
            let hw = Hardware::from_config(config).await.unwrap();
            assert!(!hw.has_role("ig1"));
            hw.igniters["spare_igniter"]
                .set_actuated(true)
                .await
                .unwrap();
            hw.solenoids["spare_valve"].set_open(true).await.unwrap();
            hw.shutdown().await;
            assert!(!hw.igniters["spare_igniter"].is_igniting().await);
            assert!(!hw.solenoids["spare_valve"].is_open().await.unwrap());
        });
    }
    #[cfg(all(
        not(any(target_os = "linux", target_os = "android")),
        any(feature = "liquid", feature = "hybrid")
    ))]
    #[test]
    fn selected_default_profile_initializes_configured_roles() {
        smol::block_on(async {
            let hw = Hardware::new().await.unwrap();
            #[cfg(feature = "hybrid")]
            { assert!(hw.missing_roles(&DEVICE_ROLES).is_empty()); assert_eq!(hw.configured_devices_mask, 4095); }
            #[cfg(feature = "liquid")]
            { assert_eq!(hw.missing_roles(&DEVICE_ROLES), vec!["qd_stepper"]); assert_eq!(hw.configured_devices_mask, 2047); }
            assert_eq!(hw.adcs.len(), 2);
            assert_eq!(hw.solenoids.len(), 5);
            hw.shutdown().await;
        });
    }
    #[test]
    fn enabled_initialization_failure_is_returned() {
        smol::block_on(async {
            let config=HardwareConfig::parse(r#"{"version":1,"profile":"liquid","configured_devices_mask":1,"devices":[{"id":"broken_igniter","type":"igniter","role":"ig1","connections":{},"settings":{}}]}"#).unwrap();
            assert!(Hardware::from_config(config).await.is_err());
        });
    }

    #[test]
    fn disabled_launch_dependencies_fail_before_any_effect() {
        let config = HardwareConfig::parse(
            r#"{"version":1,"profile":"none","configured_devices_mask":0,"devices":[]}"#,
        )
        .unwrap();
        assert_eq!(config.missing_roles(&["ig1", "ig2"]), vec!["ig1", "ig2"]);
    }
}
