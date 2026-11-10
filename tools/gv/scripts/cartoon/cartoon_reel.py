"""Cartoon-story Reel renderer: a story script (story.json) + today's facts item + real RapidTradeView screenshots -> a 9:16
Reel with flat cartoon characters, a camera that never stops, word-by-word captions on a local TTS voice, and the real
screen as the payoff. Runs in the project conda env (PIL + numpy); the voice runs in its own venv.

Format v3 (owner verdict 2026-11-09: "the pilot short is too complicated and it isnt clear what brand behind it"): ONE
situation, ONE punchline, 15-22 s, at most 7 shots, no side gags; the RapidTradeView pill is on screen from frame 0 to the
last frame (a layer drawn over every frame, transitions included); the voice says RapidTradeView in the first 5 s and in
the last 5 s; the payoff is our real page with its own header and logo. make_story.py writes the story from a facts item.
v4: nothing that stays on screen sits under the pill (pill_clear gate: real cards keep below it, header flies off before
the zoom); the end card keeps out of the right 12% (end_card_safe) and keeps moving (wordmark pulse, head bob).
Feature shorts (owner verdict 2026-11-10: "they arent good, only the last one show the visuals correctly as it shown on
website"): the payoff is a SITE SCREEN, els "site": one window that shows a strip of the real page at phone width, the
card whole and about 1000 px wide, scrolled like a thumb when it is taller than the stage, the key outlined where it
stands, the captions in a band under the window. Gates site_card_whole, card_width, no_overlap, key_in_place; the run
folder also gets compare.png (the site capture beside the video frames, at one scale).

    cartoon_reel.py --story STORY.json --out DIR [--ffmpeg-dir DIR] [--tts-python PY] [--sheet-every 1.5]

Inputs (story.json, schema rtv-cartoon-story/1; SKILL.md in this folder says how to write one):
  item_id, facts_file           the facts item (its numbers, phrasings and banned words gate every text)
  feature                       instead of facts_file, a FEATURE short (make_feature_story.py): {"id": a features.json id,
                                "values": the values read from the captures}. The item is then built from the capture
                                sidecars at render time (cartoon_qa.feature_item): every number and name must be on a
                                capture made today, and the story must be exactly the one make_feature_story writes from
                                the registry and those sidecars (lines, say map, crops, outline: story_drift)
  fact_phrase                   the ONE data sentence, verbatim one of the item's own phrasings; read aloud, or shown whole
                                on a receipt card (els "receipt", text "$fact_phrase") for at least RECEIPT_MIN_S
  post_date                     YYYY-MM-DD the video goes out (a story-time weekday must be this day's weekday)
  voices                        {"narrator": {"id", "speed"}, "<role>": {...}} Kokoro voice ids (local, Apache-2.0)
  say                           display word -> spoken form ("$14.99M" -> "fourteen point nine nine million dollars")
  screens                       {"name": "<capture png>"}: each with its capture.py sidecar (<png>.json)
  screen_numbers_ack            {screen name: {number: why it is there}} for numbers on a screenshot that are not item numbers
  shots                         the shot list (kind, set, els, move, vo, voice, claim, bubble, chip, peek, ...), last one END
                                (a voiced shot may carry "lead": seconds of picture before its first word)
                                (a shot whose vo states a fact carries "claim": the phrasing id it paraphrases)

Outputs in DIR: reel_9x16.mp4 (1080x1920, 30 fps, H.264 + AAC), reel.json (provenance: item, numbers, voice engine and
licence, music samples, screenshot and file sha256, screen crops, shot list, and claims_for_human_check: the story lines
that paraphrase a fact, for a person to read), reel-qa.json (pass, summary, details), sheet.png (a frame
every 1.5 s), vo.wav / mix.wav. Exit 0 = every QA gate passed, 1 = a QA gate failed, 2 = unusable input or a render error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "v6cat"))
sys.path.insert(0, str(HERE))
import cartoon_qa as Q  # noqa: E402
import cast as C  # noqa: E402
import vsco_score  # noqa: E402

cr = Q.cr                                 # the v6cat card-Reel renderer (encode, fonts, pill, sweep, gates)

RENDERER = "rtv-cartoon-reel/1"
W, H, FPS = cr.W, cr.H, cr.FPS
O = np.array([W / 2, H / 2])
MARGIN = (162, 288)                       # the world canvas is 1404 x 2496: 1.3x the frame, centred on it
CANVAS = (W + 2 * MARGIN[0], H + 2 * MARGIN[1])
SR = vsco_score.SR
END_S = 3.0
DURATION_RANGE = Q.ONE_IDEA_DURATION       # 15-22 s (v3: one situation, one punchline)
SHOT_RANGE = (0.7, 2.6)
HOOK_MAX = 3.0          # the hook carries the voiced number; a longer figure ('$0.20' read out) runs ~2.7 s (2026-11-10 KKR)
PAYOFF_MAX = 4.5                          # v3: the payoff holds our real page (brand + fact), the one place to linger
PAYOFF_MAX_SITE = 5.0                     # a site screen shot: the top of the card, then a thumb scroll to its end
SHOTS_RANGE = (4, Q.ONE_IDEA_MAX_SHOTS)   # at most 7 shots
LUFS_RANGE, TP_MAX, TARGET_LUFS = (-15.0, -13.0), -1.0, -14.0
STATIC_MAD, STATIC_RUN = 0.3, 8
CAPTION_SIZE, CAPTION_MIN, CAPTION_MAX_W = 92, 72, 760
CAPTION_Y = 1230                          # ONE caption band (64% of the height) for every shot; frame the shots around it
SPEAKER_COL = {"dale": (255, 178, 158), "pip": (160, 242, 208)}   # caption colour per voice (narrator white)
PAYOFF_WINDOW = (2.0, 8.0)                # first PAYOFF start -> last PAYOFF end, reaction cut-ins included
PAYOFF_WINDOW_SITE = (2.0, 9.5)           # a site screen: the scroll over the real card and the outlined key
SITE_RIM, SITE_RADIUS = 5, 34             # the window's brand-gradient rim and its corner radius (frame px)
SCROLL_TICK_S = 0.6                       # one soft run of scroll ticks per this much scrolling
SCREEN_MIN_S = 1.8                        # the real screenshot is on screen at least this long
RECEIPT_MIN_S = 1.8                       # a fact phrase shown (not read) stays on screen at least this long
CHAR_GAP_MAX = 2.0                        # a character is never off screen for longer than this
HOOK_NUMBER_BY = 2.5                      # an item number is on screen (caption or chip) by this time
HOOK_CHAR_W = 0.5                         # frame 0: a character at least this share of the frame width
LEAD_F = 2                                # the picture cuts 2 frames before the first word of its line
SEARCH_TEXT = "Search RapidTradeView"
END_TEXTS = (cr.BRAND, SEARCH_TEXT, cr.SITE, cr.DISCLAIMER)
BRAND_PILL_SIZE = 40                      # the persistent brand pill (card_reel.pill): top-left, under the platform's
BRAND_PILL_XY = (54, 262)                 # top bar (SAFE_TOP 250), far from the bottom 18% and the right 12% (IG/YT UI)
BRAND_SWEEP_EVERY = 4.0                   # a light sweep crosses the pill every 4 s (a little life, never a fade)
END_BRAND_SIZE = 68                       # the end card's wordmark (~740 px): with its pop and pulse it stays left of x 950
END_PULSE = 0.035                         # the wordmark's pulse after the search has typed (the end card never freezes)
RIGHT_BAND_X = 0.88 * 1080                # the right ~12% is under the IG/YT action rail: no brand text there
LIME, CYANC, GREEN, RED = C.LIME, (56, 225, 245), (52, 211, 120), (248, 92, 92)
BUBBLE_FILL = {"lime": C.LIME, "cyan": C.CYAN, "white": (255, 255, 255)}
font = cr.font


class InputError(Exception):
    pass


def ease_out(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def eob(x, s=1.7):
    x = min(1.0, max(0.0, x))
    return cr.ease_out_back(x, s)


def lerp(a, b, u):
    return a + (b - a) * u


def cruise(x, a=0.15):
    """A thumb scroll's progress 0..1: it speeds up over the first `a`, runs at one speed, slows over the last `a` (the
    peak speed is 1 / (1 - a) of the average: a smoothstep's 1.5x blurs a tall page past the eye)."""
    x = min(1.0, max(0.0, x))
    v = 1.0 / (1.0 - a)
    if x < a:
        return v * x * x / (2 * a)
    if x > 1 - a:
        return 1.0 - v * (1 - x) * (1 - x) / (2 * a)
    return v * (x - a / 2)


def interp(v, u):
    """A number, or [a, b] interpolated over the shot (u = 0..1)."""
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return lerp(v[0], v[1], u)
    return v


def rot(a_deg):
    a = math.radians(a_deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s], [s, c]])


def ops_dir() -> Path:
    env = os.environ.get("RTV_OPS_DIR")
    if env:
        return Path(env)
    for p in HERE.parents:
        if (p / ".ops" / "cache").is_dir():
            return p / ".ops"
    raise InputError("no .ops/cache folder above the renderer (set RTV_OPS_DIR)")


# =============================================================================================== story + timeline
class Story:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise InputError(f"story unreadable ({type(e).__name__}: {e})") from e
        d = self.doc
        self.feature = None                # a FEATURE short: the registry entry; its item comes from the captures
        for k in ("item_id", "fact_phrase", "shots", "screens") + (() if d.get("feature") else ("facts_file",)):
            if k not in d:
                raise InputError(f"story has no {k}")
        if not d.get("feature"):
            ff = Path(d["facts_file"])
            if not ff.is_absolute():
                ff = (path.parent / ff).resolve()
            try:
                facts = json.loads(ff.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as e:
                raise InputError(f"facts file unreadable: {ff} ({type(e).__name__})") from e
            self.item = next((i for i in facts.get("items", []) if i.get("item_id") == d["item_id"]), None)
            if not self.item:
                raise InputError(f"item {d['item_id']} not in {ff}")
            self.facts_path = ff
            self.banned = [w for w in (facts.get("rules") or {}).get("banned_words") or [] if isinstance(w, str)]
            self.banned += [w for w in self.item.get("banned_words") or [] if isinstance(w, str)]
        self.say = dict(d.get("say") or {})
        self.voices = d.get("voices") or {"narrator": {"id": "af_heart", "speed": 1.0}}
        self.shots = d["shots"]
        if not self.shots or self.shots[-1].get("kind") != "END":
            raise InputError("the last shot must be kind END")
        self.screens = {}
        for name, p in d["screens"].items():
            png = Path(p)
            if not png.is_absolute():
                png = (path.parent / png).resolve()
            side = png.with_suffix(".json")
            if not png.is_file() or not side.is_file():
                raise InputError(f"screen {name}: {png} or its sidecar is missing (capture it with capture.py)")
            meta = json.loads(side.read_text(encoding="utf-8"))
            with Image.open(png) as im:
                fmt, size = im.format, im.size
                img = im.convert("RGB")
            self.screens[name] = {"png": png, "img": img, "meta": meta, "fmt": fmt, "size": size}
        if d.get("feature"):
            self._feature_item(d)
        ack = d.get("screen_numbers_ack") or {}
        if not isinstance(ack, dict) or any(not isinstance(v, dict) for v in ack.values()) or set(ack) - set(self.screens):
            raise InputError("screen_numbers_ack must be {screen name: {number: reason}} (one entry per screen in `screens`)")
        self.ack = {n: ack.get(n, {}) for n in self.screens}
        self.post_date = d.get("post_date")
        if self.post_date:
            try:
                dt.date.fromisoformat(str(self.post_date))
            except ValueError as e:
                raise InputError(f"post_date {self.post_date!r} is not YYYY-MM-DD") from e


    def _feature_item(self, d: dict) -> None:
        """A FEATURE short: the registry entry and the item built from the capture sidecars (never from the story)."""
        try:
            reg = Q.load_features()
            self.feature = Q.feature_by_id(reg, str((d["feature"] or {}).get("id")))
            metas = {n: sc["meta"] for n, sc in self.screens.items()}
            day = Q.capture_day(metas)
            if not str(d["item_id"]).startswith(day):
                raise Q.FeatureError(f"item_id {d['item_id']} does not start with the capture day {day}")
            vals = Q.feature_values(self.feature, metas)
            self.item = Q.feature_item(self.feature, vals, metas, d["item_id"])
        except Q.FeatureError as e:
            raise InputError(f"feature story: {e}") from e
        self.facts_path = Path(reg["_path"])
        self.banned = [w for w in reg.get("banned_words") or [] if isinstance(w, str)]


class Word:
    __slots__ = ("text", "start", "end", "shot", "idx")

    def __init__(self, text, start, end, shot, idx):
        self.text, self.start, self.end, self.shot, self.idx = text, start, end, shot, idx


def run_tts(story: Story, utts: list[dict], work: Path, tts_python: str) -> None:
    """Every utterance through the local Kokoro CLI (one model load); cached by text + voice + speed."""
    jobs = []
    for u in utts:
        v = story.voices.get(u["voice"]) or {}
        vid, speed = v.get("id", "af_heart"), float(v.get("speed", 1.0))
        key = hashlib.sha256(json.dumps([u["spoken"], vid, speed]).encode()).hexdigest()[:16]
        u.update(voice_id=vid, speed=speed, wav=work / f"{key}.wav", timings=work / f"{key}.json")
        if not (u["wav"].is_file() and u["timings"].is_file()):
            jobs.append({"text": u["spoken"], "voice": vid, "speed": speed, "out": str(u["wav"]), "timings": str(u["timings"])})
    if jobs:
        work.mkdir(parents=True, exist_ok=True)
        jf = work / "jobs.json"
        jf.write_text(json.dumps(jobs, indent=1), encoding="utf-8")
        r = subprocess.run([tts_python, "-I", str(HERE / "tts.py"), "--batch", str(jf)], capture_output=True, text=True)
        if r.returncode != 0:
            raise InputError(f"TTS failed: {r.stderr.strip()[-600:]}")


def read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        x = np.frombuffer(w.readframes(n), "<i2").astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    return x, sr


def voiced_end(x: np.ndarray, sr: int) -> float:
    """The end of the last voiced 20 ms window (-42 dBFS)."""
    win = int(0.02 * sr)
    n = len(x) // win
    if n == 0:
        return len(x) / sr
    rms = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(1))
    on = np.nonzero(rms > 10 ** (-42 / 20))[0]
    return ((on[-1] + 1) * win / sr) if len(on) else len(x) / sr


