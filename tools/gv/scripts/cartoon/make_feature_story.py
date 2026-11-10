"""FEATURE mode for the cartoon Reel: one feature of the site -> story.json in the one-idea format, filled from a capture
made now. No facts item and no hand-written creative: the registry (features.json) holds the page, the card to capture,
how each value is read from the capture's text, and the story lines with {slots} for those values.

    make_feature_story.py FEATURE_ID --run DIR [--capture] [--shot-python PY] [--list]

Owner request 2026-11-10: "create one for features like smart money, concentration visuals, portfolio visuals and such".
Owner verdict on the first four, the same day: "they arent good, only the last one show the visuals correctly as it shown
on website". Three of them had cut the real page into fragment cards (a thin headline strip, one table row, the donut
lifted out of its card, values captured again at 6x). So the payoff is now the SITE SCREEN:
  - the site's real card WHOLE, at phone width, exactly as the website draws it (title, headline and chart together,
    pixels untouched), in one window that takes the frame's width under the brand pill: the card is 940-1010 px wide;
  - a card taller than the stage is SCROLLED like a thumb over the one capture (never faster than 900 px/s, never a
    jump); nothing is cut out of it;
  - the page STANDS only where the window's edges cut no row of it (no line of text, bar, logo or chart sliced or
    sitting on the edge): the window's height and the scroll's stops are solved from the capture's row boxes;
  - the key value is outlined IN PLACE on that screen, in a frame that also holds a chart whole;
  - the captions sit in a band below the window and Pip's head is small, beside them: nothing covers the screen;
  - the screen is chosen by its visual (the card with the chart), not by a text row.
The pattern and every other owner rule are the daily short's (make_story.py):
  1 HOOK      Dale says something confident, with a number that is on our page today     "Congress made 76 buys!"
  2 CLOSE     Pip does not get it and says where he looks                               "And sells? Checking RapidTradeView."
  3 CLOSE     the phone close: our name and mark, a thumb taps the page's real link       (no voice, one tap)
  4 PAYOFF    the site screen: the card from its top; then a thumb scroll to its end     the page's own words
  5 PAYOFF    the same screen, on the key, which is outlined where it stands             the page's own words
  6 CALLBACK  one word                                                                    "Oh."
  7 END       "Search RapidTradeView. Not investment advice."

With --capture the page is captured now, as a logged-out guest (capture.py in the shot venv, strip mode): once to read the
values (cartoon_qa.feature_values: never typed by hand), then again with the boxes and targets that carry a value. It
stops with exit 2, and writes no story, when
  - the card, one of its parts or a value is missing (the page changed, or today's data does not carry the story),
  - the page is in an error or loading state, or says one of the feature's refuse_if texts,
  - a provider or source brand is on what the strip shows,
  - the capture is not from today, not from the feature's page, or not the page at phone width,
  - a picture of the card did not load (an empty logo slot), or the card has no drawn chart,
  - the card would be narrower than 900 px on screen, the key would not fit the window, or no window height lets the
    page stand without cutting a row,
  - the filled lines would not pass the number and claim gates against the capture.
Then render:  cartoon_reel.py --story DIR/story.json --out DIR   (it builds the item from the sidecar again, gates the
story against the registry and rebuilds it with story_drift: a story edited by hand, its say map included, fails
feature_story; site_card_whole, card_width, edge_clear, thumb_scroll, no_overlap and key_in_place gate the rendered
frames).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_story as M  # noqa: E402

Q = M.Q
cr = Q.cr
TEMPLATE = "rtv-cartoon-feature/2"
PAGE = Q.PAGE
# The site screen's place in the 1080 x 1920 frame. The brand pill ends at y 333; the window starts under it and may run
# down to y 1457; the caption band sits right under the window and ends above the platforms' bottom 18% (y 1574).
STAGE_TOP, STAGE_BOTTOM = int(Q.SITE_STAGE[0]), int(Q.SITE_STAGE[1])
WIN_W = 1040                         # the window: the page at its full phone width, 20 px from each edge of the frame
CARD_FIT_MIN_W = Q.SITE_CARD_TARGET_W[0]   # a strip that fits the stage whole with its card this wide (940) is shown
                                     # whole, a little smaller than 1040, without a scroll; below it, it scrolls
RIM = 5                              # the window's rim (cartoon_reel.SITE_RIM)
# the caption band under the window, right of Pip's head: (caption size, the band's height with the plate at its pop)
CAP_SIZES = ((72, 118), (64, 110), (60, 104))
CAP_GAP = 6                          # px between the window's rim and the caption band
CAPTION = {"x": 566, "max_w": 700, "plate": [36, 8], "pop": False, "tint": "trade"}
PEEK = {"who": "pip", "expr": "shock", "x": 88, "hu": 88, "rot": 10}    # small, beside the captions
ENTER = {"from": [1300, 0], "dur": 0.32}  # the window comes in from the right: it crosses neither the pill nor the captions
TOP_HOLD = 1.1                       # the window stands on the strip's top first (site.top_hold)
SCROLL_PX_S = 700.0                  # the thumb scroll's top speed, frame px per second (site.px_s; the gate allows 900)
CRUISE = 0.85                        # cartoon_reel.cruise: the average speed is this share of the top speed
SCROLL_MIN_S = 0.45                  # a scroll is never shorter than this
REST = 0.35                          # the page rests after a scroll before the shot ends
END_HOLD, END_READ = 1.1, 1.5        # the page stands on the end of the scroll (site.end_hold): in shot 4, or (read_end)
                                     # in shot 5 while its line is read
KEY_HOLD = 1.65                      # the outlined key stands at least this long (the gate asks for 1.5 s)
LEAD5, HOLD5, HOLD4 = 0.35, 0.9, 0.3  # shot 5: the outline lands, then the voice names it; still beats
OUTLINE, OUTLINE_PAD = 8, [12, 6]    # the outline around the key (px)
KEY_MARGIN_CSS, KEY_MAX_H_CSS = 8, 72     # the key keeps this far inside the window; a key is a line or a two-line headline
SOLVE_SPAN, SOLVE_STEP = 240, 3      # the window may be up to this much shorter than the stage to stand on clean edges


def has_slots(o) -> bool:
    return bool(Q._slots(json.dumps(o)))


def site_targets(feature: dict, values: dict) -> list[str]:
    """The texts whose DOM boxes the capture records: the key's targets, the first outline's (key.first), and our header's
    brand when the strip starts at the page header."""
    key = feature["key"]
    out = [Q.fill(t, values) for t in key["targets"]]
    out += [Q.fill(t, values) for t in (key.get("first") or {}).get("targets", [])]
    if feature["site"].get("header"):
        out.append(cr.BRAND)
    return list(dict.fromkeys(out))


def capture_args(feature: dict, values: dict | None) -> list[str]:
    """capture.py's arguments for the feature's strip. values None = the first pass (the strip and the card's box only:
    the page text is all it is for); with the values, also the parts and the targets, slots filled."""
    site = feature["site"]
    strip = site["strip"]
    pad = strip.get("pad", 6)
    pad = list(pad) if isinstance(pad, list) else [pad]
    args = ["--url", feature["url"], "--viewport", str(feature["viewport"]), "--dpr", str(int(site.get("dpr", Q.SITE_MIN_DPR))),
            "--strip-top", strip["top"], "--strip-bottom", strip["bottom"], "--strip-pad", str(pad[0])]
    if len(pad) > 1:
        args += ["--strip-pad-bottom", str(pad[1])]
    for sp in site["card"]["box"]:
        args += ["--box", f"card={sp}"]
    if site["card"].get("bottom"):
        args += ["--box-bottom", f"card={site['card']['bottom']}"]
    if values is not None:
        for name, specs in site["parts"].items():
            for sp in specs:
                args += ["--box", f"{name}={Q.fill(sp, values)}"]
        for t in site_targets(feature, values):
            args += ["--target", t]
    return args


def plan_for(feature: dict, values: dict) -> dict:
    """The registry entry + today's values -> the plan make_story.story_shots takes (the two payoff shots are replaced by
    the site screen in build_story)."""
    ln = Q.feature_lines(feature, values)
    claims = feature.get("claims") or {}
    return {
        "kind": f"feature:{feature['id']}", "ticker": values.get(feature.get("ticker") or "") or "",
        "figure": ln["hook_figure"], "key": ln["key"], "first": ln.get("first"), "first_word": ln.get("first_word"),
        "hook": {"vo": ln["hook"], "claim": claims.get("hook")},
        "confused": {"vo": ln["confused"], "claim": claims.get("confused")},
        "fact": {"text": ln["fact_phrase"], "id": claims.get("fact_a"), "a": ln["fact_a"], "b": ln["fact_b"]},
        "claim_a": claims.get("fact_a"), "claim_b": claims.get("fact_b"), "search": ln["search"],
        "search_rate": feature.get("search_rate", 0.11), "search_dur": feature.get("search_dur", 1.5),
        "join": False, "hold4": feature.get("hold4", HOLD4), "hold5": feature.get("hold5", HOLD5),
        "phone": feature.get("phone", "type"),
    }


def _union(boxes: list) -> list[float]:
    """[x, y, w, h] boxes -> their union as (x0, y0, x1, y1)."""
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[0] + b[2] for b in boxes),
            max(b[1] + b[3] for b in boxes)]


def _mid_run(ok, best: int, lo: int, step: int) -> int:
    """`best` is the first value (counting down from the top) for which ok() holds: the middle of the unbroken run of
    values below it that also hold, so that an edge stands in the middle of a gap, not on its rim."""
    last = best
    v = best - step
    while v >= lo and ok(v):
        last = v
        v -= step
    return best - ((best - last) // (2 * step)) * step


def site_layout(feature: dict, values: dict, meta: dict) -> dict:
    """Where the window stands and how the strip moves in it. Scroll values are capture px (the strip row at the window's
    top). -> {"w", "h", "x", "y" (the window; its top is the stage's top), "k" (frame px per capture px), "card_w",
    "a" (the first stop: the strip's top), "b" (where the scroll ends), "key" (where the page stands while the key is
    outlined: a or b), "cap_y", "cap_size", "peek_y" (the caption band under the window), and the times of site_shots}.

    A strip that fits the stage is shown whole. A taller one scrolls between two stops, and the page STANDS only where
    the window's top and bottom edges cut no row (Q.window_edge_hits over the capture's rows): the window's height is
    the tallest (down to SOLVE_SPAN px under the stage) for which the first stop, the end stop and the key's stop are all
    clean, every chart of the card is whole at a stop, and a chart is whole where the key is outlined."""
    sw, sh = meta["png_size"]
    dpr = float(meta.get("dpr") or Q.SITE_MIN_DPR)
    boxes = meta.get("boxes") or {}
    card = boxes.get("card")
    if not card:
        raise M.TemplateError("the capture has no card box (capture it with --capture)")
    site = feature["site"]
    stage_h = STAGE_BOTTOM - STAGE_TOP
    w = WIN_W
    fits = sh * w / sw <= stage_h + 1e-6
    if not fits:                                    # taller than the stage: does the whole strip fit a little smaller?
        fit = int(stage_h * sw / sh)
        if card[2] * fit / sw >= CARD_FIT_MIN_W:
            w, fits = fit, True
    k = w / sw
    card_w = card[2] * k
    if card_w < Q.SITE_CARD_MIN_W:
        raise M.TemplateError(f"the card would be {card_w:.0f} px wide on screen (at least {Q.SITE_CARD_MIN_W:.0f}): "
                              "capture the page at phone width")
    ln = Q.feature_lines(feature, values)
    kb = _union([M._box(meta, t) for t in ln["key"]])
    fb = _union([M._box(meta, t) for t in ln["first"]]) if ln.get("first") else None
    for what, b_, floor in (("key", kb, Q.SITE_KEY_MIN_H), ("first outline", fb, Q.SITE_FIRST_MIN_H)):
        if b_ is None:
            continue
        if b_[3] - b_[1] > KEY_MAX_H_CSS * dpr:
            raise M.TemplateError(f"the {what}'s targets span {(b_[3] - b_[1]) / dpr:.0f} CSS px of height: they are not one "
                                  "line or headline (a target matched another place on the page)")
        if (b_[3] - b_[1]) * k < floor:
            raise M.TemplateError(f"the {what} would be {(b_[3] - b_[1]) * k:.0f} px tall on screen (at least {floor:.0f})")
        if not (card[0] - 1 <= b_[0] and b_[2] <= card[0] + card[2] + 1 and card[1] - 1 <= b_[1] and b_[3] <= card[1] + card[3] + 1):
            raise M.TemplateError(f"the {what}'s targets are not on the card")
    m = KEY_MARGIN_CSS * dpr
    charts = [boxes[c] for c in Q.site_charts(site) if c in boxes]
    if not charts:
        raise M.TemplateError("the capture has no chart box: the card is shown for its visual")
    end_show = [boxes[n] for n in site.get("end", []) if n in boxes]

    def inside(s_: float, vis: float, b_, margin: float = 0.0) -> bool:      # b_: (x0, y0, x1, y1)
        return s_ + margin <= b_[1] and b_[3] <= s_ + vis - margin

    def box_in(s_: float, vis: float, b_) -> bool:                           # b_: [x, y, w, h]
        return s_ - 1 <= b_[1] and b_[1] + b_[3] <= s_ + vis + 1

    if fits:
        h = int(min(stage_h, math.ceil(sh * k - 1e-6)))     # a strip that fits is in the window to its last row
        a = b = s_key = 0.0
    else:
        rows = Q.content_rows(meta)
        if not rows:
            raise M.TemplateError("the capture lists no rows of the page (content): capture it again")
        air = Q.SITE_EDGE_AIR / k
        card_end = card[1] + card[3]

        def clean(top: float, vis: float) -> bool:
            return not Q.window_edge_hits(rows, top, top + vis, sh, air)

        def solve(h_: int):
            """(a, b, key stop) for a window h_ px tall, or None."""
            vis = float(min(sh, round(h_ / k)))              # the strip rows the window shows (cartoon_reel.site_geom)
            smax = sh - vis
            if smax < 3 * dpr or not clean(0.0, vis):
                return None
            lo = max(3 * dpr, card_end - vis)                # the end stop reaches the card's last row

            def ok_b(s_: int) -> bool:
                return (clean(float(s_), vis) and all(box_in(s_, vis, e_) for e_ in end_show)
                        and (inside(0.0, vis, kb, m) or inside(s_, vis, kb, m)))

            top = int(smax)
            b_ = next((s_ for s_ in range(top, int(lo) - 1, -1) if ok_b(s_)), None)
            if b_ is None:
                return None
            if b_ != top:
                b_ = _mid_run(ok_b, b_, max(int(lo), b_ - int(4 * air)), 1)
            key_ = 0.0 if inside(0.0, vis, kb, m) else float(b_)
            if not all(box_in(0.0, vis, c_) or box_in(b_, vis, c_) for c_ in charts):
                return None                                  # a chart that is whole at no stop
            if not any(box_in(key_, vis, c_) for c_ in charts):
                return None                                  # the key would be outlined without a chart in the frame
            if fb is not None and not inside(0.0, vis, fb, m):
                return None                                  # the first outline is drawn on the strip's top
            return 0.0, float(b_), key_

        lo_h = stage_h - SOLVE_SPAN
        h = next((h_ for h_ in range(stage_h, lo_h - 1, -SOLVE_STEP) if solve(h_)), None)
        if h is None:
            raise M.TemplateError(
                f"no window from {lo_h} to {stage_h} px tall lets the page stand without cutting a row, with every chart "
                "whole at a stop and a chart beside the outlined key: change the strip (site.strip), or do not make it today")
        h = _mid_run(lambda v: solve(v) is not None, h, max(lo_h, h - 4 * int(Q.SITE_EDGE_AIR)), SOLVE_STEP)
        a, b, s_key = solve(h)
    vis = float(min(sh, round(h / k)))
    if not inside(s_key, vis, kb, m if not fits else 0.0):
        raise M.TemplateError("the key does not fit the window")
    # the caption band: right under the window, as large as the room above the platforms' bottom UI allows
    bottom = STAGE_TOP + h
    room = Q.SITE_CAPTION_BOTTOM - (bottom + RIM + CAP_GAP)
    cap = next(((size, band) for size, band in CAP_SIZES if band <= room), None)
    if cap is None:
        raise M.TemplateError("no room for the caption band under the window")
    cap_y = bottom + RIM + CAP_GAP + cap[1] / 2
    # the times. Shot 4 stands on the strip's top (site.top_hold), scrolls to the end stop and rests there (site.end_hold,
    # or REST when shot 5's line is read over it). Shot 5: (read_end) stands on the end while its line is read, scrolls
    # back and the key is outlined; (key on the strip's top) scrolls back first, the outline lands and the line names
    # it; (key at the end) stays where it is.
    px_s = float(site.get("px_s", SCROLL_PX_S))
    dist = abs(b - a) * k
    dur = 0.0 if dist < 1 else round(max(SCROLL_MIN_S, dist / (px_s * CRUISE)), 2)
    at = float(site.get("top_hold", TOP_HOLD))
    read_end = bool(site.get("read_end")) and dur > 0 and s_key == a
    rest = REST if (read_end or s_key == b or not dur) else float(site.get("end_hold", END_HOLD))
    lead5 = float(feature.get("lead5", LEAD5))
    if not dur or s_key == b:                      # no scroll, or the key is where the scroll ended
        back_at, back, hl_at, lead = 0.0, 0.0, lead5, lead5
    elif read_end:
        back_at = float(site.get("end_hold", END_READ))
        back, hl_at, lead = dur, round(back_at + dur + 0.15, 2), 0.1
    else:
        back_at, back = 0.05, dur
        hl_at = lead = round(max(lead5, back_at + dur + 0.15), 2)
    return {"w": int(w), "h": int(h), "x": 540, "y": STAGE_TOP + h / 2, "k": k,
            "a": round(a, 1), "b": round(b, 1), "key": round(s_key, 1), "card_w": round(card_w, 1), "fits": bool(fits),
            "cap_y": round(cap_y), "cap_size": cap[0], "peek_y": round(cap_y + 6),
            "at": at, "dur": dur, "min4": round(at + dur + rest, 2) if dur else 0.0,
            "back_at": back_at, "back": back, "hl_at": hl_at, "lead": lead,
            "min5": round(hl_at + KEY_HOLD, 2)}


def site_shots(feature: dict, plan: dict, L: dict) -> tuple[dict, dict]:
    """The two payoff shots of the site screen: (what shot 4 gets, what shot 5 gets), merged over make_story's shots."""
    win = {"t": "site", "name": PAGE, "x": L["x"], "y": L["y"], "w": L["w"], "h": L["h"], "main": True}
    still = {"type": "still"}
    pad = list(feature["key"].get("outline_pad", OUTLINE_PAD))
    caption = dict(CAPTION, y=L["cap_y"], size=L["cap_size"])
    peek = dict(PEEK, y=L["peek_y"])
    a_els = [dict(win, scroll={"y0": L["a"], "y1": L["b"], "at": L["at"], "dur": L["dur"]}, enter=dict(ENTER))]
    if plan.get("first"):                           # the first payoff line's own text, outlined when its word is read
        first = {"t": "highlight", "target": plan["first"], "at": f"word:{plan['first_word']}", "width": OUTLINE, "pad": pad}
        if L["dur"]:
            first["until"] = round(L["at"] - 0.05, 2)   # it leaves before the page moves
        a_els.append(first)
    start5 = L["b"]
    b_els = [dict(win, scroll={"y0": start5, "y1": L["key"], "at": L["back_at"], "dur": L["back"]}),
             {"t": "highlight", "target": plan["key"], "at": L["hl_at"], "width": OUTLINE, "pad": pad}]
    a = {"els": a_els, "move": still, "caption": dict(caption), "peek": dict(peek, at=0.35, **{"from": [-260, 0]})}
    if L["min4"]:
        a["min_dur"] = L["min4"]
    b = {"els": b_els, "move": still, "caption": dict(caption), "peek": dict(peek, at=0.0, **{"from": [0, 0]}),
         "key_number": plan["key"], "lead": L["lead"], "min_dur": L["min5"]}
    return a, b


