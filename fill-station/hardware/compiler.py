#!/usr/bin/env python3
"""Compile the shared SK-AM64B hardware profile for Rust, Linux and the editor."""
import argparse
from collections import defaultdict
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
BOARD = json.loads((HERE / 'board-pins.json').read_text())
CATALOG = json.loads((HERE / 'catalog.json').read_text())
PINS = {f'{p["domain"]}:0x{p["offset"]:04x}': p for p in BOARD['pins']}
ROLES = ['ig1', 'ig2', 'adc1', 'adc2', 'sv1', 'sv2', 'sv3', 'sv4', 'sv5', 'mav', 'ball_valve', 'qd_stepper']
ROLE_TYPES = dict(zip(ROLES, ['igniter'] * 2 + ['ads1015'] * 2 + ['solenoid_valve'] * 5 + ['mav_servo', 'ball_valve', 'qd_stepper']))
BUSES = {'main_i2c0': 0, 'main_i2c2': 2, 'main_i2c3': 3, 'mcu_i2c0': 4, 'mcu_i2c1': 5}
_spec = importlib.util.spec_from_file_location('hardware_pinmux', HERE / 'pinmux.py')
pinmux = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pinmux)


def load_profile(name):
    if name not in ('liquid', 'hybrid'):
        raise ValueError('profile must be liquid or hybrid')
    return json.loads((HERE / 'profiles' / f'{name}.json').read_text())


def keys(obj, allowed, required, context):
    if not isinstance(obj, dict):
        raise ValueError(f'{context}: expected an object')
    if set(obj) - set(allowed):
        raise ValueError(f'{context}: unknown fields {sorted(set(obj) - set(allowed))}')
    if set(required) - set(obj):
        raise ValueError(f'{context}: missing fields {sorted(set(required) - set(obj))}')


def identifier(value, context):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', value):
        raise ValueError(f'{context}: use a lowercase ID with letters, digits and underscores (max 48 characters)')
    return value


