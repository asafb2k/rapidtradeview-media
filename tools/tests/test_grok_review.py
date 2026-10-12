"""Stage-A draft validator (tools/grok_review.py). Run: python -m pytest tools/tests -q (offline)."""
import json
import sys
import types
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import facts as fx  # noqa: E402
import grok_review as gr  # noqa: E402

DATE = "2026-10-09"
PTR = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035562.pdf"


def facts_fixture() -> dict:
    congress = fx.make_item(
        DATE, "congress_trade", "UNH", "ptr:20035562:UNH:buy", "/smart-money/figures/maria-elvira-salazar",
        name="Maria Elvira Salazar", office="U.S. Representative (R-FL)", amount_text="$15K–$50K",
        traded=["2026-09-24"], filed="2026-10-07", source_url=PTR,
        facts_text="U.S. Representative Maria Elvira Salazar (R-FL) disclosed a purchase of UNH, $15K–$50K.",
        allowed_numbers=["$15K–$50K", "$15K", "$50K", "$15,001–$50,000", "$15,001", "$50,000",
                         *fx.date_forms("2026-10-07"), *fx.date_forms("2026-09-24")])
    picks = fx.make_item(DATE, "picks_ready", None, f"picks:{DATE}", f"/picks/{DATE}", tickers=["XE", "AMPX"],
                         source_url=f"https://www.rapidtradeview.trade/picks/{DATE}",
                         facts_text="The daily picks list is published.", allowed_numbers=[*fx.date_forms(DATE), "2"])
    pattern = fx.make_item(
        DATE, "chart_pattern", "MARA", "pattern:MARA:rising_wedge:confirmed:2026-09-28", "/dashboard/MARA",
        name="MARA Holdings, Inc.", banned_words=fx.PREDICTION_WORDS, source_url="https://www.rapidtradeview.trade/dashboard/MARA",
        facts_text="Automatic technical analysis flagged a rising wedge on $MARA (scan 2026-10-09): Confirmed Sep 28.",
        allowed_numbers=["$12.11", "$12.22", "Sep 28", "Jul 31", "Sep 21", *fx.date_forms("2026-10-09")])
    moves = fx.make_item(
        DATE, "moves_like", "AAPL", "moves:AAPL:2026-10-09", "/dashboard/AAPL", tickers=["AAPL", "TU", "WU", "HLN"],
        name="Apple Inc.", banned_words=fx.PREDICTION_WORDS, source_url="https://www.rapidtradeview.trade/dashboard/AAPL",
        facts_text="Moves Like: over the 60 sessions before Oct 9, 2026, $AAPL moved most like $TU (Sync 55, Loose).",
        allowed_numbers=["60", "100", "55", "54", *fx.date_forms("2026-10-09"), "−4.0%", "4.0%"])
    return {"schema": fx.SCHEMA, "date": DATE,
            "rules": {"banned_words": fx.BANNED_WORDS, "disclaimer": fx.DISCLAIMER, "max_len": fx.MAX_LEN,
                      "platform_placeholder": "{platform}"},
            "items": [congress, picks, pattern, moves]}


FACTS = facts_fixture()
CONGRESS, PICKS, PATTERN, MOVES = FACTS["items"]


def link(item, platform):
    return item["page_url"].replace("{platform}", platform)


def good_x(**over):
    d = {"item_id": CONGRESS["item_id"], "platform": "x",
         "text": "$UNH: Rep. Maria Elvira Salazar (R-FL) disclosed a $15K–$50K purchase, traded Sep 24, filed Oct 7, 2026. "
                 "Not investment advice.",
         "reply_text": f"Filing: {PTR}\nAll her trades: {link(CONGRESS, 'x')}",
         "link": link(CONGRESS, "x"), "media_url": CONGRESS["media"][0]["url"]}
    d.update(over)
    return d


def test_good_draft_is_approved():
    assert gr.review(good_x(), FACTS) == ("APPROVE", [])


def test_good_instagram_caption_is_approved():
    d = {"item_id": CONGRESS["item_id"], "platform": "instagram",
         "text": f"$UNH: a $15K–$50K purchase disclosed 2026-10-07. Source: {PTR} Link in bio. Not investment advice.",
         "link": link(CONGRESS, "instagram"), "media_url": CONGRESS["media"][0]["url"]}
    assert gr.review(d, FACTS) == ("APPROVE", [])


