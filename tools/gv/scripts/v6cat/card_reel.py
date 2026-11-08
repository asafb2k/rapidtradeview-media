"""Card Reel renderer (rebuilt 2026-11-08 in this repo; the old growth-video tree is gone): one facts item + its 1200 x 630 Open
Graph card -> a 9:16 Instagram Reel with its own QA.

    card_reel.py --item ITEM.json --card CARD.png --out DIR [--ffmpeg-dir DIR]

ITEM.json is {"item": <facts item>, "banned_words": [...]} (written by tools/card_reel.py). The Reel (1080 x 1920, 30 fps,
H.264 yuv420p + AAC, 7-24 s; ~10 s for a 25-word facts_text):
  hook (0-1 s)  the item's headline figure (verbatim from facts_text) punched in huge on the dark brand background, its ticker
                and a short verbatim label already sliding in on frame 0, the brand pill (logo + name) on top; a hard cut.
  body          kinetic type: facts_text in word groups of at most 6 words, one group per beat (1.0-1.5 s, longer texts get
                more beats and a longer Reel), each group alone and centred in huge type, its words punching in one after
                another, figures cyan with an extra scale punch and a light sweep; the previous group shrinks to a small dim
                line above it. The card sits on top as a context header (cropped above its footer, never clipped), with a
                slow zoom and a pulse + sheen on every beat. Text below y=1100 stays left of the right-hand button rail.
  end (3 s)     a hard cut to the end card centred on the frame: the brand pill with the logo, "rapidtradeview.trade",
                "Not investment advice.", with a pop, a slow zoom and a light sweep.
  Music: an original score played from VSCO 2 Community Edition samples (CC0; vsco_score.py): string pad chords changing on
  the cuts, a piano note on every beat, glockenspiel on figure beats, timpani on the hook and the end card.
Every word on screen is facts_text (verbatim), the brand, the site or the disclaimer: nothing is invented (No Fallbacks).

Outputs in DIR: reel_9x16.mp4, reel.json (qa_pass, item_id, files sha256, card sha256, music, seconds), reel-qa.json (pass,
summary {gate: bool}, details), vsco-instruments.json (every sample used, with its sha256), music_bed.wav. Exit 0 only when
every gate passes; 1 = QA failed; 2 = unusable input or a render error (reel-qa.json says which, in every case).
Deterministic for the same inputs (no clock, no randomness; bitexact encode flags).
ffmpeg: $RTV_FFMPEG_DIR, then PATH, then the local essentials build.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))   # run with python -I: the script's folder is not on sys.path
import vsco_score  # noqa: E402

RENDERER = "rtv-card-reel/3"
W, H, FPS = 1080, 1920, 30
SAFE_TOP, SAFE_BOTTOM = 250, H - 400              # Instagram: keep key text out of the top 250 px and the bottom 400 px
RAIL_X, RAIL_Y = 960, 1100                        # Instagram's like/comment/share rail: text below RAIL_Y stays left of RAIL_X
HOOK_S, END_S = 1.0, 3.0                          # end card ~3 s, centred on the frame (owner pace rule 2026-09-28)
CUT_F = 4                                         # an outgoing layer is gone within 4 frames before a cut (no double exposure)
BEAT_MIN_S, BEAT_MAX_S, BODY_MIN_S = 1.0, 1.5, 5.0
GROUP_MAX_WORDS, GROUP_MAX_CHARS = 6, 46
MAX_BYTES = 30 * 1024 * 1024
DURATION_RANGE = (7.0, 24.0)
CARD_SIZE = (1200, 630)
CARD_CROP = (0, 28, 1200, 452)                    # the card above its divider + footer line ("From the ... scan. Not ... advice.")
HEAD_W = 760
HEAD_H = round(HEAD_W * (CARD_CROP[3] - CARD_CROP[1]) / (CARD_CROP[2] - CARD_CROP[0]))
HEAD_TOP = 262
TEXT_W = 800                                      # centred: x 140-940, clear of the right rail
PREV_CY, PREV_BOX = 652, (800, 112)
CUR_TOP, CUR_BOTTOM = 742, 1478
CUR_CY = (CUR_TOP + CUR_BOTTOM) / 2
BREATHE = 0.035
HOOK_CY = 900
BRAND, SITE, DISCLAIMER = "RapidTradeView", "rapidtradeview.trade", "Not investment advice."
MOTION_MIN_MAD = 0.6                              # mean |diff| (0-255 grey, 270 x 480) between frames 0.5 s apart
MAX_BEAT_GAP_S = 1.5
DISCLAIMER_MIN_CORR = 0.85
SR = vsco_score.SR

FFMPEG_FALLBACK = Path("C:/Users/USER/Downloads/ffmpeg-2024-05-02-git-71669f2ad5-essentials_build/bin")
FONTS = {
    "black": ["seguibl.ttf", "segoeuib.ttf", "arialbd.ttf"],
    "bold": ["segoeuib.ttf", "arialbd.ttf"],
    "semi": ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"],
    "regular": ["segoeui.ttf", "arial.ttf"],
}
FONT_DIRS = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path("C:/Windows/Fonts")]

# data providers never named on a public surface (owner 2026-10-19; mirrors tools/grok_review.py PROVIDER_WORDS)
PROVIDER_WORDS = ("yahoo", "yfinance", "finnhub", "stock twits", "ape wisdom", "quiver", "quiver quant", "polygon", "alpaca",
                  "tiingo", "iex", "zacks", "elbstream", "marketbeat", "factset", "google news", "vader", "cnbc",
                  "alpha vantage", "twelve data", "financial modeling prep", "intrinio", "marketstack", "unusual whales",
                  "capitol trades", "openinsider", "benzinga", "tipranks", "seeking alpha", "finviz", "barchart")
PROVIDER_RX = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(
    r"[\s_.-]*".join(map(re.escape, w.split())) for w in sorted(PROVIDER_WORDS, key=len, reverse=True)) + r")(?![A-Za-z0-9])",
    re.IGNORECASE)

MONEY = r"[\u2212\-+]?\$\d[\d,]*(?:\.\d+)?[KMBT]?(?:\s?[\u2013\-]\s?\$\d[\d,]*(?:\.\d+)?[KMBT]?)?"
PCT = r"[\u2212\-+]?\d+(?:\.\d+)?%"
FIGURE_RX = re.compile(rf"(?<![\w$])(?:{MONEY}|{PCT})")
ACCENT = (56, 225, 245)        # cyan: figures
GOOD = (52, 211, 120)          # green: beat / above / purchase
BAD = (248, 92, 92)            # red: miss / below / sale
WHITE = (255, 255, 255)
DISC_GREY = (200, 200, 212)    # #C8C8D4
GRAD = ((124, 58, 237), (34, 211, 238))  # brand purple -> cyan
BG = (9, 10, 13)

# the brand mark (green R into a rising arrow), from rapidtradeview shared/data/brand-mark.json (viewBox 1024): straight
# segments and three circular arcs, written out as points + (centre, radius, start deg, end deg) so PIL can fill it
MARK_OUTER = [(214, 237), (417, 237), ("arc", 417, 415, 178, -90.0, 72.55), (515, 629.44), (728.74, 415.7), (657.07, 379.18),
              (896.78, 325.44), (843.04, 565.15), (806.52, 493.48), (515, 785), (318, 588), (254, 588), (254, 785), (134, 785),
              (134, 317), ("arc", 214, 317, 80, 180.0, 270.0)]
MARK_HOLE = [(254, 357), (417, 357), ("arc", 417, 415, 58, -90.0, 90.0), (254, 473)]
MARK_BOX = (134, 237, 896.78, 785)
MARK_GREENS = ((1, 129, 66), (56, 207, 73), (188, 255, 34))


# ---------------------------------------------------------------------------------------------------------------- helpers

def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def prog(t: float, a: float, b: float) -> float:
    return clamp01((t - a) / (b - a)) if b > a else float(t >= b)


def ease_out(x: float) -> float:
    return 1 - (1 - x) ** 3


def smooth(x: float) -> float:
    return x * x * (3 - 2 * x)


def ease_out_back(x: float, s: float = 1.9) -> float:
    x -= 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm_ws(s: str) -> str:
    return " ".join(str(s).split())


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def tool(name: str, ffmpeg_dir: str | None = None) -> str:
    exe = name + (".exe" if os.name == "nt" else "")
    for d in (ffmpeg_dir, os.environ.get("RTV_FFMPEG_DIR")):
        if d and (Path(d) / exe).is_file():
            return str(Path(d) / exe)
    found = shutil.which(name)
    if found:
        return found
    if (FFMPEG_FALLBACK / exe).is_file():
        return str(FFMPEG_FALLBACK / exe)
    raise FileNotFoundError(f"{name} not found (set RTV_FFMPEG_DIR)")


_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
FONTS_USED: dict[str, str] = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key in _font_cache:
        return _font_cache[key]
    for name in FONTS[kind]:
        for d in FONT_DIRS:
            p = d / name
            if p.is_file():
                f = ImageFont.truetype(str(p), size)
                FONTS_USED[kind] = name
                _font_cache[key] = f
                return f
    f = ImageFont.load_default(size=size)       # Pillow's bundled face; the glyph gate says if it cannot draw the text
    FONTS_USED[kind] = "pillow-default"
    _font_cache[key] = f
    return f


def missing_glyphs(text: str, f: ImageFont.FreeTypeFont) -> list[str]:
    """Characters the font draws as its .notdef box (no glyph)."""
    def shape(ch: str):
        m = f.getmask(ch)
        return m.size, bytes(m)
    notdef = shape("\uffff")
    return sorted({ch for ch in text if not ch.isspace() and shape(ch) == notdef})


# ---------------------------------------------------------------------------------------------------------------- sprites

class Sprite:
    """An RGBA image placed by its centre (cx, cy) at rest."""

    def __init__(self, img: Image.Image, cx: float, cy: float):
        self.img, self.cx, self.cy = img, cx, cy

    @property
    def box(self) -> tuple[float, float, float, float]:
        w, h = self.img.size
        return (self.cx - w / 2, self.cy - h / 2, self.cx + w / 2, self.cy + h / 2)


def faded(img: Image.Image, a: float) -> Image.Image | None:
    if a <= 0.004:
        return None
    if a >= 0.996:
        return img
    r, g, b, al = img.split()
    al = al.point([int(v * a + 0.5) for v in range(256)])
    return Image.merge("RGBA", (r, g, b, al))


def put(frame: Image.Image, img: Image.Image, cx: float, cy: float, alpha: float = 1.0, scale: float = 1.0) -> None:
    if alpha <= 0.004:
        return
    if abs(scale - 1.0) > 1e-4:
        w, h = img.size
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        img = img.resize((nw, nh), Image.BICUBIC)
    img = faded(img, alpha)
    if img is None:
        return
    w, h = img.size
    x0, y0 = round(cx - w / 2), round(cy - h / 2)
    sx0, sy0 = max(0, -x0), max(0, -y0)          # clip to the frame (alpha_composite needs the source inside it)
    sx1, sy1 = min(w, W - x0), min(h, H - y0)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    if (sx0, sy0, sx1, sy1) != (0, 0, w, h):
        img = img.crop((sx0, sy0, sx1, sy1))
    frame.alpha_composite(img, (x0 + sx0, y0 + sy0))


def ink(text: str, f: ImageFont.FreeTypeFont, pad: int = 6) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """The text's alpha mask, cropped to its ink box + pad; returns (mask L, bbox at anchor 'ls')."""
    bb = f.getbbox(text, anchor="ls")
    w, h = bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad
    m = Image.new("L", (max(1, w), max(1, h)), 0)
    ImageDraw.Draw(m).text((pad - bb[0], pad - bb[1]), text, font=f, fill=255, anchor="ls")
    return m, bb


