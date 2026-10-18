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


def item(kind, ticker=None):
    return next(i for i in DOC["items"] if i["type"] == kind and (ticker is None or i.get("ticker") == ticker))


def draft(it, text, platform="x", **over):
    link = it["page_url"].replace("{platform}", platform)
    d = {"item_id": it["item_id"], "platform": platform, "text": text, "link": link,
         "reply_text": f"Every company on one map: {link}" if platform == "x" else "", "media_url": it["media"][0]["url"]}
    d.update(over)
    return d


P1 = ("The 500 largest US-listed stocks lost about $1.0T on Friday, −1.21%. Biggest dollar drops: $GOOGL −2.47%, "
      "$MSFT −1.93%, $NVDA −1.43%. Technology led the move, −$886B. Energy went the other way, +2.64%. "
      "Every company on one map below. Not investment advice.")


def test_plan_examples_are_approved():
    mm = item("market_move")
    assert gr.review(draft(mm, P1), DOC, NOW) == ("APPROVE", [])
    assert gr.review(draft(mm, P1, platform="threads"), DOC, NOW) == ("APPROVE", [])
    g = item("mega_mover", "GOOGL")
    t = ("$GOOGL lost $105.5B of market value on Friday, −2.47%: the biggest dollar drop among the 500 largest "
         "US-listed companies. $MSFT (−$77.2B) and $NVDA (−$74.9B) were next. Not investment advice.")
    assert gr.review(draft(g, t), DOC, NOW) == ("APPROVE", [])
    b = item("reddit_buzz")
    t = ("Reddit is talking about $NBIS 7.5× more than on a usual weekend: 45 mentions vs an average of 6. The stock "
         "fell 12.18% on Friday. $SNDK (3.3×) ran hot too, and 10 of the 10 most-talked stocks fell. Not investment advice.")
    assert gr.review(draft(b, t), DOC, NOW) == ("APPROVE", [])
    w = next(i for i in DOC["items"] if i["type"] == "sector_rotation" and i["window"] == "week")
    t = ("In the week to Oct 16 the 500 largest US-listed stocks fell 2.7%, but not evenly. Tech −7.3%, Industrials −3.9%. "
         "Consumer Defensive +5.5% and Energy +5.0% rose. $DEO +9.66% led Consumer Defensive and $COP +9.25% led Energy. "
         "Not investment advice.")
    assert gr.review(draft(w, t, platform="threads"), DOC, NOW) == ("APPROVE", [])
    k = item("basket_week")
    t = ("Owning the 10 largest US-listed companies equally cost 5.04% in the week to Oct 16. Only $AAPL rose (+2.03%). $AVGO −9.07%, "
         "$TSM −8.98%. Not investment advice.")
    assert gr.review(draft(k, t), DOC, NOW) == ("APPROVE", [])


def test_single_ticker_item_may_use_its_context():
    pep = item("form4_buy", "PEP")
    assert pep["context_tickers"] == ["KO"]
    t = ("PepsiCo director Robert C. Pohlad bought $10.84M of $PEP on the open market (traded Oct 14, Form 4 filed Oct 16). "
         "Across our feed, officers and directors bought $650M and sold $4.4B on the open market over 30 days. "
         "Not investment advice.")
    d = draft(pep, t, reply_text=f"Filing: {pep['source_url']}\n{pep['page_url'].replace('{platform}', 'x')}")
    assert gr.review(d, DOC, NOW) == ("APPROVE", [])
    d2 = dict(d, text=t.replace("Across our feed", "$KO too. Across our feed"))
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
    v, why = gr.review(draft(mm, P1.replace("The 500 largest US-listed stocks lost", "Stocks lost")), DOC, NOW)
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
    dup = P1.replace("Energy went the other way, +2.64%.", "Energy +2.64%, so +2.64% for energy.")
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
    for it in DOC["items"]:
        for text in [it["facts_text"], *it.get("angles", [])]:
            assert gr.wording_reasons(it, text) == [], (it["type"], text)
            assert gr.unexplained_numbers(text, gr.item_numbers(it), gr.item_cashtags(it)) == [], (it["type"], text)
            assert "S&P" not in text and not re.search(r"\bthis week\b", text), (it["type"], text)


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
          "biggest: $SPCX, $META, $TSLA. Not investment advice.")
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
    good = ["$DEO +9.66% led Consumer Defensive.", "Tech −7.3% was the worst sector.",
            "By market value, the biggest Consumer Defensive name moving with it was $WMT, +6.70%."]
    for t in good:
        assert gr.review(threads(w, base + t + " Not investment advice."), DOC, NOW) == ("APPROVE", []), t
    mm = item("market_move")
    v, why = gr.review(draft(mm, P1.replace("Biggest dollar drops", "The only drops")), DOC, NOW)
    assert v == "REJECT" and any("unsupported comparison" in r for r in why)
    v, why = gr.review(draft(mm, P1.replace("Biggest dollar drops", "Biggest drops by %")), DOC, NOW)
    assert v == "REJECT"                                                # GOOGL's move was a $ record, not a % one
    g = item("mega_mover", "GOOGL")
    t = "$GOOGL lost $105.5B on Friday, −2.47%, the first time it fell that much. Not investment advice."
    v, why = gr.review(draft(g, t), DOC, NOW)
    assert v == "REJECT" and any("first" in r for r in why)


def test_sector_attribution():
    mm = item("market_move")
    for t in ("The 500 largest US-listed stocks lost about $1.0T on Friday. Technology alone: −$886B. $GOOGL −2.47%, "
              "$MSFT −1.93%. Not investment advice.",
              "The 500 largest US-listed stocks lost about $1.0T on Friday. Tech was −$886B of it: $GOOGL −2.47%, $MSFT "
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
    ok = ("1,631 of 2,497 US stocks fell on Friday (65%). Biggest dollar drags: $GOOGL −2.47%, $MSFT −1.93%. "
          "Not investment advice.")
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
    kinds = {i["type"] for i in items}
    assert {"congress_flow", "insider_flow"} <= kinds
    for it in items:
        for text in [it["facts_text"], *it["angles"]]:
            assert gr.wording_reasons(it, text) == [], (it["type"], text)
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
