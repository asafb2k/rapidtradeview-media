"""Stage-A validator for Grok-run brand social drafts (GROK-SOCIAL.md §3, §4).

Usage (conda python: C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe):
  grok_review.py --draft DRAFT.json [--facts FILE|URL] [--comment-state PATH]   one draft; exit 0 APPROVE, 1 REJECT
  grok_review.py --inbox [--dry-run] [--env prod|dev] [--facts-base DIR|URL] [--instinct PATH] [--env-file PATH]
                 [--comment-state PATH]

A post draft is {"item_id", "platform": "x"|"instagram", "text", "reply_text"?, "link", "media_url", "media_note"?}. The facts come from the day's
facts.json (tools/facts.py): the date is the item_id's first 10 characters; --facts-base is the Pages site by
default (what Grok reads) or a local v/ directory. Checks:
  - the item exists in that day's facts;
  - ticker: the item's $cashtag is in the text and no other cashtag is (picks: only the list's public tickers;
    moves_like: the subject and the peers listed in the item); several cashtags only for earnings_tomorrow_roundup and
    ptr_summary: at most 4, each one of the item's tickers, at least one;
  - every number-like token in text and reply is one of the item's allowed_numbers (or the cashtag); the filing names
    Form 4, Form 144, Form 13F, 8-K, 10-Q, 10-K and 13F are words, not numbers (posts and comments);
  - banned words (case-insensitive): the rules' list plus the item's own banned_words (chart_pattern / moves_like:
    no predictions such as "will"); "Not investment advice." in the text;
  - link == the item's page_url with {platform} filled in; every URL in text / reply is that link, the item's
    source_url or one of its source_urls (ptr_summary: one official PTR URL per filing); X: the link and (Congress /
    Form 4 / ptr_summary) at least one source link go in the self-reply (reply_text); Instagram: a Congress / Form 4 /
    ptr_summary caption carries one;
  - X: text and reply each <= max_len.x (X's weighted length: a link counts 23);
  - picks_ready, chart_pattern, moves_like: no "#1" / top-pick hint (the #1 ticker is hidden from us, so a pattern or
    Moves Like post never touches picks);
  - ROUND 7 (HQ 2026-10-19): a sentence that is not one of the item's phrases must EQUAL one of post_vocab.HOOKS for
    the platform, the item type and post / comment use (closed list, no free hook wording; a bare comment: comment
    hooks only). Review round 7b: review / review_comment always read the closed list and REJECT an item without
    phrasings (a facts file built before round 7); only the Growth audit (wording_reasons' audit default) keeps the
    hook-word reading. An exact repeat of a text posted / approved on the platform within 7 days is REJECTED
    (duplicate_reasons). ROTATION (inbox, and --draft --history): a phrasing id or hook id
    used in one of the last min(5, k - 1) own posts of the same item type on the same platform is REJECTED (k = the
    fact's phrasings, or the type's hooks; review round 7b: no least-recently-used escape, the window is sized instead;
    drafts approved but not in the post log yet count too: ApprovedLedger); link labels ("Full map:") never rotate;
    the inbox leaves post drafts unacked while the post history cannot be read. Universe claims on every type
    ("the stock market" as a subject; "every company" / "all 500" unless priced == total) are REJECTED.
  - VERBATIM FACTS (HQ 2026-10-19; every item with fact_phrases): every sentence of text / reply_text (and of a
    comment) that holds any fact is one of the item's fact_phrases / claim_phrases verbatim (light normalisation
    only); any other sentence is a hook made of post_vocab.HOOK_WORDS only (<= 12 words; no name, number, sector,
    date / session, direction, ranking, mood or advice word); a comment without an item_id holds hooks only;
    only generic hashtags and HOOK_EMOJI; the S&P, scope and card rules below still apply. Text is NFKC-folded
    first (math-bold / fullwidth letters); any letter run of any script is a word. Review round 6 (HQ 2026-10-19): an
    item without fact_phrases (a facts file built before the rule) is REJECTED for posts and comments alike; an item is
    usable only through the next weekday after its facts date (New York date of the review: its "on Friday" / "last
    week" / "this week" / "on Tuesday" wording holds that long), a picks item also only until its valid_until; a bare
    domain with a path ("rapidtradeview.trade/...") in a post must be the item's page_url / source, else REJECT.
    The free-form reading below is kept only for the Growth post audit of older posts (wording_reasons):
  - content (tools/claims.py, every item type; HQ review 2026-10-18): never the S&P for our universe ("the 500 largest
    US-listed stocks"; a picks post may compare "vs SPY"); a sentence with any ranking / comparison / order / quantifier
    / record / streak / ratio language (best, biggest, most, top, led, #N, second, next, then, only, all, every, since,
    again, double, more than, beat, missed, ...) only as one of the item's claim_phrases verbatim (HQ 2026-10-19
    allowlist; an item from an older facts file without claim_phrases keeps its `claims` reading); no company put in a
    sector its ticker_sectors entry does not show; scoped numbers (the 30-day insider totals: "open-market", "officers
    and directors"); nothing that contradicts the item's card (card_message);
  - G-N1 holdout: until 2026-11-21 (New York date of the review, as facts.py and select_stories date things) no
    string anywhere in the draft (every field, nested ones and keys included) carries "/earnings/reports/" (an
    earnings report page of either arm); comments likewise;
  - media_url (every own post carries native media, owner 2026-10-12): one of the item's media[].url, a file under
    <Pages>/v/<YYYY-MM-DD>/ (our rendered stills / Reels), or "grok_generated" with a media_note that names no
    digit, $, %, logo, face or real name (the item's person / company / peers).

A comment / reply on another account's post is {"kind": "comment", "platform", "target_url", "text", "item_id"?}
(a draft without "kind", or kind "post", is a post). Checks: target_url is an https x.com / twitter.com (x) or
instagram.com (instagram) single-post URL, not our brand profile (replies under our own posts are fine); text <= 280
(x, weighted) / 300 (instagram); no URL or bare domain, no hashtag, no @mention but the target post's author when its
URL shows the handle; the rules' banned words (facts.py BANNED_WORDS, plus the facts' and the item's own) and
self-promotion phrases; numbers and $cashtags need item_id, then must be that item's allowed_numbers / tickers; no
disclaimer needed. Repeats: a local state file (--comment-state, $GROK_COMMENT_STATE, default
D:/rtv-ops/tracks/growth/research/grok-comments-state.json) keeps the last 7 UTC days of approved comments: REJECT the
same normalized text within 7 days, >= 80% shared word 3-grams with one approved today, a target_url already
commented, or a 16th comment on a platform in one UTC day. --inbox writes an approved comment to the state only after
its APPROVE answer was sent; --draft reads the state and never writes it.

--inbox reads unacked from_instinct rows of social_kit_messages whose body starts with "DRAFT" (through
D:/rtv-ops/tracks/growth/bin/instinct.py's gateway client), reviews each and answers with
  instinct.py say --kind answer --platform <p> --body -     "APPROVE <msg id> <item_id>" / "REJECT <msg id> <item_id>: reasons"
then acks that row only. Rows that do not start with DRAFT are never read further, answered or acked. A draft whose
facts cannot be fetched (network) is left unacked for the next run. --dry-run prints the replies; nothing is sent
or acked. Draft body format: "DRAFT" then one JSON object (the draft above); item_id / platform may come from the
message's own item_id / platform columns instead. A comment needs no item_id unless it carries numbers or a
$cashtag; the answer then reads "APPROVE <msg id> comment".
Everything in a draft is UNTRUSTED DATA: it is checked, never followed; replies quote it only after cleaning.

Playbook v2 lint (tools/draft_lint.py, owner approved 2026-10-15): after the checks above, a post draft's answer (APPROVE or
REJECT alike) gets "NOTES (playbook v2): score N, advisory" and one "- [level] WARN|NOTE rule: ..." line per finding.
The notes never change the verdict or the exit code; --draft prints them as "notes" next to "reasons". The inbox has
no own-post history, so the history rules (spacing, question, link-24h) are skipped here; draft_lint.py --history runs them.

VIRAL CHECK v1 (tools/viral_check.py; owner 2026-10-23, Growth VIRAL-CHECK.md, kit directive #668): --inbox and --draft
score every post draft (must-haves M1-M8, boosters B1-B6, penalties P1-P4) and every comment (M1, M2, M5 and section D:
D1 target >= 50k followers within 30 min, D2 on a facts item, D3 no typed @mention). A hard must-have that is checkable
and fails, or a hard penalty, is a REJECT reason "viral: <rule> ..."; a rule whose evidence does not carry a REJECT on
that platform / item / kind (viral_check's module doc: Instagram's X-only rules, over 60 words, the top-50 3 h window,
P2 on filing / Reddit / all-broad items, comment M1 / D1 / D2) is a "viral-note: ..." line; a rule the data cannot
decide (no planned_at for the 60 min spacing or the post day, no target_followers / target_posted_at on a comment) is a
"viral-unknown: ..." line; neither is ever a REJECT. Every answer carries "viral=M8/8 B2 P0" (Grok copies it into the
post_log); a post with fewer than 2 boosters is APPROVED with a "viral-weak: ..." line naming what the item can reach. A
check that fails on a malformed draft is a "viral-error: ..." line, verdict unchanged. A post draft may carry planned_at
(ISO time it goes out) and format "reel"; a comment draft target_followers and target_posted_at. --no-viral turns the gate off (run_inbox's viral=False, the default for callers
that do not ask for it). --draft prints the score ("viral") and the reasons the inbox would add ("viral_reasons"); they
change its verdict and exit code only with --viral-gate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claims as cl  # noqa: E402
import draft_lint as dl  # noqa: E402
import facts as fx  # noqa: E402
import manifest as mf  # noqa: E402
import market_facts as mk  # noqa: E402
import post_history as ph  # noqa: E402
import select_stories as ss  # noqa: E402
import viral_check as vc  # noqa: E402

DEFAULT_FACTS_BASE = f"{mf.PAGES_BASE}/v"
DEFAULT_INSTINCT = Path("D:/rtv-ops/tracks/growth/bin/instinct.py")
PYTHON = sys.executable
UA = "RapidTradeView grok-review (contact@rapidtradeview.trade)"
SOURCE_TYPES = ("congress_trade", "form4_buy", "ptr_summary")
# Several cashtags in one post: only the roundup kinds (facts.ROUNDUP_TYPES, at most facts.ROUNDUP_MAX_TICKERS, all from
# the item's tickers). moves_like (subject + listed peers) and picks_ready (the public picks) keep their item's own list.
# Market pillars (HQ 2026-10-18) are multi-cashtag too: at most 4, all from tickers + context_tickers.
MULTI_CASHTAG_TYPES = (*fx.ROUNDUP_TYPES, *mk.MARKET_TYPES)
MULTI_CASHTAG_MAX = fx.ROUNDUP_MAX_TICKERS
SINGLE_CASHTAG_MAX = 4  # a single-ticker item: its $TICKER plus listed context_tickers, at most 4 distinct
LIST_TYPES = ("moves_like", "picks_ready")
NO_PICK_HINT_TYPES = ("picks_ready", "chart_pattern", "moves_like")
URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
CASHTAG = re.compile(r"(?<![\w$])\$([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)(?![\w])")
DIGIT_TOKEN = re.compile(r"\S*\d\S*")
# Filing names are words, not numbers (Growth 2026-10-12: "insider buy (Form 4)"): these exact tokens are blanked before
# the number check in posts and comments; anything glued to them ("Form 4%", "Form 44", "110-K", "8-K.5") stays a number.
DOC_NAME = re.compile(r"(?<![\w$.,/-])(?:Form\s+(?:4|144|13F)|8-K|10-Q|10-K|13F)(?![\w%$/]|[.,-]\d)", re.IGNORECASE)
PICK_HINT = re.compile(
    r"#\s*1\b|\bno\.?\s*1\b|\bnumber\s+(?:one|1)\b|\btop\s+(?:pick|idea|stock|choice)|\bbest\s+pick|\bfirst\s+pick"
    r"|\b(?:top|highest)[\s-]+rank|\brank(?:ed)?\s*#?\s*(?:1|one)\b|\block(?:ed)?\b|\bpick\s+of\s+the\s+day\b|\bfavou?rite\b",
    re.IGNORECASE)
DRAFT_HEAD = re.compile(r"^\s*DRAFT\b")
ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
PLATFORMS = ("x", "instagram", "threads")
REPLY_MAX = 3500
THREADS_MAX = 500
# Market wording (HQ 2026-10-18): our map is the 500 largest US-listed companies, not an index (claims.INDEX_WORDS; the
# old pattern here missed "S&P500").
INDEX_WORDS = cl.INDEX_WORDS
UNIVERSE_PHRASE = re.compile(r"\b500\s+largest\b|\blargest\s+US-listed\b", re.IGNORECASE)
ALL_500 = re.compile(r"\ball\s+500\b", re.IGNORECASE)
MARKET_CARD_LIVE = re.compile(r"^https://(?:www\.)?rapidtradeview\.trade/market/card/", re.IGNORECASE)
MARKET_CARD_PINNED = re.compile(rf"^{re.escape(mf.PAGES_BASE)}/v/\d{{4}}-\d{{2}}-\d{{2}}/cards/market-[A-Za-z0-9._-]+\.png$")

# Post media (owner rule 2026-10-12: every own post or Reel carries native media)
GROK_GENERATED = "grok_generated"
OUR_MEDIA = re.compile(rf"^{re.escape(mf.PAGES_BASE)}/v/\d{{4}}-\d{{2}}-\d{{2}}/[A-Za-z0-9._~/-]+$")
NOTE_BAD = re.compile(r"\d|\$|%|\blogos?\b|\btrademarks?\b|\bfaces?\b|\bfacial\b|\bportraits?\b|\bheadshots?\b"
                      r"|\bselfies?\b|\blikeness\b", re.IGNORECASE)
NAME_FILLER = {"inc", "corp", "corporation", "company", "holdings", "group", "the", "and", "ltd", "plc", "llc", "class",
               "trust", "fund", "etf", "rep", "sen"}

# Comments and replies on other accounts' threads (owner rule 2026-10-12: >= 5 actions/day per platform)
COMMENT_MAX = {"x": 280, "instagram": 300}
COMMENT_CAP = 15            # approved comments per platform per UTC day: a ceiling against spam
COMMENT_DAYS = 7            # the state keeps (and exact-dedupes over) this many UTC days, today included
COMMENT_NGRAM_SHARE = 0.8   # same-day near-duplicate: share of word 3-grams
PROMO_WORDS = ["follow us", "check out", "dm", "dms", "link in bio", "our app", "sign up"]
BRAND_HANDLES = {"x": "rapidtradeview", "instagram": "rapidtradeview3"}
TARGET_HOSTS = {"x": {"x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"},
                "instagram": {"instagram.com", "www.instagram.com", "m.instagram.com"}}
X_POST = re.compile(r"^/(?:i/web|i|(?P<h>[A-Za-z0-9_]{1,15}))/status/(?P<id>\d{1,25})(?:/[A-Za-z0-9_/]*)?$")
IG_POST = re.compile(r"^/(?:(?P<h>[A-Za-z0-9_.]{1,30})/)?(?:p|reel|reels|tv)/(?P<id>[A-Za-z0-9_-]{5,64})/?$")
BARE_DOMAIN = re.compile(r"(?<![\w@.-])(?:[a-z0-9-]+\.)+[a-z]{2,24}(?![\w-])(?:/\S*)?", re.IGNORECASE)
HASHTAG = re.compile(r"(?<![\w&/])[#\uff03](?=\w*[^\W\d_])\w+")
MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]{1,30})")
DEFAULT_COMMENT_STATE = Path("D:/rtv-ops/tracks/growth/research/grok-comments-state.json")
COMMENT_STATE_ENV = "GROK_COMMENT_STATE"


class FactsUnavailable(Exception):
    """facts.json could not be fetched right now (network): try again later, do not answer."""


class StateUnreadable(Exception):
    """The comment state file exists but cannot be read: comment drafts are not answered until it is fixed."""


# ---------------------------------------------------------------------------
# Facts

def facts_location(base: str, date: str) -> str:
    return f"{base.rstrip('/')}/{date}/facts.json"


def load_facts(where: str) -> dict | None:
    """The facts dict; None when there is no file for that date (404 / missing); FactsUnavailable on other errors."""
    if re.match(r"^https?://", where):
        req = urllib.request.Request(where, headers={"User-Agent": UA, "Accept": "application/json", "Cache-Control": "no-cache"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise FactsUnavailable(f"{where}: HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise FactsUnavailable(f"{where}: {type(e).__name__}") from None
    p = Path(where)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise FactsUnavailable(f"{where}: {type(e).__name__}") from None


# ---------------------------------------------------------------------------
# Checks

def short(s: str, n: int = 40) -> str:
    s = " ".join(str(s).split())
    s = re.sub(r"[^\x20-\x7e\u00a0-\u024f\u2010-\u2027\u2212]", "", s)
    return s if len(s) <= n else s[: n - 1] + "~"


MARK = "\u00a7"  # stands in for a matched number, so "$15K-$50K" still reads as a range after "$15K" is blanked


def _norm(s: str) -> str:
    return s.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2212", "-")


def strip_allowed(text: str, allowed: list[str]) -> str:
    """The text with every allowed number phrase (longest first, whole tokens only) blanked out. A sign the facts do
    not carry ("-$1.72" when the allowed number is "$1.72") keeps the number in; a range dash ("$15K-$50K") does not."""
    s = _norm(text)

    def repl(m: re.Match) -> str:
        i = m.start()
        if m.group(0)[0] not in "-+" and i > 0 and m.string[i - 1] in "-+":
            prev = m.string[i - 2] if i > 1 else ""
            if not (prev.isalnum() or prev in f"%{MARK}"):
                return m.group(0)
        return MARK

    for a in sorted({_norm(a) for a in allowed if a}, key=len, reverse=True):
        s = re.sub(rf"(?<![\w.,]){re.escape(a)}(?![\w]|[.,]\d)", repl, s, flags=re.IGNORECASE)
    return s.replace(MARK, " ")


def unexplained_numbers(text: str, allowed: list[str], tickers: list[str]) -> list[str]:
    """Number-like tokens of `text` that are not an allowed number (URLs, filing names such as "Form 4" / "10-K" and the
    item's cashtags are not numbers)."""
    s = URL.sub(" ", text)
    s = DOC_NAME.sub(" ", s)
    s = strip_allowed(s, allowed)
    s = CASHTAG.sub(lambda m: " " if m.group(1).upper() in tickers else m.group(0), s)
    out = []
    for tok in DIGIT_TOKEN.findall(s):
        tok = tok.strip(".,;:!?()[]{}\"'")
        if re.search(r"\d", tok):
            out.append(tok)
    return out


def uniq_words(words) -> list[str]:
    out: list[str] = []
    for w in words:
        if isinstance(w, str) and w and w.lower() not in (o.lower() for o in out):
            out.append(w)
    return out


def item_cashtags(item: dict) -> list[str]:
    """Cashtags a post of this item may carry: its tickers plus its context_tickers (facts.py; HQ 2026-10-18)."""
    base = item.get("tickers") or ([item["ticker"]] if item.get("ticker") else [])
    return list(dict.fromkeys(str(t).upper() for t in [*base, *(item.get("context_tickers") or [])] if t))


def item_numbers(item: dict) -> list[str]:
    """Numbers a post of this item may print: allowed_numbers plus context_numbers (both computed by facts.py)."""
    return [str(a) for a in [*(item.get("allowed_numbers") or []), *(item.get("context_numbers") or [])] if a]


def market_total_numbers(item: dict) -> list[str]:
    """The numbers of an item that state a total of the 500 (its market total): a post printing one must say whose."""
    kind = item.get("type")
    if kind == "market_move":
        t = item.get("totals") or {}
        return [*mk.usd_forms(t.get("usd_change_sum") or 0), *mk.pct_forms(t.get("pct_change") or 0)]
    if kind == "sector_rotation" and isinstance(item.get("all_500"), (int, float)):
        return mk.pct_forms(item["all_500"])
    if kind == "breadth_day" and isinstance(item.get("cap_weighted_pct"), (int, float)):
        return mk.pct_forms(item["cap_weighted_pct"])
    return []


def wording_reasons(item: dict, text: str, platform: str | None = None, audit: bool = True) -> list[str]:
    """Content rules every post of every item type passes (HQ 2026-10-18 review fixes; tools/claims.py): never the S&P
    for our universe (only a picks post may compare "vs SPY"); comparatives / superlatives only as the item's claims back
    them; no company put in a sector it is not in; scoped numbers carry their scope; no contradiction of the card.
    P1 / P2 / P6 / P7 also: "all 500" only when all 500 were priced; a market total says "500 largest". The Growth post
    audit calls this too (one rule set). audit=True (the default: the Growth audit's call of posts already published)
    keeps the hook-word reading of non-fact sentences; the validator (review, phrase_reasons) passes audit=False: closed
    hook sentences only, whatever the item (review round 7b)."""
    if cl.verbatim_mode(item):
        # HQ 2026-10-19 verbatim facts rule (claims.py section 2d): every factual sentence is one of the item's pre-verified
        # phrases, every other sentence a fact-free hook; the S&P / scope / card rules still read the whole text
        out = (cl.verbatim_reasons(item, text, platform=platform, audit=audit)
               + cl.index_reasons(item.get("type"), text, cl.item_names(item))
               + cl.card_reasons(item, text) + cl.scope_reasons(item, text, strip_allowed))
    else:
        out = cl.content_reasons(item, text, strip_allowed)
    # every item type (Growth PILLARS section 9 ask 4): "the stock market" as a subject, "every company" without coverage
    out += cl.universe_reasons(item, text)
    if item.get("type") not in mk.WORDING_TYPES:
        return out
    t = item.get("totals") or {}
    if ALL_500.search(text) and not (t.get("priced") and t.get("priced") == t.get("total")):
        out.append("market wording: not \"all 500\" (not every one of the 500 was priced)")
    totals = market_total_numbers(item)
    if totals and not UNIVERSE_PHRASE.search(text) and strip_allowed(text, totals) != _norm(text):
        out.append(f"market wording: a market total needs \"500 largest\" (\"{mk.UNIVERSE_WORDS}\")")
    return out


def phrase_reasons(item: dict, text: str) -> list[str]:
    """Why one of the item's own phrases (fact / claim phrase, angle) may not be published (facts.self_check, HQ
    2026-10-19): it must pass as a one-sentence post of the item - the verbatim reading, every number allowed, its
    cashtags the item's (at most 4), no banned word, the S&P / scope / card / market wording rules - and the data checks
    of the free-form era as a safety net (window, direction, sector attribution)."""
    out = wording_reasons(item, f"{text} Not investment advice.", audit=False)
    tickers = item_cashtags(item)
    tags = {m.group(1).upper() for m in CASHTAG.finditer(text)}
    if tags - set(tickers):
        out.append(f"cashtag not in this item: {', '.join(sorted(tags - set(tickers)))}")
    if len(tags) > MULTI_CASHTAG_MAX:
        out.append(f"{len(tags)} cashtags (at most {MULTI_CASHTAG_MAX})")
    bad = unexplained_numbers(cl.spy_blank(item.get("type"), text), item_numbers(item), tickers)
    if bad:
        out.append("numbers not allowed: " + ", ".join(sorted(set(bad))))
    low = text.lower()
    banned = [w for w in uniq_words([*fx.BANNED_WORDS, *(item.get("banned_words") or [])])
              if re.search(rf"(?<!\w){re.escape(w.lower())}(?!\w)", low)]
    if banned:
        out.append(f"banned words: {', '.join(banned)}")
    out += cl.window_reasons(item, text) + cl.direction_reasons(item, text) + cl.sector_reasons(item, text)
    return out


# G-N1 holdout (select_stories.G_N1_HOLDOUT_END, 2026-11-21): no post, self-reply, comment, link or media of ours carries
# an earnings report page (/earnings/reports/<id>) of either arm before the readout. The whole draft is screened.


def holdout_reasons(draft: dict, now: dt.datetime | None = None) -> list[str]:
    """REJECT reasons for a draft that carries /earnings/reports/ in any string (any field, nested, keys included)
    inside the G-N1 holdout (the review's New York date)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    if not ss.g_n1_holdout(now.astimezone(ss.NY).date()):
        return []
    bad = ss.report_page_paths(draft)
    return [f"{', '.join(bad)}: no {ss.REPORT_PAGE_PATH} link or media until {ss.G_N1_HOLDOUT_END} (G-N1 holdout); "
            "link /dashboard/<T>#earnings-history"] if bad else []


# Item gate (review round 6, HQ 2026-10-19): only items built under the verbatim rule, and only while their relative
# wording is true. A facts file of date D speaks of "on Friday" / "last week" / "this week" / "on Tuesday" as seen on D;
# that holds through the next weekday after D (New York date of the review), never later. A picks item also stops at its
# valid_until.

def _iso_date(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def item_last_day(item: dict, facts: dict | None) -> dt.date | None:
    """The last New York date a post / comment may use this item: the next weekday after its facts date (the earlier of
    the item_id's date and the facts file's date)."""
    days = [d for d in (_iso_date(item.get("item_id")), _iso_date((facts or {}).get("date"))) if d]
    if not days:
        return None
    nxt = min(days) + dt.timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += dt.timedelta(days=1)
    return nxt


def item_gate_reasons(item: dict, facts: dict | None, now: dt.datetime | None = None) -> list[str]:
    """REJECT reasons for using `item` at `now`: built before the verbatim rule, or past its validity."""
    iid = short(item.get("item_id"), 80)
    if not cl.verbatim_mode(item):
        return [f"item {iid} is from a facts file built before the verbatim facts rule (no fact_phrases): use an item of "
                "today's facts"]
    if not isinstance(item.get(cl.PHRASINGS_KEY), list):
        # review round 7b: no phrasings = built before the closed hooks, rotation and card rules (round 7): never usable
        return [f"item {iid} is from a facts file built before the round-7 rules (no phrasings: closed hooks, rotation, "
                "card checks): use an item of today's facts"]
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    out = []
    last = item_last_day(item, facts)
    ny = now.astimezone(ss.NY).date() if ss.NY else now.date()
    if last is None:
        out.append(f"item {iid}: no facts date, so its wording cannot be dated")
    elif ny > last:
        out.append(f"item {iid} is stale: its wording (\"on Friday\", \"last week\", \"this week\", ...) holds only through "
                   f"{last.isoformat()} (New York); use an item of today's facts")
    until = item.get("valid_until")
    if until:
        try:
            vu = dt.datetime.fromisoformat(str(until).replace("Z", "+00:00"))
            vu = vu if vu.tzinfo else vu.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            vu = None
        if vu is None:
            out.append(f"item {iid}: valid_until {short(until, 40)!r} is not a time")
        elif now > vu:
            out.append(f"item {iid} expired at {vu.astimezone(dt.timezone.utc).isoformat()} (valid_until)")
    return out


def bare_link_reasons(item: dict, text: str, allowed_urls: list[str]) -> list[str]:
    """A domain written without https:// (X / Threads auto-link it and show its path): only our bare domain or sec.gov
    without a path, a domain that is part of the item's own wording (a company name like "Amazon.com"), or one of the
    item's URLs without its scheme."""
    s = URL.sub(" ", text)
    own = " ".join(str(x) for x in [item.get("name"), item.get("company"), item.get("facts_text"),
                                    *(item.get(cl.VERBATIM_KEY) or []), *(item.get("claim_phrases") or [])] if x).lower()
    bare_ok = {u.split("://", 1)[-1].rstrip("/") for u in allowed_urls if u}
    out = []
    for m in BARE_DOMAIN.finditer(s):
        b = m.group(0).rstrip(".,;:!?)]}\"'")
        host, slash, path = b.partition("/")
        if not path.strip("/") and (host.lower().removeprefix("www.") in ("rapidtradeview.trade", "sec.gov")
                                    or host.lower() in own):
            continue
        if b.rstrip("/") in bare_ok:
            continue
        out.append(f"link without https:// not from this item: {short(b, 80)} (write the item's page_url or source in "
                   "full, or no link)")
    return out


def review(draft: dict, facts: dict | None, now: dt.datetime | None = None) -> tuple[str, list[str]]:
    """("APPROVE", []) or ("REJECT", reasons)."""
    reasons: list[str] = holdout_reasons(draft, now)
    iid = draft.get("item_id")
    platform = draft.get("platform")
    text = draft.get("text")
    reply = draft.get("reply_text")
    link = draft.get("link")
    if not isinstance(iid, str) or not iid:
        return "REJECT", ["no item_id"]
    if platform not in PLATFORMS:
        reasons.append(f"platform must be x, instagram or threads (got {short(platform)!r})")
    if not isinstance(text, str) or not text.strip():
        return "REJECT", reasons + ["no text"]
    if reply is not None and not isinstance(reply, str):
        return "REJECT", reasons + ["reply_text must be text"]
    reply = reply or ""
    if facts is None:
        return "REJECT", reasons + [f"no facts.json for {short(iid[:10])}"]
    item = next((i for i in facts.get("items") or [] if i.get("item_id") == iid), None)
    if item is None:
        return "REJECT", reasons + [f"item {short(iid, 80)} is not in the {facts.get('date')} facts"]
    gate = item_gate_reasons(item, facts, now)
    if gate:
        return "REJECT", reasons + gate
    rules = facts.get("rules") or {}
    raw_text, raw_reply = text, reply   # lengths are measured on what is posted
    text, reply = cl.nfkc(text), cl.nfkc(reply)   # every content check reads the folded text (math-bold, fullwidth)
    both = f"{text}\n{reply}"

    # Ticker (tickers + context_tickers; HQ 2026-10-18)
    tickers = item_cashtags(item)
    tags = [m.group(1).upper() for m in CASHTAG.finditer(both)]
    other = sorted({t for t in tags if t not in tickers})
    if other:
        reasons.append(f"cashtag not in this item: {', '.join('$' + short(t, 8) for t in other)}")
    distinct = set(tags)
    kind = item.get("type")
    if kind in MULTI_CASHTAG_TYPES:
        if len(distinct) > MULTI_CASHTAG_MAX:
            reasons.append(f"{kind}: at most {MULTI_CASHTAG_MAX} cashtags (got {len(distinct)})")
        if tickers and not distinct & set(tickers):
            reasons.append(f"{kind}: the text must name at least one of the item's tickers")
    elif kind not in LIST_TYPES:
        own = {str(item.get("ticker") or "").upper(), *(str(t).upper() for t in item.get("context_tickers") or [])} - {""}
        extra = sorted(distinct - own)
        if extra:
            reasons.append(f"one cashtag per post (plus the item's context_tickers): {', '.join('$' + short(t, 8) for t in extra)} "
                           "is not the item's ticker or one of its context_tickers")
        elif len(distinct) > SINGLE_CASHTAG_MAX:
            reasons.append(f"at most {SINGLE_CASHTAG_MAX} cashtags (got {len(distinct)})")
    if item.get("ticker") and f"${item['ticker'].upper()}" not in {f"${m.group(1).upper()}" for m in CASHTAG.finditer(text)}:
        reasons.append(f"the text must name ${item['ticker']}")

    # Numbers (allowed_numbers + context_numbers)
    allowed = item_numbers(item)
    bad = unexplained_numbers(cl.spy_blank(kind, both), allowed, tickers)
    if bad:
        reasons.append("numbers not in allowed_numbers / context_numbers: " + ", ".join(sorted({short(b, 24) for b in bad})))

    # Market wording (P1 P2 P6 P7), the verbatim rule with the platform's closed hooks
    reasons += wording_reasons(item, both, platform if platform in PLATFORMS else None, audit=False)

    # Words
    low = both.lower()
    words = uniq_words([*(rules.get("banned_words") or []), *(item.get("banned_words") or [])])
    banned = [w for w in words if re.search(rf"(?<!\w){re.escape(w.lower())}(?!\w)", low)]
    if banned:
        reasons.append(f"banned words: {', '.join(banned)}")
    disclaimer = rules.get("disclaimer") or "Not investment advice."
    for must in [disclaimer, *(item.get("must_include") or [])]:
        if must not in text:
            reasons.append(f'the text must include "{must}"')
            break

    # Links
    want = (item.get("page_url") or "").replace(rules.get("platform_placeholder") or "{platform}", str(platform))
    if link != want:
        reasons.append(f"link must be the item's page_url for {short(platform)} (utm_source={short(platform)}, "
                       f"utm_content={short(iid, 80)})")
    srcs = item_sources(item)
    raw_both = f"{raw_text}\n{raw_reply}"
    for u in dict.fromkeys([*URL.findall(both), *URL.findall(raw_both)]):
        u = u.rstrip(".,;:!?)]}")
        if u != want and u not in srcs:
            reasons.append(f"URL not from this item: {short(u, 80)}")
    # a domain without https:// (review round 6: "rapidtradeview.trade/GOOGL-will-double" was read past)
    for r in dict.fromkeys([*bare_link_reasons(item, both, [want, *srcs]), *bare_link_reasons(item, raw_both, [want, *srcs])]):
        reasons.append(r)
    if item.get("type") == "ptr_summary" and not srcs:
        reasons.append("ptr_summary: the item has no official source URL to cite")
    if platform == "x":
        if want and want not in raw_reply:
            reasons.append("X: the page link goes in the self-reply (reply_text)")
        if item.get("type") in SOURCE_TYPES and srcs and not any(u in raw_reply for u in srcs):
            reasons.append("X: the official source link goes in the self-reply (reply_text)")
    elif platform == "instagram" and item.get("type") in SOURCE_TYPES and srcs and not any(u in raw_both for u in srcs):
        reasons.append("Instagram: the caption must carry the official source link")

    # Media
    reasons += media_reasons(draft, item)

    # Length
    if platform == "x":
        limit = int((rules.get("max_len") or {}).get("x") or 270)
        for name, body in (("text", raw_text), ("reply_text", raw_reply)):
            n = mf.x_weighted_length(body)
            if n > limit:
                reasons.append(f"X {name} is {n} characters (limit {limit})")
    elif platform == "threads":
        limit = int((rules.get("max_len") or {}).get("threads") or THREADS_MAX)
        for name, body in (("text", raw_text), ("reply_text", raw_reply)):
            if len(body) > limit:
                reasons.append(f"Threads {name} is {len(body)} characters (limit {limit})")

    # Picks
    if item.get("type") in NO_PICK_HINT_TYPES:
        hint = PICK_HINT.search(both)
        if hint:
            reasons.append(f"picks: no #1 / top-pick hint ({short(hint.group(0))!r})")

    return ("REJECT", reasons) if reasons else ("APPROVE", [])


def item_sources(item: dict) -> list[str]:
    """The item's source URLs a post may carry: source_url and every source_urls entry (a ptr_summary over several
    filings has source_url null and one official URL per filing). ptr_summary: official PTR hosts only."""
    urls = [u for u in [item.get("source_url"), *(item.get("source_urls") or [])] if isinstance(u, str) and u]
    if item.get("type") == "ptr_summary":
        urls = [u for u in urls if fx.official(u, fx.OFFICIAL_PTR_HOSTS)]
    return list(dict.fromkeys(urls))


def item_names(item: dict) -> list[str]:
    """Name words a Grok-made image note must not carry: the item's person / company and its peers' names."""
    names = [item.get("name"), *((p or {}).get("name") for p in item.get("peers") or [] if isinstance(p, dict))]
    out: list[str] = []
    for n in names:
        if isinstance(n, str) and n.strip():
            out.append(n.strip())
            out += [w for w in re.split(r"[^A-Za-z]+", n) if len(w) >= 3 and w.lower() not in NAME_FILLER]
    return uniq_words(out)


def media_reasons(draft: dict, item: dict) -> list[str]:
    """A post carries native media: one of the item's media urls, our rendered file on Pages, or a Grok-made image
    whose media_note shows no number, logo or real person."""
    media = draft.get("media_url")
    ours = [m.get("url") for m in item.get("media") or [] if isinstance(m, dict) and m.get("url")]
    if not isinstance(media, str) or not media.strip():
        return ["media_url missing: every post carries an image or video (one of the item's media urls, our file "
                f"under {mf.PAGES_BASE}/v/<date>/, or \"{GROK_GENERATED}\" with a media_note)"]
    if media == GROK_GENERATED:
        note = draft.get("media_note")
        if not isinstance(note, str) or not note.strip():
            return [f"media_url {GROK_GENERATED} needs a media_note describing the image"]
        bad = [m.group(0) for m in NOTE_BAD.finditer(note)]
        low = note.lower()
        bad += [n for n in item_names(item) if re.search(rf"(?<!\w){re.escape(n.lower())}(?!\w)", low)]
        if bad:
            return ["media_note: a Grok-made image carries no numbers, $, %, logos, faces or real names "
                    f"({', '.join(sorted({short(b, 24) for b in bad}))})"]
        return []
    card = item.get("card") if isinstance(item.get("card"), dict) else None
    if MARKET_CARD_LIVE.match(media):
        return ["media_url: the live /market/card/ image changes every session; attach the item's pinned card "
                f"({short((card or {}).get('url') or 'card.url', 90)})"]
    if MARKET_CARD_PINNED.match(media) and media not in ours:
        return [f"media_url {short(media, 90)} is a Market card of another item or day; this item's card is "
                f"{short((card or {}).get('url') or '(none)', 90)}"]
    reel_dir = f"{mf.PAGES_BASE}/v/{str(item.get('item_id'))[:10]}/cards/{item.get('item_id')}/"
    if card and card.get("url") and media not in ours and not media.startswith(reel_dir):
        return [f"media_url: a market post carries its pinned card {short(card['url'], 90)} (or the card Reel made from it)"]
    if media in ours or (OUR_MEDIA.match(media) and ".." not in media):
        return []
    return [f"media_url {short(media, 80)} is not one of the item's media urls, a file under {mf.PAGES_BASE}/v/<date>/ "
            f"or {GROK_GENERATED}"]


# ---------------------------------------------------------------------------
# Comments and replies

def norm_comment(text: str) -> str:
    """Lowercase words only: punctuation, digits and underscores removed."""
    return " ".join(re.sub(r"[^\w\s]|[\d_]", " ", text.lower()).split())


def trigrams(norm: str) -> set[tuple[str, ...]]:
    w = norm.split()
    return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}


