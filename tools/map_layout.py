"""Which tiles the Market map share card labels (HQ 2026-10-19, card consistency: a mega_mover item may carry the pinned
map card only when its ticker is drawn on that card with its ticker AND its percent move).

A port of the frontend's geometry, the same arithmetic in the same order (IEEE doubles in both languages):
  - frontend/src/components/market/MarketCard.tsx cardChartHeight + cardChart (key "map": the layout options) and
    CARD_SIZE / CARD_CHART_W;
  - frontend/src/lib/market/panels.ts mapPanel (title, sub and foot: only their lengths matter), mapGaps, legendHeight,
    aboutUsd, leadSectorWords;
  - frontend/src/lib/market/treemap.ts squarify, layoutMarketMap (sector headers with headNeedsValue) and tileLabel (the
    ticker size and the move line; logos and dollar lines never take the move line away: keepsSub);
  - frontend/src/lib/market/format.ts usd, pct, sign, headlineSector, weekday / weekdayLong.
A tile is "labelled" when its ticker font is at least minFont and its move line (the percent) is shown. Any change to
those frontend files must be mirrored here (tests/test_map_layout.py pins the 2026-10-16 card).
"""
from __future__ import annotations

import datetime as dt
import math
from decimal import ROUND_HALF_UP, Decimal

MINUS = "−"
CARD_W, CARD_H = 1080, 1350
PAD_X = 64
CARD_CHART_W = CARD_W - 2 * PAD_X
OLD_CLOSE_LEGEND = "hatched = last stored close (date shown), not in the day's totals"
MAP_FULL_COVERAGE = 0.9
# MarketCard.cardChart, case "map"
CARD_MAP_OPTS = {"header": 26, "headFont": 15, "maxFont": 64, "minFont": 13, "minSub": 11, "sectorGap": 3,
                 "logoMinFont": 34, "maxLogo": 50, "headNeedsValue": True, "tileGap": 1}
SHORT = {"Communication Services": "Communication", "Consumer Cyclical": "Cons. Cyclical",
         "Consumer Defensive": "Cons. Defensive", "Financial Services": "Financials", "Basic Materials": "Materials",
         "No sector on file": "No sector"}
TREE_SHORT = {"Communication Services": "Communication", "Consumer Cyclical": "Cons. Cyclical",
              "Consumer Defensive": "Cons. Defensive", "Financial Services": "Financials", "Basic Materials": "Materials"}
NO_SECTOR_LABEL = "No sector"


