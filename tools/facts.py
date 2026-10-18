"""Facts feed for Grok-run brand social (D:/rtv-ops/tracks/hq/growth-roundtable-2026-10-11/GROK-SOCIAL.md §1, §3).

Usage (conda python: C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe):
  facts.py --date YYYY-MM-DD [--out FILE] [--print] [--as-of ISO]

Writes v/<date>/facts.json (schema rtv-facts/1; default --out <repo>/v/<date>/facts.json): the only facts Grok may
post for a New York market date. Every item is read from RapidTradeView's public API through select_stories.Api
(the access-policy header goes through qa_header.py; its value is never printed or written):
  congress_trade     House / Senate periodic transaction reports filed in the last 5 weekdays (weekday age 0-4),
                     listed tickers only; rows traded more than 90 days before their disclosure
                     (late_filing_over_90d) and re-filings of older reports are left out. One item per member,
                     ticker, side and report. Public feed: the newest 50 rows only (/notable/feed guest limits).
  form4_buy          material open-market buys filed in the last 5 weekdays, select_stories' rules: buys only,
                     no 10b5-1 pre-planned rows, no flagged values, listed tickers, $1M+ or a famous executive
                     (fame.json, or CEO / Chair / President of a $200B+ company). One item per person, ticker and Form 4.
  earnings_result    earnings reports published in the 24 hours before --as-of (default: now, or the end of the
                     date's New York day for a past date), with the tile label and revenue / EPS where the report
                     gives them. page_url /dashboard/<T>#earnings-history, media the ticker page's card, source_url
                     the company's SEC filing (sec.gov) or null: never the report page (G-N1 holdout, below).
  earnings_upcoming  the next weekday's reporters in our universe with a confirmed date (/earnings/tomorrow).
  picks_ready        the public picks of the list /tips/daily serves at 15:00 ET (select_stories.picks_slot: the #1
                     pick is locked and never read, so its ticker is never in this file).
  chart_pattern      the one tile /notable/pattern-showcase serves (automatic technical analysis), when its scan is in
                     the last 5 weekdays, its ticker is in our names list and it is not a #1 pick the picks list
                     exposes (for guests the #1 ticker is hidden, so this can only catch a leaked one). The pattern's
                     own text (pill, chip, key lines, points) is kept as the API writes it for our pages; the history
                     record ("past ... fell over the next 5 trading days") is left out: it is an outcome claim.
  earnings_tomorrow_roundup  per set session (before the open / after the close) of the next weekday with 2+ confirmed
                     universe reporters: up to 4 of them (largest market cap first) as cashtags; landing /earnings/tomorrow
                     (no anchor), media the /earnings card; allowed_numbers the report date and the session only.
  ptr_summary        per member and filing date with 2+ Congress items: the count of trades and up to 4 tickers (the
                     member's most newsworthy); landing the figure page #trades, media the figure card, source_urls every
                     filing's official URL (source_url only when there is one filing). Built before the per-filer cap
                     below, so it counts every trade; built only for a whole filing: the capped feed read reaches past
                     the window start and no row of that member's filing date (or of its filings) was filtered out
                     (other side, late filing, re-filing, not listed, no amount, ...). Otherwise skipped:
                     left_out.ptr_summary_incomplete says why. A partial count is never published as a filing's total.
  moves_like         /moves-like/<T> for up to 5 tickers a day of the day's other items (round robin over
                     congress_trade, form4_buy, earnings_result, earnings_upcoming, chart_pattern; 0.5 s apart): the
                     peers the stock card lists with Sync >= 65 (Close / Tight), Sync and band as the card shows them.
                     not_covered, disabled, unavailable or no peer at the floor: no item. With --previous (the day's
                     published file) a ticker already looked up today is not asked again: its item is carried over.
  market pillars     (HQ 2026-10-18, tools/market_facts.py): market_move (P1), mega_mover (P2), congress_flow /
                     insider_flow (P3), reddit_buzz (P4), earnings_week_preview / earnings_reaction (P5), sector_rotation
                     (P6), breadth_day / basket_week (P7), from GET /market/pictures and /market/flows (2 GETs a pass), each
                     only when its trigger fires; their media is the pinned share card (card {panel, url, live_url, date,
                     fingerprint, file, sha256}; tools/pin_cards.py fills url / media in the runner, or drops the item).
Every item also carries pillar, cap_tier, in_500, context_numbers / context_tickers (numbers and cashtags a post may add:
the company's cap, its last session move, the 30-day insider / Congress totals; computed here, checked by the validator),
angles (3 first-line seeds), trigger and cooldown (our own posts, tools/post_history.py: the same item posted on x,
instagram and threads, its ticker on all three within 3 trading days, or its filer within 7 days -> left_out.gates).
Gates before the rank: weekend facts do not replay filings older than the last weekday session; a form4_buy needs cap
>= $2B, a fame person, or $10M+ at cap >= $300M.
Top 8 (HQ review 2026-10-18, diversify_top): the first 8 items of the file are a varied menu: at most one small / micro
cap, at most 2 session-map items (market_move, mega_mover, sector_rotation, breadth_day, basket_week: one selloff cannot
fill the menu), no headline ticker or headline number of one top-8 item repeated by another (item.headline), and at least
4 distinct pillars when the day has them. Every item carries top8 (bool) and, below the top 8, top8_out (why).
Content (tools/claims.py): every item carries claims (the comparative / superlative statements it backs: led, biggest,
worst, most, only, first, ...), ticker_sectors / ticker_names (from the market map) and, where needed, scoped_numbers and
card_message; each item's own facts_text and angles must pass claims.content_reasons (an angle that fails is dropped, an
item whose facts_text fails is not published: errors "self-check: ..."). Caps are map-first: an item's market_cap_usd is
the market map's when the company is in it (market_cap_source "market_map"; the feed's own value stays in
market_cap_feed_usd), so one company shows one cap across item types.
chart_pattern and moves_like carry banned_words of their own (PREDICTION_WORDS): descriptive wording only.
Each item carries item_id, type, ticker, name / office, amount text as our pages show it, dates, the official
source_url, page_url (UTM built in; "{platform}" is a literal placeholder Grok fills with x or instagram),
allowed_numbers (every numeric token a post may print), must_include, a one-line facts_text and media: the
images a post may carry ([{url, kind: image, alt}], the landing page's Open Graph card <SITE><page>/opengraph-image;
earnings_upcoming: <SITE>/earnings/opengraph-image; never fetched here). The runner (tools/card_reel.py, via
daily_common.ps1 Publish-Facts) may append one {url: <Pages>/v/<date>/cards/<item_id>/reel_9x16.mp4, kind: reel, alt}
a day to one item: its share card as a 9:16 Reel for Instagram.
Rank (audience rank, HQ 2026-10-18; replaces Growth B1's): every item carries rank and rank_why; the items are sorted by
rank, highest first: base per type + recognisability (cap tier; market-level +4; a known person: fame.json or a CEO / CFO /
Chair title) + magnitude + freshness - novelty (our own recent posts). See the "Audience rank" section. At
most one Congress item per filer a day, congress_trade and ptr_summary alike (the highest-ranked; one filer, one post);
the rest are counted in left_out.per_filer_cap (dropped, and per type).
An empty type is valid: items [] and reasons say why. Nothing is estimated or invented (No Fallbacks).
G-N1 holdout (tracks/growth/bets/g-n1-holdout-prereg.md, Amendment 2): for a date before 2026-11-21 no item may carry
a /earnings/reports/ URL in any field; an item that does is not built (errors "not built: ...", left_out.g_n1_holdout).
Errors name a report by its ticker and the HTTP status, never its path; the whole document is screened before writing.

Exit codes: 0 written, every core source loaded (a failed chart_pattern / moves_like read is in errors, its item
dropped); 4 written, but a core source failed (ticker list, congress, insiders, earnings, picks: partial_sources);
5 not written: some field of the document (an item, an error, a reason, anything) carries /earnings/reports/ inside
the G-N1 holdout (the paths are printed, never the text); anything else: crashed / not written (1, or 2 for a usage
error).

  facts.py --compare-items OLD NEW    OLD / NEW: a file or an https URL (Pages; fetched past its cache). Exit 0 when
                                      both carry the same items (item_id + dedupe_key + media URLs: a card Reel the
                                      runner adds counts; so does a change of the rules block, i.e. a pipeline change;
                                      generated_at and the rest do not), 1 when they differ, 2 when one cannot be read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from urllib.parse import quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402
import claims as cl  # noqa: E402
import market_facts as mk  # noqa: E402
import post_history as ph  # noqa: E402
import select_stories as ss  # noqa: E402

SCHEMA = "rtv-facts/1"
SITE = ss.SITE
DISCLAIMER = "Not investment advice."
BANNED_WORDS = ["insider trading", "guaranteed", "moon", "buy now", "will rise", "price target", "to the moon",
                "breakout coming", "about to", "set to",
                # plain advice wording (comments and posts alike): no calls to act
                "should buy", "should sell", "load up", "buy the dip", "time to buy", "time to sell", "don't miss",
                "dont miss", "easy money", "can't lose", "cant lose", "free money", "sell now", "get in now",
                # stocks and ETFs only: no crypto talk, also on items about crypto-adjacent miners (MARA, RIOT, ...)
                "bitcoin", "btc", "crypto", "cryptocurrency", "ethereum", "blockchain"]
PREDICTION_WORDS = ["will", "going to"]  # per item (chart_pattern, moves_like): descriptive wording only
MAX_LEN = {"x": 270, "threads": 500}
PLATFORMS = ["x", "instagram", "threads"]
PLATFORM_PLACEHOLDER = "{platform}"
PARTIAL = 4  # exit code: written, but a source failed (2 is argparse's usage error)
HOLDOUT_LEAK = 5  # exit code: not written, the document carries a report page inside the G-N1 holdout
TYPES = ("congress_trade", "form4_buy", "earnings_result", "earnings_upcoming", "picks_ready", "chart_pattern", "moves_like",
         "earnings_tomorrow_roundup", "ptr_summary", *mk.MARKET_TYPES)
# Roundups (Growth B1 2026-10-12): the only kinds whose posts may carry several cashtags of their own (grok_review.py),
# at most ROUNDUP_MAX_TICKERS. moves_like (its peers) and picks_ready (the public picks) keep their own ticker lists.
ROUNDUP_TYPES = ("earnings_tomorrow_roundup", "ptr_summary")
ROUNDUP_MAX_TICKERS = 4
ROUNDUP_SESSIONS = ("bmo", "amc")  # a roundup groups one set session; "time not announced" rows are no session
WINDOW_WEEKDAYS = 4  # weekday age 0..4 = the last 5 weekdays
RESULT_HOURS = 24
# Earnings sanity hold (Growth 2026-10-16): a reported figure more than 40% away from its consensus has so far always been
# a basis mismatch in the report data (PGR revenue $7.43B vs $22.51B, FMC $125M vs $867M, FHN $407M vs $890M), never a
# real miss. Such an item is not published (left_out.consensus_mismatch_hold) until the report data is checked.
# EPS: only when |consensus| >= $0.25 (small EPS bases swing past 40% on real surprises).
HELD_REPORTS_FILE = Path(__file__).resolve().parent / "held_reports.json"


def held_reports() -> dict:
    """{report id: why} of reports held out by hand (tools/held_reports.json); {} when the file is absent."""
    try:
        data = json.loads(HELD_REPORTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: str(v) for k, v in data.items() if not k.startswith("_")} if isinstance(data, dict) else {}


SANITY_MAX_REL = 0.40
# Revenue is tighter: an unverified quarterly revenue more than 20% off its estimate has been a basis mismatch every
# time we checked (TFC 10-16: $3.75B vs $5.36B, NII vs total revenue); real revenue surprises that large are rare and
# get verified (NRIX). Holding one costs a post, publishing one is a public false miss.
SANITY_REVENUE_MAX_REL = 0.20
SANITY_EPS_MIN_BASE = 0.25


def not_comparable_reason(m) -> str | None:
    """Why a results metric must not be published as the quarter's figure, or None. The report data marks it
    `not_compared` (basis_mismatch, full_year_only, period_unconfirmed, sec_disagrees, sec_period_mismatch; HQ
    2026-10-16), or its figure covers the full fiscal year (`period` full_year: a Q4 item's full-year GAAP EPS), or it
    was not independently verified (`verification` unverified: the backend reports it but never compares it)."""
    if not isinstance(m, dict):
        return None
    if m.get("not_compared"):
        return str(m["not_compared"])
    if m.get("period") == "full_year":
        return "full_year"
    if m.get("verification") == "unverified":
        return "unverified"
    return None


def comparable(m) -> dict:
    """A results metric, or {} when not_comparable_reason() says it must not be published."""
    return {} if not isinstance(m, dict) or not_comparable_reason(m) else m


def sanity_mismatch(res: dict) -> list[str]:
    """The comparable metrics of a report's results whose reported value is more than SANITY_MAX_REL away from
    consensus (a metric the report data already marks not_compared is left out, not held; a `verified` figure, backed
    by the provider's own actual, is a real surprise and never held)."""
    out = []
    for key, min_base in (("revenue", 0.0), ("eps_adjusted", SANITY_EPS_MIN_BASE), ("eps_gaap", SANITY_EPS_MIN_BASE)):
        m = comparable(res.get(key))
        if m.get("verification") == "verified":  # the provider's own actual backs the figure (NRIX $673M, HQ 10-16)
            continue
        rep, con = m.get("reported"), m.get("consensus")
        if not (isinstance(rep, (int, float)) and isinstance(con, (int, float))) or con == 0 or abs(con) < min_base:
            continue
        if abs(rep / con - 1) > (SANITY_REVENUE_MAX_REL if key == "revenue" else SANITY_MAX_REL):
            out.append(key)
    return out
PICKS_SLOT_ET = "15:00"  # the picks post time (GROK-SOCIAL.md §2)
OFFICIAL_PTR_HOSTS = ("disclosures-clerk.house.gov", "efdsearch.senate.gov")
HOURS = {"bmo": "before the open", "amc": "after the close", "dmh": "during market hours"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MINUS = "\u2212"
# Form 4 relationships as our pages label them (frontend/src/lib/roleTitle.ts); an officer's own title is kept as filed.
ROLE_LABELS = {"officer": "Officer", "director": "Director", "ten_pct": "10% owner", "other": "Insider"}
EN_DASH = "\u2013"
SHOWCASE = "/notable/pattern-showcase"
MOVES_LIKE_MAX = 5
MOVES_LIKE_GAP_S = 0.5
MOVES_LIKE_SESSIONS = 60  # shared/lib/movesLike.ts MOVES_LIKE_SYNC_SESSIONS
MOVES_LIKE_SYNC_FLOOR = 65  # movesLike.ts MOVES_LIKE_BAND_CLOSE: Close and Tight peers only (Growth lead 2026-10-11)
MOVES_LIKE_KEEP = ("item", "not_covered", "no_peer", "below_floor")  # answers a later run of the day does not ask again
CORE_TYPES = ("congress_trade", "form4_buy", "earnings_result", "earnings_upcoming", "picks_ready")
BAND_LABELS = {"tight": "Tight", "close": "Close", "loose": "Loose"}  # movesLike.ts bandLabel
MOVES_LIKE_SUBJECT_TYPES = ("congress_trade", "form4_buy", "earnings_result", "earnings_upcoming", "chart_pattern")
SLEEP = time.sleep


# ---------------------------------------------------------------------------
# Number formats, as our pages print them

def js_fixed(x: float, n: int) -> str:
    """JavaScript Number.prototype.toFixed: the exact binary value, ties away from zero."""
    return str(Decimal(x).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def _trim_notable(s: str) -> str:
    """frontend/src/lib/notable.ts trimZeros."""
    s = re.sub(r"\.0+$", "", s)
    return re.sub(r"(\.\d*?)0+$", r"\1", s)


def usd_compact(v: float) -> str:
    """notable.ts fmtUsdCompact (Smart Money feed and figure pages): $2.42M, $15K, $500."""
    a, sign = abs(v), "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}${_trim_notable(js_fixed(a / 1e9, 2))}B"
    if a >= 1e6:
        return f"{sign}${_trim_notable(js_fixed(a / 1e6, 2))}M"
    if a >= 1e3:
        return f"{sign}${_trim_notable(js_fixed(a / 1e3, 1))}K"
    return f"{sign}${int(Decimal(a).quantize(Decimal(1), rounding=ROUND_HALF_UP))}"


def trade_amount(amount: dict) -> str | None:
    """notable.ts fmtTradeAmount: value, else the low-high range ("$15K–$50K"); None when there is no amount."""
    if isinstance(amount.get("value_usd"), (int, float)):
        return usd_compact(float(amount["value_usd"]))
    lo, hi = amount.get("low"), amount.get("high")
    if lo is not None and hi is not None:
        return usd_compact(lo) if lo == hi else f"{usd_compact(lo)}{EN_DASH}{usd_compact(hi)}"
    return None


def usd_whole(v: float) -> str:
    """congressTracker.ts fmtAmountRange's whole dollars: $15,001."""
    return f"${int(Decimal(v).quantize(Decimal(1), rounding=ROUND_HALF_UP)):,}"


def exact_range(lo, hi) -> str | None:
    """congressTracker.ts fmtAmountRange (/congress-trades): "$15,001–$50,000"."""
    if lo is not None and hi is not None:
        return usd_whole(lo) if lo == hi else f"{usd_whole(lo)}{EN_DASH}{usd_whole(hi)}"
    if lo is not None:
        return f"{usd_whole(lo)}+"
    if hi is not None:
        return f"up to {usd_whole(hi)}"
    return None


def _trim_reports(s: str, min_decimals: int) -> str:
    """earningsReports.ts trimZeros."""
    if "." not in s:
        return s
    out = s.rstrip("0")
    decimals = len(out) - out.index(".") - 1
    if decimals < min_decimals:
        out += "0" * (min_decimals - decimals)
    return out[:-1] if out.endswith(".") else out


def money_compact(v: float) -> str:
    """earningsReports.ts fmtMoneyCompact (report pages): $20.19B, $286M, $45.3M, $820K."""
    a, sign = abs(v), MINUS if v < 0 else ""
    if a >= 1e9:
        return f"{sign}${_trim_reports(js_fixed(a / 1e9, 2), 1)}B"
    if a >= 1e8:
        return f"{sign}${int(Decimal(a / 1e6).quantize(Decimal(1), rounding=ROUND_HALF_UP))}M"
    if a >= 1e7:
        return f"{sign}${_trim_reports(js_fixed(a / 1e6, 1), 1)}M"
    if a >= 1e6:
        return f"{sign}${_trim_reports(js_fixed(a / 1e6, 2), 1)}M"
    if a >= 1e3:
        return f"{sign}${int(Decimal(a / 1e3).quantize(Decimal(1), rounding=ROUND_HALF_UP))}K"
    return f"{sign}${_trim_reports(js_fixed(a, 2), 0)}"


def eps_text(v: float) -> str:
    """earningsReports.ts fmtEps: $1.72, −$0.12."""
    return f"{MINUS if v < 0 else ''}${js_fixed(abs(v), 2)}"


def date_forms(iso: str | None) -> list[str]:
    """2026-10-07 -> ["2026-10-07", "Oct 7, 2026", "Oct 7"] (our pages print "Oct 7, 2026")."""
    if not iso:
        return []
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso)
    if not m:
        return [iso]
    md = f"{MONTHS[int(m.group(2)) - 1]} {int(m.group(3))}"
    return [iso[:10], f"{md}, {m.group(1)}", md]


SHORT_DATE = re.compile(rf"\b(?:{'|'.join(MONTHS)}) \d{{1,2}}(?:, \d{{4}})?\b")


def short_dates(*texts: str | None) -> list[str]:
    """"Sep 28" / "Sep 28, 2026" as the API's pattern text writes them."""
    return [m.group(0) for t in texts if t for m in SHORT_DATE.finditer(t)]


def move_pct(x: float) -> str:
    """movesLike.ts fmtMovePct: "−6.2%", "+6.4%", and "0.0%" when it rounds to zero."""
    if abs(x) < 0.05:
        return "0.0%"
    return f"{MINUS if x < 0 else '+'}{js_fixed(abs(x), 1)}%"


def digit_words(*texts: str | None) -> list[str]:
    """Words with a digit in a name or label (e.g. "3M"), so a post may print the name as filed."""
    return [w.strip(".,;:()") for t in texts if t for w in t.split() if re.search(r"\d", w)]


def money_tokens(label: str | None) -> list[str]:
    """Dollar / percent tokens inside an API label ("Beat by $1.27B" -> "$1.27B")."""
    return re.findall(rf"{MINUS}?-?\$\d[\d,]*(?:\.\d+)?[KMBT]?|\d+(?:\.\d+)?%", label or "")


def uniq(xs) -> list[str]:
    out: list[str] = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out


# ---------------------------------------------------------------------------
# Item shape

def item_id(date: str, kind: str, ticker: str, key: str) -> str:
    return f"{date}-{kind.replace('_', '-')}-{ticker.upper().replace('.', '-')}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:6]}"


# Section anchors live on prod since HQ PR #466 (2026-10-11); the fragment goes after the query string.
# #earnings-history: the ticker page's earnings history section (<section id="earnings-history">, checked on
# /dashboard/JPM 2026-10-12). Applied only to /dashboard/<T> pages.
KIND_ANCHORS = {"moves_like": "#moves-like", "chart_pattern": "#pattern",
                "earnings_result": "#earnings-history", "earnings_upcoming": "#earnings-history"}


def anchor_for(kind: str, path: str) -> str:
    if path == "/" and kind in mk.PANEL_OF:  # the home page's Market section, one anchor per panel (HQ 10-18)
        return f"#{mk.PANEL_OF[kind]}"
    if path.startswith("/smart-money/figures/"):
        return "#trades"
    if path.startswith("/dashboard/"):
        return KIND_ANCHORS.get(kind, "")
    return ""


def page_url(path: str, iid: str, kind: str = "") -> str:
    return (f"{SITE}{path}?utm_source={PLATFORM_PLACEHOLDER}&utm_medium=social&utm_campaign=grok"
            f"&utm_content={iid}{anchor_for(kind, path)}")


def make_item(date: str, kind: str, ticker: str | None, key: str, path: str, **fields) -> dict:
    iid = item_id(date, kind, ticker or "LIST", key)
    item = {
        "item_id": iid, "type": kind, "ticker": ticker, "tickers": [ticker] if ticker else [],
        "name": None, "office": None, "amount_text": None, "traded": [], "filed": None,
        "source_url": None, "page_url": page_url(path, iid, kind), "allowed_numbers": [],
        "must_include": [DISCLAIMER], "facts_text": "", "dedupe_key": key,
    }
    item.update(fields)
    item["allowed_numbers"] = uniq(item["allowed_numbers"])
    if "media" not in fields:
        item["media"] = [og_media(kind, path, item["facts_text"])]
    return item


class HoldoutLeak(AssertionError):
    """An item carries a /earnings/reports/ URL inside the G-N1 holdout: that item is not built."""


def assert_no_report_page(item: dict, target: dt.date) -> None:
    """G-N1 holdout (select_stories.G_N1_HOLDOUT_END): before 2026-11-21 no item may carry a report page URL anywhere
    (page_url, source_url, media, facts_text, any other field)."""
    if ss.g_n1_holdout(target) and ss.report_page_in(item):
        bad = sorted(k for k, v in item.items() if ss.report_page_in(v))
        raise HoldoutLeak(f"{item.get('item_id')}: {', '.join(bad)} carries a report page URL ({ss.G_N1_REASON})")


def screen_holdout(items: list[dict], target: dt.date) -> tuple[list[dict], list[str]]:
    """(items that pass assert_no_report_page, one reason per item dropped)."""
    kept, dropped = [], []
    for it in items:
        try:
            assert_no_report_page(it, target)
        except HoldoutLeak as e:
            dropped.append(str(e))
            continue
        kept.append(it)
    return kept, dropped


def holdout_doc_leaks(doc: dict, target: dt.date) -> list[str]:
    """G-N1 holdout: the paths in the whole facts document (items, errors, reasons, left_out, any field) that carry a
    report page; [] after the holdout. main() does not write a document that has one."""
    return ss.report_page_paths(doc) if ss.g_n1_holdout(target) else []


def og_media(kind: str, path: str, facts_text: str) -> dict:
    """The landing page's own Open Graph card (a 1200x630 PNG the site renders; not fetched here).
    earnings_tomorrow_roundup lands on /earnings/tomorrow, whose card is the /earnings one; a single-ticker item uses its
    ticker's own card, which names the company (HQ 10-12: the week card did not show DPZ on the DPZ post)."""
    page = ("/earnings" if kind == "earnings_tomorrow_roundup"
            else path.split("?")[0].split("#")[0].rstrip("/"))
    return {"url": f"{SITE}{page}/opengraph-image", "kind": "image", "alt": " ".join(str(facts_text or "").split())}


def official(url: str | None, hosts: tuple[str, ...]) -> bool:
    try:
        p = urlsplit(url or "")
    except ValueError:
        return False
    return p.scheme == "https" and (p.hostname or "").lower() in hosts


# ---------------------------------------------------------------------------
# Congress

def range_tops(rows: list[dict]) -> float | None:
    """The top of each row's amount range (its low when it has no top), summed: what rank() sizes a Congress item by."""
    tops = [hi if hi is not None else lo for r in rows
            for lo, hi in [((r.get("amount") or {}).get("low"), (r.get("amount") or {}).get("high"))]
            if isinstance(hi if hi is not None else lo, (int, float))]
    return float(sum(tops)) if tops else None


def window_start(target: dt.date) -> dt.date:
    """The oldest date of weekday age <= WINDOW_WEEKDAYS (the last 5 weekdays)."""
    since = target
    while ss.weekday_age(since - dt.timedelta(days=1), target) <= WINDOW_WEEKDAYS:
        since -= dt.timedelta(days=1)
    return since


def congress_items(api, target: dt.date, names: dict[str, str]) -> tuple[list[dict], dict, str | None, dict]:
    """(items, left_out counts, feed error, coverage). coverage tells ptr_summary_items whether a filing's count is
    whole: the window start, the oldest disclosure date the capped public read reached (the feed is disclosure_date
    desc) and, per member and filing date and per filing URL, the Congress rows the filters below left out."""
    since = window_start(target)
    rows, err = ss.fetch_feed(api, "congress", since)
    left = {"rows_read": len(rows), "out_of_window": 0, "not_congress": 0, "other_side": 0, "late_filing_over_90d": 0,
            "refiles_older_report": 0, "bad_date": 0, "not_listed": 0, "no_amount": 0, "no_official_source": 0}
    read_dates = [str(r["disclosure_date"])[:10] for r in rows if isinstance(r, dict) and r.get("disclosure_date")]
    coverage: dict = {"since": since.isoformat(), "oldest_read": min(read_dates) if read_dates else None, "error": err,
                      "dropped": []}

    def drop(it: dict, reason: str, fd: dt.date | None) -> None:
        """Count a left-out Congress row; remember its member, filing date and filing URL for summary_gaps."""
        left[reason] += 1
        src = it.get("source_url")
        coverage["dropped"].append({"slug": it["figure"].get("slug"), "filed": fd.isoformat() if fd else None,
                                    "src": src if isinstance(src, str) and src else None, "reason": reason})

    groups: dict[tuple, list[dict]] = {}
    for it in rows:
        if not isinstance(it, dict) or not isinstance(it.get("figure"), dict) or it["figure"].get("kind") != "politician":
            left["not_congress"] += 1
            continue
        filed = it.get("disclosure_date")
        try:
            fd = ss.d(filed) if filed else None
        except ValueError:
            fd = None
        if fd is None:  # no readable filing date: it may belong to any filing with its URL
            drop(it, "out_of_window", None)
            continue
        if fd > target or ss.weekday_age(fd, target) > WINDOW_WEEKDAYS:
            left["out_of_window"] += 1  # another filing date: not part of any summary of this window
            continue
        if it.get("side") not in ("buy", "sell"):
            drop(it, "other_side", fd)
            continue
        if it.get("transaction_date"):
            try:
                lag = (fd - ss.d(it["transaction_date"])).days
            except ValueError:
                drop(it, "bad_date", fd)
                continue
            if lag > ss.CONGRESS_MAX_FILING_LAG_DAYS:
                drop(it, "late_filing_over_90d", fd)
                continue
        if it.get("refiles_older_report"):
            drop(it, "refiles_older_report", fd)
            continue
        ticker = ss.primary_ticker(it.get("ticker"), names)
        if not ss.listed(ticker, names):
            drop(it, "not_listed", fd)
            continue
        if trade_amount(it.get("amount") or {}) is None:
            drop(it, "no_amount", fd)
            continue
        if not official(it.get("source_url"), OFFICIAL_PTR_HOSTS):
            drop(it, "no_official_source", fd)
            continue
        groups.setdefault((it["figure"].get("slug"), ticker, it["side"], it["source_url"]), []).append(it)

    items = []
    date = target.isoformat()
    for (slug, ticker, side, src), rs in groups.items():
        fig = rs[0]["figure"]
        filed = max(r["disclosure_date"][:10] for r in rs)
        traded = sorted({r["transaction_date"][:10] for r in rs if r.get("transaction_date")})
        amounts = [trade_amount(r.get("amount") or {}) for r in rs]
        amount_text = amounts[0] if len(rs) == 1 else "; ".join(amounts)
        exact = [exact_range((r.get("amount") or {}).get("low"), (r.get("amount") or {}).get("high")) for r in rs]
        ends = [usd_compact(v) for r in rs for v in ((r.get("amount") or {}).get("low"), (r.get("amount") or {}).get("high")) if v is not None]
        ends_exact = [usd_whole(v) for r in rs for v in ((r.get("amount") or {}).get("low"), (r.get("amount") or {}).get("high")) if v is not None]
        chamber = (fig.get("chamber") or "").lower()
        title = {"house": "U.S. Representative", "senate": "U.S. Senator"}.get(chamber, "Member of Congress")
        tag = "-".join(x for x in [(fig.get("party") or "")[:1], fig.get("state") or ""] if x)
        office = f"{title}{f' ({tag})' if tag else ''}"
        owners = sorted({r.get("owner") for r in rs if r.get("owner") and r.get("owner") != "self"})
        company = names.get(ticker) or names.get(ticker.replace(".", "-"))
        doc = (src.rstrip("/").rsplit("/", 1)[-1]).split(".")[0]
        key = f"ptr:{doc}:{ticker}:{side}"
        verb = "a purchase" if side == "buy" else "a sale"
        if len(rs) > 1:
            verb = f"{len(rs)} {'purchases' if side == 'buy' else 'sales'}"
        facts_text = (f"{title} {fig.get('display_name')}{f' ({tag})' if tag else ''} disclosed {verb} of {ticker}"
                      f"{f' ({company})' if company else ''}, {amount_text}"
                      f"{', traded ' + ', '.join(traded) if traded else ''}; filed {filed}"
                      f"{' (owner: ' + ', '.join(owners) + ')' if owners else ''}.")
        items.append(make_item(
            date, "congress_trade", ticker, key, f"/smart-money/figures/{slug}",
            name=fig.get("display_name"), office=office, company=company, side=side, owner=owners or ["self"],
            figure_slug=slug, amount_text=amount_text, amount_exact_text="; ".join(e for e in exact if e), rows=len(rs),
            amount_top_usd=range_tops(rs),
            traded=traded, filed=filed, source_url=src, facts_text=facts_text,
            allowed_numbers=[*amounts, *ends, *[e for e in exact if e], *ends_exact, *date_forms(filed),
                             *(f for t in traded for f in date_forms(t)), str(len(rs)) if len(rs) > 1 else None,
                             *digit_words(fig.get("display_name"), company)]))
    items.sort(key=lambda x: (x["filed"], x["ticker"]), reverse=True)
    return items, left, err, coverage


# ---------------------------------------------------------------------------
# Form 4

def form4_items(api, target: dt.date, names: dict[str, str], fame: dict) -> tuple[list[dict], dict, list[str]]:
    trades, gathered, errors = ss.gather_trades(api, target, WINDOW_WEEKDAYS, names, fame, pages=1)
    ins = [t for t in trades if t.kind == "insider"]
    dropped = {"below_minimum": 0}
    kept = ss.rank_trades(api, ins, target, fame, [], dropped) if ins else []
    rows_by_id = {}
    feed, _ = ss.fetch_feed(api, "insiders", target)  # cached: the same public read gather_trades made
    for r in feed:
        if isinstance(r, dict):
            rows_by_id[r.get("trade_id")] = r
    left = {"rows_read": len(feed), "filings_passing_filters": len(ins), "below_minimum": dropped["below_minimum"],
            "not_open_market": gathered.get("not_open_market", 0), "no_sec_index": 0}
    items = []
    date = target.isoformat()
    for t in sorted(kept, key=lambda t: (t.filed, t.value_usd), reverse=True):
        acc, index = ss.sec_index_url(t.api_source_url)
        if not index:
            left["no_sec_index"] += 1
            continue
        row_amounts = [usd_compact(float(rows_by_id[i]["amount"]["value_usd"])) for i in t.trade_ids
                       if i in rows_by_id and isinstance((rows_by_id[i].get("amount") or {}).get("value_usd"), (int, float))]
        total = usd_compact(t.value_usd)
        traded = sorted(set(x[:10] for x in t.traded))
        filed = t.filed.isoformat()
        role = ROLE_LABELS.get(t.role or "", t.role or "Insider")
        company = t.company
        office = f"{role}{f' at {company}' if company else ''}"
        how = "an open-market purchase" if t.rows == 1 else f"{t.rows} open-market purchases"
        facts_text = (f"{t.name} ({office}) reported {how} of {t.ticker} totaling {total} on a Form 4 filed {filed}"
                      f"{', traded ' + ', '.join(traded) if traded else ''}.")
        items.append(make_item(
            date, "form4_buy", t.ticker, f"form4:{acc}:{t.ticker}", f"/smart-money/figures/{t.slug}",
            name=t.name, office=office, company=company, side="buy", accession=acc, rows=t.rows, figure_slug=t.slug,
            amount_top_usd=float(t.value_usd), market_cap_usd=t.market_cap, famous_person=t.famous_person,
            amount_text=total, row_amounts=row_amounts, traded=traded, filed=filed, source_url=index,
            facts_text=facts_text,
            allowed_numbers=[total, *row_amounts, str(t.rows) if t.rows > 1 else None, *date_forms(filed),
                             *(f for x in traded for f in date_forms(x)), *digit_words(t.name, company, role)]))
    return items, left, errors


# ---------------------------------------------------------------------------
# Earnings

def _ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def fiscal_tokens(label: str | None, quarter=None, year=None) -> list[str]:
    out = [label] if label else []
    for m in re.finditer(r"\b(?:Q[1-4](?:\s+\d{4})?|FY\d{4}|\d{4})\b", label or ""):
        out.append(m.group(0))
    if quarter:
        out.append(f"Q{quarter}")
        if year:
            out += [f"Q{quarter} {year}", f"FY{year}"]
    return out


def api_status(err: str | None, path: str) -> str | None:
    """Api.get's error without its path ("<path>: HTTP 503" -> "HTTP 503"): a report's path never goes in an error
    (G-N1 holdout; the errors and reasons are published in facts.json)."""
    if not err:
        return None
    return err[len(path) + 2:] if err.startswith(f"{path}: ") else err


def result_items(api, target: dt.date, as_of: dt.datetime) -> tuple[list[dict], dict, list[str]]:
    path = "/earnings/reports/archive"
    data, err = api.get(path)
    if err or not isinstance(data, dict) or not isinstance(data.get("reports"), list):
        return [], {}, [f"earnings report archive: {api_status(err, path) or 'unreadable response'}"]
    lo = as_of - dt.timedelta(hours=RESULT_HOURS)
    # A report published in the window was released at most a few days before it (release_date is a NY date).
    cands = [r for r in data["reports"] if isinstance(r, dict) and r.get("id") and r.get("summary_status") == "ready"
             and r.get("release_date") and lo.date() - dt.timedelta(days=4) <= ss.d(r["release_date"]) <= as_of.date()]
    left = {"archive_reports": len(data["reports"]), "recent_ready": len(cands), "outside_24h": 0, "unreadable": 0}
    errors: list[str] = []
    items = []
    date = target.isoformat()
    held = held_reports()
    for tile in cands:
        upd = _ts(tile.get("updated_at"))
        if upd is not None and upd <= lo:  # published_at <= updated_at: published before the window, no need to read it
            left["outside_24h"] += 1
            continue
        path = f"/earnings/reports/{tile['id']}"
        full, ferr = api.get(path)
        if ferr or not isinstance(full, dict):
            left["unreadable"] += 1
            errors.append(f"earnings report {tile.get('ticker') or '(no ticker)'}: "
                          f"{api_status(ferr, path) or 'unreadable response'}")
            continue
        pub = _ts(full.get("published_at"))
        if pub is None or not (lo < pub <= as_of):
            left["outside_24h"] += 1
            continue
        ticker = full.get("ticker") or tile.get("ticker")
        if not ticker:
            left["no_ticker"] = left.get("no_ticker", 0) + 1
            continue
        res = full.get("results") or {}
        why = held.get(str(full.get("id") or tile.get("id")))
        if why:  # held by hand until HQ / Growth clear the report data
            left["consensus_mismatch_hold"] = left.get("consensus_mismatch_hold", 0) + 1
            left.setdefault("held", []).append(f"{ticker}: held by hand ({why})")
            continue
        bad = sanity_mismatch(res)
        if bad:  # not a source failure (no partial_sources): the item is held, and left_out says which and why
            left["consensus_mismatch_hold"] = left.get("consensus_mismatch_hold", 0) + 1
            left.setdefault("held", []).append(f"{ticker}: {'/'.join(bad)} reported vs consensus differs by more than "
                                               f"{int(SANITY_REVENUE_MAX_REL * 100)}% (revenue) / "
                                               f"{int(SANITY_MAX_REL * 100)}% (EPS) (report data to check)")
            continue
        dropped = [f"{k} ({not_comparable_reason(res[k])})" for k in ("revenue", "eps_adjusted", "eps_gaap")
                   if isinstance(res.get(k), dict) and not_comparable_reason(res[k])]
        results: dict = {}
        nums: list[str | None] = []
        rev = comparable(res.get("revenue"))
        if any(rev.get(k) is not None for k in ("reported", "label", "verdict")):
            results["revenue"] = {k: v for k, v in {
                "reported": money_compact(rev["reported"]) if isinstance(rev.get("reported"), (int, float)) else None,
                "consensus": money_compact(rev["consensus"]) if isinstance(rev.get("consensus"), (int, float)) else None,
                "label": rev.get("label"), "verdict": rev.get("verdict")}.items() if v is not None}
        # GAAP EPS stands in only when the release has no adjusted EPS at all: an adjusted figure the report data could
        # not compare (period, basis, SEC check) leaves the GAAP figure of the same release just as doubtful.
        adj = res.get("eps_adjusted")
        if isinstance(adj, dict) and any(adj.get(k) is not None for k in ("reported", "label", "verdict")):
            # the release's own wording minus a trailing footnote marker ("...per common share(1)")
            eps, basis = comparable(adj), re.sub(r"\s*\(\d{1,2}\)\s*$", "", adj.get("basis_label") or "") or "Adjusted EPS"
        else:
            eps, basis = comparable(res.get("eps_gaap")), "GAAP EPS"
        if any(eps.get(k) is not None for k in ("reported", "label", "verdict")):
            results["eps"] = {k: v for k, v in {
                "basis": basis,
                "reported": eps_text(eps["reported"]) if isinstance(eps.get("reported"), (int, float)) else None,
                "consensus": eps_text(eps["consensus"]) if isinstance(eps.get("consensus"), (int, float)) else None,
                "label": eps.get("label"), "verdict": eps.get("verdict")}.items() if v is not None}
        if dropped:
            left["not_compared"] = left.get("not_compared", 0) + len(dropped)
            left.setdefault("not_compared_metrics", []).append(f"{ticker}: {', '.join(dropped)}")
            # A release that lost a figure and kept nothing the report data compared is suspect as a whole (PGR's
            # monthly report, FMC): held. One that still has a compared figure (FHN's EPS beat) publishes that only.
            if not any(m.get("verdict") for m in results.values()):
                left["consensus_mismatch_hold"] = left.get("consensus_mismatch_hold", 0) + 1
                left.setdefault("held", []).append(f"{ticker}: {', '.join(dropped)} and nothing else compared "
                                                   "(report data to check)")
                continue
        # The tile's beat/miss headline may still count a dropped figure: only a release with nothing dropped says it.
        tile = None if dropped else full.get("tile_label")
        half_year = res.get("period_basis") == "half_year"
        for m in results.values():
            nums += [m.get("reported"), m.get("consensus"), *money_tokens(m.get("label"))]
        parts = [f"{full.get('company_name') or ticker} ({ticker}) published {full.get('fiscal_label')} results "
                 f"on {full.get('release_date')}" + (f": {tile}." if tile else ".")]
        for name, key in (("Revenue", "revenue"), ("EPS", "eps")):
            m = results.get(key)
            if not m:
                continue
            what = f"{m['basis']}" if key == "eps" else name
            bits = [b for b in [m.get("reported"), f"vs {m['consensus']} consensus" if m.get("consensus") else None,
                                f"({m['label']})" if m.get("label") else None] if b]
            parts.append(f"{what} {' '.join(bits)}.")
        # The company's own SEC filing (8-K / press release exhibit on sec.gov) or nothing: never our report page
        # (G-N1 holdout until 2026-11-21; No Fallbacks). The landing page and its card are the ticker page's.
        src = full.get("source_url") if official(full.get("source_url"), ("www.sec.gov", "sec.gov")) else None
        items.append(make_item(
            date, "earnings_result", ticker, f"report:{full.get('id')}", f"/dashboard/{ticker}",
            name=full.get("company_name"), report_id=full.get("id"), fiscal_label=full.get("fiscal_label"),
            release_date=full.get("release_date"), published_at=full.get("published_at"),
            tile_label=tile, tile_state=full.get("tile_state") if tile else None, results=results,
            filed=(full.get("filing_date") or full.get("release_date")),
            source_url=src, facts_text=" ".join(parts),
            # a six-month report (H1) allows no quarter tokens: its figures are never "Q2"
            allowed_numbers=[*nums, *money_tokens(tile),
                             *fiscal_tokens(full.get("fiscal_label"), None if half_year else full.get("fiscal_quarter"),
                                            full.get("fiscal_year")),
                             *date_forms(full.get("release_date")), *date_forms(full.get("filing_date")),
                             *digit_words(full.get("company_name"))]))
    items.sort(key=lambda x: (x["published_at"] or "", x["ticker"]), reverse=True)
    return items, left, errors


def next_weekday(day: dt.date) -> dt.date:
    cur = day + dt.timedelta(days=1)
    while cur.weekday() >= 5:
        cur += dt.timedelta(days=1)
    return cur


def calendar_week(api, nxt: dt.date, now: dt.datetime) -> tuple[list[dict], list[str]]:
    """The one /earnings week (weeks_ahead counts from New York's current week) that holds `nxt`."""
    today = now.astimezone(ss.NY).date() if ss.NY else now.date()
    w = (ss.week_monday(nxt) - ss.week_monday(today)).days // 7
    if not 0 <= w <= 2:
        return [], [f"/earnings: {nxt} is outside the calendar's reach (weeks_ahead {w})"]
    data, err = api.get(f"/earnings?weeks_ahead={w}&scope=all")
    if err:
        return [], [err]
    return ([data] if isinstance(data, dict) and isinstance(data.get("days"), list) else []), []


def upcoming_items(api, target: dt.date, names: dict[str, str], now: dt.datetime | None = None
                   ) -> tuple[list[dict], dict, list[str], str | None]:
    """(items, counts, errors, empty reason) for the next weekday's confirmed universe reporters."""
    nxt = next_weekday(target)
    weeks, errors = calendar_week(api, nxt, now or dt.datetime.now(dt.timezone.utc))
    rows, counts, complete = ss.week_rows(weeks, [nxt])
    if not complete:
        return [], {}, errors, f"the earnings calendar for {nxt} did not load"
    seen: set[str] = set()
    picked = []
    for r in rows:
        sym = r.get("symbol")
        if r.get("in_universe") is True and r.get("date_confirmed") is True and sym and sym not in seen:
            seen.add(sym)
            picked.append(r)
    left = {"listed": counts.get(nxt.isoformat(), 0), "confirmed_in_universe": len(picked)}
    items = []
    date = target.isoformat()
    for r in sorted(picked, key=lambda r: -(r.get("market_cap") or 0)):
        sym = r["symbol"]
        company = names.get(sym) or names.get(sym.replace(".", "-"))
        when = HOURS.get(r.get("hour") or "", "time not announced")
        facts_text = (f"{company or sym} ({sym}) reports earnings on {nxt.isoformat()}, {when} "
                      f"(confirmed date; source: {r.get('date_confirmed_source') or 'calendar'}).")
        items.append(make_item(
            date, "earnings_upcoming", sym, f"upcoming:{sym}:{nxt.isoformat()}", f"/dashboard/{sym}",
            name=company, report_date=nxt.isoformat(), hour=r.get("hour"), hour_text=when,
            market_cap_usd=r.get("market_cap") if isinstance(r.get("market_cap"), (int, float)) else None,
            date_confirmed_source=r.get("date_confirmed_source"), source_url=f"{SITE}/earnings/tomorrow",
            facts_text=facts_text,
            allowed_numbers=[*date_forms(nxt.isoformat()), *fiscal_tokens(None, r.get("quarter"), r.get("year")),
                             *digit_words(company)]))
    reason = None if items else (f"no reporter in our universe with a confirmed date on {nxt} "
                                 f"({left['listed']} listed that day)")
    return items, left, errors, reason


# ---------------------------------------------------------------------------
# Picks

def picks_items(api, target: dt.date) -> tuple[list[dict], str | None]:
    """select_stories.picks_slot's guard: only the published list valid at the 15:00 ET slot, locked / #1 rows dropped."""
    slot = ss.picks_slot(api, target, PICKS_SLOT_ET)
    if "empty" in slot:
        return [], slot["empty"]
    story = slot["story"]
    trade_date = story["trade_date"]
    tickers = [p["ticker"] for p in story["picks"]]
    text = (f"The RapidTradeView daily picks list for {trade_date} is published; the public picks are "
            f"{', '.join(tickers)}.")
    if story.get("note"):
        text += f" ({story['note']})"
    item = make_item(target.isoformat(), "picks_ready", None, f"picks:{trade_date}", f"/picks/{trade_date}",
                     tickers=tickers, trade_date=trade_date, valid_until=story.get("valid_until"),
                     picks=[{"ticker": p["ticker"], "direction": p.get("direction")} for p in story["picks"]],
                     source_url=f"{SITE}/picks/{trade_date}", facts_text=text,
                     allowed_numbers=[*date_forms(trade_date), str(len(tickers))])
    return [item], None


# ---------------------------------------------------------------------------
# Chart pattern (automatic technical analysis) and Moves Like

def stale_reason(iso, target: dt.date, what: str) -> str | None:
    """Why a date-stamped answer cannot stand for the facts date (None when it can): the API serves only the current one."""
    try:
        day = ss.d(iso)
    except (TypeError, ValueError):
        return f"{what} has no valid date"
    if day > target:
        return f"{what} is for {iso}, after {target} (the API serves only the current one)"
    if ss.weekday_age(day, target) > WINDOW_WEEKDAYS:
        return f"{what} is from {iso}, older than the last 5 weekdays"
    return None


def exposed_top_picks(api) -> tuple[set[str], bool, str | None]:
    """(#1 tickers the public picks list exposes, whether a #1 row hides its ticker, error). Guests get the #1 row with an
    empty ticker, so the set is normally empty: this only catches a leaked one. The ticker is compared, never written."""
    data, err = api.get("/tips/daily")
    if err or not isinstance(data, dict):
        return set(), False, err or "/tips/daily: unreadable response"
    if data.get("status") != "ready":
        return set(), False, None
    tops = [t for t in data.get("tips") or [] if isinstance(t, dict) and (t.get("locked") or t.get("rank") == 1)]
    return {str(t["ticker"]).upper() for t in tops if t.get("ticker")}, any(not t.get("ticker") for t in tops), None


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def pattern_items(api, target: dt.date, names: dict[str, str]) -> tuple[list[dict], dict, list[str], str | None]:
    """(items, left_out, errors, empty reason) for the pattern showcase tile."""
    data, err = api.get(SHOWCASE)
    if err or not isinstance(data, dict):
        e = err or f"{SHOWCASE}: unreadable response"
        return [], {}, [e], f"the chart pattern showcase did not load ({e})"
    status = data.get("status")
    if status == "unavailable":
        code = (data.get("error") or {}).get("code") if isinstance(data.get("error"), dict) else None
        e = f"{SHOWCASE}: unavailable ({code or 'no code'})"
        return [], {}, [e], f"the chart pattern showcase did not load ({e})"
    if status != "ok":
        return [], {}, [], f"the chart pattern showcase is {status!r}"
    tile = data.get("tile")
    if tile is None:
        return [], {"tiles": 0}, [], "the chart pattern showcase has no tile"
    cp = tile.get("chart_pattern") if isinstance(tile, dict) else None
    text = cp.get("text") if isinstance(cp, dict) else None
    ticker = str(tile.get("ticker") or "").upper() if isinstance(tile, dict) else ""
    if (not isinstance(text, dict) or not ticker or not isinstance(cp.get("name"), str)
            or cp.get("status") not in ("confirmed", "forming") or not isinstance(text.get("chip"), str)):
        e = f"{SHOWCASE}: the tile has no readable pattern"
        return [], {"tiles": 1}, [e], e
    left = {"tiles": 1}
    tops, hidden, perr = exposed_top_picks(api)
    why = None
    if perr:
        why = f"the picks list did not load ({perr}), so the #1 guard cannot run"
    elif ticker in tops:
        why = "the tile's ticker is a #1 pick"  # never named
    elif not ss.listed(ticker, names):
        why = f"{ticker} is not in our names list"
    elif cp["status"] == "confirmed" and cp.get("in_window") is not True:
        why = f"{ticker}'s confirmed pattern is outside the window our pages show"
    else:
        why = stale_reason(tile.get("scan_date"), target, "the showcase scan")
    if why:
        return [], left, [perr] if perr else [], why

    scan_date = tile["scan_date"][:10]
    company = names.get(ticker) or names.get(ticker.replace(".", "-"))
    name = cp["name"]
    key_lines = [k for k in text.get("key") or [] if isinstance(k, str)]
    points = [p["t"] for p in text.get("points") or [] if isinstance(p, dict) and isinstance(p.get("t"), str)]
    texts = [text.get("pill"), text.get("chip"), text.get("callout"), text.get("detail"), text.get("what"), *key_lines, *points]
    prices = uniq(t for x in texts if isinstance(x, str) for t in money_tokens(x))

    def shown(v) -> str | None:  # a level as the pattern text prints it, when it does
        if not isinstance(v, (int, float)):
            return None
        want = f"${js_fixed(float(v), 2)}"
        return next((p for p in prices if p.replace(",", "") == want), None)

    kl = cp.get("key_level") if isinstance(cp.get("key_level"), dict) else {}
    bo = cp.get("breakout") if isinstance(cp.get("breakout"), dict) else {}
    dates = [scan_date, cp.get("start"), cp.get("end"), cp.get("confirmed_on"), cp.get("as_of"),
             *(p.get("d") for p in cp.get("pivots") or [] if isinstance(p, dict))]
    start, end = cp.get("start"), cp.get("end")
    span = f": pattern {start} to {end}" if start and end else ""
    lead = key_lines[0] if key_lines and key_lines[0].startswith(text["chip"]) else None  # says the chip and more
    facts_text = (f"Automatic technical analysis flagged {_article(name)} {name.lower()} on ${ticker}"
                  f"{f' ({company})' if company else ''} (scan {scan_date}){span}. {lead or text['chip'] + '.'}"
                  f"{' ' + key_lines[0] if key_lines and not lead else ''}")
    item = make_item(
        target.isoformat(), "chart_pattern", ticker,
        f"pattern:{ticker}:{cp.get('type')}:{cp['status']}:{cp.get('confirmed_on') or start}", f"/dashboard/{ticker}",
        name=company, scan_date=scan_date,
        pattern={"type": cp.get("type"), "name": name, "status": cp["status"], "direction": cp.get("direction"),
                 "start": start, "end": end, "start_text": (date_forms(start) or [None, None])[1],
                 "end_text": (date_forms(end) or [None, None])[1], "confirmed_on": cp.get("confirmed_on"),
                 "as_of": cp.get("as_of")},
        levels={k: v for k, v in {"key_level_name": kl.get("name"), "key_level": shown(kl.get("price")),
                                  "breakout_close": shown(bo.get("close"))}.items() if v},
        page_text={"pill": text.get("pill"), "chip": text["chip"], "detail": text.get("detail"), "what": text.get("what"),
                   "key": key_lines, "points": points},
        top_pick_check=("the #1 ticker is hidden from the public picks list; this item never mentions picks"
                        if hidden else "no #1 pick exposed"),
        banned_words=PREDICTION_WORDS, source_url=f"{SITE}/dashboard/{ticker}", facts_text=facts_text,
        allowed_numbers=[*prices, *short_dates(*texts), *(f for x in dates for f in date_forms(x)),
                         *digit_words(company, name)])
    return [item], left, [], None


def moves_subjects(items: list[dict], limit: int = MOVES_LIKE_MAX, skip=()) -> tuple[list[str], int]:
    """Up to `limit` tickers not in `skip`, round robin over the subject types (deduped), and how many distinct there were."""
    per: dict[str, list[str]] = {k: [] for k in MOVES_LIKE_SUBJECT_TYPES}
    for it in items:
        t = it.get("ticker")
        if it.get("type") in per and t and t not in per[it["type"]] and t not in skip:
            per[it["type"]].append(t)
    distinct = len({t for ts in per.values() for t in ts})
    out: list[str] = []
    while len(out) < limit and any(per.values()):
        for k in MOVES_LIKE_SUBJECT_TYPES:
            if per[k] and len(out) < limit:
                t = per[k].pop(0)
                if t not in out:
                    out.append(t)
    return out, distinct


def _peer(p) -> dict | None:
    if not isinstance(p, dict) or not isinstance(p.get("ticker"), str) or not mf.TICKER.match(p["ticker"]):
        return None
    sync, band, move = p.get("sync"), p.get("band"), p.get("day_pct")
    if not isinstance(sync, int) or isinstance(sync, bool) or not 0 <= sync <= 100 or band not in BAND_LABELS:
        return None
    if not isinstance(move, (int, float)) or isinstance(move, bool):
        return None
    label = BAND_LABELS[band]
    return {"ticker": p["ticker"], "name": p.get("name") if isinstance(p.get("name"), str) else None, "sync": sync,
            "band": label, "sync_text": f"Sync {sync} · {label}", "day_move": move_pct(float(move))}


def _move_numbers(text: str) -> list[str]:
    """A move as the card prints it ("−4.0%") and unsigned ("4.0%"), so "fell 4.0%" reads; "+4.0%" for a fall does not."""
    return [text] if text == "0.0%" else [text, text.lstrip(f"+{MINUS}")]


def previous_moves(previous: dict | None, target: dt.date) -> tuple[dict[str, str], list[dict]]:
    """The day's earlier answers ({ticker: outcome}) and moves_like items from --previous (same date only)."""
    if not isinstance(previous, dict) or previous.get("date") != target.isoformat():
        return {}, []
    items = [i for i in previous.get("items") or [] if isinstance(i, dict) and i.get("type") == "moves_like" and i.get("ticker")]
    checked = {t: o for t, o in (previous.get("moves_like_checked") or {}).items() if o in MOVES_LIKE_KEEP}
    for i in items:
        checked[i["ticker"]] = "item"
        if not i.get("media"):  # carried over from a file written before items carried media
            i["media"] = [og_media("moves_like", f"/dashboard/{i['ticker']}", i.get("facts_text") or "")]
    return checked, [i for i in items if checked.get(i["ticker"]) == "item"]


def moves_like_items(api, target: dt.date, items: list[dict], previous: dict | None = None
                     ) -> tuple[list[dict], dict, list[str], dict[str, str]]:
    """(items, left_out, errors, the day's answers by ticker). At most MOVES_LIKE_MAX tickers a day are looked up; one
    answered earlier the same day (--previous) is carried over without a GET; a failed read is retried next run."""
    checked, out = previous_moves(previous, target)
    out = [i for i in out if i["ticker"] in checked][:MOVES_LIKE_MAX]
    checked = dict(list(checked.items())[:MOVES_LIKE_MAX])
    subjects, distinct = moves_subjects(items, MOVES_LIKE_MAX - len(checked), skip=set(checked))
    left = {"tickers_in_items": distinct, "carried_over": len(checked), "requested": len(subjects), "not_covered": 0,
            "disabled": 0, "no_peer": 0, "below_floor": 0, "stale": 0, "unavailable": 0, "unreadable": 0}
    errors: list[str] = []
    for n, ticker in enumerate(subjects):
        if n:
            SLEEP(MOVES_LIKE_GAP_S)
        path = f"/moves-like/{quote(ticker, safe='')}"
        data, err = api.get(path)
        if err or not isinstance(data, dict):
            left["unreadable"] += 1
            errors.append(err or f"{path}: unreadable response")
            continue
        status = data.get("status")
        if status in ("not_covered", "disabled"):
            left[status] += 1
            if status == "not_covered":
                checked[ticker] = status
            continue
        if status == "unavailable":
            left["unavailable"] += 1
            code = (data.get("error") or {}).get("code") if isinstance(data.get("error"), dict) else None
            errors.append(f"{path}: unavailable ({code or 'no code'})")
            continue
        subject = data.get("subject")
        if (status != "ok" or str(data.get("ticker") or "").upper() != ticker or data.get("window") != MOVES_LIKE_SESSIONS
                or not isinstance(subject, dict) or not isinstance(data.get("peers"), list)):
            left["unreadable"] += 1
            errors.append(f"{path}: unexpected response (status {status!r:.30})")
            continue
        session = data.get("session")
        if stale_reason(session, target, "the Moves Like session"):
            left["stale"] += 1
            continue
        peers = [p for p in (_peer(x) for x in data["peers"]) if p and p["ticker"] != ticker]
        if data["peers"] and not peers:
            left["unreadable"] += 1
            errors.append(f"{path}: no readable peer")
            continue
        if not peers:
            left["no_peer"] += 1
            checked[ticker] = "no_peer"
            continue
        peers = [p for p in peers if p["sync"] >= MOVES_LIKE_SYNC_FLOOR]
        if not peers:
            left["below_floor"] += 1
            checked[ticker] = "below_floor"
            continue
        peers = sorted(peers, key=lambda p: -p["sync"])[:3]
        checked[ticker] = "item"
        session = session[:10]
        when = date_forms(session)[1]
        subj_move = move_pct(float(subject["day_pct"])) if isinstance(subject.get("day_pct"), (int, float)) else None
        name = subject.get("name") if isinstance(subject.get("name"), str) else None
        facts_text = (f"Moves Like: over the {MOVES_LIKE_SESSIONS} sessions before {when}, ${ticker}"
                      f"{f' ({name})' if name else ''} moved most like "
                      + ", ".join(f"${p['ticker']} (Sync {p['sync']}, {p['band']})" for p in peers)
                      + ". Sync is 0 to 100; past moves, not a prediction.")
        out.append(make_item(
            target.isoformat(), "moves_like", ticker, f"moves:{ticker}:{session}", f"/dashboard/{ticker}",
            tickers=[ticker, *(p["ticker"] for p in peers)], name=name, session=session,
            valid_through=data.get("valid_through"), window_sessions=MOVES_LIKE_SESSIONS, subject_day_move=subj_move,
            peers=peers, banned_words=PREDICTION_WORDS, source_url=f"{SITE}/dashboard/{ticker}", facts_text=facts_text,
            allowed_numbers=[str(MOVES_LIKE_SESSIONS), "100", *(str(p["sync"]) for p in peers), *date_forms(session),
                             *(_move_numbers(subj_move) if subj_move else []),
                             *(x for p in peers for x in _move_numbers(p["day_move"])),
                             *digit_words(name, *(p["name"] for p in peers))]))
    return out, left, errors, checked


# ---------------------------------------------------------------------------
# Roundups (Growth B1 2026-10-12): several cashtags in one post, landing a page that lists them all

def summary_gaps(slug: str, filed: str, srcs: list[str], coverage: dict) -> list[str]:
    """Why a member's count for one filing date may not be the whole filing ([] when it is): the capped public feed
    read did not reach past the window start, or a row of that member and filing date (or of one of its filings) was
    left out by a filter. No Fallbacks: a partial count is never published as the filing's total."""
    if coverage.get("error"):
        return ["the Congress feed did not load"]
    why = []
    oldest, since = coverage.get("oldest_read"), coverage.get("since")
    if not oldest or not since or oldest >= since:
        why.append(f"the feed read (newest rows only) reaches back to {oldest or 'no dated row'}, not before the window "
                   f"start {since}: rows of the filing may be cut off")
    dropped: dict[str, int] = {}
    for r in coverage.get("dropped") or []:
        if (r["slug"] == slug and r["filed"] == filed) or (r["src"] and r["src"] in srcs):
            dropped[r["reason"]] = dropped.get(r["reason"], 0) + 1
    if dropped:
        why.append("rows of the filing were left out (" + ", ".join(f"{k} {n}" for k, n in sorted(dropped.items())) + ")")
    return why


def ptr_summary_items(target: dt.date, congress: list[dict], fame: dict, coverage: dict) -> tuple[list[dict], dict, dict]:
    """One item per member and filing date with 2+ Congress items: the count of trades (rows) and up to
    ROUNDUP_MAX_TICKERS tickers (the member's most newsworthy, rank()), landing the figure page #trades. Built from the
    day's congress_trade items before the per-filer cap, so the trades the cap leaves out are still counted here.
    Only for a whole filing (summary_gaps, congress_items' coverage): otherwise the item is skipped and the third value
    (left_out.ptr_summary_incomplete) says why."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for it in congress:
        if it.get("figure_slug") and it.get("filed"):
            groups.setdefault((it["figure_slug"], it["filed"]), []).append(it)
    left = {"members_filing_dates": len(groups), "single_item": 0}
    incomplete = {"window_start": coverage.get("since"), "oldest_row_read": coverage.get("oldest_read"), "skipped": 0,
                  "reasons": []}
    items = []
    for (slug, filed), its in groups.items():
        if len(its) < 2:
            left["single_item"] += 1
            continue
        gaps = summary_gaps(slug, filed, uniq(i.get("source_url") for i in its), coverage)
        if gaps:
            incomplete["skipped"] += 1
            incomplete["reasons"].append(f"{slug} filed {filed}: {'; '.join(gaps)}")
            continue
        its = sorted(its, key=lambda i: -rank(i, target, fame)[0])
        tickers = uniq(i["ticker"] for i in its)
        shown = tickers[:ROUNDUP_MAX_TICKERS]
        trades = sum(int(i.get("rows") or 1) for i in its)
        buys = sum(int(i.get("rows") or 1) for i in its if i.get("side") == "buy")
        sales = trades - buys
        srcs = uniq(i.get("source_url") for i in its)
        head = its[0]
        office = head.get("office") or "Member of Congress"
        title = office.split(" (")[0]
        tag = office[len(title):].strip()
        sides = ", ".join(x for x in [f"{buys} {'purchase' if buys == 1 else 'purchases'}" if buys else None,
                                      f"{sales} {'sale' if sales == 1 else 'sales'}" if sales else None] if x)
        rest = len(tickers) - len(shown)
        reports = "a report" if len(srcs) == 1 else f"{len(srcs)} reports"
        more = f" and {rest} more" if rest else ""
        facts_text = (f"{title} {head.get('name')}{' ' + tag if tag else ''} disclosed {trades} trades ({sides}) in "
                      f"{len(tickers)} tickers on {reports} filed {filed}, including "
                      f"{', '.join('$' + t for t in shown)}{more}.")
        tops = sum(i.get("amount_top_usd") or 0 for i in its)
        items.append(make_item(
            target.isoformat(), "ptr_summary", None, f"ptrsum:{slug}:{filed}", f"/smart-money/figures/{slug}",
            tickers=shown, tickers_total=len(tickers), name=head.get("name"), office=office, figure_slug=slug,
            filed=filed, rows=trades, buys=buys, sales=sales, amount_top_usd=tops or None,
            source_url=srcs[0] if len(srcs) == 1 else None, source_urls=srcs,
            item_ids=[i["item_id"] for i in its], facts_text=facts_text,
            allowed_numbers=[str(trades), str(len(tickers)), str(buys) if buys else None, str(sales) if sales else None,
                             str(rest) if rest else None, str(len(srcs)) if len(srcs) > 1 else None,
                             *date_forms(filed), *digit_words(head.get("name"))]))
    return items, left, incomplete


def earnings_roundup_items(target: dt.date, upcoming: list[dict]) -> tuple[list[dict], dict]:
    """One item per set session (before the open / after the close) of the next weekday with 2+ confirmed reporters in
    our universe: up to ROUNDUP_MAX_TICKERS of them, largest market cap first (the earnings_upcoming order), landing
    /earnings/tomorrow (no anchor) with the /earnings card. allowed_numbers: the report date and the session only."""
    by: dict[str, list[dict]] = {}
    for it in upcoming:
        if it.get("hour") in ROUNDUP_SESSIONS:
            by.setdefault(it["hour"], []).append(it)
    left = {s: len(by.get(s, [])) for s in ROUNDUP_SESSIONS}
    left["no_set_session"] = sum(1 for it in upcoming if it.get("hour") not in ROUNDUP_SESSIONS)
    items = []
    for session in ROUNDUP_SESSIONS:
        its = by.get(session) or []
        if len(its) < 2:
            continue
        day = its[0]["report_date"]
        when = HOURS[session]
        shown = its[:ROUNDUP_MAX_TICKERS]
        rest = len(its) - len(shown)
        names = ", ".join(f"${i['ticker']}" + (f" ({i['name']})" if i.get("name") else "") for i in shown)
        facts_text = f"Reporting earnings on {day}, {when} (confirmed dates): {names}{' and more' if rest else ''}."
        caps = [i["market_cap_usd"] for i in shown if isinstance(i.get("market_cap_usd"), (int, float))]
        items.append(make_item(
            target.isoformat(), "earnings_tomorrow_roundup", None, f"roundup:{day}:{session}", "/earnings/tomorrow",
            tickers=[i["ticker"] for i in shown], names={i["ticker"]: i.get("name") for i in shown}, report_date=day,
            hour=session, hour_text=when, reporters_in_session=len(its), market_cap_usd=max(caps) if caps else None,
            item_ids=[i["item_id"] for i in shown], source_url=f"{SITE}/earnings/tomorrow", facts_text=facts_text,
            allowed_numbers=[*date_forms(day), when]))
    return items, left


# ---------------------------------------------------------------------------
# Audience rank (HQ 2026-10-18, social-content PLAN §2.2; replaces Growth B1's newsworthiness rank): the file is sorted by
# it, highest first. Grok picks across pillars (rules.variety); the order is a menu, not a posting order.
#   rank = base(type) + recognisability + magnitude + freshness - novelty
#   base            market-level items (P1 P2 P3a P3b P4 P6 P7) 4; earnings_result 3; form4_buy, congress_trade,
#                   ptr_summary, the week preview, a reaction, picks, the tomorrow roundup 2; upcoming, pattern 1; moves_like 0.5
#   recognisability market-level items without a lead ticker +4 (they name the largest companies); else the lead ticker's
#                   cap tier (the week preview: its largest reporter): mega >= $200B +4,
#                   large >= $10B +2.5, mid >= $2B +1, small 0, micro < $300M -2 (unknown cap 0); a known person +2
#                   (fame.json, or a CEO / CFO / Chair title; "director" is no longer a known name)
#   magnitude       0..3 per type: filings log10(top of the amount / $10K) ($100K 1, $1M 2, $10M+ 3), plus +1 for a
#                   Congress buy (buys over sales); market items their own (market_facts: move / 0.75% x 1.5, $ move /
#                   $50B x 1.5, log2(buzz ratio), sector spread / threshold x 1.5, ...); earnings_result 1.5 with a verdict
#   freshness       2 - 0.5 per weekday of age (filed / release / scan / session date; today's items age 0)
#   novelty         the primary ticker (or the same item) in an own post of the last 3 trading days -4; the same filer
#                   within 7 days -6; the same pillar as the newest own post -1 (post_history; no history read: no novelty)
# rank_why spells out every term.

RANK_BASE = {**{k: 4.0 for k in mk.MARKET_TYPES}, "earnings_week_preview": 2.0, "earnings_reaction": 2.0,
             "earnings_result": 3.0, "earnings_tomorrow_roundup": 2.0, "ptr_summary": 2.0, "congress_trade": 2.0,
             "form4_buy": 2.0, "picks_ready": 2.0, "earnings_upcoming": 1.0, "chart_pattern": 1.0, "moves_like": 0.5}
MARKET_LEVEL = tuple(k for k in mk.MARKET_TYPES if k not in ("earnings_week_preview", "earnings_reaction"))
RECOG = {"mega": 4.0, "large": 2.5, "mid": 1.0, "small": 0.0, "micro": -2.0, "unknown": 0.0}
RECOG_MARKET = 4.0
RANK_KNOWN = 2.0
RANK_CONGRESS_BUY = 1.0
RANK_MAG_MAX = 3.0
RANK_FRESH = 2.0       # minus 0.5 per weekday of age
NOVELTY_TICKER = 4.0   # primary ticker in an own post within TICKER_COOLDOWN_SESSIONS trading days
NOVELTY_FILER = 6.0    # same filer within FILER_COOLDOWN_DAYS days
NOVELTY_PILLAR = 1.0   # same pillar as the newest own post (a tie-breaker)
TICKER_COOLDOWN_SESSIONS = 3   # weekday age 0..2: the facts date and the 2 weekdays before it
FILER_COOLDOWN_DAYS = 7
KNOWN_TITLE = re.compile(r"\b(?:ceo|cfo|chief executive|chief financial|chair(?:man|woman|person)?)\b", re.IGNORECASE)
RANK_DATE_FIELD = {"congress_trade": "filed", "form4_buy": "filed", "ptr_summary": "filed", "earnings_result": "release_date",
                   "chart_pattern": "scan_date", "moves_like": "session", **{k: "session_date" for k in mk.MARKET_TYPES},
                   "earnings_week_preview": None, "congress_flow": None, "insider_flow": None, "reddit_buzz": "capture_date"}


def known_name(item: dict, fame: dict) -> str | None:
    """Why the item's person counts as a known name (fame.json, or a CEO / CFO / Chair title), else None."""
    name = item.get("name") or ""
    if item.get("type") in ("congress_trade", "ptr_summary"):
        hit = ss.matches_any(name, fame.get("members") or [])
        return f"{hit} (fame)" if hit else None
    if item.get("type") == "form4_buy":
        hit = item.get("famous_person") or ss.matches_any(name, fame.get("insiders") or [])
        if hit:
            return f"{hit} (fame)"
        m = KNOWN_TITLE.search(str(item.get("office") or "").split(" at ")[0])
        return f"{m.group(0)} (title)" if m else None
    return None


def magnitude(item: dict) -> tuple[float, str]:
    kind = item.get("type")
    if isinstance(item.get("magnitude"), (int, float)):
        return min(RANK_MAG_MAX, max(0.0, float(item["magnitude"]))), "market"
    if kind in ("form4_buy", "congress_trade", "ptr_summary"):
        top = item.get("amount_top_usd")
        ok = isinstance(top, (int, float)) and top > 0
        p = round(min(RANK_MAG_MAX, max(0.0, math.log10(top / 1e4))), 2) if ok else 0.0
        why = f"top {usd_compact(top)}" if ok else "no amount"
        if kind == "congress_trade" and item.get("side") == "buy":
            p += RANK_CONGRESS_BUY
            why += f", buy +{RANK_CONGRESS_BUY:g}"
        return p, why
    if kind == "earnings_result":
        verdict = any((m or {}).get("verdict") for m in (item.get("results") or {}).values())
        return (1.5, "verdict") if verdict else (1.0, "results")
    return {"earnings_tomorrow_roundup": (1.0, "roundup"), "picks_ready": (1.0, "picks"),
            "chart_pattern": (0.5, "pattern")}.get(kind, (0.0, "none"))


def item_age(item: dict, target: dt.date) -> tuple[int | None, str]:
    key = RANK_DATE_FIELD.get(item.get("type"), "")
    day = item.get(key) if key else target.isoformat()
    try:
        return (ss.weekday_age(ss.d(day), target) if day else None), f"{key or 'today'} {str(day)[:10]}"
    except (TypeError, ValueError):
        return None, f"{key} unreadable"


def recent_posts(history: list[dict] | None, target: dt.date) -> list[dict]:
    """Own posts of the last TICKER_COOLDOWN_SESSIONS trading days (weekday age 0..2)."""
    return [p for p in history or [] if p.get("ny_date") and ss.d(p["ny_date"]) <= target
            and ss.weekday_age(ss.d(p["ny_date"]), target) < TICKER_COOLDOWN_SESSIONS]


def post_tickers(p: dict) -> list[str]:
    """The lead tickers of one of our posts (post_history: its item's headline tickers, else its primary ticker)."""
    return [t for t in (p.get("headline_tickers") or [p.get("ticker")]) if t]


def novelty(item: dict, target: dt.date, history: list[dict] | None) -> tuple[float, list[str]]:
    """The novelty penalty from our own posts (post_history.resolve): ticker (or the same item), filer, pillar."""
    if not history:
        return 0.0, []
    pen, why = 0.0, []
    ticks = set(mk.headline_tickers(item))  # the item's lead tickers, whatever its pillar (a cooldown across pillars)
    same = [p for p in recent_posts(history, target) if (ticks & set(post_tickers(p)))
            or (item.get("dedupe_key") and p.get("dedupe_key") == item.get("dedupe_key"))]
    if same:
        pen += NOVELTY_TICKER
        hit = sorted(ticks & set(post_tickers(same[-1])))
        why.append(f"posted {', '.join('$' + t for t in hit) if hit else 'this item'} on {same[-1]['ny_date']} -{NOVELTY_TICKER:g}")
    filer = ph.filer_of(item)
    if filer:
        hit = [p for p in history if p.get("filer") == filer and p.get("dedupe_key") != item.get("dedupe_key")
               and p.get("ny_date") and 0 <= (target - ss.d(p["ny_date"])).days <= FILER_COOLDOWN_DAYS]
        if hit:
            pen += NOVELTY_FILER
            why.append(f"filer posted on {hit[-1]['ny_date']} -{NOVELTY_FILER:g}")
    newest = history[-1]
    if newest.get("pillar") and newest["pillar"] == item.get("pillar"):
        pen += NOVELTY_PILLAR
        why.append(f"same pillar as the newest own post ({newest['pillar']}) -{NOVELTY_PILLAR:g}")
    return pen, why


def rank(item: dict, target: dt.date, fame: dict, history: list[dict] | None = None) -> tuple[float, str]:
    """(rank, rank_why) for one item: higher reaches more people we can win."""
    kind = item.get("type")
    pts = RANK_BASE.get(kind, 0.0)
    why = [f"{kind} {pts:g}"]
    if kind in MARKET_LEVEL and not item.get("ticker"):  # about the whole market: it names the largest companies
        pts += RECOG_MARKET
        why.append(f"market-level +{RECOG_MARKET:g}")
    else:
        tier = item.get("cap_tier") or mk.tier_of(item.get("market_cap_usd"))
        if tier != "unknown":
            r = RECOG.get(tier, 0.0)
            pts += r
            cap = item.get("market_cap_usd")
            why.append(f"{tier} cap{' ' + usd_compact(cap) if isinstance(cap, (int, float)) else ''} {r:+g}")
    known = known_name(item, fame)
    if known:
        pts += RANK_KNOWN
        why.append(f"known name {known} +{RANK_KNOWN:g}")
    mag, mwhy = magnitude(item)
    if mag:
        pts += mag
        why.append(f"magnitude ({mwhy}) +{round(mag, 2):g}")
    age, label = item_age(item, target)
    if age is not None and age >= 0:
        p = max(0.0, RANK_FRESH - 0.5 * age)
        pts += p
        why.append(f"{label} (age {age}) +{p:g}")
    pen, pwhy = novelty(item, target, history)
    pts -= pen
    why += pwhy
    return round(pts, 2), "; ".join(why)


def rank_items(items: list[dict], target: dt.date, fame: dict, history: list[dict] | None = None) -> list[dict]:
    """Every item gets rank and rank_why; the list comes back sorted by rank, highest first (ties keep their order)."""
    for it in items:
        it["rank"], it["rank_why"] = rank(it, target, fame, history)
    return sorted(items, key=lambda i: -i["rank"])


def cap_per_filer(congress: list[dict], target: dt.date, fame: dict) -> tuple[list[dict], dict]:
    """At most one Congress item per filer (figure) a day, congress_trade and ptr_summary alike: the highest-ranked one
    (one filer, one post). (kept, how many of each type were left out)"""
    kept, seen = [], set()
    dropped = {"congress_trade": 0, "ptr_summary": 0}
    for it in rank_items(congress, target, fame):
        who = it.get("figure_slug") or it.get("name")
        if who in seen:
            dropped[it["type"]] = dropped.get(it["type"], 0) + 1
            continue
        seen.add(who)
        kept.append(it)
    return kept, dropped


# ---------------------------------------------------------------------------
# Market pillars (HQ 2026-10-18, social-content PLAN §1-§3): market_facts specs become items; every item gets pillar,
# cap tier, context and first-line seeds; the pipeline gates (weekend replay, small caps, cooldowns) run before the rank.

MARKET_CARD_URL = SITE + "/market/card/{panel}"
COOLDOWN_PLATFORMS = ("x", "instagram", "threads")  # the brand accounts Grok posts own posts on
SMALL_CAP_MIN = 2e9         # form4_buy: emitted at cap >= $2B, ...
SMALL_CAP_BIG_BUY = 10e6    # ... or a $10M+ buy at cap >= $300M, ...
MICRO_CAP = 300e6           # ... or a fame.json person (the only way a micro cap gets in)
TOP_SMALL_SLOTS = 8         # at most one small / micro item among the first 8
FILING_TYPES = ("form4_buy", "congress_trade", "ptr_summary")
WEEKEND_REPLAY_TYPES = (*FILING_TYPES, "chart_pattern")


def card_file(spec: dict) -> str:
    """The pinned card's file name: panel, the data date the card prints, the fingerprint of the item's numbers."""
    return f"market-{spec['panel']}-{spec.get('card_date') or 'nodate'}-{spec.get('fingerprint') or 'x'}.png"


def market_item(target: dt.date, spec: dict) -> dict:
    """A market_facts spec as a facts item. Items with a share card start with media [] and card.url null: the runner
    pins the card (tools/pin_cards.py) and fills both, or drops the item (No Fallbacks: no post without its own card)."""
    path = spec.get("path") or "/"
    skip = ("type", "key", "path", "panel", "fingerprint", "card_date", "ticker")
    fields = {k: v for k, v in spec.items() if k not in skip}
    fields["source_url"] = f"{SITE}/earnings" if spec["type"] == "earnings_week_preview" else None
    if spec.get("panel"):
        fields["card"] = {"panel": spec["panel"], "url": None, "live_url": MARKET_CARD_URL.format(panel=spec["panel"]),
                          "date": spec.get("card_date"), "fingerprint": spec.get("fingerprint"), "file": card_file(spec),
                          "sha256": None}
        fields["media"] = []
    return make_item(target.isoformat(), spec["type"], spec.get("ticker"), spec["key"], path, **fields)


def market_items(api, target: dt.date, now: dt.datetime, before: dict | None
                 ) -> tuple[list[dict], dict, dict[str, str], list[str], dict, "mk.Market"]:
    """(items, left_out, reasons, errors, state, market). state = this pass's flow top-5 lists (the next day's facts read
    them to tell when a 500-largest name enters the top 5)."""
    m, errors = mk.load(api)
    reasons: dict[str, str] = {}
    specs: list[dict] = []
    for kind, fn in (("market_move", mk.market_move), ("mega_mover", mk.mega_movers), ("sector_rotation", mk.sector_rotation),
                     ("breadth_day", mk.breadth_day), ("basket_week", mk.basket_week), ("reddit_buzz", mk.reddit_buzz)):
        if kind != "reddit_buzz" and not m.p:
            reasons[kind] = f"{mk.PICTURES} did not load"
            continue
        got, why = fn(m, target)
        specs += got
        if why:
            reasons[kind] = why
    c, cwhy, ctop = mk.congress_flow(m, target, before)
    i, iwhy, itop = mk.insider_flow(m, target, before)
    specs += c + i
    for kind, why in (("congress_flow", cwhy), ("insider_flow", iwhy)):
        if why:
            reasons[kind] = why
    # P5: the week preview (Sunday: next week; Monday: this week) and the reactions of the current calendar week
    if target.weekday() in (6, 0):
        monday = target + dt.timedelta(days=1) if target.weekday() == 6 else target
        weeks, werr = calendar_week(api, monday, now)
        errors += werr
        got, why = mk.earnings_week_preview(m, target, weeks[0] if weeks else None, monday)
        specs += got
        if why:
            reasons["earnings_week_preview"] = why
    else:
        reasons["earnings_week_preview"] = "built on Sunday and Monday facts only"
    if m.session:
        today = now.astimezone(ss.NY).date() if ss.NY else now.date()
        session = ss.d(m.session)
        week = None
        if ss.week_monday(session) == ss.week_monday(today):
            weeks, werr = calendar_week(api, session, now)
            errors += werr
            week = weeks[0] if weeks else None
        archive, aerr = api.get("/earnings/reports/archive")
        reports = archive.get("reports") if isinstance(archive, dict) and isinstance(archive.get("reports"), list) else []
        got, why = mk.earnings_reactions(m, target, week, reports)
        specs += got
        if why:
            reasons["earnings_reaction"] = why
    else:
        reasons["earnings_reaction"] = f"{mk.PICTURES} did not load"
    for s in specs:  # one pinned file per panel and data, shared by its items
        if s.get("panel"):
            s["fingerprint"] = mk.panel_fingerprint(m, s["panel"])
    items = [market_item(target, s) for s in specs]
    left = {"market_session": m.session, "priced_cap_share": ((m.p or {}).get("totals") or {}).get("priced_cap_share"),
            "flows_as_of": (m.f or {}).get("as_of")}
    state = {"session_date": m.session, "congress_top5": ctop, "insider_sell_top5": itop}
    return items, left, reasons, errors, state, m


def _angles(item: dict, m: "mk.Market") -> list[str]:
    """Three first-line seeds for the older types (number-first, name-first, contrast / question): seeds, not templates."""
    kind, t = item.get("type"), item.get("ticker")
    if kind == "form4_buy":
        role = str(item.get("office") or "Insider").split(" at ")[0]
        co = item.get("company") or t
        out = [f"{item.get('amount_text')} open-market buy of ${t} by its {role.lower()}.",
               f"{co} {role.lower()} {item.get('name')} bought {item.get('amount_text')} of ${t}."]
        sold = ((m.f or {}).get("insiders") or {}).get("sells", {}).get("total_usd") if m.f else None
        if isinstance(sold, (int, float)):
            out.append(f"Officers and directors sold {mk.usd_text(sold)} on the open market over 30 days in our feed. "
                       f"This {role.lower()} bought ${t}.")
        return out
    if kind == "congress_trade":
        verb = "purchase" if item.get("side") == "buy" else "sale"
        return [f"{item.get('amount_text')} {verb} of ${t} disclosed by {item.get('name')}.",
                f"{item.get('office', '').split(' (')[0]} {item.get('name')} disclosed a ${t} {verb}.",
                f"Who in Congress is {'buying' if verb == 'purchase' else 'selling'} ${t}? {item.get('name')}."]
    if kind == "earnings_result":
        eps = (item.get("results") or {}).get("eps") or {}
        return [x for x in [f"${t} {item.get('fiscal_label')}: {eps['basis']} {eps['reported']} vs {eps['consensus']} consensus."
                            if eps.get("reported") and eps.get("consensus") else None,
                            f"{item.get('name') or t} (${t}) reported {item.get('fiscal_label')}.",
                            f"Did ${t} beat? {eps['label']}." if eps.get("label") else None] if x]
    return []


def moves_like_claims(ticker: str, peers: list[str | None]) -> list[dict]:
    """"moved most like" a listed peer: the peers are the card's ranked list (Sync >= the floor), highest first."""
    peers = [mk.norm_ticker(p) for p in peers if p]
    if not peers:
        return []
    # the peers are ranked (closest first) within the item's own ticker, which the sentence may leave implicit
    return [mk.claim(["most", "top", "best", "led"], peers, within=[ticker], scope=r"\blike\b|sync", polarity=None,
                     metric="sync",
                     needs=r"\blike\b|sync|mov",
                     says=f"${ticker} moved most like " + ", then ".join("$" + p for p in peers) + " (by Sync)")]


def enrich(items: list[dict], m: "mk.Market") -> None:
    """pillar, cap fill (the map's company cap when the item has none), cap_tier, in_500, context_numbers /
    context_tickers (numbers computed from our API: the cap, the last session's move, the 30-day flow totals), angles,
    trigger and card defaults. In place."""
    ins = ((m.f or {}).get("insiders") or {}) if m.f else {}
    con = ((m.f or {}).get("congress") or {}) if m.f else {}
    buyers500 = [i["ticker"] for i in items if i.get("type") == "form4_buy" and m.in_500(i.get("ticker"))]
    for it in items:
        kind, t = it.get("type"), it.get("ticker")
        it["pillar"] = ph.pillar_of(kind)
        # Map-first cap (review 10-18: PEP showed $179.2B on its Form 4 item and $174.9B on Moves Like): one company,
        # one cap, the market map's, whatever the item type; the feed's own value is kept beside it.
        if t and m.cap(t):
            feed = it.get("market_cap_usd")
            if isinstance(feed, (int, float)) and feed != m.cap(t) and it.get("market_cap_source") != "market_map":
                it["market_cap_feed_usd"] = feed
            it["market_cap_usd"], it["market_cap_source"] = m.cap(t), "market_map"
        it["cap_tier"] = "market" if kind in MARKET_LEVEL and not t else mk.tier_of(it.get("market_cap_usd"))
        it["in_500"] = m.in_500(t) if t else None
        it.setdefault("context_numbers", [])
        it.setdefault("context_tickers", [])
        it.setdefault("trigger", None)
        it.setdefault("card", None)
        it.setdefault("claims", [])
        it.setdefault("headline", mk.headline(mk.headline_tickers(it)))
        # the sector and name of every ticker a post may cashtag (claims.sector_reasons: $GOOGL is not Technology)
        secs, names = {}, {}
        for x in [*(it.get("tickers") or []), *(it.get("context_tickers") or []), *([t] if t else [])]:
            row = m.by_ticker.get(mk.norm_ticker(x)) if x else None
            if row:
                if row.get("sector"):
                    secs[mk.norm_ticker(x)] = row["sector"]
                if row.get("name"):
                    names[mk.norm_ticker(x)] = row["name"]
        it["ticker_sectors"], it["ticker_names"] = secs, names
        if kind == "moves_like" and t and it.get("peers"):
            it["claims"] = moves_like_claims(t, [(p or {}).get("ticker") for p in it["peers"]])
        if kind in mk.MARKET_TYPES:
            continue
        ctx: dict = {}
        nums: list[str] = []
        cap = it.get("market_cap_usd")
        if t and isinstance(cap, (int, float)):
            ctx["market_cap"] = mk.usd_text(cap)
            nums += [mk.usd_text(cap), mk.about_usd(cap)]
        mv = m.move(t) if t else None
        if mv is not None and m.session:
            ctx["last_session_move"] = {"pct": mk.signed_pct(mv), "session": m.session}
            nums += [*mk.pct_forms(mv), *mk.date_words(m.session)]
        if kind == "form4_buy" and isinstance(ins.get("total_usd"), (int, float)):
            sold = (ins.get("sells") or {}).get("total_usd")
            ctx["insiders_30d"] = {"bought": mk.usd_text(ins["total_usd"]),
                                   "sold": mk.usd_text(sold) if isinstance(sold, (int, float)) else None}
            totals = mk.usd_forms(ins["total_usd"]) + (mk.usd_forms(sold) if isinstance(sold, (int, float)) else [])
            nums += totals + ["30"]
            it["context_tickers"] = [x for x in dict.fromkeys(buyers500) if x != t][:3]
            it["scoped_numbers"] = [{"numbers": totals, "require": [r"officers?\s+and\s+directors?", r"open[-\s]market"],
                                     "say": ("the 30-day totals are open-market buys / sells by officers and directors "
                                             "over 30 days in our feed: say \"open-market\" and \"officers and directors\"")}]
        if kind in ("congress_trade", "ptr_summary") and con.get("totals"):
            tot = con["totals"]
            ctx["congress_30d"] = {"buys": tot.get("buys"), "sells": tot.get("sells"), "members": tot.get("members")}
            nums += [str(tot.get("buys")), str(tot.get("sells")), str(tot.get("members")), "30"]
            row = next((x for x in con.get("top_tickers") or [] if t and mk.norm_ticker(x.get("ticker")) == t), None)
            if row:
                ctx["ticker_congress_30d"] = {k: row.get(k) for k in ("trades", "members", "buys", "sells")}
                nums += [str(row.get(k)) for k in ("trades", "members", "buys", "sells") if row.get(k) is not None]
        if ctx:
            it["context"] = ctx
            it["context_numbers"] = uniq([*it["context_numbers"], *nums])
        it.setdefault("angles", _angles(it, m))


def weekend_replay(it: dict, target: dt.date) -> bool:
    """On Saturday / Sunday facts, a single filing (or pattern) older than the last weekday session is not replayed."""
    if target.weekday() < 5 or it.get("type") not in WEEKEND_REPLAY_TYPES:
        return False
    key = RANK_DATE_FIELD.get(it["type"])
    try:
        return ss.weekday_age(ss.d(it.get(key)), target) >= 1
    except (TypeError, ValueError):
        return True


def small_cap_out(it: dict, fame: dict) -> str | None:
    """Why a form4_buy is left out by the small-cap gate (None: kept). Kept at cap >= $2B, or a fame.json person, or a
    $10M+ buy at cap >= $300M; a micro cap (< $300M) only for a fame.json person; an unknown cap only for a fame person."""
    if it.get("type") != "form4_buy":
        return None
    famous = bool(it.get("famous_person") or ss.matches_any(it.get("name") or "", fame.get("insiders") or []))
    if famous:
        return None
    cap, amt = it.get("market_cap_usd"), it.get("amount_top_usd") or 0
    if not isinstance(cap, (int, float)):
        return "cap unknown"
    if cap >= SMALL_CAP_MIN or (amt >= SMALL_CAP_BIG_BUY and cap >= MICRO_CAP):
        return None
    return "micro cap" if cap < MICRO_CAP else "small cap under $2B and a buy under $10M"


def cooldown(it: dict, target: dt.date, history: list[dict] | None) -> tuple[dict | None, str | None]:
    """(the item's cooldown field, why it is left out or None). The same item posted on every brand platform; its primary
    ticker posted on every platform within 3 trading days by another item (earnings results exempt); its filer posted
    within 7 days by another item."""
    if history is None:
        return None, None
    key, filer = it.get("dedupe_key"), ph.filer_of(it)
    lead = mk.headline_tickers(it)
    tick = lead[0] if lead else None  # the lead ticker, across pillars (a mega_mover post cools a market_move lead)
    same_on = sorted({p["platform"] for p in history if key and p.get("dedupe_key") == key})
    recent = recent_posts(history, target)
    tick_last = {}
    for p in recent:
        if tick and tick in post_tickers(p) and p.get("dedupe_key") != key:
            tick_last[p["platform"]] = p["ny_date"]
    filer_hits = [p for p in history if filer and p.get("filer") == filer and p.get("dedupe_key") != key
                  and p.get("ny_date") and 0 <= (target - ss.d(p["ny_date"])).days <= FILER_COOLDOWN_DAYS]
    field = {"same_item_posted_on": same_on, "ticker_last_posted": tick_last,
             "filer_last_posted": filer_hits[-1]["ny_date"] if filer_hits else None}
    if set(COOLDOWN_PLATFORMS) <= set(same_on):
        return field, "already posted on every platform"
    if it.get("type") != "earnings_result" and set(COOLDOWN_PLATFORMS) <= set(tick_last):
        return field, f"${tick} posted on every platform within {TICKER_COOLDOWN_SESSIONS} trading days"
    if filer_hits:
        return field, f"filer posted on {filer_hits[-1]['ny_date']} (within {FILER_COOLDOWN_DAYS} days)"
    return field, None


def apply_gates(items: list[dict], target: dt.date, fame: dict, history: list[dict] | None) -> tuple[list[dict], dict]:
    """Weekend replay, the small-cap gate and the cooldowns: (kept, left_out counts with one reason per item)."""
    left = {"weekend_replay": 0, "small_cap": 0, "cooldown": 0, "reasons": []}
    kept = []
    for it in items:
        tag = f"{it.get('type')} {it.get('ticker') or it.get('item_id')}"
        if weekend_replay(it, target):
            left["weekend_replay"] += 1
            left["reasons"].append(f"{tag}: weekend, filed before the last weekday session")
            continue
        why = small_cap_out(it, fame)
        if why:
            left["small_cap"] += 1
            left["reasons"].append(f"{tag}: {why}")
            continue
        field, why = cooldown(it, target, history)
        it["cooldown"] = field
        if why:
            left["cooldown"] += 1
            left["reasons"].append(f"{tag}: {why}")
            continue
        kept.append(it)
    return kept, left


TOP_N = 8                    # the menu Grok reads first
TOP_MAP_MAX = 2              # session-map items among them
TOP_MAP_TYPES = mk.WORDING_TYPES
TOP_PILLARS_MIN = 4


def headline_numbers(item: dict) -> list[str]:
    return [str(n) for n in (item.get("headline") or {}).get("numbers") or [] if n]


def top_block(it: dict, top: list[dict]) -> str | None:
    """Why `it` may not join `top` (None: it may): a second small / micro cap, a third session-map item, or a headline
    ticker / number another top item already leads with."""
    if it.get("cap_tier") in ("small", "micro") and any(t.get("cap_tier") in ("small", "micro") for t in top):
        return "small_cap: a second small / micro cap"
    if it.get("type") in TOP_MAP_TYPES and sum(1 for t in top if t.get("type") in TOP_MAP_TYPES) >= TOP_MAP_MAX:
        return f"session_map: already {TOP_MAP_MAX} session-map items (one market day does not fill the menu)"
    mine_t, mine_n = set(mk.headline_tickers(it)), set(headline_numbers(it))
    for t in top:
        dup_t = sorted(mine_t & set(mk.headline_tickers(t)))
        dup_n = sorted(mine_n & set(headline_numbers(t)))
        if dup_t or dup_n:
            what = ", ".join([*("$" + x for x in dup_t), *dup_n][:4])
            return f"repeat: leads with {what} like {t.get('item_id')}"
    return None


def diversify_top(items: list[dict]) -> tuple[list[dict], dict]:
    """The first TOP_N items, picked in rank order under top_block, with at least TOP_PILLARS_MIN distinct pillars when
    the day has them (a slot is kept for a new pillar while one is still possible). The rest follow in rank order with
    top8_out = the first rule that keeps them out (or "ranked below the top 8"). (items, counts)"""
    pool = list(items)
    top: list[dict] = []
    want = min(TOP_PILLARS_MIN, len({i.get("pillar") for i in pool if i.get("pillar")}))
    while len(top) < TOP_N:
        ok = [i for i in pool if i not in top and top_block(i, top) is None]
        if not ok:
            break
        have = {t.get("pillar") for t in top}
        need = want - len(have)
        fresh = [i for i in ok if i.get("pillar") and i.get("pillar") not in have]
        top.append(fresh[0] if need >= TOP_N - len(top) and fresh else ok[0])
    top.sort(key=lambda i: pool.index(i))
    rest = [i for i in pool if i not in top]
    counts = {"small_cap": 0, "session_map": 0, "repeat": 0, "ranked_below": 0,
              "pillars": len({t.get("pillar") for t in top if t.get("pillar")})}
    for it in top:
        it["top8"] = True
        it.pop("top8_out", None)
    for it in rest:
        why = top_block(it, top) or "ranked below the top 8"
        it["top8"], it["top8_out"] = False, why
        counts[why.split(":")[0] if ":" in why else "ranked_below"] += 1
    return top + rest, counts


def self_check(items: list[dict]) -> tuple[list[dict], list[str], int]:
    """Each item's own facts_text and angles through claims.content_reasons: an angle that fails is dropped, an item whose
    facts_text fails is not published. (kept items, errors, angles dropped)"""
    kept, errors, dropped = [], [], 0
    for it in items:
        bad = cl.content_reasons(it, it.get("facts_text") or "")
        if bad:
            errors.append(f"self-check: {it.get('type')} {it.get('ticker') or it.get('item_id')} not built: {bad[0][:200]}")
            continue
        good = [a for a in it.get("angles") or [] if not cl.content_reasons(it, a)]
        dropped += len(it.get("angles") or []) - len(good)
        it["angles"] = good
        kept.append(it)
    return kept, errors, dropped


def previous_state(repo: Path, target: dt.date, days: int = 7) -> dict | None:
    """market_state of the newest facts file before the target date (the flow top-5 lists), or None."""
    for n in range(1, days + 1):
        p = Path(repo) / "v" / (target - dt.timedelta(days=n)).isoformat() / "facts.json"
        if p.exists():
            try:
                st = json.loads(p.read_text(encoding="utf-8-sig")).get("market_state")
            except (OSError, ValueError):
                continue
            if isinstance(st, dict):
                return st
    return None


# ---------------------------------------------------------------------------
# Feed

def default_as_of(target: dt.date, now: dt.datetime) -> dt.datetime:
    """Now, or the end of the date's New York day when that is earlier (a past date)."""
    if ss.NY is None:
        return now
    end = dt.datetime(target.year, target.month, target.day, 23, 59, 59, tzinfo=ss.NY).astimezone(dt.timezone.utc)
    return min(now, end)


def ptr_summary_reason(skipped: int, capped: int) -> str:
    """Why the file has no ptr_summary: incomplete filings (left_out.ptr_summary_incomplete), the per-filer cap, or none."""
    why = []
    if skipped:
        why.append(f"{skipped} member filing date(s) with 2+ Congress items were not whole filings "
                   "(left_out.ptr_summary_incomplete)")
    if capped:
        why.append(f"{capped} member summary(ies) lost to a higher-ranked congress_trade of the same filer "
                   "(left_out.per_filer_cap)")
    return "; ".join(why) or "no member has 2+ Congress items on one filing date in the last 5 weekdays"


def build_facts(target: dt.date, api, fame: dict, now: dt.datetime | None = None, as_of: dt.datetime | None = None,
                previous: dict | None = None, history: list[dict] | None = None, history_error: str | None = None,
                before_state: dict | None = None) -> dict:
    """history: our own posts (post_history.load; None = not read: no cooldown, no novelty term, the error is listed);
    before_state: the previous facts day's market_state (flow top-5 lists)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    as_of = as_of or default_as_of(target, now)
    errors: list[str] = []
    partial: list[str] = []  # core sources that failed: exit 4
    reasons: dict[str, str] = {}
    left: dict[str, dict] = {}
    items: list[dict] = []

    names_data, nerr = api.get("/tickers/names")
    names = names_data.get("names") if isinstance(names_data, dict) and isinstance(names_data.get("names"), dict) else {}
    if nerr or not names:
        errors.append(nerr or "/tickers/names: empty")
        partial.append("tickers_names")
        for k in ("congress_trade", "form4_buy", "ptr_summary"):
            reasons[k] = f"the ticker list did not load ({nerr or 'empty'}): no trade can be checked as listed"
    else:
        c, left["congress_trade"], cerr, coverage = congress_items(api, target, names)
        if cerr:
            errors.append(cerr)
            partial.append("congress_trade")
            reasons["congress_trade"] = f"the Congress feed did not load ({cerr})"
        elif not c:
            reasons["congress_trade"] = "no Congress trade passed the rules in the last 5 weekdays (left_out has the counts)"
        ps, left["ptr_summary"], left["ptr_summary_incomplete"] = ptr_summary_items(target, c, fame, coverage)
        filers = len({i.get("figure_slug") or i.get("name") for i in c})
        kept, capped = cap_per_filer(c + ps, target, fame)
        left["per_filer_cap"] = {"dropped": sum(capped.values()), "filers": filers,
                                 "dropped_congress_trade": capped["congress_trade"],
                                 "dropped_ptr_summary": capped["ptr_summary"]}
        if not any(i["type"] == "ptr_summary" for i in kept):
            reasons["ptr_summary"] = ptr_summary_reason(left["ptr_summary_incomplete"]["skipped"], capped["ptr_summary"])
        items += kept
        f, left["form4_buy"], ferr = form4_items(api, target, names, fame)
        errors += ferr
        if ferr:
            partial.append("form4_buy")
            reasons["form4_buy"] = f"the insider feed did not load ({'; '.join(ferr)})"
        elif not f:
            reasons["form4_buy"] = ("no material open-market Form 4 buy ($1M+ or a famous executive) filed in the "
                                    "last 5 weekdays")
        items += f

    r, left["earnings_result"], rerr = result_items(api, target, as_of)
    errors += rerr
    if rerr:
        partial.append("earnings_result")
    if not r:
        reasons["earnings_result"] = (f"earnings reports did not load ({'; '.join(rerr)})" if rerr else
                                      f"no earnings report published between {(as_of - dt.timedelta(hours=RESULT_HOURS)):%Y-%m-%dT%H:%MZ} "
                                      f"and {as_of:%Y-%m-%dT%H:%MZ}")
    items += r

    u, left["earnings_upcoming"], uerr, ureason = upcoming_items(api, target, names, now)
    errors += uerr
    if uerr:
        partial.append("earnings_upcoming")
    if ureason:
        reasons["earnings_upcoming"] = ureason
    eu, left["earnings_tomorrow_roundup"] = earnings_roundup_items(target, u)
    if not eu:
        reasons["earnings_tomorrow_roundup"] = (ureason or "no session (before the open / after the close) of the next "
                                                "weekday has 2+ confirmed reporters in our universe")
    items += u + eu

    p, preason = picks_items(api, target)
    if preason:
        reasons["picks_ready"] = preason
        if "did not load" in preason:
            errors.append(f"/tips/daily: {preason}")
            partial.append("picks_ready")
    items += p

    if names:
        cp, left["chart_pattern"], cperr, cpreason = pattern_items(api, target, names)
        errors += cperr
        items += cp
    else:
        cpreason = f"the ticker list did not load ({nerr or 'empty'}): the tile cannot be checked as listed"
    if cpreason:
        reasons["chart_pattern"] = cpreason

    items = rank_items(items, target, fame)  # Moves Like looks up the most newsworthy tickers first
    m, left["moves_like"], merr, checked = moves_like_items(api, target, items, previous)
    errors += merr
    if not m:
        reasons["moves_like"] = (f"Moves Like did not load ({'; '.join(merr)})" if merr else
                                 f"no ticker of today's items has a Moves Like peer at Sync {MOVES_LIKE_SYNC_FLOOR}+ "
                                 "(left_out has the counts)"
                                 if checked else "no ticker in today's other items to look up")
    items += m

    # Market pillars (HQ 2026-10-18): non-core sources (a failed read is an error, its items are not built)
    mi, left["market"], mreasons, merrs, market_state, mkt = market_items(api, target, now, before_state)
    errors += merrs
    reasons.update({k: v for k, v in mreasons.items() if not any(i["type"] == k for i in mi)})
    items += mi
    enrich(items, mkt)
    if history_error:
        errors.append(history_error)
    items, serr, sdrop = self_check(items)
    errors += serr
    items, left["gates"] = apply_gates(items, target, fame, history)
    left["gates"]["self_check"] = {"items_not_built": len(serr), "angles_dropped": sdrop}

    items, leaks = screen_holdout(rank_items(items, target, fame, history), target)
    if leaks:
        errors += [f"not built: {why}" for why in leaks]
        left["g_n1_holdout"] = {"dropped": len(leaks), "reasons": leaks}
    items, top = diversify_top(items)
    left["gates"]["top8"] = top

    counts = {k: sum(1 for i in items if i["type"] == k) for k in TYPES}
    return {
        "schema": SCHEMA,
        "date": target.isoformat(),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rules": {
            "banned_words": BANNED_WORDS,
            "disclaimer": DISCLAIMER,
            "max_len": MAX_LEN,
            "platforms": PLATFORMS,
            "platform_placeholder": PLATFORM_PLACEHOLDER,
            "numbers": ("every number, date or amount in a post must be one of the item's allowed_numbers or "
                        "context_numbers, as written there (- and − alike); never the same number twice in a post"),
            "picks": "never name or hint at the #1 pick; it is locked and not in this file",
            "no_advice": "no buy / sell calls, predictions or price targets; every post carries the disclaimer",
            "descriptive": ("chart_pattern and moves_like describe what happened only (no forecasts; their items' "
                            "banned_words apply too); moves_like may cashtag only the peers listed in its item"),
            "cashtags": ("at most 4 distinct cashtags, all from the item's tickers + context_tickers; a single-ticker item "
                         "names its own $TICKER; moves_like may add its peers, picks_ready the public picks"),
            "order": ("items are sorted by audience_rank (rank / rank_why: recognisability, magnitude, freshness, novelty); "
                      "the first 8 (top8 true) are a varied menu: at most 2 session-map items (P1 P2 P6 P7), at most one "
                      "small cap, no lead ticker or headline number repeated between them, 4+ pillars when the day has "
                      "them; items below carry top8_out (why). Pick across pillars per variety"),
            "claims": ("comparatives and superlatives (led, biggest, largest, worst, best, most, least, only, first, top, "
                       "#1, record, 'outperformed every other') only as the item's claims state them: name only that "
                       "claim's companies / sectors in that sentence; each claim has a polarity (best = top gainer, worst "
                       "= top loser, null = no side) and a rank (1 = its one subject is #1; group = its subjects are the "
                       "top N in order) and a metric (usd_change, pct_change, market_cap, ...): say the side with the "
                       "noun ('top loser', 'led the drop', 'biggest gainer'; 'top' / 'led' / '#1' alone read as best, "
                       "whatever number stands beside them), say the metric as the claim does (dollars vs percent vs "
                       "market cap), the singular ('the biggest drop') only for the rank-1 subject, a list only from #1 "
                       "in order, 'among the biggest' for other members, 'the two biggest' only for exactly the top 2; "
                       "'of the 500' / 'overall' only with a claim that has no within, 'of the 10' for the basket; a "
                       "sector only as a sector claim (kind sector) says, a stock 'within' a sector only with that sector "
                       "or 'its sector' named; never widen the window ('ever', 'in months', 'of the quarter', 'since "
                       "September', a week on a one-session item) or call the session 'today' / 'yesterday' unless the "
                       "item's when does; no negated comparisons; never say a stock led its sector unless "
                       "sector_leaders / claims say so; never put a company in a sector its ticker_sectors entry does "
                       "not show"),
            "pillars": {"P0": "picks + scoreboard (max 1 a day per platform)", "P1": "market day (market_move)",
                        "P2": "big-name movers (mega_mover)",
                        "P3": "smart money in names you know (congress_flow, insider_flow, form4_buy, congress_trade, ptr_summary)",
                        "P4": "Reddit buzz vs usual (reddit_buzz)",
                        "P5": "earnings (earnings_result, earnings_upcoming, earnings_tomorrow_roundup, earnings_week_preview, earnings_reaction)",
                        "P6": "sector rotation (sector_rotation)", "P7": "breadth and the typical stock (breadth_day, basket_week)",
                        "PX": "automatic analysis (chart_pattern, moves_like)"},
            "variety": ["no same pillar twice in a row among a platform's own posts",
                        "at most 2 posts per pillar per platform per day",
                        "the same primary ticker on one platform not within 3 trading days (earnings results exempt)",
                        "a first line sharing >= 60% of its first 8 words with one of the platform's last 10 own posts is rejected",
                        "the same item on 2+ platforms: a different first line and >= 30% different wording",
                        "market-level pillars (P1 P2 P3 flows P4 P6 P7) >= 50% of own posts per platform per week; single "
                        "filings <= 25%; picks <= 1 a day; <= 1 small-cap post in 4 (defaults; Growth tunes them)",
                        "the item's angles are first-line seeds, not templates: rotate the angle per pillar"],
            "wording": (f"every post of every item type: our universe is '{mk.UNIVERSE_WORDS}' (or 'the 500 largest "
                        "US-listed companies'), never 'S&P 500', 'S&P', 'SPX' or 'the index' (only a picks post may compare "
                        "with the benchmark, as 'vs SPY'); 'the 10 largest US-listed companies', not 'US companies'; a "
                        "5-session window is worded as the item's when field says ('in the week to Oct 16', 'last week'); "
                        "the 30-day insider totals are 'open-market buys / sells by officers and directors over 30 days in "
                        "our feed'; a post never contradicts its card (card_message); market items: no 'crash', "
                        "'bloodbath', 'dump'"),
            "cards": ("a market item's media is its pinned share card (card.url, a file on our Pages site, the same numbers "
                      "the item states); never the live /market/card/ URL, never another day's card; no link in the main "
                      "post: the UTM link goes in a self-reply"),
        },
        "counts": counts,
        "reasons": reasons,
        "left_out": left,
        "errors": errors,
        "partial_sources": partial,
        "moves_like_checked": checked,
        "market_state": market_state,
        "post_history": {"read": history is not None, "own_posts": len(history) if history is not None else None},
        "api_requests": getattr(api, "requests", None),
        "items": items,
    }


# ---------------------------------------------------------------------------
# Comparing two feeds (the runner publishes only when the item set changed)

def item_set(facts: dict) -> set[tuple[str, str, tuple[str, ...]]]:
    """item_id, dedupe_key and the media URLs of every item (a card Reel added to an item's media is a change to publish),
    plus one entry for the rules block: new rules (a pipeline change, e.g. the 10-18 review fixes) republish the day's
    file once; a reworded facts_text alone still does not."""
    out = {(str(i.get("item_id")), str(i.get("dedupe_key")),
            tuple(str(m.get("url")) for m in i.get("media") or [] if isinstance(m, dict)))
           for i in facts.get("items") or [] if isinstance(i, dict)}
    rules = hashlib.sha1(json.dumps(facts.get("rules") or {}, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    out.add(("(rules)", rules, ()))
    return out


def read_facts(where: str) -> dict:
    """A facts file, or an https URL read past the Pages cache (a fresh query string, no-cache)."""
    if re.match(r"^https?://", where):
        url = f"{where}{'&' if '?' in where else '?'}fresh={time.time_ns()}"
        req = urllib.request.Request(url, headers={"User-Agent": ss.UA, "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8-sig"))
    return json.loads(Path(where).read_text(encoding="utf-8-sig"))


def compare_items(old: str, new: str) -> int:
    try:
        a, b = item_set(read_facts(old)), item_set(read_facts(new))
    except (OSError, ValueError, urllib.error.URLError) as e:
        print(f"unreadable: {type(e).__name__}: {str(e)[:200]}")
        return 2
    if a == b:
        print(f"same items ({len(b)})")
        return 0
    print(f"changed: {len(b)} items, {len(b - a)} new, {len(a - b)} gone")
    return 1


def print_facts(f: dict) -> None:
    print(f"facts {f['date']} (as of {f['as_of']}): {len(f['items'])} items " +
          ", ".join(f"{k} {n}" for k, n in f["counts"].items()))
    for k, why in f["reasons"].items():
        print(f"  {k}: empty: {why}")
    for i in f["items"]:
        print(f"  {i['item_id']}: {i['facts_text']}")
    for e in f["errors"]:
        print(f"  error: {e}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date")
    ap.add_argument("--compare-items", nargs=2, metavar=("OLD", "NEW"))
    ap.add_argument("--previous", help="the day's published facts.json: Moves Like answers of the day are carried over")
    ap.add_argument("--out")
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--repo", default=str(mf.REPO))
    ap.add_argument("--fame", default=str(ss.TOOLS / "fame.json"))
    ap.add_argument("--api", default=ss.API)
    ap.add_argument("--as-of", help="end of the 24-hour earnings window (ISO, UTC if no offset)")
    ap.add_argument("--no-history", action="store_true", help="do not read our own posts (no cooldowns, no novelty term)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.compare_items:
        return compare_items(*a.compare_items)
    if not a.date:
        ap.error("--date is required")
    target = ss.d(a.date)
    fame = json.loads(Path(a.fame).read_text(encoding="utf-8"))
    as_of = _ts(a.as_of) if a.as_of else None
    previous = None
    if a.previous and Path(a.previous).exists():
        try:
            previous = read_facts(a.previous)
        except (OSError, ValueError) as e:
            print(f"--previous unreadable ({type(e).__name__}): every Moves Like ticker is asked again")
    history, herr = (None, "post history: not read (--no-history)") if a.no_history else ph.load(Path(a.repo), now=None)
    facts = build_facts(target, ss.Api(a.api), fame, as_of=as_of, previous=previous, history=history, history_error=herr,
                        before_state=previous_state(Path(a.repo), target))
    out = Path(a.out) if a.out else Path(a.repo) / "v" / target.isoformat() / "facts.json"
    leaks = holdout_doc_leaks(facts, target)
    if leaks:
        print(f"NOT WRITTEN: {', '.join(leaks)} carry an earnings report page ({ss.G_N1_REASON}); {out} not updated")
        return HOLDOUT_LEAK
    mf.write_json(out, facts)
    if a.print:
        print_facts(facts)
    print(f"wrote {out} ({facts['api_requests']} API requests)")
    return PARTIAL if facts["partial_sources"] else 0


if __name__ == "__main__":
    sys.exit(main())
