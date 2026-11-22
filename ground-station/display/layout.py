"""Own the station's browser processes and reconcile local monitor hotplug."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


def plan_layout(outputs, cameras, telemetry_output=None, commanding_output=None):
    outputs = sorted(set(outputs))
    if not outputs:
        return []
    primary = telemetry_output if telemetry_output in outputs else outputs[0]
    if len(outputs) == 1:
        return [{"view": "overview", "output": primary, "path": "/station/"}]
    remaining = [name for name in outputs if name != primary]
    secondary = commanding_output if commanding_output in remaining else remaining[0]
    return [{"view": "telemetry", "output": primary, "path": "/grafana/"},
            {"view": "commanding", "output": secondary, "path": "/"}]


def ipc(binary, command):
    results = json.loads(subprocess.check_output([binary, command], text=True, timeout=5))
    if not all(result.get("success") for result in results):
        raise RuntimeError("display layout command rejected")


def browser_view(tree, pid):
    if tree.get("pid") == pid and tree.get("app_id") and isinstance(tree.get("id"), int):
        return tree
    for child in tree.get("nodes", []) + tree.get("floating_nodes", []):
        found = browser_view(child, pid)
        if found is not None:
            return found
    return None


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def grafana_ready(port):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                f"http://127.0.0.1:{port}/grafana/api/health", timeout=1) as response:
            return json.loads(response.read(4096)).get("database") == "ok"
    except (OSError, ValueError, AttributeError):
        return False


def run(settings):
    processes, placed, previous, previous_health = {}, {}, None, None
    running = True

    def shutdown(_signal, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        while running:
            try:
                outputs = json.loads(subprocess.check_output(
                    [settings["swaymsg"], "-t", "get_outputs", "-r"], text=True, timeout=5))
                layout = plan_layout([o["name"] for o in outputs if o.get("active")],
                                     settings["cameras"], settings.get("telemetryOutput"),
                                     settings.get("commandingOutput"))
                healthy = grafana_ready(settings["port"])
                if previous_health is False and healthy:
                    # Recover an initial nginx 502 when Grafana starts after the UI.
                    for view in ("overview", "telemetry"):
                        if view in processes:
                            stop(processes.pop(view))
                previous_health = healthy
                if layout != previous:
                    for process in processes.values():
                        stop(process)
                    processes.clear()
                    placed.clear()
                    previous = layout
                for pane in layout:
                    name = pane["view"]
                    if name not in processes or processes[name].poll() is not None:
                        profile = Path.home() / ".config/ground-kiosk" / name
                        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
                        path = settings.get("overviewPath", pane["path"]) if name == "overview" else pane["path"]
                        url = f'http://127.0.0.1:{settings["port"]}{path}'
                        processes[name] = subprocess.Popen([
                            settings["browser"], "--ozone-platform=wayland", "--kiosk",
                            "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble",
                            "--disable-background-networking", "--disable-component-update", "--disable-sync",
                            "--password-store=basic", "--autoplay-policy=no-user-gesture-required",
                            f"--class=crt-{name}", f"--user-data-dir={profile}", f"--app={url}",
                        ])
                tree = json.loads(subprocess.check_output(
                    [settings["swaymsg"], "-t", "get_tree", "-r"], text=True, timeout=5))
                for pane in layout:
                    name = pane["view"]
                    process = processes[name]
                    view = browser_view(tree, process.pid)
                    if view is not None and placed.get(name) != (process.pid, view["id"]):
                        # Chromium app mode chooses its own app_id despite --class.
                        # Bind only the window belonging to this owned browser PID.
                        selector = f'[con_id={view["id"]}]'
                        ipc(settings["swaymsg"], f'{selector} move container to workspace {json.dumps(name)}')
                        # Move only after a window exists: Sway can discard an
                        # empty workspace when focus changes to another output.
                        ipc(settings["swaymsg"], f'workspace {json.dumps(name)}; move workspace to output {json.dumps(pane["output"])}')
                        ipc(settings["swaymsg"], f'{selector} fullscreen enable')
                        placed[name] = (process.pid, view["id"])
                time.sleep(2)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                    json.JSONDecodeError, RuntimeError):
                # Compositor IPC can briefly fail during output changes/load.
                # Keep the owned browsers and retry placement on the next poll.
                print("Display IPC unavailable; retrying layout.", file=sys.stderr)
                time.sleep(2)
    finally:
        for process in processes.values():
            stop(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    run(json.loads(args.config.read_text()))


if __name__ == "__main__":
    main()
