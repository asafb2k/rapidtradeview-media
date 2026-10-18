"""Content checks every post and every facts text pass (HQ 2026-10-18 review fixes; social-content-2026-10-18 PLAN §4).

Shared by facts.py (a build-time self-check of each item's own facts_text and angles), grok_review.py (the validator) and,
through grok_review.wording_reasons, the Growth post audit. Pure functions, no I/O.

1. Universe wording (owner rule): our universe is "the 500 largest US-listed stocks", never "S&P 500". No post of any item
   type names the S&P (S&P 500, S&P500, SP500, SPX, "the index"). The one exception is the track record's benchmark
   comparison on a picks item, written as "vs the S&P 500 (SPY)" / "vs SPY (S&P 500)" ("vs SPY" alone needs no exception).
2. Comparative / superlative claims (led, biggest, largest, worst, best, most, least, only, first, top, record and their
   synonyms) are allowed only when the item backs them in its `claims` field, computed by facts.py / market_facts.py:
     {"words": [categories], "subjects": [tickers / canonical sector names], "bare": bool, "direction": "up"|"down"|None,
      "needs": regex or None, "says": what is true}
   A clause (sentence, or a part split at ";", ", while", ", but", ", and") that carries a superlative passes only when
     - every superlative category in it is backed by a claim whose subjects include a ticker / sector named in the clause
       (or, when the clause names none, a claim marked bare);
     - every ticker / sector named in it is a subject of a claim backing one of its superlatives;
     - the claim's direction (when set) agrees with the clause's direction words, and its `needs` pattern (when set)
       occurs in the clause.
   Definitions are not claims: "the 500 largest", "the 10 largest", "largest US-listed", "first session after",
   "best minus worst", "at least" / "at most", "first quarter".
3. Sector attribution: a clause naming one sector and listing cashtags (or followed by a clause that starts with a
   cashtag and names no sector) implies those companies are in that sector; a cashtag labelled with a sector in
   parentheses likewise. Each must match the item's ticker_sectors ($GOOGL is Communication Services, not Technology).
4. Scoped numbers: an item may require words next to some of its numbers (`scoped_numbers`: the 30-day insider totals are
   "open-market" buys / sells "by officers and directors").
5. Card message (`card_message`): words a post may not use because its attached card says the opposite (breadth: a card
   headlining a broad decline never goes with "narrow", "concentrated", "the typical stock was flat").
"""
from __future__ import annotations

import re

import market_facts as mk

# ---------------------------------------------------------------------------
# 1. Universe wording

INDEX_WORDS = re.compile(
    r"\bs\s*(?:&|&amp;|＆|and)\s*p(?:\s*-?\s*500)?(?![a-z])|\bsp\s*-?\s*500\b|\bspx\b|\bthe\s+index\b", re.IGNORECASE)
SPY_COMPARE = re.compile(
    r"\b(?:vs\.?|versus|against|than)\s+(?:the\s+)?(?:s\s*&\s*p\s*500(?:\s+etf)?\s*\(\s*\$?spy\s*\)"
    r"|\$?spy\s*\(\s*(?:the\s+)?s\s*&\s*p\s*500(?:\s+etf)?\s*\))", re.IGNORECASE)
SPY_TYPES = ("picks_ready",)  # the only item that carries the track record's benchmark comparison
UNIVERSE_WORDS = mk.UNIVERSE_WORDS


def spy_blank(kind: str | None, text: str) -> str:
    """The text with the allowed track-record benchmark phrase blanked (picks items only)."""
    return SPY_COMPARE.sub(" ", text) if kind in SPY_TYPES else text


US_COMPANIES = re.compile(r"\blargest\s+(?:U\.?S\.?|American)\s+(?:companies|stocks|names|firms)\b", re.IGNORECASE)


