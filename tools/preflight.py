"""Preflight gate for the day's posts (owner rule 2026-09-28: every post ready one hour before it goes live).

Run through `manifest.py preflight` (see there for the CLI). For each post it re-checks:
  - the manifest rules (manifest.validate_manifest) and every media file: 200 with its type and the same
    sha256 as the local copy in the repo (a cache keyed by ETag + size skips re-downloading a file already
    verified; --local-only checks the local files of a staged plan instead);
  (a) source_urls are date-pinned: a date-relative URL (weeks_ahead=N or days=N without a recorded
      week_start / since / as_of / date, a today / tomorrow / latest / this-week path, /tips/daily without a
      date, the newest-first /notable/feed) fails unless the post also cites a pinned URL on the same host;
  (b) claims lint: phrases that overstate certainty fail ("confirmed dates only", "guaranteed", "always",
      "beat the market", "insider trading", "risk-free", ...); an earnings calendar post must say where its
      dates come from on every platform (third-party calendar / company-confirmed / investor relations);
  (c) every number in the texts appears in the post's data (data.json of the story; the post-package's
      data_file; never the post-package's own texts), allowing the text's rounding and K / M / B / % units;
      a number that is the EXACT sum or difference of two numeric fields of the data of the same kind
      (two share counts, held after - bought, two value_usd ...) passes as "derived", with its formula in
      the report; a data.json may also list derived figures itself ({"derived_numbers": [{"value":
      15000, "formula": "..."}]}), which count as plain data;
  (d) freshness: every date written in the texts is a date the data holds; the data's age is reported.
A report per slot goes to D:/rtv-ops/tracks/growth/research/daily-video/<date>/preflight-<slot>.json.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.request
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import manifest as mf

WORK_ROOT = Path("D:/rtv-ops/tracks/growth/research/daily-video")
CATEGORIES_OUT = Path("D:/rtv-ops/tracks/growth/research/video-v6/categories")
NY = ZoneInfo("America/New_York")
UA = "RapidTradeView preflight (contact@rapidtradeview.trade)"

# (a) date-relative sources ------------------------------------------------------------------------
RELATIVE_PARAMS = {"weeks_ahead", "days"}
PINNING_PARAMS = {"week_start", "since", "as_of", "date", "from", "to"}
RELATIVE_SEGMENTS = {"today", "tomorrow", "yesterday", "latest", "this-week", "next-week"}
RELATIVE_VALUES = {"today", "tomorrow", "yesterday", "latest", "now"}
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def relative_reason(url: str) -> str | None:
    """Why a source URL means something else on another day, or None when it is pinned."""
    u = urlsplit(url)
    q = parse_qs(u.query)
    pinned = any(k in q and any(ISO_DATE.fullmatch(v) for v in q[k]) for k in PINNING_PARAMS)
    for k in RELATIVE_PARAMS:
        if k in q and not pinned:
            return f"{k}={q[k][0]} with no recorded week_start / since / as_of"
    for k, vals in q.items():
        if any(v.lower() in RELATIVE_VALUES for v in vals):
            return f"{k}={vals[0]}"
    segs = [s.lower() for s in u.path.split("/") if s]
    bad = [s for s in segs if s in RELATIVE_SEGMENTS]
    if bad:
        return f"'/{bad[0]}' in the path"
    if u.path.rstrip("/").endswith("/tips/daily"):
        return "/tips/daily has no date (use /tips/daily/<date>)"
    if u.path.rstrip("/").endswith("/notable/feed"):
        return "/notable/feed is the newest-first feed (cite the filings)"
    return None


def source_failures(urls: list[str]) -> list[str]:
    pinned_hosts = {urlsplit(u).netloc for u in urls if relative_reason(u) is None}
    # A post whose FIRST source is its published evidence snapshot (v/<date>/<id>/evidence/index.json: the exact
    # API responses with request URL, fetch time and sha256) is pinned; the live pages after it are for readers.
    if urls and urls[0].startswith(f"{mf.PAGES_BASE}/v/") and "/evidence/" in urls[0]:
        return []
    out = []
    for u in urls:
        why = relative_reason(u)
        if why and urlsplit(u).netloc not in pinned_hosts:
            out.append(f"(a) source {u} is date-relative ({why}) and the post cites no pinned {urlsplit(u).netloc} URL")
    return out


# (b) claims lint ------------------------------------------------------------------------------------
OVERSTATEMENTS = [
    (re.compile(r"\bconfirmed dates only\b|\bonly confirmed dates\b|\ball dates (are )?confirmed\b", re.I), "overstates how many dates are confirmed"),
    (re.compile(r"\bguarantee[ds]?\b", re.I), "certainty claim"),
    (re.compile(r"\balways\b", re.I), "certainty claim"),
    (re.compile(r"\bbeat(s|ing)? the market\b", re.I), "performance claim"),
    (re.compile(r"\binsider[\s-]*trading\b", re.I), "reads as an accusation (say insider buying / Form 4 filing)"),
    (re.compile(r"\brisk[\s-]*free\b|\bcan'?t lose\b|\bsure thing\b|\bno[\s-]brainer\b", re.I), "certainty claim"),
    (re.compile(r"\b100\s?% (accurate|certain|sure)\b", re.I), "certainty claim"),
]
DATE_SOURCE = re.compile(r"third[\s-]party|earnings calendar|company[\s-]confirmed|confirmed by (the )?compan|"
                         r"investor relations|\bIR\b|press release|compan(y|ies)'?s? (own )?(announced|confirmed)", re.I)
EARNINGS_CALENDAR = {"earnings_today", "earnings_week"}


def post_texts(post: dict) -> dict[str, list[tuple[str, str]]]:
    """Texts per platform (label, text); 'post' holds the title and alt text."""
    p = post.get("platforms", {})
    out: dict[str, list[tuple[str, str]]] = {"post": [("title", post.get("title") or ""), ("alt_text", post.get("alt_text") or "")]}
    ig = p.get("instagram")
    if ig:
        out["instagram"] = [(k, ig.get(k) or "") for k in ("caption", "first_comment", "alt_text")]
    if "x" in p:
        out["x"] = [(k, p["x"].get(k) or "") for k in ("text", "reply")]
    if "threads" in p:
        out["threads"] = [(k, p["threads"].get(k) or "") for k in ("text", "first_reply")]
    if "pinterest" in p:
        out["pinterest"] = [(k, p["pinterest"].get(k) or "") for k in ("title", "description")]
    return out


def claims_failures(post: dict) -> list[str]:
    out = []
    texts = post_texts(post)
    for plat, items in texts.items():
        for label, text in items:
            for rx, why in OVERSTATEMENTS:
                m = rx.search(text)
                if m:
                    out.append(f"(b) {plat}.{label}: \"{m.group(0)}\": {why}")
    if post.get("category") in EARNINGS_CALENDAR:
        for plat in ("instagram", "x", "threads", "pinterest"):
            items = texts.get(plat)
            if not items or all(not t for _, t in items):
                continue  # no text on this platform (an Instagram Story)
            if not any(DATE_SOURCE.search(t) for _, t in items):
                out.append(f"(b) {plat}: an earnings post must say where its dates come from (third-party calendar / company-confirmed)")
    return out


# (c) numbers and (d) dates ----------------------------------------------------------------------------
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_RX = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
NAMED_DATE = re.compile(rf"\b({MONTH_RX})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?")
ISO_DATE_RX = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
TIME_RX = re.compile(r"\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b", re.I)
URL_RX = re.compile(r"https?://\S+|www\.\S+|\b[\w-]+\.(?:trade|com|gov|org)\S*")
NUM_RX = re.compile(r"(?<![\w.,])[$]?([+\-\u2212]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(%|bn\b|billion\b|million\b|thousand\b|[KMBT](?![\w]))?", re.I)
SCALE = {"k": Decimal(1e3), "thousand": Decimal(1e3), "m": Decimal(1e6), "million": Decimal(1e6), "b": Decimal(1e9),
         "bn": Decimal(1e9), "billion": Decimal(1e9), "t": Decimal(1e12)}


def _dates_in(text: str, year: int) -> set[str]:
    out = set()
    for m in NAMED_DATE.finditer(text):
        mon = MONTHS[m.group(1)[:3].lower()]
        try:
            out.add(dt.date(int(m.group(3) or year), mon, int(m.group(2))).isoformat())
        except ValueError:
            pass
    for m in ISO_DATE_RX.finditer(text):
        out.add(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    for m in SLASH_DATE.finditer(text):
        try:
            out.add(dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat())
        except ValueError:
            pass
    return out


# Document names and aspect ratios carry digits that are not figures.
NOT_FIGURES = re.compile(r"\bForm\s+4s?\b|\b10b5-1\b|\b10-[KQ]\b|\b8-K\b|\bExhibit\s+99(?:\.\d)?\b|\bS&P\s*500\b|"
                         r"\b\d{1,2}:\d{1,2}\b|\b24/7\b", re.I)


def _strip(text: str) -> str:
    text = URL_RX.sub(" ", text)
    text = NOT_FIGURES.sub(" ", text)
    text = NAMED_DATE.sub(" ", text)
    text = ISO_DATE_RX.sub(" ", text)
    text = SLASH_DATE.sub(" ", text)
    return TIME_RX.sub(" ", text)


def _numbers(text: str) -> list[tuple[str, Decimal, int, str]]:
    """(token, value, decimals, unit) for each number in a text (URLs, dates and times removed)."""
    out = []
    for m in NUM_RX.finditer(_strip(text)):
        digits = m.group(2).replace(",", "") + (m.group(3) or "")
        try:
            v = Decimal(digits)
        except InvalidOperation:
            continue
        out.append((m.group(0).strip(), v, len(m.group(3) or "") - (1 if m.group(3) else 0), (m.group(4) or "").lower()))
    return out


def _walk(obj, strings: list[str], numbers: list[Decimal]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _walk(v, strings, numbers)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, strings, numbers)
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, (int, float)):
        try:
            numbers.append(Decimal(str(obj)))
        except InvalidOperation:
            pass
    elif isinstance(obj, str):
        strings.append(obj)


# Keys that name a container, not a quantity: a leaf under them takes the nearest meaningful key above.
GENERIC_KEYS = {"value", "raw", "display", "text", "evidence", "source_text", "decimal"}
# Share counts are one kind (held before = held after - bought; two purchases add up).
SHARE_KEYS = {"shares", "holdings_after", "held_after", "held_before", "holdings_before", "bought", "shares_bought",
              "shares_owned", "shares_owned_following_transaction"}
NUMERIC_STRING = re.compile(r"[+-]?\d+(\.\d+)?")


def _leaves(obj, path: str = "", key: str | None = None, out: list | None = None) -> list[tuple[str, str, Decimal]]:
    """(path, kind, value) of every numeric field (a JSON number, or a string that is only a number)."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            _leaves(v, f"{path}.{k}", key if k.lower() in GENERIC_KEYS else k.lower(), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _leaves(v, f"{path}[{i}]", key, out)
    elif isinstance(obj, bool) or obj is None:
        pass
    elif isinstance(obj, (int, float)) or (isinstance(obj, str) and NUMERIC_STRING.fullmatch(obj.strip())):
        try:
            v = Decimal(str(obj).strip())
        except InvalidOperation:
            return out
        if key and v != 0:
            out.append((path, "shares" if key in SHARE_KEYS else key, v))
    return out


