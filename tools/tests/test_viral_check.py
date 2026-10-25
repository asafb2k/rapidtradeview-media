"""VIRAL CHECK v1 (tools/viral_check.py; owner 2026-10-23, Growth VIRAL-CHECK.md) on real items of v/2026-10-22/facts.json,
plus its grok_review.py gate. Run: python -m pytest tools/tests -q (offline)."""
import copy
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "tests"))
import grok_review as gr  # noqa: E402
import viral_check as vc  # noqa: E402

FACTS = json.loads((TOOLS.parent / "v" / "2026-10-22" / "facts.json").read_text(encoding="utf-8-sig"))
ITEMS = {i["item_id"]: i for i in FACTS["items"]}
LRCX = ITEMS["2026-10-22-mega-mover-LRCX-4d119e"]          # mega_mover, #36 by cap, context mover $MRNA
MM = ITEMS["2026-10-22-market-move-LIST-ace539"]           # market_move (recap), session 2026-10-22
PG = ITEMS["2026-10-22-earnings-result-PG-9d164c"]         # BMO release, published 11:04Z
PG_REACTION = ITEMS["2026-10-22-earnings-reaction-PG-d9da3e"]
FIX = ITEMS["2026-10-22-earnings-result-FIX-9f8751"]       # $49B: no cap rank in the facts
META_ER = ITEMS["2026-10-22-earnings-result-META-16c72a"]  # released 2026-10-21 after the close; has a Reel
BUZZ = ITEMS["2026-10-22-reddit-buzz-META-387349"]         # META 8.2x, GOOG 5.3x, GOOGL 3.0x
EL = ITEMS["2026-10-22-congress-trade-EL-ad3999"]          # filed 2026-10-19
BAC = ITEMS["2026-10-22-congress-trade-BAC-9452d1"]        # a household name: every cashtag it offers is broad
TLH = ITEMS["2026-10-22-congress-trade-TLH-272474"]        # a Treasury-bond ETF, not a company
PKG = ITEMS["2026-10-22-earnings-result-PKG-4e7658"]       # release_date 2026-10-21, published 2026-10-22 10:02Z
BREADTH = ITEMS["2026-10-22-breadth-day-LIST-f583b0"]      # $NVDA $SPCX $AMZN: all broad
IONQ = ITEMS["2026-10-22-chart-pattern-IONQ-34deb3"]
UTC = dt.timezone.utc
AFTER_CLOSE = dt.datetime(2026, 10, 22, 21, 30, tzinfo=UTC)  # 17:30 New York, 1.5 h after the close
NEXT_MORNING = dt.datetime(2026, 10, 23, 12, 41, tzinfo=UTC)
NIA = "Not investment advice."

# A compliant X post (grok_review.review APPROVEs it) that carries every must-have and 3 boosters (B2, B3, B4)
LRCX_TEXT = ("Here is the map.\n\n$LRCX lost $38.4B of market value today (−11.76%).\n\n$MRNA lost $17.2B of market "
             "value today (−17.57%).\n\n$NVDA moved −4.40% today.\n\nWhat stood out to you?\n\n" + NIA)
PG_TEXT = ("Here are the numbers.\n\n$PG Q1 2027 revenue: $23.3B vs $22.82B consensus (beat by $477M).\n\n$PG Q1 2027 EPS: "
           "$2.00 vs $1.89 consensus (beat by $0.11).\n\nWhat is your read on this?\n\nDetails in the reply.\n\n" + NIA)


def own_still(it):
    """An item without its own card (basket_week, round 7) has no media: our rendered still on Pages (a Grok-made
    image is rejected since the 2026-10-26 gate fixes)."""
    return f"https://asafb2k.github.io/rapidtradeview-media/v/{it['item_id'][:10]}/stills/{it.get('type')}.png"


def draft(it, text, platform="x", **over):
    link = it["page_url"].replace("{platform}", platform)
    d = {"item_id": it["item_id"], "platform": platform, "text": text, "link": link,
         "reply_text": f"Full map: {link}" if platform == "x" else "",
         "media_url": it["media"][0]["url"] if it.get("media") else own_still(it)}
    d.update(over)
    return d


def sc(text, item, platform="x", kind="post", post_at=AFTER_CLOSE, prev=None, media="https://x/i.png", facts=FACTS,
       **kw):
    return vc.score(text, item, platform, kind, facts=facts, prev_own_post_at=prev, now=post_at, media=media,
                    post_at=post_at, **kw)


def ok(res, rule):
    return (res["must"].get(rule) or res["booster_detail"].get(rule) or res["penalty_detail"].get(rule))["ok"]


# ---------------------------------------------------------------------------
# A. Must-haves

def test_good_post_passes_every_must_and_is_strong():
    r = sc(LRCX_TEXT, LRCX, prev=AFTER_CLOSE - dt.timedelta(hours=2), media="grok_generated")
    assert r["fails"] == [] and r["unknown"] == [] and r["passed"] and r["strong"], r
    assert set(r["boosters"]) == {"B2", "B3", "B4"} and r["penalties"] == []
    assert r["summary"] == "M8/8 B3 P0"


def test_m1_cashtag_and_m2_number():
    r = sc("Here is the map. The 500 largest US-listed stocks lost about $1.4T of market value today. " + NIA, MM)
    assert ok(r, "M1") is False and ok(r, "M2") is True
    r = sc("$PG beat Q1 estimates. " + NIA, PG)                     # "Q1" is a period label, not a number
    assert ok(r, "M1") is True and ok(r, "M2") is False


