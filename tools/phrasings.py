"""2-3 phrasings per fact (HQ 2026-10-19 round 7, Growth: "the verbatim rule makes posts read the same").

Every fact an item states comes in up to MAX_PER_FACT phrasings: the same numbers, the same claim, another order /
subject / verb. facts.py / market_facts.py write the hand-made alternates (a fact = a list of sentences, the first is
its base); this module adds the generic re-orderings and gives every phrasing a stable id:

  id = "<fact key>.<variant>"
    fact key = a hash of the base sentence's SHAPE (cashtags, numbers, names, dates, sectors, the window and the
               direction words blanked), so the same template has the same key on every day and for every company
               ("$GOOGL lost $105.5B of market value on Friday (-2.47%)." and "$NVDA gained $40B of market value today
               (+1.1%)." are one fact key);
    variant  = "a" the base, "h1" / "h2" the hand-made alternates (facts.py / market_facts.py groups, then the template
               alternates below: TEMPLATE_ALTS), "t" the window moved to the front ("On Friday, $GOOGL lost ..."; a
               ranked list too: "On Friday, the biggest dollar drops ..., in order: ..."), "l" a ranked list read
               subjects first ("$GOOGL (-$105.5B) and $MSFT (-$77.2B) were the biggest dollar drops ..., in that
               order."), "o" a ranked subject last ("The second-largest company reporting earnings this week (...):
               $META."), "f" a count read "Of the M ..., N ...", "m" a closing signed number as "a move of N"
               ("..., a move of -2.47%."), "tm" both.

The rotation rule (grok_review.rotation_reasons, review round 7b) reads the ids: a phrasing id used in one of the last
min(5, k - 1) own posts of the same item type on the same platform is not used again, k = the number of phrasings of its
fact (a fact with 3 phrasings cycles a, b, c and is never blocked outright; a fact with one phrasing cannot rotate).
facts.self_check validates every phrasing as a one-sentence post and drops the ones that fail.
"""
from __future__ import annotations

import hashlib
import re

MAX_PER_FACT = 3
_DAYS = r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
_MON = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
# the window / date a sentence may end with (before an optional closing parenthesis and the full stop)
TIME_TAIL = (rf"today|last week|this week|next week|in the week to (?:{_MON}) \d{{1,2}}"
             rf"|on (?:{_DAYS})(?:, (?:{_MON}) \d{{1,2}})?|on (?:{_MON}) \d{{1,2}}"
             rf"|over \d+ days(?: in our feed)?|at the (?:{_MON}) \d{{1,2}} close")
_TAIL_RX = re.compile(rf"^(?P<body>.+?)\s+(?P<time>{TIME_TAIL})(?P<paren>\s*\([^()]*\))?\.$")
_SIGNED_PAREN = re.compile(r"^(?P<body>.+?)\s*\((?P<num>[+\-−]\$?\d[\d.,]*[KMBT]?%?)\)\.$")
_TIME_ANY = re.compile(rf"\b(?:{_DAYS})\b|\b(?:{_MON}) \d{{1,2}}\b|\btoday\b|\byesterday\b|\b(?:last|this|next) week\b"
                       r"|\bover \d+ days\b|\bin the week to\b")
# first words that are not names: lower-cased when the window moves in front of them ("On Friday, the 500 ...")
_LOWER_FIRST = {"The", "A", "An", "Members", "Officers", "Most", "Every", "All", "Held", "Only", "Owning", "Of", "In",
                "Over", "Weighted", "Among", "Automatic", "From", "Traded", "About", "Insiders", "Earnings"}
_DIRECTION = re.compile(r"\b(?:lost|gained|fell|rose|drops?|gains?|dropped|declined|added|worst|best|biggest|drags?|lifts?"
                        r"|losers?|gainers?|buys?|sells?|bought|sold|purchases?|sales?|up|down|cost|made)\b", re.IGNORECASE)


# capitalised first words that are template words, not names (kept in the shape)
_COMMON_FIRST = {w.lower() for w in _LOWER_FIRST} | {"on", "at", "reddit", "congress", "sync", "for", "with"}


