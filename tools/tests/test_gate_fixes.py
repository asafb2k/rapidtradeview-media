"""Growth gate fixes 2026-10-26 (tools/grok_review.py): provider-name REJECT, comment cap 10 per New York day, no
grok_generated media, verdict self-retire. Run: python -m pytest tools/tests -q (offline: fake gateway, never prod)."""
import datetime as dt
import json
import sys
import types
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(TESTS))
import grok_review as gr  # noqa: E402
import post_vocab as pv  # noqa: E402
from test_grok_review import CONGRESS, DATE, FACTS, FORM4, FACTS_F4, FakeRest, INSTINCT, PTR, SEC_INDEX, form4_x, good_x  # noqa: E402,E501


@pytest.fixture(autouse=True)
def _legacy_items(monkeypatch):
    """As in test_grok_review.py: the fixture items predate the verbatim rule; the item gate passes them here."""
    real = gr.item_gate_reasons
    monkeypatch.setattr(gr, "item_gate_reasons",
                        lambda item, facts, now=None: real(item, facts, now) if gr.cl.verbatim_mode(item) else [])


def provider(why):
    return [r for r in why if r.startswith("provider:")]


# ---------------------------------------------------------------------------
# a) provider names

OWNER_EXAMPLES = ["Yahoo", "IEX", "Alpaca", "Tiingo", "Finnhub", "ApeWisdom", "StockTwits", "Zacks", "Elbstream"]
BACKEND_LIST = ["finnhub", "yahoo", "apewisdom", "stocktwits", "alpaca", "tiingo", "cnbc", "polygon.io"]


@pytest.mark.parametrize("word", OWNER_EXAMPLES + BACKEND_LIST)
def test_every_owner_and_backend_provider_word_is_caught(word):
    assert gr.provider_hits(f"Revenue data via {word} today.")
    assert gr.provider_hits(f"{word.upper()} shows it") and gr.provider_hits(f"per {word.lower()}.")


@pytest.mark.parametrize("text", [
    "Source: yahoo.com", "see finance.yahoo for the chart", "https://finance.yahoo.com/quote/UNH",
    "query2.finance.yahoo.com/v8/x", "stocktwits.com/symbol/UNH", "https://api.stocktwits.com/x", "apewisdom.io",
    "Yahoo Finance consensus", "Yahoo! Finance", "per Stock Twits", "stock-twits buzz", "Seeking Alpha says",
    "seekingalpha.com", "(MarketBeat consensus)", "est (Zacks).", "#StockTwits", "@Finnhub", "via yfinance",
    "IEX Cloud", "iexcloud", "Google News headline", "news.google.com/rss", "https://news.google.com/x",
    "\U0001d418\U0001d41a\U0001d421\U0001d428\U0001d428 data",   # math-bold "Yahoo"
    "Ya\u200bhoo data", "\uff3a\uff41\uff43\uff4b\uff53 consensus",                        # zero-width split, fullwidth
])
def test_domains_hints_and_obfuscations_are_caught(text):
    assert gr.provider_hits(text), text


@pytest.mark.parametrize("text", [
    "$IEX rose 3% today.",                                       # a cashtag (IDEX Corp) is a ticker, never a provider
    "Form 4 filed with the SEC. https://www.sec.gov/Archives/edgar/data/1/2-index.htm",
    "Filed on sec.gov; see EDGAR.",
    "Reddit mentions of $META ran 8.2x its usual count.",        # Reddit is a platform (our P4 phrases)
    "https://www.rapidtradeview.trade/dashboard/IEX?utm_source=x&utm_campaign=grok#earnings-history",
    "rapidtradeview.trade/dashboard/IEX",                        # our own bare domain with a ticker path
    "https://asafb2k.github.io/rapidtradeview-media/v/2026-10-25/cards/x/feed.png",
    "A polygon, an alexa, Iexplore, yahoos, alpacas, Zackson, Bloombergs and cnbcx are not providers.",
    "Analysts' consensus estimate, earnings history, market data and a stock screener.",
    "Here is what Reddit is talking about.",
])
def test_ordinary_words_tickers_sec_and_our_pages_pass(text):
    assert gr.provider_hits(text) == [], text


