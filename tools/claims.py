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
      "kind": "stock"|"sector", "polarity": "best"|"worst"|None, "rank": 1|"group", "metric": what is ranked,
      "within": [scope sectors / tickers], "universe": "10"|None, "date": iso|None, "scope": regex or None, "bare": bool,
      "direction": "up"|"down"|"mixed"|None, "needs": regex or None, "says": what is true}
   A clause (sentence, or a part split at ";", ", while", ", but", ", and", or after a colon lead-in) that carries a
   superlative passes only when every superlative word in it is backed by a claim (section 2 below has the detail):
     - the side it means matches the claim's polarity: best / worst words, else the noun it governs ("top loser", "led
       the drop" = worst) or the verb before it ("fell the most"); "top" / "led" / "#1" alone = best, whatever signs
       stand beside them;
     - the metric it names matches the claim's (percent / market cap / dollars);
     - its scope words match the claim's ("of the 500", "overall" = no within; "in Tech", "its sector" = that within;
       "of the 10" = the basket);
     - every ticker / sector the clause names is ranked by such a claim (a sector only by a sector claim, or as a
       stock claim's within): singular wording / a list only from #1 in order, "among the" / "one of the" for any
       group member, "the N biggest" / "top N" for exactly the top N, "second-biggest" only for #2;
     - the claim's direction (when set) agrees with its direction words / signs, its `needs` occurs in it, a bare claim
       (a clause naming nothing) is not tied to another date, and nothing widens the window ("ever", "in months", "of
       the quarter", "since September"); a negated comparison is rejected; two named tickers / sectors compared ("did
       better than $AAPL") need a claim that ranks them so.
   Definitions are not claims: "the 500 largest", "the 10 largest", "largest US-listed", "first session after", "track record",
   "best minus worst", "at least" / "at most", "first quarter", "top line", "#1 pick"; nor is a question to the reader
   ("...surprised you most?").
   A one-session item (its `when` is "on Friday" / "today") is never "this / last / past week" (and its comparisons never
   a week or 5 sessions); a week item's comparisons are never one day; the earnings preview (a week ahead) is never "past
   week"; no item says "today" / "yesterday" / "tonight" unless its `when` does (a Monday post about Friday).
3. Sector attribution: a clause naming one sector and listing cashtags (or followed by a clause that starts with a
   cashtag and names no sector) implies those companies are in that sector; a cashtag labelled with a sector in
   parentheses likewise. Each must match the item's ticker_sectors ($GOOGL is Communication Services, not Technology).
4. Scoped numbers: an item may require words next to some of its numbers (`scoped_numbers`: the 30-day insider totals are
   "open-market" buys / sells "by officers and directors").
5. Card message (`card_message`): words a post may not use because its attached card says the opposite (breadth: a card
   headlining a broad decline never goes with "narrow", "concentrated", "the typical stock was flat").
"""
from __future__ import annotations

import datetime as dt
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
    bad = [m.group(0) for m in WEEK_WORDS.finditer(text) if m.group(0).lower() not in ok]
    # a post goes out after the facts were built (Grok's Monday pre-market slot reads Sunday's facts): "today",
    # "yesterday" and "tonight" are wrong for a session the item calls "on Friday" (or a week)
    bad += [m.group(0) for m in STALE_DAY.finditer(text) if m.group(1).lower() not in w]
    return [f"window: the item's window is \"{when}\", not {bad[0]!r}"] if bad else []


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
#          led / #1 mean the best end whatever signs stand beside them ("Tech, down 2.8%, was the top sector" = Tech was
#          the best); biggest / largest + a company / sector noun is size ("the biggest company" = market cap); most /
#          biggest alone take the clause's gain / loss words, then its signs.
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

CATEGORIES = (
    ("led", r"led|leads?|leading|leaders?"),
    ("biggest", r"biggest|largest|heaviest|greatest|sharpest|steepest|hardest|deepest"),
    ("worst", r"worst|weakest|lowest"
              r"|underperform(?:s|ed|ing)?\s+(?:every|all|any)(?:\s+other)?"
              r"|(?:worse\s+than|trail(?:s|ed)?|lagg(?:ed)?\s+behind)\s+(?:every|all|any)(?:\s+other)?"
              r"|no\s+other\s+(?:[a-z]+\s+){0,2}(?:fell|lost|dropped|declined|did)\s+(?:more|worse)"),
    ("best", r"best|strongest|highest"
             r"|outperform(?:s|ed|ing)?\s+(?:every|all|any)(?:\s+other)?"
             r"|(?:beat|beats|topped|tops|better\s+than|ahead\s+of)\s+(?:every|all|any)(?:\s+other)?"
             r"|no\s+other\s+(?:[a-z]+\s+){0,2}(?:beat|topped|rose\s+more|gained\s+more|did\s+better|came\s+close)"),
    ("most", r"most(?:-[a-z]+)?|closest|tightest|nearest"
             r"|more\s+than\s+(?:any|every|all)(?:\s+other)?"
             r"|(?:more\s+(?:[a-z$]+\s+){1,3}|(?!(?:oth|rath|ev|nev|und|ov|aft|lat|earli|ord)er\b)[a-z]+er\s+)than\s+"
             r"(?:any|every|all)(?:\s+other)?"
             r"|(?:no|nothing|none)\s+(?:other\s+)?(?:[a-z]+\s+){0,2}(?:lost|shed|gained|added|moved|fell|rose|dropped)\s+"
             r"(?:more|further|harder|as\s+much)"),
    ("least", r"least|smallest|fewest|less\s+(?:[a-z$]+\s+){0,3}than\s+(?:any|every|all)(?:\s+other)?"),
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
         r"|sank|sinks?|shed|sheds|wiped|red|retreat\w*|pullbacks?|bleed\w*|crash\w*|sell(?:ing|ers?)?|sold")
_GAIN = (r"gain\w*|winners?|ris(?:e|es|ers?|ing)|rose|advanc\w*|rall(?:y|ies|ied|ying)|lifts?|lifted|lifting|jump\w*"
         r"|higher|up|upside|climb\w*|surg\w*|soar\w*|perform\w*|green|added|adds?|rebound\w*|bounc\w*|buy(?:ing|ers?)?"
         r"|bought")
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
    r"|\b(?:of|than)\s+(?:any|every|all)\s+(?:other\s+)?(?:[\w.-]+\s+)?(?:stocks?|compan(?:y|ies)|names?|tickers?|pairs?)\b"
    r"|\b(?:any|every)\s+other\s+(?:stock|company|name|ticker)\b|\bin\s+the\s+(?:us|u\.s\.|country|world)\b"
    r"|\banywhere\b|\bon\s+wall\s+street\b|\bof\s+(?:all\s+|the\s+)?2,?[45]\d\d\b|\bacross\s+the\s+market\b", re.IGNORECASE)
BASKET_W = re.compile(r"\b(?:of|among|in)\s+(?:the\s+|these\s+|those\s+)?(?:10|ten)\b|\b(?:10|ten)\s+(?:largest|biggest|mega)"
                      r"|\bmega[-\s]?caps?\b", re.IGNORECASE)
UNIVERSE_NOUN = re.compile(r"\b(?:stocks?|compan(?:y|ies)|names?|tickers?|los(?:er|ers)|gainers?|winners?|performers?"
                           r"|decliners?|risers?)\b", re.IGNORECASE)
SEP = re.compile(r"[,;:()\[\]?!]|\s[-–—]\s|\s+(?:and|while|whereas|but|with|as|after|before|when|plus)\s+",
                 re.IGNORECASE)
PRON_BEFORE = re.compile(r"\b(?:its|their)\s+(?:[\w-]+\s+)?$", re.IGNORECASE)
# a comparison of two named entities
COMPARE = re.compile(
    r"\b(?P<better>(?:did|performed|fared|held\s+up)\s+better\s+than|better\s+than|stronger\s+than|outperform(?:ed|s|ing)?"
    r"|beat|beats|topped|tops|(?:rose|gained|climbed|added)\s+more\s+than)\b"
    r"|\b(?P<worse>(?:did|performed|fared)\s+worse\s+than|worse\s+than|weaker\s+than|underperform(?:ed|s|ing)?|trailed"
    r"|trails|lagged(?:\s+behind)?|(?:fell|dropped|lost|declined|slid)\s+more\s+than)\b", re.IGNORECASE)
BENCHMARK = {"SPY"}   # the picks' track record compares with SPY (section 1): not a ranking between two stocks
COMPARE_END = re.compile(r"\b(?:was|were|did|fared|is|are)\s+(?:even\s+)?(?P<w>worse|better|weaker|stronger)\s*[.!?]?\s*$",
                         re.IGNORECASE)

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
SECTOR_WORD = re.compile(r"(?<![\w$-])(" + _SECTOR_ALT + r")(?![\w])", re.IGNORECASE)
SECTOR_NEXT = re.compile(r"^\s+(?:dollar\s+)?(" + _SECTOR_ALT + r")(?![\w])", re.IGNORECASE)    # "biggest Tech name"
SECTOR_IN = re.compile(r"\b(?:in|of|within|inside|among)\s+(?:the\s+)?(" + _SECTOR_ALT + r")(?![\w])", re.IGNORECASE)
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
            "within": list(dict.fromkeys(within)), "scope": c.get("scope"), "bare": bool(c.get("bare")),
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


def _words(s: str) -> list[str]:
    return re.findall(r"[\w$'%.+-]+", s)


def _head(o: dict, body: str) -> str:
    """Up to 4 words after a superlative (its noun: "top loser", "biggest Tech name", "led the drop")."""
    fwd = body[o["e"]:o["seg_end"]]
    stop = _STOP.search(fwd)
    return " ".join(_words(fwd[:stop.start()] if stop else fwd)[:4])


SECTOR_NOUN = re.compile(r"\b(?:sectors?|groups?|industr(?:y|ies))\b", re.IGNORECASE)
STOCK_NOUN = re.compile(r"\b(?:stocks?|compan(?:y|ies)|names?|tickers?|shares?|firms?)\b", re.IGNORECASE)


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
        return "best", False                  # "top sector", "led on Friday": the best end, whatever the signs
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


def _scope(o: dict, cl: str, has_ticks: bool, names: list[str]):
    """The scope words of one superlative: ("global",), ("basket",), ("sector", S), ("ticker", T), ("pron", own, hist)
    or None."""
    fwd = cl[o["e"]:o["seg_end"]]
    back = cl[o["seg_start"]:o["s"]]
    if GLOBAL_W.search(fwd):
        return ("global",)
    if BASKET_W.search(fwd):
        return ("basket",)
    pron_b = PRON_BEFORE.search(back)
    own = SECTOR_SCOPE.search(fwd)
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


def _grp(o: dict, cl: str):
    """Rank wording of one superlative: ("member",), ("count", N), ("nth", k) or None (singular / a list from #1)."""
    back = cl[o["seg_start"]:o["s"]]
    fwd = cl[o["e"]:o["seg_end"]]
    if MEMBER_BEFORE.search(back) or INCLUDES.search(cl):
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
        return c["rank"] == "group" or ranked == subj[:1]
    if grp and grp[0] == "count":
        return grp[1] <= len(subj) and set(ranked) == set(subj[:grp[1]])
    if grp and grp[0] == "nth":
        return len(ranked) == 1 and ranked[0] in subj and subj.index(ranked[0]) == grp[1] - 1
    return ranked == subj[:len(ranked)]


def _side_ok(c: dict, side) -> bool:
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


def _clause_reasons(cl: str, claims: list[dict], names: list[str], ctx: dict) -> list[str]:
    body = _prep(cl)
    ticks, secs = tags_in(cl), sectors_in(cl, names)
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
    for o in occ:
        o["seg_start"] = max([0] + [e for s, e in seps if e <= o["s"]])
        o["seg_end"] = min([len(body)] + [s for s, e in seps if s >= o["e"]])
    # "Friday's best sector was not Energy" (the part that is true is left unsaid): rejected; a "not" elsewhere in the
    # sentence ("..., not a small move") is not the comparison's
    if any(NEGATION.search(cl[o["seg_start"]:o["seg_end"]]) for o in occ):
        return [f"negated comparison in \"{cl.strip()[:90]}\": state what is true positively (the item's claims say: "
                + ("; ".join(c["says"] for c in claims if c["says"])[:300] or "none") + ")"]
    dirs = directions(_prep(cl))
    sent, text = ctx["sentence"], ctx["text"]
    secmap = ctx["secmap"]
    pos = {}
    for t in ticks:
        m = re.search(r"(?<![\w$])\$" + re.escape(t).replace(r"\.", r"[.-]") + r"(?![\w])", cl, re.IGNORECASE)
        pos[t] = m.start() if m else 0

    def scope_ok(c, sc, ranked, noun):
        within = c["within"]
        if sc is None:
            if within:
                return bool(set(within) & named) or bool(c["scope"] and re.search(c["scope"], cl, re.IGNORECASE))
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
        if not (wt and ranked) or (sc and sc[0] == "ticker"):
            return True
        return min(pos[w] for w in wt) < pos[ranked[0]]

    for o in occ:
        o["scope"] = _scope(o, cl, bool(ticks), names)
    # a sector that only scopes a stock ranking ("$MSFT led Tech lower", "Tech's biggest drops: $MSFT") is not itself
    # the subject of a sector claim in that clause
    scope_secs = {o["scope"][1] for o in occ if o["scope"] and o["scope"][0] == "sector"}
    subj_secs = [s for s in secs if s not in scope_secs]
    backing, covered, fails = [], set(), []
    for o in occ:
        side, changed = _side(o, body, cl)
        metric = _metric(o, cl, side, changed)
        sc = o["scope"]
        grp = _grp(o, cl)
        seg = cl[o["seg_start"]:o["seg_end"]]
        noun = re.split(r"\b(?:in|of|on|among|within|inside|by|at|for|with|to|across|over|from)\b", _head(o, body),
                        maxsplit=1, flags=re.IGNORECASE)[0]   # "worst stock in its sector": the noun is "stock"
        if o["cat"] == "led":    # its words are an object ("led its sector", "led Energy"), not the ranked noun
            noun = ""
        only = "sector" if SECTOR_NOUN.search(noun) else "stock" if STOCK_NOUN.search(noun) else None
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
            pool = subj_secs if c["kind"] == "sector" else ticks
            ranked = [e for e in pool if e in c["subjects"]]
            if named:
                if not ranked:
                    continue
            elif not c["bare"] or not _date_ok(c, seg):
                continue
            if not (scope_ok(c, sc, ranked, noun) and _rank_ok(c, ranked, grp) and order_ok(c, ranked, sc)):
                continue
            ok.append((c, ranked))
        if not ok:
            fails.append((o, side))
        for c, ranked in ok:
            covered |= set(ranked) | (set(c["within"]) & named)
        backing += ok
    out = []
    # the object of a comparison ("worse than Energy") is checked by comparison_reasons, not ranked here
    objs = set()
    ents = _entities(cl, names)
    for m in COMPARE.finditer(cl):
        after = [e for e in ents if e[0] >= m.end() and e[0] - m.end() <= 25]
        if after:
            objs.add(after[0][1])
    miss_e = [e for e in ticks + secs if e not in covered and e not in objs] if named and not fails else []
    if fails or miss_e:
        o, side = fails[0] if fails else (occ[0], None)
        side_txt = {"best": "best side", "worst": "worst side", "size": "size", None: "no side"}[side]
        what = ", ".join(ticks + secs) or "no named company or sector"
        rel = [c for c in claims if (set(c["subjects"]) | set(c["within"])) & named] or claims
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


def _order_backed(claims: list[dict], a: str, b: str, how: str) -> bool:
    """Is "a <how> b" (better / worse) what a claim's rank order says (one claim ranking both, or a is in a best claim
    and b in a worst claim of the same kind and metric)?"""
    for c in claims:
        s = c["subjects"]
        if a in s and b in s:
            first = s.index(a) < s.index(b)
            if how == "better" and ((c["polarity"] == "best" and first) or (c["polarity"] == "worst" and not first)):
                return True
            if how == "worse" and ((c["polarity"] == "worst" and first) or (c["polarity"] == "best" and not first)):
                return True
    top = "best" if how == "better" else "worst"
    bottom = "worst" if top == "best" else "best"
    ka = [c for c in claims if c["polarity"] == top and a in c["subjects"]]
    kb = [c for c in claims if c["polarity"] == bottom and b in c["subjects"]]
    return any(x["kind"] == y["kind"] and x.get("metric") == y.get("metric") and not x["within"] and not y["within"]
               for x in ka for y in kb)


def _entities(cl: str, names: list[str]) -> list[tuple[int, str, str]]:
    """(position, entity, kind) for every cashtag and sector named in cl, in text order."""
    out = [(m.start(), mk.norm_ticker(m.group(1)), "stock") for m in CASHTAG.finditer(cl)]
    blank = PAREN.sub(lambda m: " " * len(m.group(0)), CASHTAG.sub(lambda m: " " * len(m.group(0)), _blank_names(cl, names)))
    out += [(m.start(), ALIAS_OF[m.group(1).lower()], "sector") for m in SECTOR_WORD.finditer(blank)]
    return sorted(out)


def comparison_reasons(claims: list[dict], cls: list[str], names: list[str]) -> list[str]:
    """Two named tickers / sectors compared ("$MSFT did better than $AAPL", "...$CRWV was worse.") need a claim that
    ranks them that way."""
    out = []
    prev: list[tuple[int, str, str]] = []
    for cl in cls:
        ents = _entities(cl, names)
        for m in COMPARE.finditer(cl):
            how = m.lastgroup
            after = [e for e in ents if e[0] >= m.end() and e[0] - m.end() <= 25]
            if not after:
                continue
            b = after[0]
            before = [e for e in ents if e[0] < m.start() and e[2] == b[2]]
            if not before:
                continue
            a = before[-1]
            if a[1] != b[1] and not {a[1], b[1]} & BENCHMARK and not _order_backed(claims, a[1], b[1], how):
                out.append(f"unsupported comparison: \"{a[1]} {m.group(0)} {b[1]}\" - no claim of the item ranks them so")
        me = COMPARE_END.search(cl)
        if me and prev:
            how = "worse" if me.group("w").lower() in ("worse", "weaker") else "better"
            own = [e for e in ents if e[0] < me.start()]
            if own:
                a = own[-1]
                bs = [e for e in prev if e[2] == a[2] and e[1] != a[1] and e[1] not in BENCHMARK]
                if bs and a[1] not in BENCHMARK and not _order_backed(claims, a[1], bs[-1][1], how):
                    out.append(f"unsupported comparison: \"{a[1]} was {me.group('w')}\" than {bs[-1][1]} - no claim of "
                               "the item ranks them so")
        if ents:
            prev = ents
    return out


def claim_reasons(item: dict, text: str) -> list[str]:
    """REJECT reasons for comparative / superlative wording the item's claims do not back."""
    claims = [claim_view(c) for c in item.get("claims") or [] if isinstance(c, dict)]
    names = item_names(item)
    secmap = {mk.norm_ticker(k): canon_sector(v) for k, v in (item.get("ticker_sectors") or {}).items() if v}
    norm = _norm(text or "")
    ctx = {"item": item, "text": norm, "secmap": secmap, "sector": None}
    out, all_cls = [], []
    for sent in SENTENCE.split(norm):
        if not sent.strip():
            continue
        ctx["sentence"] = sent
        for cl in claim_clauses(sent, names):
            all_cls.append(cl)
            if superlatives(cl) and not READER_QUESTION.search(cl.strip()):
                out += _clause_reasons(cl, claims, names, ctx)
            secs = sectors_in(cl, names)
            if len(secs) == 1:
                ctx["sector"] = secs[0]
            elif len(secs) > 1:
                ctx["sector"] = None
    if claims:  # an item with no ranking claims (an earnings card, a Form 4) was never ranked: nothing to compare with
        out += comparison_reasons(claims, all_cls, names)
    return list(dict.fromkeys(out))


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
