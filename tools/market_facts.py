"""Market pillars for the Grok facts feed (HQ 2026-10-18; D:/rtv-ops/tracks/hq/social-content-2026-10-18/PLAN.md §1-§2).

The owner (10-18): "I keep seeing the same boring niche posts." facts.json offered only single filings and single
companies, so every post was one. This module adds items about the whole market and the names everyone knows, built from
two GETs per facts pass on our own public API (both serve stored closes and stored filings; no Yahoo call):
  GET /market/pictures  the 500 largest US-listed companies (one tile per company): session totals, sectors 1d/5d/21d,
                        breadth (all ~2,500 tracked stocks, 20 closes), top gainers / losers
  GET /market/flows     Congress (30 days), insider buying and selling (30 days), Reddit buzz vs the usual count

Item types (pillar, the share card a post carries, the trigger: the item is emitted only when it fires):
  market_move      P1  map       |cap-weighted 1d move| >= MOVE_TRIGGER and priced cap share >= MIN_CAP_SHARE
  mega_mover       P2  map       the largest |$ move| >= MEGA_USD, or a top-100 name |1d| >= MEGA_PCT (top 20: MEGA_PCT_TOP20)
  sector_rotation  P6  sectors   day: best-worst 1d >= ROT_DAY_PP with a sector >= +1% and one <= -1%;
                                 week (session is a Friday): best-worst 5d >= ROT_WEEK_PP
  breadth_day      P7  breadth   advancers:decliners >= BREADTH_RATIO either way, or a divergence (|cap-weighted move| >=
                                 DIVERGENCE_MOVE while the median company is the other sign or within FLAT_MEDIAN)
  basket_week      P7  map       session is a Friday and the 10 largest, equal-weighted over 5 sessions, moved >= BASKET_MIN
  congress_flow    P3a congress  weekly (Saturday and Monday facts) or a 500-largest name new in the top 5
  insider_flow     P3b insiders  same; leaders are named only from within the 500 largest
  reddit_buzz      P4  buzz      the card's mostUnusual floors (mentions >= 20, usual >= 5, ratio >= 1.5); it leads only at
                                 >= BUZZ_HOT (3x), or >= BUZZ_TOP20_HOT (2x) for a top-20-by-cap name
  earnings_week_preview P5 /earnings card   Sunday / Monday facts: the week's confirmed reporters among the 500 largest,
                                 >= PREVIEW_MIN_N of them worth >= $10B
  earnings_reaction     P5 ticker card      a >= $10B 500-largest reporter whose report session is the map's session and
                                 whose 1d move is >= REACTION_MIN_MOVE (calendar of the current week only: the API serves no
                                 past week)

No Fallbacks: a source that fails or a coverage gate that fails emits no item; the reason goes in reasons / left_out.
Every number is computed here from the API's own fields with the formula next to it (unit tests: tests/test_market_facts.py
on the real 2026-10-16 session, fixture tests/fixtures/market-2026-10-16.json). This module returns plain specs; facts.py
turns them into items (item_id, page_url with UTM, rank) and the runner pins their cards (tools/pin_cards.py).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import statistics
from decimal import ROUND_HALF_UP, Decimal

PICTURES = "/market/pictures"
FLOWS = "/market/flows"
MINUS = "\u2212"
TIMES = "\u00d7"

MIN_CAP_SHARE = 0.95       # P1 coverage gate (the card names its coverage below 0.90; facts uses the stricter one)
MOVE_TRIGGER = 0.75        # P1: |cap-weighted 1d %| (the approved heatmap test, idea #1)
MEGA_USD = 50e9            # P2
MEGA_PCT = 4.0
MEGA_PCT_TOP20 = 3.0
MEGA_TOP = 100
ROT_DAY_PP = 3.0           # P6
ROT_WEEK_PP = 4.0
ROT_MOVE_MIN = 1.0         # panels.ts MOVE_MIN
BREADTH_RATIO = 2.0        # P7
DIVERGENCE_MOVE = 0.5
FLAT_MEDIAN = 0.1
BASKET_N = 10
BASKET_MIN = 2.0
BUZZ_MIN_MENTIONS = 20     # panels.ts BUZZ_MIN_MENTIONS / BUZZ_MIN_AVG / BUZZ_MIN_RATIO / BUZZ_HOT_RATIO
BUZZ_MIN_AVG = 5
BUZZ_MIN_RATIO = 1.5
BUZZ_HOT = 3.0
BUZZ_TOP20_HOT = 2.0
BUZZ_ROWS = 10             # BuzzCardList.tsx BUZZ_CARD_ROWS: the card's headline comes from its top 10 rows
PREVIEW_MIN_CAP = 10e9     # P5
PREVIEW_MIN_N = 3
PREVIEW_SHOW = 6
REACTION_MIN_CAP = 10e9
REACTION_MIN_MOVE = 3.0
FLOW_TOP = 5               # P3: "a 500-largest name enters the top 5"
FLOW_WEEKLY_DAYS = (5, 0)  # Saturday, Monday (date.weekday())

# Cap tiers (recognisability): mega >= $200B, large >= $10B, mid >= $2B, small >= $300M, micro below.
TIERS = ((200e9, "mega"), (10e9, "large"), (2e9, "mid"), (300e6, "small"))

# Share cards (frontend /market/card/<panel>, 1080x1350) and the home page's section anchors.
CARD_PANELS = ("map", "breadth", "sectors", "congress", "insiders", "buzz")
PANEL_OF = {"market_move": "map", "mega_mover": "map", "basket_week": "map", "sector_rotation": "sectors",
            "breadth_day": "breadth", "congress_flow": "congress", "insider_flow": "insiders", "reddit_buzz": "buzz"}
PILLAR_OF = {"market_move": "P1", "mega_mover": "P2", "congress_flow": "P3", "insider_flow": "P3", "reddit_buzz": "P4",
             "earnings_week_preview": "P5", "earnings_reaction": "P5", "sector_rotation": "P6", "breadth_day": "P7",
             "basket_week": "P7"}
MARKET_TYPES = tuple(PILLAR_OF)
# Types about the whole market (P1/P2/P6/P7): the market-wording guard applies (grok_review.py).
WORDING_TYPES = ("market_move", "mega_mover", "sector_rotation", "breadth_day", "basket_week")
# Wording a market post never uses (the item's banned_words; the validator rejects them).
MARKET_BANNED = ["crash", "crashed", "crashing", "bloodbath", "dump", "dumps", "dumped", "dumping", "s&p 500", "s&p",
                 "the index", "plunge", "plunged", "plunging"]
UNIVERSE_WORDS = "the 500 largest US-listed stocks"

SECTOR_SHORT = {"Technology": "Tech", "Consumer Defensive": "Consumer Defensive", "Consumer Cyclical": "Consumer Cyclical",
                "Communication Services": "Communication Services", "Financial Services": "Financials",
                "Basic Materials": "Materials", "Real Estate": "Real Estate", "Healthcare": "Healthcare",
                "Industrials": "Industrials", "Utilities": "Utilities", "Energy": "Energy"}


# ---------------------------------------------------------------------------
# Numbers

def js_fixed(x: float, n: int) -> str:
    """JavaScript toFixed: the exact binary value, ties away from zero (same as facts.js_fixed)."""
    return str(Decimal(x).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def signed_pct(x: float, n: int = 2) -> str:
    """-1.2083 -> "−1.21%", 2.64 -> "+2.64%" (a move rounding to zero reads "0.00%")."""
    s = js_fixed(abs(x), n)
    if float(s) == 0:
        return f"{s}%"
    return f"{MINUS if x < 0 else '+'}{s}%"


def pct_forms(x: float, ns=(2, 1)) -> list[str]:
    """Every way a post may print a move: signed and unsigned, 2 and 1 decimals."""
    out = []
    for n in ns:
        out += [signed_pct(x, n), f"{js_fixed(abs(x), n)}%"]
    return out


def usd_text(v: float) -> str:
    """A dollar amount as a post prints it, unsigned: $1.01T, $886B (>= $200B whole), $105.5B, $650M, $317M, $10.8M."""
    a = abs(v)
    if a >= 1e12:
        return f"${js_fixed(a / 1e12, 2)}T"
    if a >= 2e11:
        return f"${js_fixed(a / 1e9, 0)}B"
    if a >= 1e9:
        return f"${js_fixed(a / 1e9, 1)}B"
    if a >= 1e8:
        return f"${js_fixed(a / 1e6, 0)}M"
    if a >= 1e6:
        return f"${js_fixed(a / 1e6, 1)}M"
    return f"${js_fixed(a / 1e3, 0)}K"


def about_usd(v: float) -> str:
    """panels.ts aboutUsd: "$1.0T" from half a trillion on, else the whole-billion text."""
    a = abs(v)
    return f"${js_fixed(a / 1e12, 1)}T" if a >= 5e11 else usd_text(a)


def usd_forms(v: float) -> list[str]:
    """The amount unsigned and signed (−$105.5B / +$21.3B), in every precision a post may use."""
    a = abs(v)
    base = [usd_text(a), about_usd(a)]
    if a >= 1e12:
        base += [f"${js_fixed(a / 1e12, 1)}T"]
    if 1e9 <= a < 1e12:
        base += [f"${js_fixed(a / 1e9, 1)}B", f"${js_fixed(a / 1e9, 0)}B"]
    if 1e6 <= a < 1e9:
        base += [f"${js_fixed(a / 1e6, 0)}M", f"${js_fixed(a / 1e6, 1)}M"]
    sign = MINUS if v < 0 else "+"
    out = []
    for b in dict.fromkeys(base):
        out += [b, f"{sign}{b}"]
    return out


def count_forms(n: int) -> list[str]:
    return list(dict.fromkeys([str(n), f"{n:,}"]))


def ratio_text(r: float) -> str:
    """panels.ts multipleText: one decimal below 10, whole from 10 on."""
    return str(round(r)) if r >= 9.95 else js_fixed(r, 1)


def ratio_forms(r: float) -> list[str]:
    t = ratio_text(r)
    return [f"{t}{TIMES}", f"{t}x", t]


def date_words(iso: str) -> list[str]:
    """2026-10-16 -> ["2026-10-16", "Oct 16, 2026", "Oct 16"]."""
    d = dt.date.fromisoformat(iso[:10])
    md = f"{d.strftime('%b')} {d.day}"
    return [iso[:10], f"{md}, {d.year}", md]


def weekday_name(iso: str) -> str:
    return dt.date.fromisoformat(iso[:10]).strftime("%A")


def when_words(session: str, target: dt.date) -> str:
    """panels.ts sessionWhen: "today" when the session is the facts date, "on Friday" within 6 days, else "on Oct 9"."""
    s = dt.date.fromisoformat(session[:10])
    if s == target:
        return "today"
    if 0 < (target - s).days < 7:
        return f"on {s.strftime('%A')}"
    return f"on {s.strftime('%b')} {s.day}"


def norm_ticker(sym: str | None) -> str | None:
    """Map symbols are Yahoo style (BRK-B); facts and cashtags use the class dot (BRK.B)."""
    if not sym:
        return None
    s = str(sym).upper()
    if "-" in s:
        head, tail = s.rsplit("-", 1)
        if 1 <= len(tail) <= 2 and tail.isalpha():
            return f"{head}.{tail}"
    return s


def tier_of(cap: float | None) -> str:
    if not isinstance(cap, (int, float)) or cap <= 0:
        return "unknown"
    for floor, name in TIERS:
        if cap >= floor:
            return name
    return "micro"


def fingerprint(*parts) -> str:
    """A short hash of the numbers an item states: its card file is pinned under it (tools/pin_cards.py), so a card is
    reused only for the same numbers."""
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:8]


def panel_fingerprint(m: "Market", panel: str) -> str:
    """The data a share card draws, hashed: the card file is pinned under it, so every item of the same panel and data
    shares one pinned file, and new data (a late close, a new filing, a new Reddit capture) pins a new one."""
    p, f = m.p or {}, m.f or {}
    if panel in ("map", "breadth", "sectors"):
        t, b = p.get("totals") or {}, p.get("breadth") or {}
        return fingerprint(panel, p.get("session_date"), round((t.get("usd_change_sum") or 0) / 1e8), t.get("priced_count"),
                           b.get("advancers"), b.get("decliners"))
    if panel == "congress":
        c = f.get("congress") or {}
        return fingerprint(panel, c.get("last_disclosure"), c.get("totals"),
                           [(x.get("ticker"), x.get("trades")) for x in (c.get("top_tickers") or [])[:6]])
    if panel == "insiders":
        i = f.get("insiders") or {}
        return fingerprint(panel, i.get("last_disclosure"), round(i.get("total_usd") or 0),
                           round(((i.get("sells") or {}).get("total_usd")) or 0))
    if panel == "buzz":
        bz = f.get("buzz") or {}
        return fingerprint(panel, bz.get("trade_date"), bz.get("captured_at"), bz.get("price_session"))
    return fingerprint(panel)


def weekday_age(day: dt.date, target: dt.date) -> int:
    """Weekdays after `day` up to and including `target` (select_stories.weekday_age)."""
    if day >= target:
        return 0
    n, cur = 0, day
    while cur < target:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


# ---------------------------------------------------------------------------
# The two reads

class Market:
    """/market/pictures (+ /market/flows) of one facts pass. `rows` = the 500 map rows by cap, largest first."""

    def __init__(self, pictures: dict | None, flows: dict | None):
        self.p = pictures if isinstance(pictures, dict) and pictures.get("status") == "ok" else None
        self.f = flows if isinstance(flows, dict) and flows.get("status") == "ok" else None
        rows = [r for r in (self.p or {}).get("map") or [] if isinstance(r, dict) and r.get("symbol")]
        self.rows = sorted(rows, key=lambda r: -(r.get("market_cap") or 0))
        self.by_ticker = {norm_ticker(r["symbol"]): r for r in self.rows}
        self.rank = {norm_ticker(r["symbol"]): i + 1 for i, r in enumerate(self.rows)}

    @property
    def session(self) -> str | None:
        return (self.p or {}).get("session_date")

    def cap(self, ticker: str | None) -> float | None:
        r = self.by_ticker.get(norm_ticker(ticker)) if ticker else None
        c = (r or {}).get("market_cap")
        return float(c) if isinstance(c, (int, float)) and c > 0 else None

    def in_500(self, ticker: str | None) -> bool:
        return bool(ticker) and norm_ticker(ticker) in self.by_ticker

    def priced(self) -> list[dict]:
        """Map rows with a move for the session (stale rows never enter totals: the API leaves pct_change null)."""
        return [r for r in self.rows if not r.get("stale") and isinstance(r.get("pct_change"), (int, float))]

    def move(self, ticker: str | None) -> float | None:
        r = self.by_ticker.get(norm_ticker(ticker)) if ticker else None
        if r and not r.get("stale") and isinstance(r.get("pct_change"), (int, float)):
            return float(r["pct_change"])
        return None


def load(api) -> tuple[Market, list[str]]:
    """Both reads (cached by the Api for the pass). Errors name the path and the status; a failed read leaves that half
    of Market empty, and its items are not built."""
    errors = []
    p, perr = api.get(PICTURES)
    if perr or not isinstance(p, dict):
        errors.append(perr or f"{PICTURES}: unreadable response")
        p = None
    elif p.get("status") != "ok":
        if p.get("status") != "no_session":  # no published session yet is a state, not a failure
            errors.append(f"{PICTURES}: status {str(p.get('status'))[:20]}")
        p = None
    f, ferr = api.get(FLOWS)
    if ferr or not isinstance(f, dict):
        errors.append(ferr or f"{FLOWS}: unreadable response")
        f = None
    elif f.get("status") != "ok":
        errors.append(f"{FLOWS}: status {str(f.get('status'))[:20]}")
        f = None
    return Market(p, f), errors


# ---------------------------------------------------------------------------
# Computed figures (each one unit tested on 2026-10-16)

def median_move(m: Market) -> float | None:
    """The median 1d % of the priced map rows (the typical company of the 500)."""
    xs = [float(r["pct_change"]) for r in m.priced()]
    return statistics.median(xs) if xs else None


def risers(m: Market) -> int:
    return sum(1 for r in m.priced() if r["pct_change"] > 0)


def all_row(m: Market, h: str) -> float | None:
    """panels.ts allRow: the 500 over horizon h ("5d" / "21d") = summed sector $ change / summed base value, each base
    = usd_change / (pct_change / 100). None when a base cannot be recovered (a zero percent)."""
    usd_sum, base = 0.0, 0.0
    for s in (m.p or {}).get("sectors") or []:
        c = (s.get("change") or {}).get(h) or {}
        u, p = c.get("usd_change"), c.get("pct_change")
        if u is None or p is None:
            continue
        if p == 0:
            return None
        usd_sum += u
        base += u / (p / 100)
    return 100 * usd_sum / base if base > 0 else None


def sector_rows(m: Market, h: str) -> list[tuple[str, float, float | None]]:
    """(sector, pct, usd) for horizon h, priced sectors with a name only, largest move first."""
    out = []
    for s in (m.p or {}).get("sectors") or []:
        c = (s.get("change") or {}).get(h) or {}
        if s.get("sector") and s.get("priced_count") and isinstance(c.get("pct_change"), (int, float)):
            out.append((s["sector"], float(c["pct_change"]), c.get("usd_change")))
    return sorted(out, key=lambda r: -r[1])


def lead_sector(m: Market) -> tuple[str, float, float] | None:
    """panels.ts mapLeadSector: the sector with the largest 1d $ move in the direction of the whole map's move."""
    total = ((m.p or {}).get("totals") or {}).get("usd_change_sum")
    if not total:
        return None
    best = None
    for name, pct, usd in sector_rows(m, "1d"):
        if usd is None or math.copysign(1, usd) != math.copysign(1, total):
            continue
        if best is None or abs(usd) > abs(best[2]):
            best = (name, pct, usd)
    return best


