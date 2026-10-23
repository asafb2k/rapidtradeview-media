"""VIRAL CHECK v1: every post and every action carries the reach ingredients our data measured (owner 2026-10-23:
"verify each and every post/action have the potential to go viral").

Spec: D:/rtv-ops/tracks/growth/strategy/pillars-2026-10-18/VIRAL-CHECK.md (Growth; Grok kit directive #668). Evidence:
eda2 (23,006 finance-X posts, within author) and G3 (4,767 posts, 593 authors). The check cannot promise virality (who
posts explains ~92% of view variance); it makes sure a post has every ingredient the data links to reach and none of the
measured penalties. Standard library + tools/draft_lint.py only, so tools/grok_review.py (the draft gate) and Growth's
post_audit.py (live posts) share one rule set.

  score(text, item, platform, kind, facts=None, prev_own_post_at=None, now=None, media=None, *, reply_text=None,
        post_at=None, target_followers=None, target_posted_at=None, own_posts=None) -> dict

kind is "post", "reel" or "comment". `now` is the review time; `post_at` the time the post goes (or went) out when it is
known (a draft's planned_at, a live post's posted_at). Without post_at the review time is a lower bound of the post time:
a rule it already decides (a gap already >= 60 min, a release already > 3 h old, an item of an earlier day) is decided,
anything else stays unknown (a same-day item or a fast window "at review time" is not a post-time fact). Texts are
NFKC-folded first (as grok_review's compliance checks read them: a math-bold or fullwidth cashtag is a cashtag).

Hard rule or note. A rule whose evidence does not carry a REJECT on this platform / item / kind is a NOTE ("soft": a
"viral-note:" answer line, never a REJECT). Hard = the gate REJECTs when it is checkable and fails. Review round
2026-10-23 (three reviewers; Growth to fold into VIRAL-CHECK.md):
  - Instagram: M1, M3, M5, M6, P1, P2, P4 are notes. Their evidence is the X corpus only (G3 section 6 "X only. Nothing
    here speaks to Threads topic feeds or IG Reels"; eda2 E4); Instagram has no cashtag search and captions do not
    link. Threads keeps them hard as policy (eda2 plan: "Threads: mirror the X rules"), labelled so in the reason.
  - M4: over 60 words is a note (eda2: over 60 words +0.18; only niche x over-60 is negative, -0.44, not after BH). Under
    25 words stays hard (spec; likely).
  - M8: same session day is hard (owner #652). "A top-50 name's earnings within 3 h" is a note (M8.3h): neither eda2 nor
    G3 conditions the speed effect on top-50, the speed effect is likely only, and B4 already scores speed.
  - P1 / P2 are notes on filing / flow items (Congress, Form 4, PTR, insider / Congress flow) and Reddit buzz (G3 3d:
    "can't tell" / "untestable"; decided on our own data), and when unavoidable: every cashtag the item offers is broad
    (compliance allows only the item's own cashtags, so no rewrite can add a smaller name).
  - P1 is a subset of P2 (one broad company is broad-only): it is folded into P2's reason, never counted twice. P4
    counts only when the recap carries a cashtag (an index one): a recap with no cashtag at all is M1 / M3's fail
    already (G3 3c: the recap penalty is "mostly via missing cashtags").
  - Comments: replies were not testable (eda2 sections 8-9: 5 replies to others in the corpus), so M1, D1 and D2 are
    notes. M2 stays hard (the E0 guardrail: every comment carries a fact or number from our data), as do M5 (no link)
    and D3 (no typed @mention).

A. Must-haves (post / Reel):
  M1  >= 1 $cashtag in the main text                                                    (note on Instagram)
  M2  >= 1 number (draft_lint.figures: cashtags, filing names and Q3 / FY labels are not numbers)
  M3  a company is named (a cashtag that is not an index / ETF / fund, or the item's company name): not macro only
                                                                                        (note on Instagram)
  M4  25-60 words in the main text: X and Threads only (Instagram captions: n/a); over 60 is a note
  M5  no link in the main text: an http(s) URL, or a bare domain X / Threads would auto-link (a domain that is part of
      the item's own company name is not one). Instagram: a note; the official source link grok_review requires on a
      Congress / Form 4 / ptr_summary caption passes
  M6  >= 60 min from our nearest own post on the platform, before or after (eda2: gap-to-next survives Holm). Posted
      neighbours decide; an approved post that is not posted yet (the ledger's planned_at) within 60 min is unknown,
      never a REJECT (an abandoned approval must not block a slot). Unknown without any own post time. (note on IG)
  M7  own image or video attached (media; None = not known)
  M8  fresh: a session price move (market_move, mega_mover, sector_rotation, breadth_day, basket_week,
      earnings_reaction) on its session's own New York day (a week item also on the weekend after it); a Reddit capture
      on its capture day with no line about an older price session; an earnings result from its release day through
      the next session day when it came after the close (published after 16:00 New York on the release day, or
      published on a later day: our facts carry it first then); a filing on the day it is filed (an older filing in
      today's facts: unknown, the facts carry no first-seen time); picks on their trade day; a chart pattern and any
      other item on its own facts day (owner 10-22, #652). M8.3h (note): a top-50 name's result within 3 h of
      published_at (top-50 from the facts only, else unknown)
B. Boosters (a post needs >= 2; fewer is a note, never a REJECT; the note says what this item can reach at all):
  B1  native video (a Reel, an .mp4 / video media, kind "reel")
  B2  3 or more distinct cashtags
  B3  a broad lead (the first cashtag) plus 1 non-broad company (not an ETF / fund)
  B4  fast: <= 3 h after the earnings release (published_at), after the session close (16:00 New York) for a recap;
      a filing has no time in the facts (date only): unknown
  B5  a retail-attention ticker: a non-broad ticker at >= 2x its usual count in the same facts file's reddit_buzz data
      (G3: the retail-popular premium is for names outside the broad tiers; the top-20 mentions list is not in the facts)
  B6  a surprise number in line 1: a beat / miss with a figure, a >= 5% move, a >= $100B value change, a record
C. Penalties (any hard one: rewrite):
  P1  a single broad company cashtag plus a % figure and no other name (not earnings): folded into P2
  P2  broad-only cashtags on a non-earnings post (note: Instagram, filing / flow / Reddit items, unavoidable)
  P3  an @mention in our own main text (a price written "@45.20" is not a mention)
  P4  a market recap (market_move, sector_rotation, breadth_day, basket_week) whose cashtags are all index / ETF ones
                                                                                        (note on Instagram)
D. Comments / replies (kind "comment"): M1 (note), M2, M5 plus
  D1  under an account with >= 50k followers, <= 30 min after its post (target_followers / target_posted_at from the
      draft; unknown without them: the text cannot show it). A note (one anecdote; replies untestable)
  D2  on a facts item we hold: the comment's cashtag is one of the item's. A note (compliance already ties a comment's
      numbers and cashtags to its item_id)
  D3  no typed @mention (the platform adds the reply-to handle itself)
  Boosters are scored; the penalties are post rules (section D replaces C). Repeats and the 15-a-day ceiling are
  grok_review's comment state; the spec's floor of 5 a day per platform and "targets picked by B5" are not checked here
  (Growth's post_audit can count them).

Every rule is {ok: True | False | None, why, soft?: basis}; None = the data is not there (never guessed). fails = hard
must-haves that are False plus hard penalties (what grok_review REJECTs); notes = soft rules that fail (answer lines);
passed = nothing fails, nothing is unknown and no penalty fires, hard or soft; strong = passed and >= 2 boosters;
summary "M8/8 B2 P0" (+ " ?M6" naming unknown rules, + " ~P2" naming soft fails; n/a rules count as passed, as Grok logs
viral=M<passed>/8).

Broad (B3, P1, P2) = a top-100 US company by market cap, or a G3 index symbol (SPY QQQ SPX NDX DIA DJI DJIA IWM VOO VTI
ES NQ RUT). Decided by, in order: a foreign company listed in the US (G3's ADR tier: never broad); the facts' own cap
rank (rank_by_cap); a cap compared with a ranked company of the same facts file (a company worth at least #36's cap is
top-36; one worth at most #140's is not top-100); not among the 500 largest (in_500 false); then G3's static TOP100 list
(G3-evidence.md, written before any estimate: the list the -18% broad penalty was measured on). Other ETFs are not broad
(G3 counts "other ETF only" posts as no-broad) and not companies (M3, P4, B3). Top-50 (M8.3h) uses the facts only.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import draft_lint as dl  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 - no tz database: New York dates read as UTC dates (as select_stories does)
    NY = None

VERSION = "viral-check v1.1 (2026-10-23 review round)"
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
YEAR_MIN, YEAR_MAX = 2000, 2100   # a time outside this range is not a time (untrusted draft fields)

# G3-evidence.md "Ticker tiers": INDEX (broad with TOP100).
INDEX_BROAD = frozenset("SPY QQQ SPX NDX DIA DJI DJIA IWM VOO VTI ES NQ RUT".split())
# Not a company (M3, P4, B3): index / sector / leveraged ETFs and index symbols (draft_lint's list, the EDA's), plus any
# ticker the facts name as an ETF / fund (Caps.funds).
NOT_COMPANY = frozenset(dl.INDEX_ETF) | INDEX_BROAD
FUND_NAME = re.compile(r"\b(?:ETF|ETN|Fund|iShares|SPDR|ProShares|Direxion)\b", re.IGNORECASE)
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
FLOW_TYPES = (*FILING_TYPES, "insider_flow", "congress_flow")
# Items whose `name` is a person, not the company (M3 reads `company` there).
PERSON_TYPES = FILING_TYPES

# Notes, not REJECTs (see the module doc): the basis each one names.
X_ONLY_RULES = ("M1", "M3", "M5", "M6", "P1", "P2", "P4")
SOFT_INSTAGRAM = "X-only evidence (G3 section 6, eda2 E4): a note on Instagram until our own Reel data exists"
THREADS_POLICY = "X evidence; Threads mirrors the X rules by policy (eda2 plan)"
SOFT_P2_TYPES = "G3 3d: Congress / insider / Reddit posts are can't-tell or untestable; decided on our own data"
SOFT_P2_UNAVOIDABLE = ("unavoidable: every cashtag this item offers is broad and compliance allows no other, so no "
                       "rewrite adds a smaller name")
SOFT_M4_LONG = "eda2: over 60 words is +0.18 (likely); only niche x over-60 is negative (-0.44, not after BH)"
SOFT_M8_3H = ("speed is likely (+0.38, event FE) and no source conditions it on top-50; B4 scores speed: a note, not a "
              "REJECT")
SOFT_COMMENT = "replies were not testable (eda2 sections 8-9): a note, not a REJECT"
P2_NOTE_TYPES = (*FLOW_TYPES, "reddit_buzz")

URL = dl.URL
BARE_DOMAIN = re.compile(r"(?<![\w@.$-])(?:[a-z0-9-]+\.)+[a-z]{2,24}(?![\w-])(?:/\S*)?", re.IGNORECASE)
MENTION = re.compile(r"(?<![\w@.])@([A-Za-z0-9_.]{1,30})")
NUMERIC_HANDLE = re.compile(r"[\d.,]+")
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

def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _rule(ok, why: str, na: bool = False, soft: str | None = None) -> dict:
    out = {"ok": ok, "why": why}
    if na:
        out["na"] = True
    if soft:
        out["soft"] = soft
    return out


def _sane(t: dt.datetime | None) -> dt.datetime | None:
    return t if t is not None and YEAR_MIN <= t.year <= YEAR_MAX else None


def as_time(v) -> dt.datetime | None:
    """An aware UTC datetime from a datetime or an ISO string (draft_lint.parse_time); None otherwise, and None for a
    time outside 2000-2100 (draft fields are untrusted: year 1 or 9999 overflows the New York conversion)."""
    try:
        if isinstance(v, dt.datetime):
            return _sane((v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc))
        return _sane(dl.parse_time(v)) if isinstance(v, str) else None
    except (OverflowError, ValueError):
        return None


_t = as_time


def _d(v) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def ny_day(t: dt.datetime) -> dt.date:
    return (t.astimezone(NY) if NY else t.astimezone(dt.timezone.utc)).date()


def ny_hour(t: dt.datetime) -> float:
    lt = t.astimezone(NY) if NY else t.astimezone(dt.timezone.utc)
    return lt.hour + lt.minute / 60


def next_session(day: dt.date) -> dt.date:
    """The next weekday after `day` (market holidays are not in the facts)."""
    d = day + dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


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


def fold(text) -> str:
    """NFKC-folded text (claims.nfkc: math-bold / fullwidth letters and signs as their plain forms)."""
    return unicodedata.normalize("NFKC", text or "") if isinstance(text, str) else ""


def item_cashtags(item: dict | None) -> list[str]:
    """tickers + ticker + context_tickers (grok_review.item_cashtags)."""
    if not item:
        return []
    base = [*_list(item.get("tickers")), *([item["ticker"]] if item.get("ticker") else []), *_list(item.get("context_tickers"))]
    return list(dict.fromkeys(norm_ticker(t) for t in base if isinstance(t, str) and t))


def item_phrases(item: dict | None) -> list[str]:
    """The sentences a post of this item may copy (fact_phrases, claim_phrases, phrasings[].text)."""
    if not item:
        return []
    out = [*_list(item.get("fact_phrases")), *_list(item.get("claim_phrases")),
           *(p.get("text") for p in _list(item.get("phrasings")) if isinstance(p, dict))]
    return [s for s in dict.fromkeys(out) if isinstance(s, str) and s]


def offered_cashtags(item: dict | None) -> list[str]:
    """The cashtags a compliant post of this item can carry: under the verbatim rule (fact_phrases in the item) the item
    cashtags its phrases print; else (or when no phrase prints one) the item cashtags."""
    allowed = item_cashtags(item)
    if item and "fact_phrases" in item:
        seen = {t for s in item_phrases(item) for t in cashtags(s)}
        printed = [t for t in allowed if t in seen]
        if printed:
            return printed
    return allowed


def _hm(td: dt.timedelta) -> str:
    m = int(td.total_seconds() // 60)
    return f"{m} min" if abs(m) < 120 else f"{m / 60:.1f} h"


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, str) and re.fullmatch(r"\s*\d[\d,]*(?:\.\d+)?\s*", v):
        f = float(v.replace(",", ""))
        return f if math.isfinite(f) else None
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


def _on(p: dict, platform) -> bool:
    return str(p.get("platform") or "").lower() == str(platform or "").lower()


def own_post_times(history: list[dict] | None, platform: str | None) -> list[tuple[dt.datetime, bool]]:
    """[(time, pending)] of our own posts on `platform` with a known time (pending = approved, not posted yet)."""
    out = []
    for p in history or []:
        if not isinstance(p, dict) or not _on(p, platform):
            continue
        t = posted_time(p)
        if t is not None:
            logged = any(POSTED_AT.search(str(p.get(k) or "")) for k in ("body", "text"))
            out.append((t, bool(p.get("pending")) and not logged))
    return out


def prev_own_post_at(history: list[dict] | None, platform: str | None, before: dt.datetime | None) -> dt.datetime | None:
    """The newest own post time on `platform` strictly before `before` (post_history records, or any dicts with
    platform + posted_at / created_at); None when there is none or no history."""
    if not history or before is None:
        return None
    times = [t for t, _ in own_post_times(history, platform) if t < before]
    return max(times) if times else None


# ---------------------------------------------------------------------------
# Market cap ranks (broad = top-100 US company or index symbol)

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
    with a cap) and in_500; funds = tickers the facts name as an ETF / fund. top(t, n) -> (True | False | None, why)."""

    def __init__(self, item: dict | None, facts: dict | None):
        items = [i for i in (facts or {}).get("items") or [] if isinstance(i, dict)]
        if isinstance(item, dict) and item not in items:
            items.append(item)
        self.rank: dict[str, int] = {}
        self.cap: dict[str, float] = {}
        self.not500: set[str] = set()
        self.funds: set[str] = set()
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
                own = it.get("company") or (it.get("name") if it.get("type") not in PERSON_TYPES else None)
                if isinstance(own, str) and FUND_NAME.search(own):
                    self.funds.add(t)
            for k, n in _dict(it.get("ticker_names")).items():
                if isinstance(n, str) and FUND_NAME.search(n):
                    self.funds.add(norm_ticker(k))
            for d in _walk({k: v for k, v in it.items() if k not in ("phrasings", "claims")}):
                c = _num(d.get("cap"))
                if isinstance(d.get("ticker"), str) and c:
                    self.cap.setdefault(norm_ticker(d["ticker"]), c)
        self.anchors = sorted((r, self.cap[t], t) for t, r in self.rank.items() if t in self.cap)

    def fund(self, ticker: str) -> bool:
        """An index symbol, an index / sector / leveraged ETF or a ticker the facts name as an ETF / fund: not a company."""
        t = norm_ticker(ticker)
        return t in NOT_COMPANY or t in self.funds

    def top(self, ticker: str, n: int, static: bool = True) -> tuple[bool | None, str]:
        t = norm_ticker(ticker)
        if not t:
            return None, "no ticker"
        if n >= TOP_BROAD and t in INDEX_BROAD:
            return True, f"${t} is an index symbol (G3 INDEX)"
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


