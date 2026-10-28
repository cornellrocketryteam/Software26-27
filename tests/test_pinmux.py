"""Pinmux generation contract: explicit assignments, ownership, and idle states."""
import importlib.util
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = Path(os.environ.get('PINMUX_SOURCE', ROOT / 'fill-station/hardware')) / 'pinmux.py'


def generate(text):
    if not MODULE.exists():
        raise AssertionError('pinmux generator has not been implemented')
    spec = importlib.util.spec_from_file_location('pinmux', MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate(text)


def group(name, rows, domain='main'):
    macro = 'AM64X_MCU_IOPAD' if domain == 'mcu' else 'AM64X_IOPAD'
    cells = '\n'.join(f'{macro}(0x{offset:04x}, {flags}, {mode}) /* (X1) {signal} */'
                      for offset, flags, mode, signal in rows)
    return f'&{domain}_pmx0 {{ {name}: {name.replace("_", "-")} {{ pinctrl-single,pins = <{cells}>; }}; }};'


class PinmuxTests(unittest.TestCase):
    def test_usb_vbus_is_preserved_and_verified_if_gui_instance_is_removed(self):
        result = generate('')
        usb = [p for p in result['expectations']['pins'] if p['domain'] == 'main' and p['offset'] == 0x2a8]
        self.assertEqual(len(usb), 1)
        self.assertEqual(result['expectations']['pinctrl']['usb0'], ['board_usb_pins'])

    def test_idle_gpio_is_requested_as_input_not_just_rx_enabled(self):
        result = generate('')
        self.assertIn('gpio-hog;', result['overlay'])
        self.assertIn('gpios = <2 0>;', result['overlay'])
        self.assertIn('input;', result['overlay'])
        self.assertNotIn('output-low;', result['overlay'])

    def test_explicit_gui_idle_groups_are_also_hogged_as_inputs(self):
        result = generate(group('idlemain_pins_default', [
            (0x168, 'PIN_INPUT_PULLDOWN', 7, 'PRG0_PRU0_GPO2.GPIO1_2')]))
        self.assertEqual(sum(p['offset'] == 0x168 and p['domain'] == 'main' for p in result['report']['idle']), 1)
        self.assertIn('gpios = <2 0>;', result['overlay'])

    def test_board_i2c1_is_never_disabled(self):
        result = generate('')
        self.assertNotIn('&main_i2c1 {', result['overlay'])

    def test_i2c_adapter_numbers_are_stable(self):
        result = generate(group('sensor', [
            (0x50, 'PIN_INPUT', 0, 'MCU_I2C1_SCL'),
            (0x54, 'PIN_INPUT', 0, 'MCU_I2C1_SDA')], 'mcu'))
        self.assertIn('i2c5 = "/bus@f4000/bus@4000000/i2c@4910000";', result['overlay'])

    def test_i2c_selection_enables_controller_and_attaches_group(self):
        result = generate(group('senseboard_pins_default', [
            (0xb0, 'PIN_INPUT', 1, 'GPMC0_CSn2.I2C2_SCL'),
            (0xb4, 'PIN_INPUT', 1, 'GPMC0_CSn3.I2C2_SDA')]))
        self.assertIn('&main_i2c2 {', result['overlay'])
        self.assertIn('pinctrl-0 = <&senseboard_pins_default>;', result['overlay'])
        self.assertIn('clock-frequency = <400000>;', result['overlay'])

    def test_mcu_i2c_selection_uses_mcu_domain(self):
        result = generate(group('sensor', [
            (0x50, 'PIN_INPUT', 0, 'MCU_I2C1_SCL'),
            (0x54, 'PIN_INPUT', 0, 'MCU_I2C1_SDA')], 'mcu'))
        self.assertIn('&mcu_i2c1 {', result['overlay'])
        self.assertIn('&mcu_pmx0 {', result['overlay'])

    def test_unused_header_pad_defaults_to_gpio_input_pulldown(self):
        result = generate('')
        self.assertRegex(result['pins'], r'AM64X_IOPAD\(0x0168, PIN_INPUT_PULLDOWN, 7\)')
        self.assertIn('&header_idle_main_pins', result['overlay'])

    def test_dedicated_open_drain_i2c_pads_have_no_idle_pull(self):
        result = generate('')
        self.assertRegex(result['pins'], r'AM64X_MCU_IOPAD\(0x0048, PIN_INPUT, 7\)')
        self.assertIn('no internal pull', json.dumps(result['report']))

    def test_protected_ethernet_pad_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'protected|managed'):
            generate(group('bad', [(0x1f8, 'PIN_INPUT', 7, 'PRG0_PRU1_GPO18.GPIO1_38')]))

    def test_out_of_header_pin_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'protected|managed'):
            generate(group('bad', [(0, 'PIN_INPUT', 7, 'OSPI0_CLK.GPIO0_0')]))

    def test_duplicate_pad_is_rejected(self):
        a = group('one', [(0x168, 'PIN_INPUT', 7, 'PRG0_PRU0_GPO2.GPIO1_2')])
        b = group('two', [(0x168, 'PIN_OUTPUT', 7, 'PRG0_PRU0_GPO2.GPIO1_2')])
        with self.assertRaisesRegex(ValueError, 'duplicate|claimed'):
            generate(a + b)

    def test_incomplete_i2c_bus_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SCL.*SDA|SDA.*SCL'):
            generate(group('incomplete', [(0xb0, 'PIN_INPUT', 1, 'GPMC0_CSn2.I2C2_SCL')]))

    def test_spi_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unsupported|SPI'):
            generate(group('spi', [(0x210, 'PIN_OUTPUT', 0, 'SPI0_CLK')]))

    def test_ti_not_configured_groups_are_ignored(self):
        result = generate(group('mygpio00_notconf_pins_default', [
            (0, 'PIN_INPUT', 7, 'OSPI0_CLK.GPIO0_0 Pin not configured')]))
        self.assertNotIn('OSPI0_CLK', result['pins'])

    def test_bad_mux_for_known_signal_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'mux|mapping'):
            generate(group('bad', [(0x168, 'PIN_INPUT', 0, 'PRG0_PRU0_GPO2.GPIO1_2')]))

    def test_unknown_flags_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'flag'):
            generate(group('bad', [(0x168, 'PIN_MAGIC', 7, 'PRG0_PRU0_GPO2.GPIO1_2')]))

    def test_unreferenced_unknown_content_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, 'parse|unsupported|format'):
            generate('&main_pmx0 { mystery { pins = <123>; }; };')

    def test_gpio_configuration_is_preserved_and_gpio_controller_enabled(self):
        result = generate(group('pru_test_pins_default', [
            (0x164, 'PIN_INPUT', 7, 'PRG0_PRU0_GPO1.GPIO1_1')]))
        self.assertIn('0x0164, PIN_INPUT, 7', result['pins'])
        self.assertIn('&pru_test_pins_default', result['overlay'])
        self.assertIn('&main_gpio1 {', result['overlay'])
        self.assertIn('&main_i2c2 {\n    status = "disabled";', result['overlay'])


if __name__ == '__main__':
    unittest.main()