def test_m3_names_a_company():
    sectors = "Industrials (+2.9%) and Tech (+1.7%) were the best sectors on Wednesday, in that order. " + NIA
    assert ok(sc(sectors, ITEMS["2026-10-22-sector-rotation-LIST-a6e4cd"]), "M3") is False
    assert ok(sc("$SPY moved 1.2% today. " + NIA, MM), "M3") is False          # an index ETF is not a company
    assert ok(sc("Procter & Gamble published Q1 2027 results on Oct 22. " + NIA, PG), "M3") is True   # by name
    assert ok(sc("Here is the map. $NVDA moved −4.40% today. " + NIA, MM), "M3") is True


def test_m4_words_on_x_and_threads_only():
    short = "Here is the map. $LRCX moved −11.76% today. " + NIA
    assert ok(sc(short, LRCX), "M4") is False
    assert ok(sc(LRCX_TEXT, LRCX), "M4") is True
    assert ok(sc(short, LRCX, platform="threads"), "M4") is False
    ig = sc(short, LRCX, platform="instagram")
    assert ig["must"]["M4"]["ok"] is True and ig["must"]["M4"].get("na")
    long_text = " ".join(["$LRCX lost $38.4B of market value today (−11.76%)."] * 8) + " " + NIA
    assert ok(sc(long_text, LRCX), "M4") is False


def test_m5_no_link_in_the_main_post():
    link = LRCX["page_url"].replace("{platform}", "x")
    assert ok(sc(f"{LRCX_TEXT}\n{link}", LRCX), "M5") is False
    assert ok(sc(f"{LRCX_TEXT} rapidtradeview.trade/dashboard/LRCX", LRCX), "M5") is False   # X auto-links it
    assert ok(sc(LRCX_TEXT, LRCX, reply_text=f"Full map: {link}"), "M5") is True              # self-reply is fine
    assert vc.links("Amazon.com reported. $AMZN fell.", MM) == []        # the company's own name is not a link
    assert vc.links("contact@rapidtradeview.trade", None) == []
    # Instagram: the official source link grok_review requires on a Congress caption is exempt; the page link is not
    src = EL["source_url"]
    cap = f"A purchase of $EL (owner: joint), $50K–$100K. Source: {src} Link in bio. {NIA}"
    assert ok(sc(cap, EL, platform="instagram"), "M5") is True
    page = EL["page_url"].replace("{platform}", "instagram")
    assert ok(sc(f"{cap} {page}", EL, platform="instagram"), "M5") is False


def test_m6_spacing_and_history():
    assert ok(sc(LRCX_TEXT, LRCX, prev=AFTER_CLOSE - dt.timedelta(minutes=30)), "M6") is False
    assert ok(sc(LRCX_TEXT, LRCX, prev=AFTER_CLOSE - dt.timedelta(minutes=90)), "M6") is True
    assert ok(sc(LRCX_TEXT, LRCX, prev=None), "M6") is None
    # no planned time: the review time is a lower bound (a short gap is unknown, a long one passes)
    r = vc.score(LRCX_TEXT, LRCX, "x", "post", FACTS, AFTER_CLOSE - dt.timedelta(minutes=30), AFTER_CLOSE, "x.png")
    assert ok(r, "M6") is None and "planned_at" in r["must"]["M6"]["why"]
    r = vc.score(LRCX_TEXT, LRCX, "x", "post", FACTS, AFTER_CLOSE - dt.timedelta(minutes=70), AFTER_CLOSE, "x.png")
    assert ok(r, "M6") is True
    hist = [{"platform": "x", "created_at": "2026-10-22T20:59:00Z", "body": "text\n---\nposted_at=2026-10-22T20:10:00Z"},
            {"platform": "threads", "created_at": "2026-10-22T21:20:00Z", "body": "t"},
            {"platform": "x", "pending": True, "created_at": "2026-10-22T21:25:00Z"},                    # time unknown
            {"platform": "x", "pending": True, "created_at": "2026-10-22T21:00:00Z", "planned_at": "2026-10-22T21:05:00Z"},
            {"platform": "x", "created_at": "2026-10-22T22:00:00Z", "body": "later"}]
    assert vc.prev_own_post_at(hist, "x", AFTER_CLOSE) == dt.datetime(2026, 10, 22, 21, 5, tzinfo=UTC)
    assert vc.prev_own_post_at(hist[:3], "x", AFTER_CLOSE) == dt.datetime(2026, 10, 22, 20, 10, tzinfo=UTC)
    assert vc.prev_own_post_at([], "x", AFTER_CLOSE) is None


def test_m7_media():
    assert ok(sc(LRCX_TEXT, LRCX, media=""), "M7") is False
    assert ok(sc(LRCX_TEXT, LRCX, media=None), "M7") is None
    assert ok(sc(LRCX_TEXT, LRCX, media="grok_generated"), "M7") is True
    assert ok(sc(LRCX_TEXT, LRCX, media=None, kind="reel"), "M7") is True


def test_m8_session_moves_same_day_only():
    assert ok(sc(LRCX_TEXT, LRCX), "M8") is True
    r = sc(LRCX_TEXT, LRCX, post_at=NEXT_MORNING)       # the owner's 10-22 case: Wednesday's map posted Thursday
    assert ok(r, "M8") is False and "same session day" in r["must"]["M8"]["why"]
    assert ok(sc("$PG moved +5.58% on Thursday, Oct 22. " + NIA, PG_REACTION, post_at=NEXT_MORNING), "M8") is False
    week = {"item_id": "2026-10-23-basket-week-LIST-0a0b0c", "type": "basket_week", "session_date": "2026-10-23"}
    assert ok(sc("x", week, post_at=dt.datetime(2026, 10, 24, 15, 0, tzinfo=UTC)), "M8") is True    # Saturday
    assert ok(sc("x", week, post_at=dt.datetime(2026, 10, 26, 15, 0, tzinfo=UTC)), "M8") is False   # Monday


