"""Member-story Short (format "member story", 2026-11-13): a member of Congress, one disclosed trade, our real page as proof.

    PY=C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe
    $PY tools/gv/scripts/cartoon/make_member_story.py --list
    $PY tools/gv/scripts/cartoon/make_member_story.py <story-id> --capture        # capture today + render + QA
    $PY tools/gv/scripts/cartoon/make_member_story.py <story-id>                  # render again from today's captures

Output (default <media>/.ops/yt-shorts/<story-id>/): short.mp4, sheet.png (one frame per second), frame0.png,
proof.json (every stated name, number and date with the capture sidecar and the page text it was read from),
qa.json, youtube.json, voice_script.txt, screens/ (the captures + sidecars), portrait.jpg + portrait_source.json,
project.fcproj (open in FilmCraft), build_log.jsonl.

Shots (at most 4, 15-20 s):
  1 HOOK     the official portrait (US government work, public domain) with a slow push-in, the member's name and one
             fact of at most 9 words; the voice says "RapidTradeView" in its first second.
  2 PROOF    the member's real page (the "Disclosed trades" table) at phone width, whole; an eased camera move onto the
             trade's row, outlined in place; the voice reads the trade date, the filing date and the amount range.
  3 CONTEXT  one more real card from the site (the member's buy/sell counts, or the hub's most-bought list), outlined.
  4 END      "See every trade, free." + the brand + "Search RapidTradeView" + "Not investment advice."
The RapidTradeView pill is on every frame. Captions (shots 2-3) sit under the page window and never cover it.

Facts are never typed: every number, date and amount is a {slot} read from a capture of the live page made today
(capture.py, DOM sidecar). The member's name must be on the captured page; the company's short name must start the
company name the site prints next to the ticker. No provider names, no party labels, no wrongdoing words, no advice.
Renders with FilmCraft 0.20.1 (headless, `filmcraft-cli mcp`); the pill, the hook text and the end card are drawn with
the card_reel PIL helpers. Exit 0 = rendered and QA passed, 1 = QA failed (the files are kept for a look), 2 = input
or capture error (no video).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent


def _media_root() -> Path:
    """The main checkout (the first parent that has .ops/cache): renders and caches live there, also from a worktree."""
    for p in HERE.parents:
        if (p / ".ops" / "cache").is_dir():
            return p
    raise SystemExit("no .ops/cache above make_member_story.py")


MEDIA = _media_root()
OPS = MEDIA / ".ops"
os.environ.setdefault("RTV_VSCO_DIR", str(OPS / "cache" / "vsco-2-ce-1.1.0"))
sys.path.insert(0, str(HERE.parent / "v6cat"))
sys.path.insert(0, str(HERE))
import card_reel as CRD  # noqa: E402
import cartoon_reel as CR  # noqa: E402
import vsco_score  # noqa: E402
from fcmcp import FilmCraft, t as ft  # noqa: E402

REGISTRY = HERE / "member_stories.json"
SHOT_PY = OPS / "cache" / "shot-venv" / "Scripts" / "python.exe"
TTS_PY = OPS / "cache" / "tts-venv" / "Scripts" / "python.exe"
W, H, FPS = 1080, 1920, 30
SR = vsco_score.SR
WIN = (20, 342, 1060, 1440)                     # the page window: full phone width, under the pill, above the captions
WIN_CY = (WIN[1] + WIN[3]) / 2
PILL_XY = (54, 262)
CAPTION_MARGIN = 0.19                           # captions' bottom at y 1555 (the platforms' bottom 18% starts at 1574)
BG_TOP, BG_BOTTOM = (11, 8, 32), (36, 16, 74)
CYAN = "#22d3ee"
DURATION = (15.0, 20.0)
LUFS = (-15.0, -13.0)
MAX_CAPTURE_AGE_H = 12
VOICE, SPEED = "narrator", 1.15
BANNED = ("insider trading", "suspicious", "how is this legal", "corrupt", "caught", "illegal", "scandal", "shady",
          "democrat", "republican", "gop", "party", "you should", "buy now", "should buy", "copy congress", "follow the money")
PARTY_RX = re.compile(r"\b(Democrat|Republican|Independent)\b|·\s[DRI]\s·")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December"]


class InputError(RuntimeError):
    pass


# ============================================================================================ words for the voice
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def words(n: int) -> str:
    """12 -> "twelve", 500001 -> "five hundred thousand and one", 1000000 -> "one million"."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" and " + words(n % 100) if n % 100 else "")
    for unit, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= unit:
            head, rest = divmod(n, unit)
            tail = "" if not rest else (" and " if rest < 100 else " ") + words(rest)
            return words(head) + " " + name + tail
    raise ValueError(n)


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def money_say(s: str) -> str:
    """"$500,001–$1,000,000" -> "five hundred thousand and one to one million dollars"."""
    parts = [int(p.replace(",", "")) for p in re.findall(r"\$([\d,]+)", s)]
    if not parts or len(parts) > 2:
        raise InputError(f"not an amount: {s!r}")
    return " to ".join(words(p) for p in parts) + " dollars"


class Slot:
    def __init__(self, show: str, say: str | None = None, proof: dict | None = None, kind: str = "text"):
        self.show, self.say, self.proof, self.kind = show, say if say is not None else show, proof, kind


def date_slots(iso: str, proof: dict) -> tuple[Slot, Slot]:
    d = dt.date.fromisoformat(iso)
    short = Slot(f"{MONTHS[d.month - 1][:3]} {d.day}", f"{MONTHS[d.month - 1]} {ordinal(d.day)}", proof, "date")
    long = Slot(f"{MONTHS[d.month - 1][:3]} {d.day}, {d.year}", f"{MONTHS[d.month - 1]} {ordinal(d.day)}, {d.year}", proof,
                "date")
    return short, long


def count_slot(v: str, proof: dict) -> Slot:
    return Slot(str(int(v)), words(int(v)), proof, "count")


