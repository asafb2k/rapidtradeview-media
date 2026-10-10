"""Instagram is Reels only (Growth decision 2026-10-10): the manifest rules, an image story's own Reel (writer, validator, staging,
hook) and the unchanged past. All offline. Run: python -m pytest tools/tests -q

The kit's validator (frontend/src/lib/socialKitVideos.ts) must take what the writer now makes: see the TS change listed in
tools/manifest.py's docstring / the PR note (media {reel_9x16} alone for an image post, up to 5 Instagram Reels a weekday)."""
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import daily  # noqa: E402
import hook_v6cat as hook  # noqa: E402
import manifest as mf  # noqa: E402

REPO = TOOLS.parent
PUBLISHED = REPO / "v" / "2026-10-10" / "manifest.json"   # the image story published before the switch (a feed image)
SID = "earnings-week-2026-10-12"
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 20_000
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
MUSIC = json.loads((Path(__file__).parent / "fixtures" / "vsco-music.json").read_text(encoding="utf-8"))
WEEKDAY, WEEKEND, BEFORE = "2026-10-19", "2026-10-24", "2026-10-16"
IMAGES = ("feed_4x5", "square_1x1", "pin_2x3", "story_9x16")


def published_post():
    return next(p for p in json.loads(PUBLISHED.read_text(encoding="utf-8"))["posts"] if p["story_id"] == SID)


def package():
    """The post-package of the published earnings-week image story (what earnings_image.py post writes: instagram.feed.caption)."""
    p = published_post()
    return {"x": {"post": p["platforms"]["x"]["text"], "reply": p["platforms"]["x"]["reply"]},
            "instagram": {"feed": {"caption": p["platforms"]["instagram"]["caption"]}},
            "threads": {"post": p["platforms"]["threads"]["text"], "first_reply": p["platforms"]["threads"]["first_reply"]},
            "pinterest": {k: p["platforms"]["pinterest"][k] for k in ("title", "description", "link")},
            "alt_text": p["alt_text"], "source_urls": p["source_urls"]}


def story(tmp_path, date, reel=True, images=IMAGES, slot=1):
    d = tmp_path / "repo" / "v" / date / SID
    d.mkdir(parents=True, exist_ok=True)
    for f in images:
        (d / f"{f}.jpg").write_bytes(JPG)
    if reel:
        (d / "reel_9x16.mp4").write_bytes(MP4)
    pkg = tmp_path / "post-package.json"
    pkg.write_text(json.dumps(package()), encoding="utf-8")
    p = published_post()
    spec = {"date": date, "posts": [{"slot": slot, "time_et": mf.WEEKDAY_SLOTS[slot] if mf.day_type(date) == "weekday" else "12:00",
                                     "category": "earnings_week", "story_id": SID, "story_key": p["story_key"], "tickers": p["tickers"],
                                     "people": [], "post_package": str(pkg)}]}
    return tmp_path / "repo", spec


def test_the_switch_is_the_day_after_the_decision():
    assert mf.IG_REELS_ONLY_FROM == "2026-10-19"
    assert [mf.reels_only(d) for d in ("2026-10-09", BEFORE, WEEKEND, WEEKDAY)] == [False, False, True, True]
    assert mf.reserved_ig(WEEKDAY) == {4: "reel"} and mf.reserved_ig(BEFORE) == mf.reserved_ig()


@pytest.mark.parametrize("slots,want", [
    ([1, 2, 3, 4, 5, 6, 7], {2: "reel", 1: "reel", 3: "reel", 4: "reel", 6: "reel"}),   # the old 1 Reel + 4 feed, all Reels
    ([1, 3, 4, 6], {1: "reel", 3: "reel", 4: "reel", 6: "reel"}),
    ([1, 2, 3, 5, 6, 7], {2: "reel", 1: "reel", 3: "reel", 6: "reel", 5: "reel"}),
    ([1], {1: "reel"}),
])
def test_every_weekday_instagram_post_is_a_reel(slots, want):
    assert mf.assign_instagram(slots, "weekday", {}, reels=True) == want
    assert len(mf.assign_instagram(slots, "weekday", {}, reels=True)) <= mf.IG_REELS_PER_WEEKDAY


