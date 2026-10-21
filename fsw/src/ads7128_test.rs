
// only for testing purposes -- if you want to run this do cargo build --release --features test_ads7128
use embassy_time::Timer;
use crate::driver::ads7128::Ads7128Sensor;
use crate::module::SharedI2c;


pub async fn run(i2c_bus: &'static SharedI2c) -> ! {
    log::info!("ADS7128 8-channel test");

    let mut adc = Ads7128Sensor::new(i2c_bus).await;

    loop {
        for channel in 0..8 {
            match adc.read_channel(channel).await {
                Ok(value) => {
                    log::info!("A{} raw = {}", channel, value);
                }
                Err(e) => {
                    log::error!("A{} read failed: {:?}", channel, e);
                }
            }

            Timer::after_millis(100).await;
        }

        log::info!("Finished reading all 8 channels");
        Timer::after_millis(1000).await;
    }
}