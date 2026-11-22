import importlib.util
from pathlib import Path
import unittest
import http.server
import threading
import tempfile
import json
import subprocess
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]


class DisplayLayoutTests(unittest.TestCase):
    def module(self):
        path = ROOT / "ground-station/display/layout.py"
        self.assertTrue(path.exists(), "monitor layout helper is missing")
        spec = importlib.util.spec_from_file_location("display_layout", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_two_displays_separate_grafana_and_commanding(self):
        layout = self.module().plan_layout(["HDMI-A-1", "DP-1"], True)
        self.assertEqual([(p["view"], p["output"], p["path"]) for p in layout],
                         [("telemetry", "DP-1", "/grafana/"), ("commanding", "HDMI-A-1", "/")])

    def test_one_display_uses_combined_view(self):
        layout = self.module().plan_layout(["HDMI-A-1"], True)
        self.assertEqual([(p["view"], p["path"]) for p in layout], [("overview", "/station/")])

    def test_headless_and_disabled_cameras(self):
        m = self.module()
        self.assertEqual(m.plan_layout([], True), [])
        self.assertEqual([p["path"] for p in m.plan_layout(["DP-1", "HDMI-A-1"], False)], ["/grafana/", "/"])

    def test_explicit_mapping_and_missing_output_fallback(self):
        m = self.module()
        layout = m.plan_layout(["DP-1", "HDMI-A-1"], True, "HDMI-A-1", "DP-1")
        self.assertEqual([p["output"] for p in layout], ["HDMI-A-1", "DP-1"])
        layout = m.plan_layout(["DP-1"], True, "missing", "DP-1")
        self.assertEqual(layout[0]["output"], "DP-1")

    def test_grafana_readiness_requires_database_health(self):
        module = self.module()
        class Handler(http.server.BaseHTTPRequestHandler):
            body = b'{"database":"ok"}'
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(self.body)
            def log_message(self, *_args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertTrue(module.grafana_ready(server.server_port))
            Handler.body = b'{"database":"unavailable"}'
            self.assertFalse(module.grafana_ready(server.server_port))
            Handler.body = b'not JSON'
            self.assertFalse(module.grafana_ready(server.server_port))
        finally:
            server.shutdown()
            server.server_close()

    def test_transient_ipc_failure_preserves_owned_browsers(self):
        module = self.module()
        outputs = json.dumps([{"name": "A", "active": True}, {"name": "B", "active": True}])
        children = [Mock(pid=41), Mock(pid=42)]
        for child in children:
            child.poll.return_value = None
        settings = {"swaymsg": "swaymsg", "browser": "chromium", "cameras": True, "port": 8080}
        responses = [outputs, subprocess.CalledProcessError(1, "swaymsg"), outputs,
                     json.dumps({"nodes": []}), KeyboardInterrupt()]
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(module.Path, "home", return_value=Path(temporary)), \
             patch.object(module.signal, "signal"), patch.object(module.time, "sleep"), \
             patch.object(module, "grafana_ready", return_value=True), \
             patch.object(module.subprocess, "Popen", side_effect=children) as start, \
             patch.object(module.subprocess, "check_output", side_effect=responses):
            with self.assertRaises(KeyboardInterrupt):
                module.run(settings)
            self.assertEqual(start.call_count, 2)
        for child in children:
            child.terminate.assert_called_once()

    def test_window_matching_uses_owned_pid_not_chromium_app_id(self):
        tree = {"nodes": [{"id": 3, "nodes": [
            {"id": 7, "pid": 42, "app_id": "chrome-url-derived-Default"},
            {"id": 8, "pid": 43, "app_id": "crt-telemetry"},
        ]}], "floating_nodes": []}
        module = self.module()
        self.assertEqual(module.browser_view(tree, 42)["id"], 7)
        self.assertIsNone(module.browser_view(tree, 44))


if __name__ == "__main__":
    unittest.main()
