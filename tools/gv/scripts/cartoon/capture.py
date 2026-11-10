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
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


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
        pg = ctx.new_page()

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
        page_text = pg.evaluate("document.body.innerText")
        texts = pg.evaluate(JS_VISIBLE, [x0, y0, x1, y1])
        scroll_y = pg.evaluate("window.scrollY")
        final_url = pg.url
        pg.screenshot(path=str(png), clip=clip) if clip else pg.screenshot(path=str(png))
        b.close()
    head = png.read_bytes()[:24]                       # PNG IHDR: width, height (this venv has no PIL)
    size = [int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")]
    side = {"schema": "rtv-cartoon-capture/2", "url": a.url, "final_url": final_url,
            "captured_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "viewport": [vw, vh], "dpr": a.dpr, "png_size": size, "sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
            "scroll_y": scroll_y, "clip_css": clip, "targets": targets, "visible_text": texts["visible"],
            "inside_text": texts["inside"], "page_text": page_text}
    side["seal"] = seal(side)
    (out / f"{a.name}.json").write_text(json.dumps(side, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"png": str(png), "size": size, "targets": targets}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
