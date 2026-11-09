"""The cartoon Reel's TEMPLATE mode (tools/gv/scripts/cartoon/make_story.py): a facts item -> a one-idea story with the
brand early and late, at most 7 shots, the item's own phrase verbatim, claim tags, and only known page numbers
acknowledged. Offline: no capture, no voice, no render.  Run: python -m pytest tools/tests -q"""
import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
CART = TOOLS / "gv" / "scripts" / "cartoon"
sys.path.insert(0, str(CART))
_spec = importlib.util.spec_from_file_location("gv_cartoon_make_story", CART / "make_story.py")
M = importlib.util.module_from_spec(_spec)
sys.modules["gv_cartoon_make_story"] = M
_spec.loader.exec_module(M)
Q = M.Q

EPS = "Adjusted (non-GAAP) Operating Earnings"
CEG = {
    "item_id": "2026-11-09-earnings-result-CEG-d485d9", "type": "earnings_result", "ticker": "CEG", "tickers": ["CEG"],
    "name": "Constellation Energy Corporation", "report_id": "ceg-2026-q3",
    "page_url": "https://www.rapidtradeview.trade/dashboard/CEG?utm_source={platform}#earnings-history",
    "allowed_numbers": ["$9.55B", "$9.35B", "$201M", "$5.06", "$3.89", "$1.17", "Q3 2026", "Q3", "FY2026", "2026-11-09",
                        "Nov 9, 2026", "Nov 9"],
    "context_numbers": ["$84.9B", "+4.30%"],
    "results": {"eps": {"basis": EPS, "reported": "$5.06", "consensus": "$3.89", "label": "Beat by $1.17", "verdict": "beat"}},
    "phrasings": [
        {"id": "e-645f64.a", "text": "$CEG Q3 EPS $5.06, beat by $1.17."},
        {"id": "e-645f64.a", "text": f"$CEG Q3 {EPS} $5.06, beat by $1.17."},            # one id, two wordings (as in the facts)
        {"id": "e-6008a9.a", "text": "EPS $5.06 vs $3.89 consensus (beat by $1.17)."},
        {"id": "e-6008a9.a", "text": f"{EPS} $5.06 vs $3.89 consensus (beat by $1.17)."},
        {"id": "e-75ca82.a", "text": "EPS $5.06 vs $3.89 (beat by $1.17)."},
        {"id": "e-75ca82.a", "text": f"{EPS} $5.06 vs $3.89 (beat by $1.17)."},
        {"id": "e-413af8.a", "text": "Constellation Energy Corporation ($CEG) published Q3 2026 results on Nov 9."},
    ],
}
HEAD = {"png_size": [1290, 690], "targets": [{"text": "RapidTradeView", "box": [144, 48, 370, 66]}],
        "visible_text": "RapidTradeView\n0\n/\n2\nregister/sign-in\nBack\nReport summary\nCEG\nConstellation Energy Corporation"}
FACT = {"png_size": [1290, 360], "targets": [{"text": "$5.06", "box": [162, 162, 176, 96]},
                                             {"text": "$3.89", "box": [383, 276, 103, 57]}],
        "visible_text": f"Adjusted EPS\nReported · {EPS}\n$5.06\nConsensus\n$3.89"}
KEY = {"png_size": [2580, 192], "targets": [{"text": "Beat by $1.17", "box": [360, 48, 418, 96]}],
       "visible_text": "Beat by $1.17"}


def screens(head=HEAD, fact=FACT, key=KEY):
    out = {"head": {"png": "screens/head.png", "size": head["png_size"], "meta": head},
           "fact": {"png": "screens/fact.png", "size": fact["png_size"], "meta": fact}}
    if key:
        out["key"] = {"png": "screens/key.png", "size": key["png_size"], "meta": key}
    return out


def test_spoken_figures_read_back_to_the_same_value():
    for tok in ("$5.06", "$1.17", "$14.99M", "$1.29M", "$9.55B", "$201M", "4.30%", "$1,287,400"):
        assert Q.spoken_value(M.speak_figure(tok)) == pytest.approx(Q.written_value(tok)), tok
    assert M.speak_figure("$5.06") == "five point zero six dollars"
    assert M.speak_figure("$5.06", unit=False) == "five point zero six"


