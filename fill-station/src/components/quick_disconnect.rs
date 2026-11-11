//! Quick disconnect.
//!
//! This year the QD is a solenoid valve with the same control/continuity
//! wiring, so it reuses the solenoid valve driver directly rather than keeping
//! a separate copy. If the QD ever needs its own behavior, replace the alias
//! with a newtype wrapping `SolenoidValve`.

pub use super::solenoid_valve::{LinePull, SolenoidValve};

pub type QuickDisconnect = SolenoidValve;
