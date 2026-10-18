"""Validator rules for the market pillars (HQ 2026-10-18, social-content PLAN §4) on the real 2026-10-16 session.
Run: python -m pytest tools/tests -q (offline)."""
import datetime as dt
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "tests"))
import facts as fx  # noqa: E402
import grok_review as gr  # noqa: E402
import manifest as mf  # noqa: E402
from test_market_facts import NOW_SUN, SUN, FixtureApi  # noqa: E402

PAGES = mf.PAGES_BASE
NOW = dt.datetime(2026, 10, 18, 20, 0, tzinfo=dt.timezone.utc)


def build_doc() -> dict:
    items, *_, m = fx.market_items(FixtureApi(), SUN, NOW_SUN, None)
    pep = fx.make_item("2026-10-18", "form4_buy", "PEP", "form4:0001:PEP", "/smart-money/figures/robert-c-pohlad",
                       name="Robert C. Pohlad", office="Director at PepsiCo, Inc.", company="PepsiCo, Inc.", side="buy",
                       amount_top_usd=10.84e6, amount_text="$10.84M", filed="2026-10-16", traded=["2026-10-14"],
                       figure_slug="robert-c-pohlad", source_url="https://www.sec.gov/Archives/edgar/data/1/0001/index.json",
                       facts_text="Robert C. Pohlad (Director at PepsiCo, Inc.) reported an open-market purchase of PEP totaling $10.84M.",
                       allowed_numbers=["$10.84M", *fx.date_forms("2026-10-16"), *fx.date_forms("2026-10-14")])
    ko = fx.make_item("2026-10-18", "form4_buy", "KO", "form4:0002:KO", "/smart-money/figures/x", name="X Y",
                      office="Director at Coca-Cola", side="buy", amount_top_usd=2e6, filed="2026-10-16", facts_text="k",
                      allowed_numbers=["$2M"])
    allit = items + [pep, ko]
    fx.enrich(allit, m)
    for it in allit:  # what pin_cards.apply writes
        c = it.get("card")
        if c:
            c["url"] = f"{PAGES}/v/2026-10-18/cards/{c['file']}"
            it["media"] = [{"url": c["url"], "kind": "image", "alt": it["facts_text"]}]
    return {"schema": fx.SCHEMA, "date": "2026-10-18",
            "rules": {"banned_words": fx.BANNED_WORDS, "disclaimer": fx.DISCLAIMER, "max_len": fx.MAX_LEN,
                      "platform_placeholder": "{platform}"}, "items": allit}


DOC = build_doc()
# what the runner publishes: every item through facts.self_check (claim phrases and angles a post may copy pass the post
# checks; `moves` filled in)
DOC_RAW_ITEMS = [dict(i) for i in DOC["items"]]
DOC["items"], DOC_SELF_ERRORS, DOC_SELF_DROPPED = fx.self_check([dict(i) for i in DOC["items"]])


def item(kind, ticker=None):
    return next(i for i in DOC["items"] if i["type"] == kind and (ticker is None or i.get("ticker") == ticker))


def draft(it, text, platform="x", **over):
    link = it["page_url"].replace("{platform}", platform)
    d = {"item_id": it["item_id"], "platform": platform, "text": text, "link": link,
         "reply_text": f"Every company on one map: {link}" if platform == "x" else "", "media_url": it["media"][0]["url"]}
    d.update(over)
    return d


# HQ 2026-10-19 allowlist: every comparison in a post is one of the item's claim_phrases, verbatim
P1 = ("The 500 largest US-listed stocks lost about $1.0T on Friday, −1.21%. $GOOGL had the biggest dollar drop among the "
      "500 largest US-listed companies on Friday (−$105.5B). Energy went the other way on Friday (+2.64%). "
      "Every company on one map below. Not investment advice.")


def test_plan_examples_are_approved():
    mm = item("market_move")
    assert gr.review(draft(mm, P1), DOC, NOW) == ("APPROVE", [])
    assert gr.review(draft(mm, P1, platform="threads"), DOC, NOW) == ("APPROVE", [])
    g = item("mega_mover", "GOOGL")
    t = ("$GOOGL lost $105.5B of market value on Friday, −2.47%. $GOOGL had the biggest dollar drop among the 500 largest "
         "US-listed companies on Friday (−$105.5B). $MSFT had the second-biggest dollar drop among the 500 largest "
         "US-listed companies on Friday (−$77.2B). Not investment advice.")
    assert gr.review(draft(g, t, platform="threads"), DOC, NOW) == ("APPROVE", [])
    b = item("reddit_buzz")
    t = ("Reddit is talking about $NBIS 7.5× more than usual: 45 mentions vs 6.0. The stock fell 12.18% on Friday. "
         "$SNDK: 3.3× usual. 10 of the 10 most-mentioned stocks with a close for Oct 16 fell that day. "
         "Not investment advice.")
    assert gr.review(draft(b, t, platform="threads"), DOC, NOW) == ("APPROVE", [])
    w = next(i for i in DOC["items"] if i["type"] == "sector_rotation" and i["window"] == "week")
    t = ("In the week to Oct 16 the 500 largest US-listed stocks fell 2.7%. Tech −7.3%, Industrials −3.9%. "
         "Consumer Defensive +5.5% and Energy +5.0% rose. $DEO led Consumer Defensive among the 500 largest US-listed "
         "companies in the week to Oct 16 (+9.66%). Not investment advice.")
    assert gr.review(draft(w, t, platform="threads"), DOC, NOW) == ("APPROVE", [])
    k = item("basket_week")
    t = ("Owning the 10 largest US-listed companies equally cost 5.04% in the week to Oct 16. Only $AAPL of the 10 largest "
         "US-listed companies rose in the week to Oct 16 (+2.03%). $AVGO −9.07%. Not investment advice.")
    assert gr.review(draft(k, t), DOC, NOW) == ("APPROVE", [])


