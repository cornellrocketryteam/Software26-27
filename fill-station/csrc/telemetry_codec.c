#include "telemetry_codec.h"

#include <pb_decode.h>
#include <pb_encode.h>

bool telemetry_encode(const TelemetryPayload *msg, uint8_t *buf, size_t buf_len, size_t *bytes_written)
{
    pb_ostream_t stream = pb_ostream_from_buffer(buf, buf_len);
    if (!pb_encode(&stream, TelemetryPayload_fields, msg)) {
        return false;
    }
    *bytes_written = stream.bytes_written;
    return true;
}

bool telemetry_decode(const uint8_t *buf, size_t len, TelemetryPayload *out)
{
    TelemetryPayload msg = TelemetryPayload_init_zero;
    pb_istream_t stream = pb_istream_from_buffer(buf, len);
    if (!pb_decode(&stream, TelemetryPayload_fields, &msg)) {
        return false;
    }
    *out = msg;
    return true;
}
