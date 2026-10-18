"""Content checks every post and every facts text pass (HQ 2026-10-18 review fixes; social-content-2026-10-18 PLAN §4).

Shared by facts.py (a build-time self-check of each item's own facts_text and angles), grok_review.py (the validator) and,
through grok_review.wording_reasons, the Growth post audit. Pure functions, no I/O.

1. Universe wording (owner rule): our universe is "the 500 largest US-listed stocks", never "S&P 500". No post of any item
   type names the S&P (S&P 500, S&P500, SP500, SPX, "the index", "Standard & Poor's", "benchmark index", "index members",
   "SPY stocks"; invisible characters stripped first). The one exception is the track record's benchmark comparison on a
   picks item, written as "vs the S&P 500 (SPY)" / "vs SPY (S&P 500)" ("vs SPY" alone needs no exception).
2. Comparative / superlative claims (led, biggest, largest, worst, best, most, least, only, first, top, record, #1 and
   their synonyms and comparatives: "outperformed every other", "no other sector beat", "more than any") are allowed only
   when the item backs them in its `claims` field, computed by facts.py / market_facts.py:
     {"words": [categories], "subjects": [tickers, or sector names when kind="sector", in rank order],
      "kind": "stock"|"sector", "polarity": "best"|"worst"|None, "rank": 1|"group", "within": [scope sectors / tickers],
      "scope": regex or None, "bare": bool, "direction": "up"|"down"|None, "needs": regex or None, "says": what is true}
   A clause (sentence, or a part split at ";", ", while", ", but", ", and", or after a colon lead-in) that carries a
   superlative passes only when (section 2 below has the detail)
     - its polarity (best / worst words, else gain / loss words and signs; "top" / "led" alone = best) matches the claim's;
     - every ticker it names is ranked by a stock claim and every sector by a sector claim (or is the claim's `within`):
       singular wording only for the rank-1 subject, a list only from #1 in order, "among the" / "one of the" for any
       group member, "second-biggest" only for #2;
     - every superlative category in it is in the words of such a claim (a clause naming nothing: a claim marked bare);
     - the claim's direction (when set) agrees with its direction words / signs, its `needs` occurs in it, and nothing
       widens the window ("ever", "in history", "of the year").
   Definitions are not claims: "the 500 largest", "the 10 largest", "largest US-listed", "first session after", "track record",
   "best minus worst", "at least" / "at most", "first quarter", "top line", "#1 pick"; nor is a question to the reader
   ("...surprised you most?").
   A one-session item (its `when` is "on Friday" / "today") is never "this / last / past week"; the earnings preview (a
   week ahead) is never "past week".
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
    r"\bs\s*(?:&|&amp;|＆|and)\s*p(?:\s*-?\s*500)?(?![a-z])|\bsp\s*-?\s*500\b|\bspx\b|\bthe\s+index\b"
    r"|\bstandard\s*(?:&|&amp;|and)\s*poor'?s\b|\bbenchmark\s+index\b"
    r"|\bindex\s+(?:members?|heavyweights?|constituents?|components?|names|stocks|companies)\b", re.IGNORECASE)
# "any SPY stock", "SPY names": the ETF named as our universe ("vs SPY", the benchmark comparison, stays allowed)
SPY_WORD = re.compile(r"(?<![\w$])SPY\s+(?:stocks?|names?|compan(?:y|ies)|members?|constituents?|components?)\b",
                      re.IGNORECASE)
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
    text = _norm(text)  # invisible characters inside "S&P" do not hide it
    scan = _blank_names(spy_blank(kind, text), names or [])
    m = INDEX_WORDS.search(scan) or SPY_WORD.search(scan)
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
    "last week" for the current one, no "past week" for a week ahead (the earnings preview); a one-session item (when
    "on Friday", "today") is never a week."""
    when = str(item.get("when") or "")
    if not when:
        return []
    w = when.lower()
    if "week" not in w:
        ok = set()
    else:
        ahead = w.startswith("in the week of") or item.get("type") == "earnings_week_preview"
        ok = {w} | ({"past week"} if w != "this week" and not ahead else set())
    bad = [m.group(0) for m in WEEK_WORDS.finditer(text) if m.group(0).lower() not in ok]
    return [f"window: the item's window is \"{when}\", not {bad[0]!r}"] if bad else []


