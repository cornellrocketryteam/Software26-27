#!/usr/bin/env python3
"""Validate operating intent separately from saved physical wiring; never activate it."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
PROFILES = {'hybrid': 'hybrid', 'hybrid-test': 'hybrid', 'liquid': 'liquid'}
CONTROL_KINDS = {'solenoid_valve', 'quick_disconnect', 'igniter', 'ball_valve', 'mav_servo'}


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys()-set(required)-set(optional):
        raise ValueError(f'expected fields {sorted(required)} with optional {sorted(optional)}')


def named(value):
    if not isinstance(value, str) or not re.fullmatch('[a-z][a-z0-9_]{0,47}', value):
        raise ValueError('invalid stable device/sensor ID')
    return value


def unique_ids(values):
    if not isinstance(values, list):
        raise ValueError('expected ID list')
    for value in values:
        named(value)
    if len(values) != len(set(values)):
        raise ValueError('duplicate IDs')
    return set(values)


def profile_digest(profile):
    """Definition digest only; physical wiring identity must be tracked separately."""
    return hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_profile(profile, wiring):
    fields(profile, ('id','label','hardwareProfile','mappingStatus','fswEnabled','controls','sensors',
                     'disabledLocalDeviceIds','unmappedDeviceIds'))
    name = profile['id']
    if not isinstance(name, str) or name not in PROFILES or profile['hardwareProfile'] != PROFILES[name] or wiring.get('profile') != PROFILES[name]:
        raise ValueError('unknown operating profile or mismatched physical wiring family')
    if not isinstance(profile['label'], str) or not profile['label'].strip():
        raise ValueError('profile label required')
    pending = profile['mappingStatus'] == 'pending'
    if profile['mappingStatus'] not in ('specified','pending'):
        raise ValueError('unknown mapping status')
    if pending and (name != 'liquid' or profile['fswEnabled'] is not None):
        raise ValueError('only Liquid may retain explicitly unmapped FSW policy')
    if not pending and (type(profile['fswEnabled']) is not bool or profile['fswEnabled'] != (name == 'hybrid')):
        raise ValueError('invalid FSW policy for operating profile')
    devices = {d['id']: d for d in wiring['devices'] if d['enabled']}
    disabled = unique_ids(profile['disabledLocalDeviceIds'])
    unmapped = unique_ids(profile['unmappedDeviceIds'])
    if (disabled | unmapped)-devices.keys() or disabled & unmapped:
        raise ValueError('disabled/unmapped references must be known, disjoint local devices')
    if not isinstance(profile['controls'], list) or not isinstance(profile['sensors'], list):
        raise ValueError('controls/sensors must be arrays')
    if pending and (profile['controls'] or profile['sensors'] or unmapped != devices.keys()):
        raise ValueError('pending Liquid mapping must enumerate devices without inventing bindings')
    if not pending and unmapped:
        raise ValueError('specified profiles cannot contain unmapped devices')
    ids, local_controls, channels = set(), set(), set()
    for group in ('controls','sensors'):
        for item in profile[group]:
            common = ('id','label','kind','owner','deviceId')
            if group == 'controls':
                fields(item, common+('feedback',), ('energizedAction','deenergizedReconnects'))
            else:
                fields(item, common+('channel','readings','calibrationStatus','calibrationRef','engineeringUnit','range'))
            stable_id = named(item['id'])
            if stable_id in ids:
                raise ValueError('duplicate semantic device/sensor ID')
            ids.add(stable_id)
            if not isinstance(item['label'], str) or not item['label'].strip():
                raise ValueError('device/sensor label required')
            if not isinstance(item['kind'], str):
                raise ValueError('device/sensor kind must be a string')
            owner = item['owner']
            if owner not in ('local','fsw') or (owner == 'fsw' and not profile['fswEnabled']):
                raise ValueError('invalid owner or FSW dependency on standalone profile')
            if owner == 'local':
                device_id = named(item['deviceId'])
                if device_id not in devices or device_id in disabled | unmapped:
                    raise ValueError('local binding references missing/disabled/unmapped device')
                device = devices[device_id]
            elif item['deviceId'] is not None:
                raise ValueError('FSW binding cannot refer to a local device')
            if group == 'controls':
                if item['kind'] not in CONTROL_KINDS or (owner == 'local' and device['type'] != item['kind']):
                    raise ValueError('control kind mismatches physical device')
                if owner == 'local':
                    if device_id in local_controls:
                        raise ValueError('multiple controls target one local device')
                    local_controls.add(device_id)
                expected_feedback = ['commanded_output','continuity'] if item['kind'] in ('solenoid_valve','quick_disconnect','igniter') else ['commanded_output']
                if item['feedback'] != expected_feedback:
                    raise ValueError('unsupported feedback/position claim')
                if item['kind'] == 'quick_disconnect':
                    if owner != 'local' or device.get('role') != 'sv5' or item.get('energizedAction') != 'disconnect' or item.get('deenergizedReconnects') is not False:
                        raise ValueError('QD must be local SV5 disconnect-only solenoid')
                elif 'energizedAction' in item or 'deenergizedReconnects' in item:
                    raise ValueError('QD semantics attached to another control')
            else:
                if item['kind'] not in ('pressure','load_cell'):
                    raise ValueError('unsupported sensor kind')
                if owner == 'local':
                    channel = item['channel']
                    if device['type'] != 'ads1015' or type(channel) is not int or not 0 <= channel <= 3:
                        raise ValueError('sensor needs an ADS1015 input channel 0..3')
                    if (device_id, channel) in channels:
                        raise ValueError('multiple semantic sensors on one local ADC input')
                    channels.add((device_id, channel))
                elif item['channel'] is not None:
                    raise ValueError('FSW sensor cannot claim a local ADC channel')
                readings = item['readings']
                if not isinstance(readings, list) or not readings or not all(isinstance(r,str) and r in ('raw','voltage','engineering') for r in readings) or len(readings) != len(set(readings)):
                    raise ValueError('unsupported/duplicate sensor readings')
                if item['calibrationStatus'] == 'uncalibrated':
                    if readings != ['raw','voltage'] or any(item[k] is not None for k in ('calibrationRef','engineeringUnit','range')):
                        raise ValueError('uncalibrated sensor must remain raw/voltage without engineering claims')
                elif item['calibrationStatus'] != 'existing' or not isinstance(item['calibrationRef'],str) or not item['calibrationRef'] or 'engineering' not in readings:
                    raise ValueError('existing calibration requires provenance and engineering reading')
                if item['engineeringUnit'] is not None and not isinstance(item['engineeringUnit'],str):
                    raise ValueError('invalid engineering unit')
                limits = item['range']
                if limits is not None and (not isinstance(limits,list) or len(limits)!=2 or not all(type(x) in (int,float) and math.isfinite(x) for x in limits) or limits[0]>=limits[1]):
                    raise ValueError('invalid engineering range')
    return profile


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field: {key}')
        result[key] = value
    return result


def load_profiles(path=HERE/'operating-profiles.json'):
    data = json.loads(Path(path).read_text(), object_pairs_hook=no_duplicates)
    fields(data, ('schemaVersion','profiles'))
    if type(data['schemaVersion']) is not int or data['schemaVersion'] != 1 or not isinstance(data['profiles'],dict) or set(data['profiles']) != set(PROFILES):
        raise ValueError('expected operating profile contract version 1 with all three profiles')
    for name, profile in data['profiles'].items():
        if not isinstance(profile,dict) or profile.get('id') != name:
            raise ValueError('operating profile identity mismatch')
        wiring = json.loads((HERE/'profiles'/f'{PROFILES[name]}.json').read_text(), object_pairs_hook=no_duplicates)
        validate_profile(profile, wiring)
    return data['profiles']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES)
    args = parser.parse_args()
    profiles = load_profiles()
    if args.profile:
        profiles = {args.profile: profiles[args.profile]}
    print(json.dumps({'schemaVersion':1,'scope':'definition-only; no firmware/UI activation',
                      'profiles':{name:{'definitionSha256':profile_digest(profile),
                                       'hardwareProfileSha256':profile_digest(json.loads((HERE/'profiles'/f'{profile["hardwareProfile"]}.json').read_text())),
                                       **profile} for name,profile in profiles.items()}}, indent=2))

if __name__ == '__main__': main()