def index_reasons(kind: str | None, text: str, names: list[str] | None = None) -> list[str]:
    """names: company names of the item ("S&P Global Inc." is a company, not the index)."""
    out = []
    m = INDEX_WORDS.search(_blank_names(spy_blank(kind, text), names or []))
    if m:
        out.append(f"universe wording: never call our universe the S&P ({m.group(0).strip()!r}); say \"{UNIVERSE_WORDS}\" "
                   "(only a picks post may compare with the benchmark, as \"vs SPY\")")
    u = US_COMPANIES.search(text)
    if u:
        out.append(f"universe wording: {u.group(0)!r} - the largest companies listed here include foreign ones (TSM): "
                   "say \"largest US-listed\"")
    return out


WEEK_WORDS = re.compile(r"\b(?:this|last|past)\s+week\b", re.IGNORECASE)


def window_reasons(item: dict, text: str) -> list[str]:
    """A 5-session / week item worded for the build date (its `when`): no "this week" on the weekend after the week, no
    "last week" for the current one."""
    when = str(item.get("when") or "")
    if "week" not in when:
        return []
    ok = {when.lower()} | ({"past week"} if when.lower() != "this week" else set())
    bad = [m.group(0) for m in WEEK_WORDS.finditer(text) if m.group(0).lower() not in ok]
    return [f"window: the item's window is \"{when}\", not {bad[0]!r}"] if bad else []


# ---------------------------------------------------------------------------
# 2. Superlatives

CATEGORIES = (
    ("led", r"led|leads?|leading|leaders?"),
    ("biggest", r"biggest|largest|heaviest|greatest"),
    ("worst", r"worst|weakest|lowest"),
    ("best", r"best|strongest|highest"),
    ("most", r"most(?:-[a-z]+)?"),
    ("least", r"least|smallest|fewest"),
    ("only", r"only|sole|lone"),
    ("first", r"first"),
    ("top", r"top"),
    ("record", r"records?|record-[a-z]+|all-time"),
)
SUPER = re.compile(r"(?<![\w$-])(?:" + "|".join(f"(?P<{n}>{p})" for n, p in CATEGORIES) + r")(?![\w])", re.IGNORECASE)
EXEMPT = re.compile(
    r"\b\d{1,3}(?:,\d{3})?[\s-]+largest\b"            # the 500 largest / the 10 largest / 500-largest: a universe
    r"|\blargest\s+US-listed\b"
    r"|\bfirst\s+(?:full\s+)?(?:trading\s+)?(?:session|day)\s+after\b"
    r"|\bbest\s+minus\s+worst\b|\bbest[-\s]to[-\s]worst\b"
    r"|\bat\s+(?:least|most)\b"
    r"|\bfirst[-\s](?:quarter|half)\b"
    r"|\bon\s+top\s+of\b"
    r"|\b(?:double|triple|rounding)[-\s]+(?:tops?|bottoms?)\b|\bhead[-\s]+and[-\s]+shoulders(?:\s+top)?\b",
    re.IGNORECASE)
UP = re.compile(r"\b(?:rose|rise[sn]?|rising|gain(?:s|ed|ers?)?|up|higher|rall(?:y|ied|ies)|added|adds|jump(?:s|ed)?"
                r"|climb(?:s|ed)?|advanc(?:e|ed|es|ers))\b", re.IGNORECASE)
DOWN = re.compile(r"\b(?:fell|fall(?:s|ing)?|lost|los(?:s|ses|ers?)|drop(?:s|ped)?|declin(?:e|ed|es|ers)|down|lower|slid"
                  r"|sank|drags?|dragged|shed)\b", re.IGNORECASE)
CLAUSE = re.compile(r"(?<=[.!?])\s+|\n+|;\s*|,?\s+(?:while|whereas|but)\s+|,\s+and\s+", re.IGNORECASE)
CASHTAG = re.compile(r"(?<![\w$])\$([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)(?![\w])")

