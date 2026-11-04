//ADC for liquid fsw (8 channel 12 bit), check conversion time -- needs to be tested

use anyhow::Result;

#[cfg(any(target_os = "linux", target_os = "android"))]
use anyhow::{Context, bail};

#[cfg(any(target_os = "linux", target_os = "android"))]
use i2cdev::core::I2CDevice;
#[cfg(any(target_os = "linux", target_os = "android"))]
use i2cdev::linux::LinuxI2CDevice;

// Register addresses
#[cfg(any(target_os = "linux", target_os = "android"))]
const SYSTEM_STATUS: u8 = 0x00;
#[allow(dead_code)]
const GENERAL_CFG: u8 = 0x01;
// instead of the mux within the config on ADS1015, CHANNEL_SEL choses which AIN channel is used
#[cfg(any(target_os = "linux", target_os = "android"))]
const CHANNEL_SEL: u8 = 0x11;
#[cfg(any(target_os = "linux", target_os = "android"))]
const CMD_SINGLE_REGISTER_WRITE: u8 = 0x08;
#[cfg(any(target_os = "linux", target_os = "android"))]
const CMD_SINGLE_REGISTER_READ: u8 = 0x10;

/// ADS7128 8-channel 12-bit ADC driver
#[cfg(any(target_os = "linux", target_os = "android"))]
pub struct Ads7128 {
    device: LinuxI2CDevice,
    address: u16,
}

#[cfg(any(target_os = "linux", target_os = "android"))]
impl Ads7128 {
    /// Create a new ADS7128 instance
    ///
    /// # Arguments
    /// * `bus` - I2C bus path (e.g., "/dev/i2c-2")
    /// * `address` - I2C address (0x10-0x17 depending on ADDR pin)
    pub fn new(bus: &str, address: u16) -> Result<Self> {
        let device = LinuxI2CDevice::new(bus, address)
            .with_context(|| format!("Failed to open I2C device {} at address 0x{:02X}", bus, address))?;

        let mut adc = Self { device, address };

        let status = adc.read_register(SYSTEM_STATUS)?;
        tracing::info!("ADS7128 at {:#04X}: System status = {:#04X}", address, status);

        Ok(adc)
    }

    /// Get the I2C address of this device
    pub fn address(&self) -> u16 {
        self.address
    }

    /// Write an 8-bit value to a register
    fn write_register(&mut self, register: u8, value: u8) -> Result<()> {
        self.device
            .write(&[CMD_SINGLE_REGISTER_WRITE, register, value])
            .with_context(|| format!("Failed to write register {:#04X}", register))?;
        Ok(())
    }

    /// Read a 8-bit value from a register
    fn read_register(&mut self, register: u8) -> Result<u8> {
        self.device
            .write(&[CMD_SINGLE_REGISTER_READ, register])
            .with_context(|| format!("Failed to select register {:#04X}", register))?;
        let mut buf = [0u8; 1];
        self.device
            .read(&mut buf)
            .with_context(|| format!("Failed to read register {:#04X}", register))?;
        Ok(buf[0])
    }

    /// Read raw 12-bit value (0-4095) from the given channel (0-7)
    pub fn read_channel(&mut self, channel: u8) -> Result<u16> {
        if channel > 7 {
            bail!("Invalid ADS7128 channel {}", channel);
        }

        tracing::debug!("Selecting ADS7128 channel {}", channel);

        self.write_register(CHANNEL_SEL, channel)?;

        let mut buf = [0u8; 2];
        self.device
            .read(&mut buf)
            .context("Failed to read conversion data")?;

        let value = ((buf[0] as u16) << 4) | ((buf[1] as u16) >> 4);

        tracing::debug!("Channel {} raw bytes: {:02X} {:02X}", channel, buf[0], buf[1]);

        Ok(value)
    }

    //only for testing purposes -- will delete later
    pub fn test_all_channels(&mut self) {
        tracing::info!("Starting ADS7128 channel test");

        loop {
            for channel in 0u8..8 {
                match self.read_channel(channel) {
                    Ok(raw) => {
                        tracing::info!("Channel {}: raw = {}", channel, raw);
                    }
                    Err(err) => {
                        tracing::error!("Channel {} failed: {:?}", channel, err);
                    }
                }
            }

            tracing::info!("Channel scan complete");
            std::thread::sleep(std::time::Duration::from_millis(1000));
        }
    }
}

/// Stub implementation for non-Linux platforms
#[cfg(not(any(target_os = "linux", target_os = "android")))]
pub struct Ads7128 {
    _address: u16,
}

#[cfg(not(any(target_os = "linux", target_os = "android")))]
impl Ads7128 {
    pub fn new(_bus: &str, address: u16) -> Result<Self> {
        Ok(Self { _address: address })
    }

    pub fn address(&self) -> u16 {
        self._address
    }

    pub fn read_channel(&mut self, _channel: u8) -> Result<u16> {
        anyhow::bail!("ADS7128 is only supported on Linux/Android")
    }

    pub fn test_all_channels(&mut self) {
        tracing::error!("ADS7128 is only supported on Linux/Android");
    }
}
