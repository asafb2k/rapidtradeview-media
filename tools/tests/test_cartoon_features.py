"""The cartoon Reel's FEATURE mode (tools/gv/scripts/cartoon/features.json, make_feature_story.py, the feature gates in
cartoon_qa.py): a registry entry + the sidecar of a capture made today -> a one-idea story whose every number and name is
on the capture, whose voice says nothing the captions do not show, and whose payoff is the site's card WHOLE (owner
verdict 2026-11-10: "they arent good, only the last one show the visuals correctly as it shown on website"): one strip of
the page at phone width in one window, scrolled when it is taller than the stage, the key outlined in place, no fragment
card. Offline: no capture, no voice, no encode.  Run: python -m pytest tools/tests -q"""
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
AT = "2026-11-10T08:30:00Z"                  # 03:30 US Eastern on Tue Nov 10: the last closed session is Mon Nov 9
SITE = "https://www.rapidtradeview.trade"
HOME, LANDS = f"{SITE}/market", f"{SITE}/#market"
SAMPLE = f"{SITE}/sample-portfolio"
HEADER = "RapidTradeView\n0\n/\n2\nregister/sign-in"
ALL = ("congress", "insiders", "concentration", "portfolio", "market-breadth")


def seal(m):
    m["seal"] = Q.capture_seal(m)
    return m


def strip(url, size, text, targets, boxes, page=None, at=AT, final=None, top=0.0, vis=None):
    """A strip sidecar as capture.py writes it (the page at phone width, 3 px per CSS px). `text` is what the PNG shows;
    `vis` the wide text (every line touching the strip; default: the same)."""
    return seal({"url": url, "final_url": final or url, "captured_at": at, "viewport": [390, 844], "dpr": 3,
                 "png_size": list(size), "sha256": "0" * 64, "visible_text": text if vis is None else vis, "inside_text": text,
                 "targets": targets, "page_text": page if page is not None else text, "kind": "strip",
                 "strip": {"top": top, "bottom": top + size[1] / 3, "page_height": 8048}, "boxes": boxes})


def congress(sells="130", buys="76", sells_word="sells,", buys_word="buys"):
    text = (f"Congress trades\nShare\n{sells}\n{sells_word}\n{buys}\n{buys_word}\n← SELLS\nBUYS →\nTechnology\n28\n24\nHealthcare\n26\n12\n"
            "Utilities\n1\n0\nMost traded:\nSTLN\n12\n·\nNVDA\n8\nAll Congress trades →")
    return {"page": strip(HOME, [1170, 1488], text,
                          [{"text": sells, "box": [81.0, 125.3, 127.5, 90]}, {"text": "buys", "box": [505.9, 125.3, 155.9, 90]}],
                          {"card": [36, 20.3, 1098, 1446.9], "title": [81, 71.7, 349.7, 42.0], "headline": [81, 134.3, 1008, 77.2],
                           "chart": [81, 220.5, 1008, 984.1]},
                          "MARKET BREADTH\nCONGRESS TRADES\n" + text + "\nINSIDER TRADES\nREDDIT BUZZ", final=LANDS, top=2409.0)}


def insiders(bought="$502M", sold="$3.6B"):
    text = (f"Insider trades\nShare\n{bought}\nbought,\n{sold}\nsold by insiders\nBought\n{bought}\n264\ncompanies\n·\n30\n-day totals\n"
            f"MGM\n1 director\nMGM Resorts International\nCons. Cyclical\n$51.7M\nSold\n{sold}\n534\ncompanies\n·\n30\n-day totals\n"
            "SYK\n1 director\nStryker\nHealthcare\n$179M\nSmart Money feed →")
    return {"page": strip(HOME, [1170, 2022], text,
                          [{"text": bought, "box": [81.0, 123.2, 234.1, 90]}, {"text": "sold by insiders", "box": [81.0, 123.2, 951.6, 167.2]}],
                          {"card": [36, 18.2, 1098, 1985.1], "title": [81, 69.6, 326.3, 42.0], "headline": [81, 132.2, 1008, 154.5],
                           "chart": [81, 363.2, 1008, 1523.1]},
                          "CONGRESS TRADES\nINSIDER TRADES\n" + text + "\nREDDIT BUZZ", final=LANDS, top=2904.0)}


CARD_TEXT = ("Portfolio Concentration\n{verdict}\n33% of your money is in 9 chip companies.\n"
             "Technology is 57% of your money. In the S&P 500 it's 39%.\nInner ring: your\n42 holdings\n· outer ring: their sectors\n"
             "57%\n10%\n8.4%\n8.2%\n6.1%\nTOTAL\n$198.8K\n42 holdings")
SAMPLE_PAGE = "READ-ONLY SAMPLE\nSample portfolio\nPortfolio Concentration\nConcentrated\nBIGGEST INDUSTRY GROUPS\nLARGEST HOLDINGS"
HEADLINE = "33% of your money is in 9 chip companies."


def concentration(verdict="Concentrated"):
    return {"page": strip(SAMPLE, [1170, 1230], CARD_TEXT.format(verdict=verdict),
                          [{"text": HEADLINE, "box": [87.0, 156.0, 871.2, 60]}],
                          {"card": [48, 3.0, 1074, 1222.1], "title": [87, 48.0, 485.4, 63], "pill": [824.9, 57.0, 228.1, 48],
                           "headline": [87, 156.0, 871.2, 60], "chart": [195, 445.1, 780, 780.0]}, SAMPLE_PAGE, top=394.0)}


def portfolio(row2=(785.6, 2559.4)):
    text = (HEADER + "\nREAD-ONLY SAMPLE\nSample portfolio\n40 stocks + VOO and QQQ. Illustrative share counts, recorded prices.\n"
            "Build yours — register free\nSample portfolio value\n$198,819.47\n42 holdings · prices recorded\n2026-09-24\n"
            + CARD_TEXT.format(verdict="Concentrated") + "\nSectors\nyou · S&P 500\nTechnology\n▲\nhigh\n57%\nS&P 500\n39%\n"
            "Consumer Cyclical\n10%\nS&P 500\n9.3%\nShow all (\n11\n)\nBiggest industry groups\nChip companies\n9 holdings\n▲\nhigh\n33%\n"
            "Largest holdings\nVOO\nfund\n8.9%\nNVDA\n7.3%\nShow all (\n42\n)")
    return {"page": strip(SAMPLE, [1170, 4863], text,
                          [{"text": "Technology", "box": [141.0, 2559.4, 196.2, 51]}, {"text": "57%#2", "box": [row2[0], row2[1], 75.4, 51]},
                           {"text": "Sectors", "box": [87.0, 2458.1, 173.6, 48]}, {"text": "RapidTradeView", "box": [144.0, 60.8, 370.3, 66]}],
                          {"card": [0, 0.0, 1170, 4831.9], "header": [0, 0.0, 1170, 195], "value": [327.7, 909.0, 514.7, 162],
                           "chart": [195, 1627.1, 780, 780.0], "sectors": [87, 2458.1, 173.6, 957.8], "groups": [87, 3496.1, 558.0, 48.0],
                           "holdings": [87, 4006.1, 397.1, 825.8]}, SAMPLE_PAGE)}


def market(verb="rose", label="Last session (Mon, Nov 9)", count="2,061", total="2,494", pct="83%", at=AT):
    text = (f"Market breadth\n·\n{label}\nShare\n{count}\nof {total} stocks {verb} —\n{pct}\n{count} up\n409 down\n{pct}\n16%\n"
            "Up minus down, last 20 closes\n+2,000\n0\n−2,000\nOct 13\nOct 26\n+1,652\nNov 9 (Mon)")
    return {"page": strip(HOME, [1170, 1203], text, [{"text": pct, "box": [948.4, 175.2, 128.3, 81]}],
                          {"card": [36, 8.7, 1098, 1187.6], "title": [81, 59.7, 326.3, 42.0], "headline": [81, 181.2, 1008, 72.4],
                           "chart": [81, 262.6, 1008, 894.7]},
                          "MARKET BREADTH\n" + label + "\nREDDIT BUZZ", at, final=LANDS, top=996.0)}   # innerText: CSS upper-casing


METAS = {"congress": congress, "insiders": insiders, "concentration": concentration, "portfolio": portfolio,
         "market-breadth": market}


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
def test_the_shipped_registry_is_usable_and_shows_whole_cards(reg):
    assert tuple(f["id"] for f in reg["features"]) == ALL
    for f in reg["features"]:
        assert f["url"].startswith(SITE + "/") and f["viewport"].startswith("390x")
        assert "RapidTradeView" in f["lines"]["confused"]
        assert f["phone"] == "tap" and f.get("post_note")       # a page is opened by a tap on its link, never typed
        for k in Q.FEATURE_LINES + ("search",):                 # a line never types a number: numbers are slots
            assert not Q.find_numbers(Q._unslot(f["lines"][k])), (f["id"], k)
        # one strip of the real page that holds the card and its named parts; no fragment capture of schema /1
        assert "captures" not in f and "layout" not in f and set(f["key"]) <= {"targets", "top"}
        assert f["site"]["card"]["box"] and len(f["site"]["parts"]) >= 2
        assert all(v["from"] == "page" for v in f["values"])
    assert Q.feature_by_id(reg, "portfolio")["site"]["header"] is True          # the page from its header down
    assert not Q.feature_by_id(reg, "congress")["site"]["header"]               # a card far below the header