class DataFacts:
    """Every number and date the post's data holds (numbers as written and scaled by their units)."""

    def __init__(self, docs: list[object], year: int):
        strings: list[str] = []
        numbers: list[Decimal] = []
        self.kinds: dict[str, list[tuple[str, Decimal]]] = {}
        for i, d in enumerate(docs):
            _walk(d, strings, numbers)
            for path, kind, v in _leaves(d, f"doc{i}"):
                self.kinds.setdefault(kind, []).append((path, v))
        self.values: set[Decimal] = {abs(n) for n in numbers}
        self.dates: set[str] = set()
        for s in strings:
            self.dates |= _dates_in(s, year)
            for _, v, _, unit in _numbers(s):
                self.values.add(v)
                if unit in SCALE:
                    self.values.add(v * SCALE[unit])
        self.sorted = sorted(self.values)

    def has_number(self, v: Decimal, decimals: int, unit: str) -> bool:
        q = Decimal(1).scaleb(-decimals) if decimals > 0 else Decimal(1)
        cands = [v]
        for x in self.sorted:
            if unit in SCALE:
                ys = [x / SCALE[unit], x]
            elif unit == "%":
                ys = [x, x * 100]
            else:
                ys = [x]
            for y in ys:
                try:
                    if any(y.quantize(q, rounding=r) == c for r in (ROUND_HALF_UP, ROUND_HALF_EVEN) for c in cands):
                        return True
                except InvalidOperation:
                    continue
        return False


    def derived(self, v: Decimal) -> str | None:
        """How v is the exact sum or difference of two numeric fields of one kind, or None."""
        for kind, leaves in self.kinds.items():
            by_value: dict[Decimal, list[str]] = {}
            for path, x in leaves:
                by_value.setdefault(x, []).append(path)
            for path, x in leaves:
                for other, sign in ((v - x, "+"), (x - v, "-")):
                    partners = [q for q in by_value.get(other, []) if q != path]
                    if partners and other > 0:
                        return f"{x} {sign} {other} = {v} ({kind}: {path} {sign} {partners[0]})"
        return None


