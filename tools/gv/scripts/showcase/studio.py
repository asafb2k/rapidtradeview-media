"""SHOWCASE, studio look (default from day 2): the real Android app take, whole and centred in a code-built 3D phone on the
brand ground. One command per episode once its take is recorded (take_android.py, or by hand with agent-device):

    PY=C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe
    $PY tools/gv/scripts/showcase/showcase.py tools/gv/scripts/showcase/episodes/<slug>.json              # build + QA
    $PY tools/gv/scripts/showcase/showcase.py <episode.json> --check-only                                 # check6 only

Output: <media>/.ops/app-showcase/<slug>/: final.mp4, frame0.png, check6.png, sheet.png, phone.png, take/ (the chosen
recording, frames, frame log, gesture log, rect log), proof.json, episode.json (resolved), voice_script.json/.txt,
qa.json, render.json, youtube.json.

What it enforces: the screen texture is the recorded frames only (unlit, exact colours, nothing redrawn); holds are
held real frames, never interpolated; every gesture time comes from the pixels (first changed frame); keep-out rects are
projected through the camera on every frame (build fails on any visible part) and OCR reads every 10th frame; nothing we
draw overlaps the phone screen; overlay text stays inside x 60-920, y 170-1500.
Exit: 0 built and QA passed, 1 built but a QA gate failed (files kept), 2 input/take error (no video).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "filed"))
import filed as F  # noqa: E402
import sound as S  # noqa: E402

MEDIA, CACHE, FFMPEG, FFPROBE, CONDA_PY = F.MEDIA, F.CACHE, F.FFMPEG, F.FFPROBE, F.CONDA_PY
W, H, FPS = 1080, 1920, 30
SAFE = (60, 200, 920, 1500)
OCR_PS1 = HERE / "ocr.ps1"
BANNED = ("buy", "sell", "profit", "returns", "guarantee", "guaranteed", "will rise", "go up", "moon", "beat the market",
          "introducing", "new", "update", "now live", "you should", "signal", "predict", "predicts", "forecast", "tip")
OCR_BAD = ("HOLD", "BULLISH", "BEARISH", "FREE STOCK", "0/2", "1/2", "2/2", "OUR RECORD", "KEY LEVEL", "/100", "EDGAR",
           "SOURCE:", "SPONSOR")
PRICE_RX = re.compile(r"\$\s?\d|\b\d+\.\d\d\b")
TICKER_RX = re.compile(r"\b[A-Z]{2,5}\b")
LOOK = {"fov": 20, "envi": 0.85, "envrot": 2.35, "frame": 0x6d737c, "rough": 0.28, "glass": 0x050505, "glass_env": 0.06,
        "glass_clearcoat": 0.0, "key_col": 0xe6eef5, "key": 1.0, "rim_col": 0xbcd6ff, "rim": 1.5,
        "wall_top": [14, 28, 26], "wall_low": [11, 24, 21], "floor": [10, 19, 17], "pool": [22, 58, 50], "pool_w": 0.6,
        "vig": 0.22, "grain": 0.013, "shadow_a": 0.42, "shadow_blur": 80}
# body height in the whole-phone pose (px); s0 = this / body height in mm. 1136 (not 1150) so the headline / caption slot
# (pill bottom 230 + 16 px gap, 60 px tall) clears the phone top by >= 18 px with the centre at 893 and bottom <= 1468.
PHONE_H_WHOLE = 1136.0
SUBS_MAX = 32                     # n = ceil(travel / 0.9) sub-frames, 1-32 (the judges' graft; 24 stepped on fast pulls)
SLOT_GAP_PILL, SLOT_GAP_PHONE = 16, 18
BODY_H_MM = 68 * 2400 / 1080 + 2 * (1.45 + 0.75)
wjson, rjson, sha256, now_z = F.wjson, F.rjson, F.sha256, F.now_z


class InputError(F.InputError):
    pass


def ff(args: list[str]) -> str:
    return F.run_ff(args)


# ================================================================================================ script + voice
def parse_lines(ep: dict) -> list[dict]:
    """Chunks split by ' | '; '@name ' anchors a chunk; '~' = spoken, no caption; '*word' = the accent colour."""
    out = []
    for line in ep["lines"]:
        chunks = []
        for raw in line["text"].split(" | "):
            raw = raw.strip()
            anchor = None
            if raw.startswith("@"):
                anchor, raw = raw[1:].split(" ", 1)
            cap = not raw.startswith("~")
            raw = raw.lstrip("~")
            words = []
            for tok in raw.split(" "):
                words.append({"t": tok.lstrip("*"), "accent": tok.startswith("*")})
            show = " ".join(w["t"] for w in words)
            chunks.append({"anchor": anchor, "show": show, "say": F.say_map(show), "cap": cap, "wl": words})
        out.append({"id": line["id"], "gap_before": line.get("gap_before", 0.12), "speed_mul": line.get("speed_mul", 1.0),
                    "chunks": chunks})
    return out


def voice(ep: dict, run: Path) -> tuple[list[dict], list[dict], float]:
    vs = ep["voice"]
    speed = vs["speed"]
    for _ in range(5):
        lines = F.tts(parse_lines(ep), run, vs["voice"], speed)
        clips, _ = F.place_voice(lines)
        n = sum(len(ln["say"].split()) for ln in lines)
        rate = n / sum(ln["t1"] - ln["t0"] for ln in lines)
        lo, hi = vs["target_wps"]
        if lo <= rate <= hi:
            break
        speed = round(speed * ((lo + hi) / 2) / rate, 3)
    return lines, clips, speed


# ================================================================================================ take
def probe_pts(mp4: Path) -> list[float]:
    r = subprocess.run([str(FFPROBE), "-v", "error", "-select_streams", "v", "-show_entries", "frame=pts_time", "-of",
                        "csv=p=0", str(mp4)], capture_output=True, text=True)
    return [float(x) for x in r.stdout.split()]


def ingest_take(ep: dict, run: Path) -> dict:
    """Copy the chosen take, decode every recorded frame (variable rate: the recorder writes a frame only when the screen
    changes), and log from the pixels: per-frame change, the gesture times (first changed frame), the in-sheet scroll."""
    tk = ep["take"]
    src = Path(tk["source"])
    td = run / "take"
    if not (td / "raw.mp4").is_file() or sha256(td / "raw.mp4") != sha256(src / "raw.mp4"):
        if td.exists():
            shutil.rmtree(td)
        td.mkdir(parents=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, td / f.name)
    fr = td / "frames"
    pts = probe_pts(td / "raw.mp4")
    if not fr.is_dir() or len(list(fr.glob("f*.png"))) != len(pts):
        if fr.exists():
            shutil.rmtree(fr)
        fr.mkdir()
        subprocess.run([str(FFMPEG), "-v", "error", "-i", str(td / "raw.mp4"), "-fps_mode", "passthrough",
                        str(fr / "f%04d.png")], check=True)
    files = sorted(fr.glob("f*.png"))
    if len(files) != len(pts):
        raise InputError(f"take frames {len(files)} != pts {len(pts)}")
    small = [np.asarray(Image.open(p).convert("L"), np.int16)[::4, ::4] for p in files]
    x0, y0, x1, y1 = tk["tap_rect"]
    log = [{"i": 0, "file": files[0].name, "pts": pts[0], "diff": 0.0, "tap_row": 0.0}]
    for i in range(1, len(files)):
        d = float(np.abs(small[i] - small[i - 1]).mean())
        rr = float(np.abs(small[i] - small[0])[y0 // 4:y1 // 4, x0 // 4:x1 // 4].mean())
        log.append({"i": i, "file": files[i].name, "pts": round(pts[i], 6), "diff": round(d, 3), "tap_row": round(rr, 3)})
    thr, quiet = tk["change_thresh"], tk["event_quiet_s"]
    ch = [e for e in log[1:] if e["diff"] >= thr]
    clusters = []
    for e in ch:
        if clusters and e["pts"] - clusters[-1][-1]["pts"] <= quiet:
            clusters[-1].append(e)
        else:
            clusters.append([e])
    if len(clusters) != len(tk["events"]):
        raise InputError(f"take has {len(clusters)} change clusters, episode expects {tk['events']}: "
                         f"{[(c[0]['pts'], c[-1]['pts']) for c in clusters]}")
    ev = {}
    for name, c in zip(tk["events"], clusters):
        # settle: the cluster ends at its last frame above threshold; the next frame that is quiet is the rest state
        last = c[-1]["i"]
        ev[name] = {"start": c[0]["pts"], "end": c[-1]["pts"], "first_frame": c[0]["file"], "last_frame": log[last]["file"],
                    "frames": len(c)}
    # the tap: the first frame in the open cluster's window where the tapped row changes (its press highlight)
    o = ev[tk["events"][0]]
    cand = [e for e in log if o["start"] - 0.4 <= e["pts"] <= o["end"] and e["tap_row"] >= 0.8]
    ev[tk["events"][0]]["tap"] = cand[0]["pts"] if cand else o["start"]
    ev[tk["events"][0]]["tap_frame"] = cand[0]["file"] if cand else o["first_frame"]
    # scroll offset of every frame (rows matched against the settled sheet before the scroll)
    scroll = {}
    scr_states = [v for v in tk["states"].values() if v.get("scroll_event") in ev]
    if scr_states:
        se = scr_states[0]["scroll_event"]
        nxt = [ev[n]["start"] for n in tk["events"] if ev[n]["start"] > ev[se]["start"]]
        base_i = max(e["i"] for e in log if e["pts"] < ev[se]["start"])
        sp = tk["scroll_probe"]
        ref = np.asarray(Image.open(files[base_i]).convert("L"), np.float32)[:, sp["x"][0]:sp["x"][1]].mean(1)
        smax = scr_states[0]["scroll_max"] + 60
        for e in log:
            if e["pts"] < ev[se]["start"] - 1e-6 or (nxt and e["pts"] > min(nxt) - 1e-6):
                continue
            prof = np.asarray(Image.open(files[e["i"]]).convert("L"), np.float32)[:, sp["x"][0]:sp["x"][1]].mean(1)
            best, bo = 1e18, 0
            y0s, y1s = sp["y"]
            for off in range(0, smax):
                a, b = ref[y0s:y1s], prof[y0s - off:y1s - off]
                err = float(np.mean((a - b) ** 2))
                if err < best:
                    best, bo = err, off
            scroll[e["file"]] = bo
        ev[se]["offset_max"] = max(scroll.values()) if scroll else 0
        settled = [e for e in log if e["file"] in scroll and e["pts"] <= ev[se]["end"] + 1e-6]
        ev[se]["offset_settled"] = scroll[settled[-1]["file"]] if settled else 0
    unique = [e for e in log[1:] if e["diff"] > 0.02]
    fps_motion = []
    for name in tk["events"]:
        seg = [e["pts"] for e in log if ev[name]["start"] <= e["pts"] <= ev[name]["end"]]
        if len(seg) > 1:
            fps_motion.append({"event": name, "frames": len(seg), "seconds": round(seg[-1] - seg[0], 4),
                               "fps": round((len(seg) - 1) / max(1e-6, seg[-1] - seg[0]), 1),
                               "max_gap_ms": round(1000 * max(np.diff(seg)), 1)})
    host = [json.loads(x) for x in (td / "host_log.jsonl").read_text().splitlines()] if (td / "host_log.jsonl").is_file() else []
    tele = rjson(td / "raw.gesture-telemetry.json") if (td / "raw.gesture-telemetry.json").is_file() else None
    out = {"pts": pts, "files": [f.name for f in files], "events": ev, "scroll": scroll, "log": log,
           "fps_motion": fps_motion, "unique_frames": len(unique) + 1, "duration": pts[-1],
           "host_log": host, "telemetry": tele}
    wjson(td / "frame_log.json", {"frames": log, "fps_motion": fps_motion})
    gest = [{"gesture": "tap (row press highlight, first changed frame)", "t": ev[tk["events"][0]]["tap"],
             "frame": ev[tk["events"][0]]["tap_frame"], "at_px": tk["tap_at"]}]
    for name in tk["events"]:
        gest.append({"gesture": name, "t_first_change": ev[name]["start"], "t_last_change": ev[name]["end"],
                     "first_frame": ev[name]["first_frame"], "frames": ev[name]["frames"]})
    if tele:
        gest.append({"telemetry_tap_ms (agent-device, not used: late vs pixels)": [e.get("tMs") for e in tele.get("events", [])]})
    wjson(td / "gesture_log.json", {"from": "pixels (first changed frame)", "gestures": gest, "host_log": host})
    wjson(td / "rect_log.json", {"units": "capture px (1080x2400), sheet rects before its scroll; scroll offset per frame "
                                          "below", "states": {k: {"rects": v["rects"], "keepout": v["keepout"]}
                                                              for k, v in tk["states"].items()},
                                 "scroll_offset_by_frame": scroll})
    return out


def check_punch_hole(take: dict, run: Path, used: list[str]) -> dict:
    """The punch-hole may only cover uniform status-bar pixels: check every used frame (r 1.45 mm ~ 23 capture px)."""
    worst = 0
    for f in sorted(set(used)):
        a = np.asarray(Image.open(run / "take" / "frames" / f).convert("RGB"), np.int16)[56 - 26:56 + 27, 540 - 26:540 + 27]
        worst = max(worst, int(a.max() - a.min()))
    return {"ok": worst <= 3, "max_minus_min": worst, "frames_checked": len(set(used))}


# ================================================================================================ timeline
def evalx(s, env: dict) -> float | None:
    """'{name}' references, digits, + - * / ( ) and M(a, b) = max."""
    s = str(s)
    for k in re.findall(r"\{([a-z0-9_]+)\}", s):
        if k not in env:
            return None
        s = s.replace("{" + k + "}", repr(float(env[k])))
    if re.search(r"[^0-9.+\-*/() e,M]", s):
        raise InputError(f"bad expression {s!r}")
    return float(eval(s, {"__builtins__": {}}, {"M": max}))  # noqa: S307 (digits, + - * /, max only)


def retime_scroll(take: dict, ev_name: str) -> list[float]:
    """A real scroll shown at an even on-screen speed with real frames only: pick a subsequence of the recorded frames
    (each output frame a different recorded frame, so no frozen frames and no interpolation) whose per-frame scroll steps
    change as little as possible (DP on the step differences, from rest), capped near 14 capture px per output frame;
    then the recorded overscroll settle frames, each once. Returns the source pts per output frame."""
    sc = take["scroll"]
    e = take["events"][ev_name]
    pts_of = dict(zip(take["files"], take["pts"]))
    names = sorted(sc, key=lambda f: pts_of[f])
    base = max((f for f in take["files"] if pts_of[f] < e["start"]), key=lambda f: pts_of[f])
    off = [0] + [sc[f] for f in names]
    names = [base] + names
    top = int(np.argmax(off))
    mono = off[:top + 1]
    m_ = len(mono)
    dc = lambda d, pd: (d - pd) ** 2 + 5 * max(0, d - 14) ** 2  # noqa: E731
    best = np.full((m_, m_), 1e18)
    prev = -np.ones((m_, m_), int)
    for i in range(1, m_):
        if mono[i] > mono[0]:
            best[0, i] = dc(mono[i] - mono[0], 0)
    for i in range(1, m_):
        for j in range(1, i):
            d = mono[i] - mono[j]
            if d <= 0:
                continue
            c = best[:j, j] + np.array([dc(d, mono[j] - mono[k]) for k in range(j)])
            k = int(np.argmin(c))
            best[j, i], prev[j, i] = c[k], k
    j = int(np.argmin([best[j, m_ - 1] + 0.5 * (mono[m_ - 1] - mono[j]) ** 2 for j in range(m_ - 1)]))
    path = [m_ - 1, j]
    while path[-1] != 0:
        path.append(int(prev[path[-1], path[-2]]))
    path = path[::-1][1:]
    settle = [f for f in names[top + 1:] if pts_of[f] <= e["end"] + 1e-6]
    return [pts_of[names[p]] for p in path] + [pts_of[f] for f in settle]


def timeline(ep: dict, lines: list[dict], take: dict) -> dict:
    T = {}
    for ln in lines:
        T[ln["id"] + "_t0"], T[ln["id"] + "_t1"] = ln["t0"], ln["t1"]
        for c in ln["chunks"]:
            if c["anchor"]:
                T[c["anchor"]] = c["t0"]
    ev = take["events"]
    pending_t = dict(ep["times"])
    pending_moves = list(ep["moves"])
    pending_src = list(ep["source_map"])
    srcmap = []
    moves = []
    for _ in range(30):
        for k, ex in list(pending_t.items()):
            v = evalx(ex, T)
            if v is None:
                continue
            T[k] = math.ceil(v * FPS - 1e-6) / FPS if k == "end" else v
            del pending_t[k]
        for m in list(pending_moves):
            t0 = evalx(m["t0"], T)
            dur = evalx(m["dur"], T) if isinstance(m["dur"], str) else m["dur"]
            if t0 is None or dur is None:
                continue
            moves.append({**m, "t0": round(t0, 4), "dur": round(dur, 4)})
            T[m["name"] + "_t0"] = t0
            T[m["name"] + "_end"] = t0 + dur
            pending_moves.remove(m)
        for s_ in list(pending_src):
            at = evalx(s_["at"], T)
            if at is None:
                continue
            e = ev[s_["event"]]
            src = e["tap"] if s_["from"] == "tap" else e["start"]
            ent = {"at": round(at, 4), "src": src, "event": s_["event"], "settled": e["end"]}
            if s_.get("retime") == "even":
                ent["frames"] = retime_scroll(take, s_["event"])
                T["v_" + s_["event"] + "_end"] = at + len(ent["frames"]) / FPS
            else:
                T["v_" + s_["event"] + "_end"] = at + (e["end"] - src)
            srcmap.append(ent)
            T["v_" + s_["event"]] = at
            pending_src.remove(s_)
        if not pending_moves and not pending_src and not pending_t:
            break
    if pending_moves or pending_src or pending_t:
        raise InputError(f"unresolved timeline items: {[m['name'] for m in pending_moves]} {pending_src} {pending_t}")
    moves.sort(key=lambda m: m["t0"])
    srcmap.sort(key=lambda m: m["at"])
    for a, b in zip(moves, moves[1:]):
        if a["t0"] + a["dur"] > b["t0"] + 1e-6:
            raise InputError(f"moves overlap: {a['name']} ends {a['t0'] + a['dur']:.2f} > {b['name']} {b['t0']:.2f}")
    T["moves"], T["srcmap"] = moves, srcmap
    return T


EASE = {"out3": lambda x: 1 - (1 - x) ** 3,
        # the hook pull-back: already moving at frame 0 but slowly (speed 0.3 of linear), so frame 0 stays a sharp still
        "hook": lambda x: 0.3 * x + 2.4 * x * x - 1.7 * x ** 3, "io2": lambda x: 2 * x * x if x < .5 else 1 - (-2 * x + 2) ** 2 / 2,
        "in2": lambda x: x * x, "lin": lambda x: x,
        # the loop push: gentle both ends (peak speed pi/2 of linear, lower than io2) so its sub-frames stay <= 32
        "sio": lambda x: 0.5 - 0.5 * math.cos(math.pi * x)}


def pose_at(t: float, ep: dict, T: dict) -> dict:
    P = ep["poses"]
    cur = dict(P[ep["moves"][0]["from"]])
    for m in T["moves"]:
        tgt = P[m["to"]]
        if t < m["t0"]:
            break
        x = min(1.0, (t - m["t0"]) / m["dur"]) if m["dur"] > 0 else 1.0
        e = EASE[m["ease"]](x)
        z = math.exp(math.log(cur["z"]) + (math.log(tgt["z"]) - math.log(cur["z"])) * e)
        nxt = {"z": z, "uv": tgt["uv"], "A": [cur["A"][k] + (tgt["A"][k] - cur["A"][k]) * e for k in (0, 1)],
               "yaw": cur["yaw"] + (tgt["yaw"] - cur["yaw"]) * e, "moving": 0 < x < 1, "move": m["name"]}
        cur = nxt
        if x < 1:
            break
    return cur


def src_time(t: float, T: dict, take: dict) -> float:
    sm = T["srcmap"]
    first = sm[0]
    if t < first["at"]:
        return first["src"] - 0.05          # the still card before the tap (no frame is written while nothing changes)
    k = max(i for i, s in enumerate(sm) if s["at"] <= t + 1e-9)
    e = sm[k]
    if "frames" in e:                        # a retimed real scroll: one recorded frame per output frame, then held
        j = int(round((t - e["at"]) * FPS))
        return e["frames"][min(max(j, 0), len(e["frames"]) - 1)] + 1e-4
    # real speed, then hold the event's settled frame (its last changed frame) until the next real gesture
    return min(e["src"] + (t - e["at"]), e["settled"] + 1e-4)


def frame_at(s: float, take: dict) -> str:
    pts = take["pts"]
    i = max(0, int(np.searchsorted(pts, s + 1e-6, side="right")) - 1)
    return take["files"][i]


def tap_state(t: float, ep: dict, T: dict) -> dict | None:
    tp = ep["tap"]
    v = T["v_tap"]
    d = t - v
    if d < -tp["lead"] or d > tp["fade_after"]:
        return None
    # in over `lead` before the tap; the finger lifts as the sheet starts to move: out within `fade_after` of the tap
    alpha = min(1.0, (d + tp["lead"]) / tp["lead"]) if d < 0 else max(0.0, 1 - max(0.0, d - 0.05) / (tp["fade_after"] - 0.05))
    press = 1.0
    if 0 <= d <= tp["pop"]:
        press = 1 - 0.1 * math.sin(math.pi * d / tp["pop"])
    rip = d / tp["ripple"] if 0 < d < tp["ripple"] else 0.0
    # the disc sits in the tapped row's empty band (the real press point is tap_at, logged in the gesture log)
    u, vv = tp.get("disc_at", ep["take"]["tap_at"])
    return {"u": u, "v": vv, "scale": round(press, 4), "alpha": round(alpha, 4), "ripple": round(rip, 4)}


# ================================================================================================ overlay
def captions(lines: list[dict], T: dict) -> list[dict]:
    caps = []
    for ln in lines:
        first = True
        for c in ln["chunks"]:
            if not c["cap"]:
                first = False
                continue
            t0 = c["t0"] + (0.15 if first else 0.0)
            first = False
            caps.append({"t0": round(t0, 3), "t1": c["t1"], "words": c["wl"]})
    for i, c in enumerate(caps):
        nxt = caps[i + 1]["t0"] if i + 1 < len(caps) else c["t1"] + 0.35
        c["t1"] = round(min(nxt, c["t1"] + 0.35), 3)
    return caps


def word_in(t, t0, k, dur=0.13, gap=0.067):
    x = (t - t0 - k * gap) / dur
    x = max(0.0, min(1.0, x))
    return x, 6.0 * (1 - x)


def overlay_at(t: float, ep: dict, T: dict, caps: list[dict], accent: str, end_y: dict) -> dict:
    o = ep["overlay"]
    ov = {"pill": {"h": o["pill"]["h"], "top": o["pill"]["top"], "cx": 540}, "lines": {}}
    hl = ep["headline"]
    for w0, w1 in o["headline_show"]:           # windows [in, out]: shown from frame 0 (the thumbnail) and back for the loop
        h_in0, h_out = evalx(w0, T), evalx(w1, T)
        if not (h_in0 <= t < h_out + 0.12):
            continue
        kill = max(0.0, min(1.0, (h_out + 0.12 - t) / 0.12))
        ws = []
        for k, w in enumerate(hl["words"]):
            a, b = word_in(t, h_in0, k, dur=0.13, gap=0.05)
            ws.append({"t": w, "color": accent if w in hl["accent"] else "#ffffff", "alpha": round(a * kill, 4),
                       "blur": round(b, 3)})
        if any(w["alpha"] > 0 for w in ws):
            ov["lines"]["headline"] = {"words": ws, "size": hl["size"], "top": o["headline_top"], "cx": 540,
                                       "maxRight": 912, "track": hl["track"], "shadow": True}
    for c in caps:
        if c["t0"] <= t < c["t1"] + 0.12:
            kill = max(0.0, min(1.0, (c["t1"] + 0.12 - t) / 0.12))
            ws = []
            for k, w in enumerate(c["words"]):
                a, b = word_in(t, c["t0"], k)
                ws.append({"t": w["t"], "color": accent if w["accent"] else "#ffffff", "alpha": round(a * kill, 4),
                           "blur": round(b, 3)})
            ch = o["chip"]
            ov["lines"]["caption"] = {"words": ws, "size": ch["size"], "top": ch["top"], "cx": 540, "maxRight": 905,
                                      "track": -0.01, "chip": {"alpha": round(min(1.0, (t - c["t0"]) / 0.1) * kill, 4),
                                                               "padx": ch["padx"], "pady": ch["pady"]}}
    # end text: in at url_in / nia, out (0.15 s fade) before the loop push grows the phone over its slot
    out = T["text_out"]
    gone = max(0.0, min(1.0, (out - t) / 0.15))
    if t >= T["url_in"] - 0.05 and gone > 0:
        a, b = word_in(t, T["url_in"] - 0.05, 0, dur=0.2)
        ov["lines"]["url"] = {"words": [{"t": o["url"]["text"], "color": "#ffffff", "alpha": round(a * gone, 4),
                                         "blur": round(b, 3)}],
                              "size": o["url"]["size"], "top": end_y["url"], "cx": 540, "maxRight": 912, "track": -0.01,
                              "shadow": True}
    if t >= T["nia"] - 0.05 and gone > 0:
        a, b = word_in(t, T["nia"] - 0.05, 0, dur=0.2)
        ov["lines"]["disc"] = {"words": [{"t": o["disc"]["text"], "color": "rgba(255,255,255,0.86)",
                                          "alpha": round(a * gone, 4), "blur": round(b, 3)}],
                               "size": o["disc"]["size"], "top": end_y["disc"], "cx": 540,
                               "maxRight": 912, "track": 0.0, "shadow": True}
    return ov


def sample_accent(ep: dict, run: Path, take: dict) -> str:
    """The app's own green: median of the bright green text pixels in the sheet (its '+x%' figures)."""
    smp = ep["overlay"]["accent_sample"]
    ev = take["events"][smp["after_event"]]
    f = run / "take" / "frames" / frame_at(ev["end"] + 0.05, take)
    a = np.asarray(Image.open(f).convert("RGB"), np.int16)
    x0, y0, x1, y1 = smp["rect"]
    reg = a[y0:y1, x0:x1].reshape(-1, 3)
    g = reg[(reg[:, 1] > 150) & (reg[:, 0] < 120) & (reg[:, 2] < 200)]
    if len(g) < 200:
        raise InputError("could not sample the app's green from the sheet")
    c = np.median(g, 0).astype(int)
    return "#%02x%02x%02x" % tuple(c)