def test_m8_reddit_capture_without_yesterdays_prices():
    t = dt.datetime(2026, 10, 22, 13, 31, tzinfo=UTC)
    assert ok(sc("$META drew 325 Reddit mentions vs its usual count of 40 (8.2×). " + NIA, BUZZ, post_at=t), "M8") is True
    morning = dict(BUZZ, price_session="2026-10-21")   # the 10-22 morning file: capture today, closes of Oct 21
    txt = ("$META drew 325 Reddit mentions vs its usual count of 40 (8.2×). 6 of the 10 most-mentioned stocks with a "
           "close for Oct 21 rose that day. " + NIA)
    r = sc(txt, morning, post_at=t)
    assert ok(r, "M8") is False and "Oct 21" in r["must"]["M8"]["why"]
    assert ok(sc(txt, BUZZ, post_at=dt.datetime(2026, 10, 23, 13, 0, tzinfo=UTC)), "M8") is False   # an older capture


def test_m8_earnings_release_day_and_the_top50_three_hour_note():
    pub = vc.as_time(PG["published_at"])
    r = sc(PG_TEXT, PG, post_at=pub + dt.timedelta(hours=1))
    assert ok(r, "M8") is True and r["extra"]["M8.3h"]["ok"] is True
    # the top-50 3 h window is a note (likely evidence, no top-50 source), never a REJECT; same day stays hard
    r = sc(PG_TEXT, PG, post_at=pub + dt.timedelta(hours=5))
    assert ok(r, "M8") is True and r["extra"]["M8.3h"]["ok"] is False and "top-50" in r["extra"]["M8.3h"]["why"]
    assert "M8.3h" in r["notes"] and "M8.3h" not in r["fails"] and "~M8.3h" in r["summary"]
    assert vc.reject_reasons(r) == [] and any(x.startswith("viral-note: M8.3h") for x in vc.note_lines(r))
    fpub = vc.as_time(FIX["published_at"])
    r = sc("$FIX Q3 2026 results. " + NIA, FIX, post_at=fpub + dt.timedelta(hours=5))
    assert ok(r, "M8") is True and r["extra"]["M8.3h"]["ok"] is None   # no cap rank: never guessed
    r = sc("$PG results. " + NIA, PG, post_at=NEXT_MORNING)
    assert ok(r, "M8") is False and "release day only" in r["must"]["M8"]["why"]


def test_m8_after_close_release_is_fresh_through_the_next_session_day():
    # META: released 2026-10-21 after the close (published 23:01Z), first in the 10-22 facts: fresh on 10-22
    r = sc("$META results. " + NIA, META_ER, post_at=dt.datetime(2026, 10, 22, 12, 0, tzinfo=UTC))
    assert ok(r, "M8") is True and "after the close" in r["must"]["M8"]["why"]
    assert ok(sc("$META results. " + NIA, META_ER, post_at=dt.datetime(2026, 10, 23, 13, 0, tzinfo=UTC)), "M8") is False
    # PKG: release_date 10-21, our feed published it 10-22 06:02 New York: M8 and B4 read the same release time
    r = sc("$PKG results. " + NIA, PKG, post_at=vc.as_time(PKG["published_at"]) + dt.timedelta(minutes=30))
    assert ok(r, "M8") is True and ok(r, "B4") is True
    # a Friday after-close release stays fresh over the weekend through Monday
    fri = dict(PG, release_date="2026-10-23", published_at="2026-10-23T21:30:00Z")
    assert ok(sc("$PG. " + NIA, fri, post_at=dt.datetime(2026, 10, 26, 14, 0, tzinfo=UTC)), "M8") is True
    assert ok(sc("$PG. " + NIA, fri, post_at=dt.datetime(2026, 10, 27, 14, 0, tzinfo=UTC)), "M8") is False


def test_m8_and_b4_without_a_planned_time_are_unknown_unless_decided():
    pub = vc.as_time(PG["published_at"])
    r = vc.score(PG_TEXT, PG, "x", "post", FACTS, None, pub + dt.timedelta(minutes=50), "x.png")   # no post_at
    assert ok(r, "M8") is None and "planned_at" in r["must"]["M8"]["why"]
    assert ok(r, "B4") is None and "B4" not in r["boosters"]
    r = vc.score(PG_TEXT, PG, "x", "post", FACTS, None, pub + dt.timedelta(hours=4), "x.png")
    assert ok(r, "B4") is False                                    # already past 3 h at review time: decided
    r = vc.score(LRCX_TEXT, LRCX, "x", "post", FACTS, None, NEXT_MORNING, "x.png")
    assert ok(r, "M8") is False                                    # an earlier session: decided at review time


def test_m8_chart_pattern_reads_its_facts_day():
    old_scan = dict(IONQ, scan_date="2026-10-21")                  # the morning builds: last evening's scan
    assert ok(sc("x", old_scan, post_at=dt.datetime(2026, 10, 22, 13, 0, tzinfo=UTC)), "M8") is True
    assert ok(sc("x", old_scan, post_at=NEXT_MORNING), "M8") is False


def test_m8_filings():
    t = dt.datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
    r = sc("x", EL, post_at=t)
    assert ok(r, "M8") is None and "filed 2026-10-19" in r["must"]["M8"]["why"]
    assert ok(sc("x", dict(EL, filed="2026-10-22"), post_at=t), "M8") is True
    assert ok(sc("x", EL, post_at=NEXT_MORNING), "M8") is False


# ---------------------------------------------------------------------------
# B. Boosters