# real approved / published texts (post-audit state, 2026-10-16..22) carry no provider name
REAL_TEXTS = [
    "$BRK.B: U.S. Representative Richard McCormick (R-GA) disclosed a $1K–$15K purchase of Berkshire Hathaway Inc. "
    "stock.\n\nTraded Sep 18. Filed Oct 14 on a House periodic transaction report.\n\nNot investment advice.",
    "At 325 vs 40, Reddit mentions of $META ran 8.2× its usual count.\n\nOf the 10 most-mentioned stocks with a close "
    "for Oct 21, 6 rose that day.\n\nHow do you read this chart?\n\nDetails in the reply.\n\nNot investment advice.",
    "The 500 largest US-listed stocks gained about $0.7T on Wednesday.\n\n499 of the 500 largest US-listed stocks had a "
    "price on Wednesday, 99.9% of their market value.\n\n$SPCX gained $151.8B of market value on Wednesday (+7.79%).\n\n"
    "Not investment advice.",
    "Chart pattern: $APLD broke below a descending triangle. Oct 9 close $23.68 vs the $23.99 lower line; last close "
    "$20.39 (Oct 15). Pattern ran Jul 29 to Sep 22. Chart on rapidtradeview.trade (link in bio). #stockmarket Not "
    "investment advice.",
    "Earnings calendar for Monday, Oct 19: $FITB, $CLF and $DX before the open; $STLD, Wintrust, Zions, Western Alliance "
    "and more after the close (confirmed dates). Full calendar on rapidtradeview.trade (link in bio). #earnings Not "
    "investment advice.",
]
# published 10-14 posts that cited an outside consensus vendor: the leak this gate closes
REAL_LEAKS = [
    "$MS Q3: revenue $20.34B vs $20.11B consensus (beat by $228M). GAAP EPS $3.03 vs $2.83 est (Zacks).",
    "$BAC Q3 GAAP EPS $0.91 includes a $0.17/share regulatory settlement charge. Adjusted EPS $1.08 vs $1.10 est "
    "(MarketBeat consensus).",
]


def test_real_approved_texts_pass_and_real_leaks_are_caught():
    for t in REAL_TEXTS:
        assert gr.provider_hits(t) == [], t
    assert [gr.provider_hits(t) for t in REAL_LEAKS] == [["Zacks"], ["MarketBeat"]]


def test_hooks_and_post_vocab_carry_no_provider_word():
    assert not [h["id"] for h in pv.HOOKS if gr.provider_hits(h["text"])]
    for w in ("yahoo", "finnhub", "zacks", "apewisdom", "stocktwits", "factset", "marketbeat"):
        assert w not in pv.VOCAB, w
    assert "reddit" in pv.VOCAB and "mentions" in pv.VOCAB          # a platform, not a provider


def test_item_own_ticker_or_company_name_is_not_a_source():
    fds = {"item_id": f"{DATE}-earnings-result-FDS-1", "type": "earnings_result", "ticker": "FDS", "tickers": ["FDS"],
           "name": "FactSet Research Systems Inc."}
    iex = {"item_id": f"{DATE}-earnings-result-IEX-1", "type": "earnings_result", "ticker": "IEX", "tickers": ["IEX"],
           "name": "IDEX Corporation"}
    assert gr.provider_hits("FactSet Research Systems (FDS) published Q4 results.", fds) == []
    assert gr.provider_hits("IDEX Corporation (IEX) published Q3 results.", iex) == []
    # the exemption is the item's own: another provider in the same text, or no item, still counts
    assert gr.provider_hits("FactSet Research Systems (FDS) beat the Zacks consensus.", fds) == ["Zacks"]
    assert gr.provider_hits("IDEX Corporation (IEX) published Q3 results.") == ["IEX"]
    assert gr.provider_hits("FactSet consensus for $UNH.", {"item_id": "x", "ticker": "UNH", "name": "UnitedHealth"})


