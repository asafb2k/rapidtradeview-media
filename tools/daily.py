"""Python steps of the daily video run (run_daily.ps1 calls these).

Usage (conda python):
  daily.py stories --plan PLAN.json --work DIR [--slots 5,7] [--repo REPO]
      For each filled slot: DIR/<story_id>/data.json (schema rtv-daily-story/1: the selected story, its
      sources and the slot) and DIR/stories.json (the list run_daily.ps1 renders). A slot that today's
      manifest already fills is left alone (never re-rendered, never replaced by a later pass), except
      slot 7 when a report replaces the morning theme.
  daily.py stage --plan PLAN.json --work DIR --spec SPEC.json [--slots 5,7] [--repo REPO]
      For each story that rendered and passed QA (DIR/<story_id>/qa-passed.json, written by
      run_daily.ps1 after the QA hook exits 0): check its three MP4s and post-package.json, copy the
      MP4s to REPO/v/<date>/<story_id>/, and write the manifest spec (manifest.py write --spec).
      Exit 2 when nothing is ready to stage.

Rendered outputs each story directory must hold (the render / package hooks write them):
  reel_9x16.mp4, feed_4x5.mp4, square_1x1.mp4, post-package.json (the v6 shape: x.post, threads.post,
  instagram.reel.caption, pinterest.title/description/link, alt_text, source_urls).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402

STORY_SCHEMA = "rtv-daily-story/1"


def _slots(raw: str | None) -> set[int] | None:
    return {int(x) for x in raw.split(",") if x.strip()} if raw else None


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def filled(plan: dict, only: set[int] | None) -> list[dict]:
    return [s for s in plan["slots"] if s["status"] == "filled" and (only is None or s["slot"] in only)]


def published(repo: Path, date: str) -> dict[int, dict]:
    """Today's manifest posts by slot ({} when there is none yet)."""
    path = repo / "v" / date / "manifest.json"
    if not path.exists():
        return {}
    return {p["slot"]: p for p in _load(path).get("posts", []) if isinstance(p, dict) and "slot" in p}


def cmd_stories(a: argparse.Namespace) -> int:
    plan = _load(Path(a.plan))
    work = Path(a.work)
    done = published(Path(a.repo), plan["date"])
    out = []
    for s in filled(plan, _slots(a.slots)):
        have = done.get(s["slot"])
        if have and not (s["slot"] == 7 and s["category"] == "earnings_report" and have.get("category") != "earnings_report"):
            print(f"slot {s['slot']}: already published today ({have.get('story_id')}); left as is")
            continue
        sdir = work / s["story_id"]
        data = {"schema": STORY_SCHEMA, "date": plan["date"], "day_type": plan["day_type"], "slot": s["slot"], "time_et": s["time_et"],
                "category": s["category"], "template": s.get("template"), "story_id": s["story_id"], "story_key": s["story_key"],
                "tickers": s["tickers"], "people": s["people"], "story": s["story"], "sources": s["sources"]}
        mf.write_json(sdir / "data.json", data)
        out.append({"slot": s["slot"], "story_id": s["story_id"], "category": s["category"], "template": s.get("template"),
                    "dir": str(sdir), "data": str(sdir / "data.json")})
    mf.write_json(work / "stories.json", out)
    for s in plan["slots"]:
        if s["status"] != "filled":
            print(f"slot {s['slot']} {s['time_et']}: EMPTY - {s['reason']}")
    for o in out:
        print(f"slot {o['slot']}: {o['story_id']} ({o['category']}, template {o['template']}) -> {o['data']}")
    return 0


def is_mp4(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except OSError:
        return False
    return len(head) == 12 and head[4:8] == b"ftyp" and path.stat().st_size > 10_000


def cmd_stage(a: argparse.Namespace) -> int:
    plan = _load(Path(a.plan))
    work, repo = Path(a.work), Path(a.repo)
    date = plan["date"]
    posts, problems = [], []
    for s in filled(plan, _slots(a.slots)):
        sdir = work / s["story_id"]
        if not (sdir / "qa-passed.json").exists():
            problems.append(f"slot {s['slot']} {s['story_id']}: not rendered or QA not passed (no qa-passed.json)")
            continue
        bad = [f for f in mf.FORMATS if not is_mp4(sdir / f"{f}.mp4")]
        if bad:
            problems.append(f"slot {s['slot']} {s['story_id']}: missing or not an MP4: {', '.join(bad)}")
            continue
        if not (sdir / "post-package.json").exists():
            problems.append(f"slot {s['slot']} {s['story_id']}: post-package.json missing")
            continue
        dest = repo / "v" / date / s["story_id"]
        dest.mkdir(parents=True, exist_ok=True)
        for f in mf.FORMATS:
            shutil.copy2(sdir / f"{f}.mp4", dest / f"{f}.mp4")
        posts.append({"slot": s["slot"], "time_et": s["time_et"], "category": s["category"], "story_id": s["story_id"],
                      "story_key": s["story_key"], "tickers": s["tickers"], "people": s["people"],
                      "post_package": str(sdir / "post-package.json")})
    for p in problems:
        print(f"NOT STAGED: {p}")
    if not posts:
        print("nothing to stage")
        return 2
    mf.write_json(Path(a.spec), {"date": date, "posts": posts})
    for p in posts:
        print(f"staged slot {p['slot']} {p['story_id']} -> v/{date}/{p['story_id']}/")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stories")
    s.add_argument("--plan", required=True)
    s.add_argument("--work", required=True)
    s.add_argument("--slots")
    s.add_argument("--repo", default=str(mf.REPO))
    g = sub.add_parser("stage")
    g.add_argument("--plan", required=True)
    g.add_argument("--work", required=True)
    g.add_argument("--spec", required=True)
    g.add_argument("--slots")
    g.add_argument("--repo", default=str(mf.REPO))
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return {"stories": cmd_stories, "stage": cmd_stage}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