def parse_target(platform: str, url) -> tuple[str | None, str | None, str | None]:
    """(post key, author handle or None, error) for the post a comment replies to."""
    if not isinstance(url, str) or not url.strip():
        return None, None, "no target_url"
    try:
        p = urllib.parse.urlsplit(url.strip())
        port = p.port
    except ValueError:
        return None, None, f"target_url is not a URL: {short(url, 80)}"
    host = (p.hostname or "").lower()
    if p.scheme != "https" or p.username or p.password or port is not None or host not in TARGET_HOSTS.get(platform, ()):
        site = "x.com / twitter.com" if platform == "x" else "instagram.com"
        return None, None, f"target_url must be an https {site} post URL (got {short(url, 80)})"
    first = p.path.strip("/").split("/")[0].lower() if p.path.strip("/") else ""
    m = (X_POST if platform == "x" else IG_POST).match(p.path)
    if not m:
        if first == BRAND_HANDLES[platform]:
            return None, None, "target_url is our own brand account: comment on other accounts' posts"
        return None, None, f"target_url must be a single post's URL (got {short(url, 80)})"
    return f"{platform}:{m.group('id')}", m.group("h"), None


class CommentState:
    """Approved comments of the last COMMENT_DAYS UTC days: {"approved": [{date, platform, target, target_url, text,
    norm, msg_id, at}]}. Written only when an APPROVE answer was sent."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.approved: list[dict] = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as e:
                raise StateUnreadable(f"{self.path}: {type(e).__name__}") from None
            if not isinstance(data, dict) or not isinstance(data.get("approved"), list):
                raise StateUnreadable(f"{self.path}: expected {{\"approved\": [...]}}")
            self.approved = [a for a in data["approved"] if isinstance(a, dict)]

    @staticmethod
    def day(now: dt.datetime) -> str:
        return now.astimezone(dt.timezone.utc).date().isoformat()

    def recent(self, now: dt.datetime) -> list[dict]:
        since = (now.astimezone(dt.timezone.utc).date() - dt.timedelta(days=COMMENT_DAYS - 1)).isoformat()
        return [a for a in self.approved if str(a.get("date") or "") >= since]

    def reasons(self, platform: str, target: str | None, text: str, now: dt.datetime) -> list[str]:
        today, out = self.day(now), []
        recent = self.recent(now)
        n_today = sum(1 for a in recent if a.get("date") == today and a.get("platform") == platform)
        if n_today >= COMMENT_CAP:
            out.append(f"daily cap: {n_today} {platform} comments already approved today (UTC; cap {COMMENT_CAP})")
        if target and any(a.get("target") == target for a in recent):
            out.append("this target_url already got an approved comment")
        norm = norm_comment(text)
        grams = trigrams(norm)
        for a in recent:
            if norm and a.get("norm") == norm:
                out.append(f"duplicate: the same text was approved on {short(a.get('date'), 10)}")
                break
            if a.get("date") == today and grams:
                old = trigrams(str(a.get("norm") or ""))
                if old and len(grams & old) / min(len(grams), len(old)) >= COMMENT_NGRAM_SHARE:
                    out.append("near-duplicate of a comment approved today (>= 80% shared word 3-grams)")
                    break
        return out

    def add(self, draft: dict, msg_id, now: dt.datetime) -> None:
        platform = draft.get("platform")
        target, _, _ = parse_target(platform, draft.get("target_url"))
        self.approved.append({"date": self.day(now), "platform": platform, "target": target,
                              "target_url": draft.get("target_url"), "text": draft.get("text"),
                              "norm": norm_comment(draft.get("text") or ""), "msg_id": msg_id,
                              "at": now.astimezone(dt.timezone.utc).isoformat()})

    def save(self, now: dt.datetime) -> None:
        self.approved = self.recent(now)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"approved": self.approved}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)


def review_comment(draft: dict, facts: dict | None, state: CommentState | None,
                   now: dt.datetime | None = None) -> tuple[str, list[str]]:
    """("APPROVE", []) or ("REJECT", reasons) for a comment / reply on another account's post."""
    now = now or dt.datetime.now(dt.timezone.utc)
    reasons: list[str] = []
    platform = draft.get("platform")
    text = draft.get("text")
    iid = draft.get("item_id")
    reasons += holdout_reasons(draft, now)
    if platform not in COMMENT_MAX:
        return "REJECT", reasons + [f"platform must be x or instagram (got {short(platform)!r})"]
    if not isinstance(text, str) or not text.strip():
        return "REJECT", reasons + ["no text"]
    if iid is not None and (not isinstance(iid, str) or not ITEM_ID.match(iid)):
        return "REJECT", reasons + ["item_id must be a facts item id"]
    target, author, err = parse_target(platform, draft.get("target_url"))
    if err:
        reasons.append(err)

    # Length
    limit = COMMENT_MAX[platform]
    n = mf.x_weighted_length(text) if platform == "x" else len(text)
    if n > limit:
        reasons.append(f"{platform} comment is {n} characters (limit {limit})")

    raw = text
    text = cl.nfkc(text)   # every content check reads the folded text (math-bold, fullwidth); the length above is raw
    # Links, hashtags, mentions
    if URL.search(text) or BARE_DOMAIN.search(text) or URL.search(raw) or BARE_DOMAIN.search(raw):
        reasons.append("no links in comments")
    tags = HASHTAG.findall(text)
    if tags:
        reasons.append(f"no hashtags in comments ({', '.join(short(t, 24) for t in tags)})")
    # No @mention at all: X and Instagram add the reply-to handle themselves, so a typed one shows twice and reads as
    # bot-like (10-12, the first live reply showed "@christankerfund @christankerfund ...").
    handles = [m.group(1).rstrip(".") for m in MENTION.finditer(text)]
    if handles:
        reasons.append("no @mentions in comments: the platform adds the reply-to handle itself (typed one shows twice); "
                       f"remove {', '.join('@' + short(h, 30) for h in sorted(set(handles)))}")

    # Item, cashtags, numbers
    rules = (facts or {}).get("rules") or {}
    item = None
    scan = MENTION.sub(" ", text)
    cashtags = [m.group(1).upper() for m in CASHTAG.finditer(scan)]
    has_number = bool(re.search(r"\d", DOC_NAME.sub(" ", CASHTAG.sub(" ", scan))))
    if iid:
        if facts is None:
            reasons.append(f"no facts.json for {short(iid[:10])}")
        else:
            item = next((i for i in facts.get("items") or [] if i.get("item_id") == iid), None)
            if item is None:
                reasons.append(f"item {short(iid, 80)} is not in the {facts.get('date')} facts")
            else:
                gate = item_gate_reasons(item, facts, now)
                if gate:   # review round 6: an older or stale item is never an unchecked path
                    return "REJECT", reasons + gate
    elif cashtags or has_number:
        reasons.append("a comment with numbers or a $cashtag needs the item_id of the facts it uses")
    if item is not None:
        tickers = item_cashtags(item)
        other = sorted({t for t in cashtags if t not in tickers})
        if other:
            reasons.append(f"cashtag not in this item: {', '.join('$' + short(t, 8) for t in other)}")
        bad = unexplained_numbers(scan, item_numbers(item), tickers)
        if bad:
            reasons.append("numbers not in allowed_numbers: " + ", ".join(sorted({short(b, 24) for b in bad})))
        if item.get("type") in NO_PICK_HINT_TYPES:
            hint = PICK_HINT.search(text)
            if hint:
                reasons.append(f"picks: no #1 / top-pick hint ({short(hint.group(0))!r})")
        reasons += cl.index_reasons(item.get("type"), scan, cl.item_names(item)) + cl.universe_reasons(item, scan)
        if cl.verbatim_mode(item):
            # HQ 2026-10-19 verbatim facts rule: a comment states facts only as the item's phrases, verbatim (round 7:
            # every other sentence one of the closed comment hooks)
            reasons += cl.verbatim_reasons(item, scan, comment=True, platform=platform)
    elif not iid:
        # no item: closed comment hooks only (a comment is never an unchecked path for a fact)
        reasons += cl.verbatim_reasons(None, scan, comment=True, platform=platform)

    # Words
    low = text.lower()
    words = uniq_words([*fx.BANNED_WORDS, *(rules.get("banned_words") or []), *((item or {}).get("banned_words") or []),
                        *PROMO_WORDS])
    banned = [w for w in words if re.search(rf"(?<!\w){re.escape(w.lower())}(?!\w)", low)]
    if banned:
        reasons.append(f"banned words: {', '.join(banned)}")

    # Repeats and the daily cap
    if state is not None:
        reasons += state.reasons(platform, target, text, now)
    return ("REJECT", reasons) if reasons else ("APPROVE", [])


