# Interface governance

This directory records interfaces that cross subsystem boundaries. Keep the source definition and its documentation together.

Every interface change must include:

- schema or protocol version;
- producer and consumer system owners;
- compatibility behavior for older peers;
- a fixture or automated test;
- a linked design-review or meeting decision when behavior changes.

The initial FSW umbilical protocol remains binary. Protobuf schemas belong in `shared/proto/` for Fill Station and Ground Station use unless an FSW owner approves a separately tested exception.