# ---------------------------------------------------------------------------
# 2. Superlatives
#
# A claim (market_facts.claim / claim below) carries explicit ranking semantics (HQ review 2026-10-18 round 2: "Tech
# was the top sector" passed on a day Tech was the worst, "Was $MSFT the biggest dollar loser?" passed with $GOOGL #1):
#   kind      "stock" (subjects are tickers) or "sector" (subjects are canonical sector names); a sector named in a
#             sentence only ever matches a sector claim's subjects or a stock claim's `within`
#   polarity  "best" (the top of a ranking by gain), "worst" (the top of a ranking by loss) or None (a ranking with no
#             good / bad end: market value, mentions, trades, dollars sold, Sync, or the largest move either way)
#   rank      1 (its single subject is #1 for that polarity) or "group" (its subjects, in rank order, are the top N)
#   within    the scope the ranking holds in (a sector's best stock, a ticker's closest peers): the sentence must name
#             one of them or match `scope`
#   direction the subjects' own move ("up" / "down"): direction words / signs in the sentence must agree
# Neutral words (top, led, biggest, largest, most, #1) get their polarity from the sentence: best / worst words, then
# gain / loss words and signed numbers (+2.6%, -$886B); "top" / "led" with nothing else read as the best end; "biggest"
# / "most" with nothing else only match a claim without polarity. A singular superlative needs the rank-1 subject; a
# group claim allows group wording ("among the biggest", "one of the largest", "biggest drops included") for any member,
# a list of members only in rank order from #1 ("Biggest dollar drops: $GOOGL, $MSFT"), and "second-biggest" only for
# the member at that place.

CATEGORIES = (
    ("led", r"led|leads?|leading|leaders?"),
    ("biggest", r"biggest|largest|heaviest|greatest"),
    ("worst", r"worst|weakest|lowest"
              r"|underperform(?:s|ed|ing)?\s+(?:every|all|any)(?:\s+other)?"
              r"|(?:worse\s+than|trail(?:s|ed)?|lagg(?:ed)?\s+behind)\s+(?:every|all|any)(?:\s+other)?"
              r"|no\s+other\s+(?:[a-z]+\s+){0,2}(?:fell|lost|dropped|declined|did)\s+(?:more|worse)"),
    ("best", r"best|strongest|highest"
             r"|outperform(?:s|ed|ing)?\s+(?:every|all|any)(?:\s+other)?"
             r"|(?:beat|beats|topped|tops|better\s+than|ahead\s+of)\s+(?:every|all|any)(?:\s+other)?"
             r"|no\s+other\s+(?:[a-z]+\s+){0,2}(?:beat|topped|rose\s+more|gained\s+more|did\s+better|came\s+close)"),
    ("most", r"most(?:-[a-z]+)?|more\s+than\s+(?:any|every|all)(?:\s+other)?"),
    ("least", r"least|smallest|fewest"),
    ("only", r"only|sole|lone"),
    ("first", r"first"),
    ("top", r"top(?:s|ped|ping)?|\#\s?1|no\.\s?1|number\s+one"),
    ("record", r"records?|record-[a-z]+|all-time|unprecedented"),
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
    r"|\btrack[-\s]+records?\b|\brecord\s+dates?\b"     # our picks' track record (a page), a dividend's record date
    r"|\bfirst\s+(?:comment|reply)\b"                    # "link in the first comment"
    r"|\bonly(?=\s*[:.,;)\]]|\s*$)"                      # a limiter after its noun: "EPS only:", "link in bio only."
    r"|\#\s?1\s+pick\b"                                  # the locked #1 pick (a product rule, not a ranking claim)
    r"|\btop[-\s]line\b"                                 # revenue ("a small miss on the top line")
    r"|\b(?:double|triple|rounding)[-\s]+(?:tops?|bottoms?)\b|\bhead[-\s]+and[-\s]+shoulders(?:\s+top)?\b",
    re.IGNORECASE)
