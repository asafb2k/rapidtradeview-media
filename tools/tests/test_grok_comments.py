"""Comment / reply drafts and post media in tools/grok_review.py. Run: python -m pytest tools/tests -q (offline)."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(TESTS))
import facts as fx  # noqa: E402
import grok_review as gr  # noqa: E402
from test_grok_review import CONGRESS, DATE, FACTS, INSTINCT, MOVES, PATTERN, PICKS, FakeRest, good_x  # noqa: E402


@pytest.fixture(autouse=True)
def _legacy_items(monkeypatch):
    """These tests guard the link / media / length / word / free-form rules on items of facts files built before the
    verbatim rule. Review round 6 rejects such items in production (test_verbatim.py guards that gate), so here the gate
    passes them; an item WITH fact_phrases still goes through the real gate (freshness)."""
    real = gr.item_gate_reasons
    monkeypatch.setattr(gr, "item_gate_reasons",
                        lambda item, facts, now=None: real(item, facts, now) if gr.cl.verbatim_mode(item) else [])

NOW = dt.datetime(2026, 10, 12, 14, 0, tzinfo=dt.timezone.utc)
TARGET = "https://x.com/sometrader/status/1844000000000000001"
IG_TARGET = "https://www.instagram.com/p/DAbCdEfGhIj/"


def comment(**over):
    d = {"kind": "comment", "platform": "x", "target_url": TARGET,
         "text": "Thanks for sharing this chart, what stood out to you?"}   # a hook (verbatim rule, HQ 2026-10-19)
    d.update(over)
    return d


@pytest.fixture()
def state(tmp_path):
    return gr.CommentState(tmp_path / "state.json")


def approve(state, d, when=NOW, msg_id=1):
    assert gr.review_comment(d, FACTS if d.get("item_id") else None, state, when) == ("APPROVE", [])
    state.add(d, msg_id, when)


# ---------------------------------------------------------------------------
# Comments

def test_good_comment_is_approved(state):
    assert gr.review_comment(comment(), None, state, NOW) == ("APPROVE", [])
    ig = comment(platform="instagram", target_url=IG_TARGET, text="Helpful breakdown, thanks.")
    assert gr.review_comment(ig, None, state, NOW) == ("APPROVE", [])


def test_comment_with_item_numbers_is_approved_and_any_mention_rejected(state):
    d = comment(item_id=CONGRESS["item_id"],
                text="The $UNH filing shows a $15K–$50K purchase, traded Sep 24 and filed Oct 7.")
    assert gr.review_comment(d, FACTS, state, NOW) == ("APPROVE", [])
    # 10-12: the platform adds the reply-to handle; a typed one (even the author's) showed twice on the live reply
    d = comment(item_id=CONGRESS["item_id"],
                text="@sometrader the $UNH filing shows a $15K–$50K purchase, traded Sep 24 and filed Oct 7.")
    v, why = gr.review_comment(d, FACTS, state, NOW)
    assert v == "REJECT" and any("no @mentions" in r and "@sometrader" in r for r in why)


def test_comment_filing_names_are_not_numbers(state):
    # without an item a comment holds hooks only (HQ 2026-10-19): filing names with digits are not hook words
    d = comment(text="Worth reading the Form 4 and the 10-K side by side before the 8-K lands.")
    v, why = gr.review_comment(d, None, state, NOW)
    assert v == "REJECT" and all(r.startswith("comment:") for r in why)
    d = comment(item_id=CONGRESS["item_id"], text="The $UNH insider buy (Form 4) was $15K–$50K, filed Oct 7.")
    assert gr.review_comment(d, FACTS, state, NOW) == ("APPROVE", [])
    v, why = gr.review_comment(comment(item_id=CONGRESS["item_id"], text="The $UNH Form 4 shows a 4% stake."), FACTS, state, NOW)
    assert v == "REJECT" and any("4%" in r for r in why)
    v, why = gr.review_comment(comment(text="A Form 4 filing, up 4% since."), None, state, NOW)
    assert v == "REJECT" and any("needs the item_id" in r for r in why)


def test_reply_under_our_own_post_is_fine(state):
    d = comment(target_url="https://x.com/RapidTradeView/status/1844000000000000002")
    assert gr.review_comment(d, None, state, NOW) == ("APPROVE", [])


@pytest.mark.parametrize("text", [
    "Good thread, more at https://www.rapidtradeview.trade/picks",
    "Good thread, more on rapidtradeview.trade",
    "Good thread, see www.example.com/page",
])
def test_comment_link_is_rejected(state, text):
    v, why = gr.review_comment(comment(text=text), None, state, NOW)
    assert v == "REJECT" and any("no links" in r for r in why)


@pytest.mark.parametrize("phrase", ["follow us", "Check out", "DM me", "link in bio", "our app", "sign up"])
def test_comment_promo_phrase_is_rejected(state, phrase):
    v, why = gr.review_comment(comment(text=f"Nice chart work here, {phrase} for more like it."), None, state, NOW)
    assert v == "REJECT" and any("banned words" in r for r in why)


@pytest.mark.parametrize("word", ["guaranteed", "to the moon", "bitcoin", "price target", "insider trading"])
def test_comment_global_banned_words(state, word):
    v, why = gr.review_comment(comment(text=f"This one looks {word} to me honestly."), None, state, NOW)
    assert v == "REJECT" and any("banned words" in r for r in why)


def test_comment_item_prediction_words_apply(state):
    d = comment(item_id=PATTERN["item_id"], text="The $MARA wedge will resolve soon, nice chart.")
    v, why = gr.review_comment(d, FACTS, state, NOW)
    assert v == "REJECT" and any("banned words: will" in r for r in why)


def test_comment_unsupported_number_is_rejected(state):
    v, why = gr.review_comment(comment(item_id=CONGRESS["item_id"], text="$UNH up 12% since that $20K buy."), FACTS, state, NOW)
    assert v == "REJECT" and any("numbers not in allowed_numbers" in r and "12%" in r and "$20K" in r for r in why)
    v, why = gr.review_comment(comment(text="Up 12% since the filing, nice."), None, state, NOW)
    assert v == "REJECT" and any("needs the item_id" in r for r in why)
    v, why = gr.review_comment(comment(text="Nice read on $UNH."), None, state, NOW)
    assert v == "REJECT" and any("needs the item_id" in r for r in why)
    v, why = gr.review_comment(comment(item_id=CONGRESS["item_id"], text="Nice read on $MSFT."), FACTS, state, NOW)
    assert v == "REJECT" and any("cashtag not in this item: $MSFT" in r for r in why)


def test_comment_hashtags_and_other_mentions_are_rejected(state):
    v, why = gr.review_comment(comment(text="Great post #stocks #investing"), None, state, NOW)
    assert v == "REJECT" and any("no hashtags" in r for r in why)
    v, why = gr.review_comment(comment(text="@someoneelse great post"), None, state, NOW)
    assert v == "REJECT" and any("@someoneelse" in r for r in why)
    v, why = gr.review_comment(comment(platform="instagram", target_url=IG_TARGET, text="@sometrader great post"),
                               None, state, NOW)
    assert v == "REJECT" and any("no @mentions" in r for r in why)


def test_comment_length_limits(state):
    v, why = gr.review_comment(comment(text="word " * 57), None, state, NOW)   # 285 characters
    assert v == "REJECT" and any("limit 280" in r for r in why)
    ig = comment(platform="instagram", target_url=IG_TARGET, text="word " * 57)
    v, why = gr.review_comment(ig, None, state, NOW)   # within 300; not a hook (57 words, "word"): no length reason
    assert not any("limit" in r for r in why)
    v, why = gr.review_comment(dict(ig, text="word " * 61), None, state, NOW)
    assert v == "REJECT" and any("limit 300" in r for r in why)


@pytest.mark.parametrize("url,platform", [
    ("https://x.com/rapidtradeview", "x"),
    ("https://x.com/RapidTradeView/", "x"),
    ("https://www.instagram.com/rapidtradeview3/", "instagram"),
])
def test_own_account_target_is_rejected(state, url, platform):
    v, why = gr.review_comment(comment(platform=platform, target_url=url), None, state, NOW)
    assert v == "REJECT" and any("our own brand account" in r for r in why)


@pytest.mark.parametrize("url,platform", [
    ("http://x.com/sometrader/status/1", "x"),
    ("https://evil.example/sometrader/status/1", "x"),
    ("https://x.com.evil.example/sometrader/status/1", "x"),
    ("https://www.instagram.com/p/DAbCdEfGhIj/", "x"),
    ("https://x.com/sometrader", "x"),
    ("https://twitter.com/sometrader/status/1844000000000000001", "instagram"),
    (None, "x"),
])
def test_bad_targets_are_rejected(state, url, platform):
    v, why = gr.review_comment(comment(platform=platform, target_url=url), None, state, NOW)
    assert v == "REJECT" and any("target_url" in r for r in why)


def test_duplicate_text_is_rejected(state):
    approve(state, comment())
    again = comment(target_url="https://x.com/other/status/1844000000000000009",
                    text="thanks for sharing this chart; what stood out to you!!")
    v, why = gr.review_comment(again, None, state, NOW)
    assert v == "REJECT" and any(r.startswith("duplicate") for r in why)
    # exact repeats are blocked for 7 days, near-duplicates only on the same UTC day
    v, why = gr.review_comment(again, None, state, NOW + dt.timedelta(days=6))
    assert v == "REJECT" and any(r.startswith("duplicate") for r in why)
    assert gr.review_comment(again, None, state, NOW + dt.timedelta(days=7)) == ("APPROVE", [])


def test_near_duplicate_today_is_rejected(state):
    approve(state, comment())
    near = comment(target_url="https://x.com/other/status/1844000000000000009",
                   text="Thanks for sharing this chart, what stood out to you here?")
    v, why = gr.review_comment(near, None, state, NOW)
    assert v == "REJECT" and any("near-duplicate" in r for r in why)
    assert gr.review_comment(near, None, state, NOW + dt.timedelta(days=1)) == ("APPROVE", [])


def test_same_target_twice_is_rejected(state):
    approve(state, comment())
    other_text = comment(target_url="https://twitter.com/SomeTrader/status/1844000000000000001?s=20",
                         text="Different angle: the sector context matters here too.")
    v, why = gr.review_comment(other_text, None, state, NOW)
    assert v == "REJECT" and any("already got an approved comment" in r for r in why)


def test_daily_cap_is_rejected(state):
    for i in range(gr.COMMENT_CAP):
        state.add(comment(target_url=f"https://x.com/u{i}/status/{1000 + i}", text=f"distinct remark number {'abcdefghijklmnop'[i]} here"),
                  i, NOW)
    v, why = gr.review_comment(comment(), None, state, NOW)
    assert v == "REJECT" and any("daily cap" in r for r in why)
    ig = comment(platform="instagram", target_url=IG_TARGET)
    assert gr.review_comment(ig, None, state, NOW) == ("APPROVE", [])           # the cap is per platform
    assert gr.review_comment(comment(), None, state, NOW + dt.timedelta(days=1)) == ("APPROVE", [])


def test_state_round_trip_and_pruning(tmp_path):
    path = tmp_path / "sub" / "state.json"
    s = gr.CommentState(path)
    s.add(comment(), 1, NOW - dt.timedelta(days=8))
    s.add(comment(target_url="https://x.com/b/status/2", text="another distinct remark"), 2, NOW)
    s.save(NOW)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [a["msg_id"] for a in data["approved"]] == [2] and data["approved"][0]["target"] == "x:2"
    assert gr.CommentState(path).approved == data["approved"]
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(gr.StateUnreadable):
        gr.CommentState(path)


def test_comment_state_path_flag_env_default(monkeypatch, tmp_path):
    monkeypatch.delenv(gr.COMMENT_STATE_ENV, raising=False)
    assert gr.comment_state_path() == gr.DEFAULT_COMMENT_STATE
    monkeypatch.setenv(gr.COMMENT_STATE_ENV, str(tmp_path / "env.json"))
    assert gr.comment_state_path() == tmp_path / "env.json"
    assert gr.comment_state_path(str(tmp_path / "flag.json")) == tmp_path / "flag.json"


def test_unknown_kind_is_rejected():
    assert gr.draft_kind({"kind": "story"})[0] is None
    assert gr.draft_kind({})[0] == "post" and gr.draft_kind({"kind": "post"})[0] == "post"


# ---------------------------------------------------------------------------
# --inbox with comments

@pytest.fixture()
def facts_dir(tmp_path):
    d = tmp_path / "v" / DATE
    d.mkdir(parents=True)
    (d / "facts.json").write_text(json.dumps(FACTS), encoding="utf-8")
    return str(tmp_path / "v")


def comment_rows():
    good = comment()
    dup = comment(target_url="https://x.com/other/status/99", text=good["text"])
    promo = comment(target_url="https://x.com/third/status/98", text="Nice one, follow us for more")
    post = good_x(kind="post")
    return [
        {"id": 21, "kind": "report", "platform": "x", "item_id": None, "body": "DRAFT " + json.dumps(good)},
        {"id": 22, "kind": "report", "platform": "x", "item_id": None, "body": "DRAFT " + json.dumps(dup)},
        {"id": 23, "kind": "report", "platform": "x", "item_id": None, "body": "DRAFT " + json.dumps(promo)},
        {"id": 24, "kind": "report", "platform": "x", "item_id": post["item_id"], "body": "DRAFT " + json.dumps(post)},
        {"id": 25, "kind": "post_log", "platform": "x", "item_id": None, "body": "commented https://x.com/a/status/1"},
        {"id": 26, "kind": "report", "platform": "x", "item_id": None, "body": "DRAFT " + json.dumps(dict(good, kind="story"))},
    ]


def test_inbox_answers_comments_and_updates_state_only_on_approve(facts_dir, tmp_path):
    path = tmp_path / "state.json"
    rest, sent = FakeRest(comment_rows()), []
    stats = gr.run_inbox(rest, INSTINCT, "prod", facts_dir, False, lambda p, b: sent.append((p, b)) or True,
                         comment_state=path, now=NOW)
    bodies = [b for _, b in sent]
    assert bodies[0] == "APPROVE 21 comment"
    assert bodies[1].startswith("REJECT 22 comment: duplicate")
    assert bodies[2].startswith("REJECT 23 comment:") and "banned words: follow us" in bodies[2]
    assert bodies[3].splitlines()[0] == f"APPROVE 24 {CONGRESS['item_id']}"   # + playbook v2 NOTES lines
    assert bodies[4].startswith("REJECT 26 (no valid item_id): kind must be post or comment")
    assert sorted(rest.acked) == [21, 22, 23, 24, 26]                    # 25 is not a DRAFT: never acked
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [a["msg_id"] for a in data["approved"]] == [21]
    assert stats["approved"] == 2 and stats["rejected"] == 3


def test_inbox_unsent_approval_is_not_recorded(facts_dir, tmp_path):
    path = tmp_path / "state.json"
    rest = FakeRest(comment_rows()[:1])
    gr.run_inbox(rest, INSTINCT, "prod", facts_dir, False, lambda p, b: False, comment_state=path, now=NOW)
    assert rest.acked == [] and not path.exists()


def test_inbox_dry_run_writes_no_state(facts_dir, tmp_path):
    path = tmp_path / "state.json"
    rest, sent = FakeRest(comment_rows()), []
    stats = gr.run_inbox(rest, INSTINCT, "prod", facts_dir, True, lambda p, b: sent.append(b) or True,
                         comment_state=path, now=NOW)
    assert sent == [] and rest.acked == [] and not path.exists()
    assert stats["approved"] == 2 and stats["rejected"] == 3               # 22 is still caught as a duplicate in memory


def test_inbox_unreadable_state_defers_comments_only(facts_dir, tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[]", encoding="utf-8")
    rest, sent = FakeRest(comment_rows()[:4]), []
    stats = gr.run_inbox(rest, INSTINCT, "prod", facts_dir, False, lambda p, b: sent.append(b) or True,
                         comment_state=path, now=NOW)
    assert rest.acked == [24] and stats["deferred"] == 3


def test_draft_cli_comment_reads_state_without_writing(tmp_path, facts_dir):
    p, st = tmp_path / "c.json", tmp_path / "state.json"
    p.write_text(json.dumps(comment()), encoding="utf-8")
    assert gr.main(["--draft", str(p), "--facts-base", facts_dir, "--comment-state", str(st)]) == 0
    assert not st.exists()
    p.write_text(json.dumps(comment(text="check out our app")), encoding="utf-8")
    assert gr.main(["--draft", str(p), "--facts-base", facts_dir, "--comment-state", str(st)]) == 1


# ---------------------------------------------------------------------------
# Post media (owner rule 2026-10-12: every own post carries native media; comments are exempt)

def test_post_without_media_is_rejected():
    d = good_x()
    del d["media_url"]
    v, why = gr.review(d, FACTS)
    assert v == "REJECT" and any(r.startswith("media_url missing") for r in why)
    assert gr.review(good_x(media_url=""), FACTS)[0] == "REJECT"


def test_post_media_item_card_and_our_pages_file_are_approved():
    assert CONGRESS["media"][0]["url"] == "https://www.rapidtradeview.trade/smart-money/figures/maria-elvira-salazar/opengraph-image"
    assert gr.review(good_x(), FACTS) == ("APPROVE", [])
    ours = f"https://asafb2k.github.io/rapidtradeview-media/v/{DATE}/congress-UNH/feed_4x5.png"
    assert gr.review(good_x(media_url=ours), FACTS) == ("APPROVE", [])
    reel = "https://asafb2k.github.io/rapidtradeview-media/v/2026-10-08/congress-UNH/story_9x16.mp4"
    assert gr.review(good_x(media_url=reel), FACTS) == ("APPROVE", [])


@pytest.mark.parametrize("url", [
    "https://evil.example/card.png",
    PATTERN["media"][0]["url"],                                                          # another item's card
    "https://asafb2k.github.io/rapidtradeview-media/v/latest/x.png",
    "https://asafb2k.github.io/rapidtradeview-media/v/2026-10-09/../../x.png",
    "https://asafb2k.github.io/other-repo/v/2026-10-09/x.png",
])
def test_post_media_from_elsewhere_is_rejected(url):
    v, why = gr.review(good_x(media_url=url), FACTS)
    assert v == "REJECT" and any("is not one of the item's media urls" in r for r in why)


def test_grok_generated_media_needs_a_clean_note():
    ok = good_x(media_url="grok_generated", media_note="An abstract dark trading desk with a glowing candlestick chart.")
    assert gr.review(ok, FACTS) == ("APPROVE", [])
    v, why = gr.review(good_x(media_url="grok_generated"), FACTS)
    assert v == "REJECT" and any("needs a media_note" in r for r in why)
    for note in ("A chart showing 12% gains", "A $UNH ticker board", "A 50% pie", "The UnitedHealth logo on a wall",
                 "A portrait of a congresswoman", "Close-up face of a trader", "Maria Elvira Salazar at a podium",
                 "Salazar waving"):
        v, why = gr.review(good_x(media_url="grok_generated", media_note=note), FACTS)
        assert v == "REJECT" and any(r.startswith("media_note") for r in why), note
    d = {"item_id": MOVES["item_id"], "platform": "x", "text": "x", "media_url": "grok_generated",
         "media_note": "Two Apple-style laptops side by side"}
    assert any(r.startswith("media_note") for r in gr.media_reasons(d, MOVES))


def test_comments_need_no_media(state):
    assert gr.review_comment(comment(), None, state, NOW) == ("APPROVE", [])


# ---------------------------------------------------------------------------
# facts.py media

def test_facts_items_carry_their_og_card():
    assert PICKS["media"] == [{"url": f"https://www.rapidtradeview.trade/picks/{DATE}/opengraph-image", "kind": "image",
                               "alt": PICKS["facts_text"]}]
    assert PATTERN["media"][0]["url"] == "https://www.rapidtradeview.trade/dashboard/MARA/opengraph-image"
    up = fx.make_item(DATE, "earnings_upcoming", "DAL", "upcoming:DAL:2026-10-10", "/dashboard/DAL",
                      facts_text="Delta Air Lines (DAL) reports\nearnings on 2026-10-10.")
    assert up["media"] == [{"url": "https://www.rapidtradeview.trade/dashboard/DAL/opengraph-image", "kind": "image",
                            "alt": "Delta Air Lines (DAL) reports earnings on 2026-10-10."}]
    rep = fx.make_item(DATE, "earnings_result", "DAL", "report:dal-2026-q3", "/earnings/reports/dal-2026-q3")
    assert rep["media"][0]["url"] == "https://www.rapidtradeview.trade/earnings/reports/dal-2026-q3/opengraph-image"


def test_carried_over_moves_like_items_get_their_card():
    old = {k: v for k, v in MOVES.items() if k != "media"}
    _, items = fx.previous_moves({"date": DATE, "items": [old]}, dt.date.fromisoformat(DATE))
    assert items[0]["media"][0]["url"] == "https://www.rapidtradeview.trade/dashboard/AAPL/opengraph-image"