class Timeline:
    """Utterances -> word times -> shot cuts -> caption chunks."""

    def __init__(self, story: Story, work: Path, tts_python: str):
        self.story = story
        shots = story.shots
        self.utts: list[dict] = []
        for i, sh in enumerate(shots):
            vo = (sh.get("vo") or "").strip()
            if not vo:
                continue
            words = vo.split()
            say = {**story.say, **(sh.get("say") or {})}
            sp = Q.spoken_tokens(words, say)
            if sh.get("join") and self.utts and self.utts[-1]["shots"][-1] == i - 1:
                u = self.utts[-1]
                base = len(u["words"])
                u["words"] += [(i, w) for w in words]
                u["sp"] += [(base + k, t) for k, t in sp]
                u["shots"].append(i)
            else:
                self.utts.append({"voice": sh.get("voice", "narrator"), "words": [(i, w) for w in words],
                                  "sp": list(sp), "shots": [i]})
        for u in self.utts:
            u["spoken"] = " ".join(t for _, t in u["sp"])
        run_tts(story, self.utts, work, tts_python)
        # place the utterances
        t = 0.05
        self.words: list[Word] = []
        self.shot_start: dict[int, float] = {}
        self.vo_clips: list[tuple[float, np.ndarray]] = []
        n = len(shots)
        cursor_shot = 0
        end_i = n - 1
        for ui, u in enumerate(self.utts):
            first_shot = u["shots"][0]
            # silent shots before this utterance (dur only)
            while cursor_shot < first_shot:
                sh = shots[cursor_shot]
                if cursor_shot not in self.shot_start:
                    self.shot_start[cursor_shot] = t
                    t += float(sh.get("dur", 1.2))
                cursor_shot += 1
            if first_shot == end_i:
                t = max(t, self.shot_start.get(end_i, t))
                self.shot_start.setdefault(end_i, t)
                t = self.shot_start[end_i] + float(shots[end_i].get("vo_at", 0.25))
            # "lead": a silent beat at the head of the shot (the key lands and the camera settles, then the line names it)
            lead_in = float(shots[first_shot].get("lead", 0.0)) if first_shot != end_i else 0.0
            t += lead_in
            x, sr = read_wav_mono(u["wav"])
            tw = json.loads(Path(u["timings"]).read_text(encoding="utf-8"))
            if not tw:
                raise InputError(f"TTS gave no word timings for {u['spoken']!r}")
            spans = Q.align([s for _, s in u["sp"]], tw)
            lead = max(0.0, float(tw[0]["start"]) - 0.03)
            vend = voiced_end(x, sr)
            clip = x[int(lead * sr): int(min(len(x) / sr, vend + 0.12) * sr)]
            t0 = t - 0.03                          # the clip's first sample (first word at t)
            self.vo_clips.append((t0, self._to48(clip, sr), u))
            per_word: dict[int, list[tuple[float, float]]] = {}
            for (wi, _), sp_ in zip(u["sp"], spans):
                per_word.setdefault(wi, []).append(sp_)
            for wi, (si, wtext) in enumerate(u["words"]):
                spn = per_word.get(wi) or [(spans[0][0], spans[0][0])]
                ws = min(a for a, _ in spn) - lead + t0
                we = min(max(b for _, b in spn), vend) - lead + t0     # a sentence-final word's end includes the pause
                self.words.append(Word(wtext, ws, we, si, wi))
            for si in u["shots"]:
                if si == end_i:
                    continue
                if si not in self.shot_start:
                    fw = next(w for w in self.words if w.shot == si)
                    back = LEAD_F / FPS + (lead_in if si == first_shot else 0.0)
                    self.shot_start[si] = 0.0 if si == 0 else max(fw.start - back, 0.0)
            last_shot = u["shots"][-1]
            t = t0 + (vend - lead) + float(shots[last_shot].get("pause", 0.12)) + float(shots[last_shot].get("hold", 0.0))
            # enforce the shot minimum on the utterance's last shot
            st = self.shot_start.get(last_shot, t)
            if last_shot != end_i and t - st < SHOT_RANGE[0]:
                t = st + SHOT_RANGE[0]
            if last_shot != end_i and shots[last_shot].get("min_dur"):      # a scroll that outlasts the shot's line
                t = max(t, st + float(shots[last_shot]["min_dur"]) + LEAD_F / FPS)   # (the next shot cuts in LEAD_F early)
            cursor_shot = last_shot + 1
        while cursor_shot < end_i:
            self.shot_start.setdefault(cursor_shot, t)
            t = self.shot_start[cursor_shot] + float(shots[cursor_shot].get("dur", 1.2))
            cursor_shot += 1
        if end_i not in self.shot_start:
            self.shot_start[end_i] = t
        # frames
        starts = [round(self.shot_start[i] * FPS) / FPS for i in range(n)]
        starts[0] = 0.0
        self.starts = starts
        self.end_start = starts[end_i]
        self.total = self.end_start + END_S
        self.frames = int(round(self.total * FPS))
        self.ends = starts[1:] + [self.total]
        self.end_vo_finish = max((w.end for w in self.words if w.shot == end_i), default=self.end_start) - self.end_start
        self._captions()

    @staticmethod
    def _to48(x: np.ndarray, sr: int) -> np.ndarray:
        if sr == SR:
            return x
        n = int(round(len(x) * SR / sr))
        return np.interp(np.arange(n) * sr / SR, np.arange(len(x)), x)

    def shot_at(self, t: float) -> int:
        i = 0
        for k, s in enumerate(self.starts):
            if s <= t + 1e-9:
                i = k
        return i

    def _captions(self):
        """Caption chunks per shot (never across a cut) with their on/off times."""
        f = font("black", CAPTION_MIN)
        self.chunks: list[dict] = []
        end_i = len(self.story.shots) - 1
        by_shot: dict[int, list[Word]] = {}
        for w in self.words:
            if w.shot != end_i:
                by_shot.setdefault(w.shot, []).append(w)
        for si in sorted(by_shot):
            ws = by_shot[si]
            cap = self.story.shots[si].get("caption") or {}       # a shot's own caption band (the site screen's is narrower)
            groups = Q.chunk_words([w.text for w in ws], measure=lambda s: f.getlength(" ".join(Q.display_words(s))),
                                   max_px=float(cap.get("max_w", CAPTION_MAX_W)))
            voice = self.story.shots[si].get("voice", "narrator")
            for g in groups:
                text = " ".join(Q.display_words(" ".join(ws[k].text for k in g)))
                if not text:
                    continue
                self.chunks.append({"shot": si, "text": text, "voice": voice, "start": ws[g[0]].start - 1 / FPS,
                                    "w_start": ws[g[0]].start, "last_end": ws[g[-1]].end})
        if self.chunks and self.chunks[0]["shot"] == 0:
            self.chunks[0]["start"] = 0.0             # the hook: caption chunk 1 is on frame 0
        for k, c in enumerate(self.chunks):
            nxt = self.chunks[k + 1]["start"] if k + 1 < len(self.chunks) else self.end_start
            stop = nxt
            if nxt - c["last_end"] > 0.8:
                stop = c["last_end"] + 0.4
            c["end"] = min(stop, self.end_start)


# =============================================================================================== drawing helpers
def caption_sprite(text: str, stress: set[str], base=(255, 255, 255), size: int = CAPTION_SIZE,
                   max_w: float = CAPTION_MAX_W) -> Image.Image:
    words = text.split()
    while size > CAPTION_MIN and font("black", size).getlength(text) - 2 * (len(words) - 1) > max_w:
        size -= 4
    f = font("black", size)
    sw = 7
    total = f.getlength(text) - 2 * (len(words) - 1)
    asc, desc = f.getmetrics()
    img = Image.new("RGBA", (int(total + 2 * sw + 40), asc + desc + 2 * sw + 30), C.CLEAR)
    d = ImageDraw.Draw(img)
    x = sw + 20
    cols = []
    for w in words:
        core = w.strip('().,:;"!?')
        i = len(cols)
        nxt = words[i + 1] if i + 1 < len(words) else ""
        prev = words[i - 1] if i else ""
        is_date_month = re.fullmatch(r"\(?" + Q.MONTHS, w) and nxt[:1].isdigit()
        if Q.FIGURE_RX.search(w) or is_date_month or (re.search(r"\d", w) and not re.fullmatch(r"\(?Form", prev)):
            col = CYANC
        elif re.fullmatch(r"(?i)bought|buys?|purchased?|beat", core):
            col = GREEN
        elif re.fullmatch(r"(?i)sold|sells?|sale|miss(ed)?", core):
            col = RED
        elif w in stress or core in stress:
            col = LIME
        else:
            col = base
        cols.append(col)
    shadow = Image.new("L", img.size, 0)
    sd = ImageDraw.Draw(shadow)
    xs = []
    for w in words:
        xs.append(x)
        sd.text((x, sw + 15 + 6), w, font=f, fill=140, stroke_width=sw, stroke_fill=140, anchor="la")
        x += f.getlength(w + " ") - 2
    shadow = shadow.filter(ImageFilter.GaussianBlur(4))
    sh_img = Image.new("RGBA", img.size, C.INK + (0,))
    sh_img.putalpha(shadow)
    img.alpha_composite(sh_img)
    for w, xx, col in zip(words, xs, cols):
        d.text((xx, sw + 15), w, font=f, fill=col + (255,), stroke_width=sw, stroke_fill=C.INK + (255,), anchor="la")
    bb = img.getbbox() or (0, 0, 1, 1)
    return img.crop(bb)


def blit(frame: Image.Image, img: Image.Image, A: np.ndarray, b: np.ndarray, alpha: float = 1.0) -> None:
    """Draw RGBA `img` onto `frame` where sprite pixel u lands at A @ u + b (screen px)."""
    if alpha <= 0.004:
        return
    w, h = img.size
    corners = np.array([[0, 0], [w, 0], [0, h], [w, h]], float) @ A.T + b
    x0, y0 = np.floor(corners.min(0)).astype(int)
    x1, y1 = np.ceil(corners.max(0)).astype(int)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return
    Ai = np.linalg.inv(A)
    off = Ai @ (np.array([x0, y0], float) - b)
    data = (Ai[0, 0], Ai[0, 1], off[0], Ai[1, 0], Ai[1, 1], off[1])
    scale = abs(np.linalg.det(A)) ** 0.5
    out = img.transform((x1 - x0, y1 - y0), Image.AFFINE, data, Image.BICUBIC if scale > 0.6 else Image.BILINEAR,
                        fillcolor=C.CLEAR)
    if alpha < 0.996:
        out = cr.faded(out, alpha)
    frame.alpha_composite(out, (int(x0), int(y0)))


class Cam:
    """world -> screen: p = O + s R(-th) (q - c) + d."""

    def __init__(self, s=1.0, c=(W / 2, H / 2), th=0.0, d=(0.0, 0.0)):
        self.s, self.c, self.th, self.d = s, np.array(c, float), th, np.array(d, float)

    def M(self):
        return self.s * rot(-self.th)

    def p(self, q):
        return O + self.M() @ (np.array(q, float) - self.c) + self.d

    def sprite(self, frame, img, anchor, q, rot_deg=0.0, k=1.0, res=1.0, alpha=1.0):
        A = (self.s * k / res) * rot(rot_deg - self.th)
        b = self.p(q) - A @ np.array(anchor, float)
        blit(frame, img, A, b, alpha)
        return A, b


# =============================================================================================== audio synthesis
def _bp_noise(n, f0, f1, q=2.0, seed=1):
    """White noise through a biquad band-pass sweeping f0 -> f1 (deterministic)."""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    y = np.zeros(n)
    x1 = x2 = y1 = y2 = 0.0
    fs = SR
    for i in range(n):
        f = f0 + (f1 - f0) * i / max(1, n - 1)
        w0 = 2 * math.pi * f / fs
        al = math.sin(w0) / (2 * q)
        b0, b2, a0, a1, a2 = al, -al, 1 + al, -2 * math.cos(w0), 1 - al
        yi = (b0 * x[i] + b2 * x2 - a1 * y1 - a2 * y2) / a0
        x2, x1, y2, y1 = x1, x[i], y1, yi
        y[i] = yi
    return y / (np.abs(y).max() + 1e-9)


def sfx(kind: str, seed=1) -> np.ndarray:
    t = lambda d: np.arange(int(d * SR)) / SR  # noqa: E731
    if kind == "ping":
        tt = t(0.6)
        y = (np.sin(2 * math.pi * 1760 * tt) + 0.35 * np.sin(2 * math.pi * 2637 * tt)) * np.exp(-tt / 0.18)
    elif kind == "clank":
        tt = t(0.5)
        y = sum(a * np.sin(2 * math.pi * f * tt) for f, a in ((523, 1), (1187, 0.7), (1840, 0.5), (2770, 0.35))) * np.exp(-tt / 0.12)
        y[: int(0.004 * SR)] += _bp_noise(int(0.004 * SR), 3000, 3000, 1, seed)
    elif kind == "whoosh":
        y = _bp_noise(int(0.22 * SR), 3000, 600, 1.5, seed)
        tt = t(0.22)
        y *= np.sin(np.pi * tt / 0.22) ** 1.5
    elif kind == "thump":
        tt = t(0.35)
        f = 70 + 50 * np.exp(-tt / 0.025)
        y = np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.09)
    elif kind == "clack":
        y = np.zeros(int(0.06 * SR))
        b = _bp_noise(int(0.003 * SR), 2000, 2000, 2, seed)
        y[: len(b)] = b
    elif kind == "scroll":
        y = np.zeros(int(0.6 * SR))
        for k in range(6):
            b = _bp_noise(int(0.003 * SR), 2200, 2200, 2, seed + k)
            i = int(k * 0.09 * SR)
            y[i:i + len(b)] += b * (1 - 0.1 * k)
    elif kind in ("slosh", "slurp"):
        n = int(0.45 * SR)
        y = _bp_noise(n, 500, 1400 if kind == "slurp" else 300, 3, seed)
        tt = t(0.45)
        y *= (0.6 + 0.4 * np.sin(2 * math.pi * 11 * tt)) * np.sin(np.pi * tt / 0.45)
    elif kind == "creak":
        tt = t(0.7)
        f = 95 + 25 * np.sin(2 * math.pi * 3.1 * tt) + 40 * tt
        ph = np.cumsum(f) / SR
        y = (2 * (ph % 1.0) - 1) * (0.5 + 0.5 * np.sin(2 * math.pi * 23 * tt)) * np.sin(np.pi * tt / 0.7)
    elif kind == "squish":
        n = int(0.35 * SR)
        tt = t(0.35)
        y = _bp_noise(n, 900, 200, 2, seed) * np.exp(-tt / 0.15) + 0.6 * np.sin(2 * math.pi * 90 * tt) * np.exp(-tt / 0.08)
    else:
        tt = t(0.3)
        y = np.sin(2 * math.pi * 880 * tt) * np.exp(-tt / 0.1)
    return y / (np.abs(y).max() + 1e-9)


def sfx_kind(text: str) -> str:
    s = text.lower()
    for k, kind in (("clank", "clank"), ("ding", "ping"), ("ping", "ping"), ("scroll", "scroll"), ("slosh", "slosh"),
                    ("slurp", "slurp"), ("creak", "creak"), ("creeak", "creak"), ("squish", "squish"), ("tap", "clack"),
                    ("whoosh", "whoosh"), ("thump", "thump"), ("bzzt", "creak")):
        if k in s:
            return kind
    return "ping"


def loudnorm_measure(wav: Path, ffmpeg: str) -> dict:
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(wav), "-vn", "-af",
                        "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        raise RuntimeError("loudnorm gave no measurement")
    j = json.loads(m.group(0))
    return {"I": float(j["input_i"]), "TP": float(j["input_tp"]), "LRA": float(j["input_lra"])}


def limiter(x: np.ndarray, ceil: float) -> np.ndarray:
    """A look-ahead peak limiter (5 ms blocks, smoothed gain that never exceeds the block's need)."""
    blk = 240
    n = int(math.ceil(len(x) / blk))
    pad = np.zeros((n * blk, 2))
    pad[: len(x)] = x
    pk = np.abs(pad).reshape(n, blk, 2).max(axis=(1, 2))
    g = np.minimum(1.0, ceil / np.maximum(pk, 1e-9))
    g = np.minimum.reduce([g, np.r_[g[1:], 1.0], np.r_[1.0, g[:-1]], np.r_[g[2:], 1.0, 1.0]])
    k = np.hanning(9)
    k /= k.sum()
    gs = np.convolve(np.r_[np.ones(4), g, np.ones(4)], k, "valid")
    gs = np.minimum(gs, g)
    ge = np.repeat(gs, blk)[: len(x)]
    return x * ge[:, None]


