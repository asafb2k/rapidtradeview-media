"""VIRAL CHECK v1: every post and every action carries the reach ingredients our data measured (owner 2026-10-23:
"verify each and every post/action have the potential to go viral").

Spec: D:/rtv-ops/tracks/growth/strategy/pillars-2026-10-18/VIRAL-CHECK.md (Growth; Grok kit directive #668). Evidence:
eda2 (23,006 finance-X posts, within author) and G3 (4,767 posts, 593 authors). The check cannot promise virality (who
posts explains ~92% of view variance); it makes sure a post has every ingredient the data links to reach and none of the
measured penalties. Standard library + tools/draft_lint.py only, so tools/grok_review.py (the draft gate) and Growth's
post_audit.py (live posts) share one rule set.

  score(text, item, platform, kind, facts=None, prev_own_post_at=None, now=None, media=None, *, reply_text=None,
        post_at=None, target_followers=None, target_posted_at=None) -> dict

kind is "post", "reel" or "comment". `now` is the review time; `post_at` the time the post goes (or went) out when it is
known (a draft's planned_at, a live post's posted_at). Without post_at the review time is a lower bound of the post time:
a rule it already decides (a gap already >= 60 min, a release already > 3 h old, an item of an earlier day) is decided,
anything else stays unknown.

A. Must-haves (post / Reel; one that fails is a REJECT in grok_review.py when it is checkable):
  M1  >= 1 $cashtag in the main text
  M2  >= 1 number (draft_lint.figures: cashtags, filing names and Q3 / FY labels are not numbers)
  M3  a company is named (a cashtag that is not an index / ETF, or the item's company name): not macro / market only
  M4  25-60 words in the main text: X and Threads only (Instagram captions: n/a)
  M5  no link in the main text: an http(s) URL, or a bare domain X / Threads would auto-link (a domain that is part of
      the item's own company name is not one). Instagram: the official source link grok_review requires on a Congress /
      Form 4 / ptr_summary caption is exempt (compliance wins)
  M6  >= 60 min after our previous own post on the platform (prev_own_post_at; unknown without it)
  M7  own image or video attached (media; None = not known)
  M8  fresh: a session price move (market_move, mega_mover, sector_rotation, breadth_day, basket_week,
      earnings_reaction) on its session's own New York day (a week item also on the weekend after it); a Reddit capture
      on its capture day with no line about an older price session; an earnings result on its release day, within 3 h
      of the release for a top-50 name; a filing on the day it is filed (an older filing in today's facts: unknown, the
      facts carry no first-seen time); picks / pattern / any other item on its own facts day (owner 10-22, #652)
B. Boosters (a post needs >= 2; fewer is a note, never a REJECT):
  B1  native video (a Reel, an .mp4 / video media, kind "reel")
  B2  3 or more distinct cashtags
  B3  a broad lead (the first cashtag) plus 1 non-broad name
  B4  fast: <= 3 h after the earnings release (published_at), after the session close (16:00 New York) for a recap;
      a filing has no time in the facts (date only): unknown
  B5  a retail-attention ticker: in the same facts file's reddit_buzz data at >= 2x its usual count (the top-20
      mentions list is not in the facts)
  B6  a surprise number in line 1: a beat / miss with a figure, a >= 5% move, a >= $100B value change, a record
C. Penalties (any one: rewrite):
  P1  a single broad company cashtag plus a % figure and no other name (not earnings)
  P2  broad-only cashtags on a non-earnings post
  P3  an @mention in our own post (text or self-reply)
  P4  a market recap (market_move, sector_rotation, breadth_day, basket_week) with no company cashtag
D. Comments / replies (kind "comment"): must = M1, M2, M5 plus
  D1  under an account with >= 50k followers, <= 30 min after its post (target_followers / target_posted_at from the
      draft; unknown without them: the text cannot show it)
  D2  on a facts item we hold: the comment's cashtag is one of the item's (no item: fails)
  D3  no typed @mention (the platform adds the reply-to handle itself)
  Boosters are scored; the penalties are post rules (section D replaces C). Repeats and the daily count are
  grok_review's comment state.

Every rule is {ok: True | False | None, why}; None = the data is not there (never guessed). passed = every must True and
no penalty; strong = passed and >= 2 boosters; fails = the must-haves that are False plus the penalties (what
grok_review REJECTs); summary "M8/8 B2 P0" (+ " ?M6" naming unknown rules; n/a rules count as passed, as Grok logs
viral=M<passed>/8).

Broad (B3, P1, P2) = a top-100 US company by market cap, or an index ETF (SPY, QQQ, DIA, IWM). Decided by, in order:
a foreign company listed in the US (G3's ADR tier: never broad); the facts' own cap rank (rank_by_cap); a cap compared
with a ranked company of the same facts file (a company worth at least #36's cap is top-36; one worth at most #140's
is not top-100); not among the 500 largest (in_500 false); then G3's static TOP100 list (G3-evidence.md, written before
any estimate: the list the -18% broad penalty was measured on). Top-50 (M8 earnings) uses the facts only (US-listed
rank), else unknown.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import draft_lint as dl  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 - no tz database: New York dates read as UTC dates (as select_stories does)
    NY = None

VERSION = "viral-check v1 (2026-10-23)"
KINDS = ("post", "reel", "comment")
POST_RULES = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")
COMMENT_RULES = ("M1", "M2", "M5", "D1", "D2", "D3")
BOOSTERS = ("B1", "B2", "B3", "B4", "B5", "B6")
PENALTIES = ("P1", "P2", "P3", "P4")

WORDS_MIN, WORDS_MAX = 25, 60
WORD_PLATFORMS = ("x", "threads")
SPACING = dt.timedelta(minutes=60)
FAST = dt.timedelta(hours=3)
TARGET_FOLLOWERS = 50_000
TARGET_WINDOW = dt.timedelta(minutes=30)
BOOSTERS_MIN = 2
BUZZ_RATIO = 2.0
BIG_MOVE_PCT = 5.0
BIG_USD = 100e9
TOP_BROAD = 100
TOP_EARNINGS = 50
CLOSE_HOUR = 16  # New York

INDEX_BROAD = frozenset({"SPY", "QQQ", "DIA", "IWM"})
# Not a company (M3, P4): index / sector / leveraged ETFs and index symbols (draft_lint's list, the EDA's).
NOT_COMPANY = frozenset(dl.INDEX_ETF) | INDEX_BROAD
# G3-evidence.md "Ticker tiers": TOP100 (~100 largest US-listed US companies, 106 symbols, share classes merged).
G3_TOP100 = frozenset("""
AAPL ABBV ABT ACN ADBE ADI ADP AMAT AMD AMGN AMZN ANET APH APP AVGO AXP BA BAC BKNG BLK BRK.A BRK.B BSX BX C CAT CEG
CMCSA COF COIN COST CRM CRWD CSCO CVX DE DHR DIS ETN GE GEV GILD GOOG GOOGL GS HD HON HOOD IBM INTC INTU ISRG JNJ JPM
KKR KLAC KO LIN LLY LMT LOW LRCX MA MCD MDT META MO MRK MS MSFT MU NEE NFLX NKE NOW NVDA ORCL PANW PEP PFE PG PGR PLTR
PM QCOM RTX SBUX SCHW SPCX SPGI SYK T TJX TMO TMUS TSLA TXN UBER UNH UNP V VRTX VZ WFC WMT XOM
""".split())
# Foreign companies listed in the US (the RTV universe's international_adr list, backend/config/tickers.yaml, as G3 read
# it): G3 counts them as large caps, never broad, whatever their US-listed cap rank (TSM, ASML, NVO...).
ADR = frozenset("""
BABA TSM ASML SAP NVO TM SONY SHOP SE MELI NU GRAB ABNB UL DEO BUD BTI GSK AZN NVS SNY RY TD BNS BMO CM SU CNQ ENB TRP CP
CNI WCN BAM BN INFY WIT HDB IBN KB SHG MFG SMFG NMR LYG BCS DB UBS ING HSBC BP SHEL MUFG BHP RIO VALE PBR TTE LVMUY NSRGY
RHHBY TCEHY SFTBY CMWAY CFRUY HESAY SIEGY LRLCY SAN BBVA MBGYY VWAGY CRH FLUT RELX NGLOY GLNCY BASFY BAYRY AXAHY NTDOY HMC
PKX ASX UMC STLA RACE LRE TOT
""".split())

EARNINGS_TYPES = ("earnings_result", "earnings_reaction", "earnings_upcoming", "earnings_tomorrow_roundup",
                  "earnings_week_preview")
SESSION_TYPES = ("market_move", "mega_mover", "sector_rotation", "breadth_day", "basket_week", "earnings_reaction")
RECAP_TYPES = ("market_move", "sector_rotation", "breadth_day", "basket_week")
FILING_TYPES = ("congress_trade", "form4_buy", "ptr_summary")
# Items whose `name` is a person, not the company (M3 reads `company` there).
PERSON_TYPES = FILING_TYPES

URL = dl.URL
BARE_DOMAIN = re.compile(r"(?<![\w@.$-])(?:[a-z0-9-]+\.)+[a-z]{2,24}(?![\w-])(?:/\S*)?", re.IGNORECASE)
MENTION = re.compile(r"(?<![\w@.])@([A-Za-z0-9_.]{1,30})")
VIDEO_EXT = re.compile(r"\.(?:mp4|mov|m4v|webm)(?:[?#].*)?$", re.IGNORECASE)
VIDEO_KINDS = ("video", "reel", "animated_gif", "gif_video")
POSTED_AT = re.compile(r"\bposted_at\s*[=:]\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)")
PCT = re.compile(r"(?<![\w.])([+\-\u2212]?)(\d+(?:[.,]\d+)?)\s?%")
USD = re.compile(r"(?<![\w])([+\-\u2212]?)\$(\d[\d,]*(?:\.\d+)?)\s?([KMBT])\b")
MOVE_WORDS = re.compile(
    r"\b(?:gain(?:ed|s|ing)?|lost|los(?:es|ing)|add(?:ed|s|ing)?|erase[ds]?|wiped|shed|swung|swing|r[io]se|rising"
    r"|fell|fall(?:s|ing)?|drop(?:ped|s)?|jump(?:ed|s)?|climb(?:ed|s)?|slid|slump(?:ed|s)?|sank|surg(?:ed|es)|soar(?:ed|s)?"
    r"|tumbl(?:ed|es)|rall(?:ied|ies)|mov(?:ed|es)|plung(?:ed|es)|spik(?:ed|es)|up|down)\b", re.IGNORECASE)
BEAT_MISS = re.compile(r"\b(?:beat|beats|topped|tops|missed|misses|miss|exceeded|surpassed|fell\s+short)\b", re.IGNORECASE)
RECORD = re.compile(r"\b(?:record|all[-\s]time\s+high)\b", re.IGNORECASE)
NAME_SUFFIX = re.compile(r"[,.]?\s+(?:Inc|Incorporated|Corp|Corporation|Company|Co|Holdings?|Group|Ltd|Limited|plc|PLC|N\.V|"
                         r"NV|S\.A|SA|AG|SE|LLC|L\.P|LP|Trust|Oyj|ASA|Class\s+[A-C])\.?$")


# ---------------------------------------------------------------------------
# Small helpers

def _rule(ok, why: str, na: bool = False) -> dict:
    out = {"ok": ok, "why": why}
    if na:
        out["na"] = True
    return out


def as_time(v) -> dt.datetime | None:
    """An aware UTC datetime from a datetime or an ISO string (draft_lint.parse_time); None otherwise."""
    if isinstance(v, dt.datetime):
        return (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)
    return dl.parse_time(v) if isinstance(v, str) else None


_t = as_time


def _d(v) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def ny_day(t: dt.datetime) -> dt.date:
    return (t.astimezone(NY) if NY else t.astimezone(dt.timezone.utc)).date()


def close_at(day: dt.date) -> dt.datetime | None:
    """The regular close (16:00 New York) of a session day, in UTC; None without a tz database."""
    if NY is None:
        return None
    return dt.datetime(day.year, day.month, day.day, CLOSE_HOUR, tzinfo=NY).astimezone(dt.timezone.utc)


def norm_ticker(t) -> str:
    s = str(t or "").strip().upper().lstrip("$")
    if "-" in s:
        head, tail = s.rsplit("-", 1)
        if 1 <= len(tail) <= 2 and tail.isalpha():
            s = f"{head}.{tail}"
    return s


def item_cashtags(item: dict | None) -> list[str]:
    """tickers + ticker + context_tickers (grok_review.item_cashtags)."""
    if not item:
        return []
    base = [*(item.get("tickers") or []), *([item["ticker"]] if item.get("ticker") else []), *(item.get("context_tickers") or [])]
    return list(dict.fromkeys(norm_ticker(t) for t in base if t))


def _hm(td: dt.timedelta) -> str:
    m = int(td.total_seconds() // 60)
    return f"{m} min" if abs(m) < 120 else f"{m / 60:.1f} h"


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and re.fullmatch(r"\s*\d[\d,]*(?:\.\d+)?\s*", v):
        return float(v.replace(",", ""))
    return None


def posted_time(record: dict) -> dt.datetime | None:
    """When an own post went out: posted_at= in its post_log body / text, else (a draft approved, not logged yet) its
    planned_at, else the post_log row's created_at (a pending approval without planned_at: None, its post time is not
    known)."""
    for key in ("body", "text"):
        m = POSTED_AT.search(str(record.get(key) or ""))
        if m:
            t = _t(m.group(1))
            if t:
                return t
    if record.get("pending"):
        return _t(record.get("planned_at"))
    return _t(record.get("posted_at")) or _t(record.get("created_at"))


def prev_own_post_at(history: list[dict] | None, platform: str | None, before: dt.datetime | None) -> dt.datetime | None:
    """The newest own post time on `platform` strictly before `before` (post_history records, or any dicts with
    platform + posted_at / created_at); None when there is none or no history."""
    if not history or before is None:
        return None
    times = [t for p in history if str(p.get("platform") or "").lower() == str(platform or "").lower()
             for t in [posted_time(p)] if t is not None and t < before]
    return max(times) if times else None


# ---------------------------------------------------------------------------
# Market cap ranks (broad = top-100 US company or index ETF)

def _walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


class Caps:
    """Cap ranks a facts file knows: rank_by_cap, map caps (an item's market_cap_usd from the market map, every mover row
    with a cap) and in_500. top(t, n) -> (True | False | None, why)."""

    def __init__(self, item: dict | None, facts: dict | None):
        items = [i for i in (facts or {}).get("items") or [] if isinstance(i, dict)]
        if isinstance(item, dict) and item not in items:
            items.append(item)
        self.rank: dict[str, int] = {}
        self.cap: dict[str, float] = {}
        self.not500: set[str] = set()
        for it in items:
            t = norm_ticker(it.get("ticker"))
            if t:
                if isinstance(it.get("rank_by_cap"), int) and not isinstance(it.get("rank_by_cap"), bool):
                    self.rank[t] = it["rank_by_cap"]
                if it.get("in_500") is False:
                    self.not500.add(t)
                cap = _num(it.get("market_cap_usd"))
                if cap and it.get("market_cap_source") == "market_map":
                    self.cap[t] = cap
            for d in _walk({k: v for k, v in it.items() if k not in ("phrasings", "claims")}):
                c = _num(d.get("cap"))
                if isinstance(d.get("ticker"), str) and c:
                    self.cap.setdefault(norm_ticker(d["ticker"]), c)
        self.anchors = sorted((r, self.cap[t], t) for t, r in self.rank.items() if t in self.cap)

    def top(self, ticker: str, n: int, static: bool = True) -> tuple[bool | None, str]:
        t = norm_ticker(ticker)
        if not t:
            return None, "no ticker"
        if n >= TOP_BROAD and t in INDEX_BROAD:
            return True, f"${t} is an index ETF"
        if n >= TOP_BROAD and static and t in ADR:
            return False, f"${t} is a foreign company listed in the US (G3: a large cap, not broad)"
        if t in self.rank:
            r = self.rank[t]
            return r <= n, f"${t} is #{r} by cap (facts)"
        if t in self.not500:
            return False, f"${t} is not among the 500 largest (facts in_500)"
        cap = self.cap.get(t)
        if cap:
            for r, c, a in self.anchors:
                if r <= n and cap >= c:
                    return True, f"${t} is worth at least ${a} (#{r} by cap, facts)"
            for r, c, a in reversed(self.anchors):
                if r > n and cap <= c:
                    return False, f"${t} is worth at most ${a} (#{r} by cap, facts)"
        if static and n == TOP_BROAD:
            return (t in G3_TOP100), f"${t} {'is' if t in G3_TOP100 else 'is not'} on G3's TOP100 list (no cap rank in the facts)"
        return None, f"no cap rank for ${t} in the facts"


# ---------------------------------------------------------------------------
# Text facts

def cashtags(text: str) -> list[str]:
    return [norm_ticker(t) for t in dl.cashtags(text or "")]


def links(text: str, item: dict | None) -> list[str]:
    """URLs and auto-linked bare domains in a text (a domain inside the item's own company wording is not a link)."""
    s = text or ""
    found = [u.rstrip(".,;:!?)]}\"'") for u in URL.findall(s)]
    rest = URL.sub(" ", s)
    own = " ".join(str(x) for x in [(item or {}).get("name"), (item or {}).get("company"),
                                    *(((item or {}).get("ticker_names") or {}).values())] if x).lower()
    for m in BARE_DOMAIN.finditer(rest):
        b = m.group(0).rstrip(".,;:!?)]}\"'")
        if b.split("/", 1)[0].lower() in own:
            continue
        found.append(b)
    return found


def company_names(item: dict | None) -> list[str]:
    """Short company names an item stands for ("The Procter & Gamble Company" -> "Procter & Gamble")."""
    if not item:
        return []
    raw = [item.get("company"), *((item.get("ticker_names") or {}).values()), *((item.get("names") or {}).values()),
           *((p or {}).get("name") for p in item.get("peers") or [] if isinstance(p, dict))]
    if item.get("type") not in PERSON_TYPES:
        raw.append(item.get("name"))
    out = []
    for n in raw:
        if not isinstance(n, str) or not n.strip():
            continue
        s = n.strip()
        for _ in range(3):
            s = NAME_SUFFIX.sub("", s).strip(" ,.")
        s = re.sub(r"^The\s+", "", s)
        if len(s) >= 3:
            out.append(s)
    return list(dict.fromkeys(out))


def media_kind(media, item: dict | None, kind: str) -> tuple[bool | None, bool | None, str]:
    """(attached, video, why) for a media value: None (not known), "" / [] (none), a URL / "grok_generated", a
    {"url", "kind"} dict or a list of them."""
    if kind == "reel":
        return True, True, "a Reel"
    if media is None:
        return None, None, "media not known"
    entries = media if isinstance(media, list) else [media]
    entries = [e for e in entries if e not in (None, "", {})]
    if not entries:
        return False, False, "no image or video"
    ours = {m.get("url"): str(m.get("kind") or "").lower() for m in (item or {}).get("media") or [] if isinstance(m, dict)}
    video, what = False, []
    for e in entries:
        url = e.get("url") if isinstance(e, dict) else e
        k = str(e.get("kind") or e.get("type") or "").lower() if isinstance(e, dict) else ""
        url = str(url or "")
        if k in VIDEO_KINDS or VIDEO_EXT.search(url) or ours.get(url) in VIDEO_KINDS:
            video = True
            what.append("video")
        else:
            what.append("image" if url != "grok_generated" else "Grok-made image")
    return True, video, ", ".join(dict.fromkeys(what))


def first_line(text: str) -> str:
    return dl.first_line(URL.sub(" ", text or ""))


def _moves_numbers(item: dict | None) -> set[str]:
    nums = ((item or {}).get("moves") or {}).get("numbers") or {}
    return {str(k).replace("\u2212", "").lstrip("+-") for k in nums} if isinstance(nums, dict) else set()


def surprise(line: str, item: dict | None) -> tuple[bool, str]:
    """B6 on the first line: a beat / miss with a figure, a >= 5% move, a >= $100B value change, a record."""
    if not line.strip():
        return False, "empty first line"
    moves = _moves_numbers(item)
    moving = bool(MOVE_WORDS.search(line))
    figs = dl.figures(line)
    if BEAT_MISS.search(line) and figs:
        return True, f"beat / miss with a figure in line 1 ({dl.short(BEAT_MISS.search(line).group(0), 12)})"
    if RECORD.search(line):
        return True, "a record in line 1"
    for m in PCT.finditer(line):
        v = float(m.group(2).replace(",", "."))
        tok = f"{m.group(2)}%"
        if v >= BIG_MOVE_PCT and (m.group(1) or moving or tok in moves):
            return True, f"a {m.group(1)}{tok} move in line 1"
    for m in USD.finditer(line):
        v = float(m.group(2).replace(",", "")) * {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(3)]
        tok = f"${m.group(2)}{m.group(3)}"
        if v >= BIG_USD and (m.group(1) or moving or tok in moves):
            return True, f"a {m.group(1)}{tok} value change in line 1"
    return False, ("no figure in line 1" if not figs else
                   "line 1 has no beat / miss size, >= 5% move, >= $100B value change or record")


# ---------------------------------------------------------------------------
# Rules

def _m8(item: dict | None, text: str, t_post: dt.datetime, exact: bool, caps: Caps) -> dict:
    if not item:
        return _rule(None, "no facts item: freshness cannot be dated")
    kind = item.get("type")
    day = ny_day(t_post)
    at = "" if exact else " (review day: no planned_at)"
    if kind in SESSION_TYPES:
        s = _d(item.get("session_date"))
        if s is None:
            return _rule(None, f"{kind} without a session_date")
        if day == s:
            return _rule(True, f"the {s} session, posted that day{at}")
        weekly = kind == "basket_week" or (kind == "sector_rotation" and item.get("window") == "week")
        if weekly and day > s and day.weekday() >= 5 and (day - s).days <= 2:
            return _rule(True, f"a week item of the {s} session on the weekend after it")
        return _rule(False, f"a price move of the {s} session posted on {day}: same session day only, after the close "
                            "(owner 10-22)")
    if kind == "reddit_buzz":
        c = _d(item.get("capture_date"))
        if c is None:
            return _rule(None, "reddit_buzz without a capture_date")
        if c != day:
            return _rule(False, f"the {c} Reddit capture posted on {day}: today's capture only (owner 10-22)")
        ps = _d(item.get("price_session"))
        if ps and ps < day:
            md = f"{ps.strftime('%b')} {ps.day}"
            if md in text or re.search(rf"\b{ps.strftime('%A')}\b", text):
                return _rule(False, f"a line about the {md} price session in a {c} capture post: no line about an "
                                    "earlier day's prices (owner 10-22)")
        return _rule(True, f"today's Reddit capture ({c}){at}")
    if kind == "earnings_result":
        pub = _t(item.get("published_at"))
        rel = _d(item.get("release_date")) or (ny_day(pub) if pub else None)
        if rel is None:
            return _rule(None, "earnings_result without a release date")
        if rel != day:
            return _rule(False, f"the {rel} release posted on {day}: same day only")
        top, why = caps.top(item.get("ticker"), TOP_EARNINGS, static=False)
        if pub is None:
            return (_rule(True, f"release day; not a top-50 name ({why})") if top is False else
                    _rule(None, f"release day, but no release time (published_at) for the 3 h top-50 rule ({why})"))
        el = t_post - pub
        if el <= FAST:
            return _rule(True, f"{_hm(el)} after the release{at}")
        if top is True:
            return _rule(False, f"{_hm(el)} after the release: a top-50 name ({why}) posts within 3 h")
        if top is False:
            return _rule(True, f"release day; not a top-50 name ({why}), so the 3 h rule does not apply")
        return _rule(None, f"{_hm(el)} after the release; top-50 status unknown ({why})")
    if kind in FILING_TYPES:
        f = _d(item.get("filed"))
        iday = _d(item.get("item_id"))
        if f == day:
            return _rule(True, f"filed {f}, posted that day{at}")
        if iday is not None and iday != day:
            return _rule(False, f"an item of the {iday} facts posted on {day}: same day only")
        return _rule(None, f"filed {f}; the facts do not say when our feed first saw it, so 'new today' cannot be checked")
    d0 = (_d(item.get("trade_date")) if kind == "picks_ready" else
          _d(item.get("scan_date")) if kind == "chart_pattern" else _d(item.get("item_id")))
    if d0 is None:
        return _rule(None, f"{kind}: no date to check")
    if d0 == day:
        return _rule(True, f"an item of {d0}, posted that day{at}")
    return _rule(False, f"an item of {d0} posted on {day}: same day only")


def _b4(item: dict | None, t_post: dt.datetime, exact: bool) -> dict:
    if not item:
        return _rule(None, "no facts item")
    kind = item.get("type")
    at = "" if exact else " at review time"
    if kind == "earnings_result":
        pub = _t(item.get("published_at"))
        if pub is None:
            return _rule(None, "no release time (published_at)")
        el = t_post - pub
        return _rule(el <= FAST, f"{_hm(el)} after the release{at}")
    if kind in SESSION_TYPES:
        s = _d(item.get("session_date"))
        close = close_at(s) if s else None
        if close is None:
            return _rule(None, "no session close time")
        el = t_post - close
        return _rule(dt.timedelta(0) <= el <= FAST, f"{_hm(el)} after the {s} close{at}")
    if kind in FILING_TYPES:
        return _rule(None, "a filing has no time in the facts (date only)")
    return _rule(False, f"n/a: {kind} has no release, filing or close time")


def score(text: str, item: dict | None, platform: str, kind: str = "post", facts: dict | None = None,
          prev_own_post_at=None, now=None, media=None, *, reply_text: str | None = None, post_at=None,
          target_followers=None, target_posted_at=None) -> dict:
    """The VIRAL CHECK v1 score of one post, Reel or comment (see the module doc)."""
    text = text or ""
    platform = str(platform or "").strip().lower()
    kind = kind if kind in KINDS else "post"
    now_t = _t(now) or dt.datetime.now(dt.timezone.utc)
    post_t = _t(post_at)
    t_post, exact = (post_t, True) if post_t else (now_t, False)
    caps = Caps(item, facts)
    tags = cashtags(text)
    figs = dl.figures(text)
    company_tags = [t for t in tags if t not in NOT_COMPANY]
    lks = links(text, item)
    must: dict[str, dict] = {}

    # M1, M2
    must["M1"] = _rule(bool(tags), f"cashtags: {' '.join('$' + t for t in tags)}" if tags else "no $cashtag in the main text")
    must["M2"] = _rule(bool(figs), f"{len(figs)} number(s)" if figs else "no number in the main text")

    if kind == "comment":
        # M5, D1-D3 (VIRAL-CHECK section D)
        must["M5"] = _rule(not lks, f"a link in a comment: {dl.short(lks[0], 50)}" if lks else "no link")
        followers = _num(target_followers)
        tposted = _t(target_posted_at)
        if followers is None and tposted is None:
            must["D1"] = _rule(None, "target_followers / target_posted_at not in the draft: >= 50k followers within "
                                     "30 min cannot be checked from the text")
        elif followers is not None and followers < TARGET_FOLLOWERS:
            must["D1"] = _rule(False, f"the target account has {int(followers):,} followers (>= 50,000)")
        elif tposted is None:
            must["D1"] = _rule(None, "target_posted_at not in the draft: the 30 min window cannot be checked")
        else:
            el = t_post - tposted
            if el < dt.timedelta(0):
                must["D1"] = _rule(None, "target_posted_at is after the comment time")
            elif el > TARGET_WINDOW:
                must["D1"] = _rule(False, f"{_hm(el)} after the target post{'' if exact else ' at review time'} "
                                          "(within 30 min)")
            elif followers is None:
                must["D1"] = _rule(None, f"{_hm(el)} after the target post; target_followers not in the draft")
            else:
                must["D1"] = _rule(True, f"{int(followers):,} followers, {_hm(el)} after the target post")
        if not item:
            must["D2"] = _rule(False, "no facts item: a comment carries 1 cashtag + 1 number from an item we hold")
        else:
            own = set(item_cashtags(item))
            hit = [t for t in tags if t in own]
            must["D2"] = _rule(bool(hit), f"on item {dl.short(item.get('item_id'), 60)} (${hit[0]})" if hit else
                               f"no cashtag of item {dl.short(item.get('item_id'), 60)} ({', '.join('$' + t for t in sorted(own))})")
        handles = sorted({m.group(1).rstrip(".") for m in MENTION.finditer(text)})
        must["D3"] = _rule(not handles, f"typed @mention: {', '.join('@' + h for h in handles)} (the platform adds the "
                                        "reply-to handle)" if handles else "no typed @mention")
    else:
        # M3
        names = [n for n in company_names(item) if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.IGNORECASE)]
        if company_tags:
            must["M3"] = _rule(True, f"company cashtag ${company_tags[0]}")
        elif names:
            must["M3"] = _rule(True, f"names {names[0]}")
        else:
            must["M3"] = _rule(False, "no company named (macro / market only: -15 to -19%)")
        # M4
        if platform in WORD_PLATFORMS:
            n = dl.word_count(text)
            must["M4"] = _rule(WORDS_MIN <= n <= WORDS_MAX, f"{n} words (25-60)")
        else:
            must["M4"] = _rule(True, f"n/a: {platform or 'this platform'} caption (X and Threads only)", na=True)
        # M5
        bad = lks
        if platform == "instagram" and item and item.get("type") in FILING_TYPES:
            src = {u for u in [item.get("source_url"), *(item.get("source_urls") or [])] if isinstance(u, str) and u}
            bad = [u for u in lks if u not in src]
            if lks and not bad:
                must["M5"] = _rule(True, "only the official source link the caption must carry (compliance)")
        if "M5" not in must:
            must["M5"] = _rule(not bad, f"a link in the main post: {dl.short(bad[0], 60)} (self-reply or bio only)" if bad
                               else "no link in the main post")
        # M6
        prev = _t(prev_own_post_at)
        if prev is None:
            must["M6"] = _rule(None, "previous own post time not known")
        else:
            gap = t_post - prev
            if gap >= SPACING:
                must["M6"] = _rule(True, f"{_hm(gap)} after our previous {platform} post{'' if exact else ' (at review time)'}")
            elif exact:
                must["M6"] = _rule(False, f"{_hm(gap)} after our previous {platform} post (>= 60 min)")
            else:
                must["M6"] = _rule(None, f"{_hm(gap)} after our previous {platform} post at review time; the draft has no "
                                         "planned_at, so the gap at post time is unknown")
        # M7
        attached, _, mwhy = media_kind(media, item, kind)
        must["M7"] = _rule(attached, mwhy if attached is not False else "no own image or video attached")
        # M8
        must["M8"] = _m8(item, text, t_post, exact, caps)

    # Boosters
    bd: dict[str, dict] = {}
    _, video, mwhy = media_kind(media, item, kind)
    bd["B1"] = _rule(bool(video) if video is not None else None, "native video" if video else
                     ("media not known" if video is None else f"no video ({mwhy})"))
    bd["B2"] = _rule(len(tags) >= 3, f"{len(tags)} distinct cashtag(s)")
    if len(tags) >= 2:
        lead, why_lead = caps.top(tags[0], TOP_BROAD)
        rest = [(t, caps.top(t, TOP_BROAD)) for t in tags[1:]]
        small = [t for t, (b, _) in rest if b is False]
        if lead is True and small:
            bd["B3"] = _rule(True, f"broad lead ${tags[0]} + ${small[0]}")
        elif lead is None:
            bd["B3"] = _rule(None, why_lead)
        else:
            bd["B3"] = _rule(False, (f"lead ${tags[0]} is not broad ({why_lead})" if lead is False else
                                     f"broad lead ${tags[0]} but no smaller name"))
    else:
        bd["B3"] = _rule(False, "fewer than 2 cashtags")
    bd["B4"] = _b4(item, t_post, exact)
    buzz = {}
    for it in (facts or {}).get("items") or []:
        if isinstance(it, dict) and it.get("type") == "reddit_buzz":
            lead = it.get("lead") or {}
            if lead.get("ticker") and _num(lead.get("ratio")):
                buzz[norm_ticker(lead["ticker"])] = _num(lead["ratio"])
            for o in it.get("others") or []:
                if isinstance(o, dict) and o.get("ticker") and _num(o.get("ratio")):
                    buzz.setdefault(norm_ticker(o["ticker"]), _num(o["ratio"]))
    hot = [t for t in tags if (buzz.get(t) or 0) >= BUZZ_RATIO]
    if hot:
        bd["B5"] = _rule(True, f"${hot[0]} at {buzz[hot[0]]:.1f}x its usual Reddit count")
    elif facts is None or not any(isinstance(i, dict) and i.get("type") == "reddit_buzz" for i in facts.get("items") or []):
        bd["B5"] = _rule(None, "no reddit_buzz item in these facts (the top-20 mentions list is not in the facts)")
    else:
        bd["B5"] = _rule(False, "no cashtag at >= 2x its usual Reddit count (the top-20 mentions list is not in the facts)")
    ok6, why6 = surprise(first_line(text), item)
    bd["B6"] = _rule(ok6, why6)
    boosters = [b for b in BOOSTERS if bd[b]["ok"] is True]

    # Penalties (posts and Reels)
    pd: dict[str, dict] = {}
    if kind == "comment":
        for p in PENALTIES:
            pd[p] = _rule(False, "n/a: a comment (section D)", na=True)
    else:
        earnings = (item or {}).get("type") in EARNINGS_TYPES
        broad = {t: caps.top(t, TOP_BROAD) for t in tags}
        has_pct = bool(PCT.search(URL.sub(" ", text)))
        if earnings:
            pd["P1"] = _rule(False, "earnings post (exempt)")
        elif len(tags) == 1 and tags[0] not in NOT_COMPANY and has_pct:
            b, why = broad[tags[0]]
            pd["P1"] = _rule(b, (f"single broad company ${tags[0]} + a % figure, no smaller name ({why}): -25%" if b else
                                 why))
        else:
            pd["P1"] = _rule(False, "not a single company + % post")
        if earnings:
            pd["P2"] = _rule(False, "earnings post (exempt)")
        elif not tags:
            pd["P2"] = _rule(False, "no cashtags")
        else:
            vals = [b for b, _ in broad.values()]
            if all(v is True for v in vals):
                pd["P2"] = _rule(True, f"broad-only cashtags ({' '.join('$' + t for t in tags)}) on a non-earnings post: -18%")
            elif any(v is False for v in vals):
                pd["P2"] = _rule(False, "has a non-broad name")
            else:
                pd["P2"] = _rule(None, "; ".join(w for b, w in broad.values() if b is None))
        handles = sorted({m.group(1).rstrip(".") for m in MENTION.finditer(f"{URL.sub(' ', text)}\n{URL.sub(' ', reply_text or '')}")})
        pd["P3"] = _rule(bool(handles), f"@mention in our own post: {', '.join('@' + h for h in handles)} (-20% engagement)"
                         if handles else "no @mention")
        if item is None:
            pd["P4"] = _rule(None, "no facts item: recap or not unknown")
        elif item.get("type") in RECAP_TYPES:
            pd["P4"] = _rule(not company_tags, "a market recap with no company cashtag (-15%)" if not company_tags else
                             f"recap with company cashtag ${company_tags[0]}")
        else:
            pd["P4"] = _rule(False, "not a market recap")
    penalties = [p for p in PENALTIES if pd[p]["ok"] is True]

    fails = [c for c, r in must.items() if r["ok"] is False]
    unknown = [c for c, r in must.items() if r["ok"] is None]
    n_ok = sum(1 for r in must.values() if r["ok"] is True)
    passed = not fails and not unknown and not penalties
    summary = f"M{n_ok}/{len(must)} B{len(boosters)} P{len(penalties)}" + (f" ?{','.join(unknown)}" if unknown else "")
    return {"version": VERSION, "kind": kind, "platform": platform, "item_id": (item or {}).get("item_id"),
            "post_at": t_post.isoformat(), "post_at_known": exact,
            "must": must, "boosters": boosters, "booster_detail": bd, "penalties": penalties, "penalty_detail": pd,
            "fails": fails + penalties, "unknown": unknown, "passed": passed,
            "strong": passed and len(boosters) >= BOOSTERS_MIN, "summary": summary}


