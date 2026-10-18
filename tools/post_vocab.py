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
