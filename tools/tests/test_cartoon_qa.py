"""The cartoon Reel's text QA gates (tools/gv/scripts/cartoon/cartoon_qa.py): numbers come only from the item, spelled-out
numbers match their figure, screenshots carry no unexplained numbers, no provider names, captions are exactly the voice
script, and the caption chunker keeps figures and dates whole. Offline: nothing is rendered.
Run: python -m pytest tools/tests -q"""
import importlib.util
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("gv_cartoon_qa", TOOLS / "gv" / "scripts" / "cartoon" / "cartoon_qa.py")
Q = importlib.util.module_from_spec(_spec)
sys.modules["gv_cartoon_qa"] = Q
_spec.loader.exec_module(Q)

ITEM = {
    "item_id": "2026-11-09-form4-buy-KMI-eaefd0", "type": "form4_buy", "ticker": "KMI",
    "facts_text": "Richard D. Kinder (Executive Chairman at Kinder Morgan, Inc.) reported an open-market purchase of KMI totaling "
                  "$14.99M on a Form 4 filed 2026-11-06, traded 2026-11-06.",
    "allowed_numbers": ["$14.99M", "2026-11-06", "Nov 6, 2026", "Nov 6"],
    "context_numbers": ["$67.3B", "−0.76%", "30"],
    "fact_phrases": ["Richard D. Kinder, executive chairman at Kinder Morgan, Inc., bought $14.99M of $KMI on the open market "
                     "(Form 4, filed Nov 6)."],
    "amount_top_usd": 14994200.0, "rows": 1, "filed": "2026-11-06", "traded": ["2026-11-06"],
}
PHRASE = ITEM["fact_phrases"][0]


# ------------------------------------------------------------------------------------------------- numbers
def test_find_numbers_reads_figures_dates_and_skips_document_names():
    assert Q.find_numbers(PHRASE) == ["$14.99M", "Nov 6"]
    assert Q.find_numbers("filed 2026-11-06. Nov 6, 2026 moved −0.76% on $14,994,200") == \
        ["2026-11-06", "Nov 6, 2026", "-0.76%", "$14,994,200"]
    assert Q.find_numbers("a Form 4 and a 10-K, no numbers") == []


def test_numbers_gate_passes_item_numbers_and_catches_invented_ones():
    ok, d = Q.numbers_gate({"caption": PHRASE, "vo": "You saw a cat."}, Q.allowed_set(ITEM))
    assert ok, d
    ok, d = Q.numbers_gate({"chip": "3 MINUTES LATER", "caption": "bought $15M"}, Q.allowed_set(ITEM))
    assert not ok and d["not_in_item"] == {"chip": ["3"], "caption": ["$15M"]}
    # the minus sign and a hyphen are the same number; context numbers count
    ok, _ = Q.numbers_gate({"caption": "down -0.76% at a $67.3B value"}, Q.allowed_set(ITEM))
    assert ok


def test_spoken_numbers_must_say_the_same_value():
    ok, d = Q.spoken_numbers_gate({"$14.99M": "fourteen point nine nine million dollars", "6).": "sixth.", "4,": "four,",
                                   "$KMI": "K M I", "Inc.,": "Incorporated,"})
    assert ok, d
    ok, d = Q.spoken_numbers_gate({"$14.99M": "fifteen million dollars"})
    assert not ok and "$14.99M" in d["mismatch"]
    ok, d = Q.spoken_numbers_gate({"socks.": "two socks."})          # a story word may not gain a number
    assert not ok
    ok, d = Q.spoken_numbers_gate({"$14.99M": "$14.99M"})            # digits must be spelled out for the voice
    assert not ok


def test_screen_numbers_need_the_item_or_an_acknowledged_reason():
    visible = "Richard D. Kinder: stock trades\n1 disclosed trades, latest filing 2026-11-06.\n$14,994,200\nSells\n0\nS&P 500"
    ok, d = Q.screen_numbers_gate(visible, ITEM, {})
    assert not ok and d["unexplained"] == ["0", "500"]
    assert d["numbers"]["$14,994,200"] == "item value" and d["numbers"]["1"] == "item value"
    ok, d = Q.screen_numbers_gate(visible, ITEM, {"0": "the SELLS tile", "500": "index name S&P 500"})
    assert ok, d
    ok, _ = Q.screen_numbers_gate(visible, ITEM, {"0": "", "500": "index name"})   # an empty reason is no reason
    assert not ok


