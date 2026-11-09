"""The cartoon Reel's drawing kit (PIL + numpy only): the RTV cast, props, sets, SFX bubbles, ticker chips, pulse rings and
the phone frame around a real screenshot. Used by cartoon_reel.py.

Our own style (format spec section 2-3; nothing is copied from the reference videos): squircle heads, oval eyes with
pupils and expression lids, hoodie / tank-top bodies with outlined capsule limbs and mitten hands, a night gym in brand navy
and violet, pulse-ring PUNCH backgrounds, speech-bubble SFX, ticker-chip labels.

Every sprite is drawn at 2x and downsampled (LANCZOS). Transparent pixels carry the INK colour, so bicubic resampling of the
outlined sprites never leaves a light fringe. Sizes are in head units (hu = head width in px).
"""
from __future__ import annotations

import math
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cartoon_qa import cr  # noqa: E402  (the v6cat card-Reel renderer: fonts, pill, sweep)

INK = (11, 16, 32)
CLEAR = INK + (0,)
WHITE = (255, 255, 255)
VIOLET, VIOLET_D = (124, 58, 237), (109, 40, 217)
CYAN, CYAN_D = (34, 211, 238), (6, 182, 212)
GREEN, GREEN_D = (52, 211, 120), (22, 163, 74)
LIME = (188, 255, 34)
RED, RED_D = (248, 92, 92), (220, 38, 38)
CORAL = (255, 111, 97)
NAVY = (27, 31, 59)
NIGHT_TOP, NIGHT_BOT, NIGHT_FLOOR = (43, 36, 112), (26, 22, 70), (18, 15, 51)
SKY0, SKY1, SKYLINE = (14, 26, 58), (27, 45, 107), (10, 15, 42)
DESK_TOP = (58, 47, 134)
PINK = (244, 114, 182)
RING_PAIRS = {"violet": (VIOLET, VIOLET_D), "cyan": (CYAN, CYAN_D), "green": (GREEN, GREEN_D), "red": (RED, RED_D),
              "navy": ((34, 28, 92), (20, 16, 58))}
SS = 2  # supersampling


def darker(c, k=0.12):
    return tuple(int(v * (1 - k)) for v in c[:3])


def lighter(c, k=0.25):
    return tuple(int(v + (255 - v) * k) for v in c[:3])


