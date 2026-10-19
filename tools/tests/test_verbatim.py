"""Verbatim facts rule (HQ 2026-10-19, claims.py section 2d): every factual sentence of a post, self-reply or comment equals
one of the item's pre-verified sentences (claim_phrases + fact_phrases); every other sentence is a fact-free hook.
Run: python -m pytest tools/tests -q (offline)."""
import datetime as dt
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "tests"))
import claims as cl  # noqa: E402
import facts as fx  # noqa: E402
import grok_review as gr  # noqa: E402
import market_facts as mk  # noqa: E402
import test_grok_market as tg  # noqa: E402

VDOC, NOW = tg.VDOC, tg.NOW
FIX = TOOLS / "tests" / "fixtures"
PRIOR = [*json.loads((FIX / "claim_cases_2026-10-18.json").read_text(encoding="utf-8")),
         *json.loads((FIX / "allowlist_cases_2026-10-19.json").read_text(encoding="utf-8")),
         *json.loads((FIX / "vocab_cases_2026-10-19.json").read_text(encoding="utf-8"))]
HOOK = "Here are the numbers."   # a closed hook of every type (H04; round 7)
NIA = "Not investment advice."


def vitem(kind, ticker=None):
    return next(i for i in VDOC["items"] if i["type"] == kind and (ticker is None or i.get("ticker") == ticker))


def vcase_item(key: str) -> dict:
    kind, _, arg = key.partition(":")
    if kind == "sector_rotation":
        return next(i for i in VDOC["items"] if i["type"] == kind and i["window"] == arg)
    if kind == "moves_like":
        it = dict(tg.moves_like_item(arg, (("VZ", 93), ("TMUS", 76), ("BCE", 65))), name="AT&T Inc.", when=None)
        it["claim_phrases"] = fx.moves_like_phrases(it)
        it["fact_phrases"] = fx.fact_phrases(it)
        return it
    return vitem(kind, arg or None)


def post(it, text, platform="threads", reply=""):
    return gr.review(tg.draft(it, text, platform=platform, reply_text=reply), VDOC, NOW)


def verdict(it, text):
    return gr.wording_reasons(it, f"{text} {NIA}")


# --- every draft a reviewer or HQ found wrong in rounds 1-5 stays rejected; the honest free-form ones may now be rejected

def test_every_prior_reject_case_stays_rejected():
    rejects = [c for c in PRIOR if c["expect"] == "reject"]
    assert len(rejects) >= 400
    wrong = [f"[{c['item']}] {c['text']}" for c in rejects if not verdict(vcase_item(c["item"]), c["text"])]
    assert not wrong, "\n".join(wrong)


def test_prior_approve_cases_pass_or_fail_only_on_the_verbatim_rule():
    approves = [c for c in PRIOR if c["expect"] == "approve"]
    other = []
    for c in approves:
        why = verdict(vcase_item(c["item"]), c["text"])
        if why and not all(r.startswith(("not verbatim:", "not an approved hook")) for r in why):
            other.append(f"[{c['item']}] {c['text']} -> {why[:1]}")
    assert not other, "\n".join(other)


# --- every pre-verified sentence is a post; composed drafts (hook + phrases) pass the whole review

def test_every_phrase_is_approved_as_a_post_on_every_platform():
    bad = []
    for it in VDOC["items"]:
        for p in [*it.get("claim_phrases", []), *it.get("fact_phrases", [])]:
            text = f"{HOOK} {p} {NIA}"
            own = [it["ticker"]] if it.get("ticker") else (it.get("tickers") or [])
            if own and not any(f"${t}" in p for t in own):   # a post names the item's ticker (one of its tickers)
                text = f"{HOOK} {p} {next(f for f in it['fact_phrases'] if any('$' + t in f for t in own))} {NIA}"
            v, why = post(it, text)
            if v != "APPROVE" and not all(r.startswith("X ") for r in why):
                bad.append(f"{it['type']}: {p} -> {why[:2]}")
    assert not bad, "\n".join(bad)


