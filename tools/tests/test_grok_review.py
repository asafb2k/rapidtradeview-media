"""Stage-A draft validator (tools/grok_review.py). Run: python -m pytest tools/tests -q (offline)."""
import datetime as dt
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


SEC_INDEX = "https://www.sec.gov/Archives/edgar/data/1551047/000139834426018110/0001398344-26-018110-index.htm"
FORM4 = fx.make_item(
    DATE, "form4_buy", "BPRE", "form4:0001398344-26-018110:BPRE", "/smart-money/figures/kamfar-ramin-1111908",
    name="Ramin Kamfar", office="Director at Bluerock Private Real Estate Fund", amount_text="$2.42M",
    traded=["2026-10-07"], filed="2026-10-09", source_url=SEC_INDEX,
    facts_text="Ramin Kamfar reported an open-market purchase of BPRE totaling $2.42M on a Form 4 filed 2026-10-09.",
    allowed_numbers=["$2.42M", *fx.date_forms("2026-10-09"), *fx.date_forms("2026-10-07")])
FACTS_F4 = {**FACTS, "items": [*FACTS["items"], FORM4]}


def form4_x(text):
    return {"item_id": FORM4["item_id"], "platform": "x", "text": text,
            "reply_text": f"Filing: {SEC_INDEX}\nAll his trades: {link(FORM4, 'x')}",
            "link": link(FORM4, "x"), "media_url": FORM4["media"][0]["url"]}


def test_filing_names_are_words_not_numbers():
    ok = "$BPRE: a director's insider buy (Form 4) of $2.42M, filed Oct 9, 2026. Not investment advice."
    assert gr.review(form4_x(ok), FACTS_F4) == ("APPROVE", [])
    names = "Form 4, form 144, Form 13F, 8-K, 10-Q, 10-K and 13F filings"
    assert gr.unexplained_numbers(names, [], []) == []
    # anything glued to a filing name, or a bare number, is still a number
    assert gr.unexplained_numbers("Form 4% Form 44 110-K 8-K.5 Form 4-2 10-K2", [], []) == \
        ["4%", "44", "110-K", "8-K.5", "4-2", "10-K2"]


def test_stray_percent_next_to_a_filing_name_is_rejected():
    v, why = gr.review(form4_x("$BPRE: insider buy (Form 4) of $2.42M, up 4% since. Not investment advice."), FACTS_F4)
    assert v == "REJECT"
    assert any("numbers not in allowed_numbers" in r and "4%" in r for r in why)


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
    assert bodies[0].splitlines()[0] == f"APPROVE 11 {CONGRESS['item_id']}"   # + playbook v2 NOTES lines
    assert bodies[0].splitlines()[1].startswith("NOTES (playbook v2): score ")
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


# ---------------------------------------------------------------------------
# G-N1 holdout: no /earnings/reports/ in a post, self-reply, comment, link or media until 2026-11-21

import datetime as _dt  # noqa: E402

IN_HOLDOUT = _dt.datetime(2026, 10, 13, 15, 0, tzinfo=_dt.timezone.utc)
AFTER = _dt.datetime(2026, 11, 21, 5, 0, tzinfo=_dt.timezone.utc)   # 00:00 New York (EST) on 11-21: the gate is off
SEC = "https://www.sec.gov/Archives/edgar/data/19617/000001961726000099/ex99.htm"
REPORT = "https://www.rapidtradeview.trade/earnings/reports/jpm-2026-q3"


def earnings_facts(path="/dashboard/JPM"):
    er = fx.make_item("2026-10-13", "earnings_result", "JPM", "report:jpm-2026-q3", path, name="JPMorgan Chase & Co.",
                      source_url=SEC, facts_text="JPMorgan Chase & Co. (JPM) published FY2026 (Q3) results: Beat estimates.",
                      allowed_numbers=["Q3", "FY2026"])
    return {**FACTS, "date": "2026-10-13", "items": [er]}, er


def er_draft(er, **over):
    d = {"item_id": er["item_id"], "platform": "x", "text": "$JPM published FY2026 Q3 results: beat estimates. Not investment advice.",
         "reply_text": f"Filing: {SEC}\nEarnings history: {link(er, 'x')}", "link": link(er, "x"), "media_url": er["media"][0]["url"]}
    d.update(over)
    return d


def test_g_n1_the_dashboard_earnings_post_is_approved():
    facts, er = earnings_facts()
    assert er["page_url"].endswith("#earnings-history") and er["media"][0]["url"].endswith("/dashboard/JPM/opengraph-image")
    assert gr.review(er_draft(er), facts, IN_HOLDOUT) == ("APPROVE", [])