SECTOR_ALIASES = {
    "Technology": ["technology", "tech"],
    "Communication Services": ["communication services", "comm services", "communications"],
    "Consumer Defensive": ["consumer defensive", "consumer staples", "staples"],
    "Consumer Cyclical": ["consumer cyclical", "consumer discretionary", "discretionary"],
    "Financial Services": ["financial services", "financials"],
    "Healthcare": ["healthcare", "health care"],
    "Industrials": ["industrials"],
    "Energy": ["energy"],
    "Basic Materials": ["basic materials", "materials"],
    "Real Estate": ["real estate"],
    "Utilities": ["utilities"],
}
_ALIAS = sorted(((a, s) for s, al in SECTOR_ALIASES.items() for a in al), key=lambda x: -len(x[0]))
SECTOR_WORD = re.compile(r"(?<![\w$-])(" + "|".join(re.escape(a) for a, _ in _ALIAS) + r")(?![\w])", re.IGNORECASE)
ALIAS_OF = {a: s for a, s in _ALIAS}
PAREN = re.compile(r"\([^()]*\)")


def canon_sector(name: str | None) -> str | None:
    if not name:
        return None
    n = str(name).strip()
    if n in SECTOR_ALIASES:
        return n
    return ALIAS_OF.get(n.lower())


def _norm(s: str) -> str:
    return s.replace(" ", " ").replace(" ", " ").replace("−", "-")


def clauses(text: str) -> list[str]:
    return [c for c in CLAUSE.split(_norm(text or "")) if c and c.strip()]


def tags_in(s: str) -> list[str]:
    return list(dict.fromkeys(mk.norm_ticker(m.group(1)) for m in CASHTAG.finditer(s)))


def _blank_names(s: str, names: list[str]) -> str:
    for n in sorted({n for n in names if n and len(n) >= 3}, key=len, reverse=True):
        s = re.sub(re.escape(n), " ", s, flags=re.IGNORECASE)
    return s


def sectors_in(s: str, names: list[str] | None = None, outside_parens: bool = True) -> list[str]:
    """Canonical sectors named in s (company names blanked; cashtags never count; parenthesised labels skipped when
    outside_parens)."""
    s = CASHTAG.sub(" ", _blank_names(s, names or []))
    if outside_parens:
        s = PAREN.sub(" ", s)
    return list(dict.fromkeys(ALIAS_OF[m.group(1).lower()] for m in SECTOR_WORD.finditer(s)))


def item_names(item: dict) -> list[str]:
    """Company / person names the item carries (so "Constellation Energy" is not the Energy sector)."""
    out = [item.get("name"), item.get("company")]
    out += list((item.get("ticker_names") or {}).values())
    out += [(p or {}).get("name") for p in item.get("peers") or [] if isinstance(p, dict)]
    return [n for n in out if isinstance(n, str)]


def claim(words, subjects=(), says: str = "", bare: bool = False, direction: str | None = None,
          needs: str | None = None) -> dict:
    """One backed claim (market_facts / facts build them; see the module doc)."""
    subj = []
    for s in subjects:
        if not s:
            continue
        subj.append(canon_sector(s) or mk.norm_ticker(s))
    return {"words": list(dict.fromkeys(words)), "subjects": list(dict.fromkeys(subj)), "bare": bool(bare),
            "direction": direction, "needs": needs, "says": says}


def superlatives(s: str) -> list[str]:
    s = EXEMPT.sub(" ", s)
    return list(dict.fromkeys(m.lastgroup for m in SUPER.finditer(s)))


def directions(s: str) -> set[str]:
    out = set()
    if UP.search(s):
        out.add("up")
    if DOWN.search(s):
        out.add("down")
    return out


