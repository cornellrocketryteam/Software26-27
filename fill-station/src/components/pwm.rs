//! Pulse outputs shared by the native ePWM and PRU backends.
use anyhow::{Context, Result, bail};
use serde::{Deserialize, Deserializer};
use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PwmConnection {
    Epwm { device: String, channel: u32 },
    Pru { subsystem: u32, core: u32, bit: u32 },
}
impl<'de> Deserialize<'de> for PwmConnection {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Descriptor {
            backend: Option<String>,
            device: Option<String>,
            channel: Option<u32>,
            subsystem: Option<u32>,
            core: Option<u32>,
            bit: Option<u32>,
        }
        let d = Descriptor::deserialize(deserializer)?;
        use serde::de::Error;
        match d.backend.as_deref().unwrap_or("epwm") {
            "epwm" if d.subsystem.is_none() && d.core.is_none() && d.bit.is_none() => {
                Ok(Self::Epwm {
                    device: d
                        .device
                        .ok_or_else(|| D::Error::custom("missing ePWM device"))?,
                    channel: d
                        .channel
                        .ok_or_else(|| D::Error::custom("missing ePWM channel"))?,
                })
            }
            "pru" if d.device.is_none() && d.channel.is_none() => {
                let subsystem = d
                    .subsystem
                    .ok_or_else(|| D::Error::custom("missing PRU subsystem"))?;
                let core = d.core.ok_or_else(|| D::Error::custom("missing PRU core"))?;
                let bit = d
                    .bit
                    .ok_or_else(|| D::Error::custom("missing PRU output bit"))?;
                if subsystem != 0 || core > 1 || bit > 19 {
                    return Err(D::Error::custom("unsupported PRU output"));
                }
                Ok(Self::Pru {
                    subsystem,
                    core,
                    bit,
                })
            }
            _ => Err(D::Error::custom(
                "invalid PWM backend or mixed descriptor fields",
            )),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct PulseConfig {
    pub period_ns: u32,
    pub min_pulse_us: u32,
    pub max_pulse_us: u32,
    pub safe_pulse_us: u32,
}
impl PulseConfig {
    pub const fn mav() -> Self {
        Self {
            period_ns: 1_000_000_000 / super::mav::FREQUENCY_HZ,
            min_pulse_us: super::mav::MIN_US,
            max_pulse_us: super::mav::MAX_US,
            safe_pulse_us: super::mav::CLOSE_US,
        }
    }
    pub fn validate(self) -> Result<()> {
        if !(2_000_000..=50_000_000).contains(&self.period_ns)
            || self.min_pulse_us < 100
            || self.min_pulse_us >= self.max_pulse_us
            || (u64::from(self.max_pulse_us) + 100) * 1000 > u64::from(self.period_ns)
            || !(self.min_pulse_us..=self.max_pulse_us).contains(&self.safe_pulse_us)
        {
            bail!("invalid PWM timing: {:?}", self);
        }
        Ok(())
    }
    pub fn from_settings(
        settings: &BTreeMap<String, serde_json::Value>,
        mut defaults: Self,
    ) -> Result<Self> {
        for (key, value) in [
            ("period_ns", &mut defaults.period_ns),
            ("min_pulse_us", &mut defaults.min_pulse_us),
            ("max_pulse_us", &mut defaults.max_pulse_us),
            ("safe_pulse_us", &mut defaults.safe_pulse_us),
        ] {
            if let Some(input) = settings.get(key) {
                *value = u32::try_from(
                    input
                        .as_u64()
                        .with_context(|| format!("{key} must be an integer"))?,
                )?;
            }
        }
        defaults.validate()?;
        Ok(defaults)
    }
}

#[derive(Debug, Clone, Copy)]
pub struct PwmStatus {
    pub enabled: bool,
    pub faulted: bool,
    pub pulse_us: u32,
}

pub struct PulseOutput {
    config: PulseConfig,
    backend: Backend,
    enabled: std::sync::atomic::AtomicBool,
    pulse: std::sync::atomic::AtomicU32,
}
enum Backend {
    #[cfg(target_os = "linux")]
    Epwm(std::path::PathBuf),
    #[cfg(target_os = "linux")]
    Pru {
        core: std::sync::Arc<linux::Core>,
        bit: u32,
    },
    #[cfg(not(target_os = "linux"))]
    Mock,
}
impl PulseOutput {
    pub async fn new(connection: &PwmConnection, config: PulseConfig) -> Result<Self> {
        config.validate()?;
        #[cfg(target_os = "linux")]
        let backend = match connection {
            PwmConnection::Epwm { device, channel } => {
                let chip = find_pwmchip(device)?;
                let path = chip.join(format!("pwm{channel}"));
                if !path.exists() {
                    std::fs::write(chip.join("export"), channel.to_string())
                        .context("export PWM")?;
                    smol::Timer::after(std::time::Duration::from_millis(100)).await;
                }
                std::fs::write(path.join("enable"), "0").context("disable PWM")?;
                // A previous process can leave a longer duty cycle behind.
                std::fs::write(path.join("duty_cycle"), "0").context("reset PWM duty")?;
                std::fs::write(path.join("period"), config.period_ns.to_string())
                    .context("set PWM period")?;
                std::fs::write(
                    path.join("duty_cycle"),
                    (config.safe_pulse_us * 1000).to_string(),
                )
                .context("park PWM")?;
                Backend::Epwm(path)
            }
            PwmConnection::Pru {
                subsystem,
                core,
                bit,
            } => {
                let (subsystem, core_nr, bit) = (*subsystem, *core, *bit);
                let core = smol::unblock(move || linux::Core::get(subsystem, core_nr)).await?;
                let command_core = core.clone();
                smol::unblock(move || command_core.exchange(1, bit, config, config.safe_pulse_us))
                    .await?;
                Backend::Pru { core, bit }
            }
        };
        #[cfg(not(target_os = "linux"))]
        let backend = {
            tracing::info!("Mock PWM {:?} with {:?}", connection, config);
            Backend::Mock
        };
        Ok(Self {
            config,
            backend,
            enabled: std::sync::atomic::AtomicBool::new(false),
            pulse: std::sync::atomic::AtomicU32::new(config.safe_pulse_us),
        })
    }
    pub async fn set_pulse_us(&self, pulse: u32) -> Result<()> {
        let pulse = pulse.clamp(self.config.min_pulse_us, self.config.max_pulse_us);
        match &self.backend {
            #[cfg(target_os = "linux")]
            Backend::Epwm(path) => {
                let path = path.join("duty_cycle");
                smol::unblock(move || std::fs::write(path, (pulse * 1000).to_string()))
                    .await
                    .context("set PWM duty")?;
            }
            #[cfg(target_os = "linux")]
            Backend::Pru { core, bit } => {
                let core = core.clone();
                let bit = *bit;
                let config = self.config;
                smol::unblock(move || core.exchange(2, bit, config, pulse)).await?;
            }
            #[cfg(not(target_os = "linux"))]
            Backend::Mock => {
                let _ = pulse;
            }
        }
        self.pulse
            .store(pulse, std::sync::atomic::Ordering::Relaxed);
        Ok(())
    }
    pub async fn enable(&self) -> Result<()> {
        #[cfg(target_os = "linux")]
        match &self.backend {
            Backend::Epwm(path) => std::fs::write(path.join("enable"), "1")?,
            Backend::Pru { core, bit } => {
                let core = core.clone();
                let bit = *bit;
                let config = self.config;
                let pulse = self.pulse.load(std::sync::atomic::Ordering::Relaxed);
                smol::unblock(move || core.configure(bit, config, pulse, true)).await?;
            }
        }
        self.enabled
            .store(true, std::sync::atomic::Ordering::Relaxed);
        Ok(())
    }
    pub async fn enable_native(&self) -> Result<()> {
        #[cfg(target_os = "linux")]
        if matches!(&self.backend, Backend::Pru { .. }) {
            return Ok(());
        }
        self.enable().await
    }
    pub async fn disable(&self) -> Result<()> {
        #[cfg(target_os = "linux")]
        match &self.backend {
            Backend::Epwm(path) => std::fs::write(path.join("enable"), "0")?,
            Backend::Pru { core, bit } => {
                let core = core.clone();
                let bit = *bit;
                let config = self.config;
                smol::unblock(move || core.exchange(4, bit, config, 0)).await?;
            }
        }
        self.enabled
            .store(false, std::sync::atomic::Ordering::Relaxed);
        Ok(())
    }
    pub async fn status(&self) -> Result<PwmStatus> {
        #[cfg(target_os = "linux")]
        match &self.backend {
            Backend::Epwm(path) => {
                return Ok(PwmStatus {
                    enabled: std::fs::read_to_string(path.join("enable"))?.trim() == "1",
                    pulse_us: std::fs::read_to_string(path.join("duty_cycle"))?
                        .trim()
                        .parse::<u32>()?
                        / 1000,
                    faulted: false,
                });
            }
            Backend::Pru { core, bit } => {
                let core = core.clone();
                let bit = *bit;
                let config = self.config;
                return smol::unblock(move || core.exchange(5, bit, config, 0)).await;
            }
        }
        #[cfg(not(target_os = "linux"))]
        Ok(PwmStatus {
            enabled: self.enabled.load(std::sync::atomic::Ordering::Relaxed),
            pulse_us: self.pulse.load(std::sync::atomic::Ordering::Relaxed),
            faulted: false,
        })
    }
}
impl Drop for PulseOutput {
    fn drop(&mut self) {
        #[cfg(target_os = "linux")]
        match &self.backend {
            Backend::Epwm(path) => {
                let _ = std::fs::write(path.join("enable"), "0");
            }
            Backend::Pru { core, bit } => {
                let _ = core.exchange(4, *bit, self.config, 0);
            }
        }
    }
}
/// Commit all staged PRU channels only after complete hardware initialization.
pub async fn arm_pru_outputs() -> Result<()> {
    #[cfg(target_os = "linux")]
    smol::unblock(linux::arm_all).await?;
    Ok(())
}
#[cfg(target_os = "linux")]
fn find_pwmchip(device: &str) -> Result<std::path::PathBuf> {
    for entry in std::fs::read_dir("/sys/class/pwm").context("read PWM devices")? {
        let path = entry?.path();
        if std::fs::read_link(path.join("device"))
            .ok()
            .and_then(|p| p.file_name().map(|s| s == device))
            .unwrap_or(false)
        {
            return Ok(path);
        }
    }
    bail!("No pwmchip found for device {device}")
}
const MAGIC: u32 = 0x46535057;
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn rpmsg_port(value: &str) -> Option<u32> {
    let value = value.trim();
    value.strip_prefix("0x").map_or_else(
        || value.parse().ok(),
        |hex| u32::from_str_radix(hex, 16).ok(),
    )
}
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn packet(op: u32, sequence: u32, bit: u32, config: PulseConfig, pulse: u32) -> [u8; 44] {
    let words = [
        MAGIC,
        1,
        op,
        sequence,
        bit,
        (config.period_ns + 500) / 1000,
        pulse,
        config.safe_pulse_us,
        0,
        config.min_pulse_us,
        config.max_pulse_us,
    ];
    let mut bytes = [0; 44];
    for (word, chunk) in words.iter().zip(bytes.chunks_exact_mut(4)) {
        chunk.copy_from_slice(&word.to_le_bytes());
    }
    bytes
}
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn check_reply(bytes: &[u8], op: u32, sequence: u32, bit: u32) -> Result<PwmStatus> {
    if bytes.len() != 44 {
        bail!("invalid PRU PWM reply length");
    }
    let words: Vec<_> = bytes
        .chunks_exact(4)
        .map(|v| u32::from_le_bytes(v.try_into().unwrap()))
        .collect();
    if words[0] != MAGIC
        || words[1] != 1
        || words[2] != op | 0x80000000
        || words[3] != sequence
        || words[4] != bit
    {
        bail!("mismatched PRU PWM reply");
    }
    if words[5] != 0 {
        bail!("PRU PWM rejected operation {op}: status {}", words[5]);
    }
    Ok(PwmStatus {
        enabled: words[7] & (1 << bit) != 0,
        faulted: words[8] & (1 << bit) != 0,
        pulse_us: words[6],
    })
}

#[cfg(target_os = "linux")]
mod linux {
    use super::*;
    use std::{
        fs::{self, File, OpenOptions},
        io::{Read, Write},
        os::fd::AsRawFd,
        os::unix::fs::OpenOptionsExt,
        path::Path,
        sync::atomic::{AtomicBool, Ordering},
        sync::{Arc, Mutex, OnceLock, Weak},
        time::{Duration, Instant},
    };
    struct Link {
        endpoint: File,
        sequence: u32,
    }
    pub(super) struct Core {
        link: Mutex<Link>,
        failed: AtomicBool,
    }
    static CORES: OnceLock<Mutex<BTreeMap<(u32, u32), Weak<Core>>>> = OnceLock::new();
    impl Core {
        pub fn get(subsystem: u32, core: u32) -> Result<Arc<Self>> {
            if subsystem != 0 || core > 1 {
                bail!("unsupported PWM PRU core");
            }
            let mut cores = CORES
                .get_or_init(Default::default)
                .lock()
                .map_err(|_| anyhow::anyhow!("PWM registry poisoned"))?;
            if let Some(existing) = cores.get(&(subsystem, core)).and_then(Weak::upgrade) {
                return Ok(existing);
            }
            let link = Link::open(core)?;
            let result = Arc::new(Self {
                link: Mutex::new(link),
                failed: AtomicBool::new(false),
            });
            let weak = Arc::downgrade(&result);
            std::thread::Builder::new()
                .name(format!("pru-pwm-{core}"))
                .spawn(move || {
                    loop {
                        std::thread::sleep(Duration::from_millis(100));
                        let Some(core) = weak.upgrade() else {
                            break;
                        };
                        if let Err(error) = core.exchange(3, 0, PulseConfig::mav(), 0) {
                            tracing::error!("PRU PWM heartbeat stopped: {error:#}");
                            break;
                        }
                    }
                })?;
            cores.insert((subsystem, core), Arc::downgrade(&result));
            Ok(result)
        }
        pub fn configure(
            &self,
            bit: u32,
            config: PulseConfig,
            pulse: u32,
            enable: bool,
        ) -> Result<PwmStatus> {
            self.exchange_flags(1, bit, config, pulse, u32::from(enable))
        }
        pub fn exchange(
            &self,
            op: u32,
            bit: u32,
            config: PulseConfig,
            pulse: u32,
        ) -> Result<PwmStatus> {
            self.exchange_flags(op, bit, config, pulse, 0)
        }
        fn exchange_flags(
            &self,
            op: u32,
            bit: u32,
            config: PulseConfig,
            pulse: u32,
            flags: u32,
        ) -> Result<PwmStatus> {
            if self.failed.load(Ordering::SeqCst) {
                bail!("PRU PWM transport fault; restart required");
            }
            let mut link = self
                .link
                .lock()
                .map_err(|_| anyhow::anyhow!("PRU PWM transport poisoned"))?;
            let result = link.exchange(op, bit, config, pulse, flags);
            if result.is_err() {
                self.failed.store(true, Ordering::SeqCst);
            }
            result
        }
    }
    impl Link {
        fn open(core: u32) -> Result<Self> {
            let port = 30 + core;
            let mut endpoints = Vec::new();
            for entry in
                fs::read_dir("/sys/bus/rpmsg/devices").context("PRU RPMsg devices unavailable")?
            {
                let path = entry?.path();
                let canonical = fs::canonicalize(&path)?;
                if !canonical.to_string_lossy().contains("30000000") {
                    continue;
                }
                if fs::read_to_string(path.join("name"))
                    .unwrap_or_default()
                    .trim()
                    != "rpmsg-raw"
                    || rpmsg_port(&fs::read_to_string(path.join("dst")).unwrap_or_default())
                        != Some(port)
                {
                    continue;
                }
                collect_devices(&path, "rpmsg", 3, &mut endpoints)?;
            }
            if endpoints.len() != 1 {
                bail!(
                    "expected one ICSSG0 PRU{core} rpmsg-raw endpoint, found {}",
                    endpoints.len()
                );
            }
            // rpmsg-raw binds to rpmsg_char's default endpoint directly. The
            // separate rpmsg_ctrl service is not advertised by this firmware.
            let endpoint = OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_NONBLOCK)
                .open(Path::new("/dev").join(&endpoints[0]))?;
            // One process owns a core's request/ack stream and heartbeat.
            if unsafe { libc::flock(endpoint.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } < 0 {
                return Err(std::io::Error::last_os_error())
                    .context("PRU PWM endpoint already in use");
            }
            let mut link = Self {
                endpoint,
                sequence: 0,
            };
            link.exchange(5, 0, PulseConfig::mav(), 0, 0)
                .context("PRU PWM firmware handshake")?;
            Ok(link)
        }
        fn exchange(
            &mut self,
            op: u32,
            bit: u32,
            config: PulseConfig,
            pulse: u32,
            flags: u32,
        ) -> Result<PwmStatus> {
            self.sequence = self.sequence.wrapping_add(1);
            let mut request = packet(op, self.sequence, bit, config, pulse);
            request[32..36].copy_from_slice(&flags.to_le_bytes());
            let deadline = Instant::now() + Duration::from_millis(200);
            loop {
                match self.endpoint.write(&request) {
                    Ok(44) => break,
                    Ok(_) => bail!("short PRU PWM RPMsg write"),
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                    Err(e) => return Err(e).context("write PRU PWM command"),
                }
                if Instant::now() >= deadline {
                    bail!("PRU PWM send timed out");
                }
                std::thread::sleep(Duration::from_millis(1));
            }
            loop {
                let mut response = [0u8; 64];
                match self.endpoint.read(&mut response) {
                    Ok(0) => bail!("PRU PWM endpoint closed"),
                    Ok(n) => return check_reply(&response[..n], op, self.sequence, bit),
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                    Err(e) => return Err(e).context("read PRU PWM acknowledgement"),
                }
                if Instant::now() >= deadline {
                    bail!("PRU PWM acknowledgement timed out");
                }
                std::thread::sleep(Duration::from_millis(1));
            }
        }
    }
    pub fn arm_all() -> Result<()> {
        let active: Vec<_> = CORES
            .get_or_init(Default::default)
            .lock()
            .map_err(|_| anyhow::anyhow!("PWM registry poisoned"))?
            .values()
            .filter_map(Weak::upgrade)
            .collect();
        for core in active {
            core.exchange(6, 0, PulseConfig::mav(), 0)?;
        }
        Ok(())
    }
    fn collect_devices(
        path: &Path,
        prefix: &str,
        depth: usize,
        found: &mut Vec<String>,
    ) -> Result<()> {
        if depth == 0 {
            return Ok(());
        }
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            let name = entry.file_name().to_string_lossy().into_owned();
            if name
                .strip_prefix(prefix)
                .is_some_and(|s| !s.is_empty() && s.chars().all(|c| c.is_ascii_digit()))
            {
                found.push(name);
            } else if entry.file_type()?.is_dir() {
                collect_devices(&entry.path(), prefix, depth - 1, found)?;
            }
        }
        Ok(())
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rpmsg_sysfs_destinations_use_hexadecimal() {
        assert_eq!(rpmsg_port("0x1e\n"), Some(30));
        assert_eq!(rpmsg_port("0x1f\n"), Some(31));
        assert_eq!(rpmsg_port("invalid"), None);
    }
    #[test]
    fn timing_rejects_out_of_range_and_unsafe_pulses() {
        let defaults = PulseConfig::mav();
        assert!(defaults.validate().is_ok());
        assert!(
            PulseConfig {
                period_ns: 1_000_000,
                ..defaults
            }
            .validate()
            .is_err()
        );
        assert!(
            PulseConfig {
                safe_pulse_us: 3000,
                ..defaults
            }
            .validate()
            .is_err()
        );
        assert!(
            PulseConfig {
                period_ns: 50_000_001,
                ..defaults
            }
            .validate()
            .is_err()
        );
    }
    #[test]
    fn timing_requires_one_hundred_microseconds_on_and_off() {
        let defaults = PulseConfig::mav();
        assert!(
            PulseConfig {
                min_pulse_us: 99,
                ..defaults
            }
            .validate()
            .is_err()
        );
        assert!(
            PulseConfig {
                period_ns: 2_250_000,
                ..defaults
            }
            .validate()
            .is_err()
        );
    }
    #[test]
    fn numeric_settings_override_defaults_and_reject_strings() {
        let settings = serde_json::from_str(
            r#"{"period_ns":20000000,"min_pulse_us":900,"max_pulse_us":2100,"safe_pulse_us":1000}"#,
        )
        .unwrap();
        let config = PulseConfig::from_settings(&settings, PulseConfig::mav()).unwrap();
        assert_eq!(config.period_ns, 20_000_000);
        assert_eq!(config.safe_pulse_us, 1000);
        let invalid = serde_json::from_str(r#"{"period_ns":"20000000"}"#).unwrap();
        assert!(PulseConfig::from_settings(&invalid, PulseConfig::mav()).is_err());
    }
    #[test]
    fn protocol_reply_must_match_request_and_report_success() {
        let request = packet(1, 42, 12, PulseConfig::mav(), 883);
        assert_eq!(request.len(), 44);
        let mut reply = request;
        reply[8..12].copy_from_slice(&(1u32 | 0x80000000).to_le_bytes());
        reply[20..24].copy_from_slice(&0u32.to_le_bytes());
        assert!(check_reply(&reply, 1, 42, 12).is_ok());
        assert!(check_reply(&reply, 1, 43, 12).is_err());
        reply[20..24].copy_from_slice(&4u32.to_le_bytes());
        assert!(check_reply(&reply, 1, 42, 12).is_err());
    }
    #[cfg(not(target_os = "linux"))]
    #[test]
    fn pulse_output_stages_safe_then_enables_and_disables() {
        smol::block_on(async {
            let output = PulseOutput::new(
                &PwmConnection::Pru {
                    subsystem: 0,
                    core: 0,
                    bit: 12,
                },
                PulseConfig::mav(),
            )
            .await
            .unwrap();
            assert!(!output.status().await.unwrap().enabled);
            assert_eq!(output.status().await.unwrap().pulse_us, 883);
            output.enable().await.unwrap();
            output.set_pulse_us(1950).await.unwrap();
            assert!(output.status().await.unwrap().enabled);
            assert_eq!(output.status().await.unwrap().pulse_us, 1950);
            output.disable().await.unwrap();
            assert!(!output.status().await.unwrap().enabled);
        });
    }
}