UP = re.compile(r"\b(?:rose|rise[sn]?|rising|gain(?:s|ed|ers?)?|up|higher|rall(?:y|ied|ies)|added|adds|jump(?:s|ed)?"
                r"|climb(?:s|ed)?|advanc(?:e|ed|es|ers)|lifts?|lifted|winners?|surg(?:e|es|ed|ing)|soar(?:s|ed|ing)?"
                r"|outperform(?:s|ed|ing|ers?)?)\b", re.IGNORECASE)
DOWN = re.compile(r"\b(?:fell|fall(?:s|ing)?|lost|los(?:s|ses|ers?)|drop(?:s|ped)?|declin(?:e|ed|es|ers)|down|lower|slid"
                  r"|sank|drags?|dragged|shed|laggards?|sell-?offs?|slump(?:s|ed)?|tumbl(?:e|es|ed)|plung(?:e|es|ed)"
                  r"|underperform(?:s|ed|ing|ers?)?)\b", re.IGNORECASE)
SIGNED = re.compile(r"(?<![\w.,%])([+-])\s?\$?\d")   # +2.64%, -$886B (text normalised: the minus sign is "-")
CLAUSE = re.compile(r"(?<=[.!?])(?<![Nn]o\.)\s+|\n+|;\s*|,?\s+(?:while|whereas|but)\s+|,\s+and\s+", re.IGNORECASE)  # "No. 1"
CASHTAG = re.compile(r"(?<![\w$])\$([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)(?![\w])")
_SUP_WORD = r"(?:biggest|largest|heaviest|greatest|best|strongest|highest|worst|weakest|lowest|most|top)"
ORDINAL = re.compile(r"\b(second|third|fourth|fifth|2nd|3rd|4th|5th)[\s-]+(?=" + _SUP_WORD + r"\b)", re.IGNORECASE)
ORDINAL_N = {"second": 2, "third": 3, "fourth": 4, "fifth": 5, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}
GROUP = re.compile(r"\bamong\s+(?:the\s+)?(?:[\w$-]+\s+){0,2}" + _SUP_WORD + r"\b"
                   r"|\bone\s+of\s+(?:the\s+)?(?:[\w$-]+\s+){0,2}" + _SUP_WORD + r"\b"
                   r"|\binclud(?:e|es|ed|ing)\b"
                   r"|\btop[\s-]+(?:\d+|two|three|four|five|six|seven|eight|nine|ten)\b"
                   r"|\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten)\s+" + _SUP_WORD + r"\b", re.IGNORECASE)
# A claim's window is its item's (the session, the week, 30 days): never widened to a year, history or "ever".
WIDE = re.compile(r"\bever\b|\b\w+-ever\b|\bin\s+(?:(?:market|stock[-\s]market|wall\s+street)\s+)?history\b|\bhistoric"
                  r"|\bof\s+the\s+(?:year|decade|century|month)\b|\bthis\s+year\b|\byear[-\s]to[-\s]date\b|\bytd\b"
                  r"|\bon\s+record\b|\bsince\s+(?:19|20)\d\d\b|\bin\s+(?:years|decades)\b", re.IGNORECASE)
SECTOR_SCOPE = mk.SECTOR_SCOPE   # "led its sector", "best stock in each up sector"

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
INVISIBLE = re.compile("[​‌‍⁠﻿­]")


def canon_sector(name: str | None) -> str | None:
    if not name:
        return None
    n = str(name).strip()
    if n in SECTOR_ALIASES:
        return n
    return ALIAS_OF.get(n.lower())


def _norm(s: str) -> str:
    return INVISIBLE.sub("", s.replace(" ", " ").replace(" ", " ").replace("−", "-"))


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
          needs: str | None = None, **semantics) -> dict:
    """One backed claim (market_facts.claim builds them; see the section doc)."""
    return mk.claim(words, subjects, says=says, bare=bare, direction=direction, needs=needs, **semantics)


def _ent(s: str, kind: str) -> str:
    return (canon_sector(s) or s) if kind == "sector" else mk.norm_ticker(s)


