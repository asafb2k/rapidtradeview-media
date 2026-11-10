"""The cartoon Reel's FEATURE mode (tools/gv/scripts/cartoon/features.json, make_feature_story.py, the feature gates in
cartoon_qa.py): a registry entry + the sidecars of a capture made today -> a one-idea story whose every number and name is
on the capture. Offline: no capture, no voice, no render.  Run: python -m pytest tools/tests -q"""
import copy
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
CART = TOOLS / "gv" / "scripts" / "cartoon"
sys.path.insert(0, str(CART))
_spec = importlib.util.spec_from_file_location("gv_cartoon_make_feature_story", CART / "make_feature_story.py")
F = importlib.util.module_from_spec(_spec)
sys.modules["gv_cartoon_make_feature_story"] = F
_spec.loader.exec_module(F)
Q, M = F.Q, F.M

NOW = dt.datetime(2026, 11, 10, 9, 0, 0, tzinfo=dt.timezone.utc)
AT = "2026-11-10T08:30:00Z"
SITE = "https://www.rapidtradeview.trade"
HEADER = "RapidTradeView\n0\n/\n2\nregister/sign-in"
BRAND_TG = {"text": "RapidTradeView", "box": [144, 36.0, 370.3, 66]}


def side(url, size, vis, targets, page=None, at=AT):
    return {"url": url, "captured_at": at, "png_size": size, "visible_text": vis, "targets": targets,
            "page_text": page if page is not None else vis}


def congress(count="4", ticker="NVDA", name="NVIDIA Corporation"):
    row = (f"{ticker}\n{name}\n−18.3% (SPY −4.9%)\n{count} members buying\n·\n7 buy filings\n·\n7 sell filings\n·\n"
           "first buy filing Sep 2, 2026")
    url = f"{SITE}/congress-trades"
    page = "Congress stock trades tracker\nMost bought stocks by Congress\n" + row + "\nCompany logos by Elbstream"
    return {
        "head": side(url, [1170, 138], HEADER, [BRAND_TG], page),
        "fact": side(url, [1170, 459], "Most bought stocks by Congress\nTicker\nSince first buy filing\n" + row,
                     [{"text": "Most bought stocks by Congress", "box": [111, 30.0, 698.2, 63]}], page),
        "key": side(url, [2340, 510], "Ticker\nSince first buy filing\n" + row,
                    [{"text": ticker, "box": [270, 229.5, 233.7, 114]}, {"text": name, "box": [551.7, 241.5, 636.4, 96]},
                     {"text": f"{count} members buying", "box": [270, 367.5, 594, 96]}], page),
    }


SAMPLE_HEAD = side(f"{SITE}/sample-portfolio", [1170, 492],
                   HEADER + "\nREAD-ONLY SAMPLE\nSample portfolio\n40 stocks + VOO and QQQ. Illustrative share counts, recorded prices.",
                   [BRAND_TG, {"text": "READ-ONLY SAMPLE", "box": [99, 308.2, 341.9, 42]},
                    {"text": "Sample portfolio", "box": [99, 383.2, 453.5, 81]}],
                   "Sample portfolio\nPortfolio Concentration\nConcentrated")
SENTENCE = "Technology is 57% of your money. In the S&P 500 it's 39%."


def concentration(verdict="Concentrated"):
    url = f"{SITE}/sample-portfolio"
    page = SAMPLE_HEAD["page_text"]
    return {
        "head": SAMPLE_HEAD,
        "fact": side(url, [1170, 360], f"Portfolio Concentration\n{verdict}\n33% of your money is in 9 chip companies.\n{SENTENCE}",
                     [{"text": "Portfolio Concentration", "box": [87, 42.0, 485.4, 63]},
                      {"text": verdict, "box": [824.9, 51.0, 228.1, 48]}], page),
        "key": side(url, [2340, 246], f"Portfolio Concentration\n{verdict}",
                    [{"text": verdict, "box": [1649.7, 78.0, 456.3, 96]}], page),
    }