def build_story(feature: dict, values: dict, screens: dict, day: str) -> dict:
    """screens: {"page": {"png": path, "size": [w, h], "meta": sidecar}} -> the story."""
    plan = plan_for(feature, values)
    L = site_layout(feature, values, screens[PAGE]["meta"])
    shots, lines = M.story_shots(plan, {"focus4": [540, 868]}, ([], [], {"type": "still"}))
    a, b = site_shots(feature, plan, L)
    for sh, new in ((shots[3], a), (shots[4], b)):
        sh.pop("ring_centre", None)
        sh.update(new, ring_centre=[540, 868])
    for sh in shots[:-1]:                           # every caption draws a figure in the colour the card gives its side
        sh.setdefault("caption", {})["tint"] = CAPTION["tint"]
    story = {
        "schema": "rtv-cartoon-story/1",
        "template": {"name": TEMPLATE, "plan": plan["kind"], "made_by": "make_feature_story.py"},
        "feature": {"id": feature["id"], "url": feature["url"], "answers": feature.get("answers"), "values": values},
        "item_id": f"{day}-feature-{feature['id']}", "fact_phrase": plan["fact"]["text"], "post_date": day,
        "voices": M.VOICES, "say": Q.feature_say(feature, values),
        "screens": {n: str(v["png"]) for n, v in screens.items()},
        "screen_numbers_ack": {},
        "shots": shots,
    }
    return story


