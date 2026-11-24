//! Source-frame identity and clock provenance, independent of delivery order.
//! Kernel synchronization does not establish the reference's absolute UTC accuracy.
use std::fs::File;
use std::io::{self, Read};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u32)]
pub enum TimeQuality {
    Unknown = 0,
    KernelSynchronized = 1,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FrameMetadata {
    pub session_hi: u64,
    pub session_lo: u64,
    pub sequence: u64,
    pub monotonic_ms: u64,
    pub unix_ms: u64,
    pub unix_valid: bool,
    pub quality: TimeQuality,
    pub time_generation: u32,
}

impl FrameMetadata {
    /// Exact public publisher identity, matching the database session catalog.
    pub fn session_id(&self) -> String {
        format!("{:016x}{:016x}", self.session_hi, self.session_lo)
    }
}

pub struct PublisherClock {
    session_hi: u64,
    session_lo: u64,
    origin: Instant,
    next_sequence: Option<u64>,
    previous: Option<FrameMetadata>,
}

impl PublisherClock {
    pub fn new() -> io::Result<Self> {
        Self::from_entropy(&mut File::open("/dev/urandom")?)
    }

    fn from_entropy(reader: &mut impl Read) -> io::Result<Self> {
        let mut bytes = [0u8; 16];
        reader.read_exact(&mut bytes)?;
        if bytes == [0; 16] {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "zero publisher-session entropy",
            ));
        }
        Ok(Self {
            session_hi: u64::from_be_bytes(bytes[..8].try_into().unwrap()),
            session_lo: u64::from_be_bytes(bytes[8..].try_into().unwrap()),
            origin: Instant::now(),
            next_sequence: Some(1),
            previous: None,
        })
    }

    pub fn capture(
        &mut self,
        quality: TimeQuality,
    ) -> Result<(FrameMetadata, Instant), &'static str> {
        let now = Instant::now();
        let elapsed = u64::try_from(now.duration_since(self.origin).as_millis())
            .map_err(|_| "publisher monotonic clock exhausted")?;
        let unix = unix_millis(SystemTime::now());
        Ok((self.stamp_at(elapsed, unix, quality)?, now))
    }

    fn stamp_at(
        &mut self,
        monotonic_ms: u64,
        unix: Option<u64>,
        quality: TimeQuality,
    ) -> Result<FrameMetadata, &'static str> {
        let sequence = self
            .next_sequence
            .ok_or("publisher sequence exhausted; new session required")?;
        let unix_valid = unix.is_some() && quality != TimeQuality::Unknown;
        let quality = if unix_valid {
            quality
        } else {
            TimeQuality::Unknown
        };
        let unix_ms = if unix_valid { unix.unwrap() } else { 0 };
        let mut generation = self.previous.map_or(1, |old| old.time_generation);
        if let Some(old) = self.previous {
            let elapsed = monotonic_ms
                .checked_sub(old.monotonic_ms)
                .ok_or("monotonic clock regressed")?;
            let stepped = unix_valid
                && old.unix_valid
                && ((unix_ms as i128 - old.unix_ms as i128) - elapsed as i128).abs() > 1000;
            if quality != old.quality || stepped {
                generation = generation
                    .checked_add(1)
                    .ok_or("source clock generation exhausted")?;
            }
        }
        let frame = FrameMetadata {
            session_hi: self.session_hi,
            session_lo: self.session_lo,
            sequence,
            monotonic_ms,
            unix_ms,
            unix_valid,
            quality,
            time_generation: generation,
        };
        self.next_sequence = sequence.checked_add(1);
        self.previous = Some(frame);
        Ok(frame)
    }
}

/// Age of a previously captured sample, never inferred from new packet assembly.
pub fn sample_age(now: Instant, captured: Option<Instant>) -> (u64, bool) {
    captured
        .and_then(|value| now.checked_duration_since(value))
        .and_then(|value| u64::try_from(value.as_millis()).ok())
        .map_or((0, false), |age| (age, true))
}

pub fn unix_millis(time: SystemTime) -> Option<u64> {
    time.duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|value| u64::try_from(value.as_millis()).ok())
}

#[cfg(any(target_os = "linux", test))]
fn quality_from_kernel(result: i32, unsynchronized: bool, clock_error: bool) -> TimeQuality {
    // Linux TIME_OK..TIME_WAIT are 0..4; TIME_ERROR=5 and unknown states fail closed.
    if (0..=4).contains(&result) && !unsynchronized && !clock_error {
        TimeQuality::KernelSynchronized
    } else {
        TimeQuality::Unknown
    }
}

/// Read-only modes=0 query. Neither sets time nor identifies the NTP reference.
#[cfg(target_os = "linux")]
pub fn kernel_time_quality() -> TimeQuality {
    // SAFETY: timex is a C POD output buffer; modes=0 only reads kernel state.
    let mut state: libc::timex = unsafe { std::mem::zeroed() };
    let result = unsafe { libc::adjtimex(&mut state) };
    quality_from_kernel(
        result,
        state.status & libc::STA_UNSYNC != 0,
        state.status & libc::STA_CLOCKERR != 0,
    )
}

