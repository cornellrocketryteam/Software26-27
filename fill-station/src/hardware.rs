use crate::components::{
    ads1015::Ads1015,
    ads7128::Ads7128,
    ball_valve::BallValve,
    ereg::{Ereg, EregConfig},
    igniter::Igniter,
    mav::Mav,
    pwm::PulseConfig,
    quick_disconnect::{QuickDisconnect, LinePull as QdLinePull},
    solenoid_valve::{LinePull, SolenoidValve},
};
use anyhow::{Context, Result, bail};
use crate::operating_runtime::{RoutingMode, OutputDiagnostic};
#[cfg(any(target_os = "linux", target_os = "android"))]
use async_gpiod::Chip;
use serde::Deserialize;
use std::collections::BTreeMap;
include!(concat!(env!("OUT_DIR"), "/hardware_config.rs"));

// Availability bit 11 was the stepper and is now reserved. Bits 0..10 never move.
pub const DEVICE_ROLES: [&str; 11] = [
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
];

#[derive(Debug, Deserialize)]
pub struct HardwareConfig {
    pub version: u32,
    pub profile: String,
    #[serde(default)]
    pub operating_profile: Option<String>,
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
pub use crate::components::pwm::PwmConnection;
impl HardwareConfig {
    pub fn parse(json: &str) -> Result<Self> {
        let config: Self = serde_json::from_str(json)?;
        if config.version != 1 {
            bail!("unsupported hardware configuration version");
        }
        let mode = RoutingMode::parse(config.operating_profile.as_deref())
            .context("unknown operating-profile runtime selector")?;
        if mode != RoutingMode::Legacy && config.profile != "hybrid" {
            bail!("operating profile requires Hybrid physical wiring");
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
    pub routing_mode: RoutingMode,
    pub configured_devices_mask: u32,
    roles: BTreeMap<String, String>,
    pub igniters: BTreeMap<String, Igniter>,
    pub solenoids: BTreeMap<String, SolenoidValve>,
    pub adcs: BTreeMap<String, Ads1015>,
    pub ads7128s: BTreeMap<String, Ads7128>,
    pub mavs: BTreeMap<String, Mav>,
    pub eregs: BTreeMap<String, Ereg>,
    pub ball_valves: BTreeMap<String, BallValve>,
    pub quick_disconnects: BTreeMap<String, QuickDisconnect>,
}
impl Hardware {
    pub async fn new() -> Result<Self> {
        Self::from_config(HardwareConfig::parse(HARDWARE_CONFIG_JSON)?).await
    }
    pub async fn from_config(config: HardwareConfig) -> Result<Self> {
        let routing_mode = RoutingMode::parse(config.operating_profile.as_deref())
            .context("unknown operating-profile runtime selector")?;
        if routing_mode != RoutingMode::Legacy && config.profile != "hybrid" {
            bail!("operating profile requires Hybrid physical wiring");
        }
        let mut hw = Self {
            routing_mode,
            configured_devices_mask: config.configured_devices_mask,
            ..Self::default()
        };
        // Enforce fixed release polarity before requesting any GPIO, even for a
        // directly supplied runtime config that bypassed the profile compiler.
        for d in &config.devices {
            if d.kind == "quick_disconnect" {
                if d.role.as_deref().is_some_and(|r| r != "sv5") {
                    bail!("{}: quick disconnect may bind only sv5 or no role", d.id);
                }
                if d.settings.get("valve_type").is_some_and(|v| v.as_str() != Some("normally_closed")) {
                    bail!("{}: quick disconnect must be normally_closed (active-high release)", d.id);
                }
            }
        }
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
                "ads7128" => {
                    hw.ads7128s.insert(
                        d.id.clone(),
                        Ads7128::new(
                            d.bus.as_deref().context("missing ADC bus")?,
                            d.address.context("missing ADC address")?,
                        )?,
                    );
                }
                "mav_servo" => {
                    let pwm = d.pwm.as_ref().context("missing PWM")?;
                    hw.mavs.insert(
                        d.id.clone(),
                        Mav::with_pwm(pwm, &d.id, PulseConfig::from_settings(&d.settings, PulseConfig::mav())?).await?,
                    );
                }
                "ereg" => {
                    let pwm = d.pwm.as_ref().context("missing PWM")?;
                    hw.eregs.insert(
                        d.id.clone(),
                        {
                            let defaults = EregConfig::DEFAULT;
                            let timing = PulseConfig::from_settings(&d.settings, PulseConfig {
                                period_ns: defaults.period_us * 1000,
                                min_pulse_us: defaults.min_pulse_us, max_pulse_us: defaults.max_pulse_us,
                                safe_pulse_us: defaults.min_pulse_us,
                            })?;
                            let config = EregConfig { period_us: timing.period_ns / 1000,
                                min_pulse_us: timing.min_pulse_us, max_pulse_us: timing.max_pulse_us, ..defaults };
                            Ereg::with_pwm(pwm, &d.id, config, timing).await?
                        },
                    );
                }
                "ball_valve" => {
                    let (a, b) = connection("on_off")?;
                    let (c, e) = connection("signal")?;
                    hw.ball_valves
                        .insert(d.id.clone(), BallValve::new(a, b, c, e, &d.id).await?);
                }
                "quick_disconnect" => {
                    let (a, b) = connection("control")?;
                    let (c, e) = connection("sense")?;
                    hw.quick_disconnects.insert(d.id.clone(),
                        QuickDisconnect::new(a, b, c, e, QdLinePull::NormallyClosed).await?);
                }
                other => bail!("unsupported device type {}", other),
            }
            if let Some(role) = d.role {
                hw.roles.insert(role, d.id);
            }
        }
        // Native channels enable individually; all PRU channels arm together below.
        for d in hw.mavs.values() { d.enable_native().await?; }
        for d in hw.eregs.values() { d.enable_native().await?; }
        crate::components::pwm::arm_pru_outputs().await?;
        Ok(hw)
    }
    /// Read-only observations. Output is driver command memory, not physical proof.
    pub async fn output_diagnostics(&self) -> [OutputDiagnostic;3] {
        let mut result=[OutputDiagnostic::default();3];
        for (i,role) in ["ig1","ig2"].iter().enumerate() {
            if let Some(ig)=self.igniter(role) {
                result[i]=OutputDiagnostic {output:Some(ig.is_igniting().await),continuity:ig.read_continuity().await.ok()};
            }
        }
        if let Some(qd)=self.quick_disconnect("sv5") {
            result[2]=OutputDiagnostic {output:qd.is_open().await.ok(),continuity:qd.check_continuity().await.ok()};
        }
        result
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
        let id = self.roles.get(role)?;
        self.solenoids.get(id).or_else(|| self.quick_disconnects.get(id))
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
    pub fn quick_disconnect(&self, role: &str) -> Option<&QuickDisconnect> {
        self.quick_disconnects.get(self.roles.get(role)?)
    }
    pub async fn shutdown(&self) {
        for (id, d) in &self.igniters {
            if let Err(e) = d.set_actuated(false).await {
                tracing::error!("Shutdown {}: {}", id, e);
            }
        }
        for (id, d) in self.solenoids.iter().chain(self.quick_disconnects.iter()) {
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
        for (id, d) in &self.eregs {
            if let Err(e) = d.park_safe().await {
                tracing::error!("Shutdown {}: {}", id, e);
            }
        }

    }
}
#[cfg(test)]
mod configuration_tests {
    #[cfg(not(any(target_os = "linux", target_os = "android")))]
    #[test]
    fn qd_is_distinct_but_reachable_by_sv5_and_shutdown_deenergizes() {
        smol::block_on(async {
            let config=HardwareConfig::parse(r#"{"version":1,"profile":"hybrid","configured_devices_mask":256,"devices":[{"id":"qd","type":"quick_disconnect","role":"sv5","connections":{"control":{"chip":"gpiochip2","line":48},"sense":{"chip":"gpiochip2","line":46}},"settings":{"valve_type":"normally_closed"}}]}"#).unwrap();
            let hw=Hardware::from_config(config).await.unwrap();
            assert!(!hw.solenoids.contains_key("qd"));
            assert!(hw.quick_disconnects.contains_key("qd"));
            let qd=hw.quick_disconnect("sv5").unwrap();
            assert!(!qd.is_open().await.unwrap());
            hw.solenoid("sv5").unwrap().set_open(true).await.unwrap();
            assert!(qd.is_open().await.unwrap());
            hw.shutdown().await;
            assert!(!qd.is_open().await.unwrap());
        });
    }

    #[test]
    fn runtime_rejects_qd_polarity_and_wrong_role_before_gpio_access() {
        for (role,pull) in [("sv5","normally_open"),("sv1","normally_closed")] {
            let value=serde_json::json!({"version":1,"profile":"hybrid","configured_devices_mask":256,
                "devices":[{"id":"qd","type":"quick_disconnect","role":role,"connections":{},"settings":{"valve_type":pull}}]});
            let config=HardwareConfig::parse(&value.to_string()).unwrap();
            let error=smol::block_on(Hardware::from_config(config)).err().expect("invalid QD config accepted");
            assert!(error.to_string().contains("quick disconnect"),"{error}");
        }
    }

    use super::*;
    #[test]
    fn pru_pwm_descriptor_parses_without_epwm_fields() {
        let pwm: PwmConnection = serde_json::from_str(r#"{"backend":"pru","subsystem":0,"core":1,"bit":12}"#).unwrap();
        assert!(matches!(pwm, PwmConnection::Pru { subsystem: 0, core: 1, bit: 12 }));
    }

    #[test]
    fn legacy_pwm_descriptor_keeps_epwm_backend() {
        let pwm: PwmConnection = serde_json::from_str(r#"{"device":"23040000.pwm","channel":1}"#).unwrap();
        assert!(matches!(pwm, PwmConnection::Epwm { channel: 1, .. }));
    }

    #[test]
    fn unsupported_pwm_backend_is_rejected() {
        assert!(serde_json::from_str::<PwmConnection>(r#"{"backend":"unknown","device":"23040000.pwm","channel":1}"#).is_err());
    }
    #[cfg(not(any(target_os = "linux", target_os = "android")))]
    #[test]
    fn selectable_ads7128_initializes_without_claiming_telemetry_roles() {
        smol::block_on(async {
            let config = HardwareConfig::parse(r#"{"version":1,"profile":"liquid","configured_devices_mask":0,"devices":[{"id":"extra_adc","type":"ads7128","role":null,"connections":{},"settings":{},"bus":"/dev/i2c-0","address":16}]}"#).unwrap();
            let hw = Hardware::from_config(config).await.unwrap();
            assert_eq!(hw.ads7128s.len(), 1);
            assert_eq!(hw.ads7128s["extra_adc"].address(), 0x10);
            assert!(hw.adcs.is_empty());
            assert!(!hw.has_role("adc1"));
            assert!(!hw.has_role("adc2"));
            assert_eq!(hw.configured_devices_mask, 0);
        });
    }

    #[test]
    fn ads7128_requires_bus_and_address() {
        for fields in [r#", "address":16"#, r#", "bus":"/dev/i2c-0""#] {
            let json = format!(r#"{{"version":1,"profile":"liquid","configured_devices_mask":0,"devices":[{{"id":"extra_adc","type":"ads7128","role":null,"connections":{{}},"settings":{{}}{fields}}}]}}"#);
            let error = smol::block_on(Hardware::from_config(HardwareConfig::parse(&json).unwrap()))
                .err().expect("incomplete ADC config must fail");
            assert!(error.to_string().contains("missing ADC"), "{error}");
        }
    }
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
            {
                match hw.routing_mode {
                    RoutingMode::Legacy => {
                        assert!(hw.missing_roles(&DEVICE_ROLES).is_empty());
                        assert_eq!(hw.configured_devices_mask, 2047);
                        assert_eq!(hw.solenoids.len(), 4);
                    }
                    RoutingMode::Hybrid => {
                        assert_eq!(hw.configured_devices_mask, 1311);
                        assert_eq!(hw.solenoids.len(), 1);
                        assert!(!hw.has_role("mav"));
                    }
                    RoutingMode::HybridTest => {
                        assert_eq!(hw.configured_devices_mask, 1855);
                        assert_eq!(hw.solenoids.len(), 2);
                        assert!(hw.has_role("mav"));
                    }
                }
                assert_eq!(hw.adcs.len(), 2);
                assert_eq!(hw.quick_disconnects.len(), 1);
                assert!(hw.quick_disconnect("sv5").is_some());
            }
            // Liquid binds only igniters and SV1-SV5; SV6, the QDs, the ball
            // valve and the E-REG initialize without application roles.
            #[cfg(feature = "liquid")]
            {
                assert_eq!(
                    hw.missing_roles(&DEVICE_ROLES),
                    vec!["adc1", "adc2", "mav", "ball_valve"]
                );
                assert_eq!(hw.configured_devices_mask, 499);
                assert_eq!(hw.adcs.len(), 0);
                assert_eq!(hw.solenoids.len(), 8);
                assert_eq!(hw.ball_valves.len(), 1);
                assert_eq!(hw.eregs.len(), HardwareConfig::parse(HARDWARE_CONFIG_JSON).unwrap().devices.iter().filter(|d| d.kind == "ereg").count());
            }
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