def text_img(text: str, f: ImageFont.FreeTypeFont, fill: tuple[int, int, int], pad: int = 6) -> Image.Image:
    m, _ = ink(text, f, pad)
    img = Image.new("RGBA", m.size, fill + (0,))
    img.putalpha(m)
    return img


def gradient(size: tuple[int, int], c0=GRAD[0], c1=GRAD[1]) -> Image.Image:
    w, h = size
    x = np.linspace(0, 1, w)[None, :, None]
    y = np.linspace(0, 1, h)[:, None, None]
    k = np.clip(0.85 * x + 0.15 * y, 0, 1)
    arr = (np.array(c0) * (1 - k) + np.array(c1) * k).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def gradient_text(text: str, f: ImageFont.FreeTypeFont, pad: int = 8) -> Image.Image:
    m, _ = ink(text, f, pad)
    img = gradient(m.size).convert("RGBA")
    img.putalpha(m)
    return img


def rounded_mask(size: tuple[int, int], radius: int, ss: int = 4) -> Image.Image:
    w, h = size
    big = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=radius * ss, fill=255)
    return big.resize(size, Image.LANCZOS)


def _mark_points(spec: list, k: float, ox: float, oy: float) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for s in spec:
        if s[0] == "arc":
            _, cx, cy, r, a0, a1 = s
            n = max(8, int(abs(a1 - a0) / 3))
            for i in range(n + 1):
                a = math.radians(a0 + (a1 - a0) * i / n)
                pts.append(((cx + r * math.cos(a) - ox) * k, (cy + r * math.sin(a) - oy) * k))
        else:
            pts.append(((s[0] - ox) * k, (s[1] - oy) * k))
    return pts


def brand_mark(height: int, ss: int = 4) -> Image.Image:
    """The green R-arrow mark (no tile), `height` px tall, on transparency."""
    bw, bh = MARK_BOX[2] - MARK_BOX[0], MARK_BOX[3] - MARK_BOX[1]
    k = height * ss / bh
    w = max(1, round(bw * height / bh))
    m = Image.new("L", (w * ss, height * ss), 0)
    d = ImageDraw.Draw(m)
    d.polygon(_mark_points(MARK_OUTER, k, MARK_BOX[0], MARK_BOX[1]), fill=255)
    d.polygon(_mark_points(MARK_HOLE, k, MARK_BOX[0], MARK_BOX[1]), fill=0)
    m = m.resize((w, height), Image.LANCZOS)
    x = np.linspace(0, 1, w)[None, :]
    y = np.linspace(0, 1, height)[:, None]
    u = np.clip(0.6 * x + 0.4 * (1 - y), 0, 1)[..., None]                # dark green bottom-left -> lime top-right
    c0, c1, c2 = (np.array(c, np.float32) for c in MARK_GREENS)
    rgb = np.where(u < 0.5, c0 + (c1 - c0) * (u / 0.5), c1 + (c2 - c1) * ((u - 0.5) / 0.5))
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    img.putalpha(m)
    return img