def mentions(text: str) -> list[str]:
    """Typed @handles in a text (links removed; a price written "@45.20" is not a handle)."""
    hs = {m.group(1).rstrip(".") for m in MENTION.finditer(URL.sub(" ", text or ""))}
    return sorted(h for h in hs if h and not NUMERIC_HANDLE.fullmatch(h))


def links(text: str, item: dict | None) -> list[str]:
    """URLs and auto-linked bare domains in a text (a domain inside the item's own company wording is not a link)."""
    s = text or ""
    found = [u.rstrip(".,;:!?)]}\"'") for u in URL.findall(s)]
    rest = URL.sub(" ", s)
    it = _dict(item)
    own = " ".join(str(x) for x in [it.get("name"), it.get("company"), *_dict(it.get("ticker_names")).values()]
                   if x).lower()
    for m in BARE_DOMAIN.finditer(rest):
        b = m.group(0).rstrip(".,;:!?)]}\"'")
        if b.split("/", 1)[0].lower() in own:
            continue
        found.append(b)
    return found


def company_names(item: dict | None) -> list[str]:
    """Short company names an item stands for ("The Procter & Gamble Company" -> "Procter & Gamble"); ETF / fund names
    are not company names."""
    if not item:
        return []
    raw = [item.get("company"), *_dict(item.get("ticker_names")).values(), *_dict(item.get("names")).values(),
           *(p.get("name") for p in _list(item.get("peers")) if isinstance(p, dict))]
    if item.get("type") not in PERSON_TYPES:
        raw.append(item.get("name"))
    out = []
    for n in raw:
        if not isinstance(n, str) or not n.strip() or FUND_NAME.search(n):
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
    ours = {m.get("url"): str(m.get("kind") or "").lower() for m in _list(_dict(item).get("media")) if isinstance(m, dict)}
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
    nums = _dict(_dict(_dict(item).get("moves")).get("numbers"))
    return {str(k).replace("\u2212", "").lstrip("+-") for k in nums}


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