def write_wav(path: Path, mix: np.ndarray, ch=2) -> None:
    pcm = np.clip(np.round(mix * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# =============================================================================================== the renderer
class Reel:
    def __init__(self, story: Story, tl: Timeline):
        self.st, self.tl = story, tl
        self.p = self                      # card_reel.encode reads sc.p.frames
        self.frames = tl.frames
        self.shots = story.shots
        self.n = len(self.shots)
        self.cache: dict = {}
        self.bg_cache: dict = {}
        self.cap_sprites: dict[int, tuple[Image.Image, object]] = {}
        self.events: list[tuple[float, str, dict]] = []        # (t, kind, data): bubble pops, whips, lands -> shake + sfx
        self.texts: list[dict] = []                              # every text we draw: role, text, box
        self.key_samples: list[dict] = []
        self._sampled: dict[int, bool] = {}
        self.brand_samples: list[dict] = []                     # PAYOFF frames that show our real header (payoff_brand)
        self.pill_samples: list[dict] = []                      # frames with a real card: is one under the brand pill?
        self.site_samples: list[dict] = []                      # PAYOFF frames of a site screen (feature shorts)
        self._plan_overlays()
        self._end_build()
        self._brand_build()

    # ------------------------------------------------------------------------------------------ plan
    def word_time(self, si: int, ref) -> float:
        """A shot-relative time: a number (s), or "word:<text>" (the start of that word in this shot's VO)."""
        st = self.tl.starts[si]
        if isinstance(ref, (int, float)):
            return st + float(ref)
        if isinstance(ref, str) and ref.startswith("word:"):
            w = ref[5:]
            for x in self.tl.words:
                if x.shot == si and (x.text == w or x.text.strip('.,!?"') == w):
                    return x.start
            raise InputError(f"shot {si + 1}: no word {w!r} in its VO")
        return st

    def _plan_overlays(self):
        for si, sh in enumerate(self.shots):
            st, en = self.tl.starts[si], self.tl.ends[si]
            b = sh.get("bubble")
            if b:
                t0 = self.word_time(si, b.get("at", 0.25))
                img = C.sfx_bubble(b["text"], BUBBLE_FILL.get(b.get("fill", "lime"), C.LIME), b.get("size", 76),
                                   b.get("tail", 120), font_fn=font)
                b["_img"], b["_t0"] = img, t0
                b["_t1"] = min(en, t0 + float(b.get("dur", 9.0)))
                self.events.append((t0, "pop", {"sfx": sfx_kind(b["text"]), "gain": b.get("gain", 1.0)}))
                w_, h_ = img.size
                m_ = 60                                   # the sprite's transparent margin (the tail sits inside it)
                self.texts.append({"role": "bubble", "text": b["text"], "box": (b["x"] - w_ / 2 + m_, b["y"] - h_ / 2 + m_,
                                                                               b["x"] + w_ / 2 - m_, b["y"] + h_ / 2 - m_)})
            c = sh.get("chip")
            if c:
                img = C.chip(c["text"], c.get("size", 64), font_fn=font)
                c["_img"], c["_t0"] = img, self.word_time(si, c.get("at", 0.0))
                w_, h_ = img.size
                self.texts.append({"role": "chip", "text": c["text"].upper(),
                                   "box": (c["x"] - w_ / 2, c["y"] - h_ / 2, c["x"] + w_ / 2, c["y"] + h_ / 2)})
            if sh.get("transition_in") == "whip" and si > 0:
                self.events.append((st - 3 / FPS, "whip", {"sfx": "whoosh", "gain": 0.7}))
            pk = sh.get("peek")
            if pk:
                pk["_img"] = C.head_only(pk.get("who", "pip"), pk.get("expr", "shock"), int(pk.get("hu", 240)), False,
                                         1.0 if pk.get("brow") else 0.0)
            for el in sh.get("els", []):
                typ = el.get("t")
                if typ in ("screen", "card", "site") and el.get("enter"):
                    self.events.append((st + self.enter_at(si, el) + 8 / FPS, "land", {"sfx": "thump", "gain": 0.9}))
                if typ == "site":                             # a thumb scroll ticks softly; it does not shake the camera
                    sc = el.get("scroll") or {}
                    n_ticks = int(math.ceil(float(sc.get("dur", 0.0)) / SCROLL_TICK_S)) if sc.get("y0") != sc.get("y1") else 0
                    for k_ in range(n_ticks):
                        self.events.append((st + float(sc.get("at", 0.0)) + k_ * SCROLL_TICK_S, "scroll",
                                            {"sfx": "scroll", "gain": 0.45, "shake": 0.0}))
                if typ == "receipt":
                    if el.get("text", "$fact_phrase") == "$fact_phrase":
                        el["text"] = self.st.doc["fact_phrase"]
                    self.texts.append({"role": "receipt", "text": el["text"], "box": None, "shot": si})
                    self.texts.append({"role": "receipt_header", "text": el.get("header", "SEC FILING"), "box": None})
                    if el.get("enter"):
                        self.events.append((st + 6 / FPS, "land", {"sfx": "thump", "gain": 0.8}))
                if typ == "feed":
                    for txt in C.FEED_TEXTS:
                        self.texts.append({"role": "prop", "text": txt, "box": None})
                if typ == "search_phone":
                    word = str(el.get("text", ""))
                    tap = el.get("mode", "type") == "tap"
                    if not tap:
                        self.texts.append({"role": "prop", "text": C.SEARCH_PLACEHOLDER, "box": None})
                    self.texts.append({"role": "prop", "text": word, "box": None})
                    if el.get("brand", True):
                        self.texts.append({"role": "prop", "text": C.BRAND_NAME, "box": None})
                    t0 = self.word_time(si, el.get("at", 0.2))
                    rate = float(el.get("rate", 0.08))
                    el["_t0"], el["_rate"] = t0 - st, rate
                    if tap:                                   # one tap on the link (no typing)
                        self.events.append((t0, "tap", {"sfx": "clack", "gain": 1.0, "shake": 0.35}))
                    else:
                        for i in range(len(word)):
                            self.events.append((t0 + i * rate, "tap", {"sfx": "clack", "gain": 0.9, "shake": 0.2}))
        stress = {}
        for si, sh in enumerate(self.shots):
            stress[si] = set(sh.get("stress") or [])
        for k, ch in enumerate(self.tl.chunks):
            cap = self.shots[ch["shot"]].get("caption") or {}
            img = caption_sprite(ch["text"], stress.get(ch["shot"], set()), SPEAKER_COL.get(ch.get("voice"), (255, 255, 255)),
                                 int(cap.get("size", CAPTION_SIZE)), float(cap.get("max_w", CAPTION_MAX_W)))
            sweep = cr.Sweep(img, 0.4, 0.12) if Q.FIGURE_RX.search(ch["text"]) else None
            self.cap_sprites[k] = (img, sweep)
            cx, cy = float(cap.get("x", W / 2)), float(cap.get("y", CAPTION_Y))
            w_, h_ = img.size
            self.texts.append({"role": "caption", "text": ch["text"], "box": (cx - w_ / 2, cy - h_ / 2, cx + w_ / 2, cy + h_ / 2)})
            ch["cx"], ch["cy"] = cx, cy
            ch["size"] = (w_, h_)
        self.events.sort(key=lambda e: e[0])

    # ------------------------------------------------------------------------------------------ camera
    def camera(self, si: int, t: float) -> Cam:
        sh = self.shots[si]
        D = self.tl.ends[si] - self.tl.starts[si]
        u = t / D if D > 0 else 1.0
        f = t * FPS
        mv = sh.get("move") or {"type": "pop"}
        typ = mv.get("type", "pop")
        focus = np.array(mv.get("focus", (W / 2, H / 2)), float)
        s0 = float(mv.get("s0", 1.0))
        c = np.array((W / 2, H / 2), float)
        th = 0.0
        if typ == "pop":
            if f <= 6:
                s = 1 + 0.10 * ease_out(f / 6)
            elif f <= 12:
                s = 1.10 - 0.025 * smooth((f - 6) / 6)
            else:
                s = 1.075 + 0.02 * (t - 12 / FPS)
            s *= s0
        elif typ == "push":                                  # + a slow drift so the eased tail never freezes
            s = s0 * (1 + float(mv.get("amt", 0.16)) * ease_out(u)) * (1 + 0.03 * t)
        elif typ == "pull":
            a = float(mv.get("amt", 0.12))
            s = s0 * ((1 + a) - a * ease_out(u)) * (1 - 0.025 * t)
        elif typ in ("pan", "tilt"):
            s = s0 * 1.04
            c = c + np.array([float(mv.get("dx", 0.0)), float(mv.get("dy", 0.0))]) * (t - D / 2)
            focus = c
        elif typ == "zoom_to":
            return self._zoom_cam(si, t, mv)
        elif typ == "still":                                 # the site screen: the page moves (a scroll), the camera does not
            s = s0
        else:
            s = s0 * (1 + 0.04 * u)
        if typ not in ("pan", "tilt"):
            c = focus - (focus - c) / s if s > 0 else c
        th = float(mv.get("rot", 0.0)) * (t - D / 2) + float(mv.get("th", 0.0))
        return Cam(s, c, th)

    def _target_world(self, si: int, name_or_list, t: float, el=None):
        """World box corners of a screenshot target (or the union of several) on its screen/card element at time t (the
        shot's main screen unless `el` is given)."""
        names = name_or_list if isinstance(name_or_list, list) else [name_or_list]
        sh = self.shots[si]
        if el is None:                  # the card whose capture has the target (the main one first)
            cards = [e for e in sh["els"] if e.get("t") in ("screen", "card", "site")]
            cards.sort(key=lambda e: not e.get("main", True))
            el = next((e for e in cards if all(any(x["text"] == nm for x in self.st.screens[e["name"]]["meta"]["targets"])
                                               for nm in names)), None)
            if el is None:
                raise InputError(f"shot {si + 1}: no card has the target(s) {names}")
        meta = self.st.screens[el["name"]]["meta"]
        boxes = []
        for nm in names:
            tg = next((x for x in meta["targets"] if x["text"] == nm), None)
            if tg is None:
                raise InputError(f"screen {el['name']}: no target {nm!r} in its sidecar")
            boxes.append(tg["box"])
        if el.get("t") == "site":       # a text of the strip, where the scroll has it now (it may be outside the window)
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
            return np.array(self.site_world(si, el, t, (x0, y0, x1, y1))), (x1 - x0, y1 - y0)
        cx0, cy0 = (el.get("crop") or (0, 0))[:2]
        x0 = min(b[0] for b in boxes) - cx0
        y0 = min(b[1] for b in boxes) - cy0
        x1 = max(b[0] + b[2] for b in boxes) - cx0
        y1 = max(b[1] + b[3] for b in boxes) - cy0
        spr = self.screen_sprite(el)
        q, rot_deg, k, alpha = self.el_pose(si, el, t)
        img, anchor, kk, off, res = spr
        pts = []
        for (sx, sy) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            u = np.array([off[0] + sx * kk, off[1] + sy * kk])
            pts.append(np.array(q, float) + (k / res) * (rot(rot_deg) @ (u - np.array(anchor, float))))
        return np.array(pts), (x1 - x0, y1 - y0)

    def _zoom_cam(self, si: int, t: float, mv: dict) -> Cam:
        D = self.tl.ends[si] - self.tl.starts[si]
        corners, _ = self._target_world(si, mv["target"], D)
        cen = corners.mean(0)
        bw = np.linalg.norm(corners[1] - corners[0])
        bh = np.linalg.norm(corners[3] - corners[0])
        Z = float(mv.get("z") or min(2.4, 640.0 / max(bw, 1)))
        Z = max(Z, 64.0 / max(bh, 1)) if mv.get("min_px", True) else Z
        Z = min(Z, float(mv.get("z_max", 3.0)))
        land = np.array(mv.get("land", (540, 900)), float)
        c_end = cen - (land - O) / Z
        if mv.get("from_prev") and si > 0:              # continue the previous shot's camera exactly (a joined line)
            prev = self.camera(si - 1, self.tl.ends[si - 1] - self.tl.starts[si - 1])
            c_start, s_start = np.array(prev.c, float), float(prev.s)
        elif "from_target" in mv:
            c0corners, _ = self._target_world(si, mv["from_target"], 0.0)
            c0cen = c0corners.mean(0)
            Z0 = float(mv.get("z0", Z))
            c_start, s_start = c0cen - (land - O) / Z0, Z0
        else:
            c_start, s_start = np.array((W / 2, H / 2), float), float(mv.get("s0", 1.0))
        a0 = float(mv.get("at", 0.3))
        dur = float(mv.get("dur", 0.8))
        v = smooth((t - a0) / dur)
        s = lerp(s_start, Z, v)
        c = c_start + (c_end - c_start) * v
        if t > a0 + dur:
            s *= 1 + float(mv.get("drift", 0.03)) * (t - a0 - dur)
        elif t < a0 and "from_target" not in mv and not mv.get("from_prev"):
            s *= 1 + 0.03 * t
        return Cam(s, c, float(mv.get("th", 0.0)))

    # ------------------------------------------------------------------------------------------ elements
    def screen_sprite(self, el):
        crop = tuple(el.get("crop") or ())
        key = ("screen", el["name"], el["t"], el.get("w"), crop)
        if key in self.cache:
            el["_res"] = self.cache[key][4]
            return self.cache[key]
        sc = self.st.screens[el["name"]]
        img = sc["img"]
        if crop:                       # a plain rectangle of the real capture (pixels untouched), e.g. one table row
            x0, y0, x1, y1 = (int(v) for v in crop)
            if not (0 <= x0 < x1 <= img.size[0] and 0 <= y0 < y1 <= img.size[1]):
                raise InputError(f"screen {el['name']}: crop {crop} is outside the {img.size} capture")
            img = img.crop((x0, y0, x1, y1))
        if el["t"] == "screen":
            sw = int(el.get("w", 732))
            res = float(el.get("res", 2.0))
            body, k = C.phone_frame(img, int(sw * res), int(34 * res), int(112 * res), int(4 * res))
            bez = int(34 * res)
            spr, pad = C.with_shadow(body, int(28 * res), int(36 * res / 2))
            off = (pad + bez, pad + bez)
        else:
            cw = int(el.get("w", 960))
            res = float(el.get("res", img.size[0] / cw))
            body, k = C.phone_frame(img, int(cw * res), int(10 * res), int(44 * res), int(6 * res))
            spr, pad = C.with_shadow(body, int(18 * res), int(20 * res))
            off = (pad + int(10 * res), pad + int(10 * res))
        anchor = (spr.size[0] / 2, spr.size[1] / 2)
        out = (spr, anchor, k, off, res)
        self.cache[key] = out
        el["_res"] = res
        return out

    # ---- the site screen: one window onto a strip of the real page (feature shorts)
    def site_geom(self, el) -> tuple[int, int, float, int]:
        """(strip width, strip height, capture px per frame px, the window's height in capture px)."""
        sw, sh = self.st.screens[el["name"]]["size"]
        res = sw / float(el["w"])
        return sw, sh, res, int(min(sh, round(float(el["h"]) * res)))

    def site_scroll(self, el, t: float) -> float:
        """The strip row (capture px) at the window's top at shot time t."""
        sw, sh, _res, ch = self.site_geom(el)
        sc = el.get("scroll") or {}
        y0 = float(sc.get("y0", 0.0))
        y1 = float(sc.get("y1", y0))
        dur = float(sc.get("dur", 0.0))
        y = y1 if dur <= 0 else lerp(y0, y1, cruise((t - float(sc.get("at", 0.0))) / dur))
        return float(min(max(0.0, y), max(0, sh - ch)))

    def site_world(self, si, el, t, box) -> list:
        """World corners of a box of the strip (capture px: x0, y0, x1, y1) at shot time t."""
        sw, _sh, res, ch = self.site_geom(el)
        (x, y), rot_deg, k, _a = self.el_pose(si, el, t)
        sy = round(self.site_scroll(el, t))
        R = rot(rot_deg)
        return [np.array((x, y), float) + (k / res) * (R @ np.array((px - sw / 2, py - sy - ch / 2), float))
                for px, py in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]))]

    def site_window(self, si, el, t) -> list:
        """World corners of the window (the part of the strip on screen)."""
        sw, _sh, _res, ch = self.site_geom(el)
        sy = round(self.site_scroll(el, t))
        return self.site_world(si, el, t, (0, sy, sw, sy + ch))

    def site_sprite(self, el, sy: float):
        """The window at one scroll position: the strip's rows as captured (only resized with the whole window when it
        is drawn), inside a thin brand rim. -> (RGBA, anchor, capture px per frame px)."""
        sw, _sh, res, ch = self.site_geom(el)
        key = ("site", el["name"], int(el["w"]), int(el["h"]))
        if key not in self.cache:
            rim, rad = int(round(SITE_RIM * res)), int(round(SITE_RADIUS * res))
            body = C.gradient((sw + 2 * rim, ch + 2 * rim)).convert("RGBA")
            body.putalpha(C.rounded_mask(body.size, rad + rim))
            base, pad = C.with_shadow(body, int(18 * res), int(20 * res))
            self.cache[key] = (base, C.rounded_mask((sw, ch), rad), pad + rim)
        base, mask, off = self.cache[key]
        y0 = int(round(sy))
        img = base.copy()
        img.paste(self.st.screens[el["name"]]["img"].crop((0, y0, sw, y0 + ch)), (off, off), mask)
        return img, (img.size[0] / 2, img.size[1] / 2), res

    def el_pose(self, si, el, t):
        """(world pos, rotation, scale, alpha) of an element at shot time t (enter animation, sink, bob)."""
        D = self.tl.ends[si] - self.tl.starts[si]
        u = t / D if D > 0 else 1.0
        x, y = float(interp(el.get("x", 540), u)), float(interp(el.get("y", 960), u))
        r = float(interp(el.get("rot", 0.0), u))
        k = float(interp(el.get("k", 1.0), u))
        a = float(el.get("alpha", 1.0))
        en = el.get("enter")
        if en:
            d = float(en.get("dur", 9 / FPS))
            te = t - self.enter_at(si, el)                  # "at": the entrance starts later in the shot (hidden before)
            v = eob(te / d, float(en.get("back", 1.4)))
            dx, dy = en.get("from", (0, 1100))
            x += dx * (1 - v)
            y += dy * (1 - v)
            if "k0" in en:
                k *= lerp(float(en["k0"]), 1.0, v)
            a *= min(1.0, te / max(d * 0.4, 1e-3)) if en.get("fade") else 1.0
            if te < 0:
                a = 0.0
        ex = el.get("exit")
        if ex and t > float(ex.get("at", 0.0)):
            v = min(1.0, (t - float(ex.get("at", 0.0))) / float(ex.get("dur", 0.3)))
            v = v * v                                       # ease in: it leaves fast
            dx, dy = ex.get("to", (0, -1400))
            x += dx * v
            y += dy * v
        return (x, y), r, k, a

    def enter_at(self, si, el) -> float:
        """When an element's entrance starts, in shot time: 0, a number, or "word:<text>" (that word of the shot's line)."""
        en = el.get("enter") or {}
        at = en.get("at", 0.0)
        if isinstance(at, str):
            if "_at" not in en:
                en["_at"] = self.word_time(si, at) - self.tl.starts[si]
            return en["_at"]
        return float(at)

    def el_moving(self, si, el, t) -> bool:
        """True while an element is entering or leaving (its pass under the brand pill is a blur, not a collision), or
        still waiting off screen for a later entrance."""
        en, ex = el.get("enter"), el.get("exit")
        if en and t < self.enter_at(si, el) + float(en.get("dur", 9 / FPS)) + 2 / FPS:
            return True
        return bool(ex and t >= float(ex.get("at", 0.0)))

    def shot_u(self, si, t):
        D = self.tl.ends[si] - self.tl.starts[si]
        return t / D if D > 0 else 1.0

    def pip_load(self, el, t):
        """Pip's squat depth and front-rack bar (plates, tabs, bend) at shot time t, quantised for the sprite cache. squat
        may be a number, [a, b] across the shot, or {"reps": n, "depth": d} (n squats over the shot)."""
        u = self.shot_u(el["_si"], t)
        sq = el.get("squat", 0.0)
        if isinstance(sq, dict):
            sq = float(sq.get("depth", 0.8)) * (0.5 - 0.5 * math.cos(2 * math.pi * float(sq.get("reps", 1)) * u))
        squat = round(float(interp(sq, u)) * 20) / 20
        b = el.get("bar")
        bar = None
        if b:
            bar = (int(b.get("plates", 0)), int(round(interp(b.get("tabs", 0), u))), round(float(interp(b.get("bend", 0.0), u)) * 20) / 20)
        return squat, bar

    def char_sprite(self, el, t_abs, t):
        who = el["t"]
        pose, expr = el.get("pose", "idle"), el.get("expr", "deadpan")
        sw = el.get("swap")
        swapped = False
        if sw:
            ts = self.word_time(el["_si"], sw.get("at", 0.5)) - self.tl.starts[el["_si"]]
            if t >= ts:
                pose, expr = sw.get("pose", pose), sw.get("expr", expr)
                swapped = t - ts < 2 / FPS
        phase = float(el.get("phase", 0.0 if who == "pip" else 1.1))
        bt = (t_abs + phase) % 3.0
        blink = bt < 3 / FPS
        hold = tuple(el.get("hold", ("shaker",) if who == "dale" else ()))
        hu = int(el.get("hu", 300))
        if who == "pip":
            kick = round(((t_abs * 5) % 1.0) * 4) / 4 if el.get("kick") else 0.0
            squat, bar = self.pip_load(el, t)
            key = ("pip", pose, expr, hu, blink, hold, kick, squat, bar)
            if key not in self.cache:
                self.cache[key] = C.pip(pose, expr, hu, blink, hold, kick, squat=squat, bar=bar)
        else:
            brow = round(math.sin(t_abs * 2 * math.pi * 1.6) * 2) / 2 if el.get("brow") else 0.0
            key = ("dale", pose, expr, hu, blink, hold, brow)
            if key not in self.cache:
                self.cache[key] = C.dale(pose, expr, hu, blink, brow, hold)
        img, anchor = self.cache[key]
        if el.get("flip"):
            fk = key + ("flip",)
            if fk not in self.cache:
                self.cache[fk] = (img.transpose(Image.FLIP_LEFT_RIGHT), (img.size[0] - anchor[0], anchor[1]))
            img, anchor = self.cache[fk]
        return img, anchor, (1.06 if swapped else 1.0)

    def draw_els(self, frame, si, t, t_abs, cam: Cam):
        sh = self.shots[si]
        D = self.tl.ends[si] - self.tl.starts[si]
        u = t / D if D > 0 else 1.0
        for el in sh.get("els", []):
            el["_si"] = si
            typ = el["t"]
            (x, y), r, k, a = self.el_pose(si, el, t)
            if typ in ("pip", "dale"):
                img, anchor, sq = self.char_sprite(el, t_abs, t)
                bob = -0.015 * img.size[1] * k * math.sin(2 * math.pi * 1.1 * t_abs + (0.0 if typ == "pip" else 1.3))
                q = (x + bob * math.sin(math.radians(r)), y + bob * math.cos(math.radians(r)))
                cam.sprite(frame, img, anchor, q, r, k * sq, 1.0, a)
            elif typ in ("screen", "card"):
                img, anchor, kk, off, _ = self.screen_sprite(el)
                A, b = cam.sprite(frame, img, anchor, (x, y), r, k, el["_res"], a)
                if el.get("dim"):
                    pass
            elif typ == "site":
                img, anchor, res = self.site_sprite(el, self.site_scroll(el, t))
                cam.sprite(frame, img, anchor, (x, y), r, k, res, a)
            elif typ == "barbell":
                tabs = int(round(interp(el.get("tabs", 0), u)))
                bend = round(float(interp(el.get("bend", 0.0), u)) * 20) / 20
                key = ("bar", int(el.get("w", 900)), int(el.get("plates", 0)), tabs, bend)
                if key not in self.cache:
                    self.cache[key] = C.barbell(int(el.get("w", 900)), int(el.get("plates", 0)), tabs, bend)
                img, anchor = self.cache[key]
                cam.sprite(frame, img, anchor, (x, y), r, k, 1.0, a)
            elif typ == "search_phone" and el.get("mode", "type") == "tap":
                word = str(el.get("text", ""))
                v = t - el["_t0"]                              # the thumb reaches the link, taps, and lifts a little
                reach = max(0.0, min(1.0, (v + 0.25) / 0.25)) if v < 0.14 else max(0.55, 1.0 - 1.5 * (v - 0.14))
                reach = round(reach * 5) / 5
                key = ("tphone", int(el.get("w", 560)), word, reach, v >= 0)
                if key not in self.cache:
                    self.cache[key] = C.search_phone(int(el.get("w", 560)), word, False, reach, font_fn=font,
                                                     brand=el.get("brand", True), mode="tap", lit=v >= 0)
                img, anchor = self.cache[key]
                pulse = 1.0 + (0.035 * math.exp(-v / 0.08) if v >= 0 else 0.0)        # the phone gives under the tap
                cam.sprite(frame, img, anchor, (x, y), r, k * pulse, 1.0, a)
            elif typ == "search_phone":
                word = str(el.get("text", ""))
                v = t - el["_t0"]
                n_typed = 0 if v < 0 else min(len(word), int(v / el["_rate"]) + 1)
                thumb = 0.0
                if 0 <= v < len(word) * el["_rate"] + 0.1:
                    ph = (v % el["_rate"]) / el["_rate"]
                    thumb = round(max(0.0, 1 - 2.5 * ph) * 4) / 4
                caret = n_typed < len(word) or int(t * 3) % 2 == 0
                key = ("sphone", int(el.get("w", 560)), word[:n_typed], caret, thumb)
                if key not in self.cache:
                    self.cache[key] = C.search_phone(int(el.get("w", 560)), word[:n_typed], caret, thumb, font_fn=font,
                                                     brand=el.get("brand", True))
                img, anchor = self.cache[key]
                cam.sprite(frame, img, anchor, (x, y), r, k, 1.0, a)
            elif typ == "receipt":
                img, anchor = self.receipt_sprite(el)
                cam.sprite(frame, img, anchor, (x, y), r, k, 1.0, a)
            elif typ == "spray":
                self._spray(frame, el, si, t, cam)
            elif typ in ("bench_top", "bench_side", "cat", "sock", "search_bar"):
                key = (typ, int(el.get("hu", 300)), el.get("text"))
                if key not in self.cache:
                    if typ == "bench_top":
                        self.cache[key] = C.bench_top(int(el.get("hu", 300)))
                    elif typ == "bench_side":
                        self.cache[key] = C.bench_side(int(el.get("hu", 300)))
                    elif typ == "cat":
                        self.cache[key] = C.cat_box(int(el.get("hu", 300)))
                    elif typ == "sock":
                        self.cache[key] = C.sock(int(el.get("hu", 300)))
                    else:
                        self.cache[key] = C.search_bar(int(el.get("w", 880)), True, el.get("text", "Search"))
                img, anchor = self.cache[key]
                if typ == "search_bar" and int(t * 2) % 2 == 1:
                    ck = (typ, int(el.get("w", 880)), "nocaret")
                    if ck not in self.cache:
                        self.cache[ck] = C.search_bar(int(el.get("w", 880)), False, el.get("text", "Search"))
                    img, anchor = self.cache[ck]
                cam.sprite(frame, img, anchor, (x, y), r, k, 1.0, a)
            elif typ == "phone":
                key = ("phone", int(el.get("hu", 300)))
                if key not in self.cache:
                    p = C.Pen(0.7, 1.0, int(el.get("hu", 300)), origin=(0.35, 0.5))
                    C.phone_in_hand(p, 0, 0, 0.5)
                    self.cache[key] = p.done((0, 0))
                img, anchor = self.cache[key]
                cam.sprite(frame, img, anchor, (x, y), r, k, 1.0, a)
            elif typ == "feed":
                self._feed(frame, el, t, cam)
            elif typ == "tabs_burst":
                self._burst(frame, el, si, t, cam)
            elif typ == "confetti":
                self._confetti(frame, el, t, cam)
            elif typ == "highlight":
                self._highlight(frame, el, si, t, cam)

    def _feed(self, frame, el, t, cam):
        key = ("feedstrip", int(el.get("w", 900)))
        if key not in self.cache:
            self.cache[key] = C.feed_strip(int(el.get("w", 900)))
        strip = self.cache[key]
        wh = int(el.get("h", 1700))
        v0, acc = float(el.get("v0", 300)), float(el.get("acc", 300))
        off = float(el.get("start", 0)) + v0 * t + 0.5 * acc * t * t
        off = off % max(1, strip.size[1] - wh)
        crop = strip.crop((0, int(off), strip.size[0], int(off) + wh)).copy()
        crop.putalpha(C.rounded_mask(crop.size, 60))
        cam.sprite(frame, crop, (crop.size[0] / 2, crop.size[1] / 2), (el.get("x", 540), el.get("y", 980)))

    def _burst(self, frame, el, si, t, cam):
        n = int(el.get("n", 6))
        t0 = (self.word_time(si, el["at"]) - self.tl.starts[si]) if "at" in el else 0.0
        gap = float(el.get("gap", 0.06))
        ox, oy = float(el.get("x", 540)), float(el.get("y", 1300))
        spread = float(el.get("spread", 700))
        base = int(el.get("size", 230))
        for i in range(n):
            ti = t - (t0 + i * gap)
            if ti < 0:
                continue
            ang = math.radians(-90 + ((i * 67) % 150) - 75)
            dist = spread * (0.55 + 0.45 * ((i * 37) % 10) / 10) * ease_out(ti / 0.5)
            x = ox + math.cos(ang) * dist
            y = oy + math.sin(ang) * dist + 300 * max(0.0, ti - 0.5) ** 2
            k = 0.35 + 0.75 * ease_out(ti / 0.45) + 0.15 * ti
            img, anchor = C.tab_sprite(base, i)
            cam.sprite(frame, img, anchor, (x, y), ((i * 53) % 40 - 20) + 90 * ti * (1 if i % 2 else -1), k)

    def receipt_sprite(self, el):
        key = ("receipt", el["text"], int(el.get("w", 900)), el.get("header", "SEC FILING"))
        if key not in self.cache:
            img = C.receipt(el["text"], int(el.get("w", 900)), font, int(el.get("size", 52)), el.get("header", "SEC FILING"))
            spr, pad = C.with_shadow(img, 22, 18)
            self.cache[key] = (spr, (spr.size[0] / 2, spr.size[1] / 2))
        return self.cache[key]

    def _spray(self, frame, el, si, t, cam):
        """A spit-take: droplets burst from (x, y) toward `dir` degrees (0 = right, -90 = up), then fall."""
        t0 = (self.word_time(si, el["at"]) - self.tl.starts[si]) if "at" in el else 0.0
        v = t - t0
        if v < 0:
            return
        d = ImageDraw.Draw(frame)
        ox, oy = float(el.get("x", 540)), float(el.get("y", 800))
        base = math.radians(float(el.get("dir", -15)))
        n = int(el.get("n", 30))
        sp = float(el.get("speed", 1500))
        cols = ((167, 139, 250), (255, 255, 255), (200, 246, 252))
        for i in range(n):
            ang = base + math.radians(((i * 37) % 50) - 25)
            vel = sp * (0.45 + 0.55 * ((i * 53) % 10) / 10)
            delay = ((i * 29) % 7) * 0.012
            tt = v - delay
            if tt < 0:
                continue
            px = ox + math.cos(ang) * vel * tt
            py = oy + math.sin(ang) * vel * tt + 1300 * tt * tt
            p = cam.p((px, py))
            r = (9 + (i % 4) * 5) * cam.s * max(0.35, 1 - 0.5 * tt)
            d.ellipse((p[0] - r, p[1] - r * 0.8, p[0] + r, p[1] + r * 0.8), fill=C.INK + (255,))
            r2 = r * 0.72
            d.ellipse((p[0] - r2, p[1] - r2 * 0.8, p[0] + r2, p[1] + r2 * 0.8), fill=cols[i % 3] + (255,))

    def _confetti(self, frame, el, t, cam):
        d = ImageDraw.Draw(frame)
        n = int(el.get("n", 70))
        for i in range(n):
            x0 = (i * 151) % W
            y0 = -300 + (i * 97) % 1700
            vy = 500 + (i * 41) % 400
            x = x0 + 40 * math.sin(t * 3 + i)
            y = y0 + vy * t
            p = cam.p((x, y))
            a = t * 6 + i
            sz = 14 + (i % 4) * 4
            col = C.ACCENTS[i % len(C.ACCENTS)]
            pts = [(p[0] + sz * math.cos(a + k * math.pi / 2) * (1.6 if k % 2 == 0 else 0.6),
                    p[1] + sz * math.sin(a + k * math.pi / 2) * (1.6 if k % 2 == 0 else 0.6)) for k in range(4)]
            d.polygon(pts, fill=col + (255,))

    def _highlight(self, frame, el, si, t, cam):
        at = float(el.get("at", 0.9))
        if t < at:
            return
        corners, (bw, bh) = self._target_world(si, el["target"], t)
        pts = np.array([cam.p(q) for q in corners])
        cen = pts.mean(0)
        pad = el.get("pad", 18.0)                       # px around the text's box: one number, or [sideways, up and down]
        pad = np.array(pad if isinstance(pad, (list, tuple)) else (pad, pad), float)
        dirs = pts - cen
        unit = np.sign(dirs)
        pts = pts + unit * pad
        prog_ = min(1.0, (t - at) / (8 / FPS))
        per = [pts[0], pts[1], pts[2], pts[3], pts[0]]
        seg = [np.linalg.norm(per[i + 1] - per[i]) for i in range(4)]
        total = sum(seg) * prog_
        path = [tuple(per[0])]
        for i in range(4):
            if total <= 0:
                break
            if total >= seg[i]:
                path.append(tuple(per[i + 1]))
                total -= seg[i]
            else:
                v = per[i] + (per[i + 1] - per[i]) * (total / seg[i])
                path.append(tuple(v))
                total = 0
        x0, y0 = np.floor(pts.min(0) - 40).astype(int)
        x1, y1 = np.ceil(pts.max(0) + 40).astype(int)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if x1 <= x0 or y1 <= y0:
            return
        layer = Image.new("RGBA", (x1 - x0, y1 - y0), C.CYAN + (0,))
        dl = ImageDraw.Draw(layer)
        rel = [(px - x0, py - y0) for px, py in path]
        if len(rel) >= 2:
            dl.line(rel, fill=C.CYAN + (255,), width=int(el.get("width", 8)), joint="curve")
        glow = layer.filter(ImageFilter.GaussianBlur(10))
        pulse = 0.35 + 0.25 * (0.5 + 0.5 * math.sin(2 * math.pi * 1.6 * (t - at)))
        g = cr.faded(glow, min(1.0, pulse * 2.2))
        if g is not None:
            frame.alpha_composite(g, (x0, y0))
        frame.alpha_composite(layer, (x0, y0))

    # ------------------------------------------------------------------------------------------ sets
    def static_bg(self, si):
        sh = self.shots[si]
        key = (sh.get("set"), sh.get("set_variant", 0))
        if key in self.bg_cache:
            return self.bg_cache[key]
        name = sh.get("set", "gym")
        if name == "gym":
            img = C.set_gym(CANVAS, MARGIN, sh.get("set_variant", 0))
        elif name == "gym_floor":
            img = C.set_gym_floor(CANVAS, MARGIN)
        elif name == "screen":
            img = C.set_screen(CANVAS, MARGIN)
        else:
            raise InputError(f"shot {si + 1}: unknown set {name!r}")
        self.bg_cache[key] = img
        return img

    def background(self, si, t, t_abs, cam: Cam) -> Image.Image:
        sh = self.shots[si]
        name = sh.get("set", "gym")
        if name.startswith("rings") or name == "payoff":
            pair = name.split(":", 1)[1] if ":" in name else "navy"
            centre = cam.p(sh.get("ring_centre", (540, 900)))
            return C.rings(t_abs, centre, pair).convert("RGBA")
        img = self.static_bg(si)
        A = cam.M()
        b = cam.p((0, 0)) - A @ np.array(MARGIN, float)
        Ai = np.linalg.inv(A)
        off = Ai @ (-b)
        data = (Ai[0, 0], Ai[0, 1], off[0], Ai[1, 0], Ai[1, 1], off[1])
        return img.transform((W, H), Image.AFFINE, data, Image.BILINEAR, fillcolor=C.NIGHT_FLOOR).convert("RGBA")

    # ------------------------------------------------------------------------------------------ overlays
    def shake(self, t_abs) -> tuple[float, float, float]:
        dx = dy = dth = 0.0
        for te, kind, data in self.events:
            v = t_abs - te
            if 0 <= v < 0.25:
                g = float(data.get("shake", 1.0)) * (0.6 if kind == "whip" else 1.0)
                e = math.exp(-v / 0.12)
                x = 14 * g * e * math.sin(2 * math.pi * 12 * v)
                dx += x
                dy += 0.6 * x
                dth += 0.6 * g * e * math.sin(2 * math.pi * 9 * v)
        return dx, dy, dth

    def peek_pose(self, si, t_abs):
        """A PEEK cut-in (a character's head leaning in from a frame edge, screen px): (x, y, rotation, scale) or None."""
        pk = self.shots[si].get("peek")
        if not pk:
            return None
        v = t_abs - self.tl.starts[si] - float(pk.get("at", 0.0))
        if v < 0:
            return None
        e = eob(v / 0.3, 1.6)
        fx, fy = pk.get("from", (-260, 0))
        x = float(pk["x"]) + fx * (1 - e)
        y = float(pk["y"]) + fy * (1 - e) + 8 * math.sin(2 * math.pi * 1.3 * v)
        r = float(pk.get("rot", 0.0)) + 3 * math.sin(2 * math.pi * 0.8 * v)
        return x, y, r, 1.0

    def overlays(self, frame, si, t_abs):
        sh = self.shots[si]
        en = self.tl.ends[si]
        pp = self.peek_pose(si, t_abs)
        if pp:
            img = sh["peek"]["_img"][0].rotate(pp[2], Image.BICUBIC, expand=True, fillcolor=C.CLEAR)
            cr.put(frame, img, pp[0], pp[1], 1.0, pp[3])
        c = sh.get("chip")
        if c and t_abs >= c["_t0"]:
            v = t_abs - c["_t0"]
            a = min(1.0, v / (6 / FPS))
            x = c["x"] - 60 * (1 - ease_out(v / 0.25))
            img = c["_img"].rotate(float(c.get("rot", -3)) + 2.5 * math.sin(2 * math.pi * 0.9 * v), Image.BICUBIC, expand=True,
                                   fillcolor=C.CLEAR)
            cr.put(frame, img, x, c["y"], a)
        b = sh.get("bubble")
        if b and b["_t0"] <= t_abs < b["_t1"]:
            v = t_abs - b["_t0"]
            f = v * FPS
            if f < 3:
                s = 1.15 * ease_out(f / 3)
            elif f < 5:
                s = 1.15 - 0.15 * smooth((f - 3) / 2)
            else:
                s = 1.0
            out = b["_t1"] - t_abs
            al = 1.0
            if out < 3 / FPS and b["_t1"] < en - 1e-6:
                al = out / (3 / FPS)
                s *= 0.8 + 0.2 * al
            r = float(b.get("rot", 6 if si % 2 else -6)) + 2.5 * math.sin(2 * math.pi * 0.9 * v)
            img = b["_img"].rotate(r, Image.BICUBIC, expand=True, fillcolor=C.CLEAR)
            cr.put(frame, img, b["x"], b["y"], al, max(0.05, s))
        for k, ch in enumerate(self.tl.chunks):
            if ch["shot"] != si or not (ch["start"] <= t_abs < ch["end"]):
                continue
            img, sweep = self.cap_sprites[k]
            v = (t_abs - ch["start"]) * FPS
            first = k == 0
            s = self.caption_scale(k, t_abs)
            if sweep:
                img = sweep.at(min(1.0, max(0.0, (t_abs - ch["start"] - 0.35) / 0.55)))
            al = 1.0 if first else min(1.0, (v + 1) / 2)
            if sh.get("caption_plate", sh.get("kind") == "PAYOFF"):
                pk = ("plate", img.size, tuple((sh.get("caption") or {}).get("plate", ())))
                if pk not in self.cache:
                    pw, ph = self.plate_size(img.size, sh)
                    plate = Image.new("RGBA", (pw, ph), C.INK + (0,))
                    ImageDraw.Draw(plate).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=ph // 2, fill=C.INK + (215,))
                    self.cache[pk] = plate
                cr.put(frame, self.cache[pk], ch["cx"], ch["cy"], al, s)
            cr.put(frame, img, ch["cx"], ch["cy"], al, s)

    @staticmethod
    def plate_size(size, sh: dict) -> tuple[int, int]:
        """The dark plate behind a payoff caption (a shot's caption band may make it tighter: "plate": [dw, dh])."""
        dw, dh = (sh.get("caption") or {}).get("plate", (56, 30))
        return size[0] + int(dw), size[1] + int(dh)

    def caption_scale(self, k: int, t_abs: float) -> float:
        """A caption chunk's scale at t_abs (it pops in; a figure lands large and settles)."""
        ch = self.tl.chunks[k]
        v = (t_abs - ch["start"]) * FPS
        if self.cap_sprites[k][1]:
            return 1.15 - 0.15 * eob(v / 4)
        if k == 0:
            return 0.93 + 0.07 * eob(v / 4)
        return 0.86 + 0.14 * eob(v / 4)

    def caption_boxes(self, si: int, t_abs: float) -> list:
        """Frame boxes of the captions on screen at t_abs, their plates included."""
        out = []
        sh = self.shots[si]
        for k, ch in enumerate(self.tl.chunks):
            if ch["shot"] != si or not (ch["start"] <= t_abs < ch["end"]):
                continue
            w_, h_ = ch["size"]
            if sh.get("caption_plate", sh.get("kind") == "PAYOFF"):
                w_, h_ = self.plate_size((w_, h_), sh)
            s = self.caption_scale(k, t_abs)
            out.append([ch["cx"] - w_ * s / 2, ch["cy"] - h_ * s / 2, ch["cx"] + w_ * s / 2, ch["cy"] + h_ * s / 2])
        return out

    def peek_box(self, si: int, t_abs: float):
        """Frame box of a PEEK head at t_abs (what is drawn of it, with room for its tilt), or None."""
        pp = self.peek_pose(si, t_abs)
        if not pp:
            return None
        pk = self.shots[si]["peek"]
        img = pk["_img"][0]
        if "_bb" not in pk:
            pk["_bb"] = img.getbbox() or (0, 0, img.size[0], img.size[1])
        x0, y0, x1, y1 = pk["_bb"]
        cx, cy = img.size[0] / 2, img.size[1] / 2
        g = 1.08 * pp[3]
        return [pp[0] + (x0 - cx) * g, pp[1] + (y0 - cy) * g, pp[0] + (x1 - cx) * g, pp[1] + (y1 - cy) * g]

    # ------------------------------------------------------------------------------------------ what a caption must not cover
    def protect_boxes(self, si: int, t_abs: float) -> list[dict]:
        """Screen boxes of what a caption may not cover at t_abs: faces and held props (from the cast's own geometry),
        PEEK heads, visible bubbles and chips, the key number, the receipt, the search phone and the feed."""
        sh = self.shots[si]
        t = t_abs - self.tl.starts[si]
        cam = self.camera(si, t)
        out = []

        def add(kind, pts):
            pts = np.asarray(pts, float)
            out.append({"kind": kind, "box": [float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()),
                                              float(pts[:, 1].max())]})

        for el in sh.get("els", []):
            el["_si"] = si
            typ = el["t"]
            (x, y), r, k, _a = self.el_pose(si, el, t)
            if typ in ("pip", "dale"):
                hu = int(el.get("hu", 300))
                pose = el.get("pose", "idle")
                hold = tuple(el.get("hold", ("shaker",) if typ == "dale" else ()))
                if typ == "pip":
                    squat, bar = self.pip_load(el, t)
                    boxes = C.pip_boxes(pose, hold, squat, bar)
                else:
                    boxes = C.dale_boxes(pose, hold)
                M = cam.s * k * rot(r - cam.th)
                base = cam.p((x, y))
                for kind, (x0, y0, x1, y1) in boxes:
                    if el.get("flip"):
                        x0, x1 = -x1, -x0
                    add(kind, [base + M @ (np.array(c_) * hu) for c_ in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])
            elif typ in ("receipt", "search_phone", "feed", "card", "screen"):
                if typ == "receipt":
                    w_, h_ = self.receipt_sprite(el)[0].size
                    w_, h_ = w_ - 156, h_ - 156                     # without the drop shadow and margin
                elif typ == "search_phone":
                    w_, h_ = float(el.get("w", 560)), float(el.get("w", 560)) * 1.85
                elif typ == "feed":
                    w_, h_ = float(el.get("w", 900)), float(el.get("h", 1700))
                else:
                    continue
                M = cam.s * k * rot(r - cam.th)
                base = cam.p((x, y))
                add(typ, [base + M @ np.array(c_) for c_ in ((-w_ / 2, -h_ / 2), (w_ / 2, -h_ / 2), (w_ / 2, h_ / 2), (-w_ / 2, h_ / 2))])
        if sh.get("key_number"):
            corners, _ = self._target_world(si, sh["key_number"], t)
            add("key number", [cam.p(q) for q in corners])
        pp = self.peek_pose(si, t_abs)
        if pp:
            img = sh["peek"]["_img"][0]
            w_, h_ = img.size[0] * 0.75, img.size[1] * 0.75
            add("peek face", [(pp[0] - w_ / 2, pp[1] - h_ / 2), (pp[0] + w_ / 2, pp[1] + h_ / 2)])
        b = sh.get("bubble")
        if b and b["_t0"] <= t_abs < b["_t1"]:
            w_, h_ = b["_img"].size
            add("bubble", [(b["x"] - w_ / 2 + 70, b["y"] - h_ / 2 + 70), (b["x"] + w_ / 2 - 70, b["y"] + h_ / 2 - 70)])
        c = sh.get("chip")
        if c and t_abs >= c["_t0"]:
            w_, h_ = c["_img"].size
            add("chip", [(c["x"] - w_ / 2, c["y"] - h_ / 2), (c["x"] + w_ / 2, c["y"] + h_ / 2)])
        return out

    def occlusion_samples(self) -> list[dict]:
        out = []
        for k, ch in enumerate(self.tl.chunks):
            si = ch["shot"]
            lo, hi = max(ch["start"], self.tl.starts[si]), min(ch["end"], self.tl.ends[si]) - 1e-3
            if hi <= lo:
                continue
            w_, h_ = ch["size"]
            box = [ch["cx"] - w_ / 2, ch["cy"] - h_ / 2, ch["cx"] + w_ / 2, ch["cy"] + h_ / 2]
            for tt in (lo + 0.07, (lo + hi) / 2, hi - 0.02):
                if lo <= tt <= hi:
                    out.append({"t": tt, "caption": ch["text"], "box": box, "protect": self.protect_boxes(si, tt)})
        return out

    # ------------------------------------------------------------------------------------------ the brand layer
    def _brand_build(self):
        self.b_pill = cr.pill(cr.BRAND, BRAND_PILL_SIZE, 26, 16)
        self.b_sweep = cr.Sweep(self.b_pill, 0.35, 0.10)
        x0, y0 = BRAND_PILL_XY
        w_, h_ = self.b_pill.size
        self.brand_box = (x0, y0, x0 + w_, y0 + h_)
        self.texts.append({"role": "brand_pill", "text": cr.BRAND, "box": self.brand_box})

    def brand_sprite(self, t_abs: float) -> Image.Image:
        x = ((t_abs - 0.8) % BRAND_SWEEP_EVERY) / 0.7 if t_abs >= 0.8 else -1.0
        return self.b_sweep.at(x) if 0 < x < 1 else self.b_pill

    def draw_brand(self, fr: Image.Image, t_abs: float) -> Image.Image:
        """The persistent RapidTradeView pill, drawn over the finished frame (after whips and smashes, so it never moves)."""
        if fr.mode != "RGBA":
            fr = fr.convert("RGBA")
        fr.alpha_composite(self.brand_sprite(t_abs), (int(self.brand_box[0]), int(self.brand_box[1])))
        return fr

    def _brand_sample(self, si, t, t_abs, cam):
        """On a PAYOFF frame: where our own header's brand (the capture's target "RapidTradeView") sits on screen."""
        sh = self.shots[si]
        if sh.get("kind") != "PAYOFF":
            return
        for el in sh.get("els", []):
            if el.get("t") not in ("screen", "card", "site"):
                continue
            sc = self.st.screens[el["name"]]
            tg = next((x for x in sc["meta"].get("targets", []) if x.get("text") == cr.BRAND), None)
            if tg is None:
                continue
            if el["t"] == "site":            # our header on the strip: readable while the scroll has it inside the window
                corners, _ = self._target_world(si, cr.BRAND, t, el)
                pts = np.array([cam.p(q) for q in corners])
                win = self._bbox([cam.p(q) for q in self.site_window(si, el, t)])
                box = self._bbox(pts)
                self.brand_samples.append({"t": round(t_abs, 3), "screen": el["name"],
                                           "h": round(float(np.linalg.norm(pts[3] - pts[0])), 1),
                                           "inside": bool(Q._in(box, Q._cut(win, [0, 0, W, H]))), "in_crop": True,
                                           "in_text": cr.BRAND in sc["meta"].get("visible_text", "")})
                return
            bx, by, bw, bh = tg["box"]
            crop = el.get("crop")
            in_crop = (not crop) or (crop[0] <= bx and crop[1] <= by and bx + bw <= crop[2] and by + bh <= crop[3])
            corners, _ = self._target_world(si, cr.BRAND, t, el)
            pts = np.array([cam.p(q) for q in corners])
            hh = float(np.linalg.norm(pts[3] - pts[0]))
            inside = bool(pts[:, 0].min() >= 0 and pts[:, 0].max() <= W and pts[:, 1].min() >= 0 and pts[:, 1].max() <= H)
            self.brand_samples.append({"t": round(t_abs, 3), "screen": el["name"], "h": round(hh, 1), "inside": inside,
                                       "in_crop": bool(in_crop), "in_text": cr.BRAND in sc["meta"].get("visible_text", "")})
            return

    @staticmethod
    def _bbox(pts) -> list[float]:
        a = np.asarray(pts, float)
        return [float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max())]

    def card_corners(self, si, el, t):
        """World corners of a card's real capture (the shown crop) at shot time t; for a site screen, its window."""
        if el.get("t") == "site":
            return self.site_window(si, el, t)
        sc = self.st.screens[el["name"]]
        cw, ch = sc["size"]
        crop = el.get("crop") or (0, 0, cw, ch)
        spr = self.screen_sprite(el)
        q, rot_deg, k, _a = self.el_pose(si, el, t)
        _img, anchor, kk, off, res = spr
        pts = []
        for (sx, sy) in ((0, 0), (crop[2] - crop[0], 0), (crop[2] - crop[0], crop[3] - crop[1]), (0, crop[3] - crop[1])):
            u = np.array([off[0] + sx * kk, off[1] + sy * kk])
            pts.append(np.array(q, float) + (k / res) * (rot(rot_deg) @ (u - np.array(anchor, float))))
        return pts

    def _pill_sample(self, si, t, t_abs, cam):
        """Every rendered frame with a real card: does a card that is not entering or leaving sit under the brand pill?"""
        sh = self.shots[si]
        x0, y0, x1, y1 = self.brand_box
        for el in sh.get("els", []):
            if el.get("t") not in ("screen", "card", "site"):
                continue
            pts = np.array([cam.p(q) for q in self.card_corners(si, el, t)])
            bx0, by0 = pts.min(0)
            bx1, by1 = pts.max(0)
            if el["t"] == "site":                        # the window's rim is part of what must stay clear of the pill
                bx0, by0, bx1, by1 = bx0 - SITE_RIM, by0 - SITE_RIM, bx1 + SITE_RIM, by1 + SITE_RIM
            ov = max(0.0, min(x1, bx1) - max(x0, bx0)) * max(0.0, min(y1, by1) - max(y0, by0))
            self.pill_samples.append({"t": round(t_abs, 3), "screen": el["name"], "overlap_px": round(float(ov)),
                                      "moving": self.el_moving(si, el, t),
                                      "card_box": [round(float(v)) for v in (bx0, by0, bx1, by1)]})

    def _site_sample(self, si, t, t_abs, cam):
        """A PAYOFF frame of a site screen, for the gates site_card_whole, card_width, no_overlap and key_in_place: the
        window, the card's DOM box and its parts where the scroll has them, the key while it is outlined, the captions
        and Pip's head (frame px)."""
        sh = self.shots[si]
        if sh.get("kind") != "PAYOFF":
            return
        for el in sh.get("els", []):
            if el.get("t") != "site":
                continue
            boxes = self.st.screens[el["name"]]["meta"].get("boxes") or {}
            if "card" not in boxes:
                continue

            def on_screen(b):
                return self._bbox([cam.p(q) for q in self.site_world(si, el, t, (b[0], b[1], b[0] + b[2], b[1] + b[3]))])

            hl = next((e for e in sh["els"] if e.get("t") == "highlight" and t >= float(e.get("at", 0.9))), None)
            key = key_h = None
            if hl:
                corners, _ = self._target_world(si, hl["target"], t, el)
                pts = np.array([cam.p(q) for q in corners])
                key, key_h = self._bbox(pts), float(np.linalg.norm(pts[3] - pts[0]))
            self.site_samples.append({
                "t": round(t_abs, 3), "shot": si + 1, "moving": self.el_moving(si, el, t),
                "win": self._bbox([cam.p(q) for q in self.site_window(si, el, t)]), "card": on_screen(boxes["card"]),
                "parts": {n: on_screen(b) for n, b in boxes.items() if n != "card"},
                "key": key, "key_h": key_h, "caps": self.caption_boxes(si, t_abs), "peek": self.peek_box(si, t_abs),
                "scroll_px": round(self.site_scroll(el, t))})

    def end_extent(self) -> dict:
        """The end card's widest moment: the right edges of the wordmark and the search box (frame px) over the card."""
        worst = {"wordmark": 0.0, "search": 0.0}
        n = int(round(END_S * FPS))
        for f in range(n):
            v = f / FPS
            gs, ws = self.end_scales(v)
            worst["wordmark"] = max(worst["wordmark"], W / 2 + self.e_pill.size[0] / 2 * ws)
            worst["search"] = max(worst["search"], W / 2 + self.search_box(v).size[0] / 2 * gs)
        return {k: round(v, 1) for k, v in worst.items()}

    # ------------------------------------------------------------------------------------------ end card
    def _end_build(self):
        self.e_pill = cr.pill(cr.BRAND, END_BRAND_SIZE, round(END_BRAND_SIZE * 0.65), round(END_BRAND_SIZE * 0.4))
        self.e_sweep = cr.Sweep(self.e_pill, 0.38, 0.09)
        self.e_site = cr.text_img(cr.SITE, font("semi", 46), (200, 200, 212))
        self.e_disc = cr.text_img(cr.DISCLAIMER, font("regular", 48), cr.DISC_GREY)
        gx, gy = np.meshgrid(np.linspace(0, 1, 270), np.linspace(0, 1, 480))
        self.e_shim = type("S", (), {})()
        self.e_shim.p = type("P", (), {"body_end": 1e9})()
        self.e_shim.gx, self.e_shim.gy = gx, gy
        for role, txt, cy in (("end_brand", cr.BRAND, 860), ("end_search", SEARCH_TEXT, 1040), ("end_site", cr.SITE, 1190),
                              ("end_disclaimer", cr.DISCLAIMER, 1330)):
            self.texts.append({"role": role, "text": txt, "box": (540 - 390, cy - 60, 540 + 390, cy + 60)})

    def search_box(self, v):
        n = len(SEARCH_TEXT)
        k = int(round(n * min(1.0, max(0.0, (v - 0.2) / 0.55))))
        key = ("endsearch", k, int(v * 2) % 2)
        if key in self.cache:
            return self.cache[key]
        w, h = 760, 112
        img = Image.new("RGBA", (w + 8, h + 8), C.CYAN + (0,))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((4, 4, w + 4, h + 4), radius=56, fill=(255, 255, 255, 20), outline=C.CYAN + (255,), width=3)
        cx, cy = 62, (h + 8) // 2
        d.ellipse((cx - 22, cy - 26, cx + 22, cy + 18), outline=(235, 238, 245, 255), width=6)
        d.line((cx + 15, cy + 12, cx + 30, cy + 27), fill=(235, 238, 245, 255), width=6)
        f = font("semi", 54)
        txt = SEARCH_TEXT[:k]
        d.text((112, cy), txt, font=f, fill=(235, 238, 245, 255), anchor="lm")
        if int(v * 4) % 2 == 0 or k < n:
            x = 112 + f.getlength(txt) + 6
            d.rectangle((x, cy - 30, x + 3, cy + 30), fill=C.CYAN + (255,))
        self.cache[key] = img
        return img

    def end_scales(self, v: float) -> tuple[float, float]:
        """(the card's slow push, the wordmark's scale: pop in, then a pulse once the search has typed)."""
        gs = 1 + 0.06 * min(1.0, v / END_S)
        k = eob(v / 0.36, 1.9)
        pulse = 1 + END_PULSE * math.sin(2 * math.pi * 1.3 * (v - 0.75)) if v > 0.75 else 1.0
        return gs, gs * (0.6 + 0.4 * k) * pulse

    def end_frame(self, v: float) -> Image.Image:
        fr = cr.Scenes.background(self.e_shim, v)
        gs, ws = self.end_scales(v)
        Cc = (W / 2, H / 2)

        def at(y):
            return Cc[1] + (y - Cc[1]) * gs

        blink = 1.4 < v < 1.4 + 3 / FPS
        key = ("endhead", blink)
        if key not in self.cache:
            self.cache[key] = C.head_only("pip", "smug", 300, blink)
        head, _ = self.cache[key]
        bob = 24 * math.sin(2 * math.pi * 1.1 * v)
        tilt = 7 * math.sin(2 * math.pi * 0.8 * v)
        hk = ("endhead_r", blink, round(tilt * 2) / 2)
        if hk not in self.cache:
            self.cache[hk] = head.rotate(hk[2], Image.BICUBIC, expand=True, fillcolor=C.CLEAR)
        cr.put(fr, self.cache[hk], W / 2, at(610 + bob), min(1.0, v / 0.15), gs * (0.8 + 0.2 * eob(v / 0.3)))
        x = cr.prog(v, 0.55, 1.2) if v < 1.4 else ((v - 1.5) % 0.8) / 0.55      # then a sweep every 0.8 s to the end
        cr.put(fr, self.e_sweep.at(x), W / 2, at(860), cr.prog(v, 0, 3 / FPS), ws)
        cr.put(fr, self.search_box(v), W / 2, at(1040), cr.prog(v, 0.1, 0.3), gs)
        e = ease_out(cr.prog(v, 0.12, 0.45))
        cr.put(fr, self.e_site, W / 2, at(1190 + 40 * (1 - e)), e, gs)
        e = ease_out(cr.prog(v, 0.0, 0.3))
        cr.put(fr, self.e_disc, W / 2, at(1330 + 30 * (1 - e)), e, gs)
        return fr

    # ------------------------------------------------------------------------------------------ frames
    def shot_frame(self, si: int, t_abs: float, sample: bool = False) -> Image.Image:
        if si == self.n - 1:
            return self.end_frame(t_abs - self.tl.end_start)
        t = t_abs - self.tl.starts[si]
        cam = self.camera(si, t)
        # a site screen never shakes: it stands a few px under the brand pill and above the captions, pixels untouched
        site = any(e.get("t") == "site" for e in self.shots[si].get("els", []))
        dx, dy, dth = (0.0, 0.0, 0.0) if site else self.shake(t_abs)
        cam.d = np.array([dx, dy])
        cam.th += dth
        fr = self.background(si, t, t_abs, cam)
        self.draw_els(fr, si, t, t_abs, cam)
        self.overlays(fr, si, t_abs)
        if sample:
            self._key_sample(si, t, t_abs, cam)
            self._brand_sample(si, t, t_abs, cam)
            self._pill_sample(si, t, t_abs, cam)
            self._site_sample(si, t, t_abs, cam)
        return fr

    def _key_sample(self, si, t, t_abs, cam):
        sh = self.shots[si]
        mv = sh.get("move") or {}
        if sh.get("kind") != "PAYOFF" or not sh.get("key_number"):
            return
        corners, _ = self._target_world(si, sh["key_number"], t)
        pts = np.array([cam.p(q) for q in corners])
        hh = float(np.linalg.norm(pts[3] - pts[0]))
        names = sh["key_number"] if isinstance(sh["key_number"], list) else [sh["key_number"]]
        cards = [e for e in sh["els"] if e.get("t") in ("screen", "card", "site") and all(any(
            x["text"] == nm for x in self.st.screens[e["name"]]["meta"]["targets"]) for nm in names)]
        cards.sort(key=lambda e: not e.get("main", True))
        card_w = 0.0
        if cards and not self.el_moving(si, cards[0], t):
            cc = np.array([cam.p(q) for q in self.card_corners(si, cards[0], t)])
            card_w = float(np.linalg.norm(cc[1] - cc[0]))
            cb = (self.st.screens[cards[0]["name"]]["meta"].get("boxes") or {}).get("card")
            if cards[0]["t"] == "site" and cb:           # the card inside the window, not the window
                cc = np.array([cam.p(q) for q in self.site_world(si, cards[0], t, (cb[0], cb[1], cb[0] + cb[2], cb[1] + cb[3]))])
                card_w = float(np.linalg.norm(cc[1] - cc[0]))
        self.key_samples.append({"t": round(t_abs, 3), "h": round(hh, 1), "card_w": round(card_w, 1),
                                 "box": [round(float(v)) for v in
                                         (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())]})

    def frame(self, t_abs: float) -> Image.Image:
        fi = int(round(t_abs * FPS))
        si = self.tl.shot_at(t_abs + 1e-6)
        fr = self.shot_frame(si, t_abs, sample=not self._sampled.get(fi))
        self._sampled[fi] = True
        st, en = self.tl.starts[si], self.tl.ends[si]
        fin = int(round(st * FPS))
        fout = int(round(en * FPS))
        nxt = si + 1
        # whip out of this shot / into this shot
        if nxt < self.n and self.shots[nxt].get("transition_in") == "whip" and fout - fi <= 2:
            o = {2: 0.0, 1: 0.35, 0: 0.80}.get(fout - 1 - fi, 0.0)
            if o > 0:
                inc = self.shot_frame(nxt, en)
                fr = self._whip(fr, inc, o, out=True)
        if self.shots[si].get("transition_in") == "whip" and si > 0 and fi - fin <= 1:
            o = {0: 0.80, 1: 0.35}[fi - fin]
            prev = self.shot_frame(si - 1, st - 1 / FPS)
            fr = self._whip(prev, fr, 1 - o, out=True)
        if nxt < self.n and self.shots[nxt].get("transition_in") == "smash" and fout - fi <= 4:
            m = {4: 1.0, 3: 1.25, 2: 1.6, 1: 2.2}[fout - fi]
            al = {4: 1.0, 3: 0.8, 2: 0.6, 1: 0.4}[fout - fi]
            if m > 1:
                w2, h2 = W / m, H / m
                fr = fr.crop((int(W / 2 - w2 / 2), int(H / 2 - h2 / 2), int(W / 2 + w2 / 2), int(H / 2 + h2 / 2))).resize((W, H), Image.BILINEAR)
            if al < 1:
                fr = Image.blend(Image.new("RGBA", (W, H), C.INK + (255,)), fr.convert("RGBA"), al)
        fr = self.draw_brand(fr, t_abs)
        return fr.convert("RGB")

    @staticmethod
    def _whip(a: Image.Image, b: Image.Image, o: float, out=True) -> Image.Image:
        """a slides left by o*W while b follows from the right; horizontal motion blur (7 taps across +-0.06 W)."""
        sh = int(o * W)
        canvas = Image.new("RGB", (W, H))
        canvas.paste(a.convert("RGB"), (-sh, 0))
        canvas.paste(b.convert("RGB"), (W - sh, 0))
        arr = np.asarray(canvas).astype(np.float32)
        offs = np.linspace(-0.06 * W, 0.06 * W, 7).astype(int)
        blur = np.mean([np.roll(arr, k, axis=1) for k in offs], 0)
        return Image.fromarray(blur.astype(np.uint8), "RGB")