@pytest.mark.parametrize("field,value", [
    ("text", f"$JPM beat estimates, summary at {REPORT}. Not investment advice."),
    ("reply_text", f"Summary: {REPORT}"),
    ("media_url", f"{REPORT}/opengraph-image"),
    ("media_url", "https://www.rapidtradeview.trade/earnings%2Freports%2Fjpm-2026-q3/opengraph-image"),
])
def test_g_n1_report_page_in_a_post_is_rejected(field, value):
    facts, er = earnings_facts()
    v, why = gr.review(er_draft(er, **{field: value}), facts, IN_HOLDOUT)
    assert v == "REJECT" and any(field in r and "G-N1 holdout" in r for r in why), why
    assert not any("G-N1" in r for r in gr.review(er_draft(er, **{field: value}), facts, AFTER)[1])   # gate off on 11-21


def test_g_n1_an_old_report_item_cannot_be_posted_even_with_its_own_link():
    """A facts file built before the holdout code (page_url and card on the report page): the matching link is rejected."""
    facts, er = earnings_facts(path="/earnings/reports/jpm-2026-q3")
    v, why = gr.review(er_draft(er), facts, IN_HOLDOUT)
    assert v == "REJECT" and any(r.startswith("reply_text, link, media_url: no /earnings/reports/") for r in why), why


def test_g_n1_report_page_in_a_comment_is_rejected():
    d = {"kind": "comment", "platform": "x", "target_url": "https://x.com/sometrader/status/1844000000000000001",
         "text": "Nice breakdown, the JPM summary at rapidtradeview.trade/earnings/reports/jpm-2026-q3 has the numbers too."}
    v, why = gr.review_comment(d, None, None, IN_HOLDOUT)
    assert v == "REJECT" and any("G-N1 holdout" in r for r in why)
    assert gr.holdout_reasons(d, AFTER) == []


def test_g_n1_the_cutoff_is_the_new_york_date():
    """11-21 00:00-04:59 UTC is still 11-20 in New York: inside the holdout (facts.py / select_stories date in New York)."""
    d = {"kind": "comment", "platform": "x", "text": f"see {REPORT}"}
    assert gr.holdout_reasons(d, _dt.datetime(2026, 11, 21, 4, 59, tzinfo=_dt.timezone.utc))
    assert gr.holdout_reasons(d, _dt.datetime(2026, 11, 21, 5, 0, tzinfo=_dt.timezone.utc)) == []
    # 10-13 02:00 UTC is 10-12 22:00 New York: inside either way
    assert gr.holdout_reasons(d, _dt.datetime(2026, 10, 13, 2, 0, tzinfo=_dt.timezone.utc))


@pytest.mark.parametrize("over,where", [
    ({"alt_text": f"Card of {REPORT}"}, "alt_text"),                                   # a field not named before
    ({"extra": {"links": ["https://x.com/a", REPORT]}}, "extra.links[1]"),             # nested list in a dict
    ({"media": [{"url": f"{REPORT}/opengraph-image"}]}, "media[0].url"),
    ({"notes": {REPORT: "key"}}, "notes key"),                                           # a dict key
    ({"first_reply": "https://www.rapidtradeview.trade/EARNINGS%2Freports%2Fjpm-2026-q3"}, "first_reply"),
])
def test_g_n1_the_whole_draft_is_screened(over, where):
    facts, er = earnings_facts()
    v, why = gr.review(er_draft(er, **over), facts, IN_HOLDOUT)
    assert v == "REJECT" and any(r.startswith(f"{where}: no /earnings/reports/") for r in why), why
    assert gr.holdout_reasons(er_draft(er, **over), AFTER) == []
    c = {"kind": "comment", "platform": "x", "target_url": "https://x.com/sometrader/status/1844000000000000001",
         "text": "Good thread.", **over}
    assert any(r.startswith(f"{where}: ") and "G-N1 holdout" in r for r in gr.review_comment(c, None, None, IN_HOLDOUT)[1])


# ---------------------------------------------------------------------------
# Several cashtags: only the roundup kinds, at most 4 (Growth B1 2026-10-12)

WHOLE = {"since": "2026-10-05", "oldest_read": "2026-09-25", "error": None, "dropped": []}  # a whole-filing read
PTR2 = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035570.pdf"


