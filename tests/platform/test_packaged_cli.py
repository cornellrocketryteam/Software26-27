from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.platform.runtime import PlatformError


class PackagedCLI(unittest.TestCase):
    def test_subdirectory_resolves_to_checkout_root(self):
        from tools.platform.entry import checkout_root
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            child = root / 'nested'
            child.mkdir()
            self.assertEqual(checkout_root(child), root)

    def test_build_uses_checkout_not_installed_module_directory(self):
        from tools.platform.entry import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            child = root / 'nested'
            child.mkdir()
            with patch('tools.platform.entry.Path.cwd', return_value=child), \
                 patch('tools.platform.entry.cli.main', return_value=0) as delegate:
                self.assertEqual(main(['build', 'ground-station', '--profile', 'um560-services', '--dry-run']), 0)
                self.assertEqual(delegate.call_args.kwargs['repo'], root)

    def test_status_does_not_require_a_checkout(self):
        from tools.platform.entry import main
        with tempfile.TemporaryDirectory() as directory, \
             patch('tools.platform.entry.Path.cwd', return_value=Path(directory)), \
             patch('tools.platform.entry.cli.main', return_value=0) as delegate:
            self.assertEqual(main(['status']), 0)
            delegate.assert_called_once()

    def test_non_checkout_rejected_for_build(self):
        from tools.platform.entry import checkout_root
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PlatformError):
                checkout_root(Path(directory))