def _release_window(item: dict) -> tuple[dt.date | None, dt.date | None, dt.datetime | None, str]:
    """(first day, last day, published_at, how) an earnings result is fresh: its release day, through the next session
    day when it came after the close (published after 16:00 New York on the release day, or on a later day: the facts
    carry it first then), and through the day our feed published it."""
    pub = _t(item.get("published_at"))
    rel = _d(item.get("release_date")) or (ny_day(pub) if pub else None)
    if rel is None:
        return None, None, pub, ""
    end, how = rel, ""
    if pub is not None:
        pday = ny_day(pub)
        if pday > rel or (pday == rel and ny_hour(pub) >= CLOSE_HOUR):
            end = max(next_session(rel), pday)
            how = f" (after the close: fresh through {end})"
    return rel, end, pub, how


def _m8(item: dict | None, text: str, t_post: dt.datetime, exact: bool, caps: Caps) -> tuple[dict, dict | None]:
    """(M8 same-day freshness, M8.3h note or None). Without a planned time (exact False) a True becomes unknown: the
    post day is not known yet; a False the review day already decides stays."""
    m8, extra = _m8_day(item, text, t_post), None
    if not exact and m8["ok"] is True:
        m8 = _rule(None, f"{m8['why']} at review time; the draft has no planned_at, so the post day is not known")
    if item and item.get("type") == "earnings_result" and m8["ok"] is not False:
        pub = _t(item.get("published_at"))
        if pub is not None:
            el = t_post - pub
            top, why = caps.top(item.get("ticker"), TOP_EARNINGS, static=False)
            if el > FAST and top is True:
                extra = _rule(False, f"{_hm(el)} after the release{'' if exact else ' at review time'}: a top-50 name "
                                     f"({why}) posts within 3 h", soft=SOFT_M8_3H)
            elif el > FAST and top is None:
                extra = _rule(None, f"{_hm(el)} after the release; top-50 status unknown ({why})", soft=SOFT_M8_3H)
            elif el > FAST:
                extra = _rule(True, f"not a top-50 name ({why}): the 3 h rule does not apply", soft=SOFT_M8_3H)
            elif exact:
                extra = _rule(True, f"{_hm(el)} after the release", soft=SOFT_M8_3H)
            else:
                extra = _rule(None, f"{_hm(el)} after the release at review time; no planned_at", soft=SOFT_M8_3H)
    return m8, extra