def number_failures(post: dict, facts: DataFacts, derived: list[str] | None = None) -> tuple[list[str], int]:
    out, checked = [], 0
    seen = set()
    for plat, items in post_texts(post).items():
        for label, text in items:
            for token, v, dec, unit in _numbers(text):
                checked += 1
                key = (v, dec, unit)
                if key in seen:
                    continue
                seen.add(key)
                if facts.has_number(v, dec, unit):
                    continue
                how = facts.derived(v) if not unit else None
                if how:
                    if derived is not None:
                        derived.append(f"\"{token}\" ({plat}.{label}): {how}")
                    continue
                out.append(f"(c) {plat}.{label}: the number \"{token}\" is not in the post's data (nor an exact sum or difference of two of its fields)")
    return out, checked


def date_failures(post: dict, facts: DataFacts, year: int) -> tuple[list[str], int]:
    out, found = [], set()
    for plat, items in post_texts(post).items():
        for label, text in items:
            for d in _dates_in(text, year):
                found.add(d)
                if d not in facts.dates:
                    out.append(f"(d) {plat}.{label}: the date {d} is not a date the data holds (stale or wrong story?)")
    return sorted(set(out)), len(found)


# data lookup ----------------------------------------------------------------------------------------------

def find_data(post: dict, date: str, work: Path) -> tuple[list[Path], list[str]]:
    """The post's data files: the selector's data.json, the post-package's data_file (or the category's
    data.json). Never the post-package itself (its texts are what is being checked)."""
    sid = post["story_id"]
    notes: list[str] = []
    pkgs: list[Path] = []
    if (work / sid / "post-package.json").exists():
        pkgs.append(work / sid / "post-package.json")
    for spec in sorted(work.glob("spec*.json")):
        try:
            for p in json.loads(spec.read_text(encoding="utf-8-sig")).get("posts", []):
                if p.get("story_id") == sid and p.get("post_package"):
                    pkgs.append(Path(p["post_package"]))
        except (OSError, ValueError):
            continue
    files: list[Path] = []
    if (work / sid / "data.json").exists():
        files.append(work / sid / "data.json")
    for pkg in pkgs:
        try:
            df = json.loads(pkg.read_text(encoding="utf-8-sig")).get("data_file")
        except (OSError, ValueError):
            continue
        if df and Path(df).exists():
            files.append(Path(df))
    if (CATEGORIES_OUT / sid / "data.json").exists():
        files.append(CATEGORIES_OUT / sid / "data.json")
    uniq = list(dict.fromkeys(files))
    if not uniq:
        notes.append(f"no data.json found for {sid} (looked in {work / sid}, the spec post-packages' data_file, {CATEGORIES_OUT / sid})")
    return uniq, notes


