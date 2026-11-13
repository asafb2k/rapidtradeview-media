"""SHOWCASE by RapidTradeView: one app feature a day, its real screen filmed in a generic 3D phone (Short, 1080x1920).

    PY=C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe
    $PY tools/gv/scripts/showcase/showcase.py tools/gv/scripts/showcase/episodes/<slug>.json            # takes + build
    $PY tools/gv/scripts/showcase/showcase.py <episode.json> --reuse-takes                              # rebuild
    $PY tools/gv/scripts/showcase/showcase.py <episode.json> --reuse-takes --check-only                 # check6 only

Tomorrow's feature = a new episodes/<slug>.json (voice lines, take actions on the video clock, framing) + this command.
Output: <media>/.ops/app-showcase/<slug>/: final.mp4, frame0.png, check6.png, sheet.png, phone.png, take/ (the chosen
recording, its frame log and DOM rects), takes/ (all takes), proof.json, episode.json (resolved spec), voice_script.json
and .txt (word timings), qa.json, render.json, youtube.json.

Rules this template enforces: the screen texture is the recorded frames only (no mock, nothing redrawn, unlit, no tone
mapping or grade); slow motion only where the take has real frames for it, never interpolated; keep-out rects (verdict
chips, score card, guest badge, the pattern card's key level and record block, provider credits) are projected through
the camera on every frame and the build fails if any is in frame; the hero (the app's banner, its control, its words
and the chart with its price axis) stays whole inside x 60-920 and the phone body whole in frame (probed before any
pixel is rendered, gated again in QA); captions live on the plinth, never on the screen. Setup taps (marked "setup" in
the take) are real taps made before the part the cut uses (day 1: Hide, then the app's SMA checkbox off, so the hidden
state is the chart without moving averages).
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
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "filed"))
import filed as F  # noqa: E402  (voice, TTS, loudness, master, probe, frame decode: the FILED engine)
import sound as S  # noqa: E402

MEDIA, CACHE, FFMPEG, FFPROBE = F.MEDIA, F.CACHE, F.FFMPEG, F.FFPROBE
SHOT_PY, CONDA_PY = F.SHOT_PY, F.CONDA_PY
W, H, FPS = 1080, 1920, 30
SAFE = (60, 200, 920, 1500)
SRC_W, SRC_H, DPR = 1170, 2532, 3
DRAW_MS = 1100                     # the app's draw-on (shared/lib/chartPattern.ts PATTERN_TIMELINE): dim 0-150 ms,
LABEL_MS = 950                     # lines 150-750, fill 750-950, label pop 950-1100
LINES_MS = (150, 750)
KIT2 = CACHE / "showcase-kit"
OCR_PS1 = HERE / "ocr.ps1"
BANNED = ("breakout", "buy", "sell", "profit", "returns", "guarantee", "guaranteed", "will rise", "go up", "moon",
          "beat the market", "introducing", "new", "update", "now live", "you should", "insider trading", "sure thing",
          "signal")
OCR_BAD = ("HOLD", "BULLISH", "BEARISH", "0/2", "1/2", "2/2", "OUR RECORD", "KEY LEVEL", "/100")
PARTY_RX = re.compile(r"\b(Democrat|Republican)\b|\([DRI]-[A-Z]{2}\)")
PRICE_RX = re.compile(r"\$\s?\d|\b\d+\.\d\d\b")


class InputError(F.InputError):
    pass


wjson, rjson, sha256, now_z = F.wjson, F.rjson, F.sha256, F.now_z


# ================================================================================================ sound (numpy)
def _t(d):
    return np.arange(int(round(d * S.SR))) / S.SR


def pop(seed=21):
    t = _t(0.1)
    f = 380 + 1100 * np.exp(-t * 32)
    body = np.sin(2 * np.pi * np.cumsum(f) / S.SR) * np.exp(-t * 40)
    click = S._hp(np.random.default_rng(seed).standard_normal(len(t)), 2500) * np.exp(-t * 420) * 0.35
    return S._norm(body + click, 0.8)


def pencil(dur, seed=22):
    """Graphite on paper: band-limited noise with a slow grain, rising a little as the line grows."""
    t = _t(dur)
    r = np.random.default_rng(seed)
    n = S._bp(r.standard_normal(len(t)), 1800, 7500)
    grain = 0.55 + 0.45 * np.abs(S._lp(r.standard_normal(len(t)), 35)) / 0.08
    grain = np.clip(grain, 0.2, 1.6)
    env = np.clip(t / 0.025, 0, 1) * np.clip((dur - t) / 0.08, 0, 1) * (0.75 + 0.25 * t / dur)
    return S._norm(n * grain * env, 0.55)


def glass_snap(seed=23):
    """The one impact: a soft glass snap (inharmonic partials, fast decay), a click and a small low thump."""
    t = _t(0.7)
    r = np.random.default_rng(seed)
    ring = sum(a * np.sin(2 * np.pi * f * t + p) * np.exp(-t * d) for f, d, a, p in
               ((2310, 20, 1.0, 0.0), (3720, 28, 0.6, 1.1), (5180, 36, 0.42, 2.3), (6930, 48, 0.25, 0.7)))
    click = S._bp(r.standard_normal(len(t)), 3000, 8000) * np.exp(-t * 260) * 1.1
    thump = np.sin(2 * np.pi * 92 * t) * np.exp(-t * 22) * 0.55
    return S._norm(np.tanh(1.3 * (0.5 * ring + click + thump)), 0.9)


PENCIL_MID_S = 1.1                 # the Show draw-on's line phase at 0.5x is 1.2 s; the fill phase stays quiet, so
KIT2_FX = {"pop": pop, "pencil_hook": lambda: pencil(1.05),          # >= 0.3 s of silence precede the impact
           "pencil_mid": lambda: pencil(PENCIL_MID_S, 24), "pencil_short": lambda: pencil(0.5, 25),
           "glass_snap": glass_snap}
KIT2_VERSION = "showcase-kit/4"


def make_kit() -> dict:
    import soundfile as sf
    kit = S.make_kit(F.KIT_DIR)
    KIT2.mkdir(parents=True, exist_ok=True)
    meta = KIT2 / "kit.json"
    out = {k: KIT2 / f"{k}.wav" for k in KIT2_FX}
    if not (meta.is_file() and rjson(meta).get("version") == KIT2_VERSION and all(p.is_file() for p in out.values())):
        for k, fn in KIT2_FX.items():
            sf.write(out[k], fn(), S.SR, subtype="PCM_24")
        wjson(meta, {"version": KIT2_VERSION, "files": sorted(out), "licence": "synthesised in numpy (showcase.py)"})
    return {**kit, **out}


# ================================================================================================ helpers
def run_py(py: Path, args: list[str], what: str, timeout=900) -> str:
    r = subprocess.run([str(py)] + args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    if r.returncode != 0:
        raise InputError(f"{what} failed ({r.returncode}): {(r.stderr or '')[-1500:]} {(r.stdout or '')[-800:]}")
    return r.stdout


def expr(s, env: dict) -> float:
    s = str(s)
    for k, v in env.items():
        s = s.replace("{" + k + "}", repr(float(v)))
    if re.search(r"[^0-9.+\-*/() e]", s):
        raise InputError(f"bad take expression {s!r}")
    return float(eval(s, {"__builtins__": {}}, {}))  # noqa: S307 (digits and + - * / only, checked above)


def text_problems(texts: list[str], extra_bad: tuple = ()) -> list[str]:
    bad = []
    for x in texts:
        low = x.lower()
        for w in BANNED + tuple(e.lower() for e in extra_bad):
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                bad.append(f"banned {w!r} in {x!r}")
        for w in F.PROVIDER_WORDS:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                bad.append(f"provider {w!r} in {x!r}")
        if PARTY_RX.search(x):
            bad.append(f"party label in {x!r}")
        if PRICE_RX.search(x):
            bad.append(f"price-like figure in {x!r}")
    return bad


# ================================================================================================ voice + timeline
def voice(ep: dict, run: Path, impact_guess) -> tuple[list[dict], list[dict], float]:
    lines, _ = F.build_script(ep, {})
    for ln, src in zip(lines, ep["lines"]):
        ln["after"] = src.get("after")
    vs = ep["voice"]
    speed = vs["speed"]
    for _ in range(4):
        lines = F.tts(lines, run, vs["voice"], speed)
        clips, _end = F.place_voice(lines)
        n = sum(len(ln["say"].split()) for ln in lines)
        rate = n / sum(ln["t1"] - ln["t0"] for ln in lines)
        lo, hi = vs["target_wps"]
        if lo <= rate <= hi:
            break
        speed = round(speed * ((lo + hi) / 2) / rate, 3)
    return lines, clips, speed


def shift_line(lines, clips, k, delta):
    for j in range(k, len(lines)):
        ln = lines[j]
        for c in ln["chunks"]:
            for w in c["words"]:
                w["t0"] = round(w["t0"] + delta, 3)
                w["t1"] = round(w["t1"] + delta, 3)
            c["t0"], c["t1"] = c["words"][0]["t0"], c["words"][-1]["t1"]
        ln["t0"], ln["t1"] = ln["chunks"][0]["t0"], ln["chunks"][-1]["t1"]
        clips[j]["at"] = round(clips[j]["at"] + delta, 4)


SRC_FRAME_S = 1 / 53.6              # one source frame during a draw-on (measured: 53.6 unique fps on every take)


def timeline(ep, lines, clips, lat_show: float, lat_end: float | None = None) -> dict:
    """Every beat time comes from the voice's word timings (and the take's measured tap-to-draw latency).

    Real taps in the cut (episode timing.tap_words): Hide on "Hide", Show on "tap" (its draw-on plays at 0.5x from
    real frames; its label pop is the one impact), Hide on "straight", Show placed so the app's label pops on
    "prediction" (that redraw plays at real speed), then the last Hide and a last Show whose draw-on (0.5x) runs to
    one source frame before frame 0's draw-on point, so the loop seam is the line continuing to grow."""
    L = {ln["id"]: ln for ln in lines}
    anc = {c["anchor"]: c for ln in lines for c in ln["chunks"] if c["anchor"]}
    tm = ep["timing"]
    slow = tm["slow"]
    lead = tm["hook_app_ms"] / 1000
    draw = DRAW_MS / 1000
    lat_end = lat_show if lat_end is None else lat_end
    T = {"slow": slow, "hook_lead": lead, "lat_show": round(lat_show, 4), "lat_end": round(lat_end, 4)}
    word = lambda key: anc[tm["tap_words"][key][0]]["words"][tm["tap_words"][key][1]]["t0"]  # noqa: E731
    T["hook_out"] = round((draw - lead) / slow, 4)                      # the hook draw-on ends (output time)
    T["hook_label"] = round((LABEL_MS / 1000 - lead) / slow, 3)         # its label pops: the hook's light event
    T["t_hide"] = word("t_hide")
    T["t_show"] = word("t_show")
    T["show_slow_end"] = round(T["t_show"] + (lat_show + draw) / slow, 4)          # Show's 0.5x draw-on ends
    T["show_lines_end"] = round(T["t_show"] + (lat_show + LINES_MS[1] / 1000) / slow, 4)
    T["impact"] = round(T["t_show"] + (lat_show + LABEL_MS / 1000) / slow, 3)
    T["show_line_end"] = L["show"]["t1"]
    sil = ep.get("pre_impact_silence_s", 0.3)
    if T["impact"] - T["show_line_end"] < sil - 1e-3:
        raise InputError(f"the Show line ends {T['impact'] - T['show_line_end']:.2f} s before the impact "
                         f"(< {sil} s of silence): shorten it")
    for k, ln in enumerate(lines):                                       # a line marked after=impact waits for it
        if ln.get("after") == "impact":
            need = T["impact"] + ln["gap_before"]
            if ln["t0"] < need:
                shift_line(lines, clips, k, round(need - ln["t0"], 3))
    T["t_hide_b"] = word("t_hide_b")
    lo, hi = tm["hidden_b_s"]                                           # the hidden state stays a short flash
    T["t_show_b"] = round(min(max(word("t_show_b"), T["t_hide_b"] + lo), T["t_hide_b"] + hi), 3)
    T["label_b"] = round(T["t_show_b"] + lat_show + LABEL_MS / 1000, 3)
    T["draw_b_end"] = round(T["t_show_b"] + lat_show + draw, 3)
    T["shape"] = round(T["t_show_b"] + 0.1, 3)                          # the push-in on the app's own words
    T["brand2"] = anc["brand2"]["t0"]
    T["free"] = round(T["brand2"] - 0.5, 3)
    T["disclaim"] = anc["nia"]["t0"]
    T["caption_stop"] = round(T["brand2"] - 0.02, 3)                   # the URL takes the dock on the brand word
    T["url0"] = T["brand2"]
    T["brand_big"] = round(T["brand2"], 3)
    T["speech_end"] = L["nia"]["t1"]
    T["end"] = round(round((T["speech_end"] + ep.get("tail_s", 0.3)) * FPS) / FPS, 4)
    # the last frame (end - 1/FPS) shows the last Show's draw-on at app time lead - one source frame
    T["t_show_end"] = round(T["end"] - 1 / FPS - (lat_end + lead - SRC_FRAME_S) / slow, 4)
    T["t_hide_end"] = round(T["t_show_end"] - tm["hidden_end_s"], 4)
    T["loop0"] = round(T["end"] - 0.5, 3)
    T["loop1"] = round(T["end"] - 0.04, 3)
    T["head_out1"] = round(T["hook_out"] + 0.1, 3)                    # the headline leaves as the camera starts
    T["head_out0"] = round(T["hook_out"] - 0.15, 3)                   # its push toward the banner
    T["src_hide_after_show1"] = round(lat_show + draw + T["t_hide"] - T["hook_out"], 4)
    T["src_hide_b_after_show"] = round(lat_show + draw + T["t_hide_b"] - T["show_slow_end"], 4)
    for a_, b_, gap in (("t_hide", "t_show", 0.5), ("show_slow_end", "t_hide_b", 0.25), ("t_hide_b", "t_show_b", 0.5),
                        ("draw_b_end", "t_hide_end", 0.3), ("t_hide_end", "t_show_end", 0.5)):
        if T[b_] - T[a_] < gap:
            raise InputError(f"{b_} ({T[b_]}) comes {T[b_] - T[a_]:.2f} s after {a_} ({T[a_]}): needs {gap} s")
    return T


