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
BROAD_SHARE = 60          # breadth: >= 60% of all tracked stocks moved with the market = a broad day (the card)
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


def claim(words, subjects=(), says: str = "", bare: bool = False, direction: str | None = None,
          needs: str | None = None, *, kind: str = "stock", polarity: str | None = "auto", rank=None, within=(),
          scope: str | None = None, metric: str | None = None, universe: str | None = None,
          date: str | None = None) -> dict:
    """One comparative / superlative statement the item backs (tools/claims.py checks posts against them): the words
    (claims.CATEGORIES: led, biggest, worst, best, most, least, only, first, top, record), the subjects in rank order
    (tickers, or map sector names when kind="sector"), polarity ("best" / "worst": which end of the ranking; None: a
    ranking with no good / bad end, e.g. market value, mentions; "auto": best / worst from the words), rank (1: the
    single subject is #1; "group": the subjects are the top N in order; default from the count), within (the sectors /
    tickers the ranking is inside: the sentence must name one, or match scope), bare (a claim with no subjects only: the
    word may stand without naming a subject), direction ("up" / "down": the subjects' move; the sentence's direction words and signs must agree),
    needs (a pattern the sentence must carry, e.g. "dollar" for a $ ranking), metric (what is ranked: usd_change,
    pct_change, market_cap, mentions, mention_ratio, sync, trades, usd_flow, breadth), universe ("10": the 10-largest
    basket, which a sentence must name), date (a bare claim's session: "the strongest up day" was Oct 15) and says (the
    true sentence)."""
    if kind == "sector":
        subj = [s for s in subjects if s]
    else:
        subj = [norm_ticker(s) for s in subjects if s]
    subj = list(dict.fromkeys(subj))
    if polarity == "auto":
        polarity = "best" if "best" in words else "worst" if "worst" in words else None
    wi = [s if (s and s.upper() != s) else norm_ticker(s) for s in within if s]
    return {"words": list(dict.fromkeys(words)), "subjects": subj, "kind": kind, "polarity": polarity,
            "rank": rank or (1 if len(subj) <= 1 else "group"), "within": list(dict.fromkeys(wi)), "scope": scope,
            "metric": metric, "universe": universe, "date": date,
            "bare": bool(bare) and not subj, "direction": direction, "needs": needs, "says": says}


SECTOR_SCOPE = r"\b(?:its|their|each)\s+(?:[a-z]+\s+)?sectors?\b"  # claims.SECTOR_SCOPE: "led its sector"

# Claim phrases (HQ 2026-10-18 allowlist, claims.py section 2b): every comparison / ranking an item backs, as complete
# sentences with the exact number, window and scope. A post sentence with ranking language must be one of them verbatim.
US500 = "among the 500 largest US-listed companies"
ORDW = {1: "", 2: "second-", 3: "third-", 4: "fourth-", 5: "fifth-"}


def ordinal_phrases(subjects: list[tuple[str, str]], head: str, noun: str, tail: str, list_head: str | None = None,
                    lists: tuple[int, ...] = (3, 4)) -> list[str]:
    """subjects [(subject, number text)] in rank order from #1: "{subject} {head} the {ord}{noun} {tail} ({number})." for
    the top 5, and "{list_head}, in order: A (x), B (y), C (z)." for each list length in `lists` (cashtags: at most 4)."""
    out = [f"{s} {head} the {ORDW[i + 1]}{noun} {tail} ({n})." for i, (s, n) in enumerate(subjects[:5])]
    if list_head:
        for k in lists:
            if 2 <= k <= len(subjects):
                out.append(f"{list_head}, in order: " + ", ".join(f"{s} ({n})" for s, n in subjects[:k]) + ".")
    return out


def headline(tickers=(), numbers=()) -> dict:
    """What an item leads with: its lead tickers and its headline numbers (signs stripped). facts.py keeps two items that
    share one of either out of the same day's top 8 (facts.diversify_top) and cools the tickers down across pillars."""
    nums = []
    for n in numbers:
        if n:
            nums.append(str(n).replace(MINUS, "").replace("-", "").lstrip("+"))
    return {"tickers": list(dict.fromkeys(norm_ticker(t) for t in tickers if t)), "numbers": list(dict.fromkeys(nums))}


DOLLAR = r"dollars?|market value|market cap|\$\d"


def headline_tickers(item: dict) -> list[str]:
    """An item's lead tickers: its headline (market items), else its own ticker, else its first 3 tickers (lists)."""
    h = (item.get("headline") or {}).get("tickers")
    if h:
        return [norm_ticker(t) for t in h if t]
    if item.get("ticker"):
        return [norm_ticker(item["ticker"])]
    return [norm_ticker(t) for t in (item.get("tickers") or [])[:3] if t]


def week_when(session: str, target: dt.date) -> str:
    """The 5-session window ending at `session`, worded for the facts date: "this week" on a weekday of the same week,
    "last week" on a weekday of the next week, else "in the week to Oct 16" (weekends included: a Saturday or Sunday
    post never says "this week" about the week that just closed)."""
    s = dt.date.fromisoformat(session[:10])
    mon_s, mon_t = s - dt.timedelta(days=s.weekday()), target - dt.timedelta(days=target.weekday())
    if target.weekday() < 5 and mon_s == mon_t:
        return "this week"
    if target.weekday() < 5 and (mon_t - mon_s).days == 7:
        return "last week"
    return f"in the week to {date_words(session)[2]}"


def lead_in(when: str) -> str:
    """"this week" -> "This week", "on Friday" -> "On Friday", "in the week to Oct 16" -> "In the week to Oct 16"."""
    return when[:1].upper() + when[1:]


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


