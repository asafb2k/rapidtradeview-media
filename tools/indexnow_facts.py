"""IndexNow ping of the day's facts landing pages (Growth B3 2026-10-12).

Usage (conda python: C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe):
  indexnow_facts.py --date YYYY-MM-DD [--facts FILE] [--dry-run] [--state PATH] [--log PATH] [--key-file PATH]

Run by daily_common.ps1 (Invoke-IndexNowFacts) after every Publish-Facts on weekdays; a failure is logged there and never
blocks the run. It reads the day's facts.json (default <repo>/v/<date>/facts.json), collects the distinct landing URLs
of its items (page_url without the UTM query or the #anchor, in the file's rank order), and:
  - HARD-EXCLUDES every /earnings/reports/ path (G-N1 holdout; also after it: report pages have their own ping) and
    anything off https://www.rapidtradeview.trade or the bare site root;
  - skips a URL already sent in the last 7 days (the state file, default
    D:/rtv-ops/tracks/growth/research/indexnow-facts-state.json);
  - sends at most 100 URLs a UTC day, in one POST to https://api.indexnow.org/indexnow with the site's IndexNow key;
  - pauses 24 hours after a 429 or 403 (no POST until then; the state says why);
  - writes one receipt line per send (UTC time, date, count, HTTP status) to
    D:/rtv-ops/tracks/growth/research/indexnow-facts.log.
--dry-run prints what would be sent (the key is never printed) and writes neither the state nor the log.

The key is the site's existing one: the file <key>.txt in the app repo's frontend/public (the live
https://www.rapidtradeview.trade/<key>.txt). --key-file names it; by default the one file in
D:/Coding_projects/rapidtradeview/frontend/public whose name is <hex>.txt and whose content is that hex. No such file,
or more than one: exit 2, nothing sent (No Fallbacks: a key is never made up).

Exit codes: 0 sent (200 / 202), nothing new to send, or a dry run; 1 the POST failed (state unchanged: the next run tries
again); 2 usage / key / facts error; 3 paused (a 429 / 403 now or within the last 24 hours).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
HOST = "www.rapidtradeview.trade"
ORIGIN = f"https://{HOST}"
ENDPOINT = "https://api.indexnow.org/indexnow"
REPORT_PATH = "/earnings/reports/"
DAILY_MAX = 100
DEDUPE_DAYS = 7
PAUSE_HOURS = 24
PAUSE_STATUSES = (403, 429)
DEFAULT_STATE = Path("D:/rtv-ops/tracks/growth/research/indexnow-facts-state.json")
DEFAULT_LOG = Path("D:/rtv-ops/tracks/growth/research/indexnow-facts.log")
DEFAULT_KEY_DIR = Path("D:/Coding_projects/rapidtradeview/frontend/public")
KEY_NAME = re.compile(r"^([0-9a-fA-F]{8,128})\.txt$")
UA = "RapidTradeView indexnow-facts (contact@rapidtradeview.trade)"
TIMEOUT_S = 30


class NoKey(Exception):
    """The IndexNow key file is missing or ambiguous: nothing is sent."""


# ---------------------------------------------------------------------------
# URLs

def landing(url) -> str | None:
    """The page a facts page_url lands on (no query, no fragment), or None when it is not one we ping."""
    if not isinstance(url, str):
        return None
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    if p.scheme != "https" or (p.hostname or "").lower() != HOST or p.username or p.password or p.port is not None:
        return None
    path = p.path or "/"
    if REPORT_PATH in path.lower() or path.lower().rstrip("/") == "/earnings/reports":
        return None  # G-N1 holdout: never a report page
    if path in ("", "/"):
        return None
    return urlunsplit(("https", HOST, path, "", ""))


def facts_urls(facts: dict) -> tuple[list[str], dict]:
    """(distinct landing URLs in the file's order, counts of what was left out)."""
    out: list[str] = []
    left = {"items": 0, "report_page": 0, "off_site": 0, "duplicate": 0}
    for it in facts.get("items") or []:
        if not isinstance(it, dict):
            continue
        left["items"] += 1
        raw = it.get("page_url")
        u = landing(raw)
        if u is None:
            left["report_page" if isinstance(raw, str) and REPORT_PATH in raw.lower() else "off_site"] += 1
            continue
        if u in out:
            left["duplicate"] += 1
            continue
        out.append(u)
    return out, left


# ---------------------------------------------------------------------------
# State: {"sent": {url: "YYYY-MM-DD"}, "days": {"YYYY-MM-DD": n}, "paused_until": iso | null, "pause_reason": str}

def load_state(path: Path) -> dict:
    if not path.exists():
        return {"sent": {}, "days": {}, "paused_until": None, "pause_reason": None}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("sent"), dict) or not isinstance(data.get("days"), dict):
        raise ValueError(f"{path}: expected {{\"sent\": {{}}, \"days\": {{}}}}")
    data.setdefault("paused_until", None)
    data.setdefault("pause_reason", None)
    return data