def test_b1_video():
    reel = next(m["url"] for m in META_ER["media"] if m["kind"] == "reel")
    assert ok(sc("x", META_ER, media=reel), "B1") is True
    assert ok(sc("x", LRCX, media="https://asafb2k.github.io/rapidtradeview-media/v/2026-10-22/x/reel_9x16.mp4"), "B1")
    assert ok(sc("x", LRCX, media={"url": "https://pbs/x", "kind": "video"}), "B1") is True
    assert ok(sc("x", LRCX, media="https://x/i.png"), "B1") is False
    assert ok(sc("x", LRCX, kind="reel", media=None), "B1") is True


def test_b2_b3_cashtags_and_broad_lead_plus_smaller_name():
    assert ok(sc(LRCX_TEXT, LRCX), "B2") is True
    two = "$NVDA moved −4.40% today. $SPCX moved −9.14% today. " + NIA
    assert ok(sc(two, LRCX), "B2") is False
    assert ok(sc(two, LRCX), "B3") is False                      # both broad
    assert ok(sc("$LRCX moved −11.76% today. $MRNA moved −17.57% today.", LRCX), "B3") is True
    assert ok(sc("$MRNA moved −17.57% today. $LRCX moved −11.76% today.", LRCX), "B3") is False  # lead not broad


def test_broad_ranks_from_the_facts_then_g3():
    caps = vc.Caps(None, FACTS)
    assert caps.top("NVDA", 100) == (True, "$NVDA is #1 by cap (facts)")
    assert caps.top("SPCX", 100)[0] is True and "LRCX" in caps.top("SPCX", 100)[1]   # worth more than #36
    assert caps.top("APLD", 100)[0] is False                                         # in_500 false
    assert caps.top("MRNA", 100)[0] is False and "G3" in caps.top("MRNA", 100)[1]
    assert caps.top("TSM", 100)[0] is False                                          # a foreign ADR: never broad
    assert caps.top("SPY", 100)[0] is True
    assert caps.top("MRNA", 50, static=False)[0] is None                             # top-50: facts only
    assert len(vc.G3_TOP100) == 106


def test_b4_fast():
    assert ok(sc(LRCX_TEXT, LRCX), "B4") is True                                     # 1.5 h after the close
    assert ok(sc(LRCX_TEXT, LRCX, post_at=dt.datetime(2026, 10, 23, 0, 30, tzinfo=UTC)), "B4") is False   # 4.5 h
    pub = vc.as_time(PG["published_at"])
    assert ok(sc(PG_TEXT, PG, post_at=pub + dt.timedelta(minutes=50)), "B4") is True
    assert ok(sc(PG_TEXT, PG, post_at=pub + dt.timedelta(hours=4)), "B4") is False
    assert ok(sc("x", EL), "B4") is None                                             # a filing has a date only


def test_b5_reddit_attention_on_non_broad_names_only():
    r = sc("$META drew 325 Reddit mentions.", BUZZ)                # 8.2x, but $META is broad (G3: -36% vs retail-popular)
    assert ok(r, "B5") is False and "broad" in r["booster_detail"]["B5"]["why"]
    hot = copy.deepcopy(FACTS)
    b = next(i for i in hot["items"] if i["type"] == "reddit_buzz")
    b["others"] = [*b.get("others", []), {"ticker": "MRNA", "ratio": 3.1}]
    assert ok(sc("$MRNA drew 3.1× its usual Reddit count.", LRCX, facts=hot), "B5") is True
    assert ok(sc(LRCX_TEXT, LRCX), "B5") is False
    no_buzz = {**FACTS, "items": [i for i in FACTS["items"] if i["type"] != "reddit_buzz"]}
    assert ok(sc(LRCX_TEXT, LRCX, facts=no_buzz), "B5") is None


def test_b6_surprise_number_in_line_one():
    assert ok(sc(LRCX_TEXT, LRCX), "B6") is False                                    # line 1 is a hook
    assert ok(sc("$LRCX lost $38.4B of market value today (−11.76%).\n\n" + NIA, LRCX), "B6") is True
    assert ok(sc("$PG beat Q1 2027 revenue estimates by $477M.\n" + NIA, PG), "B6") is True
    assert ok(sc("$SPCX gained $151.8B of market value on Wednesday (+7.79%).", MM), "B6") is True
    assert ok(sc("The 500 largest US-listed stocks gained about $0.7T on Wednesday.", MM), "B6") is True
    assert ok(sc("499 of the 500 largest US-listed stocks had a price on Thursday, Oct 22.", MM), "B6") is False
    assert ok(sc("$NVDA moved −4.40% today.", MM), "B6") is False                # under 5%


# ---------------------------------------------------------------------------
# C. Penalties

def test_p1_p2_broad_only_and_single_megacap_mover():
    r = sc("Here is the map. $NVDA moved −4.40% today. " + NIA, LRCX)
    # P1 is a subset of P2: folded into P2's reason, counted once
    assert ok(r, "P2") is True and "P1, -25%" in r["penalty_detail"]["P2"]["why"] and ok(r, "P1") is False
    assert r["penalties"] == ["P2"] and "P2" in r["fails"] and not r["passed"]
    assert ok(sc("$MRNA moved −17.57% today. " + NIA, LRCX), "P2") is False
    two = "$NVDA moved −4.40% today. $SPCX moved −9.14% today. " + NIA
    assert ok(sc(two, LRCX), "P1") is False and ok(sc(two, LRCX), "P2") is True
    assert ok(sc(LRCX_TEXT, LRCX), "P2") is False                                    # $MRNA is a smaller name
    er = sc("$PG moved +5.58% on Thursday, Oct 22. " + NIA, PG_REACTION)             # earnings exception
    assert ok(er, "P1") is False and ok(er, "P2") is False