def portfolio(key_size=(2340, 1830)):
    url = f"{SITE}/sample-portfolio"
    page = SAMPLE_HEAD["page_text"]
    return {
        "head": SAMPLE_HEAD,
        "fact": side(url, [1170, 216], f"{SENTENCE}\nInner ring: your\n42 holdings\n· outer ring: their sectors",
                     [{"text": "outer ring: their sectors", "box": [633.3, 158.2, 369.7, 48]}], page),
        "key": side(url, list(key_size), "Inner ring: your\n42 holdings\n· outer ring: their sectors\n57%\n10%\n8.4%\n8.2%\n6.1%\n"
                                         "TOTAL\n$198.8K\n42 holdings",
                    [{"text": "57%", "box": [1761.3, 1069.2, 139.2, 90]}, {"text": "TOTAL", "box": [1078.2, 786.0, 183.5, 84]}], page),
    }


def market(verb="rose"):
    url = f"{SITE}/market"
    page = "MARKET BREADTH\nLast session (Mon, Nov 9)\nREDDIT BUZZ"          # innerText: CSS upper-casing applied
    return {
        "head": side(url, [1170, 138], HEADER, [BRAND_TG], page),
        "fact": side(url, [1170, 393], f"Market breadth\n·\nLast session (Mon, Nov 9)\nShare\n2,061\nof 2,494 stocks {verb} —\n83%\n"
                                       "2,061 up\n409 down\n83%\n16%",
                     [{"text": "Market breadth", "box": [81, 36.0, 326.3, 42]}], page),
        "key": side(url, [2340, 258], f"·\nLast session (Mon, Nov 9)\n2,061\nof 2,494 stocks {verb} —\n83%\n2,061 up\n409 down",
                    [{"text": "83%", "box": [1896.8, 48.0, 256.7, 162]}], page),
    }


METAS = {"smart-money": congress, "concentration": concentration, "portfolio": portfolio, "market-pictures": market}


@pytest.fixture(scope="module")
def reg():
    return Q.load_features()


def story_for(reg, fid, metas=None):
    feature = Q.feature_by_id(reg, fid)
    metas = metas or METAS[fid]()
    screens = {n: {"png": f"screens/{n}.png", "size": m["png_size"], "meta": m} for n, m in metas.items()}
    values = Q.feature_values(feature, metas)
    return feature, metas, F.build_story(feature, values, screens, Q.capture_day(metas))


# ------------------------------------------------------------------------------------------------- the registry
def test_the_shipped_registry_is_usable_and_has_the_four_features(reg):
    assert [f["id"] for f in reg["features"]] == ["smart-money", "concentration", "portfolio", "market-pictures"]
    for f in reg["features"]:
        assert f["url"].startswith(SITE + "/")
        assert "RapidTradeView" in f["lines"]["confused"]
        for k in Q.FEATURE_LINES + ("search",):                 # a line never types a number: numbers are slots
            assert not Q.find_numbers(Q._unslot(f["lines"][k])), (f["id"], k)


def test_registry_problems_are_named(reg):
    def broken(change):
        r = copy.deepcopy({k: v for k, v in reg.items() if k != "_path"})
        change(r["features"][0])
        return " | ".join(Q.registry_problems(r))

    assert not Q.registry_problems({k: v for k, v in reg.items() if k != "_path"})
    assert "schema" in " ".join(Q.registry_problems({"schema": "x"}))
    assert "slot {price} is not read" in broken(lambda f: f["lines"].update(fact_b="{ticker} at {price}."))
    assert "types a number" in broken(lambda f: f["lines"].update(hook="4 in Congress bought one stock!", hook_figure="{count}"))
    assert "types a number" in broken(lambda f: f["lines"].update(confused="Four? Checking RapidTradeView."))
    assert "names a data provider" in broken(lambda f: f["lines"].update(fact_a="Most bought stocks, per Quiver."))
    assert "banned words" in broken(lambda f: f["lines"].update(fact_a="Buy now: most bought stocks by Congress."))
    assert "not a page of" in broken(lambda f: f.update(url="https://example.com/congress-trades"))
    assert "must say our brand" in broken(lambda f: f["lines"].update(confused="Which stock? Checking."))
    assert "does not target our brand" in broken(lambda f: f["captures"][0].update(targets=["Congress"]))
    assert "not a capture without slots" in broken(lambda f: f["values"][0].update({"from": "key"}))
    assert "no claim" in broken(lambda f: f["claims"].pop("hook"))
    assert "hook_figure must be a slot" in broken(lambda f: f["lines"].update(hook_figure="{ticker}"))


