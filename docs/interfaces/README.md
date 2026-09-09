# Interface governance

This directory records interfaces that cross subsystem boundaries. Keep the source definition and its documentation together.

Every interface change must include:

- schema or protocol version;
- producer and consumer system owners;
- compatibility behavior for older peers;
- a fixture or automated test;
- a linked design-review or meeting decision when behavior changes.

The initial FSW umbilical protocol remains binary. Protobuf schemas belong in `shared/proto/` for Fill Station and Ground Station use unless an FSW owner approves a separately tested exception.

## Hybrid/Liquid interface rule

This rule applies to interfaces used by both FSW and Fill Station software. Every command, telemetry field, sensor, actuator, and operational transition must state whether it applies to Hybrid, Liquid, or both. FSW and Fill Station do not have to implement the separation in the same way, but neither may silently treat a vehicle-specific contract as universal.

When a shared interface has vehicle-specific fields or states, document the compatibility behavior for the other vehicle. A change must include the affected-variant test or deployment validation and must not require the other vehicle to accept an unsupported command merely because the message is shared.
