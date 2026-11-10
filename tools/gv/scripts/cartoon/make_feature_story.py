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
  - a card taller than the stage is SCROLLED like a thumb over the one capture; nothing is cut out of it;
  - the key value is outlined IN PLACE on that screen;
  - the captions sit in a band below the window and Pip's head is small, beside them: nothing covers the screen;
  - the screen is chosen by its visual (the card with the chart), not by a text row.
The pattern and every other owner rule are the daily short's (make_story.py):
  1 HOOK      Dale says something confident, with a number that is on our page today     "Congress made 76 buys!"
  2 CLOSE     Pip does not get it and says where he looks                               "And sells? Checking RapidTradeView."
  3 CLOSE     the phone close: our name and mark, a thumb taps the page's real link       (no voice, one tap)
  4 PAYOFF    the site screen: the card from its top; then a thumb scroll to its end     the page's own words
  5 PAYOFF    the same screen, back on the key, which is outlined where it stands        the page's own words
  6 CALLBACK  one word                                                                    "Oh."
  7 END       "Search RapidTradeView. Not investment advice."

With --capture the page is captured now, as a logged-out guest (capture.py in the shot venv, strip mode): once to read the
values (cartoon_qa.feature_values: never typed by hand), then again with the boxes and targets that carry a value. It
stops with exit 2, and writes no story, when
  - the card, one of its parts or a value is missing (the page changed, or today's data does not carry the story),
  - the page is in an error or loading state, or says one of the feature's refuse_if texts,
  - a provider or source brand is on what the strip shows,
  - the capture is not from today, not from the feature's page, or not the page at phone width,
  - the card would be narrower than 900 px on screen, or the key would not fit the window,
  - the filled lines would not pass the number and claim gates against the capture.
Then render:  cartoon_reel.py --story DIR/story.json --out DIR   (it builds the item from the sidecar again, gates the
story against the registry and rebuilds it with story_drift: a story edited by hand, its say map included, fails
feature_story; site_card_whole, card_width, no_overlap and key_in_place gate the rendered frames).
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
# The site screen's place in the 1080 x 1920 frame. The brand pill ends at y 333 and the platform's bottom UI starts at
# y 1520 (card_reel.SAFE_BOTTOM): the window stands between them and leaves a band for the captions.
STAGE_TOP, STAGE_BOTTOM = 342, 1380
WIN_W = 1040                         # the window: the page at its full phone width, 20 px from each edge of the frame
CARD_FIT_MIN_W = 900                 # a card that fits the stage whole at this width or more is shown whole, without a
                                     # scroll (the whole card in one frame is what the owner liked; below it, it scrolls)
CAPTION = {"x": 600, "y": 1458, "max_w": 640, "size": 80, "plate": [44, 18]}    # the caption band: under the window, right of Pip
PEEK = {"who": "pip", "expr": "shock", "x": 96, "y": 1476, "hu": 126, "rot": 10}    # small, beside the captions
ENTER = {"from": [1300, 0], "dur": 0.32}  # the window comes in from the right: it crosses neither the pill nor the captions
TOP_HOLD, TOP_HOLD_HEADER = 0.9, 1.4      # the window stands on the strip's top first (longer when our header is on it)
SCROLL_PX_S = 900.0                  # the thumb scroll's speed, frame px per second ...
SCROLL_MIN_S, REST = 0.5, 0.3        # ... never shorter than this; and the page rests after it
SHOT4_MAX = 4.9                      # shot 4 at its longest (cartoon_reel.PAYOFF_MAX_SITE is 5.0)
BACK_PX_S, BACK_MIN_S, BACK_MAX_S = 2400.0, 0.3, 0.5      # the scroll back to the key, at the head of shot 5
LEAD5, HOLD5, HOLD4 = 0.6, 0.9, 0.3  # shot 5: the page settles on the key, then the voice names it; still beats
OUTLINE, OUTLINE_PAD = 8, [12, 6]    # the outline around the key (px)
KEY_MARGIN_CSS, KEY_MAX_H_CSS = 8, 72     # the key keeps this far inside the window; a key is a line or a two-line headline


def has_slots(o) -> bool:
    return bool(Q._slots(json.dumps(o)))


def site_targets(feature: dict, values: dict) -> list[str]:
    """The texts whose DOM boxes the capture records: the key's targets, the line the window opens on while the key is
    outlined (key.top), and our header's brand when the strip starts at the page header."""
    key = feature["key"]
    out = [Q.fill(t, values) for t in key["targets"]]
    if key.get("top"):
        out.append(Q.fill(key["top"], values))
    if feature["site"].get("header"):
        out.append(cr.BRAND)
    return list(dict.fromkeys(out))


def capture_args(feature: dict, values: dict | None) -> list[str]:
    """capture.py's arguments for the feature's strip. values None = the first pass (the strip and the card's box only:
    the page text is all it is for); with the values, also the parts and the targets, slots filled."""
    site = feature["site"]
    strip = site["strip"]
    args = ["--url", feature["url"], "--viewport", str(feature["viewport"]), "--dpr", str(int(site.get("dpr", Q.SITE_MIN_DPR))),
            "--strip-top", strip["top"], "--strip-bottom", strip["bottom"], "--strip-pad", str(strip.get("pad", 6))]
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
        "figure": ln["hook_figure"], "key": ln["key"],
        "hook": {"vo": ln["hook"], "claim": claims.get("hook")},
        "confused": {"vo": ln["confused"], "claim": claims.get("confused")},
        "fact": {"text": ln["fact_phrase"], "id": claims.get("fact_a"), "a": ln["fact_a"], "b": ln["fact_b"]},
        "claim_a": claims.get("fact_a"), "claim_b": claims.get("fact_b"), "search": ln["search"],
        "search_rate": feature.get("search_rate", 0.11), "search_dur": feature.get("search_dur", 1.5),
        "join": False, "hold4": feature.get("hold4", HOLD4), "hold5": feature.get("hold5", HOLD5),
        "lead5": feature.get("lead5", LEAD5), "phone": feature.get("phone", "type"),
    }