def _m8_day(item: dict | None, text: str, t_post: dt.datetime) -> dict:
    if not item:
        return _rule(None, "no facts item: freshness cannot be dated")
    kind = item.get("type")
    day = ny_day(t_post)
    if kind in SESSION_TYPES:
        s = _d(item.get("session_date"))
        if s is None:
            return _rule(None, f"{kind} without a session_date")
        if day == s:
            return _rule(True, f"the {s} session, posted that day")
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
        return _rule(True, f"today's Reddit capture ({c})")
    if kind == "earnings_result":
        rel, end, _, how = _release_window(item)
        if rel is None:
            return _rule(None, "earnings_result without a release date")
        if rel <= day <= end:
            return _rule(True, f"the {rel} release{how}, posted {day}")
        if day < rel:
            return _rule(None, f"posted {day}, before the {rel} release date")
        return _rule(False, f"the {rel} release{how} posted on {day}: its release day only (the next session day after "
                            "an after-close release)")
    if kind in FILING_TYPES:
        f = _d(item.get("filed"))
        iday = _d(item.get("item_id"))
        if f == day:
            return _rule(True, f"filed {f}, posted that day")
        if iday is not None and iday != day:
            return _rule(False, f"an item of the {iday} facts posted on {day}: same day only")
        return _rule(None, f"filed {f}; the facts do not say when our feed first saw it, so 'new today' cannot be "
                           "checked")
    # picks on their trade day; a chart pattern and any other item on its facts day (the module doc; a pattern's scan
    # runs the evening before the facts day that carries it)
    d0 = _d(item.get("trade_date")) if kind == "picks_ready" else _d(item.get("item_id"))
    if d0 is None:
        return _rule(None, f"{kind}: no date to check")
    if d0 == day:
        return _rule(True, f"an item of {d0}, posted that day")
    return _rule(False, f"an item of {d0} posted on {day}: same day only")