def test_hallucinated_number_is_rejected():
    v, why = gr.review(good_x(text="$UNH: Rep. Salazar bought $20K of UNH, up 12% since. Not investment advice."), FACTS)
    assert v == "REJECT"
    assert any("numbers not in allowed_numbers" in r and "$20K" in r and "12%" in r for r in why)


def test_number_forms():
    allowed = ["$15K", "$50K", "$1.72", "−$0.12", "2026-10-07", "Oct 7, 2026", "Oct 7"]
    assert gr.unexplained_numbers("a $15K-$50K range, $50K–$15K, filed 2026-10-07 (Oct 7, 2026)", allowed, []) == []
    assert gr.unexplained_numbers("EPS -$0.12 and −$0.12", allowed, []) == []
    assert gr.unexplained_numbers("EPS -$1.72", allowed, []) == ["-$1.72"]          # a sign the facts do not carry
    assert gr.unexplained_numbers("$150K, Oct 7th, $15K.5", allowed, []) == ["$150K", "7th", "$15K.5"]
    assert gr.unexplained_numbers("$UNH and $BRK.B", allowed, ["UNH", "BRK.B"]) == []


@pytest.mark.parametrize("word", ["insider trading", "To The Moon", "guaranteed", "price target"])
def test_banned_words_are_rejected(word):
    v, why = gr.review(good_x(text=f"$UNH {word}: Rep. Salazar disclosed a $15K–$50K purchase. Not investment advice."), FACTS)
    assert v == "REJECT" and any("banned words" in r for r in why)


def test_moon_is_a_word_not_a_substring():
    _, why = gr.review(good_x(text="$UNH: Rep. Salazar disclosed a $15K purchase near Moonachie. Not investment advice."), FACTS)
    assert not any("banned" in r for r in why)


def test_missing_disclaimer_is_rejected():
    v, why = gr.review(good_x(text="$UNH: Rep. Salazar disclosed a $15K–$50K purchase."), FACTS)
    assert v == "REJECT" and any("Not investment advice." in r for r in why)


def test_wrong_utm_is_rejected():
    wrong = link(CONGRESS, "x").replace("utm_source=x", "utm_source=instagram")
    v, why = gr.review(good_x(link=wrong, reply_text=f"Filing: {PTR}\n{wrong}"), FACTS)
    assert v == "REJECT" and any(r.startswith("link must be") for r in why)
    no_content = link(CONGRESS, "x").split("&utm_content=")[0]
    v, why = gr.review(good_x(link=no_content), FACTS)
    assert v == "REJECT" and any(r.startswith("link must be") for r in why)


def test_unknown_item_and_missing_facts():
    assert gr.review(good_x(item_id=f"{DATE}-congress-trade-UNH-zzzzzz"), FACTS)[0] == "REJECT"
    assert gr.review(good_x(), None) == ("REJECT", [f"no facts.json for {DATE}"])


def test_ticker_must_match():
    v, why = gr.review(good_x(text="$MSFT: Rep. Salazar disclosed a $15K purchase. Not investment advice."), FACTS)
    assert v == "REJECT" and any("$MSFT" in r for r in why) and any("must name $UNH" in r for r in why)


def test_x_source_link_goes_in_the_reply():
    v, why = gr.review(good_x(reply_text=link(CONGRESS, "x")), FACTS)
    assert v == "REJECT" and any("official source link" in r for r in why)


def test_foreign_url_is_rejected():
    v, why = gr.review(good_x(reply_text=f"{PTR} {link(CONGRESS, 'x')} https://evil.example/x"), FACTS)
    assert v == "REJECT" and any("URL not from this item" in r for r in why)


def test_x_length_limit():
    long = "$UNH " + "Rep. Salazar disclosed a purchase. " * 9 + "Not investment advice."
    v, why = gr.review(good_x(text=long), FACTS)
    assert v == "REJECT" and any("limit 270" in r for r in why)


def picks_draft(text):
    return {"item_id": PICKS["item_id"], "platform": "x", "text": text, "reply_text": link(PICKS, "x"), "link": link(PICKS, "x"),
            "media_url": PICKS["media"][0]["url"]}


