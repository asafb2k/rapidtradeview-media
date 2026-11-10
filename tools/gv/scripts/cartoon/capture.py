"""Capture a real RapidTradeView page for a cartoon Reel's payoff: a phone-viewport PNG plus a sidecar JSON with the DOM boxes
of the key figures (no OCR, no synthetic UI).

Runs in the isolated Playwright venv (never the conda env, never system python):
    <media>/.ops/cache/shot-venv/Scripts/python.exe capture.py --url URL --out DIR --name NAME
        [--scroll-to TEXT] [--scroll-frac 0.42] [--clip-from TEXT --clip-to TEXT [--clip-end-above TEXT]] [--target TEXT ...]
        [--clip-el CSS] [--viewport 430x932] [--dpr 3]
A TEXT that starts with "=" matches a whole text node only ("=V" is the ticker V, not the V of "View"); the sidecar keeps
the target's text without the "=".

Writes DIR/NAME.png and DIR/NAME.json:
    {url, final_url, captured_at (UTC), viewport, dpr, png_size, sha256, scroll_y, page_text, visible_text, inside_text,
     seal, targets: [{text, box: [x, y, w, h] in screenshot px}]}
`url` is the address asked for and `final_url` the one the browser ended on (/market answers 308 to /#market).
`visible_text` is the text of every node that touches the captured area: a superset of the pixels (a line whose box only
grazes the band's edge is listed), read by the name and error checks. `inside_text` is what the PNG really shows: the nodes,
or the words of a node, whose boxes lie mostly (at least half) inside the area; numbers and values are read from it.
`seal` is a hash over the fields the gates trust (cartoon_qa.capture_seal recomputes it): a sidecar edited by hand no
longer matches. With --clip-from/--clip-to
the PNG is a full-width band of the page from the top of the first text to the bottom of the second (a cropped UI card,
which keeps unrelated numbers off screen); with --clip-el it is the box of the first element matching a CSS selector plus
--clip-pad on every side (a chart on its own, without the page margins beside it). Target boxes are relative to the
captured area. The guest intro
panel is dismissed first (its close button), so no sample-portfolio numbers end up on screen. Exit 0 = ok, 2 = a target was
not found or the page did not load (No Fallbacks: the renderer refuses a capture without its sidecar).

STRIP mode (feature shorts, owner verdict 2026-11-10: the payoff shows the site's card WHOLE, as the site draws it):
    capture.py --url URL --out DIR --name NAME --strip-top SPEC --strip-bottom SPEC [--strip-pad 6]
        [--strip-pad-bottom N] [--box NAME=SPEC ...] [--box-bottom NAME=SPEC ...] [--target TEXT ...]
        [--viewport 390x844] [--dpr 3]
The PNG is the page at its full phone width from the top edge of the first SPEC to the bottom edge of the second, in one
piece: the renderer scrolls over it like a thumb, it never cuts a card out of it. SPEC is "page" (the document), "el:CSS"
(the first drawn element matching the selector), "all:CSS" (the union of every drawn element matching it) or "text:TEXT" (a text,
with the "=" and "#N" marks of a target). The page is
scrolled through once first, so lazy panels are drawn, and the screenshot is taken with the viewport parked off the strip:
an element that is fixed or sticky (the bottom tab bar) would otherwise be painted into the middle of it; if one still
lies on the strip the capture stops. --box records the DOM box of an element (the card, its chart) in the sidecar's
"boxes", in strip px; the same NAME twice is the union, and --box-bottom NAME=SPEC ends the box at the bottom edge of
another element (the card's head: from its top to the bottom of its chart). The sidecar also carries "kind": "strip" and
"strip": {top, bottom, page_height} in CSS px, and what the renderer and the gates need to treat the strip as a page:
  "box_tags"      {NAME: the tag names of the elements a box was read from} ("svg" for a chart, "div>graphic" for an
                  element that holds an svg, a canvas or an image, "#text" for a text);
  "content"       [[x, y, w, h, kind]] in strip px: every line of text ("text"), every image ("img") and every painted
                  leaf element ("shape": a bar, an arc; "box": a painted block) that touches the strip. The window that
                  shows the strip may stand only where its edges cross none of them (the edge_clear gate);
  "images"        [{box, ok, sym}]: every <img> on the strip, whether it finished loading with pixels, and the last part
                  of its address (a ticker logo is asked for by its symbol);
  "empty_slots"   [[x, y, w, h]]: empty square leaf elements that paint nothing: the place of a logo that did not load
                  (the site removes the <img> when its request fails and the slot stays);
  "images_failed" the last path segment of every image request of the page that failed (status >= 400, or no answer).
A logo that failed leaves its row without its picture: the feature gate refuses such a capture. A logo that loaded but is
the WRONG company's (the logo source answered with another firm's mark, seen on 2026-11-10 for one ticker) cannot be seen
by any check here: a person looks at every logo before the video ships (make_feature_story writes screens/logos.png).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # tools/: qa_header
import qa_header as qa  # noqa: E402

JS_FIND = r"""([needle, all, exact]) => {
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const hits = [];
  let n;
  while ((n = w.nextNode())) {
    const i = n.data.indexOf(needle);
    if (i < 0) continue;
    if (exact && n.data.replace(/\s+/g, ' ').trim() !== needle) continue;
    const el = n.parentElement;
    if (!el || el.offsetParent === null) continue;
    const r = document.createRange();
    r.setStart(n, i); r.setEnd(n, i + needle.length);
    const b = r.getBoundingClientRect();
    if (b.width < 1 || b.height < 1) continue;
    const h = {x: b.left, y: b.top, w: b.width, h: b.height, docY: b.top + window.scrollY};
    if (!all) return h;
    hits.push(h);
  }
  return all ? hits : null;
}"""

JS_VISIBLE = r"""([X0, Y0, X1, Y1]) => {
  const vis = [], ins = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const area = (rs) => rs.reduce((a, b) => a + b.width * b.height, 0);
  const inside = (rs) => rs.reduce((a, b) => a + Math.max(0, Math.min(b.right, X1) - Math.max(b.left, X0))
                                              * Math.max(0, Math.min(b.bottom, Y1) - Math.max(b.top, Y0)), 0);
  const boxes = (r) => [...r.getClientRects()].filter(b => b.width > 0 && b.height > 0);
  let n;
  while ((n = w.nextNode())) {
    const t = n.data.replace(/\s+/g, ' ').trim();
    if (!t) continue;
    const el = n.parentElement;
    if (!el) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    const rects = boxes(r);
    if (!rects.some(b => b.bottom > Y0 && b.top < Y1 && b.right > X0 && b.left < X1)) continue;
    vis.push(t);                                  // touches the area: the wide text (names, error words)
    const a = area(rects);
    if (a > 0 && inside(rects) / a >= 0.98) { ins.push(t); continue; }
    const words = [];                             // partly inside: keep the words whose own boxes are mostly inside
    const re = /\S+/g;
    let m;
    while ((m = re.exec(n.data))) {
      const wr = document.createRange();
      wr.setStart(n, m.index); wr.setEnd(n, m.index + m[0].length);
      const wb = boxes(wr), wa = area(wb);
      if (wa > 0 && inside(wb) / wa >= 0.5) words.push(m[0]);
    }
    if (words.length) ins.push(words.join(' '));
  }
  return {visible: vis.join('\n'), inside: ins.join('\n')};
}"""


def seal(side: dict) -> str:
    """The sidecar's fingerprint (the same fields, in the same order, as cartoon_qa.capture_seal: this script runs in its
    own venv and cannot import it; tools/tests/test_cartoon_features.py holds the two together)."""
    body = [side.get("url"), side.get("final_url"), side.get("captured_at"), side.get("sha256"), side.get("png_size"),
            side.get("visible_text"), side.get("inside_text"), side.get("targets")]
    if "boxes" in side:                              # a strip: the card's DOM boxes and the strip's place on the page
        body += [side.get("kind"), side.get("boxes"), side.get("strip"), side.get("viewport"), side.get("dpr")]
    if "content" in side:                            # what the strip draws: its rows, its images and how they loaded
        body += [side.get("content"), side.get("box_tags"), side.get("images"), side.get("empty_slots"),
                 side.get("images_failed")]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


JS_PINNED = r"""() => {
  const out = [];
  for (const e of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(e);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) continue;
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    out.push({pos: cs.position, x: r.left, w: r.width, h: r.height, docY: r.top + window.scrollY,
              text: (e.innerText || '').replace(/\s+/g, ' ').slice(0, 40)});
  }
  return out;
}"""

JS_EL_BOX = """([sel, all]) => {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const tags = [];
  for (const e of document.querySelectorAll(sel)) {      // a responsive twin that is not drawn has no box: skipped
    const b = e.getBoundingClientRect();
    if (b.width < 1 || b.height < 1) continue;
    x0 = Math.min(x0, b.left); y0 = Math.min(y0, b.top); x1 = Math.max(x1, b.right); y1 = Math.max(y1, b.bottom);
    tags.push(e.tagName.toLowerCase() + (e.querySelector('svg,canvas,img') ? '>graphic' : ''));
    if (!all) break;
  }
  return x1 > x0 ? {x: x0, y: y0, w: x1 - x0, h: y1 - y0, docY: y0 + window.scrollY, tags} : null; }"""

# What the strip draws, as boxes in viewport CSS px ([X0, Y0, X1, Y1] is the strip where the viewport is parked): the
# lines of every text, every image, every painted leaf element (an SVG bar or arc, a painted block), and the empty square
# leaves that paint nothing (the slot of a logo that did not load). A container is not content: only what has no element
# inside it, so a card's border or a chart's frame is never listed.
JS_CONTENT = r"""([X0, Y0, X1, Y1]) => {
  const content = [], images = [], slots = [];
  const touches = (b) => b.width >= 1 && b.height >= 1 && b.bottom > Y0 && b.top < Y1 && b.right > X0 && b.left < X1;
  const drawn = (e) => e.checkVisibility ? e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
                                         : e.getClientRects().length > 0;
  const alpha = (c) => { if (!c || c === 'none' || c === 'transparent') return 0;
                         const m = /rgba?\(([^)]+)\)/.exec(c); if (!m) return 1;
                         const p = m[1].split(/[,\/ ]+/).filter(Boolean); return p.length >= 4 ? parseFloat(p[3]) : 1; };
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (!n.data.trim() || !n.parentElement || !drawn(n.parentElement)) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    for (const b of r.getClientRects()) if (touches(b)) content.push([b.left, b.top, b.width, b.height, 'text']);
  }
  for (const e of document.querySelectorAll('body *')) {
    if (e.childElementCount) continue;
    const b = e.getBoundingClientRect();
    if (!touches(b) || !drawn(e)) continue;
    const tag = e.tagName.toLowerCase(), cs = getComputedStyle(e), box = [b.left, b.top, b.width, b.height];
    if (tag === 'img') {
      const seg = (e.currentSrc || e.src || '').split('?')[0].split('/').pop() || '';
      images.push({box, ok: e.complete && e.naturalWidth > 0, sym: /^[A-Za-z0-9._-]{1,16}$/.test(seg) ? seg : ''});
      content.push([...box, 'img']);
    } else if (tag === 'canvas' || tag === 'video' || tag === 'svg') {
      content.push([...box, 'img']);
    } else if (e instanceof SVGElement) {
      if (tag === 'text' || tag === 'tspan' || tag === 'title' || tag === 'desc') continue;     // its text is listed above
      const fill = alpha(cs.fill) * parseFloat(cs.fillOpacity || '1');
      const stroke = alpha(cs.stroke) * parseFloat(cs.strokeOpacity || '1');
      if (fill > 0.02 || (stroke > 0.02 && parseFloat(cs.strokeWidth || '0') > 0)) content.push([...box, 'shape']);
    } else if (!(e.textContent || '').trim()) {
      const border = ['Top', 'Right', 'Bottom', 'Left'].some(
          s_ => parseFloat(cs['border' + s_ + 'Width']) > 0 && alpha(cs['border' + s_ + 'Color']) > 0.02);
      const marks = ['::before', '::after'].some(
          p => { const c = getComputedStyle(e, p).content; return c && c !== 'none' && c !== 'normal'; });
      const mask = (cs.maskImage && cs.maskImage !== 'none') || (cs.webkitMaskImage && cs.webkitMaskImage !== 'none');
      if (alpha(cs.backgroundColor) > 0.02 || cs.backgroundImage !== 'none' || border || marks || mask) content.push([...box, 'box']);
      else if (b.width >= 10 && b.height >= 10 && b.width / b.height > 0.75 && b.width / b.height < 1.34) slots.push(box);
    }
  }
  return {content, images, slots};
}"""


def box_spec(spec: str) -> tuple[str, str]:
    """"page" | "el:CSS" | "all:CSS" | "text:TEXT" -> (kind, value)."""
    if spec == "page":
        return "page", ""
    kind, sep, val = spec.partition(":")
    if not sep or kind not in ("el", "all", "text") or not val:
        raise ValueError(f"a box is 'page', 'el:CSS', 'all:CSS' or 'text:TEXT', not {spec!r}")
    return kind, val


def named_spec(arg: str) -> tuple[str, str]:
    """"card=el:section" -> ("card", "el:section")."""
    name, sep, spec = arg.partition("=")
    if not sep or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError(f"a named box is NAME=SPEC (NAME in lower case), not {arg!r}")
    box_spec(spec)
    return name, spec


def split_spec(spec: str) -> tuple[str, str, bool]:
    """TEXT, TEXT#N, TEXT#last, each with an optional leading "=" (whole text node) -> (needle, nth or "last", exact)."""
    exact = spec.startswith("=")
    if exact:
        spec = spec[1:]
    if spec.endswith("#last"):
        return spec[:-5], "last", exact
    if re.fullmatch(r".+#\d+", spec):
        needle, _, nth = spec.rpartition("#")
        return needle, nth, exact
    return spec, "1", exact


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--scroll-to", help="scroll so this text sits at --scroll-frac of the viewport height")
    ap.add_argument("--scroll-frac", type=float, default=0.42)
    ap.add_argument("--clip-from", help="clip: band starts at the top of this text (TEXT#N = its N-th occurrence on the page, "
                                        "TEXT#last = its last occurrence above --clip-to)")
    ap.add_argument("--clip-to", help="clip: band ends at the bottom of this text (TEXT#N = its N-th occurrence on the page)")
    ap.add_argument("--clip-pad", type=float, default=14.0, help="CSS px above and below the band")
    ap.add_argument("--clip-end-above", help="clip: the band ends just above the first occurrence of this text between the "
                                             "clip-from and clip-to texts (keeps small print such as a date off the card); "
                                             "not found there = exit 2")
    ap.add_argument("--clip-el", help="clip: the box of the first element matching this CSS selector, plus --clip-pad on "
                                      "every side (instead of --clip-from/--clip-to)")
    ap.add_argument("--strip-top", help="strip mode: the page at full width from the top edge of this box (page | el:CSS | "
                                        "text:TEXT) ...")
    ap.add_argument("--strip-bottom", help="... to the bottom edge of this box")
    ap.add_argument("--strip-pad", type=float, default=6.0, help="CSS px of page above and below the strip's boxes")
    ap.add_argument("--strip-pad-bottom", type=float, help="CSS px of page below the strip's bottom box (default: --strip-pad): "
                                                           "the air the site leaves under a chart")
    ap.add_argument("--box", action="append", default=[], help="strip mode: NAME=SPEC, the DOM box of an element, recorded "
                                                               "in the sidecar's boxes (the same NAME twice = the union)")
    ap.add_argument("--box-bottom", action="append", default=[], help="strip mode: NAME=SPEC, the named box ends at the "
                                                                      "bottom edge of this element")
    ap.add_argument("--target", action="append", default=[],
                    help="text whose DOM box goes into the sidecar; TEXT#N = its N-th occurrence inside the captured area")
    ap.add_argument("--viewport", default="430x932")
    ap.add_argument("--dpr", type=int, default=3)
    ap.add_argument("--chromium", default=os.path.expandvars(r"%LOCALAPPDATA%/ms-playwright/chromium-1234/chrome-win64/chrome.exe"))
    a = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    vw, vh = (int(v) for v in a.viewport.lower().split("x"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    png = out / f"{a.name}.png"
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=a.chromium if Path(a.chromium).is_file() else None, headless=True)
        ctx = b.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=a.dpr, is_mobile=True, has_touch=True,
                            color_scheme="dark",
                            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
                                       "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
        qa.mark_browser(ctx)                         # our own capture: not a visitor
        pg = ctx.new_page()
        failed_images: list[str] = []

        def _seg(url: str) -> str:
            seg = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
            return seg if re.fullmatch(r"[A-Za-z0-9._-]{1,16}", seg) else ""

        def _on_response(resp):
            try:
                if resp.request.resource_type == "image" and resp.status >= 400:
                    failed_images.append(_seg(resp.url))
            except Exception:  # noqa: BLE001 - a listener never stops the capture
                pass

        def _on_failed(req):
            try:
                if req.resource_type == "image":
                    failed_images.append(_seg(req.url))
            except Exception:  # noqa: BLE001
                pass

        pg.on("response", _on_response)
        pg.on("requestfailed", _on_failed)

        def find_all(needle: str, exact: bool = False) -> list:
            return pg.evaluate(JS_FIND, [needle, True, exact])

        r = pg.goto(a.url, wait_until="networkidle", timeout=60000)
        if not r or r.status != 200:
            print(f"capture: {a.url} returned {r.status if r else 'nothing'}", file=sys.stderr)
            return 2
        pg.wait_for_timeout(2500)
        for sel in ('button[aria-label*="ismiss" i]', 'button[aria-label*="lose" i]', 'button[aria-label*="hide" i]'):
            loc = pg.locator(sel).first
            if loc.count():
                loc.tap()
                pg.wait_for_timeout(1200)
                break
        pg.evaluate("window.scrollTo(0, 0)")
        pg.wait_for_timeout(500)
        strip = None
        boxes: dict = {}
        box_tags: dict = {}
        if a.strip_top or a.strip_bottom:
            if not (a.strip_top and a.strip_bottom) or a.clip_el or a.clip_from or a.clip_to or a.scroll_to:
                print("capture: strip mode takes --strip-top and --strip-bottom, and no clip or scroll option", file=sys.stderr)
                return 2
            # scroll through the page once so that lazy panels and charts are drawn
            height = pg.evaluate("document.documentElement.scrollHeight")
            y = 0
            while y < height:
                pg.evaluate("(y) => window.scrollTo(0, y)", y)
                pg.wait_for_timeout(350)
                y += 600
                height = pg.evaluate("document.documentElement.scrollHeight")
            pg.wait_for_timeout(1500)
            pg.evaluate("window.scrollTo(0, 0)")
            pg.wait_for_timeout(700)
            height = pg.evaluate("document.documentElement.scrollHeight")

            def doc_box(spec: str):
                """A box in document CSS px: {x, y, w, h}; None when the element or the text is not on the page."""
                kind, val = box_spec(spec)
                if kind == "page":
                    return {"x": 0.0, "y": 0.0, "w": float(vw), "h": float(height), "tags": ["#page"]}
                if kind in ("el", "all"):       # the first element matching, or the union of all that match
                    b_ = pg.evaluate(JS_EL_BOX, [val, kind == "all"])
                    return ({"x": b_["x"], "y": b_["docY"], "w": b_["w"], "h": b_["h"], "tags": b_.get("tags") or []}
                            if b_ and b_["w"] >= 1 and b_["h"] >= 1 else None)
                needle, nth, exact = split_spec(val)
                hits = find_all(needle, exact)
                hit = (hits[-1] if nth == "last" else hits[int(nth) - 1] if len(hits) >= int(nth) else None) if hits else None
                return {"x": hit["x"], "y": hit["docY"], "w": hit["w"], "h": hit["h"], "tags": ["#text"]} if hit else None

            try:
                bt, bb = doc_box(a.strip_top), doc_box(a.strip_bottom)
                named = [named_spec(x) for x in a.box]
                cuts = dict(named_spec(x) for x in a.box_bottom)
            except ValueError as e:
                print(f"capture: {e}", file=sys.stderr)
                return 2
            if not (bt and bb):
                print("capture: --strip-top and --strip-bottom must both be on the page", file=sys.stderr)
                return 2
            pad_bottom = a.strip_pad if a.strip_pad_bottom is None else a.strip_pad_bottom
            top = float(max(0, int(bt["y"] - a.strip_pad)))
            bot = float(min(int(height), -int(-(bb["y"] + bb["h"] + pad_bottom) // 1)))
            if bot - top < 40 or (bot - top) * a.dpr > 16000:
                print(f"capture: the strip is {bot - top:.0f} CSS px tall (40 to {16000 // a.dpr} at dpr {a.dpr})", file=sys.stderr)
                return 2
            for name, spec in named:
                b_ = doc_box(spec)
                if not b_:
                    print(f"capture: box {name}: {spec!r} is not on the page", file=sys.stderr)
                    return 2
                x0_, y0_, x1_, y1_ = b_["x"], b_["y"], b_["x"] + b_["w"], b_["y"] + b_["h"]
                if name in boxes:
                    o = boxes[name]
                    x0_, y0_, x1_, y1_ = min(o[0], x0_), min(o[1], y0_), max(o[2], x1_), max(o[3], y1_)
                boxes[name] = [x0_, y0_, x1_, y1_]
                box_tags[name] = sorted(set(box_tags.get(name, [])) | set(b_.get("tags") or []))
            for name, spec in cuts.items():
                b_ = doc_box(spec)
                if name not in boxes or not b_:
                    print(f"capture: --box-bottom {name}: no such box, or {spec!r} is not on the page", file=sys.stderr)
                    return 2
                boxes[name][3] = min(boxes[name][3], b_["y"] + b_["h"])
            for name, (x0_, y0_, x1_, y1_) in boxes.items():
                if not (x0_ >= -0.5 and x1_ <= vw + 0.5 and y0_ >= top - 0.5 and y1_ <= bot + 0.5 and y1_ - y0_ >= 1):
                    print(f"capture: box {name} is not inside the strip", file=sys.stderr)
                    return 2
            # park the viewport off the strip: a fixed or sticky element is painted where the viewport is
            max_sy = max(0.0, height - vh)
            parked = None
            for cand in (bot + 8, top - vh - 8, max_sy, 0.0):
                if not (0 <= cand <= max_sy):
                    continue
                pg.evaluate("(y) => window.scrollTo(0, y)", cand)
                pg.wait_for_timeout(600)
                on_strip = [e_ for e_ in pg.evaluate(JS_PINNED) if e_["docY"] < bot and e_["docY"] + e_["h"] > top]
                if not on_strip:
                    parked = cand
                    break
            if parked is None:
                print("capture: a fixed or sticky element lies on the strip at every scroll position tried", file=sys.stderr)
                return 2
            strip = {"top": top, "bottom": bot, "page_height": height}
        if a.scroll_to:
            hit = pg.evaluate(JS_FIND, [a.scroll_to, False, False])
            if not hit:
                print(f"capture: scroll text {a.scroll_to!r} not found", file=sys.stderr)
                return 2
            pg.evaluate("(y) => window.scrollTo(0, y)", max(0, hit["docY"] - a.scroll_frac * vh))
            pg.wait_for_timeout(700)
        clip = None
        if a.clip_el:
            box = pg.evaluate("""(sel) => { const e = document.querySelector(sel); if (!e) return null;
                                 const b = e.getBoundingClientRect();
                                 return {x: b.left, w: b.width, h: b.height, docY: b.top + window.scrollY}; }""", a.clip_el)
            if not box or box["w"] < 1 or box["h"] < 1:
                print(f"capture: no element matches {a.clip_el!r}", file=sys.stderr)
                return 2
            top, bot = box["docY"] - a.clip_pad, box["docY"] + box["h"] + a.clip_pad
            if bot - top > vh:
                print("capture: the clipped element is taller than the viewport", file=sys.stderr)
                return 2
            pg.evaluate("(y) => window.scrollTo(0, y)", max(0, top - (vh - (bot - top)) / 2))
            pg.wait_for_timeout(700)
            sy = pg.evaluate("window.scrollY")
            x0 = max(0.0, box["x"] - a.clip_pad)
            clip = {"x": x0, "y": top - sy, "width": min(float(vw), box["x"] + box["w"] + a.clip_pad) - x0, "height": bot - top}
        elif a.clip_from or a.clip_to:
            def nth_hit(spec, below=None):
                """TEXT, TEXT#N (the N-th occurrence on the page) or TEXT#last (the last occurrence above `below`)."""
                needle, nth, exact = split_spec(spec)
                if nth == "last":
                    hits = [h for h in find_all(needle, exact) if below and h["docY"] < below["docY"]]
                    return max(hits, key=lambda h: h["docY"]) if hits else None
                hits = find_all(needle, exact)
                return hits[int(nth) - 1] if len(hits) >= int(nth) else None

            ht = nth_hit(a.clip_to) if a.clip_from and a.clip_to else None
            hf = nth_hit(a.clip_from, ht) if ht else None
            if not (hf and ht):
                print("capture: --clip-from and --clip-to must both be found", file=sys.stderr)
                return 2
            top, bot = hf["docY"] - a.clip_pad, ht["docY"] + ht["h"] + a.clip_pad
            if a.clip_end_above:
                cut = [h for h in find_all(a.clip_end_above)
                       if hf["docY"] < h["docY"] < ht["docY"] + ht["h"]]
                if not cut:
                    print(f"capture: {a.clip_end_above!r} not found inside the clip", file=sys.stderr)
                    return 2
                bot = min(h["docY"] for h in cut) - 3
            if bot - top > vh:
                print("capture: the clip band is taller than the viewport", file=sys.stderr)
                return 2
            pg.evaluate("(y) => window.scrollTo(0, y)", max(0, top - (vh - (bot - top)) / 2))
            pg.wait_for_timeout(700)
            sy = pg.evaluate("window.scrollY")
            clip = {"x": 0, "y": top - sy, "width": vw, "height": bot - top}
        y0 = clip["y"] if clip else 0.0
        y1 = clip["y"] + clip["height"] if clip else float(vh)
        x0 = clip["x"] if clip else 0.0
        x1 = clip["x"] + clip["width"] if clip else float(vw)
        if strip:                                    # the strip in viewport coordinates, where the viewport is parked
            sy = pg.evaluate("window.scrollY")
            y0, y1, x0, x1 = strip["top"] - sy, strip["bottom"] - sy, 0.0, float(vw)
            clip = {"x": 0, "y": y0, "width": vw, "height": y1 - y0}
        targets = []
        for t in a.target:
            needle, nth, exact = split_spec(t)
            inside = [h for h in find_all(needle, exact)
                      if h["y"] >= y0 and h["y"] + h["h"] <= y1 and h["x"] >= x0 and h["x"] + h["w"] <= x1]
            hit = (inside[-1] if nth == "last" else inside[int(nth) - 1] if len(inside) >= int(nth) else None) if inside else None
            if not hit:
                print(f"capture: target {t!r} not found inside the captured area", file=sys.stderr)
                return 2
            targets.append({"text": t[1:] if exact else t, "box": [round((hit["x"] - x0) * a.dpr, 1), round((hit["y"] - y0) * a.dpr, 1),
                                               round(hit["w"] * a.dpr, 1), round(hit["h"] * a.dpr, 1)]})
        drawn = None
        if strip:                                    # the strip's rows, images and empty logo slots (viewport px here)
            for _ in range(12):                      # an image still on its way gets up to 6 s
                drawn = pg.evaluate(JS_CONTENT, [x0, y0, x1, y1])
                if all(i_["ok"] for i_ in drawn["images"]):
                    break
                pg.wait_for_timeout(500)
        page_text = pg.evaluate("document.body.innerText")
        texts = pg.evaluate(JS_VISIBLE, [x0, y0, x1, y1])
        scroll_y = pg.evaluate("window.scrollY")
        final_url = pg.url
        if strip:
            pg.screenshot(path=str(png), full_page=True, clip={"x": 0, "y": strip["top"], "width": vw,
                                                               "height": strip["bottom"] - strip["top"]})
        elif clip:
            pg.screenshot(path=str(png), clip=clip)
        else:
            pg.screenshot(path=str(png))
        b.close()
    head = png.read_bytes()[:24]                       # PNG IHDR: width, height (this venv has no PIL)
    size = [int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")]
    side = {"schema": "rtv-cartoon-capture/2", "url": a.url, "final_url": final_url,
            "captured_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "viewport": [vw, vh], "dpr": a.dpr, "png_size": size, "sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
            "scroll_y": scroll_y, "clip_css": clip, "targets": targets, "visible_text": texts["visible"],
            "inside_text": texts["inside"], "page_text": page_text}
    if strip:
        def px(b_):                                  # a viewport box (where the viewport was parked) -> strip px
            return [round((b_[0] - x0) * a.dpr, 1), round((b_[1] - y0) * a.dpr, 1), round(b_[2] * a.dpr, 1), round(b_[3] * a.dpr, 1)]

        side.update(kind="strip", strip=strip,
                    boxes={n: [round((v[0]) * a.dpr, 1), round((v[1] - strip["top"]) * a.dpr, 1), round((v[2] - v[0]) * a.dpr, 1),
                               round((v[3] - v[1]) * a.dpr, 1)] for n, v in boxes.items()},
                    box_tags=box_tags,
                    content=sorted((px(c_[:4]) + [c_[4]] for c_ in drawn["content"]), key=lambda c_: (c_[1], c_[0])),
                    images=[{"box": px(i_["box"]), "ok": bool(i_["ok"]), "sym": i_["sym"]} for i_ in drawn["images"]],
                    empty_slots=[px(s_) for s_ in drawn["slots"]],
                    images_failed=sorted(set(x for x in failed_images if x)))
    side["seal"] = seal(side)
    (out / f"{a.name}.json").write_text(json.dumps(side, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"png": str(png), "size": size, "targets": targets}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