def test_p2_is_a_note_where_the_evidence_or_the_item_cannot_carry_a_reject():
    t = dt.datetime(2026, 10, 22, 21, 30, tzinfo=UTC)
    # Congress / insider / Reddit: G3 "can't tell" / "untestable"
    r = sc("Laurel M. Lee disclosed a sale of $BAC (owner: spouse), $50K–$100K. " + NIA, BAC, post_at=t)
    assert ok(r, "P2") is True and r["penalty_detail"]["P2"]["soft"] and "P2" in r["notes"] and "P2" not in r["fails"]
    r = sc("$META drew 325 Reddit mentions vs its usual count of 40 (8.2×). " + NIA, BUZZ, post_at=t)
    assert "P2" in r["notes"] and "P2" not in r["fails"]
    # unavoidable: every cashtag the breadth item offers is broad
    r = sc(BREADTH["phrasings"][0]["text"] + " " + NIA, BREADTH, post_at=t)
    assert "unavoidable" in r["penalty_detail"]["P2"]["soft"] and "P2" not in r["fails"]
    # Instagram: X-only evidence
    r = sc("Here is the map. $NVDA moved −4.40% today. " + NIA, LRCX, platform="instagram")
    assert "P2" in r["notes"] and "P2" not in r["fails"]
    # an avoidable broad-only X post on an item that offers a smaller name stays a REJECT
    assert "P2" in sc("Here is the map. $NVDA moved −4.40% today. " + NIA, LRCX)["fails"]


def test_broad_index_set_is_g3s():
    caps = vc.Caps(None, FACTS)
    assert all(caps.top(t, 100)[0] is True for t in ("VOO", "VTI", "SPX", "NDX", "RUT", "DJI", "ES", "NQ"))
    assert ok(sc("$AAPL fell 2.4% today. $SPX slipped 0.5% today. " + NIA, LRCX), "P2") is True
    assert ok(sc("$NVDA moved −4.40% today. $VOO moved −1.2% today.", LRCX), "B3") is False


def test_p3_mentions_in_own_post():
    assert ok(sc(LRCX_TEXT + " @Investingcom", LRCX), "P3") is True
    # the evidence is @mentions in original posts: the self-reply is not scored; a price "@45.20" is not a mention
    assert ok(sc(LRCX_TEXT, LRCX, reply_text="Map: https://x.y/z via @SECGov"), "P3") is False
    assert ok(sc(LRCX_TEXT + " An insider bought 10,000 shares @45.20.", LRCX), "P3") is False
    assert ok(sc(LRCX_TEXT + " contact@rapidtradeview.trade", LRCX), "P3") is False


def test_p4_recap_without_company_cashtag():
    recap = ("Here is the map.\n\nThe 500 largest US-listed stocks lost about $1.4T of market value today (−1.67%).\n\n"
             "Consumer Defensive went the other way today (+3.12%).\n\nWhat stood out to you?\n\n" + NIA)
    r = sc(recap, MM)
    # no cashtag at all: M1 / M3 fail already, P4 is not counted a third time (G3 3c: "mostly via missing cashtags")
    assert ok(r, "P4") is False and {"M1", "M3"} <= set(r["fails"]) and "P4" not in r["fails"]
    r = sc(recap + " $SPY moved −1.2% today.", MM)                                   # an index cashtag only
    assert ok(r, "P4") is True and "P4" in r["fails"]
    assert ok(sc(recap + " $NVDA moved −4.40% today.", MM), "P4") is False
    assert ok(sc(recap, LRCX), "P4") is False                                        # a mega_mover is not a recap
    assert ok(sc(recap, None), "P4") is None


# ---------------------------------------------------------------------------
# D. Comments

def test_comment_rules():
    t = dt.datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
    good = "$META drew 325 Reddit mentions vs its usual count of 40 (8.2×)."
    r = vc.score(good, BUZZ, "x", "comment", FACTS, None, t, None)
    assert list(r["must"]) == ["M1", "M2", "M5", "D1", "D2", "D3"]
    assert r["fails"] == [] and r["unknown"] == ["D1"] and not r["passed"] and r["summary"] == "M5/6 B0 P0 ?D1"   # B5: $META is broad
    assert all(v.get("na") for v in r["penalty_detail"].values())
    r = vc.score(good, BUZZ, "x", "comment", FACTS, None, t, None, target_followers=120_000,
                 target_posted_at=t - dt.timedelta(minutes=10))
    assert r["passed"] and r["must"]["D1"]["ok"] is True
    low = vc.score(good, BUZZ, "x", "comment", FACTS, None, t, None, target_followers=20_000, target_posted_at=t)
    assert low["must"]["D1"]["ok"] is False and "D1" in low["notes"] and low["fails"] == []   # a note: one anecdote
    assert vc.score(good, BUZZ, "x", "comment", FACTS, None, t, None, target_followers="120000",
                    target_posted_at=(t - dt.timedelta(minutes=45)).isoformat())["must"]["D1"]["ok"] is False
    hook = vc.score("What stood out to you?", None, "x", "comment", FACTS, None, t, None)
    # replies are untestable: only M2 (the E0 guardrail: a fact or number from our data) rejects; M1 / D2 are notes
    assert hook["fails"] == ["M2"] and {"M1", "D2"} <= set(hook["notes"])
    assert vc.score(good + " @Investingcom", BUZZ, "x", "comment", FACTS, None, t, None)["must"]["D3"]["ok"] is False
    assert vc.score(good + " rapidtradeview.trade", BUZZ, "x", "comment", FACTS, None, t, None)["must"]["M5"]["ok"] is False
    assert vc.score("$LRCX moved −11.76% today.", BUZZ, "x", "comment", FACTS, None, t, None)["must"]["D2"]["ok"] is False
    assert vc.score(good + " Bought @45.20.", BUZZ, "x", "comment", FACTS, None, t, None)["must"]["D3"]["ok"] is True