# =============================================================================================== audio mix
def build_audio(reel: Reel, tl: Timeline, out: Path, ffmpeg: str) -> tuple[Path, dict, dict]:
    n = int(round(tl.total * SR))
    vo = np.zeros(n)
    for t0, clip, u in tl.vo_clips:
        i0 = int(round(t0 * SR))
        rms = float(np.sqrt(np.mean(clip ** 2))) or 1.0
        g = 10 ** (-20 / 20) / rms
        seg = clip[: max(0, n - i0)] * g
        fade = min(len(seg), int(0.01 * SR))
        if fade:
            seg[:fade] *= np.linspace(0, 1, fade)
            seg[-fade:] *= np.linspace(1, 0, fade)
        vo[i0:i0 + len(seg)] += seg
    fx = np.zeros(n)
    for k, (te, kind, data) in enumerate(reel.events):
        y = sfx(data["sfx"], seed=k + 1) * 10 ** (-12 / 20) * float(data.get("gain", 1.0))
        i0 = int(round(te * SR))
        if i0 < n:
            fx[i0:i0 + len(y)] += y[: n - i0]
    cuts = [s for s in tl.starts[1:]]
    hook_end = cuts[0] if cuts else 1.0
    beats = [c for c in cuts[1:] if c < tl.end_start - 1e-6]
    figure = [k for k, c in enumerate(beats) if reel.shots[tl.shot_at(c + 1e-6)].get("kind") == "PAYOFF"]
    mix, music, instruments, score = vsco_score.compose(hook_end, beats, figure, tl.end_start, tl.total)
    mix = mix[:n] if len(mix) >= n else np.vstack([mix, np.zeros((n - len(mix), 2))])
    # duck the bed under the voice (50 ms RMS, 30 ms attack, 250 ms release)
    win = int(0.05 * SR)
    env = np.sqrt(np.convolve(vo ** 2, np.ones(win) / win, "same"))
    active = (env > 10 ** (-38 / 20)).astype(float)
    g = np.empty(n)
    a_att, a_rel = math.exp(-1 / (0.03 * SR)), math.exp(-1 / (0.25 * SR))
    blk = 48
    cur = 0.0
    for i in range(0, n, blk):
        target = active[i:i + blk].max()
        coef = a_att if target > cur else a_rel
        cur = target + (cur - target) * coef ** blk
        g[i:i + blk] = cur
    duck_db = -9.0
    bed_db = -11.0
    gain = 10 ** ((bed_db + duck_db * g) / 20)
    total = mix * gain[:, None] + (vo + fx)[:, None]
    total = 0.95 * np.tanh(total / 0.95)
    tmp = out / "mix_pre.wav"
    write_wav(tmp, np.clip(total, -1, 1))
    meas = loudnorm_measure(tmp, ffmpeg)
    for _ in range(4):
        gdb = TARGET_LUFS - meas["I"]
        total = total * 10 ** (gdb / 20)
        total = limiter(total, 10 ** (-2.0 / 20))
        write_wav(tmp, np.clip(total, -1, 1))
        meas = loudnorm_measure(tmp, ffmpeg)
        if abs(meas["I"] - TARGET_LUFS) < 0.4 and meas["TP"] <= -1.5:
            break
    wav = out / "mix.wav"
    os.replace(tmp, wav)
    write_wav(out / "vo.wav", np.clip(vo, -1, 1), ch=1)
    score["wav_sha256"] = cr.sha256(wav)
    voinfo = {"vo_rms_db": round(20 * math.log10(float(np.sqrt(np.mean(vo ** 2))) + 1e-12), 2),
              "vo_active_s": round(float(active.sum()) / SR, 2), "mix_measure": meas,
              "voice_onset_s": round(min(w.start for w in tl.words), 3) if tl.words else None}
    return wav, {"music": music, "instruments": instruments, "score": score}, voinfo