def pill(text: str, size: int, padx: int, pady: int, mark: bool = True) -> Image.Image:
    f = font("bold", size)
    m, bb = ink(text, f, 0)
    th = bb[3] - bb[1]
    mk = brand_mark(round(th * 1.18)) if mark else None
    gap = round(size * 0.32) if mark else 0
    mw = mk.size[0] if mk else 0
    w, h = mw + gap + m.size[0] + 2 * padx, th + 2 * pady
    body = gradient((w, h)).convert("RGBA")
    body.putalpha(rounded_mask((w, h), h // 2))
    if mk:
        body.alpha_composite(mk, (padx, (h - mk.size[1]) // 2))
    t = Image.new("RGBA", m.size, WHITE + (0,))
    t.putalpha(m)
    body.alpha_composite(t, (padx + mw + gap, pady))
    return body


class Sweep:
    """A light band that sweeps across a sprite (x = 0..1 across it; outside: the sprite as is)."""

    def __init__(self, img: Image.Image, strength: float = 0.45, width: float = 0.12):
        self.img, self.strength, self.width = img, strength, width
        self.arr = np.asarray(img).astype(np.float32)
        self.alpha = self.arr[:, :, 3] / 255.0

    def at(self, x: float) -> Image.Image:
        if not 0 < x < 1:
            return self.img
        h, w = self.alpha.shape
        xs = np.arange(w)[None, :] + 0.35 * np.arange(h)[:, None]
        pos = -0.25 * w + x * (1.5 * w + 0.35 * h)
        band = np.clip(1 - np.abs(xs - pos) / (self.width * w + 8), 0, 1) * self.strength * self.alpha
        arr = self.arr.copy()
        arr[:, :, :3] = arr[:, :, :3] * (1 - band[:, :, None]) + 255 * band[:, :, None]
        return Image.fromarray(arr.astype(np.uint8), "RGBA")


def fit_font(kind: str, text: str, max_w: int, start: int, low: int) -> ImageFont.FreeTypeFont:
    size = start
    while size > low and font(kind, size).getlength(text) > max_w:
        size -= 2
    return font(kind, size)


def balanced_lines(words: list[str], f: ImageFont.FreeTypeFont, max_w: float, max_lines: int = 4):
    """The fewest lines (<= max_lines) that fit max_w, broken to even widths and without a one-word last line when the
    group has more than two words. Returns (lines as word-index lists, widths) or None."""
    n = len(words)
    for nl in range(1, min(max_lines, n) + 1):
        best = None
        for cuts in itertools.combinations(range(1, n), nl - 1):
            idx = [0, *cuts, n]
            lines = [list(range(idx[i], idx[i + 1])) for i in range(nl)]
            widths = [f.getlength(" ".join(words[j] for j in ln)) for ln in lines]
            if max(widths) > max_w:
                continue
            cost = sum((max(widths) - w_) ** 2 for w_ in widths)
            if nl > 1 and n > 2 and len(lines[-1]) == 1:
                cost += (0.6 * max_w) ** 2
            if best is None or cost < best[0]:
                best = (cost, lines, widths)
        if best:
            return best[1], best[2]
    return None


def word_colour(word: str) -> tuple[int, int, int]:
    core = word.strip("().,:;")
    if FIGURE_RX.search(word):
        return ACCENT
    if re.fullmatch(r"(?i)beat|beats|above", core):
        return GOOD
    if re.fullmatch(r"(?i)miss|missed|below", core):
        return BAD
    return WHITE


def verdict_colour(label: str) -> tuple[int, int, int]:
    if re.search(r"(?i)\b(beat|beats|above|purchases?|buys?)\b", label):
        return GOOD
    if re.search(r"(?i)\b(miss|missed|below|sales?|sells?)\b", label):
        return BAD
    return ACCENT


# ---------------------------------------------------------------------------------------------------------------- content

def find_ticker(item: dict, facts: str) -> str | None:
    tk = str(item.get("ticker") or "").strip()
    if not tk:
        return None
    m = re.search(rf"(?<![A-Za-z0-9$])\$?{re.escape(tk)}(?![A-Za-z0-9])", facts)
    return m.group(0) if m else None


def hook_parts(item: dict, facts: str) -> dict[str, str | None]:
    """The hook's ticker, headline figure and label: each a verbatim piece of facts_text (or None)."""
    kind = item.get("type")
    figure = label = None
    fallback = True

    def first(rx: str, group: int = 1) -> str | None:
        m = re.search(rx, facts)
        return m.group(group).strip() if m else None

    if kind == "earnings_result":
        figure = first(rf"Revenue ({MONEY})")
        label = first(r":\s+([A-Z][^.:;()]{2,30}\.)") or first(r"\b(Q\d \d{4}) results")
    elif kind == "form4_buy":
        figure = first(rf"totaling ({MONEY})")
        label = first(r"(open-market (?:purchase|sale))")
    elif kind == "congress_trade":
        label = first(r"disclosed ((?:a|an|\d+) (?:purchases?|sales?|exchanges?))")
        if label and label.split()[0] in ("a", "an"):
            figure = first(rf"({MONEY})")
        else:
            fallback = False        # several trades: a per-trade range next to "3 purchases" would read as a total
    elif kind == "chart_pattern":
        figure = first(rf"closed ({MONEY})")
        label = first(r"flagged an? ([a-z][a-z \-]{2,40}?) on ")
    if figure is None and fallback:
        m = FIGURE_RX.search(facts)
        figure = m.group(0) if m else None
    return {"ticker": find_ticker(item, facts), "figure": figure, "label": label}


WEAK_END = {"a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "per", "the", "to", "vs", "vs.", "with", "-", "–"}
ABBREV_RX = re.compile(r"^(?:[A-Z][a-z]?\.|(?:[A-Za-z]\.){2,}|Inc\.|Corp\.|Ltd\.|Co\.|Jr\.|Sr\.|No\.)[,)]?$")


def sentence_end(word: str) -> bool:
    """A word that ends a sentence or clause ("beat.", "2026-11-04:", "$9.71M)."), not an abbreviation ("Inc.", "U.S.")."""
    return word[-1:] == ":" or (word[-1:] == "." and not ABBREV_RX.match(word))


def group_words(words: list[str]) -> list[list[int]]:
    """facts_text -> contiguous word groups for the beats: at most GROUP_MAX_WORDS words and GROUP_MAX_CHARS characters
    (one long word may stand alone), about tgt words each; groups end on a sentence or clause end where they can, never on
    a dangling "vs" / "by" / "on", do not run across a sentence end, and carry a number when the text allows it."""
    n_all = len(words)
    tgt = min(4.5, max(2.5, n_all / 4.5))
    INF = float("inf")
    dp = [INF] * (n_all + 1)
    back = [0] * (n_all + 1)
    dp[0] = 0.0

    def cost(i: int, j: int) -> float:
        n = j - i
        text = " ".join(words[i:j])
        if n > 1 and (n > GROUP_MAX_WORDS or len(text) > GROUP_MAX_CHARS):
            return INF
        c = ((n - tgt) / 2.0) ** 2
        end = words[j - 1]
        if j < n_all:
            if sentence_end(end):
                pass
            elif end[-1] in ",;)" or words[j][:1] == "(":
                c += 0.4
            else:
                c += 1.5
            if ABBREV_RX.match(words[j]):
                c += 1.5             # never split "Micron Technology, | Inc.)"
            if end.lower().strip("(),") in WEAK_END:
                c += 1.5
            if not sentence_end(end) and end[-1] not in ",;)" and words[j][:1].isdigit():
                c += 1.0             # keeps "Q3 2026" together
        if i > 0 and words[i].lower() in WEAK_END:
            c += 1.5                 # nor a group that starts on "vs"
        c += 2.5 * sum(sentence_end(w) for w in words[i:j - 1])
        if not re.search(r"\d", text):
            c += 0.5
        return c

    for j in range(1, n_all + 1):
        for i in range(max(0, j - GROUP_MAX_WORDS), j):
            if dp[i] < INF:
                v = dp[i] + cost(i, j)
                if v < dp[j]:
                    dp[j], back[j] = v, i
    out, j = [], n_all
    while j > 0:
        i = back[j]
        out.append(list(range(i, j)))
        j = i
    return out[::-1]


def beat_len(n_words: int) -> float:
    return min(BEAT_MAX_S, max(BEAT_MIN_S, 0.45 + 0.17 * n_words))


def frames_round(s: float) -> float:
    return round(s * FPS) / FPS


class Plan:
    def __init__(self, item: dict, facts: str):
        self.item, self.facts = item, facts
        self.words = facts.split()
        self.chunks = group_words(self.words)
        durs = [beat_len(len(c)) for c in self.chunks]
        if sum(durs) < BODY_MIN_S:
            k = BODY_MIN_S / sum(durs)
            durs = [min(BEAT_MAX_S, d * k) for d in durs]
        durs = [frames_round(d) for d in durs]
        self.hook_end = HOOK_S
        self.beats: list[float] = []
        t = self.hook_end
        for d in durs:
            self.beats.append(round(t, 6))
            t += d
        self.body_end = round(t, 6)
        self.body_s = self.body_end - self.hook_end
        self.total = self.body_end + END_S
        self.frames = int(round(self.total * FPS))
        self.hook = hook_parts(item, facts)
        self.caption_chunks = [" ".join(self.words[i] for i in c) for c in self.chunks]
        self.figure_beats = [k for k, c in enumerate(self.chunks) if any(FIGURE_RX.search(self.words[i]) for i in c)]
        self.texts: list[dict] = []     # every text drawn: role, text, box at rest, key (inside the safe zone), font


# ---------------------------------------------------------------------------------------------------------------- scenes

def prev_line(words: list[str]) -> Image.Image:
    """The group re-set small (bold, at most 2 lines, centred, its word colours) for the dim line above the next group."""
    for size, max_lines in ((50, 2), (44, 2), (38, 2), (34, 3)):
        f = font("bold", size)
        lay = balanced_lines(words, f, PREV_BOX[0], max_lines)
        if lay:
            break
    if not lay:
        raise ValueError(f"the words {' '.join(words)!r} do not fit the previous-line slot")
    lines, widths = lay
    lh = round(size * 1.18)
    asc, desc = f.getmetrics()
    img = Image.new("RGBA", (PREV_BOX[0] + 16, len(lines) * lh + desc + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for li, (ln, lw) in enumerate(zip(lines, widths)):
        x = (img.size[0] - lw) / 2
        for j, wi in enumerate(ln):
            pre = " ".join(words[k] for k in ln[:j])
            xx = x + (f.getlength(pre + " ") if j else 0.0)
            d.text((xx, 4 + li * lh + asc), words[wi], font=f, fill=word_colour(words[wi]) + (255,), anchor="ls")
    bb = img.getbbox() or (0, 0, 1, 1)
    return img.crop(bb)


class Group:
    """One beat's words laid out centred at the largest size that fits the text band (relative to the block centre)."""

    def __init__(self, words: list[str]):
        self.text = " ".join(words)
        band_h = CUR_BOTTOM - CUR_TOP
        size, lay = 150, None
        while size >= 48:
            f = font("black", size)
            lay = balanced_lines(words, f, TEXT_W - 32)       # room for the ink overhang + the breathe
            lh = round(size * 1.14)
            if lay and len(lay[0]) * lh <= band_h:
                break
            size -= 4
        if not lay:
            raise ValueError(f"the words {self.text!r} do not fit the frame")
        lines, widths = lay
        self.size, self.n_lines = size, len(lines)
        asc = f.getmetrics()[0]
        sprites = []
        for li, (ln, lw) in enumerate(zip(lines, widths)):
            base = li * lh + asc
            for j, wi in enumerate(ln):
                pre = " ".join(words[k] for k in ln[:j])
                x = -lw / 2 + (f.getlength(pre + " ") if j else 0.0)
                m, bb = ink(words[wi], f, 6)
                img = Image.new("RGBA", m.size, word_colour(words[wi]) + (0,))
                img.putalpha(m)
                sx, sy = x + bb[0] - 6, base + bb[1] - 6
                fig = bool(FIGURE_RX.search(words[wi]))
                sprites.append({"img": img, "cx": sx + m.size[0] / 2, "cy": sy + m.size[1] / 2, "fig": fig,
                                "sweep": Sweep(img) if fig else None})
        x0 = min(s["cx"] - s["img"].size[0] / 2 for s in sprites)
        x1 = max(s["cx"] + s["img"].size[0] / 2 for s in sprites)
        y0 = min(s["cy"] - s["img"].size[1] / 2 for s in sprites)
        y1 = max(s["cy"] + s["img"].size[1] / 2 for s in sprites)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        for s in sprites:                       # centre the ink box on (0, 0)
            s["cx"] -= mx
            s["cy"] -= my
        self.w, self.h = x1 - x0, y1 - y0
        self.words = sprites
        comp = Image.new("RGBA", (math.ceil(self.w) + 2, math.ceil(self.h) + 2), (0, 0, 0, 0))
        for s in sprites:
            iw, ih = s["img"].size
            comp.alpha_composite(s["img"], (round(s["cx"] + comp.size[0] / 2 - iw / 2), round(s["cy"] + comp.size[1] / 2 - ih / 2)))
        self.comp = comp
        self.prev = prev_line(words)


class Scenes:
    def __init__(self, plan: Plan, card: Image.Image):
        self.p = plan
        self.card = card.convert("RGB")
        self._build_hook()
        self._build_body()
        self._build_end()
        gx, gy = np.meshgrid(np.linspace(0, 1, 270), np.linspace(0, 1, 480))
        self.gx, self.gy = gx, gy

    # hook ------------------------------------------------------------------------------------------------------------
    def _build_hook(self) -> None:
        p, hk = self.p, self.p.hook
        self.h_pill = pill(BRAND, 40, 32, 20)
        p.texts.append({"role": "brand", "text": BRAND, "key": False, "font": FONTS_USED.get("bold")})
        parts: list[tuple[str, Image.Image, str]] = []
        if hk["ticker"]:
            f = fit_font("black", hk["ticker"], 900, 176 if hk["figure"] else 330, 90)   # no figure: the ticker is the hero
            parts.append(("ticker", gradient_text(hk["ticker"], f), hk["ticker"]))
        if hk["figure"]:
            f = fit_font("black", hk["figure"], 900, 340, 120)
            parts.append(("figure", text_img(hk["figure"], f, WHITE, 10), hk["figure"]))
        if hk["label"]:
            f = fit_font("bold", hk["label"], TEXT_W, 116 if hk["figure"] else 136, 64)
            col = verdict_colour(hk["label"])
            lines = [hk["label"]]
            if f.getlength(hk["label"]) > TEXT_W:
                lay = balanced_lines(hk["label"].split(), f, TEXT_W, 2)
                ws = hk["label"].split()
                lines = [" ".join(ws[i] for i in ln) for ln in lay[0]] if lay else \
                    [" ".join(ws[: len(ws) // 2]), " ".join(ws[len(ws) // 2:])]
            for ln in lines:
                parts.append(("label", text_img(ln, f, col), ln))
        gaps = {"ticker": 18, "figure": 26, "label": 8}
        total = sum(im.size[1] for _, im, _ in parts) + sum(gaps[r] for r, _, _ in parts[:-1])
        y = HOOK_CY - total / 2
        self.h_parts: list[tuple[str, Sprite]] = []
        for role, im, txt in parts:
            s = Sprite(im, W / 2, y + im.size[1] / 2)
            self.h_parts.append((role, s))
            p.texts.append({"role": f"hook_{role}", "text": txt, "box": s.box, "key": True})
            y += im.size[1] + gaps[role]
        self.h_pill_cy = 300 + self.h_pill.size[1] / 2
        self.h_punch = "figure" if any(r == "figure" for r, _ in self.h_parts) else "ticker"
        self.h_sweep = {id(s): Sweep(s.img, 0.5, 0.1) for r, s in self.h_parts if r == self.h_punch}

    def hook(self, frame: Image.Image, t: float) -> None:
        ex = prog(t, self.p.hook_end - CUT_F / FPS, self.p.hook_end)       # hard cut: out within the last 4 frames
        ga, gs = 1 - ex, 1 + 0.12 * ex
        if ga <= 0.004:
            return
        C = (W / 2, HOOK_CY)

        def at(s: Sprite, dy: float = 0.0) -> tuple[float, float]:
            return C[0] + (s.cx - C[0]) * gs, C[1] + (s.cy + dy - C[1]) * gs

        e = ease_out(prog(t, 0.0, 0.25))
        put(frame, self.h_pill, W / 2, C[1] + (self.h_pill_cy - 16 * (1 - e) - C[1]) * gs, ga, gs * (0.95 + 0.05 * e))
        for role, s in self.h_parts:
            if role == self.h_punch:
                k = ease_out_back(prog(t, 0.0, 0.36))
                sc = 1.18 - 0.18 * k + 0.05 * prog(t, 0.36, self.p.hook_end)
                img = self.h_sweep[id(s)].at(prog(t, 0.42, 0.86))
                put(frame, img, *at(s), ga, gs * sc)
            elif role == "ticker":          # already partly in on frame 0 (a cover taken from it still has the ticker)
                u = 0.6 + 0.4 * prog(t, 0.0, 0.22)
                put(frame, s.img, *at(s, -80 * (1 - ease_out(u))), ga * u, gs)
            else:
                u = 0.5 + 0.5 * prog(t, 0.0, 0.3)
                put(frame, s.img, *at(s, 90 * (1 - ease_out(u))), ga * u, gs * (1.04 - 0.04 * ease_out(u)))

    # body ------------------------------------------------------------------------------------------------------------
    def _build_body(self) -> None:
        p = self.p
        hw, hh = HEAD_W, HEAD_H
        content = self.card.crop(CARD_CROP).resize((hw, hh), Image.LANCZOS).convert("RGBA")
        content.putalpha(rounded_mask((hw, hh), 24))
        self.c_sweep = Sweep(content, 0.22, 0.14)
        b, g = 4, 60
        ring = gradient((hw + 2 * b, hh + 2 * b)).convert("RGBA")
        outer = rounded_mask((hw + 2 * b, hh + 2 * b), 24 + b)
        inner = Image.new("L", outer.size, 0)
        inner.paste(rounded_mask((hw, hh), 24), (b, b))
        ring.putalpha(Image.fromarray(np.clip(np.asarray(outer, np.int16) - np.asarray(inner, np.int16), 0, 255).astype(np.uint8)))
        glow = Image.new("RGBA", (hw + 2 * g, hh + 2 * g), GRAD[0] + (0,))
        gm = Image.new("L", glow.size, 0)
        gm.paste(rounded_mask((hw + 16, hh + 16), 32), (g - 8, g - 8))
        glow.putalpha(gm.filter(ImageFilter.GaussianBlur(22)).point([int(v * 0.6) for v in range(256)]))
        self.c_ring, self.c_glow, self.c_b, self.c_g = ring, glow, b, g
        self.c_cy = HEAD_TOP + hh / 2
        self.groups = [Group([p.words[i] for i in c]) for c in p.chunks]
        p.texts.append({"role": "caption", "text": " ".join(p.caption_chunks), "key": False})
        for k, gr in enumerate(self.groups):
            s = 1 + BREATHE
            p.texts.append({"role": "caption_group", "text": gr.text, "key": True, "font_size": gr.size, "lines": gr.n_lines,
                            "box": (W / 2 - gr.w * s / 2, CUR_CY - gr.h * s / 2, W / 2 + gr.w * s / 2, CUR_CY + gr.h * s / 2)})
            if k + 1 < len(self.groups):
                pw, ph = gr.prev.size
                p.texts.append({"role": "caption_previous", "text": gr.text, "key": True,
                                "box": (W / 2 - pw / 2, PREV_CY - ph / 2, W / 2 + pw / 2, PREV_CY + ph / 2)})

    def card_frame(self, t: float, pulse: float) -> Image.Image:
        past = [b for b in self.p.beats if b <= t]
        sheen = prog(t, past[-1] + 0.05, past[-1] + 0.65) if past else 0.0
        content = self.c_sweep.at(sheen)
        out = (faded(self.c_glow, 0.45 + 0.55 * pulse) or Image.new("RGBA", self.c_glow.size, (0, 0, 0, 0))).copy()
        off = self.c_g - self.c_b
        out.alpha_composite(faded(self.c_ring, 0.55 + 0.45 * pulse) or self.c_ring, (off, off))
        out.alpha_composite(content, (self.c_g, self.c_g))
        return out

    def body(self, frame: Image.Image, t: float) -> None:
        p = self.p
        ex = prog(t, p.body_end - CUT_F / FPS, p.body_end)                 # hard cut to the end card
        ga, gs = 1 - ex, 1 + 0.08 * ex
        if ga <= 0.004:
            return
        C = (W / 2, H / 2)

        def place(x: float, y: float) -> tuple[float, float]:
            return C[0] + (x - C[0]) * gs, C[1] + (y - C[1]) * gs

        # the card: a context header, entering on the cut, slow zoom + float, pulse and sheen on each beat
        enter = ease_out(prog(t, p.hook_end, p.hook_end + 7 / FPS))
        past = [b for b in p.beats if b <= t]
        pulse = math.exp(-(t - past[-1]) / 0.3) if past else 0.0
        z = (0.9 + 0.1 * enter) * (1 + 0.06 * smooth(prog(t, p.hook_end, p.body_end)))
        cy = self.c_cy - 60 * (1 - enter) + 5 * math.sin(2 * math.pi * (t - p.hook_end) / 3.0)
        put(frame, self.card_frame(t, pulse), *place(W / 2, cy), ga * enter, gs * z)
        # the word groups: the current one huge and centred, the previous one a small dim line above it
        n = len(self.groups)
        for k, gr in enumerate(self.groups):
            b = p.beats[k]
            e = p.beats[k + 1] if k + 1 < n else p.body_end
            if t < b:
                break
            if t < e:
                br = 1 + BREATHE * smooth(prog(t, b + 0.3, e))
                for j, wd in enumerate(gr.words):
                    ta = b + 0.12 + min(0.05 * j, 0.3)
                    if t < ta:
                        continue
                    u = prog(t, ta, ta + 0.26)
                    s0 = 1.5 if wd["fig"] else 1.25
                    sc = s0 - (s0 - 1) * ease_out_back(u, 1.7)
                    al = prog(t, ta, ta + 0.08)
                    dy = 34 * (1 - ease_out(u))
                    img = wd["sweep"].at(prog(t, ta + 0.35, ta + 0.9)) if wd["fig"] else wd["img"]
                    put(frame, img, *place(W / 2 + wd["cx"] * br, CUR_CY + (wd["cy"] + dy) * br), ga * al, gs * sc * br)
                continue
            if k + 1 >= n:
                continue
            e2 = p.beats[k + 2] if k + 2 < n else p.body_end
            if t >= e2 + CUT_F / FPS:
                continue
            # out of the centre: the big group flies up and shrinks away within 4 frames, then the same words re-set small
            # settle in the slot above (one layer at a time, never two copies of the text overlapping)
            v = prog(t, e, e + CUT_F / FPS)
            if v < 1:
                br_end = 1 + BREATHE
                put(frame, gr.comp, *place(W / 2, CUR_CY - 160 * ease_out(v)), ga * (1 - v), gs * br_end * (1 - 0.35 * v))
            u = ease_out(prog(t, e + CUT_F / FPS, e + CUT_F / FPS + 0.22))
            al = 0.5 * u
            y = PREV_CY + 40 * (1 - u)
            if t >= e2:
                w_ = prog(t, e2, e2 + CUT_F / FPS)
                al *= 1 - w_
                y -= 50 * w_
            put(frame, gr.prev, *place(W / 2, y), ga * al, gs * (0.92 + 0.08 * u))

    # end card --------------------------------------------------------------------------------------------------------
    def _build_end(self) -> None:
        p = self.p
        self.e_pill = pill(BRAND, 86, 56, 34)
        self.e_sweep = Sweep(self.e_pill, 0.38, 0.09)
        self.e_site = text_img(SITE, font("semi", 58), (235, 238, 245))
        self.e_disc = text_img(DISCLAIMER, font("regular", 48), DISC_GREY)
        hs = [self.e_pill.size[1], self.e_site.size[1], self.e_disc.size[1]]
        gaps = [44, 36]
        total = sum(hs) + sum(gaps)
        y = H / 2 - total / 2
        self.e_cy = []
        for h_, g_ in zip(hs, gaps + [0]):
            self.e_cy.append(y + h_ / 2)
            y += h_ + g_
        for role, txt, im, cy in (("end_brand", BRAND, self.e_pill, self.e_cy[0]), ("end_site", SITE, self.e_site, self.e_cy[1]),
                                  ("end_disclaimer", DISCLAIMER, self.e_disc, self.e_cy[2])):
            p.texts.append({"role": role, "text": txt, "box": Sprite(im, W / 2, cy).box, "key": True})

    def end(self, frame: Image.Image, t: float) -> None:
        p = self.p
        v = t - p.body_end
        if v < 0:
            return
        gs = 1 + 0.06 * prog(v, 0, END_S)
        C = (W / 2, H / 2)
        k = ease_out_back(prog(v, 0.0, 0.36))
        x = prog(v, 0.55, 1.2) if v < 1.4 else prog(v, 1.75, 2.4)
        put(frame, self.e_sweep.at(x), C[0], C[1] + (self.e_cy[0] - C[1]) * gs, prog(v, 0, 3 / FPS), gs * (0.6 + 0.4 * k))
        e = ease_out(prog(v, 0.12, 0.45))
        put(frame, self.e_site, C[0], C[1] + (self.e_cy[1] + 50 * (1 - e) - C[1]) * gs, e, gs)
        e = ease_out(prog(v, 0.25, 0.6))
        put(frame, self.e_disc, C[0], C[1] + (self.e_cy[2] + 40 * (1 - e) - C[1]) * gs, e, gs)

    # background ------------------------------------------------------------------------------------------------------
    def background(self, t: float) -> Image.Image:
        p, gx, gy = self.p, self.gx, self.gy

        def glow(cx: float, cy: float, r: float) -> np.ndarray:
            return np.exp(-(((gx - cx) ** 2) + ((gy - cy) * 1.7778) ** 2) / (2 * r * r))

        w = 2 * math.pi * t / 9.0
        rgb = np.zeros(gx.shape + (3,), np.float32) + np.array(BG, np.float32)
        rgb += np.array((124, 58, 237), np.float32) * (0.30 * glow(0.16 + 0.10 * math.sin(w), 0.80 - 0.06 * math.cos(w), 0.36))[..., None]
        rgb += np.array((20, 184, 166), np.float32) * (0.20 * glow(0.86 - 0.08 * math.sin(w * 1.3), 0.16 + 0.05 * math.sin(w), 0.30))[..., None]
        burst = 0.42 * math.exp(-t / 0.35) + 0.30 * math.exp(-max(0.0, t - p.body_end) / 0.45) * (t >= p.body_end)
        if burst > 0.01:
            rgb += np.array((99, 102, 241), np.float32) * (burst * glow(0.5, 0.49, 0.28))[..., None]
        img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").resize((W, H), Image.BICUBIC)
        return img.convert("RGBA")

    def frame(self, t: float) -> Image.Image:
        fr = self.background(t)
        if t < self.p.hook_end:
            self.hook(fr, t)
        elif t < self.p.body_end:
            self.body(fr, t)
        else:
            self.end(fr, t)
        return fr.convert("RGB")


# ---------------------------------------------------------------------------------------------------------------- music

def write_wav(path: Path, mix: np.ndarray) -> None:
    pcm = np.clip(np.round(mix * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------------------------------------------------------- encode

def encode(sc: Scenes, wav: Path, mp4: Path, ffmpeg: str) -> None:
    """Frames go to ffmpeg as a PNG stream (image2pipe): the local build has no rawvideo demuxer and few filters."""
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "image2pipe", "-c:v", "png", "-framerate", str(FPS), "-i", "-", "-i", str(wav),
           "-map", "0:v", "-map", "1:a", "-vf", "scale=out_color_matrix=bt709:flags=bicubic",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2", "-shortest", "-movflags", "+faststart",
           "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact", str(mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(sc.p.frames):
            buf = io.BytesIO()
            sc.frame(i / FPS).save(buf, "PNG", compress_level=1)
            proc.stdin.write(buf.getvalue())
        proc.stdin.close()
    except OSError:              # ffmpeg stopped reading (BrokenPipe / EINVAL on Windows): its stderr says why
        pass
    err = proc.stderr.read().decode("utf-8", "replace")
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {err.strip()[-800:]}")


# ---------------------------------------------------------------------------------------------------------------- QA

def probe(mp4: Path, ffprobe: str) -> dict:
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,sample_rate,channels:format=duration,size",
                          "-of", "json", str(mp4)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def split_pngs(data: bytes) -> list[bytes]:
    """A concatenated PNG stream (image2pipe) -> one bytes object per image, walking the chunks to each IEND."""
    out, i, sig = [], 0, bytes([137, 80, 78, 71, 13, 10, 26, 10])
    while i < len(data):
        if data[i:i + 8] != sig:
            raise ValueError("not a PNG stream")
        j = i + 8
        while True:
            ln = int.from_bytes(data[j:j + 4], "big")
            kind = data[j + 4:j + 8]
            j += 12 + ln
            if kind == b"IEND" or j >= len(data):
                break
        out.append(data[i:j])
        i = j
    return out


def grey_frames(mp4: Path, ffmpeg: str, size=(270, 480)) -> np.ndarray:
    """Every decoded frame, downscaled, as grey (the local build has no fps/format filters: decode all, pick in numpy)."""
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(mp4), "-an", "-vf", f"scale={size[0]}:{size[1]}:flags=area",
                          "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True, check=True).stdout
    pngs = split_pngs(raw)
    if not pngs:
        raise ValueError("no frames decoded")
    return np.stack([np.asarray(Image.open(io.BytesIO(b)).convert("L"), np.float32) for b in pngs])


def grey_at(mp4: Path, ffmpeg: str, t: float) -> np.ndarray:
    raw = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{t:.3f}", "-i", str(mp4), "-an", "-frames:v", "1",
                          "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True, check=True).stdout
    pngs = split_pngs(raw)
    if not pngs:
        raise ValueError(f"no frame decoded at {t:.3f} s")
    return np.asarray(Image.open(io.BytesIO(pngs[0])).convert("L"), np.float32)


def volume(mp4: Path, ffmpeg: str) -> tuple[float | None, float | None]:
    """(RMS dBFS, peak dBFS) of the decoded audio track."""
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(mp4), "-map", "0:a:0", "-c:a", "pcm_s16le", "-f", "wav", "-"],
                         capture_output=True, check=True).stdout
    with wave.open(io.BytesIO(raw)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768.0
    if not pcm.size:
        return None, None
    rms, peak = float(np.sqrt(np.mean(pcm ** 2))), float(np.abs(pcm).max())

    def db(x: float) -> float | None:
        return round(20 * math.log10(x), 2) if x > 0 else None
    return db(rms), db(peak)


def word_rx(w: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(map(re.escape, w.lower().split())) + r"(?![A-Za-z0-9])")


def text_gates(plan: Plan, banned: list[str]) -> tuple[dict, dict]:
    """The gates that read the render plan: verbatim caption/hook, banned words, provider names, disclaimer, glyphs, safe
    zones (and the right rail), beat cadence."""
    s, d = {}, {}
    facts_n = norm_ws(plan.facts)
    joined = " ".join(plan.caption_chunks).split()
    hook_ok = all(v is None or norm_ws(v) in facts_n for v in plan.hook.values())
    cap = next(x for x in plan.texts if x["role"] == "caption")
    groups = [x["text"] for x in plan.texts if x["role"] == "caption_group"]
    allowed_fixed = {BRAND, SITE, DISCLAIMER}
    origins_ok = all(x["text"] in allowed_fixed if x["role"] in ("brand", "end_brand", "end_site", "end_disclaimer")
                     else norm_ws(x["text"]) in facts_n for x in plan.texts)
    s["caption_verbatim"] = (joined == plan.words and cap["text"].split() == plan.words and groups == plan.caption_chunks
                             and hook_ok and origins_ok)
    d["caption_verbatim"] = {"chunks": plan.caption_chunks, "hook": plan.hook, "words": len(plan.words)}
    every = " \n ".join(x["text"] for x in plan.texts).lower()
    hits = sorted({w for w in banned if isinstance(w, str) and w.strip() and word_rx(w).search(every)})
    s["banned_words"] = not hits
    d["banned_words"] = {"found": hits, "checked": len(banned)}
    prov = sorted({m.group(0) for m in PROVIDER_RX.finditer(" \n ".join(x["text"] for x in plan.texts))})
    s["no_provider_names"] = not prov
    d["no_provider_names"] = {"found": prov}
    s["disclaimer_text"] = any(x["role"] == "end_disclaimer" and x["text"] == DISCLAIMER for x in plan.texts)
    miss: dict[str, list[str]] = {}
    checks = [("caption", " ".join(plan.words), font("black", 100))]
    for role, kind in (("hook_ticker", "black"), ("hook_figure", "black"), ("hook_label", "bold")):
        for x in plan.texts:
            if x["role"] == role:
                checks.append((role, x["text"], font(kind, 100)))
    checks += [("end_site", SITE, font("semi", 58)), ("end_disclaimer", DISCLAIMER, font("regular", 48)),
               ("brand", BRAND, font("bold", 86))]
    for role, txt, f in checks:
        m = missing_glyphs(txt, f)
        if m:
            miss[role] = m
    s["glyphs"] = not miss
    d["glyphs"] = {"missing": miss, "fonts": dict(FONTS_USED)}
    bad, rail = [], []
    for x in plan.texts:
        if not (x.get("key") and "box" in x):
            continue
        x0, y0, x1, y1 = x["box"]
        if not (y0 >= SAFE_TOP and y1 <= SAFE_BOTTOM and x0 >= 0 and x1 <= W):
            bad.append(x["role"])
        if y1 > RAIL_Y and x1 > RAIL_X:
            rail.append(x["role"])
    s["safe_zones"] = not bad and not rail
    d["safe_zones"] = {"outside": bad, "under_right_rail": rail, "top": SAFE_TOP, "bottom": SAFE_BOTTOM,
                       "rail": {"x": RAIL_X, "below_y": RAIL_Y},
                       "boxes": [[x["role"], [round(v) for v in x["box"]]] for x in plan.texts if "box" in x]}
    gaps = [b - a for a, b in zip([plan.hook_end] + plan.beats, plan.beats + [plan.body_end])]
    s["beat_cadence"] = bool(plan.beats) and max(gaps) <= MAX_BEAT_GAP_S + 1e-6
    d["beat_cadence"] = {"beats_s": [round(b, 3) for b in plan.beats], "max_gap_s": round(max(gaps), 3),
                         "groups": len(plan.chunks), "max_words": max(len(c) for c in plan.chunks)}
    return s, d


def video_gates(mp4: Path, sc: Scenes, ffmpeg: str, ffprobe: str) -> tuple[dict, dict]:
    plan = sc.p
    s, d = {}, {}
    info = probe(mp4, ffprobe)
    v = next((x for x in info.get("streams", []) if x.get("codec_type") == "video"), {})
    a = next((x for x in info.get("streams", []) if x.get("codec_type") == "audio"), None)
    dur = float(info.get("format", {}).get("duration") or 0)
    size = mp4.stat().st_size
    s["resolution"] = (v.get("width"), v.get("height")) == (W, H)
    s["duration"] = DURATION_RANGE[0] <= dur <= DURATION_RANGE[1]
    s["video_codec"] = v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p" and v.get("r_frame_rate") == f"{FPS}/1"
    s["audio_present"] = bool(a) and a.get("codec_name") == "aac"
    mean, peak = volume(mp4, ffmpeg) if a else (None, None)
    s["audio_not_silent"] = mean is not None and peak is not None and mean > -40 and peak > -20
    s["file_size"] = 0 < size <= MAX_BYTES
    d.update(resolution=[v.get("width"), v.get("height")], duration=round(dur, 3), duration_range=list(DURATION_RANGE),
             video_codec={k: v.get(k) for k in ("codec_name", "pix_fmt", "r_frame_rate")},
             audio_present=a and {k: a.get(k) for k in ("codec_name", "sample_rate", "channels")},
             audio_not_silent={"mean_db": mean, "max_db": peak}, file_size={"bytes": size, "limit": MAX_BYTES})
    g = grey_frames(mp4, ffmpeg)[:: FPS // 2]
    first = g[0]
    s["first_frame_not_blank"] = float(first.std()) >= 12 and float(first.max() - np.median(first)) >= 100
    d["first_frame_not_blank"] = {"std": round(float(first.std()), 2), "max": float(first.max()), "median": float(np.median(first))}
    mads = [float(np.abs(g[i + 1] - g[i]).mean()) for i in range(len(g) - 1)]
    s["motion_every_beat"] = len(mads) >= int(DURATION_RANGE[0] * 2) - 1 and min(mads) > MOTION_MIN_MAD
    d["motion_every_beat"] = {"step_s": 0.5, "threshold": MOTION_MIN_MAD, "min": round(min(mads), 3) if mads else None,
                              "mads": [round(m, 2) for m in mads]}
    # the disclaimer is really on screen near the end: its box in the decoded frame has contrast AND matches the planned
    # frame's pixels there (any other text in that box, or a frozen body frame, does not correlate)
    fi = plan.frames - 14
    tt = fi / FPS
    full = grey_at(mp4, ffmpeg, tt)
    want = np.asarray(sc.frame(tt).convert("L"), np.float32)
    box = next(x["box"] for x in plan.texts if x["role"] == "end_disclaimer")
    gs = 1 + 0.06 * prog(tt - plan.body_end, 0, END_S)            # the end card's zoom at that time
    cx, cy = W / 2, H / 2
    x0, y0, x1, y1 = (cx + (box[0] - cx) * gs, cy + (box[1] - cy) * gs, cx + (box[2] - cx) * gs, cy + (box[3] - cy) * gs)
    x0, y0, x1, y1 = max(0, int(x0) - 4), max(0, int(y0) - 4), min(W, int(math.ceil(x1)) + 4), min(H, int(math.ceil(y1)) + 4)
    region, ref = full[y0:y1, x0:x1], want[y0:y1, x0:x1]
    contrast = float(region.max() - np.median(region)) if region.size else 0.0
    if region.size and region.std() > 0 and ref.std() > 0:
        corr = float(np.corrcoef(region.ravel(), ref.ravel())[0, 1])
    else:
        corr = 0.0
    s["disclaimer_on_screen"] = contrast >= 60 and corr >= DISCLAIMER_MIN_CORR
    d["disclaimer_on_screen"] = {"t": round(tt, 3), "box": [x0, y0, x1, y1], "contrast": round(contrast, 1),
                                 "corr_vs_planned": round(corr, 3), "min_corr": DISCLAIMER_MIN_CORR}
    return s, d


# ---------------------------------------------------------------------------------------------------------------- main

def fail(out: Path, item_id: str | None, why: str, gate: str = "inputs") -> int:
    write_json(out / "reel-qa.json", {"schema": "rtv-card-reel-qa/1", "renderer": RENDERER, "item_id": item_id, "pass": False,
                                      "summary": {gate: False}, "details": {gate: why}})
    print(f"card_reel: {why}", file=sys.stderr)
    return 2


def fail_input(out: Path, item_id: str | None, why: str) -> int:
    return fail(out, item_id, why, "inputs")


def run(a: argparse.Namespace, out: Path, ctx: dict) -> int:
    try:
        doc = json.loads(Path(a.item).resolve().read_text(encoding="utf-8-sig"))
        item = doc["item"]
        banned = [w for w in doc.get("banned_words") or [] if isinstance(w, str)]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return fail_input(out, None, f"item.json unreadable ({type(e).__name__})")
    iid = item.get("item_id") if isinstance(item, dict) else None
    ctx["iid"] = iid if isinstance(iid, str) else None
    facts = item.get("facts_text") if isinstance(item, dict) else None
    if not isinstance(iid, str) or not isinstance(facts, str) or not facts.strip():
        return fail_input(out, ctx["iid"], "the item has no item_id or no facts_text")
    card_path = Path(a.card).resolve()
    try:
        with Image.open(card_path) as im:
            fmt, size = im.format, im.size
            card = im.convert("RGB")
    except Exception as e:  # noqa: BLE001 - any decode error means no card
        return fail_input(out, iid, f"the card does not decode ({type(e).__name__})")
    if fmt != "PNG" or size != CARD_SIZE:
        return fail_input(out, iid, f"the card is {fmt} {size[0]}x{size[1]}, not a 1200x630 PNG")
    try:
        ffmpeg, ffprobe = tool("ffmpeg", a.ffmpeg_dir), tool("ffprobe", a.ffmpeg_dir)
    except FileNotFoundError as e:
        return fail_input(out, iid, str(e))

    plan = Plan(item, norm_ws(facts))
    sc = Scenes(plan, card)
    try:
        mix, music, instruments, score = vsco_score.compose(plan.hook_end, plan.beats, plan.figure_beats, plan.body_end, plan.total)
    except vsco_score.SampleError as e:
        return fail(out, iid, f"music: {e}", "music")
    wav = out / "music_bed.wav"
    write_wav(wav, mix)
    score["wav_sha256"] = sha256(wav)
    write_json(out / "vsco-instruments.json", instruments)
    mp4 = out / "reel_9x16.mp4"
    try:
        encode(sc, wav, mp4, ffmpeg)
    except (RuntimeError, OSError) as e:
        return fail(out, iid, f"render failed: {e}", "render")
    summary, details = text_gates(plan, banned)
    try:
        vs, vd = video_gates(mp4, sc, ffmpeg, ffprobe)
    except (subprocess.CalledProcessError, ValueError, OSError) as e:
        vs, vd = {"video_readable": False}, {"video_readable": f"{type(e).__name__}: {e}"}
    summary = {**vs, **summary}
    details = {**vd, **details}
    ok = all(summary.values())
    write_json(out / "reel-qa.json", {"schema": "rtv-card-reel-qa/1", "renderer": RENDERER, "item_id": iid, "pass": ok,
                                      "summary": summary, "details": details})
    seconds = details.get("duration")
    write_json(out / "reel.json", {
        "schema": "rtv-card-reel/1", "renderer": RENDERER, "item_id": iid, "qa_pass": ok,
        "files": {"reel_9x16.mp4": sha256(mp4)}, "card": {"sha256": sha256(card_path), "size": list(CARD_SIZE)},
        "music": music, "score": score, "seconds": seconds, "fps": FPS, "size": [W, H],
        "caption": plan.facts, "hook": plan.hook, "groups": plan.caption_chunks, "beats_s": [round(b, 3) for b in plan.beats],
        "fonts": dict(FONTS_USED)})
    bad = [k for k, v in summary.items() if not v]
    print(f"card_reel: {iid}: {'QA passed' if ok else 'QA failed: ' + ', '.join(bad)} ({mp4.stat().st_size} bytes, {seconds} s)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--item", required=True)
    ap.add_argument("--card", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ffmpeg-dir")
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name in ("reel_9x16.mp4", "reel.json", "reel-qa.json", "music_bed.wav", "vsco-instruments.json"):
        (out / name).unlink(missing_ok=True)
    ctx: dict = {"iid": None}
    try:
        return run(a, out, ctx)
    except Exception as e:  # noqa: BLE001 - every failure still leaves a reel-qa.json that says why
        return fail(out, ctx["iid"], f"render error: {type(e).__name__}: {e}", "render")


if __name__ == "__main__":
    sys.exit(main())