def claim_reasons(item: dict, text: str) -> list[str]:
    """REJECT reasons for comparative / superlative wording the item's claims do not back."""
    claims = [c for c in item.get("claims") or [] if isinstance(c, dict)]
    names = item_names(item)
    out = []
    for cl in clauses(text):
        words = superlatives(cl)
        if not words:
            continue
        subj = set(tags_in(cl)) | set(sectors_in(cl, names))
        dirs = directions(cl)
        usable = [c for c in claims
                  if (not c.get("direction") or not dirs or c["direction"] in dirs)
                  and (not c.get("needs") or re.search(c["needs"], cl, re.IGNORECASE))]

        def backs(c, w):
            return w in c.get("words", []) and ((subj & set(c.get("subjects") or [])) if subj else c.get("bare"))
        miss_w = [w for w in words if not any(backs(c, w) for c in usable)]
        miss_s = sorted(s for s in subj if not any(s in (c.get("subjects") or []) and set(c.get("words", [])) & set(words)
                                                    for c in usable))
        if miss_w or miss_s:
            backed = "; ".join(c.get("says") or "" for c in claims if c.get("says")) or "none"
            what = ", ".join(sorted(subj)) or "no named company or sector"
            out.append(f"unsupported comparison ({'/'.join(words)}) about {what} in \"{cl.strip()[:90]}\": only the "
                       f"item's claims may be stated, one claim's subjects per sentence (backed: {backed[:300]})")
    return out


# ---------------------------------------------------------------------------
# 3. Sector attribution

def sector_reasons(item: dict, text: str) -> list[str]:
    secmap = {mk.norm_ticker(k): canon_sector(v) for k, v in (item.get("ticker_sectors") or {}).items() if v}
    if not secmap:
        return []
    names = item_names(item)
    out = []
    cls = clauses(text)
    for i, cl in enumerate(cls):
        # a cashtag labelled with one sector in parentheses: "$GOOGL −2.47% (Tech)"
        for m in re.finditer(r"\$([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)(?![\w])[^$()]*\(([^()]*)\)", cl):
            t, labels = mk.norm_ticker(m.group(1)), sectors_in(m.group(2), names, outside_parens=False)
            if len(labels) == 1 and secmap.get(t) and secmap[t] != labels[0]:
                out.append(f"sector: ${t} is labelled {labels[0]} (it is {secmap[t]})")
        secs = sectors_in(cl, names)
        if len(secs) != 1:
            continue
        tags = tags_in(PAREN.sub(" ", cl))
        if not tags and i + 1 < len(cls) and cls[i + 1].lstrip().startswith("$") and not sectors_in(cls[i + 1], names):
            tags = tags_in(cls[i + 1])
        for t in tags:
            if secmap.get(t) and secmap[t] != secs[0]:
                out.append(f"sector: the wording puts ${t} in {secs[0]} (it is {secmap[t]}); name its sector or "
                           "keep it out of that sentence")
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# 4. Scoped numbers and 5. card message

def scope_reasons(item: dict, text: str, strip_allowed) -> list[str]:
    """`strip_allowed(text, numbers)` blanks the numbers (grok_review.strip_allowed): a changed text printed one."""
    out = []
    norm = _norm(text)
    for sc in item.get("scoped_numbers") or []:
        nums = [str(n) for n in sc.get("numbers") or [] if n]
        if not nums or strip_allowed(text, nums) == norm:
            continue
        missing = [r for r in sc.get("require") or [] if not re.search(r, text, re.IGNORECASE)]
        if missing:
            out.append(f"scope: {sc.get('say') or 'these numbers need their scope'}")
    return out


def card_reasons(item: dict, text: str) -> list[str]:
    cm = item.get("card_message") or {}
    bad = cm.get("never")
    if not bad:
        return []
    m = re.search(bad, text, re.IGNORECASE)
    if not m:
        return []
    return [f"card: the attached card says {cm.get('says') or 'otherwise'}; the text must not contradict it "
            f"({m.group(0)!r})"]


def content_reasons(item: dict, text: str, strip_allowed=None) -> list[str]:
    """Every content check of this module for one text (facts self-check and the validator)."""
    out = (index_reasons(item.get("type"), text, item_names(item)) + claim_reasons(item, text) + sector_reasons(item, text)
           + card_reasons(item, text) + window_reasons(item, text))
    if strip_allowed is not None:
        out += scope_reasons(item, text, strip_allowed)
    return out