def roundup_facts() -> dict:
    up = [fx.make_item(DATE, "earnings_upcoming", t, f"upcoming:{t}:2026-10-12", "/earnings/tomorrow", name=f"{t} Inc.",
                       report_date="2026-10-12", hour="bmo", market_cap_usd=cap)
          for t, cap in (("JPM", 8e11), ("JNJ", 4e11), ("UNH", 3e11), ("WFC", 2e11), ("C", 1e11))]
    roundup, _ = fx.earnings_roundup_items(dt.date(2026, 10, 9), up)
    congress = [fx.make_item(DATE, "congress_trade", t, f"ptr:20035562:{t}:sell", "/smart-money/figures/maria-elvira-salazar",
                             name="Maria Elvira Salazar", office="U.S. Representative (R-FL)", side="sell",
                             figure_slug="maria-elvira-salazar", filed="2026-10-07", rows=1, source_url=PTR,
                             amount_top_usd=15000)
                for t in ("UNH", "MSFT", "AAPL", "DAL", "XE")]
    summary, _, _ = fx.ptr_summary_items(dt.date(2026, 10, 9), congress, {"members": [], "insiders": []}, WHOLE)
    five = dict(roundup[0], item_id=f"{DATE}-earnings-tomorrow-roundup-LIST-fffff5",
                tickers=["JPM", "JNJ", "UNH", "WFC", "C"])   # a malformed item with 5 tickers: the cap still holds
    return {"schema": fx.SCHEMA, "date": DATE, "rules": FACTS["rules"], "items": [roundup[0], summary[0], five, CONGRESS]}


def roundup_post(item, text, platform="x", reply=None):
    lk = link(item, platform)
    return {"item_id": item["item_id"], "platform": platform, "text": text,
            "reply_text": reply if reply is not None else (f"{item['source_url']}\n{lk}" if item.get("source_url") else lk),
            "link": lk, "media_url": item["media"][0]["url"]}


def test_roundup_four_cashtags_approve_five_reject_outside_reject():
    rf = roundup_facts()
    roundup, summary, five, _ = rf["items"]
    assert roundup["tickers"] == ["JPM", "JNJ", "UNH", "WFC"]
    four = roundup_post(roundup, "Reporting Oct 12, before the open: $JPM $JNJ $UNH $WFC. Not investment advice.")
    assert gr.review(four, rf) == ("APPROVE", [])
    v, why = gr.review(roundup_post(five, "Reporting Oct 12, before the open: $JPM $JNJ $UNH $WFC $C. "
                                          "Not investment advice."), rf)
    assert v == "REJECT" and any("at most 4 cashtags (got 5)" in r for r in why)
    v, why = gr.review(roundup_post(roundup, "Reporting Oct 12: $JPM $JNJ $UNH $GS. Not investment advice."), rf)
    assert v == "REJECT" and any("cashtag not in this item: $GS" in r for r in why)
    v, why = gr.review(roundup_post(roundup, "Big banks report Oct 12. Not investment advice."), rf)
    assert v == "REJECT" and any("at least one of the item's tickers" in r for r in why)
    # ptr_summary: the member's tickers, the counts and the filing date; the PTR goes in the X self-reply
    s_text = "Rep. Maria Elvira Salazar disclosed 5 trades (5 sales) filed Oct 7: $UNH $MSFT $AAPL $DAL. Not investment advice."
    assert gr.review(roundup_post(summary, s_text), rf) == ("APPROVE", [])
    v, why = gr.review(roundup_post(summary, s_text.replace("$DAL", "$DAL $XE")), rf)
    assert v == "REJECT" and any("cashtag not in this item: $XE" in r for r in why)
    v, why = gr.review(roundup_post(summary, s_text, reply=link(summary, "x")), rf)
    assert v == "REJECT" and any("official source link" in r for r in why)


def test_single_ticker_kinds_keep_one_cashtag():
    rf = roundup_facts()
    congress = dict(CONGRESS, tickers=["UNH", "MSFT"])   # even if a single-ticker item listed more, one cashtag only
    rf["items"][3] = congress
    v, why = gr.review(good_x(text="$UNH and $MSFT: Rep. Salazar disclosed a $15K–$50K purchase. Not investment advice."), rf)
    assert v == "REJECT" and any("one cashtag per post" in r for r in why)
    assert gr.review(good_x(), rf) == ("APPROVE", [])


def multi_filing_summary() -> tuple[dict, dict]:
    congress = [fx.make_item(DATE, "congress_trade", t, f"ptr:{src[-12:-4]}:{t}:sell", "/smart-money/figures/maria-elvira-salazar",
                             name="Maria Elvira Salazar", office="U.S. Representative (R-FL)", side="sell",
                             figure_slug="maria-elvira-salazar", filed="2026-10-07", rows=1, source_url=src,
                             amount_top_usd=15000)
                for t, src in (("UNH", PTR), ("MSFT", PTR), ("AAPL", PTR2))]
    summary, _, _ = fx.ptr_summary_items(dt.date(2026, 10, 9), congress, {"members": [], "insiders": []}, WHOLE)
    item = summary[0]
    return item, {"schema": fx.SCHEMA, "date": DATE, "rules": FACTS["rules"], "items": [item]}