# ---------------------------------------------------------------------------
# Variety lint (HQ 2026-10-18, social-content PLAN §3.2 rules 5-10). Own posts only (comments are exempt). History = the
# platform's own posts from the kit post_log (post_history.py). Each rule WARNs on its first breach on a platform's New York
# day (a NOTES line; the verdict stands) and REJECTs a repeat breach of the same rule that day (VarietyState, written only
# after an APPROVE answer with the warning was sent).

DEFAULT_VARIETY_STATE = Path("D:/rtv-ops/tracks/growth/research/grok-variety-state.json")
VARIETY_STATE_ENV = "GROK_VARIETY_STATE"
HISTORY_POSTS = 10           # rule 8 looks at the platform's last 10 own posts
FIRST_WORDS = 8
FIRST_LINE_OVERLAP = 0.6     # rule 8: share of the draft's first 8 words found in an earlier first 8 words
TWIN_SIMILARITY = 0.7        # rule 9: >= 30% different wording = word-set similarity under 0.7
PILLAR_DAY_CAP = 2           # rule 6
WORD = re.compile(r"\$?[a-z0-9][a-z0-9.%'\u2212-]*")
MONEY_PCT = re.compile(r"[\u2212+-]?\$\d[\d,]*(?:\.\d+)?[KMBT]?|[\u2212+-]?\d+(?:\.\d+)?%")