def captions(lines, T) -> list[dict]:
    caps = []
    for ln in lines:
        for c in ln["chunks"]:
            if not c["cap"]:
                continue
            parts = [{"text": w.rstrip(",.:;"), "color": c["accent"].get(w.strip(",.:;"), "white")}
                     for w in c["show"].split(" ")]
            caps.append({"t0": c["t0"], "t1": c["t1"], "parts": parts})
    for i, c in enumerate(caps):
        nxt = caps[i + 1]["t0"] if i + 1 < len(caps) else c["t1"] + 0.35
        c["t1"] = round(min(nxt, c["t1"] + 0.35, T["caption_stop"]), 3)
    caps[0]["t0"] = 0.0
    return caps


# ================================================================================================ takes
def take_plan(ep: dict, T: dict) -> dict:
    acts = []
    for a in ep["take"]["actions"]:
        a = dict(a)
        if a["do"] == "wait_until":
            a["s"] = round(expr(a["s"], T), 4)
        acts.append(a)
    return {**ep, "take": {**ep["take"], "actions": acts}}


def record_takes(ep, T, run: Path, n: int) -> list[Path]:
    tdir = run / "takes"
    tdir.mkdir(parents=True, exist_ok=True)
    plan = take_plan(ep, T)
    wjson(tdir / "plan.json", plan)
    resolved = tdir / "resolve.json"
    if not resolved.is_file():
        run_py(SHOT_PY, [str(HERE / "take.py"), "--episode", str(tdir / "plan.json"), "--out", str(tdir),
                         "--resolve-only"], "resolve")
    out = []
    for k in range(1, n + 1):
        d = tdir / f"take{k}"
        if d.exists():
            shutil.rmtree(d)
        run_py(SHOT_PY, [str(HERE / "take.py"), "--episode", str(tdir / "plan.json"), "--out", str(d),
                         "--resolved", str(resolved)], f"take {k}")
        out.append(d)
    return out


def small(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("L").reduce(3), dtype=np.float32)      # 390x844


def analyze_take(d: Path, ep: dict) -> dict:
    tk = rjson(d / "take.json")
    t0 = tk["t0_wall"]
    fr = tk["frames"]
    ts = np.array([f[1] - t0 for f in fr])
    imgs = [small(d / "frames" / f"{f[0]:05d}.png") for f in fr]
    steps = {s["label"]: s for s in tk["steps"]}
    drawn = steps["drawn"]["named"]
    cx, cy, cw, ch = drawn["chart"]["rect"]                               # css px = small-image px
    win = (slice(int(cy), int(cy + ch)), slice(int(cx), int(cx + cw)))
    dchart = np.array([0.0] + [float(np.abs(imgs[i][win] - imgs[i - 1][win]).max()) for i in range(1, len(imgs))])
    dfull = np.array([0.0] + [float(np.abs(imgs[i] - imgs[i - 1]).mean()) for i in range(1, len(imgs))])
    marks = {}
    for l in tk["log"]:
        if l["what"] == "jumped":
            marks["jumped"] = l["wall"] - t0
    for tp in tk["taps"]:
        marks[tp["name"]] = tp["wall0"] - t0
    late = [l["what"] for l in tk["log"] if l["what"].startswith("LATE")]
    cand = [i for i in range(len(ts)) if marks["jumped"] - 0.4 <= ts[i] <= marks["jumped"] + 0.6]
    if not cand:
        raise InputError(f"{d.name}: no frame near the jump")
    jf = max(cand, key=lambda i: dfull[i])

    def burst(i0):
        """the run of changing chart frames from i0 (gaps < 0.15 s); returns (first, last) frame index"""
        ch_ = [i for i in range(i0, len(ts)) if dchart[i] > 6]
        if not ch_:
            return None
        a = ch_[0]
        b = a
        for i in ch_[1:]:
            if ts[i] - ts[b] > 0.15:
                break
            b = i
        return a, b

    def drawon(i0, name):
        bb = burst(i0)
        if not bb:
            raise InputError(f"{d.name}: no draw-on after {name}")
        a, _b = bb
        # the start is the MEASURED first chart change (the dim at 0 ms); the draw-on ends with the label pop
        # (950-1100 ms), so the last strong change within 1.3 s gives the measured length, checked against the app's
        # 1.1 s (a warning, not a guess: the timeline never infers the start from it)
        b = max(i for i in range(a, len(ts)) if ts[i] <= ts[a] + 1.3 and (dchart[i] > 6 or i == a))
        dur = ts[b] - ts[a]
        start = ts[a]
        inwin = [i for i in range(len(ts)) if start <= ts[i] <= start + DRAW_MS / 1000]
        uniq = [i for i in inwin if dchart[i] > 1.0]
        gaps = np.diff(ts[inwin]) if len(inwin) > 1 else np.array([9.0])
        warn = None if abs(dur - DRAW_MS / 1000) <= 0.1 else (
            f"measured draw-on burst {dur:.3f} s, the app's timeline says {DRAW_MS / 1000} s: check PATTERN_TIMELINE")
        return {"first_change_s": round(float(ts[a]), 4), "last_change_s": round(float(ts[b]), 4),
                "burst_s": round(float(dur), 3), "start_s": round(float(start), 4), "start_from": "measured first change",
                "burst_check": warn or "ok (1.1 s +- 0.1)",
                "frames_in_draw": len(inwin), "unique_frames": len(uniq),
                "unique_fps": round(len(uniq) / (DRAW_MS / 1000), 1), "max_gap_ms": round(float(gaps.max()) * 1000, 1),
                "median_gap_ms": round(float(np.median(gaps)) * 1000, 1)}, warn

    tap = {t["name"]: t for t in tk["taps"]}
    for need in ("show1", "hide", "show", "hide_b", "show_b", "hide_end", "show_end"):
        if need not in tap:
            raise InputError(f"{d.name}: tap {need} missing")
    idx_of = lambda name: int(np.searchsorted(ts, marks[name]))  # noqa: E731
    d1, w1 = drawon(idx_of("show1"), "the hook Show tap")
    d2, w2 = drawon(idx_of("show"), "Show")
    d3, w3 = drawon(idx_of("show_b"), "the second Show")
    d4, w4 = drawon(idx_of("show_end"), "the last Show")
    resp = {}
    for nm in ("hide", "hide_b", "hide_end"):
        bb = burst(idx_of(nm))
        resp[nm] = round(float(ts[bb[0]] - marks[nm]), 3) if bb else None
    banner = drawn.get("banner") or {}
    shown = steps.get("shown", {}).get("named", {})
    res = {"take": d.name, "frames": len(fr), "jump_frame": int(jf), "jump_s": round(float(ts[jf]), 4),
           "marks": {k: round(v, 4) for k, v in marks.items()}, "late": late,
           "draw_on_1": d1, "draw_on_2_show": d2, "draw_on_3_show_b": d3, "draw_on_4_show_end": d4,
           "tap_response_s": resp, "warnings": [w for w in (w1, w2, w3, w4) if w],
           "banner_text": banner.get("text"), "banner_text_after_show": (shown.get("banner") or {}).get("text"),
           "guest_badge_text_in_page": tk.get("guest_badge_end"), "search_track": tk.get("search_track")}
    res["score"] = (min(d1["unique_fps"], d2["unique_fps"]) - 0.2 * max(d1["max_gap_ms"], d2["max_gap_ms"])
                    - 30 * len(late) - 50 * sum(v is None for v in resp.values()) - 10 * len(res["warnings"]))
    return res


