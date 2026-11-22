"""Manual Chromium acceptance using only generated synthetic RTSP video."""
import http.server
import os
from pathlib import Path
import threading
import urllib.request

from playwright.sync_api import sync_playwright
import test_cameras_relay

ROOT = Path(__file__).resolve().parents[2]


def browser_check(relay):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path in ("/station/", "/grafana/"):
                if self.path == "/station/":
                    body = (Path(os.environ["STATION_DISPLAY"]) / "index.html").read_bytes()
                else:
                    body = b'<html><body style="background:#111820;color:white;font:24px sans-serif">Synthetic telemetry fixture</body></html>'
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path in ("/cameras/", "/cameras/viewer.js"):
                path = ROOT / "ground-station/cameras" / ("index.html" if self.path.endswith("/") else "viewer.js")
                body = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html" if self.path.endswith("/") else "application/javascript")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path in (f"/cameras/fillcam{i}/stream.mp4" for i in range(3)):
                name = self.path.split("/")[2]
                try:
                    with urllib.request.urlopen(relay + f"/api/stream.mp4?src={name}&video&audio=none", timeout=8) as upstream:
                        self.send_response(200)
                        self.send_header("Content-Type", "video/mp4")
                        self.end_headers()
                        while chunk := upstream.read(16384):
                            self.wfile.write(chunk)
                            self.wfile.flush()
                except (OSError, BrokenPipeError):
                    pass
            else:
                self.send_error(404)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(f"http://127.0.0.1:{server.server_port}/cameras/", wait_until="domcontentloaded")
            page.wait_for_function("document.querySelectorAll('video').length === 3 && [...document.querySelectorAll('video')].every(v => v.currentTime > 1 && v.readyState >= 2)", timeout=45000)
            page.screenshot(path="/private/tmp/crt-camera-browser.png", full_page=True)
            print("PASS: Chrome decoded all three synthetic live streams with advancing playback.")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    test_cameras_relay.main(browser_check=browser_check)