def test_ptr_summary_over_several_filings_cites_any_of_its_official_urls():
    item, facts = multi_filing_summary()
    assert item["source_url"] is None and sorted(item["source_urls"]) == [PTR, PTR2]
    text = "Rep. Maria Elvira Salazar disclosed 3 trades (3 sales) on 2 reports filed Oct 7: $UNH $MSFT $AAPL. Not investment advice."
    lk = link(item, "x")
    for src in (PTR, PTR2):   # either filing's URL is the item's own
        assert gr.review(roundup_post(item, text, reply=f"Filings: {src}\n{lk}"), facts) == ("APPROVE", [])
    assert gr.review(roundup_post(item, text, reply=f"{PTR} {PTR2}\n{lk}"), facts) == ("APPROVE", [])
    # X: at least one official source URL in the self-reply
    v, why = gr.review(roundup_post(item, text, reply=lk), facts)
    assert v == "REJECT" and any("official source link goes in the self-reply" in r for r in why)
    v, why = gr.review(roundup_post(item, f"{text} {PTR2}", reply=lk), facts)   # in the text only: still not in the reply
    assert v == "REJECT" and any("official source link goes in the self-reply" in r for r in why)
    # a URL that is no filing of this item
    other = PTR.replace("20035562", "20035599")
    v, why = gr.review(roundup_post(item, text, reply=f"{other}\n{lk}"), facts)
    assert v == "REJECT" and any("URL not from this item" in r for r in why)
    # Instagram: the caption carries one of them
    ig = link(item, "instagram")
    post = {"item_id": item["item_id"], "platform": "instagram", "text": f"{text}\nFiling: {PTR2}\n{ig}", "link": ig,
            "media_url": item["media"][0]["url"]}
    assert gr.review(post, facts) == ("APPROVE", [])
    v, why = gr.review(dict(post, text=f"{text}\n{ig}"), facts)
    assert v == "REJECT" and any("caption must carry the official source link" in r for r in why)


def test_ptr_summary_source_urls_must_be_official():
    item, facts = multi_filing_summary()
    bad = "https://example.com/ptr.pdf"
    item = dict(item, source_urls=[bad])
    facts = dict(facts, items=[item])
    text = "Rep. Maria Elvira Salazar disclosed 3 trades (3 sales) on 2 reports filed Oct 7: $UNH. Not investment advice."
    lk = link(item, "x")
    v, why = gr.review(roundup_post(item, text, reply=f"{bad}\n{lk}"), facts)
    assert v == "REJECT" and any("URL not from this item" in r for r in why)
    assert any("no official source URL" in r for r in why)


# ---------------------------------------------------------------------------
# earnings_week_calendar (Growth test 2026-10-16): up to 12 cashtags, only its own calendar image, X only in v1

WEEK = json.loads((TOOLS / "tests" / "fixtures" / "earnings_week_2026-10-19.json").read_text(encoding="utf-8"))
CAL_TAGS = "$META $TSLA $PG $LRCX $GE $PM $NFLX $TXN $RTX $TMO $IBM $AXP"
CAL_T1 = (f"Biggest earnings next week, Oct 19–23 (confirmed dates):\n{CAL_TAGS}\n"
          "Every day, before the open and after the close, is in the image.\nNot investment advice.")
CAL_T2 = (f"205 companies in our coverage have confirmed earnings dates Oct 19–23. The largest:\n{CAL_TAGS}\n"
          "The image lays out each day, before the open and after the close.\nNot investment advice.")


def week_facts(reel=False) -> dict:
    (it,), _, why = fx.week_calendar_items(dt.date(2026, 10, 16), [WEEK["earnings"]], [], WEEK["names"])
    assert why is None
    png = f"{gr.mf.PAGES_BASE}/v/2026-10-16/cards/{it['item_id']}/calendar_4x5.png"
    media = [{"url": png, "kind": "image", "alt": "Earnings calendar"}]
    if reel:
        media.append({"url": png.replace("calendar_4x5.png", "calendar_9x16.mp4"), "kind": "reel", "alt": "Earnings calendar"})
    it = dict(it, media=media)
    thirteen = dict(it, item_id=f"{it['item_id'][:-6]}fff013", tickers=[*it["tickers"], "ABT"])  # malformed: the cap holds
    return {"schema": fx.SCHEMA, "date": "2026-10-16", "rules": FACTS["rules"], "items": [it, thirteen]}