def basket(m: Market, n: int = BASKET_N) -> dict | None:
    """The n largest by cap, equal-weighted over 5 sessions: the mean of pct_change_5d over the rows that have one;
    stale rows (no 5d move) are listed and left out. None when fewer than n - 2 rows have a move."""
    top = m.rows[:n]
    moved = [r for r in top if not r.get("stale") and isinstance(r.get("pct_change_5d"), (int, float))]
    if len(moved) < n - 2:
        return None
    mean = sum(float(r["pct_change_5d"]) for r in moved) / len(moved)
    return {"rows": moved, "excluded": [norm_ticker(r["symbol"]) for r in top if r not in moved], "mean": mean}


def breadth_prev_peak(b: dict) -> tuple[str, int] | None:
    """panels.ts breadthPrevPeak: the session before D when its net (up minus down) is the window's single largest."""
    s = b.get("series") or []
    if len(s) < 3:
        return None
    net = [x["advancers"] - x["decliners"] for x in s]
    i = len(s) - 2
    if net[i] <= 0 or any(v >= net[i] for j, v in enumerate(net) if j != i):
        return None
    return s[i]["date"], net[i]


def fresh_session(m: Market, target: dt.date) -> str | None:
    """Why the map's session cannot stand for the facts date (None when it can): the last weekday session before or on
    the facts date (weekday age <= 1: Friday's session on Saturday, Sunday and Monday)."""
    if not m.session:
        return "the market map has no session"
    s = dt.date.fromisoformat(m.session[:10])
    if s > target:
        return f"the market session {m.session} is after the facts date"
    if weekday_age(s, target) > 1:
        return f"the market session {m.session} is older than the last weekday session"
    return None