def test_unknown_feature_and_unfilled_slot_are_errors(reg):
    with pytest.raises(Q.FeatureError):
        Q.feature_by_id(reg, "etf-holdings")
    with pytest.raises(Q.FeatureError):
        Q.fill("{count} members", {})
    assert Q.fill("{ticker}: {count_line}.", {"ticker": "NVDA", "count_line": "4 members buying"}) == "NVDA: 4 members buying."


# ------------------------------------------------------------------------------------------------- values from the capture
def test_values_are_read_from_the_top_row_only(reg):
    f = Q.feature_by_id(reg, "smart-money")
    assert Q.feature_values(f, congress()) == {"ticker": "NVDA", "name": "NVIDIA Corporation", "count": "4",
                                               "count_line": "4 members buying"}
    assert Q.feature_values(f, congress("14", "V", "Visa Inc."))["count_line"] == "14 members buying"
    m = congress()
    m["fact"]["visible_text"] += "\nMSFT\nMicrosoft Corporation\n+7.4% (SPY −4.0%)\n3 members buying"
    assert Q.feature_values(f, m)["ticker"] == "NVDA"           # a second row changes nothing


def test_missing_region_or_a_story_that_does_not_hold_stops(reg):
    f = Q.feature_by_id(reg, "smart-money")
    with pytest.raises(Q.FeatureError, match="below 2"):
        Q.feature_values(f, congress("1"))                      # "1 members buying" would never be on the page; a 1 breaks the hook
    m = congress()
    m["fact"]["visible_text"] = "Most bought stocks by Congress\nThe Congress tracker is unavailable right now"
    with pytest.raises(Q.FeatureError, match="no line 'Since first buy filing'"):
        Q.feature_values(f, m)
    m = congress()
    m["fact"]["visible_text"] = m["fact"]["visible_text"].replace("NVIDIA Corporation\n", "")     # no company name line
    with pytest.raises(Q.FeatureError):
        Q.feature_values(f, m)
    with pytest.raises(Q.FeatureError, match="not 'Concentrated'"):
        Q.feature_values(Q.feature_by_id(reg, "concentration"), concentration("Balanced"))
    with pytest.raises(Q.FeatureError, match="was not made"):
        Q.feature_values(f, {"head": congress()["head"]})


def test_market_values_follow_the_days_direction(reg):
    f = Q.feature_by_id(reg, "market-pictures")
    v = Q.feature_values(f, market("fell"))
    assert v == {"total": "2,494", "verb": "fell", "mid": "of 2,494 stocks fell —", "count": "2,061", "pct": "83%"}
    assert Q.feature_lines(f, v)["hook"] == "83% of stocks fell!"
    assert Q.feature_lines(f, v)["fact_a"] == "2,061 of 2,494 stocks fell:"


def test_verbatim_is_word_for_word():
    meta = {"visible_text": "2,061\nof 2,494 stocks rose —\n83%\n2,061 up"}
    assert Q.on_capture("2,061 of 2,494 stocks rose — 83%", meta)
    assert Q.on_capture("2,061 of 2,494 stocks rose: 83%.", meta)       # punctuation is not a word
    assert not Q.on_capture("2,061 of 2,494 stocks rose — 8.3%", meta)
    assert not Q.on_capture("2,494 of 2,061 stocks rose", meta)
    assert not Q.on_capture("stocks rose 83% 409 down", meta)             # not an unbroken run
    assert Q.page_words("−18.3% (SPY −4.9%)") == ["-18.3%", "SPY", "-4.9%"]