# ================================================================================================ the screen track
def line_drawn(img: np.ndarray, L: list) -> float:
    """How far the app has drawn one pattern line on this frame: the last column (of the fitted line's span) where a
    line-coloured pixel (#bbf7d0) sits within 3 px of the line, as a fraction of the span."""
    u0, v0, u1, v1 = L
    xs = np.arange(int(u0), int(u1))
    vs = (v0 + (v1 - v0) * (xs - u0) / (u1 - u0)).astype(int)
    hit = np.zeros(len(xs), bool)
    for dv in range(-3, 4):
        px = img[np.clip(vs + dv, 0, img.shape[0] - 1), xs]
        hit |= (px[:, 0] > 140) & (px[:, 1] > 225) & (px[:, 2] > 180) & (px[:, 2] < 240)
    nz = np.nonzero(hit)[0]
    return round(float((nz.max() + 1) / len(xs)), 3) if len(nz) else 0.0


def build_track(tk: dict, an: dict, T: dict, take_dir: Path | None = None, lines: list | None = None) -> dict:
    t0 = tk["t0_wall"]
    ts = np.array([f[1] - t0 for f in tk["frames"]])
    nums = [f[0] for f in tk["frames"]]
    m = an["marks"]
    d1, d2 = an["draw_on_1"]["start_s"], an["draw_on_2_show"]["start_s"]
    d4 = an["draw_on_4_show_end"]["start_s"]
    a0 = d1 + T["hook_lead"]
    sl = T["slow"]
    last_out = T["end"] - 1 / FPS                                        # the last frame: one source frame before
    last_src = d4 + T["hook_lead"] - SRC_FRAME_S                         # frame 0's point in the draw-on
    anchors = [(0.0, a0), (T["hook_out"], d1 + DRAW_MS / 1000), (T["t_hide"], m["hide"]), (T["t_show"], m["show"]),
               (T["show_slow_end"], m["show"] + (T["show_slow_end"] - T["t_show"]) * sl),
               (T["t_hide_b"], m["hide_b"]), (T["t_show_b"], m["show_b"]), (T["t_hide_end"], m["hide_end"]),
               (T["t_show_end"], m["show_end"]), (last_out, last_src), (T["end"], last_src + sl / FPS)]
    segs = []
    for (o0, s0), (o1, s1) in zip(anchors, anchors[1:]):
        if o1 <= o0:
            raise InputError(f"timeline anchors out of order: {anchors}")
        segs.append({"out": [round(o0, 4), round(o1, 4)], "src": [round(s0, 4), round(s1, 4)],
                     "speed": round((s1 - s0) / (o1 - o0), 4)})
    n = int(round(T["end"] * FPS))
    track, srcs, idx = [], [], []
    for i in range(n):
        t = i / FPS
        sg = next(s for s in segs if s["out"][0] <= t < s["out"][1] + 1e-9) if t < segs[-1]["out"][1] else segs[-1]
        s = sg["src"][0] + (t - sg["out"][0]) * sg["speed"]
        k = int(np.searchsorted(ts, s + 1e-6, side="right")) - 1          # the frame on screen at source time s
        k = max(k, 0)
        track.append(nums[k])
        idx.append(k)
        srcs.append(round(float(s), 4))
    if min(idx) < an["jump_frame"]:
        raise InputError("the track reaches back before the jump (page-top frames would show)")
    if min(srcs) < m["show1"]:
        raise InputError("the track reaches back before the hook's Show tap")

    def out_at(src_t):                                                   # output time showing source time src_t
        for sg in segs:
            if sg["src"][0] <= src_t <= sg["src"][1]:
                return sg["out"][0] + (src_t - sg["src"][0]) / sg["speed"]
        raise InputError(f"source time {src_t} is not in the cut")
    # slow segments (the hook, the Show draw-on, the last Show): unique source frames per output frame (never
    # interpolated: repeats only); every other segment plays at real speed
    for sg in segs:
        sg["kind"] = "slow" if sg["speed"] < 0.75 else "real"
    slow_out = []
    for sg in segs:
        if sg["kind"] != "slow":
            continue
        so = [i for i in range(n) if sg["out"][0] - 1e-9 <= i / FPS < sg["out"][1] - 1e-9]
        uniq = len(set(idx[i] for i in so))
        slow_out.append({"out_s": sg["out"], "speed": sg["speed"], "output_frames": len(so),
                         "distinct_source_frames": uniq, "repeat_frames": len(so) - uniq, "interpolated_frames": 0})
    seg_speeds = [sg["speed"] for sg in segs if sg["kind"] == "real"]
    # per output frame: where the app's pattern drawing is (seconds since the last measured draw-on start), or how
    # long ago it was hidden: the background beams follow the real draw-ons with the app's own timeline
    starts = [an[k]["start_s"] for k in ("draw_on_1", "draw_on_2_show", "draw_on_3_show_b", "draw_on_4_show_end")]
    hides = [m[k] + (an["tap_response_s"].get(k) or 0.045) for k in ("hide", "hide_b", "hide_end")]
    beam, prog_cache = [], {}
    for s, k in zip(srcs, idx):
        ds = max((x for x in starts if x <= s), default=None)
        hs = max((x for x in hides if x <= s), default=None)
        if hs is not None and (ds is None or hs > ds):
            beam.append([-1.0, round(s - hs, 4), 0.0, 0.0])
            continue
        a = round(s - ds, 4) if ds is not None else 9.0
        if a <= 0.9 and lines is not None:                               # the real line tips, measured on the frame
            if k not in prog_cache:
                img = np.asarray(Image.open(take_dir / "frames" / f"{nums[k]:05d}.png").convert("RGB")).astype(np.int16)
                prog_cache[k] = [line_drawn(img, L_) for L_ in lines]
            pu, pl = prog_cache[k]
        else:
            pu = pl = 1.0
        beam.append([a, -1.0, pu, pl])
    return {"track": track, "src_s": srcs, "src_idx": idx, "segments": segs, "anchors": anchors, "beam": beam,
            "impact_out": round(out_at(d2 + LABEL_MS / 1000), 4), "show_latency_s": round(d2 - m["show"], 4),
            "d2_out": round(out_at(d2), 4), "d3_out": round(out_at(an["draw_on_3_show_b"]["start_s"]), 4),
            "label_b_out": round(out_at(an["draw_on_3_show_b"]["start_s"] + LABEL_MS / 1000), 4),
            "real_speed_range": [round(min(seg_speeds), 4), round(max(seg_speeds), 4)],
            "loop_seam": {"last_frame_app_s": round(srcs[-1] - d4, 4), "frame0_app_s": round(srcs[0] - d1, 4),
                          "source_frame_s": round(SRC_FRAME_S, 4)},
            "slow": {"segments": slow_out, "speed": sl,
                     "output_frames": sum(x["output_frames"] for x in slow_out),
                     "distinct_source_frames": sum(x["distinct_source_frames"] for x in slow_out),
                     "repeat_frames": sum(x["repeat_frames"] for x in slow_out), "interpolated_frames": 0}}