# a sentence that already opens with a framing phrase ("By market value, ...", "Over 30 days, ...") keeps its order
_FRAMED = re.compile(r"^(?:By|In|Over|Among|Of|Held|Weighted|On|At|From|Traded|After|Before|For)\b[^,]{0,40},")


def _lower_first(s: str) -> str:
    w = s.split(" ", 1)[0]
    return s[0].lower() + s[1:] if w in _LOWER_FIRST else s


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def front_time(s: str) -> str | None:
    """The trailing window moved to the front: "X lost $1T on Friday (-1.2%)." -> "On Friday, x lost $1T (-1.2%)."
    Only when the sentence names no other date (the moved window must stay the sentence's only one). A ranked list whose
    head ends with the window likewise: "The best sectors last week, in order: A (+1%), B (+0.5%)." -> "Last week, the
    best sectors, in order: A (+1%), B (+0.5%)."."""
    m = _TAIL_RX.match(s.strip())
    if not m:
        lm = _IN_ORDER.match(s.strip())
        hm = _HEAD_TIME.match(lm.group("head")) if lm else None
        if not hm:
            return None
        body, time = hm.group("body"), hm.group("time")
        if _TIME_ANY.search(body) or body.endswith(",") or _FRAMED.match(body) or _PRE.match(body):
            return None
        return f"{_cap(time)}, {_lower_first(body)}, in order: {lm.group('items')}."
    body, time, paren = m.group("body"), m.group("time"), m.group("paren") or ""
    if _TIME_ANY.search(body) or body.endswith(",") or _FRAMED.match(body):
        return None
    return f"{_cap(time)}, {_lower_first(body)}{paren}."


def move_of(s: str) -> str | None:
    """A closing signed number in parentheses as "a move of N": "... on Friday (+2.64%)." -> "... on Friday, a move of
    +2.64%." (same tokens otherwise; unsigned numbers - counts, shares - are left alone)."""
    m = _SIGNED_PAREN.match(s.strip())
    # never inside a list ("in order: $A (+2.0%), $B (-1.1%)."): the body holds no other parenthesis
    if not m or "(" in m.group("body") or ":" in m.group("body"):
        return None
    return f"{m.group('body').rstrip(',')}, a move of {m.group('num')}."


_IN_ORDER = re.compile(r"^(?P<head>.+?), in order: (?P<items>.+)\.$")
_HEAD_TIME = re.compile(rf"^(?P<body>.+?)\s+(?P<time>{TIME_TAIL})$")
# a framing window in front of a sentence ("Over the 60 sessions before Oct 16, 2026, ...")
_PRE = re.compile(rf"^(?P<pre>Over the \d+ sessions before (?:{_MON}) \d{{1,2}}, \d{{4}}), (?P<rest>.+)$")


def split_top(s: str) -> list[str]:
    """Split a list on ", " outside parentheses: "$A (+1.0%), $B (-2,000)" -> ["$A (+1.0%)", "$B (-2,000)"]."""
    out, depth, cur, i = [], 0, "", 0
    while i < len(s):
        c = s[i]
        depth += (c == "(") - (c == ")")
        if depth == 0 and s.startswith(", ", i):
            out.append(cur)
            cur, i = "", i + 2
            continue
        cur += c
        i += 1
    out.append(cur)
    return [x.strip() for x in out if x.strip()]


def and_join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def list_first(s: str) -> str | None:
    """A ranked list read subjects first: "{head}, in order: A, B, C." -> "A, B and C were {head}, in that order."
    (a framing window in front stays in front)."""
    m = _IN_ORDER.match(s.strip())
    if not m:
        return None
    head, parts = m.group("head"), split_top(m.group("items"))
    if len(parts) < 2 or any(" and " in p or ":" in p for p in parts):
        return None
    pre = ""
    pm = _PRE.match(head)
    if pm:
        pre, head = pm.group("pre") + ", ", pm.group("rest")
    return f"{pre}{and_join(parts)} were {_lower_first(head)}, in that order."