def fresh(item: dict, at, text: str = "") -> dict:
    """M8 (same-day freshness, the hard part) of an item posted at `at` (facts.py: an item stale at build time stays
    out of the top 8)."""
    t = _t(at) or dt.datetime.now(dt.timezone.utc)
    return _m8_day(item, fold(text), t)


def _b4(item: dict | None, t_post: dt.datetime, exact: bool) -> dict:
    if not item:
        return _rule(None, "no facts item")
    kind = item.get("type")
    if kind == "earnings_result":
        pub = _t(item.get("published_at"))
        if pub is None:
            return _rule(None, "no release time (published_at)")
        el = t_post - pub
        if el > FAST:
            return _rule(False, f"{_hm(el)} after the release{'' if exact else ' at review time'}")
        return (_rule(True, f"{_hm(el)} after the release") if exact else
                _rule(None, f"{_hm(el)} after the release at review time; no planned_at, so the post time is not known"))
    if kind in SESSION_TYPES:
        s = _d(item.get("session_date"))
        close = close_at(s) if s else None
        if close is None:
            return _rule(None, "no session close time")
        el = t_post - close
        if el > FAST:
            return _rule(False, f"{_hm(el)} after the {s} close{'' if exact else ' at review time'}")
        if exact:
            return _rule(el >= dt.timedelta(0), f"{_hm(el)} after the {s} close" if el >= dt.timedelta(0) else
                         f"before the {s} close")
        return _rule(None, f"{_hm(el)} after the {s} close at review time; no planned_at, so the post time is not known")
    if kind in FILING_TYPES:
        return _rule(None, "a filing has no time in the facts (date only)")
    return _rule(False, f"n/a: {kind} has no release, filing or close time")


def _m6(t_post: dt.datetime, exact: bool, platform: str, prev, own) -> dict:
    """M6 from our own post times on the platform: [(time, pending)] (own), else one earlier posted time (prev)."""
    label = platform or "this"
    soft = SOFT_INSTAGRAM if platform == "instagram" else None
    times = list(own) if own is not None else ([(prev, False)] if prev is not None else [])
    times = [(t, bool(p)) for t, p in times if t is not None]
    if not times:
        return _rule(None, "previous own post time not known", soft=soft)
    before = [x for x in times if x[0] <= t_post]
    after = [x for x in times if x[0] > t_post]
    if exact:
        near = sorted((abs(t_post - t), t, p) for t, p in times if abs(t_post - t) < SPACING)
        posted = [x for x in near if not x[2]]
        if posted:
            gap, t, _ = posted[0]
            side = "after our previous" if t <= t_post else "before our next"
            return _rule(False, f"{_hm(gap)} {side} {label} post (>= 60 min)", soft=soft)
        if near:
            gap, t, _ = near[0]
            return _rule(None, f"{_hm(gap)} from an approved {label} post planned for {t:%H:%M}Z that is not posted yet "
                               "(an abandoned approval never rejects)", soft=soft)
        parts = []
        if before:
            parts.append(f"{_hm(t_post - max(before)[0])} after our previous {label} post")
        if after:
            parts.append(f"{_hm(min(after)[0] - t_post)} before our next one")
        return _rule(True, "; ".join(parts), soft=soft)
    # no planned time: the post goes out at the review time or later
    if after:
        t = min(after)[0]
        return _rule(None, f"an own {label} post is planned for {t:%H:%M}Z; the draft has no planned_at, so the gap "
                           "cannot be checked", soft=soft)
    t, _ = max(before)
    gap = t_post - t
    if gap >= SPACING:
        return _rule(True, f"{_hm(gap)} after our previous {label} post (at review time)", soft=soft)
    return _rule(None, f"{_hm(gap)} after our previous {label} post at review time; the draft has no planned_at, so the "
                       "gap at post time is unknown", soft=soft)


def _buzz(facts: dict | None) -> dict[str, float] | None:
    """{ticker: ratio} of the facts' reddit_buzz items (lead + others); None when the facts carry no reddit_buzz item."""
    items = [it for it in (facts or {}).get("items") or [] if isinstance(it, dict) and it.get("type") == "reddit_buzz"]
    if not items:
        return None
    buzz: dict[str, float] = {}
    for it in items:
        lead = it.get("lead") or {}
        if isinstance(lead, dict) and lead.get("ticker") and _num(lead.get("ratio")):
            buzz[norm_ticker(lead["ticker"])] = _num(lead["ratio"])
        for o in _list(it.get("others")):
            if isinstance(o, dict) and o.get("ticker") and _num(o.get("ratio")):
                buzz.setdefault(norm_ticker(o["ticker"]), _num(o["ratio"]))
    return buzz