def claim_view(c: dict) -> dict:
    """A claim with its ranking semantics filled in. Claims built before 2026-10-18 round 2 carry no kind / polarity /
    rank / within: sectors listed beside stocks become their scope, polarity comes from best / worst in the words or
    the direction, rank from the number of subjects."""
    words = list(c.get("words") or [])
    raw = [s for s in c.get("subjects") or [] if s]
    within = [canon_sector(s) or mk.norm_ticker(s) for s in c.get("within") or [] if s]
    kind = c.get("kind")
    if kind in ("stock", "sector"):
        subj = [_ent(s, kind) for s in raw]
    else:
        secs = [canon_sector(s) for s in raw if canon_sector(s) and s != str(s).upper()]
        ticks = [mk.norm_ticker(s) for s in raw if not (canon_sector(s) and s != str(s).upper())]
        if ticks:
            kind, subj, within = "stock", ticks, within + secs
        else:
            kind, subj = "sector", secs
    if "polarity" in c:
        pol = c.get("polarity")
    elif "most" in words:  # "moved most like" (Sync), "most mentions": no good / bad end
        pol = {"up": "best", "down": "worst"}.get(c.get("direction"))
    else:
        pol = ("best" if "best" in words else "worst" if "worst" in words
               else {"up": "best", "down": "worst"}.get(c.get("direction")))
    rank = c.get("rank") or (1 if len(subj) <= 1 else "group")
    return {"words": words, "subjects": list(dict.fromkeys(subj)), "kind": kind, "polarity": pol, "rank": rank,
            "within": list(dict.fromkeys(within)), "scope": c.get("scope"), "bare": bool(c.get("bare")),
            "direction": c.get("direction"), "needs": c.get("needs"), "says": c.get("says") or ""}


def _prep(s: str) -> str:
    """Definitions blanked, "second-biggest" split so its superlative is seen."""
    return EXEMPT.sub(" ", ORDINAL.sub(lambda m: m.group(1) + " ", s))


def superlatives(s: str) -> list[str]:
    return list(dict.fromkeys(m.lastgroup for m in SUPER.finditer(_prep(s))))


def directions(s: str) -> set[str]:
    """Direction words and signed numbers in s."""
    out = set()
    if UP.search(s):
        out.add("up")
    if DOWN.search(s):
        out.add("down")
    for m in SIGNED.finditer(_norm(s)):
        out.add("up" if m.group(1) == "+" else "down")
    return out


def polarity(s: str, words: list[str]) -> tuple[set[str], set[str]]:
    """(ends, dirs): which end of a ranking the sentence's superlatives mean ("best" / "worst"; empty = not said) and
    its direction words / signs. best / worst words win; otherwise gain / loss words and signs; "top" / "led" alone
    read as the best end."""
    dirs = directions(_prep(s))
    ends = {e for e in ("best", "worst") if e in words}
    if not ends and dirs:
        ends = {"best" if d == "up" else "worst" for d in dirs}
    if not ends and set(words) & {"top", "led"}:
        ends = {"best"}
    return ends, dirs


# A question to the reader asserts nothing ("Which bank print surprised you most this week?"): exempt. Other questions
# ("Was $WMT the biggest gainer?") are checked like statements.
READER_QUESTION = re.compile(r"^(?=.*\byou(?:r|rs)?\b).*\?$", re.IGNORECASE | re.DOTALL)


def claim_clauses(text: str, names: list[str] | None = None) -> list[str]:
    """clauses(), each also split at a colon when the part before it carries no superlative (a lead-in such as
    "$GOOGL and $MSFT: $MSFT had the biggest drop" or "In the week to Oct 16: ..."), unless the part after it carries a
    superlative but names nothing (then the lead-in's names are its subjects: "$GOOGL fell 2.47%: the biggest drop")."""
    out = []
    for c in clauses(text):
        parts = re.split(r":\s+", c)
        cur = parts[0]
        for p in parts[1:]:
            if superlatives(cur) or (superlatives(p) and not (tags_in(p) or sectors_in(p, names))):
                cur = f"{cur}: {p}"
            else:
                out.append(cur)
                cur = p
        out.append(cur)
    return [c for c in out if c.strip()]