def test_reels_keep_the_picks_place_a_published_post_and_a_none():
    morning = mf.assign_instagram([1, 2, 3, 6, 7], "weekday", {}, mf.reserved_ig(WEEKDAY), reels=True)
    assert morning == {1: "reel", 2: "reel", 3: "reel", 6: "reel"}                      # the picks slot's Reel is held for 13:45
    kept = {**morning, 7: "none"}
    assert mf.assign_instagram([1, 2, 3, 4, 6, 7], "weekday", kept, mf.reserved_ig(WEEKDAY), reels=True) == {**morning, 4: "reel"}
    # a feed post or Story already published today counts as one of the places (and stays what it was in the manifest)
    assert mf.assign_instagram([1, 2, 3, 4, 6], "weekday", {1: "feed", 3: "story"}, mf.reserved_ig(WEEKDAY), reels=True) == \
        {1: "reel", 3: "reel", 2: "reel", 4: "reel", 6: "reel"}
    assert mf.assign_instagram([1, 2], "weekday", {1: "none"}, reels=True) == {2: "reel"}


def test_weekend_is_one_reel_image_story_or_not():
    assert mf.assign_instagram([1], "weekend", {}, reels=True) == {1: "reel"}
    assert mf.assign_instagram([1], "weekend", {}, image_slots={1}, reels=True) == {1: "reel"}   # not the old "feed"
    assert mf.assign_instagram([1], "weekend", {1: "none"}, reels=True) == {}
    assert mf.assign_instagram([1], "weekend", {}, image_slots={1}) == {1: "feed"}               # before the switch, unchanged


@pytest.mark.parametrize("date", [WEEKDAY, WEEKEND])
def test_an_image_story_posts_its_own_reel_on_instagram_and_its_images_elsewhere(tmp_path, date):
    repo, spec = story(tmp_path, date)
    m = mf.build_manifest(spec, repo=repo)
    post = m["posts"][0]
    assert post["media"] == {"reel_9x16": mf.media_url(date, SID, "reel_9x16")}                  # the Reel alone, no feed / square MP4s
    assert set(post["images"]) == set(IMAGES)
    ig = post["platforms"]["instagram"]
    assert (ig["placement"], ig["media_type"], ig["media"], ig["media_url"]) == ("reel", "video", "reel_9x16", post["media"]["reel_9x16"])
    assert ig["caption"] == package()["instagram"]["feed"]["caption"] and mf.NOT_ADVICE in ig["caption"]
    assert ig["link_sticker_url"] is None and ig["alt_text"] == post["alt_text"]
    got = {k: (v["media_type"], v["media"]) for k, v in post["platforms"].items() if k != "instagram"}
    assert got == {"x": ("image", "square_1x1"), "threads": ("image", "feed_4x5"), "pinterest": ("image", "pin_2x3")}   # as they were
    assert mf.validate_manifest(m, date) == []
    # the files the commit carries: images + the Reel (+ its still when staged)
    problems, files = mf.spec_files(repo, spec)
    assert problems == [] and any(u.endswith("/reel_9x16.mp4") for u in files) and any(u.endswith("/story_9x16.jpg") for u in files)


@pytest.mark.parametrize("asked", ["feed", "story", "reel", None])
def test_a_specs_feed_or_story_is_a_reel_from_the_switch(tmp_path, asked):
    repo, spec = story(tmp_path, WEEKDAY)
    if asked:
        spec["posts"][0]["instagram_placement"] = asked
    m = mf.build_manifest(spec, repo=repo)
    assert m["posts"][0]["platforms"]["instagram"]["placement"] == "reel"
    assert mf.validate_manifest(m, WEEKDAY) == []


def test_a_promo_keeps_its_reel_default_and_a_none_is_kept(tmp_path):
    repo, spec = story(tmp_path, WEEKDAY)
    spec["posts"][0]["instagram_placement"] = "none"
    assert "instagram" not in mf.build_manifest(spec, repo=repo)["posts"][0]["platforms"]


def test_an_image_story_without_its_reel_is_refused_never_a_feed_image(tmp_path):
    repo, spec = story(tmp_path, WEEKDAY, reel=False)
    with pytest.raises(ValueError, match="needs its reel_9x16.mp4"):
        mf.build_manifest(spec, repo=repo)
    # a lone Reel without the images is not a post either
    repo2, spec2 = story(tmp_path / "b", WEEKDAY, images=())
    problems, _ = mf.spec_files(repo2, spec2)
    assert any("lone reel_9x16.mp4 needs the story's images" in x for x in problems)