# ---------------------------------------------------------------------------
# Specs

def _spec(kind: str, key: str, **f) -> dict:
    """One item spec: facts.py builds the item. allowed = numbers the post may print; context_numbers = extra numbers
    computed here; tickers = cashtags the post may carry (the first is the lead)."""
    f.setdefault("ticker", None)
    f.setdefault("tickers", [f["ticker"]] if f["ticker"] else [])
    f.setdefault("context_tickers", [])
    f.setdefault("context_numbers", [])
    f.setdefault("angles", [])
    f.setdefault("banned_words", MARKET_BANNED if kind in WORDING_TYPES else [])
    return {"type": kind, "key": key, "pillar": PILLAR_OF[kind], "panel": PANEL_OF.get(kind), **f}


def _mover(r: dict) -> dict:
    return {"ticker": norm_ticker(r["symbol"]), "name": r.get("name"), "sector": r.get("sector"),
            "pct": float(r["pct_change"]), "usd": float(r["usd_change"]) if isinstance(r.get("usd_change"), (int, float)) else None,
            "cap": r.get("market_cap"), "pct_text": signed_pct(float(r["pct_change"])),
            "usd_text": (MINUS if (r.get("usd_change") or 0) < 0 else "+") + usd_text(r.get("usd_change") or 0)}


def _mover_numbers(mv: dict) -> list[str]:
    out = pct_forms(mv["pct"])
    if mv.get("usd") is not None:
        out += usd_forms(mv["usd"])
    return out


def market_move(m: Market, target: dt.date) -> tuple[list[dict], str | None]:
    t = (m.p or {}).get("totals") or {}
    pct, total, share = t.get("pct_change"), t.get("usd_change_sum"), t.get("priced_cap_share")
    why = fresh_session(m, target)
    if why:
        return [], why
    if not isinstance(pct, (int, float)) or not isinstance(total, (int, float)) or not isinstance(share, (int, float)):
        return [], "the market map has no session total"
    if share < MIN_CAP_SHARE:
        return [], f"priced cap share {share:.3f} < {MIN_CAP_SHARE} (too many names without a close)"
    if abs(pct) < MOVE_TRIGGER:
        return [], f"|move| {abs(pct):.2f}% < {MOVE_TRIGGER}% (a quiet day: no market-day post)"
    down = total < 0
    priced = sorted(m.priced(), key=lambda r: (r.get("usd_change") or 0) * (1 if down else -1))
    movers = [_mover(r) for r in priced if isinstance(r.get("usd_change"), (int, float))
              and (r["usd_change"] < 0) == down][:4]
    lead = lead_sector(m)
    other = [r for r in sector_rows(m, "1d") if (r[1] > 0) == down and abs(r[1]) >= ROT_MOVE_MIN]
    other = (other[0] if down else other[-1]) if other else None  # the best sector against the day's direction
    when = when_words(m.session, target)
    verb = "lost" if down else "gained"
    cov = f"{t.get('priced_count')} of {t.get('ticker_count')} priced, {js_fixed(share * 100, 1)}% of market value"
    tickers = [mv["ticker"] for mv in movers]
    text = (f"The 500 largest US-listed stocks {verb} about {about_usd(total)} {when} ({signed_pct(pct)}; {cov}). "
            f"Biggest dollar {'drops' if down else 'gains'}: "
            + ", ".join(f"${mv['ticker']} {mv['usd_text']} ({mv['pct_text']})" for mv in movers) + ".")
    if lead:
        text += f" {lead[0]} {(MINUS if lead[2] < 0 else '+') + usd_text(lead[2])} ({signed_pct(lead[1])}) led the move."
    if other:
        text += f" {other[0]} {signed_pct(other[1])} went the other way."
    allowed = [*usd_forms(total), *pct_forms(pct), "500", *count_forms(t.get("priced_count") or 0),
               *count_forms(t.get("ticker_count") or 0), f"{js_fixed(share * 100, 1)}%", *date_words(m.session),
               *(x for mv in movers for x in _mover_numbers(mv))]
    if lead:
        allowed += [*usd_forms(lead[2]), *pct_forms(lead[1])]
    if other:
        allowed += pct_forms(other[1])
    top = movers[0] if movers else None
    angles = [f"About {about_usd(total)} {'gone from' if down else 'added to'} the 500 largest US-listed stocks {when}.",
              (f"${top['ticker']} alone {'lost' if down else 'added'} {usd_text(top['usd'])} of market value {when}."
               if top else ""),
              (f"{lead[0]} {(MINUS if lead[2] < 0 else '+') + usd_text(lead[2])}, {other[0]} {signed_pct(other[1])}: "
               f"one day, two directions." if lead and other else "")]
    return [_spec("market_move", f"market_move:{m.session}", session_date=m.session, when=when,
                  tickers=tickers, totals={"usd_change_sum": total, "usd_text": about_usd(total), "pct_change": pct,
                                           "pct_text": signed_pct(pct), "priced": t.get("priced_count"),
                                           "total": t.get("ticker_count"), "priced_cap_share": round(share, 4)},
                  movers=movers, lead_sector=({"sector": lead[0], "pct": lead[1], "usd": lead[2]} if lead else None),
                  counter_sector=({"sector": other[0], "pct": other[1]} if other else None),
                  facts_text=text, allowed_numbers=allowed, angles=[a for a in angles if a],
                  magnitude=min(3.0, abs(pct) / MOVE_TRIGGER * 1.5),
                  trigger=f"|move| {js_fixed(abs(pct), 2)}% >= {MOVE_TRIGGER}%, cap share {js_fixed(share, 3)} >= {MIN_CAP_SHARE}",
                  fingerprint=fingerprint(m.session, round(total / 1e9), t.get("priced_count")),
                  card_date=m.session)], None