def reachable(item: dict | None, kind: str, caps: Caps, buzz: dict | None, b4: dict) -> list[str]:
    """The boosters a compliant post of this item can reach at all (the viral-weak note names them)."""
    if not item:
        return []
    offered = offered_cashtags(item)
    comp = [t for t in offered if not caps.fund(t)]
    broad = {t: caps.top(t, TOP_BROAD)[0] for t in comp}
    out = []
    if kind == "reel" or any(isinstance(m, dict) and (str(m.get("kind") or "").lower() in VIDEO_KINDS
                                                     or VIDEO_EXT.search(str(m.get("url") or "")))
                             for m in _list(item.get("media"))):
        out.append("B1")
    if len(offered) >= 3:
        out.append("B2")
    if any(v is True for v in broad.values()) and any(v is False for v in broad.values()):
        out.append("B3")
    if b4["ok"] is True or (b4["ok"] is None and item.get("type") in ("earnings_result", *SESSION_TYPES)):
        out.append("B4")
    if any((buzz or {}).get(t, 0) >= BUZZ_RATIO and broad.get(t) is False for t in offered):
        out.append("B5")
    if any(surprise(first_line(s), item)[0] for s in item_phrases(item)):
        out.append("B6")
    return out


def score(text: str, item: dict | None, platform: str, kind: str = "post", facts: dict | None = None,
          prev_own_post_at=None, now=None, media=None, *, reply_text: str | None = None, post_at=None,
          target_followers=None, target_posted_at=None, own_posts=None) -> dict:
    """The VIRAL CHECK v1 score of one post, Reel or comment (see the module doc). own_posts = [(time, pending)] of our
    own posts on the platform (M6 both ways); without it prev_own_post_at (one earlier posted time) is used."""
    text = fold(text)
    reply_text = fold(reply_text) if isinstance(reply_text, str) else None
    platform = str(platform or "").strip().lower()
    kind = kind if kind in KINDS else "post"
    ig = platform == "instagram"
    soft_ig = SOFT_INSTAGRAM if ig else None
    now_t = _t(now) or dt.datetime.now(dt.timezone.utc)
    post_t = _t(post_at)
    t_post, exact = (post_t, True) if post_t else (now_t, False)
    caps = Caps(item, facts)
    tags = cashtags(text)
    figs = dl.figures(text)
    company_tags = [t for t in tags if not caps.fund(t)]
    lks = links(text, item)
    must: dict[str, dict] = {}
    extra: dict[str, dict] = {}

    # M1, M2
    soft_m1 = SOFT_COMMENT if kind == "comment" else soft_ig
    must["M1"] = _rule(bool(tags), f"cashtags: {' '.join('$' + t for t in tags)}" if tags else "no $cashtag in the main text",
                       soft=soft_m1)
    must["M2"] = _rule(bool(figs), f"{len(figs)} number(s)" if figs else "no number in the main text")

    if kind == "comment":
        # M5, D1-D3 (VIRAL-CHECK section D)
        must["M5"] = _rule(not lks, f"a link in a comment: {dl.short(lks[0], 50)}" if lks else "no link")
        followers = _num(target_followers)
        tposted = _t(target_posted_at)
        if followers is None and tposted is None:
            must["D1"] = _rule(None, "target_followers / target_posted_at not in the draft: >= 50k followers within "
                                     "30 min cannot be checked from the text", soft=SOFT_COMMENT)
        elif followers is not None and followers < TARGET_FOLLOWERS:
            must["D1"] = _rule(False, f"the target account has {int(followers):,} followers (>= 50,000)", soft=SOFT_COMMENT)
        elif tposted is None:
            must["D1"] = _rule(None, "target_posted_at not in the draft: the 30 min window cannot be checked",
                               soft=SOFT_COMMENT)
        else:
            el = t_post - tposted
            if el < dt.timedelta(0):
                must["D1"] = _rule(None, "target_posted_at is after the comment time", soft=SOFT_COMMENT)
            elif el > TARGET_WINDOW:
                must["D1"] = _rule(False, f"{_hm(el)} after the target post{'' if exact else ' at review time'} "
                                          "(within 30 min)", soft=SOFT_COMMENT)
            elif followers is None:
                must["D1"] = _rule(None, f"{_hm(el)} after the target post; target_followers not in the draft",
                                   soft=SOFT_COMMENT)
            else:
                must["D1"] = _rule(True, f"{int(followers):,} followers, {_hm(el)} after the target post", soft=SOFT_COMMENT)
        if not item:
            must["D2"] = _rule(False, "no facts item: a comment carries 1 cashtag + 1 number from an item we hold",
                               soft=SOFT_COMMENT)
        else:
            own = set(item_cashtags(item))
            hit = [t for t in tags if t in own]
            must["D2"] = _rule(bool(hit), f"on item {dl.short(item.get('item_id'), 60)} (${hit[0]})" if hit else
                               f"no cashtag of item {dl.short(item.get('item_id'), 60)} ({', '.join('$' + t for t in sorted(own))})",
                               soft=SOFT_COMMENT)
        handles = mentions(text)
        must["D3"] = _rule(not handles, f"typed @mention: {', '.join('@' + h for h in handles)} (the platform adds the "
                                        "reply-to handle)" if handles else "no typed @mention")
    else:
        # M3
        names = [n for n in company_names(item) if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.IGNORECASE)]
        if company_tags:
            must["M3"] = _rule(True, f"company cashtag ${company_tags[0]}", soft=soft_ig)
        elif names:
            must["M3"] = _rule(True, f"names {names[0]}", soft=soft_ig)
        else:
            must["M3"] = _rule(False, "no company named (macro / market only: -15 to -19%)", soft=soft_ig)
        # M4
        if platform in WORD_PLATFORMS:
            n = dl.word_count(text)
            if n > WORDS_MAX:
                must["M4"] = _rule(False, f"{n} words (25-60)", soft=SOFT_M4_LONG)
            else:
                must["M4"] = _rule(n >= WORDS_MIN, f"{n} words (25-60)")
        else:
            must["M4"] = _rule(True, f"n/a: {platform or 'this platform'} caption (X and Threads only)", na=True)
        # M5
        bad = lks
        if ig and item and item.get("type") in FILING_TYPES:
            src = {u for u in [item.get("source_url"), *(item.get("source_urls") or [])] if isinstance(u, str) and u}
            bad = [u for u in lks if u not in src]
            if lks and not bad:
                must["M5"] = _rule(True, "only the official source link the caption must carry (compliance)", soft=soft_ig)
        if "M5" not in must:
            must["M5"] = _rule(not bad, f"a link in the main post: {dl.short(bad[0], 60)} (self-reply or bio only)" if bad
                               else "no link in the main post", soft=soft_ig)
        # M6
        must["M6"] = _m6(t_post, exact, platform, _t(prev_own_post_at), own_posts)
        # M7
        attached, _, mwhy = media_kind(media, item, kind)
        must["M7"] = _rule(attached, mwhy if attached is not False else "no own image or video attached")
        # M8 (+ the M8.3h note)
        must["M8"], x3 = _m8(item, text, t_post, exact, caps)
        if x3 is not None:
            extra["M8.3h"] = x3

    # Boosters
    bd: dict[str, dict] = {}
    _, video, mwhy = media_kind(media, item, kind)
    bd["B1"] = _rule(bool(video) if video is not None else None, "native video" if video else
                     ("media not known" if video is None else f"no video ({mwhy})"))
    bd["B2"] = _rule(len(tags) >= 3, f"{len(tags)} distinct cashtag(s)")
    if len(tags) >= 2:
        lead, why_lead = caps.top(tags[0], TOP_BROAD)
        rest = [(t, caps.top(t, TOP_BROAD)) for t in tags[1:]]
        small = [t for t, (b, _) in rest if b is False and not caps.fund(t)]
        if lead is True and small:
            bd["B3"] = _rule(True, f"broad lead ${tags[0]} + ${small[0]}")
        elif lead is None:
            bd["B3"] = _rule(None, why_lead)
        else:
            bd["B3"] = _rule(False, (f"lead ${tags[0]} is not broad ({why_lead})" if lead is False else
                                     f"broad lead ${tags[0]} but no smaller company"))
    else:
        bd["B3"] = _rule(False, "fewer than 2 cashtags")
    bd["B4"] = _b4(item, t_post, exact)
    buzz = _buzz(facts)
    hot = [t for t in tags if (buzz or {}).get(t, 0) >= BUZZ_RATIO]
    hot_small = [t for t in hot if caps.top(t, TOP_BROAD)[0] is False]
    if hot_small:
        bd["B5"] = _rule(True, f"${hot_small[0]} at {buzz[hot_small[0]]:.1f}x its usual Reddit count")
    elif hot:
        bd["B5"] = _rule(False, f"${hot[0]} is at {buzz[hot[0]]:.1f}x its usual Reddit count but broad (G3: the "
                                "retail-popular premium is for names outside the broad tiers)")
    elif buzz is None:
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
        itype = (item or {}).get("type")
        earnings = itype in EARNINGS_TYPES
        broad = {t: caps.top(t, TOP_BROAD) for t in tags}
        has_pct = bool(PCT.search(URL.sub(" ", text)))
        mover = (not earnings and len(tags) == 1 and not caps.fund(tags[0]) and has_pct and broad[tags[0]][0] is True)
        # P1 / P2 are notes where the evidence or the item does not carry a REJECT (module doc)
        offered = offered_cashtags(item)
        unavoidable = bool(item) and bool(offered) and not any(caps.top(t, TOP_BROAD)[0] is False for t in offered)
        soft_p2 = (SOFT_INSTAGRAM if ig else SOFT_P2_TYPES if itype in P2_NOTE_TYPES else
                   SOFT_P2_UNAVOIDABLE if unavoidable else None)
        if earnings:
            pd["P2"] = _rule(False, "earnings post (exempt)")
        elif not tags:
            pd["P2"] = _rule(False, "no cashtags")
        else:
            vals = [b for b, _ in broad.values()]
            if all(v is True for v in vals):
                pd["P2"] = _rule(True, f"broad-only cashtags ({' '.join('$' + t for t in tags)}) on a non-earnings post: -18%"
                                       + ("; a single broad company + a % figure (P1, -25%)" if mover else ""), soft=soft_p2)
            elif any(v is False for v in vals):
                pd["P2"] = _rule(False, "has a non-broad name")
            else:
                pd["P2"] = _rule(None, "; ".join(w for b, w in broad.values() if b is None), soft=soft_p2)
        if earnings:
            pd["P1"] = _rule(False, "earnings post (exempt)")
        elif mover:
            pd["P1"] = _rule(False, f"counted in P2: a single broad company ${tags[0]} + a % figure is a broad-only post "
                                    f"({broad[tags[0]][1]})")
        else:
            pd["P1"] = _rule(False, "not a single company + % post")
        handles = mentions(text)
        pd["P3"] = _rule(bool(handles), f"@mention in our own post: {', '.join('@' + h for h in handles)} (-20% engagement)"
                         if handles else "no @mention in the main post")
        if item is None:
            pd["P4"] = _rule(None, "no facts item: recap or not unknown", soft=soft_ig)
        elif itype in RECAP_TYPES:
            if not tags:
                pd["P4"] = _rule(False, "a recap with no cashtag at all: counted under M1 / M3 (G3 3c: the recap penalty "
                                        "is mostly the missing cashtags)", soft=soft_ig)
            else:
                pd["P4"] = _rule(not company_tags, "a market recap with index / ETF cashtags only, no company (-15%)"
                                 if not company_tags else f"recap with company cashtag ${company_tags[0]}", soft=soft_ig)
        else:
            pd["P4"] = _rule(False, "not a market recap")
    pd = {p: pd[p] for p in PENALTIES}

    fired = [p for p in PENALTIES if pd[p]["ok"] is True]
    penalties = [p for p in fired if not pd[p].get("soft")]
    fails = [c for c, r in must.items() if r["ok"] is False and not r.get("soft")]
    notes = ([c for c, r in must.items() if r["ok"] is False and r.get("soft")]
             + [c for c, r in extra.items() if r["ok"] is False]
             + [p for p in fired if pd[p].get("soft")])
    unknown = [c for c, r in must.items() if r["ok"] is None]
    n_ok = sum(1 for r in must.values() if r["ok"] is True)
    passed = not fails and not notes and not unknown and not fired
    summary = (f"M{n_ok}/{len(must)} B{len(boosters)} P{len(fired)}" + (f" ?{','.join(unknown)}" if unknown else "")
               + (f" ~{','.join(notes)}" if notes else ""))
    return {"version": VERSION, "kind": kind, "platform": platform, "item_id": (item or {}).get("item_id"),
            "post_at": t_post.isoformat(), "post_at_known": exact,
            "must": must, "extra": extra, "boosters": boosters, "booster_detail": bd,
            "reachable": reachable(item, kind, caps, buzz, bd["B4"]) if kind != "comment" else [],
            "penalties": penalties, "penalty_detail": pd, "fails": fails + penalties, "notes": notes, "unknown": unknown,
            "passed": passed, "strong": passed and len(boosters) >= BOOSTERS_MIN, "summary": summary}


