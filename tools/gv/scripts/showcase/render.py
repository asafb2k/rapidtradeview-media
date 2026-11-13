"""Frame stepper for the SHOWCASE scene: Chromium (discrete GPU, ANGLE d3d11) awaits window.renderFrame(i) and every
frame is piped to the full ffmpeg as PNG (x264, CRF 16), or saved as PNG (--only).

    python render.py --run RUN_DIR --ffmpeg FFMPEG.exe [--frames-dir DIR] [--only 0,60,...] [--save 0,120,...]

Fake origin http://showcase.local/: /web/* = web/, /three/* = three.js, /fonts/* = the OFL fonts, /run/* = RUN_DIR,
/take/* = RUN_DIR/take/frames (the recorded screen). Writes RUN_DIR/video_noaudio.mp4 and RUN_DIR/frames.json
(--probe: the camera and overlay framing of every frame, no pixels: RUN_DIR/probe.json).
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
    roots = dict(ROOTS, run=run_dir, take=run_dir / "take" / "frames")
    spec = json.loads((run_dir / "render.json").read_text(encoding="utf-8"))
    fps = spec["fps"]
    n = len(spec["track"])
    only = [int(x) for x in args.only.split(",")] if args.only else None

    async def route(r):
        rest = r.request.url.split("?")[0].split("http://showcase.local/", 1)[1]
        top, _, sub = rest.partition("/")
        p = roots.get(top)
        f = (p / sub) if p else None
        if not f or not f.is_file():
            await r.fulfill(status=404, body="missing " + rest)
            return
        ct = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if f.suffix == ".js":
            ct = "text/javascript"
        await r.fulfill(status=200, body=f.read_bytes(), headers={"content-type": ct})

    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=str(CHROME), args=[
            "--headless=new", "--force_high_performance_gpu", "--use-angle=d3d11", "--enable-gpu",
            "--ignore-gpu-blocklist", "--disable-gpu-vsync"])
        try:
            pg = await b.new_page(viewport={"width": spec["W"], "height": spec["H"]}, device_scale_factor=1)
            logs = []
            pg.on("console", lambda m: logs.append(m.text))
            pg.on("pageerror", lambda e: logs.append("PAGEERROR " + str(e)))
            await pg.route("http://showcase.local/**", route)
            await pg.goto("http://showcase.local/web/scene.html")
            try:
                await pg.wait_for_function("window.sceneReady === true || window.sceneError", timeout=120000)
            except Exception:
                raise SystemExit("scene did not load: " + " | ".join(logs[-20:]))
            err = await pg.evaluate("window.sceneError || null")
            if err:
                raise SystemExit("scene error: " + str(err) + " | " + " | ".join(logs[-20:]))
            rend = await pg.evaluate("window.glRenderer")
            if args.probe:
                t0 = time.time()
                fr = await pg.evaluate(f"[...Array({n}).keys()].map(i => window.probeFrame(i))")
                (run_dir / "probe.json").write_text(json.dumps({"n": n, "frames": fr}), encoding="utf-8")
                return {"renderer": rend, "probe": True, "n": n, "seconds": round(time.time() - t0, 2)}
            out_png = Path(args.frames_dir) if args.frames_dir else None
            if out_png:
                out_png.mkdir(parents=True, exist_ok=True)
            ff = None
            if not only:
                ff = subprocess.Popen([args.ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "png",
                                       "-framerate", str(fps), "-i", "pipe:0", "-c:v", "libx264", "-preset", "slow",
                                       "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart",
                                       str(run_dir / "video_noaudio.mp4")], stdin=subprocess.PIPE)
            frames = []
            t0 = time.time()
            save = set(int(x) for x in args.save.split(",")) if args.save else set()
            el = await pg.query_selector("#out")
            for i in (only if only else range(n)):
                info = await pg.evaluate(f"window.renderFrame({i})")
                png = await el.screenshot(type="png")
                if ff:
                    ff.stdin.write(png)
                if out_png and (only or i in save):
                    (out_png / f"f{i:04d}.png").write_bytes(png)
                frames.append({"i": i, **(info or {})})
            if ff:
                ff.stdin.close()
                ff.wait()
            elapsed = time.time() - t0
        finally:
            await b.close()
    res = {"renderer": rend, "fps": fps, "n": len(frames), "seconds": round(elapsed, 1),
           "render_fps": round(len(frames) / max(elapsed, 1e-6), 2), "frames": frames,
           "console": [l for l in logs if "PAGEERROR" in l or "rror" in l][:20]}
    name = "frames.json" if not only else "frames_only.json"
    (run_dir / name).write_text(json.dumps(res), encoding="utf-8")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--ffmpeg", required=True)
    ap.add_argument("--frames-dir")
    ap.add_argument("--only")
    ap.add_argument("--save")
    ap.add_argument("--probe", action="store_true", help="camera/overlay framing only, no render: RUN_DIR/probe.json")
    a = ap.parse_args()
    r = asyncio.run(run(a))
    print(json.dumps({k: v for k, v in r.items() if k != "frames"}))


if __name__ == "__main__":
    main()