#[cfg(not(target_os = "linux"))]
pub fn kernel_time_quality() -> TimeQuality {
    TimeQuality::Unknown
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    use std::time::Duration;

    fn clock() -> PublisherClock {
        PublisherClock::from_entropy(&mut Cursor::new([1u8; 16])).unwrap()
    }

    #[test]
    fn session_id_is_exact_hex_matching_the_catalog_label() {
        let mut frame = clock().stamp_at(0, None, TimeQuality::Unknown).unwrap();
        frame.session_hi = u64::MAX;
        frame.session_lo = 1;
        assert_eq!(frame.session_id(), "ffffffffffffffff0000000000000001");
    }

    #[test]
    fn ordering_survives_backward_and_forward_wall_steps() {
        let mut clock = clock();
        let a = clock
            .stamp_at(0, Some(10_000), TimeQuality::KernelSynchronized)
            .unwrap();
        let b = clock
            .stamp_at(100, Some(1_000), TimeQuality::KernelSynchronized)
            .unwrap();
        let c = clock
            .stamp_at(200, Some(90_000), TimeQuality::KernelSynchronized)
            .unwrap();
        assert_eq!((a.sequence, b.sequence, c.sequence), (1, 2, 3));
        assert_eq!(
            (a.time_generation, b.time_generation, c.time_generation),
            (1, 2, 3)
        );
        assert_eq!(a.session_hi, c.session_hi);
        assert_eq!(a.session_lo, c.session_lo);
    }

    #[test]
    fn unsynchronized_or_missing_epoch_never_claims_valid_unix_time() {
        let mut clock = clock();
        let a = clock
            .stamp_at(0, Some(9_999_999), TimeQuality::Unknown)
            .unwrap();
        let b = clock
            .stamp_at(1, None, TimeQuality::KernelSynchronized)
            .unwrap();
        for frame in [a, b] {
            assert!(!frame.unix_valid);
            assert_eq!(frame.unix_ms, 0);
            assert_eq!(frame.quality, TimeQuality::Unknown);
        }
    }

    #[test]
    fn synchronization_loss_and_recovery_change_generation_without_restarting_sequence() {
        let mut clock = clock();
        let a = clock.stamp_at(0, None, TimeQuality::Unknown).unwrap();
        let b = clock
            .stamp_at(100, Some(10_000), TimeQuality::KernelSynchronized)
            .unwrap();
        let c = clock
            .stamp_at(200, Some(10_100), TimeQuality::KernelSynchronized)
            .unwrap();
        let d = clock.stamp_at(300, None, TimeQuality::Unknown).unwrap();
        assert_eq!(
            (
                a.time_generation,
                b.time_generation,
                c.time_generation,
                d.time_generation
            ),
            (1, 2, 2, 3)
        );
        assert_eq!(d.sequence, 4);
    }

    #[test]
    fn independent_publishers_have_new_entropy_identity() {
        let a = PublisherClock::new().unwrap();
        let b = PublisherClock::new().unwrap();
        assert_ne!((a.session_hi, a.session_lo), (b.session_hi, b.session_lo));
    }

    #[test]
    fn absent_short_or_zero_entropy_is_rejected() {
        assert!(PublisherClock::from_entropy(&mut Cursor::new([0u8; 16])).is_err());
        assert!(PublisherClock::from_entropy(&mut Cursor::new([1u8; 8])).is_err());
    }

    #[test]
    fn sequence_exhaustion_does_not_wrap() {
        let mut clock = clock();
        clock.next_sequence = Some(u64::MAX);
        let last = clock.stamp_at(0, None, TimeQuality::Unknown).unwrap();
        assert_eq!(last.sequence, u64::MAX);
        assert!(clock.stamp_at(1, None, TimeQuality::Unknown).is_err());
    }

    #[test]
    fn rejected_monotonic_regression_does_not_consume_sequence() {
        let mut clock = clock();
        clock.stamp_at(20, None, TimeQuality::Unknown).unwrap();
        assert!(clock.stamp_at(19, None, TimeQuality::Unknown).is_err());
        assert_eq!(
            clock
                .stamp_at(21, None, TimeQuality::Unknown)
                .unwrap()
                .sequence,
            2
        );
    }

    #[test]
    fn sample_age_distinguishes_unknown_from_fresh_zero_and_old_cached_values() {
        let now = Instant::now();
        assert_eq!(sample_age(now, None), (0, false));
        assert_eq!(sample_age(now, Some(now)), (0, true));
        assert_eq!(
            sample_age(now, Some(now - Duration::from_millis(1500))),
            (1500, true)
        );
        assert_eq!(
            sample_age(now, Some(now + Duration::from_secs(1))),
            (0, false)
        );
    }

    #[test]
    fn kernel_error_or_unsynchronized_flags_do_not_claim_synchronized_time() {
        for (result, unsync, error) in [
            (-1, false, false),
            (5, false, false),
            (6, false, false),
            (0, true, false),
            (0, false, true),
        ] {
            assert_eq!(
                quality_from_kernel(result, unsync, error),
                TimeQuality::Unknown
            );
        }
        assert_eq!(
            quality_from_kernel(0, false, false),
            TimeQuality::KernelSynchronized
        );
    }

    #[test]
    fn epoch_conversion_does_not_panic_before_1970() {
        assert_eq!(unix_millis(UNIX_EPOCH - Duration::from_secs(1)), None);
        assert_eq!(
            unix_millis(UNIX_EPOCH + Duration::from_millis(123)),
            Some(123)
        );
    }

    #[test]
    fn captured_metadata_can_be_reused_without_resequencing() {
        let mut clock = clock();
        let frame = clock
            .stamp_at(0, Some(10_000), TimeQuality::KernelSynchronized)
            .unwrap();
        let queued_copy = frame;
        assert_eq!(queued_copy, frame);
        assert_eq!(
            clock
                .stamp_at(1, Some(10_001), TimeQuality::KernelSynchronized)
                .unwrap()
                .sequence,
            2
        );
    }
}
