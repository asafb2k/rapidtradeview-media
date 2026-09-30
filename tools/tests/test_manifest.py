"""Manifest rules (mirrors frontend/src/lib/socialKitVideos.test.ts). Run: python -m pytest tools/tests -q"""
import copy
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import manifest as mf  # noqa: E402

REAL = TOOLS.parent / "v" / "2026-09-27" / "manifest.json"


@pytest.fixture()
def m():
    return json.loads(REAL.read_text(encoding="utf-8"))


def test_real_manifest_is_valid(m):
    assert mf.validate_manifest(m, "2026-09-27") == []


def test_other_day_is_rejected(m):
    assert "manifest: date 2026-09-27 is not 2026-09-28" in mf.validate_manifest(m, "2026-09-28")


@pytest.mark.parametrize("mutate,needle", [
    (lambda m: m["posts"][0]["platforms"]["x"].__setitem__("text", "@dkhos " + m["posts"][0]["platforms"]["x"]["text"]), 'must not contain "@"'),
    (lambda m: m["posts"][0]["platforms"]["x"].__setitem__("reply", "see @uber"), 'platforms.x.reply: X text must not contain "@"'),
    (lambda m: m["posts"][0]["platforms"]["threads"].__setitem__("text", "No disclaimer."), 'threads.text: missing "Not investment advice."'),
    (lambda m: m["posts"][0]["platforms"]["pinterest"].__setitem__("description", m["posts"][0]["platforms"]["pinterest"]["description"] + " #InsiderTrading"), "#insidertrading is never used"),
    (lambda m: m["posts"][0]["media"].__setitem__("reel_9x16", "https://example.com/x.mp4"), "media.reel_9x16: must be https://asafb2k.github.io"),
    (lambda m: m["posts"][0]["platforms"]["pinterest"].__setitem__("link", "https://evil.example/UBER"), "pinterest.link: must be an https link on www.rapidtradeview.trade"),
    (lambda m: m["posts"][0].__setitem__("extra", 1), "unknown field 'extra'"),
    (lambda m: m["posts"][0]["tag_candidates"].__setitem__("x", [{"handle": "@dkhos", "verified": False}]), "only instagram and threads"),
    (lambda m: m["posts"][0]["platforms"]["x"].__setitem__("text", "a" * 270 + " Not investment advice."), "platforms.x.text: 293 characters, over the 280 limit"),
    (lambda m: m["posts"][0]["platforms"]["instagram"].__setitem__("placement", "story"), "a Story has no caption"),
    (lambda m: m["posts"].append(copy.deepcopy(m["posts"][0])), "2 posts; a weekend has at most 1"),
    (lambda m: m["posts"][0].__setitem__("title", "bad\u202etitle"), "title: contains control or invisible characters"),
])
def test_rules(m, mutate, needle):
    mutate(m)
    errors = mf.validate_manifest(m, "2026-09-27")
    assert any(needle in e for e in errors), errors


def test_x_weighted_length_matches_the_kit():
    assert mf.x_weighted_length("https://www.sec.gov/Archives/edgar/data/1/2/primarydocument.xml") == 23
    assert mf.x_weighted_length("Amazon.com") == 23
    assert mf.x_weighted_length("C3.ai") == 5
    assert mf.x_weighted_length("é") == 1 and mf.x_weighted_length("\u4e2d") == 2


# Weekdays (KIT_AUDIT_FIXES_LIVE, audit 2026-09-28): 1 Reel + 4 feed posts, no Story (the Story slots 1 and 4 are feed posts).
@pytest.mark.parametrize("slots,want", [
    ([1, 2, 3, 4, 5, 6, 7], {2: "reel", 1: "feed", 4: "feed", 3: "feed", 6: "feed"}),
    ([1, 2, 3, 4, 6, 7], {2: "reel", 1: "feed", 4: "feed", 3: "feed", 6: "feed"}),
    ([1, 3, 4, 6], {3: "reel", 1: "feed", 4: "feed", 6: "feed"}),
    ([1, 2, 3, 5, 6, 7], {2: "reel", 1: "feed", 3: "feed", 6: "feed", 5: "feed"}),  # no picks post: the 4th feed moves on
    ([2], {2: "reel"}),
])
def test_instagram_weekday_mix(slots, want):
    assert mf.assign_instagram(slots, "weekday", {}) == want


