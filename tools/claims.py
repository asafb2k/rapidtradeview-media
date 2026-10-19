"""Content checks every post and every facts text pass (HQ 2026-10-18 review fixes; social-content-2026-10-18 PLAN §4).

Shared by facts.py (a build-time self-check of each item's own facts_text and angles), grok_review.py (the validator) and,
through grok_review.wording_reasons, the Growth post audit. Pure functions, no I/O.

1. Universe wording (owner rule): our universe is "the 500 largest US-listed stocks", never "S&P 500". No post of any item
   type names the S&P (S&P 500, S&P500, SP500, SPX, "the index", "Standard & Poor's", "benchmark index", "index members",
   "SPY stocks"; invisible characters stripped first). The one exception is the track record's benchmark comparison on a
   picks item, written as "vs the S&P 500 (SPY)" / "vs SPY (S&P 500)" ("vs SPY" alone needs no exception).
2d (HQ 2026-10-19, the gate for every item with fact_phrases): VERBATIM FACTS - see section 2d at the end of this
   module; sections 2, 2b and 2c below are the reading of items from facts files built before it.
2b (HQ 2026-10-19). Comparisons are an ALLOWLIST: a sentence with any ranking / comparison language passes
   only as one of the item's `claim_phrases` verbatim (see section 2b below).
2c (HQ 2026-10-19 round 2). And so does any sentence with a word outside the closed plain vocabulary (post_vocab.VOCAB):
   the ranking word list is no longer the gate. Plain sentences tie every number and every rose / fell / up / down to its
   subject (binding_reasons: `subject_numbers`, `moves`); a chart post's above / below must match its prices. Section 2 (the `claims` reading of rounds
   1-4) applies only to items from facts files built before the allowlist (no `claim_phrases` key).
2. Comparative / superlative claims (led, biggest, largest, worst, best, most, least, only, first, top, record, #1 and
   their synonyms and comparatives: "outperformed every other", "no other sector beat", "more than any") are allowed only
   when the item backs them in its `claims` field, computed by facts.py / market_facts.py:
     {"words": [categories], "subjects": [tickers, or sector names when kind="sector", in rank order],
      "kind": "stock"|"sector", "polarity": "best"|"worst"|None, "rank": 1|"group", "metric": what is ranked,
      "within": [scope sectors / tickers], "universe": "10"|None, "date": iso|None, "scope": regex or None, "bare": bool,
      "direction": "up"|"down"|"mixed"|None, "needs": regex or None, "says": what is true}
   A clause (sentence, or a part split at ";", ", while", ", but", ", and", or after a colon lead-in) that carries a
   superlative passes only when every superlative word in it is backed by a claim (section 2 below has the detail):
     - the side it means matches the claim's polarity: best / worst words, else the noun it governs ("top loser", "led
       the drop" = worst) or the verb before it ("fell the most"); "top" / "led" / "#1" alone or with an entity noun
       ("top sector", "led its sector") = best, whatever signs stand beside them; with any other noun ("led the rout",
       "the top story") the side is unclear and nothing backs it (r4);
     - the metric it names matches the claim's (percent / market cap / dollars);
     - every scope phrase attached to it matches the claim's ("of the 500", "overall", "of all", "on the day" = no
       within; "in Tech", "Tech's", "its sector", a fronted "In Tech," = that within, never a sector named elsewhere in
       the clause; "of the 10" = the basket);
     - every ticker / sector / company name the clause names is ranked by such a claim (a sector only by a sector
       claim, or as a stock claim's within; "any Tech stock" ranks stocks): singular wording / a list only from #1 in
       order, "among the" / "one of the" for any group member ("one of the two biggest" only for the top 2), "the N
       biggest" / "top N" for exactly the top N, "second-biggest" only for #2;
     - a clause that names nothing and refers back ("It was the biggest", "The biggest dollar drop of the 500.") is
       about the company / sector named last before it (a question naming nothing: the answer named next); only a claim
       with no subjects may stand bare;
     - the claim's direction (or its subjects' move from the item) agrees with its direction words / signs, its `needs`
       occurs in it, a bare claim is not tied to another date, and nothing widens the window ("ever", "in months", "of
       the quarter", "since September"); a negated comparison is rejected; an elliptical follow-up ("and so was Tech",
       "$MSFT too") joins the superlative before it.
   Two named tickers / sectors compared ("did better than $AAPL", "lost $23.1B, more than $MSFT") need a claim of that
   metric (percent unless dollars are named) that ranks them so. "#N by <metric>" / "the Nth-biggest dollar drop" must be
   the item's rank of that company (rank_by_usd / rank_by_cap / its place in a claim).
   Definitions are not claims: "the 500 largest", "the 10 largest", "largest US-listed", "first session after", "track record",
   "best minus worst", "at least" / "at most", "first quarter", "top line", "#1 pick"; nor is a question about the reader
   that names no company or sector ("...surprised you most?").
   A one-session item (its `when` is "on Friday" / "today") is never "this / last / past week" (and its comparisons never
   a week or 5 sessions); a week item's comparisons are never one day; the earnings preview (a week ahead) is never "past
   week"; no item says "today" / "yesterday" / "tonight" unless its `when` does (a Monday post about Friday); a
   one-session item names no other weekday or date than its session's and no "this morning" / "pre-market" / "so far".
3. Sector attribution: a clause naming one sector and listing cashtags (or followed by a clause that starts with a
   cashtag and names no sector) implies those companies are in that sector; a cashtag labelled with a sector in
   parentheses likewise. Each must match the item's ticker_sectors ($GOOGL is Communication Services, not Technology).
4. Scoped numbers: an item may require words next to some of its numbers (`scoped_numbers`: the 30-day insider totals are
   "open-market" buys / sells "by officers and directors").
5. Card message (`card_message`): words a post may not use because its attached card says the opposite (breadth: a card
   headlining a broad decline never goes with "narrow", "concentrated", "the typical stock was flat").
6. Direction (`moves`): a gain / loss verb never sits beside a number or a company / sector that moved the other way.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import unicodedata

import market_facts as mk
import post_vocab as pv

# ---------------------------------------------------------------------------
# 1. Universe wording

INDEX_WORDS = re.compile(
    r"\bs\.?\s*(?:&|&amp;|＆|and)\s*p\.?(?:\s*-?\s*500)?(?![a-z])|\bsp\s*-?\s*500\b|\bspx\b|\bthe\s+index\b"
    r"|\bstandard\s*(?:&|&amp;|and)\s*poor'?s\b|\bbenchmark\s+index\b"
    # reviewer probes 10-18 ("60 S.&P. 500 companies", "Large-cap benchmark", "The US 500", "The Spiders", "the Dow")
    r"|\b(?:the\s+|large[\s-]?cap\s+)?benchmark\b|\bu\.?s\.?\s+500\b|\bspiders\b|\bthe\s+dow\b|\bdow\s+(?:jones|30)\b"
    r"|\bnasdaq[\s-]?100\b|\brussell\s+[123]000\b"
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
STALE_DAY = re.compile(r"\b(today|tonight|yesterday)(?:['’]s)?\b", re.IGNORECASE)


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
        if w.startswith("in the week to"):
            ok.add("last week")   # built on the weekend after the week, posted on Monday (HQ review r4)
    bad = [m.group(0) for m in WEEK_WORDS.finditer(text) if m.group(0).lower() not in ok]
    # a post goes out after the facts were built (Grok's Monday pre-market slot reads Sunday's facts): "today",
    # "yesterday" and "tonight" are wrong for a session the item calls "on Friday" (or a week)
    bad += [m.group(0) for m in STALE_DAY.finditer(text) if m.group(1).lower() not in w]
    bad += _wide_window_words(item, text)
    if "week" not in w:
        bad += _session_day_words(item, text)
    elif item.get("window") == "week" or item.get("type") == "basket_week":
        # a 5-session item's numbers are never one day's (r1 open issue: "On Friday, Tech fell 7.3%" on the week item)
        bad += [m.group(0) for m in DAY_WORDS.finditer(text)]
    return [f"window: the item's window is \"{when}\", not {bad[0]!r}"] if bad else []



# round 2 review: a month ("in October"), month to date, or "over N weeks / days / sessions" the item does not state widens
# its window ("Tech fell 7.3% in October", "over two weeks"); a month before a day number is a date ("Oct 16")
_MONTH_WORD = re.compile(r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december"
                         r"|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b\.?(?!\s*\d)", re.IGNORECASE)
_MTD = re.compile(r"\bmonth[\s-]+to[\s-]+date\b|\bmtd\b|\bthis\s+month\b|\bthe\s+month\b", re.IGNORECASE)
_SPAN = re.compile(r"\b(?:over|in|across|during|for|within|past|last)\s+(?:the\s+)?(?:last\s+|past\s+)?"
                   r"(?P<n>\d+|two|three|four|five|six|seven|eight|nine|ten|several|many)\s+"
                   r"(?P<u>days|weeks|months|years|sessions|trading\s+days|closes)\b", re.IGNORECASE)


def _wide_window_words(item: dict, text: str) -> list[str]:
    own = _norm(" ".join([str(item.get("facts_text") or ""), *(str(p) for p in item.get("claim_phrases") or [])])).lower()
    t = _norm(text)
    # "may" is a verb before it is a month
    bad = [m.group(0) for m in _MONTH_WORD.finditer(t) if m.group(0).lower().rstrip(".") != "may"]
    bad += [m.group(0) for m in _MTD.finditer(t)]
    for m in _SPAN.finditer(t):
        span = m.group("n").lower() + " " + re.sub(r"\s+", " ", m.group("u").lower())
        if span not in own:
            bad.append(m.group(0))
    return bad


# ---------------------------------------------------------------------------
# 2. Superlatives
#
# A claim (market_facts.claim builds them) carries explicit ranking semantics (HQ review 2026-10-18 rounds 2-3: "Tech was
# the top sector" passed on a day Tech was the worst, also with "(-2.8%)" beside it; "two biggest dollar drops: $GOOGL
# and $AVGO" passed with $AVGO #4; "$GOOGL, #1 by market cap" passed against a dollar-drop claim):
#   kind      "stock" (subjects are tickers) or "sector" (canonical sector names); a sector named in a sentence only
#             ever matches a sector claim's subjects or a stock claim's `within`
#   polarity  "best" (the top of a ranking by gain), "worst" (the top of a ranking by loss) or None (no good / bad end:
#             market value, mentions, trades, Sync, the largest move either way, the sector that led the day's move)
#   rank      1 (its single subject is #1) or "group" (its subjects, in rank order, are the top N)
#   metric    what is ranked: "usd_change" (dollars gained / lost), "pct_change", "market_cap" (size), "mentions",
#             "mention_ratio", "sync", "trades", "usd_flow" (insider dollars), "breadth" (stocks up minus down)
#   within    the scope the ranking holds in (a sector's best stock, a ticker's closest peers)
#   universe  "10" for the 10-largest basket (a sentence must say "of the 10" / "10 largest"); None: the item's own
#   date      (bare claims) the session the claim is about ("the strongest up day" was Oct 15, not Friday)
#   direction the subjects' own move ("up" / "down" / "mixed"): direction words / signs in the sentence must agree
# Each superlative word in a clause is read on its own:
#   side   best / worst words fix it. top / led / #1 / biggest / most take the side of the noun they govern ("top loser",
#          "led the drop", "biggest decline", "led Tech lower" = worst; "top gainer" = best) or of the verb before them
#          ("fell the most", "lost the most market value"); "led the move" / "biggest move" = no side. Otherwise top /
#          led / #1 alone or with an entity noun mean the best end whatever signs stand beside them ("Tech, down 2.8%,
#          was the top sector" = Tech was the best); with any other noun they are "unclear" and never backed (r4);
#          biggest / largest + a company / sector noun is size ("the biggest company" = market cap); most / biggest
#          alone take the clause's gain / loss words, then its signs.
#   metric "percent" / "percentage" = pct_change; "by market cap / value", "most valuable", size = market_cap; "dollar",
#          "market value" lost / gained = usd_change; a $ amount alone counts as dollars only for a dollar claim. A
#          dollar claim needs dollar wording; a market-cap claim needs size wording.
#   scope  words after it ("of the 500", "overall", "of the day", "of any stock", "in the market" = the whole universe:
#          only a claim with no `within` and no basket universe; "of the 10" = the basket; "in Tech", "Tech's",
#          "biggest Tech name", "led Energy" = that sector's within claim; "its / their / each sector", "its best stock",
#          "led it" = the within claim of the sector the sentence before named, or of the stock's own sector).
#   rank   singular / a list = from #1 in order; "among the" / "one of the" / "included" = any group member; "the two
#          biggest" / "top 3" = exactly the top N; "second-biggest" = the member at that place.
# A clause naming nothing may use only a claim marked bare, and then not with another date or direction. A negated
# comparison ("was not the best") is not checked: rejected. Two named tickers compared ("did better than $AAPL", "was
# worse") need a claim that ranks them that way.

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
_SECTOR_ALT = "|".join(re.escape(a) for a, _ in _ALIAS)
# an entity right after a quantified comparison ("No sector beat Tech", "Every sector beat $XOM")
_ENT_NEXT = r"(?=\s+(?:than\s+)?(?:the\s+)?(?:\$[a-z]|(?:" + _SECTOR_ALT + r")(?![\w])))"
CATEGORIES = (
    ("led", r"led|leads?|leading|leaders?"),
    ("biggest", r"biggest|largest|heaviest|greatest|sharpest|steepest|hardest|deepest"),
    ("worst", r"worst|weakest|lowest|coldest|poorest|laggards?"
              r"|underperform(?:s|ed|ing)?\s+(?:every|all|any)(?:\s+other)?"
              r"|(?:worse\s+than|trail(?:s|ed)?|lagg(?:ed)?\s+behind)\s+(?:every|all|any)(?:\s+other)?"
              r"|no\s+other\s+(?:[a-z]+\s+){0,2}(?:fell|lost|dropped|declined|did)\s+(?:more|worse)"
              r"|no\s+(?:[a-z]+\s+){0,2}?(?:did\s+worse|underperformed|trailed|lagged)" + _ENT_NEXT +
              # "Every sector beat Energy" = Energy was the worst (r4)
              r"|(?:every|all)\s+(?:other\s+)?(?:[a-z]+\s+){0,2}?(?:beat|outpaced|outperformed|topped|did\s+better\s+than"
              r"|rose\s+more\s+than|gained\s+more\s+than)" + _ENT_NEXT),
    ("best", r"best|strongest|highest|hottest|stand-?out"
             r"|outperform(?:s|ed|ing)?\s+(?:every|all|any)(?:\s+other)?"
             r"|outpac(?:es|ed|ing)?\s+(?:every|all|any)(?:\s+other)?"
             r"|(?:beat|beats|topped|tops|better\s+than|ahead\s+of)\s+(?:every|all|any)(?:\s+other)?"
             r"|no\s+other\s+(?:[a-z]+\s+){0,2}(?:beat|topped|rose\s+more|gained\s+more|did\s+better|came\s+close)"
             r"|no\s+(?:[a-z]+\s+){0,2}?(?:beat|outpaced|outperformed|topped|did\s+better)" + _ENT_NEXT +
             r"|(?:every|all)\s+(?:other\s+)?(?:[a-z]+\s+){0,2}?(?:did\s+worse\s+than|fell\s+more\s+than|lost\s+more\s+than"
             r"|underperformed|trailed|lagged(?:\s+behind)?)" + _ENT_NEXT),
    ("most", r"most(?:-[a-z]+)?|closest|tightest|nearest"
             r"|more\s+than\s+(?:any|every|all)(?:\s+other)?"
             r"|(?:more\s+(?:[a-z$]+\s+){1,3}|(?!(?:oth|rath|ev|nev|und|ov|aft|lat|earli|ord)er\b)[a-z]+er\s+)than\s+"
             r"(?:any|every|all)(?:\s+other)?"
             r"|(?:no|nothing|none)\s+(?:other\s+)?(?:[a-z]+\s+){0,2}(?:lost|shed|gained|added|moved|fell|rose|dropped)\s+"
             r"(?:more|further|harder|as\s+much)"),
    ("least", r"least|smallest|fewest|less\s+(?:[a-z$]+\s+){0,3}than\s+(?:any|every|all)(?:\s+other)?"),
    ("only", r"only|sole|lone"),
    ("first", r"first"),
    ("top", r"top(?:s|ped|ping)?|\#\s?1|no\.\s?1|number[-\s]+one"),
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
                  r"|underperform(?:s|ed|ing|ers?)?|routs?|downturns?|weakness|casualt(?:y|ies))\b", re.IGNORECASE)
SIGNED = re.compile(r"(?<![\w.,%])([+-])\s?\$?\d")   # +2.64%, -$886B (text normalised: the minus sign is "-")
CLAUSE = re.compile(r"(?<=[.!?])(?<![Nn]o\.)\s+|\n+|;\s*|,?\s+(?:while|whereas|but)\s+|,\s+and\s+", re.IGNORECASE)  # "No. 1"
SENTENCE = re.compile(r"(?<=[.!?])(?<![Nn]o\.)\s+|\n+")
CASHTAG = re.compile(r"(?<![\w$])\$([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)(?![\w])")
_NUMW = r"(\d{1,2}|two|three|four|five|six|seven|eight|nine|ten)"
NUM_N = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
ORDINAL_BEFORE = re.compile(r"\b(second|third|fourth|fifth|2nd|3rd|4th|5th)[\s-]+$", re.IGNORECASE)
ORDINAL_N = {"second": 2, "third": 3, "fourth": 4, "fifth": 5, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}
MEMBER_BEFORE = re.compile(r"\b(?:among|one\s+of)\s+(?:the\s+|its\s+|their\s+|these\s+)?(?:[\w$'-]+\s+){0,2}$", re.IGNORECASE)
INCLUDES = re.compile(r"\binclud(?:e|es|ed|ing)\b", re.IGNORECASE)
COUNT_BEFORE = re.compile(r"(?<![\w.,$#])" + _NUMW + r"[\s-]+$", re.IGNORECASE)        # "the three biggest", "Two worst"
COUNT_AFTER = re.compile(r"^[\s-]+" + _NUMW + r"\b(?![.,]\d)(?!\s*(?:%|x\b|×|largest|sessions?|days?|closes?|points?))",
                         re.IGNORECASE)                                                    # "top 3", "worst three"
# A claim's window is its item's (the session, the week, 30 days): never widened to a month, a year, history or "ever".
_MONTHS = (r"january|february|march|april|may|june|july|august|september|october|november|december"
           r"|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec")
WIDE = re.compile(
    r"\bever\b|\b\w+-ever\b|\bin\s+(?:(?:market|stock[-\s]market|wall\s+street)\s+)?history\b|\bhistoric"
    r"|\bof\s+the\s+(?:year|decade|century|month|quarter)\b|\bof\s+all[-\s]time\b|\bthis\s+(?:year|month|quarter|decade)\b"
    r"|\byear[-\s]to[-\s]date\b|\bytd\b|\bon\s+record\b|\bsince\s+(?:19|20)\d\d\b"
    r"|\bsince\s+(?:(?:early|mid|late|the\s+(?:start|end|beginning)\s+of)[-\s]+)?(?:" + _MONTHS
    + r"|last\s+(?:year|month|quarter|week)|(?:mon|tues|wednes|thurs|fri)day"
    r"|the\s+(?:spring|summer|fall|autumn|winter|peak|high|low|crash|pandemic|election|start|beginning))\b"
    r"|\bin\s+(?:years|decades|months|weeks|ages|a\s+long\s+time)\b|\bin\s+\d+\s+(?:weeks|months|years|quarters)\b"
    r"|\b52[-\s]week\b"
    r"|\bin\s+(?:a|one|the\s+(?:past|last))\s+(?:year|month|decade|quarter)\b"
    r"|\bin\s+(?:the\s+)?(?:past|last)\s+(?:\d+|few|several|two|three|six|twelve)\s+(?:years|months|weeks|quarters)\b"
    r"|\bin\s+(?:" + _MONTHS + r")\b(?![\s.]*\d)|\bin\s+20\d\d\b", re.IGNORECASE)
SESSION_WIDE = re.compile(r"\bweeks?\b|\bweekly\b|\b(?:two|three|four|five|2|3|4|5)\s+(?:sessions|trading\s+days|days)\b",
                          re.IGNORECASE)          # a one-session item's superlative is about that session
WEEKDAYS = r"monday|tuesday|wednesday|thursday|friday"
DAY_WORDS = re.compile(r"\b(?:on\s+(?:" + WEEKDAYS + r")|(?:" + WEEKDAYS + r")['’]s|today|tonight|yesterday)\b",
                       re.IGNORECASE)             # a week item's superlative is about the week, not one day
NEGATION = re.compile(r"\bnot\b|n['’]t\b|\bnever\b|\bno\s+longer\b", re.IGNORECASE)
SECTOR_SCOPE = re.compile(mk.SECTOR_SCOPE, re.IGNORECASE)   # "led its sector", "best stock in each up sector"

# the side a neutral word takes from the noun after it / the verb before it
_LOSS = (r"los(?:e|es|er|ers|s|ses|ing)|lost|drops?|dropped|dropping|declin\w*|fall(?:s|ers?|ing)?|fell|drags?|dragg\w*"
         r"|laggards?|lagg\w*|sell-?offs?|selloffs?|slides?|slid|lower|down|downside|slump\w*|plung\w*|tumbl\w*|hit|damage"
         r"|sank|sinks?|shed|sheds|wiped|red|retreat\w*|pullbacks?|bleed\w*|crash\w*|sell(?:ing|ers?)?|sold"
         # r4: loss nouns a reviewer found read as the best end ("led the rout", "the top casualty")
         r"|routs?|downturns?|downdrafts?|weak\w*|casualt(?:y|ies)|disappoint\w*|victims?|pain|carnage|bloodbath"
         r"|flops?|misses|missed|beaten|battered|punished|cold\w*|poor\w*|underperform\w*|negative|bearish"
         r"|outflows?|decliners?|bottom\w*|worse|hurt|bruis\w*|stragglers?|deficits?")
_GAIN = (r"gain\w*|winners?|ris(?:e|es|ers?|ing)|rose|advanc\w*|rall(?:y|ies|ied|ying)|lifts?|lifted|lifting|jump\w*"
         r"|higher|up|upside|climb\w*|surg\w*|soar\w*|perform\w*|green|added|adds?|rebound\w*|bounc\w*|buy(?:ing|ers?)?"
         r"|bought|outperform\w*|outpac\w*|strength|strong\w*|positive|bullish|hot\w*|inflows?|risers?|recover\w*"
         r"|better|winning|wins?")
LOSS_W = re.compile(rf"\b(?:{_LOSS})\b", re.IGNORECASE)
GAIN_W = re.compile(rf"\b(?:{_GAIN})\b", re.IGNORECASE)
MOVE_W = re.compile(r"\b(?:moves?|movers?|moving|swings?|changes?|shifts?)\b", re.IGNORECASE)
ENTITY_W = re.compile(r"\b(?:sectors?|stocks?|compan(?:y|ies)|names?|members?|reporters?|reports?|groups?|holdings?|firms?"
                      r"|caps?|giants?|weights?|constituents?|tickers?|businesses|corporations?|industr(?:y|ies)|one)\b",
                      re.IGNORECASE)
TIME_W = re.compile(r"^\s*(?:[\w-]+\s+)?(?:day|week|session|month|quarter|year|close|run|stretch|streak)s?\b",
                    re.IGNORECASE)        # "its worst day": the stock's own history, which no claim backs
_STOP = re.compile(r"\b(?:as|when|since|because|after|before|than|while)\b", re.IGNORECASE)
SIZE_WORD = re.compile(r"biggest|largest|greatest|heaviest", re.IGNORECASE)
# the metric a superlative is about
PCT_W = re.compile(r"\bper\s?cent(?:age)?\b|(?<![\d.,])\s?%(?!\d)|\bpct\b", re.IGNORECASE)   # "percent", "biggest % drop"
CAP_W = re.compile(r"\b(?:by|in)\s+market\s+(?:cap(?:italization)?|value)\b|\bmost\s+valuable\b|\bby\s+(?:size|valuation)\b"
                   r"|\#\s?1\s+by\s+market", re.IGNORECASE)
USD_W = re.compile(r"\bdollars?\b|\bmarket\s+(?:value|cap)\b", re.IGNORECASE)
AMOUNT = re.compile(r"\$\s?\d")
# the scope words after a superlative
GLOBAL_W = re.compile(
    r"\b(?:of|among|in)\s+(?:all\s+)?(?:the\s+)?500\b|\boverall\b"
    r"|\bin\s+the\s+(?:whole\s+|entire\s+|broad\s+|stock\s+|us\s+)?market\b|\bof\s+the\s+(?:day|session)\b"
    r"|\b(?:of|than)\s+(?:any|every|all)\s+(?:other\s+)?(?:(?!(?:" + _SECTOR_ALT + r")\s)[\w.-]+\s+)?"
    r"(?:stocks?|compan(?:y|ies)|names?|tickers?|pairs?)\b"
    r"|\b(?:any|every)\s+other\s+(?:stock|company|name|ticker)\b|\bin\s+the\s+(?:us|u\.s\.|country|world)\b"
    r"|\banywhere\b|\bon\s+wall\s+street\b|\bof\s+(?:all\s+|the\s+)?2,?[45]\d\d\b|\bacross\s+the\s+market\b"
    r"|\bof\s+all\b(?![\s-]+(?:time|500|the\s+500))|\bon\s+the\s+day\b|\bin\s+the\s+(?:whole\s+)?(?:universe|map)\b", re.IGNORECASE)
BASKET_W = re.compile(r"\b(?:of|among|in)\s+(?:the\s+|these\s+|those\s+)?(?:10|ten)\b|\b(?:10|ten)\s+(?:largest|biggest|mega)"
                      r"|\bmega[-\s]?caps?\b", re.IGNORECASE)
UNIVERSE_NOUN = re.compile(r"\b(?:stocks?|compan(?:y|ies)|names?|tickers?|los(?:er|ers)|gainers?|winners?|performers?"
                           r"|decliners?|risers?)\b", re.IGNORECASE)
SEP = re.compile(r"[,;:()\[\]?!]|\s[-–—]\s|\s+(?:and|while|whereas|but|with|as|after|before|when|plus)\s+",
                 re.IGNORECASE)
PRON_BEFORE = re.compile(r"\b(?:its|their)\s+(?:[\w-]+\s+)?$", re.IGNORECASE)
BENCHMARK = {"SPY"}   # the picks' track record compares with SPY (section 1): not a ranking between two stocks
COMPARE_END = re.compile(r"\b(?:was|were|did|fared|is|are)\s+(?:even\s+)?(?P<w>worse|better|weaker|stronger)\s*[.!?]?\s*$",
                         re.IGNORECASE)

SECTOR_WORD = re.compile(r"(?<![\w$-])(" + _SECTOR_ALT + r")(?![\w])", re.IGNORECASE)
SECTOR_NEXT = re.compile(r"^\s+(?:dollar\s+)?(" + _SECTOR_ALT + r")(?![\w])", re.IGNORECASE)    # "biggest Tech name"
SECTOR_IN = re.compile(r"\b(?:in|of|within|inside|among)\s+(?:the\s+|any\s+|every\s+|all\s+)?(?:other\s+)?(" + _SECTOR_ALT + r")(?![\w])", re.IGNORECASE)
SECTOR_POSS = re.compile(r"(?<![\w$-])(" + _SECTOR_ALT + r")['’]s\s+(?:[\w-]+\s+)?$", re.IGNORECASE)  # "Tech's biggest"
TICKER_POSS = re.compile(r"\$([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)['’]s\s+(?:[\w-]+\s+)?$")         # "$T's closest"
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
    """Company names blanked with spaces of the same length (positions kept)."""
    for n in sorted({n for n in names if n and len(n) >= 3}, key=len, reverse=True):
        s = re.sub(re.escape(n), lambda m: " " * len(m.group(0)), s, flags=re.IGNORECASE)
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
    out += list((item.get("names") or {}).values()) if isinstance(item.get("names"), dict) else []   # roundups
    out += [(r or {}).get("name") for r in item.get("reporters") or [] if isinstance(r, dict)]       # the week preview
    out += [(p or {}).get("name") for p in item.get("peers") or [] if isinstance(p, dict)]
    return [n for n in out if isinstance(n, str)]


def claim(words, subjects=(), says: str = "", bare: bool = False, direction: str | None = None,
          needs: str | None = None, **semantics) -> dict:
    """One backed claim (market_facts.claim builds them; see the section doc)."""
    return mk.claim(words, subjects, says=says, bare=bare, direction=direction, needs=needs, **semantics)


def _ent(s: str, kind: str) -> str:
    return (canon_sector(s) or s) if kind == "sector" else mk.norm_ticker(s)


def _old_metric(c: dict, kind: str, pol) -> str | None:
    """The metric of a claim built before 2026-10-19 (no `metric` field), from its needs / words."""
    needs = str(c.get("needs") or "")
    if "dollar" in needs:
        return "usd_change"
    if "market (?:value|cap)" in needs:
        return "market_cap"
    if needs:
        return None
    if kind == "sector" or pol in ("best", "worst"):
        return "pct_change"
    return None


def claim_view(c: dict) -> dict:
    """A claim with its ranking semantics filled in. Claims built before 2026-10-18 round 2 carry no kind / polarity /
    rank / within: sectors listed beside stocks become their scope, polarity comes from best / worst in the words or
    the direction, rank from the number of subjects; before 2026-10-19 no metric (read from `needs`) / universe / date."""
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
    metric = c["metric"] if "metric" in c else _old_metric(c, kind, pol)
    if "metric" not in c and kind == "sector" and words == ["led"]:
        pol = None   # the lead sector of a market_move ("led the move") before 2026-10-19: no side of its own
    return {"words": words, "subjects": list(dict.fromkeys(subj)), "kind": kind, "polarity": pol, "rank": rank,
            "metric": metric, "universe": c.get("universe"), "date": c.get("date"),
            "within": list(dict.fromkeys(within)), "scope": c.get("scope"),
            "bare": bool(c.get("bare")) and not subj,
            "direction": c.get("direction"), "needs": c.get("needs"), "says": c.get("says") or ""}


ORDINAL_HYPHEN = re.compile(r"\b(second|third|fourth|fifth|2nd|3rd|4th|5th)-(?=[a-z])", re.IGNORECASE)


def _prep(s: str) -> str:
    """Definitions blanked and "second-biggest" split, keeping every position (the same length as s)."""
    return EXEMPT.sub(lambda m: " " * len(m.group(0)), ORDINAL_HYPHEN.sub(lambda m: m.group(1) + " ", s))


def superlatives(s: str) -> list[str]:
    return list(dict.fromkeys(m.lastgroup for m in SUPER.finditer(_prep(s))))


def directions(s: str) -> set[str]:
    """Direction words and signed numbers in s."""
    return _word_dirs(s) | _sign_dirs(s)


def _word_dirs(s: str) -> set[str]:
    out = set()
    if UP.search(s):
        out.add("up")
    if DOWN.search(s):
        out.add("down")
    return out


def _sign_dirs(s: str) -> set[str]:
    return {"up" if m.group(1) == "+" else "down" for m in SIGNED.finditer(_norm(s))}


# A question to the reader asserts nothing ("Which bank print surprised you most this week?"): exempt only when it names
# no company / sector and the reader is the superlative's subject ("surprised you most", "your biggest"). Any other
# question ("Was $WMT the biggest gainer?", "Did you know Tech was the top sector?") is checked like a statement (r4).
_YOU_BEFORE = re.compile(r"\byou(?:r|rs|['’]re)?\b(?:\s+[\w'’-]+){0,2}\s*$", re.IGNORECASE)


def _reader_question(cl: str, ents: list) -> bool:
    if ents or not cl.strip().endswith("?"):
        return False
    body = _prep(cl)
    occ = list(SUPER.finditer(body))
    return bool(occ) and all(_YOU_BEFORE.search(body[max(0, m.start() - 40):m.start()]) for m in occ)


def claim_clauses(text: str, names: list[str] | None = None) -> list[str]:
    """clauses(), each also split at a colon when the part before it carries no superlative (a lead-in such as
    "$GOOGL and $MSFT: $MSFT had the biggest drop" or "In the week to Oct 16: ..."), unless the part after it carries a
    superlative but names nothing (then the lead-in's names are its subjects: "$GOOGL fell 2.47%: the biggest drop")."""
    out = []
    for c in clauses(text):
        parts = re.split(r":\s+", c)
        cur = parts[0]
        for p in parts[1:]:
            # r4: a lead-in naming a ticker keeps a superlative after the colon that names none ("$AVGO -$74.4B: biggest
            # dollar drop of any Tech stock": Tech is the scope, $AVGO the subject)
            if superlatives(cur) or (superlatives(p) and not tags_in(p) and (tags_in(cur) or not sectors_in(p, names))):
                cur = f"{cur}: {p}"
            else:
                out.append(cur)
                cur = p
        out.append(cur)
    return [c for c in out if c.strip()]


def _words(s: str) -> list[str]:
    return re.findall(r"[\w$'%.+-]+", s)


def _head(o: dict, body: str) -> str:
    """Up to 4 words after a superlative (its noun: "top loser", "biggest Tech name", "led the drop")."""
    fwd = body[o["e"]:o["seg_end"]]
    stop = _STOP.search(fwd)
    return " ".join(_words(fwd[:stop.start()] if stop else fwd)[:4])


SECTOR_NOUN = re.compile(r"\b(?:sectors?|groups?|industr(?:y|ies))\b", re.IGNORECASE)
STOCK_NOUN = re.compile(r"\b(?:stocks?|compan(?:y|ies)|names?|tickers?|shares?|firms?)\b", re.IGNORECASE)


# The words "top" / "led" / "#1" may govern and still mean the best end: entity nouns, places in a ranking, pronouns,
# the ranking's own nouns (mentions, matches). Sector names, cashtags and numbers are dropped first.
NEUTRAL_OK = re.compile(
    r"(?:the|a|an|its|their|his|her|this|that|it|them|these|those|our|your|every|all|whole|entire|other|others|rest"
    r"|sectors?|stocks?|names?|compan(?:y|ies)|groups?|industr(?:y|ies)|performers?|performing|-performing|spots?|places?"
    r"|positions?|slots?|ranks?|ranking|picks?|tickers?|members?|holdings?|shares?|firms?|list|lists|board|leaderboard"
    r"|charts?|pack|way|charge|field|market|everything|everyone|peers?|mentions?|chatter|buzz|reddit|wallstreetbets|wsb"
    r"|match(?:es)?|trades?|one|ones|two|three|four|five|six|seven|eight|nine|ten|mega|caps?|large|us|u\.s\.|us-listed"
    r"|listed|monday|tuesday|wednesday|thursday|friday|week|weekend|session|day|again|once|overall|again|too|also"
    r"|largest|biggest|ranked|spot)", re.IGNORECASE)
_NP_STOP = re.compile(r"\b(?:in|of|on|among|within|inside|by|at|for|with|to|across|over|from|after|before|than|as|when"
                      r"|since|because|while|during|into|through|vs|versus|and|or|but|was|were|is|are|had|has|did)\b",
                      re.IGNORECASE)


def _neutral_noun_ok(o: dict, body: str) -> bool:
    """Is the noun phrase a top / led / #1 governs one that keeps the best end (nothing, an entity noun, a sector, a
    ticker, a place in a ranking)?"""
    fwd = body[o["e"]:o["seg_end"]]
    fwd = CASHTAG.sub(" ", SECTOR_WORD.sub(" ", fwd))
    stop = _NP_STOP.search(fwd)
    words = re.findall(r"[\w'.-]+", fwd[:stop.start()] if stop else fwd)
    words = [re.sub(r"['’]s$", "", w.strip("'.")) for w in words]
    rest = [w for w in words if w and not (re.fullmatch(r"[\d.,%+-]+|\d+(?:st|nd|rd|th)?", w) or NEUTRAL_OK.fullmatch(w))]
    return not rest


def _side(o: dict, body: str, cl: str) -> tuple[str | None, bool]:
    """(side, changed): the end of a ranking one superlative means ("best" / "worst"; None: no side; "size": market
    cap) and whether a gain / loss word decided it (then "market value" means dollars lost / gained, not size)."""
    if o["cat"] in ("best", "worst"):
        return o["cat"], False
    head = _head(o, body)
    back = " ".join(_words(body[o["seg_start"]:o["s"]])[-3:])
    if re.match(r"\s*valuable\b", body[o["e"]:], re.IGNORECASE):
        return "size", False                  # "the most valuable company": market cap
    if LOSS_W.search(head):
        return "worst", True
    if GAIN_W.search(head):
        return "best", True
    if MOVE_W.search(head):
        return None, False                    # "led the move", "the biggest dollar move": either way
    if LOSS_W.search(back):
        return "worst", True                  # "fell the most", "lost the most market value", "dragged hardest"
    if GAIN_W.search(back):
        return "best", True
    if o["cat"] in ("led", "top"):
        if CAP_W.search(body[o["seg_start"]:o["seg_end"]]):
            return "size", False              # "#1 by market cap", "led by market value": size
        # "top sector", "led on Friday", "led Energy", "led its sector": the best end, whatever the signs. Any other
        # noun ("led the stampede", "the top story") is never guessed to be the best end (r4: "led the rout" was read
        # as best): no claim backs an unclear side.
        return ("best" if _neutral_noun_ok(o, body) else "unclear"), False
    if SIZE_WORD.match(o["w"]) and ENTITY_W.search(head):
        return "size", False                  # "the biggest company", "the largest sector": market cap
    wd = _word_dirs(cl)
    if len(wd) == 1:
        return ("best" if wd == {"up"} else "worst"), True
    sd = _sign_dirs(cl)
    if len(sd) == 1 and not SIZE_WORD.match(o["w"]):
        return ("best" if sd == {"up"} else "worst"), True
    return None, False


def _metric(o: dict, cl: str, side, changed: bool) -> str | None:
    """"pct", "cap", "usd" (dollar wording), "usd~" (only a $ amount in the clause) or None."""
    seg = cl[o["seg_start"]:o["seg_end"]]
    for t in (seg, cl):
        if PCT_W.search(t):
            return "pct"
        if CAP_W.search(t) and (not changed or side == "size"):
            return "cap"
        if USD_W.search(t):
            return "usd"
    if side == "size":
        return "cap"
    return "usd~" if AMOUNT.search(cl) else None


def _scope(o: dict, cl: str, has_ticks: bool, names: list[str], fwd: str | None = None, back: str | None = None):
    """The scope words of one superlative: ("global",), ("basket",), ("sector", S), ("ticker", T), ("pron", own, hist)
    or None."""
    fwd = cl[o["e"]:o["seg_end"]] if fwd is None else fwd
    back = cl[o["seg_start"]:o["s"]] if back is None else back
    if GLOBAL_W.search(fwd):
        return ("global",)
    if BASKET_W.search(fwd):
        return ("basket",)
    pron_b = PRON_BEFORE.search(back)
    own = SECTOR_SCOPE.search(fwd) or SECTOR_SCOPE.search(cl[o["e"]:o.get("next_s", len(cl))])
    if pron_b or own or (o["cat"] == "led" and re.match(r"^\s+(?:it|them)\b", fwd)):
        hist = bool(pron_b) and not own and bool(TIME_W.match(fwd))
        return ("pron", bool(own), hist)
    if has_ticks:
        fb = _blank_names(fwd, names)
        m = SECTOR_NEXT.match(fb) or SECTOR_IN.search(fb)
        if m:
            return ("sector", ALIAS_OF[m.group(1).lower()])
        m = SECTOR_POSS.search(_blank_names(back, names))
        if m:
            return ("sector", ALIAS_OF[m.group(1).lower()])
    m = TICKER_POSS.search(back)
    if m:
        return ("ticker", mk.norm_ticker(m.group(1)))
    return None


SCOPE_MORE = re.compile(r"^\s*(?:,\s*)?(?:and|&|as\s+well\s+as|plus)\s+(?=(?:on|in|of|across|among|within|inside|for)\b)",
                        re.IGNORECASE)
FRONT_SECTOR = re.compile(r"^\W*(?:in|within|inside|among)\s+(?:the\s+)?(" + _SECTOR_ALT + r")(?![\w])", re.IGNORECASE)


def _scopes(o: dict, cl: str, body: str, has_ticks: bool, names: list[str]) -> list:
    """Every scope phrase attached to one superlative (r4: "the biggest dollar drop in Technology and on Wall Street"
    makes two statements; a fronted "In Tech, $CRWV was the worst stock" scopes it too). [None] when it has none."""
    out = [_scope(o, cl, has_ticks, names)]
    end = o["seg_end"]
    while True:
        m = SCOPE_MORE.match(cl[end:])
        if not m:
            break
        start = end + m.end()
        nxt = SEP.search(body, start)
        end = nxt.start() if nxt else len(cl)
        sc = _scope(o, cl, has_ticks, names, fwd=" " + cl[start:end], back="")
        if sc and sc[0] != "pron":
            out.append(sc)
    if out[0] is None and has_ticks:
        m = FRONT_SECTOR.match(_blank_names(cl, names))
        if m:
            out[0] = ("sector", ALIAS_OF[m.group(1).lower()])
    real = [x for x in dict.fromkeys(out) if x is not None]
    return real or [None]


def _grp(o: dict, cl: str):
    """Rank wording of one superlative: ("member",), ("count", N), ("nth", k) or None (singular / a list from #1)."""
    back = cl[o["seg_start"]:o["s"]]
    fwd = cl[o["e"]:o["seg_end"]]
    mb = MEMBER_BEFORE.search(back)
    if mb or INCLUDES.search(cl):
        # "one of the two biggest", "among the top 3": a member of exactly the top N (r4: $NVDA #3 passed as "one of
        # the two biggest")
        m = COUNT_BEFORE.search(back) or COUNT_AFTER.match(fwd)
        if m:
            n = m.group(1).lower()
            return ("member", int(n) if n.isdigit() else NUM_N[n])
        return ("member",)
    m = ORDINAL_BEFORE.search(back)
    if m:
        return ("nth", ORDINAL_N[m.group(1).lower()])
    m = COUNT_BEFORE.search(back) or COUNT_AFTER.match(fwd)
    if m:
        n = m.group(1).lower()
        return ("count", int(n) if n.isdigit() else NUM_N[n])
    return None


def _rank_ok(c: dict, ranked: list[str], grp) -> bool:
    subj = c["subjects"]
    if not ranked:
        return True
    if grp and grp[0] == "member":
        if len(grp) > 1:
            return grp[1] <= len(subj) and all(t in subj[:grp[1]] for t in ranked)
        return c["rank"] == "group" or ranked == subj[:1]
    if grp and grp[0] == "count":
        return grp[1] <= len(subj) and set(ranked) == set(subj[:grp[1]])
    if grp and grp[0] == "nth":
        return len(ranked) == 1 and ranked[0] in subj and subj.index(ranked[0]) == grp[1] - 1
    return ranked == subj[:len(ranked)]


def _side_ok(c: dict, side) -> bool:
    if side == "unclear":
        return False
    if c["polarity"] is None:
        if side in (None, "size"):
            return True
        return c["direction"] in (None, "mixed") or (side == "best") == (c["direction"] == "up")
    return side == c["polarity"]


def _metric_ok(c: dict, metric, side) -> bool:
    cm = c["metric"]
    if cm == "usd_change":
        return metric in ("usd", "usd~")
    if cm == "pct_change":
        return metric in ("pct", "usd~", None)
    if cm == "market_cap":
        return metric == "cap" or (metric is None and side in (None, "size"))
    return metric != "pct" or cm is None


def _day_forms(iso: str) -> set[str]:
    d = dt.date.fromisoformat(iso[:10])
    return {w.lower() for w in mk.date_words(iso)} | {d.strftime("%A").lower(), f"{d.strftime('%B')} {d.day}".lower()}


DATE_IN = re.compile(r"\b(?:" + WEEKDAYS + r")\b|\b(?:" + _MONTHS + r")\.?\s+\d{1,2}\b|\btoday\b|\byesterday\b|\btonight\b",
                     re.IGNORECASE)


def _date_ok(c: dict, seg: str) -> bool:
    if not c.get("date"):
        return True
    forms = _day_forms(c["date"])
    for m in DATE_IN.finditer(seg):
        w = re.sub(r"\.", "", m.group(0).lower())
        w = re.sub(r"^(\w{3})\w*\s+", lambda x: x.group(1) + " ", w) if re.search(r"\d", w) else w
        if w not in forms and m.group(0).lower() not in forms:
            return False
    return True


def _universe_ok(c: dict, sent: str, text: str, noun: str) -> bool:
    """A basket claim ("10"): its sentence names the basket, or the post does and the word is not about "the stock" /
    "the loser" (which reads as the whole market: "$SPCX was the biggest loser")."""
    if c.get("universe") != "10":
        return True
    return bool(BASKET_W.search(sent)) or (bool(BASKET_W.search(text)) and not UNIVERSE_NOUN.search(noun))


# ---------------------------------------------------------------------------
# Names (r4): a company named without its cashtag ("Microsoft lost $77.2B, the biggest dollar drop", "Only Microsoft
# rose") is a subject like its cashtag. The item's own names (ticker_names, its company) and the best-known short names.

KNOWN_NAMES = {
    "apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA", "alphabet": "GOOGL", "google": "GOOGL", "amazon": "AMZN",
    "meta": "META", "facebook": "META", "tesla": "TSLA", "broadcom": "AVGO", "tsmc": "TSM", "taiwan semiconductor": "TSM",
    "berkshire": "BRK.B", "berkshire hathaway": "BRK.B", "spacex": "SPCX", "netflix": "NFLX", "oracle": "ORCL",
    "palantir": "PLTR", "walmart": "WMT", "exxon": "XOM", "exxonmobil": "XOM", "jpmorgan": "JPM", "costco": "COST",
    "eli lilly": "LLY", "lilly": "LLY", "amd": "AMD", "intel": "INTC", "coreweave": "CRWV", "nebius": "NBIS",
    "sandisk": "SNDK", "salesforce": "CRM", "adobe": "ADBE", "cisco": "CSCO", "chevron": "CVX", "pepsico": "PEP",
    "pepsi": "PEP", "coca-cola": "KO", "boeing": "BA", "disney": "DIS", "micron": "MU", "qualcomm": "QCOM", "ibm": "IBM",
    "palo alto networks": "PANW", "crowdstrike": "CRWD", "goldman sachs": "GS", "morgan stanley": "MS",
    "bank of america": "BAC", "wells fargo": "WFC", "mastercard": "MA", "unitedhealth": "UNH", "home depot": "HD",
    "procter & gamble": "PG", "johnson & johnson": "JNJ",
}
_NAME_SUFFIX = re.compile(r"[,.]?\s+(?:inc|incorporated|corp|corporation|company|co|holdings?|group|plc|p\.l\.c|n\.v|nv"
                          r"|ltd|limited|s\.a|sa|ag|se|asa|l\.p|lp|llc|trust|platforms|class\s+[a-c])\.?(?=\s|$)",
                          re.IGNORECASE)
_GENERIC_NAME = {
    "space", "british", "american", "general", "united", "first", "national", "international", "global", "bank", "the",
    "new", "royal", "digital", "advanced", "applied", "texas", "china", "japan", "canadian", "pacific", "southern",
    "northern", "western", "eastern", "interactive", "fifth", "south", "north", "east", "west", "great", "old", "public",
    "federal", "capital", "energy", "real", "consumer", "health", "financial", "industrial", "technology", "communication",
    "communications", "citizens", "regions", "progressive", "equity", "life", "home", "data", "air", "american",
    "standard", "principal", "smart", "target", "match", "block", "best", "top",
}


def name_map(item: dict) -> dict[str, str]:
    """{lowercase company name / short name: ticker} for the item (its ticker_names and its own company) and the
    best-known short names. A person's name (an item with an office) is never a company."""
    pairs = [(k, v) for k, v in (item.get("ticker_names") or {}).items() if k and isinstance(v, str)]
    t = item.get("ticker")
    if t:
        if isinstance(item.get("company"), str):
            pairs.append((t, item["company"]))
        if isinstance(item.get("name"), str) and not item.get("office"):
            pairs.append((t, item["name"]))
    out: dict[str, str] = {}
    for tk, nm in pairs:
        tk = mk.norm_ticker(tk)
        base = nm.strip().rstrip(".")
        cleaned = base
        while True:
            nxt = _NAME_SUFFIX.sub("", cleaned).strip(" ,.")
            if nxt == cleaned:
                break
            cleaned = nxt
        first = cleaned.split()[0] if cleaned.split() else ""
        for v in (base, cleaned, first):
            v = v.lower().strip(" ,.")
            if len(v) >= 3 and v not in _GENERIC_NAME and v not in ALIAS_OF and not v.isdigit():
                out.setdefault(v, tk)
    for k, v in KNOWN_NAMES.items():
        out.setdefault(k, mk.norm_ticker(v))
    return out


_NAME_RX: dict = {}


def _name_rx(nmap: dict):
    key = tuple(sorted(nmap))
    if key not in _NAME_RX:
        if len(_NAME_RX) > 64:
            _NAME_RX.clear()
        alt = "|".join(re.escape(n) for n in sorted(nmap, key=len, reverse=True))
        _NAME_RX[key] = re.compile(r"(?<![\w$&.-])(?:" + alt + r")(?![\w&])", re.IGNORECASE) if alt else None
    return _NAME_RX[key]


def entities(cl: str, nmap: dict, names: list[str]) -> list[tuple[int, int, str, str]]:
    """(start, end, entity, kind) for every cashtag, company name and sector named in cl, in text order (names and
    sectors inside parentheses are labels, not subjects)."""
    out = [(m.start(), m.end(), mk.norm_ticker(m.group(1)), "stock") for m in CASHTAG.finditer(cl)]
    blank = PAREN.sub(lambda m: " " * len(m.group(0)), CASHTAG.sub(lambda m: " " * len(m.group(0)), cl))
    rx = _name_rx(nmap)
    if rx:
        for m in rx.finditer(blank):
            key = re.sub(r"\s+", " ", m.group(0).lower())
            if key in nmap:
                out.append((m.start(), m.end(), nmap[key], "stock"))
        blank = rx.sub(lambda m: " " * len(m.group(0)), blank)
    blank = _blank_names(blank, names)
    out += [(m.start(), m.end(), ALIAS_OF[m.group(1).lower()], "sector") for m in SECTOR_WORD.finditer(blank)]
    return sorted(out)


# A clause that names nothing and refers back ("It was the biggest dollar drop", "The biggest dollar drop of the 500.")
# is about the company / sector the post named last (or, at the top of a post, the one it names next), never about
# whatever a claim ranks #1 (r4: "$MSFT lost $77.2B. It was the biggest dollar drop of the 500." passed).
REF_PRON = re.compile(r"\b(?:it|that|this|they|these|those)\b(?!\s+(?:week|weekend|day|session|month|year|morning|afternoon"
                      r"|evening|quarter|time|one|ones|stocks?|compan(?:y|ies)|sectors?|names?|moves?|drops?|list|group"
                      r"|basket|number|figure)\b)", re.IGNORECASE)
FRAG_LEAD = re.compile(r"^(?:[\W_]|\b(?:and|but|so|also|plus|then|the|a|an|its|their|which|making|marking|second|third"
                       r"|fourth|fifth|2nd|3rd|4th|5th|one|of|among)\b)*$", re.IGNORECASE)
GROUP_NOUN = re.compile(r"\b(?:stocks|names|companies|tickers|members|sectors|days?|sessions?|closes?|weeks?)\b",
                        re.IGNORECASE)
SECTOR_STOCK = re.compile(r"(?<![\w$-])(?:" + _SECTOR_ALT + r")\s+(?:stocks?|names?|compan(?:y|ies)|tickers?|shares?"
                          r"|firms?|members?)\b", re.IGNORECASE)   # "of any Tech stock": Tech scopes a stock ranking


QUIZ = re.compile(r"\?\s*$")   # a question that names nothing: its answer follows ("The biggest drop? $GOOGL.")


OF_NOUN = re.compile(r"^\s*(?:of|among)\s+(?:any|every|all|the|these|those)?\s*(?:other\s+)?(?:[\w.-]+\s+)?"
                     r"(?:stocks?|names?|compan(?:y|ies)|tickers?|sectors?|groups?|industr(?:y|ies))\b", re.IGNORECASE)
STOCK_SCOPE_W = re.compile(r"\b(?:of|among|in)\s+(?:all\s+)?(?:the\s+)?500\b|\bof\s+(?:all\s+|the\s+)?2,?[45]\d\d\b",
                           re.IGNORECASE)


def _reference(cl: str) -> str | None:
    """"pron" (a pronoun subject before the first superlative: "It was the biggest"), "frag" (the clause opens with the
    superlative: "The biggest dollar drop of the 500.") or None ("Only one of the 10 rose": a subject of its own)."""
    body = _prep(cl)
    m = SUPER.search(body)
    if not m:
        return None
    lead = body[:m.start()]
    if REF_PRON.search(lead):
        return "pron"
    if m.lastgroup not in ("only", "first") and FRAG_LEAD.match(lead):
        return "frag"
    return None


def _clause_reasons(cl: str, claims: list[dict], names: list[str], ctx: dict) -> list[str]:
    body = _prep(cl)
    ents = ctx["ents"]
    ticks = list(dict.fromkeys(e for _, _, e, k in ents if k == "stock"))
    secs = list(dict.fromkeys(e for _, _, e, k in ents if k == "sector"))
    named = set(ticks) | set(secs)
    item = ctx["item"]
    occ = [{"cat": m.lastgroup, "s": m.start(), "e": m.end(), "w": m.group(0)} for m in SUPER.finditer(body)]
    if not occ:
        return []
    wide = WIDE.search(cl)
    if wide:
        return [f"scope: {wide.group(0)!r} widens a comparison past the item's window (its claims hold for the session /"
                f" week / 30 days of the item, not a month, a year, history or ever)"]
    when = str(item.get("when") or "").lower()
    if when and "week" not in when:
        m = SESSION_WIDE.search(cl)
        if m:
            return [f"window: {m.group(0)!r} - the item's comparisons hold for one session ({item.get('when')})"]
    if "week" in when and not when.startswith("in the week of") and item.get("type") != "earnings_week_preview":
        m = DAY_WORDS.search(cl)
        if m:
            return [f"window: {m.group(0)!r} - the item's comparisons hold for {item.get('when')}, not one day"]
    seps = [(m.start(), m.end()) for m in SEP.finditer(body)]
    for i, o in enumerate(occ):
        o["seg_start"] = max([0] + [e for s, e in seps if e <= o["s"]])
        o["seg_end"] = min([len(body)] + [s for s, e in seps if s >= o["e"]])
        o["next_s"] = occ[i + 1]["s"] if i + 1 < len(occ) else len(body)
    # "Friday's best sector was not Energy" (the part that is true is left unsaid): rejected; a "not" elsewhere in the
    # sentence ("..., not a small move") is not the comparison's
    if any(NEGATION.search(cl[o["seg_start"]:o["seg_end"]]) for o in occ):
        return [f"negated comparison in \"{cl.strip()[:90]}\": state what is true positively (the item's claims say: "
                + ("; ".join(c["says"] for c in claims if c["says"])[:300] or "none") + ")"]
    dirs = directions(_prep(cl))
    vdirs = {"up" if _UP_V.match(re.sub(r"\s+", " ", m.group(0))) else "down" for m in MOVE_VERB.finditer(cl)}
    sent, text = ctx["sentence"], ctx["text"]
    secmap = ctx["secmap"]
    ref = ctx.get("ref")
    inh = ctx.get("inherit") or {}
    inh_t = inh.get("stock") if ref and not ticks else None
    inh_s = inh.get("sector") if ref and not ticks and not secs else None
    has_ticks = bool(ticks or inh_t)
    named_ext = named | {x for x in (inh_t, inh_s) if x}
    pos: dict[str, int] = {}
    for st, _, e, k in ents:
        if k == "stock":
            pos.setdefault(e, st)

    def scope_ok(c, sc, ranked, noun):
        within = c["within"]
        if sc is None:
            if within:
                # a ticker's peers ("$PEP moved most like $KO"): the ticker named anywhere; a sector's ranking needs its
                # scope next to the word ("in Tech", "Tech's", "its sector"), not a sector named elsewhere (r4)
                wt = [w for w in within if not canon_sector(w)]
                if not wt:
                    return False
                return bool(set(wt) & named_ext) or bool(c["scope"] and re.search(c["scope"], cl, re.IGNORECASE))
            return _universe_ok(c, sent, text, noun)
        k = sc[0]
        if k == "global":
            return not within and c.get("universe") != "10"
        if k == "basket":
            return c.get("universe") == "10" or (c.get("universe") is None and not within and c["kind"] == "stock")
        if k == "sector":
            return c["kind"] == "stock" and sc[1] in within
        if k == "ticker":
            return sc[1] in within
        own, hist = sc[1], sc[2]
        if hist or c["kind"] != "stock" or not within:
            return False
        if own:
            return all(secmap.get(t) in within for t in ranked if secmap.get(t)) and bool(ranked)
        if ctx.get("sector"):
            return ctx["sector"] in within
        return bool(ranked) and all(secmap.get(t) in within for t in ranked if secmap.get(t))

    def order_ok(c, ranked, sc):
        """A ticker-scoped ranking ("$T moved most like $VZ") names its own ticker first, unless it says whose
        ("$VZ is $T's closest match")."""
        wt = [w for w in c["within"] if w in ticks]
        if not (wt and ranked) or (sc and sc[0] == "ticker") or ranked[0] not in pos:
            return True
        return min(pos[w] for w in wt) < pos[ranked[0]]

    for o in occ:
        o["scopes"] = _scopes(o, cl, body, has_ticks, names)
    # a sector that only scopes a stock ranking ("$MSFT led Tech lower", "Tech's biggest drops: $MSFT") is not itself
    # the subject of a sector claim in that clause
    scope_secs = {sc[1] for o in occ for sc in o["scopes"] if sc and sc[0] == "sector"}
    subj_secs = [s for s in secs if s not in scope_secs]
    backing, covered, fails = [], set(), []
    for o in occ:
        side, changed = _side(o, body, cl)
        metric = _metric(o, cl, side, changed)
        grp = _grp(o, cl)
        seg = cl[o["seg_start"]:o["seg_end"]]
        head = _head(o, body)
        noun = re.split(r"\b(?:in|of|on|among|within|inside|by|at|for|with|to|across|over|from)\b", head,
                        maxsplit=1, flags=re.IGNORECASE)[0]   # "worst stock in its sector": the noun is "stock"
        if o["cat"] == "led":    # its words are an object ("led its sector", "led Energy"), not the ranked noun
            noun = ""
        only = "sector" if SECTOR_NOUN.search(noun) else "stock" if STOCK_NOUN.search(noun) else None
        if not only:
            # "the biggest dollar drop of any Tech stock", "the best of any stock", "the worst of the 500" rank stocks,
            # not sectors (r4)
            fwd = cl[o["e"]:o["seg_end"]]
            om = OF_NOUN.match(fwd)
            if SECTOR_STOCK.search(fwd) or (om and STOCK_NOUN.search(om.group(0))) or STOCK_SCOPE_W.search(fwd):
                only = "stock"
            elif om and SECTOR_NOUN.search(om.group(0)):
                only = "sector"
        group_noun = bool(GROUP_NOUN.search(head))
        per_scope = []
        for sc in o["scopes"]:
            ok = []
            for c in claims:
                if o["cat"] not in c["words"] or (only and c["kind"] != only):
                    continue
                if not (_side_ok(c, side) and _metric_ok(c, metric, side)):
                    continue
                if c["needs"] and not re.search(c["needs"], cl, re.IGNORECASE):
                    continue
                if c["direction"] == "mixed" and dirs:
                    continue
                if c["direction"] in ("up", "down") and dirs and c["direction"] not in dirs:
                    continue
                if c["kind"] == "sector":
                    pool = subj_secs or ([inh_s] if inh_s else [])
                else:
                    pool = ticks or ([inh_t] if inh_t else [])
                ranked = [e for e in pool if e in c["subjects"]]
                # a claim with no direction of its own takes its subjects' move from the item ("The most-mentioned stock
                # rose" when it fell; r4): a move verb in the clause must agree
                moved = {ctx["moves"].get(e) for e in ranked}
                if c["direction"] is None and len(moved) == 1 and None not in moved and vdirs and moved - vdirs:
                    continue
                if pool or named:
                    if not ranked:
                        continue
                else:
                    # nothing named or carried over: only a claim with no subjects ("the strongest up day"), marked
                    # bare; a clause that refers back to a company takes no subject-less claim unless it speaks of a
                    # group or a day ("The most-mentioned stocks all fell", not "It had the most mentions")
                    if c["subjects"] or not c["bare"] or not _date_ok(c, seg):
                        continue
                    if ref and (inh_t or inh_s) and not group_noun:
                        continue
                if not (scope_ok(c, sc, ranked, noun) and _rank_ok(c, ranked, grp) and order_ok(c, ranked, sc)):
                    continue
                ok.append((c, ranked))
            per_scope.append(ok)
        if any(not ok for ok in per_scope):
            fails.append((o, side))
        for ok in per_scope:
            for c, ranked in ok:
                covered |= set(ranked) | (set(c["within"]) & named)
            backing += ok
    out = []
    # the object of a comparison ("worse than Energy") is checked by comparison_reasons, not ranked here
    objs = set()
    for m in COMPARE.finditer(cl):
        after = [e for e in ents if e[0] >= m.end() and e[0] - m.end() <= 25]
        if after:
            objs.add(after[0][2])
    miss_e = [e for e in ticks + secs if e not in covered and e not in objs] if named and not fails else []
    if fails or miss_e:
        o, side = fails[0] if fails else (occ[0], None)
        side_txt = {"best": "best side", "worst": "worst side", "size": "size", None: "no side",
                    "unclear": "unclear side: say best / worst or gain / loss"}[side]
        what = ", ".join(ticks + secs) or (f"{inh_t or inh_s} (named before)" if (inh_t or inh_s)
                                           else "no named company or sector")
        rel = [c for c in claims if (set(c["subjects"]) | set(c["within"])) & named_ext] or claims
        backed = "; ".join(c["says"] for c in rel if c["says"]) or "none"
        out.append(f"unsupported comparison ({o['w'].lower()}; {side_txt}) about {what} in \"{cl.strip()[:90]}\": "
                   f"only the item's claims may be stated - the #1 for that side and metric, a list only from #1 in order, "
                   f"\"among the\" for other members, \"the N biggest\" only for exactly the top N, a sector only as a "
                   f"sector claim says, a stock in a sector only with that sector (backed: {backed[:300]})")
    # a ticker beside a sector it does not rank in ("$DEO led Energy and $COP led Consumer Defensive")
    for part in re.split(r",|;|\band\b|&", PAREN.sub(" ", cl)):
        pt, ps = tags_in(part), sectors_in(part, names)
        if len(pt) != 1 or not ps:
            continue
        cs = [c for c, r in backing if pt[0] in r and c["kind"] == "stock" and c["within"]]
        sec_claimed = any(c["kind"] == "sector" and set(r) & set(ps) for c, r in backing)
        if cs and not sec_claimed and not any(set(c["within"]) & set(ps) for c in cs):
            out.append(f"unsupported comparison: ${pt[0]} is ranked in {', '.join(w for c in cs for w in c['within'])}, "
                       f"not {', '.join(ps)} (\"{part.strip()[:80]}\")")
    return list(dict.fromkeys(out))


# Comparisons of two named entities (r4): "better / worse / outperformed / fell more" mean percent unless the clause
# speaks of dollars ("market value", "dollar", a $ amount); a dollar order never backs a percent comparison. "more /
# less than $T" after an amount compares the amounts ("$PANW lost $23.1B, more than $MSFT").
COMPARE = re.compile(
    r"\b(?P<better>(?:did|performed|fared|held\s+up)\s+better\s+than|better\s+than|stronger\s+than|outperform(?:ed|s|ing)?"
    r"|outpac(?:ed|es|ing)?|beat|beats|topped|tops|(?:rose|gained|climbed|added|jumped)\s+more\s+than)\b"
    r"|\b(?P<worse>(?:did|performed|fared)\s+worse\s+than|worse\s+than|weaker\s+than|underperform(?:ed|s|ing)?|trailed"
    r"|trails|lagged(?:\s+behind)?|(?:fell|dropped|lost|declined|slid|shed)\s+more\s+than)\b"
    r"|\b(?P<more>more|further|harder|bigger|larger)(?:\s+(?!than\b)[\w$'-]+){0,3}?\s+than\b"
    r"|\b(?P<less>less|fewer|smaller)(?:\s+(?!than\b)[\w$'-]+){0,3}?\s+than\b", re.IGNORECASE)
_CMP_LOSS = re.compile(r"\b(?:lost|lose|loses|fell|falls|dropped|drops|declined|slid|shed|sank|tumbled|wiped)\b", re.IGNORECASE)
_CMP_GAIN = re.compile(r"\b(?:gained|gains|rose|rises|added|adds|jumped|climbed|rallied|surged)\b", re.IGNORECASE)


def _cmp_metric(cl: str) -> str:
    if USD_W.search(cl) or AMOUNT.search(cl):
        return "usd"
    if re.search(r"mention|talked|discussed|reddit|buzz", cl, re.IGNORECASE):
        return "mentions"
    if re.search(r"\blike\b|\bsync|closely|correlat", cl, re.IGNORECASE):
        return "sync"
    return "pct"


def _metric_fits(c: dict, metric: str) -> bool:
    cm = c.get("metric")
    if metric == "usd":
        return cm == "usd_change"
    if metric == "pct":
        return cm in ("pct_change", None)
    if metric == "mentions":
        return cm in ("mentions", "mention_ratio")
    return cm == metric


def _cmp_how(m, cl: str) -> str:
    how = m.lastgroup
    if how not in ("more", "less"):
        return how
    lead = cl[:m.start()]
    loss = [x.end() for x in _CMP_LOSS.finditer(lead)]
    gain = [x.end() for x in _CMP_GAIN.finditer(lead)]
    if loss or gain:
        down = (max(loss) if loss else -1) > (max(gain) if gain else -1)
        more_is_worse = down
        return ("worse" if more_is_worse else "better") if how == "more" else ("better" if more_is_worse else "worse")
    return "ahead" if how == "more" else "behind"


def _order_backed(claims: list[dict], a: str, b: str, how: str, metric: str = "pct") -> bool:
    """Is "a <how> b" (better / worse; ahead / behind in a ranking with no good end) what a claim of the comparison's
    metric says (one claim ranking both, or a in a best claim and b in a worst claim of the same kind and metric)?"""
    cs = [c for c in claims if _metric_fits(c, metric)]
    for c in cs:
        s = c["subjects"]
        if a in s and b in s:
            first = s.index(a) < s.index(b)
            pol = c["polarity"]
            if how == "better" and ((pol == "best" and first) or (pol == "worst" and not first)):
                return True
            if how == "worse" and ((pol == "worst" and first) or (pol == "best" and not first)):
                return True
            if how == "ahead" and first and pol is None:
                return True
            if how == "behind" and not first and pol is None:
                return True
    if how not in ("better", "worse"):
        return False
    top = "best" if how == "better" else "worst"
    bottom = "worst" if top == "best" else "best"
    ka = [c for c in cs if c["polarity"] == top and a in c["subjects"]]
    kb = [c for c in cs if c["polarity"] == bottom and b in c["subjects"]]
    return any(x["kind"] == y["kind"] and x.get("metric") == y.get("metric") and not x["within"] and not y["within"]
               for x in ka for y in kb)


def comparison_reasons(claims: list[dict], cls: list[tuple[str, list]]) -> list[str]:
    """Two named tickers / sectors compared ("$MSFT did better than $AAPL", "...$CRWV was worse.") need a claim of that
    metric that ranks them that way. cls: (clause, entities) in post order."""
    out = []
    prev: list = []
    for cl, ents in cls:
        metric = _cmp_metric(cl)
        for m in COMPARE.finditer(cl):
            how = _cmp_how(m, cl)
            after = [e for e in ents if e[0] >= m.end() and e[0] - m.end() <= 25]
            if not after:
                continue
            b = after[0]
            before = [e for e in ents if e[0] < m.start() and e[3] == b[3]]
            if not before:
                continue
            a = before[-1]
            if a[2] != b[2] and not {a[2], b[2]} & BENCHMARK and not _order_backed(claims, a[2], b[2], how, metric):
                out.append(f"unsupported comparison: \"{a[2]} {m.group(0)} {b[2]}\" ({'dollars' if metric == 'usd' else metric}) "
                           "- no claim of the item ranks them so in that measure")
        me = COMPARE_END.search(cl)
        if me and prev:
            how = "worse" if me.group("w").lower() in ("worse", "weaker") else "better"
            own = [e for e in ents if e[0] < me.start()]
            if own:
                a = own[-1]
                bs = [e for e in prev if e[3] == a[3] and e[2] != a[2] and e[2] not in BENCHMARK]
                if bs and a[2] not in BENCHMARK and not _order_backed(claims, a[2], bs[-1][2], how, metric):
                    out.append(f"unsupported comparison: \"{a[2]} was {me.group('w')}\" than {bs[-1][2]} - no claim of "
                               "the item ranks them so")
        if ents:
            prev = ents
    return out


# Rank numbers (r4): "#3 by dollar drop", "No. 15 by market cap", "the 15th-biggest dollar drop" state a rank: it must be
# the item's rank of that company for that measure (rank_by_usd / rank_by_cap, or its place in a dollar-move claim).
_RANK_METRIC = (r"(?P<m>market\s+(?:cap(?:italization)?|value)(?:\s+(?:lost|loss|drop|decline|gained|gain|change|move"
                r"|wiped))?|size|valuation|dollars?(?:[\s-]+(?:drops?|loss(?:es)?|lost|declines?|falls?|moves?|changes?"
                r"|gains?|gained|terms))?|percent(?:age)?(?:[\s-]+(?:drops?|loss(?:es)?|declines?|falls?|moves?|gains?))?"
                r"|%\s+(?:drops?|loss(?:es)?|declines?|falls?|moves?|gains?))")
RANK_PHRASE = re.compile(
    r"(?:\#\s?(?P<a>\d{1,4})|\bno\.\s?(?P<b>\d{1,4})|\bnumber\s+(?P<c>\d{1,4})|\b(?P<d>\d{1,4})(?:st|nd|rd|th)"
    r"(?:[\s-]+(?:biggest|largest|most\s+valuable))?)(?![\w.,])\s*(?:(?:biggest|largest)\s+)?(?:(?:by|in|for)\s+)?"
    + _RANK_METRIC + r"\b", re.IGNORECASE)


def rank_map(item: dict, claims: list[dict]) -> dict:
    """{(ticker, "usd" | "cap", scope sector or None): (rank, direction)} the item states."""
    out = {}
    t = mk.norm_ticker(item.get("ticker")) if item.get("ticker") else None
    mv = item.get("mover") or {}
    d = ("down" if (mv.get("usd") or mv.get("pct") or 0) < 0 else "up") if mv else None
    if t and isinstance(item.get("rank_by_usd"), int):
        out[(t, "usd", None)] = (item["rank_by_usd"], d)
    if t and isinstance(item.get("rank_by_cap"), int):
        out[(t, "cap", None)] = (item["rank_by_cap"], None)
    for c in claims:
        metric = {"usd_change": "usd", "market_cap": "cap"}.get(c["metric"])
        if not metric or c["kind"] != "stock" or c.get("universe"):
            continue
        scopes = [w for w in c["within"] if canon_sector(w)] or ([None] if not c["within"] else [])
        for sc in scopes:
            for i, s in enumerate(c["subjects"]):
                out.setdefault((s, metric, sc), (i + 1, c["direction"]))
    return out


_RANK_SECTOR_AFTER = re.compile(r"^\s*(?:(?:in|of|among|within)\s+(?:the\s+)?(" + _SECTOR_ALT + r")(?![\w])"
                                r"|(?:in|of|among|within)\s+(?:its|their)\s+sector)", re.IGNORECASE)


def rank_reasons(item: dict, claims: list[dict], cls: list[tuple[str, list]]) -> list[str]:
    ranks = rank_map(item, claims)
    secmap = {mk.norm_ticker(k): canon_sector(v) for k, v in (item.get("ticker_sectors") or {}).items() if v}
    names = item_names(item)
    out = []
    last = mk.norm_ticker(item.get("ticker")) if item.get("ticker") else None
    for cl, ents in cls:
        for m in RANK_PHRASE.finditer(_norm(cl)):
            n = int(next(g for g in m.group("a", "b", "c", "d") if g))
            mt = m.group("m").lower()
            metric = ("pct" if ("percent" in mt or "%" in mt) else
                      "usd" if ("dollar" in mt or re.search(r"lost|loss|drop|decline|gain|change|move|wiped", mt)) else "cap")
            before = [e for e in ents if e[0] < m.start() and e[3] == "stock"]
            who = before[-1][2] if before else last
            # "Tech's #1 by market value", "#1 by market cap in Tech", "#2 in its sector": a rank inside that sector
            scope = None
            ps = SECTOR_POSS.search(_blank_names(cl[:m.start()], names))
            pa = _RANK_SECTOR_AFTER.match(cl[m.end():])
            if ps:
                scope = ALIAS_OF[ps.group(1).lower()]
            elif pa:
                scope = ALIAS_OF[pa.group(1).lower()] if pa.group(1) else secmap.get(who)
            got = ranks.get((who, metric, scope)) if who else None
            if metric == "pct" or got is None:
                out.append(f"rank: {m.group(0).strip()!r} - the item states no {'percent' if metric == 'pct' else metric} "
                           f"rank for ${who}{' in ' + scope if scope else ''}" + (
                               f" (it states: {', '.join(f'${k[0]} #{v[0]} by {k[1]}' + (f' in {k[2]}' if k[2] else '') for k, v in ranks.items())})"
                               if ranks else ""))
                continue
            if got[0] != n:
                out.append(f"rank: {m.group(0).strip()!r} - ${who} is #{got[0]} by "
                           f"{'dollar move' if metric == 'usd' else 'market cap'}, not #{n}")
                continue
            wd = _word_dirs(mt)
            if got[1] and wd and got[1] not in wd:
                out.append(f"rank: {m.group(0).strip()!r} - ${who}'s dollar move was {'a drop' if got[1] == 'down' else 'a gain'}")
        stocks = [e for e in ents if e[3] == "stock"]
        if stocks:
            last = stocks[-1][2]
    return out


# Elliptical follow-ups (r4): "Energy was the best sector, and so was Tech." / "Tech too." / "$MSFT and $NVDA too."
# attach new subjects to the previous clause's superlative: they are checked as part of it (a singular superlative takes
# one subject only: "the biggest dollar drop" cannot be three companies).
ELLIPSIS_W = re.compile(r"\b(?:too|as\s+well|also|likewise|ditto|same\s+(?:for|with|goes\s+for)"
                        r"|so\s+(?:was|were|did|had|is|are|has|have))\b", re.IGNORECASE)
_ELLIPSIS_FILL = re.compile(r"(?:and|so|was|were|did|had|is|are|has|have|too|also|as|well|likewise|ditto|same|for|with"
                            r"|goes|plus|the|a|on|in|of|this|that|week|weekend|session|day|both|" + WEEKDAYS + r")",
                            re.IGNORECASE)
PLURAL_HEAD = re.compile(r"\b(?:sectors|stocks|names|companies|drops|declines|losses|gains|gainers|losers|decliners|movers"
                         r"|moves|performers|winners|tickers|members|groups|matches|peers|firms|laggards|leaders)\b",
                         re.IGNORECASE)


def _elliptical(cl: str, ents: list) -> bool:
    if not ents or not ELLIPSIS_W.search(cl):
        return False
    s = cl
    for st, en, _, _ in sorted(ents, reverse=True):
        s = s[:st] + " " + s[en:]
    s = re.sub(r"[+\-−]?\$?\d[\d.,]*[%×xKMBT]?", " ", s)
    left = [w for w in re.findall(r"[A-Za-z']+", s) if not _ELLIPSIS_FILL.fullmatch(w)]
    return not left


def ellipsis_reasons(prev_cl: str, cl: str, ents: list, claims: list[dict], names: list[str], ctx: dict) -> list[str]:
    body = _prep(prev_cl)
    m = SUPER.search(body)
    head = " ".join(_words(body[m.end():])[:4]) if m else ""
    new = list(dict.fromkeys(f"${e}" if k == "stock" else e for _, _, e, k in ents))
    if not PLURAL_HEAD.search(head):
        return [f"unsupported comparison: \"{cl.strip()[:60]}\" adds {', '.join(new)} to \"{prev_cl.strip()[:70]}\" - "
                "only one subject can be the #1 for a singular superlative; state each true claim on its own"]
    synth = prev_cl.rstrip(" .!?") + ", " + ", ".join(new) + "."
    sub = dict(ctx, ents=entities(synth, ctx["nmap"], names), ref=None)
    return _clause_reasons(synth, claims, names, sub)


def claim_reasons(item: dict, text: str) -> list[str]:
    """REJECT reasons for comparative / superlative wording the item's claims do not back."""
    claims = [claim_view(c) for c in item.get("claims") or [] if isinstance(c, dict)]
    names = item_names(item)
    nmap = name_map(item)
    secmap = {mk.norm_ticker(k): canon_sector(v) for k, v in (item.get("ticker_sectors") or {}).items() if v}
    norm = _norm(text or "")
    ctx = {"item": item, "text": norm, "secmap": secmap, "sector": None, "nmap": nmap,
           "moves": (item.get("moves") or item_moves(item)).get("subjects") or {}}
    seq = []   # (sentence, clause, entities) in post order
    for sent in SENTENCE.split(norm):
        if sent.strip():
            for cl in claim_clauses(sent, names):
                seq.append((sent, cl, entities(cl, nmap, names)))
    out, last_sup = [], None
    for i, (sent, cl, ents) in enumerate(seq):
        ctx["sentence"], ctx["ents"] = sent, ents
        ref = _reference(cl) if superlatives(cl) else None
        if superlatives(cl) and not ents and QUIZ.search(cl.strip()):
            ref = "quiz"    # "Which company lost the most dollars on Friday? $GOOGL.": the answer that follows
        inherit = {}
        if ref:
            for kind in ("stock", "sector"):
                before = [e[2] for _, _, es in seq[:i] for e in es if e[3] == kind]
                after = [e[2] for _, _, es in seq[i + 1:] for e in es if e[3] == kind]
                inherit[kind] = (after[0] if after else None) if ref == "quiz" else (before[-1] if before else None)
        ctx["ref"], ctx["inherit"] = ref, inherit
        if superlatives(cl):
            if not _reader_question(cl, ents):
                out += _clause_reasons(cl, claims, names, ctx)
            last_sup = cl
        elif last_sup and _elliptical(cl, ents):
            out += ellipsis_reasons(last_sup, cl, ents, claims, names, dict(ctx))
        secs = [e[2] for e in ents if e[3] == "sector"]
        secs = list(dict.fromkeys(secs))
        if len(secs) == 1:
            ctx["sector"] = secs[0]
        elif len(secs) > 1:
            ctx["sector"] = None
    pairs = [(cl, ents) for _, cl, ents in seq]
    if claims:  # an item with no ranking claims (an earnings card, a Form 4) was never ranked: nothing to compare with
        out += comparison_reasons(claims, pairs)
    out += rank_reasons(item, claims, pairs)
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# 2b. Comparisons: an ALLOWLIST (HQ decision 2026-10-18 after four review rounds: a denylist of ranking wordings cannot
# converge - synonyms, order words, polarity guesses, scope / window stretching, pairs, lists, ratios, streaks).
#
# facts.py / market_facts.py give each item `claim_phrases`: short complete sentences, generated from the data, that state
# every comparison / ranking / direction relation the item backs, with exact numbers, window and scope
# ("Technology was the worst sector in the week to Oct 16 (−7.3%).", "$MSFT had the second-biggest dollar drop among the
# 500 largest US-listed companies on Friday (−$77.2B).").
# A post sentence that carries ANY ranking / comparison / superlative / order / quantifier / streak / record / ratio /
# window-stretch language (RANK_LANGUAGE, read broadly) passes only when it IS one of those phrases (after normalising
# case, whitespace, punctuation, "$" on cashtags, minus signs, "×" and sector aliases: "Tech" = "Technology"), or
# contains phrases verbatim with nothing around them but neutral connective words (NEUTRAL: "and", "also", "so", ...).
# Everything else in such a sentence - an extra number, a name, a scope word - rejects it. A question to the reader that
# names no company, sector or number ("Which move surprised you most?") asserts nothing and is exempt. Plain sentences
# with no such language keep the other checks (numbers, direction, window, sector, card, universe).

_EST_OK = {
    "interest", "invest", "honest", "request", "suggest", "digest", "harvest", "forest", "contest", "protest",
    "manifest", "modest", "earnest", "arrest", "guest", "chest", "nest", "pest", "vest", "quest", "rest", "test", "west",
    "zest", "jest", "lest", "crest", "behest", "conquest", "inquest", "bequest", "unrest", "midwest", "priest", "attest",
    "detest", "infest", "divest", "wrest", "everest", "pretest", "backtest", "retest", "latest", "southwest",
    "northwest", "tempest", "congest", "ingest", "reinvest", "disinterest", "celest", "fest", "pinterest",
}
_DAYS_W = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_NUMW_ALL = r"\d[\d,]*|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|sixty|ninety"
# definitions and idioms that are not comparisons: blanked before RANK_LANGUAGE is read
RANK_IDIOMS = re.compile(
    r"\btrack\s+record\b|\bbest\s+minus\s+worst\b|\bat\s+(?:least|most)\b"
    r"|\b(?:first|second|third|fourth|1st|2nd|3rd|4th)[\s-]+(?:quarter|half|comment|reply|post|look)s?\b"
    r"|\bfirst\s+(?:session|trading\s+day)\s+after\b"
    r"|\bnext\s+(?:session|trading\s+day|week|month|quarter|earnings|reports?|" + _DAYS_W + r")\b"
    r"|\b(?:double|triple)[\s-]+(?:tops?|bottoms?)\b|\btop\s+line\b|\bbottom\s+line\b|\bon\s+top\s+of\s+that\b"
    r"|\blead\s+(?:independent\s+)?directors?\b"
    r"|\b(?:every|all)\s+(?:company|companies|stock|stocks)\s+on\s+(?:one|a\s+single|the|our)\s+(?:map|page)\b"
    r"|\bahead\s+of\s+(?:its\s+|their\s+|the\s+|this\s+|next\s+)?(?:earnings|results|reports?|prints?|calls?|open|opening"
    r"\s+bell|bell|week|session|" + _DAYS_W + r")\b"
    r"|\b(?:the\s+)?(?:week|days|session|month)\s+ahead\b|\bwhat['’]?s\s+ahead\b"
    r"|\blast\s+(?:week|weekend|session|sessions|close|closes|trading\s+days?|night|" + _DAYS_W + "|" + _NUMW_ALL + r")\b"
    r"|\b(?:learn|read|see|find\s+out)\s+more\b|\band\s+more\b|\bmore\s+(?:on|at|in|here|below|details|info)\b"
    r"|\brather\s+than\b|\bas\s+well\s+as\b"
    # product / calendar idioms found in our own honest posts (backtest 2026-10-18, N=162 texts)
    r"|\bthird[\s-]party\b|\bearnings[\s-]history\b|\bnext\s+up\b|\bnext\s+on\s+(?:the|our)\s+calendar\b"
    r"|\b(?:pull|cover|post|watch|track|check|look\s+at)\s+next\b|\+\s?\d[\d,]*\s+more\b|\bplus\s+more\b"
    r"|\b(?:bought|buys|buying|added|adds|adding)\s+more(?:\s+shares|\s+stock)?\b(?!\s+than)"
    r"|\bevery\s+(?:pick|filing|report|post|chart|card|page)s?\b"
    r"|(?:^|[,:;(]\s*)every\s+(?:us\s+)?(?:trading\s+)?(?:day|weekday)\b"
    r"|\ball\s+(?:report|reported|reporting|have\s+earnings|are\s+reporting|report\s+earnings)\b"
    r"|\ball\s+(?:of\s+)?(?:his|her|their|its|our|the)\s+(?:trades|filings|disclosures|picks|reports|details|numbers|data"
    r"|charts?|holdings|transactions|sources|sessions|companies|stocks)\s*(?::|on\b|in\b|at\b|here\b|below\b)"
    # our universe and basket by name ("The 500 largest US-listed stocks fell", "Owning the 10 largest", "60 of the 500
    # largest ... report"), never membership ("one of / among / in / joined the 10 largest" stays a ranking claim)
    r"|(?<!\bone of )(?<!\bamong )(?<!\bin )(?<!\binto )(?<!\bof )(?<!\bjoined )(?<!\bentered )(?<!\binside )"
    r"(?<!\bwithin )(?<!\bto )\bthe\s+(?:500|10|ten)\s+largest\b(?:\s+us-listed\b)?"
    r"|\b\d[\d,]*\s+of\s+the\s+(?:500|10|ten)\s+largest\b(?:\s+us-listed\b)?", re.IGNORECASE)
_RANK_PARTS = (
    r"(?P<est>\b[a-z]{2,}est\b)",
    r"\b(?:best|worst|most|least|utmost|foremost|topmost)\b",
    r"\b[a-z]+er\s+than\b|\b(?:more|less|fewer)\b",
    r"\b(?:worse|better|bigger|smaller|larger|greater|stronger|weaker|hotter|colder|harder|rougher|tougher|steeper"
    r"|sharper|deeper|heavier|faster|slower|wider|outsized|further|farther)\b",
    r"\btop(?:s|ped|ping)?\b|\b(?:lead|leads|leading|leader|leaders|leadership|led)\b",
    r"\bbeat(?:s|ing|en)?\b|\bout(?:perform|pac|did|do|does|doing|shin|shone|run|ran|strip|gain|class|number|sold)\w*"
    r"|\bunderperform\w*|\btrail(?:s|ed|ing)?\b|\blag(?:s|ged|ging|gard|gards)?\b|\bbested\b|\beclips\w*|\bsurpass\w*"
    r"|\bexceed\w*|\bovert(?:ake|akes|ook|aken|aking)\b|\bedged\s+out\b",
    r"\brank\w*|#\s?\d+\b|\bno\.\s?\d+\b|\bnumber[\s-]+(?:one|two|three|1|2|3)\b|\b\d+(?:st|nd|rd|th)\b",
    r"\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b|\brunner[\s-]?up\b|\bnext\b"
    r"|\bfollowed\s+by\b|(?P<then>\bthen\b)|\bbehind\b|\bahead\b|\bin\s+that\s+order\b|\brespectively\b",
    r"\b(?:only|sole|solely|lone)\b|\b(?:every|everyone|everything|everybody|all|none|nobody|nothing|anyone|anybody"
    r"|anything)\b|\bno\s+(?:other|one|sector|sectors|stock|stocks|company|companies|name|names|ticker|single)\b"
    r"|\bnot\s+(?:one|a\s+single)\b|\bany\s+other\b|\bof\s+any\b",
    r"\brecords?\b|\bever\b|\bstreaks?\b|\bin\s+a\s+row\b|\bsince\b|\bstraight\b|\bconsecutive\w*"
    r"|\b(?:days?|sessions?|weeks?|times?|years?|months?)\s+running\b|\bagain\b|\blately\b|\brecently\b"
    r"|\bin\s+a\s+while\b|\bin\s+(?:weeks|months|years|decades)\b"
    r"|\bthis\s+(?:fall|autumn|spring|summer|season|year|month|quarter|decade)\b"
    r"|\ball[\s-]time\b|\b52[\s-]week\b|\byear[\s-]to[\s-]date\b|\bytd\b|\bmulti[\s-]year\b|\bdecades?\b"
    r"|\bhistor(?:y|ic|ical)\b|\bunprecedented\b|\b(?:new|fresh)\s+(?:highs?|lows?)\b"
    r"|\bof\s+the\s+(?:year|month|quarter|decade|century)\b|\bin\s+(?:\d+|two|three|four|five|six|several|many)\s+"
    r"(?:days|sessions|weeks|months|years)\b|\bfor\s+(?:\d+|two|three|four|five|six|seven|eight|nine|ten)\s+(?:days"
    r"|sessions|weeks|months)\b",
    r"\b(?:doubl\w*|tripl\w*|quadrupl\w*|twice|thrice|half|halved|halves|combined)\b"
    r"|(?:\d[\d.,]*\s*(?:x|×)|\b\d[\d.,]*\s+times|\b(?:two|three|four|five|six|seven|eight|nine|ten)\s+times)\s+(?:more"
    r"|less|bigger|larger|smaller|higher|lower|as|than|what|the|that|its\s+peers?)\b",
    r"\b(?:winners?|losers?|gainers?|won|wins?|winning|champion\w*|crown\w*|mvp|podium|medal\w*|bronze|dominat\w*|ruled"
    r"|reign\w*|sweep|swept|outnumber\w*|stand[\s-]?outs?|stood\s+out|stands\s+out|twins?|doppelg\w+)\b|\bking\s+of\b"
    r"|\bqueen\s+of\b",
    r"\b(?:last|bottom|rear|tail[\s-]end)\b",
    r"\bmiss(?:ed|es|ing)?\b|\b(?:fell|came\s+in)\s+short\b|\bshort\s+of\b|\bin[\s-]line\b"
    r"|\b(?:above|below)\s+(?:the\s+)?(?:estimates?|consensus|expectations?|forecasts?|guidance|views?|street)\b",
    r"\bas\s+(?:much|many|big|large|hard|far|bad|good|strong|weak|high|low|fast|steep|sharp|badly)\s+as\b",
)
RANK_LANGUAGE = re.compile("|".join(_RANK_PARTS), re.IGNORECASE)
# round 2 review: no weekday, "morning" or "weekend" here ("Friday, Oct 15 was the strongest up day ...", "... on Friday and
# Thursday morning" widened a phrase); a "Monday recap:" label opening the sentence is dropped first (LEAD_LABEL)
NEUTRAL = {"and", "but", "also", "so", "plus", "meanwhile", "while", "yet", "note", "notably", "fact", "fun", "recap",
           "data", "why", "it", "matters", "the", "on", "map", "chart", "card", "here", "is", "this", "quick", "look",
           "check", "in", "short", "numbers", "update", "briefing", "reminder", "read"}
# a label opening a sentence ("Monday recap:", "Friday morning briefing -", "Happy Monday!"): dropped before the phrase and
# vocabulary checks (the window rule still reads its weekday)
LEAD_LABEL = re.compile(r"^\s*(?:(?:happy|good)\s+)?(?:(?:" + _DAYS_W + r")(?:['’]s)?\s+)?(?:morning\s+)?"
                        r"(?:recap|update|briefing|brief|rundown|read|notes?|reminder|morning)?\s*[:!–—-]\s+", re.IGNORECASE)
_TOKEN = re.compile(r"[+-]?\$?\d[\d,]*(?:\.\d+)?(?:%|x|[kmbt](?![a-z]))?|[a-z0-9]+(?:'[a-z]+)?")


_THEN_RANK = re.compile(r"[\s,:]*(?:\$[A-Za-z]|#|[+-]?\$?\d|(?:" + _SECTOR_ALT + r")(?![\w])|came\b|comes\b|was\b"
                        r"|were\b|is\b|are\b|ranked\b|followed\b|in\s+(?:second|third|fourth)\b|the\b)", re.IGNORECASE)


def _starts_entity(rest: str, nmap: dict | None, names: list[str] | None) -> bool:
    """`rest` opens (after spaces / commas) with a company named in words."""
    if not nmap:
        return False
    head = re.match(r"[\s,:]*", rest).end()
    return any(st == head for st, _, _, _ in entities(rest[:head + 40], nmap, names or []))


def rank_words(text: str, names: list[str] | None = None, nmap: dict | None = None) -> list[str]:
    """The ranking / comparison words of `text` (company names and idioms blanked first)."""
    base = re.sub(r"https?://\S+", lambda m: " " * len(m.group(0)), _norm(text))   # positions kept
    s = _blank_names(base, names or [])
    s = RANK_IDIOMS.sub(lambda m: " " * len(m.group(0)), s)
    out = []
    for m in RANK_LANGUAGE.finditer(s):
        w = m.group(0)
        if m.group("est") and w.lower() in _EST_OK:
            continue
        if m.group("then") and not _THEN_RANK.match(base[m.end():]) and not _starts_entity(base[m.end():], nmap, names):
            continue   # "then graded", "then fell": a sequence of events; "then $MSFT", "then Tech", "then -$77.2B" rank
        out.append(re.sub(r"\s+", " ", w.strip()))
    return list(dict.fromkeys(out))


def phrase_tokens(s: str) -> list[str]:
    """A sentence as comparison tokens: lower case, sector aliases as their canonical name, "$" off cashtags, minus signs
    as "-", "×" as "x", punctuation dropped (a sign or "$" glued to a number stays part of it)."""
    s = _norm(s).replace("’", "'").replace("×", "x")
    s = re.sub(r"[–—](?=\$?\d)", "-", s)   # an en / em dash before a number is a minus sign
    s = SECTOR_WORD.sub(lambda m: ALIAS_OF[m.group(1).lower()], s)
    s = re.sub(r"\$(?=[A-Za-z])", "", s).lower()
    s = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", s)
    return _TOKEN.findall(s)


def _phrase_match(sent: list[str], phrases: list[list[str]], extra: frozenset = frozenset()) -> bool:
    """The sentence is one phrase, or phrases with only NEUTRAL (or the item's `extra`) words around them."""
    if not sent:
        return False
    if any(sent == p for p in phrases):
        return True
    rest, found = list(sent), False
    for p in sorted(phrases, key=len, reverse=True):
        n = len(p)
        if not n:
            continue
        i = 0
        while i + n <= len(rest):
            if rest[i:i + n] == p:
                rest[i:i + n] = ["\x00"]
                found = True
            i += 1
    return found and all(t == "\x00" or t in NEUTRAL or t in extra for t in rest)


# An earnings result is about one company: its own name, ticker and fiscal label may stand around a phrase too
# ("$UNH Q3 results are out: revenue $112.7B vs $111.49B consensus (beat by $1.21B)."). Never on a multi-company item
# ("... and Microsoft" would add a subject).
_EARNINGS_LEAD = {"results", "are", "out", "earnings", "report", "reports", "posted", "published"}


def _extra_words(item: dict) -> frozenset:
    if item.get("type") != "earnings_result":
        return frozenset()
    words = set(_EARNINGS_LEAD)
    for v in (item.get("ticker"), item.get("name"), item.get("fiscal_label")):
        if isinstance(v, str):
            words |= {w for w in phrase_tokens(v)
                      if (len(w) >= 2 and not re.search(r"\d", w)) or re.fullmatch(r"q[1-4]|fy\d{4}|\d{4}", w)}
    return frozenset(w for w in words if not RANK_LANGUAGE.search(w))


_NUM_PAREN_END = re.compile(r"\s*\(\s*[+\-−]?\$?\d[\d.,]*(?:%|[KMBT]|×|x)?\s*\)(?=\.?\s*$)")


def item_phrases(item: dict) -> list[str]:
    """The item's claim phrases, each also without a closing parenthesised number ("Tech was the worst sector on Friday."
    for "... on Friday (−2.8%)."): the number backs the relation, leaving it out changes nothing. A parenthesis that
    words a scope or metric ("(by market value, confirmed dates)", "(+1,212 stocks up minus down)") always stays."""
    out = []
    when = str(item.get("when") or "")
    for p in item.get("claim_phrases") or []:
        if isinstance(p, str) and p.strip():
            forms = [p.strip()]
            if when.startswith("in the week to ") and when in p:
                forms.append(p.strip().replace(when, "last week"))   # posted the Monday after (window rule allows it)
            for f in forms:
                out.append(f)
                bare = _NUM_PAREN_END.sub("", f)
                if bare != f:
                    out.append(bare if bare.endswith(".") else bare + ".")
    return list(dict.fromkeys(out))


def short_text(s: str, n: int = 90) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


# an elliptical add-on right after a sentence with ranking language ("Tech too.", "And $MSFT.", "So was Energy.")
ELLIPSIS = re.compile(r"\b(?:too|as\s+well|also|likewise|ditto|same\s+(?:for|with|goes|here|story)|so\s+(?:was|were|did|had"
                      r"|is|are|does)|neither|nor|either)\b|^\W*(?:and|plus|or|nor)\b", re.IGNORECASE)


def allowlist_reasons(item: dict, text: str) -> list[str]:
    """REJECT reasons for sentences that are not the item's claim_phrases and either carry ranking / comparison language
    (RANK_LANGUAGE) or any word outside the plain vocabulary (section 2c: post_vocab.VOCAB; round 2 review: the ranking
    word list alone let "Energy alone rose", "the rest fell", "took gold", "kept falling", "matched" through)."""
    names = item_names(item)
    nmap = name_map(item)
    phrases = [phrase_tokens(p) for p in item_phrases(item)]
    extra = _extra_words(item)
    out, prev_rank, prev_quiz = [], False, False
    for sent in post_sentences(text):
        body = LEAD_LABEL.sub("", sent, count=1)
        words = rank_words(body, names, nmap)
        unknown = vocab_unknown(item, body, names, nmap)
        after, quiz = prev_rank, prev_quiz
        prev_rank, prev_quiz = bool(words), False
        if not words and not unknown:
            add = ELLIPSIS.search(body) if after else None
            if add:   # "Energy was the best sector on Friday (+2.6%). Tech too." adds Tech to the ranking (r4 review)
                out.append(f"unsupported comparison: {short_text(sent.strip())!r} adds to the comparison before it "
                           f"({add.group(0).strip()!r}) - a claim phrase states its subjects; write the next fact on its own")
            elif quiz and entities(body, nmap, names):
                # "Do you know which stock fell most? $MSFT.": the answer makes the question a claim
                out.append(f"unsupported comparison: {short_text(sent.strip())!r} answers the ranking question before it "
                           "- for any comparison copy one of the item's claim_phrases verbatim")
            continue
        if _phrase_match(phrase_tokens(body), phrases, extra):
            continue
        st = body.strip()
        if (st.endswith("?") and re.search(r"\byou(?:r|rs|['’]re)?\b", st, re.IGNORECASE) and not re.search(r"\d", st)
                and not entities(st, nmap, names)):
            prev_quiz = True
            continue   # a question to the reader that names nothing asserts nothing (until a sentence answers it)
        if words:
            hint = (" - this item has no claim_phrases: say it without comparing or ranking" if not phrases else
                    " - for any comparison, ranking, order, 'only' / 'all', record, streak or ratio copy one of the item's "
                    "claim_phrases verbatim (its own sentence)")
            out.append(f"unsupported comparison: {short_text(sent.strip())!r} uses {', '.join(repr(w) for w in words[:4])}"
                       f"{hint}")
        else:
            out.append(f"wording: {short_text(sent.strip())!r} uses {', '.join(repr(w) for w in unknown[:5])}, outside the "
                       "plain post vocabulary - a sentence that is not one of the item's claim_phrases may use only plain "
                       "words (the item's names, numbers and window, rose / fell / up / down, reported, filed, bought, "
                       "sold, ...): say it plainly or copy a claim phrase verbatim")
    return out


# ---------------------------------------------------------------------------
# 2c. The plain vocabulary and number / direction binding (HQ round 2 review 2026-10-19)
#
# A sentence that is not a claim phrase passes only when nothing is left after removing the item's entities (cashtags,
# company / person names, sectors, "the 500 largest US-listed stocks", "the 10 largest", "US stocks RapidTradeView
# tracks"), its numbers and dates, its idioms and a closed list of plain words (post_vocab.VOCAB). Any other word, a
# number word, or one of > < = sends it to the claim-phrase check.
# Plain sentences are then bound to the data (binding_reasons):
#   - every signed / percent / dollar / ratio number, "Sync N" and "N mentions" belongs to the nearest entity before it
#     in its sentence (or the one it is "for" / "of", or the one after it in the clause, or - after "it" / "the stock" -
#     the entity named last before), and must be one of that entity's numbers in the item (`subject_numbers`, read from
#     the item's own facts_text and claim phrases): "$MSFT +2.03%" when +2.03% is $AAPL's is rejected;
#   - every direction word (post_vocab.DIRECTION_UP / DOWN) belongs to the entities named since the previous one (or,
#     at the head of a sentence / before ":", to those after it; after "it" / "the stock", to the entity named last) and
#     must match each one's move in the item (`moves.subjects`), or - for a subject with no known move - the sign of a
#     number beside it; a direction word with no subject the data backs is rejected, and so is any negated move.

# sentences for the vocabulary and binding reading: no split after a middle initial ("Robert C. Pohlad") or a title /
# company abbreviation ("Rep. Salazar", "PepsiCo, Inc. director")
POST_SENTENCE = re.compile(r"(?<=[.!?])(?<![Nn]o\.)(?<!\s[A-Z]\.)(?<!\bRep\.)(?<!\bSen\.)(?<!\bInc\.)(?<!\bCorp\.)"
                           r"(?<!\bCo\.)(?<!\bLtd\.)(?<!\bJr\.)(?<!\bSr\.)(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)"
                           r"(?<!\bSt\.)(?<!\bvs\.)(?<!\bU\.S\.)(?<!\bN\.V\.)(?<!\bS\.A\.)\s+|\n+")


def post_sentences(text: str) -> list[str]:
    """The text's sentences (POST_SENTENCE), each also split at ";" (a phrase never holds one)."""
    return [x for s0 in POST_SENTENCE.split(_norm(html.unescape(text or ""))) for x in s0.split(";") if x.strip()]


_PSEUDO = (
    ("#U500", re.compile(r"\b(?:the\s+)?500\s+largest(?:\s+us-listed)?(?:\s+(?:stocks|companies|names))?(?![\w-])",
                         re.IGNORECASE)),
    ("#B10", re.compile(r"\b(?:the\s+)?10\s+largest(?:\s+us-listed)?(?:\s+(?:stocks|companies|names))?(?![\w-])",
                        re.IGNORECASE)),
    ("#TRACKED", re.compile(r"\b(?:(?:the\s+)?us\s+)?(?:stocks|names|tickers)\s+(?:that\s+)?"
                            r"(?:rapidtradeview|we)\s+tracks?\b|\b(?:the\s+)?us\s+stocks\b", re.IGNORECASE)),
)
_SCOPE_BEFORE = re.compile(r"\b(?:of|among|in|within|inside|into|across|from)\s*$", re.IGNORECASE)
_TICK_SCOPE = re.compile(r"(?<!\bshares )(?<!\bstock )(?<!\bpurchase )(?<!\bsale )(?<!\bbuy )\b(?:of|among|within)\s*$",
                         re.IGNORECASE)
_SECTOR_MOD = re.compile(r"\s+(?:dollar\s+)?(?:stocks?|names?|compan(?:y|ies)|tickers?|shares?|losers?|gainers?|drops?"
                         r"|declines?|movers?|members?|peers?|sector)\b", re.IGNORECASE)
_DATE_RX = re.compile(r"\b(?:" + _MONTHS + r")\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b|\b\d{4}-\d{2}-\d{2}\b"
                      r"|\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", re.IGNORECASE)
_URL_RX = re.compile(r"https?://\S+|\b(?:www\.)?(?:rapidtradeview\.trade|rapidtradeview\.com|sec\.gov)(?:/\S*)?", re.IGNORECASE)
# arrows, medals, trophies, rockets, coloured dots / squares, check marks: a direction or a ranking without words
_SIGN_SYMBOLS = re.compile("[\u2190-\u21ff\u2b05-\u2b07\u2b95\u25b2-\u25bc\u2705\u2714\u2716\u274c\u274e"
                           "\U0001f4c8\U0001f4c9\U0001f53a\U0001f53b\U0001f3c6\U0001f947-\U0001f949\U0001f451\U0001f680"
                           "\U0001f7e0-\U0001f7eb\U0001f534-\U0001f539\U0001f44d\U0001f44e\U0001f4aa\U0001f4a5\U0001f525]")
_VOCAB_IDIOMS = re.compile("|".join(pv.IDIOMS) + r"|\bin\s+equal\s+amounts\b|\bequal[\s-]+weight(?:ed)?\b"
                           r"|\bequally[\s-]+weighted\b", re.IGNORECASE)
_WORD_RX = re.compile(r"[a-z0-9]+(?:'[a-z]+)*")
_DAYS_VOCAB = frozenset("monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu thurs fri sat sun "
                        "recap briefing rundown".split())


def _person_names(item: dict) -> list[str]:
    out = [item.get("name"), item.get("company"), item.get("office")]
    for k in ("filer", "insider", "member"):
        v = item.get(k)
        if isinstance(v, str):
            out.append(v)
    return [x for x in out if isinstance(x, str) and len(x) >= 2]


def vocab_unknown(item: dict, sent: str, names: list[str] | None = None, nmap: dict | None = None) -> list[str]:
    """Words of `sent` outside the plain vocabulary (after the item's entities, numbers, dates and idioms are removed),
    plus number words and > < = signs."""
    names = names if names is not None else item_names(item)
    nmap = nmap if nmap is not None else name_map(item)
    s = _norm(html.unescape(sent)).replace("’", "'")
    out = []
    s = _URL_RX.sub(" ", spy_blank(item.get("type"), s))   # a picks post's "vs the S&P 500 (SPY)" (section 1)
    sym = re.search(r"[<>=≥≤≠≫≪]", s) or _SIGN_SYMBOLS.search(s)
    if sym:
        out.append(sym.group(0))
    for must in [*(item.get("must_include") or []), "Not investment advice."]:
        if isinstance(must, str) and must.strip():
            s = re.sub(re.escape(must.strip().rstrip(".")), " ", s, flags=re.IGNORECASE)
    tags = {mk.norm_ticker(t).lower() for t in [*(item.get("tickers") or []), *(item.get("context_tickers") or []),
                                                 item.get("ticker")] if t}
    joined = {re.sub(r"[^a-z0-9]", "", n.lower()) for n in [*names, *nmap.keys()] if n}
    joined |= {re.sub(r"[^a-z0-9]", "", _NAME_SUFFIX.sub("", n).lower()) for n in names if n}
    for m in re.finditer(r"#(\w+)", s):
        h = m.group(1).lower()
        if not (re.search(r"\d", h) or h in pv.HASHTAGS or h in tags or h in joined):
            out.append("#" + m.group(1))
    s = re.sub(r"#\w+", " ", s)
    s = CASHTAG.sub(" ", s)
    s = _blank_names(s, [*names, *_person_names(item)])
    rx = _name_rx(nmap)
    if rx:
        s = rx.sub(" ", s)
    s = SECTOR_WORD.sub(" ", s)
    s = _VOCAB_IDIOMS.sub(" ", s)
    for _, prx in _PSEUDO:
        s = prx.sub(" ", s)
    s = _DATE_RX.sub(" ", s)
    s = re.sub(r"\b(?:last|this|past)\s+week\b", " week ", s, flags=re.IGNORECASE)   # the window rule reads these
    allowed = pv.VOCAB | _DAYS_VOCAB | pv.BY_TYPE.get(str(item.get("type")), frozenset())
    # names may be shortened ("Rep. Salazar", "R-FL", "JPMorgan Chase", "Travelers") and tickers written bare ("the public
    # picks are RTX, EROC"): the words of the item's own names and its tickers are names too (never a ranking / number
    # word: "Fifth Third", "Best Buy" keep their ranking word out)
    allowed = allowed | tags | {w for n in [*names, *_person_names(item)] for w in _WORD_RX.findall(n.lower())
                                if not RANK_LANGUAGE.search(w) and w not in pv.NUMBER_WORDS}
    for w in _WORD_RX.findall(s.lower()):
        if re.search(r"\d", w):
            continue   # numbers: allowed_numbers and binding_reasons
        base = w[:-2] if w.endswith("'s") else w
        if w in allowed or base in allowed:
            continue
        out.append(w)
    return list(dict.fromkeys(out))


# --- binding ---------------------------------------------------------------------------------------------------------

_NUM_RX = re.compile(
    r"(?P<usd>(?<![\w.])[+-]?\$\d[\d,]*(?:\.\d+)?(?:\s?[KMBT](?![a-zA-Z]))?)"
    r"|(?P<pct>(?<![\w.$])[+-]?\d[\d,]*(?:\.\d+)?\s?%)"
    r"|(?P<x>(?<![\w.$])\d[\d,]*(?:\.\d+)?\s?(?:×|x(?![a-zA-Z])))"
    r"|(?P<signed>(?<![\w.$])[+-]\d[\d,]*(?:\.\d+)?(?![\d%.,]|\s?[KMBT×x]\b))"
    r"|(?:\bsync\s+)(?P<sync>\d{1,3})\b"
    r"|(?<=\()\s*(?P<paren>\d{1,3})(?=\s*[),])"
    r"|(?P<ment>(?<![\w.$])\d[\d,]*)(?=\s+(?:reddit\s+)?mentions\b)"
    # a plain count ("840 of 2,497"): gives a direction word its sign, never bound to a subject
    r"|(?P<cnt>(?<![\w.$+-])\d[\d,]*(?:\.\d+)?(?![\d.,%]|\s?(?:[KMBT×x]\b|%)))", re.IGNORECASE)
_SCALE = {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
_REF_RX = re.compile(r"\b(?:it|its|it's|they|their|the\s+(?:stock|company|shares|sector|name|ticker)|shares)\b",
                     re.IGNORECASE)
_DIR_RX = re.compile(r"\b(?:" + "|".join(sorted(pv.DIRECTION_UP | pv.DIRECTION_DOWN, key=len, reverse=True)) + r")\b",
                     re.IGNORECASE)
# "up" / "down" that state no move: "up day", "stocks up minus down", "each up sector", "sign up", "set up"
_DIR_IDLE_AFTER = re.compile(r"^\s*(?:minus|days?|sectors?|and\s+down|or\s+down|next|front|to\s+date)\b", re.IGNORECASE)
_DIR_IDLE_BEFORE = re.compile(r"\b(?:sign|set|follow|line|pick|look|catch|wrap|round|sum|show|turn|back|stack|break"
                              r"|each|strongest|weakest|an?)\s*$", re.IGNORECASE)
_NEG_RX = re.compile(r"\bnot\b|n't\b|\bnever\b|\bno\b|\bneither\b|\bnor\b", re.IGNORECASE)
_MODAL_RX = re.compile(r"\b(?:will|would|could|may|might|should|can|must|shall)\b", re.IGNORECASE)


def _num(m: re.Match) -> tuple | None:
    """(unit, |value| in its scale, decimals, scale, sign) of a _NUM_RX match; sign 0 when unsigned."""
    kind = m.lastgroup
    raw = m.group(kind).strip()
    sign = -1 if raw.startswith("-") else 1 if raw.startswith("+") else 0
    raw = raw.lstrip("+-").replace("$", "").replace(",", "").replace("%", "").replace("×", "").strip()
    scale = 1.0
    unit = {"usd": "$", "pct": "%", "x": "x", "signed": "n", "sync": "n", "paren": "n", "ment": "n", "cnt": "c"}[kind]
    if unit == "$" and raw[-1:].isalpha() and raw[-1:].upper() in _SCALE:
        scale, raw = _SCALE[raw[-1:].upper()], raw[:-1].strip()
    if unit == "x":
        raw = raw.rstrip("xX").strip()
    try:
        v = float(raw)
    except ValueError:
        return None
    dec = len(raw.split(".")[1]) if "." in raw else 0
    return unit, v, dec, scale, sign


def _same_value(a: tuple, b: tuple) -> bool:
    """Draft number a is item number b (one may be the other rounded; signs agree when both carry one)."""
    if a[0] != b[0] or (a[4] and b[4] and a[4] != b[4]):
        return False
    av, bv = a[1] * a[3], b[1] * b[3]
    for x, y in ((a, bv), (b, av)):
        if abs(round(y / x[3], x[2]) - x[1]) < 1e-9:
            return True
    return False


def _sent_events(item: dict, sent: str, names: list[str], nmap: dict) -> list[tuple]:
    """("ent", start, end, key, scope) / ("num", start, end, value) / ("dir", start, end, "up"|"down") in text order."""
    s = sent
    ev = []
    for st, en, e, k in entities(s, nmap, names):
        lead = s[:st]
        scope = bool(_SCOPE_BEFORE.search(lead)) if k == "sector" else bool(_TICK_SCOPE.search(lead))
        if k == "sector" and _SECTOR_MOD.match(s[en:]):
            scope = True   # "the biggest Energy name", "Tech stocks": a scope, not the subject
        ev.append(("ent", st, en, e, scope))
    taken = [(st, en) for _, st, en, _, _ in ev]
    for key, prx in _PSEUDO:
        for m in prx.finditer(s):
            if any(st < m.end() and m.start() < en for st, en in taken):
                continue
            ev.append(("ent", m.start(), m.end(), key, bool(_SCOPE_BEFORE.search(s[:m.start()]))))
            taken.append((m.start(), m.end()))
    blank = _DATE_RX.sub(lambda m: " " * len(m.group(0)), s)
    blank = _VOCAB_IDIOMS.sub(lambda m: " " * len(m.group(0)), blank)   # "rising wedge", "the next session"
    for _, prx in _PSEUDO:
        blank = prx.sub(lambda m: " " * len(m.group(0)), blank)
    for m in _NUM_RX.finditer(blank):
        v = _num(m)
        if v:
            ev.append(("num", m.start(), m.end(), v))
    for m in _DIR_RX.finditer(blank):
        w = m.group(0).lower()
        if w in ("up", "down") and (_DIR_IDLE_AFTER.match(blank[m.end():]) or _DIR_IDLE_BEFORE.search(blank[:m.start()])):
            continue
        ev.append(("dir", m.start(), m.end(), "up" if w in pv.DIRECTION_UP else "down"))
    return sorted(ev, key=lambda x: (x[1], x[0] != "ent"))


def _num_subject(ev: list[tuple], i: int, sent: str, carried: str | None) -> str | None:
    """The entity a number belongs to: a parenthesis right after a name is that name's ("Energy (+2.6%)"); "N% for / of X"
    is X's; else the nearest entity before it that is not a scope ("among the 500 largest", "in Technology", "the
    biggest Energy name", "peer of $T"), the next one in its clause, or - after "it" / "the stock" - the entity named
    last."""
    st, en = ev[i][1], ev[i][2]
    after = sent[en:]
    subj_ents = [e for e in ev if e[0] == "ent" and not e[4]]
    op = sent.rfind("(", 0, st)
    if op >= 0 and ")" not in sent[op:st]:
        before = [e for e in subj_ents if e[2] <= op]
        if before and not sent[before[-1][2]:op].strip():
            return before[-1][3]
    m = re.match(r"\s*(?:\)|,)?\s*(?:for|of)\s+", after)
    if m:
        nxt = [e for e in ev[i + 1:] if e[0] == "ent" and e[1] == en + m.end()]
        if nxt:
            return nxt[0][3]
    prev = [e for e in ev[:i] if e[0] == "ent" and not e[4]]
    if prev:
        return prev[-1][3]
    seg = re.split(r"[;,.!?]", after, maxsplit=1)[0]
    nxt = [e for e in ev[i + 1:] if e[0] == "ent" and e[1] <= en + len(seg) + 1]
    if nxt:
        return nxt[0][3]
    if carried and _REF_RX.search(sent[:st]):
        return carried
    return None


def item_subject_numbers(item: dict) -> dict[str, list[list]]:
    """{subject: [[unit, value, decimals, scale, sign], ...]}: each number of the item's own facts_text and claim phrases
    bound to its entity the way binding_reasons reads a post (facts.py stores it as `subject_numbers`)."""
    names, nmap = item_names(item), name_map(item)
    out: dict[str, list] = {}
    main = mk.norm_ticker(item["ticker"]) if item.get("ticker") else None
    for text in [item.get("facts_text") or "", *(item.get("claim_phrases") or [])]:
        last = main
        for sent in post_sentences(text):
            ev = _sent_events(item, sent, names, nmap)
            for i, e in enumerate(ev):
                if e[0] == "num" and e[3][0] != "c":
                    subj = _num_subject(ev, i, sent, last)
                    if subj and list(e[3]) not in out.setdefault(subj, []):
                        out[subj].append(list(e[3]))
            ents = [e for e in ev if e[0] == "ent" and not e[4]]
            if ents:
                last = ents[-1][3]

    def put(subj, raw):
        if not subj or not isinstance(raw, (str, int, float)):
            return
        for m in _NUM_RX.finditer(_norm(str(raw))):
            v = _num(m)
            if v and v[0] != "c" and list(v) not in out.setdefault(subj, []):
                out[subj].append(list(v))

    ctx = item.get("context") or {}
    put(main, (ctx.get("last_session_move") or {}).get("pct"))
    put(main, ctx.get("market_cap"))
    put(main, item.get("subject_day_move"))
    for p0 in item.get("peers") or []:
        if isinstance(p0, dict) and p0.get("ticker"):
            put(mk.norm_ticker(p0["ticker"]), p0.get("day_move"))
            if isinstance(p0.get("sync"), int):
                put(mk.norm_ticker(p0["ticker"]), f"Sync {p0['sync']}")
    return out


def _pseudo_dirs(item: dict) -> dict[str, str]:
    out = {}
    for k in ("all_500", "cap_weighted_pct"):
        if isinstance(item.get(k), (int, float)) and item[k]:
            out["#U500"] = "up" if item[k] > 0 else "down"
    t = (item.get("totals") or {}).get("pct_change")
    if isinstance(t, (int, float)) and t:
        out["#U500"] = "up" if t > 0 else "down"
    if isinstance(item.get("mean_5d"), (int, float)) and item["mean_5d"]:
        out["#B10"] = "up" if item["mean_5d"] > 0 else "down"
    b = item.get("breadth") or {}
    if isinstance(b.get("advancers"), int) and isinstance(b.get("decliners"), int) and b["advancers"] != b["decliners"]:
        out["#TRACKED"] = "up" if b["advancers"] > b["decliners"] else "down"
    return out


_REL_RX = re.compile(r"\b(?P<w>above|below|under|over)\b(?!\s+(?:the\s+)?(?:last\s+|past\s+)?\d+\s+(?:sessions|trading\s+days"
                     r"|days|closes)\b)", re.IGNORECASE)


def chart_reasons(item: dict, text: str) -> list[str]:
    """A chart-pattern post's "above" / "below": the two prices in its clause compare that way ("closed $30.56, below the
    $34.81 neckline"), or - with fewer prices - the pattern's breakout close and key level do."""
    if item.get("type") != "chart_pattern":
        return []
    lv = item.get("levels") or {}

    def price(x):
        try:
            return float(str(x).replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            return None

    close, key = price(lv.get("breakout_close")), price(lv.get("key_level"))
    out = []
    for cl in clauses(text):
        for m in _REL_RX.finditer(cl):
            up = m.group("w").lower() in ("above", "over")
            ps = [float(x.replace(",", "")) for x in re.findall(r"\$(\d[\d,]*(?:\.\d+)?)", cl)]
            if len(ps) >= 2:
                a, b = ps[0], ps[-1]
            elif close is not None and key is not None:
                a, b = close, key
            else:
                out.append(f"chart: {short_text(cl)!r} - {m.group('w')!r} needs the two prices it compares")
                continue
            if (a > b) != up or a == b:
                out.append(f"chart: {short_text(cl)!r} - ${a:g} is not {m.group('w')} ${b:g}")
    return list(dict.fromkeys(out))


def _show(e: str) -> str:
    return {"#U500": "the 500 largest US-listed stocks", "#B10": "the 10 largest US-listed companies",
            "#TRACKED": "the US stocks RapidTradeView tracks"}.get(e) or (e if canon_sector(e) else f"${e}")


def binding_reasons(item: dict, text: str) -> list[str]:
    """Numbers and direction words of the sentences that are not claim phrases, tied to their subjects (section 2c)."""
    names, nmap = item_names(item), name_map(item)
    phrases = [phrase_tokens(p) for p in item_phrases(item)]
    extra = _extra_words(item)
    bound = item.get("subject_numbers") or item_subject_numbers(item)
    bound = {k: [tuple(v) for v in vs] for k, vs in bound.items()}
    mv = item.get("moves") or item_moves(item)
    sdir = {**(mv.get("subjects") or {}), **_pseudo_dirs(item)}
    for k, vs in bound.items():   # a subject whose numbers in the facts all carry one sign moved that way
        sg = {v[4] for v in vs if v[4] and v[0] in ("%", "$")}
        if k not in sdir and len(sg) == 1:
            sdir[k] = "up" if sg.pop() > 0 else "down"
    nsign = mv.get("numbers") or {}
    main = mk.norm_ticker(item["ticker"]) if item.get("ticker") else None
    out = []
    carried, prev_dir = main, False
    for sent in post_sentences(text):
        body = LEAD_LABEL.sub("", sent, count=1)
        ev = _sent_events(item, body, names, nmap)
        ents = [e for e in ev if e[0] == "ent" and not e[4]]
        if (_phrase_match(phrase_tokens(body), phrases, extra) or rank_words(body, names, nmap)
                or vocab_unknown(item, body, names, nmap)):
            # a claim phrase is verified as built; any other sentence with ranking or non-plain words is rejected by
            # allowlist_reasons already
            carried = ents[-1][3] if ents else carried
            continue
        st = short_text(sent.strip())
        # numbers
        for i, e in enumerate(ev):
            if e[0] != "num" or e[3][0] == "c":
                continue
            owners = {k for k, vs in bound.items() if any(_same_value(e[3], v) for v in vs)}
            if not owners:
                continue
            subj = _num_subject(ev, i, body, carried)
            if subj and subj not in owners:
                raw = body[e[1]:e[2]].strip()
                out.append(f"binding: {st!r} puts {raw} on {_show(subj)} - in the item's facts it is "
                           f"{', '.join(sorted(_show(o) for o in owners))}'s number")
        # direction words
        dirs = [i for i, e in enumerate(ev) if e[0] == "dir"]
        if dirs and _NEG_RX.search(body):
            out.append(f"direction: {st!r} negates a move - state the move as the data has it")
        if dirs and _MODAL_RX.search(body):
            out.append(f"direction: {st!r} - a move with will / would / could / may / might / should / can is a forecast; "
                       "state the session's move")
        if not dirs and prev_dir and ELLIPSIS.search(body) and ents and not any(x[0] == "num" for x in ev):
            # "Energy rose on Friday. Tech did also." / "... and so did Tech": the follow-up claims the same move
            out.append(f"direction: {st!r} carries the move of the sentence before to {_show(ents[0][3])} - state its own "
                       "move with its number")
        prev_dir = bool(dirs)
        prev_end = -1
        for j, i in enumerate(dirs):
            e = ev[i]
            stop = dirs[j + 1] if j + 1 < len(dirs) else len(ev)
            subs = [x[3] for x in ev[prev_end + 1:i] if x[0] == "ent" and not x[4]]
            if not subs:   # "Up: Energy", "Biggest dollar drops on Friday: $GOOGL", "drops ... included $AVGO"
                subs = [x[3] for x in ev[i + 1:stop] if x[0] == "ent" and not x[4]]
            if not subs and carried and _REF_RX.search(body[:e[1]]):
                subs = [carried]
            # the number the word governs: the first one after it (before the next name / direction word), else the
            # last one before it in its own group ("1,631 of 2,497 ... fell", "Energy rose 2.6% ... and Tech fell 2.8%")
            nxt = next((k for k in range(i + 1, len(ev)) if ev[k][0] in ("ent", "dir")), len(ev))
            grp0 = max([prev_end] + [k for k in range(prev_end + 1, i) if ev[k][0] == "ent"])

            def signed(xs):
                for x in xs:
                    raw = body[x[1]:x[2]].strip()
                    sg = "+" if x[3][4] > 0 else "-" if x[3][4] < 0 else nsign.get(raw.lstrip("+-"))
                    if sg:
                        return sg
                return None

            grp_ents = [x for x in ev[prev_end + 1:i] if x[0] == "ent" and not x[4]]
            sign = (signed([x for x in ev[i + 1:nxt] if x[0] == "num"][:1])
                    or signed([x for x in ev[grp0 + 1:i] if x[0] == "num"])
                    or (signed([x for x in ev[prev_end + 1:i] if x[0] == "num"])   # "840 of 2,497 US stocks ... rose"
                        if all(x[3].startswith("#") for x in grp_ents) else None))
            want = e[3]
            word = body[e[1]:e[2]]
            if sign and (sign == "+") != (want == "up"):
                out.append(f"direction: {st!r} - {word!r} beside a number that is a "
                           f"{'gain' if sign == '+' else 'loss'} in the item's facts")
            if not subs and not sign:
                d = sdir.get(main) if main else None
                if d is None:
                    out.append(f"direction: {st!r} - {word!r} says something moved, but the sentence names no "
                               "company or sector whose move the item gives (name it, with its number)")
                elif d != want:
                    out.append(f"direction: {st!r} - ${main} {'rose' if d == 'up' else 'fell'} in the item's facts")
            for s0 in subs:
                d = sdir.get(s0)
                if s0.startswith("#") and sign:
                    continue   # a count's own sign ("840 of 2,497 ... rose") decides for the group
                if d is None:
                    if not sign:
                        out.append(f"direction: {st!r} - the item gives no move for {_show(s0)}; {word!r} is not backed")
                elif d != want:
                    out.append(f"direction: {st!r} - {_show(s0)} {'rose' if d == 'up' else 'fell'} in the item's facts")
            prev_end = i
        if dirs:
            # names after the last direction word with no number of their own share it ("Energy rose, and so did Tech")
            last_d = ev[dirs[-1]]
            tail = ev[dirs[-1] + 1:]
            for k, x in enumerate(tail):
                if x[0] != "ent" or x[4]:
                    continue
                nxt_e = next((j for j in range(k + 1, len(tail)) if tail[j][0] == "ent"), len(tail))
                if any(y[0] == "num" for y in tail[k + 1:nxt_e]):
                    continue
                d = sdir.get(x[3])
                if d is not None and d != last_d[3]:
                    out.append(f"direction: {st!r} - {_show(x[3])} {'rose' if d == 'up' else 'fell'} in the item's facts")
        if ents:
            carried = ents[-1][3]
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# 3. Sector attribution

def sector_reasons(item: dict, text: str) -> list[str]:
    secmap = {mk.norm_ticker(k): canon_sector(v) for k, v in (item.get("ticker_sectors") or {}).items() if v}
    if not secmap:
        return []
    names = item_names(item)
    out = []
    # the next clause's cashtags are borrowed only inside one sentence (HQ review r4: "Tech was the worst sector on
    # Friday. $NVDA −1.43%, $XOM +2.46%." does not put $XOM in Tech)
    cls, last = [], []
    for sent in SENTENCE.split(_norm(text or "")):
        cs = [c for c in CLAUSE.split(sent) if c and c.strip()]
        cls += cs
        last += [False] * (len(cs) - 1) + [True] if cs else []
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
        if not tags and i + 1 < len(cls) and not last[i] and cls[i + 1].lstrip().startswith("$") and not sectors_in(cls[i + 1], names):
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


# A one-session item (r4): a weekday or date other than its session's ("Tech was the worst sector on Thursday") and
# words of the posting moment ("this morning", "pre-market", "so far") misdate it: Grok posts Friday's facts on Monday.
PRESENT_W = re.compile(r"\b(?:this\s+(?:morning|afternoon|evening)|overnight|right\s+now|pre-?market|premarket|so\s+far"
                       r"|intraday|as\s+we\s+speak|at\s+the\s+moment|currently)\b", re.IGNORECASE)
# round 2 review: "Thursday morning", "Monday morning", "this Monday", "for Monday", "..., Thursday morning update" widened a
# one-session phrase; a weekday is exempt only before the open / bell ahead of it, or as a label opening a sentence
# ("Monday recap:", "Monday morning briefing -")
_DAY_EXEMPT = re.compile(r"\b(?:ahead\s+of|before|happy)\s+(?:" + "|".join(
    ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")) + r")\b"
    r"|\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:['’]s)?\s+(?:open|opening\s+bell|bell|watchlist"
    r"|setup|preview|outlook|session\s+ahead)\b"
    r"|(?:^|(?<=[.!?\n])\s*)\s*(?:(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:['’]s)?\s+(?:morning\s+)?"
    r"(?:recap|briefing|brief|update|rundown|read|catch-?up|notes?|motivation)\b|(?:monday|tuesday|wednesday|thursday"
    r"|friday|saturday|sunday)\s+morning\s*[:\-–—])"
    r"|\beyes\s+on\s+(?:monday|tuesday|wednesday|thursday|friday)\b", re.IGNORECASE | re.MULTILINE)
_ANY_DAY = re.compile(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE)
_MDAY = re.compile(r"\b(" + _MONTHS + r")\.?\s+(\d{1,2})\b(?!\s*,?\s*\d{3})", re.IGNORECASE)
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _item_dates(item: dict) -> list[str]:
    out = [str(item.get("session_date") or "")[:10]]
    out += [str(c.get("date") or "")[:10] for c in item.get("claims") or [] if isinstance(c, dict)]
    out += [str(n) for n in item.get("allowed_numbers") or [] if _ISO.match(str(n))]
    return [d for d in dict.fromkeys(out) if _ISO.match(d)]


def _session_day_words(item: dict, text: str) -> list[str]:
    if not item.get("session_date"):
        return []
    t = _norm(text)
    bad = [m.group(0) for m in PRESENT_W.finditer(t)]
    dates = _item_dates(item)
    days = {dt.date.fromisoformat(d).strftime("%A").lower() for d in dates}
    mdays = {f"{dt.date.fromisoformat(d).strftime('%b').lower()} {dt.date.fromisoformat(d).day}" for d in dates}
    blank = _DAY_EXEMPT.sub(lambda m: " " * len(m.group(0)), t)
    bad += [m.group(0) for m in _ANY_DAY.finditer(blank) if m.group(0).lower() not in days]
    for m in _MDAY.finditer(t):
        if f"{m.group(1).lower()[:3]} {int(m.group(2))}" not in mdays:
            bad.append(m.group(0))
    return bad


# ---------------------------------------------------------------------------
# 6. Direction (r4): a gain / loss verb next to a number or a company / sector that moved the other way ("Energy fell
# 2.6%" on a day Energy rose 2.6%; "$GOOGL gained $105.5B"). facts.py stores each item's `moves` (item_moves): the sign
# of every number it allows with one sign only, and the direction of every company / sector it describes.

_V_UP = (r"rose|gained|jumped|climbed|rallied|added|surged|soared|advanced|rebounded|bounced|popped|spiked|grew|firmed"
         r"|recovered|ticked\s+up|moved\s+up|edged\s+(?:up|higher)|inched\s+(?:up|higher)|went\s+up"
         r"|(?:closed|ended|finished)\s+green|up|higher")
_V_DOWN = (r"fell|lost|dropped|declined|slid|slipped|dipped|sagged|eased|sank|shed|tumbled|slumped|plunged|retreated"
           r"|gave\s+(?:back|up)|erased|ticked\s+down|moved\s+down|edged\s+(?:down|lower)|inched\s+(?:down|lower)"
           r"|went\s+down|(?:closed|ended|finished)\s+red|down|lower")
_FILL = r"(?:\s+(?:by|about|nearly|roughly|almost|around|over|some|a|an|another|just|more\s+than|less\s+than|as\s+much\s+as))*"
NUM_AFTER_VERB = re.compile(r"\b(?P<v>" + _V_UP + "|" + _V_DOWN + r")\b" + _FILL
                            + r",?\s+(?P<n>[+-]?\$?\d[\d.,]*(?:%|[×x](?![a-z])|[KMBT]\b)?)", re.IGNORECASE)
VERB_AFTER_ENT = re.compile(r"^\s*(?:\([^()]*\)\s*)?(?:['’]s\s+)?(?:shares\s+|stocks?\s+|names\s+|sector\s+)?"
                            r"(?:was\s+|were\s+|is\s+|are\s+|ended\s+|closed\s+|finished\s+|traded\s+)?"
                            r"(?P<v>" + _V_UP + "|" + _V_DOWN + r")\b", re.IGNORECASE)
_UP_V = re.compile(r"^(?:" + _V_UP + r")$", re.IGNORECASE)
# r4 review: noun forms ("a $105.5B rally", "$GOOGL's 2.47% gain") and counts before their verb ("1,631 of 2,497 stocks
# rose", "65% of US stocks rose") carry a direction too
_N_UP = r"gains?|rall(?:y|ies)|jumps?|surges?|pops?|rises?|advances?|rebounds?|bounces?|climbs?|upticks?"
_N_DOWN = (r"drops?|loss(?:es)?|slides?|declines?|plunges?|falls?|sell-?offs?|slumps?|tumbles?|dips?|downturns?"
           r"|wipeouts?")
NUM_NOUN = re.compile(r"(?<![\w.,])(?P<n>[+-]?\$?\d[\d.,]*(?:%|[KMBT]\b)?)(?:\s+(?!(?:and|but|or|while|vs)\b)[A-Za-z-]+){0,2}?"
                      r"\s+(?P<w>" + _N_UP + "|" + _N_DOWN + r")\b", re.IGNORECASE)
_N_UP_RX = re.compile(r"^(?:" + _N_UP + r")$", re.IGNORECASE)
NUM_THEN_VERB = re.compile(
    r"(?<![\w.,$+-])(?P<n>\d[\d,]*(?:\.\d+)?%?)(?:\s+of\s+(?:the\s+)?[\d,]+)?"
    r"(?:\s+(?:of|the|us|u\.s\.|us-listed|listed|largest|stocks?|compan(?:y|ies)|names?|tickers?|shares?|rapidtradeview"
    r"|tracks|tracked|we|track|in|our|universe|feed|most-mentioned|mentioned|reddit|them|those|these|with|a|close|for"
    r"|oct|\d{1,2}))*"
    r"\s+(?:have\s+|had\s+|were\s+|was\s+)?(?P<v>" + _V_UP + "|" + _V_DOWN + r")\b", re.IGNORECASE)
MOVE_VERB = re.compile(r"\b(?:rose|gained|jumped|climbed|rallied|surged|soared|advanced|rebounded|fell|lost|dropped|declined"
                       r"|slid|sank|tumbled|slumped|plunged|retreated)\b", re.IGNORECASE)


def item_moves(item: dict) -> dict:
    """{"numbers": {unsigned number: "+" | "-"}, "subjects": {ticker / sector: "up" | "down"}} for one item: numbers
    the item allows with a single sign, subjects from its movers, sector lists, basket and single-subject claims (a
    subject seen both ways is left out)."""
    signs: dict[str, set] = {}
    for n in [*(item.get("allowed_numbers") or []), *(item.get("context_numbers") or [])]:
        n = _norm(str(n))
        if n[:1] in "+-" and len(n) > 1 and re.search(r"\d", n):
            signs.setdefault(n[1:], set()).add(n[0])
    # counts with a direction (r4 review: "1,631 of 2,497 stocks rose" passed): breadth fell / rose counts and the share
    # that moved with the day, the Reddit card's fell / rose counts
    b = item.get("breadth") or {}
    if isinstance(b.get("advancers"), int) and isinstance(b.get("decliners"), int):
        for n, sg in ((b["decliners"], "-"), (b["advancers"], "+")):
            for f in mk.count_forms(n):
                signs.setdefault(f, set()).add(sg)
        if isinstance(b.get("share_pct"), int):
            signs.setdefault(f"{b['share_pct']}%", set()).add("-" if b["decliners"] >= b["advancers"] else "+")
    if item.get("type") == "reddit_buzz" and isinstance(item.get("fell"), int) and isinstance(item.get("with_close"), int):
        for n, sg in ((item["fell"], "-"), (item["with_close"] - item["fell"], "+")):
            if n:
                signs.setdefault(str(n), set()).add(sg)
    nums = {k: next(iter(v)) for k, v in signs.items() if len(v) == 1}
    subj: dict[str, set] = {}

    def put(e, x):
        if e and isinstance(x, (int, float)) and x != 0:
            subj.setdefault(e, set()).add("up" if x > 0 else "down")

    for r in [item.get("mover") or {}, *(item.get("next_movers") or [])]:
        put(mk.norm_ticker(r.get("ticker")), r.get("pct"))
    for p0 in item.get("peers") or []:   # a Moves Like peer's move on the session
        dm = _norm(str((p0 or {}).get("day_move") or "")) if isinstance(p0, dict) else ""
        if re.fullmatch(r"[+-]\d+(?:\.\d+)?%", dm):
            put(mk.norm_ticker(p0.get("ticker")), float(dm.rstrip("%")))
    for r in [*(item.get("best") or []), *(item.get("worst") or [])]:
        if isinstance(r, dict):
            put(canon_sector(r.get("sector")), r.get("pct"))
    for k in ("sector_leaders", "sector_movers"):
        for r in (item.get(k) or {}).values():
            if isinstance(r, dict):
                put(mk.norm_ticker(r.get("ticker")), r.get("pct"))
    for r in item.get("basket") or []:
        if isinstance(r, dict):
            put(mk.norm_ticker(r.get("ticker")), r.get("pct_5d"))
    lead = item.get("lead") or {}
    if isinstance(lead, dict):
        put(mk.norm_ticker(lead.get("ticker")), lead.get("move"))
    # the item's own ticker: its last session (context), its earnings-reaction move
    t0 = mk.norm_ticker(item["ticker"]) if item.get("ticker") else None
    last = ((item.get("context") or {}).get("last_session_move") or {}).get("pct")
    if t0 and isinstance(last, str) and re.fullmatch(r"[+-]\d+(?:\.\d+)?%", _norm(last)):
        put(t0, float(_norm(last).rstrip("%")))
    if t0 and item.get("type") == "earnings_reaction":
        put(t0, item.get("move"))
    for c in item.get("claims") or []:
        if isinstance(c, dict) and c.get("direction") in ("up", "down") and len(c.get("subjects") or []) == 1:
            s0 = c["subjects"][0]
            e = (canon_sector(s0) or s0) if c.get("kind") == "sector" else mk.norm_ticker(s0)
            put(e, 1 if c["direction"] == "up" else -1)
    return {"numbers": nums, "subjects": {k: next(iter(v)) for k, v in subj.items() if len(v) == 1}}


def direction_reasons(item: dict, text: str) -> list[str]:
    mv = item.get("moves") or item_moves(item)
    nums, subj = mv.get("numbers") or {}, mv.get("subjects") or {}
    if not (nums or subj):
        return []
    names, nmap = item_names(item), name_map(item)
    out = []
    for cl in clauses(text):
        for m in NUM_AFTER_VERB.finditer(cl):
            up = bool(_UP_V.match(re.sub(r"\s+", " ", m.group("v"))))
            n = m.group("n").rstrip(".,")
            sign = n[0] if n[0] in "+-" else nums.get(n)
            if sign and (sign == "+") != up:
                out.append(f"direction: {m.group(0).strip()!r} - that number is a {'gain' if sign == '+' else 'loss'} "
                           "in the item's facts")
        for m in NUM_NOUN.finditer(cl):
            n = m.group("n").rstrip(".,")
            sign = n[0] if n[0] in "+-" else nums.get(n)
            up = bool(_N_UP_RX.match(m.group("w")))
            if sign and (sign == "+") != up:
                out.append(f"direction: {m.group(0).strip()!r} - that number is a {'gain' if sign == '+' else 'loss'} "
                           "in the item's facts")
        for m in NUM_THEN_VERB.finditer(cl):
            n = m.group("n")
            sign = nums.get(n)
            up = bool(_UP_V.match(re.sub(r"\s+", " ", m.group("v"))))
            if sign and (sign == "+") != up:
                out.append(f"direction: {m.group(0).strip()!r} - that count {'rose' if sign == '+' else 'fell'} in the "
                           "item's facts")
        for st, en, e, k in entities(cl, nmap, names):
            d = subj.get(e)
            m = VERB_AFTER_ENT.match(cl[en:]) if d else None
            if m and (d == "up") != bool(_UP_V.match(re.sub(r"\s+", " ", m.group("v")))):
                out.append(f"direction: {cl[st:en + m.end()].strip()!r} - {e} {'rose' if d == 'up' else 'fell'} in the "
                           "item's facts")
    return list(dict.fromkeys(out))


def content_reasons(item: dict, text: str, strip_allowed=None, allowlist: bool = True) -> list[str]:
    """Every content check of this module for one text (the validator; the facts self-check passes allowlist=False for
    the item's own facts_text: the data sheet states its rankings in its own words, a post copies a claim phrase)."""
    # comparisons: the allowlist (section 2b); claim_reasons (the round 1-4 denylist reading of `claims`) is no longer a
    # gate - `claims` stay in the facts for the direction / date reading (item_moves, _item_dates)
    # an item from a facts.json built before the allowlist (no `claim_phrases` key: posts audited against old facts) keeps
    # the reading it was published under (claim_reasons, rounds 1-4); every item facts.py builds now carries the key
    compare = [] if not allowlist else allowlist_reasons(item, text) if "claim_phrases" in item else claim_reasons(item, text)
    # numbers and direction words tied to their subjects (section 2c; the facts_text is where the ties come from)
    bind = binding_reasons(item, text) + chart_reasons(item, text) if allowlist and "claim_phrases" in item else []
    out = (index_reasons(item.get("type"), text, item_names(item)) + compare
           + sector_reasons(item, text) + card_reasons(item, text) + window_reasons(item, text)
           + direction_reasons(item, text) + bind)
    if strip_allowed is not None:
        out += scope_reasons(item, text, strip_allowed)
    return out


# ---------------------------------------------------------------------------
# 2d. Verbatim facts (HQ 2026-10-19, the gate for every item built since): free-form factual sentences cannot be validated
# safely (five review rounds: a subject after its number, "a down day", order / count words, date words beside the wrong
# number, comments unchecked, buy / sell calls). So the post text is closed by construction:
#   - a sentence with ANY factual token (a cashtag / ticker, a company or person name, a number / percent / amount / count,
#     a sector, a date / weekday / session word, a direction word, a ranking / comparison word - in short, any word
#     outside post_vocab.HOOK_WORDS) must EQUAL one of the item's pre-verified sentences: its claim_phrases or its
#     fact_phrases (facts.py / market_facts.py build both from the data and self-check each as a one-sentence post).
#     Equal after light normalisation only: case, whitespace, punctuation, "$" on cashtags, dash / minus types, "x" for
#     the times sign, sector short names (Tech = Technology); a closing "(number)" may be left off a phrase. No partial
#     match, no splicing, no extra word inside it;
#   - every other sentence is a HOOK: only HOOK_WORDS (no fact of any kind), at most HOOK_MAX_WORDS words, and the
#     banned lists still apply (no buy / sell / hold / should / will / target ... - none is a hook word);
#   - the same for self-replies and comments (a comment without an item_id may hold hooks only);
#   - "Not investment advice." (and the item's must_include) is neither: it is removed before the reading; URLs are checked
#     by the link rules and removed too; a generic hashtag (HOOK_HASHTAGS, the item type's topic hashtags) is dropped, any
#     other hashtag is a fact; emoji other than HOOK_EMOJI (arrows, chart up / down, fire, rockets, medals, colours) and
#     > < = are rejected anywhere.
# An item from a facts file built before this rule (no `fact_phrases` key) is rejected by grok_review (review round 6);
# only the Growth post audit of older posts still reads it the way it was published (content_reasons).

VERBATIM_KEY = "fact_phrases"
# A word token is ANY run of letters / digits of any script, so a Cyrillic look-alike or a CJK word is a token that matches
# no phrase and no hook word, never a gap the matcher reads past; the text is NFKC-folded first (math-bold "SELL" reads as
# "SELL"). Letters / digits no token consumed add _V_UNREAD (review round 6).
_VTOKEN = re.compile(r"[+-]?\$?\d(?:[\d,]*\d)?(?:\.\d+)?(?:%|x|[kmbt](?![a-z]))?\+?|[^\W_]+(?:'[^\W_]+)?")
_V_UNREAD = "\x00unread"
# Only full http(s) URLs are removed (review() / review_comment() check each is the item's page_url / source, or allow no
# link at all) and our bare domain WITHOUT a path; a bare "domain/path" stays in the text, so a path cannot carry words.
_V_URL = re.compile(r"https?://[^\s<>\"']+|(?<![\w@./-])(?:www\.)?(?:rapidtradeview\.trade|sec\.gov)/?(?![\w/-]|\.\w)",
                    re.IGNORECASE)


def nfkc(s: str) -> str:
    """Compatibility-folded text: math-bold / fullwidth / ligature letters as their plain letters."""
    return unicodedata.normalize("NFKC", s or "")
_V_DISCLAIMER = re.compile(r"\bnot\s+investment\s+advice\b\.?", re.IGNORECASE)
_V_HASHTAG = re.compile(r"(?<![\w&])#([A-Za-z][A-Za-z0-9_]*)")
_V_OK_CHARS = set(" \t\n.,;:!?'\"()[]-+$%&/#@*_|•") | set("’‘“”–—−×…·"
                                                        "  ")


def verbatim_mode(item: dict | None) -> bool:
    return isinstance(item, dict) and VERBATIM_KEY in item


def verbatim_tokens(s: str) -> list[str]:
    """A sentence as compared under the verbatim rule: lower case, "$" off cashtags, every dash / minus before a number
    a "-", the times sign as "x", sector short names as their canonical name, punctuation dropped (a sign, "$", "%", "+"
    glued to a number stay part of it: "5+" is not "5", "+2.6%" is not "2.6%")."""
    s = _norm(nfkc(html.unescape(s or ""))).replace("’", "'").replace("‘", "'").replace("×", "x")
    s = re.sub("[–—‒](?=\\$?\\d)", "-", s)
    s = SECTOR_WORD.sub(lambda m: ALIAS_OF[m.group(1).lower()], s)
    s = re.sub(r"\$(?=[A-Za-z])", "", s).lower()
    s = re.sub("(?<=[a-z])[-–—](?=[a-z])", " ", s)
    toks = _VTOKEN.findall(s)
    if any(c.isalnum() for c in _VTOKEN.sub(" ", s)):
        toks.append(_V_UNREAD)
    return toks


def _phrase_forms(item: dict, phrases) -> list[str]:
    """Each phrase, plus the form without a closing "(number)" and, on a week item, "last week" for its when (as
    item_phrases does for claim phrases)."""
    out = []
    when = str(item.get("when") or "")
    for p in phrases or []:
        if not (isinstance(p, str) and p.strip()):
            continue
        forms = [p.strip()]
        if when.startswith("in the week to ") and when in p:
            forms.append(p.strip().replace(when, "last week"))
        for f in forms:
            out.append(f)
            bare = _NUM_PAREN_END.sub("", f)
            if bare != f:
                out.append(bare if bare.endswith(".") else bare + ".")
    return list(dict.fromkeys(out))


def verbatim_phrases(item: dict | None) -> list[str]:
    """Every sentence a post of this item may state: its claim_phrases and fact_phrases (with their forms)."""
    if not item:
        return []
    return list(dict.fromkeys([*_phrase_forms(item, item.get("claim_phrases")),
                               *_phrase_forms(item, item.get(VERBATIM_KEY))]))


def _hook_hashtags(item: dict | None) -> frozenset:
    return pv.HOOK_HASHTAGS | pv.HOOK_HASHTAGS_BY_TYPE.get(str((item or {}).get("type")), frozenset())


_DATEISH = re.compile(r"(?:" + _DAYS_W + r"|today|tonight|yesterday|tomorrow|weeks?|weekly|weekend|months?|quarters?|"
                      r"years?|morning|afternoon|evening|sessions?|open|close|premarket|pre|overnight|" + _MONTHS
                      + r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)")


def _word_kind(item: dict | None, w: str) -> str:
    """Why a word is not a hook word (for the reason text)."""
    if re.search(r"\d", w):
        return "number"
    if item:
        tags = {mk.norm_ticker(t).lower() for t in [*(item.get("tickers") or []), *(item.get("context_tickers") or []),
                                                     item.get("ticker")] if t}
        if w in tags:
            return "ticker"
        names = " ".join(n.lower() for n in [*item_names(item), *_person_names(item)] if isinstance(n, str))
        if re.search(rf"\b{re.escape(w)}\b", names):
            return "name"
    if w in ALIAS_OF or w in {s.lower() for s in ALIAS_OF.values()}:
        return "sector"
    if _DATEISH.fullmatch(w):
        return "date / session word"
    if w in pv.DIRECTION_UP or w in pv.DIRECTION_DOWN or LOSS_W.fullmatch(w) or GAIN_W.fullmatch(w):
        return "direction word"
    if w in pv.ADVICE_WORDS:
        return "advice / forecast word"
    if RANK_LANGUAGE.search(w) or w in pv.NUMBER_WORDS:
        return "ranking / count word"
    return "not a hook word"


def hook_reasons(item: dict | None, sent: str, toks: list[str] | None = None) -> list[str]:
    """[] when `sent` is a hook: only HOOK_WORDS, at most HOOK_MAX_WORDS words, no cashtag. Else what makes it factual."""
    toks = verbatim_tokens(sent) if toks is None else toks
    bad: dict[str, str] = {}
    odd = sorted({c for c in sent if c.isalpha() and not c.isascii()})
    if odd:   # a hook is plain English: a non-Latin or accented letter is never read past (look-alike letters)
        bad["".join(odd[:5])] = "letters outside A-Z"
    for m in CASHTAG.finditer(sent):
        bad["$" + m.group(1)] = "ticker"
    for w in toks:
        if w == _V_UNREAD:
            bad["?"] = "characters that are not plain words"
            continue
        base = w[:-2] if w.endswith("'s") else w
        if w in pv.HOOK_WORDS or (base in pv.HOOK_WORDS and not re.search(r"\d", base)):
            continue
        bad.setdefault(w, _word_kind(item, base))
    out = []
    if bad:
        out.append(", ".join(f"{w!r} ({k})" for w, k in list(bad.items())[:5]))
    if len(toks) > pv.HOOK_MAX_WORDS:
        out.append(f"{len(toks)} words (a hook has at most {pv.HOOK_MAX_WORDS})")
    return out


def _closest(sent_toks: list[str], phrases: list[str]) -> str | None:
    import difflib  # noqa: PLC0415
    best, score = None, 0.0
    for p in phrases:
        r = difflib.SequenceMatcher(None, sent_toks, verbatim_tokens(p), autojunk=False).ratio()
        if r > score:
            best, score = p, r
    return best if score >= 0.5 else None


def verbatim_reasons(item: dict | None, text: str, comment: bool = False) -> list[str]:
    """REJECT reasons under the verbatim facts rule (section 2d) for a post text / self-reply / comment."""
    out: list[str] = []
    s = _norm(nfkc(html.unescape(text or "")))
    s = _V_URL.sub(" ", s)
    for must in (item or {}).get("must_include") or []:
        if isinstance(must, str) and must.strip():
            s = re.sub(re.escape(must.strip()), " ", s, flags=re.IGNORECASE)
    s = _V_DISCLAIMER.sub(" ", s)
    ok_tags = _hook_hashtags(item)
    tags_bad = [m.group(1) for m in _V_HASHTAG.finditer(s) if m.group(1).lower() not in ok_tags]
    if tags_bad:
        out.append(f"hashtag {', '.join('#' + short_text(t, 24) for t in tags_bad[:4])}: a hashtag may only be a generic one "
                   f"({', '.join('#' + t for t in sorted(ok_tags))}); a ticker, company, sector or any other hashtag is a "
                   "fact")
    s = _V_HASHTAG.sub(" ", s)
    syms = sorted({c for c in s if not (c.isalnum() or c in _V_OK_CHARS or c in pv.HOOK_EMOJI)})
    if syms:
        out.append(f"symbols {' '.join(syms[:6])!r}: no arrows, chart / fire / rocket / medal / colour emoji or > < = "
                   "(a direction or a ranking without words); allowed emoji: "
                   + " ".join(sorted(pv.HOOK_EMOJI - {"️"})))
    phrases = verbatim_phrases(item)
    want = {tuple(verbatim_tokens(p)) for p in phrases}
    want.discard(())
    span = max([len(post_sentences(p)) for p in phrases] or [1])
    sents = post_sentences(s)
    toks = [verbatim_tokens(x) for x in sents]
    i = 0
    while i < len(sents):
        if not toks[i] and not any(c.isalpha() for c in sents[i]):
            i += 1
            continue
        hit = 0
        for j in range(min(len(sents), i + span), i, -1):
            if tuple(t for k in range(i, j) for t in toks[k]) in want:
                hit = j
                break
        if hit:
            i = hit
            continue
        why = hook_reasons(item, sents[i], toks[i])
        if why:
            st = short_text(sents[i].strip())
            if comment and not item:
                out.append(f"comment: {st!r} is not a hook ({'; '.join(why)}) - a comment without an item_id holds only "
                           "fact-free hooks (rules.verbatim.hook_words); to state a fact give the item_id and copy one of "
                           "its fact_phrases / claim_phrases verbatim")
            else:
                near = _closest(toks[i], phrases)
                out.append(f"not verbatim: {st!r} states facts ({'; '.join(why)}) but is not one of the item's "
                           "fact_phrases / claim_phrases - copy one exactly as its own sentence (no word added, dropped "
                           "or changed), or write a hook with no fact in it"
                           + (f"; closest phrase: {short_text(near, 140)!r}" if near else ""))
        i += 1
    return out
