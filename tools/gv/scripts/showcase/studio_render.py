"""Frame stepper for the SHOWCASE studio look (studio/studio.js) on the RTX 4090 (Chromium, ANGLE d3d11).

    shot-venv python studio_render.py probe  --run RUN_DIR --req probe_req.json --out probe_res.json
    shot-venv python studio_render.py render --run RUN_DIR --plan plan.json --ffmpeg FFMPEG.exe [--save-dir DIR]

probe: measurements of a list of cfgs (no pixels). render: every frame's sub-frames are drawn at 2x, averaged in linear
light on the GPU, box-reduced 2:1 with the overlay composited, read back from the WebGL target (no page screenshots) and
piped raw to x264 (BT.709 tagged). Frames listed in plan["save"] are also written as lossless PNG.
Fake origin http://studio.local/: /studio/* scene, /three/*, /fonts/*, /hdri/*, /brand/brand-mark.json, /run/* = RUN_DIR,
/take/* = the take's frame PNGs (plan or scene.json "take_frames").
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import mimetypes
import subprocess
import time
from pathlib import Path

import numpy as np
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
CHROME = Path.home() / "AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe"
BRAND = Path("D:/Coding_projects/rapidtradeview/shared/data/brand-mark.json")      # read only


def _media_root() -> Path:
    for p in HERE.parents:
        if (p / ".ops" / "cache").is_dir():
            return p
    raise SystemExit("no .ops/cache above studio_render.py")


CACHE = _media_root() / ".ops" / "cache"


async def open_scene(p, run_dir: Path):
    scene = json.loads((run_dir / "scene.json").read_text(encoding="utf-8"))
    roots = {"studio": HERE / "studio", "three": CACHE / "filed-node" / "node_modules" / "three",
             "fonts": CACHE / "filed-fonts", "hdri": CACHE / "hdri-polyhaven", "run": run_dir,
             "take": Path(scene["take_frames"])}

    async def route(r):
        rest = r.request.url.split("?")[0].split("http://studio.local/", 1)[1]
        if rest == "brand/brand-mark.json":
            f = BRAND
        else:
            top, _, sub = rest.partition("/")
            f = roots[top] / sub if top in roots else None
        if not f or not f.is_file():
            await r.fulfill(status=404, body="missing " + rest)
            return
        ct = "text/javascript" if f.suffix == ".js" else (mimetypes.guess_type(str(f))[0] or "application/octet-stream")
        await r.fulfill(status=200, body=f.read_bytes(), headers={"content-type": ct})

    b = await p.chromium.launch(executable_path=str(CHROME), args=[
        "--headless=new", "--force_high_performance_gpu", "--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist",
        "--disable-gpu-vsync"])
    pg = await b.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=2)
    logs: list[str] = []
    pg.on("console", lambda m: logs.append(m.text))
    pg.on("pageerror", lambda e: logs.append("PAGEERROR " + str(e)))
    await pg.route("http://studio.local/**", route)
    await pg.goto("http://studio.local/studio/studio.html")
    try:
        await pg.wait_for_function("window.sceneReady === true || window.sceneError", timeout=120000)
    except Exception:
        await b.close()
        raise SystemExit("scene did not load: " + " | ".join(logs[-20:]))
    err = await pg.evaluate("window.sceneError || null")
    if err:
        await b.close()
        raise SystemExit("scene error: " + str(err) + " | " + " | ".join(logs[-20:]))
    return b, pg, logs


async def probe(a) -> dict:
    run_dir = Path(a.run).resolve()
    req = json.loads(Path(a.req).read_text(encoding="utf-8"))
    async with async_playwright() as p:
        b, pg, logs = await open_scene(p, run_dir)
        try:
            t0 = time.time()
            out = []
            for i in range(0, len(req), 400):
                out += await pg.evaluate("c => window.probeMany(c)", req[i:i + 400])
            mm = await pg.evaluate("window.phoneMM")
        finally:
            await b.close()
    res = {"n": len(out), "seconds": round(time.time() - t0, 2), "phone_mm": mm, "res": out}
    Path(a.out).write_text(json.dumps(res), encoding="utf-8")
    return {k: v for k, v in res.items() if k != "res"}


async def render(a) -> dict:
    run_dir = Path(a.run).resolve()
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    frames = plan["frames"]
    save = set(plan.get("save", []))
    save_dir = Path(a.save_dir) if a.save_dir else run_dir / "frames"
    save_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = Path(plan["out"])
    ff = None
    if not plan.get("no_video"):
        ff = subprocess.Popen([a.ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1080x1920",
                               "-framerate", str(plan["fps"]), "-i", "pipe:0", "-vf",
                               "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
                               "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv", "-c:v", "libx264",
                               "-preset", "slow", "-crf", str(plan.get("crf", 17)), "-tune", "film",
                               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                               "-color_range", "tv", "-movflags", "+faststart", str(out_mp4)], stdin=subprocess.PIPE)
    from PIL import Image
    meta = []
    async with async_playwright() as p:
        b, pg, logs = await open_scene(p, run_dir)
        try:
            gpu = await pg.evaluate("window.glRenderer")
            fb = await pg.evaluate("window.floatBlend")
            t0 = time.time()
            for fr in frames:
                r = await pg.evaluate("j => window.frame(j)", {"subs": fr["subs"], "ov": fr.get("ov", {})})
                a8 = np.frombuffer(base64.b64decode(r["b64"]), np.uint8).reshape(1920, 1080, 4)[::-1, :, :3]
                if ff:
                    ff.stdin.write(np.ascontiguousarray(a8).tobytes())
                if fr["i"] in save:
                    Image.fromarray(a8).save(save_dir / f"f{fr['i']:04d}.png", compress_level=1)
                m = r["m"]
                m.pop("pts", None)
                meta.append({"i": fr["i"], **m})
                if fr["i"] % 30 == 0:
                    print(f"frame {fr['i']} subs {m['subs']} {m['ms']} ms  elapsed {time.time() - t0:.0f}s", flush=True)
            elapsed = time.time() - t0
        finally:
            await b.close()
    if ff:
        ff.stdin.close()
        ff.wait()
    res = {"gpu": gpu, "float_blend": fb, "n": len(meta), "seconds": round(elapsed, 1),
           "sec_per_frame": round(elapsed / max(1, len(meta)), 3),
           "console": [x for x in logs if "rror" in x or "PAGEERROR" in x][:20], "frames": meta}
    (Path(a.plan).with_name(Path(a.plan).stem + "_result.json")).write_text(json.dumps(res), encoding="utf-8")
    return {k: v for k, v in res.items() if k != "frames"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["probe", "render"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--req")
    ap.add_argument("--out")
    ap.add_argument("--plan")
    ap.add_argument("--ffmpeg")
    ap.add_argument("--save-dir")
    a = ap.parse_args()
    r = asyncio.run(probe(a) if a.mode == "probe" else render(a))
    print(json.dumps(r))


if __name__ == "__main__":
    main()