def mega_movers(m: Market, target: dt.date) -> tuple[list[dict], str | None]:
    """Up to 2: the largest |$ move| among the 500 when >= MEGA_USD, and the largest |%| move of a top-100 name past its
    threshold (another ticker)."""
    why = fresh_session(m, target)
    if why:
        return [], why
    t = (m.p or {}).get("totals") or {}
    if (t.get("priced_cap_share") or 0) < MIN_CAP_SHARE:
        return [], f"priced cap share {t.get('priced_cap_share')} < {MIN_CAP_SHARE}"
    priced = [r for r in m.priced() if isinstance(r.get("usd_change"), (int, float))]
    by_usd = sorted(priced, key=lambda r: -abs(r["usd_change"]))
    picks: list[tuple[dict, str]] = []
    if by_usd and abs(by_usd[0]["usd_change"]) >= MEGA_USD:
        picks.append((by_usd[0], f"|$ move| {usd_text(by_usd[0]['usd_change'])} >= {usd_text(MEGA_USD)}"))
    top = [r for r in priced if m.rank.get(norm_ticker(r["symbol"]), 999) <= MEGA_TOP]
    pct_hits = [r for r in top if abs(r["pct_change"]) >= (MEGA_PCT_TOP20 if m.rank[norm_ticker(r["symbol"])] <= 20 else MEGA_PCT)
                and all(r is not p[0] for p in picks)]
    if pct_hits:
        r = max(pct_hits, key=lambda r: abs(r["pct_change"]))
        lim = MEGA_PCT_TOP20 if m.rank[norm_ticker(r["symbol"])] <= 20 else MEGA_PCT
        picks.append((r, f"top-{MEGA_TOP} name (#{m.rank[norm_ticker(r['symbol'])]} by cap) |1d| "
                         f"{js_fixed(abs(r['pct_change']), 2)}% >= {lim}%"))
    if not picks:
        lead = by_usd[0] if by_usd else None
        return [], ("no 500-largest name moved $50B+ and no top-100 name moved 4%+ (3%+ for the top 20)"
                    + (f"; the largest $ move was ${norm_ticker(lead['symbol'])} {usd_text(lead['usd_change'])}" if lead else ""))
    when = when_words(m.session, target)
    out = []
    for r, trig in picks:
        mv = _mover(r)
        down = mv["pct"] < 0
        same = [x for x in by_usd if (x["usd_change"] < 0) == down]
        pos = next((i + 1 for i, x in enumerate(same) if x is r), None)
        nxt = [_mover(x) for x in same if x is not r][:2]
        rank = m.rank[mv["ticker"]]
        verb = "lost" if down else "added"
        place = (f"the biggest dollar {'drop' if down else 'gain'} among the 500 largest US-listed companies" if pos == 1
                 else f"#{pos} by dollar {'drop' if down else 'gain'} among the 500 largest US-listed companies")
        text = (f"${mv['ticker']} ({mv['name']}) {verb} {usd_text(mv['usd'])} of market value {when}, {mv['pct_text']}: "
                f"{place} (#{rank} by market cap). {'Next' if pos == 1 else 'Biggest dollar ' + ('drops' if down else 'gains')}: "
                + ", ".join(f"${n['ticker']} {n['usd_text']} ({n['pct_text']})" for n in nxt) + ".")
        allowed = [*_mover_numbers(mv), "500", str(rank), f"#{rank}", *date_words(m.session),
                   *(x for n in nxt for x in _mover_numbers(n))]
        if pos:
            allowed += [str(pos), f"#{pos}"]
        if pos == 1:
            angles = [f"{usd_text(mv['usd'])} of ${mv['ticker']} market value {'gone' if down else 'added'} in one session.",
                      f"${mv['ticker']} {mv['pct_text']} {when}: the biggest dollar move of the 500 largest US-listed companies.",
                      f"Which company moved the most dollars {when}? ${mv['ticker']}, by {usd_text(mv['usd'])}."]
        else:
            angles = [f"${mv['ticker']} {mv['pct_text']} {when}, a {usd_text(mv['usd'])} move in market value.",
                      f"One of the 100 largest US-listed companies moved {js_fixed(abs(mv['pct']), 2)}% {when}: ${mv['ticker']}.",
                      f"${mv['ticker']} is #{rank} by market cap. {when.capitalize() if when == 'today' else when[3:] if when.startswith('on ') else when} it {'fell' if down else 'rose'} {js_fixed(abs(mv['pct']), 2)}%."]
        mag = max(abs(mv["usd"]) / MEGA_USD * 1.5, abs(mv["pct"]) / MEGA_PCT * 1.5)
        out.append(_spec("mega_mover", f"mega_mover:{m.session}:{mv['ticker']}", ticker=mv["ticker"],
                         tickers=[mv["ticker"], *(n["ticker"] for n in nxt)], name=mv["name"], session_date=m.session,
                         when=when, mover=mv, rank_by_cap=rank, rank_by_usd=pos, next_movers=nxt, facts_text=text,
                         allowed_numbers=allowed, angles=angles, magnitude=min(3.0, mag), trigger=trig,
                         market_cap_usd=mv["cap"],
                         fingerprint=fingerprint(m.session, mv["ticker"], round(mv["usd"] / 1e8)), card_date=m.session))
    return out, None


def _top_cap_mover(m: Market, sector: str, h: str, sign: float) -> dict | None:
    """The largest-cap priced name of a sector whose move over h has the sector's sign."""
    key = "pct_change" if h == "1d" else "pct_change_5d"
    for r in m.priced():
        v = r.get(key)
        if r.get("sector") == sector and isinstance(v, (int, float)) and v != 0 and math.copysign(1, v) == sign:
            return {"ticker": norm_ticker(r["symbol"]), "pct": float(v), "pct_text": signed_pct(float(v))}
    return None


