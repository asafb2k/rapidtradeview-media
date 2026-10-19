"""The plain-word vocabulary of a post sentence that is not a claim phrase (claims.py section 2c, HQ 2026-10-19 round 2).

A sentence passes without a claim phrase only when every word left after removing the item's entities (cashtags,
company / person names, sectors, "the 500 largest US-listed stocks"), its numbers and dates, its window words and the
idioms below is in VOCAB. Anything else - a synonym of "best", "alone", "the rest", "kept falling", "matched", a number
word, a month name, an intensity verb, an unknown noun - sends the sentence to the claim-phrase check, where it passes
only as one of the item's claim_phrases verbatim. The list is closed on purpose: a new honest word is added here after a
look at what it can claim (never a word that ranks, compares, quantifies a set, states a streak / record / window, or
states a direction this module does not check).

Direction words (DIRECTION_UP / DIRECTION_DOWN) are in VOCAB because claims.binding_reasons ties each one to the subject
it governs and to the item's data; any other up / down word (surged, tanked, swelled, in the green, richer, higher,
lower, ...) is left out, so it can never pass unchecked.
"""
from __future__ import annotations

DIRECTION_UP = frozenset("""
rose rise rises rising gained gain gains gaining climbed climb climbs climbing up
""".split())
DIRECTION_DOWN = frozenset("""
fell fall falls falling lost lose loses losing loss losses dropped drop drops dropping declined decline declines
declining slid slide slides sliding slipped slip slips dipped dip dips shed sheds down drag drags
""".split())

_FUNCTION = """
a an the and or but so yet also plus of in on at by for from to with without into via per as if vs versus against
across out
after before until through during between about around near not
it its this that these those they their them he his him she her we our us you your who whom whose which what when
where how why there here
is are was were be been being am has have had having do does did done will would can could may might should
can't don't doesn't didn't isn't aren't wasn't weren't it's that's here's what's there's let's we're you're
they're
"""
_VERBS = """
report reports reported reporting post posts posted posting publish publishes published publishing file files filed
filing disclose discloses disclosed disclosing trade trades traded trading buy buys bought buying sell sells sold
selling purchase purchased purchases purchasing own owns owned hold holds held holding show shows showed shown see sees
saw seen watch watches watched watching check checks checked read reads list lists listed flag flags flagged track
tracks tracked grade grades graded grading score scores scored compute computed measure measured close closes closed
closing open opens opened end ends ended finish finished move moves moved moving come comes came cost costs total
totals totaling totaled totalled make makes made confirm confirms confirmed announce
announces announced walk walks sign signing signed build built building tell tells say says said think thinks know
notice noticed talk talking talked mention mentions mentioned price priced weight weighted value valued set sets get
gets got give gives gave take takes took follow follows find found learn want wants need needs expected split pay paid
start starts started due scheduled call calls print update updated visit tap click explain explains map maps chart
stay stays
charted look looks scan scanned capture captured filter filtered owning portfolio
"""
_NOUNS = """
stock stocks share shares company companies name names ticker tickers sector sectors industry market markets value cap
caps capitalization dollar dollars percent pct point points price prices session sessions day days week weekday today
tomorrow tonight yesterday hour hours time date dates calendar earnings revenue revenues sales eps income profit
consensus estimate estimates est expectations results result report release quarter guidance gaap adjusted adj
diluted core basis charge settlement unadjusted
insider insiders director directors officer officers ceo cfo coo chairman chair president founder owner owners
executive executives member members congress house senate representative rep sen senator senators spouse filing filings form
sec edgar ptr disclosure disclosures trade purchase sale amount amounts range ranges investor investors fund funds
holder holders stake position positions transaction transactions buyer seller
chart charts close
picks list lists scoreboard app site page pages card cards link links bio details detail source sources data feed
dashboard post reel clip video poll question answer comment reply replies thread view views tool tools screener
research analysis summary summaries note notes
reddit stocktwits apewisdom mentions
am pm et utc est q fy bmo amc co both then
analyst analysts zacks factset marketbeat yahoo finnhub rapidtradeview
"""
_ADJ = """
public daily free full official new open confirmed automatic technical reported live plain past prediction
individual direct indirect
watchlist radar thoughts surprised happy hello welcome advice investment information educational
"""
# words only some item types use (the type's own data words)
BY_TYPE = {
    "picks_ready": frozenset("pick pick's picks signal signals graded spy benchmark each once".split()),
    "reddit_buzz": frozenset("weekend average ratio usual buzz capture".split()),
    "moves_like": frozenset("sync peer peers like close tight".split()),
    # claims.chart_reasons checks each one against the prices
    # pattern words only on a pattern item (elsewhere "Tech's breakdown", "at its lows", "broke out" would state an unchecked
    # move); claims.chart_reasons checks each above / below / under / over against the prices
    "chart_pattern": frozenset("""above below under over pattern patterns line lines level levels support resistance neckline
        triangle descending ascending symmetrical wedge flag pennant channel head shoulders cup handle breakout breakdown
        highs lows ran run runs broke break breaks""".split()),
}