def test_a_composed_x_post_with_link_reply_passes():
    mm = vitem("market_move")
    text = ("The 500 largest US-listed stocks lost about $1.0T on Friday. "
            "$GOOGL had the biggest dollar drop among the 500 largest US-listed companies on Friday (−$105.5B). "
            "What stood out to you? Not investment advice.")
    link = mm["page_url"].replace("{platform}", "x")
    assert gr.review(tg.draft(mm, text, platform="x", reply_text=f"Full map: {link}"), VDOC, NOW) == ("APPROVE", [])
    pep = vitem("form4_buy", "PEP")
    text = ("PepsiCo, Inc. director Robert C. Pohlad bought $10.84M of $PEP on the open market (Form 4, filed Oct 16). "
            "$PEP had a market value of $174.9B at the Oct 16 close. Not investment advice.")
    assert post(pep, text) == ("APPROVE", [])


# --- the rule: no splicing, no added / dropped / changed words, hooks carry no fact

GOOGL_P = "$GOOGL had the biggest dollar drop among the 500 largest US-listed companies on Friday (−$105.5B)."


def test_light_normalisation_only():
    mm = vitem("market_move")
    for ok in [GOOGL_P, GOOGL_P.replace("$GOOGL", "GOOGL"), GOOGL_P.replace("−", "-"), GOOGL_P.replace("−", "–"),
               GOOGL_P.upper(), "  " + GOOGL_P.replace(" ", "  "), GOOGL_P.replace(" (−$105.5B).", "."),
               GOOGL_P.replace("(", "").replace(")", "")]:
        assert verdict(mm, ok) == [], ok
    w = next(i for i in VDOC["items"] if i["type"] == "sector_rotation" and i["window"] == "week")
    assert verdict(w, "Tech was the worst sector last week (−7.3%).") == []   # the Monday form of a week item
    assert verdict(w, "Technology was the worst sector in the week to Oct 16 (−7.3%).") == []   # sector short name


def test_any_change_inside_a_fact_sentence_is_rejected():
    mm, pep = vitem("market_move"), vitem("form4_buy", "PEP")
    cases = [
        (mm, GOOGL_P.replace("−$105.5B", "−$105.6B")),                       # a number
        (mm, GOOGL_P.replace("−$105.5B", "$105.5B")),                        # a sign
        (mm, GOOGL_P.replace("Friday", "Thursday")),                         # a day
        (mm, GOOGL_P.replace("biggest", "second-biggest")),                  # an order word
        (mm, GOOGL_P.replace("$GOOGL", "$MSFT")),                            # the subject
        (mm, GOOGL_P.replace("had the", "had by far the")),                  # an added word
        (mm, GOOGL_P.replace("the 500 largest US-listed companies", "the 500 largest")),   # a dropped scope
        (mm, GOOGL_P[:-1] + ", and $MSFT too."),                             # splicing
        (mm, "And " + GOOGL_P),                                              # a lead-in word
        (mm, "Monday recap: " + GOOGL_P),                                    # a label
        (mm, GOOGL_P.replace(".", ";") + " A rough day."),                   # a mood add-on
        (pep, "PepsiCo, Inc. director Robert C. Pohlad bought $10.84M of $PEP on the open market, a vote of confidence."),
        (pep, "Robert C. Pohlad bought $10.84M of $PEP."),                   # "on the open market" dropped
        (pep, "Robert C. Pohlad bought $10.84M of $PEP on the open market on Oct 14."),   # a date beside the amount
        (vitem("reddit_buzz"), "Among the 10 most-mentioned stocks on Reddit with 20 mentions and a usual count of 5, "
                               "$NBIS had the highest mentions-vs-usual ratio (7.5× its usual count)."),   # 20+ / 5+
    ]
    for it, text in cases:
        why = verdict(it, text)
        assert why and any(r.startswith("not verbatim:") for r in why), text