def test_single_ticker_item_may_use_its_context():
    pep = item("form4_buy", "PEP")
    assert pep["context_tickers"] == ["KO"]
    t = ("PepsiCo director Robert C. Pohlad bought $10.84M of $PEP on the open market (traded Oct 14, Form 4 filed Oct 16). "
         "Across our feed, officers and directors bought $650M and sold $4.4B on the open market over 30 days. "
         "Not investment advice.")
    d = draft(pep, t, reply_text=f"Filing: {pep['source_url']}\n{pep['page_url'].replace('{platform}', 'x')}")
    assert gr.review(d, DOC, NOW) == ("APPROVE", [])
    d2 = dict(d, text=t.replace("Across our feed", "See also $KO. Across our feed"))
    assert gr.review(d2, DOC, NOW) == ("APPROVE", [])
    v, why = gr.review(dict(d, text=t.replace("Across our feed", "$MSFT too. Across our feed")), DOC, NOW)
    assert v == "REJECT" and any("$MSFT" in r for r in why)
    v, why = gr.review(dict(d, text=t.replace("$4.4B", "$4.9B")), DOC, NOW)
    assert v == "REJECT" and any("$4.9B" in r for r in why)


def test_market_wording_guard():
    mm = item("market_move")
    for bad in ("The S&P 500 lost about $1.0T on Friday", "The index lost about $1.0T on Friday"):
        v, why = gr.review(draft(mm, P1.replace("The 500 largest US-listed stocks lost about $1.0T on Friday", bad)), DOC, NOW)
        assert v == "REJECT" and any("universe wording" in r for r in why), bad
    bare = "Stocks lost about $1.0T on Friday, −1.21%. Energy went the other way, +2.64%. Not investment advice."
    v, why = gr.review(draft(mm, bare), DOC, NOW)
    assert v == "REJECT" and any('needs "500 largest"' in r for r in why)
    v, why = gr.review(draft(mm, P1.replace("Every company", "All 500 companies")), DOC, NOW)
    assert v == "REJECT" and any("all 500" in r for r in why)
    v, why = gr.review(draft(mm, P1.replace("went the other way", "dumped")), DOC, NOW)
    assert v == "REJECT" and any("banned words" in r for r in why)


def test_card_check():
    mm = item("market_move")
    v, why = gr.review(draft(mm, P1, media_url="https://www.rapidtradeview.trade/market/card/map"), DOC, NOW)
    assert v == "REJECT" and any("live /market/card/" in r for r in why)
    wrong = f"{PAGES}/v/2026-10-15/cards/market-map-2026-10-14-abcdef12.png"
    v, why = gr.review(draft(mm, P1, media_url=wrong), DOC, NOW)
    assert v == "REJECT" and any("another item or day" in r for r in why)
    other = f"{PAGES}/v/2026-10-18/some-video.mp4"
    v, why = gr.review(draft(mm, P1, media_url=other), DOC, NOW)
    assert v == "REJECT" and any("pinned card" in r for r in why)
    pep = item("form4_buy", "PEP")
    v, why = gr.review(draft(pep, "x", media_url=mm["media"][0]["url"]), DOC, NOW)
    assert v == "REJECT" and any("another item or day" in r for r in why)


def hist(platform, ticker, date, pillar, text="", dedupe="other", iid="2026-10-15-form4-buy-PEP-aaaaaa"):
    return {"platform": platform, "ticker": ticker, "ny_date": date, "pillar": pillar, "text": text, "dedupe_key": dedupe,
            "item_id": iid, "created_at": f"{date}T15:00:00+00:00", "filer": None}


def test_variety_warns_first_then_rejects_a_repeat(tmp_path):
    pep = item("form4_buy", "PEP")
    t = "PepsiCo director Robert C. Pohlad bought $10.84M of $PEP on the open market. Not investment advice."
    d = draft(pep, t, reply_text=f"{pep['source_url']}\n{pep['page_url'].replace('{platform}', 'x')}")
    h = [hist("x", "PEP", "2026-10-16", "P3")]
    state = gr.VarietyState(tmp_path / "v.json")
    rej, notes, rec = gr.apply_variety(d, DOC, h, state, NOW)
    assert rej == [] and "rule7_ticker_repeat" in rec and "rule5_same_pillar" in rec
    assert any("VARIETY WARN rule7_ticker_repeat" in n for n in notes)
    for r in rec:
        state.add("2026-10-18", "x", r, 1)
    rej, notes, rec = gr.apply_variety(d, DOC, h, state, NOW)
    assert any("rule7_ticker_repeat (a repeat today)" in r for r in rej)
    # other platforms and older posts do not count
    assert gr.apply_variety(dict(d, platform="instagram"), DOC, h, state, NOW)[0] == []
    assert gr.variety_breaches(d, pep, [hist("x", "PEP", "2026-10-12", "P5")], NOW) == []


def test_variety_first_line_twin_and_duplicate_number():
    mm = item("market_move")
    h = [hist("x", None, "2026-10-17", "P4", text="The 500 largest US-listed stocks lost about $0.9T on Thursday.")]
    rules = [r for r, _ in gr.variety_breaches(draft(mm, P1), mm, h, NOW)]
    assert "rule8_first_line" in rules
    twin = [hist("threads", None, "2026-10-18", "P1", text=P1, dedupe=mm["dedupe_key"], iid=mm["item_id"])]
    assert "rule9_cross_platform" in [r for r, _ in gr.variety_breaches(draft(mm, P1), mm, twin, NOW)]
    fresh = ("About $1.0T gone from the 500 largest US-listed stocks on Friday. Tech alone: −$886B. $GOOGL −2.47%, "
             "$MSFT −1.93%. Energy +2.64% led the gainers. Not investment advice.")
    assert "rule9_cross_platform" not in [r for r, _ in gr.variety_breaches(draft(mm, fresh), mm, twin, NOW)]
    dup = P1.replace("Energy went the other way on Friday (+2.64%).", "Energy +2.64%, so +2.64% for energy.")
    assert "rule10_duplicate_number" in [r for r, _ in gr.variety_breaches(draft(mm, dup), mm, [], NOW)]


