"""Card Reel (Growth 2026-10-12; two a day since 2026-11-08): Instagram Reels made from facts.json items' share cards, at most
REELS_PER_DAY (2) a date, each from ONE item.

    card_reel.py prepare --date D --facts FILE --work DIR [--repo DIR] [--now ISO] [--no-push] [--gv DIR] [--python EXE]
    card_reel.py live    --date D --facts FILE --work DIR [--repo DIR] [--timeout S]

Called by daily_common.ps1 Publish-Facts on every facts build (the morning pass, the 30-minute intraday refresh, the picks pass and
the weekend pass), on the day's facts file BEFORE it is compared and published. Nothing here ever changes the run's exit code.

prepare
  - up to two card Reels per date, one per slot (state: <work>/card-reel.json, schema rtv-card-reel-state/2: {"date", "reels":
    [slot 1, slot 2]}; a one-reel rtv-card-reel-state/1 file of the date is read as slot 1). Once a slot's reel is live on Pages,
    every later facts build of the day gets {"url": <Pages URL>, "kind": "reel", "alt": <the item's facts_text>} appended to that
    item's media (when the item is still in it).
  - when it renders: weekdays from 10:00 ET (America/New_York; the first facts build at or after it: the 10:00 intraday refresh), so
    the morning's 06:45-08:30 ET reporters are in the earnings_result list; weekends on the weekend pass (any time).
  - which item: the first available of earnings_result (largest market cap, from /snapshot), congress_trade, form4_buy (both:
    buys before sales, then the largest amount at the top of its range, then the freshest filing), chart_pattern (freshest scan);
    then the facts order. Slot 1 takes the first item by that order; slot 2 the next one by the same order: never slot 1's
    item, and an item of another ticker when one qualifies (else the same ticker's next item). Both are chosen on the first build
    that is due (slot 2 on a later build when no second item qualifies yet). An item qualifies when it has facts_text and its
    media[0] is our page's Open Graph card (https://www.rapidtradeview.trade/.../opengraph-image), and (G-N1 holdout, until
    2026-11-21) carries no /earnings/reports/ URL anywhere: an earnings_result's card is its ticker page's
    (/dashboard/<T>/opengraph-image).
  - each slot's chosen item is fixed for the day: a failed download, card check, render or QA logs its reason in the slot and the
    item stays without a reel; the same item is tried once more on the next build (MAX_ATTEMPTS per slot), never another one (No
    Fallbacks). A failed slot 1 is not replaced (not by slot 2's item, not by a third one): that day has slot 2's reel only.
  - the card: media[0].url downloaded with the access header (qa_header), a 1200 x 630 PNG that is not the site's generic card.
  - the render: tools/gv/scripts/v6cat/card_reel.py in this repo, run with python -I (--gv overrides the tree; rebuilt
    2026-11-08 after the old growth-video tree was deleted): 1 s hook, facts_text as kinetic type one word group per beat under
    the card as a context header, a 3 s end card, an original score from VSCO 2 CE (CC0) samples; exit 0 only when its QA
    passes) -> staged as v/<date>/cards/<item_id>/reel_9x16.mp4 + music.json (provenance, samples used, file hash) in the repo.
  exit 0: nothing to push (attached, skipped or failed: the log says which); 10: files staged (every staged slot's), listed one
  per line in <work>/card-reel-files.txt: commit + push them, then run `live`. --no-push (a dry run): a staged reel is attached at
  once (Pages does not serve it) and the exit is 0.
live
  waits until Pages serves every staged slot's MP4 (200 video/mp4, the local size), marks each live and attaches it to --facts as
  it is served; exit 1 when one is not served within --timeout (the next facts build checks again).
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

GV = Path(__file__).resolve().parent / "gv"    # the renderer tree (tools/gv/scripts/v6cat/card_reel.py)
PYTHON = "C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe"
ORDER = ("earnings_result", "congress_trade", "form4_buy", "chart_pattern")
WEEKDAY_FROM_ET = (10, 0)
MAX_ATTEMPTS = 2                                # per slot
REELS_PER_DAY = 2
RENDER_TIMEOUT_S = 1200
CARD_SIZE = (1200, 630)
OG_CARD = re.compile(r"^https://www\.rapidtradeview\.trade/[A-Za-z0-9._~/%-]*opengraph-image$")
GENERIC_CARD = f"{ss.SITE}/opengraph-image"
UA = "RapidTradeView card reel (contact@rapidtradeview.trade)"
STATE = "card-reel.json"
SCHEMA = "rtv-card-reel-state/2"
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


def report_leak(item: dict) -> bool:
    """G-N1 holdout (select_stories.G_N1_HOLDOUT_END): an item dated (item_id) before 2026-11-21 that carries a
    /earnings/reports/ URL anywhere never becomes a Reel. An item_id without a date counts as inside the holdout."""
    try:
        day = dt.date.fromisoformat(str(item.get("item_id") or "")[:10])
    except ValueError:
        day = ss.G_N1_HOLDOUT_END - dt.timedelta(days=1)
    return ss.g_n1_holdout(day) and ss.report_page_in(item)


def eligible(item: dict) -> bool:
    media = item.get("media") or []
    first = media[0] if media and isinstance(media[0], dict) else {}
    return (not report_leak(item) and item.get("type") in ORDER and isinstance(item.get("item_id"), str) and isinstance(item.get("facts_text"), str)
            and bool(item["facts_text"].strip()) and first.get("kind") == "image" and bool(OG_CARD.match(str(first.get("url") or ""))))


def choose(items: list[dict], caps: dict[str, float | None]) -> tuple[dict | None, str]:
    """Slot 1's card item: the first type of ORDER with an eligible item; within it
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