def test_before_the_switch_an_image_post_is_still_a_feed_image_and_never_a_reel(tmp_path):
    repo, spec = story(tmp_path, BEFORE, reel=False)
    m = mf.build_manifest(spec, repo=repo)
    ig = m["posts"][0]["platforms"]["instagram"]
    assert (ig["placement"], ig["media_type"], ig["media"]) == ("feed", "image", "feed_4x5") and m["posts"][0]["media"] == {}
    assert mf.validate_manifest(m, BEFORE) == []
    m["posts"][0]["platforms"]["instagram"]["placement"] = "reel"
    assert any("an image post is never a Reel" in e for e in mf.validate_manifest(m, BEFORE))


def test_every_published_manifest_stays_valid():
    paths = sorted((REPO / "v").glob("*/manifest.json"))
    assert paths
    for path in paths:
        assert mf.validate_manifest(json.loads(path.read_text(encoding="utf-8")), path.parent.name) == [], path


def valid_reel_day(tmp_path, date=WEEKDAY, n=1):
    repo, spec = story(tmp_path, date)
    return mf.build_manifest(spec, repo=repo), repo, spec


@pytest.mark.parametrize("mutate,needle", [
    (lambda p: p["platforms"]["instagram"].update(placement="feed"), "Instagram posts are Reels only from 2026-10-19 (not feed)"),
    (lambda p: p["platforms"]["instagram"].update(placement="story", caption=None), "Instagram posts are Reels only from 2026-10-19 (not story)"),
    (lambda p: p["platforms"]["instagram"].update(media_type="image", media="feed_4x5", media_url=p["images"]["feed_4x5"]),
     "an Instagram Reel is a video; an image story posts its reel_9x16.mp4"),
    (lambda p: p["platforms"]["instagram"].update(media="feed_4x5"), "instagram.media: must be reel_9x16 for a video"),
    (lambda p: p["platforms"]["instagram"].update(media_url=p["images"]["feed_4x5"]), "instagram.media_url: must be the post's media.reel_9x16"),
    (lambda p: p.__setitem__("images", {}) or p.pop("images"), "a video post has all of"),            # a lone Reel needs its images
    (lambda p: p["media"].update(feed_4x5=mf.media_url(WEEKDAY, SID, "feed_4x5")), "a video post has all of"),   # Reel + one more MP4
    (lambda p: p["media"].update(reel_9x16="https://example.com/x.mp4"), "media.reel_9x16: must be https://asafb2k.github.io"),
])
def test_validator_rules_once_instagram_is_reels_only(tmp_path, mutate, needle):
    m, _, _ = valid_reel_day(tmp_path)
    mutate(m["posts"][0])
    errors = mf.validate_manifest(m, WEEKDAY)
    assert any(needle in e for e in errors), errors


def test_a_weekday_has_at_most_five_reels_and_a_weekend_one_post(tmp_path):
    m, _, _ = valid_reel_day(tmp_path)
    base = m["posts"][0]
    day = copy.deepcopy(m)
    day["posts"] = []
    for i in range(6):
        p = copy.deepcopy(base)
        sid = f"story-{i + 1}"
        p.update(slot=i + 1, story_id=sid, id=f"video-{WEEKDAY}-{sid}")
        p["media"] = {"reel_9x16": mf.media_url(WEEKDAY, sid, "reel_9x16")}
        p["images"] = {f: mf.image_url(WEEKDAY, sid, f, "jpg") for f in IMAGES}
        p["platforms"]["instagram"]["media_url"] = p["media"]["reel_9x16"]
        for plat, f in (("x", "square_1x1"), ("threads", "feed_4x5"), ("pinterest", "pin_2x3")):
            p["platforms"][plat]["media_url"] = p["images"][f]
        day["posts"].append(p)
    day["posts"] = day["posts"][:5]
    assert mf.validate_manifest(day, WEEKDAY) == []
    day["posts"].append(copy.deepcopy(day["posts"][0]))
    day["posts"][5].update(slot=6, id="video-2026-10-12-story-1-b")
    assert any("6 Instagram reel posts; a weekday has at most 5" in e for e in mf.validate_manifest(day, WEEKDAY))
    # the promo's Reel is on top of the day (it never counted against the mix)
    promo = copy.deepcopy(day["posts"][4])
    promo.update(slot=8, category="product_promo", id="video-2026-10-12-promo", story_id="promo")
    day["posts"] = day["posts"][:5] + [promo]
    assert not any("Instagram reel posts" in e for e in mf.validate_manifest(day, WEEKDAY))