# =============================================================================================== QA
def text_gates(st: Story, tl: Timeline, reel: Reel, now: dt.datetime | None = None) -> tuple[dict, dict]:
    s, d = {}, {}
    item = st.item
    metas = {n: sc["meta"] for n, sc in st.screens.items()}
    end_i = len(st.shots) - 1
    script = " ".join((sh.get("vo") or "").strip() for sh in st.shots[:end_i] if (sh.get("vo") or "").strip())
    all_vo = " ".join((sh.get("vo") or "").strip() for sh in st.shots if (sh.get("vo") or "").strip())
    chunks = [c["text"] for c in tl.chunks]
    s["caption_verbatim"], d["caption_verbatim"] = Q.caption_gate(chunks, script)
    # the fact phrase: read aloud, or shown whole on a receipt card long enough to read
    shown = {}
    for si, sh in enumerate(st.shots):
        for el in sh.get("els", []):
            if el.get("t") == "receipt":
                dur = tl.ends[si] - tl.starts[si] - float((el.get("enter") or {}).get("dur", 0.0))
                shown[el["text"]] = shown.get(el["text"], 0.0) + dur
    long_enough = [t_ for t_, dur in shown.items() if dur >= RECEIPT_MIN_S]
    if st.feature:                         # a feature short: the phrase is on today's capture, and read aloud
        s["fact_phrase"], d["fact_phrase"] = Q.feature_fact_gate(st.doc["fact_phrase"], metas, script)
        s["feature_capture"], d["feature_capture"] = Q.feature_capture_gate(st.feature, metas,
                                                                            now or dt.datetime.now(dt.timezone.utc))
        ok_f, det_f = Q.feature_story_gate(st.doc, st.feature, metas)
        import make_feature_story as F          # the generator itself: the story must be the one it writes (no cycle: F
        drift = F.story_drift(st.doc, st.feature, metas)       # does not import this module)
        s["feature_story"], d["feature_story"] = ok_f and not drift, {**det_f, "differs_from_generator": drift}
    else:
        s["fact_phrase"], d["fact_phrase"] = Q.fact_phrase_gate(st.doc["fact_phrase"], item, script, long_enough)
    d["fact_phrase"]["receipt_s"] = {k: round(v, 2) for k, v in shown.items()}
    spoken = " ".join(u["spoken"] for u in tl.utts)
    drawn = {f"{x['role']}:{i}": x["text"] for i, x in enumerate(reel.texts)}
    texts = {"vo_script": all_vo, **drawn}
    ok_w, d_w = Q.numbers_gate(texts, Q.allowed_set(item))
    ok_s, d_s = Q.numbers_gate({"spoken": spoken}, Q.allowed_set(item), words=False)
    s["numbers_verbatim"], d["numbers_verbatim"] = ok_w and ok_s, {**d_w, "spoken": d_s}
    texts = {**texts, "spoken": spoken}
    s["weekdays"], d["weekdays"] = Q.weekday_gate({"vo_script": all_vo, **drawn}, item, st.post_date)
    lines = [{"line": (sh.get("vo") or "").strip(), "claim": sh.get("claim"), "shot": i + 1}
             for i, sh in enumerate(st.shots[:end_i]) if (sh.get("vo") or "").strip()]
    s["claim_lines"], d["claim_lines"] = Q.claim_lines_gate(lines, item, st.post_date)
    used_say = {}
    for sh in st.shots:
        say = {**st.say, **(sh.get("say") or {})}
        for w in (sh.get("vo") or "").split():
            if w in say:
                used_say[w] = say[w]
    s["spoken_numbers"], d["spoken_numbers"] = Q.spoken_numbers_gate(used_say)
    scr_ok, scr_d = True, {}
    for name, sc in st.screens.items():
        # a feature capture: the numbers the PNG shows (inside_text); the wide visible_text also lists lines that only
        # touch the band, and those are not on screen
        shown = Q.shown_text(sc["meta"]) if st.feature else sc["meta"].get("visible_text", "")
        ok, det = Q.screen_numbers_gate(shown, item, st.ack.get(name, {}))
        scr_ok &= ok
        scr_d[name] = det
    s["screen_numbers"], d["screen_numbers"] = scr_ok, scr_d
    vis = {f"screen:{n}": sc["meta"].get("visible_text", "") for n, sc in st.screens.items()}
    # a feature short: the wider source list and look-alike letters, on what is drawn, captioned, SPOKEN and captured
    s["no_provider_names"], d["no_provider_names"] = (Q.vendor_gate if st.feature else Q.provider_gate)({**texts, **vis})
    if st.feature:
        adv = {k: Q.advice_hits(v) for k, v in texts.items()}
        adv = {k: v for k, v in adv.items() if v}
        s["no_advice"], d["no_advice"] = not adv, {"found": adv}
    s["banned_words"], d["banned_words"] = Q.banned_gate({**texts, **vis}, st.banned)
    end_vo = (st.shots[-1].get("vo") or "").strip()
    s["disclaimer_text"] = end_vo.endswith(cr.DISCLAIMER) and any(x["role"] == "end_disclaimer" and x["text"] == cr.DISCLAIMER
                                                                     for x in reel.texts)
    d["disclaimer_text"] = {"end_vo": end_vo}
    miss = {}
    for role, txt, f in (("captions", script, font("black", CAPTION_SIZE)), ("bubbles", " ".join(x["text"] for x in reel.texts if x["role"] == "bubble"), font("black", 76)),
                         ("chips", " ".join(x["text"] for x in reel.texts if x["role"] == "chip"), font("black", 64)),
                         ("end", " ".join(END_TEXTS), font("semi", 54))):
        m = cr.missing_glyphs(txt, f)
        if m:
            miss[role] = m
    s["glyphs"], d["glyphs"] = not miss, {"missing": miss, "fonts": dict(cr.FONTS_USED)}
    bad, rail = [], []
    for x in reel.texts:
        if x.get("box") is None:                # drawn inside a moving element (feed, phone, receipt): no fixed box
            continue
        x0, y0, x1, y1 = x["box"]
        if not (y0 >= cr.SAFE_TOP and y1 <= cr.SAFE_BOTTOM and x0 >= 0 and x1 <= W):
            bad.append([x["role"], x["text"], [round(v) for v in x["box"]]])
        if y1 > cr.RAIL_Y and x1 > cr.RAIL_X:
            rail.append([x["role"], x["text"]])
    s["safe_zones"], d["safe_zones"] = not bad and not rail, {"outside": bad, "under_right_rail": rail}
    # screenshots are the real captures
    real = {}
    ok_all = True
    day = st.doc["item_id"][:10]
    want_urls = {st.feature["url"]} if st.feature else Q.item_page_urls(item)
    for name, sc in st.screens.items():
        m = sc["meta"]
        sha = cr.sha256(sc["png"])
        ok = (sc["fmt"] == "PNG" and sha == m.get("sha256") and list(sc["size"]) == list(m.get("png_size", []))
              and str(m.get("captured_at", ""))[:10] == day and re.sub(r"[?#].*$", "", m.get("url", "")) in want_urls)
        real[name] = {"png": str(sc["png"]), "sha256": sha, "sidecar_sha256": m.get("sha256"), "captured_at": m.get("captured_at"),
                      "url": m.get("url"), "ok": ok}
        ok_all &= ok
    s["screenshot_real"], d["screenshot_real"] = ok_all, real
    # structure
    durs = [round(e - b, 3) for b, e in zip(tl.starts, tl.ends)]
    kinds = [sh.get("kind") for sh in st.shots]
    site = any(e.get("t") == "site" for sh in st.shots for e in sh.get("els", []))     # a site screen may run longer
    pay_max, pay_window = (PAYOFF_MAX_SITE, PAYOFF_WINDOW_SITE) if site else (PAYOFF_MAX, PAYOFF_WINDOW)
    bad_len = [i + 1 for i, (dd, k) in enumerate(zip(durs[:-1], kinds[:-1]))
               if not (SHOT_RANGE[0] - 1e-6 <= dd <= (pay_max if k == "PAYOFF" else HOOK_MAX if k == "HOOK" else SHOT_RANGE[1]) + 1e-6)]
    first_pay = next((tl.starts[i] for i, k in enumerate(kinds) if k == "PAYOFF"), None)
    last_pay = max((tl.ends[i] for i, k in enumerate(kinds) if k == "PAYOFF"), default=None)
    window = (last_pay - first_pay) if first_pay is not None else 0.0
    screen_s = sum(dd for dd, sh in zip(durs, st.shots) if any(e.get("t") in ("screen", "card", "site") for e in sh.get("els", [])))
    onset = min(w.start for w in tl.words)
    s["structure"] = (SHOTS_RANGE[0] <= len(st.shots) <= SHOTS_RANGE[1] and not bad_len and abs(durs[-1] - END_S) < 1e-6
                      and kinds[-1] == "END" and pay_window[0] <= window <= pay_window[1] and screen_s >= SCREEN_MIN_S
                      and onset <= 0.10 and tl.end_vo_finish <= 2.7)
    d["structure"] = {"shots": len(st.shots), "durations": durs, "out_of_range": bad_len,
                      "payoff_window_s": round(window, 2), "payoff_window_range": list(pay_window), "payoff_shot_max_s": pay_max,
                      "real_screen_s": round(screen_s, 2), "first_payoff_at": round(first_pay or -1, 2),
                      "first_payoff_share": round((first_pay or 0) / tl.total, 3), "voice_onset_s": round(onset, 3),
                      "end_vo_finishes_s": round(tl.end_vo_finish, 2), "kinds": kinds,
                      "note": "first_payoff_share is reported, not gated"}
    # a character on screen at least every CHAR_GAP_MAX seconds (els pip/dale, a PEEK, or the end card's head)
    gap = worst = 0.0
    worst_at = None
    for i, sh in enumerate(st.shots):
        has = i == end_i or bool(sh.get("peek")) or any(e.get("t") in ("pip", "dale", "search_phone") for e in sh.get("els", []))
        gap = 0.0 if has else gap + durs[i]
        if gap > worst:
            worst, worst_at = gap, i + 1
    s["character_on_screen"] = worst <= CHAR_GAP_MAX
    d["character_on_screen"] = {"longest_gap_s": round(worst, 2), "ends_at_shot": worst_at, "limit": CHAR_GAP_MAX}
    # the hook: a close character at frame 0 (not top-down), and an item number on screen by HOOK_NUMBER_BY
    sh0 = st.shots[0]
    cam0 = reel.camera(0, 0.0)
    widths, flipped = [], False
    for el in sh0.get("els", []):
        if el.get("t") in ("pip", "dale"):
            el["_si"] = 0
            img, _anc, _sq = reel.char_sprite(el, 0.0, 0.0)
            bb = img.getbbox() or (0, 0, 0, 0)
            (_x, _y), r0, k0, _a = reel.el_pose(0, el, 0.0)
            widths.append(round((bb[2] - bb[0]) * cam0.s * k0 / W, 3))
            flipped |= abs(((r0 + 180) % 360) - 180) > 60
    allowed = Q.allowed_set(item)
    num_at = [c["start"] for c in tl.chunks if any(n in allowed for n in Q.find_numbers(c["text"]))]
    for i, sh in enumerate(st.shots):
        c = sh.get("chip")
        if c and any(n in allowed for n in Q.find_numbers(c["text"])):
            num_at.append(c["_t0"])
    first_num = min(num_at) if num_at else None
    s["hook"] = bool(widths) and max(widths) >= HOOK_CHAR_W and not flipped and first_num is not None and first_num <= HOOK_NUMBER_BY
    d["hook"] = {"char_width_share": widths, "upside_down": flipped, "first_item_number_s": None if first_num is None else round(first_num, 2),
                 "limits": {"char_width_share": HOOK_CHAR_W, "number_by_s": HOOK_NUMBER_BY}}
    # the brand, said early and late; one situation, one punchline
    s["brand_spoken"], d["brand_spoken"] = Q.brand_spoken_gate([(w.text, w.start) for w in tl.words], tl.total)
    s["one_idea"], d["one_idea"] = Q.one_idea_gate(st.shots, tl.total)
    # captions stay off faces, held props, bubbles, chips, the key number, the receipt and the phone
    s["caption_occlusion"], d["caption_occlusion"] = Q.occlusion_gate(reel.occlusion_samples())
    # caption sync: onset 1 frame before its first word
    off = [round((c["start"] - (c["w_start"] - 1 / FPS)) * FPS, 2) for c in tl.chunks]
    s["caption_sync"] = all(abs(o) <= 2 for k, o in enumerate(off) if k > 0)    # chunk 1 is on frame 0 by design
    d["caption_sync"] = {"max_frames_off": max((abs(o) for o in off), default=0), "chunks": len(off)}
    return s, d