def rule_of(res: dict, code: str) -> dict:
    """The detail of a must-have, an extra note rule, a booster or a penalty by code."""
    for k in ("must", "extra", "penalty_detail", "booster_detail"):
        if code in (res.get(k) or {}):
            return res[k][code]
    return {}


# ---------------------------------------------------------------------------
# Drafts (tools/grok_review.py) and answer lines

def find_item(facts: dict | None, item_id) -> dict | None:
    return next((i for i in (facts or {}).get("items") or [] if isinstance(i, dict) and i.get("item_id") == item_id), None)


def score_draft(draft: dict, facts: dict | None, kind: str, history: list[dict] | None = None, now=None) -> dict:
    """score() of a validator draft: a post {item_id, platform, text, reply_text, media_url, planned_at?, format?} or a
    comment {kind: comment, platform, text, item_id?, target_followers?, target_posted_at?, planned_at?}. history = our
    own posts (post_history records, approved-not-logged ones included and marked pending) for M6."""
    now_t = _t(now) or dt.datetime.now(dt.timezone.utc)
    post_at = _t(draft.get("planned_at")) if isinstance(draft.get("planned_at"), str) else None
    platform = str(draft.get("platform") or "").lower()
    item = find_item(facts, draft.get("item_id"))
    text = draft.get("text") if isinstance(draft.get("text"), str) else ""
    if kind == "comment":
        return score(text, item, platform, "comment", facts, None, now_t, None,
                     post_at=post_at, target_followers=draft.get("target_followers"),
                     target_posted_at=draft.get("target_posted_at") if isinstance(draft.get("target_posted_at"), str)
                     else None)
    vkind = "reel" if str(draft.get("format") or "").lower() == "reel" else "post"
    media = draft.get("media_url")
    media = media if isinstance(media, str) else ""   # a post draft without media_url has none (not "unknown")
    own = own_post_times(history, platform) if history is not None else None
    return score(text, item, platform, vkind, facts, None, now_t, media,
                 reply_text=draft.get("reply_text") if isinstance(draft.get("reply_text"), str) else None, post_at=post_at,
                 own_posts=own)


