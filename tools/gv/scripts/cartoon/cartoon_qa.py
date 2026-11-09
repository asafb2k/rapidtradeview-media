"""Text QA for the cartoon-story Reel (cartoon_reel.py): pure functions, no rendering, so the gates are unit-tested offline
(tools/tests/test_cartoon_qa.py).

  find_numbers(text)                 every number-like token (money, %, dates, counts); document names such as "Form 4" are
                                     names, not numbers
  numbers_gate(texts, allowed, ...)  every number we draw, caption or speak is one of the item's numbers, as written there
  spoken_numbers_gate(say)           every spelled-out number we make the voice say equals the figure it stands for
  screen_numbers_gate(...)           every number visible in a real screenshot comes from the item or is acknowledged by the story
  provider_gate(texts)               no data-provider names (card_reel.PROVIDER_RX)
  banned_gate(texts, banned)         none of the item's banned words
  caption_gate(chunks, script)       the captions, joined, are exactly the voice script (nothing added, dropped or reordered)
  chunk_words(words, measure)        the caption chunker (1-3 words, <= 18 characters, never across a sentence end)
"""
from __future__ import annotations

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
NUM_RX = re.compile(r"[−+\-]?\$?\d+(?:[,./]\d+)*(?:[KMBT](?![a-z])|%)?")
TRAIL = ".,;:)]!?\"'”"


def norm_num(tok: str) -> str:
    return " ".join(tok.replace("−", "-").split()).strip(TRAIL).lstrip("(\"'“")


def find_numbers(text: str) -> list[str]:
    """Number-like tokens in order: month-day dates ("Nov 6", "Nov 6, 2026") and ISO dates as one token, money and percent
    with their sign/suffix, other digit runs ("2/2", "500"). Document names ("Form 4", "10-K") are skipped."""
    s = DOC_NAME_RX.sub(lambda m: " " * len(m.group(0)), str(text))
    out: list[tuple[int, str]] = []
    for m in DATE_RX.finditer(s):
        out.append((m.start(), norm_num(m.group(0))))
    s = DATE_RX.sub(lambda m: " " * len(m.group(0)), s)
    for m in NUM_RX.finditer(s):
        out.append((m.start(), norm_num(m.group(0))))
    return [t for _, t in sorted(out)]


def allowed_set(item: dict) -> set[str]:
    return {norm_num(x) for x in (item.get("allowed_numbers") or []) + (item.get("context_numbers") or []) if isinstance(x, str)}


def numbers_gate(texts: dict[str, str], allowed: set[str] | list[str]) -> tuple[bool, dict]:
    """texts: role -> text. Every number token must be in `allowed` (normalised: - and the minus sign alike)."""
    ok_set = {norm_num(a) for a in allowed}
    bad: dict[str, list[str]] = {}
    seen: dict[str, list[str]] = {}
    for role, txt in texts.items():
        nums = find_numbers(txt)
        if nums:
            seen[role] = nums
        miss = [n for n in nums if n not in ok_set]
        if miss:
            bad[role] = miss
    return not bad, {"not_in_item": bad, "found": seen}


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


def screen_numbers_gate(visible_text: str, item: dict, ack: dict[str, str]) -> tuple[bool, dict]:
    """Numbers visible in a real screenshot: each is an item number as written, an item value in another format (the page's
    "$14,994,200" for amount_top_usd 14994200; the trade count `rows`), or acknowledged by the story with a reason."""
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
            out[n] = "acknowledged: " + str(ack[n]).strip()
        else:
            out[n] = None
    bad = sorted(k for k, v in out.items() if v is None)
    return not bad, {"numbers": out, "unexplained": bad}


# ------------------------------------------------------------------------------------------------- words
def provider_gate(texts: dict[str, str]) -> tuple[bool, dict]:
    hits = {role: sorted({m.group(0) for m in PROVIDER_RX.finditer(t)}) for role, t in texts.items()}
    hits = {k: v for k, v in hits.items() if v}
    return not hits, {"found": hits}


def banned_gate(texts: dict[str, str], banned: list[str]) -> tuple[bool, dict]:
    every = " \n ".join(texts.values()).lower()
    hits = sorted({w for w in banned if isinstance(w, str) and w.strip() and cr.word_rx(w).search(every)})
    return not hits, {"found": hits, "checked": len(banned)}


def caption_gate(chunks: list[str], script: str) -> tuple[bool, dict]:
    """The captions, joined in order, are exactly the voice script's words; reports the first difference."""
    cap, ref = " ".join(chunks).split(), str(script).split()
    if cap == ref:
        return True, {"words": len(ref)}
    sm = difflib.SequenceMatcher(a=ref, b=cap, autojunk=False)
    diff = [{"op": op, "script": ref[i1:i2], "captions": cap[j1:j2]} for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
    not_in_script = sorted({w for w in cap if w not in set(ref)})
    return False, {"diff": diff[:8], "caption_words_not_in_script": not_in_script}


def fact_phrase_gate(phrase: str, item: dict, script: str) -> tuple[bool, dict]:
    """The one data sentence is one of the item's own phrasings (or its facts_text), verbatim, and the voice script holds it."""
    pool = [item.get("facts_text")] + list(item.get("fact_phrases") or []) + list(item.get("angles") or [])
    pool += [p.get("text") for p in item.get("phrasings") or [] if isinstance(p, dict)]
    norm = cr.norm_ws
    in_item = any(isinstance(p, str) and norm(p) == norm(phrase) for p in pool)
    in_script = norm(phrase) in norm(script)
    return in_item and in_script, {"phrase": phrase, "in_item": in_item, "in_script": in_script}


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
    without its quote marks."""
    out = []
    for i, w in enumerate(words):
        sp = say.get(w)
        if sp is None:
            sp = w.replace('"', "").replace("“", "").replace("”", "")
        for tok in sp.split():
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
