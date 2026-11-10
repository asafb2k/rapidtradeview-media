"""Text QA for the cartoon-story Reel (cartoon_reel.py): pure functions, no rendering, so the gates are unit-tested offline
(tools/tests/test_cartoon_qa.py).

  find_numbers(text)                 every number-like token (money, %, dates, counts); document names such as "Form 4" are
                                     names, not numbers
  find_number_words(text)            spelled-out numbers ("fifteen million", "sixth"); a lone "one" is a word, not data
  numbers_gate(texts, allowed, ...)  every number we draw, caption or speak is one of the item's numbers, as written there,
                                     and no number is typed into the script as words
  weekday_gate(texts, item, post)    a weekday name is the weekday of an item date, or of the day the video is posted
  spoken_numbers_gate(say)           every spelled-out number we make the voice say equals the figure it stands for
  screen_numbers_gate(...)           every number visible in ONE real screenshot comes from the item or is acknowledged for
                                     that screen; an acknowledgement cannot explain away a value the item carries
  provider_gate(texts)               no data-provider names (card_reel.PROVIDER_RX)
  banned_gate(texts, banned)         none of the item's banned words, inflections included ("moons", "mooning")
  caption_gate(chunks, script)       the captions, joined, are exactly the voice script (quote marks and brackets not shown)
  fact_phrase_gate(...)              the one data sentence is the item's own phrasing, verbatim, in the voice or on screen
  claim_lines_gate(lines, item, ..)  every story line that states a fact is tagged with the phrasing it paraphrases and uses
                                     only that phrasing's numbers and names (listed for a human check)
  occlusion_gate(samples)            captions never sit on a face, a held prop, a bubble, a chip or the key number
  chunk_words(words, measure)        the caption chunker (1-3 words, <= 18 characters, never across a sentence end)

Brand and format gates (owner verdict 2026-11-09: "the pilot short is too complicated and it isnt clear what brand behind
it"):
  brand_spoken_gate(words, total)    the voice says "RapidTradeView" in the first 5 s and again in the last 5 s
  region_match(region, ref)          (correlation, mean abs diff) of a decoded frame region against the planned pixels
  brand_pill_gate(samples)           the persistent brand pill is on screen in every sampled frame
  pill_clear_gate(samples)           no standing real card sits under that pill (no two logos colliding)
  payoff_brand_gate(samples)         the payoff's real screen shows our own header/logo, readable, for long enough
  one_idea_gate(shots, total)        one situation: 15-22 s, at most 7 shots, no side-gag props
  item_page_urls(item)               the real pages a capture may come from (the item's page, its earnings report page)

Feature shorts (owner 2026-11-10; no facts item, the capture made on the render day is the truth; registry features.json):
  load_features() / registry_problems(reg)   the registry and what is wrong with it
  feature_values(feature, sidecars)  the slot values, read from the captures' visible text by the registry's rules
  feature_item(...)                  the item the number / claim / hook gates run against, built from the captures
  feature_capture_gate(...)          our page (asked for and ended on), captured today, data loaded, no provider name on
                                     what is shown, the sidecar unedited (capture_seal)
  feature_story_gate(...)            the story's lines, chip, phone, key and outline are the registry's templates filled from
                                     the sidecars, and its say map is exactly the generator's (feature_say): the voice says
                                     nothing the captions do not show
  shown_text(meta) / vendor_hits(t)  the text inside a capture / provider and source brands in a text (look-alikes folded)
  say_map / speak_figure             the spoken forms (figures to words, the ticker as letters): the only say-map source
  feature_fact_gate(...)             the one data phrase is on a capture and read aloud, word for word
  key_target_gate(samples, fps, kind) the outlined key is big enough for long enough (a figure, or a chart)
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import hashlib
import sys
import unicodedata
from pathlib import Path

import importlib.util  # noqa: E402


def _load_card_reel():
    """The v6cat card-Reel renderer, loaded by path as gv_card_reel (tools/card_reel.py, the daily runner, has the same
    module name)."""
    if "gv_card_reel" in sys.modules:
        return sys.modules["gv_card_reel"]
    path = Path(__file__).resolve().parents[1] / "v6cat" / "card_reel.py"
    spec = importlib.util.spec_from_file_location("gv_card_reel", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gv_card_reel"] = mod
    spec.loader.exec_module(mod)
    return mod


cr = _load_card_reel()

PROVIDER_RX = cr.PROVIDER_RX
WEAK_END = cr.WEAK_END
ABBREV_RX = cr.ABBREV_RX
FIGURE_RX = cr.FIGURE_RX

MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
DOC_NAME_RX = re.compile(r"(?<![A-Za-z0-9])(?:Form\s+(?:3|4|5|144|13F|13D|13G|8-K|10-K|10-Q)|13F|10-K|10-Q|8-K|10b5-1)(?![A-Za-z0-9])")
DATE_RX = re.compile(rf"(?<![A-Za-z0-9]){MONTHS}\s+\d{{1,2}}(?:,\s+\d{{4}})?(?![0-9])|\d{{4}}-\d{{2}}-\d{{2}}")
FISCAL_RX = re.compile(r"(?<![A-Za-z0-9])(?:Q[1-4](?:\s+\d{4})?|FY\s?\d{4})(?![A-Za-z0-9])")   # "Q3 2026", "Q3", "FY2026": one token
NUM_RX = re.compile(r"[−+\-]?\$?\d+(?:[,./]\d+)*(?:[KMBT](?![a-z])|%)?")
TRAIL = ".,;:)]!?\"'”"


def norm_num(tok: str) -> str:
    return " ".join(tok.replace("−", "-").split()).strip(TRAIL).lstrip("(\"'“")


def find_numbers(text: str) -> list[str]:
    """Number-like tokens in order: month-day dates ("Nov 6", "Nov 6, 2026") and ISO dates as one token, money and percent
    with their sign/suffix, other digit runs ("2/2", "500"). Document names ("Form 4", "10-K") are skipped."""
    s = DOC_NAME_RX.sub(lambda m: " " * len(m.group(0)), str(text))
    out: list[tuple[int, str]] = []
    for rx in (DATE_RX, FISCAL_RX):
        for m in rx.finditer(s):
            out.append((m.start(), norm_num(m.group(0))))
        s = rx.sub(lambda m: " " * len(m.group(0)), s)
    for m in NUM_RX.finditer(s):
        out.append((m.start(), norm_num(m.group(0))))
    return [t for _, t in sorted(out)]


def allowed_set(item: dict) -> set[str]:
    return {norm_num(x) for x in (item.get("allowed_numbers") or []) + (item.get("context_numbers") or []) if isinstance(x, str)}


def numbers_gate(texts: dict[str, str], allowed: set[str] | list[str], words: bool = True) -> tuple[bool, dict]:
    """texts: role -> text. Every number token must be in `allowed` (normalised: - and the minus sign alike). With `words`
    (the default) a spelled-out number fails too: the script writes a figure as the item does ("$14.99M") and the say map
    spells it for the voice, where spoken_numbers_gate checks the value. Pass words=False only for the TTS text."""
    ok_set = {norm_num(a) for a in allowed}
    bad: dict[str, list[str]] = {}
    seen: dict[str, list[str]] = {}
    spelled: dict[str, list[str]] = {}
    for role, txt in texts.items():
        nums = find_numbers(txt)
        if nums:
            seen[role] = nums
        miss = [n for n in nums if n not in ok_set]
        if miss:
            bad[role] = miss
        if words:
            nw = find_number_words(txt)
            if nw:
                spelled[role] = nw
    return not bad and not spelled, {"not_in_item": bad, "number_words": spelled, "found": seen}


# ------------------------------------------------------------------------------------------------- spoken numbers
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                      "fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
        "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
        "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30}
_SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
_SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def spoken_value(s: str) -> float | None:
    """English number words -> value ("fourteen point nine nine million dollars" -> 14990000, "sixth" -> 6, "twenty-first" ->
    21). None when the text has no number words."""
    words = [w for w in re.split(r"[\s\-]+", re.sub(r"[^a-z\s\-]", " ", s.lower())) if w]
    total, cur, frac, in_frac, found = 0.0, 0.0, "", False, False
    for w in words:
        if w in _UNITS or w in _ORD:
            v = _UNITS.get(w, _ORD.get(w))
            found = True
            if in_frac:
                frac += str(v)
            else:
                cur += v
        elif w in _TENS:
            cur += _TENS[w]
            found = True
        elif w == "hundred":
            cur = (cur or 1) * 100
        elif w == "point":
            in_frac = True
        elif w in _SCALE:
            val = cur + (float("0." + frac) if frac else 0.0)
            total += (val or 1) * _SCALE[w]
            cur, frac, in_frac = 0.0, "", False
            found = True
    if not found:
        return None
    return total + cur + (float("0." + frac) if frac else 0.0)


NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_ORD) | set(_SCALE) | {"hundred", "dozen", "dozens", "half", "twice", "thrice",
                                                                    "double", "triple", "quadruple", "hundreds", "thousands",
                                                                    "millions", "billions", "trillions", "halves", "doubled",
                                                                    "tripled"}
NON_DATA_WORDS = {"one"}               # "one app", "one name", "ONE SEARCH": a word, not a figure
_GLUE = {"point", "and", "a"}


def find_number_words(text: str) -> list[str]:
    """Runs of spelled-out number words ("fifteen million dollars" -> "fifteen million", "twenty-first", "sixth",
    "fourteen point nine nine million"). A run that is only "one", or "second" on its own (time), is not a number."""
    toks = re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*|[.,;:!?()\"]", str(text))      # punctuation ends a run
    out: list[str] = []
    run: list[str] = []

    def flush():
        while run and run[-1].lower() in _GLUE:
            run.pop()
        while run and run[0].lower() in _GLUE:
            run.pop(0)
        if run:
            low = [w.lower() for w in run]
            if not (len(low) == 1 and low[0] in NON_DATA_WORDS | {"second"}):
                out.append(" ".join(run))
        run.clear()

    for t in toks:
        if t.lower() == "second" or not t[0].isalpha():   # "a second" is time, not a figure; punctuation ends a run
            flush()
        elif all(p in NUMBER_WORDS for p in t.lower().split("-")):
            run.append(t)
        elif run and t.lower() in _GLUE:
            run.append(t)
        else:
            flush()
    flush()
    return out


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
WEEKDAY_RX = re.compile(r"(?<![A-Za-z])(" + "|".join(WEEKDAYS) + r")(?![A-Za-z])", re.IGNORECASE)


def _weekday(word: str) -> str:
    return word[:1].upper() + word[1:].lower()


def item_dates(item: dict) -> list[dt.date]:
    out = []
    for d in [item.get("filed")] + list(item.get("traded") or []):
        try:
            out.append(dt.date.fromisoformat(str(d)[:10]))
        except ValueError:
            pass
    return out


def allowed_weekdays(item: dict, post_date: str | None = None) -> dict[str, str]:
    """Weekday -> why it may be named: the weekday of an item date (filed, traded) or of the story's post_date."""
    allowed = {WEEKDAYS[d.weekday()]: f"item date {d.isoformat()}" for d in item_dates(item)}
    if post_date:
        pd_ = dt.date.fromisoformat(str(post_date)[:10])
        allowed.setdefault(WEEKDAYS[pd_.weekday()], f"post_date {pd_.isoformat()} (story time)")
    return allowed


def weekday_gate(texts: dict[str, str], item: dict, post_date: str | None = None) -> tuple[bool, dict]:
    """A weekday name in the script or on screen is the weekday of one of the item's dates (filed, traded: "Friday" for a
    Form 4 filed 2026-11-06), or the weekday of the story's post_date (story time: "Monday. Leg day." only works when the
    video goes out on a Monday)."""
    try:
        allowed = allowed_weekdays(item, post_date)
    except ValueError:
        return False, {"error": f"post_date {post_date!r} is not an ISO date"}
    bad: dict[str, list[str]] = {}
    seen: dict[str, list[str]] = {}
    for role, txt in texts.items():
        for m in WEEKDAY_RX.finditer(str(txt)):
            day = _weekday(m.group(1))
            seen.setdefault(day, []).append(role)
            if day not in allowed:
                bad.setdefault(role, []).append(day)
    return not bad, {"allowed": allowed, "found": {k: sorted(set(v)) for k, v in seen.items()}, "wrong_weekday": bad}


