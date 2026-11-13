"""One real take of an app feature on the live site at phone size, for the SHOWCASE series.

    SHOT_PY take.py --episode EPISODE.json --out TAKE_DIR [--resolve-only]

Records the CDP screencast (every composited frame, PNG at 1170x2532 = 390x844 css px at dpr 3, dark, guest, with its
timestamp) while the script runs the episode's `take.actions` with REAL touch taps (page.touchscreen.tap at the logged
centre of the control). Logs, per step, the DOM rects (css px, viewport space) of the episode's `rects` and of every
keep-out element (the part of it actually visible on the page, sampled with elementFromPoint), plus every visible
text node with its rect (the renderer's text gate projects these through its camera).

The stock page is opened only on a free route: /dashboard/<T>#from=<report id> (a stock opened from its own earnings
report spends no guest view). The day's ticker is read from the home page's own /api/pattern-showcase answer (the page
loads it; this script only listens). reducedMotion is "no-preference": under "reduce" the app skips its draw-on.

Writes TAKE_DIR/frames/%05d.png, TAKE_DIR/take.json ({resolve, url, steps[], taps[], frames[[i, ts]], ...}).
Exit 0 ok, 2 the page did not show what the episode needs (no pattern, no report link, a control missing).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in HERE.parents:
    if (p / "qa_header.py").is_file():
        sys.path.insert(0, str(p))
        break
import qa_header as qa  # noqa: E402

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
CHROME = os.path.expandvars(r"%LOCALAPPDATA%/ms-playwright/chromium-1234/chrome-win64/chrome.exe")
SITE = "https://www.rapidtradeview.trade"

# the inner scroller (the stock page scrolls inside <main>, not the document)
MARK_SCROLLER = """() => { let best = null, bh = 0; for (const e of document.querySelectorAll('body *')) {
  const cs = getComputedStyle(e); if (!/(auto|scroll)/.test(cs.overflowY)) continue; const d = e.scrollHeight - e.clientHeight;
  if (d > bh) { best = e; bh = d; } } if (best) best.setAttribute('data-take-scroller', '1'); return bh; }"""

# rects of named things + keep-out elements + every visible text node; "visible" = sampled with elementFromPoint,
# so a part scrolled under the opaque sticky header or off the viewport does not count
SNAPSHOT = r"""(spec) => {
  const VW = innerWidth, VH = innerHeight;
  const R = b => [Math.round(b.left * 100) / 100, Math.round(b.top * 100) / 100, Math.round(b.width * 100) / 100, Math.round(b.height * 100) / 100];
  const vis = (el) => {                      // visible bounding box of el, sampling a grid with elementFromPoint
    const b = el.getBoundingClientRect(); if (b.width <= 0 || b.height <= 0) return null;
    const x0 = Math.max(0, b.left), x1 = Math.min(VW, b.right), y0 = Math.max(0, b.top), y1 = Math.min(VH, b.bottom);
    if (x1 <= x0 || y1 <= y0) return null;
    let mx0 = 1e9, my0 = 1e9, mx1 = -1, my1 = -1, n = 0;
    const nx = Math.max(2, Math.min(24, Math.ceil((x1 - x0) / 6))), ny = Math.max(2, Math.min(24, Math.ceil((y1 - y0) / 4)));
    for (let i = 0; i <= nx; i++) for (let j = 0; j <= ny; j++) {
      const x = x0 + (x1 - x0) * (i / nx) * 0.999 + 0.0005, y = y0 + (y1 - y0) * (j / ny) * 0.999 + 0.0005;
      const h = document.elementFromPoint(x, y);
      if (h && (h === el || el.contains(h) || h.contains(el) && h.tagName === 'CANVAS')) { n++; mx0 = Math.min(mx0, x); my0 = Math.min(my0, y); mx1 = Math.max(mx1, x); my1 = Math.max(my1, y); }
    }
    if (!n) return null;
    return [Math.round(mx0 * 100) / 100, Math.round(my0 * 100) / 100, Math.round((mx1 - mx0) * 100) / 100, Math.round((my1 - my0) * 100) / 100];
  };
  const out = { named: {}, keepout: [], texts: [], scrollTop: null, t_wall: Date.now() / 1000 };
  const sc = document.querySelector('[data-take-scroller]'); if (sc) out.scrollTop = sc.scrollTop;
  for (const [name, sel] of Object.entries(spec.named)) {
    let el = null;
    if (sel.startsWith('text:')) {
      const needle = sel.slice(5); const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let nd;
      while ((nd = w.nextNode())) { if (nd.data.trim() === needle && nd.parentElement.checkVisibility()) { el = nd.parentElement; break; } }
    } else if (sel.startsWith('up:')) {        // up:N:selector = the Nth ancestor of selector
      const [, k, s] = sel.match(/^up:(\d+):(.*)$/); el = document.querySelector(s); for (let i = 0; el && i < +k; i++) el = el.parentElement;
    } else if (sel.startsWith('closest:')) {   // closest:ANCESTOR_SEL|SEL
      const [anc, s] = sel.slice(8).split('|'); el = document.querySelector(s); el = el && el.closest(anc);
    } else if (sel.startsWith('js:')) { el = (new Function('return ' + sel.slice(3)))();
    } else el = document.querySelector(sel);
    out.named[name] = el ? { rect: R(el.getBoundingClientRect()), visible: vis(el), text: (el.innerText || '').slice(0, 200) } : null;
  }
  // keep-out: elements whose own text matches a keep-out pattern, and the containers named in spec.keepout_sel
  const rx = spec.keepout_rx.map(s => new RegExp(s, 'i'));
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let nd;
  while ((nd = w.nextNode())) {
    const s = nd.data.trim(); if (!s) continue; const el = nd.parentElement; if (!el || !el.checkVisibility()) continue;
    const rg = document.createRange(); rg.selectNodeContents(nd); const rects = [...rg.getClientRects()].filter(b => b.width > 0 && b.height > 0);
    if (!rects.length) continue;
    const u = rects.reduce((a, b) => ({ left: Math.min(a.left, b.left), top: Math.min(a.top, b.top), right: Math.max(a.right, b.right), bottom: Math.max(a.bottom, b.bottom) }), { left: 1e9, top: 1e9, right: -1e9, bottom: -1e9 });
    const box = { left: u.left, top: u.top, width: u.right - u.left, height: u.bottom - u.top, right: u.right, bottom: u.bottom };
    if (box.bottom < 0 || box.top > VH || box.right < 0 || box.left > VW) continue;
    const v = vis(el);
    out.texts.push({ text: s.slice(0, 160), rect: R(box), visible: v });
    if (rx.some(r => r.test(s)) && v) out.keepout.push({ why: 'text: ' + s.slice(0, 60), rect: R(box), visible: v });
  }
  for (const [why, sel] of Object.entries(spec.keepout_sel)) {
    for (const el of document.querySelectorAll(sel)) { const v = vis(el); if (v) out.keepout.push({ why, rect: R(el.getBoundingClientRect()), visible: v }); }
  }
  for (const [why, needle] of Object.entries(spec.keepout_block || {})) {   // a heading's whole card/row: the heading's Nth ancestor
    const [txt, up] = needle; const w2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n2;
    while ((n2 = w2.nextNode())) { if (n2.data.trim().toLowerCase() !== txt.toLowerCase()) continue; let el = n2.parentElement; for (let i = 0; el && i < up; i++) el = el.parentElement;
      if (el) { const v = vis(el); if (v) out.keepout.push({ why, rect: R(el.getBoundingClientRect()), visible: v }); } }
  }
  return out;
}"""


def now_z() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TakeError(RuntimeError):
    pass


def resolve(pg, ep: dict) -> dict:
    """The day's showcase ticker, from the home page's own /api/pattern-showcase answer, and its report id."""
    got = {}

    def on_resp(r):
        if "/api/pattern-showcase" in r.url and "body" not in got:
            try:
                got["status"] = r.status
                got["body"] = r.json()
                got["url"] = r.url
            except Exception as e:  # noqa: BLE001
                got["error"] = str(e)
    pg.on("response", on_resp)
    pg.goto(SITE + "/", wait_until="domcontentloaded", timeout=60000)
    t_end = time.time() + 25
    while "body" not in got and "error" not in got and time.time() < t_end:
        pg.wait_for_timeout(250)
    pg.remove_listener("response", on_resp)
    if "body" not in got:
        raise TakeError(f"the home page did not load /api/pattern-showcase ({got})")
    tile = got["body"].get("tile") if isinstance(got["body"], dict) else None
    if not tile or not tile.get("ticker"):
        raise TakeError(f"no showcase tile today: {str(got['body'])[:400]}")
    ticker = tile["ticker"].upper()
    cp = tile.get("chart_pattern") or {}
    # the report id: the earnings-reports page's own link for that ticker (newest first)
    pg.goto(SITE + "/earnings/reports", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(1500)
    hrefs = pg.evaluate("""(t) => [...document.querySelectorAll('a[href^="/earnings/reports/' + t + '-"]')].map(a => a.getAttribute('href'))""",
                        ticker.lower())
    if not hrefs:
        raise TakeError(f"no earnings report link for {ticker}: the free #from route is not available")
    rid = hrefs[0].rsplit("/", 1)[1]
    return {"read_at": now_z(), "showcase_url": got["url"], "showcase_status": got["status"], "ticker": ticker,
            "pattern_name": cp.get("name"), "pattern_status": cp.get("status"), "chip": (cp.get("text") or {}).get("chip"),
            "report_id": rid, "report_links_seen": hrefs[:5], "tile": tile}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--resolve-only", action="store_true")
    ap.add_argument("--resolved", help="reuse a resolve.json (all takes of one build use the same ticker)")
    a = ap.parse_args()
    ep = json.loads(Path(a.episode).read_text(encoding="utf-8"))
    tk = ep["take"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log: list = []
    t0 = time.time()

    def mark(what, **kw):
        log.append({"t": round(time.time() - t0, 3), "wall": time.time(), "what": what, **kw})
        print(f"{log[-1]['t']:7.2f} {what}", flush=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME if Path(CHROME).is_file() else None, headless=True,
                              args=["--force-device-scale-factor=3", "--force_high_performance_gpu", "--use-angle=d3d11"])
        try:
            ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True,
                                has_touch=True, color_scheme="dark", reduced_motion="no-preference", user_agent=UA)
            qa.mark_browser(ctx)
            pg = ctx.new_page()
            if a.resolved:
                res = json.loads(Path(a.resolved).read_text(encoding="utf-8"))
            else:
                res = resolve(pg, ep)
                (out / "resolve.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
            mark(f"resolved {res['ticker']} {res['pattern_name']} / {res['chip']} report {res['report_id']}")
            if a.resolve_only:
                return 0
            pg.close()
            ctx.close()
            ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True,
                                has_touch=True, color_scheme="dark", reduced_motion="no-preference", user_agent=UA)
            qa.mark_browser(ctx)
            pg = ctx.new_page()
            fdir = out / "frames"
            fdir.mkdir(exist_ok=True)
            for f in fdir.glob("*.png"):
                f.unlink()
            frames: list = []
            cdp = ctx.new_cdp_session(pg)

            def on_frame(ev):
                i = len(frames)
                (fdir / f"{i:05d}.png").write_bytes(base64.b64decode(ev["data"]))
                frames.append([i, ev["metadata"].get("timestamp")])
                try:
                    cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
                except Exception:  # noqa: BLE001
                    pass
            cdp.on("Page.screencastFrame", on_frame)
            track = []
            pg.on("response", lambda r: track.append({"status": r.status, "body": r.request.post_data or ""})
                  if "search/track" in r.url else None)
            url = f"{SITE}/dashboard/{res['ticker']}#from={res['report_id']}"
            spec = {"named": tk["rects"], "keepout_rx": tk["keepout_rx"], "keepout_sel": tk.get("keepout_sel", {}),
                    "keepout_block": tk.get("keepout_block", {})}
            steps, taps, marks = [], [], {}
            cdp.send("Page.startScreencast", {"format": "png", "maxWidth": 1170, "maxHeight": 2532, "everyNthFrame": 1})
            mark("goto " + url)
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            for act in tk["actions"]:
                kind = act["do"]
                if kind == "wait_for":
                    pg.wait_for_selector(act["sel"], state="visible", timeout=act.get("timeout", 30000))
                    pg.wait_for_timeout(act.get("then_ms", 0))
                    mark("ready " + act["sel"])
                elif kind == "settle_network":
                    try:
                        pg.wait_for_load_state("networkidle", timeout=act.get("timeout", 15000))
                    except Exception:  # noqa: BLE001
                        pass
                    mark("network settled")
                elif kind == "jump_to":
                    # instant scroll: the card's top lands just under the sticky header (no scroll blur in the take)
                    pg.evaluate(MARK_SCROLLER)
                    info = pg.evaluate("""([sel, up, gap]) => { const sc = document.querySelector('[data-take-scroller]');
                        let el = document.querySelector(sel); if (el && typeof up === 'string') el = el.closest(up); else for (let i = 0; el && i < up; i++) el = el.parentElement;
                        if (!el || !sc) return null;
                        const hdr = [...document.querySelectorAll('header, [class*="sticky"]')].filter(h => { const b = h.getBoundingClientRect(); return b.top <= 1 && b.height > 30 && b.height < 200 && getComputedStyle(h).position.match(/sticky|fixed/); })
                          .map(h => h.getBoundingClientRect().bottom); const hb = hdr.length ? Math.max(...hdr) : 0;
                        const top = el.getBoundingClientRect().top; sc.scrollTop = sc.scrollTop + top - hb - gap;
                        return { header_bottom: hb, scrollTop: sc.scrollTop }; }""", [act["sel"], act.get("up", 0), act.get("gap", 6)])
                    if not info:
                        raise TakeError(f"jump_to: {act['sel']} or the scroller not found")
                    marks["jumped"] = time.time()
                    mark("jumped", **info)
                elif kind == "wait":
                    pg.wait_for_timeout(int(act["s"] * 1000))
                    mark(f"waited {act['s']} s")
                elif kind == "wait_until":
                    # wait until `s` seconds after a named moment (the jump, or a tap's dispatch): the episode's
                    # timeline sets these, so the take runs on the video's own clock
                    left = marks[act["since"]] + float(act["s"]) - time.time()
                    if left < -0.02:
                        mark(f"LATE by {-left:.3f} s for {act['since']}+{act['s']}")
                    if left > 0:
                        pg.wait_for_timeout(int(left * 1000))
                    mark(f"at {act['since']}+{float(act['s']):.3f}")
                elif kind == "snap":
                    s = pg.evaluate(SNAPSHOT, spec)
                    s["label"] = act["label"]
                    s["t"] = round(time.time() - t0, 3)
                    steps.append(s)
                    mark("snap " + act["label"], keepout=len(s["keepout"]))
                elif kind == "tap":
                    loc = pg.locator(act["sel"]).first
                    loc.wait_for(state="visible", timeout=10000)
                    bb = loc.bounding_box()
                    if not bb:
                        raise TakeError("tap target has no box: " + act["sel"])
                    x, y = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
                    label = loc.inner_text().strip()
                    w0 = time.time()
                    pg.touchscreen.tap(x, y)
                    w1 = time.time()
                    marks[act["name"]] = w0
                    taps.append({"name": act["name"], "sel": act["sel"], "label": label, "x": round(x, 2), "y": round(y, 2),
                                 "box": [round(bb["x"], 2), round(bb["y"], 2), round(bb["width"], 2), round(bb["height"], 2)],
                                 "wall0": w0, "wall1": w1, "t": round(w0 - t0, 3)})
                    mark(f"tap {act['name']} '{label}' at {x:.1f},{y:.1f}")
                else:
                    raise TakeError("unknown action " + kind)
            badge = pg.evaluate(r"""() => { const t = document.body.innerText.match(/^\s*(\d)\/(\d)\s*$/m); return t ? t[0].trim() : null; }""")
            mark(f"badge {badge}")
            cdp.send("Page.stopScreencast")
            pg.wait_for_timeout(300)
            pg.close()
            ctx.close()
        finally:
            b.close()
    take = {"captured_at": now_z(), "url": url, "viewport_css": [390, 844], "dpr": 3, "color_scheme": "dark",
            "reduced_motion": "no-preference", "resolve": res, "log": log, "steps": steps, "taps": taps,
            "search_track": track, "guest_badge_end": badge, "frames": frames, "t0_wall": t0,
            "frame_size": [1170, 2532], "chrome_args": ["--force-device-scale-factor=3", "--force_high_performance_gpu",
                                                        "--use-angle=d3d11"]}
    (out / "take.json").write_text(json.dumps(take, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"frames": len(frames), "taps": len(taps), "steps": len(steps), "track": track, "badge": badge}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TakeError as e:
        print("TAKE ERROR:", e, file=sys.stderr)
        sys.exit(2)