def _union(boxes: list) -> list[float]:
    """[x, y, w, h] boxes -> their union as (x0, y0, x1, y1)."""
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[0] + b[2] for b in boxes),
            max(b[1] + b[3] for b in boxes)]


def site_layout(feature: dict, values: dict, meta: dict) -> dict:
    """Where the window stands and how the strip moves in it. All scroll values are capture px (the strip row at the
    window's top). -> {"w", "h", "x", "y", "k" (frame px per capture px), "s0" (the strip's top), "s1" (the end of the
    scroll: the strip's end), "s_key" (where the page stands while the key is outlined), "card_w" (px on screen),
    "at", "dur" (the scroll in shot 4), "back" (the scroll back in shot 5, s), "min4" (shot 4's shortest length)}."""
    sw, sh = meta["png_size"]
    dpr = float(meta.get("dpr") or Q.SITE_MIN_DPR)
    card = (meta.get("boxes") or {}).get("card")
    if not card:
        raise M.TemplateError("the capture has no card box (capture it with --capture)")
    stage_h = STAGE_BOTTOM - STAGE_TOP
    w = WIN_W
    if sh * w / sw > stage_h:                       # taller than the stage: does the whole strip fit a little smaller?
        fit = int(stage_h * sw / sh)
        if card[2] * fit / sw >= CARD_FIT_MIN_W:
            w = fit
    k = w / sw
    h = int(min(stage_h, math.ceil(sh * k - 1e-6)))     # a strip that fits is in the window to its last row
    card_w = card[2] * k
    if card_w < Q.SITE_CARD_MIN_W:
        raise M.TemplateError(f"the card would be {card_w:.0f} px wide on screen (at least {Q.SITE_CARD_MIN_W:.0f}): "
                              "capture the page at phone width")
    vis = h / k                                     # capture rows the window shows
    smax = max(0.0, sh - vis)
    if smax < 1.5:                                  # less than a pixel and a half to scroll: it fits
        smax = 0.0
    kb = _union([M._box(meta, t) for t in Q.feature_lines(feature, values)["key"]])
    if kb[3] - kb[1] > KEY_MAX_H_CSS * dpr:
        raise M.TemplateError(f"the key's targets span {(kb[3] - kb[1]) / dpr:.0f} CSS px of height: they are not one line "
                              "or headline (a target matched another place on the page)")
    if (kb[3] - kb[1]) * k < Q.SITE_KEY_MIN_H:
        raise M.TemplateError(f"the key would be {(kb[3] - kb[1]) * k:.0f} px tall on screen (at least {Q.SITE_KEY_MIN_H:.0f})")
    if not (card[0] - 1 <= kb[0] and kb[2] <= card[0] + card[2] + 1 and card[1] - 1 <= kb[1] and kb[3] <= card[1] + card[3] + 1):
        raise M.TemplateError("the key's targets are not on the card")
    m = KEY_MARGIN_CSS * dpr

    def shows(s_: float) -> bool:
        return s_ + m <= kb[1] and kb[3] <= s_ + vis - m

    s0, s1 = 0.0, smax
    top = feature["key"].get("top")
    # while the key is outlined the window opens on the line the registry names (key.top), else on the card's top (the
    # strip's top when the strip starts at the card): the card's title is never cut in half by the window's edge
    anchor = M._box(meta, Q.target_name(Q.fill(top, values)))[1] - m if top else (0.0 if card[1] < 3 * m else card[1] - m)
    s_key = min(smax, max(0.0, anchor))
    if not shows(s_key):
        s_key = s1 if shows(s1) else min(smax, max(0.0, (kb[1] + kb[3]) / 2 - vis / 2))    # where the scroll ends, or centred
    if not shows(s_key):
        raise M.TemplateError("the key does not fit the window")
    at = TOP_HOLD_HEADER if feature["site"].get("header") else TOP_HOLD
    dist = (s1 - s0) * k
    dur = 0.0 if dist < 1 else round(min(max(dist / SCROLL_PX_S, SCROLL_MIN_S), SHOT4_MAX - at - REST), 2)
    back_px = abs(s_key - s1) * k
    back = 0.0 if back_px < 1 else round(min(max(back_px / BACK_PX_S, BACK_MIN_S), BACK_MAX_S), 2)
    return {"w": int(w), "h": h, "x": 540, "y": round(STAGE_TOP + (stage_h - h) / 2 + h / 2), "k": k,
            "s0": round(s0, 1), "s1": round(s1, 1), "s_key": round(s_key, 1), "card_w": round(card_w, 1),
            "at": at, "dur": dur, "back": back, "min4": round(at + dur + REST, 2) if dur else 0.0}