VOCAB = (frozenset(w for block in (_FUNCTION, _VERBS, _NOUNS, _ADJ) for w in block.split()) | DIRECTION_UP | DIRECTION_DOWN
         | frozenset("abcdefghijklmnopqrstuvwyz"))   # single letters: initials, "M&T", an orphan "'s" (never "x": 3x)

# hashtags a post may carry besides its tickers and its companies' names run together (#CharlesSchwab)
HASHTAGS = frozenset("""
stocks stockmarket earnings investing insiderbuying insidertrading dailypicks earningsseason earningscalendar
congresstrades congress sec form4 secfilings trading politics banks healthcare realestate reit stocktrading
investors finance markets wallstreet smartmoney reddit wallstreetbets technicalanalysis chartpatterns
""".split())

NUMBER_WORDS = frozenset("""
zero one two three four five six seven eight nine ten eleven twelve thirteen fifteen twenty thirty forty fifty sixty
seventy eighty ninety hundred thousand million billion trillion dozen dozens hundreds thousands millions billions
trillions twice thrice single double triple half quarter-point
""".split())

# idioms blanked before the vocabulary is read: product and calendar wording with no ranking in it (each one checked:
# nothing in it can state a comparison, a direction or a window other than its own)
IDIOMS = (
    r"\bearnings[\s-]+history\b", r"\btrack\s+record\b", r"\blink\s+in\s+(?:our\s+)?bio\b",
    r"\bnot\s+investment\s+advice\b", r"\bopen[\s-]+market\b", r"\bper\s+(?:diluted\s+)?share\b",
    r"\bdouble\s+(?:top|bottom)\b", r"\bhead\s+and\s+shoulders\b", r"\b(?:lower|upper)\s+line\b",
    r"\blast\s+close\b", r"\b(?:learn|read|see)\s+more\b", r"\bmore\s+(?:details|info)\b",
    r"\b(?:before|after)\s+the\s+(?:open|close|bell)\b", r"\bfirst\s+(?:comment|reply)\b",
    # a window the item states ("over the 60 sessions", "over 5 sessions"); claims.window_reasons checks its N
    r"\bover\s+(?:the\s+)?(?:last\s+|past\s+)?\d+\s+(?:sessions|trading\s+days|days|closes)\b",
    # a link label ("All her trades: <link>"), a party / state tag ("(R-FL)")
    r"\ball\s+(?:of\s+)?(?:his|her|their|our|the)\s+(?:trades|filings|disclosures|picks|reports)\s*:",
    r"\(\s*[RDI]\s*-\s*[A-Z]{2}(?:-?\d{1,2})?\s*\)",
    # the basket's and the preview's definitions ("held equally", "(each worth $10B+)"), a week window ("over the past week")
    r"\bowning\s+the\s+10\s+largest(?:\s+us-listed)?\s+companies\s+equally\b", r",?\s*held\s+equally\b",
    r"\(\s*each\s+worth\s+\$\d[\d.,]*[KMBT]?\+?\s*\)", r"\bover\s+the\s+(?:past|last)\s+week\b",
    # the map link ("Every company on one map below."), the session after a report ("The next session: -3.88%.")
    r"\b(?:every|all)\s+(?:company|companies|stock|stocks)\s+on\s+(?:one|a\s+single|the|our)\s+(?:map|page)\b(?:\s+below)?",
    r"\bthe\s+next\s+(?:session|trading\s+day)\b",
    # chart pattern names: a shape, not a move
    r"\b(?:rising|falling|ascending|descending|symmetrical)\s+(?:wedge|triangle|channel)\b",
    r"\b(?:bull|bear)(?:ish)?\s+(?:flag|pennant)\b", r"\b(?:inverse\s+)?head\s+and\s+shoulders\b",
    # link lines and list tails ("Every filing on rapidtradeview.trade", "Every pick is graded in public:", "+1 more",
    # "... and more")
    r"\bevery\s+(?:filing|pick|trade|report)\s+(?:is\s+(?:then\s+)?graded(?:\s+in\s+public)?|on)\b", r"\+\s?\d[\d,]*\s+more\b",
    r"\band\s+more\b",
)