def sector_rotation(m: Market, target: dt.date) -> tuple[list[dict], str | None]:
    why = fresh_session(m, target)
    if why:
        return [], why
    out, quiet = [], []
    week = dt.date.fromisoformat(m.session[:10]).weekday() == 4
    for h, win in (("1d", "day"), ("5d", "week")):
        if win == "week" and not week:
            quiet.append("week: the session is not a Friday")
            continue
        rows = sector_rows(m, h)
        if len(rows) < 2:
            quiet.append(f"{win}: fewer than 2 priced sectors")
            continue
        spread = rows[0][1] - rows[-1][1]
        lim = ROT_DAY_PP if win == "day" else ROT_WEEK_PP
        if spread < lim:
            quiet.append(f"{win}: best minus worst sector {js_fixed(spread, 1)} pp < {lim} pp")
            continue
        if win == "day" and not (rows[0][1] >= ROT_MOVE_MIN and rows[-1][1] <= -ROT_MOVE_MIN):
            quiet.append(f"{win}: no sector up {ROT_MOVE_MIN}%+ and one down {ROT_MOVE_MIN}%+")
            continue
        all500 = (m.p["totals"].get("pct_change") if h == "1d" else all_row(m, h))
        if not isinstance(all500, (int, float)):
            quiet.append(f"{win}: the all-500 move cannot be computed")
            continue
        best, worst = rows[:2], rows[-2:][::-1]
        named = [*best, *worst]
        movers = {}
        for name, pct, _ in named:
            mv = _top_cap_mover(m, name, h, math.copysign(1, pct))
            if mv:
                movers[name] = mv
        lag = (target - dt.date.fromisoformat(m.session[:10])).days
        when = (when_words(m.session, target) if win == "day" else "this week" if lag <= 2 else "last week" if lag <= 9
                else f"in the week to {date_words(m.session)[2]}")
        lead_in = when[3:].capitalize() if when.startswith("on ") else when[:1].upper() + when[1:]
        if when.startswith("on "):
            lead_in = "On " + when[3:]
        fmt = lambda r: f"{SECTOR_SHORT.get(r[0], r[0])} {signed_pct(r[1], 1)}"  # noqa: E731
        text = (f"{lead_in}: the 500 largest US-listed stocks moved {signed_pct(all500, 1)} ({'5 sessions to' if win == 'week' else 'close of'} "
                f"{date_words(m.session)[2]}). Up: {', '.join(fmt(r) for r in best)}. Down: {', '.join(fmt(r) for r in worst)}. "
                f"Best minus worst: {js_fixed(spread, 1)} points.")
        if movers:
            text += " Largest names moving with their sector: " + ", ".join(
                f"${v['ticker']} {v['pct_text']} ({SECTOR_SHORT.get(k, k)})" for k, v in movers.items()) + "."
        allowed = [*pct_forms(all500), "500", *date_words(m.session), js_fixed(spread, 1), *(x for r in named for x in pct_forms(r[1])),
                   *(x for v in movers.values() for x in pct_forms(v["pct"]))]
        if win == "week":
            allowed += ["5", *date_words(m.p["horizon_from"]["5d"])]
        tick = list(dict.fromkeys(v["ticker"] for v in movers.values()))[:4]
        angles = [f"{fmt(worst[0])}, {fmt(best[0])} {when}.",
                  f"The 500 largest moved {signed_pct(all500, 1)} {when}, but not evenly.",
                  f"{SECTOR_SHORT.get(best[0][0], best[0][0])} up, {SECTOR_SHORT.get(worst[0][0], worst[0][0])} down: "
                  f"a {js_fixed(spread, 1)}-point gap {when}."]
        out.append(_spec("sector_rotation", f"sector_rotation:{m.session}:{win}", session_date=m.session, window=win,
                         when=when, tickers=tick, all_500=all500, best=[{"sector": r[0], "pct": r[1]} for r in best],
                         worst=[{"sector": r[0], "pct": r[1]} for r in worst], spread_pp=round(spread, 2),
                         sector_movers=movers, facts_text=text, allowed_numbers=allowed, angles=angles,
                         magnitude=min(3.0, spread / lim * 1.5),
                         trigger=f"{win}: best minus worst {js_fixed(spread, 1)} pp >= {lim} pp",
                         fingerprint=fingerprint(m.session, win, [round(r[1], 2) for r in named]), card_date=m.session))
    return out, (None if out else "; ".join(quiet))


def breadth_day(m: Market, target: dt.date) -> tuple[list[dict], str | None]:
    why = fresh_session(m, target)
    if why:
        return [], why
    b = (m.p or {}).get("breadth") or {}
    t = (m.p or {}).get("totals") or {}
    adv, dec, unch, total = b.get("advancers"), b.get("decliners"), b.get("unchanged"), b.get("total")
    if not total or adv is None or dec is None:
        return [], "breadth has no counts for the session"
    med, up500 = median_move(m), risers(m)
    pct = t.get("pct_change")
    if med is None or not isinstance(pct, (int, float)) or (t.get("priced_cap_share") or 0) < MIN_CAP_SHARE:
        return [], "the 500's median or move is missing, or cap coverage < 0.95"
    ratio = max(adv, dec) / max(1, min(adv, dec))
    lopsided = ratio >= BREADTH_RATIO
    diverge = abs(pct) >= DIVERGENCE_MOVE and (abs(med) <= FLAT_MEDIAN or math.copysign(1, med) != math.copysign(1, pct))
    if not (lopsided or diverge):
        return [], (f"advancers:decliners {js_fixed(ratio, 2)} < {BREADTH_RATIO} and no divergence (cap-weighted "
                    f"{signed_pct(pct)}, median {signed_pct(med)})")
    fell = dec >= adv
    share = round(100 * (dec if fell else adv) / total)
    priced = t.get("priced_count") or len(m.priced())
    down = pct < 0
    drags = sorted((r for r in m.priced() if isinstance(r.get("usd_change"), (int, float)) and (r["usd_change"] < 0) == down),
                   key=lambda r: abs(r["usd_change"]), reverse=True)[:3]
    drags = [_mover(r) for r in drags]
    when = when_words(m.session, target)
    peak = breadth_prev_peak(b)
    text = (f"{dec if fell else adv:,} of {total:,} US stocks RapidTradeView tracks {'fell' if fell else 'rose'} {when} "
            f"({share}%); {adv if fell else dec:,} {'rose' if fell else 'fell'} and {unch} were flat.")
    if peak:
        text += f" It came a day after the strongest up day of the last {len(b.get('series') or [])} closes (+{peak[1]:,} on {date_words(peak[0])[2]})."
    text += (f" The 500 largest US-listed stocks moved {signed_pct(pct)} weighted by market value, while the median "
             f"company moved {signed_pct(med)}: {up500} of {priced} priced rose.")
    if drags:
        text += f" Biggest dollar {'drags' if down else 'lifts'}: " + ", ".join(f"${d['ticker']} {d['pct_text']}" for d in drags) + "."
    allowed = [*count_forms(adv), *count_forms(dec), *count_forms(unch), *count_forms(total), f"{share}%", str(share),
               *pct_forms(pct), *pct_forms(med), *count_forms(up500), *count_forms(priced), "500", *date_words(m.session),
               *(x for d in drags for x in pct_forms(d["pct"]))]
    if peak:
        allowed += [*count_forms(peak[1]), f"+{peak[1]:,}", f"+{peak[1]}", *date_words(peak[0]), str(len(b.get("series") or []))]
    kind = "divergence" if diverge else "lopsided"
    angles = [f"{dec if fell else adv:,} of {total:,} US stocks {'fell' if fell else 'rose'} {when}.",
              (f"The 500 largest moved {signed_pct(pct)}, yet the typical one moved {signed_pct(med)}." if diverge
               else f"{share}% of US stocks {'fell' if fell else 'rose'} {when}."),
              f"Was {when.replace('on ', '')} as broad as it looked? {up500} of the 500 largest rose."]
    mag = min(3.0, max((ratio - 1), abs(pct) / MOVE_TRIGGER * 1.5 if diverge else 0))
    return [_spec("breadth_day", f"breadth_day:{m.session}", session_date=m.session, when=when,
                  tickers=[d["ticker"] for d in drags],
                  breadth={"advancers": adv, "decliners": dec, "unchanged": unch, "total": total, "share_pct": share},
                  median_500=round(med, 4), risers_500=up500, priced_500=priced, cap_weighted_pct=pct, drags=drags,
                  signal=kind, facts_text=text, allowed_numbers=allowed, angles=angles, magnitude=mag,
                  trigger=(f"divergence: cap-weighted {signed_pct(pct)} vs median {signed_pct(med)}" if diverge
                           else f"advancers:decliners {js_fixed(ratio, 2)} >= {BREADTH_RATIO}"),
                  fingerprint=fingerprint(m.session, adv, dec, round(med, 3)), card_date=m.session)], None


