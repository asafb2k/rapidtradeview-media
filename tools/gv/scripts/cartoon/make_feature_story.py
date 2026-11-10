"""FEATURE mode for the cartoon Reel: one feature of the site -> story.json in the one-idea format, filled from a capture
made now. No facts item and no hand-written creative: the registry (features.json) holds the page, the capture bands, how
each value is read from a capture's visible text, and the story lines with {slots} for those values.

    make_feature_story.py FEATURE_ID --run DIR [--capture] [--shot-python PY] [--list]

Owner request 2026-11-10: "create one for features like smart money, concentration visuals, portfolio visuals and such".
A feature short shows what one feature answers, with our real screen as the payoff; it is not tied to a news item. The
pattern and every owner rule are the daily short's (make_story.py):
  1 HOOK      Dale says something confident, with a number that is on our page today     "4 in Congress bought the same stock!"
  2 CLOSE     Pip does not get it and says where he looks                               "Which stock? Checking RapidTradeView."
  3 CLOSE     the phone close: our name and mark, a thumb taps the page's real link       (no voice, one tap)
  4 PAYOFF    our real page: its header and logo on top, the feature's card below        the page's own words
  5 PAYOFF    the header flies off, the key lands big and outlined                       the page's own words
  6 CALLBACK  one word                                                                    "Oh."
  7 END       "Search RapidTradeView. Not investment advice."

With --capture the page is captured now, as a logged-out guest (capture.py in the shot venv): first the bands that need no
value, then the values are read from those sidecars (cartoon_qa.feature_values: never typed by hand), then the bands whose
clip texts use a value (the key, at 6x). It stops with exit 2, and writes no story, when
  - a band or a value is missing (the page changed, or its top row does not carry the story),
  - the page is in an error or loading state, or says one of the feature's refuse_if texts,
  - a provider or source brand is on what a band shows,
  - a capture is not from today, or not from the feature's page,
  - the filled lines would not pass the number and claim gates against the captures.
Layouts: "stack" (the daily short's: header + fact card, then fact card + the key tag) and "hero" (header + fact card, then
both fly off and the key capture, a chart, fills the stage with one label outlined).
Then render:  cartoon_reel.py --story DIR/story.json --out DIR   (it builds the item from the sidecars again, gates the
story against the registry and rebuilds it with story_drift: a story edited by hand, its say map included, fails
feature_story).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_story as M  # noqa: E402

Q = M.Q
cr = Q.cr
TEMPLATE = "rtv-cartoon-feature/1"
# A feature short lingers on the real screen: a still beat after each payoff line, and the key lands (and the camera
# settles) before the voice names it, so its caption never sits on a card that is still flying in.
HOLD4, LEAD5, HOLD5 = 0.4, 0.5, 1.0         # 1.6 s after the last caption read as dead air (review 2026-11-10)
HERO_W_MAX = 900                     # the hero card's width at landing (frame px)
HERO_DRIFT, HERO_SHOT_S = 0.012, 4.5 # the camera's drift after landing, and the longest the shot may run (PAYOFF_MAX);
                                     # a slower drift leaves the chart more of the stage (0.02 cost it 4% of its size)
HERO_AT = 0.5                        # the outline starts once the hero has landed, with the line that names it
HERO_OUTLINE, HERO_OUTLINE_PAD = 10, 3   # px: a chart label is small: a heavier line than a tag's (8), drawn close to the
                                         # label (a tag's 18 px ran over the line under the market card's "83%")
SIDE_EXIT = 1400                     # a card that leaves goes off sideways: upwards it passed under the brand pill


def filled(c: dict, values: dict) -> dict:
    """A registry capture with its {slots} filled."""
    out = dict(c)
    for k in ("clip_from", "clip_to", "end_above"):
        if out.get(k):
            out[k] = Q.fill(out[k], values)
    out["targets"] = [Q.fill(t, values) for t in c.get("targets") or []]
    return out


def has_slots(c: dict) -> bool:
    return bool(Q._slots(json.dumps(c)))


def plan_for(feature: dict, values: dict) -> dict:
    """The registry entry + today's values -> the plan make_story.story_shots takes."""
    ln = Q.feature_lines(feature, values)
    claims = feature.get("claims") or {}
    key = feature["key"]
    return {
        "kind": f"feature:{feature['id']}", "ticker": values.get(feature.get("ticker") or "") or "",
        "figure": ln["hook_figure"], "key": ln["key"],
        "hook": {"vo": ln["hook"], "claim": claims.get("hook")},
        "confused": {"vo": ln["confused"], "claim": claims.get("confused")},
        "fact": {"text": ln["fact_phrase"], "id": claims.get("fact_a"), "a": ln["fact_a"], "b": ln["fact_b"]},
        "claim_a": claims.get("fact_a"), "claim_b": claims.get("fact_b"), "search": ln["search"],
        "search_rate": feature.get("search_rate", 0.11), "search_dur": feature.get("search_dur", 1.5),
        "join": False, "hold4": feature.get("hold4", HOLD4), "hold5": feature.get("hold5", HOLD5),
        "key_pad": key.get("pad"), "key_crop": [Q.fill(t, values) for t in key.get("crop") or []] or None,
        "key_w": key.get("w", M.KEY_W), "lead5": feature.get("lead5", LEAD5),
        "phone": feature.get("phone", "type"), "head_exit": [SIDE_EXIT, 0], "key_outline": key.get("outline"),
        "key_whole": key.get("kind", "figure") == "visual",
        "key_also": (dict(key["also"], target=ln["also"], at=Q.fill(key["also"]["at"], values)) if key.get("also") else None),
        "url": feature["url"], "viewport": feature.get("viewport"),
        "captures": [filled(c, values) for c in feature["captures"]],
    }