def key_number_gate(reel: Reel, st: Story) -> tuple[bool, dict]:
    if st.feature:                         # a text of the real card, outlined where it stands
        ok, det = Q.key_target_gate(reel.key_samples, FPS, "site")
        det["targets"] = [sh["key_number"] for sh in st.shots if sh.get("key_number")]
        return ok, det
    good = [k for k in reel.key_samples if k["h"] >= 64 and 60 <= k["box"][0] and k["box"][2] <= 960 and 300 <= k["box"][1]
            and k["box"][3] <= 1400]
    secs = len(good) / FPS
    # the target on the screenshot is the item's figure in the page's own format
    vals = []
    for sh in st.shots:
        if sh.get("key_number"):
            vals.append(sh["key_number"])
    fig_ok = True
    want = Q.written_value(str(st.item.get("amount_text") or ""))
    for v in vals:
        got = Q.written_value(v)
        if want is not None and got is not None:
            fig_ok &= abs(round(got / 1e4) * 1e4 - want) <= 0.005 * want
    return secs >= 1.5 and fig_ok, {"readable_s": round(secs, 2), "samples": len(reel.key_samples), "targets": vals,
                                    "matches_item_figure": fig_ok,
                                    "min_h": min((k["h"] for k in reel.key_samples), default=None),
                                    "max_h": max((k["h"] for k in reel.key_samples), default=None)}