def test_picks_good_and_number_one_hints():
    assert gr.review(picks_draft("Today's public picks: $XE and $AMPX (2 names). Not investment advice."), FACTS)[0] == "APPROVE"
    for hint in ("Our #1 pick is waiting", "the top pick is locked", "number one idea inside", "plus one locked name"):
        v, why = gr.review(picks_draft(f"$XE and $AMPX today; {hint}. Not investment advice."), FACTS)
        assert v == "REJECT" and any("#1" in r for r in why), hint
    v, why = gr.review(picks_draft("$XE, $AMPX and $NVDA today. Not investment advice."), FACTS)
    assert v == "REJECT" and any("$NVDA" in r for r in why)


def feature_draft(item, text, platform="x"):
    return {"item_id": item["item_id"], "platform": platform, "text": text,
            "reply_text": f"See it on the chart: {link(item, platform)}", "link": link(item, platform),
            "media_url": item["media"][0]["url"]}


PATTERN_TEXT = ("$MARA: automatic technical analysis flagged a rising wedge (Jul 31 to Sep 21). Confirmed Sep 28: "
                "closed $12.11, below the lower line at $12.22. Not investment advice.")
MOVES_TEXT = ("$AAPL moved most like $TU and $WU over the 60 sessions before Oct 9 (Sync 55 and 54, out of 100). "
              "$TU fell 4.0% on Oct 9. Not investment advice.")


def test_chart_pattern_and_moves_like_good_drafts_are_approved():
    assert gr.review(feature_draft(PATTERN, PATTERN_TEXT), FACTS) == ("APPROVE", [])
    assert gr.review(feature_draft(MOVES, MOVES_TEXT), FACTS) == ("APPROVE", [])
    ig = feature_draft(MOVES, MOVES_TEXT.replace("Not investment", "Link in bio. Not investment"), "instagram")
    assert gr.review(dict(ig, reply_text=None), FACTS) == ("APPROVE", [])


@pytest.mark.parametrize("phrase", ["a breakout coming", "it will drop", "about to break", "set to fall", "going to bounce"])
def test_feature_predictions_are_rejected(phrase):
    for item, text in ((PATTERN, PATTERN_TEXT), (MOVES, MOVES_TEXT)):
        v, why = gr.review(feature_draft(item, text.replace("Not investment", f"{phrase}. Not investment")), FACTS)
        assert v == "REJECT" and any("banned words" in r for r in why), (item["type"], phrase)


def test_will_is_banned_only_where_the_item_says():
    v, why = gr.review(good_x(text="$UNH: Rep. Salazar disclosed a $15K–$50K purchase; the filing will stay public. "
                                   "Not investment advice."), FACTS)
    assert v == "APPROVE", why


def test_peer_not_in_the_item_is_rejected():
    v, why = gr.review(feature_draft(MOVES, MOVES_TEXT.replace("$WU", "$NVDA")), FACTS)
    assert v == "REJECT" and any("cashtag not in this item: $NVDA" in r for r in why)
    v, why = gr.review(feature_draft(PATTERN, PATTERN_TEXT.replace("rising wedge", "rising wedge like $TU")), FACTS)
    assert v == "REJECT" and any("$TU" in r for r in why)          # peers belong to the moves_like item only
    v, why = gr.review(feature_draft(MOVES, MOVES_TEXT.replace("Sync 55", "Sync 91")), FACTS)
    assert v == "REJECT" and any("91" in r for r in why)


def test_feature_posts_never_touch_the_number_one():
    v, why = gr.review(feature_draft(PATTERN, PATTERN_TEXT.replace("Confirmed", "Also our top pick. Confirmed")), FACTS)
    assert v == "REJECT" and any("#1" in r for r in why)


# ---------------------------------------------------------------------------
# --inbox

class FakeRest:
    def __init__(self, rows):
        self.rows = rows
        self.acked: list[int] = []
        self.calls: list[tuple] = []

    def call(self, method, query, body=None, prefer=None):
        self.calls.append((method, query))
        if method == "GET":
            return [r for r in self.rows if r["id"] not in self.acked]
        if method == "PATCH":
            mid = int(query.split("id=eq.")[1].split("&")[0])
            assert "direction=eq.from_instinct" in query and "acked_at=is.null" in query
            self.acked.append(mid)
            return [{"id": mid}]
        raise AssertionError(method)