def _down(x: float) -> str:
    return "down" if x < 0 else "up"


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
    d = "down" if down else "up"
    priced = sorted(m.priced(), key=lambda r: (r.get("usd_change") or 0) * (1 if down else -1))
    same_way = [r for r in priced if isinstance(r.get("usd_change"), (int, float)) and (r["usd_change"] < 0) == down]
    movers = [_mover(r) for r in same_way[:4]]
    lead = lead_sector(m)
    lead_movers = [_mover(r) for r in same_way if lead and r.get("sector") == lead[0]][:3]
    rows1d = sector_rows(m, "1d")
    other = [r for r in rows1d if (r[1] > 0) == down and abs(r[1]) >= ROT_MOVE_MIN]
    other = (other[0] if down else other[-1]) if other else None  # the best sector against the day's direction
    when = when_words(m.session, target)
    verb = "lost" if down else "gained"
    cov = f"{t.get('priced_count')} of {t.get('ticker_count')} priced, {js_fixed(share * 100, 1)}% of market value"
    tickers = list(dict.fromkeys([mv["ticker"] for mv in movers] + [mv["ticker"] for mv in lead_movers]))
    drops = "drops" if down else "gains"
    # each mover carries its own sector, so no sentence reads as if $GOOGL were a Technology company
    text = (f"The 500 largest US-listed stocks {verb} about {about_usd(total)} {when} ({signed_pct(pct)}; {cov}). "
            f"Biggest dollar {drops}: "
            + ", ".join(f"${mv['ticker']} {mv['usd_text']} ({mv['pct_text']}, {mv['sector']})" for mv in movers) + ".")
    pol = "worst" if down else "best"  # the end of the day's ranking these movers / the lead sector top
    claims = [claim(["biggest", "top", "most", "led"], [mv["ticker"] for mv in movers], needs=DOLLAR, direction=d,
                    polarity=pol, metric="usd_change", says=f"biggest dollar {drops} {when}, in order: "
                    + ", ".join("$" + mv["ticker"] for mv in movers))]
    if lead:
        text += f" {lead[0]} {(MINUS if lead[2] < 0 else '+') + usd_text(lead[2])} ({signed_pct(lead[1])}) led the move."
        # "led the move" has no side of its own (the move was the day's direction): polarity None, direction d
        claims.append(claim(["led"], [lead[0]], direction=d, kind="sector", polarity=None,
                            says=f"{lead[0]} led the move / the {'drop' if down else 'gain'} (largest sector dollar move)"))
        claims.append(claim(["biggest", "most", "top"], [lead[0]], needs=DOLLAR, direction=d, kind="sector", polarity=pol,
                            metric="usd_change", says=f"{lead[0]} had the biggest sector dollar {'drop' if down else 'gain'}"))
        extreme = rows1d and ((down and rows1d[-1][0] == lead[0]) or (not down and rows1d[0][0] == lead[0]))
        if extreme:
            claims.append(claim(["worst" if down else "best", "biggest", "top", "led", "most"], [lead[0]], direction=d,
                                kind="sector", metric="pct_change",
                                says=f"{lead[0]} was the {'worst' if down else 'best'} sector by % {when}"))
        if lead_movers:
            text += (f" {lead[0]}'s biggest dollar {drops}: "
                     + ", ".join(f"${mv['ticker']} {mv['pct_text']}" for mv in lead_movers) + ".")
            claims.append(claim(["biggest", "top", "most", "led"], [mv["ticker"] for mv in lead_movers], within=[lead[0]],
                                needs=DOLLAR, direction=d, polarity=pol, metric="usd_change", says=f"{lead[0]}'s biggest dollar {drops}, in order: "
                                + ", ".join("$" + mv["ticker"] for mv in lead_movers)))
    if other:
        text += f" {other[0]} {signed_pct(other[1])} went the other way."
        od = "up" if down else "down"
        claims.append(claim(["best" if down else "worst", "led", "top", "biggest", "most"], [other[0]], direction=od,
                            kind="sector", metric="pct_change", says=f"{other[0]} {signed_pct(other[1])} was the {'best' if down else 'worst'} sector {when}"))
    allowed = [*usd_forms(total), *pct_forms(pct), "500", *count_forms(t.get("priced_count") or 0),
               *count_forms(t.get("ticker_count") or 0), f"{js_fixed(share * 100, 1)}%", *date_words(m.session),
               *(x for mv in movers + lead_movers for x in _mover_numbers(mv))]
    if lead:
        allowed += [*usd_forms(lead[2]), *pct_forms(lead[1])]
    if other:
        allowed += pct_forms(other[1])
    word = "drop" if down else "gain"
    phrases = ordinal_phrases([("$" + mv["ticker"], mv["usd_text"]) for mv in movers], "had", f"biggest dollar {word}",
                              f"{US500} {when}", f"The biggest dollar {word}s {US500} {when}")
    if lead:
        lead_usd = (MINUS if lead[2] < 0 else "+") + usd_text(lead[2])
        phrases.append(f"{lead[0]} had the biggest dollar {word} of any sector {when} ({lead_usd}).")
        if rows1d and ((down and rows1d[-1][0] == lead[0]) or (not down and rows1d[0][0] == lead[0])):
            phrases.append(f"{lead[0]} was the {'worst' if down else 'best'} sector {when} ({signed_pct(lead[1])}).")
        if lead_movers:
            phrases += ordinal_phrases([("$" + mv["ticker"], mv["usd_text"]) for mv in lead_movers], "had",
                                       f"biggest dollar {word}", f"in {lead[0]} {when}",
                                       f"{lead[0]}'s biggest dollar {word}s {when}", (2, 3))
    if other:
        phrases.append(f"{other[0]} was the {'best' if down else 'worst'} sector {when} ({signed_pct(other[1])}).")
    top = movers[0] if movers else None
    angles = [f"About {about_usd(total)} {'gone from' if down else 'added to'} the 500 largest US-listed stocks {when}.",
              (f"${top['ticker']} alone {'lost' if down else 'added'} {usd_text(top['usd'])} of market value {when}."
               if top else ""),
              (f"{lead[0]} {(MINUS if lead[2] < 0 else '+') + usd_text(lead[2])}, {other[0]} {signed_pct(other[1])}: "
               f"one day, two directions." if lead and other else "")]
    return [_spec("market_move", f"market_move:{m.session}", session_date=m.session, when=when,
                  tickers=tickers[:4], context_tickers=tickers[4:],
                  totals={"usd_change_sum": total, "usd_text": about_usd(total), "pct_change": pct,
                          "pct_text": signed_pct(pct), "priced": t.get("priced_count"),
                          "total": t.get("ticker_count"), "priced_cap_share": round(share, 4)},
                  movers=movers, lead_sector=({"sector": lead[0], "pct": lead[1], "usd": lead[2],
                                               "movers": lead_movers} if lead else None),
                  counter_sector=({"sector": other[0], "pct": other[1]} if other else None),
                  facts_text=text, allowed_numbers=allowed, angles=[a for a in angles if a], claims=claims,
                  claim_phrases=phrases,
                  headline=headline([mv["ticker"] for mv in movers[:3]], [about_usd(total), *pct_forms(pct)]),
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
        d = "down" if down else "up"
        word = "drop" if down else "gain"
        pol = "worst" if down else "best"
        if pos == 1:
            # by_usd[0] is the largest dollar move either way too ("the biggest dollar move"): no polarity needed then
            claims = [claim(["biggest", "most", "top", "led"], [mv["ticker"]], needs=DOLLAR, direction=d,
                            polarity=None if r is by_usd[0] else pol, metric="usd_change",
                            says=f"${mv['ticker']}: the biggest dollar {word} among the 500 largest US-listed companies {when}"),
                      claim(["biggest", "most", "top"], [mv["ticker"], *(n["ticker"] for n in nxt)], needs=DOLLAR, direction=d,
                            polarity=pol, metric="usd_change", says="the biggest dollar " + word + "s, in order: "
                            + ", ".join("$" + x for x in [mv["ticker"], *(n["ticker"] for n in nxt)]))]
        else:
            claims = [claim(["biggest", "most", "top"], [n["ticker"] for n in nxt], needs=DOLLAR, direction=d, polarity=pol,
                            metric="usd_change", says=f"the biggest dollar {word}s other than ${mv['ticker']}, in order: "
                            + ", ".join("$" + n["ticker"] for n in nxt))]
            allowed += ["100", str(MEGA_TOP)]
        place_of = {norm_ticker(x["symbol"]): i + 1 for i, x in enumerate(same)}
        ranked = sorted([mv, *nxt], key=lambda x: place_of.get(x["ticker"], 999))
        top_run = [x for i, x in enumerate(ranked) if place_of.get(x["ticker"]) == i + 1]   # #1, #2, ... without a gap
        phrases = ordinal_phrases([("$" + x["ticker"], x["usd_text"]) for x in top_run], "had", f"biggest dollar {word}",
                                  f"{US500} {when}", f"The biggest dollar {word}s {US500} {when}", (2, 3))
        if pos and pos > len(top_run):
            phrases.append(f"${mv['ticker']} was #{pos} by dollar {word} {US500} {when} ({mv['usd_text']}).")
        move_p = f"${mv['ticker']} had the biggest dollar move {US500} {when} ({mv['usd_text']})."
        if r is by_usd[0]:
            phrases.append(move_p)
        cap_p = f"${mv['ticker']} was #{rank} by market cap {US500} {when}."
        phrases.append(cap_p)
        if rank <= MEGA_TOP:
            phrases.append(f"${mv['ticker']} is one of the {MEGA_TOP} largest US-listed companies by market cap (#{rank}).")
            allowed += [str(MEGA_TOP)]
        if pos == 1:
            angles[1] = move_p if r is by_usd[0] else phrases[0]
            angles[2] = next((p for p in phrases if ", in order: " in p), phrases[0])
        else:
            angles[1] = cap_p
            angles[2] = (f"${mv['ticker']} was #{pos} by dollar {word} {US500} {when} ({mv['usd_text']})." if pos
                         else angles[0])
        mag = max(abs(mv["usd"]) / MEGA_USD * 1.5, abs(mv["pct"]) / MEGA_PCT * 1.5)
        out.append(_spec("mega_mover", f"mega_mover:{m.session}:{mv['ticker']}", ticker=mv["ticker"],
                         tickers=[mv["ticker"], *(n["ticker"] for n in nxt)], name=mv["name"], session_date=m.session,
                         when=when, mover=mv, rank_by_cap=rank, rank_by_usd=pos, next_movers=nxt, facts_text=text,
                         allowed_numbers=allowed, angles=list(dict.fromkeys(angles)), magnitude=min(3.0, mag), trigger=trig,
                         claims=claims, claim_phrases=phrases,
                         headline=headline([mv["ticker"]], [usd_text(mv["usd"]), *pct_forms(mv["pct"])]),
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


def sector_leader(m: Market, sector: str, h: str, sign: float) -> dict | None:
    """The sector's best % move over h among the priced 500 (an up sector) or its worst (a down sector), with the
    sector's sign: what "led its sector" means (sector_leaders in the item)."""
    key = "pct_change" if h == "1d" else "pct_change_5d"
    rows = [r for r in m.priced() if r.get("sector") == sector and isinstance(r.get(key), (int, float)) and r[key] != 0
            and math.copysign(1, r[key]) == sign]
    if not rows:
        return None
    r = max(rows, key=lambda r: r[key] * sign)
    return {"ticker": norm_ticker(r["symbol"]), "name": r.get("name"), "pct": float(r[key]), "pct_text": signed_pct(float(r[key]))}


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
        movers, leaders = {}, {}
        for name, pct, _ in named:
            mv = _top_cap_mover(m, name, h, math.copysign(1, pct))
            if mv:
                movers[name] = mv
            ld = sector_leader(m, name, h, math.copysign(1, pct))
            if ld:
                leaders[name] = ld
        when = when_words(m.session, target) if win == "day" else week_when(m.session, target)
        short = lambda n: SECTOR_SHORT.get(n, n)  # noqa: E731
        fmt = lambda r: f"{short(r[0])} {signed_pct(r[1], 1)}"  # noqa: E731
        text = (f"{lead_in(when)}: the 500 largest US-listed stocks moved {signed_pct(all500, 1)} ({'5 sessions to' if win == 'week' else 'close of'} "
                f"{date_words(m.session)[2]}). Up: {', '.join(fmt(r) for r in best)}. Down: {', '.join(fmt(r) for r in worst)}. "
                f"Best minus worst: {js_fixed(spread, 1)} points.")
        claims = []
        b0, w0 = best[0], worst[0]
        # "top" / "led" alone read as the best end; on the worst claim they need a loss noun ("led the drop")
        bw = ["best", "top", "led", "most"] + (["biggest"] if b0[1] > 0 else [])
        ww = ["worst", "top", "led", "most"] + (["biggest"] if w0[1] < 0 else [])
        claims.append(claim(bw, [b0[0]], kind="sector", metric="pct_change",
                            direction="up" if b0[1] > 0 else None, says=f"{short(b0[0])} was the best sector {when}"))
        claims.append(claim(ww, [w0[0]], kind="sector", metric="pct_change",
                            direction="down" if w0[1] < 0 else None, says=f"{short(w0[0])} was the worst sector {when}"))
        if len(rows) >= 4:  # the two named on each side are the top 2 / bottom 2 ("among the worst", "second-best")
            claims.append(claim(bw, [r[0] for r in best], kind="sector", metric="pct_change", polarity="best",
                                direction="up" if best[-1][1] > 0 else None,
                                says=f"best 2 sectors {when}, in order: " + ", ".join(short(r[0]) for r in best)))
            claims.append(claim(ww, [r[0] for r in worst], kind="sector", metric="pct_change", polarity="worst",
                                direction="down" if worst[-1][1] < 0 else None,
                                says=f"worst 2 sectors {when}, in order: " + ", ".join(short(r[0]) for r in worst)))
        ups = [(k, v) for k, v in leaders.items() if v["pct"] > 0]
        downs = [(k, v) for k, v in leaders.items() if v["pct"] < 0]
        # one claim per sector: the stock is #1 inside that sector only (the sentence names the sector or "its sector")
        if ups:
            text += " Best stock in each up sector: " + ", ".join(f"${v['ticker']} {v['pct_text']} ({short(k)})" for k, v in ups) + "."
            claims += [claim(["best", "led", "top", "biggest"], [v["ticker"]], within=[k], scope=SECTOR_SCOPE, direction="up",
                             metric="pct_change", says=f"${v['ticker']} was the best stock by % in {short(k)}") for k, v in ups]
        if downs:
            text += " Worst stock in each down sector: " + ", ".join(f"${v['ticker']} {v['pct_text']} ({short(k)})" for k, v in downs) + "."
            claims += [claim(["worst", "led", "top", "biggest"], [v["ticker"]], within=[k], scope=SECTOR_SCOPE, direction="down",
                             metric="pct_change", says=f"${v['ticker']} was the worst stock by % in {short(k)}") for k, v in downs]
        if movers:
            text += " By market value, the biggest names moving with their sector: " + ", ".join(
                f"${v['ticker']} {v['pct_text']} ({short(k)})" for k, v in movers.items()) + "."
            claims += [claim(["biggest", "top"], [v["ticker"]], within=[k], scope=SECTOR_SCOPE, polarity=None,
                             needs=r"market (?:value|cap)", metric="market_cap", direction="up" if v["pct"] > 0 else "down",
                             says=f"by market value, ${v['ticker']} was the biggest {short(k)} name moving with its sector "
                                  f"({v['pct_text']})") for k, v in movers.items()]
        p1 = lambda r: signed_pct(r[1], 1)  # noqa: E731
        phrases = [f"{short(b0[0])} was the best sector {when} ({p1(b0)}).",
                   f"{short(w0[0])} was the worst sector {when} ({p1(w0)})."]
        if len(rows) >= 4:
            phrases += [f"{short(best[1][0])} was the second-best sector {when} ({p1(best[1])}).",
                        f"{short(worst[1][0])} was the second-worst sector {when} ({p1(worst[1])}).",
                        f"The best sectors {when}, in order: " + ", ".join(f"{short(r[0])} ({p1(r)})" for r in best) + ".",
                        f"The worst sectors {when}, in order: " + ", ".join(f"{short(r[0])} ({p1(r)})" for r in worst) + "."]
        for k, v in ups:
            phrases += [f"${v['ticker']} was the best {short(k)} stock {US500} {when} ({v['pct_text']}).",
                        f"${v['ticker']} led {short(k)} {US500} {when} ({v['pct_text']})."]
        for k, v in downs:
            phrases.append(f"${v['ticker']} was the worst {short(k)} stock {US500} {when} ({v['pct_text']}).")
        for k, v in movers.items():
            phrases.append(f"By market value, ${v['ticker']} was the biggest {short(k)} name moving with its sector {when} "
                           f"({v['pct_text']}).")
        allowed = [*pct_forms(all500), "500", *date_words(m.session), js_fixed(spread, 1), *(x for r in named for x in pct_forms(r[1])),
                   *(x for v in [*movers.values(), *leaders.values()] for x in pct_forms(v["pct"]))]
        if win == "week":
            allowed += ["5", *date_words(m.p["horizon_from"]["5d"])]
        tick = list(dict.fromkeys(v["ticker"] for v in movers.values()))[:4]
        ctx = [t for t in dict.fromkeys(v["ticker"] for v in leaders.values()) if t not in tick][:4]
        angles = [f"{fmt(worst[0])}, {fmt(best[0])} {when}.",
                  f"The 500 largest moved {signed_pct(all500, 1)} {when}, but not evenly.",
                  f"{short(best[0][0])} up, {short(worst[0][0])} down: a {js_fixed(spread, 1)}-point gap {when}."]
        out.append(_spec("sector_rotation", f"sector_rotation:{m.session}:{win}", session_date=m.session, window=win,
                         when=when, tickers=tick, context_tickers=ctx, all_500=all500,
                         best=[{"sector": r[0], "pct": r[1]} for r in best],
                         worst=[{"sector": r[0], "pct": r[1]} for r in worst], spread_pp=round(spread, 2),
                         sector_movers=movers, sector_leaders=leaders, facts_text=text, allowed_numbers=allowed,
                         angles=angles, claims=claims, claim_phrases=phrases,
                         # the story is the best and the worst sector: their names lead, the other movers are context
                         headline=headline([movers[k]["ticker"] for k in (b0[0], w0[0]) if k in movers],
                                           [*pct_forms(all500, (1,)), *pct_forms(b0[1], (1,)), *pct_forms(w0[1], (1,))]),
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
    # The breadth card headlines all ~2,500 tracked stocks ("1,631 of 2,497 stocks fell - 65%"). When most of them moved
    # with the market (BROAD_SHARE), the post may not call the day narrow or the typical stock flat (it would contradict
    # its own card); the median / risers of the 500 are then left out of the numbers. Otherwise the narrow reading
    # (the 500's median against the cap-weighted move) is the story, and "broad" is the word it may not use.
    with_mkt = dec if down else adv
    side_share = round(100 * with_mkt / total)
    narrative = "broad" if side_share >= BROAD_SHARE else "narrow"
    drags = sorted((r for r in m.priced() if isinstance(r.get("usd_change"), (int, float)) and (r["usd_change"] < 0) == down),
                   key=lambda r: abs(r["usd_change"]), reverse=True)[:3]
    drags = [_mover(r) for r in drags]
    when = when_words(m.session, target)
    peak = breadth_prev_peak(b)
    n_series = len(b.get("series") or [])
    text = (f"{dec if fell else adv:,} of {total:,} US stocks RapidTradeView tracks {'fell' if fell else 'rose'} {when} "
            f"({share}%); {adv if fell else dec:,} {'rose' if fell else 'fell'} and {unch} were flat.")
    claims = []
    if peak:
        text += f" It came a day after the strongest up day of the last {n_series} closes (+{peak[1]:,} on {date_words(peak[0])[2]})."
        claims.append(claim(["best"], [], bare=True, direction="up", needs=r"\bday\b|close|session", metric="breadth",
                            date=peak[0],
                            says=f"{date_words(peak[0])[2]} was the strongest up day (stocks up minus down) of the last {n_series} closes"))
    if narrative == "narrow":
        text += (f" The 500 largest US-listed stocks moved {signed_pct(pct)} weighted by market value, while the median "
                 f"company moved {signed_pct(med)}: {up500} of {priced} priced rose.")
    else:
        text += f" The 500 largest US-listed stocks moved {signed_pct(pct)} weighted by market value."
    if drags:
        text += f" Biggest dollar {'drags' if down else 'lifts'}: " + ", ".join(f"${d['ticker']} {d['pct_text']}" for d in drags) + "."
        claims.append(claim(["biggest", "top", "most", "led"], [d["ticker"] for d in drags], needs=DOLLAR,
                            direction="down" if down else "up", polarity="worst" if down else "best", metric="usd_change",
                            says="biggest dollar " + ("drags" if down else "lifts") + ", in order: "
                            + ", ".join("$" + d["ticker"] for d in drags)))
    allowed = [*count_forms(adv), *count_forms(dec), *count_forms(unch), *count_forms(total), f"{share}%", str(share),
               *pct_forms(pct), "500", *date_words(m.session), *(x for d in drags for x in _mover_numbers(d))]
    phrases = ordinal_phrases([("$" + d["ticker"], d["usd_text"]) for d in drags], "was",
                              f"biggest dollar {'drag' if down else 'lift'}", f"{US500} {when}",
                              f"The biggest dollar {'drags' if down else 'lifts'} {US500} {when}", (2, 3))
    side_n = dec if fell else adv
    if side_n * 2 > total:
        phrases.append(f"Most US stocks RapidTradeView tracks {'fell' if fell else 'rose'} {when}: {side_n:,} of {total:,} "
                       f"({share}%).")
    if peak:
        day_of = lead_in(when.replace("on ", ""))
        phrases += [f"{date_words(peak[0])[2]} was the strongest up day of the last {n_series} closes "
                    f"(+{peak[1]:,} stocks up minus down).",
                    f"{day_of} came a day after the strongest up day of the last {n_series} closes.",
                    f"{day_of} came a day after the strongest up day of the last {n_series} closes "
                    f"(+{peak[1]:,} on {date_words(peak[0])[2]})."]
    if narrative == "narrow":
        allowed += [*pct_forms(med), *count_forms(up500), *count_forms(priced)]
    if peak:
        allowed += [*count_forms(peak[1]), f"+{peak[1]:,}", f"+{peak[1]}", *date_words(peak[0]), str(n_series)]
    kind = "divergence" if diverge else "lopsided"
    if narrative == "narrow":
        angles = [f"{dec if fell else adv:,} of {total:,} US stocks {'fell' if fell else 'rose'} {when}.",
                  f"The 500 largest moved {signed_pct(pct)}, yet the typical one moved {signed_pct(med)}.",
                  f"How many of the 500 largest rose {when}? {up500} of {priced} priced."]
        card = {"says": f"{dec if fell else adv:,} of {total:,} US stocks {'fell' if fell else 'rose'} ({share}%): a split day",
                "never": r"\b(?:broad(?:-based)?|widespread|across the board|sweeping)\b|\beverything\s+(?:fell|rose|sold)\b"}
    else:
        angles = [f"{with_mkt:,} of {total:,} US stocks {'fell' if down else 'rose'} {when}.",
                  f"{side_share}% of US stocks {'fell' if down else 'rose'} {when}.",
                  (f"{lead_in(when.replace('on ', ''))} came a day after the strongest up day of the last {n_series} closes."
                   if peak else f"The 500 largest moved {signed_pct(pct)} {when}, and most US stocks moved with them.")]
        card = {"says": f"{with_mkt:,} of {total:,} US stocks {'fell' if down else 'rose'} ({side_share}%): a broad move",
                "never": (r"\b(?:narrow\w*|concentrat\w*|typical|median|handful|under the surface)\b"
                          r"|\bfew\s+(?:giants|names|stocks|companies|big)\b|\bonly\s+(?:a\s+few|the\s+giants|the\s+biggest)\b"
                          # r4 review: "The giants did all the damage", "a Big Tech selloff, not a broad one"
                          r"|\bgiants?\b|\bmega[\s-]?caps?\b|\bbig\s+tech\b|\bnot\s+(?:a\s+|that\s+|so\s+)?broad"
                          r"|\ball\s+the\s+damage\b|\baverage\s+(?:stock|company|name)\b|\bheld\s+up\b")}
    mag = min(3.0, max((ratio - 1), abs(pct) / MOVE_TRIGGER * 1.5 if diverge else 0))
    return [_spec("breadth_day", f"breadth_day:{m.session}", session_date=m.session, when=when,
                  tickers=[d["ticker"] for d in drags],
                  breadth={"advancers": adv, "decliners": dec, "unchanged": unch, "total": total, "share_pct": share},
                  median_500=round(med, 4), risers_500=up500, priced_500=priced, cap_weighted_pct=pct, drags=drags,
                  signal=kind, narrative=narrative, card_message=card, facts_text=text, allowed_numbers=allowed,
                  angles=angles, claims=claims, claim_phrases=phrases, magnitude=mag,
                  headline=headline([d["ticker"] for d in drags], [*count_forms(with_mkt), f"{share}%", *pct_forms(pct)]),
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
    tk = lambda r: norm_ticker(r["symbol"])  # noqa: E731
    fmt = lambda r: f"${tk(r)} {signed_pct(r['pct_change_5d'])}"  # noqa: E731
    n = len(bk["rows"])
    when = week_when(m.session, target)
    # "US-listed", not "US": the 10 largest by market value include foreign companies listed here (TSM)
    text = (f"The {n} largest US-listed companies by market value, held in equal amounts, moved {signed_pct(mean)} over the "
            f"5 sessions to {date_words(m.session)[2]}. {len(up)} of {n} rose. Best: {', '.join(fmt(r) for r in best)}. "
            f"Worst: {', '.join(fmt(r) for r in worst)}.")
    if bk["excluded"]:
        text += f" Left out (no 5-session move): {', '.join(bk['excluded'])}."
    bk10 = {"universe": "10", "metric": "pct_change"}  # a sentence names the basket ("of the 10", "10 largest")
    claims = [claim(["best", "top", "most"], [tk(r) for r in best], **bk10,
                    says="best 3 of the 10 by 5-session move, in order: " + ", ".join("$" + tk(r) for r in best)),
              claim(["worst", "top", "most"] + (["biggest"] if worst[-1]["pct_change_5d"] < 0 else []), [tk(r) for r in worst],
                    **bk10, direction="down" if worst[-1]["pct_change_5d"] < 0 else None,
                    says="worst 3 of the 10 by 5-session move, in order: " + ", ".join("$" + tk(r) for r in worst)),
              claim(["best", "led", "top", "most"], [tk(best[0])], **bk10, direction="up" if best[0]["pct_change_5d"] > 0 else None,
                    says=f"${tk(best[0])} was the best of the 10"),
              claim(["worst", "biggest", "most"], [tk(worst[0])], **bk10, direction="down" if worst[0]["pct_change_5d"] < 0 else None,
                    says=f"${tk(worst[0])} was the worst of the 10")]
    angles = [f"Owning the {n} largest US-listed companies equally {'cost' if mean < 0 else 'made'} {js_fixed(abs(mean), 2)}% {when}.",
              f"{len(up)} of the {n} largest US-listed companies rose {when}.",
              f"What did a mega-cap portfolio do {when}? {signed_pct(mean)}, equal-weighted."]
    if len(up) == 1:
        # a claim with subjects is never bare (HQ review r4): "Only Microsoft rose" names its subject; "Only one of the
        # 10 rose" is the count, a claim of its own
        claims.append(claim(["only"], [tk(up[0])], direction="up", universe="10", says=f"only ${tk(up[0])} of the {n} rose"))
        claims.append(claim(["only"], [], bare=True, direction="up", universe="10", says=f"only one of the {n} rose"))
        angles[1] = f"Only 1 of the {n} largest US-listed companies rose {when}: ${tk(up[0])}."
    elif len(up) == n - 1:
        dn = next(r for r in rows if r["pct_change_5d"] <= 0)
        claims.append(claim(["only"], [tk(dn)], direction="down", universe="10", says=f"only ${tk(dn)} of the {n} fell"))
        claims.append(claim(["only"], [], bare=True, direction="down", universe="10", says=f"only one of the {n} fell"))
    b10 = f"the {n} largest US-listed companies"
    pc = lambda r: signed_pct(r["pct_change_5d"])  # noqa: E731
    phrases = (ordinal_phrases([("$" + tk(r), pc(r)) for r in best], "was", "best", f"of {b10} {when}",
                               f"The best of {b10} {when}", (2, 3))
               + ordinal_phrases([("$" + tk(r), pc(r)) for r in worst], "was", "worst", f"of {b10} {when}",
                                 f"The worst of {b10} {when}", (2, 3)))
    if len(up) == 1:
        phrases += [f"Only ${tk(up[0])} of {b10} rose {when} ({pc(up[0])}).", f"Only 1 of {b10} rose {when}."]
        angles[1] = f"Only ${tk(up[0])} of {b10} rose {when} ({pc(up[0])})."
    elif len(up) == n - 1:
        dn = next(r for r in rows if r["pct_change_5d"] <= 0)
        phrases += [f"Only ${tk(dn)} of {b10} fell {when} ({pc(dn)}).", f"Only 1 of {b10} fell {when}."]
    named = list(dict.fromkeys(tk(r) for r in (worst + best)))
    allowed = [*pct_forms(mean), str(n), *count_forms(len(up)), "5", *date_words(m.session), *date_words(m.p["horizon_from"]["5d"]),
               *(x for r in rows for x in pct_forms(r["pct_change_5d"]))]
    return [_spec("basket_week", f"basket_week:{m.session}", session_date=m.session, when=when, tickers=named[:4],
                  context_tickers=named[4:],
                  basket=[{"ticker": tk(r), "pct_5d": r["pct_change_5d"]} for r in rows],
                  excluded=bk["excluded"], mean_5d=round(mean, 4), risers=len(up), facts_text=text, allowed_numbers=allowed,
                  angles=angles, claims=claims, claim_phrases=phrases,
                  headline=headline([tk(best[0]), tk(worst[0]), tk(worst[1])], pct_forms(mean)),
                  magnitude=min(3.0, abs(mean) / BASKET_MIN * 1.5),
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
    allowed = [*(f for v in nums if isinstance(v, int) for f in count_forms(v)), "500", *date_words(win["from"]), *date_words(win["to"]),
               *date_words(c.get("last_disclosure") or win["to"])]
    if tot.get("buys") and tot.get("sells"):
        r = max(tot["buys"], tot["sells"]) / min(tot["buys"], tot["sells"])
        allowed += [js_fixed(r, 1)]
    angles = [f"{lead['members']} members of Congress traded ${lt} in the last {win.get('days')} days.",
              f"${lt}: the most-traded 500-largest stock in Congress over {win.get('days')} days, {lead['buys']} buys vs {lead['sells']} sells.",
              f"Congress disclosed {tot.get('sells')} sells and {tot.get('buys')} buys in {win.get('days')} days. Most-traded 500-largest name: ${lt}."]
    phrases = [f"${lt} was the most-traded of the 500 largest US-listed stocks in Congress over {win.get('days')} days "
               f"({lead['trades']} trades)."]
    angles[1] = phrases[0]
    angles[2] = f"Congress disclosed {tot.get('sells')} sells and {tot.get('buys')} buys over {win.get('days')} days. {phrases[0]}"
    claims = [claim(["most", "top", "led", "biggest"], [lt], needs=r"trad", metric="trades",
                    says=f"${lt} was the most-traded 500-largest stock in Congress over {win.get('days')} days (by trades)")]
    return [_spec("congress_flow", f"congress_flow:{c.get('last_disclosure')}:{lt}", ticker=lt,
                  tickers=[lt, *(norm_ticker(x["ticker"]) for x in others)], name=lead.get("name"),
                  window=win, totals=tot, leader=lead, others=others, facts_text=text, allowed_numbers=allowed, angles=angles,
                  claims=claims, claim_phrases=phrases, headline=headline([lt]),
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
    # Scope (review 10-18): the totals are open-market buys and sells by officers and directors (Form 4) in our feed,
    # not every insider transaction in the market.
    text = (f"Officers and directors reported {usd_text(bought)} of open-market buys and {usd_text(sold)} of open-market sells "
            f"over {win.get('days')} days in our feed (Form 4 filings, filed {date_words(win['from'])[2]} to {date_words(last)[2]}; "
            f"{i.get('company_count')} companies with buys, {sells.get('company_count')} with sells).")
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
        allowed += [js_fixed(sold / bought, 1), "$1"]
    lt = named[0]
    days = win.get("days")
    angles = [f"Officers and directors sold {usd_text(sold)} and bought {usd_text(bought)} of their own companies' stock on "
              f"the open market over {days} days in our feed.",
              f"${lt} insiders: {usd_text((lead_s or lead_b)[0]['total_usd'])} {'sold' if lead_s else 'bought'} in {days} days.",
              (f"For every $1 officers and directors bought on the open market, they sold ${js_fixed(sold / bought, 1)}. "
               f"{'Top seller' if lead_s else 'Top buyer'} among the 500 largest: ${lt}." if bought else "")]
    feed = f"{US500} over {days} days in our feed"
    phrases = []
    if lead_s:
        phrases += ordinal_phrases([("$" + norm_ticker(x["ticker"]), usd_text(x["total_usd"])) for x in lead_s], "had",
                                   "largest open-market sells by officers and directors", feed,
                                   f"The largest open-market sellers {feed}", (2, 3))
    if lead_b:
        phrases += ordinal_phrases([("$" + norm_ticker(x["ticker"]), usd_text(x["total_usd"])) for x in lead_b], "had",
                                   "largest open-market buys by officers and directors", feed,
                                   f"The largest open-market buyers {feed}", (2,))
    if bought:
        ratio_p = (f"For every $1 officers and directors bought on the open market over {days} days in our feed, they sold "
                   f"${js_fixed(sold / bought, 1)}.")
        phrases.append(ratio_p)
        angles[2] = f"{ratio_p} {phrases[0]}" if (lead_s or lead_b) else ratio_p
    claims = []
    if lead_s:
        claims.append(claim(["biggest", "top", "most", "led"], [norm_ticker(x["ticker"]) for x in lead_s], needs=r"sell|sold",
                            metric="usd_flow",
                            says="largest open-market sellers among the 500 largest, in order: "
                            + ", ".join("$" + norm_ticker(x["ticker"]) for x in lead_s)))
    if lead_b:
        claims.append(claim(["biggest", "top", "most", "led"], [norm_ticker(x["ticker"]) for x in lead_b], needs=r"buy|bought",
                            metric="usd_flow",
                            says="largest open-market buyers among the 500 largest, in order: "
                            + ", ".join("$" + norm_ticker(x["ticker"]) for x in lead_b)))
    scoped = [{"numbers": [*usd_forms(bought), *usd_forms(sold)],
               "require": [r"officers?\s+and\s+directors?", r"open[-\s]market"],
               "say": (f"the 30-day totals ({usd_text(bought)} bought, {usd_text(sold)} sold) are open-market buys / sells by "
                       "officers and directors over 30 days in our feed: say \"open-market\" and \"officers and directors\"")}]
    return [_spec("insider_flow", f"insider_flow:{last}:{lt}", ticker=lt, tickers=list(dict.fromkeys(named))[:4],
                  claims=claims, claim_phrases=phrases, scoped_numbers=scoped,
                  headline=headline([norm_ticker(x["ticker"]) for x in (lead_s or lead_b)[:3]], [usd_text(sold), usd_text(bought)]),
                  window=win, bought_usd=bought, sold_usd=sold, buy_companies=i.get("company_count"),
                  sell_companies=sells.get("company_count"), top_sellers_500=lead_s, top_buyers_500=lead_b,
                  facts_text=text, allowed_numbers=allowed, angles=[a for a in angles if a],
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
    cap_day = dt.date.fromisoformat((bz.get("trade_date") or target.isoformat())[:10])
    if day == "weekend":
        span = "this weekend" if target.weekday() >= 5 and (target - cap_day).days <= 1 else "over the weekend"
    else:
        span = "today" if cap_day == target else f"on {cap_day.strftime('%A')}"
    first = norm_ticker(rows[0]["ticker"])
    # the move of the most-mentioned stocks (a sentence about them that names none may not say they rose if they fell)
    buzz_dir = (None if not moved else "down" if fell == len(moved) else "up" if fell == 0 else "mixed")
    claims = [claim(["most", "top", "led", "biggest"], [lt], needs=r"unusual|usual|normal|average|more than|\d\s*[x\u00d7]",
                    metric="mention_ratio",
                    says=f"${lt} had the highest mentions-vs-usual ratio of the top {len(rows)} Reddit stocks (20+ mentions, usual 5+)"),
              claim(["most", "top", "led"], [first], needs=r"mention|talked|discussed", metric="mentions",
                    says=f"${first} had the most Reddit mentions of the stocks on the buzz card (ETFs are not ranked there)"),
              claim(["most", "top"], [], bare=True, needs=r"mention|talked|discussed", metric="mentions", direction=buzz_dir,
                    says=f"the {len(rows)} most-mentioned stocks on Reddit (the buzz card's rows)")]
    talk = (f"Reddit is talking about ${lt} {ratio_text(lr)}{TIMES} more than usual: {lead['mentions']} mentions vs "
            f"{avg_txt[1 if lead['mentions_avg'] < 9.95 else 0]}.")
    phrases = [talk, f"${lt} had the highest mentions-vs-usual ratio of the top {len(rows)} stocks on Reddit "
                     f"({ratio_text(lr)}{TIMES} usual)."]
    phrases.append(f"${first} had the most Reddit mentions of the stocks on the buzz card"
                   + (f" ({lead['mentions']})." if first == lt else "."))
    if moved:
        phrases.append(f"{fell} of the {len(moved)} most-mentioned stocks with a close for {date_words(session)[2]} fell "
                       "that day." if fell * 2 >= len(moved) else
                       f"{len(moved) - fell} of the {len(moved)} most-mentioned stocks with a close for "
                       f"{date_words(session)[2]} rose that day.")
    angles = [talk,
              phrases[1],
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
                  claims=claims, claim_phrases=phrases, headline=headline([lt], [ratio_forms(lr)[0]]),
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
    # the real window for the build date: "this week" on its Monday, "the week of Oct 19" on the Sunday before
    when = "this week" if target == monday else f"in the week of {date_words(monday.isoformat())[2]}"
    angles = [f"{len(uniq)} big names report {when}. The biggest: ${t0['ticker']} on {dt.date.fromisoformat(t0['date']).strftime('%A')}.",
              f"${show[0]['ticker']}, ${show[1]['ticker']} and ${show[2]['ticker']} all report {when}.",
              f"Which report are you watching {when}: ${show[0]['ticker']} or ${show[1]['ticker']}?"]
    phrases = ordinal_phrases([("$" + r["ticker"], "by market value, confirmed dates") for r in show], "is",
                              "largest company reporting earnings", when)
    for k in (3, 4):
        if len(show) >= k:
            phrases.append(f"The largest companies reporting earnings {when} (by market value, confirmed dates), in order: "
                           + ", ".join("$" + r["ticker"] for r in show[:k]) + ".")
    angles[0] = phrases[0]
    angles[1] = f"${show[0]['ticker']}, ${show[1]['ticker']} and ${show[2]['ticker']} report {when}."
    claims = [claim(["biggest", "top", "led", "most"], [r["ticker"] for r in show], metric="market_cap",
                    says="largest by market value among the confirmed $10B+ reporters, in order: " + ", ".join("$" + r["ticker"] for r in show))]
    return [_spec("earnings_week_preview", f"earnings_week_preview:{monday.isoformat()}", tickers=[r["ticker"] for r in show[:4]],
                  context_tickers=[r["ticker"] for r in show[4:]], when=when, claims=claims, claim_phrases=phrases,
                  headline=headline([r["ticker"] for r in show[:3]]),
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
                             headline=headline([sym], pct_forms(mv)),
                             magnitude=min(3.0, abs(mv) / REACTION_MIN_MOVE * 1.5),
                             trigger=f"|next-session move| {js_fixed(abs(mv), 2)}% >= {REACTION_MIN_MOVE}%",
                             path=f"/dashboard/{sym}"))
    return out, (None if out else f"no $10B+ 500-largest reporter moved {REACTION_MIN_MOVE}%+ in its report session {m.session}")
