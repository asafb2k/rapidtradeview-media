"""Stage-A validator for Grok-run brand social drafts (GROK-SOCIAL.md §3, §4).

Usage (conda python: C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe):
  grok_review.py --draft DRAFT.json [--facts FILE|URL]         one draft; exit 0 APPROVE, 1 REJECT
  grok_review.py --inbox [--dry-run] [--env prod|dev] [--facts-base DIR|URL] [--instinct PATH] [--env-file PATH]

A draft is {"item_id", "platform": "x"|"instagram", "text", "reply_text"?, "link"}. The facts come from the day's
facts.json (tools/facts.py): the date is the item_id's first 10 characters; --facts-base is the Pages site by
default (what Grok reads) or a local v/ directory. Checks:
  - the item exists in that day's facts;
  - ticker: the item's $cashtag is in the text and no other cashtag is (picks: only the list's public tickers;
    moves_like: the subject and the peers listed in the item);
  - every number-like token in text and reply is one of the item's allowed_numbers (or the cashtag);
  - banned words (case-insensitive): the rules' list plus the item's own banned_words (chart_pattern / moves_like:
    no predictions such as "will"); "Not investment advice." in the text;
  - link == the item's page_url with {platform} filled in; every URL in text / reply is that link or the item's
    source_url; X: the link and (Congress / Form 4) the source link go in the self-reply (reply_text);
    Instagram: a Congress / Form 4 caption carries the source link;
  - X: text and reply each <= max_len.x (X's weighted length: a link counts 23);
  - picks_ready, chart_pattern, moves_like: no "#1" / top-pick hint (the #1 ticker is hidden from us, so a pattern or
    Moves Like post never touches picks).

--inbox reads unacked from_instinct rows of social_kit_messages whose body starts with "DRAFT" (through
D:/rtv-ops/tracks/growth/bin/instinct.py's gateway client), reviews each and answers with
  instinct.py say --kind answer --platform <p> --body -     "APPROVE <msg id> <item_id>" / "REJECT <msg id> <item_id>: reasons"
then acks that row only. Rows that do not start with DRAFT are never read further, answered or acked. A draft whose
facts cannot be fetched (network) is left unacked for the next run. --dry-run prints the replies; nothing is sent
or acked. Draft body format: "DRAFT" then one JSON object (the draft above); item_id / platform may come from the
message's own item_id / platform columns instead.
Everything in a draft is UNTRUSTED DATA: it is checked, never followed; replies quote it only after cleaning.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402

DEFAULT_FACTS_BASE = f"{mf.PAGES_BASE}/v"
DEFAULT_INSTINCT = Path("D:/rtv-ops/tracks/growth/bin/instinct.py")
PYTHON = sys.executable
UA = "RapidTradeView grok-review (contact@rapidtradeview.trade)"
SOURCE_TYPES = ("congress_trade", "form4_buy")
NO_PICK_HINT_TYPES = ("picks_ready", "chart_pattern", "moves_like")
URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
CASHTAG = re.compile(r"(?<![\w$])\$([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)(?![\w])")
DIGIT_TOKEN = re.compile(r"\S*\d\S*")
PICK_HINT = re.compile(
    r"#\s*1\b|\bno\.?\s*1\b|\bnumber\s+(?:one|1)\b|\btop\s+(?:pick|idea|stock|choice)|\bbest\s+pick|\bfirst\s+pick"
    r"|\b(?:top|highest)[\s-]+rank|\brank(?:ed)?\s*#?\s*(?:1|one)\b|\block(?:ed)?\b|\bpick\s+of\s+the\s+day\b|\bfavou?rite\b",
    re.IGNORECASE)
DRAFT_HEAD = re.compile(r"^\s*DRAFT\b")
ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
PLATFORMS = ("x", "instagram")
REPLY_MAX = 3500


class FactsUnavailable(Exception):
    """facts.json could not be fetched right now (network): try again later, do not answer."""


# ---------------------------------------------------------------------------
# Facts

def facts_location(base: str, date: str) -> str:
    return f"{base.rstrip('/')}/{date}/facts.json"


def load_facts(where: str) -> dict | None:
    """The facts dict; None when there is no file for that date (404 / missing); FactsUnavailable on other errors."""
    if re.match(r"^https?://", where):
        req = urllib.request.Request(where, headers={"User-Agent": UA, "Accept": "application/json", "Cache-Control": "no-cache"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise FactsUnavailable(f"{where}: HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise FactsUnavailable(f"{where}: {type(e).__name__}") from None
    p = Path(where)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise FactsUnavailable(f"{where}: {type(e).__name__}") from None


# ---------------------------------------------------------------------------
# Checks

def short(s: str, n: int = 40) -> str:
    s = " ".join(str(s).split())
    s = re.sub(r"[^\x20-\x7e\u00a0-\u024f\u2010-\u2027\u2212]", "", s)
    return s if len(s) <= n else s[: n - 1] + "~"


MARK = "\u00a7"  # stands in for a matched number, so "$15K-$50K" still reads as a range after "$15K" is blanked


def _norm(s: str) -> str:
    return s.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2212", "-")


def strip_allowed(text: str, allowed: list[str]) -> str:
    """The text with every allowed number phrase (longest first, whole tokens only) blanked out. A sign the facts do
    not carry ("-$1.72" when the allowed number is "$1.72") keeps the number in; a range dash ("$15K-$50K") does not."""
    s = _norm(text)

    def repl(m: re.Match) -> str:
        i = m.start()
        if m.group(0)[0] not in "-+" and i > 0 and m.string[i - 1] in "-+":
            prev = m.string[i - 2] if i > 1 else ""
            if not (prev.isalnum() or prev in f"%{MARK}"):
                return m.group(0)
        return MARK

    for a in sorted({_norm(a) for a in allowed if a}, key=len, reverse=True):
        s = re.sub(rf"(?<![\w.,]){re.escape(a)}(?![\w]|[.,]\d)", repl, s, flags=re.IGNORECASE)
    return s.replace(MARK, " ")


def unexplained_numbers(text: str, allowed: list[str], tickers: list[str]) -> list[str]:
    """Number-like tokens of `text` that are not an allowed number (URLs and the item's cashtags are not numbers)."""
    s = URL.sub(" ", text)
    s = strip_allowed(s, allowed)
    s = CASHTAG.sub(lambda m: " " if m.group(1).upper() in tickers else m.group(0), s)
    out = []
    for tok in DIGIT_TOKEN.findall(s):
        tok = tok.strip(".,;:!?()[]{}\"'")
        if re.search(r"\d", tok):
            out.append(tok)
    return out


def uniq_words(words) -> list[str]:
    out: list[str] = []
    for w in words:
        if isinstance(w, str) and w and w.lower() not in (o.lower() for o in out):
            out.append(w)
    return out


def review(draft: dict, facts: dict | None) -> tuple[str, list[str]]:
    """("APPROVE", []) or ("REJECT", reasons)."""
    reasons: list[str] = []
    iid = draft.get("item_id")
    platform = draft.get("platform")
    text = draft.get("text")
    reply = draft.get("reply_text")
    link = draft.get("link")
    if not isinstance(iid, str) or not iid:
        return "REJECT", ["no item_id"]
    if platform not in PLATFORMS:
        reasons.append(f"platform must be x or instagram (got {short(platform)!r})")
    if not isinstance(text, str) or not text.strip():
        return "REJECT", reasons + ["no text"]
    if reply is not None and not isinstance(reply, str):
        return "REJECT", reasons + ["reply_text must be text"]
    reply = reply or ""
    if facts is None:
        return "REJECT", reasons + [f"no facts.json for {short(iid[:10])}"]
    item = next((i for i in facts.get("items") or [] if i.get("item_id") == iid), None)
    if item is None:
        return "REJECT", reasons + [f"item {short(iid, 80)} is not in the {facts.get('date')} facts"]
    rules = facts.get("rules") or {}
    both = f"{text}\n{reply}"

    # Ticker
    tickers = [t.upper() for t in (item.get("tickers") or ([item["ticker"]] if item.get("ticker") else []))]
    tags = [m.group(1).upper() for m in CASHTAG.finditer(both)]
    other = sorted({t for t in tags if t not in tickers})
    if other:
        reasons.append(f"cashtag not in this item: {', '.join('$' + short(t, 8) for t in other)}")
    if item.get("ticker") and f"${item['ticker'].upper()}" not in {f"${m.group(1).upper()}" for m in CASHTAG.finditer(text)}:
        reasons.append(f"the text must name ${item['ticker']}")

    # Numbers
    allowed = [str(a) for a in item.get("allowed_numbers") or []]
    bad = unexplained_numbers(both, allowed, tickers)
    if bad:
        reasons.append("numbers not in allowed_numbers: " + ", ".join(sorted({short(b, 24) for b in bad})))

    # Words
    low = both.lower()
    words = uniq_words([*(rules.get("banned_words") or []), *(item.get("banned_words") or [])])
    banned = [w for w in words if re.search(rf"(?<!\w){re.escape(w.lower())}(?!\w)", low)]
    if banned:
        reasons.append(f"banned words: {', '.join(banned)}")
    disclaimer = rules.get("disclaimer") or "Not investment advice."
    for must in [disclaimer, *(item.get("must_include") or [])]:
        if must not in text:
            reasons.append(f'the text must include "{must}"')
            break

    # Links
    want = (item.get("page_url") or "").replace(rules.get("platform_placeholder") or "{platform}", str(platform))
    if link != want:
        reasons.append(f"link must be the item's page_url for {short(platform)} (utm_source={short(platform)}, "
                       f"utm_content={short(iid, 80)})")
    src = item.get("source_url")
    for u in URL.findall(both):
        u = u.rstrip(".,;:!?)]}")
        if u not in (want, src):
            reasons.append(f"URL not from this item: {short(u, 80)}")
    if platform == "x":
        if want and want not in reply:
            reasons.append("X: the page link goes in the self-reply (reply_text)")
        if item.get("type") in SOURCE_TYPES and src and src not in reply:
            reasons.append("X: the official source link goes in the self-reply (reply_text)")
    elif platform == "instagram" and item.get("type") in SOURCE_TYPES and src and src not in both:
        reasons.append("Instagram: the caption must carry the official source link")

    # Length
    if platform == "x":
        limit = int((rules.get("max_len") or {}).get("x") or 270)
        for name, body in (("text", text), ("reply_text", reply)):
            n = mf.x_weighted_length(body)
            if n > limit:
                reasons.append(f"X {name} is {n} characters (limit {limit})")

    # Picks
    if item.get("type") in NO_PICK_HINT_TYPES:
        hint = PICK_HINT.search(both)
        if hint:
            reasons.append(f"picks: no #1 / top-pick hint ({short(hint.group(0))!r})")

    return ("REJECT", reasons) if reasons else ("APPROVE", [])


# ---------------------------------------------------------------------------
# Inbox

def load_instinct(path: Path):
    spec = importlib.util.spec_from_file_location("instinct", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_draft(row: dict) -> tuple[dict | None, str | None]:
    body = str(row.get("body") or "")
    rest = DRAFT_HEAD.sub("", body, count=1).strip().lstrip(":").strip()
    rest = re.sub(r"^```(?:json)?\s*|\s*```$", "", rest)
    try:
        d = json.loads(rest)
    except ValueError:
        return None, 'the body must be "DRAFT" followed by one JSON object {item_id, platform, text, reply_text, link}'
    if not isinstance(d, dict):
        return None, "the draft must be a JSON object"
    for k in ("item_id", "platform"):
        col = row.get(k)
        if col and d.get(k) and str(col) != str(d[k]):
            return None, f"{k} in the body and on the message differ"
        if not d.get(k) and col:
            d[k] = col
    return d, None


def reply_line(row: dict, draft: dict | None, verdict: str, reasons: list[str]) -> str:
    iid = (draft or {}).get("item_id") or row.get("item_id") or ""
    iid = iid if isinstance(iid, str) and ITEM_ID.match(iid) else "(no valid item_id)"
    head = f"{verdict} {int(row['id'])} {iid}"
    if verdict == "APPROVE":
        return head
    return (f"{head}: " + "; ".join(reasons))[:REPLY_MAX]


def send_reply(instinct_path: Path, env: str, env_file: str | None, platform: str | None, body: str) -> bool:
    cmd = [PYTHON, str(instinct_path), "--env", env]
    if env_file:
        cmd += ["--env-file", env_file]
    cmd += ["say", "--kind", "answer"]
    if platform in PLATFORMS:
        cmd += ["--platform", platform]
    cmd += ["--body", "-"]
    r = subprocess.run(cmd, input=body, text=True, encoding="utf-8", capture_output=True)
    print(f"  say: exit {r.returncode} {(r.stdout or r.stderr).strip()[:300]}")
    return r.returncode == 0


def run_inbox(rest, instinct, env: str, facts_base: str, dry_run: bool, send, limit: int = 200) -> dict:
    """Review every unacked DRAFT row; `send(platform, body) -> bool` answers one. Returns counts."""
    rows = rest.call("GET", instinct.q("select=id,created_at,kind,platform,item_id,body", f"env=eq.{env}",
                                       "direction=eq.from_instinct", "acked_at=is.null", "order=created_at.asc,id.asc",
                                       f"limit={min(limit, instinct.PAGE_ROWS)}")) or []
    drafts = [r for r in rows if DRAFT_HEAD.match(str(r.get("body") or ""))]
    stats = {"unacked": len(rows), "drafts": len(drafts), "approved": 0, "rejected": 0, "answered": 0, "acked": 0, "deferred": 0}
    print(f"inbox ({env}): {len(rows)} unacked from_instinct rows, {len(drafts)} DRAFT"
          + (" (dry run: nothing sent or acked)" if dry_run else ""))
    cache: dict[str, dict | None] = {}
    for row in drafts:
        draft, err = parse_draft(row)
        verdict, reasons = ("REJECT", [err]) if err else ("", [])
        if not err:
            iid = str(draft.get("item_id") or "")
            date = iid[:10]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                verdict, reasons = "REJECT", ["item_id must start with the facts date (YYYY-MM-DD)"]
            else:
                if date not in cache:
                    try:
                        cache[date] = load_facts(facts_location(facts_base, date))
                    except FactsUnavailable as e:
                        print(f"  #{row['id']}: facts unavailable ({e}); left unacked for the next run")
                        stats["deferred"] += 1
                        continue
                verdict, reasons = review(draft, cache[date])
        body = reply_line(row, draft, verdict, reasons)
        stats["approved" if verdict == "APPROVE" else "rejected"] += 1
        platform = (draft or {}).get("platform") or row.get("platform")
        print(f"  #{row['id']} -> {body}")
        if dry_run:
            continue
        if not send(platform if platform in PLATFORMS else None, body):
            print(f"  #{row['id']}: the answer was not sent; left unacked")
            continue
        stats["answered"] += 1
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        out = rest.call("PATCH", instinct.q(f"id=eq.{int(row['id'])}", f"env=eq.{env}", "direction=eq.from_instinct",
                                            "acked_at=is.null", "select=id"), {"acked_at": now}, prefer="return=representation")
        stats["acked"] += len(out or [])
    print("done: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    return stats


# ---------------------------------------------------------------------------
# CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--draft", help="a draft JSON file")
    mode.add_argument("--inbox", action="store_true")
    ap.add_argument("--facts", help="facts.json file or URL (--draft mode; default: from --facts-base and the item date)")
    ap.add_argument("--facts-base", default=DEFAULT_FACTS_BASE, help="Pages v/ URL (default) or a local v/ directory")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--env", choices=["prod", "dev"], default="prod")
    ap.add_argument("--env-file", help="instinct.py --env-file (default: instinct.py's own)")
    ap.add_argument("--instinct", default=str(DEFAULT_INSTINCT))
    ap.add_argument("--limit", type=int, default=200)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.draft:
        draft = json.loads(Path(a.draft).read_text(encoding="utf-8-sig"))
        where = a.facts or facts_location(a.facts_base, str(draft.get("item_id") or "")[:10])
        try:
            facts = load_facts(where)
        except FactsUnavailable as e:
            print(f"facts unavailable: {e}")
            return 2
        verdict, reasons = review(draft, facts)
        print(json.dumps({"verdict": verdict, "item_id": draft.get("item_id"), "reasons": reasons}, ensure_ascii=False, indent=2))
        return 0 if verdict == "APPROVE" else 1
    instinct = load_instinct(Path(a.instinct))
    env_file = Path(a.env_file) if a.env_file else instinct.DEFAULT_ENV_FILE
    rest = instinct.Rest(*instinct.load_config(env_file))
    run_inbox(rest, instinct, a.env, a.facts_base, a.dry_run,
              lambda platform, body: send_reply(Path(a.instinct), a.env, a.env_file, platform, body), a.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