def line_geometry(take_dir: Path, tk: dict, an: dict) -> dict:
    """The real upper pattern line on the replayed draw-on (for the camera glide), and the line colour (the accent)."""
    t0 = tk["t0_wall"]
    ts = np.array([f[1] - t0 for f in tk["frames"]])
    nums = [f[0] for f in tk["frames"]]
    d2 = an["draw_on_2_show"]["start_s"]
    k_on = int(np.searchsorted(ts, d2 + 1.5, side="right")) - 1
    k_off = int(np.searchsorted(ts, an["marks"]["show"] - 0.05, side="right")) - 1
    on = np.asarray(Image.open(take_dir / "frames" / f"{nums[k_on]:05d}.png").convert("RGB")).astype(np.int16)
    off = np.asarray(Image.open(take_dir / "frames" / f"{nums[k_off]:05d}.png").convert("RGB")).astype(np.int16)
    chart = rjson(take_dir / "take.json")["steps"]
    named = next(s for s in chart if s["label"] == "drawn")["named"]
    bx, by, bw, bh = [v * DPR for v in named["chart"]["rect"]]
    by0 = (named["banner"]["rect"][1] + named["banner"]["rect"][3]) * DPR + 6
    sub_on = on[int(by0):int(by + bh), int(bx):int(bx + bw)]
    sub_off = off[int(by0):int(by + bh), int(bx):int(bx + bw)]
    # the app's pattern line colour is #bbf7d0 (light mint; PATTERN_STYLE.line); candles are #10b981-ish and the
    # anchor dots #86efac, so a red channel > 140 separates the lines from both
    r, g, b = sub_on[..., 0], sub_on[..., 1], sub_on[..., 2]
    mint = ((r > 140) & (g > 225) & (b > 180) & (b < 240) & (g > r + 25)
            & (np.abs(sub_on - sub_off).max(axis=2) > 40))
    ys, xs = np.nonzero(mint)
    if len(xs) < 200:
        raise InputError("could not find the drawn pattern lines on the replay frame")
    # the app's accent (#4ade80: the callout border, PATTERN_STYLE.accent), measured on the frame
    acc_px = sub_on[np.abs(sub_on - np.array([74, 222, 128])).max(axis=2) < 12]
    if len(acc_px) < 200:
        raise InputError("the app's accent colour is not on the replay frame")
    accent = "#%02x%02x%02x" % tuple(int(v) for v in np.median(acc_px, axis=0))
    line_color = "#%02x%02x%02x" % tuple(int(v) for v in np.median(sub_on[mint], axis=0))
    # two lines by RANSAC over the line pixels (deterministic seed): the best line, its inliers removed, the next
    pts = np.stack([xs, ys], 1).astype(float)
    rng = np.random.default_rng(7)

    def ransac(P):
        best, bi = None, None
        for _ in range(2500):
            a, b = P[rng.integers(len(P))], P[rng.integers(len(P))]
            if abs(b[0] - a[0]) < 60:
                continue
            k = (b[1] - a[1]) / (b[0] - a[0])
            res = np.abs(P[:, 1] - (a[1] + k * (P[:, 0] - a[0]))) / math.sqrt(1 + k * k)
            inl = res < 4.0
            if best is None or inl.sum() > best:
                best, bi = int(inl.sum()), inl
        p = np.polyfit(P[bi, 0], P[bi, 1], 1)
        a, b = float(np.percentile(P[bi, 0], 0.5)), float(np.percentile(P[bi, 0], 99.5))
        return [a, float(np.polyval(p, a)), b, float(np.polyval(p, b))], bi, best
    l1, in1, n1 = ransac(pts)
    l2, _, n2 = ransac(pts[~in1])
    if min(n1, n2) < 300:
        raise InputError(f"could not fit two pattern lines (inliers {n1}, {n2})")
    mid = lambda l_: (l_[1] + l_[3]) / 2  # noqa: E731
    up, lo = sorted([l1, l2], key=mid)
    up, lo = ([round(l_[0] + bx, 1), round(l_[1] + by0, 1), round(l_[2] + bx, 1), round(l_[3] + by0, 1)]
              for l_ in (up, lo))
    return {"accent": accent, "line_color": line_color, "accent_px": int(len(acc_px)),
            "upper_line_src": up, "lower_line_src": lo,
            "frames_used": [nums[k_on], nums[k_off]], "mint_pixels": int(len(xs))}


# ================================================================================================ camera
def pose(t, s, top, xc=None, uf=None, fx=None, yaw=0.0, pitch=2.0, key=0.0, sweep=-2.4, ease="io", vf=632.0):
    if uf is None:
        uf, fx = SRC_W / 2, xc
    return {"t": round(t, 4), "uf": uf, "vf": vf, "fx": fx, "fy": top + vf * s, "s": s, "yaw": yaw, "pitch": pitch,
            "key": key, "sweep": sweep, "ease": ease}


def camera_keys(ep, T, rects, line) -> list[dict]:
    """The phone stays whole: every key frames the complete banner and chart inside the safe zone (x 60-920; the QA
    hero gate checks every output frame). Pushes scale about the screen centre (the chart's centre) instead of
    panning sideways; the 'glide' along the upper line is a yaw sweep that follows the line as it draws."""
    cam = ep["camera"]
    p0, he, push, pull, mac = cam["frame0"], cam["hook_end"], cam["push"], cam["pull"], cam["macro"]
    k = [
        pose(0.0, p0["s"], p0["top"], p0["xc"], yaw=p0["yaw"], pitch=p0["pitch"], sweep=-2.4),
        pose(T["hook_out"], he["s"], he["top"], he["xc"], yaw=he["yaw"], pitch=he["pitch"], key=0.2, sweep=-1.0,
             ease="lin"),
        pose(T["t_hide"] - 0.08, push["s"], push["top"], push["xc"], yaw=2.0, pitch=2.6, key=0.6, sweep=0.6, ease="o"),
        pose(T["t_show"] + 0.2, push["s"] + 0.004, push["top"] - 2, push["xc"], yaw=2.6, pitch=2.4, key=0.6,
             sweep=1.2, ease="lin"),
        # the glide: a yaw sweep that follows the upper line while the app draws it (0.5x)
        pose(T["show_lines_end"], push["s"] + 0.008, push["top"] - 5, push["xc"], yaw=-2.4, pitch=2.0, key=0.9,
             sweep=2.4, ease="io"),
        pose(T["impact"], push["s"] + 0.008, push["top"] - 5, push["xc"], yaw=-2.6, pitch=2.0, key=0.9, sweep=2.4,
             ease="lin"),
        pose(T["t_hide_b"] - 0.05, pull["s"], pull["top"], pull["xc"], yaw=-1.2, pitch=3.2, key=1.0, sweep=2.0,
             ease="io"),
        pose(T["shape"] + 0.55, mac["s"], mac["top"], mac["xc"], yaw=mac["yaw"], pitch=1.8, key=1.3, sweep=-2.0,
             ease="o"),
        pose(T["label_b"] + 0.25, mac["s"] + 0.004, mac["top"] - 2, mac["xc"], yaw=mac["yaw"] + 0.8, pitch=1.8,
             key=1.2, sweep=-2.4, ease="lin"),
        pose(max(T["brand2"] + 0.5, T["label_b"] + 1.0), p0["s"] * 1.03, p0["top"] - 6, p0["xc"] - 4, yaw=p0["yaw"] + 2.0,
             pitch=p0["pitch"] - 0.3, key=0.4, sweep=0.0),
        pose(T["end"], p0["s"], p0["top"], p0["xc"], yaw=p0["yaw"], pitch=p0["pitch"], key=0.0, sweep=-2.4),
    ]
    return k


# ================================================================================================ QA helpers
def framing_problems(fl: list[dict]) -> dict:
    """keep-out rects in frame, hero rects outside the safe zone, our overlays on the screen window (every frame)."""
    ko, hero_out, over = [], [], []
    for f in fl:
        ko += [(f["i"], k["id"]) for k in f["keepout"] if k["visible"]]
        for h in f.get("hero", []):
            if h.get("skip_t") and h["skip_t"][0] <= f["t"] <= h["skip_t"][1]:
                continue
            x0, y0, x1, y1 = h.get("zone") or SAFE
            xs = [p[0] for p in h["quad"]]
            ys = [p[1] for p in h["quad"]]
            if min(xs) < x0 - 0.5 or max(xs) > x1 + 0.5 or min(ys) < y0 - 0.5 or max(ys) > y1 + 0.5:
                hero_out.append((f["i"], h["id"], [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]))
        quad = [tuple(p) for p in f["window_quad"]]
        for b in f["texts"]:
            if b["role"] != "ripple" and sat_overlap(b["box"], quad):
                over.append((f["i"], b["role"], b["box"]))
    return {"keepout_visible": ko, "hero_outside": hero_out, "overlay_on_screen": over}


def sat_overlap(rect, quad) -> bool:
    x, y, w, h = rect
    R_ = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    for poly in (R_, quad):
        for i in range(len(poly)):
            ax, ay = poly[i]
            bx_, by_ = poly[(i + 1) % len(poly)]
            nx, ny = by_ - ay, ax - bx_
            p1 = [nx * px + ny * py for px, py in R_]
            p2 = [nx * px + ny * py for px, py in quad]
            if max(p1) <= min(p2) or max(p2) <= min(p1):
                return False
    return True


def ocr(paths: list[Path], run: Path) -> dict:
    lst = run / "qa_ocr_list.txt"
    lst.write_text("\n".join(str(p.resolve()) for p in paths), encoding="utf-8")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(OCR_PS1), "-List",
                        str(lst.resolve())], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600)
    if r.returncode != 0:
        raise InputError("OCR failed: " + r.stderr[-800:])
    out = {}
    for ln in r.stdout.splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            o = json.loads(ln, strict=False)
            out[Path(o["path"]).name] = o["text"]
    return out