def test_registry_problems_are_named(reg):
    def broken(change, i=0):
        r = copy.deepcopy({k: v for k, v in reg.items() if k != "_path"})
        change(r["features"][i])
        return " | ".join(Q.registry_problems(r))

    assert not Q.registry_problems({k: v for k, v in reg.items() if k != "_path"})
    assert "schema" in " ".join(Q.registry_problems({"schema": "x"}))
    assert "schema" in " ".join(Q.registry_problems({**reg, "schema": "rtv-cartoon-features/1"}))     # the fragment schema
    assert "slot {price} is not read" in broken(lambda f: f["lines"].update(fact_b="{sells} sells at {price}."))
    assert "types a number" in broken(lambda f: f["lines"].update(hook="Congress made 76 buys!", hook_figure="{buys}"))
    assert "types a number" in broken(lambda f: f["lines"].update(confused="Four? Checking RapidTradeView."))
    assert "types a number" in broken(lambda f: f["lines"].update(confused="Hundreds? Checking RapidTradeView."))
    assert "names a data provider" in broken(lambda f: f["lines"].update(fact_a="Congress trades, per Quiver."))
    assert "names a data provider" in broken(lambda f: f["lines"].update(fact_a="Congress trades, says Bloomberg."))
    assert "banned words" in broken(lambda f: f["lines"].update(fact_a="Buy now: Congress trades."))
    assert "not a page of" in broken(lambda f: f.update(url="https://example.com/market"))
    assert "must say our brand" in broken(lambda f: f["lines"].update(confused="And sells? Checking."))
    assert "a feature has one capture, 'page'" in broken(lambda f: f["values"][0].update({"from": "key"}))
    assert "does not name the capture 'page'" in broken(lambda f: f["sources"]["title"].update(capture="fact"))
    assert "no claim" in broken(lambda f: f["claims"].pop("hook"))
    assert "hook_figure must be a slot" in broken(lambda f: f["lines"].update(hook_figure="{sells}"))
    # advice and predictions the phrase list does not hold
    assert "advice or a prediction" in broken(lambda f: f["lines"].update(fact_a="Buy it."))
    assert "advice or a prediction" in broken(lambda f: f["lines"].update(fact_a="It will go up."))
    # a person, a ticker or a number typed into a line or a source
    assert "types the name 'Jane Roe'" in broken(lambda f: f["lines"].update(fact_a="Trades by Jane Roe."))
    assert "types a ticker" in broken(lambda f: f["lines"].update(fact_a="Most traded: TSLA."))
    assert "source title types a number" in broken(lambda f: f["sources"]["title"].update(text="Top 5 Congress trades"))
    # pages that count a guest view or need a sign-in
    assert "never captured" in broken(lambda f: f.update(url=f"{SITE}/dashboard/NVDA"))
    assert "never captured" in broken(lambda f: f.update(url=f"{SITE}/smart-money"))
    assert "never captured" in broken(lambda f: f.update(url=f"{SITE}/portfolio"))
    assert "phone is one of" in broken(lambda f: f.update(phone="swipe"))
    assert "captured at phone width" in broken(lambda f: f.update(viewport="1280x800"))


def test_fragment_layouts_are_refused(reg):
    """Owner verdict 2026-11-10: three of the first four shorts cut the page into fragment cards. The registry no longer
    has a way to ask for one."""
    def broken(change, i=0):
        r = copy.deepcopy({k: v for k, v in reg.items() if k != "_path"})
        change(r["features"][i])
        return " | ".join(Q.registry_problems(r))

    old_key = {"name": "key", "clip_from": "Biggest industry groups", "clip_to": "Chip companies", "dpr": 6, "targets": ["33%"]}
    assert "fragment cards are not allowed" in broken(lambda f: f.update(captures=[old_key]))
    assert "fragment cards are not allowed" in broken(lambda f: f.update(layout="stack"))
    assert "fragment cards are not allowed" in broken(lambda f: f.update(layout="hero"))
    assert "fragment cards are not allowed" in broken(lambda f: f["key"].update(crop=["{sells}"]))
    assert "fragment cards are not allowed" in broken(lambda f: f["key"].update(also={"target": "buys", "at": "word:76"}))
    assert "fragment cards are not allowed" in broken(lambda f: f["key"].update(capture="key", kind="figure"))
    assert "key.targets lists" in broken(lambda f: f["key"].pop("targets"))
    assert "site.strip needs top and bottom" in broken(lambda f: f["site"].pop("strip"))
    assert "site.card.box" in broken(lambda f: f["site"].update(card={}))
    assert "site.parts names at least 2 parts" in broken(lambda f: f["site"].update(parts={"title": ["text:Congress trades"]}))
    assert "is not page | el:CSS" in broken(lambda f: f["site"]["parts"].update(chart=["svg"]))
    assert "no slot in" in broken(lambda f: f["site"]["strip"].update(top="text:{sells}"))
    assert "slot {seats} is not read" in broken(lambda f: f["site"]["parts"].update(title=["text:{seats}"]))
    assert "slot {seats} is not read" in broken(lambda f: f["key"].update(targets=["={seats}"]))


def test_unknown_feature_and_unfilled_slot_are_errors(reg):
    with pytest.raises(Q.FeatureError):
        Q.feature_by_id(reg, "etf-holdings")
    with pytest.raises(Q.FeatureError):
        Q.fill("{count} members", {})
    assert Q.fill("{sells} sells, {buys} buys.", {"sells": "130", "buys": "76"}) == "130 sells, 76 buys."
    assert Q.target_name("=130") == "130" and Q.target_name("=57%#2") == "57%#2" and Q.target_name("buys") == "buys"


# ------------------------------------------------------------------------------------------------- values from the capture
def test_values_are_read_from_the_cards_headline(reg):
    f = Q.feature_by_id(reg, "congress")
    assert Q.feature_values(f, congress()) == {"sells": "130", "sells_word": "sells,", "buys": "76", "buys_word": "buys"}
    assert Q.feature_values(f, congress("1,204", "310"))["sells"] == "1,204"
    f = Q.feature_by_id(reg, "insiders")
    assert Q.feature_values(f, insiders()) == {"bought": "$502M", "bought_word": "bought,", "sold": "$3.6B",
                                               "sold_word": "sold by insiders"}
    f = Q.feature_by_id(reg, "portfolio")
    v = Q.feature_values(f, portfolio())
    assert (v["total"], v["sector"], v["pct"], v["holdings_line"]) == ("$198,819.47", "Technology", "57%", "42 holdings")


def test_missing_region_or_a_story_that_does_not_hold_stops(reg):
    f = Q.feature_by_id(reg, "congress")
    with pytest.raises(Q.FeatureError, match="not more than buys"):
        Q.feature_values(f, congress("40", "76"))               # more buys than sells: "And sells?" has no punchline
    with pytest.raises(Q.FeatureError, match="below 2"):
        Q.feature_values(f, congress("5", "0"))                 # "0 buys": no hook
    with pytest.raises(Q.FeatureError, match="does not match"):
        Q.feature_values(f, congress("130", "1", buys_word="buy"))     # "1 buy": the line "{buys} buys" would be wrong
    m = congress()
    m["page"]["inside_text"] = "Congress trades\nNo stock trades by members of Congress were disclosed from Oct 11 to Nov 9."
    with pytest.raises(Q.FeatureError):
        Q.feature_values(f, m)
    with pytest.raises(Q.FeatureError, match="not more than bought"):
        Q.feature_values(Q.feature_by_id(reg, "insiders"), insiders("$3.6B", "$502M"))
    with pytest.raises(Q.FeatureError, match="not 'Concentrated'"):
        Q.feature_values(Q.feature_by_id(reg, "concentration"), concentration("Balanced"))
    with pytest.raises(Q.FeatureError, match="was not made"):
        Q.feature_values(f, {})


def test_values_come_from_what_is_inside_the_strip_not_what_touches_it(reg):
    m = congress()
    m["page"]["visible_text"] += "\nAll trades →\n$99M"                # the card above only touches the strip's edge
    seal(m["page"])
    assert "$99M" in m["page"]["visible_text"] and "$99M" not in Q.shown_text(m["page"])
    assert Q.shown_text({"visible_text": "old sidecar"}) == "old sidecar"            # no inside_text: the wide text
    f, metas, story = story_for(reg, "congress", m)
    item = Q.feature_item(f, story["feature"]["values"], metas, story["item_id"])
    assert {"130", "76", "28", "24"} <= Q.allowed_set(item) and "$99M" not in Q.allowed_set(item)
    assert not Q.on_capture("All trades", metas["page"])


def test_market_values_follow_the_days_direction_and_name_the_session(reg):
    f = Q.feature_by_id(reg, "market-breadth")
    v = Q.feature_values(f, market("fell"))
    assert v == {"wd": "Mon", "mon": "Nov", "day": "9", "session_line": "Last session (Mon, Nov 9)", "total": "2,494",
                 "verb": "fell", "mid": "of 2,494 stocks fell —", "count": "2,061", "pct": "83%", "weekday": "Monday",
                 "session_date": "2026-11-09"}
    ln = Q.feature_lines(f, v)
    assert ln["hook"] == "83% of stocks fell Monday!" and ln["fact_a"] == "2,061 of 2,494 stocks fell:"
    assert ln["confused"] == "Out of how many? Checking RapidTradeView." and ln["key"] == ["83%"]


