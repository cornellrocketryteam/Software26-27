"""Conservative preflight routing; build failures are never reclassified/retried."""
from pathlib import Path
from .config import endpoint, number
from .runtime import PlatformError, json_response, run
from .receipts import identity

SYSTEMS = ('aarch64-linux', 'x86_64-linux')


def local_health(config, platform):
    timeout = number(config, 'probeTimeoutSeconds', 10, 60)
    run(['nix', 'store', 'ping', '--json'], timeout=timeout)
    settings = json_response(run(['nix', 'config', 'show', '--json'], timeout=timeout), 'Nix settings')
    def value(key, default):
        entry = settings.get(key, {})
        return entry.get('value', default) if isinstance(entry, dict) else default
    systems = [value('system', '')] + value('extra-platforms', [])
    if platform in systems and value('max-jobs', 1) != 0:
        return 'local daemon advertises compatible execution'
    # Preserve Determinate external builders. Presence is declared capability, not a live VM benchmark.
    for builder in value('external-builders', []):
        if isinstance(builder, dict) and platform in builder.get('systems', []):
            return 'configured external builder advertises platform (runtime not yet proven)'
    # Other SSH workers are deliberately not inherited: they can make a missing station mandatory.
    raise PlatformError(f'local has no compatible {platform} native/external builder; configure the accepted Linux VM')


def probe_station(config):
    """Read-only observation; never sets validation or authorizes a build."""
    station = config.get('station', {})
    _, target, options = endpoint(station)
    timeout = number(config, 'probeTimeoutSeconds', 10, 60)
    health = json_response(run(['ssh', *options, '--', target, 'crt-platform-builder-health-v1'], timeout=timeout), 'station health')
    free = health.get('freeBytes') if isinstance(health, dict) else None
    platforms = health.get('platforms') if isinstance(health, dict) else None
    if (not isinstance(health, dict) or type(health.get('protocol')) is not int or health['protocol'] != 1
            or type(health.get('available')) is not bool
            or health.get('operationalMode') not in ('maintenance', 'field', 'unknown')
            or type(free) is not int or free < 0 or not isinstance(platforms, list)
            or not all(isinstance(p, str) and p in SYSTEMS for p in platforms)
            or len(platforms) != len(set(platforms))):
        raise PlatformError('invalid station health protocol/capacity/platform response')
    if health.get('workerId') is not None:
        identity(health['workerId'], 'station worker identity')
    elif 'workerId' in health and health['available']:
        raise PlatformError('available station has no worker identity')
    if 'workerId' in station:
        identity(station['workerId'], 'configured station worker identity')
        if health.get('workerId') != station['workerId']:
            raise PlatformError('station worker identity does not match pinned configuration')
    return health


def station_health(config, platform):
    station = config.get('station', {})
    platforms = station.get('platforms', [])
    if (station.get('validated') is not True or not isinstance(platforms, list)
            or not all(isinstance(p, str) and p in SYSTEMS for p in platforms)
            or len(platforms) != len(set(platforms)) or platform not in platforms):
        raise PlatformError(f'station requires validated capability for {platform}; disabled by default')
    health = probe_station(config)
    free = health['freeBytes']
    minimum = station.get('minFreeBytes', 100_000_000_000)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
        raise PlatformError('station.minFreeBytes must be a nonnegative integer')
    if (health.get('available') is not True
            or health.get('operationalMode') != 'maintenance' or platform not in health.get('platforms', [])
            or isinstance(free, bool) or not isinstance(free, int) or free < minimum):
        raise PlatformError('station unavailable: incompatible, busy, field mode, or insufficient free space; '
                            + str(health.get('reason', 'health preflight rejected')))
    return 'validated station passed bounded maintenance/capacity preflight'


def select(config, requested, platform, offline):
    if offline and requested == 'station':
        raise PlatformError('--offline cannot use --builder station')
    if requested != 'auto':
        reason = local_health(config, platform) if requested == 'local' else station_health(config, platform)
        return requested, reason
    order = ['station', 'local'] if config.get('policy', {}).get('preferStation') is True and not offline else ['local', 'station']
    errors = []
    for worker in order:
        if worker == 'station' and offline:
            continue
        try:
            reason = local_health(config, platform) if worker == 'local' else station_health(config, platform)
            return worker, '; '.join(errors + [reason])
        except PlatformError as exc:
            errors.append(f'{worker} preflight: {exc}')
    raise PlatformError('; '.join(errors))