# ---------------------------------------------------------------------------
# Verbatim facts rule (HQ 2026-10-19, claims.py section 2d): a post sentence is either one of the item's pre-verified
# sentences (fact_phrases / claim_phrases) copied verbatim, or a HOOK. A hook carries no fact at all: every word of it is
# in HOOK_WORDS (closed on purpose: no name, number, sector, date / weekday / session word, direction word, ranking or
# comparison word, intensity or mood word, advice word), at most HOOK_MAX_WORDS words. "Here is how the day looked." /
# "What stood out to you?" / "Full map in the reply." are hooks; "A down day for chips." / "Big names led." are not.
HOOK_MAX_WORDS = 12
# Review round 6: no word that turns a hook into an implicit call to act or a position claim - do / does / did ("You know
# what to do.", "Do what they did.", "I did."), have / has / had ("We have it."), i / we / we're ("We're in."), move /
# moves ("This is the move."), take / follow / catch / know ("Follow them.", "They know.").
HOOK_WORDS = frozenset("""
a an the this that these those here there it its is are was were be been you your our
us they them their what which who how why where and or but so if of in on at to for from with about into out as
here's what's it's that's there's you're let's
look looks looked see seen check read think tell share sharing save watch watching stand stands stood
notice noticed surprised surprise matter matters mean means show shows find found tap swipe scroll
day chart charts map maps card cards numbers data list details breakdown picture view thread post link bio reply
comments page source sources context story summary recap question thoughts market stocks companies investors traders
names rapidtradeview sec filing filings official
full quick key clear interesting helpful useful curious below
thanks thank
""".split())
# emoji a hook (or a verbatim sentence) may carry: pointers and props, no direction, size, mood or ranking (arrows, charts
# up / down, fire, rockets, medals, colours, alarms are all out)
HOOK_EMOJI = frozenset("\U0001f447\U0001f440\U0001f9f5\U0001f4ca\U0001f5fa\U0001f4c5\U0001f50e\U0001f50d\U0001f4ac"
                       "\U0001f4cc\ufe0f")