def test_hooks_carry_no_fact():
    mm = vitem("market_move")
    assert verdict(mm, "• " + GOOGL_P + "\n• Here is how the day looked. | Full map in the reply.") == []
    for ok in ["Here is how the day looked.", "What stood out to you?", "Full map in the reply.", "Link in bio.",
               "What surprised you?", "Here is the picture \U0001f447", "What is your read on this? #stocks #investing"]:
        assert verdict(mm, ok) == [], ok
    # round 7: free combinations of hook words are no longer hooks (closed list of whole sentences)
    for free in ["Here's the full picture.", "Thoughts?", "Here is the full map.", "What stood out?", "Full map below.",
                 "Here is how the day looked to us."]:
        why = verdict(mm, free)
        assert why and any(r.startswith("not an approved hook") for r in why), free
    for bad in ["A down day.", "A down day for chips.", "Big names led.", "Tech had a day.", "Monday recap.",
                "Time to buy?", "Is it a buying opportunity?", "Should you sell?", "What about $NVDA?",
                "What about Alphabet?", "Stocks fell.", "The giants did all the damage.", "Green day.",
                "Not a broad selloff.", "Three sectors rose.", "Same story as last week.", "Will it bounce?",
                "Is this the bottom?", "Here is how the market looked today.", "Expect more of this.",
                "Here is how the day looked for you and for the market and the stocks in it.",
                "\U0001f4c9 Here is how the day looked.", "Here is how the day looked \U0001f680",
                "Here is how the day looked. #NVDA", "Here is how the day looked. #Tech",
                "Тор ріск.", "Here is how the dаy looked.",   # look-alike letters
                # review round 6: implicit calls to act / position claims
                "Which move surprised you?", "This is the move.", "You know what to do.", "Do what they did.",
                "Follow them.", "They know.", "We're in.", "We have it.", "I did.", "Take it."]:
        assert verdict(mm, bad), bad


def test_self_reply_and_comments_follow_the_rule():
    mm = vitem("market_move")
    link = mm["page_url"].replace("{platform}", "x")
    ok = tg.draft(mm, f"{HOOK} {GOOGL_P} {NIA}", platform="x", reply_text=f"Full map: {link}")
    assert gr.review(ok, VDOC, NOW) == ("APPROVE", [])
    bad = dict(ok, reply_text=f"Tech took the biggest hit: {link}")
    v, why = gr.review(bad, VDOC, NOW)
    assert v == "REJECT" and any(r.startswith("not verbatim:") for r in why)
    target = "https://x.com/sometrader/status/1844000000000000001"
    c = {"kind": "comment", "platform": "x", "target_url": target, "text": "Thanks for sharing, what stood out to you?"}
    assert gr.review_comment(c, None, None, NOW) == ("APPROVE", [])
    v, why = gr.review_comment(dict(c, text="Brutal day for chips, thanks for sharing."), None, None, NOW)
    assert v == "REJECT" and any(r.startswith("comment:") for r in why)
    v, why = gr.review_comment(dict(c, text="Buy the dip?"), None, None, NOW)
    assert v == "REJECT"
    with_item = dict(c, item_id=mm["item_id"], text=GOOGL_P)
    assert gr.review_comment(with_item, VDOC, None, NOW) == ("APPROVE", [])
    v, why = gr.review_comment(dict(with_item, text="$GOOGL dropped the most on Friday (−$105.5B)."), VDOC, None, NOW)
    assert v == "REJECT" and any(r.startswith("not verbatim:") for r in why)


def test_a_rejection_names_the_closest_phrase():
    why = verdict(vitem("market_move"), "$GOOGL had the biggest dollar drop of the 500 largest on Friday (−$105.5B).")
    assert any("closest phrase" in r and "biggest dollar drop among the 500 largest" in r for r in why)


def test_old_facts_without_fact_phrases_keep_their_reading():
    it = dict(vitem("market_move"))
    it.pop("fact_phrases")
    assert not cl.verbatim_mode(it)
    assert gr.wording_reasons(it, "The 500 largest US-listed stocks lost about $1.0T on Friday, −1.21%. " + NIA) == []


# --- generated phrases: every item type has fact phrases; the two false phrases are fixed; ties are not ordered