def words_of(text: str) -> list[str]:
    return WORD.findall(_norm(text or "").lower())


def first_words(text: str) -> list[str]:
    line = next((ln for ln in (text or "").splitlines() if ln.strip()), "")
    return words_of(line)[:FIRST_WORDS]


def overlap(a: list[str], b: list[str]) -> float:
    return len(set(a) & set(b)) / len(set(a)) if a else 0.0


def similarity(a: str, b: str) -> float:
    x, y = set(words_of(a)), set(words_of(b))
    return len(x & y) / len(x | y) if x | y else 0.0


def variety_breaches(draft: dict, item: dict, history: list[dict], now: dt.datetime) -> list[tuple[str, str]]:
    """[(rule, why)] for one post draft against our own posts (oldest first)."""
    platform, text, iid = draft.get("platform"), draft.get("text") or "", draft.get("item_id")
    today = (now.astimezone(ss.NY) if ss.NY else now).date()
    own = [p for p in history if p.get("platform") == platform and p.get("item_id") != iid]
    pillar = ph.pillar_of(item.get("type"))
    out: list[tuple[str, str]] = []
    if own and pillar and own[-1].get("pillar") == pillar:
        out.append(("rule5_same_pillar", f"same pillar ({pillar}) as the platform's newest own post"))
    n_today = sum(1 for p in own if p.get("ny_date") == today.isoformat() and p.get("pillar") == pillar)
    if pillar and n_today >= PILLAR_DAY_CAP:
        out.append(("rule6_pillar_cap", f"{n_today} {pillar} posts on {platform} today already (max {PILLAR_DAY_CAP})"))
    ticks = set(mk.headline_tickers(item))  # lead tickers, across pillars (a GOOGL mega_mover cools a GOOGL-led market_move)
    mine = [p for p in history if p.get("platform") == platform]
    if item.get("dedupe_key") and any(p.get("dedupe_key") == item["dedupe_key"] for p in mine):
        out.append(("rule7_ticker_repeat", f"this item is already posted on {platform}"))
    elif ticks and item.get("type") != "earnings_result":
        hit = [p for p in mine if ticks & set(fx.post_tickers(p)) and p.get("ny_date")
               and ss.weekday_age(ss.d(p["ny_date"]), today) < fx.TICKER_COOLDOWN_SESSIONS]
        if hit:
            same = ", ".join("$" + t for t in sorted(ticks & set(fx.post_tickers(hit[-1]))))
            out.append(("rule7_ticker_repeat", f"{same} led a {platform} post on {hit[-1]['ny_date']} (within 3 trading days, any pillar)"))
    fw = first_words(text)
    for p in mine[-HISTORY_POSTS:]:
        if overlap(fw, first_words(p.get("text") or "")) >= FIRST_LINE_OVERLAP:
            out.append(("rule8_first_line", f"the first line repeats {int(round(overlap(fw, first_words(p.get('text') or '')) * 100))}% "
                                            f"of an own post's first words ({p.get('ny_date')})"))
            break
    for p in history:
        if p.get("platform") != platform and item.get("dedupe_key") and p.get("dedupe_key") == item["dedupe_key"]:
            same_first = first_words(p.get("text") or "") == fw
            sim = similarity(text, p.get("text") or "")
            if same_first or sim >= TWIN_SIMILARITY:
                out.append(("rule9_cross_platform", f"the {p['platform']} post of this item reads the same "
                                                    f"({'same first line' if same_first else f'{int(sim * 100)}% same words'})"))
                break
    nums = [m.group(0).lstrip("+-\u2212") for m in MONEY_PCT.finditer(_norm(URL.sub(" ", text)))]
    dup = sorted({n for n in nums if nums.count(n) > 1})
    if dup:
        out.append(("rule10_duplicate_number", f"the same number twice: {', '.join(short(d, 16) for d in dup)}"))
    return out