def basket_week(m: Market, target: dt.date) -> tuple[list[dict], str | None]:
    why = fresh_session(m, target)
    if why:
        return [], why
    if dt.date.fromisoformat(m.session[:10]).weekday() != 4:
        return [], "the session is not a Friday (the basket is a week-in-review item)"
    bk = basket(m)
    if not bk:
        return [], f"fewer than {BASKET_N - 2} of the {BASKET_N} largest have a 5-session move"
    mean = bk["mean"]
    if abs(mean) < BASKET_MIN:
        return [], f"the {BASKET_N} largest moved {signed_pct(mean)} equal-weighted (< {BASKET_MIN}%)"
    rows = sorted(bk["rows"], key=lambda r: r["pct_change_5d"])
    up = [r for r in rows if r["pct_change_5d"] > 0]
    worst, best = rows[:3], rows[::-1][:3]
    fmt = lambda r: f"${norm_ticker(r['symbol'])} {signed_pct(r['pct_change_5d'])}"  # noqa: E731
    n = len(bk["rows"])
    text = (f"The {n} largest US-listed companies by market value, held in equal amounts, moved {signed_pct(mean)} over the "
            f"5 sessions to {date_words(m.session)[2]}. {len(up)} of {n} rose. Best: {', '.join(fmt(r) for r in best)}. "
            f"Worst: {', '.join(fmt(r) for r in worst)}.")
    if bk["excluded"]:
        text += f" Left out (no 5-session move): {', '.join(bk['excluded'])}."
    named = list(dict.fromkeys(norm_ticker(r["symbol"]) for r in (worst + best)))
    allowed = [*pct_forms(mean), str(n), *count_forms(len(up)), "5", *date_words(m.session), *date_words(m.p["horizon_from"]["5d"]),
               *(x for r in rows for x in pct_forms(r["pct_change_5d"]))]
    angles = [f"Owning the {n} largest US companies equally {'cost' if mean < 0 else 'made'} {js_fixed(abs(mean), 2)}% this week.",
              f"{len(up)} of the {n} largest US companies rose this week.",
              f"What did a mega-cap portfolio do this week? {signed_pct(mean)}, equal-weighted."]
    return [_spec("basket_week", f"basket_week:{m.session}", session_date=m.session, tickers=named[:4],
                  basket=[{"ticker": norm_ticker(r["symbol"]), "pct_5d": r["pct_change_5d"]} for r in rows],
                  excluded=bk["excluded"], mean_5d=round(mean, 4), risers=len(up), facts_text=text, allowed_numbers=allowed,
                  angles=angles, magnitude=min(3.0, abs(mean) / BASKET_MIN * 1.5),
                  trigger=f"|equal-weight 5d| {js_fixed(abs(mean), 2)}% >= {BASKET_MIN}%",
                  fingerprint=fingerprint(m.session, round(mean, 3)), card_date=m.session)], None


def _flow_due(target: dt.date, top_now: list[str], top_before: list[str] | None, m: Market) -> str | None:
    """Why a flow item is due (None: not due): weekly (Saturday / Monday facts) or a 500-largest name new in the top 5."""
    if target.weekday() in FLOW_WEEKLY_DAYS:
        return f"weekly ({target.strftime('%A')} facts)"
    if top_before is None:
        return None
    new = [t for t in top_now if t not in top_before and m.in_500(t)]
    return f"{', '.join('$' + t for t in new)} entered the top {FLOW_TOP}" if new else None


def congress_flow(m: Market, target: dt.date, before: dict | None) -> tuple[list[dict], str | None, list[str]]:
    c = (m.f or {}).get("congress") or {}
    tops = [x for x in c.get("top_tickers") or [] if isinstance(x, dict) and x.get("ticker")]
    top5 = [norm_ticker(x["ticker"]) for x in tops[:FLOW_TOP]]
    if not m.f:
        return [], "the flows read failed", top5
    tot = c.get("totals") or {}
    if not tops or not tot:
        return [], "no Congress trades in the window", top5
    due = _flow_due(target, top5, (before or {}).get("congress_top5"), m)
    if not due:
        return [], "not due (weekly on Saturday / Monday, or when a 500-largest name enters the top 5)", top5
    lead = next((x for x in tops if m.in_500(x["ticker"])), None)
    if not lead:
        return [], "no 500-largest name in the Congress top tickers (a post would name no stock people know)", top5
    win = c.get("window") or {}
    lt = norm_ticker(lead["ticker"])
    others = [x for x in tops if x is not lead and m.in_500(x["ticker"])][:2]
    text = (f"${lt} ({lead.get('name')}) was the most-traded 500-largest stock in Congress over {win.get('days')} days "
            f"({date_words(win['from'])[2]} to {date_words(c.get('last_disclosure') or win['to'])[2]}, by disclosure): "
            f"{lead['trades']} trades by {lead['members']} members, {lead['buys']} buys and {lead['sells']} sells. "
            f"All members: {tot.get('buys')} buys, {tot.get('sells')} sells in {tot.get('tickers')} tickers by {tot.get('members')} members.")
    if others:
        text += " Also busy: " + ", ".join(f"${norm_ticker(x['ticker'])} {x['trades']} trades" for x in others) + "."
    nums = [lead["trades"], lead["members"], lead["buys"], lead["sells"], tot.get("buys"), tot.get("sells"), tot.get("tickers"),
            tot.get("members"), win.get("days"), *(x["trades"] for x in others), *(x.get("members") for x in others)]
    allowed = [*(f for v in nums if isinstance(v, int) for f in count_forms(v)), *date_words(win["from"]), *date_words(win["to"]),
               *date_words(c.get("last_disclosure") or win["to"])]
    if tot.get("buys") and tot.get("sells"):
        r = max(tot["buys"], tot["sells"]) / min(tot["buys"], tot["sells"])
        allowed += [js_fixed(r, 1)]
    angles = [f"{lead['members']} members of Congress traded ${lt} in the last {win.get('days')} days.",
              f"${lt}: the most-traded big stock in Congress this month, {lead['buys']} buys vs {lead['sells']} sells.",
              f"Congress disclosed {tot.get('sells')} sells and {tot.get('buys')} buys in {win.get('days')} days. Top name: ${lt}."]
    return [_spec("congress_flow", f"congress_flow:{c.get('last_disclosure')}:{lt}", ticker=lt,
                  tickers=[lt, *(norm_ticker(x["ticker"]) for x in others)], name=lead.get("name"),
                  window=win, totals=tot, leader=lead, others=others, facts_text=text, allowed_numbers=allowed, angles=angles,
                  market_cap_usd=m.cap(lt), magnitude=min(3.0, lead["trades"] / 4), trigger=due, top5=top5,
                  fingerprint=fingerprint(c.get("last_disclosure"), tot, [(x["ticker"], x["trades"]) for x in tops[:3]]),
                  card_date=c.get("last_disclosure"))], None, top5


