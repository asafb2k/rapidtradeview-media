"""Record one take of the real Android app for a studio episode (the actions in episode["take"]["record"]).

    python take_android.py --episode episodes/<slug>.json --agent-device "<the command device_open returned>" \
        --out <media>/.ops/app-showcase/<slug>/takes/take1 [--adb ADB.exe --serial emulator-5558 --demo on|off]

Drive the device only through the agent-device command bound by device_open (taps, gestures, recording); adb is used
for demo mode only (9:41, full wifi and battery, no notification icons). Navigate to the episode's screen first (by
hand, with the same command). Writes OUT/raw.mp4, OUT/host_log.jsonl (host clock per action) and the recorder's
telemetry. Gesture times for the cut come later from the pixels (studio.py ingest), not from these logs.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

# "exit" first: entering on top of a stale demo state left a second wifi icon on day 3's emulator (11-14)
DEMO = [["exit"], ["enter"], ["clock", "-e", "hhmm", "0941"], ["battery", "-e", "level", "100", "-e", "plugged", "false"],
        ["network", "-e", "wifi", "show", "-e", "level", "4", "-e", "fully", "true"], ["network", "-e", "mobile", "hide"],
        ["network", "-e", "ethernet", "hide"], ["notifications", "-e", "visible", "false"]]


def demo(adb: str, serial: str, on: bool) -> None:
    sh = [adb, "-s", serial, "shell"]
    if on:
        subprocess.run(sh + ["settings", "put", "global", "sysui_demo_allowed", "1"], check=True)
        for c in DEMO:
            subprocess.run(sh + ["am", "broadcast", "-a", "com.android.systemui.demo", "-e", "command"] + c, check=True,
                           capture_output=True)
    else:
        subprocess.run(sh + ["am", "broadcast", "-a", "com.android.systemui.demo", "-e", "command", "exit"], check=True,
                       capture_output=True)
        subprocess.run(sh + ["settings", "put", "global", "sysui_demo_allowed", "0"], check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", required=True)
    ap.add_argument("--agent-device", required=True)
    ap.add_argument("--out")
    ap.add_argument("--adb")
    ap.add_argument("--serial")
    ap.add_argument("--demo", choices=["on", "off"])
    a = ap.parse_args()
    if a.demo:
        demo(a.adb, a.serial, a.demo == "on")
        return 0
    ep = json.loads(Path(a.episode).read_text(encoding="utf-8"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "host_log.jsonl").open("w", encoding="utf-8")

    def mark(what):
        log.write(json.dumps({"what": what, "host_ms": int(time.time() * 1000)}) + "\n")
        log.flush()

    def ad(*args):
        r = subprocess.run([a.agent_device, *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if r.returncode != 0:
            raise SystemExit(f"agent-device {args} failed: {r.stdout[-400:]} {r.stderr[-400:]}")
        return r.stdout

    for act in ep["take"]["record"]["actions"]:
        d = act["do"]
        name = act.get("name", d)
        mark(name + "_call")
        if d == "record_start":
            ad("record", "start", str(out / "raw.mp4"), "--scope", "device", "--quality", "high", "--hide-touches")
        elif d == "record_stop":
            ad("record", "stop")
        elif d == "sleep":
            time.sleep(act["s"])
        elif d == "press":
            ad("press", act["x"], act["y"])
        elif d == "pan":
            ad("gesture", "pan", act["x"], act["y"], act["dx"], act["dy"], act["ms"])
        elif d == "back":
            ad("back", "--system")
        else:
            raise SystemExit(f"unknown action {d}")
        mark(name + "_done")
    log.close()
    print(json.dumps({"take": str(out), "raw": str(out / "raw.mp4")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