_ORDINAL = re.compile(r"^(?P<s>\$[A-Z][A-Za-z.\-]{0,7}) (?:is|was|had) the (?P<rest>[^()]+?) \((?P<n>[^()]+)\)\.$")


def subject_last(s: str) -> str | None:
    """A ranked subject read last: "$META is the second-largest company ... (x)." -> "The second-largest company ...
    (x): $META."."""
    m = _ORDINAL.match(s.strip())
    if not m or m.group("rest").startswith(("same ", "only ")):
        return None
    return f"The {m.group('rest')} ({m.group('n')}): {m.group('s')}."


_OF_COUNT = re.compile(r"^(?P<only>Only )?(?P<n>\d[\d,]*) of (?P<the>the )?(?P<m>\d[\d,]*) (?P<noun>[^,:()]+?) "
                       r"(?P<verb>fell|rose|had|were|was|report|reported|moved|gained|lost|closed|ended|traded|disclosed)"
                       r"\b(?P<rest>[^:]*)\.$")


def of_front(s: str) -> str | None:
    """A count read "Of the M ..., N ...": "445 of the 500 largest US-listed stocks had a price on Friday." -> "Of the
    500 largest US-listed stocks, 445 had a price on Friday."."""
    m = _OF_COUNT.match(s.strip())
    if not m:
        return None
    only = "only " if m.group("only") else ""
    return (f"Of {m.group('the') or ''}{m.group('m')} {m.group('noun')}, {only}{m.group('n')} {m.group('verb')}"
            f"{m.group('rest')}.")


