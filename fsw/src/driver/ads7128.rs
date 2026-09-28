//ADC for liquid fsw (8 channel 12 bit), check conversion time -- needs to be tested 

use crate::module::{I2cDevice, SharedI2c};
use embassy_embedded_hal::shared_bus::asynch::i2c::I2cDevice as SharedI2cDevice;
use embedded_hal_async::i2c::I2c;

use crate::constants;
use crate::packet::Packet;

// Register addresses
const SYSTEM_STATUS: u8 = 0x00;
const GENERAL_CFG: u8 = 0x01;
// instead of the mux within the config on ADS1015, CHANNEL_SEL choses which AIN channel is used 
const CHANNEL_SEL: u8 =  0x11; 
const CMD_SINGLE_REGISTER_WRITE: u8 = 0x08;
const CMD_SINGLE_REGISTER_READ: u8 = 0x10;



//errors with the driver 
#[derive(Debug)]
pub enum Ads7128Error<E> {
    I2c(E),
    InvalidChannel,
}

//i2c error 
impl<E> From<E> for Ads7128Error<E> {
    fn from(error: E) -> Self {
        Ads7128Error::I2c(error)
    }
}

pub struct Ads7128Sensor {
    i2c: I2cDevice<'static>,
    initialized: bool,
}


impl Ads7128Sensor {

    pub fn unavailable(i2c_bus: &'static SharedI2c) -> Self {
        Self {
            i2c: SharedI2cDevice::new(i2c_bus),
            initialized: false,
        }
    }

    pub async fn new(i2c_bus: &'static SharedI2c) -> Self {
        let mut sensor = Self {
            i2c: SharedI2cDevice::new(i2c_bus),
            initialized: false,
        };

        match sensor.init().await {
            Ok(_) => {
                log::info!(
                    "ADS7128 initialized at address {:#04X}",
                    constants::ADS7128_I2C_ADDR
                );
                sensor.initialized = true;
            }
            Err(_) => log::error!("Failed to initialize ADS7128"),
        }

        sensor
    }

    async fn init( &mut self,) -> Result<(), Ads7128Error<<I2cDevice<'static> as embedded_hal_async::i2c::ErrorType>::Error>> {
        let status = self.read_register(SYSTEM_STATUS).await?;
        log::info!("ADS7128: System status = {:#04X}", status);
        Ok(())
    }

    /// Write an 8-bit value to a register
    async fn write_register(&mut self, register: u8, value: u8) -> Result<(), Ads7128Error<<I2cDevice<'static> as embedded_hal_async::i2c::ErrorType>::Error>> {
        self.i2c.write(constants::ADS7128_I2C_ADDR, &[CMD_SINGLE_REGISTER_WRITE, register, value]).await?;
        Ok(())
    }

    /// Read a 8-bit value from a register
    async fn read_register(&mut self, register: u8) -> Result<u8, Ads7128Error<<I2cDevice<'static> as embedded_hal_async::i2c::ErrorType>::Error>> {
        let mut buf = [0u8; 1];
        self.i2c.write_read(constants::ADS7128_I2C_ADDR, &[CMD_SINGLE_REGISTER_READ,register], &mut buf).await?;
        Ok(buf[0])
    }

    pub async fn read_channel(&mut self, channel: u8) -> Result<u16, Ads7128Error<<I2cDevice<'static> as embedded_hal_async::i2c::ErrorType>::Error>> {
        if channel > 7 {
            return Err(Ads7128Error::InvalidChannel);
        }
        self.write_register(CHANNEL_SEL, channel).await?; 

        let mut buf = [0u8; 2];
        self.i2c.read(constants::ADS7128_I2C_ADDR, &mut buf).await?;


        //upper and lower need to be shifted
        let value = ((buf[0] as u16) << 4) | ((buf[1] as u16) >> 4);

        Ok(value)
    }

    //need to figure out what other channels need to be read + scaling for them and change it from last years 
    pub async fn read_into_packet(&mut self, packet: &mut Packet) -> Result<(), Ads7128Error<<I2cDevice<'static> as embedded_hal_async::i2c::ErrorType>::Error>> {
        if !self.initialized {
            return Ok(());
        }
        let raw_rtd = self.read_channel(1).await?;
        let raw_pt4 = self.read_channel(2).await?;
        let raw_pt3 = self.read_channel(3).await?;

        // need to fix the constants for scaling, also the # of packets needed for the respective sensors 
        packet.rtd = raw_rtd as f32 * constants::ADS1015_RTD_SCALE_M + constants::ADS1015_RTD_SCALE_B;

        let scaled_pt4 = raw_pt4 as f32 * constants::ADS1015_PT4_SCALE_M + constants::ADS1015_PT4_SCALE_B;
        packet.pt4 = scaled_pt4;

        let scaled_pt3 = raw_pt3 as f32 * constants::ADS1015_PT3_SCALE_M + constants::ADS1015_PT3_SCALE_B;
        packet.pt3 = scaled_pt3;

        Ok(())
    }




}