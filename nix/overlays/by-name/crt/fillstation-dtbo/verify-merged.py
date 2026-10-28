#!/usr/bin/env python3
"""Check pin values AND consumer attachments after merging with the real board DTB."""
import json
from pathlib import Path
import subprocess
import sys


def verify(dtb, expectations):
    def get(path, prop, hexadecimal=False):
        args = ['fdtget'] + (['-tx'] if hexadecimal else []) + [str(dtb), path, prop]
        return subprocess.check_output(args, text=True).strip()

    def symbol(name):
        return get('/__symbols__', name)

    group_pins = {}
    for pin in expectations['pins']:
        group_pins.setdefault(pin['group'], []).extend([pin['offset'], pin['value']])
    for group, expected in group_pins.items():
        actual = [int(cell, 16) for cell in get(symbol(group), 'pinctrl-single,pins', True).split()]
        if actual != expected:
            raise ValueError(f'{group}: expected {expected}, got {actual}')
    for controller, expected in expectations['controllers'].items():
        actual = get(symbol(controller), 'status')
        if actual != expected:
            raise ValueError(f'{controller}: expected status {expected}, got {actual}')
    for consumer, groups in expectations['pinctrl'].items():
        if not groups:
            continue
        name = consumer.replace('gpio:', '') + '_pmx0' if consumer.startswith('gpio:') else consumer
        actual = [int(cell, 16) for cell in get(symbol(name), 'pinctrl-0', True).split()]
        expected = [int(get(symbol(group), 'phandle', True), 16) for group in groups]
        if actual != expected:
            raise ValueError(f'{name}: pinctrl-0 does not attach the selected pin groups')
    for controller, lines in expectations['idle_gpio_lines'].items():
        for line in lines:
            path = symbol(controller) + f'/idle_line_{line}'
            get(path, 'gpio-hog')
            get(path, 'input')
            properties = subprocess.check_output(['fdtget', '-p', str(dtb), path], text=True).split()
            if 'output-high' in properties or 'output-low' in properties:
                raise ValueError(f'{controller} line {line}: idle hog must not drive an output')
            if get(path, 'gpios', True) != f'{line:x} 0':
                raise ValueError(f'{controller} line {line}: incorrect idle GPIO line')
    alias_paths = {
        'i2c0': 'main_i2c0', 'i2c2': 'main_i2c2', 'i2c3': 'main_i2c3',
        'i2c4': 'mcu_i2c0', 'i2c5': 'mcu_i2c1',
    }
    for alias, controller in alias_paths.items():
        if get('/aliases', alias) != symbol(controller):
            raise ValueError(f'{alias}: does not identify {controller}')
    eeprom = symbol('main_i2c0') + '/eeprom@51'
    if get(eeprom, 'reg', True) != '51' or get(eeprom, 'compatible') != 'atmel,24c512':
        raise ValueError('shared I2C0 board EEPROM was changed')
    print(f'Pinmux verified: {len(expectations["pins"])} pads, '
          f'{len(expectations["controllers"])} controller states, consumer attachments')


if __name__ == '__main__':
    try:
        verify(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()))
    except (ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f'DTB pinmux check failed: {exc}')