class VarietyState:
    """{"warned": [{date, platform, rule, msg_id}]}: the variety rules already warned today (New York date)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.warned: list[dict] = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8-sig"))
                self.warned = [w for w in data.get("warned") or [] if isinstance(w, dict)]
            except (OSError, ValueError, AttributeError) as e:
                raise StateUnreadable(f"{self.path}: {type(e).__name__}") from None

    def seen(self, day: str, platform: str, rule: str) -> bool:
        return any(w.get("date") == day and w.get("platform") == platform and w.get("rule") == rule for w in self.warned)

    def add(self, day: str, platform: str, rule: str, msg_id) -> None:
        self.warned.append({"date": day, "platform": platform, "rule": rule, "msg_id": msg_id})

    def save(self, today: str) -> None:
        self.warned = [w for w in self.warned if str(w.get("date") or "") >= today]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"warned": self.warned}, indent=1), encoding="utf-8")
        tmp.replace(self.path)


def apply_variety(draft: dict, facts: dict | None, history: list[dict] | None, state: "VarietyState | None",
                  now: dt.datetime) -> tuple[list[str], list[str], list[str]]:
    """(reject reasons, NOTES lines, rules to record as warned once the answer is sent) for a post draft."""
    if history is None or facts is None:
        return [], [], []
    item = next((i for i in facts.get("items") or [] if i.get("item_id") == draft.get("item_id")), None)
    if item is None:
        return [], [], []
    day = (now.astimezone(ss.NY) if ss.NY else now).date().isoformat()
    rejects, notes, record = [], [], []
    for rule, why in variety_breaches(draft, item, history, now):
        if state is not None and state.seen(day, draft.get("platform"), rule):
            rejects.append(f"variety {rule} (a repeat today): {why}")
        else:
            notes.append(f"- VARIETY WARN {rule}: {why} (a second {rule} on {draft.get('platform')} today is rejected)")
            record.append(rule)
    return rejects, notes, record


# ---------------------------------------------------------------------------
# VIRAL CHECK v1 (owner 2026-10-23; tools/viral_check.py): a checkable must-have that fails, or a penalty, is a REJECT;
# unknown rules and fewer than 2 boosters are answer lines only.

def apply_viral(draft: dict, facts: dict | None, kind: str, history: list[dict] | None,
                now: dt.datetime) -> tuple[list[str], list[str], dict | None]:
    """(reject reasons, answer lines, score) for a post or comment draft. A post whose item is not in the facts is
    already rejected by review(): it is not scored (None). Never raises: draft fields are untrusted Grok JSON, and a
    check that fails on one is a "viral-error:" answer line with the verdict left alone (as playbook_notes), so one bad
    row never stops the inbox before it is answered and acked."""
    try:
        if kind == "post" and vc.find_item(facts, draft.get("item_id")) is None:
            return [], [], None
        res = vc.score_draft(draft, facts, kind, history, now)
        return vc.reject_reasons(res), vc.note_lines(res), res
    except Exception as e:  # noqa: BLE001 - the viral check never blocks an answer
        return [], [f"viral-error: VIRAL CHECK failed on this draft ({type(e).__name__}); verdict unchanged"], None


# ---------------------------------------------------------------------------
# Rotation (HQ 2026-10-19 round 7; review round 7b): a post may not reuse a phrasing id or a hook id that one of the
# newest own posts of the same item type on the same platform used (post_history.rotation_window; the ids each post used
# come from its text: post_history.resolve -> claims.used_ids). The window is sized by the choices (post_history.
# rotation_span): a fact with k phrasings blocks a used id for min(ROTATION_POSTS, k - 1) posts (3 phrasings cycle a, b,
# c; a fact is never blocked outright); a hook for min(ROTATION_POSTS, hooks for the type - 1). Only when one post used
# several phrasings of one fact (so none is free) may the least recently used come back. A REJECT, not a note.

def rotation_reasons(draft: dict, item: dict, history: list[dict]) -> list[str]:
    """REJECT reasons for phrasing / hook ids the draft repeats from the rotation window (items with phrasings only;
    review() rejects an item without them)."""
    if not isinstance(item.get(cl.PHRASINGS_KEY), list):
        return []
    platform, kind = draft.get("platform"), item.get("type")
    win = ph.rotation_window(history, kind, platform)
    if not win:
        return []
    text = "\n".join([str(draft.get("text") or ""), str(draft.get("reply_text") or "")])
    pids, hids = cl.used_ids(item, cl.nfkc(text), platform)
    out: list[str] = []
    by_fact: dict[str, list[dict]] = {}
    for p in item[cl.PHRASINGS_KEY]:
        by_fact.setdefault(p.get("fact"), []).append(p)

    def when(post: dict) -> str:
        return str(post.get("ny_date") or str(post.get("created_at") or "")[:10])

    def lru(group: list[str], field: str) -> str:
        last = {g: max((i for i, p in enumerate(win) if g in (p.get(field) or [])), default=-1) for g in group}
        return min(group, key=lambda g: last[g])
    for pid in pids:
        fact = pid.rsplit(".", 1)[0]
        group = list(dict.fromkeys(p["id"] for p in by_fact.get(fact, [])))   # phrasing order (the base first)
        span = ph.rotation_span(len(group))
        hit = ph.used_within(win, pid, span, "phrasing_ids")
        if hit is None:
            continue
        free = [g for g in group if ph.used_within(win, g, span, "phrasing_ids") is None]
        if not free and pid == lru(group, "phrasing_ids"):
            continue
        texts = {p["id"]: p["text"] for p in by_fact.get(fact, [])}
        alt = (f"; use another phrasing of this fact: {short(texts[free[0]], 160)!r}" if free else
               f"; only {lru(group, 'phrasing_ids')} of this fact may come back")
        out.append(f"rotation: phrasing {pid} was used in a {kind} post on {platform} on {when(hit)} (this fact has "
                   f"{len(group)} phrasings, so a used one waits {span} {kind} posts there){alt}")
    # link labels ("Full map:", "Source:") are structure, not wording: they never rotate
    allowed = [h["id"] for h in cl.hooks_for(item, platform) if not cl.pv.HOOK_BY_ID[h["id"]]["text"].endswith(":")]
    hspan = ph.rotation_span(len(allowed))
    for hid in hids:
        if hid not in allowed:
            continue
        hit = ph.used_within(win, hid, hspan, "hook_ids")
        if hit is None:
            continue
        free = [cl.pv.HOOK_BY_ID[h]["text"] for h in allowed if ph.used_within(win, h, hspan, "hook_ids") is None]
        out.append(f"rotation: hook {hid} {cl.pv.HOOK_BY_ID[hid]['text']!r} was used in a {kind} post on {platform} on "
                   f"{when(hit)} (one of the last {hspan} {kind} posts there)"
                   + (f"; unused hooks for it: {', '.join(repr(x) for x in free[:4])}" if free else ""))
    return out


# An exact repeat (review round 7b): the rotation window only reaches the last few posts of a type, so the same text again
# on the same platform within DUPLICATE_DAYS (an own post, or a draft approved and not logged yet) is rejected outright.
DUPLICATE_DAYS = 7
_DUP_TOKEN = re.compile(r"[\w$%+\-\u2212.,]+")


def _dup_tokens(s) -> str:
    return " ".join(_DUP_TOKEN.findall(cl.nfkc(str(s or "")).lower()))


def duplicate_reasons(draft: dict, history: list[dict], now: dt.datetime) -> list[str]:
    """REJECT reasons when the draft's text was already posted (or approved) on its platform within DUPLICATE_DAYS."""
    t = _dup_tokens(draft.get("text"))
    platform = draft.get("platform")
    if not t:
        return []
    cut = now - dt.timedelta(days=DUPLICATE_DAYS)
    for p in reversed(history or []):
        ts = _ts(p.get("created_at"))
        if p.get("platform") != platform or (ts is not None and ts < cut):
            continue
        if t in _dup_tokens(p.get("text")):
            what = "approved (not posted yet)" if p.get("pending") else "posted"
            return [f"duplicate: this text was already {what} on {platform} on "
                    f"{p.get('ny_date') or str(p.get('created_at') or '')[:10]}; write a new post (another hook and "
                    "phrasing)"]
    return []