def hero_pay(plan: dict, screens: dict) -> tuple[dict, tuple]:
    """The "hero" payoff: shot 4 is the stacked header + fact card; in shot 5 both fly off and the key capture (a chart)
    lands alone, as wide as the stage allows, with the key label outlined. The camera returns to scale 1 about the frame
    centre and drifts: the card's top and bottom are set so that it stays below the brand pill and above the caption band
    for the longest the shot may run. -> (the layout, (shot 4 elements, shot 5 elements, shot 5 camera move))."""
    L, _geo = M.head_fact_layout(screens)
    head_el, fact_el = M.head_fact_els(L)
    kw, kh = screens["key"]["size"]
    f = 1 + HERO_DRIFT * HERO_SHOT_S
    top = 960 - (960 - M.STAGE_TOP) / f
    bot = 960 + (M.STAGE_BOTTOM - 960) / f
    w = int(min(HERO_W_MAX, (bot - top - 20) * kw / kh, (1080 - 2 * 40) / f - 20))
    h = kh * w / kw + 20
    yc = (top + bot) / 2
    bx, by, bw, bh = M._box(screens["key"]["meta"], plan["key"])
    sc = w / kw
    if w < Q.KEY_VISUAL_MIN_W or bh * sc < Q.KEY_VISUAL_MIN_H:
        raise M.TemplateError(f"the hero capture reads too small in the stage (card {w} px wide, key label {bh * sc:.0f} px tall); "
                              "capture a tighter band")
    land = [round(540 - w / 2 + (bx + bw / 2) * sc), round(yc - (h - 20) / 2 + (by + bh / 2) * sc)]
    L.update(hero_w=w, y_key=round(yc))
    pay4 = [dict(head_el, enter={"from": [-1200, 0], "dur": 0.3}), dict(fact_el, enter={"from": [0, 1100], "dur": 0.34})]
    pay5 = [dict(head_el, exit={"to": [SIDE_EXIT, 0], "at": 0.0, "dur": 0.3}),
            dict(fact_el, exit={"to": [-SIDE_EXIT, 0], "at": 0.0, "dur": 0.3}),
            {"t": "card", "name": "key", "x": 540, "y": round(yc), "w": w, "rot": -1.0, "main": True,
             "enter": {"from": [0, 1100], "dur": 0.34}},
            {"t": "highlight", "target": plan["key"], "at": HERO_AT, "width": HERO_OUTLINE, "pad": HERO_OUTLINE_PAD}]
    move5 = {"type": "zoom_to", "target": plan["key"], "z": 1.0, "min_px": False, "from_prev": True, "at": 0.0, "dur": 0.5,
             "land": land, "drift": HERO_DRIFT}
    return L, (pay4, pay5, move5)


