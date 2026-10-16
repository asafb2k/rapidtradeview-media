"""Weekly earnings calendar image (Growth test, owner 2026-10-16): the picture an earnings_week_calendar facts item posts with.

    week_calendar.py render  --item FILE --out DIR
    week_calendar.py prepare --date D --facts FILE --work DIR [--repo DIR] [--now ISO] [--no-push]
    week_calendar.py live    --date D --facts FILE --work DIR [--repo DIR] [--timeout S]
    week_calendar.py strip   --date D --facts FILE

render (pure; the mockup and the tests): FILE is the item (or a facts file that holds one); writes DIR/calendar_4x5.png and
  DIR/calendar-qa.json. A 1080 x 1350 PNG (<= 400 KB) in the Market terminal look (growth-video boards.tsx TERM), sized for
  X's phone feed (~310 px wide, reviews 2026-10-16): a title, then per day a header line (weekday, date, "N confirmed" and any
  note: early close, during market hours, time not set; a market holiday shows its name) over two full-width cells, before
  the open / after the close, each with up to 6 ticker tiles (the item's own "shown" list; "+M more" in the sixth slot).
  Tickers only (40 px, condensed only when wider than the tile): no company names, logos, favicons or yellow marker; the
  fonts are vendored in tools/fonts (Archivo, Geist, Geist Mono; OFL). Data: the item's calendar only, no request.
  Self-QA (any failure = no image): every box inside the 40 px safe area, no two texts overlap, every tile inside its cell
  and its slot (a 16 px gutter to the next), type floors (ticker 40, "+M" 34, column headers 30, all text 24), shown + more
  == total in every cell and drawn as such, a closed market day draws no tile, every digit drawn comes from the item, no
  text ends in a conjunction, PNG size. Exit 0 rendered, 1 QA failed.

prepare (daily_common.ps1 Invoke-WeekCalendar, on every facts build, before the card Reel and the compare). Fridays only (the
  facts date); other days and builds without the item leave the facts file untouched. State: <work>/week-calendar.json.
  - builds before 07:00 ET (FREEZE_FROM_ET) take the item out and freeze nothing: the API's Yahoo date check has a short
    deadline, and the 05:00 ET morning pass may catch it half done (a large company served as unconfirmed);
  - the first build at or after 07:00 ET that carries the item freezes it (later builds of the day reuse it: the image and
    the item never drift, the item_id stays), renders v/<date>/cards/<item_id>/calendar_4x5.png into the repo, lists it in
    <work>/week-calendar-files.txt, takes the item OUT of the facts file until Pages serves the image (counts and reasons
    updated) and exits 10: commit + push the file, then run `live`.
  - once live, every build gets the frozen item back with media [{url: <Pages PNG>, kind: image, alt}] (replaced or
    re-inserted), exit 0.
  - at most MAX_ATTEMPTS renders a day; after that reasons.earnings_week_calendar is "calendar image failed: ..." and there
    is no item (No Fallbacks: no image, no item; never another image).
  - --no-push (a dry run): the staged image is attached at once (Pages does not serve it) and the exit is 0.
live: waits until Pages serves the staged PNG (200 image/png, the local size; up to --timeout), marks it live and puts the item
  back into --facts with its image; exit 1 when it is not served in time (the item stays out; the next build checks again).
strip: takes the item out of --facts (the runner's guard when prepare crashed): no item without its image.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import facts as fx  # noqa: E402
import manifest as mf  # noqa: E402
import select_stories as ss  # noqa: E402

KIND = fx.WEEK_CALENDAR
FONTS = Path(__file__).resolve().parent / "fonts"
PNG = "calendar_4x5.png"
QA_FILE = "calendar-qa.json"
STATE = "week-calendar.json"
FILES = "week-calendar-files.txt"
EXIT_STAGED = 10
MAX_ATTEMPTS = 2
ALT_MAX = 1000
FREEZE_FROM_ET = 7        # the first build at or after 07:00 New York time freezes the item

# ---------------------------------------------------------------------------------------------------------------- the look
W, H = 1080, 1350
SS = 2                    # drawn at 2x, downscaled once: smooth rules and corners
SAFE = 40
MAX_BYTES = 400_000
TERM = {"base": (7, 10, 17), "head": (14, 20, 34), "cyan": (34, 211, 238), "mint": (52, 211, 153), "violet": (167, 139, 250),
        "primary": (245, 250, 250), "secondary": (196, 218, 223), "muted": (157, 176, 186), "dim": (129, 147, 160),
        "purple": (124, 58, 237), "blue": (59, 130, 246)}
FONT_FILES = {"archivo": "Archivo.ttf", "bold": "Geist-Bold.woff2", "medium": "Geist-Medium.woff2",
              "mono": "GeistMono-Medium.woff2"}
# Type floors at 1080 px (growth-video boards.tsx: 22.5 px any text, 34 px counts; X shows the image ~310 px wide on a
# phone, so 24 px reads as ~7 px and a 40 px ticker as ~11.5 px).
TICKER_PX = 40
MORE_PX = 34
TEXT_FLOOR = 24
FLOOR = {"ticker": TICKER_PX, "more": MORE_PX, "column": 30, "weekday": 34, "title": 56, "range": 40}
CONDENSED = (100, 96, 92, 88, 84, 80, 76, 72, 68, 64)   # Archivo width steps for a ticker wider than its tile (weight 800)
CONJUNCTION_END = re.compile(r"(?:\s|^)(?:and|&|of|the|,)$", re.IGNORECASE)

MX = 44                   # side margin
GAP = 12                  # between the two cells of a day
CELL_W = (W - 2 * MX - GAP) / 2
CELL_PAD = 14
SLOT_W = (CELL_W - 2 * CELL_PAD) / 3
TILE_GUTTER = 16          # a ticker keeps this much air to the next tile (a wider one is drawn condensed)
STRIP_TOP, STRIP_BOTTOM = 214, 262
ROWS_TOP = 276
ROW_PITCH = 186
DAY_HEAD = 42             # the day's header line above its cells
CELL_H = 130
LINE1, LINE2 = 52, 108    # ticker baselines inside a cell
FOOT_RULE = 1214
SESSIONS = (("bmo", "BEFORE THE OPEN", "mint", (52, 211, 153, 28)), ("amc", "AFTER THE CLOSE", "violet", (167, 139, 250, 33)))
RULE = (34, 211, 238, 77)       # rgba(34,211,238,.30)
RULE_HI = (34, 211, 238, 184)   # rgba(34,211,238,.72)
GRID = (34, 211, 238, 13)       # rgba(34,211,238,.05)
CLOSED_TINT = (129, 147, 160, 20)
TITLE = "Largest companies reporting"
SUBLINE = "By market cap in each session · confirmed dates in our coverage"


class QAError(Exception):
    """The image failed its self-QA: it is not published."""


# ---------------------------------------------------------------------------------------------------------------- drawing
_fonts: dict = {}


def font(name: str, size: float, wdth: int = 100):
    from PIL import ImageFont
    key = (name, size, wdth)
    if key not in _fonts:
        f = ImageFont.truetype(str(FONTS / FONT_FILES[name]), round(size * SS))
        if name == "archivo":
            f.set_variation_by_axes([800, wdth])
        _fonts[key] = f
    return _fonts[key]


def px(v: float) -> int:
    return round(v * SS)


class Canvas:
    """A 2x RGB canvas that logs every text it draws (1x boxes) for the self-QA."""

    def __init__(self):
        from PIL import Image, ImageDraw
        self.Image, self.ImageDraw = Image, ImageDraw
        self.img = Image.new("RGB", (W * SS, H * SS), TERM["base"])
        self.draw = ImageDraw.Draw(self.img, "RGBA")
        self.texts: list[dict] = []
        self.cells: list[dict] = []

    def width(self, s: str, name: str, size: float, tracking: float = 0.0, wdth: int = 100) -> float:
        f = font(name, size, wdth)
        if not tracking:
            return f.getlength(s) / SS
        return (sum(f.getlength(ch) for ch in s) + tracking * size * SS * (len(s) - 1)) / SS

    def text(self, x: float, base: float, s: str, name: str, size: float, fill, role: str, tracking: float = 0.0,
             wdth: int = 100, cell: dict | None = None, slot: tuple[float, float] | None = None, mask=None) -> dict:
        """Left / baseline anchored text; `mask` (an L image) collects the glyphs instead (gradient text)."""
        f = font(name, size, wdth)
        target = self.ImageDraw.Draw(mask) if mask is not None else self.draw
        ink = 255 if mask is not None else fill
        boxes = []
        if not tracking:
            boxes.append(target.textbbox((px(x), px(base)), s, font=f, anchor="ls"))
            target.text((px(x), px(base)), s, font=f, fill=ink, anchor="ls")
        else:
            cx = px(x)
            for ch in s:
                boxes.append(target.textbbox((cx, px(base)), ch, font=f, anchor="ls"))
                target.text((cx, px(base)), ch, font=f, fill=ink, anchor="ls")
                cx += f.getlength(ch) + tracking * size * SS
        boxes = [b for b in boxes if b[2] > b[0] and b[3] > b[1]]
        box = (min(b[0] for b in boxes) / SS, min(b[1] for b in boxes) / SS, max(b[2] for b in boxes) / SS,
               max(b[3] for b in boxes) / SS) if boxes else (x, base, x, base)
        rec = {"text": s, "role": role, "size": size, "box": [round(v, 2) for v in box], "font": name,
               "wdth": wdth, "cell": cell["id"] if cell else None, "slot": [round(v, 2) for v in slot] if slot else None}
        self.texts.append(rec)
        return rec

    def rect(self, box, radius: float, fill=None, outline=None, width: float = 0):
        self.draw.rounded_rectangle([px(box[0]), px(box[1]), px(box[2]), px(box[3])], radius=px(radius), fill=fill,
                                    outline=outline, width=max(1, px(width)) if outline else 0)

    def gradient_fill(self, mask, c0, c1, box: tuple[int, int, int, int] | None = None):
        """Paint c0 -> c1 (left to right) through the L `mask` over its ink (or `box`)."""
        bb = box or mask.getbbox()
        if not bb:
            return
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        grad = self.Image.new("RGB", (w, 1))
        for i in range(w):
            t = i / max(1, w - 1)
            grad.putpixel((i, 0), tuple(round(a + (b - a) * t) for a, b in zip(c0, c1)))
        grad = grad.resize((w, h))
        self.img.paste(grad, (bb[0], bb[1]), mask.crop(bb))


def background(cv: Canvas) -> None:
    """Base, two faint brand glows (CSS radial-gradient, 0 at 65 %), the 40 px grid and the 4 px mint top line."""
    import numpy as np
    Image = cv.Image
    w, h = W * SS, H * SS
    rgb = np.empty((h, w, 3), dtype=np.float32)
    rgb[:] = TERM["base"]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for (cx, cy, rx, ry, color, alpha) in ((0.95 * w, 0.0, 0.75 * w, 0.42 * h, TERM["cyan"], 0.10),
                                            (0.05 * w, 1.0 * h, 0.85 * w, 0.48 * h, TERM["purple"], 0.17)):
        t = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
        a = (alpha * np.clip(1.0 - t / 0.65, 0.0, 1.0))[..., None]
        rgb = rgb * (1 - a) + np.array(color, dtype=np.float32) * a
    cv.img = Image.fromarray(np.round(rgb).astype(np.uint8))   # H x W x 3 uint8: RGB
    cv.draw = cv.ImageDraw.Draw(cv.img, "RGBA")
    for x in range(0, W, 40):
        cv.draw.rectangle([px(x), 0, px(x) + SS - 1, h], fill=GRID)
    for y in range(0, H, 40):
        cv.draw.rectangle([0, px(y), w, px(y) + SS - 1], fill=GRID)
    cv.draw.rectangle([0, 0, w, px(4) - 1], fill=TERM["mint"])


def day_note(day: dict) -> str:
    """The right side of a day's header: "76 confirmed", "+ early close", "2 during market hours", "3 time not set"; a
    market holiday: its name."""
    if day.get("market") == "closed":
        return f"Market closed · {day.get('holiday') or 'NYSE holiday'}"
    bits = [f"{day['total']} confirmed"]
    if day.get("market") == "early_close":
        bits.append("early close")
    if day.get("during_market"):
        bits.append(f"{day['during_market']} during market hours")
    if day.get("no_session"):
        bits.append(f"{day['no_session']} time not set")
    return " · ".join(bits)


def range_line(mon: dt.date, fri: dt.date) -> str:
    return f"earnings next week · {fx.week_range_text(mon, fri, ' – ')}"


def render_calendar(item: dict) -> tuple[bytes, dict]:
    """(PNG bytes, QA report) for an earnings_week_calendar item; QAError when the self-QA fails."""
    from PIL import Image
    if item.get("type") != KIND:
        raise QAError(f"not an {KIND} item ({item.get('type')!r})")
    cal = item.get("calendar")
    if not isinstance(cal, list) or len(cal) != 5:
        raise QAError("the item has no 5-day calendar")
    mon, fri = ss.d(item["week_start"]), ss.d(item["week_end"])
    asof = ss.d(item["as_of_date"])
    cv = Canvas()
    background(cv)

    # header: the title, the week (gradient), the subline
    cv.text(MX, 100, TITLE, "archivo", 62, TERM["primary"], "title")
    rng = range_line(mon, fri)
    size = next((s for s in (48, 46, 44, 42, 40) if cv.width(rng, "archivo", s) <= W - 2 * MX), 40)
    mask = Image.new("L", cv.img.size, 0)
    cv.text(MX, 158, rng, "archivo", size, None, "range", mask=mask)
    cv.gradient_fill(mask, TERM["mint"], TERM["cyan"])
    cv.text(MX, 198, SUBLINE, "medium", 24, TERM["secondary"], "subline")

    # column strip
    cv.draw.rectangle([0, px(STRIP_TOP), W * SS, px(STRIP_BOTTOM)], fill=TERM["head"] + (217,))
    cv.draw.rectangle([0, px(STRIP_BOTTOM) - 1, W * SS, px(STRIP_BOTTOM + 1.5)], fill=RULE_HI)
    for i, (_, label, color, _) in enumerate(SESSIONS):
        cv.text(MX + i * (CELL_W + GAP) + CELL_PAD, STRIP_BOTTOM - 14, label, "bold", 30, TERM[color], "column",
                tracking=0.08)

    # day rows: a header line, then the two cells
    for r, day in enumerate(cal):
        top = ROWS_TOP + r * ROW_PITCH
        d = ss.d(day["date"])
        closed = day.get("market") == "closed"
        wd = cv.text(MX, top + 32, day["weekday"].upper(), "archivo", 34, TERM["primary"], "weekday")
        cv.text(wd["box"][2] + 14, top + 31, fx.date_forms(day["date"])[2].upper(), "mono", 26, TERM["muted"], "day_date")
        note = day_note(day)
        cv.text(W - MX - cv.width(note, "medium", 24), top + 31, note, "medium", 24,
                TERM["muted"] if closed else TERM["dim"], "day_note")
        ctop = top + DAY_HEAD
        for c, (session, _, _, tint) in enumerate(SESSIONS):
            x0 = MX + c * (CELL_W + GAP)
            box = (x0, ctop, x0 + CELL_W, ctop + CELL_H)
            data = day.get(session) or {}
            cell = {"id": f"{d.isoformat()}:{session}", "box": [round(v, 2) for v in box], "total": data.get("total"),
                    "shown": list(data.get("shown") or []), "more": data.get("more"), "tiles": 0, "more_drawn": None,
                    "closed": closed}
            cv.cells.append(cell)
            cv.rect(box, 8, fill=CLOSED_TINT if closed else tint, outline=RULE, width=1.5)
            if closed:
                cv.text(x0 + CELL_PAD, ctop + 76, "Market closed", "mono", 24, TERM["dim"], "empty", cell=cell)
                continue
            if not data.get("total"):
                cv.text(x0 + CELL_PAD, ctop + 76, "None confirmed", "mono", 24, TERM["dim"], "empty", cell=cell)
                continue
            shown = cell["shown"]
            if len(shown) > fx.WEEK_CALENDAR_SLOTS or (data.get("more") and len(shown) >= fx.WEEK_CALENDAR_SLOTS):
                raise QAError(f"{cell['id']}: {len(shown)} tiles and +{data.get('more')} do not fit 6 slots")
            for j, t in enumerate(shown):
                sx = x0 + CELL_PAD + (j % 3) * SLOT_W
                base = ctop + (LINE1 if j < 3 else LINE2)
                room = SLOT_W - TILE_GUTTER
                wdth = next((v for v in CONDENSED if cv.width(t, "archivo", TICKER_PX, wdth=v) <= room), CONDENSED[-1])
                cv.text(sx, base, t, "archivo", TICKER_PX, TERM["primary"], "ticker", wdth=wdth, cell=cell,
                        slot=(sx, sx + room))
                cell["tiles"] += 1
            if data.get("more"):
                sx = x0 + CELL_PAD + 2 * SLOT_W
                slot = (sx, sx + SLOT_W)
                rec = cv.text(sx, ctop + LINE2, f"+{data['more']}", "mono", MORE_PX, TERM["secondary"], "more", cell=cell,
                              slot=slot)
                cv.text(rec["box"][2] + 8, ctop + LINE2, "more", "medium", 24, TERM["muted"], "more_label", cell=cell,
                        slot=slot)
                cell["more_drawn"] = rec["text"]

    # footer
    cv.draw.rectangle([0, px(FOOT_RULE), W * SS, px(FOOT_RULE + 1.5)], fill=RULE)
    pill_text = "RapidTradeView"
    pw = cv.width(pill_text, "bold", 24) + 36
    pill = (MX, 1236, MX + pw, 1282)
    pmask = Image.new("L", cv.img.size, 0)
    cv.ImageDraw.Draw(pmask).rounded_rectangle([px(v) for v in pill], radius=px(23), fill=255)
    cv.gradient_fill(pmask, TERM["purple"], TERM["blue"], tuple(px(v) for v in pill))
    cv.draw.rounded_rectangle([px(v) for v in pill], radius=px(23), outline=(206, 192, 255, 115), width=SS)
    cv.text(MX + 18, 1267, pill_text, "bold", 24, TERM["primary"], "brand")
    cv.text(pill[2] + 16, 1267, "rapidtradeview.trade/earnings", "medium", 24, TERM["secondary"], "url")
    asof_text = f"Confirmed dates as of {fx.date_forms(asof.isoformat())[2]}"
    right = W - MX
    cv.text(right - cv.width(asof_text, "medium", 24), 1254, asof_text, "medium", 24, TERM["muted"], "asof")
    cv.text(right - cv.width(fx.DISCLAIMER, "medium", 24), 1286, fx.DISCLAIMER, "medium", 24, TERM["muted"],
            "disclaimer")

    out = cv.img.reduce(SS)   # 2x2 box average: the supersample, no ringing (half the PNG size of LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    png = buf.getvalue()
    report = qa(item, cv, len(png))
    if report["failures"]:
        raise QAError("; ".join(report["failures"][:6]))
    return png, report


def allowed_digits(item: dict) -> set[str]:
    """Digit runs the image may draw: the days of the month, the years, the as-of day, the day / cell counts."""
    out = {str(ss.d(item[k]).day) for k in ("week_start", "week_end", "as_of_date")}
    out |= {str(ss.d(item[k]).year) for k in ("week_start", "week_end", "as_of_date")}
    for day in item.get("calendar") or []:
        out |= {str(ss.d(day["date"]).day), str(day.get("total")), str(day.get("no_session")),
                str(day.get("during_market"))}
        for s in ("bmo", "amc"):
            c = day.get(s) or {}
            out |= {str(c.get("total")), str(c.get("more"))}
    return out


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def qa(item: dict, cv: Canvas, size: int) -> dict:
    fails: list[str] = []
    for t in cv.texts:
        x0, y0, x1, y1 = t["box"]
        if x0 < SAFE or y0 < SAFE or x1 > W - SAFE or y1 > H - SAFE:
            fails.append(f"{t['role']} {t['text']!r} leaves the {SAFE} px safe area ({t['box']})")
        floor = FLOOR.get(t["role"], TEXT_FLOOR)
        if t["size"] < floor:
            fails.append(f"{t['role']} {t['text']!r} at {t['size']} px is below the {floor} px floor")
        if t["slot"] and (x0 < t["slot"][0] - 0.5 or x1 > t["slot"][1] + 0.5):
            fails.append(f"{t['role']} {t['text']!r} leaves its tile ({t['box']} vs slot {t['slot']})")
        if "…" in t["text"] or t["text"].endswith("..."):
            fails.append(f"{t['role']} {t['text']!r} is cut")
        if CONJUNCTION_END.search(t["text"].strip()):
            fails.append(f"{t['role']} {t['text']!r} ends in a conjunction (a cut name)")
    for c in cv.cells:
        x0, y0, x1, y1 = c["box"]
        if x0 < SAFE or y0 < SAFE or x1 > W - SAFE or y1 > H - SAFE:
            fails.append(f"cell {c['id']} leaves the safe area")
        if c["closed"]:
            if c["tiles"] or c["more_drawn"] or c["total"]:
                fails.append(f"cell {c['id']}: a market holiday shows reporters")
            continue
        if c["total"] != len(c["shown"]) + (c["more"] or 0):
            fails.append(f"cell {c['id']}: {len(c['shown'])} shown + {c['more']} more != {c['total']} total")
        if c["tiles"] != len(c["shown"]):
            fails.append(f"cell {c['id']}: {c['tiles']} tiles drawn for {len(c['shown'])} shown")
        if (c["more_drawn"] or None) != (f"+{c['more']}" if c["more"] else None):
            fails.append(f"cell {c['id']}: drew {c['more_drawn']!r} for {c['more']} more")
        for t in cv.texts:
            if t["cell"] == c["id"]:
                b = t["box"]
                if b[0] < x0 or b[1] < y0 or b[2] > x1 or b[3] > y1:
                    fails.append(f"{t['role']} {t['text']!r} leaves cell {c['id']}")
    for i, a in enumerate(cv.texts):
        for b in cv.texts[i + 1:]:
            if _overlap(a["box"], b["box"]):
                fails.append(f"{a['role']} {a['text']!r} overlaps {b['role']} {b['text']!r}")
    ok_digits = allowed_digits(item)
    for t in cv.texts:
        bad = [r for r in re.findall(r"\d+", t["text"]) if r not in ok_digits]
        if bad:
            fails.append(f"{t['role']} {t['text']!r} draws {', '.join(bad)}, not from the item")
    if size > MAX_BYTES:
        fails.append(f"the PNG is {size} bytes (max {MAX_BYTES})")
    return {"pass": not fails, "failures": fails, "bytes": size, "size": [W, H], "texts": cv.texts,
            "tiles": sum(c["tiles"] for c in cv.cells), "cells": cv.cells,
            "condensed": [t["text"] for t in cv.texts if t["role"] == "ticker" and t["wdth"] != 100]}


def alt_text(item: dict) -> str:
    """Per day and session, the shown tickers (whole entries only, at most ALT_MAX characters)."""
    mon, fri = ss.d(item["week_start"]), ss.d(item["week_end"])
    out = (f"Largest companies reporting earnings next week, {fx.week_range_text(mon, fri)}, by market cap in each "
           "session; confirmed dates in our coverage.")
    for day in item.get("calendar") or []:
        head = f"{day['weekday']} {fx.date_forms(day['date'])[2]}"
        if day.get("market") == "closed":
            entries = [f" {head}: market closed ({day.get('holiday') or 'NYSE holiday'})."]
        else:
            entries = []
            for s, label in (("bmo", "before the open"), ("amc", "after the close")):
                c = day.get(s) or {}
                what = (", ".join(c.get("shown") or []) + (f" and {c['more']} more" if c.get("more") else "")
                        if c.get("total") else "none confirmed")
                entries.append(f" {head}{' (early close)' if day.get('market') == 'early_close' and s == 'bmo' else ''}, "
                               f"{label}: {what}.")
        for entry in entries:
            if len(out) + len(entry) > ALT_MAX:
                return out
            out += entry
    return out


def write_render(item: dict, out_dir: Path) -> tuple[Path, dict]:
    png, report = render_calendar(item)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / PNG
    path.write_bytes(png)
    return path, report


# ---------------------------------------------------------------------------------------------------------------- the runner
def now_utc(raw: str | None) -> dt.datetime:
    if not raw:
        return dt.datetime.now(dt.timezone.utc)
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw.strip()).replace("Z", "+00:00")
    t = dt.datetime.fromisoformat(raw)
    return (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_state(work: Path, date: str) -> dict:
    p = work / STATE
    if p.is_file():
        s = load(p)
        if s.get("date") == date:
            return s
    return {"schema": "rtv-week-calendar-state/1", "date": date, "status": "new", "attempts": 0, "log": []}


def save_state(work: Path, state: dict) -> None:
    mf.write_json(work / STATE, state)


def note(state: dict, msg: str, now: dt.datetime) -> None:
    state.setdefault("log", []).append(f"{now:%Y-%m-%dT%H:%M:%SZ} {msg}")
    print(f"week calendar: {msg}", flush=True)


def png_url(date: str, item_id: str) -> str:
    return f"{mf.PAGES_BASE}/v/{date}/cards/{item_id}/{PNG}"


def set_item(facts: dict, item: dict | None, why: str | None = None) -> None:
    """Put `item` in place of any item of this kind (or take them out, with `why` as the reason); counts, reasons and the
    rank order follow."""
    items = [i for i in facts.get("items") or [] if not (isinstance(i, dict) and i.get("type") == KIND)]
    if item is not None:
        items.append(item)
        items.sort(key=lambda i: -(i.get("rank") or 0) if isinstance(i, dict) else 0)
    facts["items"] = items
    facts.setdefault("counts", {})[KIND] = 1 if item is not None else 0
    reasons = facts.setdefault("reasons", {})
    if item is not None:
        reasons.pop(KIND, None)
    elif why:
        reasons[KIND] = why


def write_facts(path: Path, facts: dict) -> None:
    mf.write_json(path, facts)


def with_media(state: dict) -> dict:
    return dict(state["item"], media=[{"url": state["url"], "kind": "image", "alt": state["alt"]}])


def attach(facts_file: Path, state: dict) -> str:
    facts = load(facts_file)
    set_item(facts, with_media(state))
    write_facts(facts_file, facts)
    return f"{state['item_id']} is in the facts with {state['url']}"


def strip(facts_file: Path, why: str, only_if_present: bool = False) -> bool:
    """Take the item out of the facts file with `why` as its reason (True when there was one). only_if_present: a file
    without the item is left untouched (the crash guard)."""
    facts = load(facts_file)
    had = any(isinstance(i, dict) and i.get("type") == KIND for i in facts.get("items") or [])
    if had or (not only_if_present and (facts.get("reasons") or {}).get(KIND) != why):
        set_item(facts, None, why)
        write_facts(facts_file, facts)
    return had


def is_friday(date: str) -> bool:
    return dt.date.fromisoformat(date).weekday() == fx.WEEK_CALENDAR_FRIDAY


def stage(state: dict, a: argparse.Namespace, now: dt.datetime) -> bool:
    """Render the frozen item into the repo (v/<date>/cards/<item_id>/calendar_4x5.png). True when staged."""
    item = state["item"]
    iid = item["item_id"]
    state["attempts"] = state.get("attempts", 0) + 1
    state["status"] = "rendering"
    save_state(Path(a.work), state)
    try:
        png, report = render_calendar(item)
    except QAError as e:
        note(state, f"FAILED {iid}: QA: {e}", now)
        return False
    except Exception as e:  # noqa: BLE001 - a render crash is a failed attempt, never a published item without image
        note(state, f"FAILED {iid}: render crashed ({type(e).__name__}: {str(e)[:200]})", now)
        return False
    rel = f"v/{a.date}/cards/{iid}"
    dest = Path(a.repo) / rel
    dest.mkdir(parents=True, exist_ok=True)
    (dest / PNG).write_bytes(png)
    mf.write_json(Path(a.work) / "week-calendar" / iid / QA_FILE, report)
    state.update(status="staged", url=png_url(a.date, iid), alt=alt_text(item), files=[f"{rel}/{PNG}"], bytes=len(png),
                 sha256=hashlib.sha256(png).hexdigest())
    note(state, f"staged {rel}/{PNG} ({len(png)} bytes, QA passed)", now)
    return True


def failed_reason(state: dict) -> str:
    last = (state.get("log") or ["?"])[-1]
    last = re.sub(r"^\S+ FAILED \S+: ", "", last)
    return f"calendar image failed: {last}"


def cmd_prepare(a: argparse.Namespace) -> int:
    now = now_utc(a.now)
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    (work / FILES).unlink(missing_ok=True)
    facts_file = Path(a.facts)
    if not is_friday(a.date):
        print(f"week calendar: {a.date} is not a Friday: nothing to do")
        return 0
    facts = load(facts_file)
    state = read_state(work, a.date)
    if not state.get("item"):
        item = next((i for i in facts.get("items") or [] if isinstance(i, dict) and i.get("type") == KIND), None)
        if item is None:
            print(f"week calendar: no {KIND} item in this build ({(facts.get('reasons') or {}).get(KIND, 'no reason')})")
            return 0
        ny = now.astimezone(ss.NY)
        if ny.date().isoformat() == a.date and ny.hour < FREEZE_FROM_ET:
            strip(facts_file, f"the calendar freezes at the first build at or after {FREEZE_FROM_ET:02d}:00 ET (the API's "
                              f"date check may be half done before; this build ran {ny:%H:%M} ET)")
            print(f"week calendar: {ny:%H:%M} ET is before {FREEZE_FROM_ET:02d}:00 ET: nothing frozen, the item stays out")
            return 0
        if ss.g_n1_holdout(dt.date.fromisoformat(a.date)) and ss.report_page_in(item):
            strip(facts_file, f"calendar image failed: the item carries a report page URL ({ss.G_N1_REASON})")
            return 0
        state.update(item=dict(item, media=[]), item_id=item["item_id"], frozen_at=f"{now:%Y-%m-%dT%H:%M:%SZ}")
        note(state, f"froze {item['item_id']} (week of {item.get('week_start')}, {len(item.get('tickers') or [])} cashtags)",
             now)
        save_state(work, state)
    st = state.get("status")
    if st == "live" or (st == "staged" and a.no_push):
        print(f"week calendar: {attach(facts_file, state)}" + (" (-NoPush: not on Pages)" if st == "staged" else ""))
        return 0
    if st == "staged":
        missing = [f for f in state.get("files") or [] if not (Path(a.repo) / f).is_file()]
        if not missing:
            strip(facts_file, "the calendar image is staged, not yet live on Pages (the item comes back with it)")
            (work / FILES).write_text("\n".join(state["files"]) + "\n", encoding="utf-8")
            print(f"week calendar: {state['item_id']} is staged, not yet served by Pages: push + check again")
            return EXIT_STAGED
        note(state, f"FAILED {state['item_id']}: staged files are gone ({', '.join(missing)})", now)
        state["status"] = "failed"
        save_state(work, state)
    if state.get("attempts", 0) >= MAX_ATTEMPTS:
        strip(facts_file, failed_reason(state))
        print(f"week calendar: no item today: {state['item_id']} failed {state['attempts']} times")
        return 0
    if not stage(state, a, now):
        state["status"] = "failed"
        save_state(work, state)
        left = MAX_ATTEMPTS - state["attempts"]
        strip(facts_file, failed_reason(state) + (" (one more try on the next build)" if left > 0 else ""))
        return 0
    save_state(work, state)
    if a.no_push:
        print(f"week calendar: {attach(facts_file, state)} (-NoPush: not on Pages)")
        return 0
    strip(facts_file, "the calendar image is staged, not yet live on Pages (the item comes back with it)")
    (work / FILES).write_text("\n".join(state["files"]) + "\n", encoding="utf-8")
    return EXIT_STAGED


def cmd_live(a: argparse.Namespace) -> int:
    now = now_utc(None)
    work = Path(a.work)
    state = read_state(work, a.date)
    if state.get("status") != "staged":
        print(f"week calendar: nothing staged (status {state.get('status')})")
        return 1
    local = Path(a.repo) / state["files"][0]
    deadline = time.monotonic() + a.timeout
    while True:
        errors = mf.check_media_urls({state["url"]: local})
        if not errors:
            break
        if time.monotonic() > deadline:
            print(f"week calendar: not served within {a.timeout} s: {errors[0]}")
            return 1
        time.sleep(15)
    state["status"] = "live"
    note(state, f"live on Pages: {state['url']}", now)
    save_state(work, state)
    print(f"week calendar: {attach(Path(a.facts), state)}")
    return 0


def cmd_render(a: argparse.Namespace) -> int:
    data = load(Path(a.item))
    item = data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        item = next((i for i in data["items"] if isinstance(i, dict) and i.get("type") == KIND), None)
        if item is None:
            print(f"week calendar: {a.item} has no {KIND} item ({(data.get('reasons') or {}).get(KIND, 'no reason')})")
            return 1
    try:
        path, report = write_render(item, Path(a.out))
    except QAError as e:
        print(f"week calendar: QA FAILED: {e}")
        return 1
    mf.write_json(Path(a.out) / QA_FILE, report)
    print(f"week calendar: {path} ({report['bytes']} bytes, {report['tiles']} tiles, "
          f"condensed {report['condensed'] or 'none'}; QA passed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--item", required=True)
    r.add_argument("--out", required=True)
    for name in ("prepare", "live"):
        p = sub.add_parser(name)
        p.add_argument("--date", required=True)
        p.add_argument("--facts", required=True)
        p.add_argument("--work", required=True)
        p.add_argument("--repo", default=str(mf.REPO))
    sub.choices["prepare"].add_argument("--now", help="the clock (ISO; run_daily.ps1 -Now for a dry run)")
    sub.choices["prepare"].add_argument("--no-push", action="store_true")
    sub.choices["live"].add_argument("--timeout", type=int, default=600)
    s = sub.add_parser("strip")
    s.add_argument("--date", required=True)
    s.add_argument("--facts", required=True)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.cmd == "render":
        return cmd_render(a)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
        ap.error("--date must be YYYY-MM-DD")
    if a.cmd == "strip":
        had = strip(Path(a.facts), "calendar image failed: the renderer did not finish (no item without its image)", True)
        print(f"week calendar: {'took the item out of' if had else 'no item in'} {a.facts}")
        return 0
    if a.cmd == "live":
        return cmd_live(a)
    try:
        return cmd_prepare(a)
    except Exception as e:  # noqa: BLE001 - whatever broke, the item never goes out without its image
        print(f"week calendar: prepare crashed ({type(e).__name__}: {str(e)[:200]}); taking the item out")
        try:
            strip(Path(a.facts), f"calendar image failed: the runner crashed ({type(e).__name__})", True)
        except Exception as e2:  # noqa: BLE001
            print(f"week calendar: could not take the item out ({type(e2).__name__})")
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