OWNER_ACCOUNT = {"spouse": "spouse's account", "self": "own account", "joint w/ spouse": "joint account with spouse",
                 "dependent child": "dependent child's account", "joint": "joint account"}


# ============================================================================================ captures
def run_capture(name: str, spec: dict, out: Path) -> dict:
    cmd = [str(SHOT_PY), "-I", str(HERE / "capture.py"), "--url", spec["url"], "--out", str(out), "--name", name,
           "--viewport", "390x844", "--dpr", "3"]
    if "top" in spec:
        pad = spec.get("pad", [8, 8])
        cmd += ["--strip-top", spec["top"], "--strip-bottom", spec["bottom"], "--strip-pad", str(pad[0]),
                "--strip-pad-bottom", str(pad[1])]
        for k in spec.get("key", []):
            cmd += ["--target", k]
    else:                                         # a name lookup: the viewport around one text, never shown
        cmd += ["--scroll-to", spec["target"], "--target", spec["target"]]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise InputError(f"capture {name} failed: {(r.stderr or r.stdout).strip()[-600:]}")
    return json.loads((out / f"{name}.json").read_text(encoding="utf-8"))


def load_capture(name: str, screens: Path) -> dict:
    p = screens / f"{name}.json"
    if not p.is_file():
        raise InputError(f"no capture {p} (run with --capture)")
    side = json.loads(p.read_text(encoding="utf-8"))
    import cartoon_qa as Q
    if Q.capture_seal(side) != side.get("seal"):
        raise InputError(f"{p} was edited after the capture (seal mismatch): capture again")
    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(side["captured_at"], "%Y-%m-%dT%H:%M:%SZ")
           .replace(tzinfo=dt.timezone.utc)).total_seconds() / 3600
    if age > MAX_CAPTURE_AGE_H:
        raise InputError(f"capture {name} is {age:.1f} h old (max {MAX_CAPTURE_AGE_H} h): run with --capture")
    side["_path"] = str(p)
    side["_png"] = str(screens / f"{name}.png")
    return side


def proof_ref(side: dict, found: str) -> dict:
    return {"capture": side["_path"], "png": side["_png"], "url": side["url"], "captured_at": side["captured_at"],
            "png_sha256": side["sha256"], "text_found": found}


ROW_RX = re.compile(r"(?m)^(?P<ticker>[A-Z][A-Z.]*)\n(?P<side>buy|sell|exchange)\n(?P<perf>(?:(?!Traded\n)[^\n]*\n)*?)"
                    r"Traded\n(?P<traded>\d{4}-\d\d-\d\d)\n·\ndisclosed\n(?P<filed>\d{4}-\d\d-\d\d)\n"
                    r"(?P<amount>\$[\d,]+(?:–\$[\d,]+)?)\n(?P<owner>[^\n]+)\n")


def read_slots(story: dict, caps: dict) -> dict[str, Slot]:
    s: dict[str, Slot] = {}
    proof = caps["proof"]
    member = story["member"]
    head = f"{member}: stock trades"
    if head not in proof["page_text"]:
        raise InputError(f"the member page does not carry {head!r}")
    s["member"] = Slot(member, member, proof_ref(proof, head), "name")
    s["pronoun"] = Slot(story["pronoun"])
    s["pronoun_cap"] = Slot(story["pronoun"].capitalize())
    s["ticker"] = Slot(story["ticker"], " ".join(story["ticker"]), None, "ticker")
    rows = [m.groupdict() for m in ROW_RX.finditer(proof["inside_text"] + "\n")]
    mine = [r for r in rows if r["ticker"] == story["ticker"] and r["side"] == story["side"]]
    if len(mine) < story["nth"]:
        raise InputError(f"the proof strip has {len(mine)} {story['ticker']} {story['side']} rows (need #{story['nth']})")
    row = mine[story["nth"] - 1]
    row_text = (f"{row['ticker']} {row['side'].upper()} · Traded {row['traded']} · disclosed {row['filed']} · "
                f"{row['amount']} {row['owner']}")
    ref = proof_ref(proof, row_text)
    s["ticker"].proof = ref
    s["traded"], s["traded_long"] = date_slots(row["traded"], ref)
    s["filed"], s["filed_long"] = date_slots(row["filed"], ref)
    s["amount"] = Slot(row["amount"], money_say(row["amount"]), ref, "amount")
    hi = re.findall(r"\$[\d,]+", row["amount"])[-1]
    s["amount_hi"] = Slot(hi, money_say(hi), ref, "amount")
    if row["owner"] not in OWNER_ACCOUNT:
        raise InputError(f"unknown owner {row['owner']!r} on the row")
    s["owner_account"] = Slot(OWNER_ACCOUNT[row["owner"]], None, ref, "text")
    same = [r for r in mine if (r["traded"], r["filed"], r["amount"]) == (row["traded"], row["filed"], row["amount"])]
    s["rows_same"] = count_slot(str(len(same)), proof_ref(proof, f"{len(same)} rows: {row_text}"))
    # the key the video outlines must be this row: its amount target is the row's amount
    amt_targets = [k for k in story["captures"]["proof"]["key"] if k.startswith("$")]
    if amt_targets and amt_targets[0].split("#")[0] != row["amount"]:
        raise InputError(f"the outlined amount {amt_targets[0]!r} is not the row's amount {row['amount']!r}")
    ctx_spec = story["captures"]["context"]
    ctx = caps["context"]
    m = re.search(ctx_spec["rx"], ctx["inside_text"])
    if not m:
        raise InputError("the context capture does not match its reader (the page changed, or today does not carry it)")
    cref = proof_ref(ctx, m.group(0).replace("\n", " "))
    for k, v in m.groupdict().items():
        s[k] = count_slot(v, cref) if v.isdigit() else Slot(v, None, cref)
    for k, want in ctx_spec.get("require", {}).items():
        want = want.format_map({kk: vv.show for kk, vv in s.items()})
        if s[k].show != want:
            raise InputError(f"context {k} is {s[k].show!r}, the story needs {want!r}")
    cf = story["company_from"]
    cside = caps[cf["capture"]]
    m = re.search(cf["rx"], cside["inside_text"])
    if not m:
        raise InputError("the company name is not on its capture")
    company = m.group("company")
    if not company.lower().startswith(story["short"].lower()):
        raise InputError(f"the short name {story['short']!r} does not start the site's company name {company!r}")
    s["company"] = Slot(company, None, proof_ref(cside, f"{story['ticker']} {company}"), "name")
    s["short"] = Slot(story["short"], None, proof_ref(cside, f"{story['ticker']} {company}"), "name")
    return s