def test_every_item_type_gets_fact_phrases():
    kinds = {i["type"] for i in VDOC["items"] if i.get("fact_phrases")}
    assert {"market_move", "mega_mover", "sector_rotation", "breadth_day", "basket_week", "reddit_buzz",
            "earnings_week_preview", "earnings_reaction", "form4_buy"} <= kinds
    for it in [*_core_items()]:
        assert fx.fact_phrases(it), it["type"]


def _core_items():
    con = fx.make_item("2026-10-18", "congress_trade", "UNH", "ptr:1:UNH:buy", "/smart-money/figures/x", name="Jane Roe",
                       office="U.S. Representative (R-FL)", company="UnitedHealth Group", side="buy", rows=1,
                       amount_text="$15K–$50K", traded=["2026-09-24"], filed="2026-10-07", owner=["spouse"],
                       facts_text="x", allowed_numbers=["$15K–$50K", *fx.date_forms("2026-10-07"), *fx.date_forms("2026-09-24")])
    er = fx.make_item("2026-10-18", "earnings_result", "TFC", "report:1", "/dashboard/TFC", name="Truist Financial",
                      fiscal_label="Q3 2026", release_date="2026-10-16", facts_text="x",
                      results={"eps": {"basis": "Adjusted diluted EPS", "reported": "$1.16", "consensus": "$1.21",
                                       "label": "Missed by $0.05", "verdict": "miss"}},
                      allowed_numbers=["$1.16", "$1.21", "$0.05", "Q3 2026", "Q3", *fx.date_forms("2026-10-16")])
    up = fx.make_item("2026-10-18", "earnings_upcoming", "FITB", "upcoming:FITB", "/dashboard/FITB", name="Fifth Third Bancorp",
                      report_date="2026-10-19", hour_text="before the open", facts_text="x",
                      allowed_numbers=fx.date_forms("2026-10-19"))
    rd = fx.make_item("2026-10-18", "earnings_tomorrow_roundup", None, "roundup:x", "/earnings/tomorrow", tickers=["FITB", "CLF"],
                      names={"FITB": "Fifth Third Bancorp", "CLF": "Cleveland-Cliffs Inc."}, report_date="2026-10-19",
                      hour_text="before the open", facts_text="x", allowed_numbers=fx.date_forms("2026-10-19"))
    pk = fx.make_item("2026-10-18", "picks_ready", None, "picks:2026-10-16", "/picks/2026-10-16", tickers=["DRS", "DAR"],
                      trade_date="2026-10-16", facts_text="x", allowed_numbers=[*fx.date_forms("2026-10-16"), "2"])
    ch = fx.make_item("2026-10-18", "chart_pattern", "IREN", "pattern:x", "/dashboard/IREN", scan_date="2026-10-16",
                      pattern={"name": "Double top", "status": "confirmed", "start": "2026-08-13", "end": "2026-09-23",
                               "confirmed_on": "2026-10-14"},
                      levels={"key_level_name": "Neckline", "key_level": "$34.81", "breakout_close": "$30.56"},
                      facts_text="x", allowed_numbers=["$34.81", "$30.56", *fx.date_forms("2026-10-16"),
                                                       *fx.date_forms("2026-08-13"), *fx.date_forms("2026-09-23"),
                                                       *fx.date_forms("2026-10-14")])
    ps = fx.make_item("2026-10-18", "ptr_summary", None, "ptrsum:x", "/smart-money/figures/x", tickers=["AAPL", "MSFT"],
                      tickers_total=3, name="Jane Roe", office="U.S. Representative (R-FL)", filed="2026-10-07", rows=4,
                      buys=3, sales=1, source_urls=["https://disclosures-clerk.house.gov/a.pdf"], facts_text="x",
                      allowed_numbers=["4", "3", "1", *fx.date_forms("2026-10-07")])
    return [con, er, up, rd, pk, ch, ps]


