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
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
import sys
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
                                                                    "double", "triple", "quadruple"}
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
    a written form without digits, e.g. "socks" -> "two socks")."""
    bad = {}
    for written, spoken in say.items():
        wv, sv = written_value(written), spoken_value(spoken)
        if re.search(r"\d", spoken):
            bad[written] = f"spoken form has digits: {spoken!r}"
        elif wv is None and sv is not None:
            bad[written] = f"adds a number: {spoken!r}"
        elif wv is not None and (sv is None or abs(sv - wv) > 1e-6 * max(1.0, wv)):
            bad[written] = f"{spoken!r} is {sv}, not {wv}"
    return not bad, {"mismatch": bad, "checked": len(say)}


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
        if any("(" in w for w in words[i + 1:j]):
            c += 2.0                                   # a parenthesis opens a chunk, it does not sit inside one
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
STORY_ELS = {"pip", "dale", "search_phone", "card", "screen", "highlight", "receipt"}   # anything else is a side gag
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
