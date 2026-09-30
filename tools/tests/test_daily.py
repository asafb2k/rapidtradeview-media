"""daily.py staging. Run: python -m pytest tools/tests -q"""
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import daily  # noqa: E402

MP4_HEAD = b"\x00\x00\x00\x18ftypisom"


def _still(sdir):
    (sdir / "still").mkdir(parents=True, exist_ok=True)
    (sdir / "still" / "feed_4x5.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    (sdir / "still" / "feed_4x5.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)


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
    assert daily.main(["stories", "--plan", str(pp), "--work", str(work), "--repo", str(repo)]) == 0
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
    # A video without its still (the Threads fallback) is not staged.
    assert daily.main(["stage", "--plan", str(pp), "--work", str(work), "--spec", str(spec), "--repo", str(repo)]) == 2
    _still(sdir)
    assert daily.main(["stage", "--plan", str(pp), "--work", str(work), "--spec", str(spec), "--repo", str(repo)]) == 0
    assert (repo / "v" / "2026-09-28" / "len-berkshire-hathaway" / "square_1x1.mp4").exists()
    still = repo / "v" / "2026-09-28" / "len-berkshire-hathaway" / "still"
    assert sorted(p.name for p in still.iterdir()) == ["feed_4x5.jpg", "feed_4x5.png"]
    s = json.loads(spec.read_text(encoding="utf-8"))
    assert [p["slot"] for p in s["posts"]] == [2]