def pv_rotation() -> int:
    return cl.pv.ROTATION_POSTS


def history_from_rest(rest, instinct, env: str, facts_base: str, days: int = 8) -> list[dict]:
    """Our own posts of the last `days` days through the inbox's gateway client, resolved against facts_base."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    rows = rest.get_all(instinct.q("select=id,created_at,platform,item_id,url,body", f"env=eq.{env}",
                                   "direction=eq.from_instinct", "kind=eq.post_log",
                                   f"created_at=gte.{instinct.iso(since)}", "order=created_at.asc,id.asc"))
    cache: dict[str, dict | None] = {}

    def get(date: str):
        if date not in cache:
            try:
                cache[date] = load_facts(facts_location(facts_base, date))
            except FactsUnavailable:
                cache[date] = None
        return cache[date]
    return ph.resolve(ph.own_posts(rows), get)


def variety_state_path(flag: str | None = None) -> Path:
    import os
    return Path(flag or os.environ.get(VARIETY_STATE_ENV) or DEFAULT_VARIETY_STATE)


# Approved, not yet logged (review round 7b, HQ 2026-10-19): the rotation window and the variety lint read our own posts
# from the post_log, which Grok writes only after it posts. A post draft approved earlier in the same inbox run, or in an
# earlier run whose post_log row has not arrived yet, counts as a post at once: run_inbox adds every APPROVE to its
# working history, and a sent APPROVE goes into this ledger until a post_log row of the same item on the same platform
# (created at or after the approval) appears, or LEDGER_HOURS pass.
DEFAULT_APPROVED_LEDGER = Path("D:/rtv-ops/tracks/growth/research/grok-approved-ledger.json")
APPROVED_LEDGER_ENV = "GROK_APPROVED_LEDGER"
LEDGER_HOURS = 24


def _ts(s) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def ledger_entry(draft: dict, msg_id, now: dt.datetime) -> dict:
    out = {"msg_id": msg_id, "at": now.astimezone(dt.timezone.utc).isoformat(), "platform": draft.get("platform"),
           "item_id": draft.get("item_id"),
           "text": "\n".join([str(draft.get("text") or ""), str(draft.get("reply_text") or "")])}
    try:   # untrusted draft field: a time it cannot read (or out of range) is simply not kept
        planned = vc.as_time(draft.get("planned_at")) if isinstance(draft.get("planned_at"), str) else None
    except Exception:  # noqa: BLE001
        planned = None
    if planned is not None:   # VIRAL CHECK M6: an approved post with a planned time counts in the 60 min spacing
        out["planned_at"] = planned.isoformat()
    return out


class ApprovedLedger:
    """{"approved": [{msg_id, at, platform, item_id, text}]}: post drafts approved (answer sent) and not logged yet."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: list[dict] = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8-sig"))
                rows = data.get("approved")
            except (OSError, ValueError, AttributeError) as e:
                raise StateUnreadable(f"{self.path}: {type(e).__name__}") from None
            if not isinstance(rows, list):
                raise StateUnreadable(f"{self.path}: expected {{\"approved\": [...]}}")
            self.entries = [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def logged(entry: dict, history: list[dict]) -> bool:
        at = _ts(entry.get("at"))
        for p in history:
            if p.get("pending"):
                continue
            if p.get("platform") == entry.get("platform") and p.get("item_id") == entry.get("item_id"):
                t = _ts(p.get("created_at"))
                if at is None or (t is not None and t >= at):
                    return True
        return False

    def pending(self, history: list[dict], now: dt.datetime) -> list[dict]:
        """The entries still waiting for their post_log row (newer than LEDGER_HOURS), oldest first."""
        cut = now - dt.timedelta(hours=LEDGER_HOURS)
        return [e for e in self.entries if (_ts(e.get("at")) or cut) > cut and not self.logged(e, history)]

    def save(self, history: list[dict], now: dt.datetime) -> None:
        self.entries = self.pending(history, now)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"approved": self.entries}, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


