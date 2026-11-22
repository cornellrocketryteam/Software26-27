"""Saved fill-station kernel policy; optionally check a build's resolved config."""
import os
from pathlib import Path
import re
import unittest

CONFIG = Path(os.environ.get('KERNEL_POLICY_CONFIG',
    Path(__file__).resolve().parents[2] / 'nix/packages/crt/fill-station-linux/kernel.config'))


def read_config(path):
    values = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'CONFIG_(\w+)=(.*)', line)
        disabled = re.fullmatch(r'# CONFIG_(\w+) is not set', line)
        if match:
            values[match[1]] = match[2]
        elif disabled:
            values[disabled[1]] = 'n'
    return values


class KernelPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = read_config(CONFIG)

    def test_wifi_stack_disabled(self):
        self.assert_values({'WIRELESS': 'n', 'WLAN': 'n'})
        for symbol in ('WIRELESS', 'WLAN', 'CFG80211', 'MAC80211',
                       'WLAN_VENDOR_TI', 'WL18XX', 'WLCORE', 'WLCORE_SDIO', 'WLCORE_SPI'):
            with self.subTest(symbol=symbol):
                self.assertEqual(self.config.get(symbol, 'n'), 'n')

    def test_pru_servo_transport_retained(self):
        expected = {
            'REMOTEPROC': 'y', 'PRU_REMOTEPROC': 'm', 'TI_PRUSS': 'm',
            'TI_PRUSS_INTC': 'm', 'RPMSG': 'y', 'RPMSG_CHAR': 'm',
            'RPMSG_CTRL': 'm', 'RPMSG_NS': 'y', 'RPMSG_VIRTIO': 'y',
            'VIRTIO': 'y', 'MAILBOX': 'y', 'OMAP2PLUS_MBOX': 'm',
            'TI_MESSAGE_MANAGER': 'y', 'TI_SCI_PROTOCOL': 'y',
        }
        self.assert_values(expected)

    def assert_values(self, expected):
        for symbol, value in expected.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.config.get(symbol), value)

    def test_boot_ethernet_and_hardware_retained(self):
        builtin = '''DEVTMPFS DEVTMPFS_MOUNT USB USB_ACM USB_XHCI_HCD
            USB_XHCI_PLATFORM USB_CDNS3 USB_CDNS3_HOST USB_CDNS3_TI
            TI_K3_AM65_CPSW_NUSS TI_DAVINCI_MDIO PHYLIB PHYLINK DP83867_PHY
            PHY_TI_GMII_SEL TI_K3_CPPI_DESC_POOL TI_K3_UDMA TI_K3_UDMA_GLUE_LAYER
            TI_K3_PSIL TI_K3_RINGACC EXT4_FS EROFS_FS OVERLAY_FS MTD MTD_BLOCK
            MTD_SPI_NOR SPI_CADENCE_QUADSPI MMC MMC_BLOCK MMC_SDHCI_AM654
            I2C I2C_OMAP SPI GPIOLIB GPIO_CDEV GPIO_DAVINCI PINCTRL_SINGLE PWM
            TI_SCI_CLK TI_SCI_PM_DOMAINS RESET_TI_SCI'''.split()
        self.assert_values(dict.fromkeys(builtin, 'y'))
        self.assert_values({'PWM_TIEHRPWM': 'm', 'PWM_TIECAP': 'm'})

    def test_deferred_trim_candidates_retained(self):
        self.assert_values(dict.fromkeys(
            ('GREYBUS', 'WWAN', 'USB_SERIAL_WWAN', 'USB_SERIAL_OPTION'), 'm'))


if __name__ == '__main__':
    unittest.main()
