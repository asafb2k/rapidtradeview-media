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
    ([1, 2, 3, 4, 5, 6, 7], {2: "reel", 1: "story", 4: "story", 3: "feed", 5: "feed"}),
    ([1, 2, 3, 4, 6, 7], {2: "reel", 1: "story", 4: "story", 3: "feed", 6: "feed"}),
    ([1, 3, 4, 6], {3: "reel", 1: "story", 4: "story", 6: "feed"}),
    ([2], {2: "reel"}),
])
def test_instagram_weekday_mix(slots, want):
    assert mf.assign_instagram(slots, "weekday", {}) == want


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
    assert built == m
