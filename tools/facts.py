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
                     gives them.
  earnings_upcoming  the next weekday's reporters in our universe with a confirmed date (/earnings/tomorrow).
  picks_ready        the public picks of the list /tips/daily serves at 15:00 ET (select_stories.picks_slot: the #1
                     pick is locked and never read, so its ticker is never in this file).
  chart_pattern      the one tile /notable/pattern-showcase serves (automatic technical analysis), when its scan is in
                     the last 5 weekdays, its ticker is in our names list and it is not a #1 pick the picks list
                     exposes (for guests the #1 ticker is hidden, so this can only catch a leaked one). The pattern's
                     own text (pill, chip, key lines, points) is kept as the API writes it for our pages; the history
                     record ("past ... fell over the next 5 trading days") is left out: it is an outcome claim.
  moves_like         /moves-like/<T> for up to 5 tickers a day of the day's other items (round robin over
                     congress_trade, form4_buy, earnings_result, earnings_upcoming, chart_pattern; 0.5 s apart): the
                     peers the stock card lists with Sync >= 65 (Close / Tight), Sync and band as the card shows them.
                     not_covered, disabled, unavailable or no peer at the floor: no item. With --previous (the day's
                     published file) a ticker already looked up today is not asked again: its item is carried over.
chart_pattern and moves_like carry banned_words of their own (PREDICTION_WORDS): descriptive wording only.
Each item carries item_id, type, ticker, name / office, amount text as our pages show it, dates, the official
source_url, page_url (UTM built in; "{platform}" is a literal placeholder Grok fills with x or instagram),
allowed_numbers (every numeric token a post may print), must_include and a one-line facts_text.
An empty type is valid: items [] and reasons say why. Nothing is estimated or invented (No Fallbacks).

Exit codes: 0 written, every core source loaded (a failed chart_pattern / moves_like read is in errors, its item
dropped); 4 written, but a core source failed (ticker list, congress, insiders, earnings, picks: partial_sources);
anything else: crashed / not written (1, or 2 for a usage error).

  facts.py --compare-items OLD NEW    OLD / NEW: a file or an https URL (Pages; fetched past its cache). Exit 0 when
                                      both carry the same items (item_id + dedupe_key; generated_at and the rest do
                                      not count), 1 when they differ, 2 when one cannot be read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
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
import select_stories as ss  # noqa: E402

SCHEMA = "rtv-facts/1"
SITE = ss.SITE
DISCLAIMER = "Not investment advice."
BANNED_WORDS = ["insider trading", "guaranteed", "moon", "buy now", "will rise", "price target", "to the moon",
                "breakout coming", "about to", "set to",
                # stocks and ETFs only: no crypto talk, also on items about crypto-adjacent miners (MARA, RIOT, ...)
                "bitcoin", "btc", "crypto", "cryptocurrency", "ethereum", "blockchain"]
PREDICTION_WORDS = ["will", "going to"]  # per item (chart_pattern, moves_like): descriptive wording only
MAX_LEN = {"x": 270}
PLATFORMS = ["x", "instagram"]
PLATFORM_PLACEHOLDER = "{platform}"
PARTIAL = 4  # exit code: written, but a source failed (2 is argparse's usage error)
TYPES = ("congress_trade", "form4_buy", "earnings_result", "earnings_upcoming", "picks_ready", "chart_pattern", "moves_like")
WINDOW_WEEKDAYS = 4  # weekday age 0..4 = the last 5 weekdays
RESULT_HOURS = 24
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
    return f"{date}-{kind}-{ticker.upper().replace('.', '-')}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:6]}"


def page_url(path: str, iid: str) -> str:
    return (f"{SITE}{path}?utm_source={PLATFORM_PLACEHOLDER}&utm_medium=social&utm_campaign=grok"
            f"&utm_content={iid}")


