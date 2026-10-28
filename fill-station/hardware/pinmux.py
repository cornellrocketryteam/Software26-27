#!/usr/bin/env python3
"""Render validated IOPAD groups into an SK-AM64B fill-station overlay.

Only the documented GPIO/I2C/ePWM/USB subset is accepted. Never apply TI's
whole-device *_notconf groups: those include DDR, Ethernet and boot pads.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

BOARD = json.loads(Path(__file__).with_name('board-pins.json').read_text())
PINS = {(p['domain'], p['offset']): p for p in BOARD['pins']}
FLAGS = {
    'PIN_OUTPUT': 0x10000, 'PIN_OUTPUT_PULLUP': 0x20000,
    'PIN_OUTPUT_PULLDOWN': 0, 'PIN_INPUT': 0x50000,
    'PIN_INPUT_PULLUP': 0x60000, 'PIN_INPUT_PULLDOWN': 0x40000,
    'PIN_DEBOUNCE_DISABLE': 0, 'PIN_DRIVE_STRENGTH_NOMINAL': 0,
    'PIN_DRIVE_STRENGTH_HIGH': 1 << 19,
    'PIN_SCMITT_TRIGGER_ENABLE': 1 << 14,
    'PIN_SCMITT_TRIGGER_DISABLE': 0,
}
GROUP = re.compile(r'(?P<label>\w+)\s*:\s*[\w-]+\s*\{\s*pinctrl-single,pins\s*=\s*<(?P<cells>.*?)>\s*;\s*\};', re.S)
CELL = re.compile(r'AM64X(?P<mcu>_MCU)?_IOPAD\(\s*(?P<offset>0x[\da-fA-F]+),\s*(?P<flags>[\w|\s]+),\s*(?P<mode>\d+)\s*\)\s*/\*\s*\((?P<ball>\w+)\)\s*(?P<signal>[^\s*]+)[^*]*\*/')
CONTROLLERS = ([f'main_i2c{i}' for i in (0, 2, 3)] +
               [f'mcu_i2c{i}' for i in range(2)] +
               [f'epwm{i}' for i in range(9)])


def pin_value(flags, mode):
    value = mode
    terms = flags.split('|')
    if len([t for t in terms if t.strip().startswith(('PIN_INPUT', 'PIN_OUTPUT'))]) != 1:
        raise ValueError(f'expected exactly one input/output flag: {flags}')
    for term in terms:
        if term.strip() not in FLAGS:
            raise ValueError(f'unsupported pin flag {term.strip()}')
        value |= FLAGS[term.strip()]
    return value


def classify(signal):
    if re.fullmatch(r'(?:MCU_)?GPIO\d+_\d+', signal):
        controller = ('mcu_' if signal.startswith('MCU_') else 'main_') + 'gpio' + signal.split('GPIO')[1].split('_')[0]
        return 'gpio', controller, None
    if m := re.fullmatch(r'(MCU_)?I2C(\d+)_(SCL|SDA)', signal):
        return 'i2c', ('mcu_' if m[1] else 'main_') + 'i2c' + m[2], m[3]
    if m := re.fullmatch(r'EHRPWM(\d+)_([AB])', signal):
        return 'pwm', 'epwm' + m[1], m[2]
    if signal == 'USB0_DRVVBUS':
        return 'usb', 'usb0', None
    raise ValueError(f'unsupported peripheral signal {signal}; supported: GPIO, I2C, ePWM, USB0_DRVVBUS (SPI is out of scope)')


def generate(text, profile='hybrid'):
    groups = []
    claimed = {}
    labels = set()
    expectations = []
    consumers = defaultdict(list)
    bus_signals = defaultdict(list)
    gpio_controllers = set()
    idle_gpio_lines = defaultdict(set)
    report = {'assignments': [], 'idle': [], 'protected': BOARD['protected'], 'idle_exceptions': BOARD['idle_exceptions']}
    matches = list(GROUP.finditer(text))
    # Reject malformed or unfamiliar output instead of returning an empty overlay.
    residue = GROUP.sub('', text)
    residue = re.sub(r'/\*.*?\*/', '', residue, flags=re.S)
    residue = re.sub(r'&(main|mcu)_pmx0\s*\{|\}\s*;', '', residue)
    if residue.strip():
        raise ValueError('unsupported IOPAD DTSI format; cannot parse all pin groups')
    for match in matches:
        label = match['label']
        if '_notconf' in label:
            continue
        if label in labels:
            raise ValueError(f'duplicate pin-group label {label}')
        labels.add(label)
        rows = list(CELL.finditer(match['cells']))
        if not rows or CELL.sub('', match['cells']).strip():
            raise ValueError(f'cannot parse pin cells in {label}')
        group_consumers = set()
        group_domains = set()
        for row in rows:
            domain = 'mcu' if row['mcu'] else 'main'
            offset, mode = int(row['offset'], 16), int(row['mode'])
            flags = re.sub(r'\s+', '', row['flags'])
            # TI comments use PAD.FUNCTION; dedicated pins use FUNCTION alone.
            signal = row['signal'].rsplit('.', 1)[-1]
            kind, controller, member = classify(signal)
            key = domain, offset
            if key not in PINS:
                raise ValueError(f'{domain} pad {offset:#x} is protected or outside managed header pads')
            pin = PINS[key]
            if pin['functions'].get(signal) != mode:
                raise ValueError(f'invalid mux mapping {domain} {offset:#x} -> {signal} mode {mode}')
            if signal.startswith('MCU_') != (domain == 'mcu'):
                raise ValueError(f'incorrect pad domain for {signal}')
            if key in claimed:
                raise ValueError(f'duplicate pad {domain} {offset:#x}: claimed by {claimed[key]} and {label}')
            claimed[key] = label
            value = pin_value(flags, mode)
            if kind == 'i2c' and not value & (1 << 18):
                raise ValueError(f'I2C {signal} must have its input receiver enabled')
            group_domains.add(domain)
            group_consumers.add('gpio:' + domain if kind == 'gpio' else controller)
            if kind == 'gpio':
                gpio_controllers.add(controller)
            if kind in ('i2c', 'pwm'):
                bus_signals[controller].append(member)
            if kind == 'i2c' and (controller == 'main_i2c1' or controller == 'main_i2c0' and profile != 'liquid'):
                raise ValueError('main_i2c1 is protected; main_i2c0 is available only in Liquid (Hybrid retains QD enable wiring)')
            entry = dict(domain=domain, offset=offset, value=value, signal=signal, group=label,
                         headers=pin['headers'], ball=pin['ball'])
            if label in ('idlemain_pins_default', 'idlemcu_pins_default'):
                if kind != 'gpio' or not value & (1 << 18):
                    raise ValueError(f'{label}: idle pins must be input-enabled GPIOs; use an active GPIO instance for outputs')
                report['idle'].append(entry)
                idle_gpio_lines[controller].add(int(signal.rsplit('_', 1)[1]))
            else:
                report['assignments'].append(entry)
            expectations.append(entry)
        if len(group_consumers) != 1 or len(group_domains) != 1:
            raise ValueError(f'{label}: group mixes controllers/domains; create a separate IOPAD instance for each controller')
        consumer = next(iter(group_consumers))
        consumers[consumer].append(label)
        groups.append((next(iter(group_domains)), match.group(0)))

    for controller, signals in bus_signals.items():
        if 'i2c' in controller and sorted(signals) != ['SCL', 'SDA']:
            raise ValueError(f'{controller} needs exactly one SCL and one SDA; got {signals}')
        if controller.startswith('epwm') and len(signals) != len(set(signals)):
            raise ValueError(f'{controller} output mapped to multiple pads: {signals}')

    for domain in ('main', 'mcu'):
        idle = []
        for key, pin in PINS.items():
            if key[0] != domain or not pin['idle'] or key in claimed:
                continue
            if not pin['gpio']:
                raise ValueError(f'no GPIO idle mapping for {pin["pad"]}')
            flags = 'PIN_INPUT' if pin['idle_bias'] == 'none' else 'PIN_INPUT_PULLDOWN'
            mode = pin['functions'][pin['gpio']]
            macro = 'AM64X_MCU_IOPAD' if domain == 'mcu' else 'AM64X_IOPAD'
            idle.append(f'        {macro}(0x{pin["offset"]:04x}, {flags}, {mode}) /* ({pin["ball"]}) {pin["pad"]}.{pin["gpio"]} */')
            entry = dict(domain=domain, offset=pin['offset'], value=pin_value(flags, mode),
                         signal=pin['gpio'], group=f'header_idle_{domain}_pins',
                         headers=pin['headers'], ball=pin['ball'])
            report['idle'].append(entry)
            expectations.append(entry)
            controller = classify(pin['gpio'])[1]
            gpio_controllers.add(controller)
            idle_gpio_lines[controller].add(int(pin['gpio'].rsplit('_', 1)[1]))
        if idle:
            label = f'header_idle_{domain}_pins'
            if label in labels:
                raise ValueError(f'{label} is reserved for generated idle settings')
            groups.append((domain, f'{label}: header-idle-{domain}-pins {{\n    pinctrl-single,pins = <\n' + '\n'.join(idle) + '\n    >;\n};'))
            consumers['gpio:' + domain].append(label)

    pins = '\n\n'.join(f'&{domain}_pmx0 {{\n' + '\n'.join(body for d, body in groups if d == domain) + '\n};' for domain in ('main', 'mcu') if any(d == domain for d, _ in groups)) + '\n'
    blocks = ['/dts-v1/;', '/plugin/;', '#include "k3.h"', '#include "hardware-pinmux.dtsi"']
    aliases = '\n'.join(f'    i2c{number} = "{path}";' for number, path in [(2, '/bus@f4000/i2c@20020000'), (3, '/bus@f4000/i2c@20030000'), (4, '/bus@f4000/bus@4000000/i2c@4900000'), (5, '/bus@f4000/bus@4000000/i2c@4910000')])
    blocks.append('&{/aliases} {\n' + aliases + '\n};')
    for controller in CONTROLLERS:
        active = controller in consumers
        body = [f'    status = "{"okay" if active else "disabled"}";']
        if active:
            body += ['    pinctrl-names = "default";', '    pinctrl-0 = <' + ' '.join('&' + label for label in consumers[controller]) + '>;']
            if 'i2c' in controller:
                body += ['    clock-frequency = <400000>;']
        blocks.append(f'&{controller} {{\n' + '\n'.join(body) + '\n};')
    for domain in ('main', 'mcu'):
        if consumers['gpio:' + domain]:
            blocks.append(f'&{domain}_pmx0 {{\n    pinctrl-names = "default";\n    pinctrl-0 = <' + ' '.join('&' + label for label in consumers['gpio:' + domain]) + '>;\n};')
    for controller in sorted(gpio_controllers):
        hogs = ''.join(f'    idle_line_{line} {{ gpio-hog; gpios = <{line} 0>; input; line-name = "header-idle-{line}"; }};\n' for line in sorted(idle_gpio_lines[controller]))
        blocks.append(f'&{controller} {{\n    status = "okay";\n' + hogs + '};')
    for controller in ('gpmc0', 'main_spi0', 'main_spi1', 'main_mcan1', 'mcu_spi0', 'mcu_spi1', 'mcu_uart1', 'main_uart5'):
        blocks.append(f'&{controller} {{ status = "disabled"; }};')
    # Existing board USB policy is independent of editable header pin groups.
    usb_pins = consumers.get('usb0', [])
    blocks.append('&usbss0 { ti,vbus-divider; ti,usb2-only; };')
    usb_body = ['status = "okay";', 'dr_mode = "host";', 'maximum-speed = "high-speed";']
    if usb_pins:
        usb_body += ['pinctrl-names = "default";', 'pinctrl-0 = <' + ' '.join('&' + label for label in usb_pins) + '>;']
    else:
        # VBUS is board-owned; preserve it even if a GUI edit removes the instance.
        # It is not an unused header signal and must never be idled automatically.
        pins += '\n&main_pmx0 { board_usb_pins: board-usb-pins { pinctrl-single,pins = <AM64X_IOPAD(0x02a8, PIN_OUTPUT, 0)>; }; };\n'
        usb_body += ['pinctrl-names = "default";', 'pinctrl-0 = <&board_usb_pins>;']
        consumers['usb0'] = ['board_usb_pins']
        entry = dict(domain='main', offset=0x2a8, value=pin_value('PIN_OUTPUT', 0), signal='USB0_DRVVBUS', group='board_usb_pins', headers=[], ball='E19')
        expectations.append(entry)
        report['assignments'].append(entry)
    blocks.append('&usb0 { ' + ' '.join(usb_body) + ' };')
    return {'pins': pins, 'overlay': '\n\n'.join(blocks) + '\n', 'report': report,
            'expectations': {'pins': expectations, 'pinctrl': dict(consumers), 'idle_gpio_lines': {c: sorted(lines) for c, lines in idle_gpio_lines.items()}, 'controllers': {c: ('okay' if c in consumers else 'disabled') for c in CONTROLLERS}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dtsi', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        result = generate(args.dtsi.read_text())
    except ValueError as exc:
        parser.exit(1, f'pinmux configuration error: {exc}\n')
    args.output.mkdir(parents=True, exist_ok=True)
    for name, key in [('hardware-pinmux.dtsi', 'pins'), ('k3-am64-fillstation-pinmux-overlay.dts', 'overlay')]:
        (args.output / name).write_text(result[key])
    for name, key in [('pinmux-report.json', 'report'), ('expectations.json', 'expectations')]:
        (args.output / name).write_text(json.dumps(result[key], indent=2) + '\n')


if __name__ == '__main__':
    main()