class Pen:
    """A 2x RGBA drawing surface in head units: P(x, y) maps hu coordinates (origin at `origin` hu) to pixels."""

    def __init__(self, w_hu: float, h_hu: float, hu: float, origin=(0.0, 0.0)):
        self.hu = hu * SS
        self.ox, self.oy = origin
        self.img = Image.new("RGBA", (max(2, int(w_hu * self.hu)), max(2, int(h_hu * self.hu))), CLEAR)
        self.d = ImageDraw.Draw(self.img)

    def P(self, x, y):
        return ((x + self.ox) * self.hu, (y + self.oy) * self.hu)

    def L(self, v):
        return v * self.hu

    def outline(self, o_hu=None):
        o = self.L(o_hu if o_hu is not None else 0.035)
        return max(6 * SS, min(20 * SS, o))

    def rrect(self, cx, cy, w, h, r, fill, line=True, o=None):
        x0, y0 = self.P(cx - w / 2, cy - h / 2)
        x1, y1 = self.P(cx + w / 2, cy + h / 2)
        rr = self.L(r)
        if line:
            oo = o if o is not None else self.outline()
            self.d.rounded_rectangle((x0 - oo, y0 - oo, x1 + oo, y1 + oo), radius=rr + oo, fill=INK)
        self.d.rounded_rectangle((x0, y0, x1, y1), radius=max(0, rr), fill=fill)

    def ellipse(self, cx, cy, w, h, fill, line=True, o=None):
        x0, y0 = self.P(cx - w / 2, cy - h / 2)
        x1, y1 = self.P(cx + w / 2, cy + h / 2)
        if line:
            oo = o if o is not None else self.outline()
            self.d.ellipse((x0 - oo, y0 - oo, x1 + oo, y1 + oo), fill=INK)
        self.d.ellipse((x0, y0, x1, y1), fill=fill)

    def capsule(self, a, b, w, fill, line=True, o=None):
        (x0, y0), (x1, y1) = self.P(*a), self.P(*b)
        ww = self.L(w)
        passes = []
        if line:
            oo = o if o is not None else self.outline()
            passes.append((INK, ww + 2 * oo))
        passes.append((fill, ww))
        for col, width in passes:
            self.d.line((x0, y0, x1, y1), fill=col, width=int(width))
            for x, y in ((x0, y0), (x1, y1)):
                self.d.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=col)

    def poly(self, pts, fill, line=True, o=None):
        pp = [self.P(*p) for p in pts]
        if line:
            oo = o if o is not None else self.outline()
            self.d.line(pp + [pp[0]], fill=INK, width=int(2 * oo), joint="curve")
            for x, y in pp:
                self.d.ellipse((x - oo, y - oo, x + oo, y + oo), fill=INK)
        self.d.polygon(pp, fill=fill)

    def line(self, pts, w, fill=INK):
        pp = [self.P(*p) for p in pts]
        ww = self.L(w)
        self.d.line(pp, fill=fill, width=max(1, int(ww)), joint="curve")
        for x, y in (pp[0], pp[-1]):
            self.d.ellipse((x - ww / 2, y - ww / 2, x + ww / 2, y + ww / 2), fill=fill)

    def arc(self, cx, cy, w, h, a0, a1, lw, fill=INK):
        x0, y0 = self.P(cx - w / 2, cy - h / 2)
        x1, y1 = self.P(cx + w / 2, cy + h / 2)
        self.d.arc((x0, y0, x1, y1), a0, a1, fill=fill, width=max(1, int(self.L(lw))))

    def done(self, anchor_hu):
        """Downsample to 1x; returns (RGBA, anchor px)."""
        w, h = self.img.size
        img = self.img.resize((w // SS, h // SS), Image.LANCZOS)
        ax, ay = self.P(*anchor_hu)
        return img, (ax / SS, ay / SS)


# ------------------------------------------------------------------------------------------------- faces
EXPR = {  # lid cover (0-1), pupil size (hu), gaze x (hu), mouth
    "deadpan": (0.45, 0.07, 0.0, "flat"),
    "side": (0.45, 0.07, 0.03, "flat"),
    "shock": (0.0, 0.05, 0.0, "open"),
    "smug": (0.30, 0.07, -0.02, "smirk"),
    "panic": (0.0, 0.04, 0.0, "zigzag"),
    "strain": (0.25, 0.06, 0.0, "teeth"),
    "happy": (0.15, 0.07, 0.0, "smile"),
    "sip": (0.35, 0.07, 0.02, "o"),
}


def face(p: Pen, skin, expr: str, blink: bool, eye_dx=0.19, eye_y=-0.02, mouth_y=0.24, gaze_y=0.0):
    lid, pup, gx, mouth = EXPR.get(expr, EXPR["deadpan"])
    ew, eh = 0.16, 0.20
    for sx in (-1, 1):
        ex = sx * eye_dx
        p.ellipse(ex, eye_y, ew, eh, WHITE, o=p.L(0.022))
        px = ex + gx + (0.0 if expr != "panic" else 0.0)
        p.ellipse(px, eye_y + 0.02 + gaze_y, pup, pup, INK, line=False)
        p.ellipse(px + pup * 0.22, eye_y + 0.02 + gaze_y - pup * 0.25, pup * 0.32, pup * 0.32, WHITE, line=False)
        cover = 1.0 if blink else lid
        if cover > 0:
            tilt = 0.03 * sx if expr == "smug" else 0.0
            top = eye_y - eh / 2 - 0.02
            y_lid = eye_y - eh / 2 + eh * cover
            pts = [(ex - ew / 2 - 0.03, top), (ex + ew / 2 + 0.03, top), (ex + ew / 2 + 0.03, y_lid + tilt),
                   (ex - ew / 2 - 0.03, y_lid - tilt)]
            p.poly(pts, skin, line=False)
            p.line([(ex - ew / 2 - 0.005, y_lid - tilt), (ex + ew / 2 + 0.005, y_lid + tilt)], 0.025)
    my = mouth_y
    if mouth == "flat":
        p.line([(-0.09, my), (0.09, my)], 0.03)
    elif mouth == "open":
        p.rrect(0, my + 0.02, 0.14, 0.16, 0.06, INK, line=False)
        p.ellipse(0, my + 0.07, 0.10, 0.05, PINK, line=False)
    elif mouth == "smirk":
        p.arc(0.02, my - 0.06, 0.20, 0.12, 20, 150, 0.03)
    elif mouth == "smile":
        p.arc(0, my - 0.08, 0.24, 0.18, 15, 165, 0.035)
    elif mouth == "zigzag":
        p.line([(-0.12, my), (-0.06, my - 0.04), (0.0, my), (0.06, my - 0.04), (0.12, my)], 0.03)
    elif mouth == "teeth":
        p.rrect(0, my, 0.28, 0.11, 0.04, WHITE, o=p.L(0.025))
        for x in (-0.07, 0.0, 0.07):
            p.line([(x, my - 0.045), (x, my + 0.045)], 0.018)
    elif mouth == "o":
        p.ellipse(0, my, 0.07, 0.08, INK, line=False)
    if expr == "panic":
        x, y = eye_dx + 0.2, -0.22
        p.poly([(x, y - 0.08), (x + 0.045, y + 0.01), (x, y + 0.045), (x - 0.045, y + 0.01)], CYAN, o=p.L(0.018))


# Pip's own face (the series face): solid dot eyes with a glint and thick slanted brows that carry the expression, no
# eye whites and no lids. (brow tilt: + = inner ends down / cross; raise in hu; eye scale; mouth; eye style)
PIP_EXPR = {
    "deadpan": (0.00, 0.00, 1.00, "flat", "dot"),
    "side": (0.00, 0.00, 1.00, "flat", "side"),
    "shock": (-0.05, 0.09, 1.30, "open", "ring"),
    "smug": (0.05, 0.02, 1.00, "smirk", "dot"),
    "panic": (-0.09, 0.05, 0.90, "zigzag", "dot"),
    "strain": (0.10, -0.02, 1.00, "teeth", "squeeze"),
    "happy": (-0.03, 0.04, 1.00, "smile", "arc"),
    "sip": (0.00, 0.01, 1.00, "o", "dot"),
    "spit": (0.08, 0.06, 1.00, "spit", "squeeze"),
}


def pip_face(p: Pen, expr: str, blink: bool, eye_dx=0.2, eye_y=0.02, mouth_y=0.25):
    tilt, raise_, es, mouth, style = PIP_EXPR.get(expr, PIP_EXPR["deadpan"])
    for sx in (-1, 1):
        ex = sx * eye_dx
        if blink and style in ("dot", "side", "ring"):
            p.line([(ex - 0.06, eye_y), (ex + 0.06, eye_y)], 0.035)
        elif style == "squeeze":                                   # > <
            p.line([(ex - sx * 0.06, eye_y - 0.05), (ex + sx * 0.04, eye_y), (ex - sx * 0.06, eye_y + 0.05)], 0.035)
        elif style == "arc":                                       # happy closed eyes
            p.arc(ex, eye_y + 0.03, 0.13, 0.12, 200, 340, 0.035)
        else:
            gx = 0.035 if style == "side" else 0.0
            if style == "ring":
                p.ellipse(ex, eye_y, 0.17 * es, 0.19 * es, WHITE, o=p.L(0.02))
            p.ellipse(ex + gx, eye_y, 0.095 * es, 0.12 * es, INK, line=False)
            p.ellipse(ex + gx + 0.02, eye_y - 0.03, 0.035, 0.035, WHITE, line=False)
        by = eye_y - 0.14 - raise_
        inner, outer = ex - sx * 0.05, ex + sx * 0.08
        p.line([(inner, by + tilt * 0.5), (outer, by - tilt * 0.5)], 0.055)
    my = mouth_y
    if mouth == "flat":
        p.line([(-0.07, my), (0.07, my)], 0.03)
    elif mouth == "open":
        p.rrect(0, my + 0.03, 0.14, 0.17, 0.06, INK, line=False)
        p.ellipse(0, my + 0.08, 0.10, 0.05, PINK, line=False)
    elif mouth == "smirk":
        p.arc(0.03, my - 0.06, 0.18, 0.12, 20, 150, 0.03)
    elif mouth == "smile":
        p.rrect(0, my + 0.01, 0.22, 0.1, 0.05, INK, line=False)
        p.rrect(0, my - 0.01, 0.18, 0.04, 0.02, WHITE, line=False)
    elif mouth == "zigzag":
        p.line([(-0.11, my), (-0.055, my - 0.04), (0.0, my), (0.055, my - 0.04), (0.11, my)], 0.03)
    elif mouth == "teeth":
        p.rrect(0, my, 0.26, 0.1, 0.04, WHITE, o=p.L(0.025))
        p.line([(0.0, my - 0.04), (0.0, my + 0.04)], 0.018)
    elif mouth == "o":
        p.ellipse(0, my, 0.06, 0.07, INK, line=False)
    elif mouth == "spit":
        p.ellipse(0.02, my + 0.02, 0.2, 0.15, INK, line=False)
        p.ellipse(0.06, my + 0.01, 0.1, 0.07, (167, 139, 250), line=False)
    if expr == "panic":
        x, y = eye_dx + 0.22, -0.2
        p.poly([(x, y - 0.08), (x + 0.045, y + 0.01), (x, y + 0.045), (x - 0.045, y + 0.01)], CYAN, o=p.L(0.018))


def mitten(p: Pen, x, y, skin, toward=(0.0, -1.0), size=0.23):
    """Pip's mitten hand: an oval palm with a thumb nub pointing `toward` (unit-ish, hu space)."""
    p.ellipse(x, y, size, size * 0.9, skin, o=p.L(0.022))
    tx, ty = toward
    n = math.hypot(tx, ty) or 1.0
    p.ellipse(x + tx / n * size * 0.45, y + ty / n * size * 0.45, size * 0.42, size * 0.42, skin, o=p.L(0.02))
    p.ellipse(x, y, size * 0.8, size * 0.72, skin, line=False)


# ------------------------------------------------------------------------------------------------- props (in hu)
def brand_mark_on(p: Pen, cx, cy, h_hu):
    """Our green R-arrow mark (card_reel.brand_mark), h_hu tall, centred at (cx, cy) hu."""
    hpx = max(4, int(p.L(h_hu)))
    mk = cr.brand_mark(hpx)
    x, y = p.P(cx, cy)
    p.img.alpha_composite(mk, (int(x - mk.size[0] / 2), int(y - mk.size[1] / 2)))


def phone_in_hand(p: Pen, cx, cy, w=0.46, glow=CYAN):
    """A phone held up, screen to the viewer: our app's mark on the screen (the app in the story is RapidTradeView)."""
    h = w * 1.75
    p.rrect(cx, cy, w, h, w * 0.18, INK, o=p.L(0.02))
    p.rrect(cx, cy, w * 0.84, h * 0.88, w * 0.12, (22, 20, 52), line=False)
    brand_mark_on(p, cx, cy - h * 0.2, w * 0.46)
    pts = [(cx - w * 0.28, cy + h * 0.3), (cx - w * 0.1, cy + h * 0.2), (cx + w * 0.04, cy + h * 0.25), (cx + w * 0.28, cy + h * 0.12)]
    p.line(pts, w * 0.06, glow)


def shaker(p: Pen, cx, cy, s=1.0, level=0.6):
    w, h = 0.55 * s, 0.95 * s
    p.rrect(cx, cy, w, h, 0.12 * s, (200, 246, 252))
    lh = h * level
    p.rrect(cx, cy + h / 2 - lh / 2 - 0.03 * s, w - 0.08 * s, lh - 0.04 * s, 0.08 * s, (167, 139, 250), line=False)
    p.rrect(cx, cy - h / 2 - 0.06 * s, w * 1.1, 0.2 * s, 0.07 * s, WHITE)
    p.rrect(cx, cy - h / 2 - 0.2 * s, w * 0.36, 0.12 * s, 0.04 * s, CYAN)


def tab_card(p: Pen, cx, cy, w, h, accent, k=0):
    p.rrect(cx, cy, w, h, min(w, h) * 0.12, (236, 240, 255))
    p.rrect(cx, cy - h / 2 + h * 0.11, w, h * 0.22, min(w, h) * 0.1, accent, line=False)
    for j in range(3):
        y = cy - h * 0.08 + j * h * 0.2
        x0 = cx - w * 0.36
        x1 = cx + w * (0.3 - 0.12 * ((j + k) % 3))
        n = 6
        pts = [(x0 + (x1 - x0) * i / n, y + (0.02 * h if i % 2 else -0.02 * h)) for i in range(n + 1)]
        p.line(pts, h * 0.045, (148, 163, 184))


ACCENTS = (VIOLET, CYAN, LIME, CORAL, GREEN, (251, 191, 36))


@lru_cache(maxsize=256)
def tab_sprite(px_w: int, k: int):
    hu = px_w
    p = Pen(1.3, 1.05, hu, origin=(0.65, 0.52))
    tab_card(p, 0, 0, 1.0, 0.72, ACCENTS[k % len(ACCENTS)], k)
    return p.done((0, 0))


# ------------------------------------------------------------------------------------------------- characters
PIP_SKIN, PIP_HOOD = (141, 232, 195), VIOLET
DALE_SKIN, DALE_TANK, DALE_SHORTS = (168, 107, 69), CORAL, NAVY

PIP_POSES = {  # (left hand, right hand) in hu from the head centre (image left / right)
    "idle": ((-0.66, 1.05), (0.66, 1.05)),
    "phone_hold": ((-0.16, 0.86), (0.16, 0.86)),
    "press": ((-0.78, -0.38), (0.78, -0.38)),
    "strain": ((-0.5, -0.55), (0.5, -0.55)),
    "shrug": ((-0.78, 0.42), (0.78, 0.42)),
    "point": ((-0.66, 1.05), (0.98, 0.36)),
    "arms_up": ((-0.72, -0.3), (0.72, -0.3)),
    "sip": ((-0.66, 1.05), (0.12, 0.34)),
    "wave": ((-0.66, 1.05), (0.9, -0.3)),
    "flail": ((-0.95, 0.1), (0.9, 0.6)),
    "rack": ((-0.4, 0.47), (0.4, 0.47)),
    "spit": ((-0.66, 1.05), (0.66, 0.66)),
}
DALE_POSES = {
    "idle": ((-0.55, 1.55), (1.45, 2.55)),
    "sip": ((-0.25, 0.42), (1.45, 2.55)),
    "lean": ((-0.55, 1.55), (1.2, 2.1)),
    "point": ((-0.55, 1.55), (1.9, 0.7)),
    "empty": ((-0.55, 1.55), (1.45, 2.55)),
    "shout": ((-0.55, 1.55), (1.7, 0.2)),
}


def headband(p: Pen, band=0.0):
    """Pip's lime headband, high on the forehead (the brows below it carry his expressions), knot tails on the left."""
    ang = math.radians(8 + band)
    cx, cy, L, T = 0.0, -0.33, 1.06, 0.12
    c, s = math.cos(ang), math.sin(ang)
    pts = [(cx + dx * c - dy * s, cy + dx * s + dy * c) for dx, dy in ((-L / 2, -T / 2), (L / 2, -T / 2), (L / 2, T / 2), (-L / 2, T / 2))]
    p.poly(pts, LIME, o=p.L(0.025))
    p.poly([(-0.5, -0.4), (-0.7, -0.5), (-0.66, -0.3)], LIME, o=p.L(0.02))


PIP_SQUAT_DROP = 0.32          # hu the body sinks at full squat depth (the feet stay put)


def bar_with_load(p: Pen, y, half=1.3, plates=0, tabs=0, bend=0.0, k0=0):
    """A front-view barbell across x -half..half at height y: iron plates or app tabs stacked as plates; bend sags the
    ends down (the bar bows under the tabs)."""
    n = 20
    pts = [(-half + 2 * half * i / n, y + bend * 0.35 * (abs(i - n / 2) / (n / 2)) ** 2) for i in range(n + 1)]
    p.line(pts, 0.06, (203, 213, 225))
    end_y = y + bend * 0.35
    for sx in (-1, 1):
        for j in range(plates):
            p.rrect(sx * (half - 0.2 + 0.1 * j), end_y, 0.09, 0.5, 0.03, (100, 116, 139), o=p.L(0.02))
        for j in range(tabs):
            x = sx * (half - 0.28 + 0.1 * (j % 4))
            yy = end_y - 0.06 * (j // 4)
            p.rrect(x, yy, 0.09, 0.62 + 0.08 * (j % 3), 0.04, ACCENTS[(j + k0) % len(ACCENTS)], o=p.L(0.016))


def pip(pose="idle", expr="deadpan", hu=300, blink=False, hold=(), kick=0.0, band=0.0, squat=0.0, bar=None):
    """Pip, the protagonist ("you"): mint squircle head with dot eyes and thick brows, violet hoodie with cuffed sleeves and
    mitten hands, a lime headband slipping over one eye. squat (0-1) bends the knees and sinks the body; bar =
    (plates, tabs, bend) puts a front-rack barbell across the shoulders (pose "rack")."""
    p = Pen(3.0, 2.95, hu, origin=(1.5, 0.95))
    hands = PIP_POSES.get(pose, PIP_POSES["idle"])
    sh = ((-0.36, 0.52), (0.36, 0.52))
    behind = pose in ("idle", "press", "strain", "arms_up", "wave", "shrug", "flail")
    drop = PIP_SQUAT_DROP * squat
    # legs + shoes (feet fixed; with squat the hips sink and the knees go out)
    for sx, ph in ((-1, 0.0), (1, math.pi)):
        k = 0.12 * math.sin(kick * 2 * math.pi + ph) if kick else 0.0
        hip, foot = (sx * 0.2, 1.25 + drop), (sx * 0.24 + k, 1.67 - abs(k) * 0.3)
        if squat > 0.05:
            knee = (sx * (0.26 + 0.42 * squat), min(1.56, 1.36 + drop * 0.6))
            p.capsule(hip, knee, 0.2, NAVY)
            p.capsule(knee, foot, 0.18, NAVY)
        else:
            p.capsule(hip, foot, 0.18, NAVY)
        p.rrect(foot[0] + sx * 0.06, foot[1] + 0.06, 0.30, 0.13, 0.06, WHITE)
    p.oy += drop                                    # everything above the hips sinks with the squat

    def arm(a, b):
        p.capsule(a, b, 0.21, PIP_HOOD)
        cuff = (a[0] + (b[0] - a[0]) * 0.8, a[1] + (b[1] - a[1]) * 0.8)
        p.capsule(cuff, (a[0] + (b[0] - a[0]) * 0.9, a[1] + (b[1] - a[1]) * 0.9), 0.23, LIME, o=p.L(0.02))
        mitten(p, b[0], b[1], PIP_SKIN, toward=(-(b[0] - a[0]) * 0.2, -1.0))
    if behind:
        for a, b in zip(sh, hands):
            arm(a, b)
    # hoodie body (trapezoid look: a rounded rect + a wider hem), pocket, hood ring
    p.rrect(0, 0.88, 0.84, 0.95, 0.2, PIP_HOOD)
    p.rrect(0, 1.29, 0.9, 0.12, 0.05, darker(PIP_HOOD), line=False)
    p.rrect(0, 1.05, 0.46, 0.18, 0.07, darker(PIP_HOOD), line=False)
    p.ellipse(0, 0.42, 0.62, 0.2, darker(PIP_HOOD, 0.2))
    # head
    p.rrect(0, 0, 1.0, 0.92, 0.36, PIP_SKIN)
    pip_face(p, expr, blink)
    headband(p, band)
    if not behind:
        if "phone" in hold:
            phone_in_hand(p, 0, 0.7)
        for a, b in zip(sh, hands):
            arm(a, b)
    if "shaker" in hold:
        shaker(p, hands[1][0], hands[1][1] - 0.2, 0.42, level=0.3)
    if "barbell" in hold:
        y = hands[0][1]
        p.line([(-1.25, y), (1.25, y)], 0.05, (203, 213, 225))
        for x in (-1.12, 1.12):
            p.rrect(x, y, 0.1, 0.32, 0.03, (100, 116, 139), o=p.L(0.02))
        for b in hands:
            mitten(p, b[0], b[1], PIP_SKIN)
    if bar is not None:                              # front rack: bar on the shoulders, mittens on top of it
        plates, tabs, bend = bar
        bar_with_load(p, 0.5, 1.3, plates, tabs, bend)
        for sx in (-1, 1):
            mitten(p, sx * 0.4, 0.47, PIP_SKIN, toward=(-sx, -0.4))
    p.oy -= drop
    return p.done((0, 1.8))


def pip_boxes(pose="idle", hold=(), squat=0.0, bar=None):
    """Pip's protected boxes in hu relative to his anchor (feet at (0, 0), y down): the head (with headband) and any held
    prop. Captions must stay off these (cartoon_qa.occlusion_gate)."""
    dy = PIP_SQUAT_DROP * squat - 1.8
    out = [("pip face", (-0.58, dy - 0.56, 0.58, dy + 0.5))]
    hands = PIP_POSES.get(pose, PIP_POSES["idle"])
    if "phone" in hold:
        out.append(("pip phone", (-0.25, dy + 0.28, 0.25, dy + 1.12)))
    if "shaker" in hold:
        hx, hy = hands[1]
        out.append(("pip shaker", (hx - 0.15, hy - 0.2 - 0.32 + dy, hx + 0.15, hy - 0.2 + 0.24 + dy)))
    if bar is not None:                              # bar at 0.5 hu below the head centre, ends sag by bend, plates hang
        plates, tabs, bend = bar
        low = 0.5 + bend * 0.35 + (0.36 if tabs else 0.27 if plates else 0.05)
        out.append(("pip bar", (-1.4, dy + 0.15, 1.4, dy + low)))
    return out


def dale(pose="idle", expr="deadpan", hu=170, blink=False, brow=0.0, hold=("shaker",)):
    """Dale, the gym regular: tiny head, big coral tank top, chunky brows, never without his shaker."""
    p = Pen(5.2, 6.0, hu, origin=(2.6, 0.75))
    hands = DALE_POSES.get(pose, DALE_POSES["idle"])
    sh = ((-1.05, 0.95), (1.05, 0.95))
    for sx in (-1, 1):
        p.capsule((sx * 0.55, 3.6), (sx * 0.58, 4.55), 0.4, DALE_SKIN)
        p.rrect(sx * 0.7, 4.66, 0.75, 0.3, 0.12, WHITE)
    p.rrect(0, 3.45, 2.15, 0.75, 0.2, DALE_SHORTS)
    p.capsule((0, 0.25), (0, 0.75), 0.42, DALE_SKIN)
    p.rrect(0, 1.95, 2.3, 2.6, 0.38, DALE_TANK)
    p.ellipse(0, 0.75, 0.75, 0.42, DALE_SKIN, line=False)
    p.arc(0, 0.53, 0.8, 0.5, 10, 170, 0.06)
    for sx in (-1, 1):
        p.ellipse(sx * 1.0, 0.98, 0.55, 0.42, DALE_SKIN, line=False)
    for a, b in zip(sh, hands):
        p.capsule(a, b, 0.42, DALE_SKIN)
        p.ellipse(b[0], b[1], 0.46, 0.46, DALE_SKIN)
    p.rrect(0, 0, 1.0, 0.95, 0.36, DALE_SKIN)
    face(p, DALE_SKIN, expr, blink, mouth_y=0.25)
    tilt = {"smug": 0.06, "side": 0.04, "shock": -0.05}.get(expr, 0.0)
    for sx in (-1, 1):
        y = -0.25 + brow * (0.06 if sx < 0 else -0.04)
        p.line([(sx * 0.07, y + (tilt if sx < 0 else -tilt) * 0.5), (sx * 0.33, y - (tilt if sx < 0 else -tilt) * 0.5)], 0.09)
    if "shaker" in hold and pose != "empty":
        hx, hy = hands[0]
        shaker(p, hx, hy - 0.25, 1.0, level=0.15 if pose == "sip" else 0.65)
        p.ellipse(hx, hy, 0.46, 0.46, DALE_SKIN)
    return p.done((0, 4.82))


def head_only(who="pip", expr="smug", hu=300, blink=False, brow=0.0):
    """A head on its own (end card, and the PEEK cut-ins that keep a character on screen during the real screenshot)."""
    p = Pen(1.6, 1.5, hu, origin=(0.8, 0.75))
    if who == "pip":
        p.rrect(0, 0, 1.0, 0.92, 0.36, PIP_SKIN)
        pip_face(p, expr, blink)
        headband(p)
        return p.done((0, 0))
    if who == "dale":
        p.rrect(0, 0, 1.0, 0.95, 0.36, DALE_SKIN)
        face(p, DALE_SKIN, expr, blink, mouth_y=0.25)
        tilt = {"smug": 0.06, "side": 0.04, "shock": -0.05}.get(expr, 0.0)
        for sx in (-1, 1):
            y = -0.25 + brow * (0.06 if sx < 0 else -0.04)
            p.line([(sx * 0.07, y + (tilt if sx < 0 else -tilt) * 0.5), (sx * 0.33, y - (tilt if sx < 0 else -tilt) * 0.5)], 0.09)
        return p.done((0, 0))
    raise ValueError(who)


def dale_boxes(pose="idle", hold=("shaker",)):
    """Dale's protected boxes in hu relative to his anchor (feet at (0, 0)): the head and the shaker he holds."""
    dy = -4.82
    out = [("dale face", (-0.56, dy - 0.56, 0.56, dy + 0.52))]
    if "shaker" in hold and pose != "empty":
        hx, hy = DALE_POSES.get(pose, DALE_POSES["idle"])[0]
        out.append(("dale shaker", (hx - 0.36, hy - 0.25 - 0.8 + dy, hx + 0.36, hy - 0.25 + 0.55 + dy)))
    return out


# ------------------------------------------------------------------------------------------------- small props
def cat_box(hu=300, sock=False):
    p = Pen(1.6, 1.5, hu, origin=(0.8, 0.8))
    fur = (251, 146, 60)
    p.poly([(-0.42, -0.22), (-0.3, -0.62), (-0.1, -0.32)], fur)
    p.poly([(0.42, -0.22), (0.3, -0.62), (0.1, -0.32)], fur)
    p.rrect(0, -0.05, 0.9, 0.72, 0.3, fur)
    face(p, fur, "deadpan", False, eye_dx=0.17, eye_y=-0.1, mouth_y=0.08)
    for sx in (-1, 1):
        for dy in (0.0, 0.07):
            p.line([(sx * 0.3, 0.05 + dy), (sx * 0.58, 0.02 + dy * 1.6)], 0.018)
    if sock:
        p.poly([(-0.5, 0.18), (0.5, 0.18), (0.55, 0.62), (-0.55, 0.62)], (244, 114, 182))
        for y in (0.3, 0.45):
            p.line([(-0.5, y), (0.5, y)], 0.06, WHITE)
    else:
        p.poly([(-0.6, 0.2), (0.6, 0.2), (0.55, 0.65), (-0.55, 0.65)], (180, 120, 70))
        p.poly([(-0.6, 0.2), (-0.75, 0.05), (-0.45, 0.05)], (150, 98, 56))
    return p.done((0, 0))


def sock(hu=300):
    p = Pen(1.2, 1.4, hu, origin=(0.5, 0.65))
    pts = [(-0.18, -0.55), (0.18, -0.55), (0.18, 0.2), (0.45, 0.32), (0.45, 0.58), (-0.05, 0.58), (-0.18, 0.4)]
    p.poly(pts, (34, 211, 238))
    for y in (-0.42, -0.3):
        p.line([(-0.17, y), (0.17, y)], 0.06, WHITE)
    return p.done((0, 0))


def bench_top(hu=300):
    p = Pen(1.4, 3.2, hu, origin=(0.7, 1.6))
    for y in (-1.2, 1.2):
        p.rrect(0, y, 1.25, 0.12, 0.05, (100, 116, 139))
    p.rrect(0, 0, 0.8, 2.9, 0.3, DESK_TOP)
    p.rrect(0, -1.0, 0.55, 0.62, 0.22, lighter(DESK_TOP, 0.12), line=False)
    return p.done((0, 0))


def bench_side(hu=300):
    p = Pen(3.2, 1.2, hu, origin=(1.6, 0.3))
    for x in (-1.1, 1.1):
        p.rrect(x, 0.45, 0.12, 0.7, 0.04, (100, 116, 139))
    p.rrect(0, 0.05, 2.9, 0.26, 0.12, DESK_TOP)
    return p.done((0, 0))


def barbell(width_px=900, plates=2, tabs=0, bend=0.0, k0=0):
    """A side-view barbell: `plates` small iron plates per side, or `tabs` app tabs stacked as plates; bend sags the bar."""
    hu = width_px / 3.0
    p = Pen(3.4, 2.4, hu, origin=(1.7, 0.9))
    n = 24
    pts = [(-1.5 + 3.0 * i / n, bend * 0.55 * (1 - ((i - n / 2) / (n / 2)) ** 2)) for i in range(n + 1)]
    p.line(pts, 0.06, (203, 213, 225))
    end_y = 0.0
    for sx in (-1, 1):
        for j in range(plates):
            p.rrect(sx * (1.18 + 0.1 * j), end_y, 0.09, 0.42, 0.03, (100, 116, 139), o=p.L(0.02))
        for j in range(tabs):
            x = sx * (1.05 + 0.13 * (j % 4))
            y = end_y - 0.05 * (j // 4)
            p.rrect(x, y - 0.0, 0.11, 0.9 + 0.08 * (j % 3), 0.04, ACCENTS[(j + k0) % len(ACCENTS)], o=p.L(0.018))
    return p.done((0, 0))


def search_bar(w_px=880, caret=True, text="Search"):
    font = cr.font
    h = 150
    img = Image.new("RGBA", ((w_px + 40) * SS, (h + 40) * SS), CLEAR)
    d = ImageDraw.Draw(img)
    o = 8 * SS
    box = (20 * SS, 20 * SS, (20 + w_px) * SS, (20 + h) * SS)
    d.rounded_rectangle((box[0] - o, box[1] - o, box[2] + o, box[3] + o), radius=(h // 2) * SS + o, fill=INK)
    d.rounded_rectangle(box, radius=(h // 2) * SS, fill=(236, 240, 255))
    cx, cy = box[0] + 80 * SS, (box[1] + box[3]) // 2
    r = 30 * SS
    d.ellipse((cx - r, cy - r - 6 * SS, cx + r, cy + r - 6 * SS), outline=INK, width=9 * SS)
    d.line((cx + 20 * SS, cy + 14 * SS, cx + 44 * SS, cy + 38 * SS), fill=INK, width=11 * SS)
    f = font("semi", 64 * SS)
    d.text((box[0] + 140 * SS, cy), text, font=f, fill=(100, 116, 139), anchor="lm")
    if caret:
        x = box[0] + 140 * SS + f.getlength(text) + 10 * SS
        d.rectangle((x, cy - 36 * SS, x + 6 * SS, cy + 36 * SS), fill=VIOLET)
    img = img.resize((img.size[0] // SS, img.size[1] // SS), Image.LANCZOS)
    return img, (img.size[0] / 2, img.size[1] / 2)


# ------------------------------------------------------------------------------------------------- sets (world canvas)
def vgrad(w, h, c0, c1):
    t = np.linspace(0, 1, h)[:, None, None]
    arr = (np.array(c0, np.float32) * (1 - t) + np.array(c1, np.float32) * t)
    return Image.fromarray(np.broadcast_to(arr, (h, w, 3)).astype(np.uint8), "RGB")


SKY_TABLE = [(0, 260), (70, 380), (150, 300), (210, 470), (300, 340), (360, 520), (450, 290), (520, 410), (600, 360),
             (660, 560), (750, 320), (820, 450), (900, 380), (960, 500), (1050, 300), (1120, 430), (1200, 350), (1280, 480)]


def set_gym(size, off, variant=0):
    """Night gym, side view: violet wall, a wide window with a city skyline, a mirror strip, a dumbbell rack, rubber floor
    (world y > 1420)."""
    W_, H_ = size
    ox, oy = off
    img = vgrad(W_, H_, NIGHT_TOP, NIGHT_BOT)
    d = ImageDraw.Draw(img)
    floor_y = oy + 1420
    # window + skyline
    wx0, wy0, wx1, wy1 = ox + 40, oy + 180, ox + 1040, oy + 820
    sky = vgrad(wx1 - wx0, wy1 - wy0, SKY0, SKY1)
    sd = ImageDraw.Draw(sky)
    for i, (x, hgt) in enumerate(SKY_TABLE):
        x0 = x * (wx1 - wx0) / 1300
        bw = 60 + (i * 37) % 50
        top = (wy1 - wy0) - hgt * 0.9
        sd.rectangle((x0, top, x0 + bw, wy1 - wy0), fill=SKYLINE)
        for r in range(int(top) + 14, wy1 - wy0 - 10, 34):
            for c in range(int(x0) + 10, int(x0 + bw) - 10, 22):
                if (r * 7 + c * 13 + i) % 5 == 0:
                    sd.rectangle((c, r, c + 9, r + 14), fill=((34, 211, 238), (188, 255, 34), (253, 230, 138))[(r + c) % 3])
    img.paste(sky, (wx0, wy0))
    d.rectangle((wx0 - 14, wy0 - 14, wx1 + 14, wy1 + 14), outline=INK, width=14)
    d.line((wx0 + (wx1 - wx0) // 2, wy0, wx0 + (wx1 - wx0) // 2, wy1), fill=INK, width=12)
    # mirror strip + rack
    d.rectangle((ox - 200, oy + 960, ox + 1300, oy + 1000), fill=(58, 47, 134))
    for i in range(7):
        x = ox - 120 + i * 210 + (variant * 60) % 210
        d.rounded_rectangle((x, oy + 1130, x + 150, oy + 1190), radius=24, fill=INK)
        d.rounded_rectangle((x + 10, oy + 1140, x + 40, oy + 1180), radius=10, fill=(76, 29, 149))
        d.rounded_rectangle((x + 110, oy + 1140, x + 140, oy + 1180), radius=10, fill=(76, 29, 149))
    d.rectangle((ox - 200, oy + 1200, ox + 1300, oy + 1225), fill=INK)
    # floor
    d.rectangle((0, floor_y, W_, H_), fill=NIGHT_FLOOR)
    d.line((0, floor_y, W_, floor_y), fill=INK, width=10)
    for i in range(-6, 12):
        x = ox + 540 + i * 220
        d.line((ox + 540 + i * 70, floor_y, x, H_), fill=(28, 24, 72), width=6)
    return img


def set_gym_floor(size, off):
    """Top-down gym floor: rubber tiles and a violet mat."""
    W_, H_ = size
    img = Image.new("RGB", size, NIGHT_FLOOR)
    d = ImageDraw.Draw(img)
    for x in range(off[0] % 240 - 240, W_, 240):
        d.line((x, 0, x, H_), fill=(30, 25, 80), width=8)
    for y in range(off[1] % 240 - 240, H_, 240):
        d.line((0, y, W_, y), fill=(30, 25, 80), width=8)
    ox, oy = off
    d.rounded_rectangle((ox + 140, oy + 260, ox + 940, oy + 1700), radius=60, fill=(46, 30, 120), outline=INK, width=12)
    return img


def set_screen(size, off, color=(15, 18, 34)):
    """A giant phone screen as the set (for the feed and the search bar)."""
    W_, H_ = size
    img = vgrad(W_, H_, (24, 20, 64), (12, 10, 36))
    d = ImageDraw.Draw(img)
    ox, oy = off
    d.rounded_rectangle((ox + 30, oy + 60, ox + 1050, oy + 1860), radius=90, fill=color, outline=INK, width=26)
    d.rounded_rectangle((ox + 470, oy + 100, ox + 610, oy + 130), radius=15, fill=(30, 34, 56))
    return img


def feed_strip(width=900, seed_cards=("cat", "sock_ad", "cat_sock", "cat", "sock_ad", "cat", "cat_sock", "cat")):
    """The doom-scroll feed: a tall strip of cards (cats, a sock ad, a cat in a sock). Words only, no numbers."""
    font = cr.font
    ch = 760
    img = Image.new("RGBA", (width, ch * len(seed_cards) + 40), (15, 18, 34, 255))
    d = ImageDraw.Draw(img)
    for i, kind in enumerate(seed_cards):
        y = 20 + i * ch
        d.rounded_rectangle((20, y, width - 20, y + ch - 40), radius=44, fill=(30, 34, 60), outline=(48, 54, 90), width=4)
        d.ellipse((50, y + 30, 120, y + 100), fill=(76, 29, 149))
        d.rounded_rectangle((140, y + 45, 420, y + 85), radius=18, fill=(56, 62, 98))
        if kind == "sock_ad":
            d.rounded_rectangle((60, y + 130, width - 60, y + ch - 150), radius=30, fill=(253, 230, 138))
            s, a = sock(380)
            img.alpha_composite(s, (int(width / 2 - a[0] - 120), int(y + 140)))
            f = font("black", 110)
            d.text((width * 0.68, y + ch * 0.42), "SOCKS", font=f, fill=INK, anchor="mm")
            f2 = font("bold", 46)
            d.rounded_rectangle((70, y + 140, 170, y + 196), radius=14, fill=INK)
            d.text((120, y + 168), "ad", font=f2, fill=WHITE, anchor="mm")
        else:
            d.rounded_rectangle((60, y + 130, width - 60, y + ch - 150), radius=30, fill=(46, 40, 110))
            c, a = cat_box(330, sock=(kind == "cat_sock"))
            img.alpha_composite(c, (int(width / 2 - a[0]), int(y + 130 + (ch - 280) / 2 - a[1])))
        for j, x in enumerate((70, 200, 330)):
            d.ellipse((x, y + ch - 120, x + 56, y + ch - 64), outline=(120, 130, 170), width=6)
    return img


# ------------------------------------------------------------------------------------------------- PUNCH rings
_RING_CACHE: dict = {}


def rings(t: float, centre, pair="violet", size=(1080, 1920), speed=120.0, band=90.0):
    """Concentric two-tone rings expanding at `speed` px/s around `centre` (screen px), plus 10 radial speed lines.
    Drawn at half resolution with numpy and upscaled (the rings always move)."""
    w, h = size[0] // 2, size[1] // 2
    cx, cy = centre[0] / 2, centre[1] / 2
    key = (w, h)
    if key not in _RING_CACHE:
        _RING_CACHE[key] = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    gx, gy = _RING_CACHE[key]
    r = np.hypot(gx - cx, gy - cy) * 2
    b = (np.floor((r - speed * t) / band) % 2).astype(np.uint8)
    c0, c1 = RING_PAIRS.get(pair, RING_PAIRS["violet"])
    pal = np.array([c1, c0], np.uint8)
    arr = pal[b]
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img)
    lc = lighter(c0, 0.45)
    for i in range(10):
        a = 2 * math.pi * (i / 10) + 0.31 + 0.15 * t
        r0 = (260 + 40 * ((i * 7) % 3) + 60 * ((t * 1.4 + i * 0.37) % 1.0))
        r1 = r0 + 200 + 50 * (i % 3)
        d.line((cx + r0 * math.cos(a), cy + r0 * math.sin(a), cx + r1 * math.cos(a), cy + r1 * math.sin(a)), fill=lc, width=3)
    return img.resize(size, Image.BICUBIC)


# ------------------------------------------------------------------------------------------------- bubbles and chips
def sfx_bubble(text: str, fill=LIME, size=76, tail_deg=120.0, font_fn=None):
    """A speech-bubble SFX word: pill body (radius = height/2), a 36 px tail pointing at the source (tail_deg: 0 = right,
    90 = down), three INK tick lines on the far side, INK outline 7 px, Segoe UI Black INK text."""
    f = font_fn("black", size * SS)
    bb = f.getbbox(text, anchor="ls")
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    px, py = 26 * SS, 16 * SS
    bw, bh = tw + 2 * px, th + 2 * py + 8 * SS
    pad = 80 * SS
    W_, H_ = bw + 2 * pad, bh + 2 * pad
    img = Image.new("RGBA", (W_, H_), CLEAR)
    d = ImageDraw.Draw(img)
    cx, cy = W_ / 2, H_ / 2
    o = 7 * SS
    a = math.radians(tail_deg)
    ex, ey = cx + math.cos(a) * (bw / 2 * 0.62 + 36 * SS), cy + math.sin(a) * (bh / 2 + 36 * SS)
    bx, by = cx + math.cos(a) * bw / 2 * 0.45, cy + math.sin(a) * bh / 2 * 0.6
    nx, ny = -math.sin(a), math.cos(a)
    tail = [(bx + nx * 20 * SS, by + ny * 20 * SS), (ex, ey), (bx - nx * 20 * SS, by - ny * 20 * SS)]
    d.line(tail + [tail[0]], fill=INK, width=2 * o, joint="curve")
    box = (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
    d.rounded_rectangle((box[0] - o, box[1] - o, box[2] + o, box[3] + o), radius=bh / 2 + o, fill=INK)
    d.polygon(tail, fill=fill)
    d.rounded_rectangle(box, radius=bh / 2, fill=fill)
    d.text((cx - tw / 2 - bb[0], cy + th / 2 + 2 * SS), text, font=f, fill=INK, anchor="ls")
    back = a + math.pi
    for k in (-1, 0, 1):
        aa = back + math.radians(30 * k)
        r0x, r0y = bw / 2 + 18 * SS, bh / 2 + 18 * SS
        x0, y0 = cx + math.cos(aa) * r0x, cy + math.sin(aa) * r0y
        x1, y1 = x0 + math.cos(aa) * 22 * SS, y0 + math.sin(aa) * 22 * SS
        d.line((x0, y0, x1, y1), fill=INK, width=6 * SS)
    img = img.resize((W_ // SS, H_ // SS), Image.LANCZOS)
    return img


def chip(text: str, size=64, font_fn=None):
    """A ticker-chip label: navy pill, 5 px cyan border, white Segoe UI Black uppercase."""
    text = text.upper()
    f = font_fn("black", size * SS)
    bb = f.getbbox(text, anchor="ls")
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    px, py = 34 * SS, 18 * SS
    w, h = tw + 2 * px, th + 2 * py + 6 * SS
    o = 5 * SS
    img = Image.new("RGBA", (w + 4 * o + 20 * SS, h + 4 * o + 20 * SS), (34, 211, 238, 0))
    d = ImageDraw.Draw(img)
    x0, y0 = 2 * o + 10 * SS, 2 * o + 10 * SS
    d.rounded_rectangle((x0 - o - 3 * SS, y0 - o - 3 * SS, x0 + w + o + 3 * SS, y0 + h + o + 3 * SS), radius=h / 2 + o + 3 * SS, fill=INK)
    d.rounded_rectangle((x0 - o, y0 - o, x0 + w + o, y0 + h + o), radius=h / 2 + o, fill=CYAN)
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=h / 2, fill=(20, 18, 53))
    d.text((x0 + px - bb[0], y0 + py + th + 2 * SS), text, font=f, fill=WHITE, anchor="ls")
    return img.resize((img.size[0] // SS, img.size[1] // SS), Image.LANCZOS)


# ------------------------------------------------------------------------------------------------- phone + card (real screenshot)
def gradient(size, c0=VIOLET, c1=CYAN):
    w, h = size
    x = np.linspace(0, 1, w)[None, :, None]
    y = np.linspace(0, 1, h)[:, None, None]
    k = np.clip(0.85 * x + 0.15 * y, 0, 1)
    return Image.fromarray((np.array(c0) * (1 - k) + np.array(c1) * k).astype(np.uint8), "RGB")


def rounded_mask(size, radius, ss=4):
    w, h = size
    big = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=radius * ss, fill=255)
    return big.resize(size, Image.LANCZOS)


def phone_frame(shot: Image.Image, screen_w: int, bezel: int, radius: int, rim: int = 4):
    """The drawn phone around a real screenshot (left untouched apart from the resize): INK bezel, brand-gradient rim, a
    speaker pill. Returns (RGBA, scale of the screenshot inside it)."""
    k = screen_w / shot.size[0]
    sh = round(shot.size[1] * k)
    screen = shot.convert("RGB").resize((screen_w, sh), Image.LANCZOS).convert("RGBA")
    screen.putalpha(rounded_mask((screen_w, sh), max(4, radius - bezel)))
    W_, H_ = screen_w + 2 * bezel, sh + 2 * bezel
    body = gradient((W_, H_)).convert("RGBA")
    body.putalpha(rounded_mask((W_, H_), radius))
    inner = Image.new("RGBA", (W_ - 2 * rim, H_ - 2 * rim), INK + (255,))
    inner.putalpha(rounded_mask(inner.size, radius - rim))
    body.alpha_composite(inner, (rim, rim))
    body.alpha_composite(screen, (bezel, bezel))
    if bezel >= 20:
        pw, ph = max(40, screen_w // 6), max(8, bezel // 3)
        pill = Image.new("RGBA", (pw, ph), (30, 34, 56, 255))
        pill.putalpha(rounded_mask((pw, ph), ph // 2))
        body.alpha_composite(pill, ((W_ - pw) // 2, (bezel - ph) // 2))
    return body, k


def with_shadow(img: Image.Image, dy: int, blur: int, alpha: float = 0.45):
    pad = blur * 2 + abs(dy)
    out = Image.new("RGBA", (img.size[0] + 2 * pad, img.size[1] + 2 * pad), CLEAR)
    m = Image.new("L", out.size, 0)
    m.paste(img.getchannel("A"), (pad, pad + dy))
    m = m.filter(ImageFilter.GaussianBlur(blur)).point([int(v * alpha) for v in range(256)])
    sh = Image.new("RGBA", out.size, CLEAR)
    sh.putalpha(m)
    out.alpha_composite(sh)
    out.alpha_composite(img, (pad, pad))
    return out, pad


# ------------------------------------------------------------------------------------------------- search phone + receipt
FEED_TEXTS = ("SOCKS", "ad")                 # the words drawn on the feed strip (they go through the text gates)
SEARCH_PLACEHOLDER = "Search"
BRAND_NAME = cr.BRAND                        # drawn on the search phone's top bar (brand=True)


def search_phone(w_px=560, typed="", caret=True, thumb=0.0, font_fn=None, brand=True):
    """Pip's two mitten hands holding a phone close to the lens; a plain search field near the top shows `typed` (or the
    placeholder). Not our app's UI: a cartoon phone, the real screen comes after the whip. With brand (the default) the
    screen's top bar shows our mark and the name RapidTradeView, so the viewer knows which app this is. Anchor = phone centre.
    thumb (0-1) presses the right thumb onto the screen (a letter being typed)."""
    font_fn = font_fn or cr.font
    p = Pen(2.1, 2.75, w_px, origin=(1.05, 1.05))
    for sx in (-1, 1):                                          # sleeves from below the frame up to the hands
        hand = (sx * 0.55, 0.42 - (0.06 if sx > 0 else 0.0))
        p.capsule((sx * 0.85, 1.65), hand, 0.34, PIP_HOOD)
        cuff0 = (sx * 0.85 + (hand[0] - sx * 0.85) * 0.78, 1.65 + (hand[1] - 1.65) * 0.78)
        cuff1 = (sx * 0.85 + (hand[0] - sx * 0.85) * 0.9, 1.65 + (hand[1] - 1.65) * 0.9)
        p.capsule(cuff0, cuff1, 0.37, LIME, o=p.L(0.02))
    p.rrect(0, 0, 1.0, 1.85, 0.14, INK, o=p.L(0.03))
    p.rrect(0, 0.02, 0.9, 1.7, 0.1, (15, 18, 34), line=False)
    p.rrect(0, -0.8, 0.22, 0.05, 0.025, (30, 34, 56), line=False)
    if brand:                                                  # the app in the story: our mark and name, top of the screen
        fb = font_fn("bold", int(p.L(0.082)))
        tw = fb.getlength(BRAND_NAME) / p.hu
        mk_w = 0.115
        x0 = -(mk_w + 0.03 + tw) / 2
        brand_mark_on(p, x0 + mk_w / 2, -0.62, 0.1)
        bx, by = p.P(x0 + mk_w + 0.03, -0.62)
        p.d.text((bx, by), BRAND_NAME, font=fb, fill=(255, 255, 255), anchor="lm")
        p.d.line((p.P(-0.4, -0.5), p.P(0.4, -0.5)), fill=(40, 44, 72), width=max(1, int(p.L(0.008))))
    bar_y = -0.36 if brand else -0.55
    p.rrect(0, bar_y, 0.8, 0.17, 0.085, (236, 240, 255), o=p.L(0.018))
    cx, cy = p.P(-0.31, bar_y)
    r = p.L(0.032)
    p.d.ellipse((cx - r, cy - r - p.L(0.006), cx + r, cy + r - p.L(0.006)), outline=INK, width=int(p.L(0.012)))
    p.d.line((cx + r * 0.7, cy + r * 0.6, cx + r * 1.5, cy + r * 1.4), fill=INK, width=int(p.L(0.014)))
    f = font_fn("bold", int(p.L(0.085)))
    tx, ty = p.P(-0.24, bar_y)
    txt = typed or SEARCH_PLACEHOLDER
    p.d.text((tx, ty), txt, font=f, fill=INK if typed else (100, 116, 139), anchor="lm")
    if caret:
        x = tx + (f.getlength(typed) if typed else 0) + p.L(0.01)
        p.d.rectangle((x, ty - p.L(0.05), x + p.L(0.012), ty + p.L(0.05)), fill=VIOLET)
    # hands: mitten grips on both edges, the right thumb over the screen
    mitten(p, -0.55, 0.42, PIP_SKIN, toward=(1.0, -0.6), size=0.3)
    mitten(p, 0.55, 0.36, PIP_SKIN, toward=(-1.0, -0.2), size=0.3)
    th = 0.06 * thumb
    p.ellipse(0.4 - th, 0.22 + th, 0.16, 0.14, PIP_SKIN, o=p.L(0.02))           # a short thumb pad, pressing
    return p.done((0, 0))


def receipt(text: str, w_px=900, font_fn=None, size=52, header="SEC FILING"):
    """The fact phrase as a paper receipt (held on screen so the viewer can read the full sentence): cream paper, INK
    outline, a header tag, the phrase wrapped in bold INK with figures in violet and buy/sell verbs in green/red, and a
    torn zigzag bottom edge. Returns RGBA (1x)."""
    font_fn = font_fn or cr.font
    S = SS
    f = font_fn("bold", size * S)
    fh = font_fn("black", 34 * S)
    pad = 54 * S
    wmax = w_px * S - 2 * pad
    lines, cur = [], []
    for w in text.split():
        trial = " ".join(cur + [w])
        if cur and f.getlength(trial) > wmax:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    lh = int(size * 1.32 * S)
    head_h = 70 * S
    body_h = pad + head_h + lh * len(lines) + pad
    zig = 26 * S
    W_, H_ = w_px * S + 40 * S, body_h + zig + 40 * S
    img = Image.new("RGBA", (W_, H_), CLEAR)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 20 * S, 20 * S, 20 * S + w_px * S, 20 * S + body_h
    teeth = 18
    pts = [(x0, y0 + 30 * S), (x0 + 30 * S, y0), (x1 - 30 * S, y0), (x1, y0 + 30 * S), (x1, y1)]
    for i in range(teeth, -1, -1):
        pts.append((x0 + (x1 - x0) * i / teeth, y1 + (zig if i % 2 else 0)))
    d.polygon(pts, fill=INK)
    inner = [(x + (S * 7 if x < (x0 + x1) / 2 else -S * 7), y + (S * 7 if y < (y0 + y1) / 2 else -S * 7)) for x, y in pts]
    d.polygon(inner, fill=(255, 251, 240))
    # header tag
    hb = fh.getbbox(header, anchor="ls")
    hw = hb[2] - hb[0] + 44 * S
    hx, hy = x0 + pad, y0 + pad - 10 * S
    d.rounded_rectangle((hx, hy, hx + hw, hy + 52 * S), radius=26 * S, fill=INK)
    d.text((hx + 22 * S, hy + 38 * S), header, font=fh, fill=LIME, anchor="ls")
    y = y0 + pad + head_h + int(size * 0.95 * S)
    for ln in lines:
        x = x0 + pad
        for k, w in enumerate(ln):
            core = w.strip("().,;:")
            prev = ln[k - 1] if k else (lines[lines.index(ln) - 1][-1] if lines.index(ln) else "")
            if (cr.FIGURE_RX.search(w) or re.search(r"\d", w)) and not re.fullmatch(r"\(?Form", prev):
                col = VIOLET_D
            elif re.fullmatch(r"(?i)bought|buys?|purchased?", core):
                col = GREEN_D
            elif re.fullmatch(r"(?i)sold|sells?|sale", core):
                col = RED_D
            else:
                col = INK
            d.text((x, y), w, font=f, fill=col + (255,), anchor="ls")
            x += f.getlength(w + " ")
        y += lh
    img = img.resize((W_ // S, H_ // S), Image.LANCZOS)
    return img