def make_item(date: str, kind: str, ticker: str | None, key: str, path: str, **fields) -> dict:
    iid = item_id(date, kind, ticker or "LIST", key)
    item = {
        "item_id": iid, "type": kind, "ticker": ticker, "tickers": [ticker] if ticker else [],
        "name": None, "office": None, "amount_text": None, "traded": [], "filed": None,
        "source_url": None, "page_url": page_url(path, iid), "allowed_numbers": [],
        "must_include": [DISCLAIMER], "facts_text": "", "dedupe_key": key,
    }
    item.update(fields)
    item["allowed_numbers"] = uniq(item["allowed_numbers"])
    return item


def official(url: str | None, hosts: tuple[str, ...]) -> bool:
    try:
        p = urlsplit(url or "")
    except ValueError:
        return False
    return p.scheme == "https" and (p.hostname or "").lower() in hosts


# ---------------------------------------------------------------------------
# Congress

def congress_items(api, target: dt.date, names: dict[str, str]) -> tuple[list[dict], dict, str | None]:
    since = target
    while ss.weekday_age(since - dt.timedelta(days=1), target) <= WINDOW_WEEKDAYS:
        since -= dt.timedelta(days=1)
    rows, err = ss.fetch_feed(api, "congress", since)
    left = {"rows_read": len(rows), "out_of_window": 0, "not_congress": 0, "other_side": 0, "late_filing_over_90d": 0,
            "refiles_older_report": 0, "bad_date": 0, "not_listed": 0, "no_amount": 0, "no_official_source": 0}
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
        if fd is None or fd > target or ss.weekday_age(fd, target) > WINDOW_WEEKDAYS:
            left["out_of_window"] += 1
            continue
        if it.get("side") not in ("buy", "sell"):
            left["other_side"] += 1
            continue
        if it.get("transaction_date"):
            try:
                lag = (fd - ss.d(it["transaction_date"])).days
            except ValueError:
                left["bad_date"] += 1
                continue
            if lag > ss.CONGRESS_MAX_FILING_LAG_DAYS:
                left["late_filing_over_90d"] += 1
                continue
        if it.get("refiles_older_report"):
            left["refiles_older_report"] += 1
            continue
        ticker = ss.primary_ticker(it.get("ticker"), names)
        if not ss.listed(ticker, names):
            left["not_listed"] += 1
            continue
        if trade_amount(it.get("amount") or {}) is None:
            left["no_amount"] += 1
            continue
        if not official(it.get("source_url"), OFFICIAL_PTR_HOSTS):
            left["no_official_source"] += 1
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
            amount_text=amount_text, amount_exact_text="; ".join(e for e in exact if e), rows=len(rs),
            traded=traded, filed=filed, source_url=src, facts_text=facts_text,
            allowed_numbers=[*amounts, *ends, *[e for e in exact if e], *ends_exact, *date_forms(filed),
                             *(f for t in traded for f in date_forms(t)), str(len(rs)) if len(rs) > 1 else None,
                             *digit_words(fig.get("display_name"), company)]))
    items.sort(key=lambda x: (x["filed"], x["ticker"]), reverse=True)
    return items, left, err


# ---------------------------------------------------------------------------
# Form 4

def form4_items(api, target: dt.date, names: dict[str, str], fame: dict) -> tuple[list[dict], dict, list[str]]:
    trades, _, errors = ss.gather_trades(api, target, WINDOW_WEEKDAYS, names, fame, pages=1)
    ins = [t for t in trades if t.kind == "insider"]
    dropped = {"below_minimum": 0}
    kept = ss.rank_trades(api, ins, target, fame, [], dropped) if ins else []
    rows_by_id = {}
    feed, _ = ss.fetch_feed(api, "insiders", target)  # cached: the same public read gather_trades made
    for r in feed:
        if isinstance(r, dict):
            rows_by_id[r.get("trade_id")] = r
    left = {"rows_read": len(feed), "filings_passing_filters": len(ins), "below_minimum": dropped["below_minimum"],
            "no_sec_index": 0}
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
            name=t.name, office=office, company=company, side="buy", accession=acc, rows=t.rows,
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


