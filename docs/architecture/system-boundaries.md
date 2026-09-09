# System boundaries

| System | Owns | Does not own |
| --- | --- | --- |
| FSW | flight state, sensing, actuation sequencing, FSW telemetry | fill, vent, purge, or ground-device automation |
| Fill Station | local fill, timed vent, purge, emergency safing, umbilical endpoint | flight-state decisions |
| Ground Station | operator UI, recording, network device control, non-time-critical commands | time-critical fill or vent timing |
| shared/proto | versioned Ground Station/Fill Station message definitions | FSW wire protocol |

## Integration rule

A subsystem may consume another system's published contract. It may not encode another system's operational responsibility as a local fallback without an approved interface and design review.