def test_review_rejects_a_provider_in_text_reply_alt_link_and_media():
    assert gr.review(good_x(), FACTS) == ("APPROVE", [])
    v, why = gr.review(good_x(alt="Chart via Yahoo Finance"), FACTS)
    assert v == "REJECT" and why == provider(why) and "alt 'Yahoo'" in why[0], why   # alt: the provider screen only
    assert why[0].startswith("provider: no data-provider name on a public surface (owner 10-19): ")
    v, why = gr.review(good_x(alt_text="logo by Elbstream"), FACTS)
    assert v == "REJECT" and "alt_text 'Elbstream'" in provider(why)[0]
    cases = [
        (dict(text=good_x()["text"].replace("Not investment", "Data: Finnhub. Not investment")), "text 'Finnhub'"),
        (dict(reply_text=good_x()["reply_text"] + "\nQuote: https://finance.yahoo.com/quote/UNH"),
         "reply_text 'finance.yahoo.com'"),
        (dict(link="https://stocktwits.com/symbol/UNH"), "link host stocktwits.com"),
        (dict(media_url="https://s.finance.yahoo.com/chart.png"), "media_url host s.finance.yahoo.com"),
        (dict(media_url="apewisdom.io/stocks/UNH.png"), "media_url 'apewisdom'"),     # no scheme: read as text
    ]
    for over, want in cases:
        v, why = gr.review(good_x(**over), FACTS)
        assert v == "REJECT" and provider(why) and want in provider(why)[0], (over, why)
    # one reason, every finding listed
    v, why = gr.review(good_x(alt="Zacks", link="https://www.zacks.com/x"), FACTS)
    assert len(provider(why)) == 1 and "alt 'Zacks'" in provider(why)[0] and "link host www.zacks.com" in provider(why)[0]


def test_review_allows_sec_and_our_own_media_paths():
    assert gr.review(form4_x("$BPRE: a director's insider buy (Form 4) of $2.42M, filed Oct 9, 2026. Not investment advice."),
                     FACTS_F4) == ("APPROVE", [])
    assert SEC_INDEX in form4_x("x")["reply_text"] and PTR in good_x()["reply_text"]
    ours = f"https://asafb2k.github.io/rapidtradeview-media/v/{DATE}/yahoo-test/feed_4x5.png"   # our host: path not read
    assert gr.review(good_x(media_url=ours), FACTS) == ("APPROVE", [])


def test_provider_reason_survives_an_unknown_item_or_missing_facts():
    v, why = gr.review(good_x(item_id=f"{DATE}-nope", alt="per Zacks"), FACTS)
    assert v == "REJECT" and provider(why) and any("is not in the" in r for r in why)
    v, why = gr.review(good_x(alt="per Zacks"), None)
    assert v == "REJECT" and provider(why)
    v, why = gr.review({"text": "Zacks", "platform": "x"}, FACTS)
    assert v == "REJECT" and provider(why) and why[-1] == "no item_id"


def test_comment_with_a_provider_name_is_rejected(tmp_path):
    state = gr.CommentState(tmp_path / "s.json")
    now = dt.datetime(2026, 10, 12, 14, 0, tzinfo=dt.timezone.utc)
    ok = {"kind": "comment", "platform": "x", "target_url": "https://x.com/someone/status/1844000000000000001",
          "text": "Useful context, thanks."}
    assert gr.review_comment(ok, None, state, now) == ("APPROVE", [])
    v, why = gr.review_comment(dict(ok, text="Useful context, thanks. StockTwits agrees."), None, state, now)
    assert v == "REJECT" and provider(why), why
    v, why = gr.review_comment(dict(ok, alt="Tiingo chart"), None, state, now)
    assert v == "REJECT" and "alt 'Tiingo'" in provider(why)[0]


# ---------------------------------------------------------------------------
# b) comment cap: 10 approved per platform per New York day

def _fill(state, n, at, platform="x"):
    for i in range(n):
        state.add({"kind": "comment", "platform": platform, "target_url": f"https://x.com/u{i}/status/{5000 + i}",
                   "text": f"filler remark {'abcdefghijklmnop'[i]} here"}, 900 + i, at)


def test_cap_counts_the_new_york_day_not_the_utc_day(tmp_path):
    state = gr.CommentState(tmp_path / "s.json")
    late_ny = dt.datetime(2026, 10, 12, 2, 0, tzinfo=dt.timezone.utc)        # Oct 11 22:00 New York (EDT)
    _fill(state, 10, late_ny)
    d = {"kind": "comment", "platform": "x", "target_url": "https://x.com/a/status/1", "text": "Useful context, thanks."}
    v, why = gr.review_comment(d, None, state, late_ny + dt.timedelta(hours=1, minutes=30))   # Oct 11 23:30 NY
    assert v == "REJECT" and why == ["cap: 10 comments a day on x (10 approved already on New York day 2026-10-11)"]
    # 00:30 New York on Oct 12: a new New York day, though the UTC day (Oct 12) is the same one
    assert gr.review_comment(d, None, state, late_ny + dt.timedelta(hours=2, minutes=30)) == ("APPROVE", [])
    # and the other way: approvals at 18:00 New York stay "today" after UTC midnight (21:00 New York)
    state2 = gr.CommentState(tmp_path / "s2.json")
    _fill(state2, 10, dt.datetime(2026, 10, 12, 22, 0, tzinfo=dt.timezone.utc))
    v, why = gr.review_comment(d, None, state2, dt.datetime(2026, 10, 13, 1, 0, tzinfo=dt.timezone.utc))
    assert v == "REJECT" and why[0].startswith("cap: 10 comments a day on x")
    assert state2.approved_today("x", dt.datetime(2026, 10, 13, 1, 0, tzinfo=dt.timezone.utc)) == 10
    assert state2.approved_today("instagram", dt.datetime(2026, 10, 13, 1, 0, tzinfo=dt.timezone.utc)) == 0