def video_gates(mp4: Path, reel: Reel, ffmpeg: str, ffprobe: str) -> tuple[dict, dict, np.ndarray]:
    s, d = {}, {}
    info = cr.probe(mp4, ffprobe)
    v = next((x for x in info.get("streams", []) if x.get("codec_type") == "video"), {})
    a = next((x for x in info.get("streams", []) if x.get("codec_type") == "audio"), None)
    dur = float(info.get("format", {}).get("duration") or 0)
    size = mp4.stat().st_size
    s["resolution"] = (v.get("width"), v.get("height")) == (W, H)
    s["duration"] = DURATION_RANGE[0] <= dur <= DURATION_RANGE[1]
    s["video_codec"] = v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p" and v.get("r_frame_rate") == f"{FPS}/1"
    s["audio_present"] = bool(a) and a.get("codec_name") == "aac"
    mean, peak = cr.volume(mp4, ffmpeg) if a else (None, None)
    s["audio_not_silent"] = mean is not None and peak is not None and mean > -40 and peak > -20
    s["audio_not_clipping"] = peak is not None and peak < -0.3
    s["file_size"] = 0 < size <= cr.MAX_BYTES
    meas = loudnorm_measure(mp4, ffmpeg) if a else {"I": None, "TP": None}
    s["loudness"] = meas["I"] is not None and LUFS_RANGE[0] <= meas["I"] <= LUFS_RANGE[1] and meas["TP"] <= TP_MAX
    d.update(resolution=[v.get("width"), v.get("height")], duration=round(dur, 3), duration_range=list(DURATION_RANGE),
             video_codec={k: v.get(k) for k in ("codec_name", "pix_fmt", "r_frame_rate")},
             audio_present=a and {k: a.get(k) for k in ("codec_name", "sample_rate", "channels")},
             audio_not_silent={"mean_db": mean, "max_db": peak}, audio_not_clipping={"max_db": peak},
             file_size={"bytes": size, "limit": cr.MAX_BYTES}, loudness={**meas, "range": list(LUFS_RANGE), "tp_max": TP_MAX})
    g = cr.grey_frames(mp4, ffmpeg, size=(216, 384))
    first = g[0]
    s["first_frame_not_blank"] = float(first.std()) >= 12
    d["first_frame_not_blank"] = {"std": round(float(first.std()), 2)}
    step = g[:: FPS // 2]
    mads = [float(np.abs(step[i + 1] - step[i]).mean()) for i in range(len(step) - 1)]
    s["motion_every_beat"] = bool(mads) and min(mads) > cr.MOTION_MIN_MAD
    d["motion_every_beat"] = {"min": round(min(mads), 3) if mads else None, "at_s": round(0.5 * int(np.argmin(mads)), 2) if mads else None}
    pair = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))
    run = best = 0
    best_at = 0
    for i, m in enumerate(pair):
        run = run + 1 if m < STATIC_MAD else 0
        if run > best:
            best, best_at = run, i
    s["no_static_run"] = best <= STATIC_RUN
    d["no_static_run"] = {"longest_pairs": best, "ends_at_s": round((best_at + 1) / FPS, 2), "limit": STATIC_RUN}
    # disclaimer really on screen on the last frame
    tt = (reel.frames - 1) / FPS
    full = cr.grey_at(mp4, ffmpeg, tt - 0.01)
    want = np.asarray(reel.frame(tt).convert("L"), np.float32)
    gs = 1 + 0.06 * min(1.0, (tt - reel.tl.end_start) / END_S)
    cy = H / 2 + (1330 - H / 2) * gs
    y0, y1 = int(cy - 40), int(cy + 40)
    x0, x1 = 200, 880
    region, ref = full[y0:y1, x0:x1], want[y0:y1, x0:x1]
    contrast = float(region.max() - np.median(region)) if region.size else 0.0
    corr = float(np.corrcoef(region.ravel(), ref.ravel())[0, 1]) if region.std() > 0 and ref.std() > 0 else 0.0
    s["disclaimer_on_screen"] = contrast >= 60 and corr >= cr.DISCLAIMER_MIN_CORR
    # the brand pill in every sampled decoded frame (every second, and the last frame)
    x0, y0, x1, y1 = (int(v) for v in reel.brand_box)
    inset = (y1 - y0) // 2
    ref = np.asarray(reel.b_pill.convert("L"), np.float32)[4:-4, inset:-inset]
    samples = []
    for ts in list(np.arange(0.0, tt, 1.0)) + [tt - 0.01]:
        g_ = cr.grey_at(mp4, ffmpeg, float(ts))
        c_, m_ = Q.region_match(g_[y0 + 4:y1 - 4, x0 + inset:x1 - inset], ref)
        samples.append({"t": float(ts), "corr": c_, "mad": m_})
    s["brand_pill"], d["brand_pill"] = Q.brand_pill_gate(samples)
    d["brand_pill"]["box"] = [x0, y0, x1, y1]
    d["disclaimer_on_screen"] = {"t": round(tt, 3), "contrast": round(contrast, 1), "corr_vs_planned": round(corr, 3)}
    return s, d, g