def data_age_hours(files: list[Path], post_time: dt.datetime) -> float | None:
    stamps = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        for k in ("generated_at_utc", "generated_at", "verified_at_utc", "as_of"):
            v = d.get(k) if isinstance(d, dict) else None
            if isinstance(v, str):
                try:
                    stamps.append(dt.datetime.fromisoformat(v.replace("Z", "+00:00")))
                except ValueError:
                    pass
    stamps = [s if s.tzinfo else s.replace(tzinfo=dt.timezone.utc) for s in stamps]
    return round((post_time - max(stamps)).total_seconds() / 3600, 1) if stamps else None


# media ----------------------------------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def remote_check(url: str, local: Path, cache: dict) -> str | None:
    """None when the URL answers 200 with its type and the local file's sha256, else why not."""
    if not local.exists():
        return f"no local copy {local} to compare with"
    want_type = mf.expected_type(url)
    local_sha = sha256_file(local)
    status, ctype, length = mf.head(url)
    if status != 200 or not ctype.lower().startswith(want_type):
        return f"HTTP {status} {ctype or '(no type)'} (want 200 {want_type})"
    etag = None
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            etag = r.headers.get("ETag")
    except (urllib.error.URLError, OSError):
        pass
    hit = cache.get(url)
    if hit and etag and hit.get("etag") == etag and hit.get("length") == length and hit.get("sha256") == local_sha:
        return None
    h = hashlib.sha256()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=120) as r:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                h.update(chunk)
    except (urllib.error.URLError, OSError) as e:
        return f"download failed ({type(e).__name__})"
    if h.hexdigest() != local_sha:
        return f"served file differs from the local copy (sha256 {h.hexdigest()[:12]} vs {local_sha[:12]})"
    cache[url] = {"etag": etag, "length": length, "sha256": local_sha}
    return None