def test_video_stories_are_reels_too(tmp_path):
    """The trade / picks / report videos: every Instagram post was a feed video before; now placement reel on the same reel_9x16 file."""
    date = WEEKDAY
    d = tmp_path / "repo" / "v" / date
    posts = []
    for slot, cat in ((1, "earnings_week"), (2, "insider_trade"), (3, "insider_trade")):
        sid = f"video-{slot}"
        (d / sid).mkdir(parents=True)
        for f in mf.FORMATS:
            (d / sid / f"{f}.mp4").write_bytes(MP4)
        pkg = tmp_path / f"pkg-{slot}.json"
        pkg.write_text(json.dumps({**package(), "instagram": {"reel": {"caption": package()["instagram"]["feed"]["caption"]}}}), encoding="utf-8")
        posts.append({"slot": slot, "time_et": mf.WEEKDAY_SLOTS[slot], "category": cat, "story_id": sid, "story_key": f"k:{slot}",
                      "tickers": [], "people": [], "post_package": str(pkg)})
    m = mf.build_manifest({"date": date, "posts": posts}, repo=tmp_path / "repo")
    assert {p["slot"]: (p["platforms"]["instagram"]["placement"], p["platforms"]["instagram"]["media"]) for p in m["posts"]} == \
        {1: ("reel", "reel_9x16"), 2: ("reel", "reel_9x16"), 3: ("reel", "reel_9x16")}
    assert mf.validate_manifest(m, date) == []
    m["posts"][1]["platforms"]["instagram"]["placement"] = "feed"
    assert any("Reels only" in e for e in mf.validate_manifest(m, date))


def test_a_manifest_merge_keeps_a_published_post_and_adds_the_picks_reel(tmp_path):
    repo, spec = story(tmp_path, WEEKDAY)
    morning = mf.build_manifest(spec, repo=repo)
    sid = "picks-1"
    d = repo / "v" / WEEKDAY / sid
    d.mkdir(parents=True)
    for f in mf.FORMATS:
        (d / f"{f}.mp4").write_bytes(MP4)
    pkg = tmp_path / "pkg-picks.json"
    pkg.write_text(json.dumps({**package(), "instagram": {"reel": {"caption": "Today's picks. Not investment advice."}}}), encoding="utf-8")
    picks = {"date": WEEKDAY, "posts": [{"slot": 4, "time_et": "15:00", "category": "daily_picks", "story_id": sid, "story_key": "picks:x",
                                         "tickers": [], "people": [], "post_package": str(pkg)}]}
    m = mf.build_manifest(picks, existing=morning, repo=repo)
    assert {p["slot"]: p["platforms"]["instagram"]["placement"] for p in m["posts"]} == {1: "reel", 4: "reel"}
    assert mf.validate_manifest(m, WEEKDAY) == []


# ---- staging --------------------------------------------------------------------------------------------------------------
def plan(tmp, date, slot=1):
    p = {"date": date, "day_type": mf.day_type(date), "slots": [
        {"slot": slot, "time_et": "08:00" if slot == 1 else "12:00", "status": "filled", "category": "earnings_week", "template": "earnings_image",
         "story_id": SID, "story_key": "earnings:week_ahead:2026-10-12", "tickers": ["JPM"], "people": [], "story": {"mode": "week_ahead"}, "sources": []}]}
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"plan-{date}.json"
    path.write_text(json.dumps(p), encoding="utf-8")
    return path