# ------------------------------------------------------------------------------------------------- words
def test_provider_gate_catches_vendor_names_anywhere():
    ok, d = Q.provider_gate({"caption": PHRASE, "bubble": "ding."})
    assert ok
    ok, d = Q.provider_gate({"screen:top": "Prices from Yahoo Finance", "vo": "via Finnhub and Stock-Twits"})
    assert not ok and set(d["found"]) == {"screen:top", "vo"}


def test_banned_gate():
    ok, _ = Q.banned_gate({"vo": "Dale says, Push."}, ["moon", "buy now"])
    assert ok
    ok, d = Q.banned_gate({"chip": "TO THE MOON"}, ["moon", "buy now"])
    assert not ok and d["found"] == ["moon"]


def test_caption_gate_requires_the_exact_voice_script():
    script = "Monday. Leg day. " + PHRASE
    chunks = ["Monday.", "Leg day.", "Richard D. Kinder,", "executive chairman", "at Kinder", "Morgan, Inc.,", "bought $14.99M",
              "of $KMI", "on the open market", "(Form 4,", "filed Nov 6)."]
    ok, d = Q.caption_gate(chunks, script)
    assert ok, d
    ok, d = Q.caption_gate(chunks[:6] + ["bought $15M"] + chunks[7:], script)
    assert not ok and d["caption_words_not_in_script"] == ["$15M"]
    ok, d = Q.caption_gate(chunks[1:], script)                        # a dropped word fails too
    assert not ok


def test_fact_phrase_is_the_items_own_phrasing_and_in_the_script():
    ok, d = Q.fact_phrase_gate(PHRASE, ITEM, "Or. You search one name. " + PHRASE)
    assert ok, d
    ok, d = Q.fact_phrase_gate(PHRASE.replace("bought", "scooped up"), ITEM, PHRASE)
    assert not ok and not d["in_item"]


# ------------------------------------------------------------------------------------------------- chunks + alignment
def test_chunker_keeps_figures_dates_and_sentences_whole():
    words = ("Monday. Leg day. And Dale knows something you don't. " + PHRASE).split()
    chunks = [" ".join(words[i] for i in c) for c in Q.chunk_words(words)]
    assert " ".join(chunks).split() == words
    assert all(len(c) <= Q.MAX_CHARS or len(c.split()) == 1 for c in chunks)
    assert "Monday." in chunks and "Leg day." in chunks                      # never across a sentence end
    assert "filed Nov 6)." in chunks and any(c.endswith("$14.99M") for c in chunks)
    assert not any(c.split()[-1].lower() in Q.WEAK_END for c in chunks[:-1])


def test_align_maps_spoken_tokens_to_engine_words():
    words = "bought $14.99M of $KMI".split()
    say = {"$14.99M": "fourteen point nine nine million dollars", "$KMI": "K M I"}
    sp = Q.spoken_tokens(words, say)
    assert [i for i, _ in sp] == [0, 1, 1, 1, 1, 1, 1, 2, 3, 3, 3]
    tts = [{"word": t, "start": k * 0.2, "end": k * 0.2 + 0.15} for k, (_, t) in enumerate(sp)]
    spans = Q.align([t for _, t in sp], tts)
    assert spans[1] == (0.2, 0.35) and spans[-1] == (2.0, 2.15)
    # the engine merged two tokens: both still get a time inside the merged word
    merged = tts[:8] + [{"word": "KM", "start": 1.6, "end": 1.9}] + tts[10:]
    spans = Q.align([t for _, t in sp], merged)
    assert all(s is not None for s in spans) and 1.6 <= spans[8][0] <= 1.9


# ------------------------------------------------------------------------------------------------- v2 gates (review 2026-11-09)
ITEM2 = {**ITEM, "name": "Richard D. Kinder", "company": "Kinder Morgan, Inc.", "tickers": ["KMI"],
         "phrasings": [{"id": "form4buy-a1ddae.h1", "text": PHRASE}]}


