"""Capture the live RapidTradeView pages the Congress walkthrough video shows: desktop width, real data, no redraw.

Runs in the isolated Playwright venv (never the conda env, never system python):
    <media>/.ops/cache/shot-venv/Scripts/python.exe -I capture_walkthrough.py --out <run>/screens

One browser session, as a guest (never signed in), 1920x1080 CSS px at --dpr (default 2), dark scheme, a normal desktop
Chrome user agent (the headless one is refused by the API and the header then shows "Service unavailable"):
  1. /congress-trades
  2. the member page, opened by clicking the member's link on /congress-trades
  3. the stock page, opened by clicking the ticker's link on the member page (a guest stock view: guests get 2 a day
     per address, so this script loads it exactly once)

For each page it writes, under --out:
  <page>.json    url, final_url, captured_at (UTC), viewport, dpr, page_height (CSS px), page_text, the index of every drawn
                 text line ({t, x, y, w, h} in document CSS px), every link ({t, href, box}), the guest badge text, and
                 the tiles below. `problems` lists loading words, error words or a missing require text: a page with
                 problems makes the script exit 2 (No Fallbacks: the video is not built from it).
  <page>_<k>.png tiles of the page at full width: tile k covers document CSS y [k*STEP, k*STEP + TILE] (TILE 3000,
                 STEP 1500), so any window up to 1500 CSS px tall lies whole inside one tile. Pixels untouched.

The guest intro panel is dismissed first (its close button). A page that still shows a loading word, an error, or the
"Service unavailable" badge stops the capture.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # tools/: qa_header
import qa_header as qa  # noqa: E402

SITE = "https://www.rapidtradeview.trade"
TILE, STEP = 3000, 1500
BAD_WORDS = ("Loading", "loading…", "Service unavailable", "Something went wrong", "Failed to load", "Try again",
             "Sign in to see", "daily limit", "Daily limit", "limit reached")

JS_INDEX = r"""() => {
  const lines = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const drawn = (e) => e.checkVisibility ? e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) : true;
  let n;
  while ((n = w.nextNode())) {
    const t = n.data.replace(/\s+/g, ' ').trim();
    if (!t || !n.parentElement || !drawn(n.parentElement)) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    const rs = [...r.getClientRects()].filter(b => b.width >= 1 && b.height >= 1);
    if (!rs.length) continue;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const b of rs) { x0 = Math.min(x0, b.left); y0 = Math.min(y0, b.top); x1 = Math.max(x1, b.right); y1 = Math.max(y1, b.bottom); }
    lines.push({t, x: x0 + scrollX, y: y0 + scrollY, w: x1 - x0, h: y1 - y0,
                rows: rs.map(b => [b.left + scrollX, b.top + scrollY, b.width, b.height])});
  }
  const links = [...document.querySelectorAll('a')].filter(drawn).map(a => {
    const b = a.getBoundingClientRect();
    return {t: (a.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80), href: a.getAttribute('href'),
            box: [b.left + scrollX, b.top + scrollY, b.width, b.height]};
  }).filter(l => l.box[2] >= 1 && l.box[3] >= 1);
  const els = {};
  for (const [name, sel] of Object.entries(window.__rtvBoxes || {})) {
    const e = document.querySelector(sel); if (!e) continue;
    const b = e.getBoundingClientRect(); els[name] = [b.left + scrollX, b.top + scrollY, b.width, b.height];
  }
  return {lines, links, els};
}"""

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 "
      "Safari/537.36")


def settle(pg, rounds: int = 1) -> None:
    """Scroll through the page so lazy panels and charts are drawn, then back to the top."""
    for _ in range(rounds):
        h = pg.evaluate("document.documentElement.scrollHeight")
        y = 0
        while y < h:
            pg.evaluate("(y) => window.scrollTo(0, y)", y)
            pg.wait_for_timeout(400)
            y += 700
            h = pg.evaluate("document.documentElement.scrollHeight")
    pg.wait_for_timeout(2000)
    pg.evaluate("window.scrollTo(0, 0)")
    pg.wait_for_timeout(1200)


def dismiss_intro(pg) -> None:
    """Close the guest introduction banner only (FirstOpenBanner). The app suggestion card stays: the video shows it."""
    loc = pg.locator('button[aria-label="Dismiss introduction"]')
    for i in range(loc.count()):
        el = loc.nth(i)
        try:
            if el.is_visible():
                el.click()
                pg.wait_for_timeout(800)
        except Exception:  # noqa: BLE001 - a banner that went away by itself is fine
            pass


# Data-provider names that must never be on screen (owner rule). A screen that shows one is framed so the camera never
# shows that line; the builder checks every framed window against these lines.
PROVIDERS = ("reddit", "vader", "elbstream", "yahoo", "finnhub", "stocktwits", "apewisdom", "google news", "quiver",
             "capitol trades", "unusual whales", "benzinga", "polygon", "alpha vantage", "marketbeat", "openinsider")

JS_SCROLLER = r"""() => {
  let best = null;
  for (const e of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(e);
    if (!/(auto|scroll)/.test(cs.overflowY) || e.scrollHeight <= e.clientHeight + 50) continue;
    if (!best || e.scrollHeight > best.scrollHeight) best = e;
  }
  if (best) best.setAttribute('data-rtv-scroller', '1');
  return best ? {sh: best.scrollHeight, ch: best.clientHeight, top: best.getBoundingClientRect().top} : null;
}"""

JS_HEADING_TOP = r"""([text, minTop]) => {
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (n.data.replace(/\s+/g, ' ').trim() !== text) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    const b = r.getBoundingClientRect();
    if (b.height >= 1 && b.top > minTop) return b.top;
  }
  return null;
}"""


def screen(pg, name: str, out: Path, dpr: int, require: list[str]) -> dict:
    """One real 1920x1080 screen as the visitor sees it (a page that scrolls inside a container: the stock page)."""
    idx = pg.evaluate(JS_INDEX)
    text = pg.evaluate("document.body.innerText")
    png = out / f"{name}.png"
    pg.screenshot(path=str(png))
    shown = [ln for ln in idx["lines"] if ln["y"] + ln["h"] > 0 and ln["y"] < 1080]
    problems = [f"shows {w!r}" for w in BAD_WORDS if any(w in ln["t"] for ln in shown)]
    problems += [f"misses {r!r}" for r in require if not any(r in ln["t"] for ln in shown)]
    providers = [ln for ln in shown if any(pv in ln["t"].lower() for pv in PROVIDERS)]
    side = {"schema": "rtv-walkthrough-capture/1", "name": name, "kind": "screen", "url": pg.url, "final_url": pg.url,
            "captured_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "viewport": [1920, 1080], "dpr": dpr, "page_height": 1080, "tile": 1080, "step": 1080,
            "tiles": [{"file": png.name, "top": 0, "bottom": 1080, "sha256": hashlib.sha256(png.read_bytes()).hexdigest()}],
            "problems": problems, "provider_lines": providers, "lines": shown, "links": idx["links"], "page_text": text}
    (out / f"{name}.json").write_text(json.dumps(side, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(json.dumps({"screen": name, "problems": problems, "provider_lines": [ln["t"] for ln in providers]},
                     ensure_ascii=False), flush=True)
    return side


def snapshot(pg, name: str, out: Path, dpr: int, require: list[str]) -> dict:
    settle(pg)
    idx = pg.evaluate(JS_INDEX)
    height = pg.evaluate("document.documentElement.scrollHeight")
    text = pg.evaluate("document.body.innerText")
    problems = [f"shows {w!r}" for w in BAD_WORDS if w in text]
    problems += [f"misses {r!r}" for r in require if r not in text]
    pinned = pg.evaluate("""() => [...document.querySelectorAll('body *')].filter(e => {
        const cs = getComputedStyle(e); return cs.position === 'fixed' && cs.display !== 'none' && cs.visibility !== 'hidden'
          && e.getBoundingClientRect().width > 4 && e.getBoundingClientRect().height > 4; })
        .map(e => (e.innerText || e.tagName).replace(/\\s+/g, ' ').slice(0, 60))""")
    tiles = []
    k = 0
    while k * STEP < height:
        top = k * STEP
        bot = min(height, top + TILE)
        png = out / f"{name}_{k}.png"
        pg.screenshot(path=str(png), full_page=True, clip={"x": 0, "y": top, "width": 1920, "height": bot - top})
        tiles.append({"file": png.name, "top": top, "bottom": bot,
                      "sha256": hashlib.sha256(png.read_bytes()).hexdigest()})
        if bot >= height:
            break
        k += 1
    badge = [ln["t"] for ln in idx["lines"] if ln["y"] < 70 and "/" in ln["t"] and len(ln["t"]) <= 6]
    side = {"schema": "rtv-walkthrough-capture/1", "name": name, "url": pg.url, "final_url": pg.url,
            "captured_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "viewport": [1920, 1080], "dpr": dpr, "page_height": height, "tile": TILE, "step": STEP, "tiles": tiles,
            "guest_badge": badge, "fixed_elements": pinned, "problems": problems,
            "lines": idx["lines"], "links": idx["links"], "page_text": text}
    (out / f"{name}.json").write_text(json.dumps(side, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(json.dumps({"page": name, "url": pg.url, "height": height, "tiles": len(tiles), "badge": badge,
                      "fixed": pinned, "problems": problems}), flush=True)
    return side


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--member", default="/smart-money/figures/nancy-pelosi", help="the member page (its link on /congress-trades)")
    ap.add_argument("--ticker", default="NVDA", help="the stock opened from the member page")
    ap.add_argument("--dpr", type=int, default=2)
    ap.add_argument("--skip-stock", action="store_true", help="do not open the stock page (saves the guest view)")
    ap.add_argument("--chromium", default=os.path.expandvars(r"%LOCALAPPDATA%/ms-playwright/chromium-1234/chrome-win64/chrome.exe"))
    a = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=a.chromium if Path(a.chromium).is_file() else None, headless=True)
        ctx = b.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=a.dpr, color_scheme="dark",
                            user_agent=UA, locale="en-US", timezone_id="America/New_York")
        qa.mark_browser(ctx)                         # our own capture: not a visitor
        pg = ctx.new_page()
        r = pg.goto(SITE + "/congress-trades", wait_until="networkidle", timeout=90000)
        if not r or r.status != 200:
            print(f"capture: /congress-trades returned {r.status if r else 'nothing'}", file=sys.stderr)
            return 2
        pg.wait_for_timeout(2500)
        dismiss_intro(pg)
        side = snapshot(pg, "congress", out, a.dpr, ["Congress stock trades tracker", "Most active members of Congress",
                                                    "Most bought stocks by Congress", "Latest disclosures"])
        bad += bool(side["problems"])

        link = pg.locator(f'a[href="{a.member}"]').first
        link.scroll_into_view_if_needed()
        with pg.expect_navigation(wait_until="networkidle", timeout=90000):
            link.click()
        pg.wait_for_timeout(2500)
        dismiss_intro(pg)
        side = snapshot(pg, "member", out, a.dpr, ["stock trades", "Disclosed trades", "BUYS", "SELLS"])
        bad += bool(side["problems"])

        if not a.skip_stock:
            link = pg.locator(f'a[href="/dashboard/{a.ticker}"]').first
            link.scroll_into_view_if_needed()
            with pg.expect_navigation(wait_until="networkidle", timeout=90000):
                link.click()
            pg.wait_for_timeout(6000)
            dismiss_intro(pg)
            sc = pg.evaluate(JS_SCROLLER)            # the stock page scrolls inside a container, not the document
            if not sc:
                print("capture: the stock page has no scroll container", file=sys.stderr)
                return 2
            scroll = "document.querySelector('[data-rtv-scroller]')"
            for y in range(0, sc["sh"], 600):        # draw the lazy panels
                pg.evaluate(f"(y) => {{ {scroll}.scrollTop = y; }}", y)
                pg.wait_for_timeout(450)
            pg.wait_for_timeout(2500)
            pg.evaluate(f"{scroll}.scrollTop = 0")
            pg.wait_for_timeout(1500)
            side = screen(pg, "stock_top", out, a.dpr, [a.ticker, "Close"])
            bad += bool(side["problems"])
            top = pg.evaluate(JS_HEADING_TOP, ["Smart Money", 300])
            if top is None:
                print("capture: no Smart Money section on the stock page", file=sys.stderr)
                return 2
            pg.evaluate(f"(d) => {{ {scroll}.scrollTop += d; }}", top - 175)   # the heading just under the sticky bar
            pg.wait_for_timeout(1500)
            side = screen(pg, "stock_smart", out, a.dpr, ["Smart Money", "notable figures"])
            bad += bool(side["problems"])
        b.close()
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