def cal_post(item, text, platform="x", media=None, reply=None):
    lk = link(item, platform)
    return {"item_id": item["item_id"], "platform": platform, "text": text,
            "reply_text": reply if reply is not None else
            f"Next week's full table, Oct 19 – Oct 23, with every confirmed date: {lk}",
            "link": lk, "media_url": media or item["media"][0]["url"]}


def test_week_calendar_twelve_cashtags_and_its_image_approve():
    wf = week_facts()
    it = wf["items"][0]
    assert it["tickers"] == CAL_TAGS.replace("$", "").split()
    for text in (CAL_T1, CAL_T2):
        assert gr.review(cal_post(it, text), wf) == ("APPROVE", [])
        assert gr.mf.x_weighted_length(text) <= 270
    assert gr.review(cal_post(it, CAL_T1.replace("Oct 19–23", "Oct 19–23, 2026")), wf) == ("APPROVE", [])
    assert gr.review(cal_post(it, CAL_T1.replace("Oct 19–23", "Oct 19-23")), wf) == ("APPROVE", [])


def test_week_calendar_rejections():
    wf = week_facts()
    it, thirteen = wf["items"]
    v, why = gr.review(cal_post(thirteen, CAL_T1.replace("$AXP", "$AXP $ABT")), wf)
    assert v == "REJECT" and any("earnings_week_calendar: at most 12 cashtags (got 13)" in r for r in why)
    # ABT is on the image but not one of the item's tickers
    v, why = gr.review(cal_post(it, CAL_T1.replace("$AXP", "$ABT")), wf)
    assert v == "REJECT" and any("cashtag not in this item: $ABT" in r for r in why)
    # its own image only: no Grok-made image, no other Pages file, not the /earnings card
    other = f"{gr.mf.PAGES_BASE}/v/2026-10-16/cards/{it['item_id']}/other.png"
    for media in ("grok_generated", other, "https://www.rapidtradeview.trade/earnings/opengraph-image"):
        d = dict(cal_post(it, CAL_T1, media=media), media_note="an abstract calendar grid")
        v, why = gr.review(d, wf)
        assert v == "REJECT" and any("media_url must be the item's own image" in r for r in why), media
    # Instagram only with a Reel in the item's media (none in v1)
    v, why = gr.review(cal_post(it, CAL_T1, platform="instagram"), wf)
    assert v == "REJECT" and any("Instagram only with the item's own Reel" in r for r in why)
    # dates only as allowed_numbers print them; never "most anticipated"
    v, why = gr.review(cal_post(it, CAL_T1.replace("Oct 19–23", "Oct 19 to 23")), wf)
    assert v == "REJECT" and any("numbers not in allowed_numbers: 23" in r for r in why)
    v, why = gr.review(cal_post(it, CAL_T1.replace("Biggest", "Most anticipated")), wf)
    assert v == "REJECT" and any("banned words: most anticipated, anticipated" in r for r in why)
    v, why = gr.review(cal_post(it, CAL_T1.replace("Every day", "Every day will")), wf)
    assert v == "REJECT" and any("banned words: will" in r for r in why)
    # an item without its image (the runner keeps it out of the feed until Pages serves it) can never be posted
    bare = dict(it, media=[])
    v, why = gr.review(cal_post(bare, CAL_T1, media=it["media"][0]["url"]), dict(wf, items=[bare]))
    assert v == "REJECT" and any("no media yet" in r for r in why)


def test_week_calendar_instagram_needs_the_items_reel():
    wf = week_facts(reel=True)
    it = wf["items"][0]
    caption = (f"Next week's earnings calendar (Oct 19–23): the largest companies reporting each day. {CAL_TAGS}\n"
               "Confirmed dates on the RapidTradeView earnings page. Link in bio.\nNot investment advice.")
    reel = it["media"][1]["url"]
    assert gr.review(cal_post(it, caption, platform="instagram", media=reel), wf) == ("APPROVE", [])
    v, why = gr.review(cal_post(it, caption, platform="instagram"), wf)   # the still image is not the Reel
    assert v == "REJECT" and any("on Instagram media_url must be the item's Reel" in r for r in why)


def test_roundup_cap_stays_four():
    rf = roundup_facts()
    five = rf["items"][2]
    v, why = gr.review(roundup_post(five, "Reporting Oct 12, before the open: $JPM $JNJ $UNH $WFC $C. "
                                          "Not investment advice."), rf)
    assert v == "REJECT" and any("earnings_tomorrow_roundup: at most 4 cashtags (got 5)" in r for r in why)
    assert fx.cashtag_max(rf["items"][1]["type"]) == 4