def test_instagram_placement_is_held_for_the_picks_pass():
    # 05:00 pass: slots 1-3, 6, 7; the picks slot (4) is filled at 13:45 and keeps its feed post.
    morning = mf.assign_instagram([1, 2, 3, 6, 7], "weekday", {}, mf.reserved_ig())
    assert morning == {1: "feed", 2: "reel", 3: "feed", 6: "feed"}
    kept = {**morning, 7: "none"}
    assert mf.assign_instagram([1, 2, 3, 5, 6, 7], "weekday", kept, mf.reserved_ig()) == morning  # 10:00: the report gets none
    assert mf.assign_instagram([1, 2, 3, 4, 6, 7], "weekday", kept, mf.reserved_ig()) == {**morning, 4: "feed"}  # 13:45


def test_grid_moves_picks_and_report():
    assert mf.WEEKDAY_SLOTS[4] == "15:00" and mf.WEEKDAY_SLOTS[5] == "16:00"
    assert mf.PASS_TIMES == {"morning": "05:00", "reports": "10:00", "picks": "13:45"}
    # owner 2026-09-30: 1-2 posts per platform per day; HQ quality rule: the morning post is slot 2 (trade) or 1 (earnings)
    assert mf.PASSES == {"morning": (1, 2), "reports": (5, 7), "picks": (4,)}


def test_instagram_weekend_is_one_reel():
    assert mf.assign_instagram([1], "weekend", {}) == {1: "reel"}