INSTINCT = types.SimpleNamespace(q=lambda *p: "&".join(p), PAGE_ROWS=1000)


def inbox_rows():
    good = good_x()
    bad = good_x(text="$UNH to the moon, $20K. ")
    return [
        {"id": 11, "kind": "report", "platform": "x", "item_id": good["item_id"], "body": "DRAFT " + json.dumps(good)},
        {"id": 12, "kind": "post_log", "platform": "x", "item_id": None, "body": "posted https://x.com/rtv/1"},
        {"id": 13, "kind": "report", "platform": "x", "item_id": None, "body": "DRAFT\n```json\n" + json.dumps(bad) + "\n```"},
        {"id": 14, "kind": "report", "platform": None, "item_id": None, "body": "DRAFT not json"},
        {"id": 15, "kind": "question", "platform": None, "item_id": None, "body": "Drafting the plan now"},
    ]


@pytest.fixture()
def facts_dir(tmp_path):
    d = tmp_path / "v" / DATE
    d.mkdir(parents=True)
    (d / "facts.json").write_text(json.dumps(FACTS), encoding="utf-8")
    return str(tmp_path / "v")


def test_inbox_answers_and_acks_only_draft_rows(facts_dir):
    rest, sent = FakeRest(inbox_rows()), []
    stats = gr.run_inbox(rest, INSTINCT, "prod", facts_dir, False, lambda p, b: sent.append((p, b)) or True)
    assert sorted(rest.acked) == [11, 13, 14]           # 12 (post_log) and 15 ("Drafting") never acked
    bodies = [b for _, b in sent]
    assert bodies[0] == f"APPROVE 11 {CONGRESS['item_id']}"
    assert bodies[1].startswith(f"REJECT 13 {CONGRESS['item_id']}: ") and "banned words" in bodies[1] and "$20K" in bodies[1]
    assert bodies[2].startswith("REJECT 14 (no valid item_id): the body must be")
    assert [p for p, _ in sent] == ["x", "x", None]
    assert stats["approved"] == 1 and stats["rejected"] == 2 and stats["acked"] == 3


def test_inbox_dry_run_sends_and_acks_nothing(facts_dir):
    rest, sent = FakeRest(inbox_rows()), []
    stats = gr.run_inbox(rest, INSTINCT, "prod", facts_dir, True, lambda p, b: sent.append(b) or True)
    assert sent == [] and rest.acked == [] and all(m == "GET" for m, _ in rest.calls)
    assert stats["drafts"] == 3


def test_inbox_failed_send_is_not_acked(facts_dir):
    rest = FakeRest(inbox_rows()[:1])
    gr.run_inbox(rest, INSTINCT, "prod", facts_dir, False, lambda p, b: False)
    assert rest.acked == []


def test_inbox_unreachable_facts_defers(monkeypatch):
    def boom(where):
        raise gr.FactsUnavailable("HTTP 503")
    monkeypatch.setattr(gr, "load_facts", boom)
    rest, sent = FakeRest(inbox_rows()[:1]), []
    stats = gr.run_inbox(rest, INSTINCT, "prod", "https://example.invalid/v", False, lambda p, b: sent.append(b) or True)
    assert sent == [] and rest.acked == [] and stats["deferred"] == 1


def test_draft_cli(tmp_path, facts_dir):
    p = tmp_path / "d.json"
    p.write_text(json.dumps(good_x()), encoding="utf-8")
    assert gr.main(["--draft", str(p), "--facts-base", facts_dir]) == 0
    p.write_text(json.dumps(good_x(text="$UNH guaranteed. Not investment advice.")), encoding="utf-8")
    assert gr.main(["--draft", str(p), "--facts-base", facts_dir]) == 1


@pytest.mark.parametrize("word", ["Bitcoin", "BTC", "crypto", "cryptocurrency", "Ethereum", "blockchain"])
def test_crypto_words_are_banned_on_every_item(word):
    v, why = gr.review(feature_draft(PATTERN, PATTERN_TEXT.replace("Not investment", f"Tracks {word}. Not investment")), FACTS)
    assert v == "REJECT" and any("banned words" in r for r in why)
    v, why = gr.review(good_x(text=f"$UNH: Rep. Salazar disclosed a $15K–$50K purchase; {word}. Not investment advice."), FACTS)
    assert v == "REJECT" and any("banned words" in r for r in why)