def test_cap_nine_approved_allows_the_tenth_only(tmp_path):
    state = gr.CommentState(tmp_path / "s.json")
    now = dt.datetime(2026, 10, 12, 15, 0, tzinfo=dt.timezone.utc)
    _fill(state, 9, now - dt.timedelta(hours=2))
    d = {"kind": "comment", "platform": "x", "target_url": "https://x.com/a/status/1", "text": "Useful context, thanks."}
    assert gr.review_comment(d, None, state, now) == ("APPROVE", [])
    state.add(d, 1, now)
    d2 = dict(d, target_url="https://x.com/b/status/2", text="Interesting thread.")
    v, why = gr.review_comment(d2, None, state, now)
    assert v == "REJECT" and why == ["cap: 10 comments a day on x (10 approved already on New York day 2026-10-12)"]


def test_entry_without_at_falls_back_to_its_date():
    assert gr.CommentState.entry_ny_day({"date": "2026-10-12"}) == "2026-10-12"
    assert gr.CommentState.entry_ny_day({"date": "2026-10-12", "at": "2026-10-12T03:00:00+00:00"}) == "2026-10-11"


def test_inbox_counts_approvals_of_the_same_run_against_the_cap(tmp_path):
    path = tmp_path / "state.json"
    now = dt.datetime(2026, 10, 12, 15, 0, tzinfo=dt.timezone.utc)
    st = gr.CommentState(path)
    _fill(st, 9, now - dt.timedelta(hours=1))
    st.save(now)
    c1 = {"kind": "comment", "platform": "x", "target_url": "https://x.com/a/status/11", "text": "Helpful breakdown, thanks."}
    c2 = {"kind": "comment", "platform": "x", "target_url": "https://x.com/b/status/12", "text": "Interesting thread."}
    rows = [{"id": 31, "kind": "report", "platform": "x", "item_id": None, "body": "DRAFT " + json.dumps(c1)},
            {"id": 32, "kind": "report", "platform": "x", "item_id": None, "body": "DRAFT " + json.dumps(c2)}]
    for dry in (True, False):
        sent = []
        gr.run_inbox(FakeRest(rows), INSTINCT, "prod", str(tmp_path / "v"), dry, lambda p, b: sent.append(b) or True,
                     comment_state=path, now=now)
        if dry:
            assert sent == [] and len(gr.CommentState(path).approved) == 9      # a dry run writes nothing
        else:
            assert sent[0] == "APPROVE 31 comment"
            assert sent[1].startswith("REJECT 32 comment: cap: 10 comments a day on x"), sent
            assert len(gr.CommentState(path).approved) == 10


# ---------------------------------------------------------------------------
# c) no grok_generated (the media rule; test_grok_comments.py guards the review() path too)

def test_grok_generated_is_rejected_at_the_inbox(tmp_path):
    d = tmp_path / "v" / DATE
    d.mkdir(parents=True)
    (d / "facts.json").write_text(json.dumps(FACTS), encoding="utf-8")
    draft = good_x(media_url="grok_generated", media_note="abstract dark trading desk")
    rows = [{"id": 41, "kind": "report", "platform": "x", "item_id": draft["item_id"], "body": "DRAFT " + json.dumps(draft)}]
    sent = []
    gr.run_inbox(FakeRest(rows), INSTINCT, "prod", str(tmp_path / "v"), False, lambda p, b: sent.append(b) or True)
    assert sent[0].startswith(f"REJECT 41 {CONGRESS['item_id']}: media_url grok_generated is not accepted")


# ---------------------------------------------------------------------------
# d) verdict self-retire (fake gateway; never prod)