def test_market_refuses_a_session_that_is_not_the_last_closed_one(reg):
    f = Q.feature_by_id(reg, "market-breadth")
    with pytest.raises(Q.FeatureError, match="no line matches"):
        Q.feature_values(f, market(label="Live"))
    with pytest.raises(Q.FeatureError, match=r"'Fri, Oct 30'.*'Mon, Nov 9'"):
        Q.feature_values(f, market(label="Last session (Fri, Oct 30)"))
    with pytest.raises(Q.FeatureError, match="last closed session"):                # the right date, the wrong weekday
        Q.feature_values(f, market(label="Last session (Tue, Nov 9)"))
    # captured after Tuesday's close the card must say Tuesday; before it, Monday
    late = "2026-11-10T21:30:00Z"                                                   # 16:30 Eastern
    with pytest.raises(Q.FeatureError, match="'Tue, Nov 10'"):
        Q.feature_values(f, market(at=late))
    assert Q.feature_values(f, market(label="Last session (Tue, Nov 10)", at=late))["weekday"] == "Tuesday"
    # a weekend capture: Friday is the last closed session
    assert Q.feature_values(f, market(label="Last session (Fri, Nov 13)", at="2026-11-15T12:00:00Z"))["weekday"] == "Friday"


def test_last_closed_session_knows_the_clock_change():
    utc = dt.timezone.utc
    assert Q.last_closed_session(dt.datetime(2026, 11, 10, 20, 59, tzinfo=utc)) == dt.date(2026, 11, 9)    # 15:59 EST
    assert Q.last_closed_session(dt.datetime(2026, 11, 10, 21, 0, tzinfo=utc)) == dt.date(2026, 11, 10)    # 16:00 EST
    assert Q.last_closed_session(dt.datetime(2026, 7, 14, 19, 59, tzinfo=utc)) == dt.date(2026, 7, 13)     # 15:59 EDT
    assert Q.last_closed_session(dt.datetime(2026, 7, 14, 20, 0, tzinfo=utc)) == dt.date(2026, 7, 14)      # 16:00 EDT
    assert Q.last_closed_session(dt.datetime(2026, 11, 9, 9, 0, tzinfo=utc)) == dt.date(2026, 11, 6)       # Monday morning


def test_market_refuses_a_page_whose_numbers_do_not_hold(reg):
    f = Q.feature_by_id(reg, "market-breadth")
    with pytest.raises(Q.FeatureError, match="below 1000"):
        Q.feature_values(f, market(count="0", total="0", pct="0%"))
    with pytest.raises(Q.FeatureError, match="below 1000"):
        Q.feature_values(f, market(count="3", total="4", pct="75%"))
    with pytest.raises(Q.FeatureError, match="38% is not 2,061 of 2,494"):
        Q.feature_values(f, market(pct="38%"))
    with pytest.raises(Q.FeatureError, match="below 50"):                           # "12% of stocks rose" is not the headline's side
        Q.feature_values(f, market(count="300", total="2,494", pct="12%"))
    assert Q.feature_values(f, market(count="1,777", total="2,494", pct="71%"))["pct"] == "71%"


def test_verbatim_is_word_for_word():
    meta = {"visible_text": "2,061\nof 2,494 stocks rose —\n83%\n2,061 up"}
    assert Q.on_capture("2,061 of 2,494 stocks rose — 83%", meta)
    assert Q.on_capture("2,061 of 2,494 stocks rose: 83%.", meta)       # punctuation is not a word
    assert not Q.on_capture("2,061 of 2,494 stocks rose — 8.3%", meta)
    assert not Q.on_capture("2,494 of 2,061 stocks rose", meta)
    assert not Q.on_capture("stocks rose 83% 409 down", meta)             # not an unbroken run
    assert Q.page_words("−18.3% (SPY −4.9%)") == ["-18.3%", "SPY", "-4.9%"]
    assert Q.on_capture("130 sells, 76 buys", congress()["page"])         # four text nodes of the headline, one phrase
    assert Q.on_capture("$502M bought, $3.6B sold by insiders", insiders()["page"])


# ------------------------------------------------------------------------------------------------- the capture gate
def test_capture_gate_passes_todays_clean_strips(reg):
    for fid, make in METAS.items():
        ok, det = Q.feature_capture_gate(Q.feature_by_id(reg, fid), make(), NOW)
        assert ok, (fid, det["problems"])


def test_capture_gate_refuses_stale_foreign_broken_or_branded_captures(reg):
    f = Q.feature_by_id(reg, "congress")

    def why(change, now=NOW, resealed=True):
        m = congress()
        change(m)
        if resealed:
            for x in m.values():
                seal(x)
        ok, det = Q.feature_capture_gate(f, m, now)
        assert not ok
        return json.dumps(det["problems"])

    page = lambda fn: (lambda m: fn(m["page"]))            # noqa: E731
    assert "capture it again today" in why(lambda m: None, NOW + dt.timedelta(hours=13))          # yesterday's capture
    assert "capture it again today" in why(page(lambda p: p.update(captured_at="2026-11-10T10:00:00Z")))   # the future
    assert "is not https://www.rapidtradeview.trade/market" in why(page(lambda p: p.update(url=f"{SITE}/smart-money")))
    assert "provider names on screen" in why(page(lambda p: p.update(visible_text=p["visible_text"] + "\nCompany logos by Elbstream")))
    assert "provider names on screen" in why(page(lambda p: p.update(visible_text=p["visible_text"] + "\nREDDIT")))
    assert "error or loading state" in why(page(lambda p: p.update(visible_text="Congress trades\nLoading…")))
    for word in ("No data", "Unable to load", "Service unavailable", "NaN%"):
        assert "error or loading state" in why(page(lambda p, w=word: p.update(visible_text=p["visible_text"] + "\n" + w)))
    assert "the page says" in why(page(lambda p: p.update(page_text="CONGRESS TRADES\nNo stock trades by members of Congress were disclosed from Oct 11 to Nov 9.")))
    assert "the page lacks" in why(page(lambda p: p.update(page_text="MARKET BREADTH")))
    assert "capture missing" in why(lambda m: m.pop("page"))
    # the page the browser ended on is recorded and checked (a redirect to a sign-in page keeps the asked-for url)
    assert "the browser ended on" in why(page(lambda p: p.update(final_url=f"{SITE}/auth/signin")))
    assert "the browser ended on" in why(page(lambda p: p.pop("final_url")))
    assert "has no inside_text" in why(page(lambda p: p.pop("inside_text")))
    # the footer of the page may name a source: only the strip is on screen
    assert "REDDIT BUZZ" in congress()["page"]["page_text"]
    # `require` is matched without case: the page text has CSS upper-casing applied
    assert Q.feature_capture_gate(Q.feature_by_id(reg, "market-breadth"), market(), NOW)[0]


def test_capture_gate_refuses_fragments(reg):
    """The capture is the page at phone width with the card whole in it: a band, a lifted element, a 6x re-crop, a strip
    without the card's box or with a part outside the card is not it."""
    f = Q.feature_by_id(reg, "congress")

    def why(change):
        m = congress()
        change(m["page"])
        seal(m["page"])
        ok, det = Q.feature_capture_gate(f, m, NOW)
        assert not ok
        return json.dumps(det["problems"])

    assert "not a strip of the page" in why(lambda p: p.pop("kind"))                       # a band (--clip-from/--clip-to)
    assert "not a strip of the page" in why(lambda p: p.update(kind="clip"))
    assert "not the page at phone width" in why(lambda p: p.update(dpr=2, png_size=[780, 992]))      # 2x is too coarse
    assert "not the page at phone width" in why(lambda p: p.update(viewport=[430, 932], png_size=[1290, 1488]))
    assert "not the page at phone width" in why(lambda p: p.update(png_size=[780, 780]))             # an element's own box
    assert "no DOM box 'card'" in why(lambda p: p["boxes"].pop("card"))
    assert "no DOM box 'chart'" in why(lambda p: p["boxes"].pop("chart"))
    assert "the box 'chart' is not inside the strip" in why(lambda p: p["boxes"].update(chart=[81, 220.5, 1008, 1984.1]))
    assert "the part 'title' is not inside the card's box" in why(lambda p: p["boxes"].update(card=[36, 200, 1098, 1200]))
    # the three bands of schema /1 are not captures of a feature any more
    m = congress()
    m["key"] = copy.deepcopy(m["page"])
    ok, det = Q.feature_capture_gate(f, m, NOW)
    assert not ok and "'key' is not it" in json.dumps(det["problems"])
    # the portfolio short says its strip starts at our header: the header's brand must be a target
    p = portfolio()
    p["page"]["targets"] = [t for t in p["page"]["targets"] if t["text"] != "RapidTradeView"]
    seal(p["page"])
    ok, det = Q.feature_capture_gate(Q.feature_by_id(reg, "portfolio"), p, NOW)
    assert not ok and "no target for our header's brand" in json.dumps(det["problems"])


def test_dpr_six_at_phone_width_is_still_the_page(reg):
    m = congress()
    m["page"].update(dpr=6, png_size=[2340, 2976])
    m["page"]["boxes"] = {k: [v * 2 for v in b] for k, b in m["page"]["boxes"].items()}
    seal(m["page"])
    assert Q.feature_capture_gate(Q.feature_by_id(reg, "congress"), m, NOW)[0]      # sharper, the same page width


def test_the_market_page_is_the_home_pages_market_section(reg):
    f = Q.feature_by_id(reg, "market-breadth")
    assert f["lands_on"] == LANDS
    m = market()
    assert Q.feature_capture_gate(f, m, NOW)[0]
    for x in m.values():
        seal(dict.update(x, final_url=f"{SITE}/market") or x)       # no redirect happened: not the page we describe
    ok, det = Q.feature_capture_gate(f, m, NOW)
    assert not ok and "the browser ended on" in json.dumps(det["problems"])