def choose_next(items: list[dict], caps: dict[str, float | None], taken: list[dict]) -> tuple[dict | None, str]:
    """A later slot's item by the same order (choose): never an earlier slot's item (taken: their states), and a ticker no earlier
    slot has when such an item qualifies, else the next item of a ticker already used. Returns (item, why)."""
    ids = {s.get("item_id") for s in taken}
    tickers = {s.get("ticker") for s in taken if s.get("ticker")}
    rest = [i for i in items if i.get("item_id") not in ids]
    other = [i for i in rest if not i.get("ticker") or i.get("ticker") not in tickers]
    item, why = choose(other, caps)
    if item is not None:
        return item, why + (f", another ticker than {', '.join(sorted(tickers))}" if tickers else "")
    item, why = choose(rest, caps)
    if item is not None:
        return item, why + f", no item of another ticker than {', '.join(sorted(tickers))} qualifies"
    return None, why + " besides the earlier slots' items"


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


def new_slot(n: int) -> dict:
    return {"slot": n, "status": "new", "attempts": 0, "log": []}


def read_state(work: Path, date: str) -> dict:
    """The date's state {"schema", "date", "reels": [one dict per chosen slot, in slot order]}. A one-reel file (schema /1: the
    slot's fields at the top level) of the date is read as slot 1; another date's file starts the day with no slot chosen."""
    p = work / STATE
    if p.is_file():
        s = load(p)
        if s.get("date") == date:
            if isinstance(s.get("reels"), list):
                return s
            old = {k: v for k, v in s.items() if k not in ("schema", "date")}
            return {"schema": SCHEMA, "date": date, "reels": [dict(new_slot(1), **old)] if old.get("item_id") else []}
    return {"schema": SCHEMA, "date": date, "reels": []}


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
    cmd = [a.python, "-I", str(Path(a.gv) / "scripts" / "v6cat" / "card_reel.py"), "--item", str(wdir / "item.json"),
           "--card", str(card), "--out", str(out)]
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


def staged_files(state: dict) -> list[str]:
    return [f for slot in state["reels"] if slot.get("status") == "staged" for f in slot.get("files") or []]


