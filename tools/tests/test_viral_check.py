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
UTC = dt.timezone.utc
AFTER_CLOSE = dt.datetime(2026, 10, 22, 21, 30, tzinfo=UTC)  # 17:30 New York, 1.5 h after the close
NEXT_MORNING = dt.datetime(2026, 10, 23, 12, 41, tzinfo=UTC)
NIA = "Not investment advice."

# A compliant X post (grok_review.review APPROVEs it) that carries every must-have and 3 boosters (B2, B3, B4)
LRCX_TEXT = ("Here is the map.\n\n$LRCX lost $38.4B of market value today (−11.76%).\n\n$MRNA lost $17.2B of market "
             "value today (−17.57%).\n\n$NVDA moved −4.40% today.\n\nWhat stood out to you?\n\n" + NIA)
PG_TEXT = ("Here are the numbers.\n\n$PG Q1 2027 revenue: $23.3B vs $22.82B consensus (beat by $477M).\n\n$PG Q1 2027 EPS: "
           "$2.00 vs $1.89 consensus (beat by $0.11).\n\nWhat is your read on this?\n\nDetails in the reply.\n\n" + NIA)


def draft(it, text, platform="x", **over):
    link = it["page_url"].replace("{platform}", platform)
    d = {"item_id": it["item_id"], "platform": platform, "text": text, "link": link,
         "reply_text": f"Full map: {link}" if platform == "x" else "",
         "media_url": it["media"][0]["url"] if it.get("media") else "grok_generated"}
    if not it.get("media"):
        d["media_note"] = "abstract illustration of a market map"
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


def test_m8_earnings_release_day_and_three_hours_for_top50():
    pub = vc.as_time(PG["published_at"])
    assert ok(sc(PG_TEXT, PG, post_at=pub + dt.timedelta(hours=1)), "M8") is True
    r = sc(PG_TEXT, PG, post_at=pub + dt.timedelta(hours=5))
    assert ok(r, "M8") is False and "top-50" in r["must"]["M8"]["why"]       # $PG is worth more than #36 $LRCX
    fpub = vc.as_time(FIX["published_at"])
    r = sc("$FIX Q3 2026 results. " + NIA, FIX, post_at=fpub + dt.timedelta(hours=5))
    assert r["must"]["M8"]["ok"] is None and "unknown" in r["must"]["M8"]["why"]   # no cap rank: never guessed
    r = sc("$META results. " + NIA, META_ER, post_at=dt.datetime(2026, 10, 22, 12, 0, tzinfo=UTC))
    assert ok(r, "M8") is False and "2026-10-21 release" in r["must"]["M8"]["why"]


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


def test_b5_reddit_attention():
    assert ok(sc("$META drew 325 Reddit mentions.", BUZZ), "B5") is True
    assert ok(sc("$GOOGL hit 3.0× its usual count.", BUZZ), "B5") is True
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
    assert ok(r, "P1") is True and ok(r, "P2") is True and not r["passed"]
    assert ok(sc("$MRNA moved −17.57% today. " + NIA, LRCX), "P1") is False
    two = "$NVDA moved −4.40% today. $SPCX moved −9.14% today. " + NIA
    assert ok(sc(two, LRCX), "P1") is False and ok(sc(two, LRCX), "P2") is True
    assert ok(sc(LRCX_TEXT, LRCX), "P2") is False                                    # $MRNA is a smaller name
    er = sc("$PG moved +5.58% on Thursday, Oct 22. " + NIA, PG_REACTION)             # earnings exception
    assert ok(er, "P1") is False and ok(er, "P2") is False


def test_p3_mentions_in_own_post():
    assert ok(sc(LRCX_TEXT + " @Investingcom", LRCX), "P3") is True
    assert ok(sc(LRCX_TEXT, LRCX, reply_text="Map: https://x.y/z @someone"), "P3") is True
    assert ok(sc(LRCX_TEXT + " contact@rapidtradeview.trade", LRCX), "P3") is False


