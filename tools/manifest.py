"""Daily video manifest: v/<date>/manifest.json lists the day's video and image posts for the posting agents.

The social kit (frontend/src/lib/socialKitVideos.ts) fetches the manifest from GitHub Pages and
re-validates it with the same rules; keep the two in step (same keys, same limits).

Usage (conda python: C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe; --repo goes before the
subcommand and defaults to this repo):
  manifest.py write --spec SPEC.json [--merge] [--replace-slot N ...] [--check-urls] [--repo DIR]
      Build v/<date>/manifest.json from a spec (the posts: slot, time_et, category, story_id,
      post_package path). Captions come verbatim from each post-package.json. Validates before
      writing; nothing is written when a rule fails. --merge keeps the existing manifest's posts
      for slots the spec does not name. --replace-slot N (with --merge): the spec deliberately
      replaces the already-published post in slot N (a correction); refused unless slot N is in both
      the published manifest and the spec, and the spec names no other published slot.
  manifest.py validate --date YYYY-MM-DD [--check-urls] [--remote] [--repo DIR]
      Validate the local manifest (or, with --remote, the one GitHub Pages serves).
  manifest.py wait-urls --spec SPEC.json [--timeout 900] [--repo DIR]
      Poll until every media URL of the spec answers 200 (video/mp4, image/png or image/jpeg) with the
      local file's size (GitHub Pages deploys a push in ~1-3 min).
  manifest.py preflight --date YYYY-MM-DD [--slots 1,2 | --due-within-min 90 [--due-after-min 60]]
                        [--manifest FILE --local-only [--media-dir DIR]] [--hold] [--now ISO-UTC]
      The preflight gate (tools/preflight.py; owner rule 2026-09-28: every post ready one hour before it
      goes live): re-checks each post, its media (200 + sha256 of the local copy), date-pinned sources,
      the claims lint, every number and date against the post's data. One report per slot in
      D:/rtv-ops/tracks/growth/research/daily-video/<date>/preflight-<slot>.json. --hold marks each
      failing post "status": "held" (+ held_reason) in the manifest; nothing is deleted. Exit 0 = all
      pass, 1 = a failure, 2 = nothing to check (no manifest, or nothing due in the window).
  manifest.py check-spec --spec SPEC.json [--list-out FILE]
      Every post has its post-package and its files in v/<date>/<story_id>/; writes the repo paths of
      those files to FILE (for git add). Exit 1 with the missing ones.

Media: a video post has reel_9x16.mp4, feed_4x5.mp4 and square_1x1.mp4; an image post has PNG or JPEG
images (feed_4x5, square_1x1, pin_2x3, story_9x16); a post may carry both ("media_type" in the spec
picks what the platforms post; default video when the MP4s are there). Images per platform: X
square_1x1 (else feed_4x5), Threads feed_4x5 (else square_1x1), Pinterest pin_2x3 (else feed_4x5),
Instagram feed feed_4x5, Instagram Story story_9x16; an image post is never a Reel.

Spec (JSON):
  {"date": "2026-09-27", "posts": [{"slot": 1, "time_et": "12:00", "category": "insider_trade",
    "story_id": "uber-khosrowshahi", "post_package": "D:/.../post-package.json",
    "story_key": "form4:0001184237-26-000008:UBER", "tickers": ["UBER"], "people": ["Dara Khosrowshahi"],
    "title": "optional; default pinterest.title", "instagram_placement": "optional reel|feed|story|none",
    "media_type": "optional video|image"}]}

Rules checked (both here and in the kit):
  - media URLs are https://asafb2k.github.io/rapidtradeview-media/v/<date>/<story_id>/<format>.mp4
    (images: .png or .jpg) and (--check-urls) answer 200 with Content-Type video/mp4 (image/png, image/jpeg);
  - X text and reply carry no "@"; every main text (Instagram caption, X text, Threads text,
    Pinterest description) carries "Not investment advice."; no text anywhere carries #insidertrading;
  - X text carries EXACTLY ONE hashtag, counted inside the 280 weighted limit, so the posting agent posts
    it verbatim and never trims (Growth lead 2026-09-28, after a 287-character post on 2026-09-27);
    manifests dated X_ONE_HASHTAG_FROM or later (the 2026-09-27 / 09-28 ones predate the rule);
  - platform limits: X 280 (weighted), Threads 500, Instagram 2,200, Pinterest title 100 /
    description 500; alt text 500;
  - Instagram mix: weekdays at most 1 Reel, 2 feed posts and 2 Stories; weekends one post in all;
  - a post may carry "status": "held" with a held_reason (the kit shows it as "do not post").
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
# A feature promo (slot 8) comes on top of the daily plan (owner 2026-09-28: "in addition", not instead), so its
# Instagram post (a Reel unless the spec says otherwise) does not count against the mix.
MIX_EXEMPT_CATEGORIES = ("product_promo",)
IMAGE_FORMATS = ("feed_4x5", "square_1x1", "pin_2x3", "story_9x16")
IMAGE_EXTS = {"png": "image/png", "jpg": "image/jpeg"}
# Image media per platform: the writer takes the first one the post has; the validator accepts any.
IMAGE_PLATFORM_MEDIA = {"x": ("square_1x1", "feed_4x5"), "threads": ("feed_4x5", "square_1x1"), "pinterest": ("pin_2x3", "feed_4x5")}
IG_IMAGE_MEDIA = {"feed": "feed_4x5", "story": "story_9x16"}  # an image post is never a Reel
MEDIA_TYPES = ("video", "image")
# Owner-approved daily plan, New York time. Growth lead 2026-09-28 (owner: every post ready an hour before
# it goes live): picks 15:00 (rendered at the 13:45 pass, ready ~14:00), report summary 16:00 (10:00 pass).
# Weekends: one post per platform.
WEEKDAY_SLOTS = {1: "08:00", 2: "09:45", 3: "11:00", 4: "15:00", 5: "16:00", 6: "16:30", 7: "19:00", 8: "20:30"}  # 8 = extra feature-promo slot, promo days only
# Weekday passes of run_daily.ps1 (-Pass): which slots each one fills, and when (New York time).
PASSES = {"morning": (1, 2, 3, 6, 7), "reports": (5, 7), "picks": (4,)}
PASS_TIMES = {"morning": "05:00", "reports": "10:00", "picks": "13:45"}
# Preflight window of the 15-minute preflight pass: posts due in 60-90 minutes.
PREFLIGHT_WINDOW_MIN = (60, 90)
# Held posts ("status": "held") go into the live manifest only once the kit that knows the field is on prod:
# the kit before it rejects an unknown field and would drop the whole day. Set True with that release.
HELD_STATUS_LIVE = True  # kit with "held" live on prod since main 786fc27a (2026-09-28)
# The picks slot is filled by a later pass: its Instagram Story is held for it.
RESERVED_IG = {4: "story"}
WEEKEND_SLOTS = {1: "12:00"}
CATEGORIES = (
    "earnings_today", "earnings_week", "insider_trade", "congress_trade", "daily_picks", "earnings_report",
    "congress_week", "congress_30d", "congress_theme", "person_spotlight", "track_record", "insider_week",
    "product_promo",
)
NOT_ADVICE = "Not investment advice."
BANNED = re.compile(r"#insidertrading", re.IGNORECASE)
# A hashtag as X links it: '#' not after a word character, '&' or '#', then word characters with at least one
# letter ("#1" is not a hashtag). Same pattern as growth-video scripts/xtext.py X_HASHTAG.
X_HASHTAG = re.compile(r"(?<![\w&#])#(?=\w*[A-Za-z])\w+")
X_ONE_HASHTAG_FROM = "2026-09-29"
ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
STORY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
TICKER = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")
HANDLE = re.compile(r"^@[A-Za-z0-9._]{1,30}$")
TIME_ET = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# C0 controls except tab / LF, DEL, C1, bidi controls, zero-width and invisible format characters.
CONTROL = re.compile("[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
LIMITS = {"x": 280, "threads": 500, "instagram": 2200, "pinterest_title": 100, "pinterest_description": 500, "alt": 500,
          "title": 200, "story_key": 200, "person": 120, "held_reason": 300}
MAX_POSTS = 8
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
POST_OPTIONAL_KEYS = {"images", "status", "held_reason"}
POST_STATUSES = ("held",)  # absent = ready to post
PLATFORM_OPTIONAL_KEYS = {"media_type"}  # absent = video (manifests written before image posts)


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


def image_url(date: str, story_id: str, fmt: str, ext: str) -> str:
    return f"{PAGES_BASE}/v/{date}/{story_id}/{fmt}.{ext}"


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
        _keys(errors, at, p, POST_KEYS | POST_OPTIONAL_KEYS, POST_KEYS)
        if "status" in p or "held_reason" in p:
            if p.get("status") not in POST_STATUSES:
                errors.append(f"{at}.status: must be held (leave it out for a post that is ready)")
            _text(errors, f"{at}.held_reason", p.get("held_reason"), required=True, limit=LIMITS["held_reason"])
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
            _keys(errors, f"{at}.media", media, set(FORMATS), set())
            if media and set(media) != set(FORMATS):
                errors.append(f"{at}.media: a video post has all of {', '.join(FORMATS)} (an image-only post has {{}})")
            for f in media:
                if sid and f in FORMATS and media.get(f) != media_url(date, sid, f):
                    errors.append(f"{at}.media.{f}: must be {media_url(date, sid, f)}")
        images = p.get("images", {})
        if not isinstance(images, dict):
            errors.append(f"{at}: images must be an object")
            images = {}
        else:
            _keys(errors, f"{at}.images", images, set(IMAGE_FORMATS), set())
            if "images" in p and not images:
                errors.append(f"{at}.images: leave it out when the post has no images")
            for f, u in images.items():
                if sid and f in IMAGE_FORMATS and u not in (image_url(date, sid, f, "png"), image_url(date, sid, f, "jpg")):
                    errors.append(f"{at}.images.{f}: must be {image_url(date, sid, f, 'png')} (or .jpg)")
        if not media and not images:
            errors.append(f"{at}: a post needs its videos (media) or its images")
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
            _keys(errors, pat, block, PLATFORM_KEYS[plat] | PLATFORM_OPTIONAL_KEYS, PLATFORM_KEYS[plat])
            mtype = block.get("media_type", "video")
            if mtype not in MEDIA_TYPES:
                errors.append(f"{pat}.media_type: must be video or image")
                continue
            image = mtype == "image"
            if plat == "instagram":
                placement = block.get("placement")
                if placement not in IG_PLACEMENTS:
                    errors.append(f"{pat}.placement: must be reel, feed or story")
                    continue
                if p.get("category") not in MIX_EXEMPT_CATEGORIES:
                    ig_count[placement] += 1
                if image and placement == "reel":
                    errors.append(f"{pat}.placement: an image post is never a Reel (feed or story)")
                    continue
                want = (IG_IMAGE_MEDIA[placement],) if image else (IG_MEDIA[placement],)
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
                want = IMAGE_PLATFORM_MEDIA["x"] if image else (PLATFORM_MEDIA["x"],)
                _text(errors, f"{pat}.text", block.get("text"), required=True, limit=LIMITS["x"], count=x_weighted_length, needs_advice=True, no_at=True)
                if date >= X_ONE_HASHTAG_FROM and isinstance(block.get("text"), str):
                    tags = X_HASHTAG.findall(block["text"])
                    if len(tags) != 1:
                        errors.append(f"{pat}.text: {len(tags)} hashtags {tags}; the X text carries exactly one (inside the 280)")
                _text(errors, f"{pat}.reply", block.get("reply"), required=False, limit=LIMITS["x"], count=x_weighted_length, no_at=True)
            elif plat == "threads":
                want = IMAGE_PLATFORM_MEDIA["threads"] if image else (PLATFORM_MEDIA["threads"],)
                _text(errors, f"{pat}.text", block.get("text"), required=True, limit=LIMITS["threads"], needs_advice=True)
                _text(errors, f"{pat}.first_reply", block.get("first_reply"), required=False, limit=LIMITS["threads"])
            else:
                want = IMAGE_PLATFORM_MEDIA["pinterest"] if image else (PLATFORM_MEDIA["pinterest"],)
                _text(errors, f"{pat}.title", block.get("title"), required=True, limit=LIMITS["pinterest_title"])
                _text(errors, f"{pat}.description", block.get("description"), required=True, limit=LIMITS["pinterest_description"], needs_advice=True)
                if not _https(block.get("link"), SITE_HOSTS):
                    errors.append(f"{pat}.link: must be an https link on www.rapidtradeview.trade")
            source, name = (images, "images") if image else (media, "media")
            if block.get("media") not in want:
                errors.append(f"{pat}.media: must be {' or '.join(want)} for {'an image' if image else 'a video'}")
            elif block.get("media_url") != source.get(block["media"]):
                errors.append(f"{pat}.media_url: must be the post's {name}.{block['media']}")
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


def expected_type(url: str) -> str:
    ext = url.rsplit(".", 1)[-1].lower()
    return "video/mp4" if ext == "mp4" else IMAGE_EXTS.get(ext, "?")


def check_media_urls(urls: dict[str, Path | None]) -> list[str]:
    """Each URL must answer 200 with its type (video/mp4, image/png, image/jpeg); when a local file is
    given, with its exact size."""
    errors = []
    for url, local in urls.items():
        status, ctype, length = head(url)
        want = expected_type(url)
        if status != 200 or not ctype.lower().startswith(want):
            errors.append(f"{url}: HTTP {status} {ctype or '(no type)'} (want 200 {want})")
        elif local is not None and local.exists() and length is not None and length != local.stat().st_size:
            errors.append(f"{url}: {length} bytes served, local file has {local.stat().st_size} (Pages not deployed yet?)")
    return errors


def manifest_media_urls(m: dict, repo: Path) -> dict[str, Path | None]:
    out: dict[str, Path | None] = {}
    prefix = f"{PAGES_BASE}/"
    for p in m.get("posts", []):
        for url in list((p.get("media") or {}).values()) + list((p.get("images") or {}).values()):
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


def _first(pkg: dict, *paths: tuple[str, ...]) -> str | None:
    """The first non-empty text among post-package paths (the Uber and the category post-packages
    keep some texts in different places)."""
    for path in paths:
        v = _opt(pkg, *path)
        if v:
            return v
    return None


def local_media(repo: Path, date: str, sid: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """(video URLs, image URLs, problems) for the files present in v/<date>/<sid>/."""
    d = repo / "v" / date / sid
    videos = {f: media_url(date, sid, f) for f in FORMATS if (d / f"{f}.mp4").exists()}
    problems = []
    if videos and len(videos) != len(FORMATS):
        problems.append(f"{d}: only {', '.join(videos)} of the three MP4s")
    images: dict[str, str] = {}
    for f in IMAGE_FORMATS:
        found = [e for e in IMAGE_EXTS if (d / f"{f}.{e}").exists()]
        if found:
            # When a renderer ships both, post the JPEG: smaller, and every platform takes it.
            ext = next((e for e in found if e in ("jpg", "jpeg")), found[0])
            images[f] = image_url(date, sid, f, ext)
    return videos, images, problems


def post_media_type(spec: dict, videos: dict, images: dict) -> str:
    if not spec.get("media_type") and not videos and not images:
        raise ValueError(f"{spec['story_id']}: no files in v/<date>/{spec['story_id']}/ yet (a video post needs "
                         f"{', '.join(f + '.mp4' for f in FORMATS)}; an image post PNG or JPEG images)")
    mtype = spec.get("media_type") or ("video" if videos else "image")
    if mtype == "video" and len(videos) != len(FORMATS):
        raise ValueError(f"{spec['story_id']}: a video post needs {', '.join(f + '.mp4' for f in FORMATS)} in v/<date>/{spec['story_id']}/")
    if mtype == "image" and not images:
        raise ValueError(f"{spec['story_id']}: an image post needs PNG or JPEG images ({', '.join(IMAGE_FORMATS)}) in v/<date>/{spec['story_id']}/")
    if mtype not in MEDIA_TYPES:
        raise ValueError(f"{spec['story_id']}: media_type must be video or image")
    return mtype


def _tags(block: object) -> list[dict]:
    out = []
    if isinstance(block, dict):
        for t in block.get("tag_candidates_unverified") or []:
            if isinstance(t, dict) and isinstance(t.get("handle"), str):
                out.append({"handle": t["handle"], "verified": False})
    return out


def assign_instagram(slots: list[int], dtype: str, overrides: dict[int, str | None],
                     reserved: dict[int, str] | None = None, image_slots: set[int] | None = None) -> dict[int, str]:
    """Instagram placements. Weekend: the one post is a Reel. Weekdays (owner: 1 Reel, 2 feed posts,
    2 Stories; Growth lead 2026-09-27): the Reel on the best trade (slot 2), Stories on earnings (1)
    and picks (4), feed posts on the second and third trades (3, 6). A placement whose slot is empty
    moves to the next filled slot in its list (reel 2, 3, 6, 7; story 1, 4, 7, 6; feed 3, 6, 5, 7, 2).
    `reserved` slots (the picks slot, filled by the 13:45 pass) count as filled, so their placement
    is held for them. Spec overrides ("none" = no Instagram post for that slot) and the placements
    of posts already published today win. An image post (`image_slots`) is never the Reel (weekends:
    a feed post)."""
    image_slots = image_slots or set()
    if dtype == "weekend":
        return {s: (overrides.get(s) or ("feed" if s in image_slots else "reel")) for s in slots if overrides.get(s, "reel") != "none"}
    prefs = {"reel": [2, 3, 6, 7], "story": [1, 4, 7, 6], "feed": [3, 6, 5, 7, 2]}
    pool = set(slots) | set(reserved or {})
    out: dict[int, str] = {}
    left = dict(IG_WEEKDAY_MIX)
    for s, placement in overrides.items():
        if s in pool and placement and placement != "none":
            out[s] = placement
            left[placement] -= 1
    blocked = {s for s, v in overrides.items() if v == "none"}
    for placement in ("reel", "story", "feed"):
        for s in prefs[placement]:
            if left[placement] <= 0:
                break
            if s in pool and s not in out and s not in blocked and not (placement == "reel" and s in image_slots):
                out[s] = placement
                left[placement] -= 1
    return {s: p for s, p in out.items() if s in slots}


def build_post(date: str, spec: dict, placement: str | None, repo: Path = REPO) -> dict:
    sid = spec["story_id"]
    pkg_path = Path(spec["post_package"])
    pkg = _load(pkg_path)
    videos, images, problems = local_media(repo, date, sid)
    if problems:
        raise ValueError("; ".join(problems))
    mtype = post_media_type(spec, videos, images)

    def pick(plat: str) -> tuple[str, str]:
        if mtype == "video":
            return PLATFORM_MEDIA[plat], videos[PLATFORM_MEDIA[plat]]
        for f in IMAGE_PLATFORM_MEDIA[plat]:
            if f in images:
                return f, images[f]
        raise ValueError(f"{sid}: no {' or '.join(IMAGE_PLATFORM_MEDIA[plat])} image for {plat}")

    alt = _first(pkg, ("alt_text",), ("instagram", "reel", "alt_text"), ("instagram", "alt_text"))
    if not alt:
        raise ValueError("post-package: missing alt_text")
    platforms: dict[str, dict] = {}
    if placement:
        if mtype == "image":
            if placement not in IG_IMAGE_MEDIA:
                raise ValueError(f"{sid}: an image post is never an Instagram Reel (slot {spec['slot']})")
            ig_fmt = IG_IMAGE_MEDIA[placement]
            if ig_fmt not in images:
                raise ValueError(f"{sid}: the Instagram {placement} needs {ig_fmt}.png or .jpg")
            ig_url = images[ig_fmt]
        else:
            ig_fmt = IG_MEDIA[placement]
            ig_url = videos[ig_fmt]
        if placement == "story":
            sticker = _first(pkg, ("instagram", "story", "link_sticker", "url"), ("instagram", "story_link_sticker"))
            platforms["instagram"] = {"placement": "story", "media_type": mtype, "media": ig_fmt, "media_url": ig_url, "caption": None,
                                      "first_comment": None, "link_sticker_url": sticker, "alt_text": alt}
        else:
            caption_paths = [("instagram", "feed", "caption"), ("instagram", "caption"), ("instagram", "reel", "caption")] if placement == "feed" \
                else [("instagram", "reel", "caption"), ("instagram", "caption")]
            caption = _first(pkg, *caption_paths)
            if not caption:
                raise ValueError(f"post-package: missing the Instagram {placement} caption")
            src = "feed" if placement == "feed" and _opt(pkg, "instagram", "feed", "caption") else "reel"
            platforms["instagram"] = {"placement": placement, "media_type": mtype, "media": ig_fmt, "media_url": ig_url,
                                      "caption": caption,
                                      "first_comment": _first(pkg, ("instagram", src, "first_comment"), ("instagram", "first_comment")),
                                      "link_sticker_url": None,
                                      "alt_text": _opt(pkg, "instagram", src, "alt_text") or alt}
    fx, ux = pick("x")
    ft, ut = pick("threads")
    fp, up = pick("pinterest")
    platforms["x"] = {"media_type": mtype, "media": fx, "media_url": ux, "text": _req(pkg, "x", "post"), "reply": _opt(pkg, "x", "reply")}
    platforms["threads"] = {"media_type": mtype, "media": ft, "media_url": ut, "text": _req(pkg, "threads", "post"),
                            "first_reply": _opt(pkg, "threads", "first_reply")}
    platforms["pinterest"] = {"media_type": mtype, "media": fp, "media_url": up,
                              "title": _req(pkg, "pinterest", "title"), "description": _req(pkg, "pinterest", "description"),
                              "link": _req(pkg, "pinterest", "link")}
    tags = {}
    if "instagram" in platforms and _tags(pkg.get("instagram")):
        tags["instagram"] = _tags(pkg.get("instagram"))
    if _tags(pkg.get("threads")):
        tags["threads"] = _tags(pkg.get("threads"))
    src_urls = pkg.get("source_urls") if isinstance(pkg.get("source_urls"), list) else []
    post = {
        "slot": spec["slot"],
        "time_et": spec["time_et"],
        "category": spec["category"],
        "id": f"video-{date}-{sid}",
        "story_id": sid,
        "story_key": spec["story_key"],
        "title": spec.get("title") or _req(pkg, "pinterest", "title"),
        "tickers": list(spec.get("tickers") or []),
        "people": list(spec.get("people") or []),
        "media": videos,
        "alt_text": alt,
        "source_urls": list(src_urls)[:10],
        "tag_candidates": tags,
        "platforms": platforms,
    }
    if images:
        post["images"] = images
    return post


def build_manifest(spec: dict, existing: dict | None = None, now: dt.datetime | None = None, repo: Path = REPO) -> dict:
    date = spec["date"]
    dtype = day_type(date)
    kept = []
    if existing:
        named = {p["slot"] for p in spec["posts"]}
        kept = [p for p in existing.get("posts", []) if p.get("slot") not in named]
    # Promos sit outside the mix: they take their own placement (default a Reel) and never shift the others'.
    extra = {p["slot"]: p.get("instagram_placement") or "reel" for p in spec["posts"] if p["category"] in MIX_EXEMPT_CATEGORIES}
    mixed = [p for p in spec["posts"] if p["slot"] not in extra]
    kept_mixed = [p for p in kept if p.get("category") not in MIX_EXEMPT_CATEGORIES]
    slots = sorted([p["slot"] for p in mixed] + [p["slot"] for p in kept_mixed])
    overrides = {p["slot"]: p.get("instagram_placement") for p in mixed if "instagram_placement" in p}
    # Kept posts keep their Instagram placement; the new ones fill what is left of the mix.
    for p in kept_mixed:
        overrides[p["slot"]] = (p.get("platforms", {}).get("instagram") or {}).get("placement") or "none"
    image_slots = set()
    for p in mixed:
        videos, images, _ = local_media(repo, date, p["story_id"])
        if (p.get("media_type") or ("video" if len(videos) == len(FORMATS) else "image")) == "image":
            image_slots.add(p["slot"])
    placements = assign_instagram(slots, dtype, overrides, RESERVED_IG if dtype == "weekday" else None, image_slots)
    placements.update({s: v for s, v in extra.items() if v != "none"})
    new_posts = [build_post(date, p, placements.get(p["slot"]), repo) for p in spec["posts"]]
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
    missing, _ = spec_files(repo, spec)
    if missing:
        return _fail(missing)
    path = repo / "v" / date / "manifest.json"
    existing = _load(path) if a.merge and path.exists() else None
    if a.replace_slot:
        if not existing:
            return _fail(["--replace-slot needs --merge and an existing manifest"])
        have = {p.get("slot"): p for p in existing.get("posts", [])}
        named = {p["slot"] for p in spec["posts"]}
        bad = [f"--replace-slot {n}: slot {n} is not in the published manifest" for n in a.replace_slot if n not in have]
        bad += [f"--replace-slot {n}: slot {n} is not in the spec" for n in a.replace_slot if n not in named]
        bad += [f"slot {n} is already published ({have[n].get('story_id')}); name it with --replace-slot {n} to replace it"
                for n in sorted(named & set(have)) if n not in a.replace_slot]
        if bad:
            return _fail(bad)
        for n in a.replace_slot:
            print(f"replacing slot {n}: {have[n].get('id')} (explicit --replace-slot)")
    try:
        m = build_manifest(spec, existing, repo=repo)
    except (ValueError, KeyError) as e:
        return _fail([str(e)])
    errors = validate_manifest(m, date)
    if not errors and a.check_urls:
        errors = check_media_urls(manifest_media_urls(m, repo))
    if errors:
        return _fail(errors)
    if path.exists():
        before = _load(path)
        if {k: v for k, v in before.items() if k != "generated_at"} == {k: v for k, v in m.items() if k != "generated_at"}:
            print(f"unchanged: {path} ({len(m['posts'])} posts)")
            return 0
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
    print(f"valid: {a.date} ({len(m['posts'])} posts){' + media URLs 200 with their types' if a.check_urls else ''}")
    return 0


def evidence_files(repo: Path, date: str, sid: str, pkg_path: Path) -> tuple[list[str], list[Path]]:
    """(problems, local files) of the evidence snapshot a post-package cites (growth-video scripts/v6cat/evidence.py):
    v/<date>/<sid>/evidence/<name> for every name of pkg['evidence']['files']; none cited -> nothing to stage."""
    try:
        ev = _load(pkg_path).get("evidence") or {}
    except (OSError, ValueError):
        return [], []
    names = ev.get("files") or []
    base = f"{PAGES_BASE}/v/{date}/{sid}/evidence/"
    if names and not str(ev.get("index_url", "")).startswith(base):
        return [f"post-package evidence index {ev.get('index_url')} is not under {base}"], []
    d = repo / "v" / date / sid / "evidence"
    missing = [n for n in names if not (d / n).exists()]
    return ([f"evidence file v/{date}/{sid}/evidence/{n} not staged" for n in missing], [d / n for n in names if (d / n).exists()])


def spec_files(repo: Path, spec: dict) -> tuple[list[str], dict[str, Path]]:
    """(problems, {url: local file}) for every post of a spec: its post-package and the files of its
    media type in v/<date>/<story_id>/."""
    date = spec["date"]
    problems: list[str] = []
    files: dict[str, Path] = {}
    for p in spec.get("posts", []):
        label = f"slot {p.get('slot')} {p.get('story_id')}"
        if not Path(p.get("post_package", "")).exists():
            problems.append(f"{label}: post-package {p.get('post_package')} missing")
        videos, images, local_problems = local_media(repo, date, p["story_id"])
        problems.extend(f"{label}: {x}" for x in local_problems)
        try:
            post_media_type(p, videos, images)
        except ValueError as e:
            problems.append(f"{label}: {e}")
        for url in list(videos.values()) + list(images.values()):
            files[url] = repo / url[len(PAGES_BASE) + 1:]
    return problems, files


def cmd_preflight(a: argparse.Namespace) -> int:
    import preflight as pf

    repo, date = Path(a.repo), a.date
    work = Path(a.work) if a.work else pf.WORK_ROOT / date
    path = Path(a.manifest) if a.manifest else repo / "v" / date / "manifest.json"
    if not path.exists():
        print(f"nothing to check: no manifest {path}")
        return 2
    m = _load(path)
    now = dt.datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else dt.datetime.now(dt.timezone.utc)
    slots = None
    if a.slots:
        slots = {int(x) for x in a.slots.split(",") if x.strip()}
    elif a.due_within_min is not None:
        lo, hi = a.due_after_min * 60, a.due_within_min * 60
        slots = {p["slot"] for p in m.get("posts", []) if lo <= (pf.post_time(date, p["time_et"]) - now).total_seconds() <= hi}
        if not slots:
            print(f"nothing due in {a.due_after_min}-{a.due_within_min} min")
            return 2
    reports = pf.preflight(m, date, repo, work, slots, a.local_only, Path(a.media_dir) if a.media_dir else None, now)
    for r in reports:
        write_json(work / f"preflight-{r['slot']}.json", r)
        print(f"slot {r['slot']} {r['time_et']} {r['story_id']}: {r['result'].upper()} "
              f"({r['minutes_before_post']} min before the post; {r['checks']['numbers_checked']} numbers "
              f"({len(r['checks']['numbers_derived'])} derived), "
              f"{r['checks']['dates_checked']} dates checked)")
        for f in r["failures"]:
            print(f"  FAIL {f}")
        for d in r["checks"]["numbers_derived"]:
            print(f"  derived {d}")
        for w in r["warnings"]:
            print(f"  warn {w}")
    failed = [r for r in reports if r["result"] == "fail"]
    if a.hold and failed:
        if a.manifest is None and not HELD_STATUS_LIVE:
            print("HOLD NOT WRITTEN: the kit on prod does not accept \"status\" yet (HELD_STATUS_LIVE = False); "
                  "the failing posts stay as they are: pull them by hand.")
        else:
            changed = []
            for post in m["posts"]:
                r = next((x for x in failed if x["slot"] == post["slot"]), None)
                if r and post.get("status") != "held":
                    post["status"] = "held"
                    post["held_reason"] = pf.held_reason(r)
                    changed.append(post["slot"])
            if changed:
                errors = validate_manifest(m, date)
                if errors:
                    return _fail(errors)
                write_json(path, m)
                print(f"HELD slots {', '.join(map(str, changed))} in {path} (status held; nothing deleted)")
    return 1 if failed else 0


def cmd_check_spec(a: argparse.Namespace) -> int:
    repo = Path(a.repo)
    spec = _load(Path(a.spec))
    problems, files = spec_files(repo, spec)
    evidence: list[Path] = []
    for p in spec.get("posts", []):
        ev_problems, ev_files = evidence_files(repo, spec["date"], p["story_id"], Path(p.get("post_package", "")))
        problems += [f"slot {p.get('slot')} {p.get('story_id')}: {x}" for x in ev_problems]
        evidence += ev_files
    if problems:
        return _fail(problems)
    if a.list_out:
        rel = sorted(str(f.relative_to(repo)).replace("\\", "/") for f in list(files.values()) + evidence)
        with open(a.list_out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(rel) + "\n")
    print(f"ready: {len(files)} files")
    return 0


def cmd_wait_urls(a: argparse.Namespace) -> int:
    repo = Path(a.repo)
    spec = _load(Path(a.spec))
    problems, urls = spec_files(repo, spec)
    if problems:
        return _fail(problems)
    deadline = time.monotonic() + a.timeout
    while True:
        errors = check_media_urls(urls)
        if not errors:
            print(f"all {len(urls)} media URLs answer 200 with their type and the local sizes")
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
    w.add_argument("--replace-slot", type=int, action="append", default=[], help="replace this already-published slot (with --merge)")
    w.add_argument("--check-urls", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("--date", required=True)
    v.add_argument("--check-urls", action="store_true")
    v.add_argument("--remote", action="store_true")
    v.add_argument("--same-as-local", action="store_true")
    u = sub.add_parser("wait-urls")
    u.add_argument("--spec", required=True)
    u.add_argument("--timeout", type=int, default=900)
    f = sub.add_parser("preflight")
    f.add_argument("--date", required=True)
    f.add_argument("--slots")
    f.add_argument("--slot", dest="slots")
    f.add_argument("--due-within-min", type=int)
    f.add_argument("--due-after-min", type=int, default=0)
    f.add_argument("--manifest")
    f.add_argument("--work")
    f.add_argument("--local-only", action="store_true")
    f.add_argument("--media-dir")
    f.add_argument("--hold", action="store_true")
    f.add_argument("--now")
    c = sub.add_parser("check-spec")
    c.add_argument("--spec", required=True)
    c.add_argument("--list-out")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    return {"write": cmd_write, "validate": cmd_validate, "wait-urls": cmd_wait_urls, "check-spec": cmd_check_spec,
            "preflight": cmd_preflight}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
