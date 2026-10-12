"""Card Reel (Growth 2026-10-12): a second Instagram Reel a day made from ONE facts.json item's share card.

    card_reel.py prepare --date D --facts FILE --work DIR [--repo DIR] [--now ISO] [--no-push] [--gv DIR] [--python EXE]
    card_reel.py live    --date D --facts FILE --work DIR [--repo DIR] [--timeout S]

Called by daily_common.ps1 Publish-Facts on every facts build (the morning pass, the 30-minute intraday refresh, the picks pass and
the weekend pass), on the day's facts file BEFORE it is compared and published. Nothing here ever changes the run's exit code.

prepare
  - one card Reel per date at most (state: <work>/card-reel.json). Once it is live on Pages, every later facts build of the day gets
    {"url": <Pages URL>, "kind": "reel", "alt": <the item's facts_text>} appended to that item's media (when the item is still in it).
  - when it renders: weekdays from 10:00 ET (America/New_York; the first facts build at or after it: the 10:00 intraday refresh), so
    the morning's 06:45-08:30 ET reporters are in the earnings_result list; weekends on the weekend pass (any time).
  - which item: the first available of earnings_result (largest market cap, from /snapshot), congress_trade, form4_buy (both:
    buys before sales, then the largest amount at the top of its range, then the freshest filing), chart_pattern (freshest scan);
    then the facts order. An item qualifies when it has facts_text and its media[0] is our
    page's Open Graph card (https://www.rapidtradeview.trade/.../opengraph-image).
  - the chosen item is fixed for the day: a failed download, card check, render or QA logs its reason in the state and the item stays
    without a reel; the same item is tried once more on the next build (MAX_ATTEMPTS), never another one (No Fallbacks).
  - the card: media[0].url downloaded with the access header (qa_header), a 1200 x 630 PNG that is not the site's generic card.
  - the render: growth-video scripts/v6cat/card_reel.py (caption = facts_text, push-in, VSCO bed, end card; exit 0 only when its QA
    passes) -> staged as v/<date>/cards/<item_id>/reel_9x16.mp4 + music.json (provenance, file hash, the samples used) in the repo.
  exit 0: nothing to push (attached, skipped or failed: the log says which); 10: files staged, listed one per line in
  <work>/card-reel-files.txt: commit + push them, then run `live`. --no-push (a dry run): the staged reel is attached at once
  (Pages does not serve it) and the exit is 0.
live
  waits until Pages serves the staged MP4 (200 video/mp4, the local size), marks it live and attaches it to --facts; exit 1 when it
  is not served within --timeout (the next facts build checks again).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402
import qa_header as qa  # noqa: E402
import select_stories as ss  # noqa: E402

GV = Path("D:/rtvw/growth-video")
PYTHON = "C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe"
ORDER = ("earnings_result", "congress_trade", "form4_buy", "chart_pattern")
WEEKDAY_FROM_ET = (10, 0)
MAX_ATTEMPTS = 2
RENDER_TIMEOUT_S = 1200
CARD_SIZE = (1200, 630)
OG_CARD = re.compile(r"^https://www\.rapidtradeview\.trade/[A-Za-z0-9._~/%-]*opengraph-image$")
GENERIC_CARD = f"{ss.SITE}/opengraph-image"
UA = "RapidTradeView card reel (contact@rapidtradeview.trade)"
STATE = "card-reel.json"
FILES = "card-reel-files.txt"
EXIT_STAGED = 10


def now_utc(raw: str | None) -> dt.datetime:
    if not raw:
        return dt.datetime.now(dt.timezone.utc)
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw.strip()).replace("Z", "+00:00")    # PowerShell's 'o' has 7 fraction digits
    t = dt.datetime.fromisoformat(raw)
    return (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)


def due(now: dt.datetime) -> str | None:
    """None when a card Reel may render now, else why not."""
    et = now.astimezone(ss.NY)
    if et.weekday() >= 5:
        return None
    if (et.hour, et.minute) >= WEEKDAY_FROM_ET:
        return None
    return f"weekday before {WEEKDAY_FROM_ET[0]:02d}:{WEEKDAY_FROM_ET[1]:02d} ET ({et:%a %H:%M} ET): the morning's reports may still come"


def eligible(item: dict) -> bool:
    media = item.get("media") or []
    first = media[0] if media and isinstance(media[0], dict) else {}
    return (item.get("type") in ORDER and isinstance(item.get("item_id"), str) and isinstance(item.get("facts_text"), str)
            and bool(item["facts_text"].strip()) and first.get("kind") == "image" and bool(OG_CARD.match(str(first.get("url") or ""))))


def choose(items: list[dict], caps: dict[str, float | None]) -> tuple[dict | None, str]:
    """The day's card item: the first type of ORDER with an eligible item; within it
      earnings_result               the largest market cap (an unknown cap ranks last),
      congress_trade / form4_buy    buys before sales, then the largest amount (amount_upper), then the freshest filing,
      chart_pattern                 the freshest scan;
    then the facts order. Returns (item, why)."""
    for kind in ORDER:
        cands = [(n, i) for n, i in enumerate(items) if i.get("type") == kind and eligible(i)]
        if not cands:
            continue
        if kind == "earnings_result":
            rank, why = (lambda c: (caps.get(c[1].get("ticker")) or -1.0, -c[0])), "largest market cap"
        elif kind == "chart_pattern":
            rank, why = (lambda c: (str(c[1].get("scan_date") or ""), -c[0])), "freshest scan"
        else:
            rank, why = (lambda c: (c[1].get("side") == "buy", amount_upper(c[1]), str(c[1].get("filed") or ""), -c[0])),                 "buys first, largest amount, freshest filing"
        best = max(cands, key=rank)[1]
        return best, f"{kind}: {why} of {len(cands)}"
    return None, "no earnings_result, congress_trade, form4_buy or chart_pattern item with a facts_text and an Open Graph card"


MONEY = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([KMB])?", re.IGNORECASE)
SCALE = {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9}


def amount_upper(item: dict) -> float:
    """The item's amount in USD at the top of its range: per disclosed row ("; "-separated) the largest $ figure (a range's upper
    bound, "$1,001-$15,000" -> 15,000; a Form 4 total "$2.42M" -> 2,420,000), summed over the rows. Congress items use
    amount_exact_text (whole dollars), else amount_text. Nothing readable -> 0 (ranks last)."""
    text = item.get("amount_exact_text") or item.get("amount_text") or ""
    total = 0.0
    for row in str(text).split(";"):
        vals = [float(m.group(1).replace(",", "")) * SCALE[(m.group(2) or "").upper()] for m in MONEY.finditer(row)]
        total += max(vals, default=0.0)
    return total


def market_caps(items: list[dict]) -> dict[str, float | None]:
    tickers = sorted({i["ticker"] for i in items if i.get("type") == "earnings_result" and eligible(i) and i.get("ticker")})
    if not tickers:
        return {}
    api = ss.Api()
    return {t: ss.company_info(api, t)[1] for t in tickers}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_state(work: Path, state: dict) -> None:
    mf.write_json(work / STATE, state)


def read_state(work: Path, date: str) -> dict:
    p = work / STATE
    if p.is_file():
        s = load(p)
        if s.get("date") == date:
            return s
    return {"schema": "rtv-card-reel-state/1", "date": date, "status": "new", "attempts": 0, "log": []}


def note(state: dict, msg: str, now: dt.datetime) -> None:
    state.setdefault("log", []).append(f"{now:%Y-%m-%dT%H:%M:%SZ} {msg}")
    print(f"card reel: {msg}", flush=True)


def reel_url(date: str, item_id: str) -> str:
    return f"{mf.PAGES_BASE}/v/{date}/cards/{item_id}/reel_9x16.mp4"


def attach(facts_file: Path, state: dict) -> str:
    """Append the reel to its item's media in the facts file (once). Returns what happened."""
    facts = load(facts_file)
    item = next((i for i in facts.get("items") or [] if i.get("item_id") == state["item_id"]), None)
    if item is None:
        return f"{state['item_id']} is not in this facts build: the reel is not attached"
    media = item.setdefault("media", [])
    if any(isinstance(m, dict) and m.get("url") == state["url"] for m in media):
        return f"already attached to {state['item_id']}"
    media.append({"url": state["url"], "kind": "reel", "alt": state["alt"]})
    mf.write_json(facts_file, facts)
    return f"attached {state['url']} to {state['item_id']}"