def rendered_image_story(sdir, reel=True, music=True, still=True):
    sdir.mkdir(parents=True, exist_ok=True)
    for f in IMAGES:
        (sdir / f"{f}.jpg").write_bytes(JPG)
    pkg = package()
    if music:
        pkg["music"] = MUSIC
    (sdir / "post-package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (sdir / "qa-passed.json").write_text("{}", encoding="utf-8")
    if reel:
        (sdir / "reel_9x16.mp4").write_bytes(MP4)
        (sdir / "vsco-instruments.json").write_text(json.dumps({"library": {"commit": "2809277"}, "instruments": []}), encoding="utf-8")
    if reel and still:
        (sdir / "still").mkdir(exist_ok=True)
        (sdir / "still" / "reel_9x16.jpg").write_bytes(JPG)
        (sdir / "still" / "reel_9x16.png").write_bytes(PNG)


def stage(tmp_path, date, **kw):
    work, repo = tmp_path / "work", tmp_path / "repo"
    pp = plan(tmp_path, date)
    assert daily.main(["stories", "--plan", str(pp), "--work", str(work), "--repo", str(repo)]) == 0
    rendered_image_story(work / SID, **kw)
    spec = tmp_path / "spec.json"
    return daily.main(["stage", "--plan", str(pp), "--work", str(work), "--spec", str(spec), "--repo", str(repo)]), repo / "v" / date / SID, spec


@pytest.mark.parametrize("date", [WEEKDAY, WEEKEND])
def test_stage_takes_an_image_story_with_its_reel_still_and_music(tmp_path, date):
    code, dest, spec = stage(tmp_path, date)
    assert code == 0
    assert sorted(p.name for p in dest.iterdir() if p.is_file()) == sorted([f"{f}.jpg" for f in IMAGES] + ["reel_9x16.mp4", "music.json"])
    assert sorted(p.name for p in (dest / "still").iterdir()) == ["reel_9x16.jpg", "reel_9x16.png"]
    m = json.loads((dest / "music.json").read_text(encoding="utf-8"))
    assert m["music"] == MUSIC and set(m["files"]) == {"reel_9x16.mp4"}                         # the music is the Reel's, not the images'
    assert m["files"]["reel_9x16.mp4"] == hashlib.sha256((dest / "reel_9x16.mp4").read_bytes()).hexdigest()
    assert "samples_used" in m
    # the writer takes the staged files: Instagram = the Reel, music carried into the manifest post
    day = mf.build_manifest(json.loads(spec.read_text(encoding="utf-8")), repo=dest.parent.parent.parent)
    assert day["posts"][0]["platforms"]["instagram"]["placement"] == "reel" and day["posts"][0]["music"] == MUSIC
    assert mf.validate_manifest(day, date) == []


def test_stage_never_publishes_an_image_story_without_its_reel_from_the_switch(tmp_path):
    code, _, _ = stage(tmp_path, WEEKDAY, reel=False)
    assert code == 2                                                                              # nothing staged: no feed-image fallback


def test_stage_needs_the_reels_still_and_its_music(tmp_path):
    assert stage(tmp_path / "a", WEEKDAY, still=False)[0] == 2
    assert stage(tmp_path / "b", WEEKDAY, music=False)[0] == 2


def test_before_the_switch_an_image_story_still_stages_without_a_reel(tmp_path):
    code, dest, _ = stage(tmp_path, BEFORE, reel=False, music=False)
    assert code == 0 and sorted(p.name for p in dest.iterdir()) == sorted(f"{f}.jpg" for f in IMAGES)


def test_check_spec_lists_the_reel_and_its_still_for_the_media_commit(tmp_path):
    code, dest, spec = stage(tmp_path, WEEKDAY)
    assert code == 0
    out = tmp_path / "files.txt"
    assert mf.main(["--repo", str(tmp_path / "repo"), "check-spec", "--spec", str(spec), "--list-out", str(out)]) == 0
    listed = out.read_text(encoding="utf-8").split()
    for name in (f"v/{WEEKDAY}/{SID}/reel_9x16.mp4", f"v/{WEEKDAY}/{SID}/still/reel_9x16.jpg", f"v/{WEEKDAY}/{SID}/still/reel_9x16.png",
                 f"v/{WEEKDAY}/{SID}/music.json", f"v/{WEEKDAY}/{SID}/story_9x16.jpg"):
        assert name in listed, name


# ---- the render hook ------------------------------------------------------------------------------------------------------
def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def categories_dir(root: Path, date: str, reel=True, qa_pass=True, music=True, mp4=MP4, source_bytes=PNG, rqa_pass=True):
    d = root / SID
    (d / "evidence").mkdir(parents=True)
    for f in IMAGES:
        (d / f"{f}.png").write_bytes(source_bytes if f == "story_9x16" else PNG)
        (d / f"{f}.jpg").write_bytes(JPG)
    (d / "qa.json").write_text(json.dumps({"pass": True}), encoding="utf-8")
    index = f"https://asafb2k.github.io/rapidtradeview-media/v/{date}/{SID}/evidence/index.json"
    (d / "evidence" / "index.json").write_text("{}", encoding="utf-8")
    pkg = {**package(), "source_urls": [index, "https://www.rapidtradeview.trade/earnings/this-week"], "evidence": {"index_url": index, "files": ["index.json"]}}
    (d / "post-package.json").write_text(json.dumps(pkg), encoding="utf-8")
    if reel:
        (d / "still").mkdir()
        (d / "reel_9x16.mp4").write_bytes(MP4)
        (d / "still" / "reel_9x16.png").write_bytes(PNG)
        (d / "still" / "reel_9x16.jpg").write_bytes(JPG)
        (d / "vsco-instruments.json").write_text("{}", encoding="utf-8")
        (d / "reel-qa.json").write_text(json.dumps({"pass": rqa_pass}), encoding="utf-8")
        (d / "reel.json").write_text(json.dumps({
            "qa_pass": qa_pass, "source": {"file": "story_9x16.png", "sha256": sha(PNG)}, "files": {"reel_9x16.mp4": sha(MP4)},
            "music": MUSIC if music else None}), encoding="utf-8")
        if mp4 != MP4:
            (d / "reel_9x16.mp4").write_bytes(mp4)
        (d / "story_9x16.png").write_bytes(source_bytes)
    return d


def run_hook(tmp_path, monkeypatch, date, **kw):
    cats = tmp_path / "categories"
    categories_dir(cats, date, **kw)
    monkeypatch.setattr(hook, "CATEGORIES_OUT", cats)
    data = {"schema": "rtv-daily-story/1", "date": date, "story_id": SID, "category": "earnings_week", "story": {"mode": "week_ahead"}}
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out"
    code = hook.main(["--data", str(data_file), "--out", str(out), "--use-existing", SID])
    return code, out


def test_the_hook_runs_the_reel_step_from_the_switch_only():
    data = lambda date: {"story_id": SID, "date": date, "category": "earnings_week", "story": {"mode": "week_ahead"}}
    steps = hook.image_steps(data(WEEKDAY), "py")
    assert steps[-1] == ["py", "scripts/v6cat/still_reel.py", "--id", SID] and steps[-2][1].endswith("qa_stills.py")
    assert not any("still_reel" in " ".join(s) for s in hook.image_steps(data("2026-10-09"), "py"))   # a Friday render before the switch


def test_the_hook_copies_the_reel_and_writes_its_music_into_the_work_package(tmp_path, monkeypatch):
    code, out = run_hook(tmp_path, monkeypatch, WEEKDAY)
    assert code == 0
    for n in hook.REEL_FILES + hook.REEL_AUDIT_FILES[:2]:
        assert (out / n).is_file(), n
    pkg = json.loads((out / "post-package.json").read_text(encoding="utf-8"))
    assert pkg["music"] == MUSIC and "instagram" in pkg


@pytest.mark.parametrize("kw", [
    {"reel": False},                                       # no Reel at all
    {"qa_pass": False},                                    # reel.json says the QA did not pass
    {"rqa_pass": False},                                   # reel-qa.json says it did not
    {"music": False},                                      # no provenance
    {"mp4": MP4 + b"edited"},                              # an MP4 reel.json did not hash (a stale / edited Reel)
    {"source_bytes": PNG + b"changed"},                    # built from a different image than the one now in the story
])
def test_the_hook_skips_a_story_whose_reel_is_missing_stale_or_failed(tmp_path, monkeypatch, capsys, kw):
    code, out = run_hook(tmp_path, monkeypatch, WEEKDAY, **kw)
    assert code == 1
    assert "story skipped" in capsys.readouterr().out
    assert not (out / "reel_9x16.mp4").exists()


def test_the_hook_needs_no_reel_before_the_switch(tmp_path, monkeypatch):
    code, out = run_hook(tmp_path, monkeypatch, BEFORE, reel=False)
    assert code == 0 and not (out / "reel_9x16.mp4").exists()
    assert "music" not in json.loads((out / "post-package.json").read_text(encoding="utf-8"))