# ------------------------------------------------------------------------------------------------- the capture gate
def test_capture_gate_passes_todays_clean_captures(reg):
    for fid, make in METAS.items():
        ok, det = Q.feature_capture_gate(Q.feature_by_id(reg, fid), make(), NOW)
        assert ok, (fid, det["problems"])


def test_capture_gate_refuses_stale_foreign_broken_or_branded_captures(reg):
    f = Q.feature_by_id(reg, "smart-money")

    def why(change, now=NOW):
        m = congress()
        change(m)
        ok, det = Q.feature_capture_gate(f, m, now)
        assert not ok
        return json.dumps(det["problems"])

    assert "capture it again today" in why(lambda m: None, NOW + dt.timedelta(hours=13))          # yesterday's capture
    assert "capture it again today" in why(lambda m: m["key"].update(captured_at="2026-11-10T10:00:00Z"))   # the future
    assert "is not https://www.rapidtradeview.trade/congress-trades" in why(lambda m: m["fact"].update(url=f"{SITE}/smart-money"))
    assert "provider names on screen" in why(lambda m: m["fact"].update(visible_text=m["fact"]["visible_text"] + "\nCompany logos by Elbstream"))
    assert "provider names on screen" in why(lambda m: m["head"].update(visible_text=HEADER + "\nREDDIT"))
    assert "error or loading state" in why(lambda m: m["fact"].update(visible_text="Most bought stocks by Congress\nLoading…"))
    assert "the page says" in why(lambda m: m["head"].update(page_text="The Congress tracker is unavailable right now (the filings store did not answer)."))
    assert "the page lacks" in why(lambda m: m["head"].update(page_text="Congress stock trades tracker"))
    assert "capture missing" in why(lambda m: m.pop("key"))
    # a provider in the page's footer, far below the bands, is not on screen
    assert "Elbstream" in congress()["fact"]["page_text"]
    # `require` is matched without case: the page text has CSS upper-casing applied
    assert Q.feature_capture_gate(Q.feature_by_id(reg, "market-pictures"), market(), NOW)[0]


# ------------------------------------------------------------------------------------------------- the story
@pytest.mark.parametrize("fid", list(METAS))
def test_story_follows_the_owner_rules_and_the_registry(reg, fid):
    feature, metas, story = story_for(reg, fid)
    shots = story["shots"]
    assert len(shots) == 7 and [s["kind"] for s in shots] == ["HOOK", "CLOSE", "CLOSE", "PAYOFF", "PAYOFF", "CALLBACK", "END"]
    assert "RapidTradeView" in shots[1]["vo"] and shots[-1]["vo"] == "Search RapidTradeView. Not investment advice."
    assert story["item_id"] == f"2026-11-10-feature-{fid}" and "facts_file" not in story
    assert Q.one_idea_gate(shots, 16.0)[0]
    assert not F.check_story(story, feature, metas, NOW)
    # every number the script says or draws is on a capture
    item = Q.feature_item(feature, story["feature"]["values"], metas, story["item_id"])
    said = {f"s{i}": s["vo"] for i, s in enumerate(shots) if s.get("vo")}
    said["chip"] = shots[0]["chip"]["text"]
    assert Q.numbers_gate(said, Q.allowed_set(item))[0]
    assert Q.spoken_numbers_gate(story["say"])[0]
    # the real header card is in the first payoff shot; the key is outlined in the second
    assert any(e.get("name") == "head" for e in shots[3]["els"])
    assert any(e.get("t") == "highlight" and e["target"] == shots[4]["key_number"] for e in shots[4]["els"])
    assert shots[4].get("lead", 0) >= 0.4 and not shots[4]["join"]       # the key lands before the voice names it