def build_story(feature: dict, values: dict, screens: dict, day: str) -> dict:
    """screens: {name: {"png": path, "size": [w, h], "meta": sidecar}} for every capture of the feature -> the story."""
    plan = plan_for(feature, values)
    if feature.get("layout", "stack") == "hero":
        L, pay = hero_pay(plan, screens)
    else:
        L, pay = M.payoff_layout(plan, screens), None
    shots, lines = M.story_shots(plan, L, pay)
    return {
        "schema": "rtv-cartoon-story/1",
        "template": {"name": TEMPLATE, "plan": plan["kind"], "made_by": "make_feature_story.py"},
        "feature": {"id": feature["id"], "url": feature["url"], "answers": feature.get("answers"), "values": values},
        "item_id": f"{day}-feature-{feature['id']}", "fact_phrase": plan["fact"]["text"], "post_date": day,
        "voices": M.VOICES, "say": M.say_map(lines, plan["ticker"]),
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
    """How a story differs from the one this script writes from the same registry entry and the same sidecars (empty =
    it is that story). The renderer runs it inside feature_story: a line, a say entry, a crop, an outline, a voice or a
    timing edited by hand is named here. The screens' paths are not compared (a run folder can move)."""
    try:
        values = Q.feature_values(feature, metas)
        screens = {n: {"png": f"screens/{n}.png", "size": m["png_size"], "meta": m} for n, m in metas.items()}
        want = build_story(feature, values, screens, Q.capture_day(metas))
    except (Q.FeatureError, M.TemplateError, KeyError) as e:
        return [f"the story cannot be rebuilt from the captures: {e}"]
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
    """What would fail at render time and can be known now: the captures (page, day, state, providers), the story against
    the registry, and the lines against the captures (numbers, claims, banned words, the fact phrase)."""
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


def load_screens(run: Path, names: list[str]) -> dict:
    out = {}
    for n in names:
        png, side = run / "screens" / f"{n}.png", run / "screens" / f"{n}.json"
        if not png.is_file() or not side.is_file():
            raise M.TemplateError(f"capture {png} is missing (run with --capture)")
        meta = json.loads(side.read_text(encoding="utf-8"))
        out[n] = {"png": png, "size": meta["png_size"], "meta": meta}
    return out


def capture_feature(feature: dict, run: Path, shot_python: str, now: dt.datetime) -> None:
    """Capture the bands that need no value, read the values from their sidecars, then capture the rest."""
    screens = run / "screens"
    for c in feature["captures"]:
        for ext in (".png", ".json"):
            (screens / f"{c['name']}{ext}").unlink(missing_ok=True)
    plain = [c for c in feature["captures"] if not has_slots(c)]
    base = {"url": feature["url"], "viewport": feature.get("viewport")}
    M.run_captures({**base, "captures": plain}, screens, shot_python)
    metas = {n: v["meta"] for n, v in load_screens(run, [c["name"] for c in plain]).items()}
    ok, det = Q.feature_capture_gate(feature, metas, now)
    bad = {n: w for n, w in det["problems"].items() if n in metas}          # the other bands are not made yet
    if bad:
        raise Q.FeatureError("; ".join(f"capture {n}: {'; '.join(w)}" for n, w in bad.items()))
    values = Q.feature_values(feature, metas)
    rest = [filled(c, values) for c in feature["captures"] if has_slots(c)]
    M.run_captures({**base, "captures": rest}, screens, shot_python)


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
        screens = load_screens(run, [c["name"] for c in feature["captures"]])
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