# ---------------------------------------------------------------------------
# Drafts (tools/grok_review.py) and answer lines

def find_item(facts: dict | None, item_id) -> dict | None:
    return next((i for i in (facts or {}).get("items") or [] if isinstance(i, dict) and i.get("item_id") == item_id), None)


def score_draft(draft: dict, facts: dict | None, kind: str, history: list[dict] | None = None, now=None) -> dict:
    """score() of a validator draft: a post {item_id, platform, text, reply_text, media_url, planned_at?, format?} or a
    comment {kind: comment, platform, text, item_id?, target_followers?, target_posted_at?, planned_at?}. history = our
    own posts (post_history records, approved-not-logged ones included) for M6."""
    now_t = _t(now) or dt.datetime.now(dt.timezone.utc)
    post_at = _t(draft.get("planned_at"))
    platform = str(draft.get("platform") or "").lower()
    item = find_item(facts, draft.get("item_id"))
    if kind == "comment":
        return score(str(draft.get("text") or ""), item, platform, "comment", facts, None, now_t, None,
                     post_at=post_at, target_followers=draft.get("target_followers"),
                     target_posted_at=draft.get("target_posted_at"))
    vkind = "reel" if str(draft.get("format") or "").lower() == "reel" else "post"
    media = draft.get("media_url")
    media = media if isinstance(media, str) else ""   # a post draft without media_url has none (not "unknown")
    prev = prev_own_post_at(history, platform, post_at or now_t) if history is not None else None
    return score(str(draft.get("text") or ""), item, platform, vkind, facts, prev, now_t, media,
                 reply_text=draft.get("reply_text") if isinstance(draft.get("reply_text"), str) else None, post_at=post_at)


def reject_reasons(res: dict) -> list[str]:
    """REJECT reasons: a checkable must-have that fails (False, never an unknown) and every penalty."""
    out = [f"viral: {c} {res['must'][c]['why']}" for c in res["must"] if res["must"][c]["ok"] is False]
    out += [f"viral: {p} {res['penalty_detail'][p]['why']}" for p in res["penalties"]]
    return out


def note_lines(res: dict) -> list[str]:
    """Answer lines: the score (Grok copies it into the post_log), viral-weak under 2 boosters (posts / Reels), and the
    rules that could not be checked."""
    lines = [f"viral={res['summary']} (VIRAL CHECK v1; boosters: {' '.join(res['boosters']) or 'none'})"]
    if res["kind"] != "comment" and len(res["boosters"]) < BOOSTERS_MIN:
        lines.append(f"viral-weak: {len(res['boosters'])} booster(s); a post needs >= {BOOSTERS_MIN}: native video, 3+ "
                     "cashtags, a broad lead + a context ticker, posting <= 3 h after the release / close, a Reddit-hot "
                     "ticker, or a surprise number in line 1")
    for c in res["unknown"]:
        lines.append(f"viral-unknown: {c} {res['must'][c]['why']}")
    return lines