def test_inbox_variety_state_is_written_after_an_approve(tmp_path):
    from test_grok_review import FakeRest, INSTINCT
    mm = item("market_move")
    vdir = tmp_path / "v" / "2026-10-18"
    vdir.mkdir(parents=True)
    (vdir / "facts.json").write_text(json.dumps(DOC), encoding="utf-8")
    rows = [{"id": 21, "kind": "report", "platform": "x", "item_id": mm["item_id"], "body": "DRAFT " + json.dumps(draft(mm, P1))}]
    h = [hist("x", None, "2026-10-17", "P1", text="Something else entirely about markets.")]
    sent = []
    gr.run_inbox(FakeRest(rows), INSTINCT, "prod", str(tmp_path / "v"), False, lambda p, b: sent.append(b) or True,
                 now=NOW, history=h, variety_state=tmp_path / "vs.json", comment_state=tmp_path / "c.json")
    assert sent[0].startswith(f"APPROVE 21 {mm['item_id']}") and "VARIETY WARN rule5_same_pillar" in sent[0]
    st = json.loads((tmp_path / "vs.json").read_text(encoding="utf-8"))
    assert st["warned"][0]["rule"] == "rule5_same_pillar"


# ---------------------------------------------------------------------------
# HQ review 2026-10-18: universe wording on every item type, backed comparisons only, sector attribution, scopes,
# the card's message, the week window. Every item's own facts_text and angles pass the same checks.

def threads(it, text):
    return draft(it, text, platform="threads", reply_text="")


def test_every_item_text_and_angle_passes_the_content_checks():
    assert DOC_SELF_ERRORS == []
    raw = {i["item_id"]: i for i in DOC_RAW_ITEMS}
    for it in DOC["items"]:
        # the data sheet is not a post: every check but the allowlist (it states rankings in its own words)
        assert gr.cl.content_reasons(it, it["facts_text"], gr.strip_allowed, allowlist=False) == [], it["type"]
        # every claim phrase survives the self-check (a post may copy each one verbatim)
        assert it.get("claim_phrases") == list(dict.fromkeys(raw[it["item_id"]].get("claim_phrases") or [])), it["type"]
        for text in [it["facts_text"], *it.get("angles", []), *it.get("claim_phrases", [])]:
            assert gr.unexplained_numbers(text, gr.item_numbers(it), gr.item_cashtags(it)) == [], (it["type"], text)
            assert "S&P" not in text and not re.search(r"\bthis week\b", text), (it["type"], text)
        for text in [*it.get("angles", []), *it.get("claim_phrases", [])]:
            assert gr.wording_reasons(it, text) == [], (it["type"], text)
    # the market items keep at least 2 angles each (they were rewritten as claim phrases where they ranked)
    for it in DOC["items"]:
        if it["type"] in gr.mk.MARKET_TYPES:
            assert len(it["angles"]) >= 2, (it["type"], it["angles"])


def test_sp500_is_rejected_on_every_item_type():
    pv, bz, pep = item("earnings_week_preview"), item("reddit_buzz"), item("form4_buy", "PEP")
    drafts = [
        (pv, "60 S&P 500 companies worth $10B+ report earnings in the week of Oct 19. The biggest: $SPCX, $META, $TSLA. "
             "Not investment advice."),
        (bz, "Reddit is talking about $NBIS 7.5× more than usual: 45 mentions vs 6, more than any S&P500 name. "
             "Not investment advice."),
        (pep, "PepsiCo director Robert C. Pohlad bought $10.84M of $PEP, an S&P 500 stock, on the open market. "
              "Not investment advice."),
        (pep, "PepsiCo director Robert C. Pohlad bought $10.84M of $PEP on the open market while the SPX fell. "
              "Not investment advice."),
    ]
    for it, text in drafts:
        v, why = gr.review(threads(it, text), DOC, NOW)
        assert v == "REJECT" and any("universe wording" in r for r in why), text
    # the right words pass
    ok = ("60 of the 500 largest US-listed companies (each worth $10B+) report earnings in the week of Oct 19. The "
          "largest companies reporting earnings in the week of Oct 19 (by market value, confirmed dates), in order: "
          "$SPCX, $META, $TSLA. Not investment advice.")
    assert gr.review(threads(pv, ok), DOC, NOW) == ("APPROVE", [])
    v, why = gr.review(threads(pv, ok.replace("in the week of Oct 19", "this week")), DOC, NOW)
    assert v == "REJECT" and any("window" in r for r in why)          # built Sunday: the week of Oct 19, not "this week"


def test_benchmark_comparison_only_on_a_picks_item():
    picks = fx.make_item("2026-10-18", "picks_ready", None, "picks:2026-10-16", "/picks/2026-10-16", tickers=["DRS"],
                         facts_text="The daily picks list is published.", allowed_numbers=["5"])
    doc = dict(DOC, items=[*DOC["items"], picks])
    d = dict(threads(picks, "Our picks are graded 5 sessions out vs the S&P 500 (SPY). Today: $DRS. Not investment advice."),
             media_url=f"{PAGES}/v/2026-10-18/picks.png")
    assert gr.review(d, doc, NOW) == ("APPROVE", [])
    assert gr.review(dict(d, text=d["text"].replace("vs the S&P 500 (SPY)", "vs SPY")), doc, NOW) == ("APPROVE", [])
    v, why = gr.review(dict(d, text=d["text"].replace("vs the S&P 500 (SPY)", "and beat the S&P 500")), doc, NOW)
    assert v == "REJECT" and any("universe wording" in r for r in why)