def test_core_fact_phrases_read_right():
    con, er, up, rd, pk, ch, ps = _core_items()
    assert ("U.S. Representative Jane Roe (R-FL) disclosed a purchase of $UNH (owner: spouse), $15K–$50K (filed Oct 7)."
            in fx.fact_phrases(con))
    assert "Jane Roe's $UNH purchase was traded Sep 24 and disclosed on Oct 7." in fx.fact_phrases(con)
    assert "$TFC Q3 2026 Adjusted diluted EPS: $1.16 vs $1.21 consensus." in fx.fact_phrases(er)
    assert "Fifth Third Bancorp ($FITB) reports earnings on Monday, Oct 19, before the open (confirmed date)." in fx.fact_phrases(up)
    assert "$FITB and $CLF report earnings on Monday, Oct 19, before the open (confirmed dates)." in fx.fact_phrases(rd)
    assert "The public picks on the RapidTradeView list for Oct 16 are $DRS and $DAR." in fx.fact_phrases(pk)
    assert not any("#1" in p or "top pick" in p.lower() for p in fx.fact_phrases(pk))
    assert "$IREN closed at $30.56 on Oct 14, below the $34.81 neckline." in fx.fact_phrases(ch)
    assert "U.S. Representative Jane Roe (R-FL) disclosed 4 trades in 3 tickers on a report filed Oct 7." in fx.fact_phrases(ps)
    for it in (con, er, up, rd, pk, ch, ps):   # no pronoun subject: each sentence stands on its own
        assert not any(p.split()[0].lower() in ("it", "it's", "they", "this", "that") for p in fx.fact_phrases(it))


def test_reddit_phrases_fixed():
    bz = vitem("reddit_buzz")
    phrases = bz["claim_phrases"] + bz["fact_phrases"]
    assert not any("more than usual" in p for p in phrases)
    assert "Reddit mentions of $NBIS hit 7.5× its usual weekend count: 45 vs 6.0." in phrases
    top = [p for p in phrases if "highest mentions-vs-usual ratio" in p]
    assert top and all("usual count of 5+" in p and "20+ mentions" in p for p in top)
    lead = bz["lead"]
    assert mk.ratio_text(lead["mentions"] / lead["usual"]) == "7.5"


def test_ordinal_phrases_never_order_a_tie():
    out = mk.ordinal_phrases([("$A", "−$5.0B"), ("$B", "−$4.1B"), ("$C", "−$4.1B")], "had", "biggest dollar drop", "on Friday",
                             "The biggest dollar drops on Friday", (2, 3), after="−$3.0B")
    assert "$A had the biggest dollar drop on Friday (−$5.0B)." in out
    assert "$B and $C tied for the second-biggest dollar drop on Friday (−$4.1B each)." in out
    assert not any("second-biggest" in p and "tied" not in p for p in out) and not any("third" in p for p in out)
    assert "The biggest dollar drops on Friday, in order: $A (−$5.0B), $B (−$4.1B)." not in out   # #2 = #3
    assert not any("in order" in p and "$C" in p for p in out)
    out = mk.ordinal_phrases([("$A", "+1.0%"), ("$B", "+0.5%")], "was", "best", "of the 10", "The best of the 10", (2,),
                             after="+0.5%")
    assert out == ["$A was the best of the 10 (+1.0%)."]   # $B ties the unlisted #3: no order, no list
    ml = dict(tg.moves_like_item("T", (("VZ", 80), ("TMUS", 80), ("BCE", 70))), name="AT&T Inc.")
    p = fx.moves_like_phrases(ml)
    assert not any("most like" in x for x in p) and any("$VZ and $TMUS tied for the closest peer" in x for x in p)
    assert not any("in order" in x for x in p)


def test_rules_tell_grok_the_verbatim_rule():
    r = fx.verbatim_rules()
    assert "verbatim" in r["rule"].lower() and "hook_words" not in r and "hook_max_words" not in r
    assert [h["text"] for h in r["hooks"]] == [h["text"] for h in gr.cl.pv.HOOKS] and r["rotation_posts"] == 5


# --- review round 6 (HQ 2026-10-19): non-ASCII letters, older / stale items, hook calls, bare-domain paths