def written_value(tok: str) -> float | None:
    """"$14.99M" -> 14990000, "6)." -> 6, "4," -> 4, "$14,994,200" -> 14994200. None without digits."""
    m = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", tok)
    if not m:
        return None
    v = float(m.group(0).replace(",", ""))
    suf = tok[m.end():m.end() + 1]
    return v * _SUFFIX.get(suf, 1.0)


def spoken_numbers_gate(say: dict[str, str]) -> tuple[bool, dict]:
    """Every say-map entry whose written form has a digit must speak the same value (and a spelled value must not appear for
    a written form without digits, e.g. "socks" -> "two socks", "lots" -> "a dozen")."""
    bad = {}
    for written, spoken in say.items():
        wv, sv = written_value(written), spoken_value(spoken)
        if re.search(r"\d", spoken):
            bad[written] = f"spoken form has digits: {spoken!r}"
        elif wv is None and (sv is not None or find_number_words(spoken)):     # "a dozen", "half", "hundreds" too
            bad[written] = f"adds a number: {spoken!r}"
        elif wv is not None and (sv is None or abs(sv - wv) > 1e-6 * max(1.0, wv)):
            bad[written] = f"{spoken!r} is {sv}, not {wv}"
    return not bad, {"mismatch": bad, "checked": len(say)}


# ------------------------------------------------------------------------------------------------- spoken forms (the say map)
class TemplateError(Exception):
    """A story cannot be made from this input (make_story / make_feature_story exit 2)."""


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen " \
        "eighteen nineteen".split()
_TENS_W = "twenty thirty forty fifty sixty seventy eighty ninety".split()


def int_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS_W[n // 10 - 2] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + int_words(n % 100))
    if n < 1_000_000:
        return int_words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + int_words(n % 1000))
    if n < 1_000_000_000:
        return int_words(n // 1_000_000) + " million" + ("" if n % 1_000_000 == 0 else " " + int_words(n % 1_000_000))
    raise TemplateError(f"no spoken form for {n}")


def speak_figure(tok: str, unit: bool = True) -> str:
    """"$5.06" -> "five point zero six dollars", "$1.29M" -> "one point two nine million dollars" (spoken_value reads it
    back: the renderer's spoken_numbers gate)."""
    m = re.fullmatch(r"([−+\-]?)(\$?)(\d+(?:,\d{3})*)(?:\.(\d+))?([KMBT]?)(%?)", tok)
    if not m:
        raise TemplateError(f"no spoken form for the figure {tok!r}")
    sign, dollar, whole, frac, suf, pct = m.groups()
    out = int_words(int(whole.replace(",", "")))
    if frac:
        out += " point " + " ".join(_ONES[int(c)] for c in frac)
    out += {"K": " thousand", "M": " million", "B": " billion", "T": " trillion", "": ""}[suf]
    if pct:
        out += " percent"
    if dollar and unit:
        out += " dollars"
    if sign in ("-", "−"):
        out = "minus " + out
    return out


def say_map(lines: list[str], ticker: str, bare: tuple[str, ...] = ()) -> dict[str, str]:
    """Display word (with its punctuation) -> what the voice says, for every figure, the ticker, EPS, vs and our name.
    In the `bare` lines (the read-out fact; the form4 hook) a dollar figure is said without "dollars" ("EPS five point zero
    six", "bought one point two nine million"): the screen shows the $ and the line is shorter. A long plain figure
    ("$1,287,400") keeps its "dollars". This is the ONLY source of a story's say map: a feature story whose say map is not
    exactly this one fails feature_story (a hand-written entry could make the voice say what no caption shows)."""
    say = {}
    ticker = ticker or ""                        # a feature short about a page has no ticker
    letters = " ".join(ticker.replace("-", " "))
    for line in lines:
        unit = line not in bare
        for w in line.split():
            core = w.strip("().,!?:;")
            lead, trail = w[: w.index(core)] if core else "", w[w.index(core) + len(core):] if core else ""
            trail = trail.replace(")", "")
            lead = lead.replace("(", "")
            if re.search(r"\d", core):
                v = written_value(core) or 0.0
                big = v >= 1000 and not re.search(r"\d[KMBT]$", core)      # "$1,287,400" says dollars; "$1.29M" not
                say[w] = lead + speak_figure(core, unit or big) + trail
            elif ticker and core.lstrip("$").upper() == ticker.upper() and len(core.lstrip("$")) <= 5:
                say[w] = lead + letters + trail
            elif core == "EPS":
                say[w] = lead + "E P S" + trail
            elif core == "vs":
                say[w] = lead + "versus" + trail
            elif core == cr.BRAND:
                say[w] = lead + "Rapid Trade View" + trail
    return say


def item_values(item: dict) -> dict[float, str]:
    """|value| -> written form for every non-date number the item carries (allowed + context numbers, amount_top_usd)."""
    out: dict[float, str] = {}
    for x in (item.get("allowed_numbers") or []) + (item.get("context_numbers") or []):
        if not isinstance(x, str) or find_numbers(x) != [norm_num(x)] or DATE_RX.fullmatch(x.strip()):
            continue
        v = written_value(x)
        if v is not None:
            out.setdefault(abs(v), x)
    if isinstance(item.get("amount_top_usd"), (int, float)):
        out.setdefault(abs(float(item["amount_top_usd"])), "amount_top_usd")
    return out


def screen_numbers_gate(visible_text: str, item: dict, ack: dict[str, str]) -> tuple[bool, dict]:
    """Numbers visible in ONE real screenshot: each is an item number as written, an item value in another format (the
    page's "$14,994,200" for amount_top_usd 14994200; the trade count `rows`), or acknowledged for this screen with a
    reason. An acknowledgement is refused when the number's value is one the item carries (then it is data in another
    form, or a different figure that looks like ours: crop it out instead of explaining it away)."""
    if not isinstance(ack, dict) or any(not isinstance(v, str) for v in ack.values()):
        return False, {"error": "screen_numbers_ack must be {screen name: {number: reason}}", "numbers": {}, "unexplained": []}
    others = item_values(item)
    refused: dict[str, str] = {}
    allowed = allowed_set(item)
    values = set()
    for k in ("amount_top_usd", "rows"):
        v = item.get(k)
        if isinstance(v, (int, float)):
            values.add(float(v))
    for d in [item.get("filed")] + list(item.get("traded") or []):
        if isinstance(d, str):
            allowed.add(d)
    out = {}
    for n in find_numbers(visible_text):
        if n in allowed:
            out[n] = "item number"
        elif written_value(n) is not None and written_value(n) in values and not re.search(r"[/%]", n):
            out[n] = "item value"
        elif n in ack and str(ack[n]).strip():
            v = written_value(n)
            if v is not None and abs(v) in others:
                out[n] = None
                refused[n] = f"same value as the item's {others[abs(v)]}"
            else:
                out[n] = "acknowledged: " + str(ack[n]).strip()
        else:
            out[n] = None
    bad = sorted(k for k, v in out.items() if v is None)
    return not bad, {"numbers": out, "unexplained": bad, "ack_refused": refused}


# ------------------------------------------------------------------------------------------------- words
def provider_gate(texts: dict[str, str]) -> tuple[bool, dict]:
    hits = {role: sorted({m.group(0) for m in PROVIDER_RX.finditer(t)}) for role, t in texts.items()}
    hits = {k: v for k, v in hits.items() if v}
    return not hits, {"found": hits}


INFLECT = r"(?:s|es|ed|d|ing|in|in'|er|ers|y|ies|'s)?"


def banned_rx(w: str) -> re.Pattern:
    """A banned term with inflections on its last word ("moon" -> moons, mooning, mooned, moony; "load up" -> "load ups"),
    matched from a word start so "moonlight" and "harmony" stay clean."""
    parts = [re.escape(x) for x in w.lower().split()]
    if not parts:
        return re.compile(r"(?!)")
    body = r"[\s\-]+".join(parts[:-1] + [parts[-1] + INFLECT])
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])")


def banned_gate(texts: dict[str, str], banned: list[str]) -> tuple[bool, dict]:
    every = " \n ".join(texts.values()).lower()
    hits = sorted({w for w in banned if isinstance(w, str) and w.strip() and banned_rx(w).search(every)})
    return not hits, {"found": hits, "checked": len(banned)}


DISPLAY_STRIP = "\"“”()"


def display_word(w: str) -> str:
    """A script word as the caption shows it: quote marks and brackets are dropped (on screen they read as typos; the
    speaker is shown by the caption colour instead)."""
    return "".join(ch for ch in w if ch not in DISPLAY_STRIP)


def display_words(text: str) -> list[str]:
    return [d for d in (display_word(w) for w in str(text).split()) if d]