def test_p4_recap_without_company_cashtag():
    recap = ("Here is the map.\n\nThe 500 largest US-listed stocks lost about $1.4T of market value today (−1.67%).\n\n"
             "Consumer Defensive went the other way today (+3.12%).\n\nWhat stood out to you?\n\n" + NIA)
    r = sc(recap, MM)
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
    assert r["fails"] == [] and r["unknown"] == ["D1"] and not r["passed"] and r["summary"] == "M5/6 B1 P0 ?D1"
    assert all(v.get("na") for v in r["penalty_detail"].values())
    r = vc.score(good, BUZZ, "x", "comment", FACTS, None, t, None, target_followers=120_000,
                 target_posted_at=t - dt.timedelta(minutes=10))
    assert r["passed"] and r["must"]["D1"]["ok"] is True
    assert vc.score(good, BUZZ, "x", "comment", FACTS, None, t, None, target_followers=20_000,
                    target_posted_at=t)["must"]["D1"]["ok"] is False
    assert vc.score(good, BUZZ, "x", "comment", FACTS, None, t, None, target_followers="120000",
                    target_posted_at=(t - dt.timedelta(minutes=45)).isoformat())["must"]["D1"]["ok"] is False
    hook = vc.score("What stood out to you?", None, "x", "comment", FACTS, None, t, None)
    assert {"M1", "M2", "D2"} <= set(hook["fails"])
    assert vc.score(good + " @Investingcom", BUZZ, "x", "comment", FACTS, None, t, None)["must"]["D3"]["ok"] is False
    assert vc.score(good + " rapidtradeview.trade", BUZZ, "x", "comment", FACTS, None, t, None)["must"]["M5"]["ok"] is False
    assert vc.score("$LRCX moved −11.76% today.", BUZZ, "x", "comment", FACTS, None, t, None)["must"]["D2"]["ok"] is False


def test_reasons_and_notes():
    bad = sc("Here is the map. $NVDA moved −4.40% today. " + NIA, LRCX)
    reasons = vc.reject_reasons(bad)
    assert all(r.startswith("viral: ") for r in reasons)
    assert any(r.startswith("viral: M4") for r in reasons) and any(r.startswith("viral: P1") for r in reasons)
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
    assert any(r.startswith("viral: M4") for r in rej) and any(r.startswith("viral: P1") for r in rej)
    rej, _, res = gr.apply_viral(draft(LRCX, LRCX_TEXT, planned_at="2026-10-22T19:20:00Z"), FACTS, "post", hist,
                                 AFTER_CLOSE)
    assert any(r.startswith("viral: M6") for r in rej)                               # 20 min after our 19:00 post
    assert gr.apply_viral(dict(draft(LRCX, LRCX_TEXT), item_id="2026-10-22-nope-X-000000"), FACTS, "post", [],
                          AFTER_CLOSE) == ([], [], None)                             # review() rejects it already
    rej, notes, _ = gr.apply_viral({"kind": "comment", "platform": "x", "text": "What stood out to you?",
                                    "target_url": "https://x.com/someone/status/123"}, None, "comment", None, AFTER_CLOSE)
    assert any(r.startswith("viral: D2") for r in rej) and notes[0].startswith("viral=")


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
              draft(LRCX, "The numbers are below. $LRCX's move today: −11.76%. " + NIA),  # REJECT M4 + P1
              {"kind": "comment", "platform": "x", "text": "What stood out to you?",           # REJECT M1 M2 D2
               "target_url": "https://x.com/someone/status/1234567"}]
    sent = []
    stats = gr.run_inbox(FakeRest(_inbox_rows(drafts)), INSTINCT, "prod", vdir, False, lambda p, b: sent.append(b) or True,
                         comment_state=tmp_path / "c.json", now=AFTER_CLOSE - dt.timedelta(minutes=20), history=hist,
                         need_history=True, variety=False, viral=True)
    assert (stats["approved"], stats["rejected"]) == (1, 2), (stats, sent)
    head = sent[0].splitlines()
    assert head[0] == f"APPROVE 700 {LRCX['item_id']}" and head[1].startswith("viral=M8/8 B3 P0")
    assert sent[1].startswith(f"REJECT 701 {LRCX['item_id']}: ") and "viral: M4" in sent[1] and "viral: P1" in sent[1]
    assert sent[2].startswith("REJECT 702 comment: ") and "viral: M1" in sent[2] and "viral: D2" in sent[2]
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