def _label(res: dict, code: str) -> str:
    return f" ({THREADS_POLICY})" if res.get("platform") == "threads" and code in X_ONLY_RULES else ""


def reject_reasons(res: dict) -> list[str]:
    """REJECT reasons: a hard must-have that fails (False, never an unknown) and every hard penalty."""
    out = [f"viral: {c} {res['must'][c]['why']}{_label(res, c)}" for c in res["must"]
           if res["must"][c]["ok"] is False and not res["must"][c].get("soft")]
    out += [f"viral: {p} {res['penalty_detail'][p]['why']}{_label(res, p)}" for p in res["penalties"]]
    return out


def note_lines(res: dict) -> list[str]:
    """Answer lines: the score (Grok copies it into the post_log), viral-weak under 2 boosters (posts / Reels; with what
    this item can reach at all), the soft rules that fail and the rules that could not be checked."""
    lines = [f"viral={res['summary']} (VIRAL CHECK v1; boosters: {' '.join(res['boosters']) or 'none'})"]
    if res["kind"] != "comment" and len(res["boosters"]) < BOOSTERS_MIN:
        reach = res.get("reachable") or []
        n = len(res["boosters"])
        if len(reach) < BOOSTERS_MIN:
            lines.append(f"viral-weak: {n} booster(s); this item can reach at most {len(reach)} "
                         f"({' '.join(reach) or 'none'}), so the floor of {BOOSTERS_MIN} is not reachable for it: not a "
                         "reason to drop the item")
        else:
            lines.append(f"viral-weak: {n} booster(s); a post needs >= {BOOSTERS_MIN}; this item can reach "
                         f"{' '.join(reach)} (native video, 3+ cashtags, a broad lead + a smaller company, <= 3 h after "
                         "the release / close, a non-broad Reddit-hot ticker, a surprise number in line 1)")
    for c in res.get("notes") or []:
        r = rule_of(res, c)
        lines.append(f"viral-note: {c} {r.get('why', '')} [{r.get('soft', 'note')}]")
    for c in res["unknown"]:
        lines.append(f"viral-unknown: {c} {res['must'][c]['why']}")
    return lines