def insider_flow(m: Market, target: dt.date, before: dict | None) -> tuple[list[dict], str | None, list[str]]:
    i = (m.f or {}).get("insiders") or {}
    sells = i.get("sells") or {}
    stop = [x for x in sells.get("top") or [] if isinstance(x, dict) and x.get("ticker")]
    btop = [x for x in i.get("top") or [] if isinstance(x, dict) and x.get("ticker")]
    s500 = [x for x in stop if m.in_500(x["ticker"])]
    b500 = [x for x in btop if m.in_500(x["ticker"])]
    top5 = [norm_ticker(x["ticker"]) for x in s500[:FLOW_TOP]]
    if not m.f:
        return [], "the flows read failed", top5
    bought, sold = i.get("total_usd"), sells.get("total_usd")
    if not isinstance(bought, (int, float)) or not isinstance(sold, (int, float)):
        return [], "insider totals missing", top5
    due = _flow_due(target, top5, (before or {}).get("insider_sell_top5"), m)
    if not due:
        return [], "not due (weekly on Saturday / Monday, or when a 500-largest name enters the top 5)", top5
    if not s500 and not b500:
        return [], "no 500-largest name among the top insider buyers or sellers", top5
    win = i.get("window") or {}
    # panels.ts cardDate: the newest disclosure of either side, else the window end
    last = max([x for x in (i.get("last_disclosure"), sells.get("last_disclosure")) if x] or [win.get("to")])
    lead_s = s500[:3]
    lead_b = b500[:2]
    text = (f"Insiders reported {usd_text(bought)} of open-market buying and {usd_text(sold)} of selling over {win.get('days')} "
            f"days (Form 4s filed {date_words(win['from'])[2]} to {date_words(last)[2]}; {i.get('company_count')} companies with "
            f"buys, {sells.get('company_count')} with sells).")
    if lead_s:
        text += " Largest sellers among the 500 largest US-listed companies: " + ", ".join(
            f"${norm_ticker(x['ticker'])} {usd_text(x['total_usd'])} ({x['insider_count']} insiders)" for x in lead_s) + "."
    if lead_b:
        text += " Largest buyers among them: " + ", ".join(
            f"${norm_ticker(x['ticker'])} {usd_text(x['total_usd'])}" for x in lead_b) + "."
    named = [norm_ticker(x["ticker"]) for x in lead_s + lead_b]
    allowed = [*usd_forms(bought), *usd_forms(sold), *count_forms(win.get("days") or 30), *count_forms(i.get("company_count") or 0),
               *count_forms(sells.get("company_count") or 0), "500", *date_words(win["from"]), *date_words(last),
               *(x for r in lead_s + lead_b for x in usd_forms(r["total_usd"])),
               *(f for r in lead_s + lead_b for f in count_forms(r.get("insider_count") or 0))]
    if bought:
        allowed.append(js_fixed(sold / bought, 1))
    lt = named[0]
    angles = [f"Insiders sold {usd_text(sold)} and bought {usd_text(bought)} of their own stock in {win.get('days')} days.",
              f"${lt} insiders: {usd_text((lead_s or lead_b)[0]['total_usd'])} {'sold' if lead_s else 'bought'} in {win.get('days')} days.",
              f"For every $1 insiders bought, they sold ${js_fixed(sold / bought, 1) if bought else '?'}. Top seller: ${lt}."]
    return [_spec("insider_flow", f"insider_flow:{last}:{lt}", ticker=lt, tickers=list(dict.fromkeys(named))[:4],
                  window=win, bought_usd=bought, sold_usd=sold, buy_companies=i.get("company_count"),
                  sell_companies=sells.get("company_count"), top_sellers_500=lead_s, top_buyers_500=lead_b,
                  facts_text=text, allowed_numbers=allowed, angles=[a for a in angles if "?" not in a or bought],
                  market_cap_usd=m.cap(lt), magnitude=min(3.0, max(0.0, math.log10(max(sold, 1) / 1e8)) * 1.5), trigger=due,
                  top5=top5, fingerprint=fingerprint(last, round(bought / 1e6), round(sold / 1e6), named),
                  card_date=last)], None, top5


def reddit_buzz(m: Market, target: dt.date) -> tuple[list[dict], str | None]:
    bz = (m.f or {}).get("buzz") or {}
    if not m.f:
        return [], "the flows read failed"
    stocks = sorted([s for s in bz.get("stocks") or [] if isinstance(s, dict) and s.get("ticker")], key=lambda s: s.get("rank") or 999)
    rows = stocks[:BUZZ_ROWS]

    def ratio(s):
        avg = s.get("mentions_avg")
        return s["mentions"] / avg if isinstance(avg, (int, float)) and avg > 0 else None

    def qualifies(s):
        r = ratio(s)
        return (r is not None and s["mentions_avg"] >= BUZZ_MIN_AVG and r >= BUZZ_MIN_RATIO
                and s.get("mentions", 0) >= BUZZ_MIN_MENTIONS)

    q = [s for s in rows if qualifies(s)]
    if not q:
        return [], "no top-10 Reddit stock is 1.5x+ its usual count (20+ mentions, usual 5+)"
    lead = max(q, key=lambda s: (ratio(s), s["mentions"]))
    lt = norm_ticker(lead["ticker"])
    lr = ratio(lead)
    top20 = m.rank.get(lt, 999) <= 20
    if not (lr >= BUZZ_HOT or (top20 and lr >= BUZZ_TOP20_HOT)):
        return [], f"the most unusual, ${lt}, is {ratio_text(lr)}x usual (< {BUZZ_HOT}x; {BUZZ_TOP20_HOT}x for a top-20 name)"
    others = sorted([s for s in q if s is not lead and ratio(s) >= 2], key=lambda s: -ratio(s))[:2]
    moved = [s for s in rows if not s.get("stale") and isinstance(s.get("price_change_pct"), (int, float))]
    fell = sum(1 for s in moved if s["price_change_pct"] < 0)
    usual = bz.get("usual") or {}
    day = "weekend" if usual.get("day_type") == "weekend" else "day"
    session = bz.get("price_session")
    lead_move = (lead.get("price_change_pct") if not lead.get("stale") and lead.get("price_as_of") == session else None)
    text = (f"Reddit mentions of ${lt} ({lead.get('name')}): {lead['mentions']} vs a usual {day} average of "
            f"{js_fixed(lead['mentions_avg'], 0) if lead['mentions_avg'] >= 9.95 else js_fixed(lead['mentions_avg'], 1)} "
            f"({ratio_text(lr)}{TIMES} usual; capture {date_words(bz.get('trade_date') or target.isoformat())[2]}).")
    if isinstance(lead_move, (int, float)):
        text += f" The stock moved {signed_pct(lead_move)} on {weekday_name(session)}, {date_words(session)[2]}."
    if others:
        text += " Also running hot: " + ", ".join(f"${norm_ticker(s['ticker'])} {ratio_text(ratio(s))}{TIMES}" for s in others) + "."
    if moved:
        text += (f" {fell} of the {len(moved)} most-mentioned stocks with a close for {date_words(session)[2]} fell that day."
                 if fell * 2 >= len(moved) else
                 f" {len(moved) - fell} of the {len(moved)} most-mentioned stocks with a close for {date_words(session)[2]} rose that day.")
    avg_txt = [js_fixed(lead["mentions_avg"], 0), js_fixed(lead["mentions_avg"], 1)]
    allowed = [*count_forms(lead["mentions"]), *avg_txt, *ratio_forms(lr), *(x for s in others for x in ratio_forms(ratio(s))),
               str(len(rows)), str(len(moved)), str(fell), str(len(moved) - fell), *date_words(session or target.isoformat()),
               *date_words(bz.get("trade_date") or target.isoformat())]
    if isinstance(lead_move, (int, float)):
        allowed += pct_forms(lead_move)
    angles = [f"Reddit is talking about ${lt} {ratio_text(lr)}{TIMES} more than usual: {lead['mentions']} mentions vs {avg_txt[1 if lead['mentions_avg'] < 9.95 else 0]}.",
              f"${lt} is the most unusual name on Reddit {'this weekend' if day == 'weekend' else 'today'}.",
              (f"${lt} moved {signed_pct(lead_move)}, and Reddit noticed: {ratio_text(lr)}{TIMES} its usual mentions."
               if isinstance(lead_move, (int, float)) else "")]
    return [_spec("reddit_buzz", f"reddit_buzz:{bz.get('trade_date')}:{lt}", ticker=lt,
                  tickers=[lt, *(norm_ticker(s["ticker"]) for s in others)], name=lead.get("name"),
                  capture_date=bz.get("trade_date"), price_session=session, usual=usual,
                  lead={"ticker": lt, "mentions": lead["mentions"], "usual": lead["mentions_avg"], "ratio": round(lr, 3),
                        "move": lead_move},
                  others=[{"ticker": norm_ticker(s["ticker"]), "ratio": round(ratio(s), 3)} for s in others],
                  top_rows=len(rows), fell=fell, with_close=len(moved), facts_text=text, allowed_numbers=allowed,
                  angles=[a for a in angles if a], market_cap_usd=m.cap(lt), magnitude=min(3.0, math.log2(lr)),
                  trigger=f"${lt} {ratio_text(lr)}x usual >= {BUZZ_TOP20_HOT if top20 and lr < BUZZ_HOT else BUZZ_HOT}x",
                  fingerprint=fingerprint(bz.get("trade_date"), lt, lead["mentions"], session),
                  card_date=session)], None