def media_urls(post: dict) -> list[str]:
    return list((post.get("media") or {}).values()) + list((post.get("images") or {}).values())


# the gate --------------------------------------------------------------------------------------------------

def post_time(date: str, hhmm: str) -> dt.datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    d = dt.date.fromisoformat(date)
    return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=NY)


def preflight(m: dict, date: str, repo: Path, work: Path, slots: set[int] | None, local_only: bool,
              media_dir: Path | None, now: dt.datetime) -> list[dict]:
    """One report per checked post."""
    year = int(date[:4])
    base_errors = mf.validate_manifest(m, date)
    cache_path = work / "preflight-cache.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    except ValueError:
        cache = {}
    reports = []
    for i, post in enumerate(m.get("posts", [])):
        if slots is not None and post.get("slot") not in slots:
            continue
        failures: list[str] = []
        warnings: list[str] = []
        failures += [f"manifest: {e}" for e in base_errors if e.startswith(f"posts[{i}]") or e.startswith("manifest:")]
        media = {}
        for url in media_urls(post):
            rel = url[len(mf.PAGES_BASE) + 1:]
            if local_only:
                local = (media_dir / Path(rel).relative_to(f"v/{date}")) if media_dir else repo / rel
                ok = local.exists() and local.stat().st_size > 0
                media[url] = "local file present (not published yet)" if ok else f"missing locally: {local}"
                if not ok:
                    failures.append(f"media: {url}: missing locally ({local})")
            else:
                why = remote_check(url, repo / rel, cache)
                media[url] = "200, type and sha256 match the local copy" if why is None else why
                if why:
                    failures.append(f"media: {url}: {why}")
        failures += source_failures(list(post.get("source_urls") or []))
        failures += claims_failures(post)
        files, notes = find_data(post, date, work)
        docs = []
        for f in files:
            try:
                docs.append(json.loads(f.read_text(encoding="utf-8-sig")))
            except (OSError, ValueError) as e:
                notes.append(f"{f}: unreadable ({type(e).__name__})")
        n_checked = d_checked = 0
        derived: list[str] = []
        if docs:
            facts = DataFacts(docs, year)
            nf, n_checked = number_failures(post, facts, derived)
            df, d_checked = date_failures(post, facts, year)
            failures += nf + df
        else:
            failures += [f"(c)/(d) {n}" for n in notes]
        when = post_time(date, post["time_et"])
        age = data_age_hours(files, when)
        if age is not None and age > 24:
            warnings.append(f"data built {age} h before the post time")
        minutes_left = round((when - now).total_seconds() / 60)
        if post.get("status") == "held":
            warnings.append(f"already held: {post.get('held_reason')}")
        reports.append({
            "date": date, "slot": post.get("slot"), "time_et": post.get("time_et"), "id": post.get("id"),
            "story_id": post.get("story_id"), "category": post.get("category"),
            "checked_at": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "minutes_before_post": minutes_left, "result": "fail" if failures else "pass",
            "failures": failures, "warnings": warnings + (notes if docs else []),
            "checks": {"media": media, "source_urls": post.get("source_urls"), "data_files": [str(f) for f in files],
                       "numbers_checked": n_checked, "numbers_derived": derived, "dates_checked": d_checked,
                       "data_age_hours": age},
            "status_in_manifest": post.get("status", "ready"),
        })
    work.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cache, fh, indent=1)
    return reports


def held_reason(report: dict) -> str:
    text = "Preflight " + report["checked_at"] + ": " + "; ".join(report["failures"][:3])
    if len(report["failures"]) > 3:
        text += f"; +{len(report['failures']) - 3} more"
    text = mf.CONTROL.sub("", text)
    return text if len(text) <= mf.LIMITS["held_reason"] else text[: mf.LIMITS["held_reason"] - 3] + "..."
