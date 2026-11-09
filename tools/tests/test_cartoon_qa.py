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