DRIFT_KEYS = ("schema", "template", "feature", "item_id", "fact_phrase", "post_date", "voices", "say", "screen_numbers_ack",
              "shots")


def _plain(o):
    """JSON-shaped, without the keys the renderer adds while it runs ("_img", "_t0", ...)."""
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    return o if isinstance(o, (str, int, float, bool)) or o is None else str(o)


def story_drift(doc: dict, feature: dict, metas: dict) -> list[str]:
    """How a story differs from the one this script writes from the same registry entry and the same sidecar (empty =
    it is that story). The renderer runs it inside feature_story: a line, a say entry, the window, a scroll, an outline,
    a voice or a timing edited by hand is named here. The screen's path is not compared (a run folder can move)."""
    try:
        values = Q.feature_values(feature, metas)
        screens = {n: {"png": f"screens/{n}.png", "size": m["png_size"], "meta": m} for n, m in metas.items()}
        want = build_story(feature, values, screens, Q.capture_day(metas))
    except (Q.FeatureError, M.TemplateError, KeyError) as e:
        return [f"the story cannot be rebuilt from the capture: {e}"]
    got, want = _plain(json.loads(json.dumps(_plain(doc)))), _plain(json.loads(json.dumps(want)))
    out = []
    for k in sorted(set(got) | set(DRIFT_KEYS)):
        if k == "screens":
            if set(got.get(k) or {}) != set(metas):
                out.append(f"screens {sorted(got.get(k) or {})} are not the captures {sorted(metas)}")
        elif k not in DRIFT_KEYS:
            out.append(f"the story has a key the generator does not write: {k}")
        elif k == "shots":
            a, b = got.get(k) or [], want[k]
            if len(a) != len(b):
                out.append(f"{len(a)} shots, the generator writes {len(b)}")
            for i, (x, y) in enumerate(zip(a, b)):
                keys = sorted(kk for kk in set(x) | set(y) if x.get(kk) != y.get(kk))
                if keys:
                    out.append(f"shot {i + 1} differs from the generator's in {keys}")
        elif got.get(k) != want[k]:
            out.append(f"{k} differs from the generator's")
    return out