def test_unbacked_superlatives_are_rejected():
    w = next(i for i in DOC["items"] if i["type"] == "sector_rotation" and i["window"] == "week")
    base = "In the week to Oct 16 the 500 largest US-listed stocks fell 2.7% ($NVDA −6.61%). "
    bad = [
        "$WMT +6.70% and $XOM +5.94% led their sectors.",                 # the review's sample: false (DEO, COP led)
        "$WMT +6.70% had the biggest gain in Consumer Defensive.",
        "Energy was the worst sector, +5.0%.",                              # Tech was the worst
        "$NVDA −6.61% was the worst stock in Tech.",                   # CIEN was
    ]
    for t in bad:
        v, why = gr.review(threads(w, base + t + " Not investment advice."), DOC, NOW)
        assert v == "REJECT" and any("unsupported comparison" in r for r in why), t
    good = ["$DEO led Consumer Defensive among the 500 largest US-listed companies in the week to Oct 16 (+9.66%).",
            "Tech was the worst sector in the week to Oct 16 (−7.3%).",
            "By market value, $WMT was the biggest Consumer Defensive name moving with its sector in the week to Oct 16 "
            "(+6.70%)."]
    for t in good:
        assert gr.review(threads(w, base + t + " Not investment advice."), DOC, NOW) == ("APPROVE", []), t
    mm = item("market_move")
    v, why = gr.review(draft(mm, P1.replace("$GOOGL had the biggest dollar drop", "$GOOGL had the only drop")), DOC, NOW)
    assert v == "REJECT" and any("unsupported comparison" in r for r in why)
    v, why = gr.review(draft(mm, P1.replace("biggest dollar drop", "biggest % drop")), DOC, NOW)
    assert v == "REJECT" and any("unsupported comparison" in r for r in why)   # a $ ranking, not a % one
    g = item("mega_mover", "GOOGL")
    t = "$GOOGL lost $105.5B on Friday, −2.47%, the first time it fell that much. Not investment advice."
    v, why = gr.review(draft(g, t), DOC, NOW)
    assert v == "REJECT" and any("first" in r for r in why)


def test_sector_attribution():
    mm = item("market_move")
    # r4 review: a sector sentence no longer lends its sector to the cashtags of the NEXT sentence ("Tech was the worst
    # sector on Friday. $NVDA −1.43%, $XOM +2.46%." is honest); inside one sentence it still does
    assert gr.review(draft(mm, "The 500 largest US-listed stocks lost about $1.0T on Friday. Technology: −$886B. "
                               "$GOOGL −2.47%, $MSFT −1.93%. Not investment advice."), DOC, NOW) == ("APPROVE", [])
    for t in ("The 500 largest US-listed stocks lost about $1.0T on Friday. Tech was −$886B of it: $GOOGL −2.47%, $MSFT "
              "−1.93%. Not investment advice.",
              "The 500 largest US-listed stocks lost about $1.0T on Friday. $GOOGL −2.47% (Tech) and $MSFT −1.93%. "
              "Not investment advice."):
        v, why = gr.review(draft(mm, t), DOC, NOW)
        assert v == "REJECT" and any("$GOOGL" in r and "Communication Services" in r for r in why), t
    t = ("The 500 largest US-listed stocks lost about $1.0T on Friday. Tech was −$886B of it: $MSFT −1.93%, "
         "$NVDA −1.43%. Not investment advice.")
    assert gr.review(draft(mm, t), DOC, NOW) == ("APPROVE", [])


def test_breadth_text_does_not_contradict_its_card():
    b = item("breadth_day")
    v, why = gr.review(draft(b, "1,631 of 2,497 US stocks fell on Friday, but the damage was concentrated in $GOOGL, "
                                "$MSFT and $NVDA. Not investment advice."), DOC, NOW)
    assert v == "REJECT" and any("card" in r for r in why)
    v, why = gr.review(draft(b, "The 500 largest US-listed stocks moved −1.21% on Friday, yet the median company moved "
                                "−0.03%. Not investment advice."), DOC, NOW)
    assert v == "REJECT"
    ok = ("1,631 of 2,497 US stocks fell on Friday (65%). $GOOGL was the biggest dollar drag among the 500 largest "
          "US-listed companies on Friday (−$105.5B). Not investment advice.")
    assert gr.review(draft(b, ok), DOC, NOW) == ("APPROVE", [])


def test_insider_totals_carry_their_scope():
    pep = item("form4_buy", "PEP")
    t = ("PepsiCo director Robert C. Pohlad bought $10.84M of $PEP on the open market. Insiders bought $650M and sold "
         "$4.4B over 30 days. Not investment advice.")
    v, why = gr.review(threads(pep, t), DOC, NOW)
    assert v == "REJECT" and any("officers and directors" in r for r in why)
    ok = t.replace("Insiders bought $650M and sold $4.4B over 30 days",
                   "Officers and directors bought $650M and sold $4.4B on the open market over 30 days in our feed")
    assert gr.review(threads(pep, ok), DOC, NOW) == ("APPROVE", [])


def test_rule7_cools_a_ticker_down_across_pillars():
    mm = item("market_move")
    h = [dict(hist("x", "GOOGL", "2026-10-17", "P2", text="$GOOGL lost $105.5B."), headline_tickers=["GOOGL"])]
    rules = dict(gr.variety_breaches(draft(mm, P1), mm, h, NOW))
    assert "rule7_ticker_repeat" in rules and "$GOOGL" in rules["rule7_ticker_repeat"]


def test_monday_flow_items_pass_their_own_checks():
    from test_market_facts import MON
    mon = dt.datetime(2026, 10, 19, 13, 0, tzinfo=dt.timezone.utc)
    items, *_, m = fx.market_items(FixtureApi(), MON, mon, None)
    fx.enrich(items, m)
    raw = {i["item_id"]: list(dict.fromkeys(i.get("claim_phrases") or [])) for i in items}
    items, errs, _ = fx.self_check(items)
    assert errs == []
    kinds = {i["type"] for i in items}
    assert {"congress_flow", "insider_flow"} <= kinds
    for it in items:
        assert it["claim_phrases"] == raw[it["item_id"]], it["type"]
        assert gr.cl.content_reasons(it, it["facts_text"], gr.strip_allowed, allowlist=False) == [], it["type"]
        for text in [*it["angles"], *it["claim_phrases"]]:
            assert gr.wording_reasons(it, text) == [], (it["type"], text)
        for text in [it["facts_text"], *it["angles"], *it["claim_phrases"]]:
            assert gr.unexplained_numbers(text, gr.item_numbers(it), gr.item_cashtags(it)) == [], (it["type"], text)
    ins = next(i for i in items if i["type"] == "insider_flow")
    assert ins["facts_text"].startswith("Officers and directors reported $650M of open-market buys and $4.4B of "
                                        "open-market sells over 30 days in our feed")
    basket = next(i for i in items if i["type"] == "basket_week")
    assert basket["when"] == "last week"