def compile_profile(profile):
    keys(profile, ['version', 'profile', 'devices', 'buses'], ['version', 'profile', 'devices', 'buses'], 'profile')
    if type(profile['version']) is not int or profile['version'] != 1:
        raise ValueError('unsupported hardware profile version; expected 1')
    if profile['profile'] not in ('liquid', 'hybrid'):
        raise ValueError('profile must be liquid or hybrid')
    if not isinstance(profile['devices'], list) or not isinstance(profile['buses'], list):
        raise ValueError('devices and buses must be arrays')
    groups = defaultdict(list)
    claimed, ids, roles = {}, set(), set()
    runtime = []

    def connection(conn, kind, direction, owner, expected=None, claim=True):
        keys(conn, ['pin', 'function', 'bias', 'schmitt'], ['pin', 'function', 'bias', 'schmitt'], owner)
        pin_id = conn['pin']
        if not isinstance(pin_id, str) or pin_id not in PINS:
            raise ValueError(f'{owner}: pin {pin_id!r} is protected or outside managed pads')
        pin = PINS[pin_id]
        function = conn['function']
        if not isinstance(function, str) or function not in pin['functions']:
            raise ValueError(f'{owner}: invalid function mapping {function!r} on {pin_id}')
        actual_kind, controller, member = pinmux.classify(function)
        if actual_kind != kind or expected and function != expected:
            raise ValueError(f'{owner}: expected {expected or kind}, got function {function}')
        bias = conn['bias']
        if bias not in ('none', 'pull-up', 'pull-down') or type(conn['schmitt']) is not bool:
            raise ValueError(f'{owner}: invalid bias or schmitt setting')
        if (pin['domain'], pin['offset']) in [('main', 0x260), ('main', 0x264), ('mcu', 0x48), ('mcu', 0x4c)] and bias != 'none':
            raise ValueError(f'{owner}: dedicated open-drain pad has no internal pull')
        if claim:
            if pin_id in claimed:
                raise ValueError(f'duplicate pad {pin_id}: claimed by {claimed[pin_id]} and {owner}')
            claimed[pin_id] = owner
            flag = 'PIN_INPUT' if direction == 'input' else 'PIN_OUTPUT'
            if bias == 'pull-up': flag += '_PULLUP'
            if bias == 'pull-down': flag += '_PULLDOWN'
            if conn['schmitt']: flag += '|PIN_SCMITT_TRIGGER_ENABLE'
            macro = 'AM64X_MCU_IOPAD' if pin['domain'] == 'mcu' else 'AM64X_IOPAD'
            group = 'config_' + (controller if kind != 'gpio' else pin['domain'] + '_gpio')
            groups[(pin['domain'], group)].append(f'{macro}(0x{pin["offset"]:04x}, {flag}, {pin["functions"][function]}) /* ({pin["ball"]}) {pin["pad"]}.{function} */')
        if kind == 'gpio':
            chip = 'gpiochip0' if controller == 'mcu_gpio0' else 'gpiochip1' if controller == 'main_gpio0' else 'gpiochip2'
            return {'chip': chip, 'line': int(function.rsplit('_', 1)[1])}
        if kind == 'pwm':
            return {'device': f'{0x23000000 + int(controller[4:]) * 0x10000:x}.pwm', 'channel': 0 if member == 'A' else 1}
        return controller

    buses = {}
    controllers = set()
    for bus in profile['buses']:
        keys(bus, ['id', 'controller', 'connections'], ['id', 'controller', 'connections'], 'bus')
        bus_id = identifier(bus['id'], 'bus id')
        if bus_id in buses: raise ValueError(f'duplicate bus id {bus_id}')
        controller = bus['controller']
        if not isinstance(controller, str) or controller not in BUSES: raise ValueError(f'unsupported I2C controller {controller!r}')
        if controller == 'main_i2c0' and profile['profile'] != 'liquid':
            raise ValueError('main_i2c0 is protected outside Liquid')
        if controller in controllers: raise ValueError(f'I2C controller {controller} needs one shared bus definition')
        controllers.add(controller)
        keys(bus['connections'], ['scl','sda'], ['scl','sda'], bus_id)
        prefix = controller.upper().replace('MAIN_', '')
        for port in ('scl', 'sda'):
            connection(bus['connections'][port], 'i2c', 'input', f'{bus_id}.{port}', f'{prefix}_{port.upper()}', claim=False)
        buses[bus_id] = bus

    if profile['profile'] == 'liquid' and 'main_i2c0' not in controllers:
        raise ValueError('Liquid requires its shared I2C0 bus on PRU pins 6/8')
    addresses = set()
    active_buses = {bid for bid,b in buses.items() if b['controller']=='main_i2c0'}
    for device in profile['devices']:
        keys(device, ['id','type','role','enabled','connections','settings','bus','address'], ['id','type','role','enabled','connections','settings'], 'device')
        name = identifier(device['id'], 'device id')
        if name in ids: raise ValueError(f'duplicate device id {name}')
        ids.add(name)
        dtype = device['type']
        if not isinstance(dtype, str) or dtype not in CATALOG: raise ValueError(f'{name}: unsupported device type {dtype!r}')
        if type(device['enabled']) is not bool: raise ValueError(f'{name}: enabled must be a boolean')
        enabled = device['enabled']
        role = device['role']
        if role is not None:
            if not isinstance(role,str) or ROLE_TYPES.get(role) != dtype: raise ValueError(f'{name}: invalid role {role!r} for {dtype}')
            if role in roles: raise ValueError(f'duplicate application role {role}')
            roles.add(role)
        spec = CATALOG[dtype]
        keys(device['connections'], spec['ports'], spec['ports'], f'{name} connections')
        keys(device['settings'], spec['settings'], [], f'{name} settings')
        settings = {}
        for key, setting in spec['settings'].items():
            value = device['settings'].get(key, setting['default'])
            if value not in setting['choices']: raise ValueError(f'{name}: invalid setting {key}: {value!r}')
            settings[key] = value
        resolved = dict(id=name, type=dtype, role=role, settings=settings, connections={})
        for port, definition in spec['ports'].items():
            value = connection(device['connections'][port], definition['kind'], definition['direction'], f'{name}.{port}', claim=enabled)
            if definition['kind'] == 'pwm': resolved['pwm'] = value
            else: resolved['connections'][port] = value
        if dtype == 'ads1015':
            bus_id = device.get('bus')
            if not isinstance(bus_id, str) or bus_id not in buses: raise ValueError(f'{name}: select a defined I2C bus')
            address = device.get('address')
            if buses[bus_id]['controller']=='main_i2c0' and address in BOARD['shared_i2c0']['reserved_addresses']:
                raise ValueError(f'{name}: address {address:#x} is reserved for onboard devices')
            if type(address) is not int or not 0x48 <= address <= 0x4b: raise ValueError(f'{name}: ADS1015 address must be 0x48–0x4b')
            if enabled:
                pair = bus_id, address
                if pair in addresses: raise ValueError(f'duplicate I2C address {address:#x} on {bus_id}')
                addresses.add(pair); active_buses.add(bus_id)
            resolved.update(bus=f'/dev/i2c-{BUSES[buses[bus_id]["controller"]]}', address=address)
        elif 'bus' in device or 'address' in device:
            raise ValueError(f'{name}: bus/address are only supported for ADS1015')
        if enabled: runtime.append(resolved)

    for bus_id in sorted(active_buses):
        bus = buses[bus_id]
        prefix = bus['controller'].upper().replace('MAIN_', '')
        for port in ('scl', 'sda'):
            connection(bus['connections'][port], 'i2c', 'input', f'{bus_id}.{port}', f'{prefix}_{port.upper()}')

    # These are board policy, never writable device records.
    for pin_id, function, direction, bias in [('main:0x0164','GPIO1_1','input','none'), ('main:0x02a8','USB0_DRVVBUS','output','none')]:
        connection(dict(pin=pin_id,function=function,bias=bias,schmitt=True), 'gpio' if function.startswith('GPIO') else 'usb', direction, 'board.' + function)
    # Preserve TI's existing Schmitt setting on every idle pad as well as active pads.
    for pin_id, pin in PINS.items():
        if pin['idle'] and pin_id not in claimed:
            flag = 'PIN_INPUT' if pin['idle_bias'] == 'none' else 'PIN_INPUT_PULLDOWN'
            macro = 'AM64X_MCU_IOPAD' if pin['domain'] == 'mcu' else 'AM64X_IOPAD'
            groups[(pin['domain'], 'idle' + pin['domain'] + '_pins_default')].append(f'{macro}(0x{pin["offset"]:04x}, {flag}|PIN_SCMITT_TRIGGER_ENABLE, {pin["functions"][pin["gpio"]]}) /* ({pin["ball"]}) {pin["pad"]}.{pin["gpio"]} */')
    text = '\n'.join(f'&{domain}_pmx0 {{ {group}: {group.replace("_", "-")} {{ pinctrl-single,pins = <' + '\n'.join(rows) + '>; }; };' for (domain, group), rows in groups.items())
    result = pinmux.generate(text, profile=profile['profile'])
    result['runtime'] = {'version': 1, 'profile': profile['profile'], 'devices': runtime, 'configured_devices_mask': sum(1 << ROLES.index(d['role']) for d in runtime if d['role'])}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=['liquid','hybrid','none'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.profile == 'none':
            result = {'runtime': {'version':1,'profile':'none','devices':[],'configured_devices_mask':0}}
        else:
            result = compile_profile(load_profile(args.profile))
        args.output.mkdir(parents=True, exist_ok=True)
        for name, key in [('hardware-pinmux.dtsi','pins'), ('k3-am64-fillstation-pinmux-overlay.dts','overlay')]:
            if key in result: (args.output / name).write_text(result[key])
        for name, key in [('pinmux-report.json','report'), ('expectations.json','expectations'), ('hardware-runtime.json','runtime')]:
            if key in result: (args.output / name).write_text(json.dumps(result[key],indent=2)+'\n')
        runtime_json = json.dumps(result['runtime'], separators=(',', ':'))
        (args.output / 'hardware_config.rs').write_text('pub const HARDWARE_CONFIG_JSON: &str = ' + json.dumps(runtime_json) + ';\n')
    except (ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'hardware configuration error: {exc}\n')

if __name__ == '__main__': main()