NOW = dt.datetime(2026, 10, 26, 12, 0, tzinfo=dt.timezone.utc)
KIT = types.SimpleNamespace(q=lambda *p: "&".join(p), PAGE_ROWS=1000,
                            iso=lambda t: t.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"))


BASE = [NOW]   # the clock the row builders count back from (the CLI tests use the real clock: main reads now())


def at(hours_ago: float) -> str:
    return (BASE[0] - dt.timedelta(hours=hours_ago)).isoformat()


@pytest.fixture()
def real_clock():
    BASE[0] = dt.datetime.now(dt.timezone.utc)
    yield
    BASE[0] = NOW


class FakeKit:
    """The kit table behind the gateway: GET verdicts / post_logs / drafts, PATCH active=false. Anything else (a POST,
    a PATCH of another shape) fails the test."""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.calls: list[tuple] = []

    def _ids(self, query):
        return [int(x) for x in query.split("id=in.(")[1].split(")")[0].split(",")]

    def get_all(self, query):
        self.calls.append(("GET_ALL", query))
        assert "env=eq.prod" in query and "order=" in query
        if "direction=eq.to_instinct" in query:
            assert "kind=eq.answer" in query and "active=is.true" in query
            return [r for r in self.rows if r["direction"] == "to_instinct" and r["kind"] == "answer" and r["active"]]
        if "kind=eq.post_log" in query:
            assert "direction=eq.from_instinct" in query
            since = query.split("created_at=gte.")[1].split("&")[0] if "created_at=gte." in query else ""
            return [r for r in self.rows if r["kind"] == "post_log"
                    and (not since or gr._ts(r["created_at"]) >= gr._ts(since))]
        raise AssertionError(query)

    def call(self, method, query, body=None, prefer=None):
        self.calls.append((method, query))
        if method == "GET" and "acked_at=is.null" in query:
            return []
        if method == "GET":
            assert "direction=eq.from_instinct" in query and "id=in.(" in query
            ids = self._ids(query)
            return [r for r in self.rows if r["id"] in ids and r["direction"] == "from_instinct"]
        if method == "PATCH":
            assert body == {"active": False} and prefer == "return=representation"
            for f in ("env=eq.prod", "direction=eq.to_instinct", "kind=eq.answer", "active=is.true"):
                assert f in query, (f, query)
            out = []
            for r in self.rows:
                if r["id"] in self._ids(query) and r["direction"] == "to_instinct" and r["kind"] == "answer" and r["active"]:
                    r["active"] = False
                    out.append({"id": r["id"]})
            return out
        raise AssertionError((method, query))

    def active(self):
        return sorted(r["id"] for r in self.rows if r["direction"] == "to_instinct" and r["active"])


POST_ITEM = "2026-10-26-moves-like-AAOI-57e0fd"
POST_ITEM2 = "2026-10-26-earnings-week-preview-LIST-bb2c72"
CTARGET = "https://x.com/bigtrader/status/2112000000000000001"


def draft_row(rid, draft, hours_ago):
    return {"id": rid, "direction": "from_instinct", "kind": "report", "active": True, "platform": draft.get("platform"),
            "item_id": None, "created_at": at(hours_ago), "body": "DRAFT " + json.dumps(draft)}


def verdict_row(rid, body, platform, hours_ago, active=True):
    return {"id": rid, "direction": "to_instinct", "kind": "answer", "active": active, "platform": platform,
            "item_id": None, "created_at": at(hours_ago), "body": body}


def log_row(rid, platform, item_id, body, hours_ago):
    return {"id": rid, "direction": "from_instinct", "kind": "post_log", "active": True, "platform": platform,
            "item_id": item_id, "created_at": at(hours_ago), "body": body}


def kit_rows():
    post = {"item_id": POST_ITEM, "platform": "x", "text": "t"}
    post2 = {"item_id": POST_ITEM2, "platform": "threads", "text": "t"}
    com = {"kind": "comment", "platform": "x", "target_url": CTARGET, "text": "Interesting thread.", "item_id": POST_ITEM}
    return [
        # old verdicts: retired by age, logged or not
        verdict_row(101, "REJECT 100 2026-10-24-congress-flow-HD-20dcc8: viral: M8 same day", "x", 25),
        verdict_row(103, "APPROVE 102 comment", "instagram", 30),
        # Growth's own answers and audits: never touched, however old
        verdict_row(105, "to=rtv-grok-main; from=Growth. APPROVE the plan #104 as sent.", "x", 40),
        verdict_row(106, "AUDIT https://x.com/rapidtradeview/status/1: $2.83 is not in the facts item", "x", 40),
        # young post verdicts: REJECT then APPROVE of the same item; the post_log names neither
        draft_row(110, post, 5), verdict_row(111, f"REJECT 110 {POST_ITEM}: banned words: moon", "x", 5),
        draft_row(112, post, 4), verdict_row(113, f"APPROVE 112 {POST_ITEM}\nviral=M8/8 B2 P0", "x", 4),
        log_row(114, "x", POST_ITEM, "AAOI moves like ... Not investment advice.\n---\nkind=post; platform=x", 3),
        # young APPROVE whose post_log only names the draft and approval ids (no item_id column)
        draft_row(120, post2, 6), verdict_row(121, f"APPROVE 120 {POST_ITEM2}", "threads", 6),
        log_row(122, "threads", None, "Earnings this week ... | viral=M8/8 B2 P0 (APPROVE #121, draft #120).", 5),
        # young comment verdict on the same item: the own post's post_log (114) is not its post_log
        draft_row(130, com, 4.5), verdict_row(131, f"APPROVE 130 {POST_ITEM}", "x", 4.5),
        # young, still waiting for its post: stays active
        draft_row(140, post, 2), verdict_row(141, f"APPROVE 140 {POST_ITEM}", "instagram", 2),
        # a retired verdict stays retired (not read again)
        verdict_row(150, "APPROVE 149 comment", "x", 50, active=False),
    ]


def test_self_retire_by_age_and_by_post_log():
    kit = FakeKit(kit_rows())
    res = gr.self_retire(kit, KIT, "prod", NOW, False, lambda ids: gr.retire_rows(kit, KIT, "prod", ids))
    assert res["ids"] == [101, 103, 111, 113, 121] and res["retired"] == 5 and res["active"] == 7
    assert kit.active() == [105, 106, 131, 141]
    assert not any(m == "POST" for m, _ in kit.calls)


def test_comment_verdict_retires_on_its_target_post_log_only():
    rows = kit_rows() + [log_row(160, "x", POST_ITEM, f"Interesting thread.\n---\nkind=comment; target_url={CTARGET}?s=20; "
                                                      "url=https://x.com/rapidtradeview/status/9", 1)]
    kit = FakeKit(rows)
    res = gr.self_retire(kit, KIT, "prod", NOW, False, lambda ids: gr.retire_rows(kit, KIT, "prod", ids))
    assert 131 in res["ids"] and 141 not in res["ids"]
    # a comment post_log on the post verdict's item does not retire the post verdict (141: instagram anyway)
    rows2 = kit_rows()[:-3] + [draft_row(140, {"item_id": POST_ITEM, "platform": "x", "text": "t"}, 2),
                                verdict_row(141, f"APPROVE 140 {POST_ITEM}", "x", 2),
                                log_row(161, "x", POST_ITEM, "c\n---\nkind=comment; target_url=https://x.com/z/status/5", 1)]
    kit2 = FakeKit(rows2)
    assert 141 not in gr.self_retire(kit2, KIT, "prod", NOW, True, lambda ids: 0)["ids"]


def test_post_log_before_the_verdict_or_on_another_platform_does_not_count():
    rows = [draft_row(200, {"item_id": POST_ITEM, "platform": "x", "text": "t"}, 3),
            verdict_row(201, f"APPROVE 200 {POST_ITEM}", "x", 3),
            log_row(202, "x", POST_ITEM, "an earlier post of the item", 4),          # before the verdict
            log_row(203, "threads", POST_ITEM, "the threads post of the item", 2)]   # another platform
    kit = FakeKit(rows)
    assert gr.self_retire(kit, KIT, "prod", NOW, False, lambda ids: gr.retire_rows(kit, KIT, "prod", ids))["ids"] == []
    assert kit.active() == [201]


def test_dry_run_prints_and_writes_nothing(capsys):
    kit = FakeKit(kit_rows())
    called = []
    res = gr.self_retire(kit, KIT, "prod", NOW, True, lambda ids: called.append(ids) or 99)
    assert res["ids"] == [101, 103, 111, 113, 121] and res["retired"] == 0 and called == []
    assert not any(m == "PATCH" for m, _ in kit.calls) and kit.active() == [101, 103, 105, 106, 111, 113, 121, 131, 141]
    out = capsys.readouterr().out
    assert "verdicts (prod): 7 active, 5 to retire (dry run: nothing retired)" in out
    assert "would retire #101 (REJECT of draft #100): older than 24 h" in out
    assert "would retire #121 (APPROVE of draft #120): its post_log arrived" in out


def test_no_young_verdicts_reads_no_post_logs():
    kit = FakeKit([verdict_row(301, "APPROVE 300 comment", "x", 30)])
    res = gr.self_retire(kit, KIT, "prod", NOW, False, lambda ids: gr.retire_rows(kit, KIT, "prod", ids))
    assert res["ids"] == [301] and [c for c in kit.calls if "post_log" in c[1]] == []


def test_retire_rows_batches_with_the_safe_filters():
    rows = [verdict_row(1000 + i, f"APPROVE {500 + i} comment", "x", 30) for i in range(120)]
    kit = FakeKit(rows)
    assert gr.retire_rows(kit, KIT, "prod", [r["id"] for r in rows]) == 120
    patches = [q for m, q in kit.calls if m == "PATCH"]
    assert len(patches) == 3 and kit.active() == []


def test_parse_verdict_reads_only_validator_answers():
    v = gr.parse_verdict({"id": 7, "body": "REJECT 6 2026-10-24-congress-flow-HD-20dcc8: viral: M8", "platform": "X",
                          "created_at": "2026-10-25T12:51:02.503612+00:00"})
    assert v["verdict"] == "REJECT" and v["draft_id"] == 6 and v["item_id"] == "2026-10-24-congress-flow-HD-20dcc8"
    assert v["platform"] == "x" and v["at"].tzinfo is not None
    assert gr.parse_verdict({"id": 8, "body": "APPROVE 5 comment"})["item_id"] is None
    assert gr.parse_verdict({"id": 9, "body": "REJECT 4 (no valid item_id): the body must be"})["item_id"] is None
    for body in ("to=rtv-grok-main; from=Growth. APPROVE 5 x", "AUDIT https://x.com/a", "approve 5 x", "", None):
        assert gr.parse_verdict({"id": 10, "body": body}) is None


class FakeInstinct(types.SimpleNamespace):
    pass


def _fake_instinct(kit):
    return FakeInstinct(DEFAULT_ENV_FILE=Path("unused.env"), load_config=lambda p: ("https://gateway.invalid", "k"),
                        Rest=lambda url, key: kit, q=KIT.q, iso=KIT.iso, PAGE_ROWS=1000)


def test_cli_inbox_retires_after_answering_and_flags_work(monkeypatch, tmp_path, capsys, real_clock):
    monkeypatch.setattr(gr, "send_reply", lambda *a, **k: pytest.fail("no answer may be sent in this test"))
    common = ["--inbox", "--facts-base", str(tmp_path / "v"), "--comment-state", str(tmp_path / "c.json"),
              "--variety-state", str(tmp_path / "v.json"), "--approved-ledger", str(tmp_path / "l.json")]
    kit = FakeKit(kit_rows())
    monkeypatch.setattr(gr, "load_instinct", lambda p: _fake_instinct(kit))
    assert gr.main(common + ["--dry-run"]) == 0
    assert not any(m == "PATCH" for m, _ in kit.calls) and "would retire #101" in capsys.readouterr().out
    kit.calls.clear()
    assert gr.main(common + ["--no-retire"]) == 0
    assert not any("kind=eq.answer" in q for _, q in kit.calls) and len(kit.active()) == 9
    assert gr.main(common) == 0
    assert kit.active() == [105, 106, 131, 141]


def test_cli_gateway_error_during_retire_never_fails_the_run(monkeypatch, tmp_path, capsys, real_clock):
    class Down(FakeKit):
        def get_all(self, query):
            if "kind=eq.answer" in query:
                raise SystemExit("GET social_kit_messages: HTTP 503 upstream")
            return super().get_all(query)
    kit = Down(kit_rows())
    monkeypatch.setattr(gr, "load_instinct", lambda p: _fake_instinct(kit))
    assert gr.main(["--inbox", "--facts-base", str(tmp_path / "v"), "--comment-state", str(tmp_path / "c.json"),
                    "--approved-ledger", str(tmp_path / "l.json"), "--variety-state", str(tmp_path / "v.json")]) == 0
    assert "verdict retire skipped this run: GET social_kit_messages: HTTP 503" in capsys.readouterr().out
