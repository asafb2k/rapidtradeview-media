"""The card Reel's music: an original score played from VSCO 2 Community Edition samples (CC0 1.0), the sampled library the
owner chose on 2026-09-29. Used by card_reel.py in this folder.

    compose(hook_end, beats, figure_beats, body_end, total) -> (mix float64 (n, 2) at SR, music, instruments, score)

The samples (a fixed set, below) are fetched once from the library's tag 1.1.0 commit into a cache inside this repo
(<repo>/.ops/cache/vsco-2-ce-1.1.0/, gitignored with .ops; $RTV_VSCO_DIR may point at an extracted 1.1.0 archive instead) and
every file is checked against its sha256 before use. The hashes were recorded from the verified 1.1.0 archive
(ARCHIVE_SHA256) by the earlier growth-video score; a file that does not match stops the render (No Fallbacks: no other
music is substituted).

The score, in G major: string-section pad chords (cello, viola, violin sustains) that change on the cuts (hook G, the body
in pairs of beats ending on D, the end card back on G); an upright-piano note on every caption beat (and an echo a beat
fraction later); a glockenspiel ping on beats that reveal a figure; bass drum + timpani on the hook; timpani, a soft crash, a
harp arpeggio and a piano chord on the end card. Deterministic: no randomness.
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

SR = 48000
REPO = Path(__file__).resolve().parents[4]
CACHE = REPO / ".ops" / "cache" / "vsco-2-ce-1.1.0"
COMMIT = "28092772094b2d9f1148d84cea97f4545b8c687d"
RAW = f"https://raw.githubusercontent.com/sgossner/VSCO-2-CE/{COMMIT}/"
ARCHIVE_SHA256 = "4a4446628df0e1a12aaee58e9f65f8fa7cde51971e961abb1b43083a6d3a8ab7"
UA = "RapidTradeView card reel (contact@rapidtradeview.trade)"

MUSIC = {   # the provenance shape the publishing kit accepts (tools/manifest.py MUSIC_KEYS; tools/tests/fixtures/vsco-music.json)
    "type": "original score",
    "samples": "VSCO 2 Community Edition",
    "version": f"1.1.0 (tag 1.1.0, commit {COMMIT})",
    "license": "CC0 1.0",
    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "source_url": "https://github.com/sgossner/VSCO-2-CE/archive/refs/tags/1.1.0.zip",
    "archive_sha256": ARCHIVE_SHA256,
    "third_party_tracks": False,
    "credit": "Samples: VSCO 2 Community Edition by Versilian Studios (vis.versilstudios.net/vsco-community.html)",
}
LIBRARY = {
    "name": "VSCO 2 Community Edition (VS Chamber Orchestra: Community Edition)",
    "publisher": "Versilian Studios LLC (Sam Gossner)",
    "version": "1.1.0",
    "tag": "1.1.0",
    "commit": COMMIT,
    "repository": "https://github.com/sgossner/VSCO-2-CE",
    "release_page": "https://github.com/sgossner/VSCO-2-CE/releases/tag/1.1.0",
    "homepage": "http://vis.versilstudios.net/vsco-community.html",
    "license": "CC0 1.0",
    "archive_sha256": ARCHIVE_SHA256,
}

# path: (sha256, pitch_keycenter, sounding_offset, tuning_correction_cents, measured_pitch_midi, onset_trim_ms)
SAMPLES: dict[str, tuple] = {
    "Keys/Upright Nr1/UR1_G3_mf_RR1.wav": ("f5285e48d4a4c6083216e0efdbb47d5d87304206fd0dedac062136cf0f20a166", 55, 0, 3.73, None, 6.3),
    "Keys/Upright Nr1/UR1_C4_mf_RR1.wav": ("9f3a820c2ccbfb60209ff21ab8e80082d6bb7f09f7ff29027380d6cc43c69997", 60, 0, 2.52, None, 2.9),
    "Keys/Upright Nr1/UR1_G4_mf_RR1.wav": ("dcd0789e9d06c26d405e327e032d446481295f4251c21d6049796095bd91d50c", 67, 0, -0.75, None, 0.54),
    "Keys/Upright Nr1/UR1_G4_mf_RR2.wav": ("6046f4b8edadec9104725f7a042dcb154c10b48b1d5a1fc21f002df87468298c", 67, 0, -0.11, None, 0.0),
    "Keys/Upright Nr1/UR1_C5_mf_RR1.wav": ("dacba2dd26c3fd581c093d8131321d2b46fb0f52d5031aad6f173aa7e357b0fb", 72, 0, -2.3, None, 8.19),
    "Keys/Upright Nr1/UR1_C5_mf_RR2.wav": ("e2d78b204d7fdf52f88c6972a18ff620bf2ec3a5686f2d73a9af337cd46bdeae", 72, 0, 0.0, None, 1.52),
    "Keys/Upright Nr1/UR1_G5_mf_RR1.wav": ("16407000a20cafb6602078ea61e19bddbeb709810f7d1b931528e86b3dd96787", 79, 0, 0.0, None, 0.61),
    "Keys/Upright Nr1/UR1_G5_mf_RR2.wav": ("04669393b6846280793750f4881668f7dc1ca15b1e0d403a3f6aa331a1571782", 79, 0, 0.0, None, 0.75),
    "Keys/Upright Nr1/UR1_C6_mf_RR1.wav": ("425938849f04921dddc5251cfc74f7192d5f6b733ee51e58c4f8dd2cf2c3f547", 84, 0, -7.92, None, 1.77),
    "Percussion/Glock/glock_medium_G4.wav": ("6c4649b13e24fa01e4634edad8fe8edf18aef33facc5d49fe53097b376bac4da", 67, 12, -8.18, None, 0.0),
    "Percussion/Glock/glock_medium_C5.wav": ("635f898e0bcb6975b96b18efd9c896f6f1b97ff12174a339ada4814e49675660", 72, 12, -11.76, None, 6.8),
    "Percussion/Glock/glock_medium_G5.wav": ("7045c0ef7260e2f1ad11a64406cf7575ed898d1207a91104d33d78caefac63e4", 79, 12, -11.85, None, 6.73),
    "Strings/Violin Section/susVib/VlnEns_susVib_B2_v2.wav": ("a822fd195e60881afac5e0801d8d494b782a8f6787a08f3c711f5e00290b3fb6", 59, 0, -4.31, None, 23.22),
    "Strings/Violin Section/susVib/VlnEns_susVib_D3_v2.wav": ("77893dbf1ea1be8c40ad756d16b916298e6b1b0742495e9853e020375592357c", 62, 0, 0.0, None, 60.75),
    "Strings/Violin Section/susVib/VlnEns_susVib_F#3_v2.wav": ("d7bc6b4c259b9543de4fe66228ee107205b8f539c8d7c1de71f5781d45a14fc7", 66, 0, -2.56, None, 48.68),
    "Strings/Viola Section/susvib/ViolaEns_susvib_D2_v2_1.wav": ("d3bf192cc03925a4da5ee626763287f85aad1dc498578abf612a97eb548736eb", 50, 0, 0.0, None, 4.08),
    "Strings/Viola Section/susvib/ViolaEns_susvib_E2_v2_1.wav": ("bb31bed6936b5c855fceb94d829e2d3a0492f9af4ad7a2cee57e783719710ceb", 52, 0, -1.79, None, 6.28),
    "Strings/Viola Section/susvib/ViolaEns_susvib_G2_v2_1.wav": ("e3552ebd2d1ac5d089cd2424d31ea88be8d887643311cb23abf5b416838ce2ba", 55, 0, 0.0, None, 8.87),
    "Strings/Viola Section/susvib/ViolaEns_susvib_B2_v2_1.wav": ("edc77038a83f47cf49296c0009fdac23cb5ade3133a2beabd0d2d1f591ccf3cb", 59, 0, -0.93, None, 3.76),
    "Strings/Cello Section/susvib/susvib_E1_v3_1.wav": ("ee190b95be4f2416b9f41d248d255a4d7067b722f9b21482b30bc9872a9bb0d1", 40, 0, 0.0, None, 9.07),
    "Strings/Cello Section/susvib/susvib_G1_v3_1.wav": ("e4c61d4ab855ec20ddb69ff608a1c066ff8a779ddd08d1dfe1d534d3a4563ad0", 43, 0, 0.96, None, 5.92),
    "Strings/Cello Section/susvib/susvib_B1_v3_1.wav": ("8331a0e13f41243efab111f9b5e9185524c27ee48631269acecafc954ab7eaa8", 47, 0, 0.0, None, 3.72),
    "Strings/Cello Section/susvib/susvib_D2_v3_1.wav": ("fc946615cd6550570c8f05d61c0d59b9079bf9daba8bf25be7943487fea5a7ae", 50, 0, 0.0, None, 1.41),
    "Strings/Harp/KSHarp_E5_mf.wav": ("95dd9ddb0bd15bee7687906e00f25aafcaa43020cc9501f0e8b6cabf0e9a53ec", 76, 0, 12.45, None, 24.74),
    "Strings/Harp/KSHarp_G5_mf.wav": ("f2004dfc617997fbabc6f849add2af06f4f859361c44a8fca0f993dc7f999540", 79, 0, 5.84, None, 21.79),
    "Strings/Harp/KSHarp_B5_mf.wav": ("f2757b674c6b7301bed52e17a1ae3e3d34d628b3f7edc5773ebb25798d2541f7", 83, 0, 8.68, None, 20.59),
    "Strings/Harp/KSHarp_D6_mf.wav": ("b040b61fb279efa1a9b9c60dcbd8626a37f57ffb30f3b50747a2123ee4db5bd2", 86, 0, 9.08, None, 20.93),
    "Percussion/Timpani/Timpani2_Hit_v3_rr1_Sum.wav": ("69e5d604effd3f29c86117d22ad2335f73e43f5d47868dc57d8fa593975ee241", 46, 0, 0.0, 46.883, 0.07),
    "Percussion/Timpani/Timpani3_Hit_v3_rr1_Sum.wav": ("46cd2ba3798f9e3a6be515b13dbc37d2ef65c82afb0d0e9e34121e4524bfcd3a", 49, 0, 0.0, 49.521, 0.23),
    "Percussion/BDrumNewhit_v3_rr1_Sum.wav": ("a2d8829e8b2b59e8afb12fa396b01758827059339c2a84ad066d17b36c82d1ff", None, None, None, None, 0.02),
    "Percussion/cymbal-crash1_mp_rr1.wav": ("36d5beaaaa28cd4865a71647f89743ba4e7f5f76a3a3bc011548ead7303050fc", None, None, None, None, 1.07),
}
INSTRUMENTS = {   # label, sfz (the library's patch the samples belong to), sample path prefix
    "piano": ("piano: VS Upright No. 1", "VSUpright1.sfz", "Keys/Upright Nr1/"),
    "glock": ("glockenspiel", "Glockenspiel.sfz", "Percussion/Glock/"),
    "violin": ("violin section sustain (vib)", "ViolinEnsSusVib.sfz", "Strings/Violin Section/"),
    "viola": ("viola section sustain (vib)", "ViolaEnsSusVib.sfz", "Strings/Viola Section/"),
    "cello": ("cello section sustain (vib)", "CelloEnsSusVib.sfz", "Strings/Cello Section/"),
    "harp": ("harp", "Harp.sfz", "Strings/Harp/"),
    "timpani": ("timpani", "Timpani.sfz", "Percussion/Timpani/"),
    "perc": ("orchestral percussion one-shots (bass drum, crash cymbal)", None, "Percussion/"),
}

# G major. bass = cello; viola / violin = the pad's inner and top voices; melody = the piano's beat notes (sounding MIDI)
CHORDS = {
    "G": {"bass": 43, "viola": (55, 59), "violin": (62, 67), "melody": (79, 74, 71)},
    "D": {"bass": 38, "viola": (54, 57), "violin": (62, 66), "melody": (78, 74, 69)},
    "Em": {"bass": 40, "viola": (55, 59), "violin": (64, 67), "melody": (76, 71, 67)},
    "C": {"bass": 48, "viola": (52, 55), "violin": (60, 64), "melody": (76, 72, 67)},
}
LEVEL_DB = {"cello": -16.0, "viola": -20.0, "violin": -20.0, "piano": -13.0, "piano_echo": -21.0, "glock": -17.0,
            "harp": -19.0, "timpani": -13.0, "bdrum": -15.0, "crash": -27.0, "piano_chord": -19.0}


class SampleError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample_root() -> Path:
    env = os.environ.get("RTV_VSCO_DIR")
    return Path(env) if env else CACHE


def ensure_samples(paths=None, timeout: float = 60.0) -> Path:
    """Every pinned sample present and matching its sha256 (fetching the missing ones into the cache). Returns the root."""
    root = sample_root()
    for rel in paths or SAMPLES:
        want = SAMPLES[rel][0]
        dest = root / rel
        if dest.is_file() and _sha(dest) == want:
            continue
        if root != CACHE:
            raise SampleError(f"{rel} is missing or altered in RTV_VSCO_DIR ({root})")
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = RAW + urllib.parse.quote(rel)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
        except OSError as e:
            raise SampleError(f"the VSCO sample {rel} did not download ({type(e).__name__}: {e})") from e
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            raise SampleError(f"the VSCO sample {rel} does not match its pinned sha256 ({got[:12]} != {want[:12]})")
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    return root


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """PCM 16/24/32-bit or float 32/64 WAV (plain or WAVE_FORMAT_EXTENSIBLE) -> (float64 (n, 2) in -1..1, sample rate)."""
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise SampleError(f"{path.name} is not a WAV file")
    i, fmt, pcm = 12, None, None
    while i + 8 <= len(data):
        cid, size = data[i:i + 4], struct.unpack("<I", data[i + 4:i + 8])[0]
        body = data[i + 8:i + 8 + size]
        if cid == b"fmt ":
            tag, ch, sr, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, ch, sr, bits)
        elif cid == b"data":
            pcm = body
        i += 8 + size + (size & 1)
    if fmt is None or pcm is None:
        raise SampleError(f"{path.name} has no fmt or data chunk")
    tag, ch, sr, bits = fmt
    if tag == 1 and bits == 16:
        x = np.frombuffer(pcm[: len(pcm) // 2 * 2], "<i2").astype(np.float64) / 32768.0
    elif tag == 1 and bits == 24:
        b = np.frombuffer(pcm[: len(pcm) // 3 * 3], np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(v >= 1 << 23, v - (1 << 24), v).astype(np.float64) / float(1 << 23)
    elif tag == 1 and bits == 32:
        x = np.frombuffer(pcm[: len(pcm) // 4 * 4], "<i4").astype(np.float64) / float(1 << 31)
    elif tag == 3 and bits == 32:
        x = np.frombuffer(pcm[: len(pcm) // 4 * 4], "<f4").astype(np.float64)
    elif tag == 3 and bits == 64:
        x = np.frombuffer(pcm[: len(pcm) // 8 * 8], "<f8").astype(np.float64)
    else:
        raise SampleError(f"{path.name}: unsupported WAV format {tag}/{bits} bit")
    x = x[: len(x) // ch * ch].reshape(-1, ch)
    if ch == 1:
        x = np.repeat(x, 2, axis=1)
    elif ch > 2:
        x = x[:, :2]
    return x, sr


class Player:
    def __init__(self, total: float, root: Path):
        self.n = int(round(total * SR))
        self.buf = np.zeros((self.n, 2))
        self.root = root
        self._raw: dict[str, tuple[np.ndarray, int, float]] = {}
        self.used: dict[str, int] = {}

    def _load(self, rel: str) -> tuple[np.ndarray, int, float]:
        if rel not in self._raw:
            x, sr = read_wav(self.root / rel)
            trim = int(round((SAMPLES[rel][5] or 0) / 1000 * sr))
            x = x[trim:]
            win = x[: int(1.0 * sr)]
            rms = float(np.sqrt(np.mean(win ** 2))) if win.size else 0.0
            if rms <= 1e-6:
                raise SampleError(f"{rel} is silent")
            self._raw[rel] = (x, sr, rms)
        return self._raw[rel]

    def pick(self, prefix: str, target: float) -> str:
        """The sample of an instrument whose sounding pitch is nearest the target (the first on a tie)."""
        best, dist = None, 1e9
        for rel, (_, key, off, _, meas, _) in SAMPLES.items():
            if not rel.startswith(prefix) or key is None:
                continue
            d = abs(target - (meas if meas else key + off))
            if d < dist - 1e-9:
                best, dist = rel, d
        if best is None:
            raise SampleError(f"no sample under {prefix}")
        return best

    def note(self, t0: float, rel: str, level_db: float, target: float | None = None, dur: float | None = None,
             release: float = 0.35, pan: float = 0.0, attack: float = 0.004) -> None:
        x, sr, rms = self._load(rel)
        _, key, off, cents, meas, _ = SAMPLES[rel]
        semis = 0.0
        if target is not None and key is not None:
            semis = target - (meas if meas else key + off) + (cents or 0.0) / 100.0
        step = (sr / SR) * 2 ** (semis / 12)
        i0 = int(round(t0 * SR))
        if i0 >= self.n:
            return
        length = int((len(x) - 1) / step)
        if dur is not None:
            length = min(length, int((dur + release) * SR))
        length = min(length, self.n - max(i0, 0))
        if length <= 0:
            return
        pos = np.arange(length) * step
        src = np.arange(len(x))
        y = np.stack([np.interp(pos, src, x[:, 0]), np.interp(pos, src, x[:, 1])], axis=1)
        tt = np.arange(length) / SR
        env = np.minimum(1.0, tt / max(attack, 1e-4))
        if dur is not None:
            r = np.clip((tt - dur) / max(release, 1e-3), 0, 1)
            env = env * (0.5 + 0.5 * np.cos(np.pi * r))
        y *= (env * (10 ** (level_db / 20) / rms))[:, None]
        a = (pan + 1) * math.pi / 4
        y[:, 0] *= math.cos(a) * math.sqrt(2)
        y[:, 1] *= math.sin(a) * math.sqrt(2)
        if i0 < 0:
            y, i0 = y[-i0:], 0
        self.buf[i0:i0 + len(y)] += y
        self.used[rel] = self.used.get(rel, 0) + 1

    def inst(self, name: str, t0: float, target: float, level_db: float, **kw) -> None:
        prefix = INSTRUMENTS[name][2]
        self.note(t0, self.pick(prefix, target), level_db, target=target, **kw)


def chord_plan(hook_end: float, beats: list[float], body_end: float, total: float) -> list[tuple[float, float, str]]:
    """(start, end, chord): G on the hook, the body in pairs of beats ending on D, G on the end card."""
    starts = [hook_end] + [beats[k] for k in range(2, len(beats), 2)]
    names = (["G", "Em", "C", "D"] * 32)[-len(starts):]
    segs = [(0.0, hook_end, "G")]
    for k, s in enumerate(starts):
        segs.append((s, starts[k + 1] if k + 1 < len(starts) else body_end, names[k]))
    segs.append((body_end, total, "G"))
    return segs


def compose(hook_end: float, beats: list[float], figure_beats: list[int], body_end: float, total: float):
    root = ensure_samples()
    p = Player(total, root)
    segs = chord_plan(hook_end, beats, body_end, total)
    L = LEVEL_DB
    # the string pad, changing on the cuts
    for k, (a, b, name) in enumerate(segs):
        c = CHORDS[name]
        dur = b - a
        lead = 0.0 if a == 0 else 0.06
        p.inst("cello", a - lead, c["bass"], L["cello"], dur=dur + lead, release=0.5, attack=0.03 if a == 0 else 0.12)
        for j, m in enumerate(c["viola"]):
            p.inst("viola", a - lead, m, L["viola"], dur=dur + lead, release=0.5, pan=-0.35 + 0.2 * j, attack=0.05 if a == 0 else 0.15)
        for j, m in enumerate(c["violin"]):
            p.inst("violin", a - lead, m, L["violin"], dur=dur + lead, release=0.5, pan=0.15 + 0.25 * j, attack=0.05 if a == 0 else 0.15)

    def chord_at(t: float) -> dict:
        return CHORDS[[s for s in segs if s[0] <= t + 1e-6][-1][2]]

    # the hook: bass drum + timpani + piano chord, glock on the figure punch
    p.note(0.0, "Percussion/BDrumNewhit_v3_rr1_Sum.wav", L["bdrum"])
    p.inst("timpani", 0.0, 50, L["timpani"])
    for j, m in enumerate((55, 67, 71, 74)):
        p.inst("piano", 0.0 + 0.012 * j, m, L["piano_chord"], pan=-0.2 + 0.13 * j)
    p.inst("glock", 0.06, 91, L["glock"], pan=0.25)
    # a piano note on every caption beat (+ a softer echo), a glock ping on beats that reveal a figure
    for k, b in enumerate(beats):
        c = chord_at(b)
        mel = c["melody"][k % 3]
        p.inst("piano", b, mel, L["piano"], pan=-0.15 if k % 2 else 0.15)
        p.inst("piano", b + 0.17, mel - 12 if mel - 12 >= 55 else mel - 5, L["piano_echo"], pan=0.2 if k % 2 else -0.2)
        if k in figure_beats:
            p.inst("glock", b + 0.12, c["melody"][0] + 12, L["glock"] - 2, pan=0.3 if k % 2 else -0.3)
    # the end card: timpani, a soft crash, a piano chord, a harp arpeggio, a glock top note
    e = body_end
    p.inst("timpani", e, 43, L["timpani"] + 1)
    p.note(e, "Percussion/cymbal-crash1_mp_rr1.wav", L["crash"])
    for j, m in enumerate((55, 62, 67, 71)):
        p.inst("piano", e + 0.01 * j, m, L["piano_chord"], pan=-0.2 + 0.13 * j)
    for j, m in enumerate((67, 71, 74, 79, 83, 86)):
        p.inst("harp", e + 0.10 + 0.085 * j, m, L["harp"], pan=-0.4 + 0.16 * j)
    p.inst("glock", e + 0.75, 91, L["glock"] - 1, pan=0.2)

    mix = p.buf
    peak = float(np.abs(mix).max())
    if peak <= 1e-9:
        raise SampleError("the score rendered silent")
    mix = mix / peak * 0.70                           # peak -3 dBFS
    t = np.arange(len(mix)) / SR
    mix *= (np.minimum(1, t / 0.006) * np.clip((total - t) / 0.6, 0, 1))[:, None]

    instruments = {"library": LIBRARY, "instruments": []}
    for name, (label, sfz, prefix) in INSTRUMENTS.items():
        used = sorted(r for r in p.used if r.startswith(prefix) and not any(
            r.startswith(INSTRUMENTS[o][2]) and len(INSTRUMENTS[o][2]) > len(prefix) for o in INSTRUMENTS))
        if not used:
            continue
        instruments["instruments"].append({
            "label": label, "sfz": sfz, "notes_rendered": sum(p.used[r] for r in used), "samples_used_N": len(used),
            "samples": [{"sample": r, "sha256": SAMPLES[r][0], "notes": p.used[r], "pitch_keycenter": SAMPLES[r][1],
                         "sounding_offset": SAMPLES[r][2], "tuning_correction_cents": SAMPLES[r][3],
                         "measured_pitch_midi": SAMPLES[r][4], "onset_trim_ms": SAMPLES[r][5]} for r in used]})
    score = {"engine": "tools/gv/scripts/v6cat/vsco_score.py", "key": "G major",
             "chords": [[round(a, 3), round(b, 3), n] for a, b, n in segs],
             "hits": {"hook": 0.0, "beats": [round(b, 3) for b in beats], "figure_beats": list(figure_beats),
                      "end_card": round(body_end, 3)},
             "levels_db": dict(LEVEL_DB)}
    return mix, dict(MUSIC), instruments, score
