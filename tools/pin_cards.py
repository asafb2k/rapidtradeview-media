"""Pin the Market share cards that the day's facts items use (HQ 2026-10-18, social-content PLAN §2.4).

The live card (https://www.rapidtradeview.trade/market/card/<panel>, 1080x1350) redraws every session and with every new
filing. A post preflighted an hour ahead must carry the image its text describes, and an audit must see what went out, so
a market item's media is a copy of the card on our Pages site, made in the same facts pass that read the numbers:
  v/<date>/cards/market-<panel>-<data date>-<fingerprint>.png
<fingerprint> hashes the panel's data (market_facts.panel_fingerprint): every item of one panel and data shares one file,
and an existing file (any date folder) is reused, never downloaded again.

Usage (conda python), as tools/daily_common.ps1 Invoke-PinCards runs it:
  pin_cards.py prepare --facts TMP --repo REPO --date D --work W   download the missing cards (the QA header via
        qa_header.py, a warm-up GET first so the card's own data cache refreshes, then the GET that is kept; PNG checks),
        write <work>/pin-cards.json (item_id -> file, url, sha256) and <work>/pin-cards-files.txt (paths to git add,
        pruned files included). Exit 10: files to commit; 0: nothing new; 1: a failure (logged; apply still runs).
  pin_cards.py apply --facts TMP --repo REPO --work W [--timeout S] [--no-wait]   wait until Pages serves every planned
        file (HEAD 200), then fill each item's card.url / card.sha256 / media. An item whose card is not served is taken
        out of the facts (left_out.card_unpinned, an error line): No Fallbacks, no market post without its own card.
Pruning: market-*.png files under v/<date>/cards older than PRUNE_DAYS are deleted (in prepare, listed for git add).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402
import qa_header as qa  # noqa: E402

UA = "RapidTradeView facts card pin (contact@rapidtradeview.trade)"
PNG = b"\x89PNG\r\n\x1a\n"
MIN_BYTES = 20_000
WARMUP_S = 15
PRUNE_DAYS = 30
SLEEP = time.sleep


def card_items(facts: dict) -> list[dict]:
    return [i for i in facts.get("items") or [] if isinstance(i, dict) and isinstance(i.get("card"), dict)
            and i["card"].get("file") and i["card"].get("live_url")]


def pages_url(rel: str) -> str:
    return f"{mf.PAGES_BASE}/{rel}"


def existing(repo: Path, name: str) -> str | None:
    """The repo-relative path of an already pinned file with this name (oldest date folder first), or None."""
    hits = sorted(Path(repo).glob(f"v/*/cards/{name}"))
    return hits[0].relative_to(repo).as_posix() if hits else None


def fetch_png(url: str) -> bytes:
    """One GET of a share card through the QA header; raises ValueError when it is not a real card PNG."""
    req = urllib.request.Request(f"{url}?pin={time.time_ns()}", headers={"User-Agent": UA, "Accept": "image/png"})
    with qa.urlopen(req, timeout=60) as r:
        body = r.read()
        ctype = r.headers.get("Content-Type", "")
    if not ctype.startswith("image/png") or not body.startswith(PNG) or len(body) < MIN_BYTES:
        raise ValueError(f"not a card PNG ({ctype or 'no type'}, {len(body)} bytes)")
    return body


def prune(repo: Path, today: dt.date) -> list[str]:
    out = []
    for p in Path(repo).glob("v/*/cards/market-*.png"):
        try:
            day = dt.date.fromisoformat(p.parent.parent.name)
        except ValueError:
            continue
        if (today - day).days > PRUNE_DAYS:
            p.unlink()
            out.append(p.relative_to(repo).as_posix())
    return out


def prepare(facts_path: Path, repo: Path, date: str, work: Path) -> int:
    facts = json.loads(facts_path.read_text(encoding="utf-8-sig"))
    plan: dict[str, dict] = {}
    new: list[str] = []
    failed = 0
    by_file: dict[str, str] = {}
    for it in card_items(facts):
        c = it["card"]
        name = c["file"]
        if name not in by_file:
            rel = existing(repo, name)
            if not rel:
                rel = f"v/{date}/cards/{name}"
                try:
                    fetch_png(c["live_url"])          # warm-up: the card route's data cache refreshes on this request
                    SLEEP(WARMUP_S)
                    body = fetch_png(c["live_url"])
                except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                    print(f"pin {c['panel']}: {type(e).__name__}: {str(e)[:120]}")
                    failed += 1
                    by_file[name] = ""
                    continue
                dest = Path(repo) / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
                new.append(rel)
                print(f"pinned {c['panel']} -> {rel} ({len(body)} bytes)")
            by_file[name] = rel
        rel = by_file[name]
        if rel:
            sha = hashlib.sha256((Path(repo) / rel).read_bytes()).hexdigest()
            plan[it["item_id"]] = {"file": rel, "url": pages_url(rel), "sha256": sha}
    pruned = prune(repo, dt.date.fromisoformat(date))
    work.mkdir(parents=True, exist_ok=True)
    (work / "pin-cards.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    (work / "pin-cards-files.txt").write_text("\n".join(new + pruned) + ("\n" if new or pruned else ""), encoding="utf-8")
    print(f"pin cards: {len(plan)} items planned, {len(new)} new files, {len(pruned)} pruned, {failed} failed")
    if new or pruned:
        return 10
    return 1 if failed else 0


def served(url: str) -> bool:
    req = urllib.request.Request(f"{url}?fresh={time.time_ns()}", method="HEAD",
                                 headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def apply(facts_path: Path, work: Path, timeout: int, wait: bool) -> int:
    facts = json.loads(facts_path.read_text(encoding="utf-8-sig"))
    try:
        plan = json.loads((work / "pin-cards.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        plan = {}
    urls = sorted({p["url"] for p in plan.values()})
    ok = set(urls)
    if wait and urls:
        deadline = time.monotonic() + timeout
        pending = set(urls)
        while pending:
            pending = {u for u in pending if not served(u)}
            if not pending or time.monotonic() > deadline:
                break
            SLEEP(20)
        ok = set(urls) - pending
    kept, dropped = [], []
    for it in facts.get("items") or []:
        c = it.get("card") if isinstance(it, dict) else None
        if not isinstance(c, dict) or not c.get("file"):
            kept.append(it)
            continue
        p = plan.get(it["item_id"])
        if not p or p["url"] not in ok:
            dropped.append(f"{it['type']} {it.get('ticker') or it['item_id']}: share card not pinned "
                           f"({'not served by Pages yet' if p else 'download failed'})")
            continue
        c["url"], c["sha256"] = p["url"], p["sha256"]
        it["media"] = [{"url": p["url"], "kind": "image", "alt": " ".join(str(it.get("facts_text") or "").split())}]
        kept.append(it)
    facts["items"] = kept
    if dropped:
        facts.setdefault("left_out", {})["card_unpinned"] = {"dropped": len(dropped), "reasons": dropped}
        facts.setdefault("errors", []).extend(f"not published: {d}" for d in dropped)
        counts = facts.get("counts") or {}
        for k in counts:
            counts[k] = sum(1 for i in kept if i.get("type") == k)
    mf.write_json(facts_path, facts)
    print(f"pin cards apply: {len(kept)} items kept, {len(dropped)} dropped (card not pinned)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["prepare", "apply"])
    ap.add_argument("--facts", required=True)
    ap.add_argument("--repo", default=str(mf.REPO))
    ap.add_argument("--date")
    ap.add_argument("--work", required=True)
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--no-wait", action="store_true", help="apply without checking Pages (a -NoPush dry run)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.mode == "prepare":
        if not a.date:
            ap.error("--date is required for prepare")
        return prepare(Path(a.facts), Path(a.repo), a.date, Path(a.work))
    return apply(Path(a.facts), Path(a.work), a.timeout, not a.no_wait)


if __name__ == "__main__":
    sys.exit(main())