def test_track_record_is_a_page_not_a_record_claim():
    picks = fx.make_item("2026-10-18", "picks_ready", None, "picks:2026-10-16", "/picks/2026-10-16", tickers=["DRS"],
                         facts_text="The daily picks list is published.", allowed_numbers=["Oct 16"])
    assert gr.wording_reasons(picks, "Our picks for Oct 16: $DRS. The full list and the track record are on our page.") == []
    assert gr.wording_reasons(picks, "Our picks for Oct 16: $DRS, a record list.") != []


def test_a_question_to_the_reader_is_not_a_claim():
    g = item("mega_mover", "GOOGL")
    assert gr.wording_reasons(g, "Which mega cap move surprised you most on Friday?") == []
    assert gr.wording_reasons(g, "Was Energy the biggest dollar loser on Friday?") != []


def test_idioms_that_are_not_claims():
    g = item("mega_mover", "GOOGL")
    for t in ("Link in the first comment.", "Every company on one map below.", "The next session: −2.47%."):
        assert gr.wording_reasons(g, t) == [], t
    # the allowlist reads "only" broadly (HQ 2026-10-19): an idiom with it is rewritten, never a claim
    for t in ("Only Energy rose on Friday.", "The report has EPS only: $1.16 vs $1.21.", "Link in bio only."):
        assert gr.wording_reasons(g, t) != [], t


# Claim polarity and rank (HQ review 2026-10-18 round 2): a claim carries kind (stock / sector), polarity (best / worst /
# none), rank (1 / group in order) and within (its scope). Every case below is one a reviewer found approved before.

def week_rot():
    return next(i for i in DOC["items"] if i["type"] == "sector_rotation" and i["window"] == "week")


def day_rot():
    return next(i for i in DOC["items"] if i["type"] == "sector_rotation" and i["window"] == "day")


def rejected(it, text):
    why = gr.wording_reasons(it, text)
    assert why, text
    return why


def approved(it, text):
    assert gr.wording_reasons(it, text) == [], text


def approved_or_not_a_phrase(it, text):
    """Rounds 1-4 approved these true sentences. Under the allowlist (HQ 2026-10-19) one that is not a claim phrase is
    rejected by the allowlist alone, and no other check (direction, window, sector, universe) fires on it."""
    why = gr.wording_reasons(it, text)
    assert all(r.startswith("unsupported comparison:") for r in why), (text, why)


def test_neutral_superlatives_take_the_sentence_polarity():
    w, d, mm = week_rot(), day_rot(), item("market_move")
    # the MAJOR: no up / down word, so the direction was never checked; Tech was the WORST sector both windows
    for it in (w, d, mm):
        rejected(it, "Tech was the top sector.")
        rejected(it, "Tech was the top-performing group.")
        rejected(it, "Tech topped every sector.")
        rejected(it, "Tech was the biggest winner.")
    rejected(w, "Industrials led in the week to Oct 16.")                 # a down sector, and only a scope of stock claims
    rejected(w, "Energy was the top sector in the week to Oct 16.")       # #2: Consumer Defensive was the best
    rejected(w, "No other sector beat Energy in the week to Oct 16.")
    rejected(w, "Energy was the worst sector, +5.0%.")
    approved_or_not_a_phrase(mm, "Technology led the move.")              # the facts_text's own words: "led the move" has no side (r3)
    rejected(mm, "Energy +2.64% led the move on Friday.")                 # Energy went the other way
    rejected(w, "Tech was No. 1 in the week to Oct 16.")
    approved_or_not_a_phrase(w, "Consumer Defensive was No. 1 in the week to Oct 16, +5.5%.")
    approved_or_not_a_phrase(w, "Consumer Defensive was the top sector in the week to Oct 16.")
    approved_or_not_a_phrase(w, "Tech was the worst sector in the week to Oct 16, −7.3%.")
    approved_or_not_a_phrase(d, "Energy was the top sector on Friday, +2.6%.")
    approved_or_not_a_phrase(mm, "Technology led the move, −$886B.")
    approved_or_not_a_phrase(mm, "Technology led the drop.")
    approved_or_not_a_phrase(mm, "Energy was the best sector on Friday.")


def test_stock_claims_inside_a_sector():
    w, d = week_rot(), day_rot()
    rejected(w, "$CIEN was the top stock in Tech in the week to Oct 16.")                 # CIEN was the worst
    rejected(w, "$SPCX was the biggest market value winner in Industrials in the week to Oct 16.")  # it fell
    rejected(w, "$COP +9.25% led Consumer Defensive in the week to Oct 16.")              # COP led Energy
    rejected(w, "$DEO +9.66% led Energy and $COP +9.25% led Consumer Defensive.")         # swapped pairs
    rejected(w, "$WMT +6.70% outperformed every other stock in Consumer Defensive in the week to Oct 16.")
    approved_or_not_a_phrase(w, "$CIEN −26.02% was the worst stock in Tech in the week to Oct 16.")
    approved_or_not_a_phrase(w, "$DEO +9.66% led its sector in the week to Oct 16.")
    approved_or_not_a_phrase(d, "$GOOGL −2.47% and $NVDA −1.43% were the biggest names by market value moving with their sector.")