def to_fixed(x: float, n: int) -> str:
    """JavaScript Number.prototype.toFixed (the exact binary value, ties away from zero)."""
    return str(Decimal(x).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def sign(v: float) -> str:
    return "+" if v > 0 else MINUS if v < 0 else ""


def pct(p: float | None, dp: int = 2) -> str:
    if p is None:
        return "no price"
    return sign(float(to_fixed(p, dp))) + to_fixed(abs(p), dp) + "%"


def usd(v: float | None, dp: int | None = None) -> str:
    if v is None:
        return "no price"
    a = abs(v)
    s = sign(v)
    if a >= 1e12:
        return f"{s}${to_fixed(a / 1e12, 2 if dp is None else dp)}T"
    if a >= 1e9:
        return f"{s}${to_fixed(a / 1e9, (0 if a >= 1e11 else 1) if dp is None else dp)}B"
    return f"{s}${to_fixed(a / 1e6, 0 if dp is None else dp)}M"


def about_usd(a: float) -> str:
    v = abs(a)
    return f"${to_fixed(v / 1e12, 1)}T" if v >= 5e11 else usd(v, 0).lstrip("+" + MINUS)


def headline_sector(s: str | None) -> str:
    if s == "Technology":
        return "Tech"
    return NO_SECTOR_LABEL if s is None else SHORT.get(s, s)


def _day(iso: str) -> dt.date:
    return dt.date.fromisoformat(iso[:10])


def weekday(iso: str) -> str:
    return _day(iso).strftime("%a")


def weekday_long(iso: str) -> str:
    return _day(iso).strftime("%A")


def map_gaps(d: dict) -> dict:
    last, none = 0, 0
    for t in d.get("map") or []:
        if t.get("pct_change") is not None:
            continue
        if t.get("price") is not None:
            last += 1
        else:
            none += 1
    return {"lastClose": last, "noClose": none}


def legend_height(g: dict) -> int:
    return 54 if g["lastClose"] else 46


def _lead_sector(d: dict) -> dict | None:
    total = (d.get("totals") or {}).get("usd_change_sum")
    if total is None or total == 0:
        return None
    best = None
    for s in d.get("sectors") or []:
        u = ((s.get("change") or {}).get("1d") or {}).get("usd_change")
        if u is None or math.copysign(1, u) != math.copysign(1, total) or u == 0:
            continue
        if best is None or abs(u) > abs(best["usd"]):
            best = {"sector": s.get("sector"), "usd": u}
    return best


def _lead_words(d: dict, signed: bool) -> str:
    lead = _lead_sector(d)
    total = (d.get("totals") or {}).get("usd_change_sum")
    if not lead or total is None:
        return ""
    plain = usd(abs(lead["usd"])).lstrip("+" + MINUS)
    amt = ((MINUS if lead["usd"] < 0 else "+") if signed else "") + plain
    if abs(lead["usd"]) < abs(total):
        return f"{headline_sector(lead['sector'])} was {amt} of it"
    return f"{headline_sector(lead['sector'])} alone {'lost' if lead['usd'] < 0 else 'gained'} {plain}"


def map_headline(d: dict) -> dict | None:
    """panels.mapPanel's headline (title as one string, sub, foot), or None when the card is an error (no card)."""
    t = d.get("totals") or {}
    if not d.get("map") or t.get("usd_change_sum") is None or not t.get("priced_count"):
        return None
    total = t["usd_change_sum"]
    a = abs(total)
    gained = total >= 0
    verb = "gained" if gained else "lost"
    about = about_usd(a)
    exact = (usd(a) if a >= 1e12 else usd(a, 0)).lstrip("+" + MINUS)
    session = d["session_date"]
    wd = weekday(session)
    share = "" if t.get("priced_cap_share") is None else f", {to_fixed(t['priced_cap_share'] * 100, 1)}% of market value"
    count, priced = t.get("ticker_count"), t.get("priced_count")
    every = priced >= count
    partial = not every and (t.get("priced_cap_share") is None or t["priced_cap_share"] < MAP_FULL_COVERAGE)
    lead = _lead_words(d, True)
    sub = (f"{'The ' + str(count) if every else str(priced) + ' of the ' + str(count)} largest US-listed stocks, "
           f"{weekday_long(session)}'s close." + (f" {lead}." if lead else ""))
    gaps = map_gaps(d)
    foot = [f"{count} of {count} priced for {wd}: {exact} in market value ({pct(t.get('pct_change'))})" if every else
            f"{priced} of {count} priced for {wd}{share}, {verb} {exact} ({pct(t.get('pct_change'))}); the other "
            f"{count - priced} are not counted"]
    if gaps["lastClose"]:
        foot.append(f"{OLD_CLOSE_LEGEND} ({gaps['lastClose']})")
    if gaps["noClose"]:
        foot.append(f"black = no close stored ({gaps['noClose']})")
    title = f"About {about} {verb}" + (f", {priced} of {count} priced" if partial else "")
    return {"title": title, "sub": sub, "foot": "; ".join(foot) + ". Tile size = market value."}


def card_chart_height(h: dict, extra: int) -> int:
    def lines(text: str, per: int) -> int:
        return max(1, math.ceil(len(text) / per))

    def wrap_lines(text: str, per: int) -> int:
        n, used = 1, 0
        for w in [x for x in text.split() if x]:
            if used and used + 1 + len(w) > per:
                n += 1
                used = len(w)
            else:
                used += (1 if used else 0) + len(w)
        return n
    title_lines = wrap_lines(h["title"], 23)
    sub_lines = lines(h["sub"], 70)
    foot_lines = lines(f"{h['foot']} Not investment advice.", 78)
    fixed = 56 + 44 + 44 + 24 + 12 + 16 + 34 + 26 + 21 + 48
    return math.floor(CARD_H - fixed - title_lines * 78 - sub_lines * 35 - foot_lines * 24 - extra - 8)


def squarify(items: list[dict], x: float, y: float, w: float, h: float) -> list[dict]:
    """treemap.ts squarify: each item {value, ...} with x, y, w, h; largest first (stable for ties)."""
    nodes = sorted([d for d in items if d["value"] > 0], key=lambda d: -d["value"])
    total = 0
    for d in nodes:
        total += d["value"]
    out: list[dict] = []
    if not total or w <= 0 or h <= 0:
        return out
    k = (w * h) / total
    i, x0, y0, x1, y1 = 0, x, y, x + w, y + h
    while i < len(nodes):
        cw, ch = x1 - x0, y1 - y0
        side = min(cw, ch)
        row: list[tuple[dict, float]] = []
        s_sum, min_a, max_a, best = 0, math.inf, 0, math.inf
        j = i
        while j < len(nodes):
            a = nodes[j]["value"] * k
            s = s_sum + a
            mn, mx = min(min_a, a), max(max_a, a)
            worst = max((side * side * mx) / (s * s), (s * s) / (side * side * mn))
            if row and worst > best:
                break
            row.append((nodes[j], a))
            s_sum, min_a, max_a, best = s, mn, mx, worst
            j += 1
        i = j
        last = i >= len(nodes)
        if cw >= ch:
            t = cw if last else s_sum / ch
            yy = y0
            for idx, (it, a) in enumerate(row):
                hh = y1 - yy if idx == len(row) - 1 else a / t
                out.append({"item": it, "x": x0, "y": yy, "w": t, "h": hh})
                yy += hh
            x0 += t
        else:
            t = ch if last else s_sum / cw
            xx = x0
            for idx, (it, a) in enumerate(row):
                ww = x1 - xx if idx == len(row) - 1 else a / t
                out.append({"item": it, "x": xx, "y": y0, "w": ww, "h": t})
                xx += ww
            y0 += t
    return out


def _label(symbol: str, w: float, h: float, has_pct: bool, o: dict) -> tuple[float, float]:
    """(ticker font, move-line font) of a tile with a session move (treemap.ts tileLabel's base layout; 0 = none)."""
    fs0 = min((w * 0.86) / (max(len(symbol), 3) * 0.62), h * 0.36, o["maxFont"])
    if fs0 < o["minFont"]:
        return 0.0, 0.0
    if not has_pct:   # a tile without a move has no percent to show: never "labelled" for a move claim
        return fs0, 0.0
    fs2 = max(min(fs0 * 0.58, 22), 0)
    show = h > fs0 * 1.15 + fs2 * 1.3 and fs2 >= o["minSub"]
    return fs0, (fs2 if show else 0.0)


def layout_map(d: dict, W: float, H: float, o: dict = CARD_MAP_OPTS) -> list[dict]:
    """treemap.ts layoutMarketMap: every tile {symbol, x, y, w, h, fs, fs2}."""
    groups: dict[str, dict] = {}
    for t in d.get("map") or []:
        key = t.get("sector") or ""
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"sector": t.get("sector"), "value": 0, "items": []}
        value = t.get("market_cap") or 0
        if value <= 0:
            continue
        g["items"].append({**t, "value": value})
        g["value"] += value
    api = {(s.get("sector") or ""): s for s in d.get("sectors") or []}
    sg, hb = o["sectorGap"], o["header"]
    tiles = []
    for sr in squarify(list(groups.values()), 0, 0, W, H):
        g = sr["item"]
        sw, sh = sr["w"] - sg, sr["h"] - sg
        head = False
        if sr["w"] > 60 and sr["h"] > hb * 3:
            row = api.get(g["sector"] or "")
            c1 = ((row or {}).get("change") or {}).get("1d") or {}
            chg, p = c1.get("usd_change"), c1.get("pct_change")
            full = (g["sector"] or NO_SECTOR_LABEL).upper()
            sh2 = (TREE_SHORT.get(g["sector"], g["sector"]) if g["sector"] else NO_SECTOR_LABEL).upper()
            m = "" if chg is None else usd(chg)
            v1 = "" if chg is None else (f"{m} {pct(p)}" if m else pct(p))
            v2 = "" if chg is None else (m or pct(p))
            cw = o["headFont"] * 0.66
            avail = sw - 12

            def fits(n: str, v: str) -> bool:
                return (len(n) + (len(v) + 2 if v else 0)) * cw <= avail
            if o.get("headNeedsValue"):
                head = chg is not None and any(fits(n, v) for n, v in ((full, v1), (sh2, v1), (full, v2), (sh2, v2)))
            else:
                head = True
        top = hb if head else 0
        iw, ih = sw + 1, sh - top + 1
        for r in squarify(g["items"], 0, 0, iw, ih):
            w, h = r["w"] - o["tileGap"], r["h"] - o["tileGap"]
            if w <= 0 or h <= 0:
                continue
            it = r["item"]
            fs, fs2 = _label(str(it.get("symbol") or ""), w, h, it.get("pct_change") is not None, o)
            tiles.append({"symbol": it.get("symbol"), "x": sr["x"] + r["x"], "y": sr["y"] + top + r["y"], "w": w, "h": h,
                          "fs": fs, "fs2": fs2})
    return tiles


def card_map_tiles(d: dict) -> list[dict] | None:
    """The map share card's tiles for a /market/pictures response, or None when the card would be an error."""
    h = map_headline(d)
    if h is None:
        return None
    H = card_chart_height(h, legend_height(map_gaps(d)))
    return layout_map(d, CARD_CHART_W, H)


def labelled(d: dict, symbol: str) -> bool | None:
    """True when the map card draws `symbol` (API form, e.g. BRK-B) with its ticker and its move line; None when the
    card would not render."""
    tiles = card_map_tiles(d)
    if tiles is None:
        return None
    t = next((x for x in tiles if x["symbol"] == symbol), None)
    return bool(t and t["fs"] > 0 and t["fs2"] > 0)
