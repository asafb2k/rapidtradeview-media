"""2-3 phrasings per fact (HQ 2026-10-19 round 7, Growth: "the verbatim rule makes posts read the same").

Every fact an item states comes in up to MAX_PER_FACT phrasings: the same numbers, the same claim, another order /
subject / verb. facts.py / market_facts.py write the hand-made alternates (a fact = a list of sentences, the first is
its base); this module adds the generic re-orderings and gives every phrasing a stable id:

  id = "<fact key>.<variant>"
    fact key = a hash of the base sentence's SHAPE (cashtags, numbers, names, dates, sectors, the window and the
               direction words blanked), so the same template has the same key on every day and for every company
               ("$GOOGL lost $105.5B of market value on Friday (-2.47%)." and "$NVDA gained $40B of market value today
               (+1.1%)." are one fact key);
    variant  = "a" the base, "h1" / "h2" the hand-made alternates, "t" the window moved to the front ("On Friday,
               $GOOGL lost ..."), "m" a closing signed number as "a move of N" ("..., a move of -2.47%."), "tm" both.

The rotation rule (grok_review.rotation_reasons) reads the ids: a phrasing id used in one of the last 5 own posts of the
same item type on the same platform is not used again, unless every phrasing of its fact was (then only the least
recently used one). facts.self_check validates every phrasing as a one-sentence post and drops the ones that fail.
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
    Only when the sentence names no other date (the moved window must stay the sentence's only one)."""
    m = _TAIL_RX.match(s.strip())
    if not m:
        return None
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
    base, alts = group[0], group[1:]
    out = [("a", base)] + [(f"h{i + 1}", t) for i, t in enumerate(alts)]
    t = front_time(base)
    m = move_of(base)
    tm = move_of(t) if t else None
    for tag, txt in (("t", t), ("m", m), ("tm", tm)):
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