def save_state(path: Path, state: dict, today: dt.date) -> None:
    since = (today - dt.timedelta(days=DEDUPE_DAYS - 1)).isoformat()
    state["sent"] = {u: d for u, d in state["sent"].items() if str(d) >= since}
    state["days"] = {d: n for d, n in state["days"].items() if str(d) >= since}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def paused(state: dict, now: dt.datetime) -> str | None:
    until = state.get("paused_until")
    if not until:
        return None
    try:
        t = dt.datetime.fromisoformat(str(until).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return f"paused until {t:%Y-%m-%dT%H:%MZ} ({state.get('pause_reason') or 'no reason recorded'})" if now < t else None


def plan(urls: list[str], state: dict, today: dt.date) -> tuple[list[str], dict]:
    """(URLs to send now, counts): not sent in the last DEDUPE_DAYS days, within today's DAILY_MAX."""
    since = (today - dt.timedelta(days=DEDUPE_DAYS - 1)).isoformat()
    fresh = [u for u in urls if not str(state["sent"].get(u) or "") >= since]
    room = max(0, DAILY_MAX - int(state["days"].get(today.isoformat()) or 0))
    send = fresh[:room]
    return send, {"landing_urls": len(urls), "sent_in_last_7_days": len(urls) - len(fresh),
                  "over_daily_cap": len(fresh) - len(send), "to_send": len(send), "room_today": room}


# ---------------------------------------------------------------------------
# Key and HTTP

def find_key(key_file: str | None, key_dir: Path = DEFAULT_KEY_DIR) -> str:
    """The site's IndexNow key from its <key>.txt file (the name and the content must agree)."""
    if key_file:
        files = [Path(key_file)]
    else:
        try:
            files = sorted(p for p in key_dir.iterdir() if KEY_NAME.match(p.name))
        except OSError as e:
            raise NoKey(f"{key_dir}: {type(e).__name__}") from None
    good = []
    for p in files:
        m = KEY_NAME.match(p.name)
        try:
            body = p.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        if m and body == m.group(1):
            good.append(body)
    if len(good) != 1:
        raise NoKey(f"expected exactly one <key>.txt whose content is its name in "
                        f"{key_file or key_dir}, found {len(good)}")
    return good[0]


def payload(key: str, urls: list[str]) -> dict:
    return {"host": HOST, "key": key, "keyLocation": f"{ORIGIN}/{key}.txt", "urlList": urls}


def http_post(url: str, body: bytes) -> tuple[int, str]:
    """(status, short body). Network errors raise OSError (urllib.error.URLError is one)."""
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status, r.read(300).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read(300) or b"").decode("utf-8", "replace")


POST = http_post


def log_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


# ---------------------------------------------------------------------------

