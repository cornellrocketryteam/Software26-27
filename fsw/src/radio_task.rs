//! Radio tasks — keep the RFD900x UART out of the flight loop.
//!
//! A 197-byte telemetry frame takes ~17 ms on the wire at 115200 baud, and
//! waiting for a ground command used to cost a 10 ms timeout every cycle.
//! Both now run in their own tasks:
//!
//!   - [`radio_tx_task`] sends the most recent packet at `RADIO_TX_PERIOD_MS`.
//!     The flight loop hands packets over with [`queue_telemetry`], which never
//!     waits; a newer packet simply replaces one that hasn't been sent yet.
//!   - [`radio_rx_task`] listens continuously and queues parsed ground
//!     commands. The flight loop drains them with [`try_recv_command`].

use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::channel::Channel;
use embassy_sync::signal::Signal;
use embassy_time::{with_timeout, Duration, Ticker};

use crate::constants;
use crate::driver::rfd900x::{Rfd900xRx, Rfd900xTx};
use crate::packet::{Command, Packet};

/// Latest telemetry packet waiting to be sent (latest value wins).
static TX_PACKET: Signal<CriticalSectionRawMutex, [u8; Packet::SIZE]> = Signal::new();

/// Ground commands parsed by the RX task, waiting for the flight loop.
static COMMANDS: Channel<CriticalSectionRawMutex, Command, 4> = Channel::new();

/// Longest command message we buffer before parsing.
const MAX_COMMAND_LEN: usize = 32;

/// Hand the latest telemetry packet to the TX task. Never waits.
pub fn queue_telemetry(data: [u8; Packet::SIZE]) {
    TX_PACKET.signal(data);
}

/// Take the next pending ground command, if any. Never waits.
pub fn try_recv_command() -> Option<Command> {
    COMMANDS.try_receive().ok()
}

#[embassy_executor::task]
pub async fn radio_tx_task(mut radio: Rfd900xTx<'static>) {
    let mut ticker = Ticker::every(Duration::from_millis(constants::RADIO_TX_PERIOD_MS));
    loop {
        let data = TX_PACKET.wait().await;
        match radio.send(&data).await {
            Ok(_) => {
                log::info!("RFD | Data transmitted successfully!");
            }
            Err(e) => {
                log::warn!("RFD | Failed to transmit packet via radio: {:?}", e);
            }
        }
        ticker.next().await;
    }
}

#[embassy_executor::task]
pub async fn radio_rx_task(mut radio: Rfd900xRx<'static>) {
    let idle = Duration::from_millis(constants::RADIO_CMD_IDLE_MS);
    let mut buf = [0u8; MAX_COMMAND_LEN];
    let mut len = 0;
    let mut byte = [0u8; 1];

    loop {
        // A message ends at a newline, a full buffer, or a gap on the line.
        // With nothing buffered there is no gap to time, so just wait.
        let got_byte = if len == 0 {
            radio.receive(&mut byte).await.is_ok()
        } else {
            match with_timeout(idle, radio.receive(&mut byte)).await {
                Ok(result) => result.is_ok(),
                Err(_) => {
                    queue_command(&buf[..len]);
                    len = 0;
                    continue;
                }
            }
        };

        if !got_byte {
            // UART error (framing/overrun): drop the partial message.
            len = 0;
            continue;
        }

        if byte[0] == b'\n' || byte[0] == b'\r' {
            queue_command(&buf[..len]);
            len = 0;
            continue;
        }

        buf[len] = byte[0];
        len += 1;
        if len == MAX_COMMAND_LEN {
            queue_command(&buf[..len]);
            len = 0;
        }
    }
}

/// Parse one message and queue it for the flight loop if it is a command.
fn queue_command(msg: &[u8]) {
    if let Some(cmd) = parse_command(msg) {
        if COMMANDS.try_send(cmd).is_err() {
            log::warn!("RFD | Command queue full, dropping {:?}", cmd);
        }
    }
}

// Simple string-based command parsing
// Commands might not have the sync-word unless they are sent by another FSW board.
fn parse_command(msg: &[u8]) -> Option<Command> {
    if msg.starts_with(b"VNT") {
        Some(Command::Vent)
    } else if msg.starts_with(b"N1") {
        Some(Command::N1)
    } else if msg.starts_with(b"N2") {
        Some(Command::N2)
    } else if msg.starts_with(b"N3") {
        Some(Command::N3)
    } else if msg.starts_with(b"N4") {
        Some(Command::N4)
    } else if msg.starts_with(b"FM") {
        // Example: "FM2" for Coast
        let digit = (*msg.get(2)? as char).to_digit(10)?;
        Some(Command::ForceMode(digit))
    } else {
        None
    }
}
