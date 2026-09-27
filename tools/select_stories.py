"""Pick the day's video stories from RapidTradeView's public API (https://api.rapidtradeview.trade).

Usage (conda python: C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe):
  select_stories.py --date YYYY-MM-DD [--out plan.json] [--print] [--repo DIR] [--track-record FILE]

Output: a plan JSON (schema rtv-daily-plan/1) with one entry per slot of the owner-approved grid
(manifest.WEEKDAY_SLOTS / WEEKEND_SLOTS): the story, its filing / source URLs, or why the slot is empty.
Weak items never pad a slot: an empty slot says why.

Weekday grid (New York time; run_daily.ps1 fills it in three passes: 06:15 slots 1-3, 6-7; 10:30
reports 5 and 7; 13:45 picks 4):
  1 08:00  earnings: Monday = the week's confirmed reporters; Tue-Fri = today's, else the rest of the week
  2 09:45  best trade        3 11:00  second trade        6 16:30  third trade
  4 14:00  daily picks (#1 locked): the list /tips/daily serves at 14:00, i.e. today's (published ~13:30);
           before it is out the slot is empty, never the previous day's list
  5 15:00  earnings report summary #1 (released since the previous weekday, consensus confirmed)
  7 19:00  report #2, else the weekday theme (Mon Congress last week, Tue Congress 30 days, Wed person
           spotlight, Thu track record paragraph, Fri the week's top insider buys)
Weekends: one post. Saturday = next week's confirmed earnings; Sunday = the best trade of the week.

Trades are ranked by fame x dollar size x recency x novelty:
  fame     famous person (fame.json) or company size (market cap from /snapshot): mega 0.9, large 0.6,
           mid 0.3, small 0.1, unknown 0.05; combined as 1 - (1 - person)(1 - company)
  size     log scale, $1K -> 0, $1M -> 0.5, $1B -> 1 (insiders: value; Congress: range midpoint)
  recency  filed within the last 3 weekdays (weekends 5): age 0 -> 1.0, 1 -> 0.85, 2 -> 0.7, 3 -> 0.55,
           4 -> 0.45, 5 -> 0.35, then -0.01 per weekday down to 0.15 (backlog)
  novelty  0 when the filing (or the same person in the same ticker within 30 days) is in an earlier
           manifest; 0.5 when the person or the ticker was posted in the last 14 days; else 1
Minimums: insider purchases of $1M+ or a famous executive (fame.json, or CEO / Chair / President of a
$200B+ company); Congress trades of $15K+ (range low) or a famous member. Insider sales and
pre-planned (10b5-1 marked) buys are left out.
A trade slot takes a recent trade scoring >= 0.30 (MIN_TRADE_SCORE). Below that it takes the BACKLOG:
trades by a famous person (fame.json, or a famous executive) filed within the last 30 days and in no
earlier manifest, ranked by the same score. Nothing qualifies -> the slot stays empty.

Amounts: one story = one Form 4 here (its API rows summed). A buying program often spans several
Form 4s (Berkshire's LEN buys: 2026-09-21 $212.4M and 2026-09-25 $136.4M), so the API figure is never
"the total": the trade template takes every number from the SEC XML of the filing(s) it shows.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402

API = "https://api.rapidtradeview.trade"
SITE = "https://www.rapidtradeview.trade"
UA = "RapidTradeView daily-video selector (contact@rapidtradeview.trade)"
PLAN_SCHEMA = "rtv-daily-plan/1"
TOOLS = Path(__file__).resolve().parent
DEFAULT_TRACK_RECORD = Path("D:/rtv-ops/tracks/growth/social-kit/track-record-paragraph.json")

RECENCY_WEEKDAYS = 3
WEEKEND_WINDOW_WEEKDAYS = 5
MIN_TRADE_SCORE = 0.30
BACKLOG_DAYS = 30
INSIDER_MIN_USD = 1_000_000
CONGRESS_MIN_LOW = 15_000
EARNINGS_MIN_CAP = 10e9
REPORT_MIN_CAP = 10e9
NOVELTY_DAYS = 14
SAME_TRADE_DAYS = 30
MAX_SNAPSHOTS = 40
RECENCY = {0: 1.0, 1: 0.85, 2: 0.7, 3: 0.55, 4: 0.45, 5: 0.35}


def recency(age: int) -> float:
    return RECENCY[age] if age in RECENCY else round(max(0.15, 0.35 - 0.01 * (age - 5)), 3)
TEMPLATES = {
    "insider_trade": "trade", "congress_trade": "trade",
    "earnings_today": "earnings_week", "earnings_week": "earnings_week",
    "earnings_report": "report_summary", "daily_picks": "daily_picks",
    "congress_week": "congress_theme", "congress_30d": "congress_theme", "congress_theme": "congress_theme",
    "person_spotlight": None, "track_record": None, "insider_week": None,
}
WEEKDAY_THEMES = {0: "congress_week", 1: "congress_30d", 2: "person_spotlight", 3: "track_record", 4: "insider_week"}
NY = None
try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - tzdata missing
    NY = None


# ---------------------------------------------------------------------------
# API

class Api:
    def __init__(self, base: str = API):
        self.base = base
        self.cache: dict[str, tuple[object, str | None]] = {}
        self.requests = 0

    def get(self, path: str) -> tuple[object, str | None]:
        """(data, None) or (None, error). Two tries; errors carry the status, never a body."""
        if path in self.cache:
            return self.cache[path]
        err = "request failed"
        for _ in range(2):
            self.requests += 1
            req = urllib.request.Request(f"{self.base}{path}", headers={"User-Agent": UA, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    out = (json.loads(r.read().decode("utf-8")), None)
                    self.cache[path] = out
                    return out
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}"
                if e.code < 500:
                    break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                err = f"{type(e).__name__}"
        out = (None, f"{path}: {err}")
        self.cache[path] = out
        return out


# ---------------------------------------------------------------------------
# Helpers

def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


def weekday_age(filed: dt.date, target: dt.date) -> int:
    """Weekdays after the filing day up to and including the target (filed Fri, target Mon -> 1)."""
    if filed >= target:
        return 0
    n, cur = 0, filed
    while cur < target:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def prev_weekday(day: dt.date) -> dt.date:
    cur = day - dt.timedelta(days=1)
    while cur.weekday() >= 5:
        cur -= dt.timedelta(days=1)
    return cur


def week_monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


STOP = {"jr", "sr", "ii", "iii", "iv", "inc", "llc", "lp", "l", "p", "co", "corp", "et", "al", "the", "ltd", "plc", "mr", "ms", "dr"}


def tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", name.lower().replace("-", " ")) if t not in STOP and len(t) > 1}


def matches_any(name: str, entries: list[str]) -> str | None:
    have = tokens(name)
    for e in entries:
        need = tokens(e)
        if need and need <= have:
            return e
    return None


def same_person(a: str, b: str) -> bool:
    ta, tb = tokens(a), tokens(b)
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small) >= 2 and small <= big


def slugify(text: str, words: int = 3) -> str:
    parts = [p for p in re.findall(r"[a-z0-9]+", text.lower()) if p not in STOP][:words]
    return "-".join(parts) or "story"


ENTITY = re.compile(r"\b(inc|llc|l\.?p|lp|ltd|plc|corp|co|capital|partners|holdings|fund|funds|management|advisors|"
                    r"investments?|trust|group|hathaway|foundation|ventures|et al)\b", re.IGNORECASE)


TOP_OFFICER = re.compile(r"\b(ceo|chief executive|chair|president)\b", re.IGNORECASE)


def name_slug(name: str) -> str:
    """Short story-id part: a person's last name ("uber-khosrowshahi"), an entity's first two words."""
    words = [p for p in re.findall(r"[a-z0-9]+", name.lower()) if p not in STOP and len(p) > 1]
    if not words:
        return "story"
    return "-".join(words[:2]) if ENTITY.search(name) else words[-1]


def sec_index_url(api_source_url: str | None) -> tuple[str | None, str | None]:
    """(accession with dashes, EDGAR filing index page) from an EDGAR archive URL."""
    if not api_source_url:
        return None, None
    m = re.search(r"/Archives/edgar/data/(\d+)/(\d{18})/", api_source_url)
    if not m:
        return None, None
    raw = m.group(2)
    acc = f"{raw[:10]}-{raw[10:12]}-{raw[12:]}"
    return acc, f"https://www.sec.gov/Archives/edgar/data/{m.group(1)}/{raw}/{acc}-index.htm"


def usd_short(v: float) -> str:
    if v >= 1e9:
        return f"${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:.1f}M"
    return f"${v / 1e3:.0f}K"


def slot_datetime_utc(day: dt.date, hhmm: str) -> dt.datetime | None:
    if NY is None:
        return None
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=NY).astimezone(dt.timezone.utc)


# ---------------------------------------------------------------------------
# Prior manifests (novelty)

@dataclass
class Posted:
    date: dt.date
    story_key: str
    tickers: list[str]
    people: list[str]


def prior_posts(repo: Path, target: dt.date, days: int = 60) -> list[Posted]:
    out: list[Posted] = []
    for path in sorted((repo / "v").glob("*/manifest.json")):
        try:
            day = d(path.parent.name)
        except ValueError:
            continue
        if not (target - dt.timedelta(days=days) <= day < target):
            continue
        try:
            m = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        for p in m.get("posts", []):
            out.append(Posted(day, str(p.get("story_key", "")), list(p.get("tickers") or []), list(p.get("people") or [])))
    return out


def novelty(key: str, tickers: list[str], people: list[str], target: dt.date, prior: list[Posted]) -> tuple[float, str | None]:
    for p in prior:
        if p.story_key == key:
            return 0.0, f"already posted {p.date} ({key})"
        age = (target - p.date).days
        same_t = bool(set(tickers) & set(p.tickers))
        same_p = any(same_person(a, b) for a in people for b in p.people)
        if same_t and same_p and age <= SAME_TRADE_DAYS:
            return 0.0, f"same person and ticker posted {p.date}"
    for p in prior:
        age = (target - p.date).days
        if age <= NOVELTY_DAYS and (set(tickers) & set(p.tickers) or any(same_person(a, b) for a in people for b in p.people)):
            return 0.5, f"person or ticker posted {p.date}"
    return 1.0, None


# ---------------------------------------------------------------------------
# Trades

@dataclass
class Trade:
    kind: str  # insider | congress
    name: str
    slug: str
    ticker: str
    side: str
    filed: dt.date
    role: str | None = None
    party: str | None = None
    chamber: str | None = None
    state: str | None = None
    owner: str | None = None
    value_usd: float = 0.0
    low: float = 0.0
    high: float = 0.0
    shares: float = 0.0
    rows: int = 0
    trade_ids: list[int] = field(default_factory=list)
    traded: list[str] = field(default_factory=list)
    api_source_url: str | None = None
    famous_person: str | None = None
    company: str | None = None
    market_cap: float | None = None
    score: float = 0.0
    parts: dict = field(default_factory=dict)
    novelty_note: str | None = None
    source: str = "recent"  # recent | backlog

    @property
    def usd(self) -> float:
        return self.value_usd if self.kind == "insider" else (self.low + self.high) / 2

    @property
    def story_key(self) -> str:
        if self.kind == "insider":
            acc, _ = sec_index_url(self.api_source_url)
            return f"form4:{acc or self.slug + ':' + self.filed.isoformat()}:{self.ticker}"
        doc = (self.api_source_url or "").rstrip("/").rsplit("/", 1)[-1] or f"{self.slug}-{self.filed}"
        return f"ptr:{doc}:{self.ticker}:{self.side}"


def fetch_feed(api: Api, tab: str, since: dt.date, extra: str = "", pages: int = 5) -> tuple[list[dict], str | None]:
    items: list[dict] = []
    for page in range(pages):
        data, err = api.get(f"/notable/feed?tab={tab}{extra}&limit=200&offset={page * 200}")
        if err:
            return items, err
        batch = data.get("items") if isinstance(data, dict) else None
        if not isinstance(batch, list):
            return items, f"/notable/feed?tab={tab}: unreadable response"
        items.extend(batch)
        dates = [x.get("disclosure_date") for x in batch if isinstance(x, dict) and x.get("disclosure_date")]
        if not data.get("has_more") or not dates or min(dates) < since.isoformat():
            break
    return items, None


def listed(ticker: str | None, names: dict[str, str]) -> bool:
    if not ticker or not mf.TICKER.match(ticker) or ticker in {"NONE", "NA", "NULL", "UNKNOWN", "TBD"}:
        return False
    return ticker in names or ticker.replace(".", "-") in names


def gather_trades(api: Api, target: dt.date, window: int, names: dict[str, str], fame: dict, pages: int = 5) -> tuple[list[Trade], dict, list[str]]:
    """Grouped trades filed within `window` weekdays of the target; counts of what was left out; errors."""
    since = target
    while weekday_age(since - dt.timedelta(days=1), target) <= window:
        since -= dt.timedelta(days=1)
    dropped = {"out_of_window": 0, "not_listed": 0, "sale_or_other": 0, "pre_planned": 0, "flagged_value": 0, "below_minimum": 0}
    errors: list[str] = []
    groups: dict[tuple, Trade] = {}

    ins, err = fetch_feed(api, "insiders", since, "&side=buy", pages)
    if err:
        errors.append(err)
    for it in ins:
        if not isinstance(it, dict) or not isinstance(it.get("figure"), dict):
            continue
        filed = it.get("disclosure_date")
        if not filed or weekday_age(d(filed), target) > window or d(filed) > target:
            dropped["out_of_window"] += 1
            continue
        fig, amt = it["figure"], it.get("amount") or {}
        if it.get("side") != "buy" or fig.get("kind") != "insider":
            dropped["sale_or_other"] += 1
            continue
        if (it.get("trading_plan") or {}).get("status") == "pre_planned":
            dropped["pre_planned"] += 1
            continue
        if amt.get("value_flag") is not None or not isinstance(amt.get("value_usd"), (int, float)):
            dropped["flagged_value"] += 1
            continue
        ticker = (it.get("ticker") or "").upper()
        if not listed(ticker, names):
            dropped["not_listed"] += 1
            continue
        key = ("insider", fig.get("slug"), ticker, filed, sec_index_url(it.get("source_url"))[0])
        t = groups.get(key)
        if t is None:
            t = groups[key] = Trade("insider", fig.get("display_name") or "", fig.get("slug") or "", ticker, "buy", d(filed),
                                    role=fig.get("title") or fig.get("role"), owner=it.get("owner"), api_source_url=it.get("source_url"))
        t.value_usd += float(amt["value_usd"])
        t.shares += float(amt.get("shares") or 0)
        t.rows += 1
        t.trade_ids.append(it.get("trade_id"))
        if it.get("transaction_date"):
            t.traded.append(it["transaction_date"])

    cong, err = fetch_feed(api, "congress", since, "", pages)
    if err:
        errors.append(err)
    for it in cong:
        if not isinstance(it, dict) or not isinstance(it.get("figure"), dict):
            continue
        filed = it.get("disclosure_date")
        if not filed or weekday_age(d(filed), target) > window or d(filed) > target:
            dropped["out_of_window"] += 1
            continue
        fig, amt = it["figure"], it.get("amount") or {}
        if it.get("side") not in ("buy", "sell") or fig.get("kind") != "politician":
            dropped["sale_or_other"] += 1
            continue
        ticker = (it.get("ticker") or "").upper()
        if not listed(ticker, names):
            dropped["not_listed"] += 1
            continue
        if amt.get("low") is None and amt.get("high") is None:
            dropped["flagged_value"] += 1
            continue
        key = ("congress", fig.get("slug"), ticker, it["side"], it.get("source_url"))
        t = groups.get(key)
        if t is None:
            t = groups[key] = Trade("congress", fig.get("display_name") or "", fig.get("slug") or "", ticker, it["side"], d(filed),
                                    party=fig.get("party"), chamber=fig.get("chamber"), state=fig.get("state"),
                                    owner=it.get("owner"), api_source_url=it.get("source_url"))
        t.low += float(amt.get("low") or 0)
        t.high += float(amt.get("high") or amt.get("low") or 0)
        t.rows += 1
        t.trade_ids.append(it.get("trade_id"))
        if it.get("transaction_date"):
            t.traded.append(it["transaction_date"])

    trades = []
    for t in groups.values():
        t.famous_person = matches_any(t.name, fame["insiders"] if t.kind == "insider" else fame["members"])
        trades.append(t)
    return trades, dropped, errors


def company_info(api: Api, ticker: str) -> tuple[str | None, float | None]:
    data, err = api.get(f"/snapshot/{urllib.parse.quote(ticker)}")
    if err or not isinstance(data, dict):
        return None, None
    stats = ((data.get("profile") or {}).get("stats") or {})
    cap = stats.get("market_cap")
    return data.get("company_name"), float(cap) if isinstance(cap, (int, float)) and cap > 0 else None


def company_fame(cap: float | None, tiers: dict) -> float:
    if cap is None:
        return 0.05
    if cap >= tiers["mega"]:
        return 0.9
    if cap >= tiers["large"]:
        return 0.6
    if cap >= tiers["mid"]:
        return 0.3
    return 0.1


def famous_exec(t: Trade, tiers: dict) -> bool:
    if t.famous_person:
        return True
    return bool(TOP_OFFICER.search(t.role or "")) and (t.market_cap or 0) >= tiers["mega"]


def rank_trades(api: Api, trades: list[Trade], target: dt.date, fame: dict, prior: list[Posted], dropped: dict) -> list[Trade]:
    tiers = fame["company_tiers_usd"]
    # Cheap bar first (dollar minimum, famous person, or a top officer's $100K+ buy that may be at a
    # $200B+ company), so /snapshot is read only for real candidates.
    pre = [t for t in trades if t.famous_person or (t.kind == "insider" and t.value_usd >= INSIDER_MIN_USD)
           or (t.kind == "congress" and t.low >= CONGRESS_MIN_LOW)
           or (t.kind == "insider" and t.value_usd >= 100_000 and TOP_OFFICER.search(t.role or ""))]
    pre.sort(key=lambda t: -t.usd)
    for t in pre[:MAX_SNAPSHOTS]:
        t.company, t.market_cap = company_info(api, t.ticker)
    kept = []
    for t in pre:
        ok = (t.value_usd >= INSIDER_MIN_USD or famous_exec(t, tiers)) if t.kind == "insider" else (t.low >= CONGRESS_MIN_LOW or bool(t.famous_person))
        if not ok:
            dropped["below_minimum"] += 1
            continue
        person = 1.0 if (t.famous_person or (t.kind == "insider" and famous_exec(t, tiers))) else 0.0
        comp = company_fame(t.market_cap, tiers)
        fame_score = 1 - (1 - person) * (1 - comp)
        size = min(1.0, max(0.05, math.log10(max(t.usd, 1e3) / 1e3) / 6))
        rec = recency(weekday_age(t.filed, target))
        nov, note = novelty(t.story_key, [t.ticker], [t.name], target, prior)
        t.parts = {"fame": round(fame_score, 3), "size": round(size, 3), "recency": round(rec, 3), "novelty": nov}
        t.score = fame_score * size * rec * nov
        t.novelty_note = note
        kept.append(t)
    dropped["below_minimum"] += len([t for t in trades if t not in pre])
    kept.sort(key=lambda t: (-t.score, -t.usd))
    return kept


def pick_distinct(ranked: list[Trade], n: int, taken: list[Trade] | None = None) -> list[Trade]:
    """Up to n trades, best first, none sharing a ticker or a person with each other or with `taken`."""
    out: list[Trade] = []
    for t in ranked:
        if len(out) >= n:
            break
        if t.score <= 0:
            continue
        if any(t.ticker == o.ticker or same_person(t.name, o.name) or t.slug == o.slug for o in (taken or []) + out):
            continue
        out.append(t)
    return out



def is_famous(t: Trade, tiers: dict) -> bool:
    return bool(t.famous_person) or (t.kind == "insider" and famous_exec(t, tiers))


def choose_trades(api: "Api", target: dt.date, window: int, names: dict[str, str], fame: dict, prior: list["Posted"],
                  n: int) -> tuple[list[Trade], list[Trade], list[Trade], dict, list[str]]:
    """(chosen, recent ranked, backlog ranked, left-out counts, errors). Recent trades scoring
    >= MIN_TRADE_SCORE first; the rest from the famous 30-day backlog that is in no earlier manifest."""
    trades, dropped, errors = gather_trades(api, target, window, names, fame)
    ranked = rank_trades(api, trades, target, fame, prior, dropped) if trades else []
    chosen = pick_distinct([t for t in ranked if t.score >= MIN_TRADE_SCORE], n)
    backlog: list[Trade] = []
    if len(chosen) < n:
        days = weekday_age(target - dt.timedelta(days=BACKLOG_DAYS), target)
        old, _, berr = gather_trades(api, target, days, names, fame, pages=12)
        errors.extend(e for e in berr if e not in errors)
        old = [t for t in old if t.famous_person or (t.kind == "insider" and t.value_usd >= 100_000 and TOP_OFFICER.search(t.role or ""))]
        tiers = fame["company_tiers_usd"]
        backlog = [t for t in rank_trades(api, old, target, fame, prior, {"below_minimum": 0})
                   if is_famous(t, tiers) and t.parts["novelty"] > 0]
        for t in backlog:
            t.source = "backlog"
        chosen += pick_distinct(backlog, n - len(chosen), taken=chosen)
    return chosen, ranked, backlog, dropped, errors


def trade_story(t: Trade) -> dict:
    acc, index = sec_index_url(t.api_source_url)
    who = t.name
    if t.kind == "insider":
        what = f"{who} ({t.role or 'insider'}) bought {usd_short(t.value_usd)} of {t.ticker} in this Form 4"
        amount = {"value_usd": round(t.value_usd, 2), "shares": t.shares or None,
                  "note": "API rows of this one Form 4 summed. A buying program can span several Form 4s: never call this "
                          "the total; the trade template takes every number from the SEC XML of the filing(s) it shows."}
    else:
        tag = "-".join(x for x in [(t.party or "")[:1], t.state or ""] if x)
        what = f"{who}{f' ({tag})' if tag else ''} {'bought' if t.side == 'buy' else 'sold'} {usd_short(t.low)}-{usd_short(t.high)} of {t.ticker}"
        amount = {"low": t.low, "high": t.high}
    sources = [u for u in [index, t.api_source_url if t.kind == "congress" else None,
                           f"{SITE}/dashboard/{t.ticker}", f"{SITE}/smart-money/figures/{t.slug}" if t.slug else None] if u]
    return {
        "headline": what,
        "kind": t.kind,
        "person": t.name,
        "person_slug": t.slug,
        "famous_person_match": t.famous_person,
        "role": t.role,
        "party": t.party, "chamber": t.chamber, "state": t.state, "owner": t.owner,
        "ticker": t.ticker,
        "company": t.company,
        "market_cap_usd": t.market_cap,
        "side": t.side,
        "filed": t.filed.isoformat(),
        "traded": sorted(set(t.traded)),
        "amount": amount,
        "rows": t.rows,
        "trade_ids": t.trade_ids,
        "accession": acc,
        "api_source_url": t.api_source_url,
        "score": round(t.score, 4),
        "score_parts": t.parts,
        "selected_from": t.source,
        "novelty_note": t.novelty_note,
        "sources": sources,
    }


def trade_slot(t: Trade) -> dict:
    story = trade_story(t)
    return {
        "category": "insider_trade" if t.kind == "insider" else "congress_trade",
        "story_id": f"{t.ticker.lower().replace('.', '-')}-{name_slug(t.name)}",
        "story_key": t.story_key,
        "tickers": [t.ticker],
        "people": [t.name],
        "story": story,
        "sources": story["sources"],
    }


# ---------------------------------------------------------------------------
# Earnings calendar and reports

def load_weeks(api: Api) -> tuple[list[dict], list[str]]:
    weeks, errors = [], []
    for w in range(3):
        data, err = api.get(f"/earnings?weeks_ahead={w}&scope=all")
        if err:
            errors.append(err)
            continue
        if isinstance(data, dict) and isinstance(data.get("days"), list):
            weeks.append(data)
    return weeks, errors


def week_rows(weeks: list[dict], days: list[dt.date]) -> tuple[list[dict], dict[str, int], bool]:
    """Rows of the given days, per-day listed counts, and whether every day was in a loaded week."""
    want = {x.isoformat() for x in days}
    rows, counts, seen = [], {}, set()
    for w in weeks:
        for day in w["days"]:
            if day.get("date") in want:
                seen.add(day["date"])
                counts[day["date"]] = int(day.get("count") or 0)
                rows.extend(r for r in day.get("reports") or [] if isinstance(r, dict))
    return rows, counts, seen == want


def earnings_slot(api: Api, target: dt.date, weeks: list[dict], names: dict[str, str], mode: str) -> dict:
    if mode == "week_ahead":
        start = week_monday(target) + dt.timedelta(days=7)
        days = [start + dt.timedelta(days=i) for i in range(5)]
    elif mode == "week":
        days = [target + dt.timedelta(days=i) for i in range(5 - target.weekday())]
    else:
        days = [target]
    rows, counts, complete = week_rows(weeks, days)
    if not complete:
        return {"empty": f"the earnings calendar for {days[0]}..{days[-1]} did not load"}
    confirmed = [r for r in rows if r.get("date_confirmed") is True]
    big = sorted([r for r in confirmed if r.get("in_universe") and (r.get("market_cap") or 0) >= EARNINGS_MIN_CAP],
                 key=lambda r: -(r.get("market_cap") or 0))
    if not big:
        return {"empty": f"no confirmed-date reporter with a ${EARNINGS_MIN_CAP / 1e9:.0f}B+ market cap on {days[0]}..{days[-1]} "
                         f"({len(confirmed)} confirmed of {sum(counts.values())} listed)"}
    companies = [{
        "symbol": r["symbol"], "company": names.get(r["symbol"]), "date": r["date"], "hour": r.get("hour"),
        "market_cap_usd": r.get("market_cap"), "date_confirmed_source": r.get("date_confirmed_source"),
        "eps_estimate": r.get("eps_estimate"), "revenue_estimate": r.get("revenue_estimate"),
    } for r in big[:8]]
    category = "earnings_today" if mode == "today" else "earnings_week"
    page = f"{SITE}/earnings/today" if mode == "today" else f"{SITE}/earnings/this-week"
    first = days[0].isoformat()
    return {
        "category": category,
        "story_id": f"earnings-{'today' if mode == 'today' else 'week'}-{first}",
        "story_key": f"earnings:{mode}:{first}",
        "tickers": [c["symbol"] for c in companies],
        "people": [],
        "story": {
            "headline": f"{len(big)} companies with a $10B+ market cap report {'today' if mode == 'today' else 'this week'} (confirmed dates)",
            "mode": mode, "days": [x.isoformat() for x in days],
            "listed_by_day": counts, "confirmed_count": len(confirmed), "large_confirmed_count": len(big),
            "companies": companies,
            "note": "Dates: the third-party calendar, or the company's confirmed date where marked; rows not confirmed are left out.",
        },
        "sources": [page] + [f"{SITE}/dashboard/{c['symbol']}" for c in companies],
    }


def report_candidates(api: Api, target: dt.date, weeks: list[dict]) -> tuple[list[dict], str | None, int]:
    """Reports released from the previous weekday through the target with a confirmed consensus and a
    $10B+ market cap, largest first; the error; how many releases were looked at."""
    data, err = api.get("/earnings/reports?days=7&limit=50")
    if err or not isinstance(data, dict):
        return [], err or "/earnings/reports: unreadable response", 0
    lo, hi = prev_weekday(target), target
    caps = {r["symbol"]: r.get("market_cap") for w in weeks for day in w["days"] for r in day.get("reports") or [] if isinstance(r, dict)}
    recent = [r for r in data.get("recent") or [] if isinstance(r, dict) and r.get("release_date")
              and lo <= d(r["release_date"]) <= hi and r.get("summary_status") == "ready"]
    out = []
    for tile in recent:
        full, ferr = api.get(f"/earnings/reports/{urllib.parse.quote(tile['id'])}")
        if ferr or not isinstance(full, dict):
            continue
        cons, res = full.get("consensus") or {}, full.get("results") or {}
        confirmed = []
        for metric, key in (("revenue", "revenue"), ("eps", "eps_adjusted")):
            c = cons.get(metric) or {}
            r = res.get(key) or {}
            if c.get("status") == "ready" and r.get("verdict") in ("beat", "miss", "in_line", "inline", "met"):
                confirmed.append({"metric": metric, "verdict": r.get("verdict"), "label": r.get("label"),
                                  "reported": r.get("reported"), "consensus": r.get("consensus"), "basis": c.get("basis"), "analysts": c.get("analysts")})
        if not confirmed:
            continue
        cap = caps.get(full["ticker"])
        if cap is None:
            _, cap = company_info(api, full["ticker"])
        if (cap or 0) < REPORT_MIN_CAP:
            continue
        out.append({"report": full, "confirmed": confirmed, "market_cap": cap})
    out.sort(key=lambda x: -(x["market_cap"] or 0))
    return out, None, len(recent)


def report_slot(c: dict) -> dict:
    r = c["report"]
    page = f"{SITE}/earnings/reports/{r['id']}"
    labels = "; ".join(f"{x['metric']}: {x['label']}" for x in c["confirmed"] if x.get("label"))
    return {
        "category": "earnings_report",
        "story_id": f"report-{r['id']}",
        "story_key": f"report:{r['id']}",
        "tickers": [r["ticker"]],
        "people": [],
        "story": {
            "headline": f"{r.get('company_name')} ({r['ticker']}) {r.get('fiscal_label')}: {labels or r.get('tile_label')}",
            "report_id": r["id"], "ticker": r["ticker"], "company": r.get("company_name"), "fiscal_label": r.get("fiscal_label"),
            "release_date": r.get("release_date"), "tile_label": r.get("tile_label"), "market_cap_usd": c["market_cap"],
            "consensus_confirmed": c["confirmed"], "outlook": (r.get("outlook") or {}).get("label"),
            "summary_bullets": ((r.get("summary") or {}).get("bullets") or [])[:4],
            "press_release_url": r.get("source_url"), "accession": r.get("accession"),
        },
        "sources": [u for u in [r.get("source_url"), page] if u],
    }


# ---------------------------------------------------------------------------
# Picks

def picks_slot(api: Api, target: dt.date, time_et: str) -> dict:
    data, err = api.get("/tips/daily")
    if err or not isinstance(data, dict):
        return {"empty": f"/tips/daily did not load ({err or 'unreadable response'})"}
    if data.get("status") != "ready":
        return {"empty": f"no published picks list (status {data.get('status')!r})"}
    when = slot_datetime_utc(target, time_et)
    until = data.get("valid_until")
    if when is None or not until or dt.datetime.fromisoformat(until.replace("Z", "+00:00")) < when:
        return {"empty": f"the published list ({data.get('trade_date')}) expires {until} before the {time_et} ET slot; "
                         f"today's list publishes at {data.get('publish_time_et')}"}
    guest = [t for t in data.get("tips") or [] if isinstance(t, dict) and not t.get("locked") and t.get("rank") != 1 and t.get("ticker")]
    if not guest:
        return {"empty": f"the {data.get('trade_date')} list has no public picks beyond the locked #1"}
    trade_date = data["trade_date"]
    picks = [{"ticker": t["ticker"], "direction": t.get("direction"),
              "signals": [s.get("label") for s in t.get("signal_labels") or [] if isinstance(s, dict) and s.get("label")][:3]} for t in guest]
    note = None
    if trade_date != target.isoformat():
        note = (f"The {time_et} ET slot comes before today's list ({data.get('publish_time_et')}); this is the {trade_date} list, "
                f"valid until {until}.")
    return {
        "category": "daily_picks",
        "story_id": f"picks-{trade_date}",
        "story_key": f"picks:{trade_date}",
        "tickers": [p["ticker"] for p in picks],
        "people": [],
        "story": {"headline": f"Daily picks for {trade_date}: {', '.join(p['ticker'] for p in picks)} (#1 locked for guests)",
                  "trade_date": trade_date, "valid_until": until, "top_pick_locked": True, "picks": picks, "note": note},
        "sources": [f"{SITE}/picks/{trade_date}"],
    }


# ---------------------------------------------------------------------------
# Themes (slot 7 when there is no second report)

def theme_slot(api: Api, target: dt.date, kind: str, trades_all: list[Trade], fame: dict, track_record: Path, names: dict[str, str]) -> dict:
    if kind == "congress_week":
        start = week_monday(target) - dt.timedelta(days=7)
        end = start + dt.timedelta(days=4)
        items, err = fetch_feed(api, "congress", start)
        if err:
            return {"empty": f"Congress feed did not load ({err})"}
        rows = [it for it in items if isinstance(it, dict) and it.get("disclosure_date") and start <= d(it["disclosure_date"]) <= end
                and it.get("side") in ("buy", "sell") and listed((it.get("ticker") or "").upper(), names)]
        big = sorted([r for r in rows if ((r.get("amount") or {}).get("low") or 0) >= CONGRESS_MIN_LOW],
                     key=lambda r: -((r.get("amount") or {}).get("high") or 0))
        if len(big) < 3:
            return {"empty": f"only {len(big)} Congress trades of $15K+ filed {start}..{end} (need 3)"}
        top = [{"member": r["figure"]["display_name"], "party": r["figure"].get("party"), "state": r["figure"].get("state"),
                "ticker": r["ticker"], "side": r["side"], "low": r["amount"].get("low"), "high": r["amount"].get("high"),
                "filed": r["disclosure_date"], "source_url": r.get("source_url")} for r in big[:5]]
        return {"category": "congress_week", "story_id": f"congress-week-{start}", "story_key": f"theme:congress_week:{start}",
                "tickers": sorted({t["ticker"] for t in top}), "people": sorted({t["member"] for t in top}),
                "story": {"headline": f"Congress trades filed {start}..{end}: {len(rows)} trades, {len({r['figure']['slug'] for r in rows})} members",
                          "trades": len(rows), "members": len({r["figure"]["slug"] for r in rows}), "top": top},
                "sources": [f"{SITE}/congress-trades"] + [t["source_url"] for t in top if t["source_url"]]}
    if kind == "congress_30d":
        data, err = api.get("/notable/congress?days=30")
        if err or not isinstance(data, dict):
            return {"empty": f"/notable/congress did not load ({err or 'unreadable response'})"}
        totals = data.get("totals") or {}
        if (totals.get("trades") or 0) < 10:
            return {"empty": f"only {totals.get('trades')} Congress trades in 30 days (need 10)"}
        strip = lambda rows, k: [{"ticker": r["ticker"], k: r.get(k), "members": r.get("members")} for r in rows[:5]]
        mb, ms = strip(data.get("most_bought") or [], "buys"), strip(data.get("most_sold") or [], "sells")
        return {"category": "congress_30d", "story_id": f"congress-30d-{target}", "story_key": f"theme:congress_30d:{target}",
                "tickers": sorted({r["ticker"] for r in mb + ms}), "people": [],
                "story": {"headline": f"Congress, last 30 days: {totals.get('trades')} trades by {totals.get('members')} members",
                          "since": data.get("since"), "totals": totals, "most_bought": mb, "most_sold": ms,
                          "note": "Counts only; no returns (the kit's no-performance rule)."},
                "sources": [f"{SITE}/congress-trades"]}
    if kind == "person_spotlight":
        famous = sorted([t for t in trades_all if t.famous_person], key=lambda t: -t.usd)
        if not famous:
            return {"empty": "no famous person (fame.json) filed a trade in the window"}
        t = famous[0]
        slot = trade_slot(t)
        slot.update({"category": "person_spotlight", "story_id": f"spotlight-{name_slug(t.name)}-{target}",
                     "story_key": f"theme:person_spotlight:{t.slug}:{target}"})
        return slot
    if kind == "track_record":
        try:
            para = json.loads(track_record.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            return {"empty": f"approved track-record paragraph unreadable ({track_record}: {type(e).__name__})"}
        as_of = para.get("as_of") if isinstance(para, dict) else None
        if not as_of or (target - d(as_of)).days > 7:
            return {"empty": f"the approved track-record paragraph is older than 7 days (as_of {as_of})"}
        return {"category": "track_record", "story_id": f"track-record-{as_of}", "story_key": f"theme:track_record:{as_of}",
                "tickers": [], "people": [], "story": {"headline": f"Track record as of {as_of} (approved paragraph, verbatim)",
                                                      "as_of": as_of, "text": para.get("text"), "caveats": para.get("caveats")},
                "sources": [f"{SITE}/scoreboard"]}
    if kind == "insider_week":
        start = week_monday(target)
        buys = sorted([t for t in trades_all if t.kind == "insider" and start <= t.filed <= target and t.value_usd >= INSIDER_MIN_USD],
                      key=lambda t: -t.value_usd)
        if len(buys) < 3:
            return {"empty": f"only {len(buys)} insider buys of $1M+ filed since {start} (need 3)"}
        top = [trade_story(t) for t in buys[:5]]
        return {"category": "insider_week", "story_id": f"insider-week-{start}", "story_key": f"theme:insider_week:{start}",
                "tickers": [x["ticker"] for x in top], "people": [x["person"] for x in top],
                "story": {"headline": f"Top insider buys filed since {start}", "top": top},
                "sources": [s for x in top for s in x["sources"][:1]]}
    return {"empty": f"unknown theme {kind}"}


# ---------------------------------------------------------------------------
# Plan

def build_plan(target: dt.date, api: Api, repo: Path, fame: dict, track_record: Path) -> dict:
    weekend = target.weekday() >= 5
    grid = mf.WEEKEND_SLOTS if weekend else mf.WEEKDAY_SLOTS
    prior = prior_posts(repo, target)
    notes: list[str] = []
    names_data, err = api.get("/tickers/names")
    names = names_data.get("names") if isinstance(names_data, dict) and isinstance(names_data.get("names"), dict) else {}
    if err or not names:
        notes.append(f"ticker list did not load ({err or 'empty'}): no trade can be checked, trade slots stay empty")
    window = WEEKEND_WINDOW_WEEKDAYS if weekend else RECENCY_WEEKDAYS
    need = 0 if target.weekday() == 5 else (1 if weekend else 3)
    chosen: list[Trade] = []
    ranked: list[Trade] = []
    backlog: list[Trade] = []
    dropped: dict = {}
    terr: list[str] = []
    if names and need:
        chosen, ranked, backlog, dropped, terr = choose_trades(api, target, window, names, fame, prior, need)
    notes.extend(terr)
    weeks, werr = load_weeks(api)
    notes.extend(werr)
    slots: dict[int, dict] = {}

    def trade_reason(n: int) -> str:
        strong = sum(t.score >= MIN_TRADE_SCORE for t in ranked)
        why = (f"{strong} of {len(ranked)} trades passing the minimums in the last {window} weekdays scored >= {MIN_TRADE_SCORE}, "
               f"and the famous {BACKLOG_DAYS}-day backlog had {len(backlog)} unposted candidates; fewer than {n} are distinct")
        if terr:
            why += f"; feed errors: {'; '.join(terr)}"
        return f"no trade #{n}: {why}"

    if weekend:
        if target.weekday() == 5:
            slots[1] = earnings_slot(api, target, weeks, names, "week_ahead")
        else:
            slots[1] = trade_slot(chosen[0]) if chosen else {"empty": trade_reason(1)}
    else:
        mode = "week" if target.weekday() == 0 else "today"
        e = earnings_slot(api, target, weeks, names, mode)
        if "empty" in e and mode == "today":
            rest = earnings_slot(api, target, weeks, names, "week") if target.weekday() < 4 else e
            e = rest if "empty" not in rest else {"empty": f"{e['empty']}; rest of the week: {rest.get('empty', 'n/a')}"}
        slots[1] = e
        for i, slot_no in enumerate((2, 3, 6)):
            slots[slot_no] = trade_slot(chosen[i]) if i < len(chosen) else {"empty": trade_reason(i + 1)}
        slots[4] = picks_slot(api, target, grid[4])
        reports, rerr, looked = report_candidates(api, target, weeks)
        lo = prev_weekday(target)
        if rerr:
            slots[5] = {"empty": f"earnings reports did not load ({rerr})"}
        elif reports:
            slots[5] = report_slot(reports[0])
        else:
            slots[5] = {"empty": f"no report released {lo}..{target} with a confirmed consensus and a $10B+ market cap "
                                 f"({looked} released reports looked at; the 10:30 ET pass looks again after the morning releases)"}
        if len(reports) > 1:
            slots[7] = report_slot(reports[1])
        else:
            theme = WEEKDAY_THEMES[target.weekday()]
            pool = ranked
            if theme == "insider_week":  # the whole week so far, not only the 3-weekday window
                pool, _, _ = gather_trades(api, target, target.weekday(), names, fame) if names else ([], {}, [])
            t = theme_slot(api, target, theme, pool, fame, track_record, names)
            if "empty" in t:
                t = {"empty": f"no second report; theme {theme}: {t['empty']}"}
            slots[7] = t

    out_slots = []
    used_ids: set[str] = set()
    for n in sorted(grid):
        s = slots.get(n, {"empty": "not planned"})
        entry = {"slot": n, "time_et": grid[n]}
        if "empty" in s:
            entry.update({"status": "empty", "reason": s["empty"]})
        else:
            sid = s["story_id"]
            if sid in used_ids:
                sid = f"{sid}-{n}"
            used_ids.add(sid)
            entry.update({"status": "filled", "category": s["category"], "template": TEMPLATES.get(s["category"]),
                          "story_id": sid, "story_key": s["story_key"], "tickers": s["tickers"], "people": s["people"],
                          "story": s["story"], "sources": s["sources"]})
        out_slots.append(entry)

    return {
        "schema": PLAN_SCHEMA,
        "date": target.isoformat(),
        "weekday": target.strftime("%A"),
        "day_type": "weekend" if weekend else "weekday",
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api": api.base,
        "api_requests": api.requests,
        "rules": {"trade_window_weekdays": window, "min_trade_score": MIN_TRADE_SCORE, "backlog_days": BACKLOG_DAYS,
                  "insider_min_usd": INSIDER_MIN_USD, "congress_min_low_usd": CONGRESS_MIN_LOW,
                  "earnings_min_cap_usd": EARNINGS_MIN_CAP, "report_min_cap_usd": REPORT_MIN_CAP, "novelty_days": NOVELTY_DAYS,
                  "prior_manifest_posts": len(prior)},
        "slots": out_slots,
        "trade_candidates": [dict(trade_story(t), rank=i + 1) for i, t in enumerate(ranked[:12])],
        "backlog_candidates": [dict(trade_story(t), rank=i + 1) for i, t in enumerate(backlog[:12])],
        "trades_left_out": dropped,
        "notes": notes,
    }


def print_plan(plan: dict) -> None:
    print(f"{plan['date']} ({plan['weekday']}, {plan['day_type']}): {sum(s['status'] == 'filled' for s in plan['slots'])}/"
          f"{len(plan['slots'])} slots filled; {plan['api_requests']} API requests")
    for s in plan["slots"]:
        if s["status"] == "filled":
            print(f"  {s['slot']} {s['time_et']} ET  {s['category']:<16} {s['story_id']}")
            print(f"      {s['story']['headline']}")
            for u in s["sources"][:3]:
                print(f"      source: {u}")
        else:
            print(f"  {s['slot']} {s['time_et']} ET  EMPTY: {s['reason']}")
    for key, title in (("trade_candidates", f"recent trade candidates (score = fame x size x recency x novelty; slot needs >= {MIN_TRADE_SCORE})"),
                       ("backlog_candidates", f"famous {BACKLOG_DAYS}-day backlog, not in an earlier manifest")):
        if plan.get(key):
            print(f"  {title}:")
            for c in plan[key][:8]:
                p = c["score_parts"]
                print(f"    #{c['rank']} {c['score']:.3f} [{p['fame']}x{p['size']}x{p['recency']}x{p['novelty']}] {c['headline']} (filed {c['filed']})")
    print(f"  left out: {plan['trades_left_out']}")
    for n in plan["notes"]:
        print(f"  note: {n}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True)
    ap.add_argument("--out")
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--repo", default=str(mf.REPO))
    ap.add_argument("--fame", default=str(TOOLS / "fame.json"))
    ap.add_argument("--track-record", default=str(DEFAULT_TRACK_RECORD))
    ap.add_argument("--api", default=API)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    target = d(a.date)
    fame = json.loads(Path(a.fame).read_text(encoding="utf-8"))
    plan = build_plan(target, Api(a.api), Path(a.repo), fame, Path(a.track_record))
    if a.out:
        mf.write_json(Path(a.out), plan)
    if a.print or not a.out:
        print_plan(plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
