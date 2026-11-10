//! Opt-in ADS7128 bench diagnostic; never initializes fill-station actuators.

const USAGE: &str = "usage: fill-station --ads7128-test <address 0x10..0x17>";

pub fn parse_args(args: &[String]) -> Result<Option<u16>, &'static str> {
    if !args.iter().any(|arg| arg == "--ads7128-test") {
        return Ok(None);
    }
    if args.len() != 2 || args[0] != "--ads7128-test" {
        return Err(USAGE);
    }
    let text = &args[1];
    let (digits, radix) = match text.strip_prefix("0x").or_else(|| text.strip_prefix("0X")) {
        Some(digits) => (digits, 16),
        None => (text.as_str(), 10),
    };
    if digits.is_empty() || !digits.chars().all(|ch| ch.is_digit(radix)) {
        return Err(USAGE);
    }
    let address = u16::from_str_radix(digits, radix).map_err(|_| USAGE)?;
    if !(0x10..=0x17).contains(&address) {
        return Err(USAGE);
    }
    Ok(Some(address))
}

fn scan_line<E: std::fmt::Display>(
    address: u16,
    mut read: impl FnMut(u8) -> Result<u16, E>,
) -> String {
    use std::fmt::Write;

    let mut line = format!("ADS7128 0x{address:02x}:");
    for channel in 0..8 {
        match read(channel) {
            Ok(raw) => write!(line, " CH{channel}={raw}"),
            Err(error) => write!(line, " CH{channel}=ERROR({error})"),
        }
        .expect("writing to a String cannot fail");
    }
    line
}

/// Probe once, then report all eight channels once per second until interrupted.
#[cfg(not(test))]
pub fn run(address: u16) -> anyhow::Result<()> {
    #[cfg(any(target_os = "linux", target_os = "android"))]
    {
        use crate::components::ads7128::Ads7128;
        use std::io::Write;
        use std::time::{Duration, Instant};

        let mut adc = Ads7128::new("/dev/i2c-0", address)?;
        loop {
            let started = Instant::now();
            println!(
                "{}",
                scan_line(address, |channel| adc.read_channel(channel))
            );
            std::io::stdout().flush()?;
            std::thread::sleep(Duration::from_secs(1).saturating_sub(started.elapsed()));
        }
    }
    #[cfg(not(any(target_os = "linux", target_os = "android")))]
    {
        let _ = address;
        anyhow::bail!("ADS7128 diagnostic requires Linux/Android");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(values: &[&str]) -> Vec<String> {
        values.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn normal_invocation_is_unchanged() {
        assert_eq!(parse_args(&[]), Ok(None));
        assert_eq!(parse_args(&args(&["--other"])), Ok(None));
    }

    #[test]
    fn accepts_every_ads7128_address() {
        for address in 0x10..=0x17 {
            for text in [
                format!("0x{address:02x}"),
                format!("0X{address:02X}"),
                address.to_string(),
            ] {
                assert_eq!(
                    parse_args(&args(&["--ads7128-test", &text])),
                    Ok(Some(address))
                );
            }
        }
    }

    #[test]
    fn rejects_other_devices_and_malformed_addresses() {
        for text in [
            "0x0f", "0x18", "0x30", "0x51", "0x48", "0x10010", "", "0x", "xyz", "-16", "+16",
            " 16", "16 ",
        ] {
            assert!(
                parse_args(&args(&["--ads7128-test", text])).is_err(),
                "{text:?}"
            );
        }
    }

    #[test]
    fn diagnostic_requires_exactly_one_address_and_first_position() {
        for values in [
            vec!["--ads7128-test"],
            vec!["--ads7128-test", "0x10", "extra"],
            vec!["--other", "--ads7128-test", "0x10"],
        ] {
            assert_eq!(parse_args(&args(&values)), Err(USAGE));
        }
    }

    #[test]
    fn scans_all_channels_in_order_and_keeps_errors_local() {
        let mut channels = Vec::new();
        let line = scan_line(0x10, |channel| {
            channels.push(channel);
            if channel == 2 {
                Err("read failed")
            } else {
                Ok(u16::from(channel) * 500)
            }
        });
        assert_eq!(channels, (0..8).collect::<Vec<u8>>());
        assert_eq!(
            line,
            "ADS7128 0x10: CH0=0 CH1=500 CH2=ERROR(read failed) CH3=1500 CH4=2000 CH5=2500 CH6=3000 CH7=3500"
        );
    }
}