def test_filled_lines_come_from_the_capture(reg):
    _f, _m, s = story_for(reg, "smart-money")
    assert [x["vo"] for x in s["shots"] if x.get("vo")][:4] == [
        "4 in Congress bought one stock!", "Which stock? Checking RapidTradeView.", "Most bought stocks by Congress.",
        "NVDA: 4 members buying."]
    assert s["say"]["NVDA:"] == "N V D A:" and s["say"]["4"] == "four"
    _f, _m, s = story_for(reg, "smart-money", congress("6", "PG", "The Procter & Gamble Company"))
    assert s["shots"][0]["vo"] == "6 in Congress bought one stock!" and s["shots"][4]["vo"] == "PG: 6 members buying."
    assert s["shots"][0]["chip"]["text"] == "6" and s["shots"][4]["key_number"] == "PG"


def test_a_story_edited_by_hand_fails(reg):
    feature, metas, story = story_for(reg, "smart-money")
    assert Q.feature_story_gate(story, feature, metas)[0]

    def problems(change):
        s = copy.deepcopy(story)
        change(s)
        ok, det = Q.feature_story_gate(s, feature, metas)
        assert not ok
        return " | ".join(det["problems"])

    assert "voice lines" in problems(lambda s: s["shots"][0].update(vo="9 in Congress bought one stock!"))
    assert "story values" in problems(lambda s: s["feature"]["values"].update(count="9"))
    assert "chips" in problems(lambda s: s["shots"][0]["chip"].update(text="40"))
    assert "the phone types" in problems(lambda s: s["shots"][2]["els"][0].update(text="TSLA"))
    assert "ticker-like words" in problems(lambda s: s["shots"][2]["els"][0].update(text="TSLA"))
    assert "key" in problems(lambda s: s["shots"][4].update(key_number="4 members buying"))
    assert "carries claim" in problems(lambda s: s["shots"][0].update(claim="heading"))
    assert "no bubble" in problems(lambda s: s["shots"][1].update(bubble={"text": "WOW", "x": 500, "y": 500}))
    # the page changed after the story was written: the same story no longer matches the sidecars
    ok, det = Q.feature_story_gate(story, feature, congress("5"))
    assert not ok and "story values" in " ".join(det["problems"])


def test_check_story_catches_what_the_renderer_would(reg):
    feature, metas, story = story_for(reg, "portfolio")
    s = copy.deepcopy(story)
    s["shots"][3]["vo"] = "Technology is 75% of your money."
    probs = " | ".join(F.check_story(s, feature, metas, NOW))
    assert "numbers that are not on a capture" in probs and "voice lines" in probs
    assert "capture it again today" in " | ".join(F.check_story(story, feature, metas, NOW + dt.timedelta(days=1)))


def test_feature_item_is_built_from_the_captures(reg):
    feature, metas, story = story_for(reg, "smart-money")
    item = Q.feature_item(feature, story["feature"]["values"], metas, story["item_id"])
    assert item["ticker"] == "NVDA" and item["name"] == "NVIDIA Corporation"
    assert {"4", "7", "-18.3%", "-4.9%", "Sep 2, 2026", "0", "2"} <= Q.allowed_set(item)
    assert {p["id"] for p in item["phrasings"]} == {"heading", "row"}
    lines = [{"line": s["vo"], "claim": s.get("claim")} for s in story["shots"][:-1] if s.get("vo")]
    ok, det = Q.claim_lines_gate(lines, item, story["post_date"])
    assert ok, det["bad"]
    assert [c["line"] for c in det["needs_human_check"]] == ["4 in Congress bought one stock!", "Most bought stocks by Congress.",
                                                             "NVDA: 4 members buying."]
    bad = [{"line": "MSFT: 4 members buying.", "claim": "row"}]
    assert not Q.claim_lines_gate(bad, {**item, "tickers": ["NVDA", "MSFT"]}, story["post_date"])[0]
    # a source text that is not on its capture stops the item
    f2 = copy.deepcopy(feature)
    f2["sources"]["heading"]["text"] = "Most sold stocks by Congress"
    with pytest.raises(Q.FeatureError, match="is not on the fact capture"):
        Q.feature_item(f2, story["feature"]["values"], metas, story["item_id"])


