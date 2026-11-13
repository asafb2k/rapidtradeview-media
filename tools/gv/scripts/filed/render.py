"""Frame stepper for the FILED. scene: Chromium (discrete GPU, ANGLE d3d11) steps window.renderFrame(t) and every frame
is piped to the full ffmpeg as PNG (lossless into x264 at CRF 14), and saved as PNG where asked.

    python render.py --run RUN_DIR --ffmpeg FFMPEG.exe [--frames-dir DIR] [--only 0,75,...] [--sheet-only]

Files are served from a fake origin (http://filed.local/...) through Playwright routing, so ES modules load without a
web server: /web/* = this folder's web/, /three/* = the three.js package, /fonts/* = the font folder, /run/* = RUN_DIR.
Writes RUN_DIR/video_noaudio.mp4 and RUN_DIR/frames.json ({renderer, fps, frames: [{i, t, mark: [x,y,w,h]}]}).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import subprocess
import time
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
CHROME = Path.home() / "AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe"


def _media_root() -> Path:
    for p in HERE.parents:
        if (p / ".ops" / "cache").is_dir():
            return p
    raise SystemExit("no .ops/cache above render.py")


CACHE = _media_root() / ".ops" / "cache"
ROOTS = {"web": HERE / "web", "three": CACHE / "filed-node" / "node_modules" / "three", "fonts": CACHE / "filed-fonts"}


async def run(args) -> dict:
    run_dir = Path(args.run).resolve()
    roots = dict(ROOTS, run=run_dir)
    spec = json.loads((run_dir / "render.json").read_text(encoding="utf-8"))
    fps, dur = spec["fps"], spec["duration"]
    n = int(round(dur * fps))
    only = [int(x) for x in args.only.split(",")] if args.only else None

    async def route(r):
        url = r.request.url.split("?")[0]
        rest = url.split("http://filed.local/", 1)[1]
        top, _, sub = rest.partition("/")
        p = roots.get(top)
        f = (p / sub) if p else None
        if not f or not f.is_file():
            await r.fulfill(status=404, body="missing " + rest)
            return
        ct = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if f.suffix == ".js":
            ct = "text/javascript"
        await r.fulfill(status=200, body=f.read_bytes(), headers={"content-type": ct, "access-control-allow-origin": "*"})

    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=str(CHROME), args=[
            "--headless=new", "--force_high_performance_gpu", "--use-angle=d3d11", "--enable-gpu",
            "--ignore-gpu-blocklist", "--disable-gpu-vsync"])
        pg = await b.new_page(viewport={"width": spec["W"], "height": spec["H"]}, device_scale_factor=1)
        logs = []
        pg.on("console", lambda m: logs.append(m.text))
        pg.on("pageerror", lambda e: logs.append("PAGEERROR " + str(e)))
        await pg.route("http://filed.local/**", route)
        await pg.goto("http://filed.local/web/scene.html")
        try:
            await pg.wait_for_function("window.sceneReady === true || window.sceneError", timeout=120000)
        except Exception:
            raise SystemExit("scene did not load: " + " | ".join(logs[-20:]))
        err = await pg.evaluate("window.sceneError || null")
        if err:
            raise SystemExit("scene error: " + str(err) + " | " + " | ".join(logs[-20:]))
        rend = await pg.evaluate("window.glRenderer")
        out_png = Path(args.frames_dir) if args.frames_dir else None
        if out_png:
            out_png.mkdir(parents=True, exist_ok=True)
        ff = None
        if not only:
            ff = subprocess.Popen([args.ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "png",
                                   "-framerate", str(fps), "-i", "pipe:0", "-c:v", "libx264", "-preset", "slow",
                                   "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart",
                                   str(run_dir / "video_noaudio.mp4")], stdin=subprocess.PIPE)
        frames = []
        t0 = time.time()
        idx = only if only else range(n)
        save = set(int(x) for x in args.save.split(",")) if args.save else set()
        for i in idx:
            t = i / fps
            info = await pg.evaluate(f"window.renderFrame({t})")
            png = await pg.screenshot(type="png")
            if ff:
                ff.stdin.write(png)
            if out_png and (only or i in save):
                (out_png / f"f{i:04d}.png").write_bytes(png)
            frames.append({"i": i, "t": round(t, 4), **(info or {})})
        if ff:
            ff.stdin.close()
            ff.wait()
        el = time.time() - t0
        await b.close()
    res = {"renderer": rend, "fps": fps, "n": len(frames), "seconds": round(el, 1),
           "render_fps": round(len(frames) / max(el, 1e-6), 2), "frames": frames,
           "console": [l for l in logs if "PAGEERROR" in l or "rror" in l][:20]}
    if not only:
        (run_dir / "frames.json").write_text(json.dumps(res, indent=0), encoding="utf-8")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--ffmpeg", required=True)
    ap.add_argument("--frames-dir")
    ap.add_argument("--only", help="render only these frame indices (to PNG, no video)")
    ap.add_argument("--save", help="while rendering the video, also save these frame indices as PNG")
    a = ap.parse_args()
    r = asyncio.run(run(a))
    print(json.dumps({k: v for k, v in r.items() if k != "frames"}))


if __name__ == "__main__":
    main()