def test_group_claims_allow_only_group_wording_for_members_below_1():
    mm, g, b, pv, k = item("market_move"), item("mega_mover", "GOOGL"), item("breadth_day"), item("earnings_week_preview"), item("basket_week")
    for it in (mm, g, b):
        rejected(it, "Was $MSFT the biggest dollar loser on Friday?")                     # $GOOGL was #1
        rejected(it, "$MSFT had the biggest dollar drop on Friday.")
    rejected(g, "$GOOGL and $MSFT: $MSFT had the biggest dollar drop on Friday, $77.2B.")
    rejected(g, "$GOOGL fell 2.47% on Friday, but $MSFT was #1 in dollars lost.")
    rejected(g, "$GOOGL lost $105.5B on Friday; $NVDA was the number one loser by percent at 1.43%.")
    rejected(mm, "$MSFT and $NVDA were the biggest dollar drops on Friday.")             # a list must start at #1
    rejected(mm, "$NVDA was the second-biggest dollar drop on Friday.")                    # #3
    rejected(pv, "$TSLA is the biggest company reporting in the week of Oct 19.")          # $SPCX is
    rejected(pv, "$PG is the biggest company reporting in the week of Oct 19.")
    rejected(k, "$TSM was the worst of the 10 largest US-listed companies in the week to Oct 16: −8.98%.")  # $SPCX
    approved_or_not_a_phrase(mm, "$GOOGL, $MSFT and $NVDA were the biggest dollar drops on Friday.")
    approved_or_not_a_phrase(mm, "$MSFT was among the biggest dollar drops on Friday.")
    approved_or_not_a_phrase(mm, "$MSFT was one of the biggest dollar drops on Friday.")
    approved_or_not_a_phrase(mm, "$MSFT was the second-biggest dollar drop on Friday.")
    approved_or_not_a_phrase(mm, "Technology's biggest dollar drops: $MSFT −1.93%, $NVDA −1.43%.")
    approved_or_not_a_phrase(g, "$GOOGL had the biggest dollar drop on Friday.")
    approved_or_not_a_phrase(g, "$GOOGL: the biggest dollar move of the day, $105.5B.")
    approved_or_not_a_phrase(g, "Was $GOOGL the biggest dollar loser on Friday?")
    approved_or_not_a_phrase(pv, "$SPCX is the biggest company reporting in the week of Oct 19.")
    approved_or_not_a_phrase(pv, "$TSLA is among the biggest companies reporting in the week of Oct 19.")
    approved_or_not_a_phrase(k, "$SPCX was the worst of the 10 largest US-listed companies in the week to Oct 16: −10.17%.")


def test_a_comparison_stays_inside_the_item_window():
    g, pep = item("mega_mover", "GOOGL"), item("form4_buy", "PEP")
    rejected(g, "$GOOGL: the biggest dollar drop of the year. It lost $105.5B on Friday.")
    rejected(g, "$GOOGL fell 2.47% on Friday. That was the biggest dollar drop in market history: $105.5B.")
    rejected(g, "$GOOGL lost $105.5B on Friday, the most market value any company has ever lost in a day.")
    rejected(pep, "An unprecedented buy: director Robert C. Pohlad bought $10.84M of $PEP.")
    rejected(pep, "Director Robert C. Pohlad made the biggest-ever buy of $PEP: $10.84M.")


def test_universe_and_window_wording_found_by_reviewers():
    pv, bz, g = item("earnings_week_preview"), item("reddit_buzz"), item("mega_mover", "GOOGL")
    for t in ("60 members of the benchmark index report in the week of Oct 19: $META.",
              "60 S\u200b&P names report in the week of Oct 19: $META.",
              "60 index heavyweights report in the week of Oct 19, led by $SPCX."):
        assert any("universe wording" in r for r in rejected(pv, t)), t
    assert any("universe wording" in r for r in rejected(bz, "Reddit is talking about $NBIS more than anything in the "
                                                              "Standard & Poor's 500."))
    assert any("universe wording" in r for r in rejected(bz, "$NBIS is the Reddit name of the weekend, more than any SPY stock."))
    assert any("window" in r for r in rejected(pv, "60 of the 500 largest US-listed companies reported earnings over the "
                                                   "past week, including $META."))
    assert any("window" in r for r in rejected(g, "$GOOGL lost $105.5B of market value this week (−2.47%)."))


def test_old_facts_keep_the_reading_they_were_published_under():
    """An item from a facts.json built before the allowlist (no claim_phrases key: Growth's audit of older posts) keeps
    the rounds 1-4 reading of its `claims`; an item with the key (every item facts.py builds now) is read by the
    allowlist only, even with an empty list."""
    w = {k: v for k, v in week_rot().items() if k != "claim_phrases"}
    rejected(w, "Tech was the top sector in the week to Oct 16.")
    approved(w, "Tech was the worst sector in the week to Oct 16.")
    approved(w, "$DEO +9.66% led Consumer Defensive.")
    w2 = dict(week_rot(), claim_phrases=[])
    rejected(w2, "Tech was the worst sector in the week to Oct 16.")
    approved(w2, "Tech −7.3%, Consumer Defensive +5.5% in the week to Oct 16.")
    assert all("claim_phrases" in i for i in DOC["items"])


def moves_like_item(ticker="PEP", peers=(("KO", 81), ("MDLZ", 70))):
    it = {"type": "moves_like", "ticker": ticker, "name": "PepsiCo, Inc.", "window_sessions": 60, "session": "2026-10-16",
          "peers": [{"ticker": t, "sync": n} for t, n in peers], "claims": fx.moves_like_claims(ticker, [t for t, _ in peers])}
    it["claim_phrases"] = fx.moves_like_phrases(it)
    return it


def test_moves_like_ranks_its_peers():
    it = moves_like_item()
    approved(it, "Over 60 sessions, $PEP moved most like $KO (Sync 81).")
    rejected(it, "Over 60 sessions, $PEP moved most like $KO.")    # "(Sync 81)" words the metric: it stays
    approved(it, "Over the 60 sessions before Oct 16, 2026, $PEP's closest peers by Sync, in order: $KO (81), $MDLZ (70).")
    rejected(it, "Over 60 sessions, $PEP moved most like $MDLZ.")                       # #2
    rejected(it, "PepsiCo moved most like $KO, then $MDLZ.")                             # not a phrase