def test_fact_phrase_is_on_a_capture_and_read_aloud(reg):
    _f, metas, story = story_for(reg, "market-pictures")
    script = " ".join(s["vo"] for s in story["shots"][:-1] if s.get("vo"))
    ok, det = Q.feature_fact_gate(story["fact_phrase"], metas, script)
    assert ok and det["on_captures"] == ["fact", "key"]
    assert not Q.feature_fact_gate("2,061 of 2,494 stocks rose — 38%", metas, script)[0]
    assert not Q.feature_fact_gate(story["fact_phrase"], metas, "83% of stocks rose! How many?")[0]


def test_captures_are_one_day(reg):
    m = congress()
    assert Q.capture_day(m) == "2026-11-10"
    m["key"]["captured_at"] = "2026-11-11T00:01:00Z"
    with pytest.raises(Q.FeatureError):
        Q.capture_day(m)


# ------------------------------------------------------------------------------------------------- layout and key
def test_stack_layout_keeps_every_card_in_the_frame(reg):
    for fid in ("smart-money", "concentration", "market-pictures"):
        _f, _m, story = story_for(reg, fid)
        s5 = story["shots"][4]
        widest = max(e["w"] for e in s5["els"] if e.get("t") == "card")
        assert (widest + 20) * s5["move"]["z"] * (1 + 4 * M.Z5_DRIFT) <= 1080 - 2 * 40 + 1, fid
        key = next(e for e in s5["els"] if e.get("name") == "key")
        x0, y0, x1, y1 = key["crop"]
        assert 0 <= x0 < x1 <= _m["key"]["png_size"][0] and 0 <= y0 < y1 <= _m["key"]["png_size"][1]


def test_key_crop_spans_ticker_and_name_and_pads_a_pill(reg):
    _f, m, story = story_for(reg, "smart-money")
    x0, y0, x1, y1 = next(e for e in story["shots"][4]["els"] if e.get("name") == "key")["crop"]
    assert x0 < 270 and x1 > 551.7 + 636.4                       # NVDA ... NVIDIA Corporation
    assert y1 < 367.5                                            # the count line below stays out of the crop
    _f, m, story = story_for(reg, "concentration")
    x0, y0, x1, y1 = next(e for e in story["shots"][4]["els"] if e.get("name") == "key")["crop"]
    assert 1649.7 - x0 > 2 * 96 and x1 - (1649.7 + 456.3) < 1.1 * 96      # room for the pill's icon on the left


def test_hero_layout_fills_the_stage_and_stays_inside_it(reg):
    _f, _m, story = story_for(reg, "portfolio")
    s5 = story["shots"][4]
    hero = next(e for e in s5["els"] if e.get("name") == "key")
    assert hero["w"] >= 800 and "crop" not in hero
    h = 1830 * hero["w"] / 2340 + 20
    f = 1 + F.HERO_DRIFT * F.HERO_SHOT_S
    assert 960 - (960 - (hero["y"] - h / 2)) * f >= M.STAGE_TOP - 1          # below the brand pill after the drift
    assert 960 + (hero["y"] + h / 2 - 960) * f <= M.STAGE_BOTTOM + 1         # above the caption band
    assert s5["move"]["z"] == 1.0 and s5["move"]["min_px"] is False
    assert all(e.get("exit") for e in s5["els"] if e.get("name") in ("head", "fact"))
    with pytest.raises(M.TemplateError, match="too small"):                  # a tall band: the chart would be a thumbnail
        story_for(reg, "portfolio", portfolio(key_size=(2340, 5200)))