def test_reasons_and_notes():
    bad = sc("Here is the map. $NVDA moved −4.40% today. " + NIA, LRCX)
    reasons = vc.reject_reasons(bad)
    assert all(r.startswith("viral: ") for r in reasons)
    assert any(r.startswith("viral: M4") for r in reasons) and any(r.startswith("viral: P2") for r in reasons)
    assert not any(r.startswith("viral: P1") for r in reasons)
    unknown = sc(LRCX_TEXT, LRCX, prev=None)
    assert vc.reject_reasons(unknown) == []                                          # unknown is never a REJECT
    lines = vc.note_lines(unknown)
    assert lines[0].startswith("viral=M7/8 B3 P0 ?M6") and any(x.startswith("viral-unknown: M6") for x in lines)
    weak = sc(PG_TEXT, PG, post_at=vc.as_time(PG["published_at"]) + dt.timedelta(hours=2), prev=AFTER_CLOSE - dt.timedelta(days=1))
    assert weak["passed"] and weak["boosters"] == ["B4"] and any(x.startswith("viral-weak:") for x in vc.note_lines(weak))


# ---------------------------------------------------------------------------
# grok_review.py gate

def test_compliant_drafts_are_approved_by_review():
    """The fixtures below are real-shaped: grok_review's compliance rules approve them, so a REJECT is viral's alone."""
    assert gr.review(draft(LRCX, LRCX_TEXT), FACTS, AFTER_CLOSE) == ("APPROVE", [])
    pg_at = vc.as_time(PG["published_at"]) + dt.timedelta(hours=1)
    pg_link = PG["page_url"].replace("{platform}", "x")
    assert gr.review(draft(PG, PG_TEXT, reply_text=f"Details: {pg_link}\nSource: {PG['source_url']}"), FACTS, pg_at) == \
        ("APPROVE", [])
    short = draft(LRCX, "Here is the map. $LRCX moved −11.76% today. " + NIA)
    assert gr.review(short, FACTS, AFTER_CLOSE) == ("APPROVE", [])


def test_apply_viral_post_and_comment():
    hist = [{"platform": "x", "created_at": "2026-10-22T19:00:00Z", "body": "earlier post"}]
    rej, notes, res = gr.apply_viral(draft(LRCX, LRCX_TEXT, planned_at="2026-10-22T21:30:00Z"), FACTS, "post", hist,
                                     AFTER_CLOSE - dt.timedelta(hours=1))
    assert rej == [] and notes[0].startswith("viral=M8/8 B3 P0") and res["strong"]
    rej, notes, _ = gr.apply_viral(draft(LRCX, "Here is the map. $LRCX moved −11.76% today. " + NIA), FACTS, "post",
                                   hist, AFTER_CLOSE)
    assert any(r.startswith("viral: M4") for r in rej) and any(r.startswith("viral: P2") for r in rej)
    rej, _, res = gr.apply_viral(draft(LRCX, LRCX_TEXT, planned_at="2026-10-22T19:20:00Z"), FACTS, "post", hist,
                                 AFTER_CLOSE)
    assert any(r.startswith("viral: M6") for r in rej)                               # 20 min after our 19:00 post
    assert gr.apply_viral(dict(draft(LRCX, LRCX_TEXT), item_id="2026-10-22-nope-X-000000"), FACTS, "post", [],
                          AFTER_CLOSE) == ([], [], None)                             # review() rejects it already
    rej, notes, _ = gr.apply_viral({"kind": "comment", "platform": "x", "text": "What stood out to you?",
                                    "target_url": "https://x.com/someone/status/123"}, None, "comment", None, AFTER_CLOSE)
    assert rej == ["viral: M2 no number in the main text"] and notes[0].startswith("viral=")
    assert any(x.startswith("viral-note: D2") for x in notes)


def test_ledger_keeps_the_planned_time_for_m6():
    e = gr.ledger_entry(draft(LRCX, LRCX_TEXT, planned_at="2026-10-22T22:00:00Z"), 5, AFTER_CLOSE)
    assert e["planned_at"] == "2026-10-22T22:00:00+00:00"
    rec = gr.pending_records([e], lambda d: FACTS if d == "2026-10-22" else None)[0]
    assert rec["pending"] and vc.posted_time(rec) == dt.datetime(2026, 10, 22, 22, 0, tzinfo=UTC)
    assert "planned_at" not in gr.ledger_entry(draft(LRCX, LRCX_TEXT), 6, AFTER_CLOSE)


def _inbox_rows(drafts):
    return [{"id": 700 + n, "created_at": "2026-10-22T21:00:00Z", "kind": "draft", "platform": d["platform"],
             "item_id": d.get("item_id"), "body": "DRAFT " + json.dumps(d)} for n, d in enumerate(drafts)]


@pytest.fixture
def vdir(tmp_path):
    d = tmp_path / "v" / "2026-10-22"
    d.mkdir(parents=True)
    (d / "facts.json").write_text(json.dumps(FACTS), encoding="utf-8")
    return str(tmp_path / "v")