def contact_sheet(mp4: Path, ffmpeg: str, every: float, path: Path, tl: Timeline, shots) -> None:
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(mp4), "-an", "-vf", "scale=216:384:flags=area", "-f", "image2pipe",
                          "-c:v", "png", "-"], capture_output=True, check=True).stdout
    pngs = cr.split_pngs(raw)
    idx = list(range(0, len(pngs), max(1, int(round(every * FPS)))))
    if idx[-1] != len(pngs) - 1:
        idx.append(len(pngs) - 1)
    cols = 9
    rows = math.ceil(len(idx) / cols)
    tw, th, lab = 216, 384, 26
    sheet = Image.new("RGB", (cols * (tw + 6) + 6, rows * (th + lab + 6) + 6), (20, 20, 24))
    d = ImageDraw.Draw(sheet)
    f = font("semi", 18)
    for k, i in enumerate(idx):
        im = Image.open(io.BytesIO(pngs[i])).convert("RGB")
        x = 6 + (k % cols) * (tw + 6)
        y = 6 + (k // cols) * (th + lab + 6)
        sheet.paste(im, (x, y + lab))
        t = i / FPS
        si = tl.shot_at(t + 1e-6)
        d.text((x + 4, y + 3), f"{t:5.1f}s  #{si + 1} {shots[si].get('kind', '')}", font=f, fill=(220, 220, 230))
    sheet.save(path)


def frame_at(mp4: Path, ffmpeg: str, t: float) -> Image.Image:
    """One decoded frame of the video."""
    raw = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(mp4), "-an", "-frames:v", "1",
                          "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(raw)).convert("RGB")


def compare_sheet(mp4: Path, ffmpeg: str, st: Story, tl: Timeline, path: Path, scale: float = 0.75) -> dict:
    """compare.png of a feature short: the site capture of the card on the left (the strip's rows that hold the card, as
    captured), the decoded video frames that show it on the right (the top of the card, the end of the scroll when there
    is one, the outlined key), all at one scale: the card is as wide in the capture as in the frames, so the two can be
    laid over each other by eye. A capture taller than a frame wraps into columns."""
    pays = [(i, next(e for e in sh["els"] if e.get("t") == "site")) for i, sh in enumerate(st.shots)
            if sh.get("kind") == "PAYOFF" and any(e.get("t") == "site" for e in sh.get("els", []))]
    (ia, ea), (ib, eb) = pays[0], pays[-1]
    sc = st.screens[ea["name"]]
    meta = sc["meta"]
    card = meta["boxes"]["card"]
    k = float(ea["w"]) / sc["size"][0] * scale                     # sheet px per capture px
    pad = 6 * float(meta.get("dpr") or 3)
    y0, y1 = int(max(0, card[1] - pad)), int(min(sc["size"][1], card[1] + card[3] + pad))
    cap = sc["img"].crop((0, y0, sc["size"][0], y1))
    cap = cap.resize((round(cap.size[0] * k), round(cap.size[1] * k)), Image.LANCZOS)
    fh, fw = round(H * scale), round(W * scale)
    scr_a, scr_b = ea.get("scroll") or {}, eb.get("scroll") or {}
    hl = next((e for e in st.shots[ib]["els"] if e.get("t") == "highlight"), {})
    times = [("the card's top", tl.starts[ia] + max(0.45, 0.8 * float(scr_a.get("at", 0.6))))]
    if float(scr_a.get("dur", 0.0)) > 0 and scr_a.get("y0") != scr_a.get("y1"):
        times.append(("the end of the scroll", min(tl.ends[ia] - 0.04, tl.starts[ia] + float(scr_a["at"]) + float(scr_a["dur"]) + 0.12)))
    times.append(("the key, outlined in place", min(tl.ends[ib] - 0.1, tl.starts[ib] + float(hl.get("at", 0.6)) + 0.9)))
    frames = [(lab, t, frame_at(mp4, ffmpeg, t).resize((fw, fh), Image.LANCZOS)) for lab, t in times]
    cols = [cap.crop((0, y, cap.size[0], min(cap.size[1], y + fh))) for y in range(0, cap.size[1], fh)]
    gap, lab_h = 18, 44
    wide = sum(c.size[0] + gap for c in cols) + sum(fw + gap for _ in frames) + gap
    sheet = Image.new("RGB", (wide, fh + lab_h + gap), (16, 16, 20))
    d = ImageDraw.Draw(sheet)
    f = font("semi", 22)
    x = gap
    d.text((x, 10), f"site capture, phone width {meta.get('viewport', ['?'])[0]} CSS px, {meta.get('captured_at', '')}", font=f,
           fill=(170, 240, 200))
    for c in cols:
        sheet.paste(c, (x, lab_h))
        x += c.size[0] + gap
    for lab, t, im in frames:
        d.text((x, 10), f"video {t:.1f} s: {lab}", font=f, fill=(200, 200, 255))
        sheet.paste(im, (x, lab_h))
        x += fw + gap
    sheet.save(path)
    return {"png": str(path), "scale": scale, "capture_rows_px": [y0, y1], "frames_at_s": [round(t, 2) for _l, t in times]}


# =============================================================================================== main
def clean(o):
    """numpy scalars / tuples -> plain JSON values."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.generic):
        return o.item()
    return o


def fail(out: Path, item_id, why: str, gate: str = "inputs", code: int = 2) -> int:
    cr.write_json(out / "reel-qa.json", {"schema": "rtv-cartoon-reel-qa/1", "renderer": RENDERER, "item_id": item_id, "pass": False,
                                         "summary": {gate: False}, "details": {gate: why}})
    print(f"cartoon_reel: {why}", file=sys.stderr)
    return code


def run(a, out: Path, ctx: dict) -> int:
    try:
        st = Story(Path(a.story).resolve())
    except InputError as e:
        return fail(out, None, str(e))
    ctx["iid"] = st.doc["item_id"]
    try:
        ffmpeg, ffprobe = cr.tool("ffmpeg", a.ffmpeg_dir), cr.tool("ffprobe", a.ffmpeg_dir)
        ops = ops_dir()
        tts_python = a.tts_python or str(ops / "cache" / "tts-venv" / "Scripts" / "python.exe")
        if not Path(tts_python).is_file():
            raise InputError(f"the TTS venv python is missing: {tts_python}")
        if not vsco_score.CACHE.is_dir() and not os.environ.get("RTV_VSCO_DIR"):
            os.environ["RTV_VSCO_DIR"] = str(ops / "cache" / "vsco-2-ce-1.1.0")
        tl = Timeline(st, out / "tts", tts_python)
        reel = Reel(st, tl)
    except (InputError, FileNotFoundError) as e:
        return fail(out, ctx["iid"], str(e))
    print(f"cartoon_reel: {len(st.shots)} shots, {tl.total:.2f} s, {tl.frames} frames; rendering", file=sys.stderr)
    try:
        wav, music, voinfo = build_audio(reel, tl, out, ffmpeg)
    except vsco_score.SampleError as e:
        return fail(out, ctx["iid"], f"music: {e}", "music")
    mp4 = out / "reel_9x16.mp4"
    try:
        cr.encode(reel, wav, mp4, ffmpeg)
    except (RuntimeError, OSError) as e:
        return fail(out, ctx["iid"], f"render failed: {e}", "render")
    summary, details = text_gates(st, tl, reel)
    summary["key_number"], details["key_number"] = key_number_gate(reel, st)
    summary["payoff_brand"], details["payoff_brand"] = Q.payoff_brand_gate(reel.brand_samples, FPS)
    summary["pill_clear"], details["pill_clear"] = Q.pill_clear_gate(reel.pill_samples)
    if st.feature:                         # the site screen: the card whole, large, uncovered, the key in place
        summary["site_card_whole"], details["site_card_whole"] = Q.site_card_whole_gate(reel.site_samples, FPS, (W, H))
        summary["card_width"], details["card_width"] = Q.card_width_gate(reel.site_samples, FPS, frame_w=W)
        summary["no_overlap"], details["no_overlap"] = Q.no_overlap_gate(reel.site_samples)
        summary["key_in_place"], details["key_in_place"] = Q.key_in_place_gate(reel.site_samples, FPS, (W, H))
        if not (st.feature.get("site") or {}).get("header"):
            # the card is far below our page header: it cannot be in the window with the card (the pill carries the brand)
            summary["payoff_brand"] = True
            details["payoff_brand"] = {**details["payoff_brand"], "not_applicable": "the registry's site.header is false: "
                                       "the card stands far below the page header; brand_pill and brand_spoken gate the brand"}
    ext = reel.end_extent()
    summary["end_card_safe"] = max(ext.values()) <= RIGHT_BAND_X
    details["end_card_safe"] = {"right_edge_px": ext, "limit_px": RIGHT_BAND_X}
    summary["voice_present"] = bool(tl.words) and voinfo["vo_active_s"] >= 0.4 * tl.total and voinfo["vo_rms_db"] > -40
    details["voice_present"] = voinfo
    try:
        vs, vd, _ = video_gates(mp4, reel, ffmpeg, ffprobe)
    except (subprocess.CalledProcessError, ValueError, OSError, RuntimeError) as e:
        vs, vd = {"video_readable": False}, {"video_readable": f"{type(e).__name__}: {e}"}
    summary = {**vs, **summary}
    details = {**vd, **details}
    summary = {k: bool(v) for k, v in summary.items()}
    details = clean(details)
    ok = all(summary.values())
    cr.write_json(out / "reel-qa.json", {"schema": "rtv-cartoon-reel-qa/1", "renderer": RENDERER, "item_id": ctx["iid"], "pass": ok,
                                         "summary": summary, "details": details})
    try:
        contact_sheet(mp4, ffmpeg, a.sheet_every, out / "sheet.png", tl, st.shots)
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        print(f"cartoon_reel: sheet failed ({e})", file=sys.stderr)
    compare = None
    if st.feature:
        try:
            compare = compare_sheet(mp4, ffmpeg, st, tl, out / "compare.png")
        except (subprocess.CalledProcessError, OSError, ValueError, StopIteration) as e:
            print(f"cartoon_reel: compare sheet failed ({e})", file=sys.stderr)
    lic_path = HERE / "tts.py"
    used_numbers = sorted({n for x in [" ".join((sh.get("vo") or "") for sh in st.shots)] for n in Q.find_numbers(x)})
    cr.write_json(out / "reel.json", clean({
        "schema": "rtv-cartoon-reel/1", "renderer": RENDERER, "item_id": ctx["iid"], "qa_pass": ok,
        "facts_file": str(st.facts_path), "facts_text": st.item.get("facts_text"), "fact_phrase": st.doc["fact_phrase"],
        "format": "v4 one idea, brand always clear (owner verdict 2026-11-09)", "template": st.doc.get("template"),
        "feature": st.feature and {"id": st.feature["id"], "url": st.feature["url"], "answers": st.feature.get("answers"),
                                   "title": st.feature.get("title"), "post_note": st.feature.get("post_note"),
                                   "lands_on": st.feature.get("lands_on") or st.feature["url"],
                                   "spoken": (details.get("feature_story") or {}).get("spoken"),
                                   "values": (details.get("feature_story") or {}).get("values"),
                                   "page_sources": {p["id"]: p["text"] for p in st.item.get("phrasings") or []}},
        "brand": {"pill_box": list(reel.brand_box), "spoken_at_s": details.get("brand_spoken", {}).get("spoken_at_s")},
        "site_screen": st.feature and {"compare": compare, "card_width_px": [details.get("card_width", {}).get("min_w"),
                                                                             details.get("card_width", {}).get("max_w")],
                                       "scrolled": details.get("site_card_whole", {}).get("scrolled"),
                                       "strip_css": (st.screens[Q.PAGE]["meta"].get("strip") if Q.PAGE in st.screens else None)},
        "allowed_numbers": st.item.get("allowed_numbers"), "numbers_used": used_numbers, "post_date": st.post_date,
        "claims_for_human_check": (details.get("claim_lines") or {}).get("needs_human_check"),
        "screen_crops": {f"shot {i + 1}": {"screen": e["name"], "crop_px": e["crop"]} for i, sh in enumerate(st.shots)
                         for e in sh.get("els", []) if e.get("t") in ("screen", "card") and e.get("crop")},
        "story": {"path": str(st.path), "sha256": cr.sha256(st.path)},
        "files": {"reel_9x16.mp4": cr.sha256(mp4), "mix.wav": cr.sha256(wav)},
        "screens": {n: {"png": str(sc["png"]), "sha256": cr.sha256(sc["png"]), "url": sc["meta"].get("url"),
                        "captured_at": sc["meta"].get("captured_at")} for n, sc in st.screens.items()},
        "voice": {"engine": "Kokoro-82M v1.0 (hexgrad) via kokoro 0.9.4, local", "licence": "Apache-2.0 (weights, voices, code)",
                  "g2p_fallback": "espeak-ng (GPL-3.0) used as a local tool only, not distributed",
                  "script": str(lic_path), "voices": {k: v for k, v in st.voices.items()},
                  "utterances": [{"voice": u["voice_id"], "speed": u["speed"], "spoken": u["spoken"],
                                  "wav_sha256": cr.sha256(u["wav"])} for u in tl.utts]},
        **music,
        "seconds": details.get("duration"), "fps": FPS, "size": [W, H],
        "shots": [{"n": i + 1, "kind": sh.get("kind"), "set": sh.get("set"), "start": round(tl.starts[i], 3),
                   "dur": round(tl.ends[i] - tl.starts[i], 3), "vo": sh.get("vo", "")} for i, sh in enumerate(st.shots)],
        "captions": [{"text": c["text"], "start": round(c["start"], 3), "end": round(c["end"], 3)} for c in tl.chunks],
        "fonts": dict(cr.FONTS_USED)}))
    bad = [k for k, v in summary.items() if not v]
    print(f"cartoon_reel: {ctx['iid']}: {'QA passed' if ok else 'QA failed: ' + ', '.join(bad)} "
          f"({mp4.stat().st_size} bytes, {details.get('duration')} s)")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--story", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ffmpeg-dir")
    ap.add_argument("--tts-python")
    ap.add_argument("--sheet-every", type=float, default=1.5)
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name in ("reel_9x16.mp4", "reel.json", "reel-qa.json", "sheet.png", "compare.png", "mix.wav", "vo.wav"):
        (out / name).unlink(missing_ok=True)
    ctx = {"iid": None}
    try:
        return run(a, out, ctx)
    except InputError as e:
        return fail(out, ctx["iid"], str(e))
    except Exception as e:  # noqa: BLE001 - every failure leaves a reel-qa.json that says why
        import traceback
        traceback.print_exc()
        return fail(out, ctx["iid"], f"render error: {type(e).__name__}: {e}", "render")


if __name__ == "__main__":
    sys.exit(main())