def test_key_target_gate_figure_and_visual():
    def run(h, card_w, n=60, box=(300, 600, 700, 700)):
        return [{"t": i / 30, "h": h, "card_w": card_w, "box": list(box)} for i in range(n)]

    assert Q.key_target_gate(run(90, 700), 30, "figure")[0]
    assert not Q.key_target_gate(run(40, 900), 30, "figure")[0]              # a 40 px figure is too small
    assert Q.key_target_gate(run(36, 880), 30, "visual")[0]                  # a chart label: the chart is big
    assert not Q.key_target_gate(run(36, 500), 30, "visual")[0]              # a small chart is not
    assert not Q.key_target_gate(run(24, 880), 30, "visual")[0]              # an unreadable label is not
    assert not Q.key_target_gate(run(90, 700, n=30), 30, "figure")[0]        # 1 s is too short
    assert not Q.key_target_gate(run(90, 700, box=(900, 600, 1070, 700)), 30, "figure")[0]   # under the action rail


def test_capture_specs_fill_slots_and_keep_whole_node_marks(reg):
    f = Q.feature_by_id(reg, "smart-money")
    v = Q.feature_values(f, congress("14", "V", "Visa Inc."))
    key = next(F.filled(c, v) for c in f["captures"] if c["name"] == "key")
    assert key["clip_to"] == "14 members buying" and key["targets"] == ["=V", "=Visa Inc.", "14 members buying"]
    assert [c["name"] for c in f["captures"] if not F.has_slots(c)] == ["head", "fact"]