# hashtags without a fact in them (sector, ticker and company hashtags are facts: never in a hook); topic hashtags only on
# an item of that topic
HOOK_HASHTAGS = frozenset("stocks stockmarket investing investors trading stocktrading finance markets wallstreet".split())
HOOK_HASHTAGS_BY_TYPE = {
    "form4_buy": frozenset("insiderbuying form4 secfilings smartmoney sec".split()),
    "insider_flow": frozenset("insiderbuying form4 secfilings smartmoney sec".split()),
    "congress_trade": frozenset("congresstrades congress politics smartmoney".split()),
    "ptr_summary": frozenset("congresstrades congress politics smartmoney".split()),
    "congress_flow": frozenset("congresstrades congress politics smartmoney".split()),
    "earnings_result": frozenset("earnings earningsseason".split()),
    "earnings_upcoming": frozenset("earnings earningsseason earningscalendar".split()),
    "earnings_tomorrow_roundup": frozenset("earnings earningsseason earningscalendar".split()),
    "earnings_week_preview": frozenset("earnings earningsseason earningscalendar".split()),
    "earnings_reaction": frozenset("earnings earningsseason".split()),
    "reddit_buzz": frozenset("reddit wallstreetbets".split()),
    "chart_pattern": frozenset("technicalanalysis chartpatterns".split()),
    "picks_ready": frozenset("dailypicks".split()),
}
# ---------------------------------------------------------------------------
# CLOSED HOOK LIST (HQ 2026-10-19, round 7): a sentence that is not one of the item's phrases must EQUAL one of these whole
# sentences (verbatim normalisation: case, spacing, punctuation), for an item whose facts carry `phrasings` and for every
# comment without an item_id. No free combination of hook words any more. Each hook is neutral, names nothing (no
# company, number, sector, date, direction, ranking, mood), never advises or tells anyone to act on a stock, and never
# claims we did anything. id = the rotation key (post_history / grok_review: a hook id used in one of the last
# ROTATION_POSTS posts of the same item type on the same platform is not used again). platforms = where it may stand
# (link hooks say where the link is); use = "post" (posts and self-replies), "comment" (comments on other accounts'
# posts) or "any" (the questions to the reader: a comment may pair one with a thanks line); types = the item types it fits
# (None = every type). HOOK_WORDS above stays only to explain a
# rejection ("states facts" vs "not an approved hook") and to read items from facts files built before this list.
_ALL = ("x", "threads", "instagram")
_XT = ("x", "threads")
_FILINGS = ("form4_buy", "congress_trade", "ptr_summary", "insider_flow", "congress_flow")
_EARNINGS = ("earnings_result", "earnings_upcoming", "earnings_tomorrow_roundup", "earnings_week_preview",
             "earnings_reaction")
_MAP = ("market_move", "mega_mover", "sector_rotation", "breadth_day", "basket_week")
_CHART = ("chart_pattern", "moves_like")


def _h(hid: str, text: str, platforms=_ALL, use: str = "post", types=None) -> dict:
    return {"id": hid, "text": text, "platforms": list(platforms), "use": use, "types": list(types) if types else None}


