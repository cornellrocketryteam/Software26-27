//! Generates nanopb C code from proto/telemetry.proto, compiles it together with
//! the nanopb runtime and the csrc/ wrapper, and emits Rust bindings for the
//! wrapper into OUT_DIR/telemetry_bindings.rs.

use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;

/// Adds `#[derive(serde::Serialize)]` to TelemetryPayload (debug-json feature only).
#[derive(Debug)]
struct SerializeDerive;

impl bindgen::callbacks::ParseCallbacks for SerializeDerive {
    fn add_derives(&self, info: &bindgen::callbacks::DeriveInfo<'_>) -> Vec<String> {
        // nanopb emits `typedef struct _TelemetryPayload { ... } TelemetryPayload;`
        if info.name == "_TelemetryPayload" {
            vec!["serde::Serialize".into()]
        } else {
            vec![]
        }
    }
}

/// nanopb source tree (runtime C files + generator). Nix provides it through
/// $NANOPB_DIR (crt.nanopb-src); otherwise fall back to a local ./vendor/nanopb.
fn nanopb_dir(manifest_dir: &Path) -> PathBuf {
    let dir = env::var_os("NANOPB_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| manifest_dir.join("vendor/nanopb"));
    assert!(
        dir.join("pb.h").exists(),
        "nanopb not found at {} (set NANOPB_DIR, e.g. by using `nix develop`, \
         or clone nanopb 0.4.9.2 into fill-station/vendor/nanopb)",
        dir.display()
    );
    dir
}

/// Python used to run the nanopb generator. It needs the `protobuf` package, plus
/// either grpcio-tools or a matching `protoc` on PATH (Nix provides the latter).
/// Order: $NANOPB_PYTHON, then ./.venv/bin/python, then python3 on PATH.
fn python(manifest_dir: &Path) -> PathBuf {
    if let Some(p) = env::var_os("NANOPB_PYTHON") {
        return p.into();
    }
    let venv = manifest_dir.join(".venv/bin/python");
    if venv.exists() {
        return venv;
    }
    "python3".into()
}

fn main() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let nanopb = nanopb_dir(&manifest_dir);
    let proto_dir = manifest_dir.join("proto");
    let proto = proto_dir.join("telemetry.proto");
    let csrc = manifest_dir.join("csrc");

    println!("cargo:rerun-if-changed={}", proto.display());
    println!("cargo:rerun-if-changed={}", csrc.join("telemetry_codec.h").display());
    println!("cargo:rerun-if-changed={}", csrc.join("telemetry_codec.c").display());
    println!("cargo:rerun-if-changed={}", nanopb.join("pb.h").display());
    println!("cargo:rerun-if-env-changed=NANOPB_PYTHON");
    println!("cargo:rerun-if-env-changed=NANOPB_DIR");

    // 1. Generate telemetry.pb.c / telemetry.pb.h into OUT_DIR
    let python = python(&manifest_dir);
    let status = Command::new(&python)
        .arg(nanopb.join("generator/nanopb_generator.py"))
        .arg("-I")
        .arg(&proto_dir)
        .arg("-D")
        .arg(&out_dir)
        .arg(&proto)
        .status()
        .unwrap_or_else(|e| panic!("failed to run nanopb generator with {}: {e}", python.display()));
    assert!(
        status.success(),
        "nanopb generator failed (does {} have protobuf installed, and grpcio-tools or protoc available?)",
        python.display()
    );

    // 2. Compile nanopb runtime + generated code + wrapper
    cc::Build::new()
        .include(&nanopb)
        .include(&out_dir)
        .include(&csrc)
        .file(nanopb.join("pb_common.c"))
        .file(nanopb.join("pb_encode.c"))
        .file(nanopb.join("pb_decode.c"))
        .file(out_dir.join("telemetry.pb.c"))
        .file(csrc.join("telemetry_codec.c"))
        .compile("telemetry_nanopb");

    // 3. Rust bindings for the wrapper
    let mut builder = bindgen::Builder::default()
        .header(csrc.join("telemetry_codec.h").to_string_lossy())
        .clang_arg(format!("-I{}", nanopb.display()))
        .clang_arg(format!("-I{}", out_dir.display()))
        .allowlist_type("TelemetryPayload")
        .allowlist_function("telemetry_encode")
        .allowlist_function("telemetry_decode")
        .allowlist_var("TelemetryPayload_size")
        .derive_default(true)
        .derive_partialeq(true);
    if env::var_os("CARGO_FEATURE_DEBUG_JSON").is_some() {
        builder = builder.parse_callbacks(Box::new(SerializeDerive));
    }
    builder
        .generate()
        .expect("bindgen failed on telemetry_codec.h")
        .write_to_file(out_dir.join("telemetry_bindings.rs"))
        .expect("failed to write telemetry_bindings.rs");
}
