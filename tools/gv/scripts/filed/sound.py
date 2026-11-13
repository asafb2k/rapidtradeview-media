"""FILED. series sound: every effect and the bed synthesised in numpy (no samples, no licences), then the mix.

The effects are the series' sound logo: `make_kit(dir)` writes them once as 48 kHz wavs (sub_boom, whoosh, tick, swish,
riser, impact, stamp) and every episode reuses the same files. The bed is a low dark pulse built here too, periodic over
the episode length so the auto-replay joins without a click.

    mix(voice_clips, cues, duration, out_wav, gaps)   -> the pre-master mix (voice + bed + effects)
Mastering (-14 LUFS integrated, -1 dBTP) is done by filed.py with ffmpeg loudnorm (two passes).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48000
KIT_VERSION = "filed-kit/2"


def _t(dur: float) -> np.ndarray:
    return np.arange(int(round(dur * SR))) / SR


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _lp(x: np.ndarray, cutoff_hz: float | np.ndarray) -> np.ndarray:
    """One-pole low-pass; cutoff may vary per sample."""
    c = np.broadcast_to(np.asarray(cutoff_hz, float), x.shape)
    a = 1 - np.exp(-2 * np.pi * c / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def _hp(x: np.ndarray, cutoff_hz: float) -> np.ndarray:
    return x - _lp(x, cutoff_hz)


def _norm(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.max(np.abs(x))) or 1.0
    return (x / m * peak).astype(np.float32)


def sub_boom(seed: int = 1) -> np.ndarray:
    t = _t(1.6)
    f = 34 + 60 * np.exp(-t * 9)                      # pitch drop 94 -> 34 Hz
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 2.4)
    click = _lp(_rng(seed).standard_normal(len(t)), 900) * np.exp(-t * 60) * 0.5
    return _norm(np.tanh(1.6 * (body + click)))


def whoosh(seed: int = 2, dur: float = 0.55) -> np.ndarray:
    t = _t(dur)
    n = _rng(seed).standard_normal(len(t))
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2.2
    sweep = 300 + 5200 * np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.5
    x = _hp(_lp(n, sweep), 120) * env
    return _norm(x, 0.8)


def tick(seed: int = 3) -> np.ndarray:
    t = _t(0.12)
    x = np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 90) + 0.6 * np.sin(2 * np.pi * 1200 * t) * np.exp(-t * 60)
    x += _hp(_rng(seed).standard_normal(len(t)), 3000) * np.exp(-t * 200) * 0.4
    return _norm(x, 0.7)


def swish(seed: int = 4, dur: float = 0.34) -> np.ndarray:
    """Highlighter: a short bright marker-on-paper scrape."""
    t = _t(dur)
    n = _rng(seed).standard_normal(len(t))
    env = np.clip(t / 0.03, 0, 1) * np.exp(-np.clip(t - 0.03, 0, None) * 7)
    grain = 1 + 0.5 * np.sin(2 * np.pi * 38 * t)
    x = _hp(_lp(n, 7000), 1800) * env * grain
    return _norm(x, 0.6)


def riser(seed: int = 5, dur: float = 1.1) -> np.ndarray:
    t = _t(dur)
    k = np.clip(t / dur, 0, 1)
    n = _rng(seed).standard_normal(len(t))
    noise = _hp(_lp(n, 400 + 9000 * k ** 2), 200) * k ** 2.2
    f = 110 * 2 ** (2.5 * k)                         # tone climbs 2.5 octaves
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.35 * k ** 1.5
    x = noise + tone
    x[-int(0.008 * SR):] *= np.linspace(1, 0, int(0.008 * SR))   # hard stop (the silence follows)
    return _norm(x, 0.75)


def _bp(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return _hp(_lp(x, hi), lo)


def impact(seed: int = 6) -> np.ndarray:
    """The sink hit, built to read on a phone speaker: a mid-range body (150 Hz-2 kHz) and a 3-6 kHz transient carry
    it; the sub layer sits about 8 dB lower than in kit/1; the tail is gone by ~0.55 s."""
    t = _t(0.7)
    r = _rng(seed)
    f = 42 + 80 * np.exp(-t * 16)
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5) * 0.4          # ~-8 dB against kit/1
    body = _bp(r.standard_normal(len(t)), 150, 2000) * np.exp(-t * 11) * 1.6
    knock = sum(np.sin(2 * np.pi * fr * t) * np.exp(-t * d) * a for fr, d, a in ((180, 14, 0.9), (330, 20, 0.6),
                                                                                   (620, 30, 0.35)))
    click = _bp(r.standard_normal(len(t)), 3000, 6000) * np.exp(-t * 90) * 1.4
    x = np.tanh(1.7 * (sub + body + knock + click))
    x *= np.clip((0.62 - t) / 0.12, 0, 1)                                          # done by 0.62 s
    return _norm(x, 0.95)


def thud(seed: int = 8) -> np.ndarray:
    """A short punch under the hook counter: low-mid knock, quick."""
    t = _t(0.35)
    r = _rng(seed)
    knock = sum(np.sin(2 * np.pi * fr * t) * np.exp(-t * d) * a for fr, d, a in ((70, 16, 0.8), (140, 22, 0.8),
                                                                                   (290, 34, 0.4)))
    snap = _bp(r.standard_normal(len(t)), 1500, 5000) * np.exp(-t * 120) * 0.6
    return _norm(np.tanh(1.5 * (knock + snap)), 0.9)


def stamp(seed: int = 7) -> np.ndarray:
    """The signature: a heavy rubber stamp on a desk, a woody knock with a short room."""
    t = _t(0.9)
    r = _rng(seed)
    knock = sum(np.sin(2 * np.pi * fr * t) * np.exp(-t * d) * a for fr, d, a in ((92, 18, 1.0), (180, 26, 0.6),
                                                                                   (410, 40, 0.35), (760, 60, 0.2)))
    slap = _lp(r.standard_normal(len(t)), 3800) * np.exp(-t * 70) * 0.9
    room = _lp(r.standard_normal(len(t)), 1200) * np.exp(-t * 9) * 0.12
    x = np.tanh(1.6 * (knock + slap + room))
    return _norm(x, 0.95)


KIT = {"sub_boom": sub_boom, "whoosh": whoosh, "tick": tick, "swish": swish, "riser": riser, "impact": impact,
       "stamp": stamp, "thud": thud}


def make_kit(kit_dir: Path) -> dict[str, Path]:
    """Write the series sound kit once (deterministic seeds); later episodes reuse the files."""
    kit_dir.mkdir(parents=True, exist_ok=True)
    meta = kit_dir / "kit.json"
    out = {name: kit_dir / f"{name}.wav" for name in KIT}
    if meta.is_file() and json.loads(meta.read_text()).get("version") == KIT_VERSION and all(p.is_file() for p in out.values()):
        return out
    for name, fn in KIT.items():
        sf.write(out[name], fn(), SR, subtype="PCM_24")
    meta.write_text(json.dumps({"version": KIT_VERSION, "sr": SR, "files": sorted(out),
                                "licence": "synthesised in numpy by sound.py (no samples)"}, indent=1))
    return out


def bed(duration: float, bpm_hint: float = 96.0, seed: int = 11) -> np.ndarray:
    """A low dark pulse, periodic over `duration` (integer cycles of every partial and an integer number of beats)."""
    n = int(round(duration * SR))
    t = np.arange(n) / SR
    beats = max(1, round(duration * bpm_hint / 60))
    beat = duration / beats

    def per(f: float) -> float:                     # nearest frequency with whole cycles in the loop
        return round(f * duration) / duration

    drone = (np.sin(2 * np.pi * per(41.2) * t) * 0.55 + np.sin(2 * np.pi * per(61.7) * t) * 0.22
             + np.sin(2 * np.pi * per(82.4) * t) * 0.12 + np.sin(2 * np.pi * per(97.9) * t) * 0.08)
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * per(0.25) * t)
    phase = (t % beat) / beat
    pulse_env = np.exp(-phase * 7.0)                 # a heartbeat-like swell on each beat
    pulse = np.sin(2 * np.pi * per(55.0) * t) * pulse_env * 0.6
    r = _rng(seed)
    air = _lp(r.standard_normal(n), 700) * 0.05
    air = air - np.linspace(air[0], air[-1], n)      # end where it starts
    x = (drone * lfo + pulse + air)
    return _norm(x, 0.5)


def _place(buf: np.ndarray, clip: np.ndarray, at: float, gain_db: float) -> None:
    i = int(round(at * SR))
    if i >= len(buf):
        return
    j = min(len(buf), i + len(clip))
    if i < 0:
        clip = clip[-i:]
        j = min(len(buf), len(clip))
        i = 0
    buf[i:j] += clip[: j - i] * (10 ** (gain_db / 20))


def _resample(x: np.ndarray, sr_in: int) -> np.ndarray:
    if sr_in == SR:
        return x
    from scipy.signal import resample_poly
    from math import gcd
    g = gcd(SR, sr_in)
    return resample_poly(x, SR // g, sr_in // g).astype(np.float32)


def compress(x: np.ndarray, thresh_db: float = -24.0, ratio: float = 3.0, attack: float = 0.004,
             release: float = 0.09, makeup_db: float = 0.0) -> np.ndarray:
    """Feed-forward peak compressor (attack/release envelope), to lower the voice's crest factor before mastering."""
    env = np.abs(x).astype(np.float64)
    a_att, a_rel = np.exp(-1 / (attack * SR)), np.exp(-1 / (release * SR))
    out = np.empty_like(env)
    e = 0.0
    for i, v in enumerate(env):
        c = a_att if v > e else a_rel
        e = c * e + (1 - c) * v
        out[i] = e
    lvl = 20 * np.log10(out + 1e-9)
    over = np.maximum(0.0, lvl - thresh_db)
    gain_db = -over * (1 - 1 / ratio) + makeup_db
    return (x * 10 ** (gain_db / 20)).astype(np.float32)