# Round 3 (HQ review 2026-10-18 r3 + HQ probes): every draft a reviewer found approved or rejected wrongly, and the
# honest drafts that must stay approved, on the same 2026-10-16 session (fixtures/claim_cases_2026-10-18.json):
# polarity of neutral words beside signs ("Tech was the top sector (-2.8%)"), "the two biggest" = exactly the top 2,
# metric (market cap / percent vs dollars), per-word scope ("led Tech lower, the biggest drop of the 500"), basket
# universe, window words (months, quarters, "today" on Monday about Friday), bare claims' date / direction, closest /
# "more closely than any" / "did better than $AAPL", and the pronoun carry ("$EQNR led it").
CASES = json.loads((TOOLS / "tests" / "fixtures" / "claim_cases_2026-10-18.json").read_text(encoding="utf-8"))


def case_item(key: str) -> dict:
    kind, _, arg = key.partition(":")
    if kind == "sector_rotation":
        return next(i for i in DOC["items"] if i["type"] == kind and i["window"] == arg)
    if kind == "moves_like":
        it = dict(moves_like_item(arg, (("VZ", 93), ("TMUS", 76), ("BCE", 65))), name="AT&T Inc.", when=None)
        it["claim_phrases"] = fx.moves_like_phrases(it)
        return it
    return item(kind, arg or None)


def test_round3_claim_cases():
    """Rounds 1-4 (481 cases): every draft a reviewer or HQ found wrongly approved stays rejected; the true drafts are
    approved or rejected by the allowlist alone (they are not claim phrases), never by another check."""
    assert len(CASES) > 300
    wrong = []
    for c in CASES:
        why = gr.wording_reasons(case_item(c["item"]), c["text"] + " Not investment advice.")
        if c["expect"] == "reject" and not why:
            wrong.append(f"reject [{c['item']}] {c['text']} -> APPROVED")
        # round 2 (HQ 2026-10-19): the vocabulary check ("wording:") is part of the allowlist
        if c["expect"] == "approve" and not all(r.startswith(("unsupported comparison:", "wording:")) for r in why):
            wrong.append(f"approve [{c['item']}] {c['text']} -> {why[:1]}")
    assert not wrong, "\n".join(wrong)


# Allowlist (HQ 2026-10-19): the round-4 review's cases (pairs, ordered lists, order words, synonyms, comparisons, ratios,
# scope, window, streaks, breadth direction, card words, direction verbs / nouns), allowlist probes, and honest drafts
# built from claim phrases (fixtures/allowlist_cases_2026-10-19.json).
ALLOW_CASES = json.loads((TOOLS / "tests" / "fixtures" / "allowlist_cases_2026-10-19.json").read_text(encoding="utf-8"))


def test_allowlist_cases():
    assert len(ALLOW_CASES) >= 100
    wrong = []
    for c in ALLOW_CASES:
        why = gr.wording_reasons(case_item(c["item"]), c["text"] + " Not investment advice.")
        if (c["expect"] == "approve") != (not why):
            wrong.append(f"{c['expect']} [{c['item']}] {c['text']} -> {why[:1]}")
    assert not wrong, "\n".join(wrong)


# Round 2 (HQ 2026-10-19): a closed vocabulary (post_vocab.VOCAB) for every sentence that is not a claim phrase, numbers and
# direction words tied to their subjects, no idiom blanking that hides a claim, no widened windows
# (fixtures/vocab_cases_2026-10-19.json: every draft of the round-2 review, plus honest plain drafts).
VOCAB_CASES = json.loads((TOOLS / "tests" / "fixtures" / "vocab_cases_2026-10-19.json").read_text(encoding="utf-8"))


def test_round2_vocabulary_cases():
    assert len(VOCAB_CASES) >= 90
    wrong = []
    for c in VOCAB_CASES:
        why = gr.wording_reasons(case_item(c["item"]), c["text"] + " Not investment advice.")
        if (c["expect"] == "approve") != (not why):
            wrong.append(f"{c['expect']} [{c['item']}] {c['text']} -> {why[:1]}")
    assert not wrong, "\n".join(wrong)


def test_vocabulary_holds_no_ranking_or_number_word():
    import post_vocab as pv
    words = pv.VOCAB | frozenset().union(*pv.BY_TYPE.values())
    # "then" is in: rank_words reads it as an order word only before a name, sector or number ("then $MSFT")
    assert not [w for w in words if gr.cl.RANK_LANGUAGE.search(w) and w != "then"]
    assert not words & pv.NUMBER_WORDS
    for w in ("alone", "just", "rest", "other", "another", "same", "matched", "equaled", "kept", "continued", "extended",
              "exception", "gold", "star", "table", "order", "higher", "lower", "green", "red", "increased", "tanked",
              "surged", "plunged", "october", "weeks", "morning", "weekend", "every", "all", "none", "included", "each"):
        assert w not in pv.VOCAB, w


def test_round2_picks_and_chart_relations():
    picks = fx.make_item("2026-10-18", "picks_ready", None, "picks:2026-10-16", "/picks/2026-10-16", tickers=["DRS", "DAR"],
                         facts_text="The RapidTradeView daily picks list for 2026-10-16 is published; the public picks are "
                                    "DRS, DAR.", allowed_numbers=["2026-10-16", "Oct 16"])
    picks["claim_phrases"] = []
    for t in ("Every pick rose on Friday: $DRS and $DAR.", "$DRS rose on Friday.", "Both picks rose on Friday."):
        assert gr.wording_reasons(picks, t + " Not investment advice."), t
    assert gr.wording_reasons(picks, "$DRS and $DAR are on the RapidTradeView picks list for Oct 16. "
                                     "Not investment advice.") == []
    pat = fx.make_item("2026-10-18", "chart_pattern", "IREN", "pattern:IREN", "/dashboard/IREN", name="IREN Limited",
                       facts_text="Automatic technical analysis flagged a double top on $IREN (IREN Limited) (scan "
                                  "2026-10-16). Confirmed Oct 14: closed $30.56, clearly below the $34.81 neckline.",
                       levels={"key_level": "$34.81", "breakout_close": "$30.56"}, allowed_numbers=["$30.56", "$34.81"])
    pat["claim_phrases"] = []
    assert gr.wording_reasons(pat, "$IREN closed $30.56 on Oct 14, below the $34.81 neckline.") == []
    assert gr.wording_reasons(pat, "$IREN closed below the neckline on Oct 14.") == []
    for t in ("$IREN closed $30.56 on Oct 14, above the $34.81 neckline.", "$IREN closed above the neckline on Oct 14."):
        assert any(r.startswith("chart:") for r in gr.wording_reasons(pat, t)), t


