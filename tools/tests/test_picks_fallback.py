"""The picks slot's Reel fallback (owner/HQ rule 2026-10-12: when the picks Reel fails its quality gate, ship a simpler
still-based Reel that day; never skip the slot). hook_v6cat.py runs the growth-video steps through subprocess.run; here a fake
growth-video answers them, so every branch runs offline:

  the Reel fails (the 2026-10-09 text_overlap at f52)        -> the picks still's Reel goes out, marked fallback still_reel
  the Reel and the still both fail                           -> the story is skipped (slot empty) with the reason
  the Reel passes                                            -> the normal three MP4s, no fallback, the still step never runs
Run: python -m pytest tools/tests -q
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import daily  # noqa: E402
import hook_v6cat as hook  # noqa: E402
import manifest as mf  # noqa: E402

DATE, BEFORE = "2026-10-12", "2026-10-09"
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 20_000
STILL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x01" * 20_000     # the still Reel (a different file from the video's Reel)
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
MUSIC = json.loads((Path(__file__).parent / "fixtures" / "vsco-music.json").read_text(encoding="utf-8"))
VIDEO_MUSIC = {**MUSIC, "credit": "the picks video's own score"}
NA = "Not investment advice."
# the gate the 2026-10-09 picks Reel failed (qa.json of that run, trimmed)
OVERLAP = {"pass": False, "real_document": False, "text_overlap_all_frames": {
    "pass": False, "frames_checked_N": 384, "violations_N": 2,
    "examples": [{"frame": 52, "a": "board.chip-2-0", "b": "board.chip-2-1"}, {"frame": 52, "a": "board.chip-3-0", "b": "board.chip-3-1"}]}}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sid(date):
    return f"picks-{date}"


def qa_json(date, reel_ok=True, feed_ok=True, square_ok=True):
    fmt = lambda ok, bad: {"pass": ok, "layout": {"pass": True}, "text_truth": {"pass": True} if ok else bad, "banned_wording_screen": []}
    formats = {"reel_9x16": fmt(reel_ok, OVERLAP), "feed_4x5": fmt(feed_ok, {"pass": False}), "square_1x1": fmt(square_ok, {"pass": False})}
    return {"id": sid(date), "kind": "daily-picks", "formats": formats, "numbers_all_formats": {"pass": True}, "post_copy": {"pass": True},
            "pass": reel_ok and feed_ok and square_ok}


def package(date):
    index = f"https://asafb2k.github.io/rapidtradeview-media/v/{date}/{sid(date)}/evidence/index.json"
    link = f"https://www.rapidtradeview.trade/picks/{date}?utm_source=x"
    return {"kind": "daily-picks", "x": {"post": f"Monday's picks: #2 $XE, #3 $AMPX.\n\n{NA} #Stocks", "reply": link},
            "instagram": {"reel": {"caption": f"Monday's picks.\n\nLink in bio.\n\n{NA}\n\n#Stocks"}, "caption": f"Monday's picks. {NA}",
                          "first_comment": link},
            "threads": {"post": f"Monday's picks. {NA} #Stocks", "first_reply": link},
            "pinterest": {"title": "Monday's published picks", "description": f"Monday's picks. {NA}",
                          "link": f"https://www.rapidtradeview.trade/picks/{date}?utm_source=pinterest"},
            "alt_text": "Animated list of the picks published today: #2 $XE, #3 $AMPX. The #1 pick is free to see after signing in.",
            "source_urls": [index, f"https://www.rapidtradeview.trade/picks/{date}"], "evidence": {"index_url": index, "files": ["index.json"]},
            "music": VIDEO_MUSIC}


def story_data(date):
    return {"schema": "rtv-daily-story/1", "date": date, "day_type": "weekday", "slot": 4, "time_et": "15:00", "category": "daily_picks",
            "template": "daily_picks", "story_id": sid(date), "story_key": f"picks:{date}", "tickers": ["XE", "AMPX"], "people": [],
            "story": {"trade_date": date}, "sources": [f"https://www.rapidtradeview.trade/picks/{date}"]}


def jw(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


class FakeVideo:
    """The growth-video commands the hook runs: make.py (writes qa.json + the three MP4s), v6_still.py (the video's still),
    picks_still_reel.py (the picks still + its Still -> Reel). Records every command."""

    def __init__(self, src: Path, date: str, qa: dict | None, still_reel_ok=True, make_exit=0):
        self.src, self.date, self.qa, self.still_reel_ok, self.make_exit = src, date, qa, still_reel_ok, make_exit
        self.calls: list[list[str]] = []

    def __call__(self, cmd, cwd=None, **kw):
        cmd = [str(c) for c in cmd]
        self.calls.append(cmd)
        script = Path(cmd[1]).name
        src = self.src
        if script == "make.py":
            if "--from-step" in cmd:                                 # the feed_4x5-only re-render for the still
                jw(src / "qa.json", {**qa_json(self.date), "formats": {"feed_4x5": qa_json(self.date)["formats"]["feed_4x5"]}, "pass": True})
                return subprocess.CompletedProcess(cmd, 0)
            jw(src / "data.json", {"kind": "daily-picks"})
            jw(src / "audio-gate.json", {"pass": True})
            jw(src / "audio-master.json", {"pass": True})
            if self.qa is not None:
                for f in mf.FORMATS:
                    (src / f"{f}.mp4").write_bytes(MP4)
                jw(src / "qa.json", self.qa)
            return subprocess.CompletedProcess(cmd, self.make_exit)
        if script == "v6_still.py":
            (src / "still").mkdir(exist_ok=True)
            (src / "still" / "feed_4x5.jpg").write_bytes(JPG)
            (src / "still" / "feed_4x5.png").write_bytes(PNG)
            return subprocess.CompletedProcess(cmd, 0)
        if script == "picks_still_reel.py":
            assert cmd[cmd.index("--dir") + 1] == str(src)
            if not self.still_reel_ok:
                return subprocess.CompletedProcess(cmd, 1)
            still, reel = src / "still", src / "still-reel"
            (still).mkdir(exist_ok=True)
            (still / "feed_4x5.png").write_bytes(PNG)
            (still / "feed_4x5.jpg").write_bytes(JPG)
            jw(still / "qa.json", {"pass": True, "formats": {"feed_4x5": {"pass": True}}})
            (reel / "still").mkdir(parents=True, exist_ok=True)
            (reel / "reel_9x16.mp4").write_bytes(STILL_MP4)
            (reel / "still" / "reel_9x16.png").write_bytes(PNG)
            (reel / "still" / "reel_9x16.jpg").write_bytes(JPG)
            jw(reel / "vsco-instruments.json", {"instruments": []})
            jw(reel / "reel-qa.json", {"pass": True})
            jw(reel / "reel.json", {"qa_pass": True, "source": {"file": "feed_4x5.png", "sha256": sha(PNG)},
                                    "files": {"reel_9x16.mp4": sha(STILL_MP4)}, "music": MUSIC})
            return subprocess.CompletedProcess(cmd, 0)
        raise AssertionError(f"unexpected command {cmd}")

    def ran(self, script: str) -> list[list[str]]:
        return [c for c in self.calls if Path(c[1]).name == script]


def setup(tmp_path, monkeypatch, date=DATE, **kw):
    cats = tmp_path / "categories"
    src = cats / sid(date)
    (src / "evidence").mkdir(parents=True)
    (src / "evidence" / "index.json").write_text("{}", encoding="utf-8")
    jw(src / "post-package.json", package(date))
    fake = FakeVideo(src, date, **kw)
    monkeypatch.setattr(hook.subprocess, "run", fake)
    data_file = tmp_path / "work" / sid(date) / "data.json"
    jw(data_file, story_data(date))
    return fake, data_file, cats


def run_hook(tmp_path, monkeypatch, date=DATE, **kw):
    fake, data_file, cats = setup(tmp_path, monkeypatch, date, **kw)
    out = data_file.parent
    code = hook.main(["--data", str(data_file), "--out", str(out), "--categories-out", str(cats), "--python", "py"])
    return code, out, fake


def test_the_reel_fails_and_the_picks_still_reel_goes_out(tmp_path, monkeypatch, capsys):
    code, out, fake = run_hook(tmp_path, monkeypatch, qa=qa_json(DATE, reel_ok=False))
    log = capsys.readouterr().out
    assert code == 0
    assert "FALLBACK still_reel for slot 4 picks-2026-10-12" in log and "reel_9x16 text_truth (text_overlap_all_frames f52)" in log
    assert len(fake.ran("picks_still_reel.py")) == 1 and not fake.ran("v6_still.py")      # the still step, not the video's still
    # the slot is the still and ITS Reel: never the video's failed reel_9x16.mp4, never the feed / square MP4s
    assert (out / "reel_9x16.mp4").read_bytes() == STILL_MP4
    assert not (out / "feed_4x5.mp4").exists() and not (out / "square_1x1.mp4").exists()
    assert (out / "feed_4x5.png").read_bytes() == PNG and (out / "feed_4x5.jpg").read_bytes() == JPG
    for n in hook.REEL_FILES:
        assert (out / n).is_file(), n
    fb = json.loads((out / hook.FALLBACK_FILE).read_text(encoding="utf-8"))
    assert fb["fallback"] == "still_reel" and fb["reason"] == "reel_9x16 text_truth (text_overlap_all_frames f52)"
    pkg = json.loads((out / "post-package.json").read_text(encoding="utf-8"))
    assert pkg["music"] == MUSIC                                       # the still Reel's score, not the video's
    assert pkg["alt_text"].startswith("List of the picks") and NA in pkg["x"]["post"]
    # staged and written like an image story with its Reel: Instagram = the still Reel, X / Threads / Pinterest = the still
    (out / "qa-passed.json").write_text("{}", encoding="utf-8")
    plan = tmp_path / "plan.json"
    s = story_data(DATE)
    jw(plan, {"date": DATE, "day_type": "weekday", "slots": [{**{k: s[k] for k in ("slot", "time_et", "category", "template", "story_id",
                                                                                    "story_key", "tickers", "people", "story", "sources")},
                                                               "status": "filled"}]})
    jw(out.parent / "stories.json", [{"slot": 4, "story_id": sid(DATE)}])
    repo, spec = tmp_path / "repo", tmp_path / "spec.json"
    assert daily.main(["stage", "--plan", str(plan), "--work", str(out.parent), "--spec", str(spec), "--repo", str(repo)]) == 0
    assert "(FALLBACK still_reel: reel_9x16 text_truth (text_overlap_all_frames f52))" in capsys.readouterr().out
    sp = json.loads(spec.read_text(encoding="utf-8"))
    assert sp["posts"][0]["fallback"] == {"type": "still_reel", "reason": "reel_9x16 text_truth (text_overlap_all_frames f52)"}
    m = mf.build_manifest(sp, repo=repo)
    post = m["posts"][0]
    assert mf.validate_manifest(m, DATE) == [] and "fallback" not in post             # the kit's post keys are fixed: the spec / log carry it
    assert post["media"] == {"reel_9x16": mf.media_url(DATE, sid(DATE), "reel_9x16")}
    assert {k: (v["media_type"], v["media"]) for k, v in post["platforms"].items()} == {
        "instagram": ("video", "reel_9x16"), "x": ("image", "feed_4x5"), "threads": ("image", "feed_4x5"), "pinterest": ("image", "feed_4x5")}
    assert post["platforms"]["instagram"]["placement"] == "reel" and post["music"] == MUSIC
    music = json.loads((repo / "v" / DATE / sid(DATE) / "music.json").read_text(encoding="utf-8"))
    assert music["files"] == {"reel_9x16.mp4": sha(STILL_MP4)}


def test_the_reel_and_the_still_both_fail_and_the_slot_stays_empty_with_the_reason(tmp_path, monkeypatch, capsys):
    code, out, fake = run_hook(tmp_path, monkeypatch, qa=qa_json(DATE, reel_ok=False), still_reel_ok=False)
    log = capsys.readouterr().out
    assert code == 1
    assert "picks_still_reel.py failed" in log and "story skipped (slot empty)" in log and "text_overlap_all_frames f52" in log
    assert not any((out / n).exists() for n in ("reel_9x16.mp4", "feed_4x5.png", "feed_4x5.jpg", hook.FALLBACK_FILE))


def test_no_still_when_the_feed_video_failed_too(tmp_path, monkeypatch, capsys):
    code, out, fake = run_hook(tmp_path, monkeypatch, qa=qa_json(DATE, reel_ok=False, feed_ok=False))
    log = capsys.readouterr().out
    assert code == 1 and not fake.ran("picks_still_reel.py")
    assert "no feed_4x5 video whose QA passed in this run" in log and "reel_9x16 text_truth" in log and "feed_4x5 text_truth" in log
    assert not (out / "reel_9x16.mp4").exists() and not (out / hook.FALLBACK_FILE).exists()


def test_a_still_reel_that_did_not_pass_its_qa_never_goes_out(tmp_path, monkeypatch, capsys):
    fake, data_file, cats = setup(tmp_path, monkeypatch, qa=qa_json(DATE, reel_ok=False))
    real = fake.__call__

    def broken(cmd, cwd=None, **kw):     # picks_still_reel.py exits 0 but its reel-qa.json says FAIL (a hand edit, a bug)
        r = real(cmd, cwd, **kw)
        if Path(str(cmd[1])).name == "picks_still_reel.py":
            jw(fake.src / "still-reel" / "reel-qa.json", {"pass": False})
        return r
    monkeypatch.setattr(hook.subprocess, "run", broken)
    out = data_file.parent
    assert hook.main(["--data", str(data_file), "--out", str(out), "--categories-out", str(cats), "--python", "py"]) == 1
    assert "the Reel's QA did not pass; story skipped (slot empty)" in capsys.readouterr().out
    assert not (out / "reel_9x16.mp4").exists()


def test_the_reel_passes_and_the_normal_video_post_is_unchanged(tmp_path, monkeypatch, capsys):
    code, out, fake = run_hook(tmp_path, monkeypatch, qa=qa_json(DATE))
    log = capsys.readouterr().out
    assert code == 0 and "FALLBACK" not in log
    assert not fake.ran("picks_still_reel.py") and len(fake.ran("v6_still.py")) == 1
    assert [Path(c[1]).name for c in fake.calls] == ["make.py", "v6_still.py"]
    assert all((out / f"{f}.mp4").read_bytes() == MP4 for f in mf.FORMATS)
    assert (out / "still" / "feed_4x5.jpg").is_file() and not (out / hook.FALLBACK_FILE).exists() and not (out / "feed_4x5.png").exists()
    pkg = json.loads((out / "post-package.json").read_text(encoding="utf-8"))
    assert pkg == package(DATE)                                         # the video's own package, untouched


def test_before_reels_only_a_failed_picks_video_is_skipped_as_before(tmp_path, monkeypatch, capsys):
    code, out, fake = run_hook(tmp_path, monkeypatch, date=BEFORE, qa=qa_json(BEFORE, reel_ok=False))
    log = capsys.readouterr().out
    assert code == 1 and "QA did not pass; story skipped" in log and "FALLBACK" not in log
    assert not fake.ran("picks_still_reel.py")


def test_a_reel_render_crash_renders_feed_alone_for_the_still(tmp_path, monkeypatch, capsys):
    """make.py stopped in the render step (no qa.json this run) after this run's data and a passing score: feed_4x5 alone is rendered
    and QA'd, then the still Reel goes out."""
    code, out, fake = run_hook(tmp_path, monkeypatch, qa=None, make_exit=1)
    log = capsys.readouterr().out
    assert code == 0, log
    rer = [c for c in fake.ran("make.py") if "--from-step" in c]
    assert len(rer) == 1 and rer[0][rer[0].index("--from-step") + 1] == "render" and rer[0][rer[0].index("--formats") + 1] == "feed_4x5"
    fb = json.loads((out / hook.FALLBACK_FILE).read_text(encoding="utf-8"))
    assert fb["reason"] == "scripts/v6cat/make.py failed (exit 1) before its QA"
    assert (out / "reel_9x16.mp4").read_bytes() == STILL_MP4


def test_leftovers_from_an_earlier_run_never_make_a_still(tmp_path, monkeypatch, capsys):
    """A crash before this run's data step: the qa.json / score files on disk are an earlier run's, so no re-render and no still."""
    fake, data_file, cats = setup(tmp_path, monkeypatch, qa=None, make_exit=1)
    old = 1_000_000_000
    for n, obj in (("qa.json", qa_json(DATE, reel_ok=False)), ("data.json", {}), ("audio-gate.json", {"pass": True}), ("audio-master.json", {"pass": True})):
        jw(fake.src / n, obj)
        os.utime(fake.src / n, (old, old))
    real = fake.__call__

    def crash_early(cmd, cwd=None, **kw):   # make.py fails in its data step: writes nothing
        fake.calls.append([str(c) for c in cmd])
        if Path(str(cmd[1])).name == "make.py":
            return subprocess.CompletedProcess(cmd, 1)
        return real(cmd, cwd, **kw)
    monkeypatch.setattr(hook.subprocess, "run", crash_early)
    out = data_file.parent
    assert hook.main(["--data", str(data_file), "--out", str(out), "--categories-out", str(cats), "--python", "py"]) == 1
    log = capsys.readouterr().out
    assert "no feed_4x5 video whose QA passed in this run" in log
    assert [Path(c[1]).name for c in fake.calls] == ["make.py"]                 # no re-render, no still


def test_failed_gates_names_every_failed_gate():
    qa = qa_json(DATE, reel_ok=False, square_ok=False)
    qa["post_copy"] = {"pass": False}
    assert hook.failed_gates(qa) == ["reel_9x16 text_truth (text_overlap_all_frames f52)", "square_1x1 text_truth", "post_copy"]
    assert hook.failed_gates({"pass": False}) == ["qa.json pass is not true"]


def test_a_leftover_fallback_file_does_not_mark_a_normal_video_post(tmp_path, capsys):
    work, repo = tmp_path / "work", tmp_path / "repo"
    sdir = work / sid(DATE)
    for f in mf.FORMATS:
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / f"{f}.mp4").write_bytes(MP4)
    (sdir / "still").mkdir()
    (sdir / "still" / "feed_4x5.jpg").write_bytes(JPG)
    (sdir / "still" / "feed_4x5.png").write_bytes(PNG)
    jw(sdir / "post-package.json", package(DATE))
    jw(sdir / "qa-passed.json", {})
    jw(sdir / hook.FALLBACK_FILE, {"fallback": "still_reel", "reason": "an earlier attempt"})
    s = story_data(DATE)
    plan = tmp_path / "plan.json"
    jw(plan, {"date": DATE, "day_type": "weekday", "slots": [{**s, "status": "filled"}]})
    jw(work / "stories.json", [{"slot": 4, "story_id": sid(DATE)}])
    spec = tmp_path / "spec.json"
    assert daily.main(["stage", "--plan", str(plan), "--work", str(work), "--spec", str(spec), "--repo", str(repo)]) == 0
    assert "fallback" not in json.loads(spec.read_text(encoding="utf-8"))["posts"][0] and "FALLBACK" not in capsys.readouterr().out


