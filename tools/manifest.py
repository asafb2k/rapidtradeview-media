"""Daily video manifest: v/<date>/manifest.json lists the day's video posts for the posting agents.

The social kit (frontend/src/lib/socialKitVideos.ts) fetches the manifest from GitHub Pages and
re-validates it with the same rules; keep the two in step (same keys, same limits).

Usage (conda python: C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe; --repo goes before the
subcommand and defaults to this repo):
  manifest.py write --spec SPEC.json [--merge] [--check-urls] [--repo DIR]
      Build v/<date>/manifest.json from a spec (the posts: slot, time_et, category, story_id,
      post_package path). Captions come verbatim from each post-package.json. Validates before
      writing; nothing is written when a rule fails. --merge keeps the existing manifest's posts
      for slots the spec does not name.
  manifest.py validate --date YYYY-MM-DD [--check-urls] [--remote] [--repo DIR]
      Validate the local manifest (or, with --remote, the one GitHub Pages serves).
  manifest.py wait-urls --spec SPEC.json [--timeout 900] [--repo DIR]
      Poll until every media URL of the spec answers 200 video/mp4 with the local file's size
      (GitHub Pages deploys a push in ~1-3 min).

Spec (JSON):
  {"date": "2026-09-27", "posts": [{"slot": 1, "time_et": "12:00", "category": "insider_trade",
    "story_id": "uber-khosrowshahi", "post_package": "D:/.../post-package.json",
    "story_key": "form4:0001184237-26-000008:UBER", "tickers": ["UBER"], "people": ["Dara Khosrowshahi"],
    "title": "optional; default pinterest.title", "instagram_placement": "optional reel|feed|story|none"}]}

Rules checked (both here and in the kit):
  - media URLs are https://asafb2k.github.io/rapidtradeview-media/v/<date>/<story_id>/<format>.mp4
    and (--check-urls) answer 200 with Content-Type video/mp4;
  - X text and reply carry no "@"; every main text (Instagram caption, X text, Threads text,
    Pinterest description) carries "Not investment advice."; no text anywhere carries #insidertrading;
  - platform limits: X 280 (weighted), Threads 500, Instagram 2,200, Pinterest title 100 /
    description 500; alt text 500;
  - Instagram mix: weekdays at most 1 Reel, 2 feed posts and 2 Stories; weekends one post in all.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCHEMA = "rtv-video-manifest/1"
REPO = Path(__file__).resolve().parent.parent
PAGES_BASE = "https://asafb2k.github.io/rapidtradeview-media"
SITE_HOSTS = ("www.rapidtradeview.trade",)
FORMATS = ("reel_9x16", "feed_4x5", "square_1x1")
PLATFORMS = ("instagram", "x", "threads", "pinterest")
IG_PLACEMENTS = ("reel", "feed", "story")
# Which rendered format each platform posts (owner-approved first wave, 2026-09-27: IG Reel/Story 9:16,
# IG feed / Threads / Pinterest 4:5, X 1:1).
IG_MEDIA = {"reel": "reel_9x16", "story": "reel_9x16", "feed": "feed_4x5"}
PLATFORM_MEDIA = {"x": "square_1x1", "threads": "feed_4x5", "pinterest": "feed_4x5"}
IG_WEEKDAY_MIX = {"reel": 1, "feed": 2, "story": 2}
# Owner-approved daily plan (2026-09-27), New York time. Weekends: one post per platform.
WEEKDAY_SLOTS = {1: "08:00", 2: "09:45", 3: "11:00", 4: "12:45", 5: "14:15", 6: "16:30", 7: "19:00"}
WEEKEND_SLOTS = {1: "12:00"}
CATEGORIES = (
    "earnings_today", "earnings_week", "insider_trade", "congress_trade", "daily_picks", "earnings_report",
    "congress_week", "congress_30d", "person_spotlight", "track_record", "insider_week",
)
NOT_ADVICE = "Not investment advice."
BANNED = re.compile(r"#insidertrading", re.IGNORECASE)
ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
STORY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
TICKER = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")
HANDLE = re.compile(r"^@[A-Za-z0-9._]{1,30}$")
TIME_ET = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# C0 controls except tab / LF, DEL, C1, bidi controls, zero-width and invisible format characters.
CONTROL = re.compile("[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
LIMITS = {"x": 280, "threads": 500, "instagram": 2200, "pinterest_title": 100, "pinterest_description": 500, "alt": 500,
          "title": 200, "story_key": 200, "person": 120}
MAX_POSTS = 7
UA = "RapidTradeView daily-video manifest (contact@rapidtradeview.trade)"

TOP_KEYS = {"schema", "date", "day_type", "timezone", "generated_at", "posts"}
POST_KEYS = {"slot", "time_et", "category", "id", "story_id", "story_key", "title", "tickers", "people", "media",
             "alt_text", "source_urls", "tag_candidates", "platforms"}
PLATFORM_KEYS = {
    "instagram": {"placement", "media", "media_url", "caption", "first_comment", "link_sticker_url", "alt_text"},
    "x": {"media", "media_url", "text", "reply"},
    "threads": {"media", "media_url", "text", "first_reply"},
    "pinterest": {"media", "media_url", "title", "description", "link"},
}
TAG_KEYS = {"handle", "verified"}


# ---------------------------------------------------------------------------
# Counting (X weighted length, same as frontend/src/lib/socialKit.ts xWeightedLength)

X_LINK = re.compile(r"https?://\S+|(?<![A-Za-z0-9@$#_./-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+)([A-Za-z]{2,})(?![A-Za-z0-9@+-])")


def _x_links_bare(labels: str, tld: str) -> bool:
    if len(tld) >= 3:
        return True
    return tld.lower() in ("co", "tv") or labels.count(".") >= 2


def x_weighted_length(text: str) -> int:
    import unicodedata
    s = unicodedata.normalize("NFC", text)

    def weigh(part: str) -> int:
        n = 0
        for ch in part:
            cp = ord(ch)
            light = cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037
            n += 1 if light else 2
        return n

    total, last = 0, 0
    for m in X_LINK.finditer(s):
        if m.group(2) is not None and not _x_links_bare(m.group(1), m.group(2)):
            continue
        total += weigh(s[last:m.start()]) + 23
        last = m.end()
    return total + weigh(s[last:])


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


# ---------------------------------------------------------------------------
# URLs

def media_url(date: str, story_id: str, fmt: str) -> str:
    return f"{PAGES_BASE}/v/{date}/{story_id}/{fmt}.mp4"


def manifest_url(date: str) -> str:
    return f"{PAGES_BASE}/v/{date}/manifest.json"


def _https(url: object, hosts: tuple[str, ...] | None = None) -> bool:
    if not isinstance(url, str) or re.search(r"\s", url) or len(url) > 500:
        return False
    m = re.match(r"^https://([A-Za-z0-9.-]+)(?::\d+)?(/[^\s]*)?$", url)
    if not m or "@" in url.split("/")[2]:
        return False
    return hosts is None or m.group(1) in hosts


def day_type(date: str) -> str:
    return "weekend" if dt.date.fromisoformat(date).weekday() >= 5 else "weekday"


# ---------------------------------------------------------------------------
# Validation (mirrors socialKitVideos.ts validateVideoManifest)

def _text(errors: list[str], at: str, v: object, *, required: bool, limit: int, count=utf16_len,
          needs_advice: bool = False, no_at: bool = False) -> None:
    if v is None:
        if required:
            errors.append(f"{at}: required text is missing")
        return
    if not isinstance(v, str) or not v.strip():
        errors.append(f"{at}: must be non-empty text")
        return
    if CONTROL.search(v):
        errors.append(f"{at}: contains control or invisible characters")
    n = count(v)
    if n > limit:
        errors.append(f"{at}: {n} characters, over the {limit} limit")
    if needs_advice and NOT_ADVICE not in v:
        errors.append(f'{at}: missing "{NOT_ADVICE}"')
    if no_at and "@" in v:
        errors.append(f'{at}: X text must not contain "@" (names only)')
    if BANNED.search(v):
        errors.append(f"{at}: #insidertrading is never used")


def _keys(errors: list[str], at: str, obj: dict, allowed: set[str], required: set[str]) -> None:
    for k in obj:
        if k not in allowed:
            errors.append(f"{at}: unknown field {k!r}")
    for k in sorted(required - set(obj)):
        errors.append(f"{at}: missing field {k!r}")


def validate_manifest(m: object, expected_date: str | None = None) -> list[str]:
    """Every rule the kit enforces; [] = valid."""
    errors: list[str] = []
    if not isinstance(m, dict):
        return ["manifest: must be a JSON object"]
    _keys(errors, "manifest", m, TOP_KEYS, TOP_KEYS)
    if m.get("schema") != SCHEMA:
        errors.append(f"manifest: schema must be {SCHEMA!r}")
    date = m.get("date")
    if not isinstance(date, str) or not DATE.match(date):
        return errors + ["manifest: date must be YYYY-MM-DD"]
    try:
        dtype = day_type(date)
    except ValueError:
        return errors + ["manifest: date is not a calendar date"]
    if expected_date is not None and date != expected_date:
        errors.append(f"manifest: date {date} is not {expected_date}")
    if m.get("day_type") != dtype:
        errors.append(f"manifest: day_type must be {dtype!r} for {date}")
    if m.get("timezone") != "America/New_York":
        errors.append("manifest: timezone must be 'America/New_York'")
    if not isinstance(m.get("generated_at"), str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", m["generated_at"]):
        errors.append("manifest: generated_at must be an ISO UTC time ending in Z")
    posts = m.get("posts")
    if not isinstance(posts, list) or not posts:
        return errors + ["manifest: posts must be a non-empty list"]
    cap = 1 if dtype == "weekend" else MAX_POSTS
    if len(posts) > cap:
        errors.append(f"manifest: {len(posts)} posts; a {dtype} has at most {cap}")
    slots: list[int] = []
    ids: set[str] = set()
    ig_count = {p: 0 for p in IG_PLACEMENTS}
    for i, p in enumerate(posts):
        at = f"posts[{i}]"
        if not isinstance(p, dict):
            errors.append(f"{at}: must be an object")
            continue
        _keys(errors, at, p, POST_KEYS, POST_KEYS)
        slot = p.get("slot")
        if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= MAX_POSTS:
            errors.append(f"{at}: slot must be an integer 1-{MAX_POSTS}")
        else:
            slots.append(slot)
        if not isinstance(p.get("time_et"), str) or not TIME_ET.match(p["time_et"]):
            errors.append(f"{at}: time_et must be HH:MM (New York time)")
        if p.get("category") not in CATEGORIES:
            errors.append(f"{at}: category must be one of {', '.join(CATEGORIES)}")
        sid = p.get("story_id")
        if not isinstance(sid, str) or not STORY_ID.match(sid):
            errors.append(f"{at}: story_id must be lower-case letters, digits and dashes")
            sid = None
        pid = p.get("id")
        if not isinstance(pid, str) or not ITEM_ID.match(pid) or (sid and pid != f"video-{date}-{sid}"):
            errors.append(f"{at}: id must be video-{date}-<story_id>")
        elif pid in ids:
            errors.append(f"{at}: duplicate id {pid}")
        else:
            ids.add(pid)
        _text(errors, f"{at}.story_key", p.get("story_key"), required=True, limit=LIMITS["story_key"])
        _text(errors, f"{at}.title", p.get("title"), required=True, limit=LIMITS["title"])
        tickers = p.get("tickers")
        if not isinstance(tickers, list) or len(tickers) > 10 or not all(isinstance(t, str) and TICKER.match(t) for t in tickers):
            errors.append(f"{at}: tickers must be a list of up to 10 US tickers")
        people = p.get("people")
        if not isinstance(people, list) or len(people) > 10:
            errors.append(f"{at}: people must be a list of up to 10 names")
        else:
            for j, name in enumerate(people):
                _text(errors, f"{at}.people[{j}]", name, required=True, limit=LIMITS["person"])
        media = p.get("media")
        if not isinstance(media, dict):
            errors.append(f"{at}: media must be an object")
            media = {}
        else:
            _keys(errors, f"{at}.media", media, set(FORMATS), set(FORMATS))
            for f in FORMATS:
                if sid and media.get(f) != media_url(date, sid, f):
                    errors.append(f"{at}.media.{f}: must be {media_url(date, sid, f)}")
        _text(errors, f"{at}.alt_text", p.get("alt_text"), required=True, limit=LIMITS["alt"])
        src = p.get("source_urls")
        if not isinstance(src, list) or len(src) > 10 or not all(_https(u) for u in src):
            errors.append(f"{at}: source_urls must be a list of up to 10 https URLs")
        tags = p.get("tag_candidates")
        if not isinstance(tags, dict):
            errors.append(f"{at}: tag_candidates must be an object")
        else:
            for plat, lst in tags.items():
                if plat not in ("instagram", "threads"):
                    errors.append(f"{at}.tag_candidates: only instagram and threads may carry handles (not {plat!r})")
                    continue
                if not isinstance(lst, list) or len(lst) > 5:
                    errors.append(f"{at}.tag_candidates.{plat}: must be a list of up to 5")
                    continue
                for j, t in enumerate(lst):
                    if not isinstance(t, dict):
                        errors.append(f"{at}.tag_candidates.{plat}[{j}]: must be an object")
                        continue
                    _keys(errors, f"{at}.tag_candidates.{plat}[{j}]", t, TAG_KEYS, TAG_KEYS)
                    if not isinstance(t.get("handle"), str) or not HANDLE.match(t["handle"]):
                        errors.append(f"{at}.tag_candidates.{plat}[{j}]: handle must look like @name")
                    if t.get("verified") is not False:
                        errors.append(f"{at}.tag_candidates.{plat}[{j}]: verified must be false (the posting agent verifies)")
        plats = p.get("platforms")
        if not isinstance(plats, dict):
            errors.append(f"{at}: platforms must be an object")
            continue
        _keys(errors, f"{at}.platforms", plats, set(PLATFORMS), {"x", "threads", "pinterest"})
        for plat, block in plats.items():
            if plat not in PLATFORM_KEYS:
                continue
            pat = f"{at}.platforms.{plat}"
            if not isinstance(block, dict):
                errors.append(f"{pat}: must be an object")
                continue
            _keys(errors, pat, block, PLATFORM_KEYS[plat], PLATFORM_KEYS[plat])
            if plat == "instagram":
                placement = block.get("placement")
                if placement not in IG_PLACEMENTS:
                    errors.append(f"{pat}.placement: must be reel, feed or story")
                    continue
                ig_count[placement] += 1
                want = IG_MEDIA[placement]
                story = placement == "story"
                _text(errors, f"{pat}.caption", block.get("caption"), required=not story, limit=LIMITS["instagram"], needs_advice=True)
                if story and block.get("caption") is not None:
                    errors.append(f"{pat}.caption: a Story has no caption (null)")
                _text(errors, f"{pat}.first_comment", block.get("first_comment"), required=False, limit=LIMITS["instagram"])
                if story and block.get("first_comment") is not None:
                    errors.append(f"{pat}.first_comment: a Story has no comments (null)")
                sticker = block.get("link_sticker_url")
                if sticker is not None and (not story or not _https(sticker, SITE_HOSTS)):
                    errors.append(f"{pat}.link_sticker_url: only a Story has one, an https link on www.rapidtradeview.trade")
                _text(errors, f"{pat}.alt_text", block.get("alt_text"), required=True, limit=LIMITS["alt"])
            elif plat == "x":
                want = PLATFORM_MEDIA["x"]
                _text(errors, f"{pat}.text", block.get("text"), required=True, limit=LIMITS["x"], count=x_weighted_length, needs_advice=True, no_at=True)
                _text(errors, f"{pat}.reply", block.get("reply"), required=False, limit=LIMITS["x"], count=x_weighted_length, no_at=True)
            elif plat == "threads":
                want = PLATFORM_MEDIA["threads"]
                _text(errors, f"{pat}.text", block.get("text"), required=True, limit=LIMITS["threads"], needs_advice=True)
                _text(errors, f"{pat}.first_reply", block.get("first_reply"), required=False, limit=LIMITS["threads"])
            else:
                want = PLATFORM_MEDIA["pinterest"]
                _text(errors, f"{pat}.title", block.get("title"), required=True, limit=LIMITS["pinterest_title"])
                _text(errors, f"{pat}.description", block.get("description"), required=True, limit=LIMITS["pinterest_description"], needs_advice=True)
                if not _https(block.get("link"), SITE_HOSTS):
                    errors.append(f"{pat}.link: must be an https link on www.rapidtradeview.trade")
            if block.get("media") != want:
                errors.append(f"{pat}.media: must be {want}")
            if isinstance(media, dict) and block.get("media_url") != media.get(want):
                errors.append(f"{pat}.media_url: must be the post's media.{want}")
    if len(set(slots)) != len(slots):
        errors.append("manifest: two posts share a slot")
    if slots != sorted(slots):
        errors.append("manifest: posts must be in slot order")
    if dtype == "weekday":
        for placement, cap_n in IG_WEEKDAY_MIX.items():
            if ig_count[placement] > cap_n:
                errors.append(f"manifest: {ig_count[placement]} Instagram {placement} posts; a weekday has at most {cap_n}")
    return errors


# ---------------------------------------------------------------------------
# URL checks

def head(url: str, timeout: float = 20.0) -> tuple[int, str, int | None]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            length = r.headers.get("Content-Length")
            return r.status, r.headers.get("Content-Type", ""), int(length) if length and length.isdigit() else None
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, f"error: {e}", None


def check_media_urls(urls: dict[str, Path | None]) -> list[str]:
    """Each URL must answer 200 video/mp4; when a local file is given, with its exact size."""
    errors = []
    for url, local in urls.items():
        status, ctype, length = head(url)
        if status != 200 or not ctype.lower().startswith("video/mp4"):
            errors.append(f"{url}: HTTP {status} {ctype or '(no type)'} (want 200 video/mp4)")
        elif local is not None and local.exists() and length is not None and length != local.stat().st_size:
            errors.append(f"{url}: {length} bytes served, local file has {local.stat().st_size} (Pages not deployed yet?)")
    return errors


def manifest_media_urls(m: dict, repo: Path) -> dict[str, Path | None]:
    out: dict[str, Path | None] = {}
    prefix = f"{PAGES_BASE}/"
    for p in m.get("posts", []):
        for url in (p.get("media") or {}).values():
            out[url] = repo / url[len(prefix):] if isinstance(url, str) and url.startswith(prefix) else None
    return out


# ---------------------------------------------------------------------------
# Building

def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _req(pkg: dict, *keys: str) -> str:
    cur: object = pkg
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            raise ValueError(f"post-package: missing {'.'.join(keys)}")
        cur = cur[k]
    if not isinstance(cur, str) or not cur.strip():
        raise ValueError(f"post-package: {'.'.join(keys)} must be non-empty text")
    return cur


def _opt(pkg: dict, *keys: str) -> str | None:
    cur: object = pkg
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur if isinstance(cur, str) and cur.strip() else None


def _tags(block: object) -> list[dict]:
    out = []
    if isinstance(block, dict):
        for t in block.get("tag_candidates_unverified") or []:
            if isinstance(t, dict) and isinstance(t.get("handle"), str):
                out.append({"handle": t["handle"], "verified": False})
    return out


def assign_instagram(slots: list[int], dtype: str, overrides: dict[int, str | None]) -> dict[int, str]:
    """Instagram placements. Weekend: the one post is a Reel. Weekdays (owner: 1 Reel, 2 feed posts,
    2 Stories): the Reel on the best trade (slot 2, else the next filled slot in 3, 6, 5, 7, 1, 4),
    Stories on earnings (1) and picks (4), feed posts on the second trade (3) and the report (5); a
    placement whose preferred slot is empty moves to the next filled slot in its list. Spec overrides
    ("none" = no Instagram post for that slot) win."""
    if dtype == "weekend":
        return {s: (overrides.get(s) or "reel") for s in slots if overrides.get(s, "reel") != "none"}
    prefs = {"reel": [2, 3, 6, 5, 7, 1, 4], "story": [1, 4, 7, 6, 5, 3, 2], "feed": [3, 5, 6, 7, 2, 1, 4]}
    out: dict[int, str] = {}
    left = dict(IG_WEEKDAY_MIX)
    for s, placement in overrides.items():
        if s in slots and placement and placement != "none":
            out[s] = placement
            left[placement] -= 1
    blocked = {s for s, v in overrides.items() if v == "none"}
    for placement in ("reel", "story", "feed"):
        for s in prefs[placement]:
            if left[placement] <= 0:
                break
            if s in slots and s not in out and s not in blocked:
                out[s] = placement
                left[placement] -= 1
    return out


def build_post(date: str, spec: dict, placement: str | None) -> dict:
    sid = spec["story_id"]
    pkg_path = Path(spec["post_package"])
    pkg = _load(pkg_path)
    media = {f: media_url(date, sid, f) for f in FORMATS}
    alt = _opt(pkg, "alt_text") or _req(pkg, "instagram", "reel", "alt_text")
    platforms: dict[str, dict] = {}
    if placement:
        ig_fmt = IG_MEDIA[placement]
        if placement == "story":
            sticker = _opt(pkg, "instagram", "story", "link_sticker", "url")
            platforms["instagram"] = {"placement": "story", "media": ig_fmt, "media_url": media[ig_fmt], "caption": None,
                                      "first_comment": None, "link_sticker_url": sticker, "alt_text": alt}
        else:
            src = "feed" if placement == "feed" and _opt(pkg, "instagram", "feed", "caption") else "reel"
            platforms["instagram"] = {"placement": placement, "media": ig_fmt, "media_url": media[ig_fmt],
                                      "caption": _req(pkg, "instagram", src, "caption"),
                                      "first_comment": _opt(pkg, "instagram", src, "first_comment"),
                                      "link_sticker_url": None,
                                      "alt_text": _opt(pkg, "instagram", src, "alt_text") or alt}
    platforms["x"] = {"media": PLATFORM_MEDIA["x"], "media_url": media[PLATFORM_MEDIA["x"]],
                      "text": _req(pkg, "x", "post"), "reply": _opt(pkg, "x", "reply")}
    platforms["threads"] = {"media": PLATFORM_MEDIA["threads"], "media_url": media[PLATFORM_MEDIA["threads"]],
                            "text": _req(pkg, "threads", "post"), "first_reply": _opt(pkg, "threads", "first_reply")}
    platforms["pinterest"] = {"media": PLATFORM_MEDIA["pinterest"], "media_url": media[PLATFORM_MEDIA["pinterest"]],
                              "title": _req(pkg, "pinterest", "title"), "description": _req(pkg, "pinterest", "description"),
                              "link": _req(pkg, "pinterest", "link")}
    tags = {}
    if "instagram" in platforms and _tags(pkg.get("instagram")):
        tags["instagram"] = _tags(pkg.get("instagram"))
    if _tags(pkg.get("threads")):
        tags["threads"] = _tags(pkg.get("threads"))
    src_urls = pkg.get("source_urls") if isinstance(pkg.get("source_urls"), list) else []
    return {
        "slot": spec["slot"],
        "time_et": spec["time_et"],
        "category": spec["category"],
        "id": f"video-{date}-{sid}",
        "story_id": sid,
        "story_key": spec["story_key"],
        "title": spec.get("title") or _req(pkg, "pinterest", "title"),
        "tickers": list(spec.get("tickers") or []),
        "people": list(spec.get("people") or []),
        "media": media,
        "alt_text": alt,
        "source_urls": list(src_urls),
        "tag_candidates": tags,
        "platforms": platforms,
    }


def build_manifest(spec: dict, existing: dict | None = None, now: dt.datetime | None = None) -> dict:
    date = spec["date"]
    dtype = day_type(date)
    kept = []
    if existing:
        named = {p["slot"] for p in spec["posts"]}
        kept = [p for p in existing.get("posts", []) if p.get("slot") not in named]
    slots = sorted([p["slot"] for p in spec["posts"]] + [p["slot"] for p in kept])
    overrides = {p["slot"]: p.get("instagram_placement") for p in spec["posts"] if "instagram_placement" in p}
    # Kept posts keep their Instagram placement; the new ones fill what is left of the mix.
    for p in kept:
        overrides[p["slot"]] = (p.get("platforms", {}).get("instagram") or {}).get("placement") or "none"
    placements = assign_instagram(slots, dtype, overrides)
    new_posts = [build_post(date, p, placements.get(p["slot"])) for p in spec["posts"]]
    posts = sorted(kept + new_posts, key=lambda p: p["slot"])
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"schema": SCHEMA, "date": date, "day_type": dtype, "timezone": "America/New_York", "generated_at": stamp, "posts": posts}


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# ---------------------------------------------------------------------------
# CLI

def _fail(errors: list[str]) -> int:
    for e in errors:
        print(f"INVALID: {e}", file=sys.stderr)
    return 1


def cmd_write(a: argparse.Namespace) -> int:
    repo = Path(a.repo)
    spec = _load(Path(a.spec))
    date = spec.get("date")
    if not isinstance(date, str) or not DATE.match(date):
        return _fail(["spec: date must be YYYY-MM-DD"])
    for p in spec.get("posts", []):
        for f in FORMATS:
            local = repo / "v" / date / p["story_id"] / f"{f}.mp4"
            if not local.exists():
                return _fail([f"{local}: missing (copy the rendered MP4s into the repo first)"])
    path = repo / "v" / date / "manifest.json"
    existing = _load(path) if a.merge and path.exists() else None
    try:
        m = build_manifest(spec, existing)
    except (ValueError, KeyError) as e:
        return _fail([str(e)])
    errors = validate_manifest(m, date)
    if not errors and a.check_urls:
        errors = check_media_urls(manifest_media_urls(m, repo))
    if errors:
        return _fail(errors)
    write_json(path, m)
    print(f"wrote {path} ({len(m['posts'])} posts)")
    return 0


def _fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def cmd_validate(a: argparse.Namespace) -> int:
    repo = Path(a.repo)
    if a.remote:
        try:
            m = _fetch_json(manifest_url(a.date))
        except (urllib.error.URLError, OSError, ValueError) as e:
            return _fail([f"{manifest_url(a.date)}: {e}"])
        if a.same_as_local:
            local = _load(repo / "v" / a.date / "manifest.json")
            if m != local:
                return _fail([f"{manifest_url(a.date)}: Pages serves a different manifest than the local file (not deployed yet?)"])
    else:
        m = _load(repo / "v" / a.date / "manifest.json")
    errors = validate_manifest(m, a.date)
    if not errors and a.check_urls:
        errors = check_media_urls(manifest_media_urls(m, repo))
    if errors:
        return _fail(errors)
    print(f"valid: {a.date} ({len(m['posts'])} posts){' + media URLs 200 video/mp4' if a.check_urls else ''}")
    return 0


def cmd_wait_urls(a: argparse.Namespace) -> int:
    repo = Path(a.repo)
    spec = _load(Path(a.spec))
    urls = {media_url(spec["date"], p["story_id"], f): repo / "v" / spec["date"] / p["story_id"] / f"{f}.mp4"
            for p in spec["posts"] for f in FORMATS}
    deadline = time.monotonic() + a.timeout
    while True:
        errors = check_media_urls(urls)
        if not errors:
            print(f"all {len(urls)} media URLs answer 200 video/mp4 with the local sizes")
            return 0
        if time.monotonic() > deadline:
            return _fail(errors)
        time.sleep(20)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(REPO))
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("--spec", required=True)
    w.add_argument("--merge", action="store_true")
    w.add_argument("--check-urls", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("--date", required=True)
    v.add_argument("--check-urls", action="store_true")
    v.add_argument("--remote", action="store_true")
    v.add_argument("--same-as-local", action="store_true")
    u = sub.add_parser("wait-urls")
    u.add_argument("--spec", required=True)
    u.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    return {"write": cmd_write, "validate": cmd_validate, "wait-urls": cmd_wait_urls}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