def prepare_slot(n: int, state: dict, items: list[dict], facts: dict, a: argparse.Namespace, now: dt.datetime) -> bool:
    """Slot n (1-based) on one facts build: attach its live reel, keep a staged one for the push, or choose / retry its item and
    render. True when the slot has staged files that need the push."""
    work, facts_file = Path(a.work), Path(a.facts)
    slots = state["reels"]
    slot = slots[n - 1] if len(slots) >= n else None
    tag = f"slot {n}"
    if slot is not None:
        st = slot.get("status")
        if st == "live" or (st == "staged" and a.no_push):
            print(f"card reel: {tag}: {attach(facts_file, slot)}" + (" (-NoPush: not on Pages)" if st == "staged" else ""))
            return False
        if st == "staged":
            missing = [f for f in slot.get("files") or [] if not (Path(a.repo) / f).is_file()]
            if missing:
                note(slot, f"FAILED {slot.get('item_id')}: staged files are gone ({', '.join(missing)})", now)
                slot["status"] = "failed"
                save_state(work, state)
                return False
            print(f"card reel: {tag}: {slot['item_id']} is staged, not yet served by Pages: push + check again")
            return True
        if slot.get("attempts", 0) >= MAX_ATTEMPTS:
            print(f"card reel: {tag}: none today: {slot.get('item_id')} failed {slot['attempts']} times "
                  f"(last: {(slot.get('log') or ['?'])[-1]})")
            return False
    why = due(now)
    if why:
        print(f"card reel: {tag}: not yet: {why}")
        return False
    if slot is not None:
        item = next((i for i in items if i.get("item_id") == slot["item_id"]), None)
        if item is None:
            note(slot, f"FAILED {slot['item_id']}: the chosen item left the facts; no other item is used for {tag} today", now)
            slot["attempts"] = MAX_ATTEMPTS
            save_state(work, state)
            return False
        if report_leak(item):
            note(slot, f"FAILED {slot['item_id']}: it carries a report page URL ({ss.G_N1_REASON}); no other item is used for "
                       f"{tag} today", now)
            slot["attempts"] = MAX_ATTEMPTS
            save_state(work, state)
            return False
    else:
        taken = slots[:n - 1]
        ids = {t.get("item_id") for t in taken}
        caps = market_caps([i for i in items if i.get("item_id") not in ids])
        item, why = choose_next(items, caps, taken) if taken else choose(items, caps)
        if item is None:
            print(f"card reel: {tag}: none now: {why}")
            return False
        slot = new_slot(n)
        slot.update(item_id=item["item_id"], type=item["type"], ticker=item.get("ticker"), chosen_at=f"{now:%Y-%m-%dT%H:%M:%SZ}",
                    chosen_why=why)
        slots.append(slot)
        note(slot, f"{tag}: chose {item['item_id']} ({why})", now)
    slot["attempts"] = slot.get("attempts", 0) + 1
    slot["status"] = "rendering"
    save_state(work, state)
    if not render(slot, item, facts.get("rules") or {}, a, now):
        slot["status"] = "failed"
        save_state(work, state)
        return False
    save_state(work, state)
    if a.no_push:
        print(f"card reel: {tag}: {attach(facts_file, slot)} (-NoPush: not on Pages)")
        return False
    return True


def cmd_prepare(a: argparse.Namespace) -> int:
    now = now_utc(a.now)
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    (work / FILES).unlink(missing_ok=True)
    state = read_state(work, a.date)
    facts = load(Path(a.facts))
    items = [i for i in facts.get("items") or [] if isinstance(i, dict)]
    push = False
    for n in range(1, REELS_PER_DAY + 1):
        if len(state["reels"]) < n - 1:
            break                                   # slot n is chosen after slot n-1 (its item and ticker are left out)
        push = prepare_slot(n, state, items, facts, a, now) or push
    if not push:
        return 0
    (work / FILES).write_text("\n".join(staged_files(state)) + "\n", encoding="utf-8")
    return EXIT_STAGED


def cmd_live(a: argparse.Namespace) -> int:
    now = now_utc(None)
    work = Path(a.work)
    state = read_state(work, a.date)
    waiting = [slot for slot in state["reels"] if slot.get("status") == "staged"]
    if not waiting:
        print(f"card reel: nothing staged (slots: {', '.join(str(s.get('status')) for s in state['reels']) or 'none chosen'})")
        return 1
    deadline = time.monotonic() + a.timeout
    errors: dict[int, str] = {}
    while True:
        for slot in list(waiting):
            bad = mf.check_media_urls({slot["url"]: Path(a.repo) / slot["files"][0]})
            if bad:
                errors[id(slot)] = bad[0]
                continue
            slot["status"] = "live"
            note(slot, f"live on Pages: {slot['url']}", now)
            save_state(work, state)
            print(f"card reel: slot {slot.get('slot')}: {attach(Path(a.facts), slot)}")
            waiting.remove(slot)
        if not waiting:
            return 0
        if time.monotonic() > deadline:
            for slot in waiting:
                print(f"card reel: slot {slot.get('slot')}: not served within {a.timeout} s: {errors.get(id(slot), '?')}")
            return 1
        time.sleep(15)


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
    sub.choices["prepare"].add_argument("--gv", default=str(GV), help="the renderer tree (default tools/gv)")
    sub.choices["prepare"].add_argument("--python", default=PYTHON)
    sub.choices["live"].add_argument("--timeout", type=int, default=600)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
        ap.error("--date must be YYYY-MM-DD")
    for key in ("work", "facts", "repo", "gv"):         # absolute: the renderer runs with cwd=--gv
        if getattr(a, key, None):
            setattr(a, key, str(Path(getattr(a, key)).resolve()))
    return cmd_prepare(a) if a.cmd == "prepare" else cmd_live(a)


if __name__ == "__main__":
    sys.exit(main())
