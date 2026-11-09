"""Local TTS with word timings for the cartoon-short pilot.

Engine: Kokoro-82M (hexgrad, Apache-2.0) via the `kokoro` package (KPipeline,
misaki G2P). Word timings are the engine's own predicted phoneme durations
(KPipeline token start_ts/end_ts), so they are engine-exact for the audio it
produced, not estimated.

Run with the isolated venv (never the conda env or system python; cartoon_reel.py calls it in --batch mode):
  D:/Coding_projects/rapidtradeview-media/.ops/cache/tts-venv/Scripts/python.exe tts.py \
      --text "..." --voice narrator --out out.wav --timings out.json

Output: 24 kHz mono 16-bit wav + JSON [{"word", "start", "end"}] in seconds.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

def _ops_cache() -> Path:
    """<media repo>/.ops/cache: $RTV_OPS_CACHE, else the first parent folder that has .ops/cache (a worktree under
    .worktrees/ finds the main checkout's)."""
    env = os.environ.get("RTV_OPS_CACHE")
    if env:
        return Path(env)
    for p in Path(__file__).resolve().parents:
        if (p / ".ops" / "cache").is_dir():
            return p / ".ops" / "cache"
    raise SystemExit("no .ops/cache found above tts.py (set RTV_OPS_CACHE)")


CACHE = _ops_cache()
os.environ.setdefault("HF_HOME", str(CACHE / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
HF_SNAP = CACHE / "hf" / "hub" / "models--hexgrad--Kokoro-82M" / "snapshots"
import warnings
warnings.filterwarnings("ignore")

SR = 24000

# Character presets -> (kokoro voice id, lang code, speed).
# Any raw Kokoro voice id (e.g. af_bella, bm_george) is also accepted.
VOICES = {
    "narrator": ("af_heart", "a", 1.0),        # warm female storyteller (top-graded voice)
    "narrator_uk": ("bm_george", "b", 0.95),   # British male storybook narrator
    "trader": ("am_michael", "a", 0.88),       # tired trader: low male, slowed
    "friend": ("am_puck", "a", 1.12),          # excited friend: bright male, faster
    "friend_f": ("af_bella", "a", 1.1),        # excited friend, female
    "deadpan": ("am_onyx", "a", 0.95),         # flat low male for "ding." beats
}


def resolve_voice(name: str):
    if name in VOICES:
        return VOICES[name]
    # raw kokoro id: first letter is the language code (a=US, b=UK)
    if len(name) > 3 and name[2] == "_" and name[0] in "ab":
        return (name, name[0], 1.0)
    raise SystemExit(f"unknown voice {name!r}; presets: {', '.join(VOICES)} or a raw Kokoro id")


def group_words(tokens, offset: float):
    """Group misaki tokens into whitespace-delimited words with timings.

    Tokens without a following space are glued to the next token ("$", "41",
    "%" or "do", "n't"), punctuation stays attached to its word for captions.
    """
    words, cur = [], None
    for t in tokens:
        if cur is None:
            cur = {"text": "", "start": None, "end": None}
        cur["text"] += t.text
        has_sound = any(ch.isalnum() for ch in t.text)
        if t.start_ts is not None and has_sound:
            if cur["start"] is None:
                cur["start"] = t.start_ts
            if t.end_ts is not None:
                cur["end"] = t.end_ts
        if t.whitespace:
            words.append(cur)
            cur = None
    if cur is not None:
        words.append(cur)

    out = []
    for w in words:
        text = w["text"].strip()
        if not text:
            continue
        if w["start"] is None:
            # pure punctuation (e.g. a lone "-"): glue to the previous word
            if out:
                out[-1]["word"] += text
            continue
        out.append({"word": text,
                    "start": round(offset + w["start"], 3),
                    "end": round(offset + (w["end"] if w["end"] is not None else w["start"]), 3)})
    return out


_PIPES = {}


def synth(text: str, voice: str, speed: float | None = None, device: str | None = None):
    import numpy as np
    import torch
    from kokoro import KModel, KPipeline

    vid, lang, preset_speed = resolve_voice(voice)
    spd = speed if speed is not None else preset_speed
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    key = (lang, dev)
    if "model" not in _PIPES or _PIPES["model_dev"] != dev:
        _PIPES["model"] = KModel(repo_id="hexgrad/Kokoro-82M").to(dev).eval()
        _PIPES["model_dev"] = dev
    if key not in _PIPES:
        _PIPES[key] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", model=_PIPES["model"])
    pipe = _PIPES[key]

    chunks, words, offset = [], [], 0.0
    for res in pipe(text, voice=vid, speed=spd, split_pattern=r"\n+"):
        audio = res.audio
        if audio is None:
            continue
        a = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        if res.tokens:
            words += group_words(res.tokens, offset)
        chunks.append(a)
        offset += len(a) / SR
    if not chunks:
        raise SystemExit("engine produced no audio")
    return np.concatenate(chunks).astype("float32"), words


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", help="text to speak (or use --text-file)")
    ap.add_argument("--batch", help="JSON file: [{text, voice, out, timings, speed?}] rendered in one model load")
    ap.add_argument("--text-file")
    ap.add_argument("--voice", default="narrator")
    ap.add_argument("--speed", type=float, default=None, help="override preset speed")
    ap.add_argument("--out")
    ap.add_argument("--timings")
    ap.add_argument("--device", choices=["cuda", "cpu"], default=None)
    ap.add_argument("--list-voices", action="store_true")
    args = ap.parse_args(argv)

    if args.list_voices:
        for k, (v, l, s) in VOICES.items():
            print(f"{k:12s} {v:10s} lang={l} speed={s}")
        return 0
    import soundfile as sf

    if args.batch:
        jobs = json.loads(Path(args.batch).read_text(encoding="utf-8"))
    else:
        if not (args.out and args.timings):
            raise SystemExit("--out and --timings are required")
        text = args.text if args.text is not None else Path(args.text_file).read_text(encoding="utf-8")
        jobs = [{"text": text, "voice": args.voice, "speed": args.speed, "out": args.out, "timings": args.timings}]

    # stay offline when every requested voice pack is cached (no hub calls per run)
    vids = {resolve_voice(j.get("voice", "narrator"))[0] for j in jobs}
    cached = all(any(HF_SNAP.glob(f"*/voices/{v}.pt")) for v in vids) and any(HF_SNAP.glob("*/kokoro-v1_0.pth"))
    os.environ.setdefault("HF_HUB_OFFLINE", "1" if cached else "0")

    t0 = time.perf_counter()
    synth(".", jobs[0].get("voice", "narrator"), None, args.device)  # load + warm up
    load_s = time.perf_counter() - t0
    for job in jobs:
        text = job["text"]
        if not text or not text.strip():
            raise SystemExit("empty text")
        t1 = time.perf_counter()
        audio, words = synth(text, job.get("voice", "narrator"), job.get("speed"), args.device)
        dt = time.perf_counter() - t1
        dur = len(audio) / SR
        Path(job["out"]).parent.mkdir(parents=True, exist_ok=True)
        sf.write(job["out"], audio, SR, subtype="PCM_16")
        Path(job["timings"]).write_text(json.dumps(words, indent=1), encoding="utf-8")
        print(json.dumps({"engine": "kokoro-82M", "voice": job.get("voice"), "device": _PIPES["model_dev"],
                          "seconds": round(dur, 3), "load_s": round(load_s, 2), "synth_s": round(dt, 3),
                          "rtf": round(dt / dur, 4), "words": len(words),
                          "timings": "engine-exact (predicted phoneme durations)",
                          "out": job["out"], "timings_file": job["timings"]}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