def result_items(api, target: dt.date, as_of: dt.datetime) -> tuple[list[dict], dict, list[str]]:
    data, err = api.get("/earnings/reports/archive")
    if err or not isinstance(data, dict) or not isinstance(data.get("reports"), list):
        return [], {}, [err or "/earnings/reports/archive: unreadable response"]
    lo = as_of - dt.timedelta(hours=RESULT_HOURS)
    # A report published in the window was released at most a few days before it (release_date is a NY date).
    cands = [r for r in data["reports"] if isinstance(r, dict) and r.get("id") and r.get("summary_status") == "ready"
             and r.get("release_date") and lo.date() - dt.timedelta(days=4) <= ss.d(r["release_date"]) <= as_of.date()]
    left = {"archive_reports": len(data["reports"]), "recent_ready": len(cands), "outside_24h": 0, "unreadable": 0}
    errors: list[str] = []
    items = []
    date = target.isoformat()
    for tile in cands:
        upd = _ts(tile.get("updated_at"))
        if upd is not None and upd <= lo:  # published_at <= updated_at: published before the window, no need to read it
            left["outside_24h"] += 1
            continue
        full, ferr = api.get(f"/earnings/reports/{tile['id']}")
        if ferr or not isinstance(full, dict):
            left["unreadable"] += 1
            errors.append(ferr or f"/earnings/reports/{tile['id']}: unreadable response")
            continue
        pub = _ts(full.get("published_at"))
        if pub is None or not (lo < pub <= as_of):
            left["outside_24h"] += 1
            continue
        ticker = full.get("ticker") or tile.get("ticker")
        res = full.get("results") or {}
        results: dict = {}
        nums: list[str | None] = []
        rev = res.get("revenue") or {}
        if any(rev.get(k) is not None for k in ("reported", "label", "verdict")):
            results["revenue"] = {k: v for k, v in {
                "reported": money_compact(rev["reported"]) if isinstance(rev.get("reported"), (int, float)) else None,
                "consensus": money_compact(rev["consensus"]) if isinstance(rev.get("consensus"), (int, float)) else None,
                "label": rev.get("label"), "verdict": rev.get("verdict")}.items() if v is not None}
        eps = res.get("eps_adjusted") or {}
        basis = eps.get("basis_label") or "Adjusted EPS"
        if not any(eps.get(k) is not None for k in ("reported", "label", "verdict")):
            eps, basis = res.get("eps_gaap") or {}, "GAAP EPS"
        if any(eps.get(k) is not None for k in ("reported", "label", "verdict")):
            results["eps"] = {k: v for k, v in {
                "basis": basis,
                "reported": eps_text(eps["reported"]) if isinstance(eps.get("reported"), (int, float)) else None,
                "consensus": eps_text(eps["consensus"]) if isinstance(eps.get("consensus"), (int, float)) else None,
                "label": eps.get("label"), "verdict": eps.get("verdict")}.items() if v is not None}
        for m in results.values():
            nums += [m.get("reported"), m.get("consensus"), *money_tokens(m.get("label"))]
        parts = [f"{full.get('company_name') or ticker} ({ticker}) published {full.get('fiscal_label')} results "
                 f"on {full.get('release_date')}: {full.get('tile_label')}."]
        for name, key in (("Revenue", "revenue"), ("EPS", "eps")):
            m = results.get(key)
            if not m:
                continue
            what = f"{m['basis']}" if key == "eps" else name
            bits = [b for b in [m.get("reported"), f"vs {m['consensus']} consensus" if m.get("consensus") else None,
                                f"({m['label']})" if m.get("label") else None] if b]
            parts.append(f"{what} {' '.join(bits)}.")
        src = full.get("source_url") if official(full.get("source_url"), ("www.sec.gov", "sec.gov")) else None
        items.append(make_item(
            date, "earnings_result", ticker, f"report:{full.get('id')}", f"/earnings/reports/{full.get('id')}",
            name=full.get("company_name"), report_id=full.get("id"), fiscal_label=full.get("fiscal_label"),
            release_date=full.get("release_date"), published_at=full.get("published_at"),
            tile_label=full.get("tile_label"), tile_state=full.get("tile_state"), results=results,
            filed=(full.get("filing_date") or full.get("release_date")),
            source_url=src or f"{SITE}/earnings/reports/{full.get('id')}", facts_text=" ".join(parts),
            allowed_numbers=[*nums, *money_tokens(full.get("tile_label")),
                             *fiscal_tokens(full.get("fiscal_label"), full.get("fiscal_quarter"), full.get("fiscal_year")),
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
            date, "earnings_upcoming", sym, f"upcoming:{sym}:{nxt.isoformat()}", "/earnings/tomorrow",
            name=company, report_date=nxt.isoformat(), hour=r.get("hour"), hour_text=when,
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
# Feed

def default_as_of(target: dt.date, now: dt.datetime) -> dt.datetime:
    """Now, or the end of the date's New York day when that is earlier (a past date)."""
    if ss.NY is None:
        return now
    end = dt.datetime(target.year, target.month, target.day, 23, 59, 59, tzinfo=ss.NY).astimezone(dt.timezone.utc)
    return min(now, end)


def build_facts(target: dt.date, api, fame: dict, now: dt.datetime | None = None, as_of: dt.datetime | None = None,
                previous: dict | None = None) -> dict:
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
        for k in ("congress_trade", "form4_buy"):
            reasons[k] = f"the ticker list did not load ({nerr or 'empty'}): no trade can be checked as listed"
    else:
        c, left["congress_trade"], cerr = congress_items(api, target, names)
        if cerr:
            errors.append(cerr)
            partial.append("congress_trade")
            reasons["congress_trade"] = f"the Congress feed did not load ({cerr})"
        elif not c:
            reasons["congress_trade"] = "no Congress trade passed the rules in the last 5 weekdays (left_out has the counts)"
        items += c
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
    items += u

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

    m, left["moves_like"], merr, checked = moves_like_items(api, target, items, previous)
    errors += merr
    if not m:
        reasons["moves_like"] = (f"Moves Like did not load ({'; '.join(merr)})" if merr else
                                 f"no ticker of today's items has a Moves Like peer at Sync {MOVES_LIKE_SYNC_FLOOR}+ "
                                 "(left_out has the counts)"
                                 if checked else "no ticker in today's other items to look up")
    items += m

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
            "numbers": "every number, date or amount in a post must be one of the item's allowed_numbers, as written there",
            "picks": "never name or hint at the #1 pick; it is locked and not in this file",
            "no_advice": "no buy / sell calls, predictions or price targets; every post carries the disclaimer",
            "descriptive": ("chart_pattern and moves_like describe what happened only (no forecasts; their items' "
                            "banned_words apply too); moves_like may cashtag only the peers listed in its item"),
        },
        "counts": counts,
        "reasons": reasons,
        "left_out": left,
        "errors": errors,
        "partial_sources": partial,
        "moves_like_checked": checked,
        "api_requests": getattr(api, "requests", None),
        "items": items,
    }


# ---------------------------------------------------------------------------
# Comparing two feeds (the runner publishes only when the item set changed)

def item_set(facts: dict) -> set[tuple[str, str]]:
    return {(str(i.get("item_id")), str(i.get("dedupe_key"))) for i in facts.get("items") or [] if isinstance(i, dict)}


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
    facts = build_facts(target, ss.Api(a.api), fame, as_of=as_of, previous=previous)
    out = Path(a.out) if a.out else Path(a.repo) / "v" / target.isoformat() / "facts.json"
    mf.write_json(out, facts)
    if a.print:
        print_facts(facts)
    print(f"wrote {out} ({facts['api_requests']} API requests)")
    return PARTIAL if facts["partial_sources"] else 0


if __name__ == "__main__":
    sys.exit(main())