def test_capture_spec_parsing():
    spec = importlib.util.spec_from_file_location("gv_cartoon_capture", CART / "capture.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)                                 # playwright is imported inside main(), not here
    assert cap.split_spec("=V") == ("V", "1", True)
    assert cap.split_spec("first buy filing #1") == ("first buy filing ", "1", False)
    assert cap.split_spec("EPS#last") == ("EPS", "last", False)
    assert cap.split_spec("57%#2") == ("57%", "2", False)
    assert cap.split_spec("=57%#2") == ("57%", "2", True)


def test_make_feature_story_exit_codes(tmp_path, capsys):
    assert F.main(["--list"]) == 0
    assert "smart-money" in capsys.readouterr().out
    assert F.main(["etf-holdings", "--run", str(tmp_path)]) == 2             # not in the registry
    assert F.main(["smart-money", "--run", str(tmp_path)]) == 2              # no captures, no --capture: no story
    assert not (tmp_path / "story.json").exists()
    for n, m in congress("1").items():                                       # a top row with one member: the hook does not hold
        (tmp_path / "screens").mkdir(exist_ok=True)
        (tmp_path / "screens" / f"{n}.json").write_text(json.dumps(m), encoding="utf-8")
        (tmp_path / "screens" / f"{n}.png").write_bytes(b"png")
    assert F.main(["smart-money", "--run", str(tmp_path)]) == 2
    assert "below 2" in capsys.readouterr().err and not (tmp_path / "story.json").exists()


# ------------------------------------------------------------------------------------------------- the renderer's side
def _reel():
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    spec = importlib.util.spec_from_file_location("gv_cartoon_reel", CART / "cartoon_reel.py")
    if "gv_cartoon_reel" in sys.modules:
        return sys.modules["gv_cartoon_reel"]
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gv_cartoon_reel"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_run(tmp_path, reg, fid, metas=None, edit=None):
    """A run folder as make_feature_story leaves it: story.json + screens/<name>.png + sidecars (tiny real PNGs)."""
    from PIL import Image
    feature, metas, story = story_for(reg, fid, metas)
    (tmp_path / "screens").mkdir(exist_ok=True)
    for n, m in metas.items():
        png = tmp_path / "screens" / f"{n}.png"
        Image.new("RGB", (m["png_size"][0] // 10, m["png_size"][1] // 10), (12, 12, 16)).save(png)
        (tmp_path / "screens" / f"{n}.json").write_text(json.dumps(m), encoding="utf-8")
    story = json.loads(json.dumps(story))
    if edit:
        edit(story)
    (tmp_path / "story.json").write_text(json.dumps(story), encoding="utf-8")
    return tmp_path / "story.json"


def test_renderer_builds_the_item_from_the_sidecars_not_the_story(reg, tmp_path):
    R = _reel()
    st = R.Story(_write_run(tmp_path, reg, "smart-money", edit=lambda s: s["feature"]["values"].update(count="99")))
    assert st.feature["id"] == "smart-money" and st.item["type"] == "feature"
    assert "4" in Q.allowed_set(st.item) and "99" not in Q.allowed_set(st.item)      # the story's typed 99 is not data
    assert "insider trading" in st.banned
    assert not Q.feature_story_gate(st.doc, st.feature, {n: sc["meta"] for n, sc in st.screens.items()})[0]


def test_renderer_refuses_a_feature_story_whose_page_does_not_carry_it(reg, tmp_path):
    R = _reel()
    with pytest.raises(R.InputError, match="no feature"):
        R.Story(_write_run(tmp_path, reg, "smart-money", edit=lambda s: s["feature"].update(id="etf-holdings")))
    with pytest.raises(R.InputError, match="capture day"):
        R.Story(_write_run(tmp_path, reg, "smart-money", edit=lambda s: s.update(item_id="2026-11-09-feature-smart-money")))
    path = _write_run(tmp_path, reg, "smart-money")
    side_ = tmp_path / "screens" / "fact.json"
    m = json.loads(side_.read_text(encoding="utf-8"))
    m["visible_text"] = m["visible_text"].replace("4 members buying", "1 members buying")
    side_.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(R.InputError, match="below 2"):
        R.Story(path)


def test_lead_puts_the_key_on_screen_before_its_line(reg, tmp_path, monkeypatch):
    """Shot 5 starts `lead` seconds before its first word (the key lands, the camera settles, then the voice names it)."""
    R = _reel()
    import wave

    def fake_tts(story, utts, work, tts_python):                  # 0.3 s per spoken token, silence
        work.mkdir(parents=True, exist_ok=True)
        for k, u in enumerate(utts):
            toks = u["spoken"].split()
            u.update(voice_id="x", speed=1.0, wav=work / f"{k}.wav", timings=work / f"{k}.json")
            with wave.open(str(u["wav"]), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
                w.writeframes(b"\x10\x20" * int(24000 * 0.3 * len(toks)))
            u["timings"].write_text(json.dumps([{"word": t, "start": 0.3 * i, "end": 0.3 * i + 0.25} for i, t in enumerate(toks)]),
                                    encoding="utf-8")

    monkeypatch.setattr(R, "run_tts", fake_tts)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_lead = R.Timeline(R.Story(_write_run(tmp_path / "a", reg, "portfolio")), tmp_path / "a" / "tts", "unused")
    no_lead = R.Timeline(R.Story(_write_run(tmp_path / "b", reg, "portfolio", edit=lambda s: s["shots"][4].pop("lead"))),
                         tmp_path / "b" / "tts", "unused")
    lead = F.LEAD5
    first = lambda tl: min(w.start for w in tl.words if w.shot == 4)          # noqa: E731
    assert with_lead.starts[4] == pytest.approx(no_lead.starts[4], abs=1 / R.FPS)
    assert first(with_lead) - with_lead.starts[4] == pytest.approx(lead + R.LEAD_F / R.FPS, abs=1 / R.FPS)
    assert first(no_lead) - no_lead.starts[4] == pytest.approx(R.LEAD_F / R.FPS, abs=1 / R.FPS)
    assert with_lead.total == pytest.approx(no_lead.total + lead, abs=2 / R.FPS)
    assert all(c["start"] >= with_lead.starts[4] + lead - 1 / R.FPS for c in with_lead.chunks if c["shot"] == 4)