def tile_sheet(items: list[tuple[str, Path]], out: Path, tw=216, cols=11, scale_label=0.09) -> Path:
    th = tw * 16 // 9
    rows = math.ceil(len(items) / cols)
    sh = Image.new("RGB", (cols * tw, rows * (th + 4)), (20, 20, 24))
    for k, (lab, p) in enumerate(items):
        im = Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        f = F.font(int(tw * scale_label))
        d.rectangle((0, 0, tw, int(tw * 0.13)), fill=(0, 0, 0))
        d.text((6, 2), lab, font=f, fill=(255, 255, 255))
        sh.paste(im, ((k % cols) * tw, (k // cols) * (th + 4)))
    sh.save(out)
    return out


# ================================================================================================ main
def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    eps = [x for x in argv if x.endswith(".json")]
    if eps and rjson(Path(eps[0])).get("look", "studio") == "studio":    # the default look since day 2
        import studio
        return studio.main(argv)
    return main_dock(argv)


def main_dock(argv=None) -> int:
    """Day 1 look ("look": "dock"): the recorded mobile site on a slab in a dock (web take via take.py)."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode")
    ap.add_argument("--out")
    ap.add_argument("--takes", type=int, default=3)
    ap.add_argument("--reuse-takes", action="store_true", help="use takes/take*/ already recorded by this run")
    ap.add_argument("--take", help="force this take (take1/take2/...)")
    ap.add_argument("--check-only", action="store_true", help="stop after check6.png")
    ap.add_argument("--skip-render", action="store_true")
    a = ap.parse_args(argv)
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    ep = rjson(Path(a.episode))
    run = Path(a.out) if a.out else MEDIA / ".ops" / "app-showcase" / ep["slug"]
    run.mkdir(parents=True, exist_ok=True)
    log = []
    try:
        # ---------------------------------------------------------------- voice and the planned timeline
        lines, clips, speed = voice(ep, run, None)
        T = timeline(ep, lines, clips, lat_show=ep.get("show_latency_guess", 0.06))
        log.append({"planned_T": T, "voice_speed": speed})
        if T["t_hide"] > 4.2:
            raise InputError(f"the first real tap would land at {T['t_hide']} s (> 4.2 s): shorten the hook lines")
        # ---------------------------------------------------------------- takes
        tdir = run / "takes"
        if a.reuse_takes:
            takes = sorted(p for p in tdir.glob("take*") if (p / "take.json").is_file())
        else:
            takes = record_takes(ep, T, run, a.takes)
        res = rjson(tdir / "resolve.json")
        req = ep["requires"]
        if res["pattern_status"] != req["pattern_status"]:
            raise InputError(f"today's showcase pattern is {res['pattern_status']!r}; this episode is written for "
                             f"{req['pattern_status']!r}")
        analyses = []
        for d in takes:
            try:
                analyses.append(analyze_take(d, ep))
            except InputError as e:
                analyses.append({"take": d.name, "error": str(e), "score": -1e9})
        wjson(tdir / "analysis.json", analyses)
        good = [x for x in analyses if "error" not in x]
        if not good:
            raise InputError("no usable take: " + json.dumps(analyses)[:1500])
        best = next(x for x in good if x["take"] == a.take) if a.take else max(good, key=lambda x: x["score"])
        bdir = tdir / best["take"]
        for w_ in req["banner_words"]:
            if w_ not in (best["banner_text"] or ""):
                raise InputError(f"the banner does not read {w_!r}: {best['banner_text']!r}")
        chip_line = next((l for l in (best["banner_text"] or "").split("\n") if "Confirmed" in l or "Forming" in l), "")
        if req.get("banner_chip_starts") and req["banner_chip_starts"] not in chip_line:
            raise InputError(f"the banner chip reads {chip_line!r}, not {req['banner_chip_starts']!r}")
        # the chosen take, copied whole (frames + logs)
        take_out = run / "take"
        if take_out.exists():
            shutil.rmtree(take_out)
        shutil.copytree(bdir, take_out)
        wjson(take_out / "analysis.json", best)
        tk = rjson(take_out / "take.json")
        # ---------------------------------------------------------------- the real timeline (measured)
        lines, clips, speed = voice(ep, run, None)
        lat = best["draw_on_2_show"]["start_s"] - best["marks"]["show"]
        lat_end = best["draw_on_4_show_end"]["start_s"] - best["marks"]["show_end"]
        T = timeline(ep, lines, clips, lat_show=lat, lat_end=lat_end)
        line = line_geometry(take_out, tk, best)
        trk = build_track(tk, best, T, take_out, [line["upper_line_src"], line["lower_line_src"]])
        T["impact"] = trk["impact_out"]
        T["d2_out"], T["d3_out"] = trk["d2_out"], trk["d3_out"]
        T["flash0"] = T["hook_label"]                                    # light events: the hook's label pop
        T["flash1"] = T["impact"]                                        # ... and the one impact
        T["label_b"] = trk["label_b_out"]
        steps = {s["label"]: s for s in tk["steps"]}
        named = steps["drawn"]["named"]
        rects = {k: v["rect"] for k, v in named.items() if v}
        # keep-out union (css -> source px) over every recorded state the track uses, and the visible page text
        keep, texts = [], {}
        for lab in [s_["label"] for s_ in tk["steps"] if s_["label"] != "top"]:
            for kx in steps[lab]["keepout"]:
                x, y, w, h = kx["visible"]
                keep.append({"id": f"{lab}: {kx['why']}", "src": [x * DPR, y * DPR, (x + w) * DPR, (y + h) * DPR]})
            for tx in steps[lab]["texts"]:
                if tx["visible"]:
                    x, y, w, h = tx["visible"]
                    texts[(tx["text"], round(y))] = {"text": tx["text"], "src": [x * DPR, y * DPR, (x + w) * DPR,
                                                                                  (y + h) * DPR]}
        chart_bottom = (named["chart"]["rect"][1] + named["chart"]["rect"][3]) * DPR
        top_keep = min(k["src"][1] for k in keep)
        v_plinth = round(min(chart_bottom - 2, top_keep - 4), 1)
        if v_plinth < chart_bottom - 30:
            raise InputError(f"a keep-out element sits inside the chart window (v {top_keep} < {chart_bottom}): "
                             f"{[k['id'] for k in keep if k['src'][1] < chart_bottom]}")
        logo = named.get("ticker_logo")
        logo_src = [v * DPR for v in (logo["rect"][0], logo["rect"][1], logo["rect"][0] + logo["rect"][2],
                                      logo["rect"][1] + logo["rect"][3])] if logo else None
        cam = camera_keys(ep, T, rects, line)
        taps = []
        for name in ("hide", "show", "hide_b", "show_b", "hide_end", "show_end"):
            tp = next(x for x in tk["taps"] if x["name"] == name)
            taps.append({"name": name, "t": T["t_" + name], "u": tp["x"] * DPR, "v": tp["y"] * DPR, "label": tp["label"]})
        # the hero: the app's banner, its Hide/Show control, its words and the chart (price axis included) must be
        # whole and inside the safe zone on every frame (no cropped UI)
        hero = []
        sty_ = ep["style"]
        for lab in ("drawn", "hidden"):
            for k in ep["hero_rects"]:
                v = (steps[lab]["named"].get(k) or {}).get("rect")
                if v:
                    x, y, w, h = v
                    hero.append({"id": f"{lab}: {k}", "src": [x * DPR, y * DPR, (x + w) * DPR, min((y + h) * DPR, v_plinth)]})
        bz = sty_["phone"]["bezel"] * 1000                               # the whole phone (above the dock) in frame
        free = [T["t_hide_b"], round(max(T["brand2"] + 0.5, T["label_b"] + 1.0), 3)] if ep["camera"]["macro"].get("free_phone") else None
        hero.append({"id": "phone body", "src": [-bz, -bz, SRC_W + bz, v_plinth], "zone": [0, 0, W, H], "skip_t": free})
        caps = captions(lines, T)
        sty = ep["style"]
        R = {"W": W, "H": H, "fps": FPS, "duration": T["end"], "supersample": 2, "fov": ep["camera"]["fov"],
             "src": {"w": SRC_W, "h": SRC_H}, "window": {"v_top": 0, "v_plinth": v_plinth},
             "phone": sty["phone"], "plinth": sty["plinth"], "safe_cx": (SAFE[0] + SAFE[2]) / 2,
             "pill": sty["pill"], "headline": sty["headline"], "caption": sty["caption"], "end": sty["end"],
             "punch": ep["camera"]["punch"], "accent": line["accent"],
             "text": {"headline": ep["headline"], "headline_accent": ep["headline_accent"],
                      "site": "rapidtradeview.trade", "disclaimer": "Not investment advice."},
             "mark": F.brand_mark_spec(), "T": T, "cam": cam, "track": trk["track"], "taps": taps,
             "captions": caps, "keepout": keep, "page_texts": list(texts.values()), "logo_src": logo_src,
             "hero": hero, "safe": SAFE, "beam": trk["beam"], "beams": sty["beams"], "floor": sty["floor"],
             "lines": [line["upper_line_src"], line["lower_line_src"]],
             "pattern_ms": {"lines": list(LINES_MS), "fill_end": 950, "label": [LABEL_MS, DRAW_MS]}}
        wjson(run / "render.json", R)
        # ---------------------------------------------------------------- framing gates before any pixel is rendered
        run_py(CONDA_PY, [str(HERE / "render.py"), "--run", str(run), "--ffmpeg", str(FFMPEG), "--probe"], "probe")
        pr_ = rjson(run / "probe.json")
        pbad = framing_problems(pr_["frames"])
        log.append({"probe": {k: (v if not isinstance(v, list) else v[:6]) for k, v in pbad.items()}})
        if (pbad["keepout_visible"] or pbad["hero_outside"] or pbad["overlay_on_screen"]) and not a.check_only:
            wjson(run / "build_log.json", log)
            raise InputError("framing gate failed before render: " + json.dumps({k: v[:4] for k, v in pbad.items()}))
        vs = {"voice": ep["voice"]["voice"], "speed": speed, "engine": "Kokoro-82M (Apache-2.0), local",
              "say_map": {"RapidTradeView": "Rapid Trade View"},
              "lines": [{"id": ln["id"], "say": ln["say"], "t0": ln["t0"], "t1": ln["t1"],
                         "words": [{"word": w["word"], "t0": w["t0"], "t1": w["t1"]} for c in ln["chunks"]
                                   for w in c["words"]]} for ln in lines]}
        wjson(run / "voice_script.json", vs)
        (run / "voice_script.txt").write_text("\n".join(f"[{ln['t0']:.2f}-{ln['t1']:.2f}] {ln['say']}" for ln in lines)
                                              + "\n", encoding="utf-8")
        resolved = {**ep, "resolved_at": now_z(), "resolve": res, "take_used": best["take"], "timeline": T,
                    "track_segments": trk["segments"], "slow": trk["slow"], "v_plinth": v_plinth,
                    "upper_line": line, "voice_speed": speed, "captions": caps, "camera": ep["camera"],
                    "camera_keys": cam, "taps": taps}
        wjson(run / "episode.json", resolved)
        # ---------------------------------------------------------------- check6 (looked at before the full render)
        n = len(trk["track"])
        c6 = [0, 2 * FPS, 4 * FPS, int(6.5 * FPS), 12 * FPS, n - 1]
        c6 = [min(i, n - 1) for i in c6]
        chk = run / "check6_frames"
        if chk.exists():
            shutil.rmtree(chk)
        out = run_py(CONDA_PY, [str(HERE / "render.py"), "--run", str(run), "--ffmpeg", str(FFMPEG), "--frames-dir",
                                str(chk), "--only", ",".join(map(str, c6))], "check6 render")
        tile_sheet([(f"{i / FPS:.1f}s", chk / f"f{i:04d}.png") for i in c6], run / "check6.png", tw=360, cols=6)
        log.append({"check6": json.loads(out.strip().splitlines()[-1])})
        if a.check_only:
            wjson(run / "build_log.json", log)
            print(json.dumps({"check6": str(run / "check6.png"), "T": T, "slow": trk["slow"]}, indent=1))
            return 0
        # ---------------------------------------------------------------- full render
        fr_dir = run / "frames_png"
        t_hidef = int(round((T["t_hide"] + 0.35) * FPS))
        t_drawf = int(round((T["d2_out"] + 0.75) * FPS))
        save = sorted({0, t_hidef, t_drawf, n - 1} | set(range(0, n, 10)))
        if not (a.skip_render and (run / "video_noaudio.mp4").is_file()):
            if fr_dir.exists():
                shutil.rmtree(fr_dir)
            out = run_py(CONDA_PY, [str(HERE / "render.py"), "--run", str(run), "--ffmpeg", str(FFMPEG),
                                    "--frames-dir", str(fr_dir), "--save", ",".join(map(str, save))], "render",
                         timeout=3600)
            log.append({"render": json.loads(out.strip().splitlines()[-1])})
        frames = rjson(run / "frames.json")
        # ---------------------------------------------------------------- sound
        kit = make_kit()
        sil = ep.get("pre_impact_silence_s", 0.3)
        pen_at = T["d2_out"] + LINES_MS[0] / 1000 / T["slow"]
        if pen_at + PENCIL_MID_S + 0.02 > T["impact"] - sil:
            raise InputError(f"the Show draw sound ({pen_at:.2f}+{PENCIL_MID_S}) runs into the pre-impact silence")
        cues = [{"sfx": "sub_boom", "at": 0.0, "gain_db": -16},
                {"sfx": "pencil_hook", "at": 0.0, "gain_db": -8},                         # the hook draw-on (0.5x)
                {"sfx": "tick", "at": T["hook_label"], "gain_db": -14},                   # its label pop + light event
                {"sfx": "whoosh", "at": T["hook_out"] - 0.1, "gain_db": -15},             # the push to the banner
                {"sfx": "pop", "at": T["t_hide"], "gain_db": -3},
                {"sfx": "pop", "at": T["t_show"], "gain_db": -3},
                {"sfx": "pencil_mid", "at": pen_at, "gain_db": -8},                       # the Show draw-on (0.5x)
                {"sfx": "glass_snap", "at": T["impact"], "gain_db": -1},                  # the one impact
                {"sfx": "pop", "at": T["t_hide_b"], "gain_db": -5},
                {"sfx": "pop", "at": T["t_show_b"], "gain_db": -5},
                {"sfx": "whoosh", "at": T["shape"] + 0.05, "gain_db": -16},               # the push to the words
                {"sfx": "pencil_short", "at": T["d3_out"] + LINES_MS[0] / 1000, "gain_db": -11},   # real speed
                {"sfx": "tick", "at": T["label_b"], "gain_db": -15},
                {"sfx": "whoosh", "at": T["brand2"] + 0.05, "gain_db": -16},              # pull back, pill grows
                {"sfx": "pop", "at": T["t_hide_end"], "gain_db": -6},
                {"sfx": "pop", "at": T["t_show_end"], "gain_db": -6}]
        pre = run / "mix_pre.wav"
        mixinfo = S.mix(clips, cues, T["end"], pre, kit, bed_under_voice_db=ep.get("bed_under_voice_db", 20.0),
                        bed_mute=[(T["impact"] - sil - 0.02, T["impact"])])
        mixed = run / "mix.wav"
        final = run / "final.mp4"
        ceiling = -2.5
        for _ in range(3):
            minfo = F.master(pre, mixed, ceiling_db=ceiling)
            F.run_ff(["-i", str(run / "video_noaudio.mp4"), "-i", str(mixed), "-map", "0:v", "-map", "1:a",
                      "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-maxrate", "9M", "-bufsize", "18M",
                      "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                      "-shortest", "-movflags", "+faststart", str(final)])
            fl = F.loudness(final)
            minfo["final_mp4"] = fl
            if fl["true_peak_dbtp"] <= -1.1:
                break
            ceiling -= fl["true_peak_dbtp"] + 1.3
        shutil.copyfile(fr_dir / "f0000.png", run / "frame0.png")
        # ---------------------------------------------------------------- QA
        q = qa(run, ep, R, T, lines, frames, final, trk, take_out, tk, best, res, save)
        q["mix"] = mixinfo
        q["master"] = minfo
        wjson(run / "qa.json", q)
        # sheets
        dur = T["end"]
        times = [round(x * 0.5, 2) for x in range(int(dur / 0.5) + 1) if x * 0.5 < dur - 0.02]
        ps = F.decode_frames(final, times, run / "sheet_frames")
        tile_sheet([(f"{t:.1f}s", p) for t, p in zip(times, ps)], run / "sheet.png")
        picks = [("frame 0", 0), ("Hide", t_hidef), ("Show draw-on", t_drawf), ("end", n - 1)]   # n-1 = loop frame
        tiles = []
        for lab, i in picks:
            im = Image.open(fr_dir / f"f{i:04d}.png").convert("RGB").resize((360, 640), Image.LANCZOS)
            dd = ImageDraw.Draw(im)
            dd.rectangle((0, 0, 360, 40), fill=(0, 0, 0))
            dd.text((8, 6), f"{lab} {i / FPS:.1f}s", font=F.font(26), fill=(255, 255, 255))
            tiles.append(im)
        ph = Image.new("RGB", (4 * 370 - 10, 640), (255, 255, 255))
        for k, im in enumerate(tiles):
            ph.paste(im, (k * 370, 0))
        ph.save(run / "phone.png")
        # proof
        fonts = [{"file": str(F.FONTS / f), "licence": "SIL Open Font License 1.1", "licence_file": str(F.FONTS / lic),
                  "sha256": sha256(F.FONTS / f)} for f, lic in (("ArchivoBlack-Regular.ttf", "OFL-ArchivoBlack.txt"),
                                                               ("Inter.ttf", "OFL-Inter.txt"))]
        proof = {
            "episode": ep["slug"], "built_at": now_z(), "final_mp4": str(final), "final_sha256": sha256(final),
            "page_url": tk["url"], "capture_time": tk["captured_at"], "showcase_read": res,
            "banner_text_read_from_page": best["banner_text"], "banner_text_after_show": best["banner_text_after_show"],
            "free_route": {"route": "/dashboard/<T>#from=<report id> (opened from its own earnings report)",
                           "search_track_answer": tk.get("search_track")},
            "taps": [{**{k: v for k, v in tp.items() if k in ("name", "label", "x", "y", "box", "t", "setup")},
                      "css_px": [tp["x"], tp["y"]]} for tp in tk["taps"]],
            "setup_note": "setup taps (Hide, then the app's own SMA checkbox off) happen before the part the cut uses, "
                          "so the app's hidden state shows the chart without moving averages; every tap is real",
            "take_log_checks": [l for l in tk["log"] if l["what"].startswith("check")],
            "tap_times_in_video_s": {t_["name"]: t_["t"] for t_ in taps},
            "source_fps_during_draw_ons": {"hook (draw-on 1, slow motion from real frames)": best["draw_on_1"],
                                           "Show replay (draw-on 2, real speed)": best["draw_on_2_show"],
                                           "second Show (draw-on 3, real speed)": best["draw_on_3_show_b"],
                                           "last Show (draw-on 4, 0.5x into the loop)": best["draw_on_4_show_end"],
                                           "slow_motion": {"speed": T["slow"], **trk["slow"]},
                                           "real_speed_segments": trk["real_speed_range"],
                                           "warnings": best["warnings"]},
            "track_segments": trk["segments"],
            "take_frames_dir": str(take_out / "frames"), "takes_recorded": [x["take"] for x in analyses],
            "take_scores": [{k: x.get(k) for k in ("take", "score", "error")} for x in analyses],
            "fonts": fonts,
            "audio": {"voice": {"engine": "Kokoro-82M", "licence": "Apache-2.0", "voice": ep["voice"]["voice"],
                                "speed": speed},
                      "sfx": {k: {"file": str(p), "sha256": sha256(p), "licence": "synthesised (numpy)"}
                              for k, p in kit.items()},
                      "bed": "synthesised (numpy, filed/sound.py bed(), periodic over the episode)"},
            "code": {"three.js": "MIT (three@0.170.0, RoundedBoxGeometry, Reflector, RoomEnvironment addons)",
                     "brand_mark": str(F.BRAND_MARK_JSON)},
        }
        wjson(run / "proof.json", proof)
        wjson(run / "youtube.json", ep["youtube"])
        wjson(run / "build_log.json", log)
        print(json.dumps({"final": str(final), "duration": dur, "qa_pass": q["pass"], "gates": q["gates"]}, indent=1))
        return 0 if q["pass"] else 1
    except InputError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        wjson(run / "build_log.json", log + [{"error": str(e)}])
        return 2


# ================================================================================================ QA
def qa(run, ep, R, T, lines, frames, final, trk, take_out, tk, best, res, saved) -> dict:
    import cv2
    q = {"checked_at": now_z()}
    pr = F.probe(final)
    v = next(s for s in pr["streams"] if s["codec_name"] == "h264")
    au = next(s for s in pr["streams"] if s["codec_name"] == "aac")
    dur = float(pr["format"]["duration"])
    num, den = v["r_frame_rate"].split("/")
    q["duration_s"] = round(dur, 3)
    q["fps"] = round(int(num) / int(den), 3)
    q["size"] = [v["width"], v["height"]]
    q["file_mb"] = round(final.stat().st_size / 1e6, 2)
    q["audio"] = {"codec": au["codec_name"], "sample_rate": au["sample_rate"], "channels": au["channels"]}
    ld = F.loudness(final)
    q["loudness"] = ld
    allw = [w for ln in lines for c in ln["chunks"] for w in c["words"]]
    br = [w["t0"] for w in allw if w["word"].lower().startswith("rapid")]
    q["brand_word"] = {"first_s": br[0] if br else None, "last_s": br[-1] if br else None, "count": len(br)}
    q["speech"] = {"first_word_s": allw[0]["t0"], "last_word_s": allw[-1]["t1"]}
    gaps = [(round(b["t0"] - a_["t1"], 3), a_["word"], b["word"], a_["t1"]) for a_, b in zip(allw, allw[1:])]
    big = [g for g in gaps if g[0] > 0.25]
    pre_imp = [g for g in big if g[3] <= T["impact"] <= g[3] + g[0] + 0.15]
    q["speech_gaps_over_0_25s"] = [{"gap_s": g[0], "after": g[1], "before": g[2], "at_s": g[3],
                                    "pre_impact_silence": g in pre_imp} for g in big]
    nw = sum(len(ln["say"].split()) for ln in lines)
    q["words_per_s"] = round(nw / sum(ln["t1"] - ln["t0"] for ln in lines), 3)
    q["words"] = nw
    fl = frames["frames"]
    # brand pill on every sampled frame (from the final video), and its height against the in-app stock logo
    times = [round(x * 0.5, 2) for x in range(int(dur / 0.5) + 1) if x * 0.5 < dur - 0.02]
    sdir = run / "qa_frames"
    if sdir.exists():
        shutil.rmtree(sdir)
    sample = F.decode_frames(final, times, sdir)
    marks, ref = [], None
    for t, p in zip(times, sample):
        fi = fl[min(len(fl) - 1, int(round(t * FPS)))]
        x, y, w, h = [int(round(z)) for z in fi["pill"]]
        tile = int(round(R["pill"]["tile"] * h / (R["pill"]["tile"] + 2 * R["pill"]["pad"])))
        pad = (h - tile) // 2
        im = np.asarray(Image.open(p).convert("RGB")).astype(np.float32)
        crop = im[y + pad:y + pad + tile, x + pad:x + pad + tile]
        g = crop[..., 1]
        green = float(np.mean((g > crop[..., 0] + 40) & (g > crop[..., 2] + 10)))
        blue = float(np.mean((crop[..., 2] > crop[..., 0] + 30) & (crop[..., 2] > 120)))
        cs = np.asarray(Image.fromarray(crop.astype(np.uint8)).resize((48, 48), Image.LANCZOS)).astype(np.float32)
        ref = cs if ref is None else ref
        a_, b_ = cs - cs.mean(), ref - ref.mean()
        ncc = float((a_ * b_).sum() / (np.sqrt((a_ ** 2).sum() * (b_ ** 2).sum()) + 1e-6))
        marks.append({"t": t, "pill": [x, y, w, h], "green_frac": round(green, 3), "blue_frac": round(blue, 3),
                      "ncc_vs_frame0": round(ncc, 3), "ok": bool(green > 0.1 and blue > 0.1 and ncc > 0.75)})
    ratios = [f["pill"][3] / f["logo_px_h"] for f in fl if f.get("logo_px_h")]
    q["brand_pill"] = {"sampled": len(marks), "detected": sum(m["ok"] for m in marks),
                       "missing_at": [m["t"] for m in marks if not m["ok"]],
                       "pill_height_px": [round(min(f["pill"][3] for f in fl)), round(max(f["pill"][3] for f in fl))],
                       "in_app_logo_height_px": [round(min(f["logo_px_h"] for f in fl if f.get("logo_px_h")), 1),
                                                 round(max(f["logo_px_h"] for f in fl if f.get("logo_px_h")), 1)],
                       "min_pill_over_logo": round(min(ratios), 3) if ratios else None, "per_sample": marks}
    # keep-out projection gate (every output frame)
    vis = [(f["i"], k["id"]) for f in fl for k in f["keepout"] if k["visible"]]
    q["keepout_gate"] = {"frames": len(fl), "rects": len(R["keepout"]), "visible_hits": len(vis),
                         "examples": vis[:10], "v_plinth_src": R["window"]["v_plinth"],
                         "rect_ids": sorted({k["id"] for k in R["keepout"]})}
    # text gate: OCR every 10th frame + the projected page text check
    od = run / "qa_ocr"
    if od.exists():
        shutil.rmtree(od)
    od.mkdir()
    o_idx = list(range(0, len(fl), 10))
    for i in o_idx:
        shutil.copyfile(run / "frames_png" / f"f{i:04d}.png", od / f"f{i:04d}.png")
    texts = ocr([od / f"f{i:04d}.png" for i in o_idx], run)
    hits = []
    for name, tx in texts.items():
        up = tx.upper()
        for bad in OCR_BAD + tuple(w.upper() for w in F.PROVIDER_WORDS):
            if re.search(r"(?<![A-Z0-9])" + re.escape(bad) + r"(?![A-Z])", up):
                hits.append({"frame": name, "word": bad})
        if PARTY_RX.search(tx):
            hits.append({"frame": name, "word": "party label"})
    page_hits = []
    for f in fl:
        if f.get("page_texts_visible") is None:
            continue
        for tx in f["page_texts_visible"]:
            for bad in OCR_BAD + tuple(w.upper() for w in F.PROVIDER_WORDS):
                if re.search(r"(?<![A-Z0-9])" + re.escape(bad) + r"(?![A-Z])", tx.upper()):
                    page_hits.append({"frame": f["i"], "text": tx})
    q["text_gate"] = {"ocr_frames": len(o_idx), "ocr_engine": "Windows.Media.Ocr (built in)", "ocr_hits": hits,
                      "projected_page_text_frames": sum(1 for f in fl if f.get("page_texts_visible") is not None),
                      "projected_page_text_hits": page_hits,
                      "ocr_sample": {k: v[:300] for k, v in list(texts.items())[:3]}}
    # overlays vs the screen window, captions in the safe zone
    over, outside = [], []
    for f in fl:
        quad = [tuple(p) for p in f["window_quad"]]
        for b in f["texts"]:
            if b["role"] == "ripple":
                continue
            if sat_overlap(b["box"], quad):
                over.append({"i": f["i"], "role": b["role"], "box": b["box"]})
            x, y, w, h = b["box"]
            if x < SAFE[0] - 0.5 or y < SAFE[1] - 0.5 or x + w > SAFE[2] + 0.5 or y + h > SAFE[3] + 0.5:
                outside.append({"i": f["i"], "role": b["role"], "box": b["box"]})
    capsz = sorted({b["size"] for f in fl for b in f["texts"] if b["role"] == "caption"})
    q["overlay_vs_screen"] = {"overlaps": len(over), "examples": over[:8],
                              "note": "tap ripples are drawn on the glass at the logged tap point (asked for)"}
    q["safe_zone"] = {"zone": SAFE, "boxes_outside": len(outside), "examples": outside[:8], "caption_px": capsz}
    q["screen_size"] = {"frame0_screen_width_px": round(fl[0]["window_quad"][1][0] - fl[0]["window_quad"][0][0], 1),
                        "frame0_fraction_of_width": round((fl[0]["window_quad"][1][0] - fl[0]["window_quad"][0][0]) / W, 3),
                        "max_abs_yaw_deg": round(max(abs(f["pose"]["yaw"]) for f in fl), 2)}
    # pixels: the on-screen UI vs the source frame (un-project a face-on frame)
    cand = [f for f in fl if f["i"] in saved and not f.get("flash") and not any(
        b["role"] == "ripple" for b in f["texts"])]
    fsel = min(cand, key=lambda f: (abs(f["pose"]["yaw"]) + abs(f["pose"]["pitch"]) * 0.5))
    img = cv2.cvtColor(cv2.imread(str(run / "frames_png" / f"f{fsel['i']:04d}.png")), cv2.COLOR_BGR2RGB)
    vp = R["window"]["v_plinth"]
    sc = 0.5
    dw, dh = int(SRC_W * sc), int(vp * sc)
    Hm = cv2.getPerspectiveTransform(np.float32(fsel["window_quad"]), np.float32([[0, 0], [dw, 0], [dw, dh], [0, dh]]))
    warped = cv2.warpPerspective(img, Hm, (dw, dh), flags=cv2.INTER_AREA).astype(np.float32)
    srcf = take_out / "frames" / f"{fsel['src']:05d}.png"
    src = np.asarray(Image.open(srcf).convert("RGB"))[:int(vp)]
    src = cv2.resize(src, (dw, dh), interpolation=cv2.INTER_AREA).astype(np.float32)
    inside = cv2.warpPerspective(np.full(img.shape[:2], 255, np.uint8), Hm, (dw, dh), flags=cv2.INTER_NEAREST)
    m = cv2.erode(inside, np.ones((5, 5), np.uint8)) == 255          # only the part of the screen that is in frame
    r_ = int(R["phone"]["screen_radius"] * 1000 * sc) + 4
    m[:r_, :r_] = m[:r_, -r_:] = False
    m[:3, :] = m[-3:, :] = m[:, :3] = m[:, -3:] = False
    diff = (warped - src)[m]
    q["pixel_check"] = {"frame": fsel["i"], "t": round(fsel["i"] / FPS, 3), "yaw": round(fsel["pose"]["yaw"], 2),
                        "pitch": round(fsel["pose"]["pitch"], 2), "source_frame": fsel["src"],
                        "compared_at_px": [dw, dh], "pixels_compared": int(m.sum()),
                        "mean_abs_diff": round(float(np.abs(diff).mean()), 2),
                        "mean_signed_diff_rgb": [round(float(x), 2) for x in diff.reshape(-1, 3).mean(axis=0)],
                        "p99_abs_diff": round(float(np.percentile(np.abs(diff), 99)), 1),
                        "psnr_db": round(10 * math.log10(255 ** 2 / max(float((diff ** 2).mean()), 1e-9)), 2),
                        "note": "rendered PNG un-projected with the frame's own screen quad, vs the source frame "
                                "area-resampled to the same size; residual = resampling + edge AA"}
    Image.fromarray(np.concatenate([warped, src], axis=1).astype(np.uint8)).save(run / "qa_pixel_pair.png")
    # loop: frame 0 vs the last frame
    f0 = np.asarray(Image.open(run / "frames_png" / "f0000.png").convert("RGB")).astype(np.float32)
    fl_ = np.asarray(Image.open(run / "frames_png" / f"f{len(fl) - 1:04d}.png").convert("RGB")).astype(np.float32)
    blur = lambda x: cv2.GaussianBlur(x, (0, 0), 3)  # noqa: E731
    pose0, posel = fl[0]["pose"], fl[-1]["pose"]
    tail_src = [trk["src_s"][i] for i in range(len(fl)) if i / FPS >= T["t_show_end"]]
    q["loop"] = {"first_vs_last_mean_abs_diff": round(float(np.abs(f0 - fl_).mean()), 2),
                 "blurred_psnr_db": round(10 * math.log10(255 ** 2 / max(float(((blur(f0) - blur(fl_)) ** 2).mean()), 1e-9)), 2),
                 "pose_delta": {k: round(posel[k] - pose0[k], 4) for k in ("s", "yaw", "pitch", "fx", "fy", "uf")},
                 "screen_state": {"first": "the hook draw-on at app time %.3f s (lines drawing)" % trk["loop_seam"]["frame0_app_s"],
                                  "last": "the last real Show's draw-on at app time %.3f s" % trk["loop_seam"]["last_frame_app_s"]},
                 "seam_app_step_s": round(trk["loop_seam"]["frame0_app_s"] - trk["loop_seam"]["last_frame_app_s"], 4),
                 "source_frame_s": trk["loop_seam"]["source_frame_s"],
                 "last_show_tap_s": T["t_show_end"], "frames_after_last_tap": len(tail_src),
                 "ripple_on_last_frame": any(b["role"] == "ripple" for b in fl[-1]["texts"]),
                 "note": "the last frame is the last real Show's draw-on one source frame before frame 0's point in "
                         "the hook draw-on: the seam is the line continuing to grow"}
    # real UI change on screen (from the track), visual changes overall
    tk_ts = np.array([f[1] - tk["t0_wall"] for f in tk["frames"]])
    idx = trk["src_idx"]
    ui = []
    win_small = None
    prev = None
    for i, k in enumerate(idx):
        if prev is not None and k != prev:
            a_ = small(take_out / "frames" / f"{tk['frames'][prev][0]:05d}.png")
            b_ = small(take_out / "frames" / f"{tk['frames'][k][0]:05d}.png")
            vrows = int(R["window"]["v_plinth"] / DPR)
            dd = float(np.abs(a_[:vrows] - b_[:vrows]).max())
            if dd > 30:
                ui.append(round(i / FPS, 3))
        prev = k
    runs_, longest, at = [], 0.0, 0.0
    pts = [0.0] + ui + [dur]
    for x0, x1 in zip(pts, pts[1:]):
        if x1 - x0 > longest:
            longest, at = x1 - x0, x0
    after_hook = [t for t in ui if t > 1.5]
    small_v = F.decode_all_small(final)
    dv = np.abs(np.diff(small_v, axis=0)).mean(axis=(1, 2))
    still = dv < 0.35
    lg, cur, st = 0, 0, 0
    for i, s_ in enumerate(still):
        cur = cur + 1 if s_ else 0
        if cur > lg:
            lg, st = cur, i - cur + 1
    q["changes"] = {"real_ui_change_frames": len(ui), "first_ui_change_s": ui[0] if ui else None,
                    "first_ui_change_after_hook_s": after_hook[0] if after_hook else None,
                    "first_real_tap_s": T["t_hide"],
                    "longest_without_real_ui_change_s": round(longest, 3), "from_s": round(at, 3),
                    "pixel_longest_still_s": round(lg / FPS, 3), "pixel_still_from_s": round(st / FPS, 3),
                    "camera_keyframes": len(R["cam"]), "captions": len(R["captions"]), "taps": len(R["taps"]),
                    "events": sorted([(0.0, "draw-on (hook, 0.5x) + beams"), (T["hook_label"], "label pops: light event"),
                                      (T["hook_out"], "push toward the banner"),
                                      (T["t_hide"], "real tap: Hide"), (T["t_show"], "real tap: Show (0.5x draw-on, glide)"),
                                      (T["impact"], "label pops: the impact + rim light + beam flare"),
                                      (T["t_hide_b"], "real tap: Hide"), (T["t_show_b"], "real tap: Show (real speed)"),
                                      (T["shape"], "push to the app's words"), (T["label_b"], "label pops on 'prediction'"),
                                      (T["brand_big"], "pull back, pill grows, URL"),
                                      (T["t_hide_end"], "real tap: Hide"), (T["t_show_end"], "real tap: Show (loop, 0.5x)")])}
    # words
    script = [ln["say"] for ln in lines] + [c["show"] for ln in lines for c in ln["chunks"]] + R["text"]["headline"] + \
        [R["text"]["site"], R["text"]["disclaimer"]]
    extra = (res["ticker"], res.get("tile", {}).get("company_name", "") or res["ticker"])
    if not res.get("chip", "").lower().startswith("confirmed"):
        extra += ("confirmed",)
    q["banned_scan"] = {"script_problems": text_problems(script, extra),
                        "youtube_problems": text_problems([ep["youtube"]["title"], ep["youtube"]["description"]], extra),
                        "lines_checked": len(script) + 2, "also_banned_today": list(extra)}
    # hero framing (every frame): banner, its control, its words and the chart whole inside the safe zone
    fp = framing_problems(fl)
    q["hero_gate"] = {"frames": len(fl), "rects": sorted({h["id"] for h in R["hero"]}), "zone": SAFE,
                      "outside": len(fp["hero_outside"]), "examples": fp["hero_outside"][:8],
                      "app_ui_min_x": round(min(min(p[0] for p in h["quad"]) for f in fl for h in f["hero"] if not h.get("zone")), 1),
                      "app_ui_max_x": round(max(max(p[0] for p in h["quad"]) for f in fl for h in f["hero"] if not h.get("zone")), 1),
                      "phone_body_x": [round(min(min(p[0] for p in h["quad"]) for f in fl for h in f["hero"] if h.get("zone") and not (h.get("skip_t") and h["skip_t"][0] <= f["t"] <= h["skip_t"][1])), 1),
                                       round(max(max(p[0] for p in h["quad"]) for f in fl for h in f["hero"] if h.get("zone") and not (h.get("skip_t") and h["skip_t"][0] <= f["t"] <= h["skip_t"][1])), 1)],
                      "phone_body_may_leave_frame_s": next((h.get("skip_t") for h in R["hero"] if h.get("skip_t")), None)}
    # the pre-impact silence, measured on the final file
    sd = subprocess.run([str(FFMPEG), "-hide_banner", "-i", str(final), "-af", "silencedetect=n=-35dB:d=0.25", "-f",
                         "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    st_ = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", sd.stderr)]
    en_ = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", sd.stderr)]
    spans = [(a_, b_) for a_, b_ in zip(st_, en_)]
    q["silence"] = {"detector": "ffmpeg silencedetect n=-35dB d=0.25", "spans": spans, "impact_s": T["impact"],
                    "pre_impact": [sp for sp in spans if sp[0] <= T["impact"] - 0.2 and sp[1] >= T["impact"] - 0.06]}
    last_roles = {b["role"] for b in fl[-1]["texts"]}
    q["end_card"] = {"last_frame_roles": sorted(last_roles)}
    br_margin = round(br[-1] - (dur - 4.0), 3) if br else None
    q["brand_word"]["last_inside_final_4s_by_s"] = br_margin
    dmin, dmax = ep.get("duration_s", [16.0, 20.0])
    hold = ep["timing"].get("max_hold_s", 2.6)
    gates = {
        "duration_in_range": dmin <= dur <= dmax + 0.05,
        "fps_30": abs(q["fps"] - 30) < 0.01,
        "size_1080x1920": q["size"] == [1080, 1920],
        "file_under_25mb": q["file_mb"] < 25,
        "lufs_-14": abs(ld["integrated_lufs"] + 14) <= 0.6,
        "true_peak_le_-1": ld["true_peak_dbtp"] <= -1.0,
        "brand_spoken_before_4s": bool(br) and br[0] < 4.0,
        "brand_spoken_in_last_4s_margin_0_3": br_margin is not None and br_margin >= 0.3,
        "pill_every_sample": q["brand_pill"]["detected"] == q["brand_pill"]["sampled"],
        "pill_ge_70px": q["brand_pill"]["pill_height_px"][0] >= 70,
        "pill_ge_1_5x_logo": (q["brand_pill"]["min_pill_over_logo"] or 0) >= 1.5,
        "hero_whole_in_safe_zone": not fp["hero_outside"],
        "pre_impact_silence": bool(q["silence"]["pre_impact"]),
        "url_and_disclaimer_on_last_frame": {"end_site", "end_disclaimer"} <= last_roles,
        "no_take_warnings": not best["warnings"],
        "real_ui_change_every_%gs" % hold: q["changes"]["longest_without_real_ui_change_s"] <= hold,
        "loop_seam_one_source_frame": 0 < q["loop"]["seam_app_step_s"] <= 2.5 * SRC_FRAME_S,
        "no_ripple_on_last_frame": not q["loop"]["ripple_on_last_frame"],
        "slow_speeds_0_5_0_6": all(0.49 <= x["speed"] <= 0.61 for x in trk["slow"]["segments"]),
        "real_speeds_1_00_1_03": 0.985 <= trk["real_speed_range"][0] and trk["real_speed_range"][1] <= 1.035,
        "keepout_none_visible": q["keepout_gate"]["visible_hits"] == 0,
        "ocr_clean": not hits,
        "page_text_clean": not page_hits,
        "no_overlay_on_screen": not over,
        "text_in_safe_zone": not outside,
        "captions_ge_84px": bool(capsz) and min(capsz) >= 84,
        "screen_ge_70pct_width_frame0": q["screen_size"]["frame0_fraction_of_width"] >= 0.70,
        "yaw_le_7": q["screen_size"]["max_abs_yaw_deg"] <= 7.0,
        "speech_from_0": allw[0]["t0"] <= 0.12,
        "speech_gaps_ok": all(g["pre_impact_silence"] for g in q["speech_gaps_over_0_25s"]),
        "words_per_s_2_7_3_0": 2.65 <= q["words_per_s"] <= 3.05,
        "first_real_tap_le_4_2": T["t_hide"] <= 4.2,
        "no_banned_words": not q["banned_scan"]["script_problems"] and not q["banned_scan"]["youtube_problems"],
        "no_interpolated_frames": trk["slow"]["interpolated_frames"] == 0,
        "pixel_match_psnr_ge_30": q["pixel_check"]["psnr_db"] >= 30,
        "pixel_bias_le_2": max(abs(x) for x in q["pixel_check"]["mean_signed_diff_rgb"]) <= 2.0,
        "pixel_still_le_2s": q["changes"]["pixel_longest_still_s"] <= 2.0,
    }
    q["gates"] = {k: bool(v) for k, v in gates.items()}
    q["pass"] = all(q["gates"].values())
    exc = ep.get("duration_exception")
    if exc and not q["gates"]["duration_in_range"]:
        q["exceptions_for_lead"] = {"duration_in_range": {"range": [dmin, dmax], "duration_s": q["duration_s"], **exc}}
        q["pass_except_lead_exceptions"] = all(v for k, v in q["gates"].items() if k != "duration_in_range")
    return q


if __name__ == "__main__":
    sys.exit(main())
