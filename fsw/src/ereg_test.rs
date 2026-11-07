// only for testing purposes -- if you want to run this do
// cargo build --release --features test_ereg

use embassy_time::Timer;
use crate::ereg::Ereg;


pub async fn run(mut ereg: Ereg<'static>) -> ! {
    log::info!("E-REG PWM test");

    loop {
        for angle in [0.0, 45.0, 90.0] {
            let success = ereg.set_angle_degrees(angle);

            if success {
                log::info!("PWM angle: {} degrees", angle);
            } else {
                log::error!("PWM output failed");
            }

            Timer::after_secs(3).await;
        }
    }
}