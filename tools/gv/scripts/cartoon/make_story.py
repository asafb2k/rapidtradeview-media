"""TEMPLATE mode for the cartoon Reel: one facts item -> story.json in the one-idea format, with no hand-written creative.

    make_story.py FACTS.json ITEM_ID --run DIR [--post-date YYYY-MM-DD] [--capture] [--shot-python PY]

The pattern (owner verdict 2026-11-09: "the pilot short is too complicated and it isnt clear what brand behind it"):
  1 HOOK      Dale says the news with the item's number, in a way that does not explain it   "CEG beat by $1.17!"
  2 CLOSE     Pip, phone up (our mark on it), is confused and says where he looks              "Beat what? Checking RapidTradeView."
  3 CLOSE     the phone close: our name and mark on top, the ticker typed into the search      (no voice, key clacks)
  4 PAYOFF    our real page: its header and logo on top, the fact card below                  the item's own phrase, part 1
  5 PAYOFF    the header flies off, the real key figure lands big and outlined                 the item's own phrase, part 2
  6 CALLBACK  one word (Pip's peek stays wide-eyed until here: shock -> happy on the word)    "Oh."
  7 END       "Search RapidTradeView. Not investment advice."

Templates: earnings_result (an EPS beat or miss against consensus) and form4_buy (an open-market buy). Any other item: exit 2
(No Fallbacks: no template, no video). The fact phrase is one of the item's own phrasings, verbatim (for earnings the one that
says "consensus", so "Beat what?" is answered in the caption); every line that states a fact carries the id of the phrasing
it paraphrases (the renderer's claim_lines gate checks it), and the payoff lines repeat the hook's figure and say what it is
(EPS / bought): the hook's short form is always resolved on screen.

With --capture the real pages are captured now (capture.py in the shot venv) into DIR/screens; without it the captures must
already be there. The earnings fact card ends above the page's "Consensus captured <date>" small print (that date is not the
item's), a Form 4 card is the trade's own two lines, and the key figure (the "Beat by $1.17" tag, the "$1,287,400" amount)
is its own 6x capture, cropped tight. Numbers on a capture that are not the item's are acknowledged only for the
guest counter in the site header, and only the counter's own digits ("0/2" on its own line, or "0", "/", "2" as three
nodes); any other number stops the script: re-crop.
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
import cast as C  # noqa: E402

cr = Q.cr
TEMPLATE = "rtv-cartoon-template/1"
VOICES = {"narrator": {"id": "af_heart", "speed": 1.1}, "dale": {"id": "am_michael", "speed": 1.12},
          "pip": {"id": "am_puck", "speed": 1.06}, "end": {"id": "af_heart", "speed": 1.15}}
REACTION = "Oh."
COUNTER = "counter"                          # the site header's guest counter ("0/2"), maybe 3 nodes
ACK_REASONS = {COUNTER: "the guest view counter in our site header"}
# The payoff stage (frame px). The persistent brand pill ends at y 333 (cartoon_reel.BRAND_PILL_XY + its height) and the one
# caption band starts at ~1175: every card that stays on screen keeps between STAGE_TOP and STAGE_BOTTOM, so the pill never
# lands on our page (two logos colliding) and the caption never covers a figure.
STAGE_TOP, STAGE_BOTTOM = 362, 1160
CARD_W, CARD_GAP, KEY_W = 860, 26, 600       # header and fact cards, the gap, the key tag card (earnings)
ALSO_GAP = 18                                # between the key card and a second crop under it
PUSH_AMT, PUSH_S = 0.03, 1.15                # shot 4: a slow push; PUSH_S bounds its scale over a long shot (drift included)
Z5_MAX, Z5_DRIFT = 1.4, 0.03                 # shot 5: the zoom onto the key figure, and its drift after landing
PEEK = {"who": "pip", "expr": "shock", "x": 175, "y": 1430, "hu": 240, "rot": 14}   # above the bottom 18% (IG caption)
# A character shot: the face's top stays below the brand pill and the held prop's bottom above the caption band, at every
# scale of the shot's push (its longest likely length included).
CHAR_TOP, CHAR_BOTTOM = 345, 1120


def char_frame(who: str, pose: str, hold: tuple, hu: float, amt: float, dur: float, x: float = 540) -> tuple[float, list]:
    """(feet y, push focus) that keep `who`'s face and held prop (cast's protect boxes) between CHAR_TOP and CHAR_BOTTOM
    while the push grows to (1 + amt)(1 + 0.03 dur)."""
    boxes = C.pip_boxes(pose, hold, 0.0, None) if who == "pip" else C.dale_boxes(pose, hold)
    top = min(b[1] for _, b in boxes) * hu                         # hu above the feet (y down: negative)
    bot = max(b[3] for _, b in boxes) * hu
    S = (1 + amt) * (1 + 0.03 * dur)
    if (bot - top) * S > CHAR_BOTTOM - CHAR_TOP:
        raise TemplateError(f"{who} at hu {hu} does not fit between the brand pill and the captions; make him smaller")
    c = (CHAR_TOP + CHAR_BOTTOM) / 2
    feet = c - (top + bot) / 2
    return round(feet), [x, round(c)]


TemplateError = Q.TemplateError              # one class for both generators and the gates (cartoon_qa holds it)

# ------------------------------------------------------------------------------------------------- spoken forms
# In cartoon_qa, so that the gates can rebuild the one say map a story may carry (feature_story).
int_words, speak_figure, say_map = Q.int_words, Q.speak_figure, Q.say_map


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
    rx = re.compile(r"^EPS (\$[\d.,]+) vs (\$[\d.,]+) consensus \((?:beat|miss\w*) by (\$[\d.,]+)\)\.$")
    fact = shortest(item, [diff, " consensus ("], lambda t: bool(rx.match(t)))
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
            # the fact card ends above the "Consensus captured <date>" small print: that date is not the item's
            {"name": "fact", "clip_from": "EPS#last", "clip_to": label, "end_above": "Consensus captured", "targets": [rep, cons],
             "pad": 6},
            # the page's own "Beat by $1.17" tag, captured alone at 6x so it can land big
            {"name": "key", "clip_from": label, "clip_to": label, "targets": [label], "pad": 8, "dpr": 6},
        ],
        "ack": {"head": [COUNTER]},
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
        # no ticker in the hook: "P A M insider bought one point two nine million dollars" ran 3.4 s on the first real
        # render (hook max 2.6 s); the ticker is typed on the phone and read in the payoff
        "hook": {"vo": f"Insider bought {amt}!", "claim": hook["id"]}, "bare_hook": True,
        "confused": {"vo": f"Who bought? Checking {cr.BRAND}.", "claim": hook["id"]},
        "fact": {"text": fact["text"], "id": fact["id"], "a": " ".join(words[:k]), "b": " ".join(words[k:])},
        "url": re.sub(r"[?#].*$", "", item["page_url"]),
        "captures": [
            {"name": "head", "clip_from": cr.BRAND, "clip_to": item["name"], "targets": [cr.BRAND], "pad": 16},
            # the trade's own two lines (dates + amount): the row above them carries a "pending · 0/20" progress count and
            # the section intro a source line, neither of them the item's (first real run, PAM 2026-11-09)
            {"name": "fact", "clip_from": "Traded#last", "clip_to": "View filing", "targets": [key], "pad": 4},
            # the amount alone at 6x: on the thin trade strip it was ~35 px tall, too small to be the punchline
            {"name": "key", "clip_from": key, "clip_to": key, "targets": [key], "pad": 8, "dpr": 6},
        ],
        "ack": {"head": [COUNTER]},
    }


PLANS = {"earnings_result": plan_earnings, "form4_buy": plan_form4}


RESOLVES = {"earnings_eps": "EPS", "form4_buy": "bought"}     # what the hook's bare figure is, said in the payoff


def plan_for(item: dict) -> dict:
    fn = PLANS.get(item.get("type"))
    if not fn:
        raise TemplateError(f"no one-idea template for {item.get('type')!r} (templates: {', '.join(PLANS)})")
    plan = fn(item)
    # the hook says the figure without saying what it is ("CEG beat by $1.17!"): the payoff lines must name it and repeat it
    pay = plan["fact"]["a"] + " " + plan["fact"]["b"]
    if plan["figure"] not in pay or RESOLVES[plan["kind"]] not in pay:
        raise TemplateError(f"the payoff {pay!r} does not resolve the hook's {plan['figure']} ({RESOLVES[plan['kind']]})")
    return plan


# ------------------------------------------------------------------------------------------------- captures
def run_captures(plan: dict, screens: Path, shot_python: str) -> None:
    for c in plan["captures"]:
        cmd = [shot_python, "-I", str(HERE / "capture.py"), "--url", plan["url"], "--out", str(screens), "--name", c["name"],
               "--clip-pad", str(c["pad"])]
        if c.get("clip_el"):                         # an element's own box (a chart), not a full-width band
            cmd += ["--clip-el", c["clip_el"]]
        else:
            cmd += ["--clip-from", c["clip_from"], "--clip-to", c["clip_to"]]
        if c.get("end_above"):
            cmd += ["--clip-end-above", c["end_above"]]
        if c.get("dpr"):
            cmd += ["--dpr", str(c["dpr"])]
        if c.get("viewport") or plan.get("viewport"):
            cmd += ["--viewport", str(c.get("viewport") or plan["viewport"])]
        for t in c["targets"]:
            cmd += ["--target", t]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise TemplateError(f"capture {c['name']} failed: {(r.stderr or r.stdout).strip()[-400:]}")


def _lone_digit(line: str) -> bool:
    return bool(re.fullmatch(r"\d", line))


def counter_lines(lines: list[str]) -> set[int]:
    """Indexes of the lines that are the guest counter itself: "0/2" alone on its line, or the three nodes "0", "/", "2"
    (a lone "/" between two lone digits). Nothing else: a number on a line near the counter is not the counter."""
    out = set()
    for i, ln in enumerate(lines):
        if re.fullmatch(r"\d+/\d+", ln):
            out.add(i)
        elif ln == "/" and 0 < i < len(lines) - 1 and _lone_digit(lines[i - 1]) and _lone_digit(lines[i + 1]):
            out |= {i - 1, i + 1}
    return out


def acks_for(plan: dict, item: dict, name: str, meta: dict) -> dict[str, str]:
    """Acknowledge only the known page part (the guest counter's own digits); any other number that is not the item's stops
    the template. A number is acknowledged only when EVERY line it appears on is the counter: a "2" in "2 releases" would
    otherwise ride on the counter's reason (the screen gate checks numbers by value, not by place)."""
    ok, det = Q.screen_numbers_gate(meta.get("visible_text", ""), item, {})
    if ok:
        return {}
    lines = [ln.strip() for ln in meta.get("visible_text", "").splitlines()]
    counters = counter_lines(lines) if COUNTER in plan.get("ack", {}).get(name, []) else set()
    out, left = {}, []
    for n in det["unexplained"]:
        where = [i for i, ln in enumerate(lines) if n in Q.find_numbers(ln)]
        if where and all(i in counters for i in where):
            out[n] = ACK_REASONS[COUNTER]
        else:
            left.append(f"{n} (in {', '.join(repr(lines[i]) for i in where) or 'the text'})")
    if left:
        raise TemplateError(f"screen {name}: numbers that are not the item's: {', '.join(left)}; crop them out")
    return out


# ------------------------------------------------------------------------------------------------- the story
def _box(meta: dict, text: str) -> list[float]:
    tg = next((x for x in meta.get("targets", []) if x.get("text") == text), None)
    if tg is None:
        raise TemplateError(f"capture has no target {text!r}")
    return tg["box"]


KEY_PAD = (0.4, 0.35, 0.4, 0.35)             # left, top, right, bottom, in heights of the key text


def crop_around(meta: dict, size, key: str, targets=None, pad=None) -> list[int]:
    """A crop of a capture: the box of the target `key` (or the union of `targets`) plus `pad` (left, top, right, bottom,
    in heights of `key`'s text)."""
    _bx, _by, _bw, bh = _box(meta, key)
    boxes = [_box(meta, t) for t in targets or [key]]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
    pl, pt, pr, pb = pad or KEY_PAD
    return [max(0, int(x0 - pl * bh)), max(0, int(y0 - pt * bh)), min(size[0], int(x1 + pr * bh)),
            min(size[1], int(y1 + pb * bh))]


def key_crop(plan: dict, meta: dict, size) -> list[int]:
    """The key card's crop of the key capture: the key text's box (or the union of plan["key_crop"], several targets, e.g.
    a ticker and its company name) plus plan["key_pad"] (left, top, right, bottom, in heights of the key text). The default
    is tight: a tag's brush edge runs ~0.3 bh past its text box; wider, a neighbour's glyphs creep in ("Officer", the
    bottom of the dates line above the amount on a Form 4 page). A pill with an icon needs more on its left."""
    return crop_around(meta, size, plan["key"], plan.get("key_crop"), plan.get("key_pad"))


def head_fact_layout(screens: dict[str, dict]) -> tuple[dict, tuple]:
    """Shot 4: the header card above the fact card, centred in the stage at a common width that still fits at the largest
    scale of the slow push. -> ({"w", "y_head", "y_fact", "focus4"}, (w, the fact card's centre y, its height))."""
    hw, hh = screens["head"]["size"]
    fw, fh = screens["fact"]["size"]
    stage_h = STAGE_BOTTOM - STAGE_TOP
    mid = (STAGE_TOP + STAGE_BOTTOM) / 2
    w = CARD_W
    ratio = hh / hw + fh / fw
    if (ratio * w + CARD_GAP + 40) * PUSH_S > stage_h:
        w = int((stage_h / PUSH_S - CARD_GAP - 40) / ratio)          # floor: the stack never grows past the stage
    h_head, h_fact = hh * w / hw + 20, fh * w / fw + 20                 # + the card frame (10 px a side)
    top = mid - (h_head + CARD_GAP + h_fact) / 2
    y_head, y_fact = top + h_head / 2, top + h_head + CARD_GAP + h_fact / 2
    return {"w": w, "y_head": round(y_head), "y_fact": round(y_fact), "focus4": [540, round(mid)]}, (w, y_fact, h_fact)


def payoff_layout(plan: dict, screens: dict[str, dict]) -> dict:
    """World positions (= frame px at camera scale 1) of the payoff cards and the two camera moves, so that every card that
    stays on screen keeps inside the stage (below the brand pill, above the caption band):
      shot 4  header + fact card, centred in the stage, a slow push about their centre (largest scale PUSH_S fits);
      shot 5  the header flies off, the key card (earnings: the page's own tag) lands under the fact card, and the camera
              zooms so fact card + key card fill the stage with the key figure big."""
    out, (w, y_fact, h_fact) = head_fact_layout(screens)
    stage_h = STAGE_BOTTOM - STAGE_TOP
    mid = (STAGE_TOP + STAGE_BOTTOM) / 2
    fact_top = y_fact - h_fact / 2
    kw_, kh_ = screens["key"]["size"]                                  # the key figure's own capture, cropped around it
    bx, by, bw, bh = _box(screens["key"]["meta"], plan["key"])
    crop = key_crop(plan, screens["key"]["meta"], (kw_, kh_))
    key_w = int(plan.get("key_w", KEY_W))
    sc = key_w / (crop[2] - crop[0])
    h_key = (crop[3] - crop[1]) * sc + 20
    y_key = y_fact + h_fact / 2 + CARD_GAP + h_key / 2
    kx = 540 - key_w / 2 + (bx + bw / 2 - crop[0]) * sc
    ky = y_key - h_key / 2 + 10 + (by + bh / 2 - crop[1]) * sc
    bottom5 = y_key + h_key / 2
    out.update(key_crop=crop, y_key=round(y_key))
    widest = max(w, key_w)
    also = plan.get("key_also")                 # a second plain crop of the key capture, landing under the key card
    if also:
        crop2 = crop_around(screens["key"]["meta"], (kw_, kh_), also["target"], None, also.get("pad"))
        w2 = int(also.get("w", KEY_W))
        h2 = (crop2[3] - crop2[1]) * w2 / (crop2[2] - crop2[0]) + 20
        y2 = bottom5 + ALSO_GAP + h2 / 2
        bottom5 = y2 + h2 / 2
        widest = max(widest, w2)
        out.update(also_crop=crop2, y_also=round(y2), also_w=w2)
    z5 = min(Z5_MAX, stage_h / ((bottom5 - fact_top) * (1 + 4 * Z5_DRIFT)),
             (1080 - 2 * 40) / ((widest + 20) * (1 + 4 * Z5_DRIFT)))  # the widest card stays whole across the frame
    c5 = (fact_top + bottom5) / 2
    out.update(z5=round(z5, 3), land5=[round(540 + (kx - 540) * z5), round(mid + (ky - c5) * z5)])
    return out


def head_fact_els(L: dict) -> tuple[dict, dict]:
    """The header card and the fact card as they stand in shot 4."""
    w = L["w"]
    return ({"t": "card", "name": "head", "x": 540, "y": L["y_head"], "w": w, "rot": -1.5, "main": False},
            {"t": "card", "name": "fact", "x": 540, "y": L["y_fact"], "w": w, "rot": 1.0, "main": False})


def payoff_els(plan: dict, L: dict) -> tuple[list, list, dict]:
    """(shot 4 elements, shot 5 elements, shot 5 camera move) of the stacked payoff laid out by payoff_layout."""
    head_el, fact_el = head_fact_els(L)
    pay4 = [dict(head_el, enter={"from": [-1200, 0], "dur": 0.3}), dict(fact_el, enter={"from": [0, 1100], "dur": 0.34})]
    pay5 = [dict(head_el, exit={"to": plan.get("head_exit") or [0, -1400], "at": 0.0, "dur": 0.3}), fact_el,
            {"t": "card", "name": "key", "x": 540, "y": L["y_key"], "w": int(plan.get("key_w", KEY_W)), "rot": -2.0,
             "main": True, "crop": L["key_crop"], "enter": {"from": plan.get("key_from") or [0, 1000], "dur": 0.32}}]
    if plan.get("key_also"):                    # lands on the word that names it (the hook's number, big, on our page)
        pay5.append({"t": "card", "name": "key", "x": 540, "y": L["y_also"], "w": L["also_w"], "rot": 1.5, "main": False,
                     "crop": L["also_crop"], "enter": {"from": [0, 1000], "dur": 0.3, "at": plan["key_also"]["at"]}})
    pay5.append({"t": "highlight", "target": plan["key"], "at": 0.5,
                 **({"width": int(plan["key_outline"])} if plan.get("key_outline") else {})})
    move5 = {"type": "zoom_to", "target": plan["key"], "z": L["z5"], "from_prev": True, "at": 0.0, "dur": 0.5,
             "land": L["land5"], "drift": Z5_DRIFT}
    if plan.get("key_whole"):                   # a table row: the cards stay whole across the frame, the camera does not
        move5["min_px"] = False                 # zoom in until the figure is 64 px (that cut the row off both edges)
    return pay4, pay5, move5


def story_shots(plan: dict, L: dict, pay: tuple | None = None) -> tuple[list, list]:
    """(the 7 shots, the voice lines) of the one-idea pattern: hook, confused, the branded phone, our real page (two payoff
    shots), one word, the end card. `pay` = (shot 4 elements, shot 5 elements, shot 5 camera move); the default is the
    stacked payoff. Plan keys beyond the templates' own: "search" (what the phone types; default the ticker),
    "search_rate", "search_dur", "claim_a" / "claim_b" (default the fact's id), "hold4" / "hold5" (a still beat after the
    line), "lead5" (shot 5 starts this long before its line: the key lands, then it is named; needs "join" False), "key_from" (where
    the key card flies in from; a large key comes in from the side, off the caption band), "join" (False: shots 4 and 5 are
    two utterances, so shot 4 can hold on the page before the key lands), "phone" ("tap": the phone shows a link with the
    text `search` and a thumb taps it at "tap_at"; default "type": the text is typed into the search field), "head_exit"
    (where the header card flies off to in shot 5; default up), "key_also" ({"target", "at": "word:<w>", "w", "pad"}: a
    second crop of the key capture that lands under the key card on that word), "key_outline" (the outline's width, px),
    "key_whole" (the key is a row or a chart: no zoom past the layout's own scale)."""
    t = plan.get("ticker") or ""
    pay4, pay5, move5 = pay or payoff_els(plan, L)
    fig = plan["figure"]
    hook_vo = plan["hook"]["vo"]
    dale_y, dale_f = char_frame("dale", "idle", ("shaker",), 280, 0.03, 2.8, 430)
    pip_y, pip_f = char_frame("pip", "phone_hold", ("phone",), 400, 0.04, 2.6)
    cb_y, cb_f = char_frame("pip", "phone_hold", ("phone",), 400, 0.06, 1.6)
    fig_word = next((x for x in hook_vo.split() if fig in x), None)
    if fig_word is None:
        raise TemplateError(f"the hook {hook_vo!r} does not say its figure {fig!r}")
    lines = [hook_vo, plan["confused"]["vo"], plan["fact"]["a"], plan["fact"]["b"], REACTION,
             f"Search {cr.BRAND}. {cr.DISCLAIMER}"]
    pay_a = {"hold": float(plan["hold4"])} if plan.get("hold4") else {}
    pay_b = {"lead": float(plan["lead5"])} if plan.get("lead5") else {}
    phone = {"t": "search_phone", "x": 540, "y": 840, "w": 520, "text": plan.get("search") or t.replace("-", "."),
             "at": 0.2, "rate": float(plan.get("search_rate", 0.11))}
    if plan.get("phone", "type") == "tap":       # a feature page is opened by a tap on its link, not typed into the search
        phone.update(mode="tap", at=float(plan.get("tap_at", 0.6)))
        del phone["rate"]
    shots = [
        {"kind": "HOOK", "set": "gym", "voice": "dale", "claim": plan["hook"]["claim"], "vo": hook_vo, "stress": [fig_word],
         "move": {"type": "push", "amt": 0.03, "focus": dale_f},
         "chip": {"text": fig, "x": 790, "y": 560, "at": f"word:{fig_word.strip('!.,')}", "rot": -4, "size": 82},
         "els": [{"t": "dale", "x": 430, "y": dale_y, "hu": 280, "pose": "idle", "expr": "smug", "brow": True}]},
        {"kind": "CLOSE", "set": "gym", "set_variant": 1, "voice": "pip", "claim": plan["confused"]["claim"],
         "vo": plan["confused"]["vo"], "stress": [f"{cr.BRAND}."], "hold": 0.1,
         "move": {"type": "push", "amt": 0.04, "focus": pip_f},
         "els": [{"t": "pip", "x": 540, "y": pip_y, "hu": 400, "pose": "phone_hold", "expr": "side", "hold": ["phone"],
                  "swap": {"at": "word:Checking", "expr": "deadpan"}}]},
        {"kind": "CLOSE", "set": "gym", "set_variant": 2, "dur": float(plan.get("search_dur", 1.5)),
         "move": {"type": "push", "amt": 0.14, "focus": [540, 600]},
         "els": [phone]},
        {"kind": "PAYOFF", "set": "payoff", "ring_centre": [540, 760], "transition_in": "whip", "voice": "narrator",
         "claim": plan.get("claim_a", plan["fact"]["id"]), "vo": plan["fact"]["a"], **pay_a,
         "move": {"type": "push", "amt": PUSH_AMT, "focus": L["focus4"]},
         "peek": dict(PEEK, at=0.3, **{"from": [-320, 0]}),
         "els": pay4},
        {"kind": "PAYOFF", "set": "payoff", "ring_centre": [540, 760], "voice": "narrator", "join": bool(plan.get("join", True)),
         "claim": plan.get("claim_b", plan["fact"]["id"]), "vo": plan["fact"]["b"], "hold": float(plan.get("hold5", 0.7)),
         "key_number": plan["key"], "move": move5, **pay_b,
         "peek": dict(PEEK, at=0.0, **{"from": [0, 0]}),                    # still wide-eyed: the reaction lands once, on "Oh."
         "els": pay5},
        {"kind": "CALLBACK", "set": "gym", "voice": "pip", "vo": REACTION, "hold": 0.5, "transition_in": "whip",
         "move": {"type": "push", "amt": 0.06, "focus": cb_f},
         "els": [{"t": "pip", "x": 540, "y": cb_y, "hu": 400, "pose": "phone_hold", "expr": "shock", "hold": ["phone"],
                  "swap": {"at": 0.3, "expr": "happy"}}]},   # shock on the cut, happy on "Oh."
        {"kind": "END", "vo": f"Search {cr.BRAND}. {cr.DISCLAIMER}", "vo_at": 0.08, "voice": "end"},
    ]
    return shots, lines


def build_story(item: dict, facts_file: str, post_date: str, plan: dict, screens: dict[str, dict]) -> dict:
    """screens: {"head": {"png": path, "size": [w, h], "meta": sidecar}, "fact": {...}, "key": {...}} -> the story dict."""
    t = plan["ticker"]
    shots, lines = story_shots(plan, payoff_layout(plan, screens))
    hook_vo = plan["hook"]["vo"]
    return {
        "schema": "rtv-cartoon-story/1",
        "template": {"name": TEMPLATE, "plan": plan["kind"], "made_by": "make_story.py"},
        "item_id": item["item_id"], "facts_file": facts_file, "fact_phrase": plan["fact"]["text"],
        "phrase_id": plan["fact"]["id"], "post_date": post_date, "voices": VOICES,
        "say": say_map(lines, t, (plan["fact"]["a"], plan["fact"]["b"]) + ((hook_vo,) if plan.get("bare_hook") else ())),
        "screens": {n: str(v["png"]) for n, v in screens.items()},
        "screen_numbers_ack": {n: acks_for(plan, item, n, v["meta"]) for n, v in screens.items()},
        "shots": shots,
    }


def load_screens(run: Path, plan: dict) -> dict[str, dict]:
    out = {}
    for c in plan["captures"]:
        n = c["name"]
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
                            load_screens(run, plan))
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