MON = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)
TARGET = "https://x.com/sometrader/status/1844000000000000001"
# every string the round-6 reviewer approved on the live 2026-10-19 facts, rewritten onto the fixture's GOOGL phrase
R6_LETTER_REJECTS = [
    GOOGL_P[:-1] + ", \U0001d412\U0001d404\U0001d40b\U0001d40b \U0001d40d\U0001d40e\U0001d416.",   # math-bold SELL NOW
    GOOGL_P[:-1] + " ВՍҮ.",                                                    # Cyrillic / Armenian BUY
    GOOGL_P[:-1] + ", 買い!",                                                          # Japanese "buy"
    "$GOOGL 强烈买入 " + GOOGL_P[7:],                                          # Chinese "strong buy"
    GOOGL_P[:-1] + ", \U0001d41b\U0001d422\U0001d420\U0001d420\U0001d41e\U0001d42c\U0001d42d \U0001d41d\U0001d42b\U0001d428"
    "\U0001d429 \U0001d41e\U0001d42f\U0001d41e\U0001d42b.",                                    # math-bold "biggest drop ever"
    GOOGL_P[:-1] + " ＳＥＬＬ.",                                               # fullwidth SELL
    GOOGL_P[:-1] + " S̶E̶L̶L̶.",                                           # combining strokes
    GOOGL_P[:-1] + " ​BUY​.",                                                         # zero-width wrapped
]


def test_round6_non_ascii_letters_are_read():
    mm = vitem("market_move")
    assert post(mm, f"{HOOK} {GOOGL_P} {NIA}") == ("APPROVE", [])
    for t in R6_LETTER_REJECTS:
        v, why = post(mm, f"{HOOK} {t} {NIA}")
        assert v == "REJECT", t
        c = {"kind": "comment", "platform": "x", "target_url": TARGET, "item_id": mm["item_id"], "text": t}
        assert gr.review_comment(c, VDOC, None, NOW)[0] == "REJECT", t
    # a phrase with its own accented letter still matches itself, and nothing else rides on it
    it = {"item_id": "2026-10-18-x", "type": "form4_buy", "fact_phrases": ["Grupo Energía Bogotá filed a Form 4."]}
    assert cl.verbatim_reasons(it, "Grupo Energía Bogotá filed a Form 4.") == []
    assert cl.verbatim_reasons(it, "Grupo Energía Bogotá filed a Form 4 买.")
    assert cl.verbatim_reasons(it, "Grupo Energia Bogota filed a Form 4.")


def test_round6_items_without_fact_phrases_are_rejected():
    old = dict(vitem("form4_buy", "PEP"))
    old.pop("fact_phrases")
    doc = {**VDOC, "items": [old if i["item_id"] == old["item_id"] else i for i in VDOC["items"]]}
    pep_p = next(p for p in vitem("form4_buy", "PEP")["fact_phrases"] if "$PEP" in p)
    for t in [pep_p, "PepsiCo director Robert C. Pohlad bought $10.84M of $PEP. Insiders know something.",
              "On a down day, $PEP director Robert C. Pohlad bought $10.84M."]:
        v, why = gr.review(tg.draft(old, f"{t} {NIA}", platform="threads"), doc, NOW)
        assert v == "REJECT" and any("before the verbatim facts rule" in r for r in why), t
    c = {"kind": "comment", "platform": "x", "target_url": TARGET, "item_id": old["item_id"],
         "text": "$PEP will double from here, insiders are loading. Accumulate."}
    v, why = gr.review_comment(c, doc, None, NOW)
    assert v == "REJECT" and any("before the verbatim facts rule" in r for r in why)