def check_story(story: dict, feature: dict, metas: dict, now: dt.datetime) -> list[str]:
    """What would fail at render time and can be known now: the capture (page, day, state, providers, a whole strip),
    the story against the registry, and the lines against the capture (numbers, claims, banned words, the fact phrase)."""
    probs = []
    ok, det = Q.feature_capture_gate(feature, metas, now)
    if not ok:
        probs += [f"capture {n}: {'; '.join(w)}" for n, w in det["problems"].items()]
    ok, det = Q.feature_story_gate(story, feature, metas)
    if not ok:
        probs += det["problems"]
    probs += story_drift(story, feature, metas)
    item = Q.feature_item(feature, story["feature"]["values"], metas, story["item_id"])
    shots = story["shots"]
    vo = {f"shot {i + 1}": sh["vo"] for i, sh in enumerate(shots) if sh.get("vo")}
    drawn = {f"chip {i + 1}": sh["chip"]["text"] for i, sh in enumerate(shots) if sh.get("chip")}
    ok, det = Q.numbers_gate({**vo, **drawn}, Q.allowed_set(item))
    if not ok:
        probs.append(f"numbers that are not on a capture, or spelled out: {det['not_in_item']} {det['number_words']}")
    ok, det = Q.claim_lines_gate([{"line": sh["vo"], "claim": sh.get("claim")} for sh in shots[:-1] if sh.get("vo")], item,
                                 story["post_date"])
    if not ok:
        probs += [f"line {b['line']!r}: {b['problem']}" for b in det["bad"]]
    ok, det = Q.spoken_numbers_gate(story["say"])
    if not ok:
        probs.append(f"spoken figures: {det['mismatch']}")
    script = " ".join(sh["vo"] for sh in shots[:-1] if sh.get("vo"))
    ok, det = Q.feature_fact_gate(story["fact_phrase"], metas, script)
    if not ok:
        probs.append(f"the fact phrase {story['fact_phrase']!r} is not on a capture and read aloud: {det}")
    return probs


