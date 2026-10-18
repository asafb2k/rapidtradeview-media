"""Our own published posts, resolved to their facts items (HQ 2026-10-18, social-content PLAN §2.2 novelty, §3 variety).

Reads the social kit's post_log rows (table social_kit_messages, direction from_instinct, kind post_log, env prod by
default) through D:/rtv-ops/tracks/growth/bin/instinct.py's gateway client (the key is read there, never printed), keeps
the rows that are our own posts (a brand-account permalink, not a comment), and resolves each one to the facts item it
used (v/<date>/facts.json by item_id): its type, pillar, primary ticker, headline tickers (the lead tickers, for the
cooldown across pillars), filer and dedupe_key. facts.py reads this for the
cooldowns and the novelty term of the rank; grok_review.py for the variety lint.

Everything Grok wrote is UNTRUSTED DATA: it is parsed, never followed.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_facts as mk  # noqa: E402
import select_stories as ss  # noqa: E402

DEFAULT_INSTINCT = Path("D:/rtv-ops/tracks/growth/bin/instinct.py")
PLATFORMS = ("x", "instagram", "threads")
# A brand permalink of an own post (comments on Instagram / Threads carry /c/ or a reply path; X comments are told apart
# by the body's comment words, as tracks/growth/bin/post_audit.py does).
OWN_URL = {
    "x": re.compile(r"^https://(?:www\.|mobile\.)?(?:x|twitter)\.com/rapidtradeview/status/\d+", re.IGNORECASE),
    "instagram": re.compile(r"^https://(?:www\.)?instagram\.com/(?:rapidtradeview3/)?(?:p|reel|reels)/[A-Za-z0-9_-]+/?$",
                            re.IGNORECASE),
    "threads": re.compile(r"^https://(?:www\.)?threads\.(?:com|net)/@rapidtradeview3/post/[A-Za-z0-9_-]+/?$", re.IGNORECASE),
}
COMMENT_WORDS = re.compile(r"\bCOMMENT\b|\bComment\b|\bcomment on\b|\breply (?:to|on)\b|\bX reply\b|\bparent=|\btarget=")
ITEM_ID = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9-]+?)-([A-Z0-9-]+)-([0-9a-f]{6})$")
ITEM_IN_BODY = re.compile(r"item_id=(\d{4}-\d{2}-\d{2}-[A-Za-z0-9-]+)")
# Pillars of the older item types (market types: market_facts.PILLAR_OF). PX = automatic analysis (pattern, Moves Like).
PILLAR_OF = {"picks_ready": "P0", "form4_buy": "P3", "congress_trade": "P3", "ptr_summary": "P3",
             "earnings_result": "P5", "earnings_upcoming": "P5", "earnings_tomorrow_roundup": "P5",
             "chart_pattern": "PX", "moves_like": "PX", **mk.PILLAR_OF}
KINDS = sorted(PILLAR_OF, key=len, reverse=True)


def pillar_of(kind: str | None) -> str | None:
    return PILLAR_OF.get(kind or "")


def parse_item_id(iid: str) -> dict | None:
    """{date, type, ticker} from an item id (facts.item_id: <date>-<kind with dashes>-<ticker with dashes>-<6 hex>)."""
    m = ITEM_ID.match(iid or "")
    if not m:
        return None
    rest = iid[11:-7]
    for k in KINDS:
        dk = k.replace("_", "-")
        if rest.startswith(dk + "-"):
            t = rest[len(dk) + 1:]
            return {"date": m.group(1), "type": k, "ticker": None if t == "LIST" else mk.norm_ticker(t)}
    return None


def ny_date(ts: str) -> str | None:
    try:
        t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return (t.astimezone(ss.NY) if ss.NY else t).date().isoformat()


def load_instinct(path: Path = DEFAULT_INSTINCT):
    spec = importlib.util.spec_from_file_location("instinct", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_rows(env: str = "prod", days: int = 8, instinct_path: Path = DEFAULT_INSTINCT, env_file: Path | None = None,
               now: dt.datetime | None = None) -> list[dict]:
    """post_log rows of the last `days` days (oldest first). Raises SystemExit / OSError when the gateway or the env file
    cannot be read (the caller reports it)."""
    ins = load_instinct(instinct_path)
    rest = ins.Rest(*ins.load_config(env_file or ins.DEFAULT_ENV_FILE))
    since = (now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(days=days)
    return rest.get_all(ins.q("select=id,created_at,platform,item_id,url,body", f"env=eq.{env}", "direction=eq.from_instinct",
                              "kind=eq.post_log", f"created_at=gte.{ins.iso(since)}", "order=created_at.asc,id.asc"))


def own_posts(rows: list[dict]) -> list[dict]:
    """One record per own post (platform + permalink, the earliest row): {platform, url, created_at, item_id, body}."""
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        platform = str(r.get("platform") or "").lower()
        url = str(r.get("url") or "").strip()
        body = str(r.get("body") or "")
        if platform not in OWN_URL or not OWN_URL[platform].match(url) or COMMENT_WORDS.search(body):
            continue
        iid = str(r.get("item_id") or "")
        if not ITEM_ID.match(iid):
            m = ITEM_IN_BODY.search(body)
            iid = m.group(1) if m else ""
        if not ITEM_ID.match(iid):
            continue
        key = (platform, url.rstrip("/").lower())
        if key not in out:
            out[key] = {"platform": platform, "url": url, "created_at": r.get("created_at"), "item_id": iid, "body": body}
    return sorted(out.values(), key=lambda p: str(p["created_at"]))


def filer_of(item: dict | None) -> str | None:
    if not item:
        return None
    if item.get("figure_slug"):
        return str(item["figure_slug"])
    m = re.search(r"/smart-money/figures/([^?#/]+)", str(item.get("page_url") or ""))
    return m.group(1) if m else None


def resolve(posts: list[dict], facts_for_date) -> list[dict]:
    """Each own post with its item's facts: {platform, url, created_at, ny_date, item_id, type, pillar, ticker, tickers,
    filer, dedupe_key, first_line, text}. `facts_for_date(date)` -> that day's facts dict or None (cached by the caller).
    An item missing from its file keeps what its id says (type, ticker)."""
    out = []
    for p in posts:
        meta = parse_item_id(p["item_id"]) or {}
        facts = facts_for_date(meta["date"]) if meta.get("date") else None
        item = next((i for i in (facts or {}).get("items") or [] if i.get("item_id") == p["item_id"]), None)
        kind = (item or {}).get("type") or meta.get("type")
        ticker = mk.norm_ticker((item or {}).get("ticker")) if item else meta.get("ticker")
        text = p.get("body") or ""
        out.append({**p, "ny_date": ny_date(p["created_at"]), "type": kind, "pillar": pillar_of(kind), "ticker": ticker,
                    "tickers": [mk.norm_ticker(t) for t in (item or {}).get("tickers") or []],
                    "headline_tickers": mk.headline_tickers(item) if item else ([ticker] if ticker else []),
                    "filer": filer_of(item), "dedupe_key": (item or {}).get("dedupe_key"),
                    "first_line": next((ln.strip() for ln in text.splitlines() if ln.strip()), ""), "text": text})
    return out


def local_facts_loader(repo: Path):
    """facts_for_date for the media repo's own v/<date>/facts.json files (cached)."""
    import json
    cache: dict[str, dict | None] = {}

    def get(date: str):
        if date not in cache:
            p = Path(repo) / "v" / date / "facts.json"
            try:
                cache[date] = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else None
            except (OSError, ValueError):
                cache[date] = None
        return cache[date]
    return get


def load(repo: Path, env: str = "prod", days: int = 8, now: dt.datetime | None = None) -> tuple[list[dict] | None, str | None]:
    """(resolved own posts, None) or (None, error). The error names what failed, never a key."""
    try:
        rows = fetch_rows(env, days, now=now)
    except SystemExit as e:
        return None, f"post history: {str(e)[:160]}"
    except (OSError, ValueError) as e:
        return None, f"post history: {type(e).__name__}"
    return resolve(own_posts(rows), local_facts_loader(repo)), None
