/*
 * Thin C wrapper around nanopb for TelemetryPayload.
 *
 * nanopb's message init values and field descriptors (TelemetryPayload_fields,
 * TelemetryPayload_init_zero, ...) are C macros, which Rust cannot call through
 * FFI. These two plain functions hide them.
 */
#ifndef TELEMETRY_CODEC_H
#define TELEMETRY_CODEC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "telemetry.pb.h"

/*
 * Encode `msg` into `buf` (capacity `buf_len`). On success, stores the number
 * of bytes written in `bytes_written` and returns true. Size `buf` with
 * TelemetryPayload_size (from telemetry.pb.h) to guarantee it fits.
 */
bool telemetry_encode(const TelemetryPayload *msg, uint8_t *buf, size_t buf_len, size_t *bytes_written);

/*
 * Decode `len` bytes from `buf` into `out`. Returns false on malformed input.
 */
bool telemetry_decode(const uint8_t *buf, size_t len, TelemetryPayload *out);

#endif /* TELEMETRY_CODEC_H */
