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
    moves_like: the subject and the peers listed in the item); several cashtags only for the roundup kinds
    (facts.ROUNDUP_TYPES): earnings_tomorrow_roundup and ptr_summary at most 4, earnings_week_calendar at most 12
    (facts.cashtag_max), each one of the item's tickers, at least one;
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
  - G-N1 holdout: until 2026-11-21 (New York date of the review, as facts.py and select_stories date things) no
    string anywhere in the draft (every field, nested ones and keys included) carries "/earnings/reports/" (an
    earnings report page of either arm); comments likewise;
  - media_url (every own post carries native media, owner 2026-10-12): one of the item's media[].url, a file under
    <Pages>/v/<YYYY-MM-DD>/ (our rendered stills / Reels), or "grok_generated" with a media_note that names no
    digit, $, %, logo, face or real name (the item's person / company / peers). earnings_week_calendar: only one of
    the item's own media urls (our calendar image; no Grok-made image, no other Pages file); on Instagram only an
    item media entry of kind "reel" (none in v1, so the calendar is an X post).

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
import draft_lint as dl  # noqa: E402
import facts as fx  # noqa: E402
import manifest as mf  # noqa: E402
import select_stories as ss  # noqa: E402

DEFAULT_FACTS_BASE = f"{mf.PAGES_BASE}/v"
DEFAULT_INSTINCT = Path("D:/rtv-ops/tracks/growth/bin/instinct.py")
PYTHON = sys.executable
UA = "RapidTradeView grok-review (contact@rapidtradeview.trade)"
SOURCE_TYPES = ("congress_trade", "form4_buy", "ptr_summary")
# Several cashtags in one post: only the roundup kinds (facts.ROUNDUP_TYPES, at most facts.cashtag_max(kind): 4, the
# weekly calendar 12; all from the item's tickers). moves_like (subject + listed peers) and picks_ready (the public picks)
# keep their item's own list.
MULTI_CASHTAG_TYPES = fx.ROUNDUP_TYPES
MULTI_CASHTAG_MAX = fx.ROUNDUP_MAX_TICKERS
# Kinds whose post carries only the item's own media (our rendered image; no Grok-made image, no other Pages file), and on
# Instagram only an item media entry of kind "reel".
OWN_MEDIA_ONLY_TYPES = ("earnings_week_calendar",)
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
PLATFORMS = ("x", "instagram")
REPLY_MAX = 3500

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
        reasons.append(f"platform must be x or instagram (got {short(platform)!r})")
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
    rules = facts.get("rules") or {}
    both = f"{text}\n{reply}"

    # Ticker
    tickers = [t.upper() for t in (item.get("tickers") or ([item["ticker"]] if item.get("ticker") else []))]
    tags = [m.group(1).upper() for m in CASHTAG.finditer(both)]
    other = sorted({t for t in tags if t not in tickers})
    if other:
        reasons.append(f"cashtag not in this item: {', '.join('$' + short(t, 8) for t in other)}")
    distinct = set(tags)
    kind = item.get("type")
    if kind in MULTI_CASHTAG_TYPES:
        most = fx.cashtag_max(kind)
        if len(distinct) > most:
            reasons.append(f"{kind}: at most {most} cashtags (got {len(distinct)})")
        if not distinct & set(tickers):
            reasons.append(f"{kind}: the text must name at least one of the item's tickers")
    elif kind not in LIST_TYPES and len(distinct) > 1:
        reasons.append(f"one cashtag per post: several only for {' / '.join(MULTI_CASHTAG_TYPES)} (got {len(distinct)})")
    if item.get("ticker") and f"${item['ticker'].upper()}" not in {f"${m.group(1).upper()}" for m in CASHTAG.finditer(text)}:
        reasons.append(f"the text must name ${item['ticker']}")

    # Numbers
    allowed = [str(a) for a in item.get("allowed_numbers") or []]
    bad = unexplained_numbers(both, allowed, tickers)
    if bad:
        reasons.append("numbers not in allowed_numbers: " + ", ".join(sorted({short(b, 24) for b in bad})))

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
    for u in URL.findall(both):
        u = u.rstrip(".,;:!?)]}")
        if u != want and u not in srcs:
            reasons.append(f"URL not from this item: {short(u, 80)}")
    if item.get("type") == "ptr_summary" and not srcs:
        reasons.append("ptr_summary: the item has no official source URL to cite")
    if platform == "x":
        if want and want not in reply:
            reasons.append("X: the page link goes in the self-reply (reply_text)")
        if item.get("type") in SOURCE_TYPES and srcs and not any(u in reply for u in srcs):
            reasons.append("X: the official source link goes in the self-reply (reply_text)")
    elif platform == "instagram" and item.get("type") in SOURCE_TYPES and srcs and not any(u in both for u in srcs):
        reasons.append("Instagram: the caption must carry the official source link")

    # Media
    reasons += media_reasons(draft, item)

    # Length
    if platform == "x":
        limit = int((rules.get("max_len") or {}).get("x") or 270)
        for name, body in (("text", text), ("reply_text", reply)):
            n = mf.x_weighted_length(body)
            if n > limit:
                reasons.append(f"X {name} is {n} characters (limit {limit})")

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
    kind = item.get("type")
    if kind in OWN_MEDIA_ONLY_TYPES:
        if draft.get("platform") == "instagram":
            reels = [m.get("url") for m in item.get("media") or []
                     if isinstance(m, dict) and m.get("url") and m.get("kind") == "reel"]
            if not reels:
                return [f"{kind}: Instagram only with the item's own Reel, and its media has none (post it on X)"]
            if media not in reels:
                return [f"{kind}: on Instagram media_url must be the item's Reel ({short(reels[0], 100)})"]
            return []
        if not ours:
            return [f"{kind}: the item has no media yet (its calendar image is not live): nothing to post"]
        if media not in ours:
            return [f"{kind}: media_url must be the item's own image ({short(ours[0], 100)}); no Grok-made image or "
                    "other file"]
        return []
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
    if platform not in PLATFORMS:
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

    # Links, hashtags, mentions
    if URL.search(text) or BARE_DOMAIN.search(text):
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
    elif cashtags or has_number:
        reasons.append("a comment with numbers or a $cashtag needs the item_id of the facts it uses")
    if item is not None:
        tickers = [t.upper() for t in (item.get("tickers") or ([item["ticker"]] if item.get("ticker") else []))]
        other = sorted({t for t in cashtags if t not in tickers})
        if other:
            reasons.append(f"cashtag not in this item: {', '.join('$' + short(t, 8) for t in other)}")
        bad = unexplained_numbers(scan, [str(a) for a in item.get("allowed_numbers") or []], tickers)
        if bad:
            reasons.append("numbers not in allowed_numbers: " + ", ".join(sorted({short(b, 24) for b in bad})))
        if item.get("type") in NO_PICK_HINT_TYPES:
            hint = PICK_HINT.search(text)
            if hint:
                reasons.append(f"picks: no #1 / top-pick hint ({short(hint.group(0))!r})")

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
              comment_state: Path | None = None, now: dt.datetime | None = None) -> dict:
    """Review every unacked DRAFT row; `send(platform, body) -> bool` answers one. Returns counts. An approved comment
    is written to the comment state only once its APPROVE answer was sent (a dry run keeps it in memory only)."""
    rows = rest.call("GET", instinct.q("select=id,created_at,kind,platform,item_id,body", f"env=eq.{env}",
                                       "direction=eq.from_instinct", "acked_at=is.null", "order=created_at.asc,id.asc",
                                       f"limit={min(limit, instinct.PAGE_ROWS)}")) or []
    drafts = [r for r in rows if DRAFT_HEAD.match(str(r.get("body") or ""))]
    stats = {"unacked": len(rows), "drafts": len(drafts), "approved": 0, "rejected": 0, "answered": 0, "acked": 0, "deferred": 0}
    print(f"inbox ({env}): {len(rows)} unacked from_instinct rows, {len(drafts)} DRAFT"
          + (" (dry run: nothing sent or acked)" if dry_run else ""))
    cache: dict[str, dict | None] = {}
    state: CommentState | None = None
    for row in drafts:
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
                if kind == "post":
                    verdict, reasons = review(draft, facts, clock)
                    notes = playbook_notes(draft, facts, clock)
                else:
                    if state is None:
                        try:
                            state = CommentState(comment_state or comment_state_path())
                        except StateUnreadable as e:
                            print(f"  #{row['id']}: comment state unreadable ({e}); left unacked for the next run")
                            stats["deferred"] += 1
                            continue
                    verdict, reasons = review_comment(draft, facts, state, clock)
        body = reply_line(row, draft, verdict, reasons, notes)
        stats["approved" if verdict == "APPROVE" else "rejected"] += 1
        platform = (draft or {}).get("platform") or row.get("platform")
        print(f"  #{row['id']} -> {body}")
        approved_comment = verdict == "APPROVE" and kind == "comment"
        if dry_run:
            if approved_comment:
                state.add(draft, int(row["id"]), clock)
            continue
        if not send(platform if platform in PLATFORMS else None, body):
            print(f"  #{row['id']}: the answer was not sent; left unacked")
            continue
        stats["answered"] += 1
        if approved_comment:
            state.add(draft, int(row["id"]), clock)
            state.save(clock)
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
        if kind == "post":
            verdict, reasons = review(draft, facts)
            notes = playbook_notes(draft, facts)
        else:
            try:
                state = CommentState(comment_state_path(a.comment_state))
            except StateUnreadable as e:
                print(f"comment state unreadable: {e}")
                return 2
            verdict, reasons = review_comment(draft, facts, state)  # --draft reads the state, never writes it
        out = {"verdict": verdict, "item_id": draft.get("item_id"), "reasons": reasons}
        if kind == "post":
            out["notes"] = notes
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if verdict == "APPROVE" else 1
    instinct = load_instinct(Path(a.instinct))
    env_file = Path(a.env_file) if a.env_file else instinct.DEFAULT_ENV_FILE
    rest = instinct.Rest(*instinct.load_config(env_file))
    run_inbox(rest, instinct, a.env, a.facts_base, a.dry_run,
              lambda platform, body: send_reply(Path(a.instinct), a.env, a.env_file, platform, body), a.limit,
              comment_state_path(a.comment_state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