# Hand-written alternates per template (review round 7b, HQ 2026-10-19: every claim fact gets 3 phrasings). Each entry:
# a pattern over the base sentence and the alternates as format strings over its named groups ("<name>_l": the group
# with its first letter lower-cased; a one-letter group's upper-case name: the group capitalised). Same numbers, same
# claim, another order / subject / verb. facts.self_check still checks every one as a post.
_W = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday)"
_LEAD = rf"Over the \d+ sessions before (?:{_MON}) \d{{1,2}}, \d{{4}}"
_T = r"\$[A-Z][A-Za-z.\-]{0,7}"
_WEEK = rf"this week|next week|in the week of (?:{_MON}) \d{{1,2}}"
TEMPLATE_ALTS: list[tuple[re.Pattern, list[str]]] = [
    # Moves Like
    (re.compile(rf"^(?P<lead>{_LEAD}), (?P<t>{_T}) moved most like (?P<p>{_T}) \(Sync (?P<n>\d+)\)\.$"),
     ["{t} moved most like {p} {lead_l} (Sync {n}).", "{lead}, {t}'s closest peer by Sync was {p} ({n})."]),
    (re.compile(rf"^Over (?P<d>\d+) sessions, (?P<t>{_T}) moved most like (?P<p>{_T}) \(Sync (?P<n>\d+)\)\.$"),
     ["{t} moved most like {p} over {d} sessions (Sync {n}).",
      "Over {d} sessions, {t}'s closest peer by Sync was {p} ({n})."]),
    (re.compile(rf"^(?P<lead>{_LEAD}), (?P<p>{_T}) was the (?P<o>[a-z]+-)closest peer of (?P<t>{_T}) by Sync "
                r"\((?P<n>\d+)\)\.$"),
     ["{p} was the {o}closest peer of {t} by Sync ({n}) {lead_l}.",
      "{lead}, {t}'s {o}closest peer by Sync was {p} ({n})."]),
    (re.compile(rf"^(?P<lead>{_LEAD}), (?P<t>{_T})'s closest peers by Sync, in order: (?P<items>.+)\.$"),
     ["{t}'s closest peers by Sync {lead_l}, in order: {items}."]),
    # Reddit buzz
    (re.compile(rf"^Reddit mentions of (?P<t>{_T}) hit (?P<x>[\d.,]+×) its (?P<u>usual(?: weekend)? count): "
                r"(?P<a>[\d.,]+) vs (?P<b>[\d.,]+)\.$"),
     ["{t} drew {a} Reddit mentions vs its {u} of {b} ({x}).", "At {a} vs {b}, Reddit mentions of {t} ran {x} its {u}."]),
    (re.compile(rf"^Among (?P<among>.+?), (?P<t>{_T}) had the highest mentions-vs-usual ratio \((?P<r>[^()]+)\)\.$"),
     ["{t} had the highest mentions-vs-usual ratio ({r}) among {among}.",
      "Among {among}, the highest mentions-vs-usual ratio belonged to {t} ({r})."]),
    # Market cap rank (mega_mover)
    (re.compile(rf"^(?P<t>{_T}) is one of the (?P<n>\d+) largest US-listed companies by market cap \((?P<r>#\d+)\)\.$"),
     ["By market cap, {t} is one of the {n} largest US-listed companies ({r}).",
      "{t} ranks {r} by market cap, one of the {n} largest US-listed companies."]),
    (re.compile(rf"^(?P<t>{_T}) was (?P<r>#\d+) by market cap among (?P<u>.+?) (?P<w>on {_W}|today)\.$"),
     ["By market cap, {t} was {r} among {u} {w}.", "{t} ranked {r} by market cap among {u} {w}."]),
    # Insider flow ratio
    (re.compile(r"^For every \$1 officers and directors bought on the open market (?P<w>over \d+ days in our feed), "
                r"they sold (?P<s>\$[\d.,]+)\.$"),
     ["Officers and directors sold {s} for every $1 they bought on the open market {w}.",
      "{W}, officers and directors sold {s} on the open market for every $1 they bought."]),
    # Breadth
    (re.compile(rf"^Most (?P<u>US stocks RapidTradeView tracks) (?P<v>fell|rose) (?P<w>on {_W}|today): "
                r"(?P<a>[\d,]+) of (?P<b>[\d,]+) \((?P<p>[\d.]+%)\)\.$"),
     ["{W}, most {u} {v}: {a} of {b} ({p}).", "{a} of the {b} {u} {v} {w} ({p})."]),
    (re.compile(rf"^(?P<d>(?:{_MON}) \d{{1,2}}) was the strongest (?P<k>up|down) day of the last (?P<n>\d+) closes "
                r"\((?P<x>[^()]+)\)\.$"),
     ["The strongest {k} day of the last {n} closes was {d} ({x}).",
      "Of the last {n} closes, {d} was the strongest {k} day ({x})."]),
    (re.compile(rf"^(?P<day>{_W}) came a day after the strongest (?P<k>up|down) day of the last (?P<n>\d+) closes"
                r"(?P<paren> \([^()]+\))?\.$"),
     ["{day} followed the strongest {k} day of the last {n} closes{paren}.",
      "The strongest {k} day of the last {n} closes came the day before {day}{paren}."]),
    # Earnings week
    (re.compile(rf"^The largest companies reporting earnings (?P<w>{_WEEK}) \(by market value, confirmed "
                r"dates\), in order: (?P<items>.+)\.$"),
     ["By market value, the largest companies reporting earnings {w} (confirmed dates), in order: {items}."]),
    (re.compile(rf"^(?P<t>{_T}) is the (?P<o>(?:second-|third-|fourth-|fifth-)?largest) company reporting earnings "
                rf"(?P<w>{_WEEK}) \(by market value, confirmed dates\)\.$"),
     ["By market value, {t} is the {o} company reporting earnings {w} (confirmed dates)."]),
    # Sector movers, Reddit counts
    (re.compile(rf"^By market value, (?P<t>{_T}) was the biggest (?P<s>[A-Z][A-Za-z ]+?) name moving with its sector "
                rf"(?P<w>on {_W}|today|last week|in the week to (?:{_MON}) \d{{1,2}}) \((?P<x>[^()]+)\)\.$"),
     ["{t} was the biggest {s} name by market value moving with its sector {w} ({x}).",
      "{W}, {t} was the biggest {s} name moving with its sector, by market value ({x})."]),
    (re.compile(rf"^(?P<t>{_T}) had the most Reddit mentions of the stocks on the buzz card \((?P<n>[\d,]+)\)\.$"),
     ["Of the stocks on the buzz card, {t} had the most Reddit mentions ({n}).",
      "The most Reddit mentions of the stocks on the buzz card went to {t} ({n})."]),
    (re.compile(r"^(?P<n>\d+) of the (?P<m>\d+) most-mentioned stocks with a close for (?P<d>(?:" + _MON + r") \d{1,2}) "
                r"(?P<v>fell|rose) that day\.$"),
     ["On {d}, {n} of the {m} most-mentioned stocks with a close that day {v}."]),
    # A session move (context facts of many types)
    (re.compile(rf"^(?P<t>{_T}) moved (?P<x>[+\-−][\d.,]+%) (?P<w>on {_W}(?:, (?:{_MON}) \d{{1,2}})?|today|last week)\.$"),
     ["{t}'s move {w}: {x}."]),
    (re.compile(rf"^The 500 largest US-listed stocks moved (?P<x>[+\-−][\d.,]+%) (?P<w>on {_W}|today|last week)\.$"),
     ["The 500 largest US-listed stocks' move {w}: {x}."]),
    (re.compile(rf"^The 500 largest US-listed stocks moved (?P<x>[+\-−][\d.,]+%) (?P<w>on {_W}|today|last week), "
                r"weighted by market value\.$"),
     ["{W}, the 500 largest US-listed stocks moved {x}, weighted by market value."]),
    # Earnings dates
    (re.compile(rf"^(?P<t>{_T}) reports earnings (?P<w>on {_W}, (?:{_MON}) \d{{1,2}}), (?P<s>before the open|after the "
                r"close) \(confirmed date\)\.$"),
     ["{W}, {s}, {t} reports earnings (confirmed date)."]),
    (re.compile(rf"^(?P<name>[^()]+?) \((?P<t>{_T})\) reports earnings (?P<w>on {_W}, (?:{_MON}) \d{{1,2}}), "
                r"(?P<s>before the open|after the close) \(confirmed date\)\.$"),
     ["{W}, {s}, {name} ({t}) reports earnings (confirmed date)."]),
    (re.compile(rf"^(?P<l>\$[^()]+?) report earnings (?P<w>on {_W}, (?:{_MON}) \d{{1,2}}), (?P<s>before the open|after "
                r"the close) \(confirmed dates\)\.$"),
     ["Reporting earnings {w}, {s} (confirmed dates): {l}."]),
    # Form 4 buys
    (re.compile(rf"^(?P<who>[^$()]+?) bought (?P<a>\$[\d.,]+[KMB]?) of (?P<t>{_T}) on the open market\.$"),
     ["On the open market, {who} bought {a} of {t}.", "{who} made an open-market purchase of {t}: {a}."]),
    (re.compile(rf"^(?P<who>.+?) reported an open-market purchase of (?P<t>{_T}) totaling (?P<a>\$[\d.,]+[KMB]?) on a "
                rf"Form 4 filed (?P<d>(?:{_MON}) \d{{1,2}})\.$"),
     ["On a Form 4 filed {d}, {who} reported an open-market purchase of {t} totaling {a}."]),
    # Congress flow
    (re.compile(rf"^(?P<t>{_T}) was the most-traded of the 500 largest US-listed stocks in Congress over (?P<d>\d+) days "
                r"\((?P<n>[^()]+)\)\.$"),
     ["In Congress over {d} days, {t} was the most-traded of the 500 largest US-listed stocks ({n})."]),
]