def pending_records(entries: list[dict], facts_for_date) -> list[dict]:
    """Ledger entries (or approvals of this run) as resolved own posts (post_history.resolve), marked pending."""
    posts = [{"platform": e.get("platform"), "url": "", "created_at": e.get("at"), "item_id": e.get("item_id"),
              "body": e.get("text") or ""} for e in entries]
    out = ph.resolve(posts, facts_for_date)
    for r, e in zip(out, entries):
        r["pending"] = True
        r["msg_id"] = e.get("msg_id")
        if e.get("planned_at"):
            r["planned_at"] = e["planned_at"]
    return out


def with_pending(history: list[dict], records: list[dict]) -> list[dict]:
    """history + pending records, oldest first (the rotation window reads the newest posts)."""
    floor = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    return sorted([*history, *records], key=lambda p: _ts(p.get("created_at")) or floor)


def approved_ledger_path(flag: str | None = None) -> Path:
    import os
    return Path(flag or os.environ.get(APPROVED_LEDGER_ENV) or DEFAULT_APPROVED_LEDGER)


# ---------------------------------------------------------------------------
# Inbox

def load_instinct(path: Path):
    spec = importlib.util.spec_from_file_location("instinct", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_draft(row: dict) -> tuple[dict | None, str | None]:
    body = str(row.get("body") or "")
    rest = DRAFT_HEAD.sub("", body, count=1).strip().lstrip(":").strip()
    rest = re.sub(r"^```(?:json)?\s*|\s*```$", "", rest)
    try:
        d = json.loads(rest)
    except ValueError:
        return None, ('the body must be "DRAFT" followed by one JSON object: a post {item_id, platform, text, reply_text, '
                      'link, media_url} or a comment {kind: comment, platform, target_url, text, item_id?}')
    if not isinstance(d, dict):
        return None, "the draft must be a JSON object"
    for k in ("item_id", "platform"):
        col = row.get(k)
        if col and d.get(k) and str(col) != str(d[k]):
            return None, f"{k} in the body and on the message differ"
        if not d.get(k) and col:
            d[k] = col
    return d, None


def playbook_notes(draft: dict, facts: dict | None, now: dt.datetime | None = None) -> list[str]:
    """draft_lint's answer lines for a post draft (advisory; never part of the verdict). A lint crash is shown, not
    hidden."""
    try:
        return dl.answer_lines(dl.lint(draft, facts, None, now))
    except Exception as e:  # noqa: BLE001 - the lint must never block a review; its failure is reported in the answer
        return [f"NOTES (playbook v2): lint failed ({type(e).__name__})"]


def reply_line(row: dict, draft: dict | None, verdict: str, reasons: list[str], notes: list[str] | None = None) -> str:
    iid = (draft or {}).get("item_id") or row.get("item_id") or ""
    if not (isinstance(iid, str) and ITEM_ID.match(iid)):
        iid = "comment" if (draft or {}).get("kind") == "comment" else "(no valid item_id)"
    head = f"{verdict} {int(row['id'])} {iid}"
    if verdict != "APPROVE":
        head = f"{head}: " + "; ".join(reasons)
    return "\n".join([head, *(notes or [])])[:REPLY_MAX]


def send_reply(instinct_path: Path, env: str, env_file: str | None, platform: str | None, body: str) -> bool:
    cmd = [PYTHON, str(instinct_path), "--env", env]
    if env_file:
        cmd += ["--env-file", env_file]
    cmd += ["say", "--kind", "answer"]
    if platform in PLATFORMS:
        cmd += ["--platform", platform]
    cmd += ["--body", "-"]
    r = subprocess.run(cmd, input=body, text=True, encoding="utf-8", capture_output=True)
    print(f"  say: exit {r.returncode} {(r.stdout or r.stderr).strip()[:300]}")
    return r.returncode == 0


def comment_state_path(flag: str | None = None) -> Path:
    """--comment-state, else $GROK_COMMENT_STATE, else DEFAULT_COMMENT_STATE."""
    import os
    return Path(flag or os.environ.get(COMMENT_STATE_ENV) or DEFAULT_COMMENT_STATE)


def draft_kind(draft: dict) -> tuple[str | None, str | None]:
    """("post" | "comment", None) or (None, error). A draft without "kind" is a post."""
    kind = draft.get("kind")
    if kind in (None, "", "post"):
        return "post", None
    if kind == "comment":
        return "comment", None
    return None, f"kind must be post or comment (got {short(kind)!r})"


def run_inbox(rest, instinct, env: str, facts_base: str, dry_run: bool, send, limit: int = 200,
              comment_state: Path | None = None, now: dt.datetime | None = None, history=None,
              variety_state: Path | None = None, need_history: bool = False, variety: bool = True,
              approved_ledger: Path | None = None, viral: bool = False) -> dict:
    """Review every unacked DRAFT row; `send(platform, body) -> bool` answers one. Returns counts. An approved comment
    is written to the comment state only once its APPROVE answer was sent (a dry run keeps it in memory only). An
    approved post joins the working history at once (rotation, variety) and, once its answer was sent, the approved
    ledger (approved_ledger) until its post_log row arrives (review round 7b). viral=True (the CLI's default) adds the
    VIRAL CHECK v1 gate to posts and comments (apply_viral)."""
    rows = rest.call("GET", instinct.q("select=id,created_at,kind,platform,item_id,body", f"env=eq.{env}",
                                       "direction=eq.from_instinct", "acked_at=is.null", "order=created_at.asc,id.asc",
                                       f"limit={min(limit, instinct.PAGE_ROWS)}")) or []
    drafts = [r for r in rows if DRAFT_HEAD.match(str(r.get("body") or ""))]
    stats = {"unacked": len(rows), "drafts": len(drafts), "approved": 0, "rejected": 0, "answered": 0, "acked": 0, "deferred": 0}
    print(f"inbox ({env}): {len(rows)} unacked from_instinct rows, {len(drafts)} DRAFT"
          + (" (dry run: nothing sent or acked)" if dry_run else ""))
    cache: dict[str, dict | None] = {}
    state: CommentState | None = None
    vstate: VarietyState | None = None
    if history is not None and variety_state is not None and variety:
        try:
            vstate = VarietyState(variety_state)
        except StateUnreadable as e:
            print(f"  variety state unreadable ({e}); variety rules warn only this run")
    def facts_for(date: str):
        if date not in cache:
            try:
                cache[date] = load_facts(facts_location(facts_base, date))
            except FactsUnavailable:
                return None   # not cached: a draft of that date still defers on its own load
        return cache[date]
    ledger: ApprovedLedger | None = None
    work = None   # the working history: own posts + approved, not yet logged (ledger) + approved in this run
    if history is not None:
        work = list(history)
        if approved_ledger is not None:
            try:
                ledger = ApprovedLedger(approved_ledger)
                pend = ledger.pending(history, now or dt.datetime.now(dt.timezone.utc))
                if pend:
                    work = with_pending(work, pending_records(pend, facts_for))
                    print(f"  approved, not yet in the post log: {len(pend)} post(s) count in the rotation window")
            except StateUnreadable as e:
                print(f"  approved ledger unreadable ({e}); post drafts are left for the next run (rotation rule)")
                work = None
    for row in drafts:
        record: list[str] = []
        draft, err = parse_draft(row)
        kind = None
        if not err:
            kind, err = draft_kind(draft)
        verdict, reasons = ("REJECT", [err]) if err else ("", [])
        notes: list[str] = []
        if not err:
            clock = now or dt.datetime.now(dt.timezone.utc)
            iid = draft.get("item_id")
            date = str(iid or "")[:10]
            facts = None
            if (kind == "post" or iid) and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                verdict, reasons = "REJECT", ["item_id must start with the facts date (YYYY-MM-DD)"]
            else:
                if kind == "post" or iid:
                    if date not in cache:
                        try:
                            cache[date] = load_facts(facts_location(facts_base, date))
                        except FactsUnavailable as e:
                            print(f"  #{row['id']}: facts unavailable ({e}); left unacked for the next run")
                            stats["deferred"] += 1
                            continue
                    facts = cache[date]
                if kind == "post" and work is None and need_history:
                    # the rotation rule reads our own posts: a post draft is not answered without them (No Fallbacks)
                    print(f"  #{row['id']}: post history unreadable; left unacked for the next run (rotation rule)")
                    stats["deferred"] += 1
                    continue
                if kind == "post":
                    verdict, reasons = review(draft, facts, clock)
                    notes = playbook_notes(draft, facts, clock)
                    item = next((i for i in (facts or {}).get("items") or [] if i.get("item_id") == iid), None)
                    if work is not None and item is not None:
                        rrej = duplicate_reasons(draft, work, clock) + rotation_reasons(draft, item, work)
                        if rrej:
                            verdict, reasons = "REJECT", reasons + rrej
                    if variety:
                        vrej, vnotes, record = apply_variety(draft, facts, work, vstate, clock)
                        if vrej:
                            verdict, reasons = "REJECT", reasons + vrej
                        notes += vnotes
                    if viral:
                        xrej, xnotes, _ = apply_viral(draft, facts, "post", work, clock)
                        if xrej:
                            verdict, reasons = "REJECT", reasons + xrej
                        notes = xnotes + notes
                else:
                    if state is None:
                        try:
                            state = CommentState(comment_state or comment_state_path())
                        except StateUnreadable as e:
                            print(f"  #{row['id']}: comment state unreadable ({e}); left unacked for the next run")
                            stats["deferred"] += 1
                            continue
                    verdict, reasons = review_comment(draft, facts, state, clock)
                    if viral:
                        xrej, xnotes, _ = apply_viral(draft, facts, "comment", None, clock)
                        if xrej:
                            verdict, reasons = "REJECT", reasons + xrej
                        notes = xnotes + notes
        body = reply_line(row, draft, verdict, reasons, notes)
        stats["approved" if verdict == "APPROVE" else "rejected"] += 1
        platform = (draft or {}).get("platform") or row.get("platform")
        print(f"  #{row['id']} -> {body}")
        approved_comment = verdict == "APPROVE" and kind == "comment"
        approved_post = verdict == "APPROVE" and kind == "post" and work is not None
        if dry_run:
            if approved_comment:
                state.add(draft, int(row["id"]), clock)
            if approved_post:   # in memory only: the next drafts of this run rotate against it
                work = with_pending(work, pending_records([ledger_entry(draft, int(row["id"]), clock)], facts_for))
            continue
        if not send(platform if platform in PLATFORMS else None, body):
            print(f"  #{row['id']}: the answer was not sent; left unacked")
            continue
        stats["answered"] += 1
        if approved_post:
            entry = ledger_entry(draft, int(row["id"]), clock)
            work = with_pending(work, pending_records([entry], facts_for))
            if ledger is not None:
                ledger.entries.append(entry)
                ledger.save(history, clock)
        if approved_comment:
            state.add(draft, int(row["id"]), clock)
            state.save(clock)
        if verdict == "APPROVE" and record and vstate is not None:
            day = (clock.astimezone(ss.NY) if ss.NY else clock).date().isoformat()
            for rule in record:
                vstate.add(day, draft.get("platform"), rule, int(row["id"]))
            vstate.save(day)
        stamp = dt.datetime.now(dt.timezone.utc).isoformat()
        out = rest.call("PATCH", instinct.q(f"id=eq.{int(row['id'])}", f"env=eq.{env}", "direction=eq.from_instinct",
                                            "acked_at=is.null", "select=id"), {"acked_at": stamp}, prefer="return=representation")
        stats["acked"] += len(out or [])
    print("done: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    return stats


# ---------------------------------------------------------------------------
# CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--draft", help="a draft JSON file")
    mode.add_argument("--inbox", action="store_true")
    ap.add_argument("--facts", help="facts.json file or URL (--draft mode; default: from --facts-base and the item date)")
    ap.add_argument("--facts-base", default=DEFAULT_FACTS_BASE, help="Pages v/ URL (default) or a local v/ directory")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--env", choices=["prod", "dev"], default="prod")
    ap.add_argument("--env-file", help="instinct.py --env-file (default: instinct.py's own)")
    ap.add_argument("--instinct", default=str(DEFAULT_INSTINCT))
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--comment-state", help=f"approved-comments state JSON (default: ${COMMENT_STATE_ENV}, else "
                                            f"{DEFAULT_COMMENT_STATE})")
    ap.add_argument("--variety-state", help=f"variety warnings state JSON (default: ${VARIETY_STATE_ENV}, else "
                                            f"{DEFAULT_VARIETY_STATE})")
    ap.add_argument("--approved-ledger", help=f"approved, not yet logged post drafts JSON (default: ${APPROVED_LEDGER_ENV}, "
                                              f"else {DEFAULT_APPROVED_LEDGER})")
    ap.add_argument("--history", action="store_true", help="--draft: read our own posts for the variety lint (read only)")
    ap.add_argument("--no-variety", action="store_true", help="--inbox: skip the variety lint (the rotation rule still runs)")
    ap.add_argument("--no-viral", action="store_true", help="skip the VIRAL CHECK v1 gate (tools/viral_check.py)")
    ap.add_argument("--viral-gate", action="store_true",
                    help="--draft: the VIRAL CHECK reasons change the verdict as in --inbox (default: printed only)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.draft:
        draft = json.loads(Path(a.draft).read_text(encoding="utf-8-sig"))
        kind, err = draft_kind(draft)
        if err:
            print(json.dumps({"verdict": "REJECT", "item_id": draft.get("item_id"), "reasons": [err]}, indent=2))
            return 1
        facts = None
        if kind == "post" or draft.get("item_id"):
            where = a.facts or facts_location(a.facts_base, str(draft.get("item_id") or "")[:10])
            try:
                facts = load_facts(where)
            except FactsUnavailable as e:
                print(f"facts unavailable: {e}")
                return 2
        notes: list[str] = []
        hist = None
        if kind == "post":
            verdict, reasons = review(draft, facts)
            notes = playbook_notes(draft, facts)
            if a.history:
                ins = load_instinct(Path(a.instinct))
                env_file = Path(a.env_file) if a.env_file else ins.DEFAULT_ENV_FILE
                hist = history_from_rest(ins.Rest(*ins.load_config(env_file)), ins, a.env, a.facts_base)
                try:   # approved, not yet logged posts count too (read only)
                    led = ApprovedLedger(approved_ledger_path(a.approved_ledger))
                except StateUnreadable as e:
                    print(f"approved ledger unreadable: {e}")
                    return 2
                pend = led.pending(hist, dt.datetime.now(dt.timezone.utc))
                if pend:
                    day = str(draft.get("item_id"))[:10]
                    def other(d: str):
                        try:
                            return facts if d == day else load_facts(facts_location(a.facts_base, d))
                        except FactsUnavailable:
                            return None
                    hist = with_pending(hist, pending_records(pend, other))
                try:
                    vs = VarietyState(variety_state_path(a.variety_state))
                except StateUnreadable:
                    vs = None
                vrej, vnotes, _ = apply_variety(draft, facts, hist, vs, dt.datetime.now(dt.timezone.utc))
                item = next((i for i in (facts or {}).get("items") or [] if i.get("item_id") == draft.get("item_id")), None)
                rrej = duplicate_reasons(draft, hist, dt.datetime.now(dt.timezone.utc)) + (
                    rotation_reasons(draft, item, hist) if item is not None else [])
                if vrej or rrej:
                    verdict, reasons = "REJECT", reasons + rrej + vrej
                notes += vnotes
            else:
                notes.append("rotation (phrasing / hook ids of the last 5 posts) not checked: run with --history")
        else:
            try:
                state = CommentState(comment_state_path(a.comment_state))
            except StateUnreadable as e:
                print(f"comment state unreadable: {e}")
                return 2
            verdict, reasons = review_comment(draft, facts, state)  # --draft reads the state, never writes it
        vres, xrej = None, []
        if not a.no_viral:   # M6 reads our own posts only with --history (else unknown)
            xrej, xnotes, vres = apply_viral(draft, facts, kind, hist, dt.datetime.now(dt.timezone.utc))
            if xrej and a.viral_gate:
                verdict, reasons = "REJECT", reasons + xrej
            notes = notes + xnotes
        out = {"verdict": verdict, "item_id": draft.get("item_id"), "reasons": reasons}
        if kind == "post" or notes:
            out["notes"] = notes
        if vres is not None:
            out["viral"] = vres
            out["viral_reasons"] = xrej   # what the inbox REJECTs on; part of the verdict only with --viral-gate
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if verdict == "APPROVE" else 1
    instinct = load_instinct(Path(a.instinct))
    env_file = Path(a.env_file) if a.env_file else instinct.DEFAULT_ENV_FILE
    rest = instinct.Rest(*instinct.load_config(env_file))
    history = None
    try:
        history = history_from_rest(rest, instinct, a.env, a.facts_base)
    except SystemExit as e:  # instinct's client exits on a gateway error: post drafts wait (rotation), never guessed
        print(f"post history unreadable ({str(e)[:120]}): post drafts are left for the next run; comments go on")
    run_inbox(rest, instinct, a.env, a.facts_base, a.dry_run,
              lambda platform, body: send_reply(Path(a.instinct), a.env, a.env_file, platform, body), a.limit,
              comment_state_path(a.comment_state), history=history, variety_state=variety_state_path(a.variety_state),
              need_history=True, variety=not a.no_variety, approved_ledger=approved_ledger_path(a.approved_ledger),
              viral=not a.no_viral)
    return 0


if __name__ == "__main__":
    sys.exit(main())