def test_inbox_viral_gate(tmp_path, vdir):
    from test_grok_review import INSTINCT, FakeRest  # noqa: PLC0415
    hist = [{"platform": "x", "created_at": "2026-10-22T18:00:00Z", "item_id": "2026-10-22-x", "body": "earlier"}]
    drafts = [draft(LRCX, LRCX_TEXT, planned_at="2026-10-22T21:30:00Z"),                       # APPROVE, strong
              draft(LRCX, "The numbers are below. $LRCX's move today: −11.76%. " + NIA),  # REJECT M4 + P2
              {"kind": "comment", "platform": "x", "text": "What stood out to you?",           # REJECT M2
               "target_url": "https://x.com/someone/status/1234567"}]
    sent = []
    stats = gr.run_inbox(FakeRest(_inbox_rows(drafts)), INSTINCT, "prod", vdir, False, lambda p, b: sent.append(b) or True,
                         comment_state=tmp_path / "c.json", now=AFTER_CLOSE - dt.timedelta(minutes=20), history=hist,
                         need_history=True, variety=False, viral=True)
    assert (stats["approved"], stats["rejected"]) == (1, 2), (stats, sent)
    head = sent[0].splitlines()
    assert head[0] == f"APPROVE 700 {LRCX['item_id']}" and head[1].startswith("viral=M8/8 B3 P0")
    assert sent[1].startswith(f"REJECT 701 {LRCX['item_id']}: ") and "viral: M4" in sent[1] and "viral: P2" in sent[1]
    assert sent[2].startswith("REJECT 702 comment: viral: M2") and "viral-note: D2" in sent[2]
    # the gate is off unless asked for (callers and tests that predate it): the same rows keep their old verdicts
    sent2 = []
    stats = gr.run_inbox(FakeRest(_inbox_rows(drafts)), INSTINCT, "prod", vdir, False, lambda p, b: sent2.append(b) or True,
                         comment_state=tmp_path / "c2.json", now=AFTER_CLOSE - dt.timedelta(minutes=20), history=hist,
                         need_history=True, variety=False)
    assert (stats["approved"], stats["rejected"]) == (3, 0), sent2
    assert not any("viral" in b for b in sent2)


def test_inbox_weak_post_is_approved_with_a_note(tmp_path, vdir):
    from test_grok_review import INSTINCT, FakeRest  # noqa: PLC0415
    pg_at = vc.as_time(PG["published_at"]) + dt.timedelta(hours=1)
    pg_link = PG["page_url"].replace("{platform}", "x")
    d = draft(PG, PG_TEXT, reply_text=f"Details: {pg_link}\nSource: {PG['source_url']}", planned_at=pg_at.isoformat())
    sent = []
    stats = gr.run_inbox(FakeRest(_inbox_rows([d])), INSTINCT, "prod", vdir, False, lambda p, b: sent.append(b) or True,
                         now=pg_at - dt.timedelta(minutes=5), history=[], need_history=True, variety=False, viral=True)
    assert stats["approved"] == 1, sent
    lines = sent[0].splitlines()
    assert lines[1].startswith("viral=M7/8 B1 P0 ?M6") and any(x.startswith("viral-weak: 1 booster") for x in lines)


def test_draft_cli_prints_the_score_and_gates_only_when_asked(tmp_path, capsys):
    f = tmp_path / "facts.json"
    f.write_text(json.dumps(FACTS), encoding="utf-8")
    p = tmp_path / "d.json"
    p.write_text(json.dumps(draft(LRCX, "Here is the map. $LRCX moved −11.76% today. " + NIA)), encoding="utf-8")
    rc = gr.main(["--draft", str(p), "--facts", str(f)])
    out = json.loads(capsys.readouterr().out)
    assert out["viral"]["summary"].startswith("M") and any(r.startswith("viral: M4") for r in out["viral_reasons"])
    assert not any(r.startswith("viral:") for r in out["reasons"])
    rc2 = gr.main(["--draft", str(p), "--facts", str(f), "--viral-gate"])
    out2 = json.loads(capsys.readouterr().out)
    assert rc2 == 1 and out2["verdict"] == "REJECT" and any(r.startswith("viral: M4") for r in out2["reasons"])
    assert rc in (0, 1)   # the item's freshness gate depends on today's date; the viral fields are printed either way


# ---------------------------------------------------------------------------
# Review round 2026-10-23: notes vs REJECTs, M6 both ways, robustness

def test_m6_both_ways_and_pending_approvals_never_reject():
    at = dt.datetime(2026, 10, 22, 22, 0, tzinfo=UTC)
    posted = [(at + dt.timedelta(minutes=25), False)]                       # a post already out 25 min after
    r = sc(LRCX_TEXT, LRCX, post_at=at, own_posts=posted)
    assert ok(r, "M6") is False and "before our next" in r["must"]["M6"]["why"]
    pending = [(at + dt.timedelta(minutes=25), True)]                      # an approval that may be abandoned
    r = sc(LRCX_TEXT, LRCX, post_at=at, own_posts=pending)
    assert ok(r, "M6") is None and "not posted yet" in r["must"]["M6"]["why"]
    assert ok(sc(LRCX_TEXT, LRCX, post_at=at, own_posts=[(at - dt.timedelta(minutes=90), False),
                                                         (at + dt.timedelta(minutes=70), True)]), "M6") is True
    # via the draft: the ledger's pending record planned 30 min after the draft's planned time
    hist = [{"platform": "x", "pending": True, "created_at": "2026-10-22T21:00:00Z", "planned_at": "2026-10-22T22:30:00Z"},
            {"platform": "x", "created_at": "2026-10-22T18:00:00Z", "body": "earlier"}]
    rej, notes, res = gr.apply_viral(draft(LRCX, LRCX_TEXT, planned_at="2026-10-22T22:00:00Z"), FACTS, "post", hist,
                                     dt.datetime(2026, 10, 22, 21, 30, tzinfo=UTC))
    assert not any(x.startswith("viral: M6") for x in rej) and res["must"]["M6"]["ok"] is None
    hist[0].pop("pending")
    hist[0]["body"] = "posted\nposted_at=2026-10-22T22:30:00Z"
    rej, _, _ = gr.apply_viral(draft(LRCX, LRCX_TEXT, planned_at="2026-10-22T22:00:00Z"), FACTS, "post", hist,
                               dt.datetime(2026, 10, 22, 21, 30, tzinfo=UTC))
    assert any(x.startswith("viral: M6 30 min before our next x post") for x in rej)


