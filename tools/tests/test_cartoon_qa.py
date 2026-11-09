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
