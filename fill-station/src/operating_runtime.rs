//! Runtime ownership policy. Missing selector preserves existing image behavior.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum RoutingMode {
    #[default]
    Legacy,
    Hybrid,
    HybridTest,
}
impl RoutingMode {
    pub fn parse(name: Option<&str>) -> Option<Self> {
        match name {
            None => Some(Self::Legacy),
            Some("hybrid") => Some(Self::Hybrid),
            Some("hybrid-test") => Some(Self::HybridTest),
            _ => None,
        }
    }
    /// Source metadata schema and explicit operating profile; legacy stays unspecified.
    pub fn telemetry_identity(self) -> (u32, u32) {
        match self {
            Self::Legacy => (1, 0),
            Self::Hybrid => (3, 1),
            Self::HybridTest => (3, 2),
        }
    }
    pub fn fsw_enabled(self) -> bool {
        self != Self::HybridTest
    }
}
#[derive(Debug, Clone, Copy)]
pub struct Sample {
    pub raw: i16,
    pub voltage: f32,
    pub scaled: Option<f32>,
}
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RawLoadCell {
    pub raw: i16,
    pub voltage: f32,
}
#[derive(Debug, PartialEq)]
pub struct RoutedSensors {
    pub pressures: [Option<f64>; 4],
    pub load_cell_1: Option<f64>,
    pub load_cell_2: Option<RawLoadCell>,
}
fn engineering(sample: Sample, valid: bool) -> Option<f64> {
    if !valid {
        return None;
    }
    sample.scaled.filter(|v| v.is_finite()).map(f64::from)
}
pub fn route_sensors(
    mode: RoutingMode,
    adc1: [Sample; 4],
    adc1_valid: bool,
    adc2: [Sample; 4],
    adc2_valid: bool,
) -> RoutedSensors {
    let test = mode == RoutingMode::HybridTest;
    RoutedSensors {
        pressures: std::array::from_fn(|i| engineering(adc1[i], adc1_valid && (i < 2 || test))),
        load_cell_1: engineering(adc2[1], adc2_valid),
        // Never carry scaled data or reuse LC1 calibration for LC2.
        load_cell_2: (test && adc2_valid && adc2[2].voltage.is_finite()).then_some(RawLoadCell {
            raw: adc2[2].raw,
            voltage: adc2[2].voltage,
        }),
    }
}

/// Independent last-commanded output and electrical continuity observations.
#[derive(Debug, Default, Clone, Copy, PartialEq)]
pub struct OutputDiagnostic {
    pub output: Option<bool>,
    pub continuity: Option<bool>,
}
impl OutputDiagnostic {
    pub fn wire_values(self) -> (bool, bool, bool, bool) {
        (
            self.output.unwrap_or(false),
            self.continuity.unwrap_or(false),
            self.output.is_some(),
            self.continuity.is_some(),
        )
    }
}