def test_instagram_x_only_rules_are_notes_and_threads_rejects_say_policy():
    cap = "Lam Research rose 6.1% today, its biggest gain this month. " + NIA          # no cashtag (IG: no search)
    r = sc(cap, LRCX, platform="instagram")
    assert ok(r, "M1") is False and "M1" in r["notes"] and "M1" not in r["fails"] and vc.reject_reasons(r) == []
    assert any(x.startswith("viral-note: M1") and "Instagram" in x for x in vc.note_lines(r))
    r = sc("Here is the map. $LRCX moved −11.76% today. " + NIA, LRCX, platform="threads",
           prev=AFTER_CLOSE - dt.timedelta(minutes=20))
    reasons = vc.reject_reasons(r)
    assert any(x.startswith("viral: M6") and "Threads mirrors" in x for x in reasons)
    assert any(x.startswith("viral: M4") and "Threads mirrors" not in x for x in reasons)


def test_m4_over_60_words_is_a_note():
    long_text = " ".join(["$LRCX lost $38.4B of market value today (−11.76%)."] * 8) + " " + NIA
    r = sc(long_text, LRCX, platform="threads")
    assert ok(r, "M4") is False and "M4" in r["notes"] and "M4" not in r["fails"]
    assert "M4" in sc("Here is the map. $LRCX moved −11.76% today. " + NIA, LRCX)["fails"]   # under 25: hard


def test_funds_are_not_companies():
    r = sc("John Boozman disclosed a purchase of $TLH (owner: joint), $1K–$15K. " + NIA, TLH)
    assert ok(r, "M3") is False                                        # a Treasury-bond ETF is not a company
    assert ok(r, "P2") is False                                        # G3: "other ETF only" posts are not broad
    assert vc.company_names(TLH) == []


def test_nfkc_folded_like_compliance():
    bold = "$\U0001d40b\U0001d411\U0001d402\U0001d417 lost $38.4B of market value today (−11.76%). " + NIA
    assert ok(sc(bold, LRCX), "M1") is True and ok(sc("\uff04LRCX moved −11.76% today. " + NIA, LRCX), "M1") is True


def test_viral_weak_names_what_the_item_can_reach():
    t = dt.datetime(2026, 10, 22, 21, 30, tzinfo=UTC)
    r = sc("Laurel M. Lee disclosed a sale of $BAC (owner: spouse), $50K–$100K. " + NIA, BAC, post_at=t)
    assert len(r["reachable"]) < 2
    assert any(x.startswith("viral-weak: 0 booster(s); this item can reach at most") and "not a reason to drop" in x
               for x in vc.note_lines(r))
    r = sc("Here is the map. $LRCX moved −11.76% today. " + NIA, LRCX)
    assert {"B2", "B3", "B4"} <= set(r["reachable"])


def test_untrusted_draft_fields_never_crash_the_inbox(tmp_path, vdir):
    from test_grok_review import INSTINCT, FakeRest  # noqa: PLC0415
    assert vc.as_time("9999-12-31T23:59:59-05:00") is None and vc.as_time("0001-01-01T03:00:00+05:00") is None
    assert vc._num(float("nan")) is None and vc._num(float("inf")) is None
    assert "planned_at" not in gr.ledger_entry(draft(LRCX, LRCX_TEXT, planned_at="0001-01-01T03:00:00+05:00"), 1,
                                                AFTER_CLOSE)
    bad = [dict(draft(LRCX, LRCX_TEXT), planned_at="9999-12-31T23:59:59-05:00"),
           {"kind": "comment", "platform": "x", "text": "$META drew 325 Reddit mentions vs its usual count of 40 (8.2×).",
            "item_id": BUZZ["item_id"], "target_followers": float("nan"),
            "target_posted_at": (AFTER_CLOSE - dt.timedelta(minutes=40)).isoformat()}]
    rows = [{**r, "body": r["body"].replace("NaN", "NaN")} for r in _inbox_rows(bad)]
    rows[1]["body"] = "DRAFT " + json.dumps(bad[1])                    # json.dumps writes NaN, as Grok's JSON could
    sent = []
    stats = gr.run_inbox(FakeRest(rows), INSTINCT, "prod", vdir, False, lambda p, b: sent.append(b) or True,
                         comment_state=tmp_path / "c.json", now=AFTER_CLOSE - dt.timedelta(minutes=20),
                         history=[], need_history=True, variety=False, viral=True)
    assert stats["answered"] == 2 and stats["acked"] == 2, (stats, sent)
    with pytest.MonkeyPatch.context() as mp:                            # a check that raises: a line, verdict kept
        mp.setattr(vc, "score_draft", lambda *a, **k: 1 / 0)
        rej, notes, res = gr.apply_viral(draft(LRCX, LRCX_TEXT), FACTS, "post", [], AFTER_CLOSE)
    assert rej == [] and res is None and notes[0].startswith("viral-error:")


def test_fresh_for_the_facts_top8():
    assert vc.fresh(LRCX, AFTER_CLOSE)["ok"] is True
    assert vc.fresh(LRCX, NEXT_MORNING)["ok"] is False
    assert vc.fresh(EL, dt.datetime(2026, 10, 22, 13, 0, tzinfo=UTC))["ok"] is None     # filed earlier: unknown
    assert vc.fresh(META_ER, dt.datetime(2026, 10, 22, 9, 0, tzinfo=UTC))["ok"] is True  # after-close release