def caption_gate(chunks: list[str], script: str) -> tuple[bool, dict]:
    """The captions, joined in order, are exactly the voice script's words as displayed (quote marks and brackets
    dropped); reports the first difference."""
    cap, ref = display_words(" ".join(chunks)), display_words(script)
    if cap == ref:
        return True, {"words": len(ref)}
    sm = difflib.SequenceMatcher(a=ref, b=cap, autojunk=False)
    diff = [{"op": op, "script": ref[i1:i2], "captions": cap[j1:j2]} for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
    not_in_script = sorted({w for w in cap if w not in set(ref)})
    return False, {"diff": diff[:8], "caption_words_not_in_script": not_in_script}


def phrase_pool(item: dict) -> list[str]:
    pool = [item.get("facts_text")] + list(item.get("fact_phrases") or []) + list(item.get("angles") or [])
    pool += [p.get("text") for p in item.get("phrasings") or [] if isinstance(p, dict)]
    return [p for p in pool if isinstance(p, str)]


def fact_phrase_gate(phrase: str, item: dict, script: str, on_screen=()) -> tuple[bool, dict]:
    """The one data sentence is one of the item's own phrasings (or its facts_text), verbatim, and the viewer gets it
    whole: in the voice script, or drawn on screen as one text (the receipt card; the renderer gates how long)."""
    norm = cr.norm_ws
    in_item = any(norm(p) == norm(phrase) for p in phrase_pool(item))
    in_script = norm(phrase) in norm(script)
    shown = any(norm(phrase) == norm(t) for t in on_screen)
    return in_item and (in_script or shown), {"phrase": phrase, "in_item": in_item, "in_script": in_script,
                                              "on_screen": shown}


# ------------------------------------------------------------------------------------------------- story lines that state facts
FACT_WORDS = re.compile(r"(?i)(?<![a-z])(bought|buys?|buying|sold|sells?|selling|purchas\w*|filed|filing|reported|traded|"
                        r"chairman|chair|ceo|cfo|director|officer|president|senator|congress\w*|insiders?)(?![a-z])")
_NAME_STOP = {"inc", "corp", "the", "and", "company", "group", "holdings", "ltd", "co"}


def _tickers(item: dict) -> set[str]:
    return {str(t).upper() for t in [item.get("ticker")] + list(item.get("tickers") or []) if t}


def fact_markers(line: str, item: dict, post_date: str | None = None) -> list[str]:
    """Why a story line states a fact: a number, a spelled number, a weekday (other than the post day), the ticker, a word
    of the person's or company's name, or a trade word / title. Empty = a story line (fiction, no check)."""
    why = []
    if find_numbers(line):
        why.append("number")
    if find_number_words(line):
        why.append("number words")
    post_wd = None
    if post_date:
        try:
            post_wd = WEEKDAYS[dt.date.fromisoformat(str(post_date)[:10]).weekday()]
        except ValueError:
            pass
    if any(_weekday(m.group(1)) != post_wd for m in WEEKDAY_RX.finditer(line)):
        why.append("weekday")
    toks = {t.strip(".'$,").lower() for t in re.findall(r"\$?[A-Za-z][A-Za-z.'-]*", line)}
    if {t.upper() for t in toks} & _tickers(item):
        why.append("ticker")
    names = {t.lower() for k in ("name", "company") for t in re.findall(r"[A-Za-z]{3,}", str(item.get(k) or ""))} - _NAME_STOP
    if toks & names:
        why.append("name")
    if FACT_WORDS.search(line):
        why.append("trade word")
    return why


def _claim_problems(line: str, src: str, item: dict, days: set, names: set) -> list[str]:
    probs = []
    src_nums = set(find_numbers(src))
    probs += [f"number {n} is not in the phrasing" for n in find_numbers(line) if n not in src_nums]
    if find_number_words(line):
        probs.append("spelled-out number")
    probs += [f"{_weekday(m.group(1))} is not the weekday of an item date" for m in WEEKDAY_RX.finditer(line)
              if _weekday(m.group(1)) not in days]
    src_words = {w.strip("$.,()'").lower() for w in src.split()}
    for t in re.findall(r"\$?[A-Za-z][A-Za-z.'-]*", line):
        core = t.strip("$.,'").lower()
        if (core.upper() in _tickers(item) or core in names) and core not in src_words:
            probs.append(f"{t} is not in the phrasing")
    return probs


def _overlap(line: str, src: str) -> float:
    """Share of the line's words that are in the phrasing (case and punctuation ignored)."""
    norm = lambda x: {w.strip("$.,()'!?:;").lower() for w in x.split()} - {""}      # noqa: E731
    lw = norm(line)
    return len(lw & norm(src)) / max(1, len(lw))


def claim_lines_gate(lines: list[dict], item: dict, post_date: str | None = None) -> tuple[bool, dict]:
    """lines: [{"line": a shot's vo or drawn text, "claim": phrasing id or None}]. A line that states a fact (fact_markers)
    must carry "claim": the id of the item phrasing it paraphrases. Its numbers must be that phrasing's numbers, its
    weekday the weekday of an item date (or the post day), its ticker and name words words of that phrasing. One id can
    carry several wordings (the facts write "EPS" and its basis, "Adjusted (non-GAAP) Operating Earnings"): the line passes
    when it passes against one of them, and the one it matches best is the "phrasing" a person reads (all of them are in
    "phrasings"). Every tagged line is listed under needs_human_check: a paraphrase can still shift the meaning ("his own
    stock"), so a person reads those lines against the phrasing before the video ships."""
    by_id: dict[str, list[str]] = {}
    for p in item.get("phrasings") or []:
        if isinstance(p, dict) and p.get("id") and p.get("text") and p["text"] not in by_id.get(p["id"], []):
            by_id.setdefault(p["id"], []).append(p["text"])
    try:
        days = set(allowed_weekdays(item, post_date))
    except ValueError:
        days = set(allowed_weekdays(item))
    names = {t.lower() for k in ("name", "company") for t in re.findall(r"[A-Za-z]{3,}", str(item.get(k) or ""))} - _NAME_STOP
    bad, check = [], []
    for ln in lines:
        line, cid = str(ln.get("line") or ""), ln.get("claim")
        why = fact_markers(line, item, post_date)
        if not why and not cid:
            continue
        if not cid:
            bad.append({"line": line, "why": why, "problem": "states a fact but has no claim tag"})
            continue
        srcs = by_id.get(cid)
        if not srcs:
            bad.append({"line": line, "claim": cid, "problem": "claim is not a phrasing id of this item"})
            continue
        scored = sorted(((not _claim_problems(line, x, item, days, names), _overlap(line, x), -len(x), x) for x in srcs),
                        reverse=True)
        src = scored[0][3]
        probs = _claim_problems(line, src, item, days, names)
        if probs:
            bad.append({"line": line, "claim": cid, "problem": "; ".join(probs)})
        entry = {"line": line, "claim": cid, "phrasing": src, "why": why}
        if len(srcs) > 1:
            entry["phrasings"] = srcs
        check.append(entry)
    return not bad, {"bad": bad, "needs_human_check": check}


def pill_clear_gate(samples: list[dict]) -> tuple[bool, dict]:
    """samples: one per rendered frame per real card: {"t", "screen", "overlap_px" (its box against the brand pill's box),
    "moving" (entering or leaving)}. A card that is standing still never sits under the persistent pill: two logos colliding
    and our page's header clipped under it read as a mistake. A card flying in or out may cross it."""
    hits = [s_ for s_ in samples if s_["overlap_px"] > 0 and not s_["moving"]]
    return not hits, {"samples": len(samples), "frames_under_pill": len(hits),
                      "at_s": sorted({s_["t"] for s_ in hits})[:12], "screens": sorted({s_["screen"] for s_ in hits})}


# ------------------------------------------------------------------------------------------------- caption occlusion
def box_overlap(a, b, shrink: float = 6.0) -> float:
    """Intersection area of two (x0, y0, x1, y1) boxes after shrinking each by `shrink` px on every side."""
    w = min(a[2], b[2]) - max(a[0], b[0]) - 2 * shrink
    h = min(a[3], b[3]) - max(a[1], b[1]) - 2 * shrink
    return max(0.0, w) * max(0.0, h)


def occlusion_gate(samples: list[dict]) -> tuple[bool, dict]:
    """samples: [{"t", "caption", "box", "protect": [{"kind", "box"}]}] in screen px. A caption may not overlap a protected
    box: a face, a held prop, a bubble, a chip, the key number, the receipt or the search phone."""
    hits = []
    for s_ in samples:
        for pr in s_.get("protect", []):
            a = box_overlap(s_["box"], pr["box"])
            if a > 0:
                hits.append({"t": round(float(s_["t"]), 2), "caption": s_["caption"], "covers": pr["kind"], "px2": round(a)})
    return not hits, {"hits": hits[:24], "n_hits": len(hits), "samples": len(samples)}


# ------------------------------------------------------------------------------------------------- caption chunks
MAX_WORDS, MAX_CHARS = 4, 18          # 4 words only when they fit 18 characters ("on the open market")


def chunk_words(words: list[str], measure=None, max_px: float = 760.0) -> list[list[int]]:
    """Words -> caption chunks (index lists): 1-3 words (4 short ones) and <= 18 characters (a longer single word stands alone), never
    across a sentence end, not ending on a weak word ("of", "the"), never splitting "Nov 6" / "Form 4" or "Morgan, Inc."; a
    chunk wider than max_px (measure(text) at the smallest caption size) is not allowed unless it is one word."""
    n = len(words)
    INF = float("inf")
    dp, back = [INF] * (n + 1), [0] * (n + 1)
    dp[0] = 0.0

    def cost(i: int, j: int) -> float:
        k = j - i
        text = " ".join(words[i:j])
        if k > 1 and (k > MAX_WORDS or len(text) > MAX_CHARS or (measure and measure(text) > max_px)):
            return INF
        if any(cr.sentence_end(w) or w.endswith(("?", "!", '."', '?"', '!"')) for w in words[i:j - 1]):
            return INF
        c = {1: 0.6, 2: 0.0, 3: 0.6, 4: 1.0}[k]
        if k == 1 and j < n and not (cr.sentence_end(words[i]) or words[i].endswith(("?", "!", ":"))):
            c += 0.05                                  # a tie goes to the split without a lone word mid-sentence ("4" for 0.2 s)
        if any("(" in w for w in words[i + 1:j]):
            c += 2.0                                   # a parenthesis opens a chunk, it does not sit inside one
        if sum(1 for w in words[i:j] if re.search(r"\d,\d{3}", w)) > 1:
            c += 3.0                                   # "2,061 of 2,494" sat 3.3 s while the voice read both: one long number a chunk
        end = words[j - 1]
        if j < n:
            nxt = words[j]
            if end.lower().strip("(),\"") in WEAK_END:
                c += 2.0
            if ABBREV_RX.match(nxt):
                c += 3.0
            if nxt[:1].isdigit():
                c += 2.5
            if not (cr.sentence_end(end) or end[-1] in ",;:)?!\""):
                c += 0.5
        return c

    for j in range(1, n + 1):
        for i in range(max(0, j - MAX_WORDS), j):
            if dp[i] < INF:
                v = dp[i] + cost(i, j)
                if v < dp[j]:
                    dp[j], back[j] = v, i
    out, j = [], n
    while j > 0:
        i = back[j]
        out.append(list(range(i, j)))
        j = i
    return out[::-1]


def spoken_tokens(words: list[str], say: dict[str, str]) -> list[tuple[int, str]]:
    """Display words -> spoken tokens [(display index, token)]: the say map (exact word, punctuation included) or the word
    without its quote marks; brackets are dropped either way ("(beat" is said "beat")."""
    out = []
    for i, w in enumerate(words):
        sp = say.get(w)
        if sp is None:
            sp = w.replace('"', "").replace("“", "").replace("”", "")
        for tok in re.sub(r"[()\[\]{}]", "", sp).split():            # a bracket is for the eye, never voiced
            out.append((i, tok))
    return out


def align(spoken: list[str], tts_words: list[dict]) -> list[tuple[float, float] | None]:
    """Spoken tokens -> (start, end) from the TTS word list, matched on their letters and digits (the engine keeps
    whitespace words, so this is normally 1:1; difflib covers a merged or split token)."""
    key = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    a, b = [key(s) for s in spoken], [key(w["word"]) for w in tts_words]
    res: list[tuple[float, float] | None] = [None] * len(a)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for d in range(i2 - i1):
                w = tts_words[j1 + d]
                res[i1 + d] = (float(w["start"]), float(w["end"]))
        elif op == "replace" and j2 > j1:
            s0, s1 = float(tts_words[j1]["start"]), float(tts_words[j2 - 1]["end"])
            for d in range(i2 - i1):
                f0, f1 = d / (i2 - i1), (d + 1) / (i2 - i1)
                res[i1 + d] = (s0 + (s1 - s0) * f0, s0 + (s1 - s0) * f1)
    for i in range(len(res)):                      # a dropped token takes the previous token's end
        if res[i] is None:
            prev = next((res[k] for k in range(i - 1, -1, -1) if res[k]), None)
            nxt = next((res[k] for k in range(i + 1, len(res)) if res[k]), None)
            t = prev[1] if prev else (nxt[0] if nxt else 0.0)
            res[i] = (t, t)
    return res


# ------------------------------------------------------------------------------------------------- brand and format (v3)
BRAND = cr.BRAND
BRAND_FIRST_S, BRAND_LAST_S = 5.0, 5.0
ONE_IDEA_DURATION = (15.0, 22.0)
ONE_IDEA_MAX_SHOTS = 7
STORY_ELS = {"pip", "dale", "search_phone", "card", "screen", "site", "highlight", "receipt"}   # anything else is a side gag
PILL_MIN_CORR, PILL_MAX_MAD = 0.8, 24.0
PAYOFF_BRAND_MIN_H, PAYOFF_BRAND_MIN_S = 24.0, 1.0


def _brand_word(text: str) -> bool:
    return re.sub(r"[^A-Za-z]", "", str(text)).lower() == BRAND.lower()


def brand_spoken_gate(words: list[tuple[str, float]], total: float, first_s: float = BRAND_FIRST_S,
                      last_s: float = BRAND_LAST_S) -> tuple[bool, dict]:
    """words: [(display word, start s)] of the whole voice track. "RapidTradeView" must start within the first `first_s` s
    and again within the last `last_s` s (the end card's "Search RapidTradeView")."""
    at = [round(float(t), 2) for w, t in words if _brand_word(w)]
    first = [t for t in at if t <= first_s]
    last = [t for t in at if t >= total - last_s]
    return bool(first) and bool(last), {"spoken_at_s": at, "first_by_s": first_s, "last_from_s": round(total - last_s, 2)}


def region_match(region, ref) -> tuple[float, float]:
    """(Pearson correlation, mean |difference|) of two same-size grey arrays (0-255)."""
    import numpy as np
    a, b = np.asarray(region, np.float64).ravel(), np.asarray(ref, np.float64).ravel()
    if a.size == 0 or a.size != b.size:
        return 0.0, 255.0
    mad = float(np.abs(a - b).mean())
    if a.std() == 0 or b.std() == 0:
        return 0.0, mad
    return float(np.corrcoef(a, b)[0, 1]), mad


def brand_pill_gate(samples: list[dict], min_corr: float = PILL_MIN_CORR, max_mad: float = PILL_MAX_MAD) -> tuple[bool, dict]:
    """samples: [{"t", "corr", "mad"}], one per sampled decoded frame (the pill region against the pill as planned). Every
    sample must match: the brand is on screen from frame 0 to the last frame."""
    bad = [s_ for s_ in samples if not (s_["corr"] >= min_corr and s_["mad"] <= max_mad)]
    return bool(samples) and not bad, {"samples": len(samples), "missing_at": [round(s_["t"], 2) for s_ in bad],
                                       "min_corr": round(min((s_["corr"] for s_ in samples), default=0.0), 3),
                                       "max_mad": round(max((s_["mad"] for s_ in samples), default=0.0), 1),
                                       "limits": {"corr": min_corr, "mad": max_mad}}


def payoff_brand_gate(samples: list[dict], fps: int, min_h: float = PAYOFF_BRAND_MIN_H,
                      min_s: float = PAYOFF_BRAND_MIN_S) -> tuple[bool, dict]:
    """samples: one per rendered PAYOFF frame that shows a real screen with our header: {"t", "screen", "in_text" (the
    capture's visible text has the brand), "in_crop" (the brand's DOM box is inside the shown crop), "h" (its height on
    screen, px), "inside" (its box is inside the frame)}. The brand on our real page must be readable for min_s."""
    good = [s_ for s_ in samples if s_["in_text"] and s_["in_crop"] and s_["inside"] and s_["h"] >= min_h]
    secs = len(good) / fps
    return secs >= min_s, {"readable_s": round(secs, 2), "samples": len(samples), "screens": sorted({s_["screen"] for s_ in samples}),
                           "max_h": round(max((s_["h"] for s_ in samples), default=0.0), 1), "limits": {"h": min_h, "s": min_s}}


def one_idea_gate(shots: list[dict], total: float, duration=ONE_IDEA_DURATION, max_shots: int = ONE_IDEA_MAX_SHOTS) -> tuple[bool, dict]:
    """One situation, one punchline: total 15-22 s, at most 7 shots, and only the story's own elements (characters, the
    branded phone, our real screen, its highlight, a receipt). Feeds, cats, socks, tab bursts, barbells: side gags."""
    gags = sorted({str(e.get("t")) for sh in shots for e in sh.get("els", []) if e.get("t") not in STORY_ELS})
    bubbles = sum(1 for sh in shots if sh.get("bubble"))
    ok = duration[0] <= total <= duration[1] and len(shots) <= max_shots and not gags and bubbles <= 1
    return ok, {"seconds": round(total, 2), "duration_range": list(duration), "shots": len(shots), "max_shots": max_shots,
                "side_gag_elements": gags, "sfx_bubbles": bubbles}


def item_page_urls(item: dict) -> set[str]:
    """Our pages a real capture may come from: the item's page_url (query and fragment dropped) and, for an earnings item,
    its report page (public: no guest view counted)."""
    out = set()
    pu = re.sub(r"[?#].*$", "", str(item.get("page_url") or ""))
    if pu:
        out.add(pu)
    m = re.match(r"(https://[^/]+)/", pu)
    if m and item.get("report_id"):
        out.add(f"{m.group(1)}/earnings/reports/{item['report_id']}")
    return out


# ------------------------------------------------------------------------------------------------- feature shorts
# A FEATURE short shows what one feature of the site answers (owner 2026-11-10: "create one for features like smart money,
# concentration visuals, portfolio visuals and such"). It has no facts item: the truth is the capture made on the render
# day. features.json (next to this file) is the registry: the page, the capture bands, how each value is read from a
# capture's visible text, the story lines with {slots} for those values, and which captured text is the key. These
# functions are pure (sidecars in, verdict out): make_feature_story.py uses them to fill a story and cartoon_reel.py uses
# them again at render time, from the sidecars, so a value typed by hand into a story fails.
FEATURES_FILE = Path(__file__).resolve().parent / "features.json"
FEATURE_SCHEMA = "rtv-cartoon-features/2"  # /2: the "site screen" payoff (owner verdict 2026-11-10 on the first four shorts:
#   "they arent good, only the last one show the visuals correctly as it shown on website"). One capture, `page`: a strip of
#   the real page at phone width that holds the feature's card whole. The renderer shows it in one window under the brand
#   pill and scrolls it like a thumb; nothing is cut out of it, nothing is captured again at 6x, the key is outlined where
#   it stands. The /1 layouts ("stack", "hero": a headline strip, one table row, a chart lifted out of its card) are refused.
PAGE = "page"                            # the one capture of a feature short
SITE_VIEWPORT_W, SITE_MIN_DPR = 390, 3   # phone width in CSS px; 3 device px per CSS px keeps a ~1000 px wide card sharp
SITE_CARD_MIN_W = 900.0                  # the card's width on screen (owner: about 940-1010 px of the 1080 frame)
SITE_WHOLE_MIN_S, SITE_PART_MIN_S = 1.0, 0.25   # a card that fits is whole for 1 s; a part passes whole for 0.25 s in a scroll
SITE_STAND_MIN_S = 1.8                   # the real screen stands (not flying in) at least this long
SITE_KEY_MIN_H, SITE_KEY_MIN_S = 40.0, 1.5      # the outlined key's height on screen, and for how long
SITE_PARTS_NEEDED = 2                    # at least this many named parts of the card (title, headline, chart, ...)
FEATURE_MAX_AGE_H = 12.0                 # "captured today": the captures are at most this old when the video is rendered
FEATURE_LINES = ("hook", "confused", "fact_a", "fact_b")
REACTION = "Oh."
# Shown on our own pages, never in a video (owner 2026-10-19: no provider or source brand on a public surface we publish).
# A deny-list can only name what somebody thought of, and a logo drawn as an image has no text at all: looking at the
# frames of shots 4 and 5 stays a required step (SKILL.md). An index or ticker name on our page ("S&P 500", "SPY") is a
# benchmark, not a source credit, and is not listed.
VENDOR_EXTRA_WORDS = (
    "reddit", "stocktwits", "stock twits", "apewisdom", "ape wisdom", "wallstreetbets", "wall street bets", "edgar",
    "bloomberg", "reuters", "nasdaq", "morningstar", "tradingview", "twitter", "wikipedia", "marketwatch", "fintel",
    "whalewisdom", "whale wisdom", "dataroma", "opensecrets", "propublica", "refinitiv", "s&p global", "dow jones",
    "wall street journal", "financial times", "barron's", "barrons", "motley fool", "investopedia", "investing.com",
    "stockanalysis", "macrotrends", "google finance", "house stock watcher", "senate stock watcher", "capitoltrades",
    "quiverquant", "x.com", "associated press")
VENDOR_EXTRA_RX = re.compile(r"(?i)(?<![a-z0-9])(?:" + "|".join(
    r"[\s_.-]*".join(map(re.escape, w.split())) for w in sorted(VENDOR_EXTRA_WORDS, key=len, reverse=True)) + r")(?![a-z0-9])")
VENDOR_ACRONYM_RX = re.compile(r"(?<![A-Za-z0-9])(?:FRED|WSJ|LSEG|CNBC|CNN|NYT|FINRA)(?![A-Za-z0-9])")      # case matters: Fred is a name
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍‎‏⁠⁡⁢⁣﻿­͏؜᠎"), None)
_LOOKALIKES = str.maketrans({
    # Cyrillic and Greek letters that read as Latin ones ("Yаhoo" with a Cyrillic a)
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ј": "j", "ѕ": "s", "һ": "h", "ԁ": "d",
    "ԛ": "q", "ԝ": "w", "к": "k", "м": "m", "т": "t", "в": "b", "н": "h", "г": "r", "ь": "b",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "І": "I", "Ј": "J", "Ѕ": "S", "ο": "o", "α": "a", "ν": "v", "ρ": "p", "υ": "u", "ι": "i", "κ": "k", "τ": "t", "χ": "x",
    "γ": "y", "ε": "e", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X"})
# advice or a prediction, however it is phrased ("Buy it.", "It will go up."): the banned list is phrase based and misses these
ADVICE_RX = re.compile(
    r"(?i)(?<![a-z])(?:(?:buy|sell|short|dump|grab) (?:it|this|that|these|those|them|some|more|now|today|shares|the stock|the dip)|"
    r"(?:will|gonna|going to|is set to|are set to|about to|bound to|should|must) (?:go (?:up|down|higher|lower)|rise|fall|rally|"
    r"crash|drop|soar|climb|jump|tank|pop|rip|double|triple|moon|rebound|recover|outperform|skyrocket|explode|surge|plunge)|"
    r"you (?:should|must|need to|have to) (?:buy|sell|own|hold|short)|(?:buy|sell) (?:signal|rating|alert)|"
    r"price target|guaranteed|can'?t lose|sure thing|get in (?:now|early)|don'?t miss)(?![a-z])")
# a page that did not load its data: an error line, a spinner word, a figure that did not compute
ERROR_STATE_RX = re.compile(r"(?im)unavailable right now|something went wrong|failed to (?:load|fetch)|could ?n[o']t (?:load|fetch)|"
                            r"unable to (?:load|fetch|connect|reach)|(?:service|temporarily|currently) unavailable|"
                            r"no data(?: available| yet| found)?\s*$|\bNaN\b|\bundefined\b|(?<![A-Za-z])null(?![A-Za-z])|"
                            r"^\s*loading\b|\bloading\s*(?:…|\.\.\.)|^\s*(?:error|retry|try again)\s*$")
TICKER_TOKEN_RX = re.compile(r"(?<![A-Za-z0-9&])\$?([A-Z]{2,5}(?:[.\-][A-Z])?)(?![A-Za-z0-9&])")
NOT_TICKERS = {"OK", "EPS", "ETF", "ETFS", "US", "USA", "AI", "CEO", "CFO", "IPO", "TV", "PM", "AM"}
# The outlined key. A figure (a tag, a ticker, an amount) is at least 64 px tall. A visual (a chart, or a table row that
# has to stay whole across the frame) cannot make its label that tall: the card is at least 640 px wide and the outlined
# label at least 40 px tall (30 px passed a 35 px donut label that read small; raised 2026-11-10).
KEY_VISUAL_MIN_W, KEY_VISUAL_MIN_H, KEY_MIN_H, KEY_MIN_S = 640.0, 40.0, 64.0, 1.5
SPEC_RX = re.compile(r"(?:page|(?:el|all|text):.+)", re.S)       # a box on the page, as capture.py reads it (box_spec)
# pages a feature short never captures: they count a guest view, or they are sign-in only
NO_CAPTURE_PATHS = ("dashboard", "smart-money", "portfolio", "account", "admin", "api", "auth", "oauth", "notifications")
PHONE_MODES = ("type", "tap")
WD3 = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MON3 = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
INSIDE_KEY = "inside_text"               # sidecar: the text whose glyph boxes lie mostly inside the captured area


class FeatureError(Exception):
    """The registry or a capture cannot carry a feature short (make_feature_story exits 2, the renderer refuses)."""


def fold(text: str) -> str:
    """Text as a reader sees it, for the name checks: compatibility forms unified, zero-width characters dropped, Cyrillic
    and Greek look-alikes mapped to their Latin letters ("Ya​hoo" and "Yаhoo" both read Yahoo)."""
    return unicodedata.normalize("NFKC", str(text)).translate(_ZERO_WIDTH).translate(_LOOKALIKES)


def vendor_hits(text: str) -> list[str]:
    """Provider and source brands in a text (card_reel.PROVIDER_RX plus the wider list here), after fold()."""
    t = fold(text)
    return sorted({m.group(0) for rx in (PROVIDER_RX, VENDOR_EXTRA_RX, VENDOR_ACRONYM_RX) for m in rx.finditer(t)})


def vendor_gate(texts: dict[str, str]) -> tuple[bool, dict]:
    """provider_gate with the wider list and the look-alike folding (feature shorts)."""
    hits = {role: vendor_hits(t) for role, t in texts.items()}
    hits = {k: v for k, v in hits.items() if v}
    return not hits, {"found": hits}


def advice_hits(text: str) -> list[str]:
    return sorted({m.group(0) for m in ADVICE_RX.finditer(fold(text))})


def shown_text(meta: dict) -> str:
    """What a capture really shows: the text mostly inside the captured area (capture.py `inside_text`). `visible_text` also
    lists lines that only touch the band's edge; it stays the text the name and error checks read (fail closed), but a
    number or a value is taken only from what is inside. Old sidecars without `inside_text` fall back to `visible_text`."""
    return str(meta.get(INSIDE_KEY) if isinstance(meta.get(INSIDE_KEY), str) else meta.get("visible_text", ""))


def capture_seal(meta: dict) -> str:
    """A fingerprint of what a capture recorded (capture.py writes it as `seal`): the page, the time, the PNG's hash, the
    texts and the target boxes. An edit to a sidecar after the capture ("4 members buying" -> "40") no longer matches. It
    is not a signature (whoever edits can also recompute it): it catches a hand edit, not a forger."""
    body = [meta.get("url"), meta.get("final_url"), meta.get("captured_at"), meta.get("sha256"), meta.get("png_size"),
            meta.get("visible_text"), meta.get(INSIDE_KEY), meta.get("targets")]
    if "boxes" in meta:                              # a strip: the card's DOM boxes and the strip's place on the page
        body += [meta.get("kind"), meta.get("boxes"), meta.get("strip"), meta.get("viewport"), meta.get("dpr")]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def us_eastern(utc: dt.datetime) -> dt.datetime:
    """A UTC time as US Eastern wall time (EDT from the second Sunday of March to the first Sunday of November)."""
    utc = utc.astimezone(dt.timezone.utc)

    def sunday(month: int, n: int) -> dt.date:
        d = dt.date(utc.year, month, 1)
        return d + dt.timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))

    start = dt.datetime.combine(sunday(3, 2), dt.time(7, 0), dt.timezone.utc)       # 02:00 EST
    end = dt.datetime.combine(sunday(11, 1), dt.time(6, 0), dt.timezone.utc)        # 02:00 EDT
    return (utc + dt.timedelta(hours=-4 if start <= utc < end else -5)).replace(tzinfo=None)


def last_closed_session(utc: dt.datetime) -> dt.date:
    """The last US session that had closed (16:00 Eastern) at `utc`: a weekday. Market holidays are not known here: the
    day after one the page shows an earlier session and the feature stops (no video that day)."""
    et = us_eastern(utc)
    d = et.date() if (et.hour, et.minute) >= (16, 0) else et.date() - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def captured_at(meta: dict) -> dt.datetime:
    try:
        return dt.datetime.strptime(str(meta.get("captured_at")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as e:
        raise FeatureError(f"captured_at {meta.get('captured_at')!r} is not a UTC timestamp") from e


def load_features(path=None) -> dict:
    p = Path(path) if path else FEATURES_FILE
    try:
        reg = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise FeatureError(f"feature registry unreadable: {p} ({type(e).__name__}: {e})") from e
    problems = registry_problems(reg)
    if problems:
        raise FeatureError(f"feature registry {p}: " + "; ".join(problems[:6]))
    reg["_path"] = str(p)
    return reg


def _slots(s: str) -> list[str]:
    return re.findall(r"\{([a-z_][a-z0-9_]*)\}", str(s))


def _unslot(s: str) -> str:
    return re.sub(r"\{[a-z_][a-z0-9_]*\}", " ", str(s))


def _value_names(f: dict) -> set[str]:
    out: set[str] = set()
    for v in f.get("values") or []:
        out |= set(re.findall(r"\(\?P<([a-z_][a-z0-9_]*)>", str(v.get("rx", ""))))
        if v.get("as"):
            out.add(v["as"])
        for k in ("prev", "next"):
            out |= set((v.get(k) or {}).keys())
    for chk in f.get("checks") or []:                   # a session check also sets the weekday and the date it read
        out |= {str(n) for n in (chk.get("sets") or {}).values()}
    return out


def target_name(spec: str) -> str:
    """A target as the sidecar names it: capture.py drops the "=" (whole text node) and keeps a "#N" (N-th occurrence)."""
    return spec[1:] if str(spec).startswith("=") else str(spec)


def _site_specs(site: dict) -> list[str]:
    """Every box spec of a registry entry's `site` block (strip, card, parts)."""
    strip, card = site.get("strip") or {}, site.get("card") or {}
    out = [strip.get("top"), strip.get("bottom")] + list(card.get("box") or []) + [card.get("bottom")]
    for v in (site.get("parts") or {}).values():
        out += list(v) if isinstance(v, list) else [v]
    return [x for x in out if x is not None]


def registry_problems(reg: dict) -> list[str]:
    """What is wrong with a registry (empty = usable): the schema, unique ids, our own https page, a `site` block that
    captures the card whole (a strip of the page, the card's box, its named parts), no fragment layout of schema /1,
    every {slot} read by a value rule, the brand in the confused line, claims that point at sources, and the owner's rules
    that can be read off the text (no provider name, no banned word, no number typed into a line: a number is always a
    slot)."""
    bad: list[str] = []
    if not isinstance(reg, dict) or reg.get("schema") != FEATURE_SCHEMA:
        return [f"schema is not {FEATURE_SCHEMA}"]
    banned = [w for w in reg.get("banned_words") or [] if isinstance(w, str)]
    if not banned:
        bad.append("no banned_words")
    feats = reg.get("features")
    if not isinstance(feats, list) or not feats or not all(isinstance(f, dict) for f in feats):
        return bad + ["no features"]
    ids = [f.get("id") for f in feats]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and re.fullmatch(r"[a-z][a-z0-9-]*", i) for i in ids):
        bad.append("feature ids must be unique lower-case slugs")
    for f in feats:
        fid = f.get("id")

        def say(m, fid=fid):
            bad.append(f"{fid}: {m}")

        url = str(f.get("url") or "")
        if not re.fullmatch(r"https://www\.rapidtradeview\.trade/[A-Za-z0-9/_-]*", url):
            say("url is not a page of https://www.rapidtradeview.trade")
        elif url.split("/")[3] in NO_CAPTURE_PATHS:
            say(f"url /{url.split('/')[3]} counts a guest view or is sign-in only: never captured")
        if "lands_on" in f and not re.fullmatch(r"https://www\.rapidtradeview\.trade/[A-Za-z0-9/_-]*(?:#[A-Za-z0-9_-]+)?",
                                               str(f["lands_on"])):
            say("lands_on is not a page of https://www.rapidtradeview.trade")
        if f.get("phone", "type") not in PHONE_MODES:
            say(f"phone is one of {PHONE_MODES}")
        if not re.fullmatch(rf"{SITE_VIEWPORT_W}x\d+", str(f.get("viewport") or "")):
            say(f"viewport is {SITE_VIEWPORT_W}x<height>: the card is captured at phone width")
        # the site screen: one strip of the real page, the card whole. Fragments are refused (owner verdict 2026-11-10).
        key = f.get("key") if isinstance(f.get("key"), dict) else {}
        if "captures" in f or f.get("layout", "site") != "site" or any(k in key for k in ("capture", "crop", "also", "kind", "w", "pad")):
            say("fragment cards are not allowed (captures / layout stack or hero / key crop, also, 6x): the payoff is the "
                "site's card whole, in `site`")
        site = f.get("site") if isinstance(f.get("site"), dict) else {}
        strip, card, parts = site.get("strip") or {}, site.get("card") or {}, site.get("parts") or {}
        specs = _site_specs(site)
        if not (isinstance(strip.get("top"), str) and isinstance(strip.get("bottom"), str)):
            say("site.strip needs top and bottom (page | el:CSS | all:CSS | text:TEXT)")
        if not (isinstance(card.get("box"), list) and card.get("box")):
            say("site.card.box lists the element(s) whose box is the card")
        if not (isinstance(parts, dict) and len(parts) >= SITE_PARTS_NEEDED
                and all(isinstance(v, list) and v for v in parts.values())
                and all(re.fullmatch(r"[a-z][a-z0-9_]*", str(k)) and k != "card" for k in parts)):
            say(f"site.parts names at least {SITE_PARTS_NEEDED} parts of the card (title, headline, chart, ...), each a list of boxes")
        for sp in specs:
            if not isinstance(sp, str) or not SPEC_RX.fullmatch(sp):
                say(f"site box {sp!r} is not page | el:CSS | all:CSS | text:TEXT")
        for sp in [strip.get("top"), strip.get("bottom")] + list(card.get("box") or []) + [card.get("bottom")]:
            if sp is not None and _slots(str(sp)):
                say(f"the strip and the card box are captured before any value is read: no slot in {sp!r}")
        if not isinstance(site.get("header", False), bool):
            say("site.header is true (the strip starts at our page header) or false")
        hold = site.get("top_hold", 1.0)
        if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not 0.5 <= hold <= 2.5:
            say("site.top_hold is 0.5 to 2.5 seconds on the strip's top before the scroll")
        names = _value_names(f)
        for v in f.get("values") or []:
            if v.get("from") != PAGE:
                say(f"value rule reads {v.get('from')!r}; a feature has one capture, {PAGE!r}")
            try:
                re.compile(str(v.get("rx", "")))
            except re.error as e:
                say(f"bad value rx {v.get('rx')!r}: {e}")
        lines = f.get("lines") or {}
        for k in FEATURE_LINES + ("hook_figure", "search"):
            if not isinstance(lines.get(k), str) or not lines[k].strip():
                say(f"no line {k}")
        targets = key.get("targets")
        if not (isinstance(targets, list) and targets and all(isinstance(t, str) and t.strip() for t in targets)):
            say("key.targets lists the text(s) of the card that are outlined in place")
            targets = []
        if "top" in key and not isinstance(key["top"], str):
            say("key.top is a text of the page (the window's top line while the key is outlined)")
        texts = [str(lines.get(k, "")) for k in FEATURE_LINES + ("hook_figure", "search")]
        texts += [str(f.get("fact_phrase", "")), str(key.get("top", ""))] + [str(t) for t in targets] + [str(sp) for sp in specs]
        texts += [str(s_.get("text", "")) for s_ in (f.get("sources") or {}).values() if isinstance(s_, dict)]
        for s_ in sorted({s_ for t in texts for s_ in _slots(t)} - names):
            say(f"slot {{{s_}}} is not read by a value rule")
        fig = str(lines.get("hook_figure", ""))
        if not _slots(fig) or fig not in str(lines.get("hook", "")):
            say("hook_figure must be a slot that the hook says")
        if BRAND not in str(lines.get("confused", "")):
            say("the confused line must say our brand (it is the voice's first RapidTradeView)")
        if not isinstance(f.get("fact_phrase"), str) or not f["fact_phrase"].strip():
            say("no fact_phrase")
        srcs = f.get("sources") or {}
        for sid, s_ in srcs.items():
            if not isinstance(s_, dict) or s_.get("capture") != PAGE:
                say(f"source {sid} does not name the capture {PAGE!r}")
        claims = f.get("claims") or {}
        for k, sid in claims.items():
            if k not in FEATURE_LINES or sid not in srcs:
                say(f"claim {k} -> {sid} is not a line -> source")
        for k in ("hook", "fact_a", "fact_b"):
            if k not in claims:
                say(f"line {k} has no claim")
        spoken = {k: str(lines.get(k, "")) for k in FEATURE_LINES + ("search",)}
        proper = {str(w) for w in reg.get("proper_words") or []} | {BRAND}
        for k, t in spoken.items():
            if find_numbers(_unslot(t)) or find_number_words(_unslot(t)):
                say(f"line {k} types a number; a number is always a slot read from the capture")
            if set(TICKER_TOKEN_RX.findall(_unslot(t))) - NOT_TICKERS:
                say(f"line {k} types a ticker; a ticker is always a slot read from the capture")
            for sent in re.split(r"(?<=[.!?:])\s+", _unslot(t).strip()):
                people = [w for w in re.findall(r"[A-Za-z][A-Za-z'’]*", sent)[1:] if w[0].isupper() and w not in proper]
                if people:                      # a name mid-sentence ("by Jane Roe"): a person or a company is always a slot
                    say(f"line {k} types the name {' '.join(people)!r}; a name is always a slot (or list it in proper_words)")
        for sid, s_ in srcs.items():
            if isinstance(s_, dict) and (find_numbers(_unslot(str(s_.get("text", ""))))
                                         or find_number_words(_unslot(str(s_.get("text", ""))))):
                say(f"source {sid} types a number; a source is the page's text, its numbers are slots")
        if any(vendor_hits(t) for t in spoken.values()):
            say("a line names a data provider")
        ok, det = banned_gate(spoken, banned)
        if not ok:
            say(f"a line uses banned words {det['found']}")
        adv = sorted({h for t in spoken.values() for h in advice_hits(t)})
        if adv:
            say(f"a line gives advice or a prediction {adv}")
    return bad


def feature_by_id(reg: dict, fid: str) -> dict:
    f = next((x for x in reg.get("features", []) if x.get("id") == fid), None)
    if f is None:
        raise FeatureError(f"no feature {fid!r} in the registry (features: "
                           f"{', '.join(str(x.get('id')) for x in reg.get('features', []))})")
    return f


def fill(template: str, values: dict) -> str:
    """"{count} members" -> "4 members"; a slot without a value is an error, never an empty string."""
    def sub(m):
        if m.group(1) not in values:
            raise FeatureError(f"no value for the slot {{{m.group(1)}}} in {template!r}")
        return str(values[m.group(1)])
    return re.sub(r"\{([a-z_][a-z0-9_]*)\}", sub, str(template))


def vis_lines(meta: dict) -> list[str]:
    """The lines a capture shows (shown_text: what lies inside the captured area, not what only touches its edge)."""
    return [ln.strip() for ln in shown_text(meta).splitlines() if ln.strip()]


def _number(tok: str, what: str) -> float:
    v = written_value(str(tok))
    if v is None:
        raise FeatureError(f"{what} {tok!r} is not a number")
    return v


def _check(chk: dict, vals: dict, metas: dict) -> None:
    """One registry check on the values read. Kinds:
      {"value": v, "min" | "max": n, "equals": text}   the value as a number / as text
      {"value": v, "more_than": w}                      the value is larger than another value of the page
      {"pct": p, "of": [count, total], "tol": 1.0}      p is count / total as a percent (the page's own arithmetic holds)
      {"session": {"wd", "mon", "day"}, "from": capture, "sets": {"weekday", "date"}}
                                                        the page's session label ("Mon, Nov 9") is the last US session
                                                        that had closed when the capture was made; sets the weekday's full
                                                        name and the ISO date as values
    A failed check raises FeatureError: the day (or the page) does not carry the story."""
    why = chk.get("why", "the story does not hold")
    if "session" in chk:
        names = chk["session"]
        try:
            wd, mon, day = (str(vals[names[k]]) for k in ("wd", "mon", "day"))
        except KeyError as e:
            raise FeatureError(f"session check: no value {e}") from e
        if chk.get("from") not in metas:
            raise FeatureError(f"session check reads capture {chk.get('from')!r}, which was not made")
        want = last_closed_session(captured_at(metas[chk["from"]]))
        label = f"{wd}, {mon} {int(_number(day, 'day'))}"
        want_label = f"{WD3[want.weekday()]}, {MON3[want.month - 1]} {want.day}"
        if label != want_label:
            raise FeatureError(f"the page's session is {label!r}, the last closed session before the capture is "
                               f"{want_label!r}: {why}")
        sets = chk.get("sets") or {}
        if sets.get("weekday"):
            vals[sets["weekday"]] = WEEKDAYS[want.weekday()]
        if sets.get("date"):
            vals[sets["date"]] = want.isoformat()
        return
    if "pct" in chk:
        try:
            p, a, b = (_number(vals[k], k) for k in (chk["pct"], chk["of"][0], chk["of"][1]))
        except KeyError as e:
            raise FeatureError(f"pct check: no value {e}") from e
        if b <= 0 or a > b or abs(100.0 * a / b - p) > float(chk.get("tol", 1.0)):
            raise FeatureError(f"{vals[chk['pct']]} is not {vals[chk['of'][0]]} of {vals[chk['of'][1]]}: {why}")
        return
    v = vals.get(chk.get("value"))
    if v is None:
        raise FeatureError(f"check on {chk.get('value')!r}: no such value")
    if "more_than" in chk:                   # another value of the page ("130 sells" against "76 buys")
        other = vals.get(chk["more_than"])
        if other is None:
            raise FeatureError(f"check on {chk['value']!r}: no value {chk['more_than']!r} to compare with")
        if _number(v, chk["value"]) <= _number(other, chk["more_than"]):
            raise FeatureError(f"{chk['value']} is {v!r}, not more than {chk['more_than']} ({other!r}): {why}")
    if "min" in chk and _number(v, chk["value"]) < float(chk["min"]):
        raise FeatureError(f"{chk['value']} is {v!r}, below {chk['min']}: {why}")
    if "max" in chk and _number(v, chk["value"]) > float(chk["max"]):
        raise FeatureError(f"{chk['value']} is {v!r}, above {chk['max']}: {why}")
    if "equals" in chk and v != chk["equals"]:
        raise FeatureError(f"{chk['value']} is {v!r}, not {chk['equals']!r}: {why}")


def feature_values(feature: dict, metas: dict) -> dict:
    """The slot values, read from the captures' visible text by the registry's rules. A rule: {"from": capture,
    "after": line (optional; the search starts below the first line equal to it), "offset": n (optional; the n-th line
    below `after` must match, else any later line may), "rx": a regex the whole line must match (named groups become
    values), "as": name for the whole line, "prev" / "next": {name: rx} for the line just above / below}. Nothing is
    guessed: a rule that finds no line, or a failed check (_check), raises FeatureError."""
    vals: dict = {}
    for rule in feature.get("values") or []:
        cap = rule.get("from")
        if cap not in metas:
            raise FeatureError(f"value rule reads capture {cap!r}, which was not made")
        lines = vis_lines(metas[cap])
        start = 0
        if rule.get("after"):
            if rule["after"] not in lines:
                raise FeatureError(f"capture {cap}: no line {rule['after']!r} (the page changed, or its data did not load)")
            start = lines.index(rule["after"]) + 1
        rx = re.compile(rule["rx"])
        idx = [start + int(rule["offset"]) - 1] if rule.get("offset") else list(range(start, len(lines)))
        hit = next(((i, m) for i in idx if i < len(lines) for m in [rx.fullmatch(lines[i])] if m), None)
        if hit is None:
            raise FeatureError(f"capture {cap}: no line matches {rule['rx']!r}"
                               + (f" below {rule['after']!r}" if rule.get("after") else ""))
        i, m = hit
        got = {k: v for k, v in m.groupdict().items() if v is not None}
        if rule.get("as"):
            got[rule["as"]] = lines[i]
        for where, j in (("prev", i - 1), ("next", i + 1)):
            for name, pat in (rule.get(where) or {}).items():
                if not (0 <= j < len(lines)) or not re.fullmatch(pat, lines[j]):
                    raise FeatureError(f"capture {cap}: the line {where} to {lines[i]!r} does not match {pat!r}")
                got[name] = lines[j]
        for k, v in got.items():
            if k in vals and vals[k] != v:
                raise FeatureError(f"value {k} is read twice and differs: {vals[k]!r} / {v!r}")
            vals[k] = v
    for chk in feature.get("checks") or []:
        _check(chk, vals, metas)
    return vals


def page_words(text: str) -> list[str]:
    """Words for a verbatim comparison: case kept, edge punctuation and punctuation-only tokens dropped, the minus sign
    and the hyphen alike ("rose — 83%" and "rose: 83%." are the same words; "83%" and "8.3%" are not)."""
    out = []
    for w in str(text).replace("−", "-").split():
        core = w.strip(".,;:!?()[]\"'“”‘’·—–|")
        if core:
            out.append(core)
    return out


def _has_run(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def on_capture(text: str, meta: dict) -> bool:
    """The words of `text`, in order and unbroken, are in the text the capture shows."""
    return _has_run(page_words(shown_text(meta)), page_words(text))


def feature_sources(feature: dict, values: dict, metas: dict) -> dict:
    """Source id -> the page text a story line may paraphrase: a text that is on its capture word for word, or (no
    "text") everything the capture shows."""
    out = {}
    for sid, src in (feature.get("sources") or {}).items():
        meta = metas.get(src.get("capture"))
        if meta is None:
            raise FeatureError(f"source {sid}: capture {src.get('capture')!r} was not made")
        if src.get("text"):
            text = fill(src["text"], values)
            if not on_capture(text, meta):
                raise FeatureError(f"source {sid}: {text!r} is not on the {src['capture']} capture")
        else:
            text = " ".join(vis_lines(meta))
        out[sid] = text
    return out


def feature_lines(feature: dict, values: dict) -> dict:
    """The story's texts: the registry's templates filled with the captured values."""
    ln = feature["lines"]
    out = {k: fill(ln[k], values) for k in FEATURE_LINES + ("hook_figure", "search")}
    out["fact_phrase"] = fill(feature["fact_phrase"], values)
    out["key"] = [target_name(fill(t, values)) for t in feature["key"]["targets"]]     # outlined together, as one box
    return out


def feature_item(feature: dict, values: dict, metas: dict, item_id: str) -> dict:
    """The facts item of a feature short, built from the captures: its allowed numbers are the numbers the captures show,
    its phrasings the registry's sources as they stand on the captures. The renderer's number, claim and hook gates then
    run unchanged, against the page instead of a facts file."""
    numbers: list[str] = []
    for meta in metas.values():
        for n in find_numbers(shown_text(meta)):
            if n not in numbers:
                numbers.append(n)
    srcs = feature_sources(feature, values, metas)
    phrase = fill(feature["fact_phrase"], values)
    if not any(on_capture(phrase, m) for m in metas.values()):
        raise FeatureError(f"the fact phrase {phrase!r} is not on a capture")
    dates = [values[c["sets"]["date"]] for c in feature.get("checks") or []
             if (c.get("sets") or {}).get("date") in values]       # the page's session day: its weekday may be named
    return {"item_id": item_id, "type": "feature", "feature": feature["id"], "page_url": feature["url"],
            "ticker": values.get(feature.get("ticker") or ""), "name": values.get(feature.get("name") or ""),
            "allowed_numbers": numbers, "facts_text": phrase, "traded": dates,
            "phrasings": [{"id": sid, "text": text} for sid, text in srcs.items()]}


def capture_day(metas: dict) -> str:
    days = {str(m.get("captured_at", ""))[:10] for m in metas.values()}
    if len(days) != 1 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", next(iter(days))):
        raise FeatureError(f"the captures are not from one day: {sorted(days)}")
    return next(iter(days))


def _page(url: str) -> str:
    """A page address for comparison: the query dropped, the fragment kept, no trailing slash before it."""
    u = re.sub(r"\?[^#]*", "", str(url or ""))
    return re.sub(r"/(?=#|$)", "", u)


def feature_capture_gate(feature: dict, metas: dict, now: dt.datetime, max_age_h: float = FEATURE_MAX_AGE_H) -> tuple[bool, dict]:
    """Every capture of a feature short: our page (the registry's URL asked for, and the page the browser ended on: the
    registry's `lands_on`, or the URL itself), made today (at most max_age_h before `now`, UTC, never in the future), its
    data loaded (the registry's `require` texts on the page, none of its `refuse_if` texts, no error or loading words on
    what is shown), no provider or source brand on what is shown, and a sidecar nobody edited (its seal). The whole
    page's text may name a source in its footer: only what the video shows is checked, and for the names that is the wide
    text (every line that touches the band), look-alike letters and zero-width characters folded."""
    bad: dict = {}
    ages = {}
    want = _page(re.sub(r"#.*$", "", feature["url"]))
    lands = _page(feature.get("lands_on") or feature["url"])
    for name, m in metas.items():
        why = []
        if _page(re.sub(r"#.*$", "", str(m.get("url") or ""))) != want:
            why.append(f"url {m.get('url')!r} is not {feature['url']}")
        if _page(m.get("final_url")) != lands:
            why.append(f"the browser ended on {m.get('final_url')!r}, not {feature.get('lands_on') or feature['url']}")
        try:
            at = dt.datetime.strptime(str(m.get("captured_at")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            age = (now - at).total_seconds() / 3600.0
            ages[name] = round(age, 2)
            if not (-0.1 <= age <= max_age_h):
                why.append(f"captured {age:.1f} h before the render (limit {max_age_h} h): capture it again today")
        except ValueError:
            why.append(f"captured_at {m.get('captured_at')!r} is not a UTC timestamp")
        if not isinstance(m.get(INSIDE_KEY), str):
            why.append(f"the sidecar has no {INSIDE_KEY} (made by an old capture.py): capture it again")
        if m.get("seal") != capture_seal(m):
            why.append("the sidecar was changed after the capture (its seal does not match): capture it again")
        page, vis = str(m.get("page_text", "")), str(m.get("visible_text", ""))
        low = page.lower()                 # the page text is innerText: CSS upper-casing is applied to it
        why += [f"the page lacks {t!r}" for t in feature.get("require") or [] if t.lower() not in low]
        why += [f"the page says {t!r}" for t in feature.get("refuse_if") or [] if t.lower() in low]
        err = sorted({x.group(0).strip() for x in ERROR_STATE_RX.finditer(vis)})
        if err:
            why.append(f"error or loading state on screen: {err}")
        prov = vendor_hits(vis)
        if prov:
            why.append(f"provider names on screen: {prov}")
        if not shown_text(m).strip():
            why.append("nothing visible")
        why += site_capture_problems(feature, m) if name == PAGE else [f"a feature has one capture, {PAGE!r}: {name!r} is not it"]
        if why:
            bad[name] = why
    if PAGE not in metas:
        bad.setdefault(PAGE, []).append("capture missing")
    return not bad, {"problems": bad, "age_h": ages, "max_age_h": max_age_h, "url": feature["url"],
                     "lands_on": feature.get("lands_on") or feature["url"]}


def site_capture_problems(feature: dict, m: dict) -> list[str]:
    """What keeps a sidecar from being the feature's site screen: it is a strip of the page at phone width (the whole
    viewport width, at least SITE_MIN_DPR device px per CSS px), and it holds the card's DOM box and the box of each named
    part inside it. A band, an element lifted out of its card, or a re-crop is not a strip and is refused."""
    why = []
    vp, dpr, size = m.get("viewport") or [0, 0], m.get("dpr") or 0, m.get("png_size") or [0, 0]
    if m.get("kind") != "strip" or not isinstance(m.get("strip"), dict):
        return ["not a strip of the page (capture.py --strip-top/--strip-bottom): fragments are not shown"]
    if vp[0] != SITE_VIEWPORT_W or dpr < SITE_MIN_DPR or size[0] != SITE_VIEWPORT_W * dpr:
        why.append(f"not the page at phone width: viewport {vp}, dpr {dpr}, {size[0]} px wide "
                   f"(want {SITE_VIEWPORT_W} CSS px at dpr >= {SITE_MIN_DPR})")
    boxes = m.get("boxes") if isinstance(m.get("boxes"), dict) else {}
    need = ["card"] + sorted((feature.get("site") or {}).get("parts") or {})
    for n in need:
        b = boxes.get(n)
        if not (isinstance(b, list) and len(b) == 4 and b[2] > 0 and b[3] > 0):
            why.append(f"no DOM box {n!r} in the sidecar")
        elif not (b[0] >= -1 and b[1] >= -1 and b[0] + b[2] <= size[0] + 1 and b[1] + b[3] <= size[1] + 1):
            why.append(f"the box {n!r} is not inside the strip")
    card = boxes.get("card")
    if isinstance(card, list) and len(card) == 4:
        for n in need[1:]:
            b = boxes.get(n)
            if isinstance(b, list) and len(b) == 4 and not (b[0] >= card[0] - 1 and b[1] >= card[1] - 1
                                                            and b[0] + b[2] <= card[0] + card[2] + 1
                                                            and b[1] + b[3] <= card[1] + card[3] + 1):
                why.append(f"the part {n!r} is not inside the card's box")
    if (feature.get("site") or {}).get("header") and not any(t.get("text") == BRAND for t in m.get("targets") or []):
        why.append("site.header is true but the strip has no target for our header's brand")
    return why


def feature_say(feature: dict, values: dict) -> dict:
    """The one say map a feature story may carry: say_map over its voice lines (figures spelled to their value, the
    ticker as letters, our name as three words). In the two payoff lines, read off the page, a dollar figure is said
    without "dollars" ("five hundred two million bought": the screen shows the $, and the line is shorter)."""
    want = feature_lines(feature, values)
    lines = [want[k] for k in FEATURE_LINES] + [REACTION, f"Search {BRAND}. {cr.DISCLAIMER}"]
    return say_map(lines, values.get(feature.get("ticker") or "") or "", (want["fact_a"], want["fact_b"]))


def spoken_script(doc: dict) -> str:
    """Everything the voice will say: every shot's line through the say maps (the story's and a shot's own)."""
    out = []
    for sh in doc.get("shots") or []:
        vo = str(sh.get("vo") or "").strip()
        if vo:
            say = {**(doc.get("say") or {}), **(sh.get("say") or {})}
            out.append(" ".join(t for _, t in spoken_tokens(vo.split(), say)))
    return " ".join(out)


def feature_story_gate(doc: dict, feature: dict, metas: dict) -> tuple[bool, dict]:
    """A feature story holds only what the registry and today's captures give: its values are the ones read from the
    sidecars now, its voice lines, chip, phone text, fact phrase, key target and outlines are the registry's templates
    filled with them, each line carries the registry's claim, its say map is exactly the generator's (feature_say: a
    hand-written entry would make the voice say what no caption shows), no shot has a say map of its own, and what the
    voice ends up saying names no provider, gives no advice, adds no number and no ticker that is not on a capture.
    make_feature_story.story_drift (run by the renderer with this gate) also rebuilds the whole story and compares."""
    probs: list[str] = []
    try:
        vals = feature_values(feature, metas)
        want = feature_lines(feature, vals)
        want_say = feature_say(feature, vals)
        day = capture_day(metas)
    except (FeatureError, TemplateError) as e:
        return False, {"problems": [str(e)]}
    got_vals = (doc.get("feature") or {}).get("values")
    if got_vals != vals:
        probs.append(f"story values {got_vals} are not the captures' {vals}")
    if doc.get("post_date") != day:
        probs.append(f"post_date {doc.get('post_date')!r} is not the capture day {day}: a feature short is rendered and "
                     "dated on the day its page was captured")
    shots = doc.get("shots") or []
    vo = [str(sh.get("vo") or "").strip() for sh in shots if str(sh.get("vo") or "").strip()]
    fixed = {REACTION, f"Search {BRAND}. {cr.DISCLAIMER}"}
    planned = [want[k] for k in FEATURE_LINES]
    free = [v for v in vo if v not in fixed]
    if free != planned:
        probs.append(f"voice lines {free} are not the registry's {planned}")
    claims = feature.get("claims") or {}
    for k in FEATURE_LINES:
        sh = next((s_ for s_ in shots if str(s_.get("vo") or "").strip() == want[k]), None)
        if sh is not None and sh.get("claim") != claims.get(k):
            probs.append(f"line {k} carries claim {sh.get('claim')!r}, the registry says {claims.get(k)!r}")
    chips = [str(sh["chip"].get("text")) for sh in shots if sh.get("chip")]
    if chips != [want["hook_figure"]]:
        probs.append(f"chips {chips} are not the hook figure {want['hook_figure']!r}")
    phones = [e for sh in shots for e in sh.get("els", []) if e.get("t") == "search_phone"]
    typed = [str(e.get("text")) for e in phones]
    if typed != [want["search"]]:
        probs.append(f"the phone shows {typed}, the registry says {want['search']!r}")
    if any(e.get("mode", "type") != feature.get("phone", "type") for e in phones):
        probs.append(f"the phone's mode is not the registry's {feature.get('phone', 'type')!r}")
    if doc.get("fact_phrase") != want["fact_phrase"]:
        probs.append(f"fact phrase {doc.get('fact_phrase')!r} is not {want['fact_phrase']!r}")
    keys = [sh.get("key_number") for sh in shots if sh.get("key_number")]
    marks = [e.get("target") for sh in shots for e in sh.get("els", []) if e.get("t") == "highlight"]
    if keys != [want["key"]] or marks != [want["key"]]:          # one outline, on the key: an extra one is a second claim
        probs.append(f"key {keys} / outlines {marks} are not the registry's key {want['key']!r} alone")
    if any(sh.get("bubble") for sh in shots) or any(e.get("t") == "receipt" for sh in shots for e in sh.get("els", [])):
        probs.append("a feature story draws no bubble and no receipt (their text is not the page's)")
    # the real screen: the one strip, whole, in a `site` window. No card cut out of it, no crop, no second capture.
    frag = sorted({str(e.get("t")) for sh in shots for e in sh.get("els", []) if e.get("t") in ("card", "screen")})
    crops = [i + 1 for i, sh in enumerate(shots) if any("crop" in e for e in sh.get("els", []))]
    if frag or crops:
        probs.append(f"fragment cards {frag} / crops in shots {crops}: a feature short shows the site's card whole "
                     "(owner verdict 2026-11-10)")
    sites = [(i + 1, e) for i, sh in enumerate(shots) for e in sh.get("els", []) if e.get("t") == "site"]
    pay = [i + 1 for i, sh in enumerate(shots) if sh.get("kind") == "PAYOFF"]
    if sorted({i for i, _e in sites}) != pay or any(e.get("name") != PAGE for _i, e in sites) or len(sites) != len(pay):
        probs.append(f"each PAYOFF shot shows the capture {PAGE!r} in one site window, and no other shot does "
                     f"(site windows in shots {[i for i, _e in sites]}, PAYOFF shots {pay})")
    if set(doc.get("screens") or {}) != {PAGE}:
        probs.append(f"screens {sorted(doc.get('screens') or {})}: a feature story has one screen, {PAGE!r}")
    # the voice: only the generator's spoken forms
    own = [i + 1 for i, sh in enumerate(shots) if sh.get("say")]
    if own:
        probs.append(f"shots {own} carry a say map of their own: a feature story speaks through the story's say map only")
    got_say = doc.get("say") or {}
    if got_say != want_say:
        extra = {k: got_say[k] for k in got_say if got_say.get(k) != want_say.get(k)}
        missing = sorted(k for k in want_say if k not in got_say)
        probs.append(f"the say map is not the generator's: changed or added {extra}, missing {missing}")
    spoken = spoken_script(doc)
    ok, det = spoken_numbers_gate({**got_say, **{k: v for sh in shots for k, v in (sh.get("say") or {}).items()}})
    if not ok:
        probs.append(f"spoken figures: {det['mismatch']}")
    said = " ".join(vo) + " " + spoken
    hits = vendor_hits(said)
    if hits:
        probs.append(f"the voice names a provider or a source: {hits}")
    adv = advice_hits(said)
    if adv:
        probs.append(f"the voice gives advice or a prediction: {adv}")
    shown = " ".join(shown_text(m) for m in metas.values())
    on_page = set(TICKER_TOKEN_RX.findall(shown))
    stray = sorted(set(TICKER_TOKEN_RX.findall(" ".join(vo + chips + typed) + " " + spoken)) - on_page - NOT_TICKERS)
    if stray:
        probs.append(f"ticker-like words that are on no capture: {stray}")
    return not probs, {"problems": probs, "values": vals, "lines": {k: want[k] for k in FEATURE_LINES}, "key": want["key"],
                       "spoken": spoken}


def feature_fact_gate(phrase: str, metas: dict, script: str) -> tuple[bool, dict]:
    """The one data phrase of a feature short is on a capture word for word and the voice reads it word for word."""
    where = sorted(n for n, m in metas.items() if on_capture(phrase, m))
    read = _has_run(page_words(script), page_words(phrase))
    return bool(where) and read, {"phrase": phrase, "on_captures": where, "in_script": read}


def key_target_gate(samples: list[dict], fps: int, kind: str = "figure") -> tuple[bool, dict]:
    """samples: one per rendered PAYOFF frame with the key outlined: {"t", "h" (the key text's height on screen), "box" (its
    box), "card_w" (the width on screen of the card it is on)}. A figure (a tag, a ticker, an amount) is at least 64 px tall
    for 1.5 s. A visual (a chart, or a table row that stays whole across the frame: its labels cannot be that tall) is at
    least 640 px wide with its outlined label at least 40 px tall for 1.5 s. Either way the key sits inside the safe area.
    A "site" key (feature shorts) is a text of the real card, outlined where it stands: at least 40 px tall on a card at
    least 900 px wide, inside the frame's safe height (a headline may run the card's width)."""
    def inside(k):
        return 60 <= k["box"][0] and k["box"][2] <= 960 and 300 <= k["box"][1] and k["box"][3] <= 1400
    if kind == "site":
        good = [k for k in samples if k["h"] >= SITE_KEY_MIN_H and k.get("card_w", 0.0) >= SITE_CARD_MIN_W
                and 0 <= k["box"][0] and k["box"][2] <= 1080 and 300 <= k["box"][1] and k["box"][3] <= 1400]
        limits = {"label_h": SITE_KEY_MIN_H, "card_w": SITE_CARD_MIN_W, "s": SITE_KEY_MIN_S}
    elif kind == "visual":
        good = [k for k in samples if k["h"] >= KEY_VISUAL_MIN_H and k.get("card_w", 0.0) >= KEY_VISUAL_MIN_W and inside(k)]
        limits = {"label_h": KEY_VISUAL_MIN_H, "card_w": KEY_VISUAL_MIN_W, "s": KEY_MIN_S}
    else:
        good = [k for k in samples if k["h"] >= KEY_MIN_H and inside(k)]
        limits = {"h": KEY_MIN_H, "s": KEY_MIN_S}
    secs = len(good) / fps
    return secs >= KEY_MIN_S, {"kind": kind, "readable_s": round(secs, 2), "samples": len(samples), "limits": limits,
                               "min_h": min((k["h"] for k in samples), default=None),
                               "max_h": max((k["h"] for k in samples), default=None),
                               "max_card_w": max((k.get("card_w", 0.0) for k in samples), default=None)}


# ------------------------------------------------------------------------------------------------- the site screen (features /2)
# One sample per rendered PAYOFF frame of a feature short (cartoon_reel.Reel._site_sample), all boxes in frame px
# (x0, y0, x1, y1):
#   {"t", "moving" (the window is flying in or out), "win" (the window that shows the strip), "card" (the card's DOM box,
#    where it would be if the window did not clip it), "parts" {name: box}, "key" (the outlined text's box, None while no
#    outline is drawn), "key_h", "caps" [caption boxes on screen], "peek" (Pip's head, or None)}
def _in(inner, outer, tol: float = 1.5) -> bool:
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol
            and inner[3] <= outer[3] + tol)


def _cut(a, b) -> list[float]:
    """The intersection of two boxes (possibly empty: x1 <= x0)."""
    return [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]


def _rows_shown(st: list[dict], box_of, fr) -> tuple[list[float], list | None]:
    """Which rows of a box the standing frames showed, as shares of its height: ([first, last reached without a gap],
    the first gap or None)."""
    ivs = []
    for s_ in st:
        c = box_of(s_)
        if c is None:
            continue
        vis = _cut(s_["win"], fr)
        h = c[3] - c[1]
        a_, b_ = max(c[1], vis[1]), min(c[3], vis[3])
        if h > 0 and b_ > a_ and c[0] >= vis[0] - 1.5 and c[2] <= vis[2] + 1.5:
            ivs.append(((a_ - c[1]) / h, (b_ - c[1]) / h))
    if not ivs:
        return [0.0, 0.0], [0.0, 1.0]
    reach, gap = 0.0, None
    for a_, b_ in sorted(ivs):
        if a_ > reach + 0.004:
            gap = [round(reach, 3), round(a_, 3)]
            break
        reach = max(reach, b_)
    return [round(min(a_ for a_, _b in ivs), 3), round(reach, 3)], gap


def site_card_whole_gate(samples: list[dict], fps: int, frame=(1080, 1920)) -> tuple[bool, dict]:
    """The payoff shows the site's card WHOLE (owner verdict 2026-11-10: "only the last one show the visuals correctly as
    it shown on website"; the first three cut the page into a headline strip, one table row and a chart lifted out).
    While the window stands: the card is never cut at its sides; the rows of the card shown over the payoff add up to its
    whole DOM box, top to bottom (a card taller than the window is scrolled, never cut into pieces); a card that fits the
    window is whole in one frame for SITE_WHOLE_MIN_S; and each named part (title, headline, chart, ...) is whole on
    screen for SITE_PART_MIN_S (a part taller than the window itself, two charts one under the other, is scrolled through
    from its first row to its last instead)."""
    fr = [0.0, 0.0, float(frame[0]), float(frame[1])]
    st = [s_ for s_ in samples if not s_["moving"]]
    side_cut = [s_ for s_ in st if not (s_["card"][0] >= max(s_["win"][0], 0.0) - 1.5
                                        and s_["card"][2] <= min(s_["win"][2], fr[2]) + 1.5)]
    rows, gap = _rows_shown(st, lambda s_: s_["card"], fr)
    covered = gap is None and rows[0] <= 0.004 and rows[1] >= 0.996
    fits = bool(st) and all(s_["card"][3] - s_["card"][1] <= s_["win"][3] - s_["win"][1] + 1.5 for s_ in st)
    whole_s = sum(1 for s_ in st if _in(s_["card"], _cut(s_["win"], fr))) / fps
    names = sorted({n for s_ in st for n in s_.get("parts") or {}})
    part_s = {n: round(sum(1 for s_ in st if n in s_["parts"] and _in(s_["parts"][n], _cut(s_["win"], fr))) / fps, 2)
              for n in names}
    win_h = min((s_["win"][3] - s_["win"][1] for s_ in st), default=0.0)
    tall = {}                                         # parts that cannot be whole in one frame: every row was shown?
    for n in names:
        hs = [s_["parts"][n][3] - s_["parts"][n][1] for s_ in st if n in s_["parts"]]
        if hs and min(hs) > win_h + 1.5:
            r_, g_ = _rows_shown(st, lambda s_, n=n: s_["parts"].get(n), fr)
            tall[n] = {"rows_shown": r_, "gap_in_rows": g_, "ok": g_ is None and r_[0] <= 0.004 and r_[1] >= 0.996}
    short = sorted(n for n, v in part_s.items() if (not tall[n]["ok"] if n in tall else v < SITE_PART_MIN_S))
    ok = (bool(st) and not side_cut and covered and not short and len(names) >= SITE_PARTS_NEEDED
          and (not fits or whole_s >= SITE_WHOLE_MIN_S))
    return ok, {"standing_s": round(len(st) / fps, 2), "frames_cut_at_the_sides": len(side_cut),
                "rows_shown": rows, "gap_in_rows": gap, "parts_taller_than_the_window": tall,
                "card_fits_the_window": fits, "whole_in_one_frame_s": round(whole_s, 2), "scrolled": not fits,
                "parts_whole_s": part_s, "parts_never_whole": short,
                "limits": {"whole_s": SITE_WHOLE_MIN_S, "part_s": SITE_PART_MIN_S, "parts": SITE_PARTS_NEEDED}}


def card_width_gate(samples: list[dict], fps: int, min_w: float = SITE_CARD_MIN_W, frame_w: float = 1080.0) -> tuple[bool, dict]:
    """The card is LARGE: at least min_w px wide on screen in every frame the window stands (the owner asked for about
    940-1010 px of the 1080 frame), inside the frame, for at least SITE_STAND_MIN_S."""
    st = [s_ for s_ in samples if not s_["moving"]]
    ws = [s_["card"][2] - s_["card"][0] for s_ in st]
    small = [round(s_["t"], 2) for s_, w in zip(st, ws) if w < min_w or s_["card"][0] < -1.5 or s_["card"][2] > frame_w + 1.5]
    secs = len(st) / fps
    return bool(st) and not small and secs >= SITE_STAND_MIN_S, {
        "min_w": round(min(ws), 1) if ws else None, "max_w": round(max(ws), 1) if ws else None, "standing_s": round(secs, 2),
        "too_small_or_off_frame_at_s": small[:12], "limits": {"w": min_w, "s": SITE_STAND_MIN_S}}


def no_overlap_gate(samples: list[dict]) -> tuple[bool, dict]:
    """Nothing of ours sits on the real screen: no caption and no Pip in any payoff frame, the frames in which the window
    flies in included (the caption band is below the window, Pip's head beside the captions)."""
    hits = []
    for s_ in samples:
        for kind, boxes in (("caption", s_.get("caps") or []), ("pip", [s_["peek"]] if s_.get("peek") else [])):
            for b_ in boxes:
                a_ = box_overlap(b_, s_["win"], shrink=0.0)
                if a_ > 0:
                    hits.append({"t": round(float(s_["t"]), 2), "what": kind, "px2": round(a_)})
    return bool(samples) and not hits, {"samples": len(samples), "n_hits": len(hits), "hits": hits[:16]}


def key_in_place_gate(samples: list[dict], fps: int, frame=(1080, 1920)) -> tuple[bool, dict]:
    """The key value is outlined IN PLACE: whenever the outline is drawn, the outlined text lies on the card, inside the
    window that shows the same strip (it is not a second capture, a re-crop or an enlargement), at least SITE_KEY_MIN_H px
    tall, for SITE_KEY_MIN_S."""
    fr = [0.0, 0.0, float(frame[0]), float(frame[1])]
    drawn = [s_ for s_ in samples if s_.get("key")]
    off = [round(s_["t"], 2) for s_ in drawn if not _in(s_["key"], _cut(_cut(s_["card"], s_["win"]), fr))]
    good = [s_ for s_ in drawn if not s_["moving"] and s_.get("key_h", 0.0) >= SITE_KEY_MIN_H]
    secs = len(good) / fps
    return bool(drawn) and not off and secs >= SITE_KEY_MIN_S, {
        "outlined_s": round(len(drawn) / fps, 2), "readable_s": round(secs, 2), "off_the_card_at_s": off[:12],
        "min_h": round(min((s_.get("key_h", 0.0) for s_ in drawn), default=0.0), 1),
        "limits": {"h": SITE_KEY_MIN_H, "s": SITE_KEY_MIN_S}}