def test_build_merges_and_keeps_placements(m, tmp_path):
    # Rebuild the real post from its spec: identical to what was published, apart from the timestamp.
    spec = {"date": "2026-09-27", "posts": [{
        "slot": 1, "time_et": "12:00", "category": "insider_trade", "story_id": "uber-khosrowshahi",
        "story_key": m["posts"][0]["story_key"], "tickers": ["UBER"], "people": ["Dara Khosrowshahi"],
        "post_package": "D:/rtv-ops/tracks/growth/research/video-v6/uber-khosrowshahi/post-package.json"}]}
    if not Path(spec["posts"][0]["post_package"]).exists():
        pytest.skip("post-package not on this machine")
    # The writer only needs the three MP4s present (their URLs come from the date and story_id): stand-ins in a
    # temporary repo, so this also runs in a sparse clone without the published videos.
    d = tmp_path / "v" / "2026-09-27" / "uber-khosrowshahi"
    d.mkdir(parents=True)
    for f in mf.FORMATS:
        (d / f"{f}.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100)
    built = mf.build_manifest(spec, existing=m, repo=tmp_path)
    built["generated_at"] = m["generated_at"]
    # Manifests written since image posts name each platform's media_type; the published one predates it.
    for block in built["posts"][0]["platforms"].values():
        assert block.pop("media_type") == "video"
    # Manifests written since the audit fixes name the Threads topic (a Form 4 trade: Stocks); the published one predates it.
    assert built["posts"][0]["platforms"]["threads"].pop("topic") == "Stocks"
    assert built == m


UBER_PKG = Path("D:/rtv-ops/tracks/growth/research/video-v6/uber-khosrowshahi/post-package.json")


def image_repo(tmp_path, formats=("feed_4x5", "square_1x1", "pin_2x3", "story_9x16"), ext="png"):
    d = tmp_path / "v" / "2026-09-28" / "earnings-week-image"
    d.mkdir(parents=True)
    for f in formats:
        (d / f"{f}.{ext}").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return tmp_path


def image_spec(**extra):
    return {"date": "2026-09-28", "posts": [dict({
        "slot": 1, "time_et": "08:00", "category": "earnings_week", "story_id": "earnings-week-image",
        "story_key": "earnings:week:2026-09-28", "tickers": ["MU"], "people": [], "instagram_placement": "story",
        "post_package": str(UBER_PKG)}, **extra)]}


@pytest.mark.skipif(not UBER_PKG.exists(), reason="post-package not on this machine")
def test_image_post_uses_each_platforms_image(tmp_path):
    repo = image_repo(tmp_path)
    m = mf.build_manifest(image_spec(), repo=repo)
    assert mf.validate_manifest(m, "2026-09-28") == []
    post = m["posts"][0]
    assert post["media"] == {} and set(post["images"]) == set(mf.IMAGE_FORMATS)
    got = {k: (v["media_type"], v["media"]) for k, v in post["platforms"].items()}
    # The spec asks for a Story; with KIT_AUDIT_FIXES_LIVE it is a feed post, which takes the 4:5 image.
    assert got == {"instagram": ("image", "feed_4x5"), "x": ("image", "square_1x1"), "threads": ("image", "feed_4x5"), "pinterest": ("image", "pin_2x3")}
    assert post["platforms"]["pinterest"]["media_url"].endswith("/earnings-week-image/pin_2x3.png")


@pytest.mark.skipif(not UBER_PKG.exists(), reason="post-package not on this machine")
def test_image_post_takes_the_next_image_and_refuses_a_missing_one(tmp_path):
    repo = image_repo(tmp_path, formats=("feed_4x5", "story_9x16"), ext="jpg")
    m = mf.build_manifest(image_spec(), repo=repo)
    assert mf.validate_manifest(m, "2026-09-28") == []
    plats = m["posts"][0]["platforms"]
    assert (plats["x"]["media"], plats["pinterest"]["media"]) == ("feed_4x5", "feed_4x5")
    # The Instagram feed post takes only the 4:5 image (never the Story's 9:16 one): without it the post is refused.
    with pytest.raises(ValueError, match="Instagram feed needs feed_4x5"):
        mf.build_manifest(image_spec(), repo=image_repo(tmp_path / "b", formats=("square_1x1", "pin_2x3", "story_9x16")))


def test_image_posts_are_never_the_reel():
    assert mf.assign_instagram([1, 2, 3], "weekday", {}, image_slots={2}) == {3: "reel", 1: "feed", 2: "feed"}
    assert mf.assign_instagram([1], "weekend", {}, image_slots={1}) == {1: "feed"}


@pytest.mark.skipif(not UBER_PKG.exists(), reason="post-package not on this machine")
@pytest.mark.parametrize("mutate,needle", [
    (lambda p: p["platforms"]["x"].__setitem__("media_url", p["images"]["feed_4x5"]), "platforms.x.media_url: must be the post's images.square_1x1"),
    (lambda p: p["images"].__setitem__("pin_2x3", p["images"]["pin_2x3"].replace(".png", ".gif")), "images.pin_2x3: must be"),
    (lambda p: p["platforms"]["instagram"].update(placement="reel"), "an image post is never a Reel"),
    (lambda p: p["platforms"]["threads"].update(media="story_9x16"), "threads.media: must be feed_4x5 or square_1x1 for an image"),
    (lambda p: p.__setitem__("images", {}), "images: leave it out"),
])
def test_image_rules(tmp_path, mutate, needle):
    m = mf.build_manifest(image_spec(), repo=image_repo(tmp_path))
    mutate(m["posts"][0])
    assert any(needle in e for e in mf.validate_manifest(m, "2026-09-28")), mf.validate_manifest(m, "2026-09-28")


def test_expected_types():
    assert [mf.expected_type(u) for u in ("a/b.mp4", "a/b.png", "a/b.jpg")] == ["video/mp4", "image/png", "image/jpeg"]


def as_tuesday(m, x_text):
    m = copy.deepcopy(m)
    m["date"], m["day_type"] = "2026-09-29", "weekday"
    p = m["posts"][0]
    p["id"] = f"video-2026-09-29-{p['story_id']}"
    for k, v in p["media"].items():
        p["media"][k] = v.replace("/2026-09-27/", "/2026-09-29/")
    for plat in p["platforms"].values():
        plat["media_url"] = plat["media_url"].replace("/2026-09-27/", "/2026-09-29/")
    p["platforms"]["x"]["text"] = x_text
    return m


@pytest.mark.parametrize("text,ok", [
    ("Dara Khosrowshahi bought Uber. Not investment advice. #InsiderBuying", True),
    ("Dara Khosrowshahi bought Uber. Not investment advice.", False),                   # no hashtag
    ("#1 pick. Not investment advice. #InsiderBuying #Form4", False),                   # two ("#1" is not a hashtag)
    ("#1 $UBER pick, #2 $GME. Not investment advice. #Stocks", True),
    ("a" * 250 + " Not investment advice. #InsiderBuying", False),                      # 288 weighted with the hashtag
])
def test_x_one_hashtag_inside_280_from_2026_09_29(m, text, ok):
    errors = mf.validate_manifest(as_tuesday(m, text), "2026-09-29")
    assert (not [e for e in errors if "platforms.x.text" in e]) == ok, errors


def test_x_hashtag_rule_starts_2026_09_29(m):
    assert mf.X_HASHTAG.findall(m["posts"][0]["platforms"]["x"]["text"]) == []
    assert mf.validate_manifest(m, "2026-09-27") == []


def video_repo(tmp_path, sids):
    for sid in sids:
        d = tmp_path / "v" / "2026-09-29" / sid
        d.mkdir(parents=True)
        for f in mf.FORMATS:
            (d / f"{f}.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100)
    return tmp_path


@pytest.mark.skipif(not UBER_PKG.exists(), reason="post-package not on this machine")
def test_promo_reel_comes_on_top_of_the_instagram_mix(tmp_path):
    repo = video_repo(tmp_path, ["trade-a", "promo"])
    post = lambda slot, cat, sid: {"slot": slot, "time_et": mf.WEEKDAY_SLOTS[slot], "category": cat, "story_id": sid,
                                   "story_key": f"k:{sid}", "tickers": [], "people": [], "post_package": str(UBER_PKG)}
    day = mf.build_manifest({"date": "2026-09-29", "posts": [post(2, "insider_trade", "trade-a")]}, repo=repo)
    m = mf.build_manifest({"date": "2026-09-29", "posts": [post(8, "product_promo", "promo")]}, existing=day, repo=repo)
    ig = {p["slot"]: p["platforms"]["instagram"]["placement"] for p in m["posts"]}
    assert ig == {2: "reel", 8: "reel"}            # the trade keeps the day's one Reel; the promo is extra
    for p in m["posts"]:                           # the Uber package predates the one-hashtag X rule
        p["platforms"]["x"]["text"] += " #Stocks"
    assert mf.validate_manifest(m, "2026-09-29") == []
    m["posts"][1]["category"] = "insider_trade"    # a second Reel that is not a promo still breaks the mix
    assert any("2 Instagram reel posts" in e for e in mf.validate_manifest(m, "2026-09-29"))


def test_check_spec_lists_a_video_posts_still_for_the_media_commit(tmp_path):
    """The still (still/feed_4x5.jpg + .png, Threads web fallback) ships in the same commit as the MP4s; not in the manifest."""
    repo = video_repo(tmp_path, ["trade-a"])
    pkg = tmp_path / "post-package.json"
    pkg.write_text("{}", encoding="utf-8")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"date": "2026-09-29", "posts": [{"slot": 2, "story_id": "trade-a", "post_package": str(pkg)}]}),
                    encoding="utf-8")
    out = tmp_path / "files.txt"
    assert mf.main(["--repo", str(repo), "check-spec", "--spec", str(spec), "--list-out", str(out)]) == 0
    assert not any("still/" in x for x in out.read_text(encoding="utf-8").split())
    still = repo / "v" / "2026-09-29" / "trade-a" / "still"
    still.mkdir()
    (still / "feed_4x5.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    (still / "feed_4x5.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    assert mf.main(["--repo", str(repo), "check-spec", "--spec", str(spec), "--list-out", str(out)]) == 0
    listed = out.read_text(encoding="utf-8").split()
    assert "v/2026-09-29/trade-a/still/feed_4x5.jpg" in listed and "v/2026-09-29/trade-a/still/feed_4x5.png" in listed
    assert "v/2026-09-29/trade-a/reel_9x16.mp4" in listed


# ---------------------------------------------------------------------------
# Social-post audit 2026-09-28: Instagram videos 9:16, Story slots -> feed posts, Threads topic (KIT_AUDIT_FIXES_LIVE)

DAY = {1: "earnings_week", 2: "insider_trade", 3: "insider_trade", 4: "daily_picks", 5: "earnings_report",
       6: "congress_trade", 7: "congress_theme"}


@pytest.fixture()
def live(monkeypatch):
    monkeypatch.setattr(mf, "KIT_AUDIT_FIXES_LIVE", True)


def day_spec(slots, date="2026-09-29"):
    return {"date": date, "posts": [{"slot": s, "time_et": mf.WEEKDAY_SLOTS[s], "category": DAY[s], "story_id": f"story-{s}",
                                     "story_key": f"ptr:{s}:X:buy" if DAY[s].startswith("congress") else f"form4:{s}:X",
                                     "tickers": [], "people": [], "post_package": str(UBER_PKG)} for s in slots]}


def one_hashtag(m):
    for p in m["posts"]:                           # the Uber package predates the one-hashtag X rule
        if mf.X_HASHTAG.search(p["platforms"]["x"]["text"]) is None:
            p["platforms"]["x"]["text"] += " #Stocks"
    return m


def ig(m):
    return {p["slot"]: (p["platforms"]["instagram"]["placement"], p["platforms"]["instagram"]["media"])
            for p in m["posts"] if "instagram" in p["platforms"]}


def test_audit_fixes_are_on_with_the_kit_on_prod():
    # The social kit release (growth/kit-audit-fixes, PR #400) on prod takes a 9:16 feed video, up to 4 feed posts
    # and Stories besides the Reel, and "topic", and still takes the older shape (4:5 feed videos, Stories, no topic).
    assert mf.KIT_AUDIT_FIXES_LIVE is True
    assert mf.ig_weekday_mix() == {"reel": 1, "feed": 4, "story": 0} and mf.reserved_ig() == {4: "feed"}
    assert {p: mf.ig_video_format(p) for p in mf.IG_PLACEMENTS} == {"reel": "reel_9x16", "feed": "reel_9x16", "story": "reel_9x16"}


@pytest.mark.skipif(not UBER_PKG.exists(), reason="post-package not on this machine")
def test_on_the_writer_makes_the_new_shape_and_the_validator_still_takes_the_old_one(monkeypatch, tmp_path):
    slots = [1, 2, 3, 5, 6, 7]
    repo = video_repo(tmp_path, [f"story-{s}" for s in slots])
    m = one_hashtag(mf.build_manifest(day_spec(slots), repo=repo))
    assert ig(m) == {1: ("feed", "reel_9x16"), 2: ("reel", "reel_9x16"), 3: ("feed", "reel_9x16"), 6: ("feed", "reel_9x16")}
    assert {p["slot"]: p["platforms"]["threads"]["topic"] for p in m["posts"]} == {
        1: "Earnings", 2: "Stocks", 3: "Stocks", 5: "Earnings", 6: "Stock Market", 7: "Stock Market"}
    assert mf.validate_manifest(m, "2026-09-29") == []
    # The same day as the writer made it before the switch (a Story, 4:5 feed videos, no topic) stays valid:
    # the kit takes both, so a manifest published before the switch is never rejected.
    monkeypatch.setattr(mf, "KIT_AUDIT_FIXES_LIVE", False)
    old = one_hashtag(mf.build_manifest(day_spec(slots), repo=repo))
    monkeypatch.setattr(mf, "KIT_AUDIT_FIXES_LIVE", True)
    assert ig(old) == {1: ("story", "reel_9x16"), 2: ("reel", "reel_9x16"), 3: ("feed", "feed_4x5"), 6: ("feed", "feed_4x5")}
    assert all("topic" not in p["platforms"]["threads"] for p in old["posts"])
    assert mf.validate_manifest(old, "2026-09-29") == []
    # Still rejected: a feed video that is neither the 9:16 nor the 4:5 file, a topic outside the kit's list.
    p3 = next(p for p in m["posts"] if p["slot"] == 3)
    p3["platforms"]["instagram"].update(media="square_1x1", media_url=p3["media"]["square_1x1"])
    p3["platforms"]["threads"]["topic"] = "Finance"
    errors = mf.validate_manifest(m, "2026-09-29")
    assert "posts[2].platforms.instagram.media: must be reel_9x16 or feed_4x5 for a video" in errors
    assert "posts[2].platforms.threads.topic: must be one of Stocks, Stock Market, Earnings, Investing" in errors


def test_live_weekday_mix_is_one_reel_and_four_feed_posts(live):
    assert mf.assign_instagram([1, 2, 3, 4, 5, 6, 7], "weekday", {}) == {2: "reel", 1: "feed", 3: "feed", 4: "feed", 6: "feed"}
    assert mf.assign_instagram([1, 3, 4, 6], "weekday", {}) == {3: "reel", 1: "feed", 4: "feed", 6: "feed"}
    assert mf.assign_instagram([1, 2, 3], "weekday", {}, image_slots={1}) == {2: "reel", 1: "feed", 3: "feed"}
    assert mf.assign_instagram([1], "weekend", {}) == {1: "reel"}
    assert mf.assign_instagram([1], "weekend", {}, image_slots={1}) == {1: "feed"}


def test_live_the_picks_slot_keeps_a_feed_post_for_the_picks_pass(live):
    assert mf.reserved_ig() == {4: "feed"}
    morning = mf.assign_instagram([1, 2, 3, 6, 7], "weekday", {}, mf.reserved_ig())
    assert morning == {1: "feed", 2: "reel", 3: "feed", 6: "feed"}
    kept = {**morning, 7: "none"}
    assert mf.assign_instagram([1, 2, 3, 5, 6, 7], "weekday", kept, mf.reserved_ig()) == morning  # 10:00: the report gets none
    assert mf.assign_instagram([1, 2, 3, 4, 6, 7], "weekday", kept, mf.reserved_ig()) == {**morning, 4: "feed"}  # 13:45


def test_live_switch_day_a_published_story_counts_against_the_four(live):
    # Morning written before the switch (a Story in slot 1); the picks pass runs after it.
    kept = {1: "story", 2: "reel", 3: "feed", 6: "feed", 7: "none"}
    placed = {k: v for k, v in kept.items() if v != "none"}
    assert mf.assign_instagram([1, 2, 3, 4, 6, 7], "weekday", kept, mf.reserved_ig()) == {**placed, 4: "feed"}
    # Two published Stories: the picks slot is the 4th besides the Reel; then nothing is left for the report (5).
    kept2 = {**kept, 6: "story"}
    assert mf.assign_instagram([1, 2, 3, 4, 6, 7], "weekday", kept2, mf.reserved_ig()) == {**placed, 6: "story", 4: "feed"}
    kept3 = {**kept2, 4: "feed"}
    assert mf.assign_instagram([1, 2, 3, 4, 5, 6, 7], "weekday", kept3, mf.reserved_ig()) == {k: v for k, v in kept3.items() if v != "none"}


@pytest.mark.skipif(not UBER_PKG.exists(), reason="post-package not on this machine")
def test_live_every_instagram_video_is_9x16_and_threads_has_its_topic(live, tmp_path):
    slots = [1, 2, 3, 4, 5, 6, 7]
    m = one_hashtag(mf.build_manifest(day_spec(slots), repo=video_repo(tmp_path, [f"story-{s}" for s in slots])))
    assert ig(m) == {1: ("feed", "reel_9x16"), 2: ("reel", "reel_9x16"), 3: ("feed", "reel_9x16"), 4: ("feed", "reel_9x16"),
                     6: ("feed", "reel_9x16")}
    for p in m["posts"]:
        if "instagram" in p["platforms"]:
            assert p["platforms"]["instagram"]["media_url"] == p["media"]["reel_9x16"]
            assert p["platforms"]["instagram"]["caption"] and p["platforms"]["instagram"]["link_sticker_url"] is None
    assert {p["slot"]: p["platforms"]["threads"]["topic"] for p in m["posts"]} == {
        1: "Earnings", 2: "Stocks", 3: "Stocks", 4: "Stocks", 5: "Earnings", 6: "Stock Market", 7: "Stock Market"}
    assert list(m["posts"][0]["platforms"]["threads"])[-1] == "topic"
    assert mf.validate_manifest(m, "2026-09-29") == []
    # The same manifest under the prod kit's rules is rejected: why the flag waits for the kit release.
    mf.KIT_AUDIT_FIXES_LIVE = False
    errors = mf.validate_manifest(m, "2026-09-29")
    assert "manifest: 4 Instagram feed posts; a weekday has at most 2" in errors
    assert any(e.endswith("threads: unknown field 'topic'") for e in errors)
    assert any(e.endswith("instagram.media: must be feed_4x5 for a video") for e in errors)


@pytest.mark.skipif(not UBER_PKG.exists(), reason="post-package not on this machine")
def test_live_a_specs_story_becomes_a_feed_post_and_images_keep_4x5(live, tmp_path):
    m = mf.build_manifest(image_spec(), repo=image_repo(tmp_path))   # the spec asks for a Story
    block = m["posts"][0]["platforms"]["instagram"]
    assert (block["placement"], block["media_type"], block["media"], block["link_sticker_url"]) == ("feed", "image", "feed_4x5", None)
    assert mf.NOT_ADVICE in block["caption"]
    assert m["posts"][0]["platforms"]["threads"]["topic"] == "Earnings"
    assert mf.validate_manifest(m, "2026-09-28") == []


@pytest.mark.skipif(not UBER_PKG.exists(), reason="post-package not on this machine")
def test_live_merge_keeps_a_published_story_and_stays_valid(monkeypatch, tmp_path):
    repo = video_repo(tmp_path, [f"story-{s}" for s in [1, 2, 3, 4, 6, 7]])
    monkeypatch.setattr(mf, "KIT_AUDIT_FIXES_LIVE", False)          # the morning pass ran before the switch
    morning = one_hashtag(mf.build_manifest(day_spec([1, 2, 3, 6, 7]), repo=repo))
    assert ig(morning)[1] == ("story", "reel_9x16") and ig(morning)[3] == ("feed", "feed_4x5")
    monkeypatch.setattr(mf, "KIT_AUDIT_FIXES_LIVE", True)           # the picks pass runs after it
    picks = one_hashtag(mf.build_manifest(day_spec([4]), existing=morning, repo=repo))
    assert ig(picks) == {**ig(morning), 4: ("feed", "reel_9x16")}
    assert mf.validate_manifest(picks, "2026-09-29") == []


def test_live_validator_caps_and_topics(live, m):
    tue = as_tuesday(m, "Dara Khosrowshahi bought Uber. Not investment advice. #InsiderBuying")
    base = tue["posts"][0]

    def day(placements):
        out = copy.deepcopy(tue)
        out["posts"] = []
        for i, pl in enumerate(placements):
            p = copy.deepcopy(base)
            sid = f"story-{i + 1}"
            p.update(slot=i + 1, story_id=sid, id=f"video-2026-09-29-{sid}",
                     media={f: mf.media_url("2026-09-29", sid, f) for f in mf.FORMATS})
            for plat in p["platforms"].values():
                plat["media_url"] = p["media"][plat["media"]]
            p["platforms"]["instagram"].update(placement=pl, media="reel_9x16", media_url=p["media"]["reel_9x16"])
            if pl == "story":
                p["platforms"]["instagram"].update(caption=None, first_comment=None)
            out["posts"].append(p)
        return out

    assert mf.validate_manifest(day(["feed", "reel", "feed", "feed", "feed"]), "2026-09-29") == []
    assert mf.validate_manifest(day(["story", "reel", "feed", "story", "feed"]), "2026-09-29") == []
    assert mf.validate_manifest(day(["story", "reel", "feed", "feed", "feed", "feed"]), "2026-09-29") == [
        "manifest: 5 Instagram feed posts and Stories; a weekday has at most 4 besides the Reel"]
    assert mf.validate_manifest(day(["story", "reel", "story", "story"]), "2026-09-29") == [
        "manifest: 3 Instagram story posts; a weekday has at most 2"]
    feed_4x5 = day(["feed"])
    feed_4x5["posts"][0]["platforms"]["instagram"].update(media="feed_4x5", media_url=feed_4x5["posts"][0]["media"]["feed_4x5"])
    assert mf.validate_manifest(feed_4x5, "2026-09-29") == []          # written before the switch
    reel_4x5 = day(["reel"])
    reel_4x5["posts"][0]["platforms"]["instagram"].update(media="feed_4x5", media_url=reel_4x5["posts"][0]["media"]["feed_4x5"])
    assert "posts[0].platforms.instagram.media: must be reel_9x16 for a video" in mf.validate_manifest(reel_4x5, "2026-09-29")
    for topic in mf.THREADS_TOPICS:
        tue["posts"][0]["platforms"]["threads"]["topic"] = topic
        assert mf.validate_manifest(tue, "2026-09-29") == []
    for bad in ("stocks", "insidertrading", None):
        tue["posts"][0]["platforms"]["threads"]["topic"] = bad
        assert "posts[0].platforms.threads.topic: must be one of Stocks, Stock Market, Earnings, Investing" in mf.validate_manifest(tue, "2026-09-29")
    del tue["posts"][0]["platforms"]["threads"]["topic"]
    tue["posts"][0]["platforms"]["x"]["topic"] = "Stocks"
    assert "posts[0].platforms.x: unknown field 'topic'" in mf.validate_manifest(tue, "2026-09-29")


def test_live_published_manifests_stay_valid(live, m):
    # Written before the switch (4:5 feed videos, Stories, no topic): still valid, as the new kit accepts them.
    assert mf.validate_manifest(m, "2026-09-27") == []
    for date in ("2026-09-28", "2026-09-29"):
        path = TOOLS.parent / "v" / date / "manifest.json"
        if path.exists():
            assert mf.validate_manifest(json.loads(path.read_text(encoding="utf-8")), date) == [], date


def test_threads_topic_covers_every_category():
    assert set(mf.THREADS_TOPIC_BY_CATEGORY) == set(mf.CATEGORIES)
    assert set(mf.THREADS_TOPIC_BY_CATEGORY.values()) <= set(mf.THREADS_TOPICS)
    assert mf.threads_topic("person_spotlight", "ptr:20035326:PG:sell") == "Stock Market"
    assert mf.threads_topic("person_spotlight", "form4:0001184237-26-000008:UBER") == "Stocks"
    assert mf.threads_topic("product_promo") == "Investing"
    assert mf.threads_topic("congress_theme", "theme:congress_bigtech:30d:AAPL") == "Stock Market"


def test_live_two_post_days_keep_the_instagram_mix(live):
    """HQ quality rule 2026-09-30: the morning post is the trade video (slot 2: the Reel) or the earnings image (slot 1:
    a feed post, never a Reel); the picks pass (slot 4) keeps its feed post either way."""
    trade = mf.assign_instagram([2], "weekday", {}, mf.reserved_ig())
    assert trade == {2: "reel"}
    assert mf.assign_instagram([2, 4], "weekday", dict(trade), mf.reserved_ig()) == {2: "reel", 4: "feed"}
    image = mf.assign_instagram([1], "weekday", {}, mf.reserved_ig(), image_slots={1})
    assert image == {1: "feed"}
    assert mf.assign_instagram([1, 4], "weekday", dict(image), mf.reserved_ig()) == {1: "feed", 4: "feed"}
