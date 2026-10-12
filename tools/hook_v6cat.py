"""run_daily.ps1 render hook for the v6 category videos and the earnings still images (D:/rtvw/growth-video/README-v6-daily.md).

Usage (conda python):
  hook_v6cat.py --data DATA.json --out DIR [--dry-run] [--use-existing ID]
      Maps the selected story (data.json, schema rtv-daily-story/1) to the growth-video category tools, checks
      their QA passed, then copies the media and post-package.json into DIR, where daily.py stage picks them up.
      A video also gets its still (frame 0 + brand footer, growth-video scripts/v6_still.py): DIR/still/feed_4x5.jpg + .png,
      for platforms where a video upload fails (Threads web).
      --use-existing reuses an already rendered categories/<ID>/ instead of rendering. Exit 0 = DIR holds
      QA-passed media; anything else = the story is skipped (the reason is printed).

Wired categories:
  daily_picks      make.py daily-picks --id <story_id> --date <story.trade_date>                 (video)
  earnings_report  make.py report-summary --id <story_id> --report <story.report_id>            (video)
  congress_theme   make.py congress-theme --id <story_id> --days <story.days>                   (video; Big Tech split)
  earnings_today   earnings_image.py day --date <date> -> render-stills -> post -> qa_stills     (still images,
                   weekday slot 1)
  earnings_week    earnings_image.py week --weeks-ahead 0 (Monday: this week) / 1 (Saturday: next week), same
                   steps (still images). The Tue-Fri "rest of the week" fallback has no image variant: skipped.
  Instagram is Reels only from manifest.IG_REELS_ONLY_FROM (Growth decision 2026-10-10): an image story then also runs
  growth-video scripts/v6cat/still_reel.py --id <story_id> (a 9:16 Reel of ~9 s built from the story's own approved image:
  push-in, VSCO bed, standard end card; its QA must pass) and this hook copies reel_9x16.mp4, still/reel_9x16.jpg + .png and
  vsco-instruments.json too, and writes the Reel's music provenance into the work copy of post-package.json ("music"; the
  manifest and music.json carry it). A story whose Reel fails is skipped: no feed-image fallback.
  Picks Reel fallback (owner/HQ rule 2026-10-12: when the picks Reel fails its quality gate, ship a simpler still-based Reel that
  day; never skip the slot). From manifest.IG_REELS_ONLY_FROM, when the daily_picks video fails (make.py exits != 0, or qa.json
  did not pass), the hook builds the picks STILL (frame 0 of the QA'd feed_4x5 video + brand footer) and its own Still -> Reel
  (growth-video scripts/v6cat/picks_still_reel.py: v6_still.py -> qa_picks_still.py -> still_reel.py; every gate must pass) and
  copies THAT as an image story with its Reel: feed_4x5.png + .jpg (X, Threads, Pinterest), reel_9x16.mp4 = the still Reel
  (Instagram), its still and music provenance, and DIR/fallback.json ({"fallback": "still_reel", "reason": the failed gates}).
  The still needs a feed_4x5 video whose QA passed in this run: when the run stopped before QA (e.g. the Reel's render crashed)
  and its data and score were made in this run, the feed_4x5 format alone is rendered and QA'd once more (make.py --from-step
  render --formats feed_4x5). If the still or its Reel fails too, the story is skipped and the reason printed (slot empty).
  The normal path (the three MP4s when the video passed) is unchanged.
Trades have their own hook (growth-video scripts/v6t-auto.py).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402  (IG_REELS_ONLY_FROM, reels_only)

VIDEO_ROOT = Path("D:/rtvw/growth-video")
CATEGORIES_OUT = Path("D:/rtv-ops/tracks/growth/research/video-v6/categories")
VIDEO_FILES = ("reel_9x16.mp4", "feed_4x5.mp4", "square_1x1.mp4", "post-package.json")
IMAGE_FORMATS = ("feed_4x5", "square_1x1", "pin_2x3", "story_9x16")
REEL_FILES = ("reel_9x16.mp4", "still/reel_9x16.png", "still/reel_9x16.jpg", "vsco-instruments.json")   # copied for an image story's Reel
REEL_AUDIT_FILES = ("reel.json", "reel-qa.json", "reel_9x16-contact.png")   # copied beside them for review (never published)
FALLBACK_FILE = "fallback.json"     # DIR/fallback.json: the picks slot went out as the still Reel, and why (daily.py stage logs it)
STILL_DIR, STILL_REEL_DIR = "still", "still-reel"   # in categories/<id>: the picks still (+ its qa.json) and its Reel


def make_args(data: dict) -> list[str]:
    story, sid = data["story"], data["story_id"]
    md = ["--media-date", data["date"]]   # post-package + evidence URLs point at v/<date>/<id>/ (daily.py stages there)
    if data["category"] == "daily_picks":
        return ["daily-picks", "--id", sid, "--date", story["trade_date"], *md]
    if data["category"] == "earnings_report":
        return ["report-summary", "--id", sid, "--report", story["report_id"], *md]
    if data["category"] == "congress_theme":
        return ["congress-theme", "--id", sid, "--days", str(int(story["days"])), *md]
    raise SystemExit(f"hook_v6cat: no category video template for {data['category']}")


def image_steps(data: dict, py: str) -> list[list[str]]:
    """Earnings still images: build (API) -> render -> post-package -> QA (writes the JPEGs and qa.json); from
    manifest.IG_REELS_ONLY_FROM then the story's Reel (still_reel.py: its own QA must pass)."""
    sid, story, date = data["story_id"], data["story"], data["date"]
    s = "scripts/v6cat/"
    if data["category"] == "earnings_today":
        build = [py, s + "earnings_image.py", "day", "--id", sid, "--date", date]
    else:
        mode = story.get("mode")
        day = dt.date.fromisoformat(date)
        weekday = day.weekday()
        # the Monday of the week shown; earnings_image.py resolves weeks_ahead against the API at render time
        # (weeks_ahead is relative to the day the API is called: a Sunday render of weeks_ahead=1 posted Monday was wrong)
        if mode == "week_ahead":
            week_start = day + dt.timedelta(days=7 - weekday)
        elif mode == "week" and weekday == 0:
            week_start = day
        else:
            raise SystemExit(f"hook_v6cat: the earnings image has no variant for mode {mode!r} on a {dt.date.fromisoformat(date):%A} "
                             "(only the full week: Monday this week, Saturday next week); story skipped")
        build = [py, s + "earnings_image.py", "week", "--id", sid, "--week-start", week_start.isoformat()]
    steps = [build, ["node", s + "render-stills.mjs", "--id", sid],
             [py, s + "earnings_image.py", "post", "--id", sid, "--publish-date", date],
             [py, s + "qa_stills.py", "--id", sid]]
    if mf.reels_only(date):
        steps.append([py, s + "still_reel.py", "--id", sid])
    return steps


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_reel(src: Path, source_dir: Path | None = None) -> tuple[dict | None, str | None]:
    """(reel.json, problem). The Reel must be one whose QA passed for the images now in `source_dir` (default `src`): reel.json and
    reel-qa.json both say pass, the MP4 is the file reel.json hashed, the picture it was built from has the bytes of the image in
    `source_dir`, and its music provenance and still exist. A leftover from an earlier run or a different image never goes out."""
    try:
        reel = json.loads((src / "reel.json").read_text(encoding="utf-8"))
        qa = json.loads((src / "reel-qa.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{src}: reel.json / reel-qa.json unreadable ({type(e).__name__}): the Reel was not made"
    if qa.get("pass") is not True or reel.get("qa_pass") is not True:
        return None, f"{src / 'reel-qa.json'}: the Reel's QA did not pass"
    missing = [n for n in REEL_FILES if not (src / n).is_file()]
    if missing:
        return None, f"{src}: Reel files missing ({', '.join(missing)})"
    if sha256_file(src / "reel_9x16.mp4") != (reel.get("files") or {}).get("reel_9x16.mp4"):
        return None, f"{src / 'reel_9x16.mp4'} is not the MP4 reel.json recorded (a stale Reel)"
    source = ((source_dir or src) / (reel.get("source") or {}).get("file", "?"))
    if not source.is_file() or sha256_file(source) != reel["source"].get("sha256"):
        return None, f"{src}: the Reel was built from a different image than the one now in the story (re-run still_reel.py)"
    if not isinstance(reel.get("music"), dict):
        return None, f"{src / 'reel.json'}: no music provenance"
    return reel, None


def failed_gates(qa: dict) -> list[str]:
    """The gates a category qa.json failed, e.g. "reel_9x16 text_truth (text_overlap_all_frames f52)"."""
    out = []
    for fmt, fr in (qa.get("formats") or {}).items():
        if not isinstance(fr, dict) or fr.get("pass") is True:
            continue
        for gate, v in fr.items():
            if not isinstance(v, dict) or v.get("pass") is not False:
                continue
            subs = []
            for k, sub in v.items():
                if isinstance(sub, dict) and sub.get("pass") is False:
                    frames = sorted({e["frame"] for e in sub.get("examples") or [] if isinstance(e, dict) and isinstance(e.get("frame"), int)})
                    subs.append(k + (" f" + ",".join(str(f) for f in frames[:4]) if frames else ""))
            out.append(f"{fmt} {gate}" + (f" ({'; '.join(subs)})" if subs else ""))
        if fr.get("banned_wording_screen"):
            out.append(f"{fmt} banned_wording_screen")
    for key in ("numbers_all_formats", "post_copy"):
        if isinstance(qa.get(key), dict) and qa[key].get("pass") is False:
            out.append(key)
    return out or ["qa.json pass is not true"]


def _fresh(path: Path, since: float | None) -> bool:
    """The file exists and (unless `since` is None: --use-existing) was written by this run."""
    return path.is_file() and (since is None or path.stat().st_mtime >= since)


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def feed_qa_passed(src: Path, since: float | None) -> bool:
    """This run's qa.json passed every gate of feed_4x5, the format the picks still is frame 0 of."""
    qa = _read(src / "qa.json") if _fresh(src / "qa.json", since) else None
    return bool(qa) and ((qa.get("formats") or {}).get("feed_4x5") or {}).get("pass") is True


def rerender_feed_ok(src: Path, since: float | None) -> bool:
    """The run stopped before its QA (the Reel's render crashed): its data and score were made in this run and the score passed, so
    the feed_4x5 format alone may be rendered and QA'd again for the still. Never on --use-existing or on leftovers."""
    if since is None or _fresh(src / "qa.json", since):
        return False
    gate, master = _read(src / "audio-gate.json"), _read(src / "audio-master.json")
    return (_fresh(src / "data.json", since) and _fresh(src / "audio-gate.json", since) and _fresh(src / "audio-master.json", since)
            and bool(gate) and gate.get("pass") is True and bool(master) and master.get("pass") is True)


def evidence_problem(pkg: dict, data: dict, src: Path) -> str | None:
    ev = pkg.get("evidence") or {}
    want = f"https://asafb2k.github.io/rapidtradeview-media/v/{data['date']}/{data['story_id']}/evidence/index.json"
    if ev.get("index_url") != want or (pkg.get("source_urls") or [None])[0] != want:
        return f"{src / 'post-package.json'}: source_urls[0] / evidence must be {want}"
    missing = [n for n in ev.get("files", []) if not (src / "evidence" / n).exists()]
    if missing or not ev.get("files"):
        return f"{src / 'evidence'}: evidence files missing ({', '.join(missing) or 'none listed'})"
    return None


def still_fallback(a: argparse.Namespace, data: dict, rid: str, src: Path, video_root: Path, reason: str, since: float | None) -> int:
    """The picks slot's Reel fallback: the picks still -> its Still -> Reel, staged as an image story with its Reel. 0 = DIR holds it."""
    label = f"slot {data.get('slot', '?')} {data['story_id']}"
    print(f"FALLBACK still_reel for {label}: the picks video failed ({reason}); building the still-based Reel", flush=True)

    def run(cmd: list[str]) -> int:
        print(f"running in {video_root}: {' '.join(cmd)}", flush=True)
        return subprocess.run(cmd, cwd=video_root).returncode

    if not feed_qa_passed(src, since) and rerender_feed_ok(src, since):
        print("the run stopped before its QA: rendering and checking feed_4x5 alone for the still", flush=True)
        run([a.python, "scripts/v6cat/make.py", *make_args(data), "--from-step", "render", "--formats", "feed_4x5"])
    if not feed_qa_passed(src, since):
        print(f"{src / 'qa.json'}: no feed_4x5 video whose QA passed in this run, so no picks still; story skipped (slot empty). "
              f"Reel failure: {reason}")
        return 1
    if run([a.python, "scripts/v6cat/picks_still_reel.py", "--id", rid, "--dir", str(src)]):
        print(f"picks_still_reel.py failed: the picks still or its Reel did not pass; story skipped (slot empty). Reel failure: {reason}")
        return 1
    still, reel_dir = src / STILL_DIR, src / STILL_REEL_DIR
    approval = _read(still / "qa.json")
    if not approval or approval.get("pass") is not True or not _fresh(still / "qa.json", since):
        print(f"{still / 'qa.json'}: the picks still is not approved by this run; story skipped (slot empty)")
        return 1
    reel, problem = check_reel(reel_dir, still)
    if problem:
        print(f"{problem}; story skipped (slot empty)")
        return 1
    images = [f"feed_4x5.{e}" for e in ("png", "jpg")]
    missing = [str(p) for p in [still / n for n in images] + [src / "post-package.json"] if not p.is_file()]
    if missing:
        print(f"missing {', '.join(missing)}; story skipped (slot empty)")
        return 1
    pkg = json.loads((src / "post-package.json").read_text(encoding="utf-8"))
    problem = evidence_problem(pkg, data, src)
    if problem:
        print(f"{problem}; story skipped (slot empty)")
        return 1
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # never a mix with an earlier attempt's video files: this story is the still and its Reel only
    for stale in ("reel_9x16.mp4", "feed_4x5.mp4", "square_1x1.mp4", "still/feed_4x5.jpg", "still/feed_4x5.png", FALLBACK_FILE):
        (out / stale).unlink(missing_ok=True)
    for n in images:
        shutil.copy2(still / n, out / n)
    (out / "still").mkdir(exist_ok=True)
    for n in REEL_FILES:
        shutil.copy2(reel_dir / n, out / n)
    for n in REEL_AUDIT_FILES:
        if (reel_dir / n).is_file():
            shutil.copy2(reel_dir / n, out / n)
    # the work copy of the post-package: the Reel's own score provenance (the still carries no audio; the video's score is not in
    # it), and an alt text that does not call a still "animated"
    pkg["music"] = reel["music"]
    if isinstance(pkg.get("alt_text"), str) and pkg["alt_text"].startswith("Animated "):
        rest = pkg["alt_text"][len("Animated "):]
        pkg["alt_text"] = rest[:1].upper() + rest[1:]
    (out / "post-package.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "evidence").mkdir(exist_ok=True)
    for n in pkg["evidence"]["files"]:
        shutil.copy2(src / "evidence" / n, out / "evidence" / n)
    record = {"fallback": "still_reel", "reason": reason, "story_id": data["story_id"], "category": data["category"],
              "still_qa": str(still / "qa.json"), "reel_qa": str(reel_dir / "reel-qa.json"), "video_qa": str(src / "qa.json"),
              "reel_sha256": reel["files"]["reel_9x16.mp4"], "source_sha256": reel["source"]["sha256"]}
    (out / FALLBACK_FILE).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"FALLBACK still_reel READY for {label}: copied {', '.join(images + list(REEL_FILES))} + evidence/ from {still} and "
          f"{reel_dir} to {out} (reason: {reason})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--use-existing")
    ap.add_argument("--video-root", help=f"growth-video tree to run in (default {VIDEO_ROOT}; a worktree for a scratch replay)")
    ap.add_argument("--categories-out", help=f"categories research dir (default {CATEGORIES_OUT}; a scratch copy for a replay)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data = json.loads(Path(a.data).read_text(encoding="utf-8-sig"))
    images = data["category"] in ("earnings_today", "earnings_week")
    cmds = image_steps(data, a.python) if images else [[a.python, "scripts/v6cat/make.py", *make_args(data)]]
    rid = a.use_existing or data["story_id"]
    reel_wanted = images and mf.reels_only(data["date"])
    video_root = Path(a.video_root) if a.video_root else VIDEO_ROOT
    categories = Path(a.categories_out) if a.categories_out else CATEGORIES_OUT
    # the picks slot's Reel fallback (owner/HQ rule 2026-10-12): Instagram is Reels only, the slot is never skipped for a failed Reel
    picks_fallback = data["category"] == "daily_picks" and mf.reels_only(data["date"])
    since = None if a.use_existing else time.time() - 2   # what this run wrote (mtime); --use-existing trusts the given dir
    still = None if images else [a.python, "scripts/v6_still.py", "category", "--id", rid]
    if a.dry_run:
        for cmd in cmds + ([still] if still else []):
            print(f"would run in {video_root}: {' '.join(cmd)}")
        return 0
    src = categories / rid
    if not a.use_existing:
        for cmd in cmds:
            print(f"running in {video_root}: {' '.join(cmd)}", flush=True)
            r = subprocess.run(cmd, cwd=video_root)
            if r.returncode:
                if picks_fallback:
                    qa = _read(src / "qa.json") if _fresh(src / "qa.json", since) else None
                    why = "; ".join(failed_gates(qa)) if qa else f"{cmd[1]} failed (exit {r.returncode}) before its QA"
                    return still_fallback(a, data, rid, src, video_root, why, since)
                print(f"{cmd[1]} failed ({r.returncode}); story skipped")
                return 1
    try:
        qa = json.loads((src / "qa.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        if picks_fallback:
            return still_fallback(a, data, rid, src, video_root, f"qa.json unreadable ({type(e).__name__})", since)
        print(f"{src / 'qa.json'} unreadable ({type(e).__name__}); story skipped")
        return 1
    if qa.get("pass") is not True:
        if picks_fallback:
            return still_fallback(a, data, rid, src, video_root, "; ".join(failed_gates(qa)), since)
        print(f"{src / 'qa.json'}: QA did not pass; story skipped")
        return 1
    reel = None
    if images:
        files = [f"{f}.{e}" for f in IMAGE_FORMATS for e in ("png", "jpg") if (src / f"{f}.{e}").exists()] + ["post-package.json"]
        if not any(f.endswith(".jpg") for f in files) or not (src / "post-package.json").exists():
            print(f"{src}: images or post-package.json missing; story skipped")
            return 1
        if reel_wanted:   # Instagram is Reels only: no Reel, no story (never a feed-image fallback)
            reel, problem = check_reel(src)
            if problem:
                print(f"{problem}; story skipped")
                return 1
    else:
        files = list(VIDEO_FILES)
        missing = [f for f in files if not (src / f).exists()]
        if missing:
            print(f"{src}: missing {', '.join(missing)}; story skipped")
            return 1
    pkg = json.loads((src / "post-package.json").read_text(encoding="utf-8"))
    ev = pkg.get("evidence") or {}
    want = f"https://asafb2k.github.io/rapidtradeview-media/v/{data['date']}/{data['story_id']}/evidence/index.json"
    if ev.get("index_url") != want or (pkg.get("source_urls") or [None])[0] != want:
        print(f"{src / 'post-package.json'}: source_urls[0] / evidence must be {want}; story skipped")
        return 1
    missing = [n for n in ev.get("files", []) if not (src / "evidence" / n).exists()]
    if missing or not ev.get("files"):
        print(f"{src / 'evidence'}: evidence files missing ({', '.join(missing) or 'none listed'}); story skipped")
        return 1
    if still:
        print(f"running in {video_root}: {' '.join(still)}", flush=True)
        if subprocess.run(still, cwd=video_root).returncode:
            print("v6_still.py failed; story skipped")
            return 1
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(src / f, out / f)
    # Every sample file the VSCO score used, with its sha256; daily.py stage writes it into music.json as
    # samples_used (the posting agents hold a video whose music lists no samples). Absent for the synth score.
    if not images and (src / "vsco-instruments.json").is_file():
        shutil.copy2(src / "vsco-instruments.json", out / "vsco-instruments.json")
        files = files + ["vsco-instruments.json"]
    if still:
        (out / "still").mkdir(exist_ok=True)
        for ext in ("jpg", "png"):
            shutil.copy2(src / "still" / f"feed_4x5.{ext}", out / "still" / f"feed_4x5.{ext}")
        files = files + ["still/feed_4x5.jpg", "still/feed_4x5.png"]
    if reel:
        (out / "still").mkdir(exist_ok=True)
        for n in REEL_FILES:
            shutil.copy2(src / n, out / n)
        for n in REEL_AUDIT_FILES:
            if (src / n).is_file():
                shutil.copy2(src / n, out / n)
        # The Reel's score provenance goes into the work copy of the post-package (the manifest keeps a present music block
        # unchanged; daily.py stage writes music.json from it): the images carry no audio, the Reel does.
        pkg_out = json.loads((out / "post-package.json").read_text(encoding="utf-8"))
        pkg_out["music"] = reel["music"]
        (out / "post-package.json").write_text(json.dumps(pkg_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = files + list(REEL_FILES) + ["music (post-package.json)"]
    (out / "evidence").mkdir(exist_ok=True)
    for n in ev["files"]:
        shutil.copy2(src / "evidence" / n, out / "evidence" / n)
    print(f"copied {', '.join(files)} + evidence/ ({len(ev['files'])} files) from {src} to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