def run(date: str, facts_file: Path, state_path: Path, log_path: Path, key_file: str | None, dry_run: bool,
        now: dt.datetime | None = None, key_dir: Path = DEFAULT_KEY_DIR) -> int:
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(dt.timezone.utc).date()
    try:
        facts = json.loads(facts_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        print(f"indexnow-facts: facts unreadable ({facts_file}: {type(e).__name__}); nothing sent")
        return 2
    if facts.get("date") != date:
        print(f"indexnow-facts: {facts_file} is for {facts.get('date')!r}, not {date}; nothing sent")
        return 2
    urls, left = facts_urls(facts)
    try:
        state = load_state(state_path)
    except (OSError, ValueError) as e:
        print(f"indexnow-facts: state unreadable ({e}); nothing sent")
        return 2
    send, counts = plan(urls, state, today)
    print(f"indexnow-facts {date}: {left['items']} items, {len(urls)} landing URLs (left out: report pages "
          f"{left['report_page']}, off site {left['off_site']}, duplicates {left['duplicate']}); "
          f"{counts['sent_in_last_7_days']} sent in the last {DEDUPE_DAYS} days, {counts['over_daily_cap']} over the "
          f"{DAILY_MAX}/day cap, {len(send)} to send")
    hold = paused(state, now)
    if dry_run:
        try:
            key = find_key(key_file, key_dir)
            where = "ok"
        except NoKey as e:
            key, where = None, f"MISSING ({e})"
        print(f"DRY RUN: would POST {len(send)} URLs to {ENDPOINT} (host {HOST}, key file {where}; the key is not printed)"
              + (f"; but {hold}" if hold else ""))
        for u in send:
            print(f"  {u}")
        return 0 if key else 2
    if hold:
        print(f"indexnow-facts: {hold}; nothing sent")
        return 3
    if not send:
        return 0
    try:
        key = find_key(key_file, key_dir)
    except NoKey as e:
        print(f"indexnow-facts: no IndexNow key ({e}); nothing sent")
        log_line(log_path, f"{now:%Y-%m-%dT%H:%M:%SZ} {date} count={len(send)} status=no-key sent=0")
        return 2
    body = json.dumps(payload(key, send)).encode("utf-8")
    try:
        status, text = POST(ENDPOINT, body)
    except OSError as e:
        print(f"indexnow-facts: POST failed ({type(e).__name__}); the next run tries again")
        log_line(log_path, f"{now:%Y-%m-%dT%H:%M:%SZ} {date} count={len(send)} status=network-error sent=0")
        return 1
    ok = status in (200, 202)
    note = ""
    if ok:
        for u in send:
            state["sent"][u] = today.isoformat()
        state["days"][today.isoformat()] = int(state["days"].get(today.isoformat()) or 0) + len(send)
    elif status in PAUSE_STATUSES:
        until = now + dt.timedelta(hours=PAUSE_HOURS)
        state["paused_until"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")
        state["pause_reason"] = f"HTTP {status} at {now:%Y-%m-%dT%H:%MZ}"
        note = f" paused_until={state['paused_until']}"
    log_line(log_path, f"{now:%Y-%m-%dT%H:%M:%SZ} {date} count={len(send)} status={status} sent={len(send) if ok else 0}{note}")
    if ok or status in PAUSE_STATUSES:
        save_state(state_path, state, today)
    print(f"indexnow-facts: HTTP {status} for {len(send)} URLs" + (f" ({' '.join(text.split())[:120]})" if text and not ok else "")
          + (f"; paused for {PAUSE_HOURS} h" if note else ""))
    if ok:
        return 0
    return 3 if status in PAUSE_STATUSES else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True)
    ap.add_argument("--facts", help="facts.json (default <repo>/v/<date>/facts.json)")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--key-file", help=f"the site's <key>.txt (default: the one in {DEFAULT_KEY_DIR})")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", a.date):
        ap.error("--date must be YYYY-MM-DD")
    facts = Path(a.facts) if a.facts else Path(a.repo) / "v" / a.date / "facts.json"
    return run(a.date, facts, Path(a.state), Path(a.log), a.key_file, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
