"""FILED. by RapidTradeView: one disclosed-trade story a day as a 3D Short (Monolith, Flip, Sink, Stamp).

    PY=C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe
    $PY tools/gv/scripts/filed/filed.py tools/gv/scripts/filed/episodes/<slug>.json            # capture now + build
    $PY tools/gv/scripts/filed/filed.py <episode.json> --reuse-capture                          # rebuild from the run's captures

Tomorrow's episode = a new episodes/<slug>.json + that one command. Output: <media>/.ops/filed/<slug>/
    final.mp4, frame0.png, sheet.png (every 0.5 s), phone.png (4 key frames at 360 px), proof.json, episode.json (the
    resolved spec the template rendered from), voice_script.json/.txt (word timings), qa.json, render.json, screens/.

Facts are never typed. The episode file holds wording templates with {slots}; every slot is read from a capture of
the live page made by this run (capture.py: PNG + sidecar with visible_text, sha256, seal). A template line that
types a digit is refused. If the trade row is gone, its figure is missing, or its sign is not the one the template
was written for, the build stops (exit 2) before anything is rendered.

Exit: 0 built and QA passed, 1 built but a QA gate failed (files kept), 2 input/capture error (no video).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sound  # noqa: E402


def _media_root() -> Path:
    for p in HERE.parents:
        if (p / ".ops" / "cache").is_dir():
            return p
    raise SystemExit("no .ops/cache above filed.py")


MEDIA = _media_root()
CACHE = MEDIA / ".ops" / "cache"
CARTOON = HERE.parent / "cartoon"
SHOT_PY = CACHE / "shot-venv" / "Scripts" / "python.exe"
TTS_PY = CACHE / "tts-venv" / "Scripts" / "python.exe"
CONDA_PY = Path(sys.executable)
FFMPEG = CACHE / "epic-lab" / "ffmpeg-dl" / "ffmpeg-9.0.2-essentials_build" / "bin" / "ffmpeg.exe"
FFPROBE = FFMPEG.with_name("ffprobe.exe")
FONTS = CACHE / "filed-fonts"
KIT_DIR = CACHE / "filed-kit"
BRAND_MARK_JSON = Path("D:/Coding_projects/rapidtradeview/shared/data/brand-mark.json")
W, H, FPS = 1080, 1920, 30
SAFE = (60, 200, 920, 1500)
HOLD = {"x": 60, "w": 960, "top": 300}
LOOP_TAIL = 0.85
BANNED = ("insider trading", "insider", "suspicious", "timed", "knew", "dump", "lost money", "before", "s&p 500",
          "s&p", "democrat", "republican", "party", "corrupt", "illegal", "scandal", "shady", "caught",
          "you should", "buy now", "should buy", "copy congress")
PARTY_RX = re.compile(r"\b(Democrat|Republican|Independent)\b|·\s?[DRI]\s?·|\([DRI]-[A-Z]{2}\)")
PROVIDER_WORDS = ("yahoo", "yfinance", "finnhub", "stocktwits", "stock twits", "apewisdom", "ape wisdom", "quiver",
                  "polygon", "alpaca", "tiingo", "iex", "zacks", "elbstream", "marketbeat", "factset", "google news",
                  "vader", "cnbc", "alpha vantage", "twelve data", "financial modeling prep", "intrinio", "marketstack",
                  "unusual whales", "capitol trades", "openinsider", "benzinga", "tipranks", "seeking alpha", "finviz",
                  "barchart")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


class InputError(RuntimeError):
    pass


def sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def now_z() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def wjson(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1,
                            default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n", encoding="utf-8")


def rjson(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# ======================================================================================== words for the voice
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
        "twelve": "twelfth"}


def words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" " + words(n % 100) if n % 100 else "")
    for unit, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= unit:
            head, rest = divmod(n, unit)
            return words(head) + " " + name + ("" if not rest else " " + words(rest))
    raise ValueError(n)


def ordinal_words(n: int) -> str:
    w = words(n)
    head, sep, last = w.rpartition("-") if "-" in w else ("", "", w)
    if last in _ORD:
        last = _ORD[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last = last + "th"
    return head + sep + last


def decimal_words(s: str) -> str:
    """"27.9" -> "twenty-seven point nine"."""
    a, _, b = s.partition(".")
    out = words(int(a))
    if b:
        out += " point " + " ".join(_ONES[int(ch)] for ch in b)
    return out


class Slot:
    def __init__(self, show: str, say: str | None = None, proof: dict | None = None):
        self.show, self.say, self.proof = show, (say if say is not None else show), proof


# ======================================================================================== captures
def capture(name: str, out: Path, url: str, extra: list[str], dpr: int = 3) -> dict:
    cmd = [str(SHOT_PY), "-I", str(CARTOON / "capture.py"), "--url", url, "--out", str(out), "--name", name,
           "--viewport", "390x844", "--dpr", str(dpr)] + extra
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise InputError(f"capture {name} failed: {(r.stderr or r.stdout).strip()[-800:]}")
    side = rjson(out / f"{name}.json")
    side["_json"] = str(out / f"{name}.json")
    side["_png"] = str(out / f"{name}.png")
    return side


ROW_RX = re.compile(r"(?m)^(?P<ticker>[A-Z][A-Z.]*)\n(?P<side>buy|sell|exchange)\n(?P<perf>(?:(?!Traded\n)[^\n]*\n)*?)"
                    r"Traded\n(?P<traded>\d{4}-\d\d-\d\d)\n·\ndisclosed\n(?P<filed>\d{4}-\d\d-\d\d)\n"
                    r"(?P<amount>\$[\d,]+(?:–\$[\d,]+)?)\n(?P<owner>[^\n]+)\n(?P<lag>\d+d lag)\n")
PP_RX = re.compile(r"^(?P<sign>[−\-+])(?P<num>\d+(?:\.\d+)?) pp$")


def nth_before(lines: list[str], upto: int, needle: str, exact: bool = False) -> int:
    """1-based index of the next occurrence of `needle` at or after line `upto`, counting text nodes like capture.py."""
    n = 0
    for i, ln in enumerate(lines):
        hit = (ln.strip() == needle) if exact else (needle in ln)
        if hit:
            n += 1
            if i >= upto:
                return n
    raise InputError(f"{needle!r} not found after line {upto}")


def do_captures(ep: dict, run: Path) -> dict:
    screens = run / "screens"
    screens.mkdir(parents=True, exist_ok=True)
    title = ep["card_title"]
    # pass 1: the whole card, to find the row (never shown)
    scan = capture("scan", screens, ep["page"], ["--strip-top", f"text:{title}", "--strip-bottom",
                                                 f"text:{ep['card_end_text']}", "--strip-pad", "10"])
    lines = scan["inside_text"].split("\n")
    text = scan["inside_text"] + "\n"
    rows = [m for m in ROW_RX.finditer(text) if m["ticker"] == ep["ticker"] and m["side"] == ep["side"]]
    if len(rows) < ep.get("nth", 1):
        raise InputError(f"STOP: the card has no {ep['ticker']} {ep['side']} row #{ep.get('nth', 1)} today")
    m = rows[ep.get("nth", 1) - 1]
    row_line = text[:m.start()].count("\n")
    end_line = text[:m.end()].count("\n") - 1               # the row's last line ("28d lag"); "View filing" follows
    # the page-level index of the row's "View filing" (strip bottom), from the page text up to the row
    page = scan["page_text"]
    ptitle = page.find(title)
    k = 0
    for mm in ROW_RX.finditer(text):
        k += 1
        if mm.start() == m.start():
            break
    vf_page = page[:ptitle].count("View filing") + k
    perf = m["perf"].strip().split("\n")
    tg = {
        "ticker": f"={m['ticker']}#{nth_before(lines, row_line, m['ticker'], exact=True)}",
        "amount": f"{m['amount']}#{nth_before(lines, row_line, m['amount'])}",
        "owner": f"={m['owner']}#{nth_before(lines, row_line, m['owner'], exact=True)}",
        "traded_word": f"=Traded#{nth_before(lines, row_line, 'Traded', exact=True)}",
        "traded": f"={m['traded']}#{nth_before(lines, row_line, m['traded'], exact=True)}",
        "filed_word": f"=disclosed#{nth_before(lines, row_line, 'disclosed', exact=True)}",
        "filed": f"={m['filed']}#{nth_before(lines, row_line, m['filed'], exact=True)}",
        "lag": f"={m['lag']}#{nth_before(lines, row_line, m['lag'], exact=True)}",
        "column": "Since filing vs SPY",
    }
    if perf and perf[0]:
        tg["perf"] = f"={perf[0]}#{nth_before(lines, row_line, perf[0], exact=True)}"
    extra = ["--strip-top", f"text:{title}", "--strip-bottom", f"text:View filing#{vf_page}", "--strip-pad", "10",
             "--strip-pad-bottom", "16"]
    for v in tg.values():
        extra += ["--target", v]
    proof = capture("card", screens, ep["page"], extra, dpr=ep.get("card_dpr", 6))
    comp = ep["company"]
    names = capture("names", screens, comp["url"], ["--scroll-to", comp["target"], "--target", comp["target"]])
    member = capture("member", screens, ep["page"], ["--scroll-to", f"{ep['member']}: stock trades",
                                                     "--target", f"{ep['member']}: stock trades"])
    return {"scan": scan, "card": proof, "names": names, "member": member, "targets": tg}


def load_captures(run: Path) -> dict:
    s = run / "screens"
    caps = {}
    for n in ("scan", "card", "names", "member"):
        d = rjson(s / f"{n}.json")
        d["_json"], d["_png"] = str(s / f"{n}.json"), str(s / f"{n}.png")
        caps[n] = d
    return caps


def proof_ref(side: dict, line: str) -> dict:
    if line not in side["visible_text"] and line not in side.get("page_text", ""):
        raise InputError(f"proof line {line!r} is not in {side['_json']}")
    return {"capture_png": side["_png"], "capture_json": side["_json"], "png_sha256": side["sha256"],
            "url": side["url"], "captured_at": side["captured_at"], "visible_text_line": line}


def iso_slots(iso: str, ref: dict) -> Slot:
    d = dt.date.fromisoformat(iso)
    return Slot(f"{MONTHS[d.month - 1][:3].upper()} {d.day}", f"{MONTHS[d.month - 1]} {ordinal_words(d.day)}", ref)


def read_slots(ep: dict, caps: dict) -> tuple[dict[str, Slot], dict]:
    card = caps["card"]
    text = card["inside_text"] + "\n"
    rows = [m for m in ROW_RX.finditer(text) if m["ticker"] == ep["ticker"] and m["side"] == ep["side"]]
    if len(rows) < ep.get("nth", 1):
        raise InputError(f"STOP: the shown card has no {ep['ticker']} {ep['side']} row")
    m = rows[ep.get("nth", 1) - 1]
    perf = m["perf"].strip()
    pm = PP_RX.match(perf)
    if not pm:
        raise InputError(f"STOP: the row has no 'since filing vs SPY' figure today ({perf!r})")
    sign = "-" if pm["sign"] in "−-" else "+"
    if sign != ep["expect"]["gap_sign"]:
        raise InputError(f"STOP: the figure changed sign ({perf!r}); this template is written for {ep['expect']['gap_sign']}")
    if ep["expect"]["column"] not in card["visible_text"]:
        raise InputError(f"the card does not carry the column {ep['expect']['column']!r}")
    row_line = (f"{m['ticker']} {m['side']} · {perf} · Traded {m['traded']} · disclosed {m['filed']} · "
                f"{m['amount']} · {m['owner']} · {m['lag']}")
    ref = {**proof_ref(card, perf), "row": row_line}
    s: dict[str, Slot] = {}
    head = f"{ep['member']}: stock trades"
    s["member"] = Slot(ep["member"], ep["member"], proof_ref(caps["member"], head))
    s["possessive"] = Slot(ep["possessive"].upper(), ep["possessive"], s["member"].proof)
    s["member_pos"] = Slot(ep["member"] + "'s", ep["member"] + "'s", s["member"].proof)
    s["ticker"] = Slot(m["ticker"], " ".join(m["ticker"]), {**proof_ref(card, m["ticker"]), "row": row_line})
    s["side"] = Slot(m["side"].upper(), m["side"], {**proof_ref(card, m["side"]), "row": row_line})
    names_txt = caps["names"]["inside_text"]
    cm = re.search(rf"(?m)^{re.escape(m['ticker'])}\n(?P<company>[^\n]+)$", names_txt)
    if not cm or not cm["company"].startswith(ep["company"]["name_starts"]):
        raise InputError(f"the company name for {m['ticker']} is not on its capture")
    s["company"] = Slot(cm["company"], cm["company"], proof_ref(caps["names"], cm["company"]))
    s["short"] = Slot(ep["company"]["short"].upper(), ep["company"]["short"], s["company"].proof)
    s["short_mixed"] = Slot(ep["company"]["short"], ep["company"]["short"], s["company"].proof)
    s["bench"] = Slot("SPY", "S P Y", proof_ref(card, ep["expect"]["column"]))
    num = pm["num"]
    s["gap"] = Slot(num, decimal_words(num), {**proof_ref(card, perf), "row": row_line})
    s["gap_signed"] = Slot(("−" if sign == "-" else "+") + num, None, s["gap"].proof)
    near = math.ceil(float(num))
    if near - float(num) > 0.3 or near == float(num):
        raise InputError(f"'nearly {near}' would not be honest for {num}: change the hook template")
    s["gap_near"] = Slot(str(near), words(near), {**s["gap"].proof, "derived": f"ceil({num}) = {near}, within 0.3"})
    s["traded"] = iso_slots(m["traded"], {**proof_ref(card, m["traded"]), "row": row_line})
    s["filed"] = iso_slots(m["filed"], {**proof_ref(card, m["filed"]), "row": row_line})
    amts = re.findall(r"\$[\d,]+", m["amount"])
    hi = int(amts[-1][1:].replace(",", ""))
    s["amount"] = Slot(m["amount"], None, {**proof_ref(card, m["amount"]), "row": row_line})
    s["amount_hi"] = Slot(amts[-1], words(hi) + " dollars", s["amount"].proof)
    owner = {"spouse": "spouse's", "self": "own", "joint": "joint", "dependent child": "child's"}.get(m["owner"])
    if not owner:
        raise InputError(f"unknown owner {m['owner']!r}")
    s["owner"] = Slot(owner.upper(), owner, {**proof_ref(card, m["owner"]), "row": row_line})
    s["day"] = Slot(f"DAY {ep['day']}", None, None)
    s["possessive_mixed"] = Slot(ep["possessive"], ep["possessive"], s["member"].proof)
    s["side_l"] = Slot(m["side"], m["side"], s["side"].proof)
    s["owner_l"] = Slot(owner, owner, s["owner"].proof)
    s["traded_iso"] = Slot(m["traded"], None, s["traded"].proof)
    s["filed_iso"] = Slot(m["filed"], None, s["filed"].proof)
    facts = {"row": row_line, "ticker": m["ticker"], "side": m["side"], "perf": perf, "sign": sign, "gap": num,
             "traded": m["traded"], "filed": m["filed"], "amount": m["amount"], "owner": m["owner"], "lag": m["lag"]}
    latest = re.search(r"latest close \(([^)]+)\)", caps["scan"]["page_text"])
    facts["latest_close"] = latest.group(1) if latest else None
    return s, facts


# ======================================================================================== script
SLOT_RX = re.compile(r"\{([a-z_]+)\}")


def fill(tmpl: str, slots: dict[str, Slot], mode: str, used: set) -> str:
    if re.search(r"\d", SLOT_RX.sub("", tmpl)):
        raise InputError(f"a template types a number: {tmpl!r} (numbers are slots)")
    def rep(mm):
        k = mm.group(1)
        if k not in slots:
            raise InputError(f"no slot {k!r} in {tmpl!r}")
        used.add(k)
        v = slots[k]
        return v.show if mode == "show" else v.say
    return SLOT_RX.sub(rep, tmpl)


def say_map(s: str) -> str:
    return s.replace("RapidTradeView", "Rapid Trade View")


def build_script(ep: dict, slots: dict[str, Slot]) -> tuple[list[dict], set]:
    """lines: [{id, chunks: [{anchor, show, say, accent: [(word, color)], cap}]}]

    Chunk syntax in the episode: chunks split by " | "; a chunk may start with "@name " (an anchor the timeline uses)
    and "~" (spoken, no caption: the screen already shows it); a word prefixed "*" is the cyan accent, "!" the red one.
    """
    used: set = set()
    out = []
    for line in ep["lines"]:
        chunks = []
        for raw in line["text"].split(" | "):
            raw = raw.strip()
            anchor = None
            if raw.startswith("@"):
                anchor, raw = raw[1:].split(" ", 1)
            cap = True
            if raw.startswith("~"):
                cap, raw = False, raw[1:]
            accents = {}
            toks_show, toks_say = [], []
            for tok in raw.split(" "):
                color = None
                if tok[:1] in "*!":
                    color = "cyan" if tok[0] == "*" else "red"
                    tok = tok[1:]
                show = fill(tok, slots, "show", used)
                say = say_map(fill(tok, slots, "say", used))
                if color:
                    for wd in show.split(" "):
                        accents[wd.upper().strip(",.:;")] = color
                toks_show.append(show)
                toks_say.append(say)
            chunks.append({"anchor": anchor, "show": " ".join(toks_show).upper(), "say": " ".join(toks_say),
                           "accent": accents, "cap": cap})
        out.append({"id": line["id"], "gap_before": line.get("gap_before", 0.12), "speed_mul": line.get("speed_mul", 1.0),
                    "chunks": chunks})
    return out, used


def text_problems(texts: list[str]) -> list[str]:
    bad = []
    for x in texts:
        low = x.lower()
        for w in BANNED:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                bad.append(f"banned {w!r} in {x!r}")
        for w in PROVIDER_WORDS:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                bad.append(f"provider {w!r} in {x!r}")
        if PARTY_RX.search(x):
            bad.append(f"party label in {x!r}")
    return bad


# ======================================================================================== voice
def tts(lines: list[dict], run: Path, voice: str, speed: float) -> list[dict]:
    d = run / "tts"
    d.mkdir(parents=True, exist_ok=True)
    jobs = []
    for ln in lines:
        text = " ".join(c["say"] for c in ln["chunks"])
        ln["say"] = text
        spd = round(speed * ln.get("speed_mul", 1.0), 3)
        stem = f"{ln['id']}_{voice}_{spd:.3f}"
        ln["wav"], ln["timings"] = str(d / f"{stem}.wav"), str(d / f"{stem}.json")
        stamp_f = Path(ln["timings"] + ".txt.json")
        cached = Path(ln["wav"]).is_file() and stamp_f.is_file() and rjson(stamp_f) == text
        if not cached:
            jobs.append({"text": text, "voice": voice, "speed": spd, "out": ln["wav"], "timings": ln["timings"]})
    if jobs:
        bj = d / "batch.json"
        wjson(bj, jobs)
        env = dict(os.environ, RTV_OPS_CACHE=str(CACHE))
        r = subprocess.run([str(TTS_PY), str(CARTOON / "tts.py"), "--batch", str(bj)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        if r.returncode != 0:
            raise InputError("tts failed: " + r.stderr[-800:])
        for j in jobs:
            wjson(Path(j["timings"] + ".txt.json"), j["text"])
    for ln in lines:
        ws = rjson(Path(ln["timings"]))
        n_say = sum(len(c["say"].split()) for c in ln["chunks"])
        if len(ws) != n_say:
            raise InputError(f"word timing count {len(ws)} != script words {n_say} for {ln['id']}: "
                             f"{[w['word'] for w in ws]}")
        i = 0
        for c in ln["chunks"]:
            k = len(c["say"].split())
            c["words"] = ws[i:i + k]
            i += k
    return lines


def place_voice(lines: list[dict]) -> tuple[list[dict], float]:
    """Trim each clip to its speech and lay the lines end to end with their gaps. Returns clips and speech end."""
    import soundfile as sf
    t = 0.0
    clips = []
    for n, ln in enumerate(lines):
        a, sr = sf.read(ln["wav"], dtype="float32")
        ws = [w for c in ln["chunks"] for w in c["words"]]
        # the engine's last word "ends" after its trailing pause: cut at the real end of the sound instead
        hop = int(0.01 * sr)
        env = np.sqrt(np.convolve(a.astype(np.float64) ** 2, np.ones(hop) / hop, mode="same"))
        thr = env.max() * 10 ** (-38 / 20)
        loud = np.nonzero(env > thr)[0]
        snd_end = (loud[-1] / sr) if len(loud) else ws[-1]["end"]
        snd_start = (loud[0] / sr) if len(loud) else ws[0]["start"]
        s0 = max(0.0, min(ws[0]["start"], snd_start) - 0.02)
        s1 = min(len(a) / sr, snd_end + 0.05)
        ws[-1]["end"] = min(ws[-1]["end"], snd_end)
        if n > 0:
            t += ln["gap_before"]
        trimmed = a[int(s0 * sr):int(s1 * sr)]
        fade = int(0.006 * sr)
        trimmed[:fade] *= np.linspace(0, 1, fade)
        trimmed[-fade:] *= np.linspace(1, 0, fade)
        p = Path(ln["wav"]).with_suffix(".trim.wav")
        sf.write(p, trimmed, sr)
        off = t - s0
        for c in ln["chunks"]:
            for w in c["words"]:
                w["t0"], w["t1"] = round(w["start"] + off, 3), round(w["end"] + off, 3)
            c["t0"], c["t1"] = c["words"][0]["t0"], c["words"][-1]["t1"]
        ln["t0"], ln["t1"] = ln["chunks"][0]["t0"], ln["chunks"][-1]["t1"]
        clips.append({"wav": str(p), "at": round(t, 4)})
        t += (s1 - s0)
    return clips, t


# ======================================================================================== assets
def portrait(ep: dict, run: Path) -> dict:
    d = run / "portrait"
    d.mkdir(parents=True, exist_ok=True)
    src = d / f"{ep['bioguide']}.jpg"
    meta = d / "source.json"
    if not src.is_file():
        req = urllib.request.Request(ep["portrait"], headers={"User-Agent": "rtv-media-tools"})
        src.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        wjson(meta, {"url": ep["portrait"], "bioguide": ep["bioguide"], "member": ep["member"], "fetched_at": now_z(),
                     "sha256": sha256(src),
                     "licence": "Official portrait of a member of the US Congress: a work of the US government, public "
                                "domain (unitedstates/images, from the GPO Member Guide)."})
    return rjson(meta) | {"path": str(src)}


def depth_map(face_png: Path, out_png: Path) -> dict:
    if out_png.is_file() and out_png.stat().st_mtime >= face_png.stat().st_mtime:
        return {"model": "depth-anything/Depth-Anything-V2-Small-hf", "licence": "Apache-2.0", "cached": True}
    env = dict(os.environ, HF_HOME=str(CACHE / "epic-lab" / "hf"), HF_HUB_OFFLINE="1")
    code = ("import sys,numpy as np,torch;from PIL import Image;from transformers import pipeline;"
            "p=pipeline('depth-estimation',model='depth-anything/Depth-Anything-V2-Small-hf',device=0);"
            "im=Image.open(sys.argv[1]).convert('RGB');o=p(im);d=np.array(o['predicted_depth'].squeeze().cpu().float());"
            "d=(d-d.min())/(d.max()-d.min());Image.fromarray((d*255).astype('uint8')).resize(im.size,Image.BICUBIC)"
            ".save(sys.argv[2])")
    r = subprocess.run([str(CONDA_PY), "-c", code, str(face_png), str(out_png)], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise InputError("depth failed: " + r.stderr[-600:])
    return {"model": "depth-anything/Depth-Anything-V2-Small-hf", "licence": "Apache-2.0", "cached": False}


def brand_mark_spec() -> dict:
    d = rjson(BRAND_MARK_JSON)
    return {"path": d["path"], "bbox": d["bbox"], "viewBox": d["viewBox"], "tileRadius": d["tileRadius"],
            "bg": d["bg"], "mark": d["mark"], "source": str(BRAND_MARK_JSON)}


def card_assets(caps: dict, run: Path, slab_aspect: float) -> dict:
    a = run / "assets"
    a.mkdir(parents=True, exist_ok=True)
    side = caps["card"]
    im = Image.open(side["_png"]).convert("RGB")
    cw, ch = im.size
    hw = HOLD["w"]
    hh = round(ch * hw / cw)
    hold = im.resize((hw, hh), Image.LANCZOS)
    hold.save(a / "card_hold.png")
    shutil.copyfile(side["_png"], a / "card.png")
    boxes = {}
    tnames = list(caps["targets"].keys())
    for k, t in zip(tnames, side["targets"]):
        boxes[k] = t["box"]
    if len(side["targets"]) != len(tnames):
        raise InputError("the card capture did not return every target box")
    return {"card": "/run/assets/card.png", "card_hold": "/run/assets/card_hold.png", "card_w": cw, "card_h": ch,
            "hold": [HOLD["x"], HOLD["top"], hw, hh], "boxes": boxes, "hold_sha256": sha256(a / "card_hold.png")}


def face_assets(por: dict, run: Path, slab_aspect: float) -> dict:
    a = run / "assets"
    im = Image.open(por["path"]).convert("RGB")
    w, h = im.size
    ch = min(h, round(w / slab_aspect))
    cw = round(ch * slab_aspect)
    x0 = (w - cw) // 2
    face = im.crop((x0, 0, x0 + cw, ch))
    face.save(a / "face.png")
    dm = depth_map(a / "face.png", a / "face_depth_raw.png")
    from PIL import ImageFilter                # a soft depth map: no hard steps at the hair line, so no halo
    Image.open(a / "face_depth_raw.png").filter(ImageFilter.GaussianBlur(5)).save(a / "face_depth.png")
    dm["smoothing"] = "Gaussian blur 5 px on the depth map (never on the portrait)"
    return {"face": "/run/assets/face.png", "depth": "/run/assets/face_depth.png", "crop": [x0, 0, cw, ch],
            "src_size": [w, h], "depth_model": dm}


# ======================================================================================== timeline
def timeline(lines: list[dict]) -> dict:
    L = {ln["id"]: ln for ln in lines}
    anc = {c["anchor"]: c for ln in lines for c in ln["chunks"] if c["anchor"]}
    T = {}
    T["flip0"] = round(L["brand"]["t0"] - 0.32, 3)
    T["flip1"] = round(T["flip0"] + 0.5, 3)
    T["lock0"] = round(max(T["flip1"] + 1.05, anc["amount"]["t0"] - 0.55), 3)
    T["lock"] = []
    for key in ("amount", "owner", "traded", "filed"):
        T["lock"].append({"key": key, "t": anc[key]["t0"]})
    T["riser0"] = round(L["row"]["t1"] - 1.05, 3)
    T["cut_sink"] = round(L["row"]["t1"] + 0.02, 3)
    T["hit"] = L["sink"]["t0"]
    T["cut_row"] = round(anc["behind"]["t0"] - 0.05, 3)
    T["end0"] = round(L["end"]["t0"] - 0.08, 3)
    T["stamp"] = round(L["end"]["t0"] + 0.22, 3)
    T["brand_big"] = anc["brandend"]["t0"]
    T["chip"] = 1.25
    T["gapnum"] = anc["gapnum"]["t0"]
    T["disclaim"] = anc["disclaim"]["t0"]
    T["speech_end"] = L["end"]["t1"]
    T["loop0"] = round(L["end"]["t1"] - 0.15, 3)
    T["end"] = round(T["loop0"] + LOOP_TAIL, 3)
    return T


def captions(lines: list[dict], T: dict) -> list[dict]:
    caps = []
    for ln in lines:
        if ln["id"] == "hook":
            continue                            # the hook's headline carries the line on screen
        for c in ln["chunks"]:
            if not c["cap"]:
                continue
            parts = []
            for w in c["show"].split(" "):
                parts.append({"text": w.rstrip(",.:;"), "color": c["accent"].get(w.strip(",.:;"), "white")})
            caps.append({"t0": c["t0"], "t1": c["t1"], "parts": parts})
    for i, c in enumerate(caps):               # hold each caption until the next one starts (max +0.35 s)
        nxt = caps[i + 1]["t0"] if i + 1 < len(caps) else c["t1"] + 0.35
        c["t1"] = round(min(nxt, c["t1"] + 0.35), 3)
    return caps


# ======================================================================================== media helpers
def run_ff(args: list[str]) -> str:
    r = subprocess.run([str(FFMPEG), "-hide_banner", "-y"] + args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        raise InputError("ffmpeg failed: " + r.stderr[-1200:])
    return r.stderr


def loudness(path: Path) -> dict:
    err = run_ff(["-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"])
    tail = err[err.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail[tail.find("True peak"):])
    return {"integrated_lufs": float(i.group(1)), "true_peak_dbtp": float(tp.group(1))}


def master(pre: Path, out: Path, target: float = -14.0, ceiling_db: float = -2.0) -> dict:
    """Gain to -14 LUFS, then a true-peak limiter (4x oversampled) at -2 dBFS so the AAC encode stays under -1 dBTP.
    Two passes: the limiter takes a little loudness, the second pass puts it back."""
    lim = 10 ** (ceiling_db / 20)
    steps = []
    gain = target - loudness(pre)["integrated_lufs"]
    for _ in range(3):
        flt = (f"volume={gain:.3f}dB,aresample=192000,alimiter=limit={lim:.4f}:attack=0.5:release=40:level=false,"
               f"aresample=48000")
        run_ff(["-i", str(pre), "-af", flt, "-ar", "48000", "-c:a", "pcm_s24le", str(out)])
        m = loudness(out)
        steps.append({"gain_db": round(gain, 3), **m})
        if abs(m["integrated_lufs"] - target) <= 0.2:
            break
        gain += target - m["integrated_lufs"]
    return {"steps": steps, "limiter_ceiling_dbfs": ceiling_db}


def probe(path: Path) -> dict:
    r = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries",
                        "stream=codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(r.stdout)


def decode_frames(path: Path, times: list[float], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    for t in times:
        p = out_dir / f"t{t:06.2f}.png"
        run_ff(["-ss", f"{t:.4f}", "-i", str(path), "-frames:v", "1", str(p)])
        res.append(p)
    return res


def decode_all_small(path: Path, w: int = 108) -> np.ndarray:
    h = w * 16 // 9
    r = subprocess.run([str(FFMPEG), "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h}:flags=area", "-f", "rawvideo",
                        "-pix_fmt", "gray", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, np.uint8)
    return a.reshape(-1, h, w).astype(np.float32)


def font(size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / "Inter.ttf"), size)
    try:
        f.set_variation_by_axes([size if size < 32 else 32, 800])
    except Exception:
        pass
    return f


# ======================================================================================== QA
def qa(run: Path, ep: dict, R: dict, lines: list[dict], caps: dict, frames: dict, final: Path) -> dict:
    q: dict = {"checked_at": now_z()}
    pr = probe(final)
    v = next(s for s in pr["streams"] if s["codec_name"] == "h264")
    a = next(s for s in pr["streams"] if s["codec_name"] == "aac")
    dur = float(pr["format"]["duration"])
    num, den = v["r_frame_rate"].split("/")
    q["duration_s"] = round(dur, 3)
    q["fps"] = round(int(num) / int(den), 3)
    q["video"] = {"codec": v["codec_name"], "size": [v["width"], v["height"]]}
    q["audio"] = {"codec": a["codec_name"], "sample_rate": a["sample_rate"], "channels": a["channels"]}
    ld = loudness(final)
    q["loudness"] = ld
    allw = [w for ln in lines for c in ln["chunks"] for w in c["words"]]
    brand_ts = [w["t0"] for w in allw if w["word"].lower().startswith("rapid")]
    q["brand_word"] = {"first_s": brand_ts[0] if brand_ts else None, "last_s": brand_ts[-1] if brand_ts else None,
                       "count": len(brand_ts)}
    q["speech"] = {"first_word_s": allw[0]["t0"], "last_word_s": allw[-1]["t1"]}
    gaps = []
    for w0, w1 in zip(allw, allw[1:]):
        gaps.append((round(w1["t0"] - w0["t1"], 3), w0["word"], w1["word"], w0["t1"]))
    big = [g for g in gaps if g[0] > 0.25]
    q["speech_gaps_over_0_25s"] = [{"gap_s": g[0], "after": g[1], "before": g[2], "at_s": g[3]} for g in big]
    nwords = sum(len(ln["say"].split()) for ln in lines)
    speech_time = sum(ln["t1"] - ln["t0"] for ln in lines)
    q["words_per_s"] = round(nwords / speech_time, 3)
    q["words"] = nwords
    # frames: sampled every 0.5 s from the final video
    times = [round(x * 0.5, 2) for x in range(int(dur / 0.5) + 1) if x * 0.5 < dur - 0.02]
    fdir = run / "qa_frames"
    if fdir.exists():
        shutil.rmtree(fdir)
    sample = decode_frames(final, times, fdir)
    finfo = {round(f["t"], 2): f for f in frames["frames"]}
    ref = None
    marks = []
    for t, p in zip(times, sample):
        fi = finfo.get(round(round(t * FPS) / FPS, 2)) or min(frames["frames"], key=lambda f: abs(f["t"] - t))
        x, y, w, h = [int(round(z)) for z in fi["mark"]]
        im = np.asarray(Image.open(p).convert("RGB")).astype(np.float32)
        crop = im[y:y + h, x:x + w]
        g = crop[..., 1]
        green = float(np.mean((g > crop[..., 0] + 40) & (g > crop[..., 2] + 10)))
        blue = float(np.mean((crop[..., 2] > crop[..., 0] + 30) & (crop[..., 2] > 120)))
        cs = np.asarray(Image.fromarray(crop.astype(np.uint8)).resize((48, 48), Image.LANCZOS)).astype(np.float32)
        if ref is None:
            ref = cs
        a_, b_ = cs - cs.mean(), ref - ref.mean()
        ncc = float((a_ * b_).sum() / (np.sqrt((a_ ** 2).sum() * (b_ ** 2).sum()) + 1e-6))
        marks.append({"t": t, "rect": [x, y, w, h], "green_frac": round(green, 3), "tile_blue_frac": round(blue, 3),
                      "ncc_vs_frame0": round(ncc, 3), "ok": bool(green > 0.12 and blue > 0.12 and ncc > 0.75)})
    q["brand_mark"] = {"sampled": len(marks), "detected": sum(m["ok"] for m in marks),
                       "missing_at": [m["t"] for m in marks if not m["ok"]], "per_frame": marks}
    # flip hold: rendered PNG vs the Lanczos card, and the decoded video frame
    hx, hy, hw, hh = R["card"]["hold"]
    hold_png = run / "assets" / "card_hold.png"
    ref_card = np.asarray(Image.open(hold_png).convert("RGB")).astype(np.int16)
    th = round((R["T"]["flip1"] + R["T"]["lock0"]) / 2 * FPS) / FPS
    rp = run / "frames_png" / f"f{round(th * FPS):04d}.png"
    hold_q = {"t": th, "rect": [hx, hy, hw, hh]}
    if rp.is_file():
        got = np.asarray(Image.open(rp).convert("RGB")).astype(np.int16)[hy:hy + hh, hx:hx + hw]
        diff = np.abs(got - ref_card)
        hold_q["rendered_png"] = {"max_abs_diff": int(diff.max()), "mean_abs_diff": round(float(diff.mean()), 4),
                                  "identical_px_frac": round(float(np.mean(diff.max(axis=2) == 0)), 5)}
    dec = decode_frames(final, [th], run / "qa_hold")[0]
    got = np.asarray(Image.open(dec).convert("RGB")).astype(np.float32)[hy:hy + hh, hx:hx + hw]
    mse = float(np.mean((got - ref_card) ** 2))
    hold_q["decoded_video_psnr_db"] = round(10 * math.log10(255 ** 2 / max(mse, 1e-9)), 2)
    hold_q["held_s"] = round(R["T"]["lock0"] - R["T"]["flip1"], 3)
    hold_q["ok"] = (hold_q.get("rendered_png", {}).get("max_abs_diff", 99) <= 1 and hold_q["held_s"] >= 1.0)
    q["flip_hold_card"] = hold_q
    # captions and readable text inside the safe zone (boxes reported by the scene for every frame)
    out_boxes = []
    for f in frames["frames"]:
        for b in f.get("texts", []):
            x, y, w, h = b["box"]
            if x < SAFE[0] - 0.5 or y < SAFE[1] - 0.5 or x + w > SAFE[2] + 0.5 or y + h > SAFE[3] + 0.5:
                out_boxes.append({"t": f["t"], **b})
    cap_frames = [f for f in frames["frames"] if any(b["role"] == "caption" for b in f.get("texts", []))]
    q["safe_zone"] = {"zone": SAFE, "frames_with_captions": len(cap_frames),
                      "text_boxes_outside": len(out_boxes), "examples_outside": out_boxes[:8]}
    cap_sizes = sorted({b.get("size") for f in cap_frames for b in f["texts"] if b["role"] == "caption"})
    q["caption_font_px"] = cap_sizes
    # loop
    first = np.asarray(Image.open(sample[0]).convert("RGB")).astype(np.float32)
    (run / "qa_last").mkdir(exist_ok=True)
    lastp = run / "qa_last" / "last.png"
    run_ff(["-sseof", "-0.3", "-i", str(final), "-update", "1", "-q:v", "1", str(lastp)])
    last = np.asarray(Image.open(lastp).convert("RGB")).astype(np.float32)
    from PIL import ImageFilter
    fb = np.asarray(Image.open(sample[0]).convert("RGB").filter(ImageFilter.GaussianBlur(3))).astype(np.float32)
    lb = np.asarray(Image.open(lastp).convert("RGB").filter(ImageFilter.GaussianBlur(3))).astype(np.float32)
    q["loop"] = {"first_vs_last_mean_abs_diff": round(float(np.mean(np.abs(first - last))), 3),
                 "blurred_psnr_db": round(10 * math.log10(255 ** 2 / max(float(np.mean((fb - lb) ** 2)), 1e-9)), 2),
                 "note": "raw difference is mostly film grain (re-seeded per frame); blurred (3 px) compares the picture",
                 "first_vs_last_psnr_db": round(10 * math.log10(255 ** 2 / max(float(np.mean((first - last) ** 2)), 1e-9)), 2)}
    # banned words: the script (said and shown) and the capture text shown on screen
    script_texts = [ln["say"] for ln in lines] + [c["show"] for ln in lines for c in ln["chunks"]] + R["text"]["headline"] + \
        [R["text"][k] for k in ("counter", "sink_label", "stamp", "disclaimer", "site")]
    shown_capture = caps["card"]["inside_text"].split("\n")
    q["banned_scan"] = {"script_problems": text_problems(script_texts),
                        "capture_problems": text_problems(shown_capture),
                        "script_lines": len(script_texts), "capture_lines": len(shown_capture)}
    # visual changes
    ev = sorted(R["events"], key=lambda e: e["t"])
    gaps_ev = [(round(b["t"] - a_["t"], 3), a_["what"], b["what"]) for a_, b in zip(ev, ev[1:])]
    small = decode_all_small(final)
    d = np.abs(np.diff(small, axis=0)).mean(axis=(1, 2))
    still = d < 0.6
    longest, cur, at = 0, 0, 0
    for i, s in enumerate(still):
        cur = cur + 1 if s else 0
        if cur > longest:
            longest, at = cur, i - cur + 1
    q["visual_changes"] = {"events": len(ev), "list": [f"{e['t']:.2f} {e['what']}" for e in ev],
                           "max_gap_between_events_s": max(g[0] for g in gaps_ev),
                           "max_gap_between": max(gaps_ev)[1:],
                           "pixel_longest_still_s": round(longest / FPS, 3), "pixel_longest_still_from_s": round(at / FPS, 3),
                           "pixel_still_threshold": "mean abs frame diff < 0.6/255 at 108x192"}
    gates = {
        "duration_18_22": 18.0 <= dur <= 22.5,
        "fps_30": abs(q["fps"] - 30) < 0.01,
        "lufs_-14": abs(ld["integrated_lufs"] + 14) <= 0.6,
        "true_peak_le_-1": ld["true_peak_dbtp"] <= -1.0,
        "brand_spoken_before_4s": bool(brand_ts) and brand_ts[0] < 4.0,
        "brand_spoken_last_4s": bool(brand_ts) and brand_ts[-1] > dur - 4.5,
        "brand_mark_every_sample": q["brand_mark"]["detected"] == q["brand_mark"]["sampled"],
        "flip_hold_untouched": hold_q["ok"],
        "text_in_safe_zone": not out_boxes,
        "speech_from_0": allw[0]["t0"] <= 0.12,
        "no_banned": not q["banned_scan"]["script_problems"] and not q["banned_scan"]["capture_problems"],
        "events_max_gap_le_3s": q["visual_changes"]["max_gap_between_events_s"] <= 3.0,
        "words_per_s_2_7_3_0": 2.6 <= q["words_per_s"] <= 3.1,
        "loop_blurred_psnr_ge_35": q["loop"]["blurred_psnr_db"] >= 35,
    }
    gates = {k: bool(v) for k, v in gates.items()}
    q["gates"] = gates
    q["pass"] = bool(all(gates.values()))
    return q


# ======================================================================================== sheets
def label(im: Image.Image, text: str) -> Image.Image:
    d = ImageDraw.Draw(im)
    f = font(int(im.width * 0.09))
    d.rectangle((0, 0, im.width, int(im.width * 0.13)), fill=(0, 0, 0))
    d.text((8, 2), text, font=f, fill=(255, 255, 255))
    return im


def sheet(final: Path, run: Path, dur: float) -> Path:
    times = [round(x * 0.5, 2) for x in range(int(dur / 0.5) + 1) if x * 0.5 < dur - 0.02]
    ps = decode_frames(final, times, run / "sheet_frames")
    tw, th = 216, 384
    cols = 11
    rows = math.ceil(len(ps) / cols)
    sh = Image.new("RGB", (cols * tw, rows * (th + 4)), (20, 20, 24))
    for k, (t, p) in enumerate(zip(times, ps)):
        im = Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS)
        im = label(im, f"{t:.1f}s")
        sh.paste(im, ((k % cols) * tw, (k // cols) * (th + 4)))
    out = run / "sheet.png"
    sh.save(out)
    return out


def phone(final: Path, run: Path, R: dict) -> Path:
    T = R["T"]
    picks = [("frame 0", 0.0), ("flip hold", (T["flip1"] + T["lock0"]) / 2),
             ("row lock", T["lock"][0]["t"] + 0.6), ("sink", T["hit"] + 0.5)]
    ps = decode_frames(final, [p[1] for p in picks], run / "phone_frames")
    tiles = []
    for (name, t), p in zip(picks, ps):
        im = Image.open(p).convert("RGB").resize((360, 640), Image.LANCZOS)
        tiles.append(label(im, f"{name} {t:.1f}s"))
    out = Image.new("RGB", (len(tiles) * 370 - 10, 640), (255, 255, 255))
    for i, t in enumerate(tiles):
        out.paste(t, (i * 370, 0))
    p = run / "phone.png"
    out.save(p)
    return p


# ======================================================================================== main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode")
    ap.add_argument("--out", help="default <media>/.ops/filed/<slug>")
    ap.add_argument("--reuse-capture", action="store_true", help="use this run's captures (no new capture)")
    ap.add_argument("--stop-after", choices=["facts", "voice", "scene", "render"], help="stop early (iteration)")
    ap.add_argument("--skip-render", action="store_true", help="reuse this run's rendered video (sound/QA iteration)")
    ap.add_argument("--only", help="render only these frame indices to frames_png (look-dev)")
    a = ap.parse_args(argv)
    ep = rjson(Path(a.episode))
    run = Path(a.out) if a.out else MEDIA / ".ops" / "filed" / ep["slug"]
    run.mkdir(parents=True, exist_ok=True)
    log = []
    try:
        caps = load_captures(run) if a.reuse_capture else do_captures(ep, run)
        if not a.reuse_capture:
            wjson(run / "screens" / "targets.json", caps["targets"])
        else:
            caps["targets"] = rjson(run / "screens" / "targets.json")
        slots, facts = read_slots(ep, caps)
        party = [ln for ln in caps["card"]["visible_text"].split("\n") if PARTY_RX.search(ln)]
        if party:
            raise InputError(f"the shown card carries a party label: {party}")
        prov = text_problems([ln for ln in caps["card"]["visible_text"].split("\n")])
        lines, used = build_script(ep, slots)
        texts_all = [c["say"] for ln in lines for c in ln["chunks"]] + [c["show"] for ln in lines for c in ln["chunks"]]
        headline = [fill(h, slots, "show", used).upper() for h in ep["headline"]]
        bad = text_problems(texts_all + headline) + prov
        if bad:
            raise InputError("text problems: " + "; ".join(bad))
        log.append({"facts": facts})
        if a.stop_after == "facts":
            print(json.dumps({"facts": facts, "lines": [[c["show"] + " / " + c["say"] for c in ln["chunks"]] for ln in lines],
                              "headline": headline}, ensure_ascii=False, indent=1))
            return 0
        # voice, calibrated to the target pace
        vs = ep["voice"]
        speed = vs["speed"]
        for attempt in range(3):
            lines = tts(lines, run, vs["voice"], speed)
            clips, speech_end = place_voice(lines)
            nwords = sum(len(ln["say"].split()) for ln in lines)
            rate = nwords / sum(ln["t1"] - ln["t0"] for ln in lines)
            log.append({"voice": vs["voice"], "speed": speed, "words_per_s": round(rate, 3)})
            lo, hi = vs.get("target_wps", [2.75, 2.95])
            if lo <= rate <= hi:
                break
            speed = round(speed * ((lo + hi) / 2) / rate, 3)
        T = timeline(lines)
        T["end"] = round(round(T["end"] * FPS) / FPS, 4)   # whole frames: audio and video end together
        duration = T["end"]
        voice_script = {"voice": vs["voice"], "speed": speed, "engine": "Kokoro-82M (Apache-2.0), local",
                        "say_map": {"RapidTradeView": "Rapid Trade View", "SPY": "S P Y"},
                        "lines": [{"id": ln["id"], "say": ln["say"], "t0": ln["t0"], "t1": ln["t1"],
                                   "words": [{"word": w["word"], "t0": w["t0"], "t1": w["t1"]}
                                             for c in ln["chunks"] for w in c["words"]]} for ln in lines]}
        wjson(run / "voice_script.json", voice_script)
        (run / "voice_script.txt").write_text("\n".join(f"[{ln['t0']:.2f}-{ln['t1']:.2f}] {ln['say']}" for ln in lines)
                                              + "\n", encoding="utf-8")
        if a.stop_after == "voice":
            print(json.dumps({"T": T, "log": log}, indent=1))
            return 0
        # assets + render spec
        por = portrait(ep, run)
        slab_aspect = ep.get("slab_aspect", 0.9)
        card = card_assets(caps, run, slab_aspect)
        face = face_assets(por, run, slab_aspect)
        gap = float(facts["gap"])
        R = {
            "W": W, "H": H, "fps": FPS, "duration": duration, "day": ep["day"],
            "slab_aspect": slab_aspect,
            "text": {"wordmark": "RapidTradeView", "headline": headline, "headline_accent": ep["headline_accent"],
                     "counter": slots["gap_signed"].show, "counter_unit": "PTS",
                     "sink_label": ep["sink_label"], "ticker": slots["ticker"].show, "bench": slots["bench"].show,
                     "day": slots["day"].show, "site": "rapidtradeview.trade", "disclaimer": "Not investment advice.",
                     "stamp": "FILED.", "line_label": ep.get("line_label", "SPY")},
            "gap": gap, "sign": facts["sign"],
            "mark": brand_mark_spec(),
            "assets": {"face": face["face"], "depth": face["depth"], "card": card["card"], "card_hold": card["card_hold"]},
            "card": {"w": card["card_w"], "h": card["card_h"], "hold": card["hold"], "boxes": card["boxes"]},
            "T": T,
            "captions": captions(lines, T),
        }
        ev = [{"t": 0.0, "what": "monolith dolly + counter settle"}, {"t": T["chip"], "what": "ticker chip snaps in"},
              {"t": T["flip0"], "what": "the flip"}, {"t": T["flip1"], "what": "card lands flat"},
              {"t": T["lock0"], "what": "push-in to row"}]
        ev += [{"t": l_["t"], "what": f"highlight {l_['key']}"} for l_ in T["lock"]]
        ev += [{"t": T["cut_sink"], "what": "cut: sink scene"}, {"t": T["hit"], "what": "impact: tower drops"},
               {"t": T["gapnum"], "what": "gap bracket draws + counter punch"},
               {"t": T["cut_row"], "what": "cut: real row, figure highlighted"},
               {"t": T["cut_row"] + 0.55, "what": "push-in on the figure"}, {"t": T["end0"], "what": "cut: pull back"},
               {"t": T["stamp"], "what": "FILED stamp"}, {"t": T["brand_big"], "what": "brand + domain"},
               {"t": T["disclaim"], "what": "disclaimer line"},
               {"t": T["loop0"], "what": "loop return"}]
        R["events"] = ev
        wjson(run / "render.json", R)
        resolved = {**ep, "resolved_at": now_z(), "facts": facts,
                    "slots": {k: {"show": v.show, "say": v.say} for k, v in slots.items()},
                    "headline_resolved": headline, "timeline": T, "duration": duration, "voice_speed": speed}
        wjson(run / "episode.json", resolved)
        if a.stop_after == "scene":
            return 0
        # render
        fr_dir = run / "frames_png"
        hold_i = round((T["flip1"] + T["lock0"]) / 2 * FPS)
        save = sorted({0, hold_i, round((duration) * FPS) - 1, round((T["hit"] + 0.5) * FPS),
                       round((T["lock"][0]["t"] + 0.6) * FPS)})
        if a.only:
            r = subprocess.run([str(CONDA_PY), str(HERE / "render.py"), "--run", str(run), "--ffmpeg", str(FFMPEG),
                                "--frames-dir", str(fr_dir), "--only", a.only], capture_output=True, text=True)
            print(r.stdout[-2000:], r.stderr[-3000:])
            return 0 if r.returncode == 0 else 2
        if a.skip_render and (run / "video_noaudio.mp4").is_file() and (run / "frames.json").is_file():
            rend = {k: v for k, v in rjson(run / "frames.json").items() if k != "frames"} | {"reused": True}
        else:
            r = subprocess.run([str(CONDA_PY), str(HERE / "render.py"), "--run", str(run), "--ffmpeg", str(FFMPEG),
                                "--frames-dir", str(fr_dir), "--save", ",".join(map(str, save))],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise InputError("render failed: " + r.stdout[-800:] + r.stderr[-2000:])
            rend = json.loads(r.stdout.strip().splitlines()[-1])
        log.append({"render": rend})
        frames = rjson(run / "frames.json")
        # sound
        kit = sound.make_kit(KIT_DIR)
        L = {ln["id"]: ln for ln in lines}
        cues = [{"sfx": "sub_boom", "at": 0.0, "gain_db": -6},
                {"sfx": "tick", "at": T["chip"], "gain_db": -6},
                {"sfx": "whoosh", "at": T["flip0"] - 0.05, "gain_db": 0},
                {"sfx": "tick", "at": T["flip1"], "gain_db": -8},
                {"sfx": "whoosh", "at": T["lock0"] - 0.05, "gain_db": -8}]
        cues += [{"sfx": "swish", "at": l_["t"], "gain_db": -4} for l_ in T["lock"]]
        riser_len = 1.1
        cues += [{"sfx": "riser", "at": T["hit"] - 0.22 - riser_len, "gain_db": -3},
                 {"sfx": "impact", "at": T["hit"], "gain_db": 0},
                 {"sfx": "whoosh", "at": T["cut_row"] - 0.08, "gain_db": -8},
                 {"sfx": "swish", "at": T["cut_row"] + 0.1, "gain_db": -5},
                 {"sfx": "whoosh", "at": T["end0"] - 0.1, "gain_db": -6},
                 {"sfx": "stamp", "at": T["stamp"], "gain_db": -2},
                 {"sfx": "whoosh", "at": T["loop0"], "gain_db": -9}]
        pre = run / "mix_pre.wav"
        mixinfo = sound.mix(clips, cues, duration, pre, kit, bed_under_voice_db=ep.get("bed_under_voice_db", 19.0),
                            bed_mute=[(T["hit"] - 0.22, T["hit"])])
        mixed = run / "mix.wav"
        final = run / "final.mp4"
        ceiling = -2.5
        for _ in range(3):                    # the AAC encode overshoots the PCM peak: measure the mp4, tighten, redo
            minfo = master(pre, mixed, ceiling_db=ceiling)
            run_ff(["-i", str(run / "video_noaudio.mp4"), "-i", str(mixed), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(final)])
            fl = loudness(final)
            minfo["final_mp4"] = fl
            if fl["true_peak_dbtp"] <= -1.1:
                break
            ceiling -= fl["true_peak_dbtp"] + 1.3
        shutil.copyfile(fr_dir / "f0000.png", run / "frame0.png")
        sheet(final, run, duration)
        phone(final, run, R)
        q = qa(run, ep, R, lines, caps, frames, final)
        q["render"] = {k: v for k, v in rend.items()}
        q["mix"] = mixinfo
        wjson(run / "qa.json", q)
        # proof
        fonts = [{"file": str(FONTS / f), "licence": "SIL Open Font License 1.1", "licence_file": str(FONTS / lic),
                  "sha256": sha256(FONTS / f)} for f, lic in (("ArchivoBlack-Regular.ttf", "OFL-ArchivoBlack.txt"),
                                                               ("Inter.ttf", "OFL-Inter.txt"),
                                                               ("JetBrainsMono.ttf", "OFL-JetBrainsMono.txt"))]
        stated = {}
        for k in sorted(used | {"gap_signed", "amount", "traded", "filed", "ticker"}):
            sl = slots[k]
            if sl.proof:
                stated[k] = {"show": sl.show, "say": sl.say, **sl.proof}
        proof = {
            "episode": ep["slug"], "built_at": now_z(), "final_mp4": str(final), "final_sha256": sha256(final),
            "row": facts["row"], "latest_close_named_on_page": facts["latest_close"],
            "stated": stated,
            "captures": {n: {"png": c["_png"], "sha256": c["sha256"], "captured_at": c["captured_at"], "url": c["url"],
                             "shown_on_screen": n == "card"} for n, c in caps.items() if n != "targets"},
            "portrait": {k: por[k] for k in ("url", "bioguide", "member", "sha256", "fetched_at", "licence")}
            | {"crop": face["crop"], "scaling": "none (cropped only); GPU texture sampling, no AI",
               "depth_model": face["depth_model"]},
            "fonts": fonts,
            "audio": {"voice": {"engine": "Kokoro-82M", "licence": "Apache-2.0", "voice": vs["voice"], "speed": speed},
                      "sfx": {k: {"file": str(p), "sha256": sha256(p), "licence": "synthesised (numpy, sound.py)"}
                              for k, p in kit.items()},
                      "bed": "synthesised (numpy, sound.py bed(), periodic over the episode)"},
            "code": {"three.js": "MIT (three@0.170.0)", "brand_mark": str(BRAND_MARK_JSON)},
            "mix": {"pre": mixinfo, "master": minfo},
        }
        wjson(run / "proof.json", proof)
        yt = {"title": fill(ep["youtube"]["title"], slots, "show", set()),
              "description": fill(ep["youtube"]["description"], slots, "show", set())}
        wjson(run / "youtube.json", yt)
        wjson(run / "build_log.json", log)
        print(json.dumps({"final": str(final), "duration": duration, "qa_pass": q["pass"], "gates": q["gates"]}, indent=1))
        return 0 if q["pass"] else 1
    except InputError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        wjson(run / "build_log.json", log + [{"error": str(e)}])
        return 2


if __name__ == "__main__":
    sys.exit(main())