HOOKS = [
    # openers / statements
    _h("H01", "Here is the map.", types=_MAP),
    _h("H02", "Here is how the day looked.", types=("market_move", "mega_mover", "sector_rotation", "breadth_day",
                                                     "reddit_buzz", "earnings_reaction")),
    _h("H03", "Here is the picture."),
    _h("H04", "Here are the numbers."),
    _h("H05", "The numbers are below."),
    _h("H06", "A quick look at the data."),
    _h("H07", "Here is the breakdown."),
    _h("H08", "Here is the chart."),
    _h("H09", "The data, in plain numbers."),
    _h("H10", "Here is what the filings show.", types=_FILINGS),
    _h("H11", "Here is what the filing shows.", types=("form4_buy", "congress_trade")),
    _h("H12", "Here is the earnings calendar.", types=("earnings_upcoming", "earnings_tomorrow_roundup",
                                                       "earnings_week_preview")),
    _h("H13", "Here is what the report shows.", types=("earnings_result",)),
    _h("H14", "Here is what Reddit is talking about.", types=("reddit_buzz",)),
    _h("H15", "Here is what the chart shows.", types=_CHART),
    _h("H16", "Here is the context."),
    # questions to the reader that name nothing
    _h("H20", "What stood out to you?", use="any"),
    _h("H21", "What surprised you?", use="any"),
    _h("H22", "What do you see here?", use="any"),
    _h("H23", "Which number stands out to you?", use="any"),
    _h("H24", "What would you look at here?", use="any"),
    _h("H25", "What caught your eye?", use="any"),
    _h("H26", "What here was new to you?", use="any"),
    _h("H27", "What is your read on this?", use="any"),
    _h("H28", "How do you read this chart?", use="any",
       types=(*_MAP, *_CHART, "reddit_buzz", "insider_flow", "congress_flow")),
    _h("H29", "Is this on your radar?", use="any"),
    _h("H30", "What else would you look at?", use="any"),
    _h("H31", "Which detail matters to you?", use="any"),
    # pointers to the link / the visual
    _h("H40", "Full map in the reply.", _XT, types=_MAP),
    _h("H41", "Source in the reply.", _XT),
    _h("H42", "Link in the reply.", _XT),
    _h("H43", "Details in the reply.", _XT),
    _h("H44", "Link in bio.", ("instagram",)),
    _h("H45", "Full map at the link in bio.", ("instagram",), types=_MAP),
    _h("H46", "Swipe for the numbers.", ("instagram",)),
    # link labels (a self-reply, or before a link in a caption)
    _h("H50", "Full map:", types=_MAP),
    _h("H51", "Source:"),
    _h("H52", "SEC filing:", types=("form4_buy", "insider_flow")),
    _h("H53", "The filing:", types=("form4_buy", "congress_trade", "ptr_summary")),
    _h("H54", "Details:"),
    _h("H55", "Earnings calendar:", types=("earnings_upcoming", "earnings_tomorrow_roundup", "earnings_week_preview")),
    _h("H56", "The details:"),
    # comments on other accounts' posts
    _h("H70", "Thanks for sharing, what stood out to you?", ("x", "instagram"), "comment"),
    _h("H71", "Thanks for sharing.", ("x", "instagram"), "comment"),
    _h("H72", "Interesting chart, thanks for sharing.", ("x", "instagram"), "comment"),
    _h("H73", "Helpful breakdown, thanks.", ("x", "instagram"), "comment"),
    _h("H74", "Useful context, thanks.", ("x", "instagram"), "comment"),
    _h("H75", "Clear chart, thanks for posting.", ("x", "instagram"), "comment"),
    _h("H76", "Good question, curious what others think.", ("x", "instagram"), "comment"),
    _h("H77", "Thanks, this is helpful.", ("x", "instagram"), "comment"),
    _h("H78", "Interesting data.", ("x", "instagram"), "comment"),
    _h("H79", "Interesting thread.", ("x", "instagram"), "comment"),
    _h("H80", "Nice breakdown.", ("x", "instagram"), "comment"),
    _h("H81", "Good context here.", ("x", "instagram"), "comment"),
    _h("H82", "Helpful thread, thanks.", ("x", "instagram"), "comment"),
    _h("H83", "This is a useful chart.", ("x", "instagram"), "comment"),
    _h("H84", "Great question.", ("x", "instagram"), "comment"),
    _h("H85", "Interesting angle.", ("x", "instagram"), "comment"),
    _h("H86", "Clear and useful, thanks.", ("x", "instagram"), "comment"),
]
HOOK_BY_ID = {h["id"]: h for h in HOOKS}
# A phrasing id or hook id used in one of the last ROTATION_POSTS own posts of the same item type on the same platform
# is not used again (grok_review.rotation_reasons); when every phrasing of a fact was used in that window, only the
# least recently used one may come back (so a fact is never blocked outright).
ROTATION_POSTS = 5

# advice / forecast words: never in a hook (none is in HOOK_WORDS; named here so the reason says why)
ADVICE_WORDS = frozenset("""
buy buying buys sell selling sells hold holding own owning should shouldn't must expect expects expected expecting
due target targets forecast forecasts will won't going gonna undervalued overvalued opportunity opportunities cheap
bargain upside downside predict prediction soon next
""".split())