def render(tmpl: str, slots: dict[str, Slot], mode: str, used: set | None = None) -> str:
    if re.search(r"\d", re.sub(r"\{[a-z_]+\}", "", tmpl)):
        raise InputError(f"a line types a number: {tmpl!r} (numbers are slots)")
    for k in re.findall(r"\{([a-z_]+)\}", tmpl):
        if k not in slots:
            raise InputError(f"no slot {k!r} for {tmpl!r}")
        if used is not None:
            used.add(k)
    return tmpl.format_map({k: (v.show if mode == "show" else v.say) for k, v in slots.items()})


def say_text(s: str) -> str:
    return s.replace("RapidTradeView", "Rapid Trade View")


def text_problems(texts: list[str]) -> list[str]:
    bad = []
    for x in texts:
        low = x.lower()
        bad += [f"banned word {w!r} in {x!r}" for w in BANNED if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low)]
        if CRD.PROVIDER_RX.search(x):
            bad.append(f"provider name in {x!r}")
    return bad


# ============================================================================================ pictures (PIL)
def bg_image() -> Image.Image:
    y = np.linspace(0, 1, H)[:, None]
    top, bot = np.array(BG_TOP, float), np.array(BG_BOTTOM, float)
    arr = (top * (1 - y) + bot * y)[:, None, :].repeat(W, axis=1)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def bands_overlay(bg: Image.Image) -> Image.Image:
    """The page window: the background above it (under the pill) and below it (the caption band), a thin rim."""
    o = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    o.paste(bg.crop((0, 0, W, WIN[1])), (0, 0))
    o.paste(bg.crop((0, WIN[3], W, H)), (0, WIN[3]))
    o.paste(bg.crop((0, WIN[1], WIN[0], WIN[3])), (0, WIN[1]))
    o.paste(bg.crop((WIN[2], WIN[1], W, WIN[3])), (WIN[2], WIN[1]))
    d = ImageDraw.Draw(o)
    d.rounded_rectangle((WIN[0] - 2, WIN[1] - 2, WIN[2] + 1, WIN[3] + 1), radius=10, outline=(124, 58, 237, 150), width=2)
    return o


def hook_overlays(name: str, fact: str, bg: Image.Image) -> tuple[Image.Image, Image.Image]:
    """(the dark ramp under the text, the text: a small label, the name, the fact with its figures in cyan)."""
    ramp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    a = np.clip((np.arange(H) - 900) / 420, 0, 1) ** 1.3
    bga = np.asarray(bg.convert("RGB")).astype(np.uint8)
    rgba = np.dstack([bga, (a[:, None].repeat(W, 1) * 255).astype(np.uint8)])
    ramp = Image.fromarray(rgba, "RGBA")
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    x0, maxw = 64, 860
    lab = CRD.font("bold", 40)
    d.text((x0, 1100), "MEMBER OF CONGRESS", font=lab, fill=(56, 225, 245, 255))
    nf = CRD.fit_font("black", name, maxw, 108, 60)
    nb = d.textbbox((0, 0), name, font=nf)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.text((x0 + 3, 1166 - nb[1] + 4), name, font=nf, fill=(0, 0, 0, 200))
    d.text((x0, 1166 - nb[1]), name, font=nf, fill=(255, 255, 255, 255))
    y = 1166 + (nb[3] - nb[1]) + 34
    # the fact: up to two lines, as large as fits; figures in cyan
    for size in range(92, 58, -2):
        ff = CRD.font("black", size)
        lines, cur = [], ""
        for w_ in fact.split():
            trial = (cur + " " + w_).strip()
            if d.textlength(trial, font=ff) <= maxw:
                cur = trial
            else:
                lines.append(cur)
                cur = w_
        lines.append(cur)
        if len(lines) <= 2 and all(d.textlength(li, font=ff) <= maxw for li in lines):
            break
    else:
        raise InputError(f"the hook fact does not fit two lines: {fact!r}")
    lh = round(size * 1.12)
    if y + lh * len(lines) > 1560:
        raise InputError("the hook text runs into the platforms' bottom band")
    for li in lines:
        x = x0
        for tok in re.split(r"(\s+)", li):
            if not tok:
                continue
            col = CRD.ACCENT + (255,) if re.search(r"[$\d]", tok) else (255, 255, 255, 255)
            sd.text((x + 3, y + 4), tok, font=ff, fill=(0, 0, 0, 200))
            d.text((x, y), tok, font=ff, fill=col)
            x += d.textlength(tok, font=ff)
        y += lh
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    shadow.alpha_composite(txt)
    return ramp, shadow


CAPTION_CY = 1500                               # caption band: y 1446-1554, under the window, above the bottom 18%