def _rank_ok(c: dict, ranked: list[str], group: bool, nth: int | None) -> bool:
    if c["rank"] == 1:
        return nth in (None, 1)
    order = c["subjects"]
    if nth:
        return len(ranked) == 1 and order.index(ranked[0]) == nth - 1
    if group:
        return True
    return ranked == order[:len(ranked)]


def _clause_reasons(cl: str, words: list[str], claims: list[dict], names: list[str]) -> list[str]:
    body = _prep(cl)
    ticks, secs = tags_in(cl), sectors_in(cl, names)
    named = set(ticks) | set(secs)
    ends, dirs = polarity(cl, words)
    group = bool(GROUP.search(body))
    om = ORDINAL.search(cl)
    nth = ORDINAL_N[om.group(1).lower()] if om else None
    wide = WIDE.search(cl)
    if wide:
        return [f"scope: {wide.group(0)!r} widens a comparison past the item's window (its claims hold for the session /"
                f" week / 30 days of the item, not a year, history or ever)"]

    def usable(c):
        return ((not c["needs"] or re.search(c["needs"], cl, re.IGNORECASE))
                and (not c["direction"] or not dirs or c["direction"] in dirs)
                and (c["polarity"] is None or c["polarity"] in ends)
                and (not c["within"] or set(c["within"]) & named
                     or (c["scope"] and re.search(c["scope"], cl, re.IGNORECASE))))
    use = [c for c in claims if usable(c)]
    applying = []
    for c in use:
        pool = secs if c["kind"] == "sector" else ticks
        ranked = [e for e in pool if e in c["subjects"]]
        if ranked and set(c["words"]) & set(words) and _rank_ok(c, ranked, group, nth):
            applying.append((c, ranked))
    if not named:
        bare = [c for c in use if c["bare"] and _rank_ok(c, c["subjects"][:1], group, nth)]
        miss_w, miss_e = [w for w in words if not any(w in c["words"] for c in bare)], []
    else:
        covered = set()
        for c, ranked in applying:
            covered |= set(ranked) | (set(c["within"]) & named)
        miss_w = [w for w in words if not any(w in c["words"] for c, _ in applying)]
        miss_e = [e for e in ticks + secs if e not in covered]
    out = []
    if miss_w or miss_e:
        side = "/".join(sorted(ends)) or "no side said"
        what = ", ".join(ticks + secs) or "no named company or sector"
        rel = [c for c in claims if (set(c["subjects"]) | set(c["within"])) & named] or claims
        backed = "; ".join(c["says"] for c in rel if c["says"]) or "none"
        out.append(f"unsupported comparison ({'/'.join(words)}; {side}) about {what} in \"{cl.strip()[:90]}\": "
                   f"only the item's claims may be stated - the #1 for that side, a list only from #1 in order, "
                   f"\"among the\" for other members, a sector only as a sector claim says (backed: {backed[:300]})")
    # a ticker beside a sector it does not rank in ("$DEO led Energy and $COP led Consumer Defensive")
    for part in re.split(r",|;|\band\b|&", PAREN.sub(" ", cl)):
        pt, ps = tags_in(part), sectors_in(part, names)
        if len(pt) != 1 or not ps:
            continue
        cs = [c for c, r in applying if pt[0] in r and c["kind"] == "stock" and c["within"]]
        sec_claimed = any(c["kind"] == "sector" and set(r) & set(ps) for c, r in applying)
        if cs and not sec_claimed and not any(set(c["within"]) & set(ps) for c in cs):
            out.append(f"unsupported comparison: ${pt[0]} is ranked in {', '.join(w for c in cs for w in c['within'])}, "
                       f"not {', '.join(ps)} (\"{part.strip()[:80]}\")")
    return out


def claim_reasons(item: dict, text: str) -> list[str]:
    """REJECT reasons for comparative / superlative wording the item's claims do not back."""
    claims = [claim_view(c) for c in item.get("claims") or [] if isinstance(c, dict)]
    names = item_names(item)
    out = []
    for cl in claim_clauses(text, names):
        words = superlatives(cl)
        if not words or READER_QUESTION.search(cl.strip()):
            continue
        out += _clause_reasons(cl, words, claims, names)
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
