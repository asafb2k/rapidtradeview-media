"""run_daily.ps1 render hook for the v6 category videos (D:/rtvw/growth-video/README-v6-daily.md).

Usage (conda python):
  hook_v6cat.py --data DATA.json --out DIR [--dry-run] [--use-existing ID]
      Maps the selected story (data.json, schema rtv-daily-story/1) to scripts/v6cat/make.py (all its
      steps: data, page, assets, score, render, post, qa; never its publish), checks qa.json passed,
      then copies reel_9x16.mp4, feed_4x5.mp4, square_1x1.mp4 and post-package.json into DIR, where
      daily.py stage picks them up. --use-existing reuses an already rendered categories/<ID>/ instead
      of rendering. Exit 0 = DIR holds a QA-passed video; anything else = the story is skipped.

Wired categories:
  daily_picks      make.py daily-picks --id <story_id> --date <story.trade_date>
  earnings_report  make.py report-summary --id <story_id> --report <story.report_id>
Not wired (daily_hooks.json keeps them TODO): trades (manual per README), earnings (now still images),
Congress themes (the template renders the Big Tech 90-day theme, not the selected story).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_ROOT = Path("D:/rtvw/growth-video")
CATEGORIES_OUT = Path("D:/rtv-ops/tracks/growth/research/video-v6/categories")
FILES = ("reel_9x16.mp4", "feed_4x5.mp4", "square_1x1.mp4", "post-package.json")


def make_args(data: dict) -> list[str]:
    story, sid = data["story"], data["story_id"]
    if data["category"] == "daily_picks":
        return ["daily-picks", "--id", sid, "--date", story["trade_date"]]
    if data["category"] == "earnings_report":
        return ["report-summary", "--id", sid, "--report", story["report_id"]]
    raise SystemExit(f"hook_v6cat: no category template for {data['category']}")


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
    cmd = [a.python, "scripts/v6cat/make.py", *make_args(data)]
    rid = a.use_existing or data["story_id"]
    if a.dry_run:
        print(f"would run in {VIDEO_ROOT}: {' '.join(cmd)}")
        return 0
    if not a.use_existing:
        print(f"running in {VIDEO_ROOT}: {' '.join(cmd)}", flush=True)
        r = subprocess.run(cmd, cwd=VIDEO_ROOT)
        if r.returncode:
            print(f"make.py failed ({r.returncode}); story skipped")
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
    missing = [f for f in FILES if not (src / f).exists()]
    if missing:
        print(f"{src}: missing {', '.join(missing)}; story skipped")
        return 1
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copy2(src / f, out / f)
    print(f"copied {', '.join(FILES)} from {src} to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
