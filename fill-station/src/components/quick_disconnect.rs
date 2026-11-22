//! Quick disconnect.
//!
//! This year the QD is a solenoid valve with the same control/continuity
//! wiring. Active-high / normally-closed is fixed by hardware initialization:
//! `set_open(true)` energizes and DISCONNECTS/releases; false de-energizes.
//! Command memory and continuity do not prove physical engagement.
//! It reuses the solenoid valve driver directly rather than keeping
//! a separate copy. If the QD ever needs its own behavior, replace the alias
//! with a newtype wrapping `SolenoidValve`.

pub use super::solenoid_valve::{LinePull, SolenoidValve};

pub type QuickDisconnect = SolenoidValve;