def lufs(x: np.ndarray) -> float:
    import pyloudnorm as pyln
    return float(pyln.Meter(SR).integrated_loudness(x.astype(np.float64)))


def mix(voice: list[dict], cues: list[dict], duration: float, out_wav: Path, kit: dict[str, Path],
        bed_under_voice_db: float = 19.0, bed_mute: list[tuple[float, float]] | None = None) -> dict:
    """voice: [{wav, at}] ; cues: [{sfx, at, gain_db}] ; bed_mute: [(t0, t1)] spans where the bed is silent."""
    n = int(round(duration * SR))
    vbus = np.zeros(n, np.float32)
    for v in voice:
        a, sr = sf.read(v["wav"], dtype="float32")
        if a.ndim > 1:
            a = a.mean(axis=1)
        _place(vbus, _resample(a, sr), v["at"], 0.0)
    pk = float(np.max(np.abs(vbus))) or 1.0
    vbus = compress(vbus / pk, thresh_db=-22.0, ratio=3.0) * pk
    v_l = lufs(vbus)
    b = bed(duration)
    b_l = lufs(b)
    b *= 10 ** (((v_l - bed_under_voice_db) - b_l) / 20)
    env = np.ones(n, np.float32)
    for t0, t1 in bed_mute or []:
        i0, i1 = int(t0 * SR), int(t1 * SR)
        fade = int(0.012 * SR)
        env[max(0, i0 - fade):i0] = np.minimum(env[max(0, i0 - fade):i0], np.linspace(1, 0, i0 - max(0, i0 - fade)))
        env[i0:i1] = 0
        env[i1:i1 + fade] = np.minimum(env[i1:i1 + fade], np.linspace(0, 1, len(env[i1:i1 + fade])))
    b = b * env
    sbus = np.zeros(n, np.float32)
    loaded = {}
    for c in cues:
        if c["sfx"] not in loaded:
            a, sr = sf.read(kit[c["sfx"]], dtype="float32")
            loaded[c["sfx"]] = _resample(a, sr)
        _place(sbus, loaded[c["sfx"]], c["at"], c.get("gain_db", 0.0))
    # sidechain: the effects bus ducks 7 dB under the voice (fast attack, 120 ms release), so no hit masks a word
    venv = np.abs(vbus).astype(np.float64)
    a_att, a_rel = np.exp(-1 / (0.005 * SR)), np.exp(-1 / (0.12 * SR))
    e, sc = 0.0, np.empty(n)
    for i, v in enumerate(venv):
        c = a_att if v > e else a_rel
        e = c * e + (1 - c) * v
        sc[i] = e
    ref = np.percentile(sc[sc > 1e-4], 60) if np.any(sc > 1e-4) else 1.0
    duck_db = -7.0 * np.clip(sc / ref, 0, 1)
    out = vbus + b + sbus * (10 ** ((-8 + duck_db) / 20)).astype(np.float32)
    peak = float(np.max(np.abs(out))) or 1.0
    if peak > 0.98:
        out = out / peak * 0.98
    sf.write(out_wav, np.stack([out, out], axis=1), SR, subtype="PCM_24")
    return {"voice_lufs": round(v_l, 2), "bed_lufs_raw": round(b_l, 2),
            "bed_lufs_set": round(lufs(b[env > 0]) if np.any(env > 0) else -99, 2),
            "bed_under_voice_db": bed_under_voice_db, "sr": SR}