def test_earnings_template_writes_the_one_idea_story():
    plan = M.plan_for(CEG)
    st = M.build_story(CEG, "facts.json", "2026-11-09", plan, screens())
    vos = [s.get("vo") for s in st["shots"]]
    assert vos == ["CEG beat by $1.17!", "Beat what? Checking RapidTradeView.", None, "EPS $5.06 vs $3.89 consensus",
                   "(beat by $1.17).", "Oh.", "Search RapidTradeView. Not investment advice."]
    assert len(st["shots"]) <= 7 and st["shots"][-1]["kind"] == "END"
    # the item's own phrasing, verbatim, and the one that says "consensus": "Beat what?" is answered in the caption
    assert st["fact_phrase"] == "EPS $5.06 vs $3.89 consensus (beat by $1.17)."
    assert plan["url"] == "https://www.rapidtradeview.trade/earnings/reports/ceg-2026-q3"
    assert plan["url"] in Q.item_page_urls(CEG)
    ok, d = Q.one_idea_gate(st["shots"], 16.0)
    assert ok, d
    lines = [{"line": s.get("vo"), "claim": s.get("claim")} for s in st["shots"][:-1] if s.get("vo")]
    ok, d = Q.claim_lines_gate(lines, CEG, "2026-11-09")
    assert ok, d
    ok, d = Q.numbers_gate({"vo": " ".join(v for v in vos if v)}, Q.allowed_set(CEG))
    assert ok, d
    ok, d = Q.spoken_numbers_gate(st["say"])
    assert ok, d
    assert st["say"]["RapidTradeView."] == "Rapid Trade View." and st["say"]["CEG"] == "C E G"
    assert st["say"]["$5.06"] == "five point zero six" and st["say"]["$1.17!"] == "one point one seven dollars!"
    # payoff 1: our header on top, the fact card below; payoff 2: the header flies off, the page's own tag lands big
    pay = [s for s in st["shots"] if s["kind"] == "PAYOFF"]
    assert [e["name"] for e in pay[0]["els"]] == ["head", "fact"]
    cards = {e["name"]: e for e in pay[1]["els"] if e["t"] == "card"}
    assert set(cards) == {"head", "fact", "key"} and cards["head"].get("exit") and cards["key"]["main"] is True
    assert pay[1]["key_number"] == "Beat by $1.17" and any(e["t"] == "highlight" for e in pay[1]["els"])
    assert pay[1]["move"]["from_prev"] is True
    assert all(s.get("peek") for s in pay)                                              # a character never leaves
    # the reaction lands once: the peek stays wide-eyed in both payoff shots, the change of face is on "Oh."
    assert [s["peek"]["expr"] for s in pay] == ["shock", "shock"]
    cb = next(s for s in st["shots"] if s["kind"] == "CALLBACK")["els"][0]
    assert cb["expr"] == "shock" and cb["swap"]["expr"] == "happy"
    assert st["screen_numbers_ack"] == {"head": {"0": "the guest view counter in our site header",
                                                 "2": "the guest view counter in our site header"},
                                        "fact": {}, "key": {}}
    for name, meta in (("head", HEAD), ("fact", FACT), ("key", KEY)):
        ok, d = Q.screen_numbers_gate(meta["visible_text"], CEG, st["screen_numbers_ack"][name])
        assert ok, d


def test_unknown_numbers_on_a_capture_stop_the_template():
    fact = dict(FACT, visible_text=FACT["visible_text"] + "\nGAAP EPS: $5.19")
    with pytest.raises(M.TemplateError, match=r"\$5.19"):
        M.build_story(CEG, "facts.json", "2026-11-09", M.plan_for(CEG), screens(fact=fact))


def test_a_number_beside_the_guest_counter_is_not_the_counter():
    # v3 joined 2 lines on each side of a number to find the counter, so "12%" next to "0/2" was acknowledged as the counter
    plan = M.plan_for(CEG)
    meta = {"visible_text": "RapidTradeView\nUp 12% today\n0/2\nregister/sign-in\nBack\nCEG"}
    with pytest.raises(M.TemplateError, match="12%"):
        M.acks_for(plan, CEG, "head", meta)
    split = {"visible_text": "RapidTradeView\n0\n/\n2\nUp 12% today\nCEG"}
    with pytest.raises(M.TemplateError, match="12%"):
        M.acks_for(plan, CEG, "head", split)
    # a counter digit that ALSO appears elsewhere on the capture is not acknowledged (the gate checks by value)
    twice = {"visible_text": "RapidTradeView\n0/2\n2 releases on file\nCEG"}
    with pytest.raises(M.TemplateError, match="2 releases"):
        M.acks_for(plan, CEG, "head", twice)
    # the counter alone: "0/2" on its own line, or "0", "/", "2" as three nodes
    assert M.acks_for(plan, CEG, "head", {"visible_text": "RapidTradeView\n0/2\nCEG"}) == {
        "0/2": "the guest view counter in our site header"}
    assert set(M.acks_for(plan, CEG, "head", HEAD)) == {"0", "2"}
    # the counter is acknowledged on the header capture only
    with pytest.raises(M.TemplateError, match="0/2"):
        M.acks_for(plan, CEG, "fact", {"visible_text": "Adjusted EPS\n0/2\n$5.06"})