def fetch(url: str, timeout: float = 60.0) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/png,image/*"})
    with qa.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type") or ""


def card_problem(data: bytes, ctype: str, generic: bytes | None) -> str | None:
    """Why these bytes are not a usable share card (None = usable)."""
    from io import BytesIO
    from PIL import Image
    if not ctype.lower().startswith("image/png"):
        return f"the card answered {ctype or 'no content type'}, not image/png"
    try:
        with Image.open(BytesIO(data)) as im:
            size, fmt = im.size, im.format
            px = im.convert("RGB").tobytes()
    except Exception as e:  # noqa: BLE001 - any decode error means no card
        return f"the card does not decode ({type(e).__name__})"
    if fmt != "PNG" or size != CARD_SIZE:
        return f"the card is {fmt} {size[0]}x{size[1]}, not a {CARD_SIZE[0]}x{CARD_SIZE[1]} PNG"
    if generic is not None:
        try:
            with Image.open(BytesIO(generic)) as g:
                same = g.size == size and g.convert("RGB").tobytes() == px
        except Exception:  # noqa: BLE001
            same = data == generic
        if same or data == generic:
            return "the card is the site's generic card (the page has no card of its own yet)"
    return None


def failed_gates(reel_dir: Path) -> str:
    try:
        rep = load(reel_dir / "reel-qa.json")
        bad = [k for k, v in (rep.get("summary") or {}).items() if not v]
        return f"QA failed: {', '.join(bad)}" if bad else "QA did not pass"
    except (OSError, ValueError):
        return "no reel-qa.json (the render stopped before its QA)"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(state: dict, item: dict, rules: dict, a: argparse.Namespace, now: dt.datetime) -> bool:
    """Download + check the card, render + QA the reel, stage it in the repo. True when staged."""
    iid = item["item_id"]
    wdir = Path(a.work) / "card-reel" / iid
    if wdir.exists():
        shutil.rmtree(wdir)
    wdir.mkdir(parents=True)
    url = item["media"][0]["url"]
    try:
        data, ctype = fetch(url)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        note(state, f"FAILED {iid}: the card did not download ({getattr(e, 'code', type(e).__name__)})", now)
        return False
    try:
        generic, _ = fetch(GENERIC_CARD)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        note(state, f"FAILED {iid}: the site's generic card did not download for the comparison ({getattr(e, 'code', type(e).__name__)})", now)
        return False
    why = card_problem(data, ctype, generic)
    if why:
        note(state, f"FAILED {iid}: {why}", now)
        return False
    card = wdir / "card.png"
    card.write_bytes(data)
    banned = [w for w in [*(rules.get("banned_words") or []), *(item.get("banned_words") or [])] if isinstance(w, str) and w]
    mf.write_json(wdir / "item.json", {"item": item, "banned_words": banned})
    out = wdir / "reel"
    cmd = [a.python, str(Path(a.gv) / "scripts" / "v6cat" / "card_reel.py"), "--item", str(wdir / "item.json"), "--card", str(card),
           "--out", str(out)]
    print("card reel: > " + " ".join(cmd), flush=True)
    try:
        r = subprocess.run(cmd, cwd=a.gv, timeout=RENDER_TIMEOUT_S)
        code = r.returncode
    except subprocess.TimeoutExpired:
        code = "timeout"
    if code != 0:
        note(state, f"FAILED {iid}: card_reel.py exit {code}: {failed_gates(out)}", now)
        return False
    try:
        reel, rep = load(out / "reel.json"), load(out / "reel-qa.json")
    except (OSError, ValueError) as e:
        note(state, f"FAILED {iid}: no reel.json / reel-qa.json ({type(e).__name__})", now)
        return False
    mp4 = out / "reel_9x16.mp4"
    if not (reel.get("qa_pass") is True and rep.get("pass") is True and reel.get("item_id") == iid and mp4.is_file()
            and reel.get("files", {}).get("reel_9x16.mp4") == sha256(mp4) and reel.get("card", {}).get("sha256") == sha256(card)
            and isinstance(reel.get("music"), dict)):
        note(state, f"FAILED {iid}: the reel's record does not match its files or its QA", now)
        return False
    rel = f"v/{a.date}/cards/{iid}"
    dest = Path(a.repo) / rel
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mp4, dest / "reel_9x16.mp4")
    record = {"music": reel["music"], "files": {"reel_9x16.mp4": sha256(dest / "reel_9x16.mp4")}, "item_id": iid,
              "card": {"url": url, "sha256": reel["card"]["sha256"]}, "seconds": reel.get("seconds")}
    if (out / "vsco-instruments.json").is_file():
        record["samples_used"] = load(out / "vsco-instruments.json")
    mf.write_json(dest / "music.json", record)
    state.update(status="staged", url=reel_url(a.date, iid), alt=" ".join(item["facts_text"].split()),
                 files=[f"{rel}/reel_9x16.mp4", f"{rel}/music.json"], bytes=(dest / "reel_9x16.mp4").stat().st_size,
                 reel_dir=str(out), qa_pass=True)
    note(state, f"staged {rel}/reel_9x16.mp4 ({state['bytes']} bytes, QA passed)", now)
    return True


def cmd_prepare(a: argparse.Namespace) -> int:
    now = now_utc(a.now)
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    (work / FILES).unlink(missing_ok=True)
    state = read_state(work, a.date)
    facts_file = Path(a.facts)
    facts = load(facts_file)
    items = [i for i in facts.get("items") or [] if isinstance(i, dict)]
    st = state.get("status")
    if st == "live" or (st == "staged" and a.no_push):
        print(f"card reel: {attach(facts_file, state)}" + (" (-NoPush: not on Pages)" if st == "staged" else ""))
        return 0
    if st == "staged":
        missing = [f for f in state.get("files") or [] if not (Path(a.repo) / f).is_file()]
        if missing:
            note(state, f"FAILED {state.get('item_id')}: staged files are gone ({', '.join(missing)})", now)
            state["status"] = "failed"
            save_state(work, state)
            return 0
        (work / FILES).write_text("\n".join(state["files"]) + "\n", encoding="utf-8")
        print(f"card reel: {state['item_id']} is staged, not yet served by Pages: push + check again")
        return EXIT_STAGED
    if state.get("attempts", 0) >= MAX_ATTEMPTS:
        print(f"card reel: none today: {state.get('item_id')} failed {state['attempts']} times (last: {(state.get('log') or ['?'])[-1]})")
        return 0
    why = due(now)
    if why:
        print(f"card reel: not yet: {why}")
        return 0
    if state.get("item_id"):
        item = next((i for i in items if i.get("item_id") == state["item_id"]), None)
        if item is None:
            note(state, f"FAILED {state['item_id']}: the chosen item left the facts; no other item is used today", now)
            state["attempts"] = MAX_ATTEMPTS
            save_state(work, state)
            return 0
    else:
        item, why = choose(items, market_caps(items))
        if item is None:
            print(f"card reel: none now: {why}")
            return 0
        state.update(item_id=item["item_id"], type=item["type"], ticker=item.get("ticker"), chosen_at=f"{now:%Y-%m-%dT%H:%M:%SZ}", chosen_why=why)
        note(state, f"chose {item['item_id']} ({why})", now)
    state["attempts"] = state.get("attempts", 0) + 1
    state["status"] = "rendering"
    save_state(work, state)
    if not render(state, item, facts.get("rules") or {}, a, now):
        state["status"] = "failed"
        save_state(work, state)
        return 0
    save_state(work, state)
    if a.no_push:
        print(f"card reel: {attach(facts_file, state)} (-NoPush: not on Pages)")
        return 0
    (work / FILES).write_text("\n".join(state["files"]) + "\n", encoding="utf-8")
    return EXIT_STAGED


def cmd_live(a: argparse.Namespace) -> int:
    now = now_utc(None)
    work = Path(a.work)
    state = read_state(work, a.date)
    if state.get("status") != "staged":
        print(f"card reel: nothing staged (status {state.get('status')})")
        return 1
    local = Path(a.repo) / state["files"][0]
    deadline = time.monotonic() + a.timeout
    while True:
        errors = mf.check_media_urls({state["url"]: local})
        if not errors:
            break
        if time.monotonic() > deadline:
            print(f"card reel: not served within {a.timeout} s: {errors[0]}")
            return 1
        time.sleep(15)
    state["status"] = "live"
    note(state, f"live on Pages: {state['url']}", now)
    save_state(work, state)
    print(f"card reel: {attach(Path(a.facts), state)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "live"):
        p = sub.add_parser(name)
        p.add_argument("--date", required=True)
        p.add_argument("--facts", required=True)
        p.add_argument("--work", required=True)
        p.add_argument("--repo", default=str(mf.REPO))
    sub.choices["prepare"].add_argument("--now", help="the clock (ISO; run_daily.ps1 -Now for a dry run)")
    sub.choices["prepare"].add_argument("--no-push", action="store_true")
    sub.choices["prepare"].add_argument("--gv", default=str(GV), help="the growth-video tree")
    sub.choices["prepare"].add_argument("--python", default=PYTHON)
    sub.choices["live"].add_argument("--timeout", type=int, default=600)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
        ap.error("--date must be YYYY-MM-DD")
    return cmd_prepare(a) if a.cmd == "prepare" else cmd_live(a)


if __name__ == "__main__":
    sys.exit(main())
