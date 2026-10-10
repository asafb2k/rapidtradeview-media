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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402  (IG_REELS_ONLY_FROM, reels_only)

VIDEO_ROOT = Path("D:/rtvw/growth-video")
CATEGORIES_OUT = Path("D:/rtv-ops/tracks/growth/research/video-v6/categories")
VIDEO_FILES = ("reel_9x16.mp4", "feed_4x5.mp4", "square_1x1.mp4", "post-package.json")
IMAGE_FORMATS = ("feed_4x5", "square_1x1", "pin_2x3", "story_9x16")
REEL_FILES = ("reel_9x16.mp4", "still/reel_9x16.png", "still/reel_9x16.jpg", "vsco-instruments.json")   # copied for an image story's Reel
REEL_AUDIT_FILES = ("reel.json", "reel-qa.json", "reel_9x16-contact.png")   # copied beside them for review (never published)


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


def check_reel(src: Path) -> tuple[dict | None, str | None]:
    """(reel.json, problem). The Reel must be one whose QA passed for the images now in `src`: reel.json and reel-qa.json both say
    pass, the MP4 is the file reel.json hashed, the picture it was built from has the bytes of the image in `src`, and its
    music provenance and still exist. A leftover from an earlier run or a different image never goes out."""
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
    source = (src / (reel.get("source") or {}).get("file", "?"))
    if not source.is_file() or sha256_file(source) != reel["source"].get("sha256"):
        return None, f"{src}: the Reel was built from a different image than the one now in the story (re-run still_reel.py)"
    if not isinstance(reel.get("music"), dict):
        return None, f"{src / 'reel.json'}: no music provenance"
    return reel, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--use-existing")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data = json.loads(Path(a.data).read_text(encoding="utf-8-sig"))
    images = data["category"] in ("earnings_today", "earnings_week")
    cmds = image_steps(data, a.python) if images else [[a.python, "scripts/v6cat/make.py", *make_args(data)]]
    rid = a.use_existing or data["story_id"]
    reel_wanted = images and mf.reels_only(data["date"])
    still = None if images else [a.python, "scripts/v6_still.py", "category", "--id", rid]
    if a.dry_run:
        for cmd in cmds + ([still] if still else []):
            print(f"would run in {VIDEO_ROOT}: {' '.join(cmd)}")
        return 0
    if not a.use_existing:
        for cmd in cmds:
            print(f"running in {VIDEO_ROOT}: {' '.join(cmd)}", flush=True)
            r = subprocess.run(cmd, cwd=VIDEO_ROOT)
            if r.returncode:
                print(f"{cmd[1]} failed ({r.returncode}); story skipped")
                return 1
    src = CATEGORIES_OUT / rid
    try:
        qa = json.loads((src / "qa.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"{src / 'qa.json'} unreadable ({type(e).__name__}); story skipped")
        return 1
    if qa.get("pass") is not True:
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
        print(f"running in {VIDEO_ROOT}: {' '.join(still)}", flush=True)
        if subprocess.run(still, cwd=VIDEO_ROOT).returncode:
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