def test_stage_rejects_a_file_that_is_not_an_mp4(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    pp = plan(tmp_path)
    daily.main(["stories", "--plan", str(pp), "--work", str(work), "--repo", str(repo)])
    sdir = work / "len-berkshire-hathaway"
    for f in ("reel_9x16", "feed_4x5", "square_1x1"):
        (sdir / f"{f}.mp4").write_bytes(b"<html>not a video</html>" * 1000)
    (sdir / "post-package.json").write_text("{}", encoding="utf-8")
    (sdir / "qa-passed.json").write_text("{}", encoding="utf-8")
    assert daily.main(["stage", "--plan", str(pp), "--work", str(work), "--spec", str(tmp_path / "s.json"), "--repo", str(repo)]) == 2


def test_a_slot_already_published_today_is_left_alone(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    pp = plan(tmp_path)
    (repo / "v" / "2026-09-28").mkdir(parents=True)
    (repo / "v" / "2026-09-28" / "manifest.json").write_text(json.dumps({"posts": [{"slot": 2, "story_id": "gme-cohen", "category": "insider_trade"}]}), encoding="utf-8")
    assert daily.main(["stories", "--plan", str(pp), "--work", str(work), "--repo", str(repo)]) == 0
    assert json.loads((work / "stories.json").read_text(encoding="utf-8")) == []


def test_stage_takes_an_image_story(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    pp = plan(tmp_path)
    daily.main(["stories", "--plan", str(pp), "--work", str(work), "--repo", str(repo)])
    sdir = work / "len-berkshire-hathaway"
    (sdir / "feed_4x5.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    (sdir / "story_9x16.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    (sdir / "post-package.json").write_text("{}", encoding="utf-8")
    (sdir / "qa-passed.json").write_text("{}", encoding="utf-8")
    assert daily.main(["stage", "--plan", str(pp), "--work", str(work), "--spec", str(tmp_path / "s.json"), "--repo", str(repo)]) == 0
    dest = repo / "v" / "2026-09-28" / "len-berkshire-hathaway"
    assert sorted(p.name for p in dest.iterdir()) == ["feed_4x5.png", "story_9x16.jpg"]


def _rendered(sdir):
    sdir.mkdir(parents=True, exist_ok=True)
    for f in ("reel_9x16", "feed_4x5", "square_1x1"):
        (sdir / f"{f}.mp4").write_bytes(MP4_HEAD + b"\x00" * 20_000)
    (sdir / "post-package.json").write_text("{}", encoding="utf-8")
    (sdir / "qa-passed.json").write_text("{}", encoding="utf-8")
    _still(sdir)


def test_a_held_slot_is_left_empty_and_never_staged(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    pp = plan(tmp_path)
    work.mkdir()
    (work / "hold.json").write_text(json.dumps({"slots": {"2": "weak amount"}}), encoding="utf-8")
    assert daily.main(["stories", "--plan", str(pp), "--work", str(work), "--repo", str(repo)]) == 0
    assert json.loads((work / "stories.json").read_text(encoding="utf-8")) == []
    _rendered(work / "len-berkshire-hathaway")  # a leftover from an earlier run
    assert daily.main(["stage", "--plan", str(pp), "--work", str(work), "--spec", str(tmp_path / "s.json"), "--repo", str(repo)]) == 2


def test_a_story_key_hold(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    pp = plan(tmp_path)
    work.mkdir()
    (work / "hold.json").write_text(json.dumps({"story_keys": {"form4:x:LEN": "lead review"}}), encoding="utf-8")
    daily.main(["stories", "--plan", str(pp), "--work", str(work), "--repo", str(repo)])
    assert json.loads((work / "stories.json").read_text(encoding="utf-8")) == []


def test_a_published_slot_is_never_staged_again(tmp_path):
    """A later pass re-plans a slot the morning pass published: its qa-passed.json must not re-stage (replace) it."""
    work, repo = tmp_path / "work", tmp_path / "repo"
    pp = plan(tmp_path)
    daily.main(["stories", "--plan", str(pp), "--work", str(work), "--repo", str(repo)])
    _rendered(work / "len-berkshire-hathaway")
    (repo / "v" / "2026-09-28").mkdir(parents=True)
    (repo / "v" / "2026-09-28" / "manifest.json").write_text(json.dumps({"posts": [{"slot": 2, "story_id": "len-berkshire-hathaway"}]}), encoding="utf-8")
    daily.main(["stories", "--plan", str(pp), "--work", str(work), "--repo", str(repo)])
    assert daily.main(["stage", "--plan", str(pp), "--work", str(work), "--spec", str(tmp_path / "s.json"), "--repo", str(repo)]) == 2


def morning_plan(tmp, slot, category="earnings_today", story_id="earnings-today-2026-09-28", key="earnings:today:2026-09-28"):
    p = {"date": "2026-09-28", "day_type": "weekday", "slots": [
        {"slot": slot, "time_et": "08:00" if slot == 1 else "09:45", "status": "filled", "category": category,
         "template": "earnings_image" if slot == 1 else "trade", "story_id": story_id, "story_key": key, "tickers": ["MU"],
         "people": [], "story": {"headline": "h"}, "sources": []}]}
    path = tmp / f"plan-{slot}.json"
    path.write_text(json.dumps(p), encoding="utf-8")
    return path


def test_stories_carry_the_story_key_for_the_render_failure_retry(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    daily.main(["stories", "--plan", str(plan(tmp_path)), "--work", str(work), "--repo", str(repo)])
    assert [s["story_key"] for s in json.loads((work / "stories.json").read_text(encoding="utf-8"))] == ["form4:x:LEN"]


def test_one_morning_post_a_day(tmp_path):
    """HQ quality rule 2026-09-30: the morning post is the trade (slot 2) or the earnings image (slot 1), never both,
    also when a later run of the day plans the other one."""
    work, repo = tmp_path / "work", tmp_path / "repo"
    (repo / "v" / "2026-09-28").mkdir(parents=True)
    man = repo / "v" / "2026-09-28" / "manifest.json"
    man.write_text(json.dumps({"posts": [{"slot": 2, "story_id": "len-berkshire-hathaway", "category": "insider_trade"}]}), encoding="utf-8")
    daily.main(["stories", "--plan", str(morning_plan(tmp_path, 1)), "--work", str(work), "--repo", str(repo)])
    assert json.loads((work / "stories.json").read_text(encoding="utf-8")) == []
    man.write_text(json.dumps({"posts": [{"slot": 1, "story_id": "earnings-today-2026-09-28", "category": "earnings_today"}]}), encoding="utf-8")
    daily.main(["stories", "--plan", str(plan(tmp_path)), "--work", str(work), "--repo", str(repo)])
    assert json.loads((work / "stories.json").read_text(encoding="utf-8")) == []
    man.write_text(json.dumps({"posts": [{"slot": 4, "story_id": "picks-2026-09-28", "category": "daily_picks"}]}), encoding="utf-8")
    daily.main(["stories", "--plan", str(morning_plan(tmp_path, 1)), "--work", str(work), "--repo", str(repo)])
    assert [s["slot"] for s in json.loads((work / "stories.json").read_text(encoding="utf-8"))] == [1]


def test_fail_records_render_failures_for_the_next_selection(tmp_path):
    import select_stories as ss
    work = tmp_path / "work"
    assert daily.main(["fail", "--work", str(work), "--slot", "2", "--story-id", "dvn-hern", "--story-key", "ptr:20035491:DVN:sell",
                       "--reason", "step 'render' failed at 2026-09-30T09:01:03Z"]) == 0
    assert daily.main(["fail", "--work", str(work), "--slot", "1", "--story-id", "earnings-today-2026-09-30",
                       "--story-key", "earnings:today:2026-09-30", "--reason", "step 'render' failed"]) == 0
    assert ss.load_exclude(str(work / "render-failed.json")) == {
        "ptr:20035491:DVN:sell": "slot 2 dvn-hern: step 'render' failed at 2026-09-30T09:01:03Z",
        "earnings:today:2026-09-30": "slot 1 earnings-today-2026-09-30: step 'render' failed"}