def test_numbers_gate_catches_spelled_out_numbers_but_not_one():
    ok, d = Q.numbers_gate({"vo": "He bought fifteen million dollars of KMI on Thursday, Nov 6."}, {"Nov 6", "$14.99M"})
    assert not ok and d["number_words"] == {"vo": ["fifteen million"]}
    ok, d = Q.numbers_gate({"vo": "You open one app. You search one name.", "chip": "ONE SEARCH"}, Q.allowed_set(ITEM))
    assert ok, d
    assert Q.find_number_words("filed the sixth, twenty-first, wait a second") == ["sixth", "twenty-first"]
    # the TTS text spells the say map out: checked by spoken_numbers_gate, not here
    ok, _ = Q.numbers_gate({"spoken": "fourteen point nine nine million dollars"}, Q.allowed_set(ITEM), words=False)
    assert ok


def test_weekday_must_match_an_item_date_or_the_post_day():
    ok, d = Q.weekday_gate({"vo": "Kinder. KMI. Friday."}, ITEM)              # 2026-11-06 is a Friday
    assert ok, d
    ok, d = Q.weekday_gate({"vo": "bought it Thursday"}, ITEM)
    assert not ok and d["wrong_weekday"] == {"vo": ["Thursday"]}
    ok, _ = Q.weekday_gate({"vo": "Monday. Leg day."}, ITEM, "2026-11-09")    # posted on a Monday: story time
    assert ok
    ok, _ = Q.weekday_gate({"vo": "Monday. Leg day."}, ITEM, "2026-11-10")    # posted Tuesday: the hook lies
    assert not ok


def test_screen_ack_cannot_explain_away_an_item_value():
    ok, d = Q.screen_numbers_gate("Officers bought 30 in 30 days. Sells 0", ITEM, {"0": "the SELLS tile"})
    assert ok, d                                                              # "30" is a context number as written
    ok, d = Q.screen_numbers_gate("Sells 67.3B and 0", ITEM, {"0": "the SELLS tile", "67.3B": "a market value"})
    assert not ok and "67.3B" in d["ack_refused"]
    ok, d = Q.screen_numbers_gate("Sells 0", ITEM, {"0": 1})                  # the per-screen form is required
    assert not ok


def test_banned_gate_catches_inflections_but_not_other_words():
    ok, d = Q.banned_gate({"vo": "it moons, it's mooning"}, ["moon"])
    assert not ok and d["found"] == ["moon"]
    ok, _ = Q.banned_gate({"vo": "moonlight harmony"}, ["moon"])
    assert ok
    ok, d = Q.banned_gate({"chip": "LOADING UP"}, ["load up"])
    assert ok                                                                 # inflection on the last word only


def test_captions_drop_quote_marks_and_brackets():
    script = 'Dale says, "Push." ' + PHRASE
    chunks = ["Dale says,", "Push.", "Richard D. Kinder,", "executive chairman", "at Kinder Morgan,", "Inc.,", "bought $14.99M",
              "of $KMI", "on the open market", "Form 4,", "filed Nov 6."]
    ok, d = Q.caption_gate(chunks, script)
    assert ok, d
    assert Q.display_words('"A company (Form 4,') == ["A", "company", "Form", "4,"]


def test_fact_phrase_may_be_shown_instead_of_read():
    ok, d = Q.fact_phrase_gate(PHRASE, ITEM, "$14.99M. His own stock. Form 4, filed Friday.", [PHRASE])
    assert ok and d["on_screen"] and not d["in_script"]
    ok, _ = Q.fact_phrase_gate(PHRASE, ITEM, "$14.99M.", [])
    assert not ok