def template_alts(base: str) -> list[str]:
    """The TEMPLATE_ALTS alternates of a base sentence ([] when no template matches)."""
    for rx, outs in TEMPLATE_ALTS:
        m = rx.match(base.strip())
        if not m:
            continue
        g = {k: (v or "") for k, v in m.groupdict().items()}
        g.update({f"{k}_l": v[:1].lower() + v[1:] for k, v in list(g.items())})
        g.update({k.upper(): v[:1].upper() + v[1:] for k, v in list(g.items()) if len(k) == 1})
        return [o.format(**g) for o in outs]
    return []


def shape(s: str) -> str:
    """The template of a sentence: everything that changes from day to day or company to company blanked."""
    x = " " + s + " "
    x = re.sub(TIME_TAIL, " WHEN ", x)
    x = re.sub(rf"\b(?:{_DAYS})\b|\b(?:{_MON})\b \d{{1,2}}(?:, \d{{4}})?", " D ", x)
    x = re.sub(r"\$[A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?(?:['’]s)?", " T ", x)
    x = re.sub(r"[+\-−]?\$?\d[\d.,]*(?:[KMBT%x×]|\b)", " N ", x)
    x = _DIRECTION.sub(" DIR ", x)
    # any word with a capital letter that does not start the sentence: a name, a company, a sector, a title
    toks = x.split()
    out = []
    for i, t in enumerate(toks):
        if (re.search(r"[A-Z]", t) and t not in ("WHEN", "D", "T", "N", "DIR", "US-listed")
                and not (i == 0 and t.lower() in _COMMON_FIRST)):
            t = "W"
        out.append(t.lower() if t not in ("WHEN", "D", "T", "N", "DIR", "W") else t)
    joined = " ".join(out)
    joined = re.sub(r"[(),.:;]", " ", joined)
    joined = re.sub(r"\b(W)(?:\s+W)+\b", r"\1", " ".join(joined.split()))
    return joined


