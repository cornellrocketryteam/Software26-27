use fill_station::operating_runtime::{RoutingMode, Sample, route_sensors};
fn samples() -> [Sample; 4] {
    std::array::from_fn(|i| Sample {
        raw: i as i16 + 100,
        voltage: i as f32 + 0.1,
        scaled: Some(i as f32 + 1000.0),
    })
}
#[test]
fn test_stand_routes_all_local_pressures_and_uncalibrated_lc2() {
    let routed = route_sensors(RoutingMode::HybridTest, samples(), true, samples(), true);
    assert_eq!(
        routed.pressures,
        [Some(1000.0), Some(1001.0), Some(1002.0), Some(1003.0)]
    );
    assert_eq!(routed.load_cell_1, Some(1001.0));
    assert_eq!(routed.load_cell_2.unwrap().raw, 102);
    assert_eq!(routed.load_cell_2.unwrap().voltage, 2.1);
    assert!(!RoutingMode::HybridTest.fsw_enabled());
}
#[test]
fn hybrid_never_relabels_local_spare_channels_as_fsw_sensors() {
    let routed = route_sensors(RoutingMode::Hybrid, samples(), true, samples(), true);
    assert_eq!(routed.pressures, [Some(1000.0), Some(1001.0), None, None]);
    assert!(routed.load_cell_2.is_none());
    assert!(RoutingMode::Hybrid.fsw_enabled());
    assert!(RoutingMode::Legacy.fsw_enabled());
}
#[test]
fn failed_adcs_and_nonfinite_values_are_unavailable_not_zero_measurements() {
    let mut a = samples();
    a[0].scaled = Some(f32::NAN);
    a[1].scaled = None;
    let mut b = samples();
    b[2].voltage = f32::INFINITY;
    let routed = route_sensors(RoutingMode::HybridTest, a, true, b, true);
    assert_eq!(routed.pressures, [None, None, Some(1002.0), Some(1003.0)]);
    assert!(routed.load_cell_2.is_none());
    let invalid = route_sensors(RoutingMode::HybridTest, a, false, b, false);
    assert_eq!(invalid.pressures, [None; 4]);
    assert!(invalid.load_cell_1.is_none());
    assert!(invalid.load_cell_2.is_none());
}
#[test]
fn mode_parsing_keeps_old_images_compatible_and_rejects_unknown_names() {
    assert_eq!(RoutingMode::parse(None), Some(RoutingMode::Legacy));
    assert_eq!(
        RoutingMode::parse(Some("hybrid-test")),
        Some(RoutingMode::HybridTest)
    );
    assert_eq!(RoutingMode::parse(Some("liquid")), None);
}

#[test]
fn hardware_configuration_checks_profile_family_and_preserves_legacy() {
    use fill_station::hardware::HardwareConfig;
    for selector in ["hybrid", "hybrid-test"] {
        let json = format!(
            r#"{{"version":1,"profile":"hybrid","operating_profile":"{selector}","configured_devices_mask":0,"devices":[]}}"#
        );
        let config = HardwareConfig::parse(&json).unwrap();
        let hw = smol::block_on(fill_station::hardware::Hardware::from_config(config)).unwrap();
        assert_eq!(hw.routing_mode, RoutingMode::parse(Some(selector)).unwrap());
        assert!(
            HardwareConfig::parse(
                &json.replace("\"profile\":\"hybrid\"", "\"profile\":\"liquid\"")
            )
            .is_err()
        );
    }
    let json = r#"{"version":1,"profile":"liquid","configured_devices_mask":0,"devices":[]}"#;
    assert!(HardwareConfig::parse(json).is_ok());
    let unknown = json.replace(
        "\"devices\":[]",
        "\"operating_profile\":\"unknown\",\"devices\":[]",
    );
    assert!(HardwareConfig::parse(&unknown).is_err());
}

#[cfg(not(any(target_os = "linux", target_os = "android")))]
#[test]
fn compiler_output_initializes_matching_mock_runtime_and_device_roles() {
    use fill_station::hardware::{Hardware, HardwareConfig};
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("hardware");
    for name in ["hybrid", "hybrid-test"] {
        let script = "import compiler,json,sys; print(json.dumps(compiler.compile_operating_profile(sys.argv[1])['runtime']))";
        let output = std::process::Command::new("python3")
            .args(["-c", script, name])
            .current_dir(&source)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let config = HardwareConfig::parse(std::str::from_utf8(&output.stdout).unwrap()).unwrap();
        let hardware = smol::block_on(Hardware::from_config(config)).unwrap();
        assert_eq!(
            hardware.routing_mode,
            RoutingMode::parse(Some(name)).unwrap()
        );
        assert_eq!(hardware.has_role("sv2"), name == "hybrid-test");
        assert_eq!(hardware.has_role("mav"), name == "hybrid-test");
        assert!(!hardware.has_role("sv3"));
        assert!(!hardware.has_role("sv4"));
        assert!(hardware.has_role("sv5"));
    }
}

#[test]
fn telemetry_identity_distinguishes_operating_modes_without_relabelling_legacy() {
    assert_eq!(RoutingMode::Legacy.telemetry_identity(), (1, 0));
    assert_eq!(RoutingMode::Hybrid.telemetry_identity(), (2, 1));
    assert_eq!(RoutingMode::HybridTest.telemetry_identity(), (2, 2));
}
