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
    return {"schema": fx.SCHEMA, "date": DATE,
            "rules": {"banned_words": fx.BANNED_WORDS, "disclaimer": fx.DISCLAIMER, "max_len": fx.MAX_LEN,
                      "platform_placeholder": "{platform}"},
            "items": [congress, picks]}


FACTS = facts_fixture()
CONGRESS, PICKS = FACTS["items"]


def link(item, platform):
    return item["page_url"].replace("{platform}", platform)


def good_x(**over):
    d = {"item_id": CONGRESS["item_id"], "platform": "x",
         "text": "$UNH: Rep. Maria Elvira Salazar (R-FL) disclosed a $15K–$50K purchase, traded Sep 24, filed Oct 7, 2026. "
                 "Not investment advice.",
         "reply_text": f"Filing: {PTR}\nAll her trades: {link(CONGRESS, 'x')}",
         "link": link(CONGRESS, "x")}
    d.update(over)
    return d


def test_good_draft_is_approved():
    assert gr.review(good_x(), FACTS) == ("APPROVE", [])


def test_good_instagram_caption_is_approved():
    d = {"item_id": CONGRESS["item_id"], "platform": "instagram",
         "text": f"$UNH: a $15K–$50K purchase disclosed 2026-10-07. Source: {PTR} Link in bio. Not investment advice.",
         "link": link(CONGRESS, "instagram")}
    assert gr.review(d, FACTS) == ("APPROVE", [])


def test_hallucinated_number_is_rejected():
    v, why = gr.review(good_x(text="$UNH: Rep. Salazar bought $20K of UNH, up 12% since. Not investment advice."), FACTS)
    assert v == "REJECT"
    assert any("numbers not in allowed_numbers" in r and "$20K" in r and "12%" in r for r in why)


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
    assert gr.review(good_x(item_id=f"{DATE}-congress_trade-UNH-zzzzzz"), FACTS)[0] == "REJECT"
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
    return {"item_id": PICKS["item_id"], "platform": "x", "text": text, "reply_text": link(PICKS, "x"), "link": link(PICKS, "x")}


def test_picks_good_and_number_one_hints():
    assert gr.review(picks_draft("Today's public picks: $XE and $AMPX (2 names). Not investment advice."), FACTS)[0] == "APPROVE"
    for hint in ("Our #1 pick is waiting", "the top pick is locked", "number one idea inside", "plus one locked name"):
        v, why = gr.review(picks_draft(f"$XE and $AMPX today; {hint}. Not investment advice."), FACTS)
        assert v == "REJECT" and any("#1" in r for r in why), hint
    v, why = gr.review(picks_draft("$XE, $AMPX and $NVDA today. Not investment advice."), FACTS)
    assert v == "REJECT" and any("$NVDA" in r for r in why)


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
