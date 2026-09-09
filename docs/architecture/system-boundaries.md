# System boundaries

| System | Owns | Does not own |
| --- | --- | --- |
| FSW | flight state, sensing, actuation sequencing, FSW telemetry | fill, vent, purge, or ground-device automation |
| Fill Station | local fill, timed vent, purge, emergency safing, umbilical endpoint | flight-state decisions |
| Ground Station | operator UI, recording, network device control, non-time-critical commands | time-critical fill or vent timing |
| shared/proto | versioned Ground Station/Fill Station message definitions | FSW wire protocol |

## Integration rule

A subsystem may consume another system's published contract. It may not encode another system's operational responsibility as a local fallback without an approved interface and design review.

## Hybrid/Liquid conditional development

The Hybrid/Liquid separation is a repository-wide requirement for both FSW and Fill Station software. The implementation mechanism can differ by system:

| Area | Shared requirement | Suitable implementation boundary |
| --- | --- | --- |
| FSW | Hybrid and Liquid behavior cannot be selected accidentally at runtime or by an undocumented build choice. Both vehicle variants must compile and be tested. | Cargo features or an equivalent compile-time configuration, with mutually exclusive vehicle selections and shared common modules. |
| Fill Station | Hybrid and Liquid pad behavior, devices, and operational sequences must remain explicit and independently valid. | Separate services, device/deployment profiles, or typed configuration selected by the deployment; use the mechanism that matches the final pad architecture. |

For every change, the pull request must state `Hybrid`, `Liquid`, or `both`, identify the affected hardware and interfaces, and show validation for every affected variant. Shared code is appropriate for genuinely shared behavior; vehicle-specific code or configuration must stay behind a named boundary rather than being copied invisibly into the other variant.
