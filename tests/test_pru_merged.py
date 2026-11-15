"""Real flattened-tree checks for exclusive PRU PWM ownership."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verifier', ROOT / 'nix/packages/crt/fillstation-dtbo/verify-merged.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtget'), 'needs dtc and fdtget')
class PruMergedTests(unittest.TestCase):
    def check_tree(self, extra='', firmware='fill-station-pru0_1-fw', client=''):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'tree.dts').write_text('/dts-v1/; / { '
                'icssg0: icssg { compatible="ti,am642-icssg"; status="okay"; '
                'pru0_1: pru { compatible="ti,am642-pru"; status="okay"; '
                f'firmware-name="{firmware}"; }}; }}; '
                'main_gpio1: gpio { #gpio-cells=<2>; gpio-controller; ' + extra + ' }; ' + client + ' };')
            subprocess.run(['dtc', '-@', '-I', 'dts', '-O', 'dtb', '-o', str(path / 'tree.dtb'), str(path / 'tree.dts')], check=True, capture_output=True)
            verifier.verify_pru(path / 'tree.dtb', {'pru_pwm': [dict(core=1, bit=2, gpio_controller='main_gpio1', gpio_line=22)]})

    def test_correct_pru_identity_and_no_gpio_hog(self):
        self.check_tree()

    def test_wrong_firmware_identity_rejected(self):
        with self.assertRaisesRegex(ValueError, 'firmware'):
            self.check_tree(firmware='unrelated-fw')

    def test_gpio_hog_on_pru_owned_line_rejected(self):
        with self.assertRaisesRegex(ValueError, 'hog|owned'):
            self.check_tree('unexpected_hog { gpio-hog; gpios=<22 0>; input; };')

    def test_unrelated_gpio_hog_allowed(self):
        self.check_tree('idle { gpio-hog; gpios=<23 0>; input; };')

    def test_enabled_competing_ethernet_client_rejected(self):
        with self.assertRaisesRegex(ValueError, 'competing client'):
            self.check_tree(client='ethernet { compatible="ti,am642-icssg-prueth"; ti,prus=<&pru0_1>; };')

    def test_disabled_competing_ethernet_client_allowed(self):
        self.check_tree(client='ethernet { status="disabled"; ti,prus=<&pru0_1>; };')


if __name__ == '__main__':
    unittest.main()