def load_screens(run: Path, names=(PAGE,)) -> dict:
    out = {}
    for n in names:
        png, side = run / "screens" / f"{n}.png", run / "screens" / f"{n}.json"
        if not png.is_file() or not side.is_file():
            raise M.TemplateError(f"capture {png} is missing (run with --capture)")
        meta = json.loads(side.read_text(encoding="utf-8"))
        out[n] = {"png": png, "size": meta["png_size"], "meta": meta}
    return out


def logos_sheet(run: Path, meta: dict) -> Path | None:
    """screens/logos.png: every image the strip shows (the ticker logos), enlarged, each with the row beside it, for the
    human look before the video ships. No check can tell a wrong company's logo from the right one: on 2026-11-10 the
    site drew another firm's mark beside a ticker on two loads out of three. None when the strip has no image."""
    from PIL import Image, ImageDraw
    imgs = [i_ for i_ in meta.get("images") or [] if isinstance(i_, dict) and i_.get("box")]
    if not imgs:
        (run / "screens" / "logos.png").unlink(missing_ok=True)
        return None
    strip = Image.open(run / "screens" / f"{PAGE}.png").convert("RGB")
    z, row_w, pad = 3, 700, 12
    tiles = []
    for i_ in imgs:
        x, y, w_, h_ = i_["box"]
        box = (max(0, int(x - pad)), max(0, int(y - pad)), min(strip.size[0], int(x + row_w)), min(strip.size[1], int(y + h_ + pad)))
        t_ = strip.crop(box)
        tiles.append(t_.resize((t_.size[0] * z // 2, t_.size[1] * z // 2), Image.LANCZOS))
    sheet = Image.new("RGB", (max(t_.size[0] for t_ in tiles) + 2 * pad, sum(t_.size[1] + pad for t_ in tiles) + pad + 40),
                      (16, 16, 20))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 10), f"{len(tiles)} images on the strip: is each the logo of the company named beside it?",
           font=cr.font("semi", 22), fill=(170, 240, 200))
    y = 40
    for t_ in tiles:
        sheet.paste(t_, (pad, y))
        y += t_.size[1] + pad
    out = run / "screens" / "logos.png"
    sheet.save(out)
    return out


def run_capture(args: list[str], screens: Path, shot_python: str) -> None:
    cmd = [shot_python, "-I", str(HERE / "capture.py"), "--out", str(screens), "--name", PAGE] + args
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise M.TemplateError(f"capture failed: {(r.stderr or r.stdout).strip()[-400:]}")


RUN_OUTPUTS = ("reel_9x16.mp4", "reel.json", "reel-qa.json", "sheet.png", "compare.png", "mix.wav", "vo.wav", "story.json")


def shelve_previous(run: Path) -> list[str]:
    """Before a new capture replaces the run folder's capture: the video that was made from the old one, its story and
    that capture move to <run>/previous/ (replacing what was there). A run folder never holds a video beside a capture
    it was not made from: on 2026-11-10 a refused capture was left next to an older video. -> the names moved."""
    old = [n for n in RUN_OUTPUTS if (run / n).is_file()]
    if not any(n in old for n in ("reel_9x16.mp4", "reel.json", "reel-qa.json")):
        return []                                    # no render here: nothing a new capture could orphan
    prev = run / "previous"
    (prev / "screens").mkdir(parents=True, exist_ok=True)
    moved = []
    for n in old:
        (run / n).replace(prev / n)
        moved.append(n)
    for f in sorted((run / "screens").glob(f"{PAGE}.*")) + [run / "screens" / "logos.png"]:
        if f.is_file():
            f.replace(prev / "screens" / f.name)
            moved.append(f"screens/{f.name}")
    return moved


def capture_feature(feature: dict, run: Path, shot_python: str, now: dt.datetime) -> None:
    """Capture the strip (the page text is read from it), read the values, then capture it again with the parts and the
    targets that carry a value. A registry entry without a slot in its boxes and targets needs one pass."""
    screens = run / "screens"
    for ext in (".png", ".json"):
        (screens / f"{PAGE}{ext}").unlink(missing_ok=True)
    two = has_slots(feature["site"]) or has_slots(feature["key"])
    run_capture(capture_args(feature, None if two else {}), screens, shot_python)
    if not two:
        return
    meta = load_screens(run)[PAGE]["meta"]
    values = Q.feature_values(feature, {PAGE: meta})
    run_capture(capture_args(feature, values), screens, shot_python)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("feature", nargs="?", help="a feature id of features.json")
    ap.add_argument("--run", help="the render folder: screens/ and story.json go here")
    ap.add_argument("--capture", action="store_true", help="capture the real page now (shot venv)")
    ap.add_argument("--shot-python", help="the Playwright venv python (default: <media>/.ops/cache/shot-venv)")
    ap.add_argument("--registry", help="another features.json (tests)")
    ap.add_argument("--list", action="store_true", help="list the registry's features and exit")
    a = ap.parse_args(argv)
    run = None
    try:
        reg = Q.load_features(a.registry)
        if a.list:
            for f in reg["features"]:
                print(f"{f['id']}\t{f['url']}\t{f.get('answers', '')}")
            return 0
        if not a.feature or not a.run:
            raise Q.FeatureError("give a feature id and --run DIR (or --list)")
        feature = Q.feature_by_id(reg, a.feature)
        run = Path(a.run).resolve()
        run.mkdir(parents=True, exist_ok=True)
        if a.capture or not (run / "reel_9x16.mp4").is_file():
            (run / "story.json").unlink(missing_ok=True)     # (a folder that holds a render keeps its story until a new
                                                             # capture shelves both, or a new story replaces it)
        now = dt.datetime.now(dt.timezone.utc)
        if a.capture:
            shot_py = a.shot_python
            if not shot_py:
                ops = next((p / ".ops" for p in HERE.parents if (p / ".ops" / "cache" / "shot-venv").is_dir()), None)
                if not ops:
                    raise M.TemplateError("no .ops/cache/shot-venv above this script (pass --shot-python)")
                shot_py = str(ops / "cache" / "shot-venv" / "Scripts" / "python.exe")
            moved = shelve_previous(run)
            if moved:
                print(f"make_feature_story: the previous render moved to {run / 'previous'} ({len(moved)} files)", file=sys.stderr)
            capture_feature(feature, run, shot_py, now)
            now = dt.datetime.now(dt.timezone.utc)
        screens = load_screens(run)
        metas = {n: v["meta"] for n, v in screens.items()}
        values = Q.feature_values(feature, metas)
        logos = logos_sheet(run, metas[PAGE])       # written before any refusal: a refused capture is looked at too
        ok_c, det_c = Q.feature_capture_gate(feature, metas, now)
        if not ok_c:                                # the capture first: a layout cannot be solved on a page that is not it
            raise Q.FeatureError("; ".join(f"capture {n}: {'; '.join(w)}" for n, w in det_c["problems"].items()))
        story = build_story(feature, values, screens, Q.capture_day(metas))
        probs = check_story(story, feature, metas, now)
        if probs:
            raise Q.FeatureError("; ".join(probs))
        for s_ in story["screens"]:
            story["screens"][s_] = str(Path(story["screens"][s_]).relative_to(run)).replace("\\", "/")
    except (Q.FeatureError, M.TemplateError) as e:
        print(f"make_feature_story: {e}", file=sys.stderr)
        # a day without a story leaves a record that says why. A folder that still holds a render (no new capture was
        # asked for) is left as it is: its video, story and QA record belong together
        if run is not None and run.is_dir() and not (run / "reel_9x16.mp4").is_file():
            (run / "reel-qa.json").write_text(json.dumps({
                "schema": "rtv-cartoon-reel-qa/1", "renderer": "make_feature_story.py", "item_id": None, "pass": False,
                "feature": a.feature, "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "summary": {"story": False}, "details": {"story": f"no story today, nothing rendered: {e}"}}, indent=1) + "\n",
                encoding="utf-8")
        return 2
    out = run / "story.json"
    out.write_text(json.dumps(story, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"story": str(out), "feature": feature["id"], "values": values, "fact_phrase": story["fact_phrase"],
                      "lines": [s_.get("vo") for s_ in story["shots"] if s_.get("vo")],
                      "logos_to_look_at": str(logos) if logos else None, "hold": feature.get("hold")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
