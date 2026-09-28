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


@pytest.mark.parametrize("slots,want", [
    ([1, 2, 3, 4, 5, 6, 7], {2: "reel", 1: "story", 4: "story", 3: "feed", 6: "feed"}),
    ([1, 2, 3, 4, 6, 7], {2: "reel", 1: "story", 4: "story", 3: "feed", 6: "feed"}),
    ([1, 3, 4, 6], {3: "reel", 1: "story", 4: "story", 6: "feed"}),
    ([2], {2: "reel"}),
])
def test_instagram_weekday_mix(slots, want):
    assert mf.assign_instagram(slots, "weekday", {}) == want


def test_instagram_story_is_held_for_the_picks_pass():
    # 06:15 pass: slots 1-3, 6, 7; the picks slot (4) is filled at 13:45 and keeps its Story.
    morning = mf.assign_instagram([1, 2, 3, 6, 7], "weekday", {}, mf.RESERVED_IG)
    assert morning == {1: "story", 2: "reel", 3: "feed", 6: "feed"}
    kept = {**morning, 7: "none"}
    assert mf.assign_instagram([1, 2, 3, 5, 6, 7], "weekday", kept, mf.RESERVED_IG) == morning  # 10:30: the report gets none
    assert mf.assign_instagram([1, 2, 3, 4, 6, 7], "weekday", kept, mf.RESERVED_IG) == {**morning, 4: "story"}  # 13:45


def test_grid_moves_picks_and_report():
    assert mf.WEEKDAY_SLOTS[4] == "14:00" and mf.WEEKDAY_SLOTS[5] == "15:00"
    assert mf.PASSES == {"morning": (1, 2, 3, 6, 7), "reports": (5, 7), "picks": (4,)}


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
    built = mf.build_manifest(spec, existing=m)
    built["generated_at"] = m["generated_at"]
    # Manifests written since image posts name each platform's media_type; the published one predates it.
    for block in built["posts"][0]["platforms"].values():
        assert block.pop("media_type") == "video"
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
    assert got == {"instagram": ("image", "story_9x16"), "x": ("image", "square_1x1"), "threads": ("image", "feed_4x5"), "pinterest": ("image", "pin_2x3")}
    assert post["platforms"]["pinterest"]["media_url"].endswith("/earnings-week-image/pin_2x3.png")


@pytest.mark.skipif(not UBER_PKG.exists(), reason="post-package not on this machine")
def test_image_post_takes_the_next_image_and_refuses_a_missing_one(tmp_path):
    repo = image_repo(tmp_path, formats=("feed_4x5", "story_9x16"), ext="jpg")
    m = mf.build_manifest(image_spec(), repo=repo)
    assert mf.validate_manifest(m, "2026-09-28") == []
    plats = m["posts"][0]["platforms"]
    assert (plats["x"]["media"], plats["pinterest"]["media"]) == ("feed_4x5", "feed_4x5")
    with pytest.raises(ValueError, match="Instagram story needs story_9x16"):
        mf.build_manifest(image_spec(), repo=image_repo(tmp_path / "b", formats=("feed_4x5",)))


def test_image_posts_are_never_the_reel():
    assert mf.assign_instagram([1, 2, 3], "weekday", {}, image_slots={2}) == {3: "reel", 1: "story", 2: "feed"}
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