def earnings_week_preview(m: Market, target: dt.date, week: dict | None, monday: dt.date) -> tuple[list[dict], str | None]:
    """Sunday / Monday facts: the week's confirmed reporters among the 500 largest (map caps), largest first."""
    if target.weekday() not in (6, 0):
        return [], "the week preview is built on Sunday and Monday facts only"
    if not m.p:
        return [], "the market map did not load (500-largest caps)"
    if not isinstance(week, dict) or not isinstance(week.get("days"), list):
        return [], f"the earnings calendar for the week of {monday} did not load"
    rows = []
    for day in week["days"]:
        d = day.get("date")
        if not d or not (monday <= dt.date.fromisoformat(d) <= monday + dt.timedelta(days=4)):
            continue
        for r in day.get("reports") or []:
            sym = norm_ticker(r.get("symbol"))
            if r.get("date_confirmed") is True and m.in_500(sym) and (m.cap(sym) or 0) >= PREVIEW_MIN_CAP:
                rows.append({"ticker": sym, "date": d, "hour": r.get("hour"), "cap": m.cap(sym),
                             "name": m.by_ticker[sym].get("name")})
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: -r["cap"]):
        if r["ticker"] not in seen:
            seen.add(r["ticker"])
            uniq.append(r)
    if len(uniq) < PREVIEW_MIN_N:
        return [], f"{len(uniq)} confirmed reporters worth $10B+ among the 500 largest this week (< {PREVIEW_MIN_N})"
    show = uniq[:PREVIEW_SHOW]
    hours = {"bmo": "before the open", "amc": "after the close", "dmh": "during market hours"}
    day = lambda iso: dt.date.fromisoformat(iso).strftime("%a")  # noqa: E731
    text = (f"{len(uniq)} of the 500 largest US-listed companies (each worth $10B+) report earnings in the week of "
            f"{date_words(monday.isoformat())[2]} (confirmed dates). Largest: "
            + ", ".join(f"${r['ticker']} {day(r['date'])} {date_words(r['date'])[2]}{', ' + hours[r['hour']] if r.get('hour') in hours else ''}"
                        for r in show) + ".")
    allowed = [*count_forms(len(uniq)), "500", "$10B", str(len(show)), *date_words(monday.isoformat()),
               *(x for r in show for x in date_words(r["date"]))]
    t0 = show[0]
    angles = [f"{len(uniq)} big names report this week. The biggest: ${t0['ticker']} on {dt.date.fromisoformat(t0['date']).strftime('%A')}.",
              f"${show[0]['ticker']}, ${show[1]['ticker']} and ${show[2]['ticker']} all report this week.",
              f"Which report are you watching this week: ${show[0]['ticker']} or ${show[1]['ticker']}?"]
    return [_spec("earnings_week_preview", f"earnings_week_preview:{monday.isoformat()}", tickers=[r["ticker"] for r in show[:4]],
                  week_of=monday.isoformat(), reporters=show, reporters_total=len(uniq), facts_text=text,
                  market_cap_usd=show[0]["cap"],
                  allowed_numbers=allowed, angles=angles, magnitude=min(3.0, len(uniq) / 4),
                  trigger=f"{len(uniq)} reporters >= $10B >= {PREVIEW_MIN_N}", path="/earnings")], None


def earnings_reactions(m: Market, target: dt.date, week: dict | None, reports: list[dict]) -> tuple[list[dict], str | None]:
    """A $10B+ 500-largest company whose report session is the map's session: bmo on that day, amc the weekday before.
    Its 1d move from the map; the report must be in the archive (ready, same release date)."""
    why = fresh_session(m, target)
    if why:
        return [], why
    if not isinstance(week, dict) or not isinstance(week.get("days"), list):
        return [], "the current week's earnings calendar did not load (the API serves no past week)"
    session = dt.date.fromisoformat(m.session[:10])
    prev = session - dt.timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= dt.timedelta(days=1)
    ready = {(str(r.get("ticker")).upper(), r.get("release_date")): r for r in reports
             if isinstance(r, dict) and r.get("summary_status") == "ready"}
    out = []
    for day in week["days"]:
        for r in day.get("reports") or []:
            sym = norm_ticker(r.get("symbol"))
            d = day.get("date")
            hit = (r.get("hour") == "bmo" and d == session.isoformat()) or (r.get("hour") == "amc" and d == prev.isoformat())
            if not hit or not m.in_500(sym) or (m.cap(sym) or 0) < REACTION_MIN_CAP:
                continue
            mv = m.move(sym)
            rep = ready.get((sym.replace(".", "-"), d)) or ready.get((sym, d))
            if mv is None or abs(mv) < REACTION_MIN_MOVE or not rep:
                continue
            row = m.by_ticker[sym]
            when = "before the open" if r["hour"] == "bmo" else "after the close"
            fl = rep.get("fiscal_label") or ""
            text = (f"${sym} ({row.get('name')}) moved {signed_pct(mv)} on {weekday_name(m.session)}, {date_words(m.session)[2]}, "
                    f"the first session after its {fl} report ({date_words(d)[2]}, {when}).")
            allowed = [*pct_forms(mv), *date_words(m.session), *date_words(d), *([fl] if fl else []),
                       *([f"Q{rep.get('fiscal_quarter')}"] if rep.get("fiscal_quarter") else [])]
            angles = [f"${sym} {signed_pct(mv)} the session after its {fl} report.",
                      f"How the market took ${sym}'s {fl} numbers: {signed_pct(mv)}.",
                      f"${sym} reported {when} on {date_words(d)[2]}. The next session: {signed_pct(mv)}."]
            out.append(_spec("earnings_reaction", f"earnings_reaction:{sym}:{d}", ticker=sym, name=row.get("name"),
                             session_date=m.session, report_date=d, hour=r["hour"], fiscal_label=fl, move=mv,
                             facts_text=text, allowed_numbers=allowed, angles=angles, market_cap_usd=m.cap(sym),
                             magnitude=min(3.0, abs(mv) / REACTION_MIN_MOVE * 1.5),
                             trigger=f"|next-session move| {js_fixed(abs(mv), 2)}% >= {REACTION_MIN_MOVE}%",
                             path=f"/dashboard/{sym}"))
    return out, (None if out else f"no $10B+ 500-largest reporter moved {REACTION_MIN_MOVE}%+ in its report session {m.session}")