def fact_key(base: str, kind: str | None) -> str:
    return f"{(kind or 'x').replace('_', '')[:10]}-{hashlib.sha1(shape(base).encode('utf-8')).hexdigest()[:6]}"


def norm_groups(out) -> list[list[str]]:
    """facts.py / market_facts.py phrase lists: a str is a fact on its own, a list / tuple a fact with alternates (first =
    base). Whitespace collapsed; a sentence with a missing value ("None", "nan", "{") or a repeat is dropped."""
    seen: set[str] = set()
    groups = []
    for g in out or []:
        texts = [g] if isinstance(g, str) else list(g or [])
        clean = []
        for t in texts:
            x = " ".join(str(t).split())
            if not x or re.search(r"None|nan|[{}]", x) or x in seen:
                continue
            seen.add(x)
            clean.append(x)
        if clean:
            groups.append(clean)
    return groups


def flat(groups: list[list[str]]) -> list[str]:
    return [t for g in groups for t in g]


def variants(group: list[str]) -> list[tuple[str, str]]:
    """[(variant tag, text)] of one fact: the base, the hand-made alternates, then the generic re-orderings of the base
    until MAX_PER_FACT."""
    base, alts = group[0], list(group[1:])
    alts += [x for x in template_alts(base) if x not in alts and x != base]
    out = [("a", base)] + [(f"h{i + 1}", t) for i, t in enumerate(alts)]
    t = front_time(base)
    m = move_of(base)
    tm = move_of(t) if t else None
    for tag, txt in (("t", t), ("l", list_first(base)), ("o", subject_last(base)), ("f", of_front(base)), ("m", m),
                     ("tm", tm)):
        if len(out) >= MAX_PER_FACT:
            break
        if txt and all(txt != x for _, x in out):
            out.append((tag, txt))
    return out[:MAX_PER_FACT] if len(out) > MAX_PER_FACT else out


def build(kind: str | None, claim_groups: list[list[str]], fact_groups: list[list[str]]) -> list[dict]:
    """[{id, fact, variant, text, claim}] for every phrasing of the item, claim facts first."""
    out: list[dict] = []
    seen: set[str] = set()
    for is_claim, groups in ((True, claim_groups), (False, fact_groups)):
        for g in groups:
            if not g:
                continue
            key = fact_key(g[0], kind)
            for tag, txt in variants(g):
                if txt in seen:
                    continue
                seen.add(txt)
                out.append({"id": f"{key}.{tag}", "fact": key, "variant": tag, "text": txt, "claim": is_claim})
    return out
