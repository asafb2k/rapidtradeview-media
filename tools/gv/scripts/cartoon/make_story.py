"""TEMPLATE mode for the cartoon Reel: one facts item -> story.json in the one-idea format, with no hand-written creative.

    make_story.py FACTS.json ITEM_ID --run DIR [--post-date YYYY-MM-DD] [--capture] [--shot-python PY]

The pattern (owner verdict 2026-11-09: "the pilot short is too complicated and it isnt clear what brand behind it"):
  1 HOOK      Dale says the news with the item's number, in a way that does not explain it   "CEG beat by $1.17!"
  2 CLOSE     Pip, phone up (our mark on it), is confused and says where he looks              "Beat what? Checking RapidTradeView."
  3 CLOSE     the phone close: our name and mark on top, the ticker typed into the search      (no voice, key clacks)
  4 PAYOFF    our real page: its header and logo on top, the key card below                   the item's own phrase, part 1
  5 PAYOFF    the camera lands on the key figure, outlined                                     the item's own phrase, part 2
  6 CALLBACK  one word                                                                          "Oh."
  7 END       "Search RapidTradeView. Not investment advice."

Templates: earnings_result (an EPS beat or miss against consensus) and form4_buy (an open-market buy). Any other item: exit 2
(No Fallbacks: no template, no video). The fact phrase is one of the item's own phrasings, verbatim; every line that
states a fact carries the id of the phrasing it paraphrases (the renderer's claim_lines gate checks it).

With --capture the real pages are captured now (capture.py in the shot venv) into DIR/screens; without it the captures must
already be there. Numbers on a capture that are not the item's are acknowledged only for two known page parts (the guest
counter in the site header, the "Consensus captured <date>" small print); any other one stops the script: re-crop.
Then render:  cartoon_reel.py --story DIR/story.json --out DIR
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cartoon_qa as Q  # noqa: E402

cr = Q.cr
TEMPLATE = "rtv-cartoon-template/1"
VOICES = {"narrator": {"id": "af_heart", "speed": 1.1}, "dale": {"id": "am_michael", "speed": 1.12},
          "pip": {"id": "am_puck", "speed": 1.06}, "end": {"id": "af_heart", "speed": 1.15}}
REACTION = "Oh."
COUNTER_RX = r"^\d+/\d+$|(?<![\d.])\d/\d(?![\d.])"           # the site header's guest counter ("0/2"), maybe split in nodes
CARD_W, CARD_TOP, CARD_GAP, CARD_BOTTOM = 860, 384, 26, 1130     # the two real cards between the brand pill and the captions


class TemplateError(Exception):
    pass


# ------------------------------------------------------------------------------------------------- spoken forms
_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen " \
        "eighteen nineteen".split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()


def int_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10 - 2] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + int_words(n % 100))
    if n < 1_000_000:
        return int_words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + int_words(n % 1000))
    if n < 1_000_000_000:
        return int_words(n // 1_000_000) + " million" + ("" if n % 1_000_000 == 0 else " " + int_words(n % 1_000_000))
    raise TemplateError(f"no spoken form for {n}")


def speak_figure(tok: str, unit: bool = True) -> str:
    """"$5.06" -> "five point zero six dollars", "$1.29M" -> "one point two nine million dollars" (Q.spoken_value reads it
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
    In the `bare` lines (the read-out fact) a small dollar figure is said without "dollars" ("EPS five point zero six"):
    the screen shows the $ and the line is a second shorter."""
    say = {}
    letters = " ".join(ticker.replace("-", " "))
    for line in lines:
        unit = line not in bare
        for w in line.split():
            core = w.strip("().,!?:;")
            lead, trail = w[: w.index(core)] if core else "", w[w.index(core) + len(core):] if core else ""
            trail = trail.replace(")", "")
            lead = lead.replace("(", "")
            if re.search(r"\d", core):
                v = Q.written_value(core) or 0.0
                say[w] = lead + speak_figure(core, unit or v >= 1000) + trail
            elif core.lstrip("$").upper() == ticker.upper() and len(core.lstrip("$")) <= 5:
                say[w] = lead + letters + trail
            elif core == "EPS":
                say[w] = lead + "E P S" + trail
            elif core == "vs":
                say[w] = lead + "versus" + trail
            elif core == cr.BRAND:
                say[w] = lead + "Rapid Trade View" + trail
    return say


# ------------------------------------------------------------------------------------------------- picking phrasings
def phrasings(item: dict) -> list[dict]:
    seen, out = set(), []
    for p in item.get("phrasings") or []:
        if isinstance(p, dict) and p.get("id") and p.get("text") and (p["id"], p["text"]) not in seen:
            seen.add((p["id"], p["text"]))
            out.append(p)
    return out


def shortest(item: dict, must: list[str], pred=lambda t: True) -> dict:
    """The shortest phrasing that has every string in `must` (and passes `pred`). Two sentences may share one id (the
    facts write EPS both as "EPS" and as its basis); they carry the same figures, which is what the claim gate checks."""
    ps = [p for p in phrasings(item) if all(m in p["text"] for m in must) and pred(p["text"])]
    if not ps:
        raise TemplateError(f"no phrasing of the item has {must}")
    return min(ps, key=lambda p: len(p["text"]))


# ------------------------------------------------------------------------------------------------- templates
def plan_earnings(item: dict) -> dict:
    eps = (item.get("results") or {}).get("eps") or {}
    label, verdict = str(eps.get("label") or ""), eps.get("verdict")
    if verdict not in ("beat", "miss") or not re.match(r"(?i)(beat|miss\w*) by \$", label):
        raise TemplateError("earnings_result without an EPS beat/miss against consensus: no one-idea template")
    if not item.get("report_id"):
        raise TemplateError("earnings_result without report_id: no report page to capture")
    ticker = item["ticker"]
    verb = label.split()[0]                                  # "Beat" / "Missed"
    diff = Q.find_numbers(label)[0]
    rx = re.compile(r"^EPS (\$[\d.,]+) vs (\$[\d.,]+) \((?:beat|miss\w*) by (\$[\d.,]+)\)\.$")
    fact = shortest(item, [diff], lambda t: bool(rx.match(t)))
    rep, cons, _ = rx.match(fact["text"]).groups()
    a, b = fact["text"].split(" (", 1)
    hook = shortest(item, [f"${ticker}", diff, "EPS"])
    base = re.match(r"(https://[^/]+)/", item["page_url"]).group(1)
    return {
        "kind": "earnings_eps", "ticker": ticker, "figure": diff, "key": label,
        "hook": {"vo": f"{ticker} {verb.lower()} by {diff}!", "claim": hook["id"]},
        "confused": {"vo": f"{verb} what? Checking {cr.BRAND}.", "claim": None},
        "fact": {"text": fact["text"], "id": fact["id"], "a": a, "b": "(" + b},
        "url": f"{base}/earnings/reports/{item['report_id']}",
        "captures": [
            {"name": "head", "clip_from": cr.BRAND, "clip_to": item["name"], "targets": [cr.BRAND, ticker], "pad": 16},
            {"name": "fact", "clip_from": "EPS#last", "clip_to": label, "targets": [rep, cons, label], "pad": 6},
        ],
        "zoom_a": [rep, cons], "ack_lines": {"head": [COUNTER_RX], "fact": [r"^Consensus captured "]},
    }


def plan_form4(item: dict) -> dict:
    ticker, amt = item["ticker"], item.get("amount_text")
    if not amt or not isinstance(item.get("amount_top_usd"), (int, float)):
        raise TemplateError("form4_buy without amount_text / amount_top_usd")
    key = f"${item['amount_top_usd']:,.0f}"                  # the page writes the full dollar figure
    hook = shortest(item, [f"${ticker}", amt], lambda t: " bought " in t)
    fact = hook
    words = fact["text"].split()
    k = next(i for i, w in enumerate(words) if amt in w) + 1
    return {
        "kind": "form4_buy", "ticker": ticker, "figure": amt, "key": key,
        "hook": {"vo": f"{ticker} insider bought {amt}!", "claim": hook["id"]},
        "confused": {"vo": f"Who bought? Checking {cr.BRAND}.", "claim": hook["id"]},
        "fact": {"text": fact["text"], "id": fact["id"], "a": " ".join(words[:k]), "b": " ".join(words[k:])},
        "url": re.sub(r"[?#].*$", "", item["page_url"]),
        "captures": [
            {"name": "head", "clip_from": cr.BRAND, "clip_to": item["name"], "targets": [cr.BRAND], "pad": 16},
            {"name": "fact", "clip_from": "Disclosed trades", "clip_to": "View filing", "targets": [key], "pad": 10},
        ],
        "zoom_a": [key], "ack_lines": {"head": [COUNTER_RX], "fact": []},
    }


PLANS = {"earnings_result": plan_earnings, "form4_buy": plan_form4}


def plan_for(item: dict) -> dict:
    fn = PLANS.get(item.get("type"))
    if not fn:
        raise TemplateError(f"no one-idea template for {item.get('type')!r} (templates: {', '.join(PLANS)})")
    return fn(item)


# ------------------------------------------------------------------------------------------------- captures
def run_captures(plan: dict, screens: Path, shot_python: str) -> None:
    for c in plan["captures"]:
        cmd = [shot_python, "-I", str(HERE / "capture.py"), "--url", plan["url"], "--out", str(screens), "--name", c["name"],
               "--clip-from", c["clip_from"], "--clip-to", c["clip_to"], "--clip-pad", str(c["pad"])]
        for t in c["targets"]:
            cmd += ["--target", t]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise TemplateError(f"capture {c['name']} failed: {(r.stderr or r.stdout).strip()[-400:]}")


def acks_for(plan: dict, item: dict, name: str, meta: dict) -> dict[str, str]:
    """Acknowledge only the known page parts; any other number that is not the item's stops the template."""
    ok, det = Q.screen_numbers_gate(meta.get("visible_text", ""), item, {})
    if ok:
        return {}
    lines = [ln.strip() for ln in meta.get("visible_text", "").splitlines()]
    out, left = {}, []
    reasons = {COUNTER_RX: "the guest view counter in our site header",
               r"^Consensus captured ": "the day the consensus was captured (small print under the figure)"}
    for n in det["unexplained"]:
        i = next((k for k, ln in enumerate(lines) if n in Q.find_numbers(ln)), None)
        line = lines[i] if i is not None else ""
        near = "".join(lines[max(0, i - 2):i + 3]) if i is not None else ""      # "0", "/", "2": one counter in 3 nodes
        rx = next((r for r in plan["ack_lines"].get(name, []) if re.search(r, line) or (r == COUNTER_RX and re.search(r, near))),
                  None)
        if rx:
            out[n] = reasons[rx]
        else:
            left.append(f"{n} (in {line!r})")
    if left:
        raise TemplateError(f"screen {name}: numbers that are not the item's: {', '.join(left)}; crop them out")
    return out


# ------------------------------------------------------------------------------------------------- the story
def build_story(item: dict, facts_file: str, post_date: str, plan: dict, screens: dict[str, dict]) -> dict:
    """screens: {"head": {"png": path, "size": [w, h], "meta": sidecar}, "fact": {...}} -> the story dict."""
    t = plan["ticker"]
    hw, hh = screens["head"]["size"]
    fw, fh = screens["fact"]["size"]
    w = CARD_W
    h_head, h_fact = hh * w / hw, fh * w / fw
    avail = CARD_BOTTOM - CARD_TOP - CARD_GAP
    if h_head + h_fact > avail:                                  # shrink both so they fit above the caption band
        k = avail / (h_head + h_fact)
        w, h_head, h_fact = int(w * k), h_head * k, h_fact * k
    y_head = CARD_TOP + h_head / 2
    y_fact = CARD_TOP + h_head + CARD_GAP + h_fact / 2
    head_el = {"t": "card", "name": "head", "x": 540, "y": round(y_head), "w": w, "rot": -1.5, "main": False}
    fact_el = {"t": "card", "name": "fact", "x": 540, "y": round(y_fact), "w": w, "rot": 1.0, "main": True}
    peek = {"who": "pip", "expr": "shock", "x": 170, "y": 1650, "hu": 250, "rot": 14, "at": 0.3, "from": [-320, 0]}
    fig = plan["figure"]
    hook_vo = plan["hook"]["vo"]
    fig_word = next(x for x in hook_vo.split() if fig in x)
    lines = [hook_vo, plan["confused"]["vo"], plan["fact"]["a"], plan["fact"]["b"], REACTION,
             f"Search {cr.BRAND}. {cr.DISCLAIMER}"]
    shots = [
        {"kind": "HOOK", "set": "gym", "voice": "dale", "claim": plan["hook"]["claim"], "vo": hook_vo, "stress": [fig_word],
         "move": {"type": "push", "amt": 0.05, "focus": [430, 480]},
         "chip": {"text": fig, "x": 790, "y": 500, "at": f"word:{fig_word.strip('!.,')}", "rot": -4, "size": 82},
         "els": [{"t": "dale", "x": 430, "y": 2041, "hu": 330, "pose": "idle", "expr": "smug", "brow": True}]},
        {"kind": "CLOSE", "set": "gym", "set_variant": 1, "voice": "pip", "claim": plan["confused"]["claim"],
         "vo": plan["confused"]["vo"], "stress": [f"{cr.BRAND}."], "hold": 0.1,
         "move": {"type": "push", "amt": 0.1, "focus": [540, 640]},
         "els": [{"t": "pip", "x": 540, "y": 1388, "hu": 460, "pose": "phone_hold", "expr": "side", "hold": ["phone"],
                  "swap": {"at": "word:Checking", "expr": "deadpan"}}]},
        {"kind": "CLOSE", "set": "gym", "set_variant": 2, "dur": 1.5,
         "move": {"type": "push", "amt": 0.14, "focus": [540, 600]},
         "els": [{"t": "search_phone", "x": 540, "y": 840, "w": 520, "text": t.replace("-", "."), "at": 0.2, "rate": 0.11}]},
        {"kind": "PAYOFF", "set": "payoff", "ring_centre": [540, 760], "transition_in": "whip", "voice": "narrator",
         "claim": plan["fact"]["id"], "vo": plan["fact"]["a"],
         "move": {"type": "zoom_to", "target": plan["zoom_a"], "z": 1.45, "s0": 1.0, "at": 1.2, "dur": 0.9, "land": [540, 800],
                  "drift": 0.02},
         "peek": peek,
         "els": [dict(head_el, enter={"from": [0, -900], "dur": 0.3}), dict(fact_el, enter={"from": [0, 1100], "dur": 0.34})]},
        {"kind": "PAYOFF", "set": "payoff", "ring_centre": [540, 760], "voice": "narrator", "join": True,
         "claim": plan["fact"]["id"], "vo": plan["fact"]["b"], "hold": 0.7, "key_number": plan["key"],
         "move": {"type": "zoom_to", "target": plan["key"], "z": 2.2, "from_target": plan["zoom_a"], "z0": 1.47, "at": 0.0,
                  "dur": 0.5, "land": [540, 800],
                  "drift": 0.03},
         "peek": dict(peek, at=0.0, **{"from": [0, 0]}, expr="smug"),
         "els": [head_el, fact_el, {"t": "highlight", "target": plan["key"], "at": 0.45}]},
        {"kind": "CALLBACK", "set": "gym", "voice": "pip", "vo": REACTION, "hold": 0.5, "transition_in": "whip",
         "move": {"type": "push", "amt": 0.12, "focus": [540, 560]},
         "els": [{"t": "pip", "x": 540, "y": 1388, "hu": 460, "pose": "phone_hold", "expr": "shock", "hold": ["phone"],
                  "swap": {"at": 0.25, "expr": "happy"}}]},
        {"kind": "END", "vo": f"Search {cr.BRAND}. {cr.DISCLAIMER}", "vo_at": 0.08, "voice": "end"},
    ]
    return {
        "schema": "rtv-cartoon-story/1",
        "template": {"name": TEMPLATE, "plan": plan["kind"], "made_by": "make_story.py"},
        "item_id": item["item_id"], "facts_file": facts_file, "fact_phrase": plan["fact"]["text"],
        "phrase_id": plan["fact"]["id"], "post_date": post_date, "voices": VOICES,
        "say": say_map(lines, t, (plan["fact"]["a"], plan["fact"]["b"])),
        "screens": {n: str(v["png"]) for n, v in screens.items()},
        "screen_numbers_ack": {n: acks_for(plan, item, n, v["meta"]) for n, v in screens.items()},
        "shots": shots,
    }


def load_screens(run: Path) -> dict[str, dict]:
    out = {}
    for n in ("head", "fact"):
        png, side = run / "screens" / f"{n}.png", run / "screens" / f"{n}.json"
        if not png.is_file() or not side.is_file():
            raise TemplateError(f"capture {png} is missing (run with --capture)")
        meta = json.loads(side.read_text(encoding="utf-8"))
        out[n] = {"png": png, "size": meta["png_size"], "meta": meta}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("facts")
    ap.add_argument("item_id")
    ap.add_argument("--run", required=True, help="the render folder: screens/ and story.json go here")
    ap.add_argument("--post-date", help="YYYY-MM-DD the video goes out (default: the facts date)")
    ap.add_argument("--capture", action="store_true", help="capture the real pages now (shot venv)")
    ap.add_argument("--shot-python", help="the Playwright venv python (default: <media>/.ops/cache/shot-venv)")
    a = ap.parse_args(argv)
    try:
        facts_path = Path(a.facts).resolve()
        facts = json.loads(facts_path.read_text(encoding="utf-8-sig"))
        item = next((i for i in facts.get("items", []) if i.get("item_id") == a.item_id), None)
        if not item:
            raise TemplateError(f"item {a.item_id} not in {facts_path}")
        plan = plan_for(item)
        run = Path(a.run).resolve()
        run.mkdir(parents=True, exist_ok=True)
        if a.capture:
            shot_py = a.shot_python
            if not shot_py:
                ops = next((p / ".ops" for p in HERE.parents if (p / ".ops" / "cache" / "shot-venv").is_dir()), None)
                if not ops:
                    raise TemplateError("no .ops/cache/shot-venv above this script (pass --shot-python)")
                shot_py = str(ops / "cache" / "shot-venv" / "Scripts" / "python.exe")
            run_captures(plan, run / "screens", shot_py)
        story = build_story(item, str(facts_path), a.post_date or str(facts.get("date") or a.item_id[:10]), plan,
                            load_screens(run))
        for s_ in story["screens"]:
            story["screens"][s_] = str(Path(story["screens"][s_]).relative_to(run)).replace("\\", "/")
    except TemplateError as e:
        print(f"make_story: {e}", file=sys.stderr)
        return 2
    out = run / "story.json"
    out.write_text(json.dumps(story, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"story": str(out), "plan": plan["kind"], "fact_phrase": story["fact_phrase"],
                      "lines": [s_.get("vo") for s_ in story["shots"] if s_.get("vo")]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
