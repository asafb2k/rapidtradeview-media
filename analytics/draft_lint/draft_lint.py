"""Playbook v2 draft lint: advisory WARNINGS and NOTES for a post draft, never a block.

Usage (Python 3.8+, standard library only, so one downloaded file runs anywhere):
  python draft_lint.py --facts <facts.json URL or path> --draft draft.json [--history recent_posts.json]
                       [--now 2026-10-15T14:00:00Z] [--format text|json|both]

Draft: one JSON object (or a list of them), the same shape the validator (grok_review.py) takes:
  {"item_id", "platform": "x"|"instagram", "text", "reply_text"?, "link"?, "media_url"?, "planned_at"?}
  planned_at (ISO time) is when the post goes out; default --now (default: the current time).
History (optional): our OWN recent posts, a JSON list (or {"posts": [...]}) of
  {"platform", "posted_at" (ISO time; "at" / "created_at" also read), "text", "kind"?}
  kind "reply" / "comment" / "self_reply" rows are skipped (a deliberate self-thread does not count for spacing).

Every finding names its evidence level from playbook v2 (owner approved 2026-10-15):
  [real]   TIER 1, measured within author;  [likely]  TIER 2, adopt and log;  [stop]  no reach effect.
A WARN is a playbook rule the draft breaks; a NOTE is information (an experiment arm, a rule the compliance
check overrides today, a freshness the lint cannot verify). score = the number of [real] + [likely] WARNs.
Compliance (numbers, cashtags per item, links, disclaimer, banned words) is grok_review.py's job and stays hard;
this lint never approves or rejects. No network except reading the facts URL; prints nothing but the draft's own
fragments.

Rules (playbook v2 section in brackets):
  cashtags   [real]   2-5 distinct cashtags (earnings_week_calendar 8-12: CASHTAG_RANGE_BY_TYPE); not only mega-caps /
                      index-ETFs; each supported by the facts (the item's tickers, any other item's tickers in the same
                      facts, moves_like peers)                                                          [TIER 1.1]
  numbers    [real]   >= 2 concrete figures in the text, one in the first line                            [TIER 1.2]
  macro      [real]   macro words (Fed, FOMC, CPI, PPI, yields, Treasury, oil, jobs report, GDP, inflation)
                      with no stock cashtag; predictive framing (will, expect, likely, set to, poised)
                      in a macro post                                                                     [TIER 1.3]
  spacing    [real]   (--history) the last own post on that platform < 2 h before the planned time        [TIER 1.4]
  length     [likely] < 25 words; > 60 words on niche items (congress, Form 4, earnings)                  [TIER 2.8]
  link       [likely] an outside link in the body: NOTE "E2 arm?"; WARN when (--history) another body-link
                      post on that platform went out in the last 24 h                                    [TIER 2.7]
  mention    [likely] an @mention in an own post (text or self-reply)                                     [TIER 2.11]
  question   [likely] (--history) a question when one of the last 2 own posts was a question             [TIER 2.12]
  breaking   [likely] BREAKING / JUST IN unless the item's event time is < 60 min old                     [TIER 2.13]
  video      [likely] X: the item has a Reel but the draft's media is not video: NOTE "E1 arm?"           [TIER 2.6]
  earnings_speed [likely] earnings_result first seen > 60 min before the planned time: NOTE (E3)          [TIER 2.9]
  list       [likely] >= 4 list lines (bullet, numbered, emoji- or cashtag-led) on a niche item           [TIER 2.8]
  self_thread [likely] reply_text longer than the post, or numbers in it the post lacks                   [STOP list]
  hashtags   [stop]   > 1 hashtag: NOTE "no reach effect"; emoji / caps are not linted                    [STOP list]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.0.0"
PLAYBOOK = "playbook v2 (2026-10-15)"
UA = "RapidTradeView draft-lint (contact@rapidtradeview.trade)"
LEVELS = ("real", "likely", "stop")
SCORED = ("real", "likely")

# Ticker classes: copied from D:/rtv-ops/tracks/growth/ml/run1/features_text.py (fixed a priori, the EDA's lists; that
# file needs numpy/pandas, this one must run alone). Keep the two in step.
MEGACAP = {"AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO", "BRK.A", "BRK.B", "LLY", "JPM",
           "V", "MA", "WMT", "ORCL", "NFLX", "XOM", "COST", "UNH"}
INDEX_ETF = {"SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "SPX", "NDX", "VIX", "RUT", "DJI", "DJIA", "ES", "NQ", "TLT",
             "GLD", "SLV", "XLF", "XLE", "XLK", "SMH", "SOXX", "SOXL", "TQQQ", "SQQQ", "UVXY", "ARKK", "HYG", "VXX"}

# Item types (tools/facts.py). Niche = the playbook's "niche posts" (congress, Form 4, earnings).
NICHE_TYPES = ("congress_trade", "ptr_summary", "form4_buy", "earnings_result", "earnings_upcoming",
               "earnings_tomorrow_roundup", "earnings_week_calendar")
# Types whose compliance check (grok_review.py, facts rules.cashtags) lets a post carry more than the item's own
# cashtag. Every other type is held to ONE cashtag by compliance today, so the 2-5 rule is a NOTE there, not a WARN.
MULTI_CASHTAG_TYPES = ("earnings_tomorrow_roundup", "ptr_summary", "moves_like", "picks_ready", "earnings_week_calendar")

CASHTAG_MIN, CASHTAG_MAX = 2, 5
# The weekly calendar post (Growth test 2026-10-16) names 8-12 of its tickers on one line: its own range.
CASHTAG_RANGE_BY_TYPE = {"earnings_week_calendar": (8, 12)}
NUMBERS_MIN = 2
WORDS_MIN, WORDS_MAX = 25, 60
SPACING = dt.timedelta(hours=2)
BODY_LINK_WINDOW = dt.timedelta(hours=24)
FRESH = dt.timedelta(minutes=60)
LIST_LINES_MAX = 3  # >= 4 list lines on a niche item warns
QUESTION_LOOKBACK = 2
SKIP_HISTORY_KINDS = {"reply", "self_reply", "comment", "self-reply"}

URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
CASHTAG = re.compile(r"(?<![\w$])\$([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)(?![\w])")
DOC_NAME = re.compile(r"(?<![\w$.,/-])(?:Form\s+(?:4|144|13F)|8-K|10-Q|10-K|13F)(?![\w%$/]|[.,-]\d)", re.IGNORECASE)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Fiscal-period labels (Q3 2026, Q3'26, Q3 FY26, FY2026, H1) name the period; they are not figures.
PERIOD = re.compile(r"\b(?:(?:Q[1-4]|H[12])(?:\s*(?:(?:19|20)\d{2}\b|'\d{2}\b|FY\s*'?\d{2,4}\b))?|FY\s*'?\d{2,4})\b",
                    re.IGNORECASE)
HASHTAG = re.compile(r"(?<![\w&/])[#\uff03](?=\w*[^\W\d_])\w+")
MENTION = re.compile(r"(?<![\w@.])@([A-Za-z0-9_]{1,30})")
WORD = re.compile(r"[A-Za-z0-9]")
EMOJI = re.compile(
    "[\U0001F1E6-\U0001F1FF\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F700-\U0001F7FF"
    "\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF"
    "\u2600-\u26ff\u2700-\u27bf\u2b05-\u2b07\u2b1b\u2b1c\u2b50\u2b55\u23e9-\u23fa\u203c\u2049\u3030\u303d\u3297\u3299]")
BULLET = re.compile("^\\s*(?:[-*\u2022\u25aa\u25ba\u25b6\u27a1\u2705\u2714\u2611\u00b7]|\\d{1,2}[.)]\\s)")
CASHTAG_LED = re.compile(r"^\s*\$[A-Za-z]")
MACRO_CASE = re.compile(r"\b(?:Fed|FOMC|CPI|PPI|GDP)\b")
MACRO_WORDS = re.compile(r"\b(?:federal reserve|yields?|treasury|treasuries|oil|crude|jobs reports?|payrolls?|inflation)\b",
                         re.IGNORECASE)
PREDICTIVE = re.compile(r"\b(?:will|expects?|expected|expecting|likely|set to|poised)\b", re.IGNORECASE)
# "expected" after vs / versus / than (within 3 words) compares a result with the estimate: results wording, not a forecast.
ESTIMATE_LEAD = re.compile(r"(?:^|\s)(?:vs\.?|versus|than)(?:\s+\S+){0,2}\s*$", re.IGNORECASE)
# The label, not the words: upper case anywhere, or any case leading a line AS a label ("Breaking:", "Just in -").
# "Just in time for the open", "Breaking down Q3" and "Justin" are not it.
BREAKING = re.compile(r"\b(?:BREAKING|JUST[\s-]+IN)\b"
                      r"|^\W*(?i:breaking(?:\s+news)?|just[\s-]+in)\s*[:|!–—-]", re.MULTILINE)
VIDEO_EXT = re.compile(r"\.(?:mp4|mov|m4v|webm)(?:[?#].*)?$", re.IGNORECASE)
EVENT_KEYS = ("published_at", "published", "updated_at", "updated", "filed_at", "filed")
FIRST_SEEN_KEYS = ("first_seen_at", "first_seen", "published_at")


class InputError(Exception):
    """A facts / draft / history input that cannot be read: reported, never guessed around."""


# ---------------------------------------------------------------------------
# Inputs

def load_json(where: str, what: str, allow_url: bool = False):
    """JSON from a local path, or from a URL when allow_url (facts only: the lint reads nothing else off the network)."""
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", str(where)):
        if not allow_url:
            raise InputError(f"{what} {short(where)}: must be a local path (only --facts may be a URL)")
        req = urllib.request.Request(str(where), headers={"User-Agent": UA, "Accept": "application/json",
                                                          "Cache-Control": "no-cache"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except urllib.error.HTTPError as e:
            raise InputError(f"{what} {where}: HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise InputError(f"{what} {where}: {type(e).__name__}") from None
    try:
        return json.loads(Path(where).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise InputError(f"{what} {where}: {type(e).__name__}") from None


def parse_time(v) -> dt.datetime | None:
    """An aware UTC datetime from an ISO timestamp; None for a date without a time, or anything else."""
    if not isinstance(v, str) or not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", v):
        return None
    s = v.strip().replace(" ", "T", 1)
    s = re.sub(r"[Zz]$", "+00:00", s)
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)                    # Python < 3.11 takes at most 6 fraction digits
    s = re.sub(r"\.(\d{1,5})(?=[+-]|$)", lambda m: "." + m.group(1).ljust(6, "0"), s)
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)


def norm_platform(v) -> str:
    """'X ' and 'x' are the same platform."""
    return str(v or "").strip().lower()


def history_rows(history) -> list[dict]:
    """Own top-level posts with a parseable time, oldest first."""
    if history is None:
        return []
    rows = history.get("posts") if isinstance(history, dict) else history
    if not isinstance(rows, list):
        raise InputError('history must be a JSON list of posts (or {"posts": [...]})')
    out = []
    for r in rows:
        if not isinstance(r, dict) or str(r.get("kind") or "post").lower() in SKIP_HISTORY_KINDS:
            continue
        t = parse_time(r.get("posted_at") or r.get("at") or r.get("created_at"))
        if t is None:
            continue
        out.append({"platform": norm_platform(r.get("platform")), "at": t, "text": str(r.get("text") or "")})
    return sorted(out, key=lambda r: r["at"])


# ---------------------------------------------------------------------------
# Text helpers

def core(text: str) -> str:
    """The text without URLs."""
    return URL.sub(" ", text or "")


def cashtags(text: str) -> list[str]:
    """Distinct cashtags in order of first use, upper-cased."""
    return list(dict.fromkeys(m.group(1).upper() for m in CASHTAG.finditer(core(text))))


def figures(text: str) -> list[str]:
    """Concrete figures: number tokens outside URLs, cashtags, filing names (Form 4, 8-K, 13F ...) and fiscal-period
    labels (Q3 2026, FY26)."""
    s = PERIOD.sub(" ", DOC_NAME.sub(" ", CASHTAG.sub(" ", core(text))))
    return NUMBER.findall(s)


def word_count(text: str) -> int:
    return sum(1 for w in core(text).split() if WORD.search(w))


def first_line(text: str) -> str:
    return next((ln for ln in (text or "").splitlines() if ln.strip()), "")


def is_question(text: str) -> bool:
    return "?" in core(text)


def has_body_link(text: str) -> bool:
    return bool(URL.search(text or ""))


def list_lines(text: str) -> int:
    n = 0
    for ln in core(text).splitlines():
        s = ln.strip()
        if s and (BULLET.match(ln) or EMOJI.match(s) or CASHTAG_LED.match(ln)):
            n += 1
    return n


def norm_number(tok: str) -> str:
    return tok.replace(",", "")


def short(s, n: int = 40) -> str:
    s = " ".join(str(s).split())
    s = re.sub(r"[^\x20-\x7e\u00a0-\u024f\u2010-\u2027\u2212]", "", s)
    return s if len(s) <= n else s[: n - 1] + "~"


# ---------------------------------------------------------------------------
# Lint

def supported_tickers(item: dict | None, facts: dict | None) -> set[str]:
    out: set[str] = set()
    items = list((facts or {}).get("items") or [])
    if item is not None and item not in items:
        items.append(item)
    for it in items:
        if not isinstance(it, dict):
            continue
        for t in [it.get("ticker"), *(it.get("tickers") or [])]:
            if isinstance(t, str) and t:
                out.add(t.upper())
        for p in it.get("peers") or []:
            if isinstance(p, dict) and isinstance(p.get("ticker"), str):
                out.add(p["ticker"].upper())
    return out


def event_time(item: dict) -> tuple[dt.datetime | None, str | None]:
    for k in EVENT_KEYS:
        t = parse_time(item.get(k))
        if t is not None:
            return t, k
    return None, None


def lint(draft: dict, facts: dict | None, history=None, now: dt.datetime | None = None) -> dict:
    """{"item_id", "platform", "score", "findings": [{rule, level, kind: warn|note, message}], "skipped": [...]}."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    findings: list[dict] = []
    skipped: list[str] = []

    def add(rule: str, level: str, kind: str, message: str) -> None:
        findings.append({"rule": rule, "level": level, "kind": kind, "message": message})

    if not isinstance(draft, dict):
        raise InputError("the draft must be a JSON object")
    text = draft.get("text") if isinstance(draft.get("text"), str) else ""
    reply = draft.get("reply_text") if isinstance(draft.get("reply_text"), str) else ""
    platform = norm_platform(draft.get("platform"))
    iid = draft.get("item_id")
    items = (facts or {}).get("items") or []
    item = next((i for i in items if isinstance(i, dict) and i.get("item_id") == iid), None)
    kind = (item or {}).get("type")
    niche = kind in NICHE_TYPES
    planned = parse_time(draft.get("planned_at")) or now
    if item is None:
        skipped.append("item rules (item not in the facts)")

    # cashtags [real]
    tags = cashtags(text)
    n = len(tags)
    # A fix that needs more cashtags than compliance allows for this item type is a NOTE, not a WARN.
    capped = item is not None and kind not in MULTI_CASHTAG_TYPES
    cap_why = f"; compliance allows only the item's own cashtag for {kind} today, so keep 1 until that rule changes"
    lo, hi = CASHTAG_RANGE_BY_TYPE.get(kind or "", (CASHTAG_MIN, CASHTAG_MAX))
    if n < lo or n > hi:
        msg = f"{n} cashtag{'s' if n != 1 else ''}; playbook: {lo}-{hi} relevant ones (>=1 vs 0 +28%, >=3 vs 1-2 +11%)"
        if n < lo and capped:
            add("cashtags", "real", "note", msg + cap_why)
        else:
            add("cashtags", "real", "warn", msg)
    if tags and not set(tags) - MEGACAP - INDEX_ETF:
        what = ("only mega-caps" if set(tags) <= MEGACAP else
                "only index/ETF tickers" if set(tags) <= INDEX_ETF else "only mega-caps and index/ETF tickers")
        msg = f"{what} ({', '.join('$' + t for t in tags)}); add a non-mega name the facts support"
        if capped:
            add("cashtags", "real", "note", msg + cap_why)
        else:
            add("cashtags", "real", "warn", msg)
    if facts is not None:
        sup = supported_tickers(item, facts)
        bad = [t for t in tags if t not in sup]
        if bad:
            add("cashtags", "real", "warn", f"not supported by the facts: {', '.join('$' + short(t, 8) for t in bad)} "
                                            "(never unrelated tickers)")

    # numbers [real]
    figs = figures(text)
    if len(figs) < NUMBERS_MIN:
        add("numbers", "real", "warn", f"{len(figs)} concrete figure{'s' if len(figs) != 1 else ''}; playbook: several "
                                       "(actual vs estimate, $ size, % move, date) (+17%, breakout odds x2.2)")
    if text.strip() and not figures(first_line(text)):
        add("numbers", "real", "warn", "no figure in the first line; lead with the headline number")

    # macro [real]
    body = core(text)
    macro = sorted({m.group(0) for m in MACRO_CASE.finditer(body)} | {m.group(0).lower() for m in MACRO_WORDS.finditer(body)})
    if macro:
        stock = [t for t in tags if t not in INDEX_ETF]
        if not stock:
            add("macro", "real", "warn", f"macro-only post ({', '.join(macro)}) with no stock cashtag (-15%); "
                                         "tie it to tickers with facts")
        pred = sorted({m.group(0).lower() for m in PREDICTIVE.finditer(body)
                       if not (m.group(0).lower() == "expected" and ESTIMATE_LEAD.search(body[:m.start()]))})
        if pred:
            add("macro", "real", "warn", f"predictive framing in a macro post ({', '.join(pred)}); facts only")

    # history rules
    rows = history_rows(history)
    mine = [r for r in rows if r["platform"] == platform and r["at"] < planned]  # strictly before: not the post itself
    if history is None:
        skipped.append("spacing, question, link-24h (no --history)")
    elif rows and not any(r["platform"] == platform for r in rows):
        skipped.append(f"spacing, question, link-24h (no history rows for platform '{short(platform, 12)}')")
    else:
        # spacing [real]
        if mine:
            gap = planned - mine[-1]["at"]
            if gap < SPACING:
                add("spacing", "real", "warn", f"last own {platform} post {int(gap.total_seconds() // 60)} min before; "
                                               "space own posts >= 2 h apart (-8% within 1 h)")
        # question [likely]
        if is_question(text):
            recent = mine[-QUESTION_LOOKBACK:]
            q = sum(1 for r in recent if is_question(r["text"]))
            if q >= 1:
                add("question", "likely", "warn", f"{q} of the last {len(recent)} own {platform} posts already asked a "
                                                  "question; at most 1 post in 3 (likes -19%)")

    # length [likely]
    words = word_count(text)
    if words < WORDS_MIN:
        add("length", "likely", "warn", f"{words} words; playbook: {WORDS_MIN}-{WORDS_MAX} (headline number + one "
                                        "why-it-matters line; < 25 is -10%)")
    elif words > WORDS_MAX and niche:
        add("length", "likely", "warn", f"{words} words on a {kind} post; playbook: {WORDS_MIN}-{WORDS_MAX}")

    # link [likely]
    if has_body_link(text):
        add("link", "likely", "note", "outside link in the body (reach -15%, engagement -22%): E2 arm? "
                                      "Otherwise move it to the self-reply")
        if history is not None:
            since = planned - BODY_LINK_WINDOW
            prior = [r for r in mine if r["at"] >= since and has_body_link(r["text"])]
            if prior:
                add("link", "likely", "warn", f"{len(prior)} own {platform} post(s) with a body link in the last 24 h; "
                                              "at most 1 a day")

    # mention [likely]
    handles = sorted({m.group(1) for m in MENTION.finditer(core(text) + "\n" + core(reply))})
    if handles:
        add("mention", "likely", "warn", f"@mention in an own post ({', '.join('@' + short(h, 30) for h in handles)}); "
                                         "-20% engagement per view")

    # breaking [likely]
    hit = BREAKING.search(text)
    if hit:
        word = short(hit.group(0).upper(), 12)
        if item is None:
            add("breaking", "likely", "warn", f"{word}: can't verify freshness (item not in the facts)")
        else:
            t, key = event_time(item)
            if t is None:
                add("breaking", "likely", "warn", f"{word}: can't verify freshness (the item has no event time, only "
                                                  f"a date); only for a filing or print within minutes")
            elif planned - t >= FRESH:
                mins = int((planned - t).total_seconds() // 60)
                add("breaking", "likely", "warn", f"{word}: the item's {key} is {mins} min old; only for genuinely "
                                                  "breaking items (< 60 min), never as decoration")

    # video [likely]
    if platform == "x" and item is not None:
        reels = [m.get("url") for m in item.get("media") or []
                 if isinstance(m, dict) and str(m.get("kind") or "").lower() in ("reel", "video")]
        media = draft.get("media_url")
        if reels and not (isinstance(media, str) and (media in reels or VIDEO_EXT.search(media))):
            add("video", "likely", "note", "video available for this item (its Reel); E1 arm? (video +28%, not yet "
                                           "confirmed)")

    # earnings speed [likely]
    if kind == "earnings_result":
        seen = next(((parse_time(item.get(k)), k) for k in FIRST_SEEN_KEYS if parse_time(item.get(k))), (None, None))
        if seen[0] is None:
            add("earnings_speed", "likely", "note", "can't tell when the report first appeared (no published_at)")
        elif planned - seen[0] > FRESH:
            mins = int((planned - seen[0]).total_seconds() // 60)
            add("earnings_speed", "likely", "note", f"{mins} min since the report appeared ({seen[1]}); the fast "
                                                    "results post is within 60 min (E3: log fast vs next-morning)")

    # list [likely]
    if niche:
        n_list = list_lines(text)
        if n_list > LIST_LINES_MAX:
            add("list", "likely", "warn", f"{n_list} list lines on a {kind} post; no grids or scorecards in niche "
                                          "posts (-41%)")

    # self-thread substance [likely]
    if reply.strip():
        r_core, t_core = " ".join(core(reply).split()), " ".join(core(text).split())
        extra = sorted({norm_number(x) for x in figures(reply)} - {norm_number(x) for x in figures(text)})
        why = []
        if len(r_core) > len(t_core):
            why.append(f"the self-reply is longer than the post ({len(r_core)} vs {len(t_core)} characters "
                       "without links)")
        if extra:
            why.append(f"it holds numbers the post lacks ({', '.join(short(x, 16) for x in extra)})")
        if why:
            add("self_thread", "likely", "warn", "; ".join(why) + "; keep substance in the main post, self-replies "
                                                                  "carry links/sources (continuations get -77% views)")

    # hashtags [stop]
    n_hash = len(HASHTAG.findall(core(text)))
    if n_hash > 1:
        add("hashtags", "stop", "note", f"{n_hash} hashtags: no reach effect (0-1 relevant is fine)")

    score = sum(1 for f in findings if f["kind"] == "warn" and f["level"] in SCORED)
    return {"item_id": iid, "platform": platform, "item_type": kind, "planned_at": planned.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "playbook": PLAYBOOK, "lint_version": VERSION, "score": score, "findings": findings, "skipped": skipped}


def finding_line(f: dict) -> str:
    return f"[{f['level']}] {f['kind'].upper()} {f['rule']}: {f['message']}"


def text_lines(result: dict) -> list[str]:
    head = (f"draft {short(result.get('item_id'), 80)} ({short(result.get('platform'), 12)}): score {result['score']} "
            f"({PLAYBOOK}; advisory, never a block)")
    out = [head] + ["  " + finding_line(f) for f in result["findings"]]
    if not result["findings"]:
        out.append("  no playbook findings")
    if result["skipped"]:
        out.append("  skipped: " + "; ".join(result["skipped"]))
    return out


def answer_lines(result: dict) -> list[str]:
    """Lines appended to grok_review's APPROVE / REJECT answer; empty when there is nothing to say."""
    if not result["findings"]:
        return []
    return [f"NOTES (playbook v2): score {result['score']}, advisory"] + ["- " + finding_line(f) for f in result["findings"]]


# ---------------------------------------------------------------------------
# CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", required=True, help="facts.json URL or path")
    ap.add_argument("--draft", required=True, help="draft JSON file: one object or a list")
    ap.add_argument("--history", help="our own recent posts (JSON list), for spacing / question / link-24h")
    ap.add_argument("--now", help="ISO time to lint at (default: now, UTC); a draft's planned_at wins")
    ap.add_argument("--format", choices=["text", "json", "both"], default="both")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    try:
        now = None
        if a.now:
            now = parse_time(a.now)
            if now is None:
                raise InputError(f"--now {short(a.now)}: not an ISO time with hours and minutes")
        facts = load_json(a.facts, "facts", allow_url=True)
        if not isinstance(facts, dict):
            raise InputError("facts must be a JSON object")
        drafts = load_json(a.draft, "draft")
        drafts = drafts if isinstance(drafts, list) else [drafts]
        history = load_json(a.history, "history") if a.history else None
        results = [lint(d, facts, history, now) for d in drafts]
    except InputError as e:
        print(f"draft_lint: {e}", file=sys.stderr)
        return 2
    if a.format in ("text", "both"):
        for r in results:
            print("\n".join(text_lines(r)))
    if a.format in ("json", "both"):
        print(json.dumps(results[0] if len(results) == 1 else results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
