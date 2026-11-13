"""Build the long-form YouTube walkthrough "How to track Congress stock trades (free)" from today's live captures.

    PY=C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe
    $PY -I tools/gv/scripts/walkthrough/build_walkthrough.py --run <media>/.ops/yt-long/congress-how-to [--capture]

--capture first records the live site (capture_walkthrough.py in .ops/cache/shot-venv; it opens one stock page as a
guest, and guests get 2 stock views a day per address). Without it the captures already in <run>/screens are used; they
must be from the last 12 hours.

Steps:
  1. script_congress.build(<run>/screens): the sentences, every figure read from a capture, with its proof.
  2. Voice: tts.py (local Kokoro, voice "narrator"), one wav per sentence, cached in <run>/tts by text.
  3. Timeline: sentences back to back with their pauses; the picture is cut to the voice: one camera target per sentence,
     an eased move into it at the sentence start, then a slow push (the screen is never still for more than a move).
  4. Edit in FilmCraft 0.20.1 (headless `filmcraft-cli mcp`, fcmcp.py): the real page tiles on V1 with the camera as
     dense motion keyframes, cross dissolves between pages, outlines drawn in place over the value being read (V2), the
     cursor (V3), the top bar with the page's real address (V4/V5), the RapidTradeView pill top-left from frame 0 to the
     end (V6), phrase captions burned in at the bottom (and exported as .srt), the voice on A1, a 4 s+ end card, export
     H.264 + AAC at -14 LUFS.
  5. QA (exit 1 on a failed gate): ffprobe (1920x1080, 30 fps, h264 + aac, 185-240 s), loudness (-15..-13 LUFS), every
     framed window of every frame clear of provider names, loading and error words, outlines and the cursor inside the
     page area and above the caption band, the pill track over the whole length, "RapidTradeView" spoken in the first 5 s
     and the last 8 s; contact sheet (a frame every 5 s), proof.json, chapters, description, voice script with timestamps.

Outputs in <run>: congress-how-to.mp4, congress-how-to.srt, congress-how-to.fcproj, sheet.png, proof.json, qa.json,
timeline.json, chapters.txt, description.txt, voice_script.txt, vo.wav, frames/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "v6cat"))
import script_congress as sc  # noqa: E402
from fcmcp import FilmCraft, t as ticks  # noqa: E402


def media_root() -> Path:
    """The main checkout of the media repo (a worktree under .worktrees/ finds it): where .ops/ lives."""
    for p in HERE.parents:
        if (p / ".ops" / "cache").is_dir():
            return p
    raise SystemExit("no .ops/cache above this script")


MEDIA = media_root()
SHOT_PY = MEDIA / ".ops" / "cache" / "shot-venv" / "Scripts" / "python.exe"
TTS_PY = MEDIA / ".ops" / "cache" / "tts-venv" / "Scripts" / "python.exe"
TTS = HERE.parent / "cartoon" / "tts.py"
NAME = "congress-how-to"
W, H, FPS = 1920, 1080, 30
BAR = 76                      # the top bar (pill + address); the page shows below it
VC = (W / 2, BAR + (H - BAR) / 2)   # the centre of the page area in the frame
CAPTION_TOP = 950             # captions sit below this line; outlines and the cursor stay above it
VOICE = "narrator"
SPEED = 1.1                   # a natural, slightly brisk tutorial pace
LEAD = 0.35                   # s of picture before the first word
MOVE_LEAD = 0.3               # a move starts this long before its sentence
CYAN = "#22d3ee"
SITE_URL = "https://www.rapidtradeview.trade/congress-trades?utm_source=youtube&utm_medium=video&utm_campaign=congress-how-to"
BAD = ("Loading", "Service unavailable", "Something went wrong", "Failed to load", "Try again")
TOP_LIMIT = {"stock_top": 68.0}   # never show the stock page's header row (the guest counter) - the ticker bar is the top


# ---------------------------------------------------------------- small helpers

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def smooth(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * x * (x * (6 * x - 15) + 10)


def snap(s: float) -> float:
    return round(s * FPS) / FPS


def fmt_ts(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


def srt_ts(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


# ---------------------------------------------------------------- voice

def voice(sentences: list[dict], tts_dir: Path) -> None:
    tts_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for s in sentences:
        key = hashlib.sha256(f"{VOICE}|{SPEED}|{s['say']}".encode("utf-8")).hexdigest()[:16]
        s["wav"] = str(tts_dir / f"{key}.wav")
        s["timings"] = str(tts_dir / f"{key}.json")
        if not (Path(s["wav"]).is_file() and Path(s["timings"]).is_file()):
            jobs.append({"text": s["say"], "voice": VOICE, "speed": SPEED, "out": s["wav"], "timings": s["timings"]})
    if jobs:
        bj = tts_dir / "batch.json"
        bj.write_text(json.dumps(jobs, indent=1), encoding="utf-8")
        run([str(TTS_PY), "-I", str(TTS), "--batch", str(bj)])
    for s in sentences:
        with wave.open(s["wav"]) as w:
            s["dur"] = w.getnframes() / w.getframerate()
            s["sr"] = w.getframerate()
        s["words"] = json.loads(Path(s["timings"]).read_text(encoding="utf-8"))


def lay_out(sentences: list[dict]) -> float:
    """Start times (snapped to frames). Returns the end of the voice."""
    t = LEAD
    for s in sentences:
        s["start"] = snap(t)
        s["end"] = s["start"] + s["dur"]
        t = s["end"] + s["pause"]
    return t


def write_vo(sentences: list[dict], total: float, path: Path) -> None:
    sr = sentences[0]["sr"]
    buf = np.zeros(int(math.ceil(total * sr)) + sr, dtype=np.int16)
    for s in sentences:
        with wave.open(s["wav"]) as w:
            a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        i = int(round(s["start"] * sr))
        buf[i:i + len(a)] = a
    buf = buf[:int(round(total * sr))]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(buf.tobytes())


# ---------------------------------------------------------------- captions

def phrases(s: dict, max_chars: int = 46) -> list[dict]:
    """Split a sentence's caption into phrases of at most max_chars at word boundaries (preferring punctuation), timed by
    the engine's word timings: a phrase boundary at a share of the caption's characters starts at the time of the spoken
    word at the same share of the spoken text."""
    words = s["text"].split()
    groups, cur = [], []
    for w in words:
        if cur and len(" ".join(cur + [w])) > max_chars:
            # back up to the last punctuation in the group if it leaves at least 3 words
            cut = max((i for i, x in enumerate(cur) if x[-1] in ",.:;" and i >= 2), default=None)
            if cut is not None and cut < len(cur) - 1:
                groups.append(cur[:cut + 1])
                cur = cur[cut + 1:]
            else:
                groups.append(cur)
                cur = []
        cur.append(w)
        if w[-1] in ".:" and len(" ".join(cur)) >= 18:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    total_chars = len(s["text"])
    say_words = s["words"]
    say_text = " ".join(w["word"] for w in say_words)
    offs, pos = [], 0
    for w in say_words:
        offs.append(pos / max(1, len(say_text)))
        pos += len(w["word"]) + 1
    out, pos = [], 0
    for g in groups:
        txt = " ".join(g)
        share = pos / total_chars
        k = min(range(len(offs)), key=lambda i: abs(offs[i] - share)) if offs else 0
        start = s["start"] + (say_words[k]["start"] if say_words else 0.0)
        out.append({"text": txt, "start": start})
        pos += len(txt) + 1
    out[0]["start"] = s["start"]
    for i, p in enumerate(out):
        p["end"] = out[i + 1]["start"] if i + 1 < len(out) else s["end"] + min(0.3, s["pause"])
    return out


# ---------------------------------------------------------------- the camera

class Shot:
    def __init__(self, cap: str, tile: dict, dpr: int, sentences: list[dict]):
        self.cap, self.tile, self.dpr, self.sentences = cap, tile, dpr, sentences
        self.top = max(tile["top"], TOP_LIMIT.get(cap, -1e9))
        self.bottom = tile["bottom"]
        self.segs: list[tuple] = []

    def clamp(self, cx: float, cy: float, z: float) -> tuple[float, float, float]:
        z = max(z, W / 1920.0, (H - BAR) / (self.bottom - self.top))
        hw, hh = W / 2 / z, (H - BAR) / 2 / z
        cx = min(max(cx, hw), 1920 - hw)
        cy = min(max(cy, self.top + hh), self.bottom - hh)
        return cx, cy, z

    def at(self, t: float) -> tuple[float, float, float]:
        for kind, t0, t1, a, b, dip in self.segs:
            if t <= t1 or (kind, t0, t1, a, b, dip) == self.segs[-1]:
                if t < t0:
                    return self.clamp(*a)
                u = 0.0 if t1 <= t0 else min(1.0, (t - t0) / (t1 - t0))
                if kind == "move":
                    e = smooth(u)
                    z = math.exp(math.log(a[2]) + (math.log(b[2]) - math.log(a[2])) * e) * (1 - dip * math.sin(math.pi * e))
                    return self.clamp(a[0] + (b[0] - a[0]) * e, a[1] + (b[1] - a[1]) * e, z)
                z = math.exp(math.log(a[2]) + (math.log(b[2]) - math.log(a[2])) * u)
                return self.clamp(a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, z)
        raise RuntimeError("no camera segment")

    def frame_pt(self, x: float, y: float, t: float) -> tuple[float, float]:
        cx, cy, z = self.at(t)
        return VC[0] + (x - cx) * z, VC[1] + (y - cy) * z

    def frame_box(self, box: list[float], t: float) -> list[float]:
        x0, y0 = self.frame_pt(box[0], box[1], t)
        x1, y1 = self.frame_pt(box[0] + box[2], box[1] + box[3], t)
        return [x0, y0, x1 - x0, y1 - y0]

    def visible(self, t: float) -> list[float]:
        cx, cy, z = self.at(t)
        return [cx - W / 2 / z, cy - (H - BAR) / 2 / z, W / z, (H - BAR) / z]


def target(view: dict) -> tuple[float, float, float]:
    z = view["zoom"]
    box = view.get("box")
    cx = view.get("cx")
    cy = view.get("cy")
    if box is not None:
        if cx is None:
            cx = box[0] + box[2] / 2
        if cy is None:
            cy = box[1] + box[3] / 2 - (view.get("at", VC[1]) - VC[1]) / z
    return float(cx), float(cy), float(z)


def pick_tile(cap_meta: dict, ys: list[tuple[float, float]]) -> dict | None:
    lo, hi = min(a for a, _ in ys), max(b for _, b in ys)
    for tile in cap_meta["tiles"]:
        if tile["top"] <= max(0.0, lo) and hi <= tile["bottom"]:
            return tile
    return None


def plan_shots(sentences: list[dict], caps: dict, end_card_from: int) -> list[Shot]:
    """Consecutive sentences on the same capture share a shot while one tile holds every window they look at."""
    shots: list[Shot] = []
    run_: list[dict] = []

    def window(s):
        cx, cy, z = target(s["view"])
        hh = (H - BAR) / 2 / z
        return cy - hh - 40, cy + hh + 40

    def flush():
        if not run_:
            return
        cap = run_[0]["view"]["cap"]
        tile = pick_tile(caps[cap], [window(s) for s in run_])
        if tile is None:
            raise SystemExit(f"no tile holds sentences {[s['id'] for s in run_]}")
        shots.append(Shot(cap, tile, caps[cap]["dpr"], list(run_)))
        run_.clear()

    for s in sentences[:end_card_from]:
        cap = s["view"]["cap"]
        if run_ and (run_[0]["view"]["cap"] != cap or
                     pick_tile(caps[cap], [window(x) for x in run_ + [s]]) is None):
            flush()
        run_.append(s)
    flush()
    return shots


def camera(shots: list[Shot], end_card_start: float) -> None:
    for i, sh in enumerate(shots):
        sh.start = 0.0 if i == 0 else sh.sentences[0]["start"] - MOVE_LEAD
        sh.end = shots[i + 1].sentences[0]["start"] - MOVE_LEAD if i + 1 < len(shots) else end_card_start
        segs = []
        prev = None
        for k, s in enumerate(sh.sentences):
            tgt = sh.clamp(*target(s["view"]))
            m0 = sh.start if k == 0 else s["start"] - MOVE_LEAD
            nxt = sh.sentences[k + 1]["start"] - MOVE_LEAD if k + 1 < len(sh.sentences) else sh.end + 0.6
            if k == 0:
                a = sh.clamp(tgt[0], tgt[1] + (0 if i == 0 else -60 / tgt[2]), tgt[2] * (1.0 if i == 0 else 0.9))
                if i == 0:
                    a = tgt
                dur = 1.1 if i else 0.0
            else:
                a = prev
                dist = math.hypot((tgt[0] - a[0]) * tgt[2], (tgt[1] - a[1]) * tgt[2])
                dur = min(1.8, 0.8 + dist / 2500 + abs(math.log(tgt[2] / a[2])) * 0.8)
            dip = 0.0 if k == 0 else min(0.45, max(0.0, (math.hypot((tgt[0] - a[0]) * tgt[2], (tgt[1] - a[1]) * tgt[2]) - 1100) / 3500))
            m1 = m0 + dur
            if m1 > nxt - 0.4:                      # a short sentence: the move takes most of it
                m1 = max(m0 + 0.5, nxt - 0.4)
            if dur > 0:
                segs.append(("move", m0, m1, a, tgt, dip))
            drift_end = (tgt[0], tgt[1], tgt[2] * (1.0 + 0.012 * max(0.0, nxt - m1)))   # a slow push: ~1.2 %/s
            segs.append(("drift", m1, nxt, tgt, drift_end, 0.0))
            s["move_end"] = m1
            s["hold_end"] = nxt
            prev = sh.clamp(*drift_end)
        sh.segs = segs


# ---------------------------------------------------------------- assets FilmCraft cannot make

def assets(adir: Path) -> dict:
    import card_reel as cr
    adir.mkdir(parents=True, exist_ok=True)
    pill = cr.pill(cr.BRAND, 28, 18, 11)
    pill.save(adir / "pill.png")
    big = cr.pill(cr.BRAND, 72, round(72 * 0.65), round(72 * 0.4))
    big.save(adir / "pill_end.png")
    # the cursor: a plain arrow, white with a dark rim (drawn at 4x, reduced)
    k = 4
    pts = [(0, 0), (0, 34), (9, 26), (15, 40), (21, 37), (15, 24), (27, 24)]
    im = Image.new("RGBA", (40 * k, 48 * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(4 * k + x * k, 3 * k + y * k) for x, y in pts], fill=(255, 255, 255, 255), outline=(10, 10, 14, 255),
              width=3 * k)
    cur = im.resize((40, 48), Image.LANCZOS)
    cur.save(adir / "cursor.png")
    return {"pill": adir / "pill.png", "pill_size": pill.size, "pill_end": adir / "pill_end.png",
            "pill_end_size": big.size, "cursor": adir / "cursor.png", "cursor_tip": (4, 3)}


# ---------------------------------------------------------------- the edit

def edit(run_dir: Path, sentences: list[dict], shots: list[Shot], caps: dict, total: float, end_start: float,
         caps_ph: list[dict], A: dict) -> dict:
    screens = run_dir / "screens"
    log = run_dir / "filmcraft_log.jsonl"
    fc = FilmCraft(log=log)
    R = fc.run
    steps: list[dict] = []

    def setp(clip, param, value, sec=None, effect="motion"):
        p = {"clip": clip, "effect": effect, "param": param, "value": value}
        if sec is not None:
            p.update(time=ticks(sec), keyframe=True)
        steps.append({"id": "effects.setParam", "params": p})

    def flush():
        if steps:
            res = fc.tool("command_batch", {"steps": steps})
            if res.get("failed"):
                bad = [r for r in res.get("results", []) if not r.get("ok")][:3]
                raise RuntimeError(f"FilmCraft batch failed: {bad}")
            steps.clear()

    R("file.newSequence", name=NAME, width=W, height=H, fps=FPS, sampleRate=48000, video=6, audio=1)
    tiles = sorted({(sh.cap, sh.tile["file"]) for sh in shots})
    paths = [str(screens / f) for _, f in tiles] + [str(run_dir / "vo.wav"), str(A["pill"]), str(A["pill_end"]),
                                                     str(A["cursor"])]
    ids = R("file.import", paths=paths)
    if ids["errors"]:
        raise RuntimeError(f"import: {ids['errors']}")
    item = dict(zip([f for _, f in tiles], ids["items"][:len(tiles)]))
    vo_id, pill_id, pill_end_id, cursor_id = ids["items"][len(tiles):]

    def sample_times(t0: float, t1: float, every: int = 2) -> list[float]:
        f0, f1 = int(math.floor(t0 * FPS)), int(math.ceil(t1 * FPS))
        return [f / FPS for f in range(f0, f1 + 1, every)] + [f1 / FPS]

    # ---- V1: the page, one clip per shot, the camera as motion keyframes
    clips = []
    for sh in shots:
        c = R("timeline.place", item=item[sh.tile["file"]], track="V1", seconds=sh.start,
              duration={"seconds": sh.end - sh.start}, insert=False, sourceIn={"seconds": 2})["clips"][0]
        clips.append(c)
        setp(c, "anchor", [0, 0])
        for tt in sample_times(sh.start - 0.4, sh.end + 0.4):
            cx, cy, z = sh.at(tt)
            setp(c, "scale", z / sh.dpr * 100, tt)
            setp(c, "position", [VC[0] - z * cx, VC[1] - z * (cy - sh.tile["top"])], tt)
        flush()

    # ---- end card on V1: the brand gradient
    endbg = R("graphics.newRectangle", position=[W / 2, H / 2], size=[W, H], seconds=total - end_start, time=ticks(end_start),
              track=0)["clip"]
    R("graphics.set", clip=endbg, layer=0, props={"fill_kind": 1, "gradient_start": "#0b0820", "gradient_end": "#24104a",
                                                   "gradient_angle": 90})
    for c in clips[:-1]:
        R("sequence.applyVideoTransition", clip=c, effect="cross_dissolve", frames=12, edge="out", align="center")
    R("sequence.applyVideoTransition", clip=clips[-1], effect="cross_dissolve", frames=16, edge="out", align="center")

    # ---- V2: outlines in place; V3: the cursor
    overlays = []
    shot_of = {s["id"]: sh for sh in shots for s in sh.sentences}
    for s in sentences:
        sh = shot_of.get(s["id"])
        if sh is None:
            continue
        if s.get("outline"):
            t0, t1 = s["move_end"], min(s["hold_end"], sh.end)
            if t1 - t0 >= 0.3:
                pad = 0
                fb0 = sh.frame_box(s["outline"], t0)
                z0 = sh.at(t0)[2]
                size = [fb0[2] + 2 * pad, fb0[3] + 2 * pad]
                r = R("graphics.newRectangle", position=[W / 2, H / 2], size=size, seconds=t1 - t0, time=ticks(t0),
                      track=1)["clip"]
                R("graphics.set", clip=r, layer=0, props={"fill": False, "stroke": True, "stroke_color": CYAN,
                                                         "stroke_width": 4, "corner_radius": 10, "shadow": True,
                                                         "shadow_color": CYAN, "shadow_blur": 18, "shadow_distance": 0,
                                                         "shadow_opacity": 70})
                setp(r, "anchor", [W / 2, H / 2])
                samples = []
                for tt in sample_times(t0, t1, 3):
                    fb = sh.frame_box(s["outline"], tt)
                    z = sh.at(tt)[2]
                    pop = 1.0 + 0.12 * (1 - smooth((tt - t0) / 0.22)) if tt - t0 < 0.22 else 1.0
                    setp(r, "position", [fb[0] + fb[2] / 2, fb[1] + fb[3] / 2], tt)
                    setp(r, "scale", z / z0 * 100 * pop, tt)
                    samples.append([round(tt, 3)] + [round(v, 1) for v in fb])
                overlays.append({"sentence": s["id"], "kind": "outline", "box_css": s["outline"], "t0": t0, "t1": t1,
                                 "frame_boxes": samples})
                flush()
        if s.get("cursor"):
            cb = s["cursor"]["box"]
            t0 = s["move_end"]
            t1 = min(s["hold_end"], sh.end) + (0.25 if s["cursor"]["click"] else 0)
            c = R("timeline.place", item=cursor_id, track="V3", seconds=t0, duration={"seconds": t1 - t0}, insert=False,
                  sourceIn={"seconds": 2})["clips"][0]
            setp(c, "anchor", list(A["cursor_tip"]))
            tip = (cb[0] + min(cb[2] * 0.35, 60), cb[1] + cb[3] * 0.6)
            arrive = t0 + 0.75 * (s["end"] - t0)
            click_at = s["end"] - 0.1
            samples = []
            for tt in sample_times(t0, t1, 2):
                px, py = sh.frame_pt(*tip, tt)
                u = smooth((tt - t0) / max(0.2, arrive - t0))
                fx, fy = px + 240 * (1 - u), py + 150 * (1 - u)
                sc_ = 100.0
                if s["cursor"]["click"] and click_at <= tt <= click_at + 0.24:
                    sc_ = 100 - 22 * math.sin(math.pi * (tt - click_at) / 0.24)
                setp(c, "position", [fx, fy], tt)
                setp(c, "scale", sc_, tt)
                samples.append([round(tt, 3), round(fx, 1), round(fy, 1)])
            overlays.append({"sentence": s["id"], "kind": "cursor", "box_css": cb, "t0": t0, "t1": t1, "click": s["cursor"]["click"],
                             "tip_frames": samples})
            flush()

    # ---- V4: the top bar; V5: the page's address per shot; V6: the pill, frame 0 to the last frame
    bar = R("graphics.newRectangle", position=[W / 2, BAR / 2], size=[W, BAR], seconds=total, time=0, track=3)["clip"]
    R("graphics.set", clip=bar, layer=0, props={"fill": True, "fill_color": "#0c0c11", "stroke": False})
    line = R("graphics.newRectangle", position=[W / 2, BAR - 1], size=[W, 2], clip=bar)
    R("graphics.set", clip=bar, layer=line.get("layer", 1), props={"fill": True, "fill_color": "#2a2a36", "stroke": False})
    for sh in shots:
        url = caps[sh.cap]["url"].replace("https://", "")
        tx = R("graphics.newText", text=url, position=[W / 2, 47], size=24, font="Segoe UI", seconds=sh.end - sh.start,
               time=ticks(sh.start), track=4)["clip"]
        R("graphics.set", clip=tx, layer=0, props={"align": "center", "fill_color": "#d4d4d8", "background": True,
                                                  "background_color": "#1d1d26", "background_opacity": 100,
                                                  "background_radius": 18, "background_size": 12})
    pw, ph = A["pill_size"]
    pc = R("timeline.place", item=pill_id, track="V6", seconds=0, duration={"seconds": total}, insert=False,
           sourceIn={"seconds": 2})["clips"][0]
    setp(pc, "position", [22 + pw / 2, BAR / 2])
    flush()

    # ---- end card: the large pill, the search line, the address, the disclaimer (V2, V3, V5)
    ew, eh = A["pill_end_size"]
    ep = R("timeline.place", item=pill_end_id, track="V2", seconds=end_start, duration={"seconds": total - end_start},
           insert=False, sourceIn={"seconds": 2})["clips"][0]
    setp(ep, "position", [W / 2, 400])
    for tt, v in ((end_start, 60), (end_start + 0.25, 106), (end_start + 0.4, 100), (total, 104)):
        setp(ep, "scale", v, tt)
    flush()
    srch = R("graphics.newText", text="Search RapidTradeView", position=[W / 2, 610], size=64, font="Segoe UI",
             fontStyle="Bold", seconds=total - end_start, time=ticks(end_start), track=2)["clip"]
    R("graphics.set", clip=srch, layer=0, props={"align": "center", "fill_color": "#0b0820", "background": True,
                                                  "background_color": "#ffffff", "background_opacity": 100,
                                                  "background_radius": 48, "background_size": 26})
    site = R("graphics.newText", text="www.rapidtradeview.trade/congress-trades", position=[W / 2, 745], size=40,
             font="Segoe UI", seconds=total - end_start, time=ticks(end_start), track=4)["clip"]
    R("graphics.set", clip=site, layer=0, props={"align": "center", "fill_color": "#c4b5fd"})
    nia = R("graphics.newText", text="Not investment advice.", position=[W / 2, 830], size=36, font="Segoe UI", clip=site)
    R("graphics.set", clip=site, layer=nia["layer"], props={"align": "center", "fill_color": "#9ca3af"})

    # ---- A1: the voice
    R("timeline.place", item=vo_id, track="A1", seconds=0, insert=False)

    # ---- captions: phrases, burned in at the bottom (frame-snapped, never overlapping)
    R("captions.newTrack", format="Subtitle", name="burned", language="en")
    R("captions.setStyle", track="C1", font="Segoe UI", fontStyle="Bold", size=40, color="#ffffff", background=True,
      backgroundColor="#000000c8", align="center", anchor="bottom", margin=0.035, outline=0)
    last_f = 0
    for p in caps_ph:
        f0 = max(last_f, round(p["start"] * FPS))
        f1 = round(p["end"] * FPS)
        if f1 - f0 < 6:
            f1 = f0 + 6
        R("captions.add", track="C1", text=p["text"], seconds=f0 / FPS, durationSeconds=(f1 - f0) / FPS)
        p["f0"], p["f1"] = f0, f1
        last_f = f1

    proj = run_dir / f"{NAME}.fcproj"
    R("file.saveAs", path=str(proj))
    seqi = R("sequence.inspect")
    srt = run_dir / f"{NAME}.srt"
    R("captions.export", path=str(srt), format="srt", track="C1")
    mp4 = run_dir / f"{NAME}.mp4"
    t_exp = time.time()
    res = R("file.exportMedia", path=str(mp4), format="h264", range="entire", loudnessLufs=-14, burnCaptions=True,
            crf=18, bitrateMode="crf", h264Profile="high", wait=True)
    fc.close()
    return {"overlays": overlays, "export": res, "export_s": round(time.time() - t_exp, 1),
            "sequence_frames": seqi.get("durationFrames"), "project": str(proj), "srt": str(srt), "mp4": str(mp4)}


# ---------------------------------------------------------------- QA

def probe(mp4: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,"
               "channels:format=duration", "-of", "json", str(mp4)]).stdout
    return json.loads(out)


def loudness(mp4: Path) -> dict:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4), "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    summ = err[err.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", summ)
    tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ)
    lra = re.search(r"LRA:\s+(-?[\d.]+) LU", summ)
    return {"integrated_lufs": float(i.group(1)) if i else None, "true_peak_dbfs": float(tp.group(1)) if tp else None,
            "lra_lu": float(lra.group(1)) if lra else None}


def frame_at(mp4: Path, t: float, out: Path) -> Path:
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1", str(out)])
    return out


def contact_sheet(mp4: Path, dur: float, fdir: Path, sheet: Path, every: float = 5.0, cols: int = 4, tw: int = 640) -> list[str]:
    fdir.mkdir(exist_ok=True)
    times = [round(x * every, 2) for x in range(int(dur // every) + 1)]
    th = tw * 9 // 16
    rows = math.ceil(len(times) / cols)
    sh = Image.new("RGB", (cols * tw, rows * (th + 28)), (20, 20, 24))
    d = ImageDraw.Draw(sh)
    files = []
    for i, tt in enumerate(times):
        f = frame_at(mp4, min(tt, dur - 0.05), fdir / f"t{int(tt):04d}.png")
        files.append(str(f))
        im = Image.open(f).convert("RGB").resize((tw, th), Image.LANCZOS)
        x, y = (i % cols) * tw, (i // cols) * (th + 28)
        sh.paste(im, (x, y + 28))
        d.text((x + 8, y + 6), fmt_ts(tt), fill=(230, 230, 230))
    sh.save(sheet)
    return files


def qa(run_dir: Path, sentences, shots, caps_full, caps_ph, ed, total, end_start) -> dict:
    mp4 = Path(ed["mp4"])
    gates, details = {}, {}
    pr = probe(mp4)
    v = [s for s in pr["streams"] if s["codec_type"] == "video"][0]
    a = [s for s in pr["streams"] if s["codec_type"] == "audio"]
    dur = float(pr["format"]["duration"])
    details["probe"] = pr
    gates["format"] = (v["codec_name"] == "h264" and v["width"] == W and v["height"] == H and v["r_frame_rate"] == "30/1"
                       and bool(a) and a[0]["codec_name"] == "aac")
    gates["duration_185_240"] = 185.0 <= dur <= 240.0
    ld = loudness(mp4)
    details["loudness"] = ld
    gates["loudness"] = ld["integrated_lufs"] is not None and -15.0 <= ld["integrated_lufs"] <= -13.0
    # every framed window: no provider name, no loading or error word on any line that shows
    hits = []
    for sh in shots:
        lines = caps_full[sh.cap].d["lines"]
        for f in range(int(sh.start * FPS), int(sh.end * FPS), 3):
            vx, vy, vw, vh = sh.visible(f / FPS)
            for ln in lines:
                if ln["x"] + ln["w"] > vx and ln["x"] < vx + vw and ln["y"] + ln["h"] > vy and ln["y"] < vy + vh:
                    low = ln["t"].lower()
                    if any(p in low for p in sc_providers()) or any(b in ln["t"] for b in BAD):
                        hits.append({"t": f / FPS, "cap": sh.cap, "line": ln["t"]})
    details["provider_or_error_lines"] = hits[:20]
    gates["no_provider_or_error_on_screen"] = not hits
    # outlines and the cursor: inside the page area, above the caption band, inside the frame
    bad_ov = []
    for ov in ed["overlays"]:
        if ov["kind"] == "outline":
            for tt, x, y, w_, h_ in ov["frame_boxes"]:
                if x < 4 or y < BAR + 4 or x + w_ > W - 4 or y + h_ > CAPTION_TOP:
                    bad_ov.append({"sentence": ov["sentence"], "t": tt, "box": [x, y, w_, h_]})
                    break
        else:
            for tt, x, y in ov["tip_frames"]:
                if x < 4 or y < BAR + 4 or x + 40 > W or y + 48 > CAPTION_TOP:
                    bad_ov.append({"sentence": ov["sentence"], "t": tt, "tip": [x, y]})
                    break
    details["overlays_out_of_place"] = bad_ov
    gates["overlays_clear_of_captions"] = not bad_ov
    # brand spoken early and late
    b_first = next((s["start"] + w["start"] for s in sentences for w in s["words"] if "RapidTradeView" in w["word"]), None)
    b_last = max((s["start"] + w["start"] for s in sentences for w in s["words"] if "RapidTradeView" in w["word"]), default=None)
    details["brand_spoken_at"] = [b_first, b_last]
    gates["brand_spoken_first_5s_and_last_8s"] = b_first is not None and b_first <= 5.0 and b_last >= total - 8.0
    gates["end_card_4s"] = total - end_start >= 4.0
    gates["disclaimer_spoken_last"] = sentences[-1]["text"].endswith("Not investment advice.")
    gates["captions_single_line"] = all(len(p["text"]) <= 48 for p in caps_ph)
    # the captures are fresh
    now = dt.datetime.now(dt.timezone.utc)
    ages = {k: (now - dt.datetime.strptime(c.d["captured_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)).total_seconds() / 3600
            for k, c in caps_full.items()}
    details["capture_age_h"] = {k: round(v, 2) for k, v in ages.items()}
    gates["captures_under_12h"] = all(v <= 12 for v in ages.values())
    # banned words (owner: neutral wording)
    banned = ("insider trading", "suspicious", "how is this legal", "corrupt", "caught", "democrat", "republican",
              "should buy", "should sell", "buy now")
    said = " ".join(s["text"] + " " + s["say"] for s in sentences).lower()
    details["banned_words_found"] = [b for b in banned if b in said]
    gates["neutral_wording"] = not details["banned_words_found"]
    gates["no_provider_names_in_words"] = not any(p in said for p in sc_providers())
    return {"pass": all(gates.values()), "gates": gates, "details": details, "duration_s": dur}


def sc_providers() -> tuple[str, ...]:
    return ("reddit", "vader", "elbstream", "yahoo", "finnhub", "stocktwits", "apewisdom", "google news", "quiver",
            "capitol trades", "unusual whales", "benzinga", "polygon", "alpha vantage", "marketbeat", "openinsider")


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default=str(MEDIA / ".ops" / "yt-long" / NAME))
    ap.add_argument("--capture", action="store_true", help="record the live site first (uses a guest stock view)")
    ap.add_argument("--member", default="Nancy Pelosi")
    ap.add_argument("--member-path", default="/smart-money/figures/nancy-pelosi")
    ap.add_argument("--ticker", default="NVDA")
    ap.add_argument("--no-export", action="store_true", help="stop after the plan (timeline.json) without FilmCraft")
    a = ap.parse_args(argv)
    run_dir = Path(a.run)
    screens = run_dir / "screens"
    if a.capture:
        r = subprocess.run([str(SHOT_PY), "-I", str(HERE / "capture_walkthrough.py"), "--out", str(screens),
                            "--member", a.member_path, "--ticker", a.ticker])
        if r.returncode:
            print("capture failed: no video", file=sys.stderr)
            return 2
    try:
        plan = sc.build(screens, a.member, a.ticker)
    except sc.ScriptError as e:
        print(f"script: {e}", file=sys.stderr)
        return 2
    S = plan["sentences"]
    caps_full = {p.stem: sc.Cap(p) for p in screens.glob("*.json")}
    voice(S, run_dir / "tts")
    voice_end = lay_out(S)
    end_idx = next(i for i, s in enumerate(S) if s["view"].get("cap") == "endcard")
    end_start = S[end_idx]["start"] - MOVE_LEAD
    total = snap(max(voice_end, end_start + 4.2) + 0.2)
    write_vo(S, total, run_dir / "vo.wav")
    shots = plan_shots(S, plan["captures"], end_idx)
    camera(shots, end_start)
    caps_ph = [p for s in S for p in phrases(s)]
    timeline = {"total_s": total, "end_card_start": end_start,
                "sentences": [{k: s[k] for k in ("id", "section", "text", "say", "start", "end", "dur", "pause", "facts",
                                                 "outline", "cursor") if k in s} for s in S],
                "shots": [{"cap": sh.cap, "tile": sh.tile["file"], "start": sh.start, "end": sh.end,
                           "sentences": [s["id"] for s in sh.sentences]} for sh in shots],
                "captions": caps_ph}
    (run_dir / "timeline.json").write_text(json.dumps(timeline, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"voice {voice_end:.1f} s, total {total:.1f} s, {len(shots)} shots, {len(caps_ph)} caption phrases", flush=True)
    if a.no_export:
        return 0
    A = assets(run_dir / "assets")
    ed = edit(run_dir, S, shots, plan["captures"], total, end_start, caps_ph, A)
    print(f"export {ed['export_s']} s", flush=True)
    q = qa(run_dir, S, shots, caps_full, caps_ph, ed, total, end_start)
    files = contact_sheet(Path(ed["mp4"]), q["duration_s"], run_dir / "frames", run_dir / "sheet.png")

    # chapters, description, voice script, proof
    chapters, seen = [], set()
    for s in S:
        if s["section"] not in seen:
            seen.add(s["section"])
            title = dict(plan["sections"])[s["section"]]
            chapters.append((0.0 if not chapters else s["start"] - MOVE_LEAD, title))
    ch_txt = "\n".join(f"{fmt_ts(t_)} {title}" for t_, title in chapters)
    (run_dir / "chapters.txt").write_text(ch_txt + "\n", encoding="utf-8")
    vs = "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in S)
    (run_dir / "voice_script.txt").write_text(vs + "\n", encoding="utf-8")
    facts = {f["id"]: f for f in plan["facts"]}
    desc = (f"Members of Congress publicly report their stock trades, and RapidTradeView lists them free on one page: "
            f"{facts['trades_90d']['value']} trades by {facts['members_90d']['value']} members in the last "
            f"{facts['window_days']['value']} days (as of the recording).\n"
            f"Free Congress trades tracker: {SITE_URL}\n\n"
            f"In this walkthrough: how to read a disclosed trade (who, ticker, buy or sell, amount range, trade date, filing "
            f"date), the most active members and most bought stocks, one member's full list of trades, a stock's Smart Money "
            f"section, and how to get a push for large trades in stocks you hold with the free Android app.\n\n"
            f"Chapters\n{ch_txt}\n\n"
            f"Figures are from the live site on {S and plan['captures']['congress']['captured_at'][:10]}; the page updates "
            f"as new filings arrive. Members report amounts as ranges and can file up to 45 days after a trade.\n\n"
            f"Not investment advice.")
    (run_dir / "description.txt").write_text(desc + "\n", encoding="utf-8")
    shot_of = {s["id"]: sh for sh in shots for s in sh.sentences}
    proof = {"video": ed["mp4"], "made_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "captures": plan["captures"], "facts": plan["facts"],
             "claims": [{"sentence": s["id"], "at": fmt_ts(s["start"]), "start_s": round(s["start"], 2), "text": s["text"],
                         "say": s["say"], "facts": [facts[f] for f in s["facts"]],
                         "on_screen": ({"capture": shot_of[s["id"]].cap, "tile": shot_of[s["id"]].tile["file"],
                                        "outline_css": s.get("outline"),
                                        "visible_css_at_start": [round(v, 1) for v in shot_of[s["id"]].visible(s.get("move_end", s["start"]))]}
                                       if s["id"] in shot_of else {"end_card": True})} for s in S],
             "overlays": ed["overlays"]}
    (run_dir / "proof.json").write_text(json.dumps(proof, indent=1, ensure_ascii=False), encoding="utf-8")
    q["files"] = {"mp4": ed["mp4"], "srt": ed["srt"], "project": ed["project"], "sheet": str(run_dir / "sheet.png"),
                  "proof": str(run_dir / "proof.json"), "frames": files[:3] + ["..."]}
    q["export"] = {"seconds": ed["export_s"], "result": ed["export"]}
    (run_dir / "qa.json").write_text(json.dumps(q, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"pass": q["pass"], "gates": q["gates"], "duration_s": q["duration_s"],
                      "loudness": q["details"]["loudness"]}, indent=1))
    return 0 if q["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