def site_shots(plan: dict, L: dict) -> tuple[dict, dict]:
    """The two payoff shots of the site screen: (what shot 4 gets, what shot 5 gets), merged over make_story's shots."""
    win = {"t": "site", "name": PAGE, "x": L["x"], "y": L["y"], "w": L["w"], "h": L["h"], "main": True}
    still = {"type": "still"}
    a_els = [dict(win, scroll={"y0": L["s0"], "y1": L["s1"], "at": L["at"], "dur": L["dur"]}, enter=dict(ENTER))]
    b_els = [dict(win, scroll={"y0": L["s1"], "y1": L["s_key"], "at": 0.05, "dur": L["back"]}),
             {"t": "highlight", "target": plan["key"], "at": float(plan["lead5"]), "width": OUTLINE, "pad": OUTLINE_PAD}]
    a = {"els": a_els, "move": still, "caption": dict(CAPTION), "peek": dict(PEEK, at=0.35, **{"from": [-260, 0]})}
    if L["min4"]:
        a["min_dur"] = L["min4"]
    b = {"els": b_els, "move": still, "caption": dict(CAPTION), "peek": dict(PEEK, at=0.0, **{"from": [0, 0]}),
         "key_number": plan["key"]}
    return a, b


def build_story(feature: dict, values: dict, screens: dict, day: str) -> dict:
    """screens: {"page": {"png": path, "size": [w, h], "meta": sidecar}} -> the story."""
    plan = plan_for(feature, values)
    L = site_layout(feature, values, screens[PAGE]["meta"])
    shots, lines = M.story_shots(plan, {"focus4": [540, 868]}, ([], [], {"type": "still"}))
    a, b = site_shots(plan, L)
    for sh, new in ((shots[3], a), (shots[4], b)):
        sh.pop("ring_centre", None)
        sh.update(new, ring_centre=[540, 868])
    return {
        "schema": "rtv-cartoon-story/1",
        "template": {"name": TEMPLATE, "plan": plan["kind"], "made_by": "make_feature_story.py"},
        "feature": {"id": feature["id"], "url": feature["url"], "answers": feature.get("answers"), "values": values},
        "item_id": f"{day}-feature-{feature['id']}", "fact_phrase": plan["fact"]["text"], "post_date": day,
        "voices": M.VOICES, "say": Q.feature_say(feature, values),
        "screens": {n: str(v["png"]) for n, v in screens.items()},
        "screen_numbers_ack": {},
        "shots": shots,
    }


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


def run_capture(args: list[str], screens: Path, shot_python: str) -> None:
    cmd = [shot_python, "-I", str(HERE / "capture.py"), "--out", str(screens), "--name", PAGE] + args
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise M.TemplateError(f"capture failed: {(r.stderr or r.stdout).strip()[-400:]}")


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
        (run / "story.json").unlink(missing_ok=True)
        now = dt.datetime.now(dt.timezone.utc)
        if a.capture:
            shot_py = a.shot_python
            if not shot_py:
                ops = next((p / ".ops" for p in HERE.parents if (p / ".ops" / "cache" / "shot-venv").is_dir()), None)
                if not ops:
                    raise M.TemplateError("no .ops/cache/shot-venv above this script (pass --shot-python)")
                shot_py = str(ops / "cache" / "shot-venv" / "Scripts" / "python.exe")
            capture_feature(feature, run, shot_py, now)
            now = dt.datetime.now(dt.timezone.utc)
        screens = load_screens(run)
        metas = {n: v["meta"] for n, v in screens.items()}
        values = Q.feature_values(feature, metas)
        story = build_story(feature, values, screens, Q.capture_day(metas))
        probs = check_story(story, feature, metas, now)
        if probs:
            raise Q.FeatureError("; ".join(probs))
        for s_ in story["screens"]:
            story["screens"][s_] = str(Path(story["screens"][s_]).relative_to(run)).replace("\\", "/")
    except (Q.FeatureError, M.TemplateError) as e:
        print(f"make_feature_story: {e}", file=sys.stderr)
        return 2
    out = run / "story.json"
    out.write_text(json.dumps(story, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"story": str(out), "feature": feature["id"], "values": values, "fact_phrase": story["fact_phrase"],
                      "lines": [s_.get("vo") for s_ in story["shots"] if s_.get("vo")]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