def test_story_lines_that_state_facts_need_a_matching_claim_tag():
    lines = [{"line": "A chairman just bought", "claim": "form4buy-a1ddae.h1"},
             {"line": "Kinder. KMI. Friday.", "claim": "form4buy-a1ddae.h1"},
             {"line": "Monday. Leg day."},                                      # the post day: story, no tag needed
             {"line": "You saw a cat."}]
    ok, d = Q.claim_lines_gate(lines, ITEM2, "2026-11-09")
    assert ok, d
    assert [c["line"] for c in d["needs_human_check"]] == ["A chairman just bought", "Kinder. KMI. Friday."]
    ok, d = Q.claim_lines_gate([{"line": "Form 4, filed Friday."}], ITEM2, "2026-11-09")
    assert not ok and d["bad"][0]["problem"].startswith("states a fact")
    ok, d = Q.claim_lines_gate([{"line": "He bought $15M on Thursday.", "claim": "form4buy-a1ddae.h1"}], ITEM2)
    assert not ok and "$15M" in d["bad"][0]["problem"] and "Thursday" in d["bad"][0]["problem"]
    ok, d = Q.claim_lines_gate([{"line": "Kinder bought.", "claim": "no-such-id"}], ITEM2)
    assert not ok


def test_occlusion_gate_flags_a_caption_on_a_face():
    face = {"kind": "pip face", "box": [300, 1100, 700, 1400]}
    ok, d = Q.occlusion_gate([{"t": 1.0, "caption": "Very heavy.", "box": [300, 1180, 780, 1280], "protect": [face]}])
    assert not ok and d["hits"][0]["covers"] == "pip face"
    ok, _ = Q.occlusion_gate([{"t": 1.0, "caption": "Very heavy.", "box": [300, 1180, 780, 1280],
                               "protect": [{"kind": "pip face", "box": [300, 700, 700, 1170]}]}])
    assert ok


# ------------------------------------------------------------------------------------------------- v3: brand and one idea
# owner verdict 2026-11-09: "the pilot short is too complicated and it isnt clear what brand behind it"
def test_fiscal_labels_are_one_number_token():
    assert Q.find_numbers("Constellation Energy Q3 2026 earnings, FY2026 guide, Q3 beat") == ["Q3 2026", "FY2026", "Q3"]


def test_brand_must_be_spoken_early_and_at_the_end():
    words = [("CEG", 0.05), ("Checking", 3.0), ("RapidTradeView.", 3.4), ("Search", 13.0), ("RapidTradeView.", 13.2)]
    ok, d = Q.brand_spoken_gate(words, 15.9)
    assert ok and d["spoken_at_s"] == [3.4, 13.2]
    ok, _ = Q.brand_spoken_gate([("RapidTradeView.", 6.2), ("RapidTradeView.", 13.2)], 15.9)      # too late at the start
    assert not ok
    ok, _ = Q.brand_spoken_gate([("RapidTradeView", 2.0)], 15.9)                                # never at the end
    assert not ok
    ok, _ = Q.brand_spoken_gate([("Rapid", 2.0), ("Search", 13.0)], 15.9)
    assert not ok


def test_brand_pill_must_match_in_every_sampled_frame():
    import numpy as np
    ref = np.tile(np.linspace(40, 220, 300), (40, 1))
    c, m = Q.region_match(ref + 3, ref)
    assert c > 0.99 and m == 3
    covered = np.full_like(ref, 30.0)                                             # something drawn over the pill
    c2, m2 = Q.region_match(covered, ref)
    ok, d = Q.brand_pill_gate([{"t": 0.0, "corr": c, "mad": m}, {"t": 1.0, "corr": c2, "mad": m2}])
    assert not ok and d["missing_at"] == [1.0]
    ok, _ = Q.brand_pill_gate([{"t": 0.0, "corr": c, "mad": m}])
    assert ok
    ok, _ = Q.brand_pill_gate([])
    assert not ok


def test_payoff_must_show_our_real_header_readably():
    good = {"t": 0, "screen": "head", "in_text": True, "in_crop": True, "inside": True, "h": 40.0}
    ok, d = Q.payoff_brand_gate([good] * 30, 30)
    assert ok and d["readable_s"] == 1.0
    ok, _ = Q.payoff_brand_gate([good] * 20, 30)                                   # under 1 s
    assert not ok
    ok, _ = Q.payoff_brand_gate([dict(good, h=12.0)] * 60, 30)                      # too small to read
    assert not ok
    ok, _ = Q.payoff_brand_gate([dict(good, in_crop=False)] * 60, 30)               # cropped away
    assert not ok


