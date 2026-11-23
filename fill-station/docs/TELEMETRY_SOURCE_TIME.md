# MQTT source-frame metadata

Implemented producer increment, November 23, 2026. This adds metadata to MQTT
protobuf and its optional debug JSON. A subsequent compatible consumer increment
now stores metadata, suppresses duplicates and exposes per-session sequence heads;
see [source ingestion](../../docs/operations/telemetry-source-ingestion.md).
Neither increment has been deployed. The existing Grafana queries remain arrival-
based; WebSocket/CSV output, time-server/client configuration and device profiles
are unchanged. Active-session selection and end-to-end view integration are pending.

## Wire contract

Both `fill-station/proto/telemetry.proto` and `ground-station/proto/telemetry.proto`
append fields 67–81. Existing fields 1–66 retain their numbers and interpretation.
A missing/zero `source_metadata_version` identifies a legacy producer.

| Field | Meaning |
| --- | --- |
| `source_metadata_version` | 1 for this producer contract; 0 is legacy |
| `publisher_session_hi`, `publisher_session_lo` | Fresh random 128-bit identity for each publisher-task lifetime |
| `publisher_sequence` | Starts at 1, increases once per assembled frame; never wraps |
| `source_monotonic_ms` | Elapsed milliseconds since this publisher session began |
| `source_unix_ms`, `source_unix_valid` | Frame assembly epoch milliseconds, or invalid/zero when synchronization/epoch is unavailable |
| `source_time_quality` | 0 unknown/unsynchronized; 1 kernel-reported synchronization, reference/UTC accuracy unverified |
| `source_time_generation` | Starts at 1; changes on quality transitions or observed wall-vs-monotonic steps exceeding one second |
| `adc1_sample_age_ms`, `adc1_sample_age_valid` | Age of the last successful completed ADC1 scan |
| `adc2_sample_age_ms`, `adc2_sample_age_valid` | Independent age of the last successful completed ADC2 scan |
| `fsw_receive_age_ms`, `fsw_receive_age_valid` | Age of the copied FSW telemetry's local receive/parse instant; invalid when disconnected/never received |

Time is captured after gathering the frame and before encoding/queueing it. MQTT
reconnection does not assign another sequence/time to the queued bytes. Sequence
gaps can result from encoding/queue/network loss; they are not proof of duplicates.
The binary and optional debug JSON copies refer to the same source frame.

The session value can be displayed as `hi` followed by `lo`, each padded to 16 hex
digits. Its halves and sequence are unsigned 64-bit integers: preserve exact
integers/decimal strings, not JavaScript `Number`. Session IDs are not credentials,
boot counters or sortable timestamps. Sequence ordering is valid within one
session, not globally across restarts. Consumer-side deduplication and active-
session selection still need implementation; do not order sessions by random ID.

A publisher uses `/dev/urandom` once per startup. Entropy/read failure disables
this MQTT task with a diagnostic rather than reusing a fixed session identity.
Sequence or clock-generation exhaustion similarly stops publication before wrap.
The application does not reset the clock, reboot or actuate anything in response.

## Clock quality and freshness boundaries

On Linux, the producer performs a read-only `adjtimex` query (`modes=0`). Failed,
error-state, unsynchronized or clock-error results give quality 0. Other platforms
currently give quality 0. The producer does not set time or discover which server
disciplined it. Quality 1 is **not proof of accurate UTC**, an external reference,
a station-relative error bound or a working Starlink connection.

With unknown quality or a wall time before the UNIX epoch/unrepresentable in the
wire field, `source_unix_valid` is false, `source_unix_ms` is zero and quality is 0.
Consumers must not turn invalid numeric zero into a 1970 event timestamp. Clock
steps and synchronization changes never reset the session sequence. Generation
is a diagnostic for observed transitions/large steps, not a complete clock audit.

ADC ages use monotonic capture instants, independent of wall-clock changes. A
completed four-channel scan is not simultaneous per-channel acquisition. A failed
scan leaves the previous success instant in place while existing reading-validity
bits become false. Consumers must apply those validity bits as well as age: an
old cached sample is not a fresh valid reading merely because a new frame exists.
Unknown age is distinct from a valid zero-millisecond age. FSW age describes local
receipt, not the rocket sensor's acquisition clock; existing FSW uptime is separate.
Do not reconstruct exact historical sample UTC by subtracting age across clock
steps without an appropriate capture-time anchor/provenance.

The legacy ADC wall-clock field now returns zero instead of panicking for a time
before 1970. This does not make that legacy field an ordered source timestamp.

## Software checks

The complete host Cargo suites passed for both Hybrid and Liquid with debug JSON:
64 test/doc-test executions per feature configuration. They cover the new clock
state tests plus existing codec, hardware and command tests. These are host tests
with mocked hardware; they do not compile/test the Linux-only syscall path or
prove a complete ARM image boots.

Five additional Python/schema/real-nanopb-C codec checks passed: exact uint64
round-trip, legacy producer defaults, old-schema consumer compatibility, duplicate
wire tag/schema-copy checks and malformed packet rejection. Run those with:

```sh
uv run --with grpcio-tools==1.76.0 --with protobuf==6.33.0 \
  python -m unittest discover -s tests -p test_source_metadata.py
```

After those tools are cached, add `--offline` to the UV invocation. Cargo uses the
vendored nanopb generator and the same Python tooling; no project dependency or
Cargo lock update is required. Tests open no board, broker or production database
connections and never change the host clock.

## Remaining work and later acceptance

1. Compatible storage/decoding, receipt deduplication and per-session query heads
   are implemented and PostgreSQL-tested. Verify the actual Timescale/EMQX path,
   old/new producer operation and deployed migration. Global active-session
   selection and delayed old-session handling in the UI remain pending.
2. Add the LAN time authority/client and explicit reference-quality/holdover policy.
   Neither system may require WAN or another machine to boot and operate locally.
3. Update event-time/latest-value queries and minimal Grafana status display only
   after compatible ingestion is installed. Keep uncertainty and stale samples
   visible. Extend WebSocket/CSV metadata consistently in the following integration.
4. Build the native ARM/Linux OSPI candidate. On hardware verify kernel status,
   new session after application restart and board reboot, stable session across
   MQTT reconnect, advancing sequence and sample ages, late/lost time synchronization
   and offline behavior. Do not change the production clock just to exercise a test.

The producer increment itself applied no database or hardware changes. The later
SQL migration is now in source, not deployed; no operational clock setting,
dashboard redesign, image flash or hardware acceptance has occurred.


The candidate now runs a supervised BusyBox LAN time client against the station.
This does not establish externally verified UTC or peer freshness; kernel quality
and offline local reference must retain their stated uncertainty. See
[LAN time deployment and acceptance](../../docs/operations/lan-time.md).


Source metadata version 2 now extends version 1 for opt-in Hybrid-test with LC2
raw/voltage/validity and operating-profile code2. Existing producers remain v1;
session/time semantics are unchanged. Migration004 includes extensions in v2
fingerprints without modifying v1 receipts. See
[the v2 contract and acceptance](../../docs/operations/lc2-telemetry.md).