def test_round6_items_expire():
    assert gr.item_last_day({"item_id": "2026-10-18-a"}, {"date": "2026-10-18"}) == dt.date(2026, 10, 19)  # Sun -> Mon
    assert gr.item_last_day({"item_id": "2026-10-19-a"}, {"date": "2026-10-19"}) == dt.date(2026, 10, 20)  # Mon -> Tue
    assert gr.item_last_day({"item_id": "2026-10-23-a"}, {"date": "2026-10-23"}) == dt.date(2026, 10, 26)  # Fri -> Mon
    mm = vitem("market_move")   # the fixture facts are dated Sunday 2026-10-18
    d = tg.draft(mm, f"{HOOK} {GOOGL_P} {NIA}", platform="threads", reply_text="")
    assert gr.review(d, VDOC, MON) == ("APPROVE", [])
    for late in (dt.datetime(2026, 10, 20, 13, 0, tzinfo=dt.timezone.utc),
                 dt.datetime(2026, 10, 27, 15, 0, tzinfo=dt.timezone.utc)):
        v, why = gr.review(d, VDOC, late)
        assert v == "REJECT" and any("is stale" in r for r in why)
        c = {"kind": "comment", "platform": "x", "target_url": TARGET, "item_id": mm["item_id"], "text": GOOGL_P}
        v, why = gr.review_comment(c, VDOC, None, late)
        assert v == "REJECT" and any("is stale" in r for r in why)
    # Monday 23:30 New York (03:30Z Tue) is still Monday; Tuesday 00:30 New York (04:30Z) is past a Sunday file
    assert not gr.item_gate_reasons(mm, VDOC, dt.datetime(2026, 10, 20, 3, 30, tzinfo=dt.timezone.utc))
    assert gr.item_gate_reasons(mm, VDOC, dt.datetime(2026, 10, 20, 4, 30, tzinfo=dt.timezone.utc))
    picks = {"item_id": "2026-10-19-picks-ready", "fact_phrases": [], "valid_until": "2026-10-19T17:30:00+00:00"}
    at = dt.datetime(2026, 10, 19, 17, 0, tzinfo=dt.timezone.utc)
    assert gr.item_gate_reasons(picks, {"date": "2026-10-19"}, at) == []
    why = gr.item_gate_reasons(picks, {"date": "2026-10-19"}, at + dt.timedelta(minutes=31))
    assert any("valid_until" in r for r in why)


def test_round6_hooks_carry_no_call_to_act():
    pep = vitem("form4_buy", "PEP")
    pep_p = next(p for p in pep["fact_phrases"] if "$PEP" in p)
    for end in ["You know what to do.", "Do what they did.", "This is the move.", "Follow them.", "We're in.",
                "They know.", "I did."]:
        v, why = post(pep, f"{pep_p} {end} {NIA}")
        assert v == "REJECT" and any(r.startswith(("not verbatim:", "not an approved hook")) for r in why), end
    for t in ["Do it.", "You know what to do.", "This is the move.", "I did. Thank you.", "We have it.", "Follow them."]:
        v, why = gr.review_comment({"kind": "comment", "platform": "x", "target_url": TARGET, "text": t}, None, None, NOW)
        assert v == "REJECT", t
    ok = {"kind": "comment", "platform": "x", "target_url": TARGET, "text": "Thanks for sharing, what stood out to you?"}
    assert gr.review_comment(ok, None, None, NOW) == ("APPROVE", [])


def test_round6_bare_domain_paths_are_rejected():
    mm = vitem("market_move")
    link = mm["page_url"].replace("{platform}", "threads")
    for u in ["rapidtradeview.trade/GOOGL-will-double-load-up-now", "rapidtradeview.trade/GOOGL-is-a-screaming-accumulate",
              "www.rapidtradeview.trade/buy", "sec.gov/accumulate-now", "rapidtradeview.trade/dashboard/GOOGL",
              "rapidtradeview．trade/GOOGL-load-up"]:
        v, why = post(mm, f"{HOOK} {GOOGL_P} {u} {NIA}")
        assert v == "REJECT" and any("without https://" in r for r in why), u
    v, why = post(mm, f'{HOOK} {GOOGL_P} {link}"BUY_NOW {NIA}')
    assert v == "REJECT", why
    # our bare domain without a path reads as a hook; a company name like "Amazon.com" is the item's own wording
    assert post(mm, f"{HOOK} {GOOGL_P} Full map: rapidtradeview.trade {NIA}") == ("APPROVE", [])
    it = {"name": "Amazon.com, Inc.", "fact_phrases": ["Amazon.com director X bought $1M of $AMZN."]}
    assert gr.bare_link_reasons(it, "Amazon.com director X bought $1M of $AMZN.", []) == []