def test_one_idea_gate_limits_length_shots_and_side_gags():
    shots = [{"els": [{"t": "dale"}]}, {"els": [{"t": "pip"}]}, {"els": [{"t": "search_phone"}]},
             {"els": [{"t": "card"}, {"t": "card"}]}, {"els": [{"t": "card"}, {"t": "highlight"}]}, {"els": [{"t": "pip"}]},
             {"kind": "END"}]
    ok, d = Q.one_idea_gate(shots, 15.9)
    assert ok, d
    assert not Q.one_idea_gate(shots, 14.0)[0] and not Q.one_idea_gate(shots, 23.0)[0]
    assert not Q.one_idea_gate(shots + [{"els": [{"t": "pip"}]}], 18.0)[0]           # 8 shots
    ok, d = Q.one_idea_gate([{"els": [{"t": "feed"}, {"t": "cat"}]}] + shots[1:], 18.0)
    assert not ok and d["side_gag_elements"] == ["cat", "feed"]


def test_item_page_urls_allow_the_earnings_report_page():
    item = {"page_url": "https://www.rapidtradeview.trade/dashboard/CEG?utm_source={platform}#earnings-history",
            "report_id": "ceg-2026-q3"}
    assert Q.item_page_urls(item) == {"https://www.rapidtradeview.trade/dashboard/CEG",
                                      "https://www.rapidtradeview.trade/earnings/reports/ceg-2026-q3"}
    assert Q.item_page_urls({"page_url": "https://www.rapidtradeview.trade/smart-money/figures/x?a=1"}) == \
        {"https://www.rapidtradeview.trade/smart-money/figures/x"}


# ------------------------------------------------------------------------------------------------- v4 review fixes
def test_one_claim_id_with_two_wordings_reports_the_one_that_matches_the_line():
    # the facts give one id to "EPS ..." and to "Adjusted (non-GAAP) Operating Earnings ...": v3 kept the last wording only,
    # so a person checking the line "EPS $5.06 vs $3.89" was shown the Operating Earnings sentence
    item = {"ticker": "CEG", "tickers": ["CEG"], "name": "Constellation Energy Corporation",
            "phrasings": [{"id": "e-1.a", "text": "EPS $5.06 vs $3.89 consensus (beat by $1.17)."},
                          {"id": "e-1.a", "text": "Adjusted (non-GAAP) Operating Earnings $5.06 vs $3.89 consensus "
                                                  "(beat by $1.17)."}]}
    ok, d = Q.claim_lines_gate([{"line": "EPS $5.06 vs $3.89 consensus", "claim": "e-1.a"}], item, "2026-11-09")
    assert ok, d
    c = d["needs_human_check"][0]
    assert c["phrasing"] == "EPS $5.06 vs $3.89 consensus (beat by $1.17)." and len(c["phrasings"]) == 2
    ok, d = Q.claim_lines_gate([{"line": "EPS $5.07 vs $3.89", "claim": "e-1.a"}], item, "2026-11-09")
    assert not ok and "$5.07" in d["bad"][0]["problem"]


def test_brackets_never_reach_the_voice():
    toks = [t for _, t in Q.spoken_tokens(["(beat", "by", "$1.17)."], {"$1.17).": "one point one seven."})]
    assert toks == ["beat", "by", "one", "point", "one", "seven."]
    toks = [t for _, t in Q.spoken_tokens(["[sic]", "(Form", "4)"], {})]
    assert toks == ["sic", "Form", "4"]


def test_no_standing_card_under_the_brand_pill():
    still = {"t": 6.0, "screen": "head", "overlap_px": 900, "moving": False}
    ok, d = Q.pill_clear_gate([still, dict(still, t=6.1, overlap_px=0)])
    assert not ok and d["at_s"] == [6.0] and d["screens"] == ["head"]
    ok, _ = Q.pill_clear_gate([dict(still, moving=True), dict(still, overlap_px=0)])     # flying in or out may cross it
    assert ok