# ================================================================================================ render plan
def cfg_at(t: float, ep: dict, T: dict, take: dict, seed: float, points=None) -> dict:
    p = pose_at(t, ep, T)
    s = src_time(t, T, take)
    readable = p["z"] >= 1.2
    c = {"screen": "/take/" + frame_at(s, take), "z": round(p["z"], 6), "uv": p["uv"], "A": [round(x, 3) for x in p["A"]],
         "yaw": round(p["yaw"], 4), "camPitch": -1.5, "sheen": ep["sheen"]["read"] if readable else ep["sheen"]["wide"],
         "seed": seed}
    ts = tap_state(t, ep, T)
    if ts:
        c["tap"] = ts
    if points:
        c["points"] = points
    return c


PROBE_UV = [[0, 0], [1080, 0], [0, 2400], [1080, 2400], [540, 1200], [540, 400], [540, 2000], [100, 1200], [980, 1200]]


def run_probe(run: Path, cfgs: list[dict]) -> dict:
    req = run / "probe_req.json"
    wjson(req, cfgs)
    out = run / "probe_res.json"
    r = subprocess.run([str(CONDA_PY), str(HERE / "studio_render.py"), "probe", "--run", str(run), "--req", str(req),
                        "--out", str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    if r.returncode != 0:
        raise InputError("probe failed: " + (r.stderr or "")[-1500:] + (r.stdout or "")[-500:])
    return rjson(out)


def run_render(run: Path, plan: dict, name: str) -> dict:
    p = run / f"{name}.json"
    wjson(p, plan)
    r = subprocess.run([str(CONDA_PY), str(HERE / "studio_render.py"), "render", "--run", str(run), "--plan", str(p),
                        "--ffmpeg", str(FFMPEG), "--save-dir", str(run / "frames")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=7200)
    if r.returncode != 0:
        raise InputError("render failed: " + (r.stderr or "")[-2000:] + (r.stdout or "")[-800:])
    return rjson(p.with_name(p.stem + "_result.json"))


# ================================================================================================ checks (geometry)
KEEPOUT_RX = re.compile(r"\b(HOLD|BUY|SELL|BULLISH|BEARISH|MACD|RSI|SCORE|OUR RECORD|KEY LEVEL|GUEST|FREE STOCK|"
                        r"\d\s*/\s*2|\d+\s*/\s*100|SOURCE|EDGAR|SPONSOR|PICKS?|SPY|\(R\)|\(D\)|\(I\))\b", re.I)


def scan_keepouts(ep: dict) -> dict:
    """Read every node of the device's accessibility snapshots for each state (the whole visible screen text with
    rects) and add any keep-out element found to that state's keep-out rects, so the projection gate covers it."""
    out = {"snapshots": {}, "added": []}
    for state, paths in ep["take"].get("snapshots", {}).items():
        n = 0
        for sn in paths:                       # {"path", "scroll"}: rects are shifted back to the state's unscrolled frame
            p, sc_off = sn["path"], sn.get("scroll", 0)
            nodes = rjson(Path(p))["data"]["nodes"]
            for nd in nodes:
                lab = (nd.get("label") or "") + " " + (nd.get("contentDescription") or "")
                r = nd.get("rect")
                if not lab.strip() or not r or nd.get("systemBar"):
                    continue
                n += 1
                words = [w for w in F.PROVIDER_WORDS if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", lab.lower())]
                if KEEPOUT_RX.search(lab) or words:
                    rect = [r["x"], r["y"] + sc_off, r["x"] + r["width"], r["y"] + r["height"] + sc_off]
                    key = f"scan: {lab.strip()[:50]}"
                    ep["take"]["states"][state]["keepout"][key] = rect
                    out["added"].append({"state": state, "label": lab.strip()[:80], "rect": rect, "snapshot": Path(p).name})
        out["snapshots"][state] = {"files": [Path(s["path"]).name for s in paths], "nodes_with_text": n}
    return out


def rects_for_frame(ep: dict, take: dict, s: float, fname: str) -> tuple[str, dict, dict, int]:
    """Which app state a source time shows, its rects and keep-outs in capture px (scroll applied)."""
    ev = take["events"]
    st = ep["take"]["states"]

    def at(ref: str) -> float:                    # "open.tap", "close.end": an event field from the pixels
        e, f = ref.split(".")
        return ev[e][f]
    default = [k for k, v in st.items() if "span" not in v]
    if len(default) != 1:
        raise InputError("episode take.states needs exactly one state without a span (the rest state)")
    for name, v in st.items():
        if "span" not in v or not (at(v["span"][0]) <= s < at(v["span"][1])):
            continue
        off = 0
        se = v.get("scroll_event")
        if se and se in ev:
            off = take["scroll"].get(fname, ev[se].get("offset_settled", 0) if s >= ev[se]["start"] else 0)
        sh = lambda r: [r[0], r[1] - off, r[2], r[3] - off]  # noqa: E731
        return name, {k: sh(r) for k, r in v["rects"].items()}, {k: sh(r) for k, r in v["keepout"].items()}, off
    d = default[0]
    return d, st[d]["rects"], st[d]["keepout"], 0


def map_rect(r, m) -> list[float]:
    """capture rect -> output rect through the probe's projected corner points (pts order: TL, TR, BL, BR of the rect)."""
    xs = [p[0] for p in m]
    ys = [p[1] for p in m]
    return [min(xs), min(ys), max(xs), max(ys)]


def overlap(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


# ================================================================================================ sheets
def label(im: Image.Image, text: str, size=26) -> Image.Image:
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, im.width, size + 12), fill=(0, 0, 0))
    d.text((8, 4), text, font=F.font(size), fill=(255, 255, 255))
    return im


def shorts_overlay(im: Image.Image) -> Image.Image:
    """mock YouTube Shorts chrome at 1080x1920: right action column, bottom title block, top icons, bottom scrim"""
    base = im.convert("RGBA")
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(1380, 1920):
        a = int(150 * ((y - 1380) / 540) ** 1.2)
        d.line([(0, y), (1080, y)], fill=(0, 0, 0, a))
    for y in [1010, 1170, 1330, 1490, 1650]:
        d.ellipse([952, y - 44, 1040, y + 44], fill=(255, 255, 255, 70), outline=(255, 255, 255, 200), width=3)
        d.rectangle([966, y + 52, 1026, y + 72], fill=(255, 255, 255, 150))
    d.rounded_rectangle([960, 1790, 1032, 1862], 12, fill=(255, 255, 255, 120))
    d.ellipse([36, 1600, 116, 1680], fill=(255, 255, 255, 140))
    d.rectangle([134, 1622, 420, 1656], fill=(255, 255, 255, 170))
    d.rounded_rectangle([440, 1612, 640, 1668], 28, fill=(255, 255, 255, 200))
    d.rectangle([36, 1712, 860, 1748], fill=(255, 255, 255, 170))
    d.rectangle([36, 1764, 640, 1800], fill=(255, 255, 255, 170))
    d.rectangle([36, 1834, 520, 1862], fill=(255, 255, 255, 120))
    for x in (880, 980):
        d.ellipse([x, 60, x + 64, 124], outline=(255, 255, 255, 200), width=4)
    d.rectangle([0, 1910, 1080, 1916], fill=(255, 0, 0, 200))
    return Image.alpha_composite(base, ov).convert("RGB")


def contact(items: list[tuple[str, Image.Image]], out: Path, tw=360, cols=6, lab=22) -> Path:
    th = tw * 16 // 9
    rows = math.ceil(len(items) / cols)
    sh = Image.new("RGB", (cols * tw + (cols - 1) * 6, rows * (th + 6)), (20, 20, 24))
    for k, (t, im) in enumerate(items):
        sh.paste(label(im.convert("RGB").resize((tw, th), Image.LANCZOS), t, lab), ((k % cols) * (tw + 6), (k // cols) * (th + 6)))
    sh.save(out)
    return out


# ================================================================================================ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode")
    ap.add_argument("--out")
    ap.add_argument("--check-only", action="store_true", help="stop after check6.png")
    ap.add_argument("--skip-render", action="store_true", help="reuse video_noaudio.mp4")
    a = ap.parse_args(argv)
    t_start = time.time()
    ep = rjson(Path(a.episode))
    run = Path(a.out) if a.out else MEDIA / ".ops" / "app-showcase" / ep["slug"]
    run.mkdir(parents=True, exist_ok=True)
    try:
        return build(ep, run, a, t_start)
    except InputError as e:
        wjson(run / "error.json", {"error": str(e), "at": now_z()})
        print("INPUT ERROR:", e)
        return 2


def build(ep: dict, run: Path, a, t_start: float) -> int:
    # ---- words first (cheap): banned words, prices, tickers we write ourselves
    texts = [ln["text"].replace("@", " ").replace("*", "").replace("~", "").replace("|", " ") for ln in ep["lines"]]
    texts += [" ".join(ep["headline"]["words"]), ep["youtube"]["title"], ep["youtube"]["description"],
              ep["overlay"]["url"]["text"], ep["overlay"]["disc"]["text"]]
    # every ticker-like token the app shows in this take (all states' screen text) plus the stock opened: we never write
    # or say one ourselves (case-sensitive: the app's own all-caps labels are in the set too, which only makes it stricter)
    tickers = {ep["take"]["stock"].upper()}
    for st_ in ep["take"]["states"].values():
        for s_ in st_["text"]:
            tickers |= set(TICKER_RX.findall(s_))
    bad = []
    for x in texts:
        low = x.lower()
        for w in BANNED:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                bad.append(f"banned {w!r} in {x!r}")
        for w in F.PROVIDER_WORDS:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                bad.append(f"provider {w!r} in {x!r}")
        if PRICE_RX.search(x):
            bad.append(f"price-like figure in {x!r}")
        toks = {w.strip(".,:;!?'’()#") for w in x.split()}
        hit = sorted(toks & tickers)
        if hit:
            bad.append(f"ticker {hit} in {x!r}")
        if "prediction" in low and "not a prediction" not in low:
            bad.append(f"'prediction' outside 'not a prediction' in {x!r}")
    if bad:
        raise InputError("words: " + "; ".join(bad))
    word_gate = {"texts_checked": len(texts), "tickers_checked": sorted(tickers), "hits": []}

    ko_scan = scan_keepouts(ep)
    take = ingest_take(ep, run)
    rl = rjson(run / "take" / "rect_log.json")
    rl["keepout_scan"] = ko_scan
    wjson(run / "take" / "rect_log.json", rl)
    lines, clips, speed = voice(ep, run)
    T = timeline(ep, lines, take)
    caps = captions(lines, T)
    accent = sample_accent(ep, run, take)
    n = int(round(T["end"] * FPS))
    dur = n / FPS
    lo, hi = ep["duration_s"]
    if not lo <= dur <= hi:
        raise InputError(f"duration {dur:.2f} s outside {lo}-{hi} s: change the lines")

    # scene spec for the page
    s0 = PHONE_H_WHOLE / BODY_H_MM
    used_frames = sorted({frame_at(src_time(i / FPS + dt, T, take), take) for i in range(n) for dt in (-1 / 120, 0, 1 / 120)})
    ph = check_punch_hole(take, run, used_frames)
    scene = {"look": LOOK, "s0": s0, "cap": [1080, 2400], "punch_hole": [540, 56] if ph["ok"] else None,
             "tap_d_mm": ep["tap"]["d_frac"] * 68, "take_frames": str(run / "take" / "frames")}
    wjson(run / "scene.json", scene)

    # end-card text slots: under the end pose's phone
    o = ep["overlay"]
    pe = ep["poses"]["end"]
    end_bottom = pe["A"][1] + pe["z"] * PHONE_H_WHOLE / 2
    pd = ep["poses"]["end_drift"]
    end_bottom = max(end_bottom, pd["A"][1] + pd["z"] * PHONE_H_WHOLE / 2)
    url_top = round(end_bottom + o["end_gap"])
    disc_top = round(url_top + o["url"]["size"] * 0.727 + o["url"]["size"] * 0.21 + 30)
    end_y = {"url": url_top, "disc": disc_top}

    # ---- probe every frame (centre + shutter ends): framing, sub-frame counts, keep-out projection, overlay vs screen
    centre = []
    for i in range(n):
        t = i / FPS
        s = src_time(t, T, take)
        fname = frame_at(s, take)
        state, rects, keep, off = rects_for_frame(ep, take, s, fname)
        pts = []
        names = []
        for k, r in list(rects.items()) + [("KEEPOUT:" + k, r) for k, r in keep.items()]:
            pts += [[r[0], r[1]], [r[2], r[1]], [r[0], r[3]], [r[2], r[3]]]
            names.append(k)
        c = cfg_at(t, ep, T, take, 0.0, PROBE_UV + pts)
        centre.append((c, names, state, off))
    ends = []
    for i in range(n):
        t = i / FPS
        for dt in (-1 / 120, 1 / 120):
            ends.append(cfg_at(t + dt, ep, T, take, 0.0, PROBE_UV))
    pr = run_probe(run, [c for c, *_ in centre] + ends)
    res = pr["res"]
    frames_meta = []
    for i in range(n):
        m = res[i]
        e0, e1 = res[n + 2 * i], res[n + 2 * i + 1]
        travel = max(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) for p0, p1 in zip(e0["pts"], e1["pts"]))
        nsub = max(1, min(SUBS_MAX, math.ceil(travel / 0.9 - 1e-9))) if travel > 0.35 else 1
        c, names, state, off = centre[i]
        rr = {}
        k0 = len(PROBE_UV)
        for j, nm in enumerate(names):
            rr[nm] = map_rect(None, m["pts"][k0 + 4 * j:k0 + 4 * j + 4])
        frames_meta.append({"i": i, "t": round(i / FPS, 4), "travel_px": round(travel, 3), "subs": nsub,
                            "phone_rect": m["phone_rect"], "screen_rect": m["screen_rect"], "px_per_cap": m["px_per_cap"],
                            "state": state, "scroll": off, "rects": rr, "screen": c["screen"], "z": c["z"], "yaw": c["yaw"]})

    # ---- plan: every frame's sub-frames + overlay
    def plan_frame(i: int) -> dict:
        t = i / FPS
        ns = frames_meta[i]["subs"]
        seed = (i * 0.137) % 1.0
        subs = [cfg_at(t + ((k + 0.5) / ns - 0.5) / 60.0, ep, T, take, seed) for k in range(ns)]
        return {"i": i, "subs": subs, "ov": overlay_at(t, ep, T, caps, accent, end_y)}

    key = {k: min(n - 1, max(0, int(round(evalx(ex, T) * FPS)))) for k, ex in ep["key_frames"].items()}
    key["frame0"], key["last"] = 0, n - 1

    overlay_boxes = {}
    # check6: six frames rendered first and looked at before the full render
    c6 = ep["check6"]
    plan6 = {"fps": FPS, "out": str(run / "check6_unused.mp4"), "no_video": True, "save": [key[k] for k in c6],
             "frames": [plan_frame(key[k]) for k in c6]}
    r6 = run_render(run, plan6, "plan_check6")
    for fr in r6["frames"]:
        overlay_boxes[fr["i"]] = fr["boxes"]
    ims = [(f"{k} t={key[k] / FPS:.2f}s", Image.open(run / "frames" / f"f{key[k]:04d}.png")) for k in c6]
    contact(ims, run / "check6.png", tw=540, cols=3, lab=28)
    T_out = {k: v for k, v in T.items() if k not in ("moves", "srcmap")}
    wjson(run / "timeline.json", {"T": T_out, "moves": T["moves"], "srcmap": T["srcmap"], "key_frames": key, "n": n,
                                  "captions": caps, "accent": accent, "end_y": end_y, "punch_hole": ph,
                                  "subs_total": sum(f["subs"] for f in frames_meta),
                                  "frames": [{k: v for k, v in f.items() if k != "rects"} for f in frames_meta]})
    if a.check_only:
        print(json.dumps({"check6": str(run / "check6.png"), "n": n, "dur": dur, "key": key,
                          "subs_total": sum(f["subs"] for f in frames_meta)}))
        return 0

    # ---- full render
    t_r = time.time()
    if not (a.skip_render and (run / "video_noaudio.mp4").is_file()):
        save = sorted(set(list(range(0, n, 5)) + list(key.values()) + [n - 1]))
        plan = {"fps": FPS, "out": str(run / "video_noaudio.mp4"), "crf": 17, "save": save,
                "frames": [plan_frame(i) for i in range(n)]}
        rr = run_render(run, plan, "plan_full")
        wjson(run / "render.json", {k: v for k, v in rr.items() if k != "frames"} | {"frames_boxes": {f["i"]: f["boxes"] for f in rr["frames"]}})
    render_min = round((time.time() - t_r) / 60, 2)
    rinfo = rjson(run / "render.json")
    for i, b in rinfo["frames_boxes"].items():
        overlay_boxes[int(i)] = b

    # ---- sound: voice, tap pop one frame after the tap, sheet slides, soft whooshes on moves >= 1 s apart, low bed
    kit = S.make_kit(F.KIT_DIR)
    from showcase import make_kit as sc_kit  # noqa: E402  (the series' numpy pop)
    kit = {**kit, **sc_kit()}
    cues = [{"sfx": "pop", "at": T["v_tap"] + 1 / FPS, "gain_db": -4.0}]
    for evn in ep["sfx"]["slides"]:              # the app's own sheet slides (visible causes)
        cues.append({"sfx": "swish", "at": T["v_" + evn] + 0.04, "gain_db": -12.5})
    last_w = -9.0
    for m in T["moves"]:
        if m["name"] in ep["sfx"]["no_whoosh"]:
            continue
        if m["t0"] - last_w >= 1.0:
            cues.append({"sfx": "whoosh", "at": max(0.0, m["t0"] + 0.02), "gain_db": -15.0})
            last_w = m["t0"]
    pre = run / "mix_pre.wav"
    mixinfo = S.mix(clips, cues, dur, pre, kit, bed_under_voice_db=ep["bed_under_voice_db"])
    mastered = run / "mix_master.wav"
    minfo = F.master(pre, mastered)
    final = run / "final.mp4"
    # BT.709 primaries, transfer and matrix written into the H.264 VUI (stream copy keeps the pixels untouched)
    ff(["-i", str(run / "video_noaudio.mp4"), "-i", str(mastered), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(final)])

    # ---- outputs: frame0, sheet, phone, voice script, youtube, episode, proof, QA
    shutil.copy2(run / "frames" / "f0000.png", run / "frame0.png")
    dec = run / "qa_decoded"
    if dec.exists():
        shutil.rmtree(dec)
    dec.mkdir()
    ff(["-i", str(final), "-fps_mode", "passthrough", str(dec / "d%04d.png")])
    dfiles = sorted(dec.glob("d*.png"))
    sheet_items = []
    for k in range(0, n, 15):
        sheet_items.append((f"{k / FPS:.1f}s", Image.open(dfiles[k])))
    contact(sheet_items, run / "sheet.png", tw=216, cols=9, lab=20)
    ph_items = []
    for nm in ["frame0", "tap", "read1", "read2_rows", "end"]:
        lossless = run / "frames" / f"f{key[nm]:04d}.png"
        im = shorts_overlay(Image.open(lossless if lossless.is_file() else dfiles[key[nm]]).convert("RGB")).resize(
            (360, 640), Image.LANCZOS)
        ph_items.append((f"{nm} {key[nm] / FPS:.1f}s", im))
    sh = Image.new("RGB", (5 * 360 + 4 * 8, 640 + 34), (20, 20, 24))
    for k, (lab, im) in enumerate(ph_items):
        sh.paste(im, (k * 368, 34))
        ImageDraw.Draw(sh).text((k * 368 + 6, 4), lab, font=F.font(22), fill=(255, 255, 255))
    sh.save(run / "phone.png")

    vs = {"voice": ep["voice"]["voice"], "speed": speed, "lines": [
        {"id": ln["id"], "say": ln["say"], "t0": ln["t0"], "t1": ln["t1"],
         "words": [{"w": w["word"], "t0": w["t0"], "t1": w["t1"]} for c in ln["chunks"] for w in c["words"]]} for ln in lines]}
    wjson(run / "voice_script.json", vs)
    (run / "voice_script.txt").write_text("\n".join(
        f"{ln['t0']:6.2f}-{ln['t1']:6.2f}  {ln['say']}" for ln in vs["lines"]) + "\n", encoding="utf-8")
    yt = dict(ep["youtube"])
    wjson(run / "youtube.json", yt)
    wjson(run / "episode.json", {**ep, "resolved": {"T": T_out, "moves": T["moves"], "srcmap": T["srcmap"],
                                                     "accent": accent, "voice_speed": speed, "n_frames": n,
                                                     "duration_s": dur}})
    q = qa(run, ep, T, lines, frames_meta, overlay_boxes, key, final, dfiles, take, accent, end_y, minfo, rinfo, caps, ph)
    q["words_gate"] = word_gate
    q["keepout_scan"] = ko_scan
    sm_ = [s for s in T["srcmap"] if "frames" in s]
    if sm_:
        st_ = [take["files"].index(frame_at(x, take)) for x in sm_[0]["frames"]]
        q["scroll_retime"] = {"event": sm_[0]["event"], "output_frames": len(st_), "distinct_source_frames": len(set(st_)),
                              "source_frames_used": [take["files"][k] for k in st_],
                              "rule": "each output frame a different recorded frame (no repeats, no interpolation)"}
        if len(set(st_)) != len(st_):
            q["fails"].append("retimed scroll repeats a source frame")
            q["passed"] = False
    q["render_minutes"] = render_min
    q["build_minutes"] = round((time.time() - t_start) / 60, 2)
    wjson(run / "qa.json", q)
    proof(run, ep, take, T, accent, mixinfo, rinfo, q)
    print(json.dumps({"final": str(final), "passed": q["passed"], "fails": q["fails"]}, ensure_ascii=False))
    return 0 if q["passed"] else 1


# ================================================================================================ QA
def qa(run, ep, T, lines, fm, boxes, key, final, dfiles, take, accent, end_y, minfo, rinfo, caps, ph) -> dict:
    fails = []
    q = {"at": now_z()}
    pb = F.probe(final)
    v = [s for s in pb["streams"] if s.get("codec_name") == "h264"][0]
    au = [s for s in pb["streams"] if s.get("codec_name") == "aac"]
    q["file"] = {"duration_s": float(pb["format"]["duration"]), "fps": v["r_frame_rate"], "size": [v["width"], v["height"]],
                 "frames": int(v.get("nb_frames", 0)), "mb": round(final.stat().st_size / 1e6, 2), "audio": bool(au)}
    cs = subprocess.run([str(FFPROBE), "-v", "error", "-select_streams", "v", "-show_entries",
                         "stream=color_space,color_transfer,color_primaries,color_range,pix_fmt", "-of", "json", str(final)],
                        capture_output=True, text=True)
    q["file"]["color"] = json.loads(cs.stdout)["streams"][0]
    col = q["file"]["color"]
    if not (col.get("color_space") == col.get("color_transfer") == col.get("color_primaries") == "bt709"):
        fails.append(f"not fully BT.709 tagged: {col}")
    if q["file"]["mb"] > 25:
        fails.append("file over 25 MB")
    if v["r_frame_rate"] != "30/1" or [v["width"], v["height"]] != [1080, 1920]:
        fails.append("not 1080x1920 at 30 fps")
    loud = F.loudness(final)
    q["loudness"] = loud
    if abs(loud["integrated_lufs"] + 14) > 0.6 or loud["true_peak_dbtp"] > -1.0:
        fails.append(f"loudness {loud}")
    # brand words
    bw = []
    for ln in lines:
        for c in ln["chunks"]:
            for w in c["words"]:
                if w["word"].lower().strip(",.") in ("rapid",):
                    bw.append(w["t0"])
    q["brand_spoken_at_s"] = bw
    if not bw or bw[0] > 4.0 or bw[-1] < q["file"]["duration_s"] - 4.5:
        fails.append("brand not spoken in the first 4 s and at the end")
    # pill on every sampled frame (the overlay boxes) and decoded pixels at its spot
    n = len(fm)
    missing = [i for i in range(n) if int(i) in boxes and "pill" not in boxes[int(i)]]
    q["pill_on_rendered_frames"] = {"frames_with_boxes": len(boxes), "missing": missing[:10]}
    if missing:
        fails.append("pill missing on some frames")
    pb_ = boxes[0]["pill"]
    q["pill_box"] = [round(x, 1) for x in pb_]
    # whole-phone pose
    wf = fm[key["whole"]]
    pr = wf["phone_rect"]
    q["whole_pose"] = {"frame": key["whole"], "phone_rect": [round(x, 1) for x in pr], "h": round(pr[3] - pr[1], 1),
                       "w": round(pr[2] - pr[0], 1), "centre": [round((pr[0] + pr[2]) / 2, 1), round((pr[1] + pr[3]) / 2, 1)],
                       "yaw": wf["yaw"]}
    if not (pr[1] >= 317.5 and pr[3] <= 1468.5 and pr[0] >= 60 and pr[2] <= 920 and 1130 <= pr[3] - pr[1] <= 1170):
        fails.append(f"whole-phone pose off spec {q['whole_pose']}")
    # headline clear of the phone top in the whole pose
    hb = boxes.get(key["whole"], {}).get("headline")
    if hb:
        ink_bottom = hb[1] + hb[3]
        q["headline_clear_px"] = round(pr[1] - ink_bottom, 1)
        if q["headline_clear_px"] < SLOT_GAP_PHONE:
            fails.append(f"headline only {q['headline_clear_px']} px above the phone")
    # the slot above the phone, on every rendered frame: pill -> headline/chip >= 16 px, headline/chip -> phone >= 18 px;
    # end text under the phone >= 18 px below it
    slot = {"min_pill_gap": 1e9, "min_phone_gap": 1e9, "min_end_gap": 1e9, "hits": []}
    for i, b in boxes.items():
        i = int(i)
        prr = fm[i]["phone_rect"]
        pill_b = b["pill"][1] + b["pill"][3] if "pill" in b else 230
        for nm in ("headline", "caption_chip", "caption"):
            if nm not in b:
                continue
            r = b[nm]
            gp, gph = r[1] - pill_b, prr[1] - (r[1] + r[3])
            slot["min_pill_gap"] = min(slot["min_pill_gap"], round(gp, 1))
            if r[0] < prr[2] and r[0] + r[2] > prr[0]:
                slot["min_phone_gap"] = min(slot["min_phone_gap"], round(gph, 1))
            if gp < SLOT_GAP_PILL or (gph < SLOT_GAP_PHONE and r[0] < prr[2] and r[0] + r[2] > prr[0]):
                slot["hits"].append({"i": i, "what": nm, "pill_gap": round(gp, 1), "phone_gap": round(gph, 1)})
        for nm in ("url", "disc"):
            if nm in b:
                g = b[nm][1] - prr[3]
                slot["min_end_gap"] = min(slot["min_end_gap"], round(g, 1))
                if g < SLOT_GAP_PHONE:
                    slot["hits"].append({"i": i, "what": nm, "below_phone_gap": round(g, 1)})
    slot["n_hits"] = len(slot["hits"])
    slot["hits"] = slot["hits"][:10]
    q["slot_clearance"] = slot
    if slot["n_hits"]:
        fails.append(f"slot clearance: {slot['n_hits']} hits")
    # settled holds on the readable beats (>= 1.2 s each)
    hold = []
    for nm, a_, b_ in ep["holds"]:
        a0, b0 = evalx(a_, T), evalx(b_, T)
        hold.append({"beat": nm, "from": round(a0, 3), "to": round(b0, 3), "s": round(b0 - a0, 3)})
        if b0 - a0 < 1.2 - 1e-6:
            fails.append(f"hold {nm} only {b0 - a0:.2f} s")
    q["holds"] = hold
    # the touch disc: gone within 0.1 s of the sheet's first visible movement (first source frame after the tap whose
    # change is >= 1.0 mean)
    tev = take["events"][ep["take"]["events"][0]]
    mv_src = min([e["pts"] for e in take["log"] if e["pts"] > tev["tap"] and e["diff"] >= 1.0] or [tev["tap"]])
    t_move = T["v_tap"] + (mv_src - tev["tap"])
    late = [round(t, 3) for t in np.arange(t_move + 0.1, t_move + 0.6, 1 / 120) if (tap_state(t, ep, T) or {}).get("alpha", 0) > 0]
    q["touch_disc"] = {"sheet_first_moves_s": round(t_move, 3), "disc_gone_by_s": round(T["v_tap"] + ep["tap"]["fade_after"], 3),
                       "visible_after_move_plus_0.1": late[:5], "at_capture_px": ep["tap"].get("disc_at"),
                       "real_press_px": ep["take"]["tap_at"]}
    if late:
        fails.append("touch disc still visible > 0.1 s after the sheet starts to move")
    # readable share and the smallest app text
    rd = [f for f in fm if f["z"] >= 1.2]
    q["readable"] = {"rule": "pose zoom >= 1.2x the whole-phone scale (screen >= 0.56 output px per capture px)",
                     "frames": len(rd), "share": round(len(rd) / n, 3)}
    st = ep["take"]["states"]
    smallest = {}
    for nm in ["frame0", "read1", "read2_same", "read2_rows", "whole", "end"]:
        f = fm[key[nm]]
        sc = f["px_per_cap"][1]
        smallest[nm] = {"t": f["t"], "out_px_per_capture_px": round(sc, 3),
                        "line_box_px": {"14sp body (42 px box)": round(42 * sc, 1), "16sp (51-57 px box)": round(54 * sc, 1),
                                        "title (66 px box)": round(66 * sc, 1)},
                        "cap_height_px_body_14sp": round(26 * sc, 1)}
    q["text_size"] = smallest
    if q["readable"]["share"] < 0.5:
        fails.append(f"readable share {q['readable']['share']}")
    # keep-out projection gate: any keep-out rect inside the screen and the output frame on any frame
    ko = []
    for f in fm:
        sr = f["screen_rect"]
        for nm, r in f["rects"].items():
            if not nm.startswith("KEEPOUT:"):
                continue
            inside_cap = r  # projected; visible if it intersects the visible screen and the frame
            vis = overlap(r, [max(0, sr[0]), max(0, sr[1]), min(W, sr[2]), min(H, sr[3])])
            if vis:
                ko.append({"i": f["i"], "what": nm, "rect": [round(x) for x in r]})
    n_ko = {}
    for f in fm:
        for nm in f["rects"]:
            if nm.startswith("KEEPOUT:"):
                n_ko[nm] = n_ko.get(nm, 0) + 1
    on_cap = sorted({nm for f in fm for nm, r in f["rects"].items() if nm.startswith("KEEPOUT:")
                     and overlap(r, f["screen_rect"])})
    q["keepout_projection"] = {"checked_frames": n, "visible": ko[:20], "rects_projected": n_ko,
                               "keepouts_ever_inside_the_screen": on_cap,
                               "note": ("every logged keep-out lies outside the recorded screen area this take shows "
                                        "(off-screen by scroll position), so the gate is trivially satisfied; OCR is the "
                                        "real guard") if not on_cap else "keep-outs inside the screen are checked against "
                                                                         "the visible frame"}
    if ko:
        fails.append("keep-out element in frame")
    # overlay vs screen: nothing we draw overlaps the screen
    ov_hits = []
    for i, b in boxes.items():
        sr = fm[int(i)]["screen_rect"]
        for nm, r in b.items():
            rr = [r[0], r[1], r[0] + r[2], r[1] + r[3]]
            if overlap(rr, sr):
                ov_hits.append({"i": int(i), "what": nm, "box": [round(x) for x in rr], "screen": [round(x) for x in sr]})
    q["overlay_vs_screen"] = {"frames_checked": len(boxes), "hits": ov_hits[:20]}
    if ov_hits:
        fails.append("overlay over the screen")
    # safe zone for captions and end text
    sz = []
    for i, b in boxes.items():
        for nm, r in b.items():
            if nm == "pill":
                continue
            if r[0] < 60 or r[0] + r[2] > 920 or r[1] < 170 or r[1] + r[3] > 1500:
                sz.append({"i": int(i), "what": nm, "box": [round(x) for x in r]})
    q["safe_zone"] = {"hits": sz[:10], "n": len(sz)}
    if sz:
        fails.append("overlay text outside x 60-920 / y 170-1500")
    # colour check: flat UI patches of the screen vs the capture frame shown (still frames only)
    cc = []
    for nm in ["whole", "read1", "read2_rows", "end", "last"]:
        i = key[nm]
        f = fm[i]
        if f["subs"] > 1 or not (run / "frames" / f"f{i:04d}.png").is_file():
            continue
        img = np.asarray(Image.open(run / "frames" / f"f{i:04d}.png").convert("RGB"), np.float32)
        cap = np.asarray(Image.open(run / "take" / "frames" / f["screen"].split("/")[-1]).convert("RGB"), np.float32)
        sr = f["screen_rect"]
        sc = f["px_per_cap"][0]
        found = 0
        for (u, vv) in [(300, 60), (540, 2380), (60, 1500), (1020, 1000), (540, 300), (200, 1800), (900, 1650)]:
            pc = cap[vv - 8:vv + 9, u - 8:u + 9]
            if pc.size == 0 or pc.max() - pc.min() > 0:
                continue
            x = sr[0] + u * (sr[2] - sr[0]) / 1080
            y = sr[1] + vv * (sr[3] - sr[1]) / 2400
            if not (3 <= x < W - 3 and 3 <= y < H - 3):
                continue
            rp = img[int(y) - 2:int(y) + 3, int(x) - 2:int(x) + 3].reshape(-1, 3).mean(0)
            cc.append({"frame": nm, "uv": [u, vv], "capture": pc.reshape(-1, 3).mean(0).round(1).tolist(),
                       "render": rp.round(1).tolist(), "max_abs_diff": round(float(np.abs(rp - pc.reshape(-1, 3).mean(0)).max()), 2)})
            found += 1
    q["colour_check"] = cc
    if not cc or max(c["max_abs_diff"] for c in cc) > 1.0:
        fails.append("screen colours differ from the capture by more than 1/255 on a flat patch")
    # adjacent-frame difference scan (pops) on the decoded final
    sm = [np.asarray(Image.open(p).convert("L").resize((108, 192)), np.float32) for p in dfiles]
    d = np.array([float(np.abs(sm[i] - sm[i - 1]).mean()) for i in range(1, len(sm))])
    pops = []
    ui_frames = set()
    for e in take["events"].values():
        pass
    for i in range(1, len(d) - 1):
        nb = max(1e-3, (d[i - 1] + d[i + 1]) / 2)
        if d[i] > 3 * nb and d[i] > 1.0:
            t = (i + 1) / FPS
            s_now, s_prev = src_time(t, T, take), src_time(t - 1 / FPS, T, take)
            ui_change = frame_at(s_now, take) != frame_at(s_prev, take)
            pops.append({"frame": i + 1, "t": round(t, 3), "diff": round(float(d[i]), 2), "neighbours": round(float(nb), 2),
                         "recorded_ui_change": ui_change})
    q["pop_scan"] = {"mean_diff_max": round(float(d.max()), 2), "spikes": pops}
    # retimed scroll: every output frame inside it must differ from the previous one (no frozen frame = no judder)
    for s_ in [s for s in T["srcmap"] if "frames" in s]:
        i0 = int(math.ceil(s_["at"] * FPS - 1e-6))
        i1 = i0 + len(s_["frames"])
        seg = [round(float(d[i - 1]), 3) for i in range(i0 + 1, min(i1, len(d) + 1))]
        frozen = [i0 + 1 + k for k, x in enumerate(seg) if x < 0.05]
        q["scroll_smoothness"] = {"frames": [i0, i1], "adjacent_diffs": seg, "frozen_frames": frozen,
                                  "diff_min": min(seg) if seg else None, "diff_max": max(seg) if seg else None}
        if frozen:
            fails.append(f"retimed scroll has {len(frozen)} frozen frames")
    if any(not p["recorded_ui_change"] for p in pops):
        fails.append("one-frame pop not caused by a recorded UI change")
    # mid-push blur frame
    mids = [f for f in fm if f["subs"] > 1]
    mid = max(mids, key=lambda f: f["travel_px"]) if mids else None
    if mid:
        q["mid_push"] = {"frame": mid["i"], "t": mid["t"], "travel_px": mid["travel_px"], "subs": mid["subs"],
                         "png": str(run / "qa_mid_push.png")}
        ff(["-i", str(final), "-vf", f"select=eq(n\\,{mid['i']})", "-vframes", "1", str(run / "qa_mid_push.png")])
    q["subframes"] = {"total": sum(f["subs"] for f in fm), "max": max(f["subs"] for f in fm),
                      "frames_blurred": len(mids)}
    # first vs last frame
    f0 = np.asarray(Image.open(dfiles[0]).convert("RGB"), np.float32)
    fl = np.asarray(Image.open(dfiles[-1]).convert("RGB"), np.float32)
    q["first_vs_last"] = {"mean_abs_diff": round(float(np.abs(f0 - fl).mean()), 2),
                          "last_pose": {"z": fm[-1]["z"], "yaw": fm[-1]["yaw"]}, "first_pose": {"z": fm[0]["z"], "yaw": fm[0]["yaw"]}}
    # first real UI change and the longest stretch without a visible change
    q["first_ui_change_s"] = round(T["v_tap"], 3)
    if T["v_tap"] > 2.6:
        fails.append(f"first real UI change at {T['v_tap']:.2f} s (target ~2.5, limit 2.6)")
    # a frame changes visibly when its pixels change (> 0.25/255 mean on the grey decode) or the camera moves the phone
    # by >= 0.3 px (probe travel over the frame interval: a slow move counts, a held pose does not)
    mv = np.array([f["travel_px"] * 2 >= 0.3 for f in fm[1:]])     # travel is over half a frame (the shutter)
    ch = (d > 0.25) | mv[:len(d)]
    longest, cur, start = 0, 0, 0
    for i, c in enumerate(ch):
        cur = 0 if c else cur + 1
        if cur > longest:
            longest, start = cur, i - cur + 1
    q["longest_still_s"] = {"seconds": round(longest / FPS, 2), "from_s": round((start + 1) / FPS, 2),
                            "rule": "no frame with mean diff > 0.25/255 (108x192 grey decode) and phone travel < 0.3 px/frame",
                            "pixels_only_longest_s": round(_longest(d > 0.25) / FPS, 2)}
    if longest / FPS > 1.5:
        fails.append(f"{longest / FPS:.2f} s without a visible change")
    # text gate: OCR every 10th decoded frame
    pick = dfiles[::10]
    try:
        o = ocr(pick, run)
        hits = []
        for p in pick:
            tx = o.get(p.name, "")
            up = tx.upper()
            for b in OCR_BAD:
                if b in up:
                    hits.append({"frame": p.name, "found": b})
            for w in F.PROVIDER_WORDS:
                if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", tx.lower()):
                    hits.append({"frame": p.name, "found": w})
        q["text_gate"] = {"frames": len(pick), "hits": hits, "ocr_sample": {k: o[k][:200] for k in list(o)[:3]}}
        if hits:
            fails.append("text gate hit")
    except Exception as e:  # noqa: BLE001
        q["text_gate"] = {"error": str(e)}
        fails.append("text gate did not run")
    # words
    allw = " ".join(ln["say"] for ln in lines) + " " + " ".join(" ".join(w["t"] for w in c["words"]) for c in caps)
    q["banned_scan"] = {"spoken_and_captions": allw, "hits": []}
    q["punch_hole"] = ph
    q["render"] = {k: rinfo.get(k) for k in ("gpu", "float_blend", "n", "seconds", "sec_per_frame")}
    q["timeline"] = {"tap": T["v_tap"], "open_end": T["v_open_end"], "scroll": T.get("v_scroll"),
                     "scroll_end": T.get("v_scroll_end"), "close": T.get("v_close"), "end": T["end"],
                     "moves": [(m["name"], m["t0"], round(m["t0"] + m["dur"], 3)) for m in T["moves"]]}
    q["fails"] = fails
    q["passed"] = not fails
    return q


def _longest(ch) -> int:
    best = cur = 0
    for c in ch:
        cur = 0 if c else cur + 1
        best = max(best, cur)
    return best


def ocr(paths: list[Path], run: Path) -> dict:
    lst = run / "qa_ocr_list.txt"
    lst.write_text("\n".join(str(p.resolve()) for p in paths), encoding="utf-8")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(OCR_PS1), "-List",
                        str(lst.resolve())], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    if r.returncode != 0:
        raise InputError("OCR failed: " + r.stderr[-800:])
    out = {}
    for ln in r.stdout.splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            o = json.loads(ln, strict=False)
            out[Path(o["path"]).name] = o["text"]
    return out


def proof(run, ep, take, T, accent, mixinfo, rinfo, q):
    tk = ep["take"]
    pr = {
        "built_at": now_z(), "episode": ep["slug"], "feature": ep["feature"],
        "app": tk["app"], "device": tk["device"], "stock_opened": tk["stock"],
        "capture": {"recorded_at_host_ms": take["host_log"][0]["host_ms"] if take["host_log"] else None,
                    "recorder": "agent-device record --scope device --quality high --hide-touches (Android screenrecord)",
                    "unique_frames": take["unique_frames"], "duration_s": take["duration"], "fps_in_motion": take["fps_motion"],
                    "note": "the recorder writes a frame only when the screen changes; still stretches are one frame"},
        "screen_text_read_from_device": {k: v["text"] for k, v in tk["states"].items()},
        "gesture_log": rjson(run / "take" / "gesture_log.json"),
        "timing_of_the_real_frames": {
            "rule": "every screen pixel is a recorded frame; holds repeat the event's settled frame; the in-sheet scroll is "
                    "shown one distinct recorded frame per output frame (chosen for an even speed), never interpolated",
            "srcmap": [{k: (v if k != "frames" else len(v)) for k, v in s.items()} for s in T["srcmap"]],
            "scroll_retime": q.get("scroll_retime")},
        "keepout_scan_of_device_snapshots": q.get("keepout_scan"),
        "touch_disc": q.get("touch_disc"),
        "accent_sampled_from_app": accent,
        "assets": [
            {"name": "Poly Haven HDRI studio_small_09 (2k)", "file": str(CACHE / "hdri-polyhaven" / "studio_small_09_2k.hdr"),
             "url": "https://polyhaven.com/a/studio_small_09", "licence": "CC0", "use": "light and reflections on the phone body only"},
            {"name": "Inter (variable)", "file": str(CACHE / "filed-fonts" / "Inter.ttf"), "licence": "OFL-1.1"},
            {"name": "three.js r170", "file": str(CACHE / "filed-node" / "node_modules" / "three"), "licence": "MIT"},
            {"name": "Kokoro TTS voice am_michael (Kokoro-82M)", "licence": "Apache-2.0"},
            {"name": "sound effects and bed", "licence": "synthesised (numpy: filed/sound.py, showcase.py pop)"},
            {"name": "phone body, ground, overlays", "licence": "our own code (studio/studio.js)"},
            {"name": "RapidTradeView brand mark", "file": "rapidtradeview/shared/data/brand-mark.json", "licence": "our own"},
            {"name": "app recording", "file": str(run / "take" / "raw.mp4"), "licence": "our own product UI"}],
        "mix": mixinfo, "render": {k: rinfo.get(k) for k in ("gpu", "float_blend", "n", "seconds", "sec_per_frame")},
        "qa_passed": q["passed"],
    }
    wjson(run / "proof.json", pr)


if __name__ == "__main__":
    sys.exit(main())
