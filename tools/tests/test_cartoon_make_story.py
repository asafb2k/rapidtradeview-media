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
        {"id": "e-75ca82.a", "text": "EPS $5.06 vs $3.89 (beat by $1.17)."},
        {"id": "e-75ca82.a", "text": f"{EPS} $5.06 vs $3.89 (beat by $1.17)."},
        {"id": "e-413af8.a", "text": "Constellation Energy Corporation ($CEG) published Q3 2026 results on Nov 9."},
    ],
}
HEAD = {"png_size": [1290, 690], "targets": [{"text": "RapidTradeView", "box": [144, 48, 370, 66]}],
        "visible_text": "RapidTradeView\n0\n/\n2\nregister/sign-in\nBack\nReport summary\nCEG\nConstellation Energy Corporation"}
FACT = {"png_size": [1290, 504], "targets": [{"text": "Beat by $1.17", "box": [180, 440, 209, 48]}],
        "visible_text": f"Adjusted EPS\nReported · {EPS}\n$5.06\nConsensus\n$3.89\n"
                        "Consensus captured Nov 8, 2026, before release\nBeat by $1.17"}


def screens(head=HEAD, fact=FACT):
    return {"head": {"png": "screens/head.png", "size": head["png_size"], "meta": head},
            "fact": {"png": "screens/fact.png", "size": fact["png_size"], "meta": fact}}


def test_spoken_figures_read_back_to_the_same_value():
    for tok in ("$5.06", "$1.17", "$14.99M", "$1.29M", "$9.55B", "$201M", "4.30%", "$1,287,400"):
        assert Q.spoken_value(M.speak_figure(tok)) == pytest.approx(Q.written_value(tok)), tok
    assert M.speak_figure("$5.06") == "five point zero six dollars"
    assert M.speak_figure("$5.06", unit=False) == "five point zero six"


def test_earnings_template_writes_the_one_idea_story():
    plan = M.plan_for(CEG)
    st = M.build_story(CEG, "facts.json", "2026-11-09", plan, screens())
    vos = [s.get("vo") for s in st["shots"]]
    assert vos == ["CEG beat by $1.17!", "Beat what? Checking RapidTradeView.", None, "EPS $5.06 vs $3.89", "(beat by $1.17).",
                   "Oh.", "Search RapidTradeView. Not investment advice."]
    assert len(st["shots"]) <= 7 and st["shots"][-1]["kind"] == "END"
    assert st["fact_phrase"] == "EPS $5.06 vs $3.89 (beat by $1.17)."                 # the item's own phrasing, verbatim
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
    # the two real cards: our header on top (not the zoom target), the key card below; payoff 2 lands on the key figure
    pay = [s for s in st["shots"] if s["kind"] == "PAYOFF"]
    assert [e["name"] for e in pay[0]["els"]] == ["head", "fact"] and pay[0]["els"][0]["main"] is False
    assert pay[1]["key_number"] == "Beat by $1.17" and any(e["t"] == "highlight" for e in pay[1]["els"])
    assert all(s.get("peek") for s in pay)                                              # a character never leaves
    assert st["screen_numbers_ack"] == {"head": {"0": "the guest view counter in our site header",
                                                 "2": "the guest view counter in our site header"},
                                        "fact": {"Nov 8, 2026": "the day the consensus was captured (small print under "
                                                                "the figure)"}}
    for name, meta in (("head", HEAD), ("fact", FACT)):
        ok, d = Q.screen_numbers_gate(meta["visible_text"], CEG, st["screen_numbers_ack"][name])
        assert ok, d


def test_unknown_numbers_on_a_capture_stop_the_template():
    fact = dict(FACT, visible_text=FACT["visible_text"] + "\nGAAP EPS: $5.19")
    with pytest.raises(M.TemplateError, match=r"\$5.19"):
        M.build_story(CEG, "facts.json", "2026-11-09", M.plan_for(CEG), screens(fact=fact))


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
    assert plan["hook"]["vo"] == "PAM insider bought $1.29M!" and plan["hook"]["claim"] == "f-1bee24.a"
    assert plan["fact"]["a"] == "Damian Miguel Mindlin bought $1.29M"
    assert plan["fact"]["a"] + " " + plan["fact"]["b"] == plan["fact"]["text"]
    assert plan["url"] == "https://www.rapidtradeview.trade/smart-money/figures/m-1"
