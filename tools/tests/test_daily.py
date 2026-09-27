"""daily.py staging. Run: python -m pytest tools/tests -q"""
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import daily  # noqa: E402

MP4_HEAD = b"\x00\x00\x00\x18ftypisom"


def plan(tmp):
    p = {"date": "2026-09-28", "day_type": "weekday", "slots": [
        {"slot": 2, "time_et": "09:45", "status": "filled", "category": "insider_trade", "template": "trade",
         "story_id": "len-berkshire-hathaway", "story_key": "form4:x:LEN", "tickers": ["LEN"], "people": ["Berkshire Hathaway Inc"],
         "story": {"headline": "h"}, "sources": []},
        {"slot": 5, "time_et": "14:15", "status": "empty", "reason": "none"},
    ]}
    path = tmp / "plan.json"
    path.write_text(json.dumps(p), encoding="utf-8")
    return path


def test_stories_and_stage(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    pp = plan(tmp_path)
    assert daily.main(["stories", "--plan", str(pp), "--work", str(work)]) == 0
    data = json.loads((work / "len-berkshire-hathaway" / "data.json").read_text(encoding="utf-8"))
    assert data["schema"] == "rtv-daily-story/1" and data["slot"] == 2
    spec = tmp_path / "spec.json"
    # Not rendered yet: nothing staged, exit 2.
    assert daily.main(["stage", "--plan", str(pp), "--work", str(work), "--spec", str(spec), "--repo", str(repo)]) == 2
    sdir = work / "len-berkshire-hathaway"
    for f in ("reel_9x16", "feed_4x5", "square_1x1"):
        (sdir / f"{f}.mp4").write_bytes(MP4_HEAD + b"\x00" * 20_000)
    (sdir / "post-package.json").write_text("{}", encoding="utf-8")
    (sdir / "qa-passed.json").write_text('{"passed": true}', encoding="utf-8")
    assert daily.main(["stage", "--plan", str(pp), "--work", str(work), "--spec", str(spec), "--repo", str(repo)]) == 0
    assert (repo / "v" / "2026-09-28" / "len-berkshire-hathaway" / "square_1x1.mp4").exists()
    s = json.loads(spec.read_text(encoding="utf-8"))
    assert [p["slot"] for p in s["posts"]] == [2]


def test_stage_rejects_a_file_that_is_not_an_mp4(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    pp = plan(tmp_path)
    daily.main(["stories", "--plan", str(pp), "--work", str(work)])
    sdir = work / "len-berkshire-hathaway"
    for f in ("reel_9x16", "feed_4x5", "square_1x1"):
        (sdir / f"{f}.mp4").write_bytes(b"<html>not a video</html>" * 1000)
    (sdir / "post-package.json").write_text("{}", encoding="utf-8")
    (sdir / "qa-passed.json").write_text("{}", encoding="utf-8")
    assert daily.main(["stage", "--plan", str(pp), "--work", str(work), "--spec", str(tmp_path / "s.json"), "--repo", str(repo)]) == 2