def test_the_consensus_small_print_is_never_acknowledged():
    # v3 acknowledged every number on a "Consensus captured ..." line ("14" analysts too); the date itself is not the
    # item's either, so v4 crops the line off the card and any number on it stops the template
    plan = M.plan_for(CEG)
    for line in ("Consensus captured Nov 8, 2026 from 14 analysts", "Consensus captured Nov 8, 2026, before release"):
        fact = dict(FACT, visible_text=FACT["visible_text"] + "\n" + line)
        with pytest.raises(M.TemplateError, match="Nov 8, 2026"):
            M.build_story(CEG, "facts.json", "2026-11-09", plan, screens(fact=fact))
    cap = next(c for c in plan["captures"] if c["name"] == "fact")
    assert cap["end_above"] == "Consensus captured" and "Beat by $1.17" not in cap["targets"]


def test_payoff_cards_keep_clear_of_the_pill_and_the_captions():
    plan = M.plan_for(CEG)
    L = M.payoff_layout(plan, screens())
    hw, hh = HEAD["png_size"]
    fw, fh = FACT["png_size"]
    w = L["w"]
    top = L["y_head"] - (hh * w / hw + 20) / 2
    bottom = L["y_fact"] + (fh * w / fw + 20) / 2
    mid = (top + bottom) / 2
    # shot 4: the push about the stack centre, at its largest scale, stays inside the stage
    assert mid - (mid - top) * M.PUSH_S >= M.STAGE_TOP - 1 and mid + (bottom - mid) * M.PUSH_S <= M.STAGE_BOTTOM + 1  # px rounding
    # shot 5: fact card + key card at the zoom (drift included) stay inside the stage, the key figure lands big
    kw_, kh_ = KEY["png_size"]
    crop = L["key_crop"]
    sc = M.KEY_W / (crop[2] - crop[0])
    fact_top = L["y_fact"] - (fh * w / fw + 20) / 2
    key_bottom = L["y_key"] + ((crop[3] - crop[1]) * sc + 20) / 2
    z = L["z5"] * (1 + 4 * M.Z5_DRIFT)
    assert (key_bottom - fact_top) * z <= M.STAGE_BOTTOM - M.STAGE_TOP + 1
    assert (w + 20) * z <= 1000 + 1                                                 # the fact card stays whole across
    assert KEY["targets"][0]["box"][3] * sc * L["z5"] >= 100                     # the tag's text is >= 100 px tall
    assert crop[0] <= 360 - 25 and crop[2] >= 360 + 418 + 25                        # the whole tag (brush edge too)
    assert crop[1] <= 48 - 25 and crop[3] >= 48 + 96 + 25


def test_the_payoff_always_resolves_the_hook():
    # the hook says the bare figure ("CEG beat by $1.17!"); the payoff must say what it is and repeat it
    plan = M.plan_for(CEG)
    pay = plan["fact"]["a"] + " " + plan["fact"]["b"]
    assert "EPS" in pay and plan["figure"] in pay and "consensus" in plan["fact"]["a"]
    no_consensus_phrase = dict(CEG, phrasings=[p for p in CEG["phrasings"] if "consensus (" not in p["text"]])
    with pytest.raises(M.TemplateError, match="consensus"):
        M.plan_for(no_consensus_phrase)


def test_no_template_no_video():
    with pytest.raises(M.TemplateError, match="no one-idea template"):
        M.plan_for({"type": "congress_trade"})
    no_consensus = dict(CEG, results={"eps": {"basis": "GAAP EPS", "reported": "$10.33"}})
    with pytest.raises(M.TemplateError, match="beat/miss"):
        M.plan_for(no_consensus)


def test_form4_template_uses_the_amount_and_the_page_figure():
    item = {"item_id": "x", "type": "form4_buy", "ticker": "PAM", "name": "Damian Miguel Mindlin", "amount_text": "$1.29M",
            "amount_top_usd": 1287400.0, "page_url": "https://www.rapidtradeview.trade/smart-money/figures/m-1?utm=1#trades",
            "phrasings": [{"id": "f-1bee24.a", "text": "Damian Miguel Mindlin bought $1.29M of $PAM on the open market."},
                          {"id": "f-431131.a", "text": "Pampa Energía S.A. vicepresident Damian Miguel Mindlin bought $1.29M "
                                                       "of $PAM on the open market (Form 4, filed Nov 9)."}]}
    plan = M.plan_for(item)
    assert plan["key"] == "$1,287,400" and plan["figure"] == "$1.29M"
    assert plan["hook"]["vo"] == "Insider bought $1.29M!" and plan["hook"]["claim"] == "f-1bee24.a"
    say = M.say_map([plan["hook"]["vo"], plan["fact"]["a"]], "PAM", (plan["hook"]["vo"], plan["fact"]["a"]))
    assert say["$1.29M!"] == "one point two nine million!" and say["$1.29M"] == "one point two nine million"
    ok, d = Q.spoken_numbers_gate(say)
    assert ok, d
    assert plan["fact"]["a"] == "Damian Miguel Mindlin bought $1.29M"
    assert plan["fact"]["a"] + " " + plan["fact"]["b"] == plan["fact"]["text"]
    assert plan["url"] == "https://www.rapidtradeview.trade/smart-money/figures/m-1"
