"""The card Reel renderer (tools/gv/scripts/v6cat/card_reel.py): the hook and caption are verbatim facts_text, the beats keep
the cadence, and the text gates catch banned words and provider names; the runner's default tree is this repo's. Offline: no
frames are encoded (the full render is verified by rendering, not here).
Run: python -m pytest tools/tests -q"""
import importlib.util
import sys
from pathlib import Path

from PIL import Image

TOOLS = Path(__file__).resolve().parent.parent
RENDERER = TOOLS / "gv" / "scripts" / "v6cat" / "card_reel.py"
_spec = importlib.util.spec_from_file_location("gv_card_reel", RENDERER)
rr = importlib.util.module_from_spec(_spec)
sys.modules["gv_card_reel"] = rr
_spec.loader.exec_module(rr)
sys.path.insert(0, str(TOOLS))
import card_reel as cr  # noqa: E402

GFS = ("GLOBALFOUNDRIES Inc. (GFS) published Q3 2026 results on 2026-11-04: Revenue beat. Revenue $1.9B vs $1.89B consensus "
       "(Beat by $9.71M). GAAP EPS −$0.49.")
CONG = ("U.S. Representative John J. McGuire III (R-VA) disclosed 3 purchases of MU (Micron Technology, Inc.), "
        "$1K–$15K; $1K–$15K; $1K–$15K, traded 2026-09-24, 2026-09-25, 2026-10-01; filed 2026-11-01 (owner: spouse).")
F4 = ("James Healy (Director at Rapport Therapeutics, Inc.) reported an open-market purchase of RAPP totaling $20M on a Form 4 "
      "filed 2026-10-30, traded 2026-10-28.")
PAT = ("Automatic technical analysis flagged a double top on $NU (Nu Holdings Ltd.) (scan 2026-10-30): pattern 2026-08-14 to "
       "2026-10-12. Confirmed Oct 28: closed $11.97, clearly below the $12.13 neckline.")


def built(kind, ticker, facts):
    plan = rr.Plan({"item_id": "x", "type": kind, "ticker": ticker, "facts_text": facts}, rr.norm_ws(facts))
    rr.Scenes(plan, Image.new("RGB", rr.CARD_SIZE, (12, 12, 12)))
    return plan


def test_the_runner_defaults_to_the_repo_renderer():
    assert cr.GV == TOOLS / "gv" and (cr.GV / "scripts" / "v6cat" / "card_reel.py").is_file()


def test_hook_pieces_are_verbatim_facts_text():
    assert rr.hook_parts({"type": "earnings_result", "ticker": "GFS"}, GFS) == {"ticker": "GFS", "figure": "$1.9B", "label": "Revenue beat."}
    assert rr.hook_parts({"type": "form4_buy", "ticker": "RAPP"}, F4) == {"ticker": "RAPP", "figure": "$20M", "label": "open-market purchase"}
    assert rr.hook_parts({"type": "chart_pattern", "ticker": "NU"}, PAT) == {"ticker": "$NU", "figure": "$11.97", "label": "double top"}
    # several congress trades: no per-trade range as the headline (it would read as a total)
    assert rr.hook_parts({"type": "congress_trade", "ticker": "MU"}, CONG) == {"ticker": "MU", "figure": None, "label": "3 purchases"}


def test_caption_beats_cover_every_word_in_order_on_a_beat():
    for kind, tk, facts in (("earnings_result", "GFS", GFS), ("congress_trade", "MU", CONG), ("form4_buy", "RAPP", F4),
                            ("chart_pattern", "NU", PAT)):
        plan = built(kind, tk, facts)
        assert " ".join(plan.caption_chunks).split() == facts.split()
        s, d = rr.text_gates(plan, ["moon", "insider trading"])
        assert all(s.values()), (kind, s, d)
        assert rr.DURATION_RANGE[0] <= plan.total <= rr.DURATION_RANGE[1] and d["beat_cadence"]["max_gap_s"] <= rr.MAX_BEAT_GAP_S
        assert all(len(c) <= rr.GROUP_MAX_WORDS for c in plan.chunks)
        assert not d["safe_zones"]["under_right_rail"]


def test_groups_end_on_clauses_not_mid_sentence():
    plan = built("earnings_result", "GFS", GFS)
    assert plan.caption_chunks == ["GLOBALFOUNDRIES Inc. (GFS)", "published Q3 2026 results on 2026-11-04:", "Revenue beat.",
                                   "Revenue $1.9B vs $1.89B consensus", "(Beat by $9.71M).", "GAAP EPS −$0.49."]
    assert plan.figure_beats == [3, 4, 5]


def test_music_provenance_is_the_vsco_record_the_kit_accepts():
    import json
    import manifest as mf
    vs = sys.modules["vsco_score"]
    fixture = json.loads((TOOLS / "tests" / "fixtures" / "vsco-music.json").read_text(encoding="utf-8"))
    assert vs.MUSIC == fixture
    errors = []
    mf._music(errors, "music", dict(vs.MUSIC))
    assert errors == []
    assert all(len(v[0]) == 64 for v in vs.SAMPLES.values())


def test_text_gates_catch_banned_words_and_provider_names():
    s, d = rr.text_gates(built("earnings_result", "GFS", GFS), ["revenue beat"])
    assert s["banned_words"] is False and d["banned_words"]["found"] == ["revenue beat"]
    s, d = rr.text_gates(built("earnings_result", "GFS", GFS + " Source: Yahoo Finance."), [])
    assert s["no_provider_names"] is False and d["no_provider_names"]["found"] == ["Yahoo"]


def test_split_pngs_reads_a_concatenated_stream():
    import io
    blobs = []
    for c in (0, 128, 255):
        b = io.BytesIO()
        Image.new("L", (4, 3), c).save(b, "PNG")
        blobs.append(b.getvalue())
    assert rr.split_pngs(b"".join(blobs)) == blobs