def test_every_claim_phrase_is_approved_as_a_post():
    """Each claim phrase of each item, posted alone (with the disclaimer), passes the whole validator: numbers, window,
    cashtags, wording."""
    for it in DOC["items"]:
        for ph in it.get("claim_phrases") or []:
            lead = it.get("ticker") or (it.get("tickers") or [None])[0]
            extra = f" ${lead}." if lead and f"${lead}" not in ph else ""   # the post names its (or one) ticker
            v, why = gr.review(threads(it, f"{ph}{extra} Not investment advice."), DOC, NOW)
            assert (v, why) == ("APPROVE", []), (it["type"], ph, why)


def test_rank_language_is_read_broadly():
    g = item("mega_mover", "GOOGL")
    for t in ("$GOOGL topped the list.", "$GOOGL was the standout.", "$GOOGL ran hotter than $MSFT.",
              "$GOOGL lost twice what $MSFT did.", "$GOOGL lost 1.4x more than $MSFT.", "$GOOGL, then $MSFT.",
              "$GOOGL came in ahead of $MSFT.", "$GOOGL edged out $MSFT.", "$GOOGL had the steepest fall.",
              "Every big name fell.", "None of the giants rose.", "$GOOGL fell again.", "$GOOGL fell for a third day in a row.",
              "$GOOGL is #3.", "$GOOGL ranks 3rd.", "$GOOGL was No. 1.", "$GOOGL was number one.", "$GOOGL lagged.",
              "$GOOGL underperformed.", "$GOOGL was the laggard.", "$GOOGL was the day's loser.", "$GOOGL was last.",
              "$GOOGL sat at the bottom.", "$GOOGL beat $MSFT.", "$GOOGL lost more than $MSFT.", "$GOOGL had it worse.",
              "$GOOGL hit a new low.", "$GOOGL had its worst day in 3 weeks.", "$GOOGL is down since September.",
              "$GOOGL had a record drop.", "$GOOGL had a historic drop.", "$GOOGL lost half as much as $MSFT.",
              "$GOOGL lost as much as $MSFT and $NVDA combined.", "$GOOGL was one of the 10 largest losers."):
        assert any(r.startswith("unsupported comparison:") for r in gr.wording_reasons(g, t)), t


def test_round3_blockers_and_window():
    d, w, mm, g = day_rot(), week_rot(), item("market_move"), item("mega_mover", "GOOGL")
    # the blocker: a sign or a loss word beside "top sector" does not make it the worst side
    for t in ("Tech was the top sector on Friday (−2.8%). $NVDA −1.43%.", "Tech, down 2.8%, was the top sector on Friday."):
        rejected(d, t)
    rejected(w, "Tech was the top sector in the week to Oct 16, down 7.3%. $NVDA −6.61%.")
    approved_or_not_a_phrase(d, "Tech led the drop on Friday.")
    approved_or_not_a_phrase(d, "Energy was the top sector on Friday, +2.6%. $EQNR +4.59% led it.")
    # Grok's first slot is Monday pre-market on Sunday's facts: Friday is not "today" or "yesterday"
    assert any("window" in r for r in rejected(mm, "Tech −2.77% was the worst sector today. $MSFT −$77.2B."))
    assert any("window" in r for r in rejected(g, "$GOOGL lost $105.5B yesterday."))
    assert any("unsupported comparison" in r
               for r in rejected(mm, "Tech −$886B was the worst sector on Friday, the worst in weeks."))


def test_round3_claims_carry_metric_and_universe():
    mm, k, b = item("market_move"), item("basket_week"), item("breadth_day")
    assert {c.get("metric") for c in mm["claims"]} >= {"usd_change", "pct_change"}
    assert all(c.get("universe") == "10" for c in k["claims"])
    peak = next(c for c in b["claims"] if c["bare"])
    assert peak["date"] == "2026-10-15" and peak["direction"] == "up"


# Round 4 (HQ review 2026-10-18 r4): the cases are in the fixture above (source "review 10-18 r4 ..." and "r4 ...");
# here the facts side: a claim with subjects is never bare, the basket count is its own subject-less claim, and every
# item carries the signs of its numbers and the moves of its subjects (claims.item_moves, stored by facts.self_check).
def test_round4_claims_and_moves():
    g, k, d = item("mega_mover", "GOOGL"), item("basket_week"), day_rot()
    assert all(not c["bare"] for it in DOC["items"] for c in it.get("claims") or [] if c["subjects"])
    assert any(c["words"] == ["only"] and not c["subjects"] and c["bare"] for c in k["claims"])
    mv = gr.cl.item_moves(d)
    assert mv["subjects"]["Energy"] == "up" and mv["subjects"]["Technology"] == "down"
    assert mv["numbers"]["2.6%"] == "+" and mv["numbers"]["2.8%"] == "-" and "2.5%" not in mv["numbers"]   # both signs
    assert gr.cl.item_moves(g)["subjects"]["GOOGL"] == "down"
    assert any("direction" in r for r in rejected(d, "Energy fell 2.6% on Friday. $XOM +2.46%."))
    assert any("rank" in r for r in rejected(g, "$MSFT was #3 by dollar drop on Friday. $GOOGL −2.47%."))
    assert any("window" in r for r in rejected(d, "Energy was the best sector on Thursday. $XOM +2.46%."))