def test_an_edited_sidecar_no_longer_matches_its_seal(reg):
    f = Q.feature_by_id(reg, "congress")
    m = congress()
    m["page"]["inside_text"] = m["page"]["inside_text"].replace("130\nsells,", "13\nsells,")
    ok, det = Q.feature_capture_gate(f, m, NOW)
    assert not ok and "seal does not match" in json.dumps(det["problems"])
    m = congress()
    m["page"]["boxes"]["card"] = [36, 20.3, 1098, 600.0]            # the card's box is sealed too
    ok, det = Q.feature_capture_gate(f, m, NOW)
    assert not ok and "seal does not match" in json.dumps(det["problems"])
    spec = importlib.util.spec_from_file_location("gv_cartoon_capture_seal", CART / "capture.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)                                 # capture.py cannot import cartoon_qa: the two must agree
    fresh = congress()["page"]
    assert cap.seal(fresh) == Q.capture_seal(fresh) == fresh["seal"]
    band = {k: v for k, v in fresh.items() if k not in ("boxes", "kind", "strip")}      # a band sidecar (the daily short)
    assert cap.seal(band) == Q.capture_seal(band) != fresh["seal"]


def test_provider_names_are_found_through_lookalikes_and_the_wider_list(reg):
    for name in ("Bloomberg", "Reuters", "Nasdaq", "Morningstar", "TradingView", "Twitter", "Wikipedia", "FRED", "MarketWatch",
                 "WSJ", "Fintel", "WhaleWisdom", "Dataroma", "OpenSecrets", "ProPublica", "Refinitiv", "LSEG", "S&P Global",
                 "Dow Jones", "Reddit", "StockTwits", "Yahoo", "Ya​hoo", "Yаhoo", "Υahoo", "Yahoo­ Finance"):
        assert Q.vendor_hits(f"Source: {name}"), name
    for clean in ("In the S&P 500 it's 39%.", "−18.3% (SPY −4.9%)", "Fred bought stocks", "Congress trades", "Insider trades",
                  "SEC filing", "Form 4", "RapidTradeView", "Market breadth", "9 holdings"):
        assert not Q.vendor_hits(clean), clean
    f = Q.feature_by_id(reg, "congress")
    for name in ("Bloomberg", "Yаhoo", "Ya​hoo"):
        m = congress()
        m["page"]["visible_text"] += "\nData: " + name
        seal(m["page"])
        ok, det = Q.feature_capture_gate(f, m, NOW)
        assert not ok and "provider names on screen" in json.dumps(det["problems"]), name


# ------------------------------------------------------------------------------------------------- the story
@pytest.mark.parametrize("fid", ALL)
def test_story_follows_the_owner_rules_and_the_registry(reg, fid):
    feature, metas, story = story_for(reg, fid)
    shots = story["shots"]
    assert len(shots) == 7 and [s["kind"] for s in shots] == ["HOOK", "CLOSE", "CLOSE", "PAYOFF", "PAYOFF", "CALLBACK", "END"]
    assert "RapidTradeView" in shots[1]["vo"] and shots[-1]["vo"] == "Search RapidTradeView. Not investment advice."
    assert story["item_id"] == f"2026-11-10-feature-{fid}" and "facts_file" not in story
    assert Q.one_idea_gate(shots, 16.0)[0]
    assert not F.check_story(story, feature, metas, NOW)
    assert not F.story_drift(story, feature, metas)
    # every number the script says or draws is on the capture
    item = Q.feature_item(feature, story["feature"]["values"], metas, story["item_id"])
    said = {f"s{i}": s["vo"] for i, s in enumerate(shots) if s.get("vo")}
    said["chip"] = shots[0]["chip"]["text"]
    assert Q.numbers_gate(said, Q.allowed_set(item))[0]
    assert Q.spoken_numbers_gate(story["say"])[0]
    assert story["say"] == Q.feature_say(feature, story["feature"]["values"]) and not any(s.get("say") for s in shots)
    # the phone opens the page by a tap on its real link, it does not type a section name into the ticker search
    phone = shots[2]["els"][0]
    assert phone["mode"] == "tap" and phone["text"] == feature["lines"]["search"] and "rate" not in phone
    # the payoff: ONE screen, the strip, in a site window in both payoff shots; no card, no crop, no second capture
    assert set(story["screens"]) == {"page"}
    for s in shots:
        for e in s.get("els", []):
            assert e["t"] not in ("card", "screen") and "crop" not in e, (fid, e)
    wins = [[e for e in s["els"] if e["t"] == "site"] for s in shots[3:5]]
    assert [len(w) for w in wins] == [1, 1] and not any(e["t"] == "site" for s in shots[:3] + shots[5:] for e in s.get("els", []))
    a, b = wins[0][0], wins[1][0]
    assert {k: a[k] for k in "xywh"} == {k: b[k] for k in "xywh"} and a["name"] == b["name"] == "page"     # one window
    # the window fills the frame's width under the pill and stays above the caption band; the card is 900+ px wide
    card_w = metas["page"]["boxes"]["card"][2] * a["w"] / metas["page"]["png_size"][0]
    assert card_w >= Q.SITE_CARD_MIN_W and a["w"] <= 1080 - 2 * 20
    top, bottom = a["y"] - a["h"] / 2, a["y"] + a["h"] / 2
    assert top >= 333 + 6 and bottom <= F.STAGE_BOTTOM                              # the pill ends at y 333; the rim is 6 px
    for s in shots[3:5]:
        cap, pk = s["caption"], s["peek"]
        assert cap["y"] - 62 > bottom and cap["y"] + 62 <= 1520                     # the caption band: under the window
        assert cap["x"] - cap["max_w"] / 2 > pk["x"] + 0.5 * pk["hu"]               # ... and right of Pip's small head
        assert pk["y"] - 0.5 * pk["hu"] > bottom and pk["hu"] <= 150                # Pip: small, under the window
        assert s["move"] == {"type": "still"}                                       # the page scrolls, the camera does not
    # the window comes in from the side: it crosses neither the pill nor the caption band
    assert a["enter"]["from"][1] == 0 and "enter" not in b
    # the scroll of shot 5 starts where shot 4's ended, and ends where the key is outlined
    assert b["scroll"]["y0"] == a["scroll"]["y1"] and a["scroll"]["y0"] == 0
    # the key is outlined in the second payoff shot, in place, and it is the only outline
    marks = [e["target"] for s in shots for e in s.get("els", []) if e.get("t") == "highlight"]
    assert marks == [shots[4]["key_number"]] and isinstance(marks[0], list)
    assert shots[4].get("lead", 0) >= 0.4 and not shots[4]["join"]       # the page settles on the key before the voice names it
    assert b["scroll"]["at"] + b["scroll"]["dur"] <= shots[4]["lead"]
    assert shots[4]["hold"] <= 1.2                                        # no dead air after the last caption


def test_filled_lines_come_from_the_capture(reg):
    lines = lambda s: [x["vo"] for x in s["shots"] if x.get("vo")][:4]          # noqa: E731
    _f, _m, s = story_for(reg, "congress")
    assert lines(s) == ["Congress made 76 buys!", "And sells? Checking RapidTradeView.", "Congress trades:", "130 sells, 76 buys."]
    assert s["say"]["76"] == "seventy-six" and s["say"]["130"] == "one hundred thirty"
    assert s["shots"][0]["chip"]["text"] == "76" and s["shots"][4]["key_number"] == ["130", "buys"]
    _f, _m, s = story_for(reg, "congress", congress("212", "98"))
    assert s["shots"][0]["vo"] == "Congress made 98 buys!" and s["shots"][4]["vo"] == "212 sells, 98 buys."
    _f, _m, s = story_for(reg, "insiders")
    assert lines(s) == ["Insiders bought $502M!", "And sold? Checking RapidTradeView.", "$502M bought,", "$3.6B sold by insiders."]
    # the hook says dollars; the two lines read off the page do not (the screen shows the $)
    assert s["say"]["$502M!"] == "five hundred two million dollars!" and s["say"]["$502M"] == "five hundred two million"
    assert s["say"]["$3.6B"] == "three point six billion"
    _f, _m, s = story_for(reg, "concentration")
    assert lines(s) == ["Only 9 are chips. I'm diversified!", "Are you? Checking RapidTradeView.",
                        "Portfolio Concentration: Concentrated.", "33% of your money is in 9 chip companies."]
    _f, _m, s = story_for(reg, "portfolio")
    assert lines(s) == ["42 holdings. Spread all over!", "Spread where? Checking RapidTradeView.", "Sample portfolio: 42 holdings.",
                        "Technology is 57% of your money."]
    assert s["shots"][4]["key_number"] == ["Technology", "57%#2"]         # the SECTORS row, not the donut's label
    _f, _m, s = story_for(reg, "market-breadth")
    assert s["shots"][0]["vo"] == "83% of stocks rose Monday!" and s["say"]["2,494"] == "two thousand four hundred ninety-four"


def test_a_story_edited_by_hand_fails(reg):
    feature, metas, story = story_for(reg, "congress")
    assert Q.feature_story_gate(story, feature, metas)[0]

    def problems(change):
        s = copy.deepcopy(story)
        change(s)
        ok, det = Q.feature_story_gate(s, feature, metas)
        assert not ok
        assert F.story_drift(s, feature, metas)                  # the rebuild names it too
        return " | ".join(det["problems"])

    assert "voice lines" in problems(lambda s: s["shots"][0].update(vo="Congress made 99 buys!"))
    assert "story values" in problems(lambda s: s["feature"]["values"].update(buys="99"))
    assert "chips" in problems(lambda s: s["shots"][0]["chip"].update(text="40"))
    assert "the phone shows" in problems(lambda s: s["shots"][2]["els"][0].update(text="TSLA"))
    assert "ticker-like words" in problems(lambda s: s["shots"][2]["els"][0].update(text="TSLA"))
    assert "the phone's mode" in problems(lambda s: s["shots"][2]["els"][0].update(mode="type"))
    assert "key" in problems(lambda s: s["shots"][4].update(key_number=["Technology"]))
    assert "carries claim" in problems(lambda s: s["shots"][0].update(claim="title"))
    assert "no bubble" in problems(lambda s: s["shots"][1].update(bubble={"text": "WOW", "x": 500, "y": 500}))
    # a second outline on another real text of the page is a second claim
    assert "outlines" in problems(lambda s: s["shots"][4]["els"].append({"t": "highlight", "target": ["buys"], "at": 1.0}))
    # the post date is the capture day
    assert "post_date" in problems(lambda s: s.update(post_date="2026-11-20"))
    # the page changed after the story was written: the same story no longer matches the sidecar
    ok, det = Q.feature_story_gate(story, feature, congress("131"))
    assert not ok and "story values" in " ".join(det["problems"])


def test_a_fragment_card_in_a_feature_story_fails(reg):
    """What the first four shorts did: a card cut out of the capture, a crop, a second screen for the key."""
    feature, metas, story = story_for(reg, "congress")

    def problems(change):
        s = copy.deepcopy(story)
        change(s)
        ok, det = Q.feature_story_gate(s, feature, metas)
        assert not ok and F.story_drift(s, feature, metas)
        return " | ".join(det["problems"])

    card = {"t": "card", "name": "page", "x": 540, "y": 900, "w": 760, "crop": [0, 120, 1170, 220]}
    assert "fragment cards ['card']" in problems(lambda s: s["shots"][4]["els"].append(card))
    assert "crops in shots [5]" in problems(lambda s: s["shots"][4]["els"][0].update(crop=[0, 0, 1170, 300]))
    assert "fragment cards ['screen']" in problems(lambda s: s["shots"][3]["els"].append({"t": "screen", "name": "page"}))
    assert "one site window" in problems(lambda s: s["shots"][3]["els"].pop(0))
    assert "one site window" in problems(lambda s: s["shots"][5]["els"].append(dict(s["shots"][4]["els"][0])))
    assert "one screen, 'page'" in problems(lambda s: s["screens"].update(key="screens/key.png"))


def test_the_voice_says_only_what_the_generator_makes_it_say(reg):
    """Review 2026-11-10: the say map was not gated, so a hand-edited story could make the voice say what no caption and no
    page shows, with every text gate green."""
    feature, metas, story = story_for(reg, "congress")

    def problems(change):
        s = copy.deepcopy(story)
        change(s)
        ok, det = Q.feature_story_gate(s, feature, metas)
        assert not ok
        assert F.story_drift(s, feature, metas)
        return " | ".join(det["problems"])

    # (a) a source name, advice and a prediction in the voice; the caption still reads "Oh."
    why = problems(lambda s: s["say"].update({"Oh.": "Oh. Reddit says buy it, it will go up."}))
    assert "the say map is not the generator's" in why and "names a provider" in why and "advice or a prediction" in why
    # (b) the voice says another figure over the headline
    why = problems(lambda s: s["say"].update({"130": "thirty"}))
    assert "the say map is not the generator's" in why and "spoken figures" in why
    # a ticker, spelled out
    assert "ticker-like words" in problems(lambda s: s["say"].update({"buys.": "buys of TSLA."}))
    # number words the value parser does not read
    for words in ("a dozen", "hundreds", "half", "double"):
        why = problems(lambda s, w=words: s["say"].update({"buys!": f"{w} buys!"}))
        assert "spoken figures" in why and "adds a number" in why, words
    # a say map on one shot, and a dropped entry (the engine would read the digits its own way)
    assert "a say map of their own" in problems(lambda s: s["shots"][5].update(say={"Oh.": "Oh. Trust me."}))
    assert "missing ['130']" in problems(lambda s: s["say"].pop("130"))
    # the spoken text the gate reports is what the engine gets
    ok, det = Q.feature_story_gate(story, feature, metas)
    assert ok and det["spoken"].startswith("Congress made seventy-six buys! And sells? Checking Rapid Trade View.")
    assert "one hundred thirty sells, seventy-six buys." in det["spoken"]


def test_spoken_numbers_gate_reads_loose_number_words():
    assert Q.spoken_numbers_gate({"4": "four", "$1.29M": "one point two nine million dollars", "EPS": "E P S"})[0]
    for spoken in ("a dozen socks", "hundreds", "half of them", "double", "two socks"):
        assert not Q.spoken_numbers_gate({"socks": spoken})[0], spoken
    assert Q.find_number_words("Hundreds of members") == ["Hundreds"]
    assert Q.find_number_words("one stock, this quarter") == []


def test_story_drift_names_what_was_changed(reg):
    feature, metas, story = story_for(reg, "portfolio")

    def drift(change):
        s = json.loads(json.dumps(story))
        change(s)
        return " | ".join(F.story_drift(s, feature, metas))

    assert not drift(lambda s: None)
    assert not drift(lambda s: s["shots"][0].update(_runtime="added by the renderer"))        # runtime keys are not the story
    assert "shot 5 differs from the generator's in ['els']" in drift(lambda s: s["shots"][4]["els"][0].update(w=700))
    assert "shot 4 differs from the generator's in ['els']" in drift(lambda s: s["shots"][3]["els"][0]["scroll"].update(y1=900))
    assert "shot 5 differs from the generator's in ['hold']" in drift(lambda s: s["shots"][4].update(hold=4.0))
    assert "shot 5 differs from the generator's in ['caption']" in drift(lambda s: s["shots"][4]["caption"].update(y=900))
    assert "shot 4 differs from the generator's in ['peek']" in drift(lambda s: s["shots"][3]["peek"].update(hu=400, y=900))
    assert "voices differs" in drift(lambda s: s["voices"]["dale"].update(speed=2.0))
    assert "say differs" in drift(lambda s: s["say"].update({"Oh.": "Oh no."}))
    assert "a key the generator does not write: bonus" in drift(lambda s: s.update(bonus=1))
    assert "screens [] are not the captures" in drift(lambda s: s["screens"].pop("page"))
    assert "6 shots" in drift(lambda s: s["shots"].pop(2))


def test_check_story_catches_what_the_renderer_would(reg):
    feature, metas, story = story_for(reg, "portfolio")
    s = copy.deepcopy(story)
    s["shots"][4]["vo"] = "Technology is 75% of your money."
    probs = " | ".join(F.check_story(s, feature, metas, NOW))
    assert "numbers that are not on a capture" in probs and "voice lines" in probs
    assert "capture it again today" in " | ".join(F.check_story(story, feature, metas, NOW + dt.timedelta(days=1)))


def test_feature_item_is_built_from_the_capture(reg):
    feature, metas, story = story_for(reg, "insiders")
    item = Q.feature_item(feature, story["feature"]["values"], metas, story["item_id"])
    assert {"$502M", "$3.6B", "264", "534", "30", "$51.7M"} <= Q.allowed_set(item)
    assert {p["id"] for p in item["phrasings"]} == {"headline"}
    lines = [{"line": s["vo"], "claim": s.get("claim")} for s in story["shots"][:-1] if s.get("vo")]
    ok, det = Q.claim_lines_gate(lines, item, story["post_date"])
    assert ok, det["bad"]
    assert [c["line"] for c in det["needs_human_check"]] == ["Insiders bought $502M!", "And sold? Checking RapidTradeView.",
                                                             "$502M bought,", "$3.6B sold by insiders."]
    assert not Q.claim_lines_gate([{"line": "Insiders bought $9B!", "claim": "headline"}], item, story["post_date"])[0]
    # a source text that is not on the capture stops the item
    f2 = copy.deepcopy(feature)
    f2["sources"]["headline"]["text"] = "{bought} sold, {sold} bought by insiders"
    with pytest.raises(Q.FeatureError, match="is not on the page capture"):
        Q.feature_item(f2, story["feature"]["values"], metas, story["item_id"])


def test_the_market_hook_may_name_the_sessions_weekday_only(reg):
    feature, metas, story = story_for(reg, "market-breadth")
    item = Q.feature_item(feature, story["feature"]["values"], metas, story["item_id"])
    assert item["traded"] == ["2026-11-09"]
    said = {"hook": story["shots"][0]["vo"]}
    assert Q.weekday_gate(said, item, story["post_date"])[0]
    assert not Q.weekday_gate({"hook": "83% of stocks rose Friday!"}, item, story["post_date"])[0]
    lines = [{"line": s["vo"], "claim": s.get("claim")} for s in story["shots"][:-1] if s.get("vo")]
    assert Q.claim_lines_gate(lines, item, story["post_date"])[0]


def test_fact_phrase_is_on_the_capture_and_read_aloud(reg):
    _f, metas, story = story_for(reg, "market-breadth")
    script = " ".join(s["vo"] for s in story["shots"][:-1] if s.get("vo"))
    ok, det = Q.feature_fact_gate(story["fact_phrase"], metas, script)
    assert ok and det["on_captures"] == ["page"]
    assert not Q.feature_fact_gate("2,061 of 2,494 stocks rose — 38%", metas, script)[0]
    assert not Q.feature_fact_gate(story["fact_phrase"], metas, "83% of stocks rose! How many?")[0]
    # a phrase read across the two payoff shots is still one phrase
    _f, metas, story = story_for(reg, "insiders")
    script = " ".join(s["vo"] for s in story["shots"][:-1] if s.get("vo"))
    assert Q.feature_fact_gate(story["fact_phrase"], metas, script)[0]


def test_captures_are_one_day(reg):
    m = congress()
    assert Q.capture_day(m) == "2026-11-10"
    m["other"] = dict(m["page"], captured_at="2026-11-11T00:01:00Z")
    with pytest.raises(Q.FeatureError):
        Q.capture_day(m)


# ------------------------------------------------------------------------------------------------- the site screen's layout
def test_a_card_that_fits_the_stage_is_whole_without_a_scroll(reg):
    for fid in ("market-breadth", "concentration"):
        f, m, _s = story_for(reg, fid)
        L = F.site_layout(f, Q.feature_values(f, m), m["page"])
        sw, sh = m["page"]["png_size"]
        assert L["s0"] == L["s1"] == L["s_key"] == 0 and L["dur"] == 0 and L["back"] == 0 and not L["min4"], fid
        assert sh * L["w"] / sw <= L["h"] <= F.STAGE_BOTTOM - F.STAGE_TOP and L["h"] - sh * L["w"] / sw < 1    # the whole strip
        assert L["card_w"] >= Q.SITE_CARD_MIN_W, (fid, L["card_w"])


def test_a_taller_card_is_scrolled_and_comes_back_to_the_key(reg):
    for fid in ("congress", "insiders"):
        f, m, _s = story_for(reg, fid)
        L = F.site_layout(f, Q.feature_values(f, m), m["page"])
        sw, sh = m["page"]["png_size"]
        vis = L["h"] / L["k"]
        assert L["w"] == F.WIN_W and L["h"] == F.STAGE_BOTTOM - F.STAGE_TOP and 960 <= L["card_w"] <= 1010, fid
        assert L["s0"] == 0 and L["s1"] == pytest.approx(sh - vis, abs=0.1)       # from the strip's top to its end: all of it
        assert L["s_key"] == 0 and L["back"] >= F.BACK_MIN_S                      # back on the card's top: the headline
        assert L["dur"] >= F.SCROLL_MIN_S and L["min4"] == pytest.approx(L["at"] + L["dur"] + F.REST)
    # the page short: from the header down to the end of LARGEST HOLDINGS, then back to SECTORS for the key
    f, m, _s = story_for(reg, "portfolio")
    L = F.site_layout(f, Q.feature_values(f, m), m["page"])
    assert L["at"] == F.TOP_HOLD_HEADER and L["min4"] <= F.SHOT4_MAX + 1e-6
    sectors = next(t["box"] for t in m["page"]["targets"] if t["text"] == "Sectors")
    assert L["s_key"] == pytest.approx(sectors[1] - F.KEY_MARGIN_CSS * 3)         # the window opens on the SECTORS heading
    assert 0 < L["s_key"] < L["s1"]


def test_site_layout_refuses_what_would_not_read(reg):
    f = Q.feature_by_id(reg, "portfolio")
    m = portfolio(row2=(600.0, 1955.0))                 # "57%#2" matched the donut's label, not the row: not one line
    with pytest.raises(M.TemplateError, match="not one line"):
        F.site_layout(f, Q.feature_values(f, m), m["page"])
    f = Q.feature_by_id(reg, "congress")
    m = congress()
    m["page"]["boxes"]["card"] = [300, 20.3, 600, 1446.9]                     # a narrow card (a desktop column)
    with pytest.raises(M.TemplateError, match="px wide on screen"):
        F.site_layout(f, Q.feature_values(f, m), m["page"])
    m = congress()
    m["page"]["targets"][1]["box"] = [505.9, 1600.0, 155.9, 90]               # a key target below the card
    with pytest.raises(M.TemplateError):
        F.site_layout(f, Q.feature_values(f, m), m["page"])
    m = congress()
    m["page"].pop("boxes")
    with pytest.raises(M.TemplateError, match="no card box"):
        F.site_layout(f, Q.feature_values(f, m), m["page"])


# ------------------------------------------------------------------------------------------------- the frame gates
WIN = [20.0, 342.0, 1060.0, 1380.0]


def _samples(n=90, card=(52, 360, 1028, 1646), scroll=0.0, key=None, caps=None, peek=None, moving=False, parts=None):
    """n frames of a standing window; `scroll` shifts the card and its parts up (frame px)."""
    out = []
    for i in range(n):
        dy = scroll(i) if callable(scroll) else scroll
        box = lambda b: [b[0], b[1] - dy, b[2], b[3] - dy]            # noqa: E731
        out.append({"t": 6 + i / 30, "moving": moving, "win": list(WIN), "card": box(card),
                    "parts": {k: box(v) for k, v in (parts or {"title": (92, 407, 442, 449), "headline": (92, 470, 1000, 547),
                                                                   "chart": (92, 556, 1000, 1540)}).items()},
                    "key": box(key) if key else None, "key_h": (key[3] - key[1]) if key else None,
                    "caps": caps or [[330, 1403, 870, 1513]], "peek": peek or [32, 1400, 172, 1540]})
    return out


def test_site_card_whole_gate():
    fit = (52, 350, 1028, 1372)                                    # a card that fits the window
    ok, det = Q.site_card_whole_gate(_samples(card=fit, parts={"title": (92, 400, 442, 440), "chart": (92, 600, 1000, 1300)}), 30)
    assert ok and det["card_fits_the_window"] and det["whole_in_one_frame_s"] == 3.0 and not det["scrolled"]
    # a taller card, scrolled from its top to its end: every row is shown, every part is whole at some time
    tall = (52, 360, 1028, 1646)
    roll = lambda i: min(266.0, max(0.0, (i - 20) * 266 / 45))     # noqa: E731
    ok, det = Q.site_card_whole_gate(_samples(card=tall, scroll=roll), 30)
    assert ok and det["scrolled"] and det["rows_shown"] == [0.0, 1.0] and det["gap_in_rows"] is None
    # the same card, never scrolled: its bottom rows are never on screen (a fragment)
    ok, det = Q.site_card_whole_gate(_samples(card=tall), 30)
    assert not ok and det["rows_shown"][1] < 0.8 and "chart" in det["parts_never_whole"]
    # a jump from the top to the bottom with the middle never shown
    ok, det = Q.site_card_whole_gate(_samples(card=(52, 360, 1028, 3000), scroll=lambda i: 0.0 if i < 45 else 1620.0), 30)
    assert not ok and det["gap_in_rows"]
    # cut at the sides (a push-in past the frame, or a crop narrower than the card)
    ok, det = Q.site_card_whole_gate(_samples(card=(-40, 350, 1120, 1372)), 30)
    assert not ok and det["frames_cut_at_the_sides"] == 90
    # a card that fits but is shown whole for a moment only
    s = _samples(card=fit, n=20) + _samples(card=fit, n=70, scroll=400.0)
    assert not Q.site_card_whole_gate(s, 30)[0]
    # a part that is never whole on screen: a headline strip without its chart
    ok, det = Q.site_card_whole_gate(_samples(card=fit, parts={"title": (92, 400, 442, 440), "chart": (92, 600, 1000, 1500)}), 30)
    assert not ok and det["parts_never_whole"] == ["chart"]
    # frames in which the window is still flying in do not count; no standing frame, no pass
    assert not Q.site_card_whole_gate(_samples(card=fit, moving=True), 30)[0]
    assert not Q.site_card_whole_gate([], 30)[0]


def test_card_width_gate():
    assert Q.card_width_gate(_samples(card=(52, 350, 1028, 1372)), 30)[0]                    # 976 px
    ok, det = Q.card_width_gate(_samples(card=(160, 350, 920, 1372)), 30)                    # 760 px: the old hero card
    assert not ok and det["min_w"] == 760.0
    assert not Q.card_width_gate(_samples(card=(52, 350, 1028, 1372), n=30), 30)[0]          # on screen for 1 s only
    assert not Q.card_width_gate(_samples(card=(-20, 350, 1100, 1372)), 30)[0]               # wider than the frame


def test_no_overlap_gate():
    assert Q.no_overlap_gate(_samples())[0]
    ok, det = Q.no_overlap_gate(_samples(caps=[[160, 1175, 920, 1285]]))                     # the old caption band, on the card
    assert not ok and det["hits"][0]["what"] == "caption"
    ok, det = Q.no_overlap_gate(_samples(peek=[55, 1310, 295, 1550]))                        # the old large peek
    assert not ok and det["hits"][0]["what"] == "pip"
    assert not Q.no_overlap_gate(_samples(moving=True, caps=[[160, 1300, 920, 1400]]))[0]    # also while the window flies in
    assert not Q.no_overlap_gate([])[0]


def test_key_in_place_gate():
    key = (92, 470, 660, 547)
    assert Q.key_in_place_gate(_samples(key=key), 30)[0]
    ok, det = Q.key_in_place_gate(_samples(key=(300, 1420, 700, 1500)), 30)                  # a key card under the window
    assert not ok and det["off_the_card_at_s"]
    assert not Q.key_in_place_gate(_samples(key=key, scroll=300.0), 30)[0]                   # scrolled out of the window
    assert not Q.key_in_place_gate(_samples(key=(92, 470, 300, 500)), 30)[0]                 # 30 px tall: too small
    assert not Q.key_in_place_gate(_samples(key=key, n=30), 30)[0]                           # 1 s only
    assert not Q.key_in_place_gate(_samples(), 30)[0]                                        # never outlined


def test_key_target_gate_figure_visual_and_site():
    def run(h, card_w, n=60, box=(300, 600, 700, 700)):
        return [{"t": i / 30, "h": h, "card_w": card_w, "box": list(box)} for i in range(n)]

    assert Q.key_target_gate(run(90, 700), 30, "figure")[0]
    assert not Q.key_target_gate(run(40, 900), 30, "figure")[0]              # a 40 px figure is too small
    assert Q.key_target_gate(run(42, 880), 30, "visual")[0]                  # a chart label: the chart is big
    assert not Q.key_target_gate(run(36, 880), 30, "visual")[0]              # the first render's 35 px donut label read small
    assert not Q.key_target_gate(run(42, 500), 30, "visual")[0]              # a small chart is not
    assert not Q.key_target_gate(run(90, 700, n=30), 30, "figure")[0]        # 1 s is too short
    assert not Q.key_target_gate(run(90, 700, box=(900, 600, 1070, 700)), 30, "figure")[0]   # under the action rail
    # a site key: a headline of the real card, where it stands; it may run the card's width
    assert Q.key_target_gate(run(56, 976, box=(77, 448, 1005, 548)), 30, "site")[0]
    assert not Q.key_target_gate(run(56, 760, box=(77, 448, 705, 548)), 30, "site")[0]       # on a small card
    assert not Q.key_target_gate(run(30, 976, box=(77, 448, 705, 478)), 30, "site")[0]


# ------------------------------------------------------------------------------------------------- the capture's arguments
def test_capture_args_ask_for_the_whole_card(reg):
    f = Q.feature_by_id(reg, "congress")
    first = F.capture_args(f, None)                               # pass 1: the strip and the card, to read the text
    assert first[:6] == ["--url", HOME, "--viewport", "390x844", "--dpr", "3"]
    assert "--strip-top" in first and "--target" not in first and first.count("--box") == 1
    assert 'card=el:[data-chart="congress"]' in first
    v = Q.feature_values(f, congress("212", "98"))
    args = F.capture_args(f, v)                                   # pass 2: the parts and the targets, slots filled
    pairs = list(zip(args, args[1:]))
    assert ("--target", "=212") in pairs and ("--target", "buys") in pairs
    assert ("--box", "title=text:Congress trades") in pairs and ("--box", 'chart=el:[data-chart="congress"] svg[role="img"]') in pairs
    assert "--clip-from" not in args and "--clip-el" not in args and args[args.index("--dpr") + 1] == "3"    # no band, no 6x
    assert F.has_slots(f["key"]) and not F.has_slots(f["site"]["strip"])
    # the concentration card's box ends at its donut; the portfolio page asks for our header's brand
    f = Q.feature_by_id(reg, "concentration")
    args = F.capture_args(f, Q.feature_values(f, concentration()))
    pairs = list(zip(args, args[1:]))
    assert ("--box-bottom", 'card=el:[aria-label="Portfolio concentration chart"]') in pairs
    assert ("--target", HEADLINE) in pairs and ("--box", "pill=text:=Concentrated") in pairs
    f = Q.feature_by_id(reg, "portfolio")
    assert F.site_targets(f, Q.feature_values(f, portfolio())) == ["=Technology", "=57%#2", "=Sectors", "RapidTradeView"]


def test_capture_spec_parsing():
    spec = importlib.util.spec_from_file_location("gv_cartoon_capture", CART / "capture.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)                                 # playwright is imported inside main(), not here
    assert cap.split_spec("=V") == ("V", "1", True)
    assert cap.split_spec("first buy filing #1") == ("first buy filing ", "1", False)
    assert cap.split_spec("EPS#last") == ("EPS", "last", False)
    assert cap.split_spec("57%#2") == ("57%", "2", False)
    assert cap.split_spec("=57%#2") == ("57%", "2", True)
    assert cap.box_spec("page") == ("page", "") and cap.box_spec("text:=Sectors") == ("text", "=Sectors")
    assert cap.box_spec('el:[data-chart="congress"] h2') == ("el", '[data-chart="congress"] h2')
    assert cap.box_spec('all:[data-chart="insiders"] svg[role="img"]')[0] == "all"
    assert cap.named_spec('card=el:[data-chart="congress"]') == ("card", 'el:[data-chart="congress"]')
    for bad in ("svg", "css:svg", "el:", "Card=el:x", "=el:x"):
        with pytest.raises(ValueError):
            cap.named_spec(bad) if "=" in bad else cap.box_spec(bad)
    for sp in ("page", "el:section", "all:svg", "text:Show all (#2"):
        assert Q.SPEC_RX.fullmatch(sp) and cap.box_spec(sp)       # the registry's check and the capture read the same forms


def test_two_long_numbers_do_not_share_one_caption():
    words = "2,061 of 2,494 stocks rose:".split()
    chunks = [" ".join(words[i] for i in g) for g in Q.chunk_words(words)]
    assert chunks == ["2,061", "of 2,494", "stocks rose:"]       # one caption sat 3.3 s while the voice read both numbers
    words = "4 in Congress bought the same stock!".split()
    assert [" ".join(words[i] for i in g) for g in Q.chunk_words(words)][0] == "4 in Congress"      # not a lone "4"


def test_make_feature_story_exit_codes(tmp_path, capsys):
    assert F.main(["--list"]) == 0
    assert "congress" in capsys.readouterr().out
    assert F.main(["etf-holdings", "--run", str(tmp_path)]) == 2             # not in the registry
    assert F.main(["congress", "--run", str(tmp_path)]) == 2                 # no capture, no --capture: no story
    assert not (tmp_path / "story.json").exists()
    (tmp_path / "screens").mkdir(exist_ok=True)
    (tmp_path / "screens" / "page.json").write_text(json.dumps(congress("40", "76")["page"]), encoding="utf-8")
    (tmp_path / "screens" / "page.png").write_bytes(b"png")                  # more buys than sells: the story does not hold
    assert F.main(["congress", "--run", str(tmp_path)]) == 2
    assert "not more than buys" in capsys.readouterr().err and not (tmp_path / "story.json").exists()


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
    """A run folder as make_feature_story leaves it: story.json + screens/page.png (a real PNG of the strip's size) + its
    sidecar."""
    from PIL import Image
    feature, metas, story = story_for(reg, fid, metas)
    (tmp_path / "screens").mkdir(exist_ok=True)
    for n, m in metas.items():
        Image.new("RGB", tuple(m["png_size"]), (12, 12, 16)).save(tmp_path / "screens" / f"{n}.png")
        (tmp_path / "screens" / f"{n}.json").write_text(json.dumps(m), encoding="utf-8")
    story = json.loads(json.dumps(story))
    if edit:
        edit(story)
    (tmp_path / "story.json").write_text(json.dumps(story), encoding="utf-8")
    return tmp_path / "story.json"


def _fake_tts(monkeypatch, R):
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


def _built(tmp_path, reg, fid, monkeypatch, edit=None):
    R = _reel()
    _fake_tts(monkeypatch, R)
    st = R.Story(_write_run(tmp_path, reg, fid, edit=edit))
    tl = R.Timeline(st, tmp_path / "tts", "unused")
    return R, st, tl, R.Reel(st, tl)


def test_renderer_builds_the_item_from_the_sidecar_not_the_story(reg, tmp_path):
    R = _reel()
    st = R.Story(_write_run(tmp_path, reg, "congress", edit=lambda s: s["feature"]["values"].update(buys="99")))
    assert st.feature["id"] == "congress" and st.item["type"] == "feature"
    assert "76" in Q.allowed_set(st.item) and "99" not in Q.allowed_set(st.item)      # the story's typed 99 is not data
    assert "insider trading" in st.banned
    assert not Q.feature_story_gate(st.doc, st.feature, {n: sc["meta"] for n, sc in st.screens.items()})[0]


def test_renderer_refuses_a_feature_story_whose_page_does_not_carry_it(reg, tmp_path):
    R = _reel()
    with pytest.raises(R.InputError, match="no feature"):
        R.Story(_write_run(tmp_path, reg, "congress", edit=lambda s: s["feature"].update(id="etf-holdings")))
    with pytest.raises(R.InputError, match="capture day"):
        R.Story(_write_run(tmp_path, reg, "congress", edit=lambda s: s.update(item_id="2026-11-09-feature-congress")))
    path = _write_run(tmp_path, reg, "congress")
    side_ = tmp_path / "screens" / "page.json"
    m = json.loads(side_.read_text(encoding="utf-8"))
    m["inside_text"] = m["inside_text"].replace("130\nsells,", "13\nsells,")
    side_.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(R.InputError, match="not more than buys"):
        R.Story(path)


def test_text_gates_fail_a_voice_that_says_what_the_captions_do_not(reg, tmp_path, monkeypatch):
    """The whole path the review used: Story -> Timeline -> Reel -> text_gates, with the two edits of the say map."""
    def gates(name, edit=None):
        run = tmp_path / name
        run.mkdir()
        R, st, tl, reel = _built(run, reg, "congress", monkeypatch, edit)
        return R.text_gates(st, tl, reel, NOW)

    s, d = gates("clean")
    for g in ("feature_story", "feature_capture", "no_provider_names", "no_advice", "banned_words", "numbers_verbatim",
              "spoken_numbers", "claim_lines", "caption_verbatim", "fact_phrase", "screen_numbers", "safe_zones",
              "caption_occlusion", "character_on_screen"):
        assert s[g], (g, d[g])
    assert d["feature_story"]["differs_from_generator"] == []

    s, d = gates("advice", lambda st: st["say"].update({"Oh.": "Oh. Reddit says buy it, it will go up."}))
    assert s["caption_verbatim"]                                  # the caption still reads "Oh."
    assert not s["feature_story"] and "say differs from the generator's" in d["feature_story"]["differs_from_generator"]
    assert not s["no_provider_names"] and d["no_provider_names"]["found"]["spoken"] == ["Reddit"]
    assert not s["no_advice"] and "spoken" in d["no_advice"]["found"]

    s, d = gates("figure", lambda st: st["say"].update({"130": "thirty"}))
    assert not s["feature_story"] and "'130': 'thirty'" in " ".join(d["feature_story"]["problems"])

    s, d = gates("shot-say", lambda st: st["shots"][3].update(say={"trades:": "trades: Sell now."}))
    assert not s["feature_story"] and not s["banned_words"]


def test_lead_and_the_scroll_time_the_payoff_shots(reg, tmp_path, monkeypatch):
    """Shot 5 starts `lead` seconds before its first word (the page settles on the key, then the voice names it); shot 4
    lasts as long as its scroll, however short its line is."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    R, st, with_lead, _reel_a = _built(tmp_path / "a", reg, "insiders", monkeypatch)
    _R, _st, no_lead, _reel_b = _built(tmp_path / "b", reg, "insiders", monkeypatch, edit=lambda s: s["shots"][4].pop("lead"))
    lead = F.LEAD5
    first = lambda tl: min(w.start for w in tl.words if w.shot == 4)          # noqa: E731
    assert with_lead.starts[4] == pytest.approx(no_lead.starts[4], abs=1 / R.FPS)
    assert first(with_lead) - with_lead.starts[4] == pytest.approx(lead + R.LEAD_F / R.FPS, abs=1 / R.FPS)
    assert first(no_lead) - no_lead.starts[4] == pytest.approx(R.LEAD_F / R.FPS, abs=1 / R.FPS)
    assert all(c["start"] >= with_lead.starts[4] + lead - 1 / R.FPS for c in with_lead.chunks if c["shot"] == 4)
    # "$502M bought," is 0.9 s of (fake) voice; the scroll over the card takes longer, and the shot waits for it
    a = st.shots[3]
    assert with_lead.ends[3] - with_lead.starts[3] >= a["min_dur"] - 2 / R.FPS
    assert with_lead.ends[3] - with_lead.starts[3] > 0.9 + 0.5                # longer than the line alone would make it
    assert a["min_dur"] == pytest.approx(a["els"][0]["scroll"]["at"] + a["els"][0]["scroll"]["dur"] + F.REST)


def test_the_window_scrolls_the_strip_and_never_cuts_it(reg, tmp_path, monkeypatch):
    """congress: the window stands on the card's top, scrolls to its end like a thumb, and comes back to the headline,
    which is outlined where it stands. The frame gates pass on the rendered payoff."""
    R, st, tl, reel = _built(tmp_path, reg, "congress", monkeypatch)
    a, b = st.shots[3]["els"][0], st.shots[4]["els"][0]
    sw, sh, res, ch = reel.site_geom(a)
    assert (sw, sh) == (1170, 1488) and res == pytest.approx(1170 / 1040) and ch == round(1038 * res)
    sc = a["scroll"]
    assert reel.site_scroll(a, 0.0) == reel.site_scroll(a, sc["at"]) == 0.0                 # it stands on the card's top
    mid = reel.site_scroll(a, sc["at"] + sc["dur"] / 2)
    assert 0 < mid < sc["y1"] and reel.site_scroll(a, sc["at"] + sc["dur"] + 0.01) == pytest.approx(sc["y1"], abs=0.6)
    assert reel.site_scroll(b, 0.0) == pytest.approx(sc["y1"], abs=0.6) and reel.site_scroll(b, st.shots[4]["lead"]) == 0.0
    assert R.cruise(0) == 0 and R.cruise(1) == 1 and R.cruise(0.5) == pytest.approx(0.5)
    assert max(R.cruise((i + 1) / 100) - R.cruise(i / 100) for i in range(100)) < 1.2 / 100         # no blur: peak 1.18x
    # the sprite is the strip's own rows inside the rim: nothing resized before the camera draws the whole window
    img, anchor, res2 = reel.site_sprite(a, 37.0)
    assert res2 == res and img.size[0] > sw and img.size[1] > ch
    # the key's box follows the scroll: on the card when the page is back on its top
    lead = st.shots[4]["lead"]
    pts, _size = reel._target_world(4, st.shots[4]["key_number"], lead + 0.5)
    assert 342 < pts[:, 1].min() and pts[:, 1].max() < 700 and 20 < pts[:, 0].min() and pts[:, 0].max() < 1060
    pts0, _ = reel._target_world(4, st.shots[4]["key_number"], 0.0)                          # scrolled away: above the window
    assert pts0[:, 1].max() < pts[:, 1].max()
    # render the two payoff shots (every 2nd frame) and gate them
    for si in (3, 4):
        t = tl.starts[si]
        while t < tl.ends[si] - 1e-6:
            reel.shot_frame(si, t, sample=True)
            t += 2 / R.FPS
    fps = R.FPS / 2
    ok, det = Q.site_card_whole_gate(reel.site_samples, fps)
    assert ok and det["scrolled"] and det["rows_shown"] == [0.0, 1.0] and not det["parts_never_whole"], det
    ok, det = Q.card_width_gate(reel.site_samples, fps)
    assert ok and 960 <= det["min_w"] <= det["max_w"] <= 1010, det
    ok, det = Q.no_overlap_gate(reel.site_samples)
    assert ok, det
    ok, det = Q.key_in_place_gate(reel.site_samples, fps)
    assert ok and det["min_h"] >= Q.SITE_KEY_MIN_H, det
    assert Q.pill_clear_gate(reel.pill_samples)[0]                                           # the window keeps under the pill
    ok, det = Q.key_target_gate(reel.key_samples, fps, "site")
    assert ok and det["max_card_w"] >= 960, det
    # the scroll ticks softly and does not shake the camera; the phone taps once
    ticks = [e for e in reel.events if e[1] == "scroll"]
    assert ticks and all(e[2]["shake"] == 0.0 for e in ticks) and reel.shake(ticks[0][0] + 0.01) == (0.0, 0.0, 0.0)
    assert reel.shake(tl.starts[3] + 0.3)[1] != 0.0                # the landing thumps (elsewhere it would shake the camera) ...
    reel.site_samples.clear()
    reel.shot_frame(3, tl.starts[3] + 0.45, sample=True)           # ... but a site screen stands still: pixels untouched
    assert reel.site_samples[0]["win"] == pytest.approx([20, 342, 1060, 1380], abs=0.2)
    taps = [e for e in reel.events if e[1] == "tap"]
    assert len(taps) == 1 and tl.starts[2] < taps[0][0] < tl.ends[2]
    assert "Market" in [x["text"] for x in reel.texts if x["role"] == "prop"]


def test_a_card_that_fits_is_whole_in_every_standing_frame(reg, tmp_path, monkeypatch):
    R, st, tl, reel = _built(tmp_path, reg, "market-breadth", monkeypatch)
    for si in (3, 4):
        t = tl.starts[si]
        while t < tl.ends[si] - 1e-6:
            reel.shot_frame(si, t, sample=True)
            t += 2 / R.FPS
    fps = R.FPS / 2
    ok, det = Q.site_card_whole_gate(reel.site_samples, fps)
    assert ok and det["card_fits_the_window"] and not det["scrolled"], det
    assert det["whole_in_one_frame_s"] == det["standing_s"] > 3.0                # whole, all the time it stands
    assert Q.card_width_gate(reel.site_samples, fps)[0] and Q.no_overlap_gate(reel.site_samples)[0]
    assert Q.key_in_place_gate(reel.site_samples, fps)[0]


def test_our_header_is_readable_on_the_page_short(reg, tmp_path, monkeypatch):
    """portfolio: the strip starts at our page header, and the window stands on it before the scroll (payoff_brand)."""
    R, st, tl, reel = _built(tmp_path, reg, "portfolio", monkeypatch)
    t = tl.starts[3]
    while t < tl.ends[3] - 1e-6:
        reel.shot_frame(3, t, sample=True)
        t += 1 / R.FPS
    ok, det = Q.payoff_brand_gate(reel.brand_samples, R.FPS)
    assert ok and det["readable_s"] >= 1.0 and det["max_h"] >= 40, det
    gone = [s for s in reel.brand_samples if s["t"] > tl.starts[3] + 2.5]
    assert gone and not any(s["inside"] for s in gone)                           # scrolled away: not counted as readable
    s, d = R.text_gates(st, tl, reel, NOW)
    assert s["structure"], d["structure"]                                        # a site shot may run up to 5 s
    assert d["structure"]["payoff_shot_max_s"] == R.PAYOFF_MAX_SITE
