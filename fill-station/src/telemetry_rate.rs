//! Rate configuration and local publisher accounting (not delivery acknowledgements).
use std::time::Duration;

pub fn parse_rate(value: Option<&str>) -> Result<u32, &'static str> {
    let Some(value) = value else {
        return Ok(10);
    };
    if value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit()) {
        return Err("expected integer MQTT rate 1..50 Hz");
    }
    match value.parse::<u32>() {
        Ok(rate) if (1..=50).contains(&rate) => Ok(rate),
        _ => Err("expected integer MQTT rate 1..50 Hz"),
    }
}

pub fn interval(rate: u32) -> Duration {
    // Only validated rates enter this function.
    Duration::from_nanos(1_000_000_000 / u64::from(rate))
}

pub enum Outcome {
    Queued,
    Rejected,
    EncodingFailed,
}

#[derive(Default)]
pub struct Stats {
    pub attempted: u64,
    pub queued: u64,
    pub rejected: u64,
    pub encoding_failed: u64,
    pub overruns: u64,
    pub max_work: Duration,
}
impl Stats {
    pub fn record(&mut self, outcome: Outcome, work: Duration, period: Duration) {
        self.attempted += 1;
        match outcome {
            Outcome::Queued => self.queued += 1,
            Outcome::Rejected => self.rejected += 1,
            Outcome::EncodingFailed => self.encoding_failed += 1,
        }
        self.overruns += u64::from(work >= period);
        self.max_work = self.max_work.max(work);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounds_and_exact_intervals() {
        assert_eq!(parse_rate(None).unwrap(), 10);
        assert_eq!(parse_rate(Some("50")).unwrap(), 50);
        for value in ["0", "51", "-1", "1.5", "", " 50", "999999999999"] {
            assert!(parse_rate(Some(value)).is_err(), "{value}");
        }
        assert_eq!(interval(50), std::time::Duration::from_millis(20));
        assert_eq!(interval(30).as_nanos(), 33_333_333);
    }
    #[test]
    fn queue_acceptance_is_separate_from_failures_and_work_overruns() {
        let mut stats = Stats::default();
        let period = interval(50);
        stats.record(Outcome::Queued, std::time::Duration::from_millis(5), period);
        stats.record(
            Outcome::Rejected,
            std::time::Duration::from_millis(25),
            period,
        );
        stats.record(
            Outcome::EncodingFailed,
            std::time::Duration::from_millis(20),
            period,
        );
        assert_eq!(
            (
                stats.attempted,
                stats.queued,
                stats.rejected,
                stats.encoding_failed,
                stats.overruns
            ),
            (3, 1, 1, 1, 2)
        );
        assert_eq!(stats.max_work, std::time::Duration::from_millis(25));
    }
}