def caption_png(text: str) -> Image.Image:
    """One caption line: white, figures in cyan, a black outline; as large as fits 900 px (76 down to 52), never wrapped."""
    probe_d = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    for size in range(76, 50, -2):
        f = CRD.font("black", size)
        if probe_d.textlength(text, font=f) + 2 * 7 <= 900:
            break
    else:
        raise InputError(f"caption too long for one line: {text!r}")
    o = Image.new("RGBA", (W, 150), (0, 0, 0, 0))
    d = ImageDraw.Draw(o)
    x = (W - d.textlength(text, font=f)) / 2
    bb = d.textbbox((0, 0), "Ag$", font=f)
    y = (150 - (bb[3] - bb[1])) / 2 - bb[1]
    for tok in re.split(r"(\s+)", text):
        if not tok:
            continue
        col = CRD.ACCENT + (255,) if re.search(r"[$\d]", tok) else (255, 255, 255, 255)
        d.text((x, y), tok, font=f, fill=col, stroke_width=7, stroke_fill=(0, 0, 0, 255))
        x += d.textlength(tok, font=f)
    return o


def end_card() -> Image.Image:
    o = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(o)

    def centred(text, f, y, fill):
        w_ = d.textlength(text, font=f)
        d.text(((W - w_) / 2, y), text, font=f, fill=fill)

    centred("See every trade, free.", CRD.font("black", 66), 640, (255, 255, 255, 255))
    pl = CRD.pill(CRD.BRAND, 68, round(68 * 0.65), round(68 * 0.4))
    o.alpha_composite(pl, ((W - pl.size[0]) // 2, 790))
    f = CRD.font("bold", 58)
    label = "Search RapidTradeView"
    tw = d.textlength(label, font=f)
    bx0, by0 = (W - tw) / 2 - 44, 990
    d.rounded_rectangle((bx0, by0, bx0 + tw + 88, by0 + 108), radius=54, fill=(255, 255, 255, 255))
    d.text((bx0 + 44, by0 + 18), label, font=f, fill=(11, 8, 32, 255))
    centred("rapidtradeview.trade", CRD.font("semi", 44), 1140, (196, 181, 253, 255))
    centred(CRD.DISCLAIMER, CRD.font("bold", 46), 1236, (220, 220, 230, 255))
    return o


# ============================================================================================ voice + music
def tts(lines: list[str], work: Path, speed: float) -> list[dict]:
    work.mkdir(parents=True, exist_ok=True)
    jobs, out = [], []
    for i, text in enumerate(lines):
        wav, tim = work / f"line{i}.wav", work / f"line{i}.json"
        key = hashlib.sha256(f"{VOICE}|{speed}|{text}".encode()).hexdigest()[:16]
        out.append({"text": text, "wav": wav, "timings": tim, "key": key})
        stamp = work / f"line{i}.key"
        if not (wav.is_file() and tim.is_file() and stamp.is_file() and stamp.read_text() == key):
            jobs.append({"text": text, "voice": VOICE, "speed": speed, "out": str(wav), "timings": str(tim)})
            stamp.unlink(missing_ok=True)
    if jobs:
        jf = work / "batch.json"
        jf.write_text(json.dumps(jobs), encoding="utf-8")
        r = subprocess.run([str(TTS_PY), "-I", str(HERE / "tts.py"), "--batch", str(jf)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise InputError(f"tts failed: {r.stderr[-800:]}")
        for o in out:
            (work / f"{o['wav'].stem}.key").write_text(o["key"])
    for o in out:
        with wave.open(str(o["wav"])) as w:
            a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768.0
            o["sr"] = w.getframerate()
        from scipy.signal import resample_poly
        o["audio"] = resample_poly(a, SR, o["sr"]) if o["sr"] != SR else a
        o["dur"] = len(o["audio"]) / SR
        o["words"] = json.loads(o["timings"].read_text(encoding="utf-8"))
    return out


def chunk_times(chunks_say: list[str], words_: list[dict]) -> list[tuple[float, float]]:
    """Each chunk's (start, end) in the line, from the engine's word timings (counts must agree: no guessing)."""
    counts = [len(c.split()) for c in chunks_say]
    if sum(counts) != len(words_):
        raise InputError(f"the voice has {len(words_)} words, the chunks {sum(counts)}: {chunks_say} / "
                         f"{[w['word'] for w in words_]}")
    out, i = [], 0
    for c in counts:
        out.append((words_[i]["start"], words_[i + c - 1]["end"]))
        i += c
    return out


def build_mix(vo_items: list[tuple[float, np.ndarray]], cuts: list[float], end_start: float, total: float,
              out: Path, ffmpeg: str) -> Path:
    n = int(round(total * SR))
    vo = np.zeros(n)
    for start, a in vo_items:
        i0 = int(round(start * SR))
        seg = a[: max(0, n - i0)]
        vo[i0:i0 + len(seg)] += seg
    mix, _music, _inst, score = vsco_score.compose(cuts[0], cuts[1:], [0], end_start, total)
    mix = mix[:n] if len(mix) >= n else np.vstack([mix, np.zeros((n - len(mix), 2))])
    win = int(0.05 * SR)
    env = np.sqrt(np.convolve(vo ** 2, np.ones(win) / win, "same"))
    active = (env > 10 ** (-38 / 20)).astype(float)
    g = np.empty(n)
    a_att, a_rel = math.exp(-1 / (0.03 * SR)), math.exp(-1 / (0.25 * SR))
    cur, blk = 0.0, 48
    for i in range(0, n, blk):
        target = active[i:i + blk].max()
        coef = a_att if target > cur else a_rel
        cur = target + (cur - target) * coef ** blk
        g[i:i + blk] = cur
    gain = 10 ** ((-12.0 + -9.0 * g) / 20)
    total_mix = mix * gain[:, None] + vo[:, None]
    total_mix = 0.95 * np.tanh(total_mix / 0.95)
    tmp = out / "mix_pre.wav"
    CR.write_wav(tmp, np.clip(total_mix, -1, 1))
    meas = CR.loudnorm_measure(tmp, ffmpeg)
    for _ in range(4):
        total_mix = CR.limiter(total_mix * 10 ** ((-14.0 - meas["I"]) / 20), 10 ** (-2.0 / 20))
        CR.write_wav(tmp, np.clip(total_mix, -1, 1))
        meas = CR.loudnorm_measure(tmp, ffmpeg)
        if abs(meas["I"] + 14.0) < 0.4 and meas["TP"] <= -1.5:
            break
    wav = out / "mix.wav"
    os.replace(tmp, wav)
    (out / "score.json").write_text(json.dumps(score, indent=1), encoding="utf-8")
    return wav


# ============================================================================================ the plan
def snap(x: float) -> float:
    return round(x * FPS) / FPS


def key_box(side: dict, pad_css: list[float]) -> tuple[float, float, float, float]:
    """The outline's box in strip px: the union of the key targets, padded, made symmetric across the page (the whole
    row: its left text and its right-hand value)."""
    k = side["dpr"]
    bs = [tg["box"] for tg in side["targets"]]
    x0 = min(b[0] for b in bs) - pad_css[0] * k
    y0 = min(b[1] for b in bs) - pad_css[1] * k
    y1 = max(b[1] + b[3] for b in bs) + pad_css[2] * k
    iw = side["png_size"][0]
    return (x0, y0, iw - x0, y1)


def plan_page(side: dict, kb: tuple, t0: float, t1: float, move: bool) -> dict:
    """Camera keys for one page shot. The page's anchor is the key's centre, so its position is where the key sits."""
    iw, ih = side["png_size"]
    s0 = (WIN[2] - WIN[0]) / iw
    q = ((kb[0] + kb[2]) / 2, (kb[1] + kb[3]) / 2)
    win_h = WIN[3] - WIN[1]
    cy = WIN_CY if ih * s0 <= win_h else WIN[1] + ih * s0 / 2           # whole, or top-aligned when taller
    pa = (W / 2 + s0 * (q[0] - iw / 2), cy + s0 * (q[1] - ih / 2))
    if not move:                                  # context: whole, slow push about the key
        return {"q": q, "segs": [("lin", t0, t1, pa, s0, pa, s0 * 1.04)], "ring_from": t0 + 0.35, "kb": kb}
    s1 = min(s0 * 1.14, (WIN[2] - WIN[0] - 24) / (kb[2] - kb[0]))
    ky = min(max(WIN_CY, WIN[1] + (kb[3] - kb[1]) * s1 / 2 + 30), WIN[3] - (kb[3] - kb[1]) * s1 / 2 - 30)
    pb = (W / 2, ky)
    ta, tb = snap(t0 + 0.9), snap(t0 + 1.8)
    return {"q": q, "kb": kb, "ring_from": tb,
            "segs": [("lin", t0, ta, pa, s0, pa, s0 * 1.01), ("ease", ta, tb, pa, s0 * 1.01, pb, s1),
                     ("lin", tb, t1, pb, s1, pb, s1 * 1.03)]}


def ring_rect(plan: dict, t: float) -> tuple[float, float, float, float]:
    """The key's outline in frame px at time t (on the last, linear segment)."""
    kind, a, b, p0, s0, p1, s1 = plan["segs"][-1]
    u = (t - a) / (b - a)
    s = s0 + (s1 - s0) * u
    p = (p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u)
    kb = plan["kb"]
    w, h = (kb[2] - kb[0]) * s, (kb[3] - kb[1]) * s
    return (p[0] - w / 2, p[1] - h / 2, p[0] + w / 2, p[1] + h / 2)


# ============================================================================================ FilmCraft
def filmcraft_build(out: Path, a: dict) -> dict:
    fc = FilmCraft(log=out / "build_log.jsonl")
    run = fc.run
    try:
        end = a["total"]
        run("file.newSequence", name=a["slug"], width=W, height=H, fps=FPS, sampleRate=SR, video=6, audio=1)
        paths = [a["bg"], a["portrait"], a["proof_png"], a["context_png"], a["bands"], a["ramp"], a["hook_text"], a["end"],
                 a["pill"], a["mix"]] + [c["png"] for c in a["captions"]]
        ids = run("file.import", paths=[str(p) for p in paths])
        if ids["errors"]:
            raise RuntimeError(f"import: {ids['errors']}")
        bg, portrait, proof, context, bands, ramp, hook_text, endc, pill, mix = ids["items"][:10]
        cap_items = ids["items"][10:]
        eased: list[tuple[int, str, list[float]]] = []

        def place(item, track, a0, a1, still=True):
            kw = {"sourceIn": {"seconds": 1}} if still else {}
            return run("timeline.place", item=item, track=track, seconds=a0, duration={"seconds": a1 - a0}, insert=False,
                       **kw)["clips"][0]

        def setp(clip, param, val, at=None):
            if at is None:
                run("effects.setParam", clip=clip, effect="motion", param=param, value=val)
            else:
                run("effects.setParam", clip=clip, effect="motion", param=param, value=val, time=ft(at), keyframe=True)

        T = a["T"]
        place(bg, "V1", 0, end)
        # shot 1: the portrait, a slow push-in on the face; the ramp and the text over it
        c1 = place(portrait, "V2", T[0], T[1])
        setp(c1, "anchor", list(a["face_px"]))
        for at, s in ((T[0], a["p_scale"]), (T[1], a["p_scale"] * 1.10)):
            setp(c1, "position", [W / 2, a["face_y"]], at)
            setp(c1, "scale", s, at)
        place(ramp, "V3", T[0], T[1])
        ht = place(hook_text, "V4", T[0], T[1])
        setp(ht, "anchor", [W / 2, 1340])
        for at, s in ((T[0], 100.0), (T[1], 103.0)):
            setp(ht, "position", [W / 2, 1340], at)
            setp(ht, "scale", s, at)
        # shots 2-3: the real pages, the window bands over them, the outline on the key
        clips_page = []
        for item, plan in ((proof, a["plan_proof"]), (context, a["plan_context"])):
            for kind, s_a, s_b, p0, sc0, p1, sc1 in plan["segs"]:
                c = place(item, "V2", s_a, s_b)
                clips_page.append(c)
                setp(c, "anchor", list(plan["q"]))
                setp(c, "position", list(p0), s_a)
                setp(c, "scale", sc0 * 100, s_a)
                setp(c, "position", list(p1), s_b)
                setp(c, "scale", sc1 * 100, s_b)
                if kind == "ease":
                    eased.append((c, "position", [s_a, s_b]))
                    eased.append((c, "scale", [s_a, s_b]))
            r0 = snap(plan["ring_from"])
            r_end = plan["segs"][-1][2]
            g = ring_rect(plan, r0)
            cx, cy = (g[0] + g[2]) / 2, (g[1] + g[3]) / 2
            ring = run("graphics.newRectangle", position=[cx, cy], size=[g[2] - g[0], g[3] - g[1]], seconds=r_end - r0,
                       time=ft(r0), track=3)["clip"]
            run("graphics.set", clip=ring, layer=0, props={"fill": False, "stroke": True, "stroke_color": CYAN,
                                                            "stroke_width": 7, "corner_radius": 14, "shadow": True,
                                                            "shadow_color": CYAN, "shadow_blur": 28, "shadow_distance": 0,
                                                            "shadow_opacity": 85})
            setp(ring, "anchor", [cx, cy])
            g_end = ring_rect(plan, r_end)
            pop = snap(r0 + 0.2)
            g_pop = ring_rect(plan, pop)
            for at, gg, k in ((r0, g, 1.18), (pop, g_pop, 1.0), (r_end, g_end, 1.0)):
                setp(ring, "position", [(gg[0] + gg[2]) / 2, (gg[1] + gg[3]) / 2], at)
                setp(ring, "scale", k * (gg[2] - gg[0]) / (g[2] - g[0]) * 100, at)
        place(bands, "V3", T[1], T[3])
        # shot 4: the end card pops in
        ec = place(endc, "V2", T[3], end)
        setp(ec, "anchor", [W / 2, H / 2])
        setp(ec, "position", [W / 2, H / 2])
        for at, s in ((T[3], 86.0), (snap(T[3] + 0.25), 100.0), (end, 103.0)):
            setp(ec, "scale", s, at)
        eased.append((ec, "scale", [T[3], snap(T[3] + 0.25)]))
        # the brand pill: frame 0 to the last frame, top track
        pc = place(pill, "V6", 0, end)
        setp(pc, "position", [PILL_XY[0] + a["pill_size"][0] / 2, PILL_XY[1] + a["pill_size"][1] / 2])
        # a whip into the proof
        run("sequence.applyVideoTransition", clip=c1, effect="whip", frames=6, edge="out", align="center",
            params={"direction": "From East"})
        run("timeline.place", item=mix, track="A1", seconds=0, insert=False)
        for item, c in zip(cap_items, a["captions"]):  # captions: PIL lines on V5, a short pop on each
            cc = place(item, "V5", c["start"], c["end"])
            setp(cc, "anchor", [W / 2, 75])
            setp(cc, "position", [W / 2, CAPTION_CY])
            for at, s in ((c["start"], 88.0), (min(c["end"], snap(c["start"] + 0.12)), 100.0)):
                setp(cc, "scale", s, at)
        clips = {it["clip"]: it for tr in run("sequence.inspect")["video"] for it in tr["items"]}
        for clip, param, secs in eased:
            it = clips[clip]
            for i, sec in enumerate(secs):
                run("effects.setInterpolation", clip=clip, effect="motion", param=param,
                    mediaTime=it["sourceIn"] + ft(sec) - it["start"], interpolation="easeOut" if i == 0 else "easeIn")
        run("file.saveAs", path=str(out / "project.fcproj"))
        t1 = time.time()
        res = run("file.exportMedia", path=str(out / "short.mp4"), format="h264", range="entire", loudnessLufs=-14,
                  burnCaptions=False, crf=18, bitrateMode="crf", h264Profile="high", wait=True)
        return {"export_s": round(time.time() - t1, 2), "result": res}
    finally:
        fc.close()


# ============================================================================================ QA
def probe(mp4: Path, ffprobe: str) -> dict:
    r = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(mp4)],
                       capture_output=True, text=True)
    return json.loads(r.stdout)


def grab(mp4: Path, t: float, png: Path, ffmpeg: str) -> Image.Image:
    subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1", str(png)], check=True)
    return Image.open(png).convert("RGB")


def qa(out: Path, a: dict, ffmpeg: str, ffprobe: str) -> dict:
    mp4 = out / "short.mp4"
    g: dict = {}
    pr = probe(mp4, ffprobe)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    au = [s for s in pr["streams"] if s["codec_type"] == "audio"]
    dur = float(pr["format"]["duration"])
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    g["format"] = {"pass": v["width"] == W and v["height"] == H and abs(num / den - FPS) < 0.01 and v["codec_name"] == "h264"
                   and bool(au) and au[0]["codec_name"] == "aac",
                   "video": f"{v['codec_name']} {v['width']}x{v['height']} {num}/{den}", "audio": au[0]["codec_name"] if au else None}
    g["duration"] = {"pass": DURATION[0] <= dur <= DURATION[1] + 0.05, "seconds": round(dur, 3)}
    meas = CR.loudnorm_measure(mp4, ffmpeg)
    g["loudness"] = {"pass": LUFS[0] <= meas["I"] <= LUFS[1] and meas["TP"] <= -1.0, **meas}
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    times = [float(x) for x in range(int(dur) + 1) if x < dur - 0.05] + [max(0.0, dur - 1.5 / FPS)]
    shots = [grab(mp4, tt, frames / f"t{tt:06.2f}.png", ffmpeg) for tt in times]
    shots[0].save(out / "frame0.png")
    pill = np.asarray(a["pill_img"]).astype(np.float64)
    m = pill[:, :, 3] >= 250
    px, py = PILL_XY
    diffs = []
    for im in shots:
        reg = np.asarray(im).astype(np.float64)[py:py + pill.shape[0], px:px + pill.shape[1], :3]
        diffs.append(float(np.abs(reg - pill[:, :, :3])[m].mean()))
    g["brand_pill"] = {"pass": max(diffs) <= 24, "max_mean_diff": round(max(diffs), 2), "frames_N": len(diffs)}
    first_brand = a["brand_said"]
    g["brand_spoken"] = {"pass": first_brand[0] <= 4.0 and first_brand[1] >= dur - 4.0,
                         "first_s": round(first_brand[0], 2), "last_s": round(first_brand[1], 2)}
    g["text"] = {"pass": not a["text_problems"], "problems": a["text_problems"]}
    g["outline_in_window"] = {"pass": a["rings_inside"], "rings": a["rings"],
                              "note": "outline inside the window (x 20-1060, y 342-1440); caption band y 1446-1554"}
    # one frame per second, tiled with PIL (the PATH ffmpeg has no tile filter)
    tw, th = 216, 384
    cols = min(len(shots), 11)
    rows = math.ceil(len(shots) / cols)
    sheet = Image.new("RGB", (cols * tw, rows * (th + 26)), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    for i, (tt, im) in enumerate(zip(times, shots)):
        x, y = (i % cols) * tw, (i // cols) * (th + 26)
        sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y + 26))
        d.text((x + 6, y + 4), f"{tt:.1f}s", fill=(255, 255, 255), font=CRD.font("bold", 18))
    sheet.save(out / "sheet.png")
    g["pass"] = all(x["pass"] for x in g.values() if isinstance(x, dict))
    return g


# ============================================================================================ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("story", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--capture", action="store_true", help="capture the live pages now (else: reuse today's captures)")
    ap.add_argument("--out", help="default <media>/.ops/yt-shorts/<story>")
    ap.add_argument("--speed", type=float, default=SPEED)
    a = ap.parse_args(argv)
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))["stories"]
    if a.list or not a.story:
        for k, v in reg.items():
            print(f"{k:22s} {v['member']} · {v['ticker']} {v['side']}")
        return 0
    if a.story not in reg:
        print(f"unknown story {a.story!r}", file=sys.stderr)
        return 2
    st = reg[a.story]
    out = Path(a.out) if a.out else OPS / "yt-shorts" / a.story
    screens = out / "screens"
    screens.mkdir(parents=True, exist_ok=True)
    ffmpeg, ffprobe = CRD.tool("ffmpeg"), CRD.tool("ffprobe")
    t_start = time.time()
    try:
        if a.capture:
            for name, spec in st["captures"].items():
                print(f"capture {name}: {spec['url']}", flush=True)
                run_capture(name, spec, screens)
        caps = {name: load_capture(name, screens) for name in st["captures"]}
        for name in ("proof", "context"):
            side = caps[name]
            if side.get("kind") != "strip" or side["png_size"][0] != 390 * side["dpr"]:
                raise InputError(f"{name} is not a strip of the page at phone width")
            if PARTY_RX.search(side["inside_text"]):
                raise InputError(f"{name} shows a party label: pick another strip")
            if CRD.PROVIDER_RX.search(side["inside_text"]):
                raise InputError(f"{name} shows a provider name")
            if not side.get("images") is None and not all(i["ok"] for i in side["images"]):
                raise InputError(f"{name}: an image on the strip did not load")
        slots = read_slots(st, caps)
        used: set = set()
        hook_name = render(st["hook"]["name"], slots, "show", used)
        hook_fact = render(st["hook"]["fact"], slots, "show", used)
        if len(hook_fact.split()) > 9:
            raise InputError(f"the hook fact has {len(hook_fact.split())} words (max 9): {hook_fact!r}")
        lines_say = [say_text(render(st["hook"]["say"], slots, "say", used))]
        chunk_sets = []
        for key in ("proof_lines", "context_lines"):
            show = [render(c, slots, "show", used) for c in st[key]]
            say = [say_text(render(c, slots, "say", used)) for c in st[key]]
            chunk_sets.append((show, say))
            lines_say.append(" ".join(say))
        end_say = "See every trade, free. Search RapidTradeView."
        lines_say.append(say_text(end_say))
        yt_title = render(st["youtube"]["title"], slots, "show")
        yt_desc = render(st["youtube"]["description"], slots, "show")
        if len(yt_title) >= 70:
            raise InputError(f"the YouTube title is {len(yt_title)} characters (under 70): {yt_title!r}")
        shown_texts = [hook_name, hook_fact, end_say, yt_title, yt_desc] + [x for s, _ in chunk_sets for x in s]
        problems = text_problems(shown_texts + lines_say)
        if problems:
            raise InputError("; ".join(problems))
        # the portrait: a US government work (public domain), its source next to the file
        pj, pp = out / "portrait.jpg", out / "portrait_source.json"
        if not pj.is_file() or json.loads(pp.read_text(encoding="utf-8")).get("url") != st["portrait"]:
            req = urllib.request.Request(st["portrait"], headers={"User-Agent": "rtv-media-tools"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            pj.write_bytes(data)
            pp.write_text(json.dumps({"url": st["portrait"], "bioguide": st["bioguide"], "member": st["member"],
                                      "sha256": hashlib.sha256(data).hexdigest(),
                                      "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                      "license": "Official portrait of a member of the US Congress: a work of the US "
                                                 "government, public domain (unitedstates/images, from the GPO Member "
                                                 "Guide)."}, indent=1), encoding="utf-8")
        por = Image.open(pj).convert("RGB")
        por_png = out / "assets" / "portrait.png"
        por_png.parent.mkdir(exist_ok=True)
        por.save(por_png)
    except InputError as e:
        print(f"make_member_story: {e}", file=sys.stderr)
        return 2

    # ---- voice: four lines; chunk timings for the captions
    vo = tts(lines_say, out / "tts", a.speed)
    proof_t = chunk_times(chunk_sets[0][1], vo[1]["words"])
    ctx_t = chunk_times(chunk_sets[1][1], vo[2]["words"])
    lead = [0.05, 0.25, 0.2, 0.2]
    durs = [lead[0] + vo[0]["dur"] + 0.25, max(3.4, lead[1] + vo[1]["dur"] + 0.35), max(2.6, lead[2] + vo[2]["dur"] + 0.4),
            max(3.0, lead[3] + vo[3]["dur"] + 0.45)]
    T = [0.0]
    for d_ in durs:
        T.append(snap(T[-1] + d_))
    total = T[-1]
    print("shots", T, "total", total, flush=True)
    if not DURATION[0] <= total <= DURATION[1]:
        print(f"make_member_story: the video would run {total:.2f} s (15-20): shorten a line or change --speed",
              file=sys.stderr)
        return 2
    starts = [T[i] + lead[i] for i in range(4)]
    captions = []
    for (show, _), tms, i in ((chunk_sets[0], proof_t, 1), (chunk_sets[1], ctx_t, 2)):
        for j, (txt, (c0, c1)) in enumerate(zip(show, tms)):
            s0 = snap(starts[i] + c0)
            e0 = snap(starts[i] + tms[j + 1][0]) if j + 1 < len(tms) else min(snap(starts[i] + c1 + 0.35), T[i + 1])
            captions.append({"text": txt, "start": s0, "end": max(e0, s0 + 2 / FPS)})
    for i in range(1, len(captions)):
        captions[i - 1]["end"] = min(captions[i - 1]["end"], captions[i]["start"])
    for k, c in enumerate(captions):
        c["png"] = out / "assets" / f"cap{k}.png"
        c["png"].parent.mkdir(exist_ok=True)
        caption_png(c["text"]).save(c["png"])
    brand_words = [starts[i] + w["start"] for i in range(4) for w in vo[i]["words"] if w["word"].startswith("Rapid")]
    # ---- pictures
    assets = out / "assets"
    bg = bg_image()
    bg.save(assets / "bg.png")
    bands_overlay(bg).save(assets / "bands.png")
    ramp, hook_text = hook_overlays(hook_name, hook_fact, bg)
    ramp.save(assets / "ramp.png")
    hook_text.save(assets / "hook_text.png")
    end_card().save(assets / "end.png")
    pill = CRD.pill(CRD.BRAND, 40, 26, 16)
    pill.save(assets / "pill.png")
    kb_p = key_box(caps["proof"], st["captures"]["proof"]["key_pad"])
    kb_c = key_box(caps["context"], st["captures"]["context"]["key_pad"])
    plan_p = plan_page(caps["proof"], kb_p, T[1], T[2], move=True)
    plan_c = plan_page(caps["context"], kb_c, T[2], T[3], move=False)
    rings = [[round(v) for v in ring_rect(plan, tt)] for plan in (plan_p, plan_c)
             for tt in (plan["ring_from"], plan["segs"][-1][2])]
    rings_inside = all(WIN[1] <= r[1] and r[3] <= WIN[3] and WIN[0] <= r[0] and r[2] <= WIN[2]
                       for plan in (plan_p, plan_c) for r in (ring_rect(plan, plan["ring_from"]),
                                                             ring_rect(plan, plan["segs"][-1][2])))
    fx, fy = st["face"]
    p_scale = max(W / por.size[0], 1320 / por.size[1]) * 100
    face_px = (fx * por.size[0], fy * por.size[1])
    mix = build_mix([(starts[i], vo[i]["audio"]) for i in range(4)], [T[1], T[2], T[3]], T[3], total, out, ffmpeg)
    build = filmcraft_build(out, {
        "slug": a.story, "total": total, "T": T, "bg": assets / "bg.png", "portrait": por_png,
        "proof_png": caps["proof"]["_png"], "context_png": caps["context"]["_png"], "bands": assets / "bands.png",
        "ramp": assets / "ramp.png", "hook_text": assets / "hook_text.png", "end": assets / "end.png",
        "pill": assets / "pill.png", "mix": mix, "face_px": face_px, "face_y": face_px[1] * p_scale / 100, "p_scale": p_scale,
        "plan_proof": plan_p, "plan_context": plan_c, "captions": captions, "pill_size": pill.size})
    # ---- proof, script, description
    facts = []
    for k in sorted(used):
        sl = slots[k]
        if sl.proof:
            facts.append({"slot": k, "kind": sl.kind, "shown": sl.show, "spoken": sl.say, **sl.proof})
    (out / "proof.json").write_text(json.dumps({
        "story": a.story, "made_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "member": st["member"], "ticker": st["ticker"], "portrait": json.loads((out / "portrait_source.json").read_text(encoding="utf-8")),
        "hook_text": {"name": hook_name, "fact": hook_fact}, "facts": facts,
        "captions": [{k: (str(v) if isinstance(v, Path) else v) for k, v in c.items()} for c in captions]}, indent=1, ensure_ascii=False), encoding="utf-8")
    script = "\n".join(f"[{starts[i]:5.2f}s] {lines_say[i]}" for i in range(4))
    (out / "voice_script.txt").write_text(script + "\n", encoding="utf-8")
    (out / "youtube.json").write_text(json.dumps({"title": yt_title, "description": yt_desc}, indent=1, ensure_ascii=False),
                                      encoding="utf-8")
    g = qa(out, {"pill_img": pill, "brand_said": (min(brand_words), max(brand_words)), "text_problems": problems,
                 "rings_inside": rings_inside, "rings": rings}, ffmpeg, ffprobe)
    g["build"] = build
    g["elapsed_s"] = round(time.time() - t_start, 1)
    (out / "qa.json").write_text(json.dumps(g, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in g.items() if k != "build"}, indent=1))
    return 0 if g["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