def test_the_dry_run_lists_the_normal_steps_only(tmp_path, monkeypatch, capsys):
    fake, data_file, cats = setup(tmp_path, monkeypatch, qa=qa_json(DATE))
    assert hook.main(["--data", str(data_file), "--out", str(tmp_path / "o"), "--dry-run", "--python", "py"]) == 0
    log = capsys.readouterr().out
    assert "make.py daily-picks" in log and "v6_still.py" in log and "picks_still_reel" not in log and not fake.calls


def test_a_fallback_after_an_earlier_staged_video_never_mixes_the_two(tmp_path, monkeypatch, capsys):
    """An earlier same-day attempt staged the video's three MP4s (no manifest yet); the rerun takes the fallback: the folder must read
    as the still and its Reel, never as a video post with the still Reel next to the old feed / square MP4s."""
    code, out, fake = run_hook(tmp_path, monkeypatch, qa=qa_json(DATE, reel_ok=False))
    assert code == 0
    (out / "qa-passed.json").write_text("{}", encoding="utf-8")
    repo = tmp_path / "repo"
    dest = repo / "v" / DATE / sid(DATE)
    dest.mkdir(parents=True)
    for f in mf.FORMATS:
        (dest / f"{f}.mp4").write_bytes(MP4)
    s = story_data(DATE)
    plan = tmp_path / "plan.json"
    jw(plan, {"date": DATE, "day_type": "weekday", "slots": [{**s, "status": "filled"}]})
    jw(out.parent / "stories.json", [{"slot": 4, "story_id": sid(DATE)}])
    spec = tmp_path / "spec.json"
    assert daily.main(["stage", "--plan", str(plan), "--work", str(out.parent), "--spec", str(spec), "--repo", str(repo)]) == 0
    assert "removed feed_4x5.mp4 of an earlier attempt" in capsys.readouterr().out
    assert sorted(p.name for p in dest.glob("*.mp4")) == ["reel_9x16.mp4"] and (dest / "reel_9x16.mp4").read_bytes() == STILL_MP4
    m = mf.build_manifest(json.loads(spec.read_text(encoding="utf-8")), repo=repo)
    assert m["posts"][0]["media"] == {"reel_9x16": mf.media_url(DATE, sid(DATE), "reel_9x16")} and mf.validate_manifest(m, DATE) == []
