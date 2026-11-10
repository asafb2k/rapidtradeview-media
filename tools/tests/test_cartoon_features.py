"""The cartoon Reel's FEATURE mode (tools/gv/scripts/cartoon/features.json, make_feature_story.py, the feature gates in
cartoon_qa.py): a registry entry + the sidecars of a capture made today -> a one-idea story whose every number and name is
on the capture, and whose voice says nothing the captions do not show. Offline: no capture, no voice, no render.
Run: python -m pytest tools/tests -q"""
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
HEADER = "RapidTradeView\n0\n/\n2\nregister/sign-in"
BRAND_TG = {"text": "RapidTradeView", "box": [144, 36.0, 370.3, 66]}


def seal(m):
    m["seal"] = Q.capture_seal(m)
    return m


def side(url, size, vis, targets, page=None, at=AT, inside=None, final=None):
    """A sidecar as capture.py writes it. `vis` is the wide text (every line touching the band), `inside` what the PNG
    shows (default: the same)."""
    return seal({"url": url, "final_url": final or url, "captured_at": at, "png_size": size, "sha256": "0" * 64,
                 "visible_text": vis, "inside_text": vis if inside is None else inside, "targets": targets,
                 "page_text": page if page is not None else vis})


def congress(count="4", ticker="NVDA", name="NVIDIA Corporation"):
    row = f"{ticker}\n{name}\n−18.3% (SPY −4.9%)\n{count} members buying\n·\n7 buy filings\n·\n7 sell filings\n·"
    last = "\nfirst buy filing Sep 2, 2026"
    url = f"{SITE}/congress-trades"
    page = "Congress stock trades tracker\nMost bought stocks by Congress\n" + row + last + "\nCompany logos by Elbstream"
    return {
        "head": side(url, [1170, 138], HEADER, [BRAND_TG], page),
        "fact": side(url, [1170, 459], "Most bought stocks by Congress\nTicker\nSince first buy filing\n" + row + last,
                     [{"text": "Most bought stocks by Congress", "box": [111, 30.0, 698.2, 63]}], page),
        # the band ends under the count line: the next line only touches it (wide text), it is not in the PNG
        "key": side(url, [2340, 510], "Ticker\nSince first buy filing\n" + row + last,
                    [{"text": ticker, "box": [270, 229.5, 233.7, 114]}, {"text": name, "box": [551.7, 241.5, 636.4, 96]},
                     {"text": f"{count} members buying", "box": [270, 367.5, 594, 96]}], page,
                    inside="Ticker\nSince first buy filing\n" + row),
    }


SAMPLE_PAGE = "READ-ONLY SAMPLE\nSample portfolio\nPortfolio Concentration\nConcentrated\nBIGGEST INDUSTRY GROUPS"
SENTENCE = "Technology is 57% of your money. In the S&P 500 it's 39%."


def sample_head():
    return side(f"{SITE}/sample-portfolio", [1170, 492],
                HEADER + "\nREAD-ONLY SAMPLE\nSample portfolio\n40 stocks + VOO and QQQ. Illustrative share counts, recorded prices.",
                [BRAND_TG, {"text": "READ-ONLY SAMPLE", "box": [99, 308.2, 341.9, 42]},
                 {"text": "Sample portfolio", "box": [99, 383.2, 453.5, 81]}], SAMPLE_PAGE,
                inside=HEADER + "\nREAD-ONLY SAMPLE\nSample portfolio")


def concentration(verdict="Concentrated", flag="high"):
    url = f"{SITE}/sample-portfolio"
    head = f"Portfolio Concentration\n{verdict}\n33% of your money is in 9 chip companies."
    return {
        "head": sample_head(),
        "fact": side(url, [1170, 246], head + "\n" + SENTENCE,                  # the grey sentence only touches the band
                     [{"text": "Portfolio Concentration", "box": [87, 42.0, 485.4, 63]},
                      {"text": verdict, "box": [824.9, 51.0, 228.1, 48]}], SAMPLE_PAGE, inside=head),
        "key": side(url, [2340, 408], f"Biggest industry groups\nChip companies\n9 holdings\n▲\n{flag}\n33%",
                    [{"text": "Biggest industry groups", "box": [174, 54.0, 1116.1, 96]},
                     {"text": "Chip companies", "box": [282, 256.5, 549.9, 102]},
                     {"text": "high", "box": [1594.2, 261.0, 151.8, 96]}, {"text": "33%", "box": [1881.8, 256.5, 152.2, 102]}],
                    SAMPLE_PAGE),
    }


def portfolio(key_size=(1584, 1584)):
    url = f"{SITE}/sample-portfolio"
    return {
        "head": sample_head(),
        "fact": side(url, [1170, 216], f"{SENTENCE}\nInner ring: your\n42 holdings\n· outer ring: their sectors",
                     [{"text": "outer ring: their sectors", "box": [633.3, 158.2, 369.7, 48]}], SAMPLE_PAGE),
        "key": side(url, list(key_size), "57%\n10%\n8.4%\n8.2%\n6.1%\nTOTAL\n$198.8K\n42 holdings",
                    [{"text": "57%", "box": [1383.3, 895.2, 139.2, 90]}, {"text": "TOTAL", "box": [700.2, 612.0, 183.5, 84]}],
                    SAMPLE_PAGE),
    }


def market(verb="rose", label="Last session (Mon, Nov 9)", count="2,061", total="2,494", pct="83%", at=AT):
    url, final = f"{SITE}/market", f"{SITE}/#market"
    page = "MARKET BREADTH\n" + label + "\nREDDIT BUZZ"          # innerText: CSS upper-casing applied
    top = f"Market breadth\n·\n{label}\nShare\n{count}\nof {total} stocks {verb} —\n{pct}\n{count} up\n409 down\n{pct}\n16%"
    return {
        "head": side(url, [1170, 138], HEADER, [BRAND_TG], page, at, final=final),
        "fact": side(url, [1170, 393], top, [{"text": "Market breadth", "box": [81, 36.0, 326.3, 42]}], page, at, final=final),
        "key": side(url, [2340, 2334], top + "\nUp minus down, last 20 closes\n+2,000\n0\n−2,000\nOct 13\nOct 26\n+1,652\nNov 9 (Mon)",
                    [{"text": pct, "box": [1896.8, 303.0, 256.7, 162]}], page, at, final=final),
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
        assert f["phone"] == "tap" and f.get("post_note")       # a page is opened by a tap on its link, never typed
        for k in Q.FEATURE_LINES + ("search",):                 # a line never types a number: numbers are slots
            assert not Q.find_numbers(Q._unslot(f["lines"][k])), (f["id"], k)


def test_registry_problems_are_named(reg):
    def broken(change, i=0):
        r = copy.deepcopy({k: v for k, v in reg.items() if k != "_path"})
        change(r["features"][i])
        return " | ".join(Q.registry_problems(r))

    assert not Q.registry_problems({k: v for k, v in reg.items() if k != "_path"})
    assert "schema" in " ".join(Q.registry_problems({"schema": "x"}))
    assert "slot {price} is not read" in broken(lambda f: f["lines"].update(fact_b="{ticker} at {price}."))
    assert "types a number" in broken(lambda f: f["lines"].update(hook="4 in Congress bought one stock!", hook_figure="{count}"))
    assert "types a number" in broken(lambda f: f["lines"].update(confused="Four? Checking RapidTradeView."))
    assert "types a number" in broken(lambda f: f["lines"].update(confused="Hundreds? Checking RapidTradeView."))
    assert "names a data provider" in broken(lambda f: f["lines"].update(fact_a="Most bought stocks, per Quiver."))
    assert "names a data provider" in broken(lambda f: f["lines"].update(fact_a="Most bought stocks, says Bloomberg."))
    assert "banned words" in broken(lambda f: f["lines"].update(fact_a="Buy now: most bought stocks by Congress."))
    assert "not a page of" in broken(lambda f: f.update(url="https://example.com/congress-trades"))
    assert "must say our brand" in broken(lambda f: f["lines"].update(confused="Which stock? Checking."))
    assert "does not target our brand" in broken(lambda f: f["captures"][0].update(targets=["Congress"]))
    assert "not a capture without slots" in broken(lambda f: f["values"][0].update({"from": "key"}))
    assert "no claim" in broken(lambda f: f["claims"].pop("hook"))
    assert "hook_figure must be a slot" in broken(lambda f: f["lines"].update(hook_figure="{ticker}"))
    # advice and predictions the phrase list does not hold
    assert "advice or a prediction" in broken(lambda f: f["lines"].update(fact_a="Buy it."))
    assert "advice or a prediction" in broken(lambda f: f["lines"].update(fact_a="It will go up."))
    # a person, a ticker or a number typed into a line or a source
    assert "types the name 'Jane Roe'" in broken(lambda f: f["lines"].update(fact_a="Most bought by Jane Roe."))
    assert "types a ticker" in broken(lambda f: f["lines"].update(fact_a="Most bought: TSLA."))
    assert "source heading types a number" in broken(lambda f: f["sources"]["heading"].update(text="Top 5 bought stocks"))
    # pages that count a guest view or need a sign-in
    assert "never captured" in broken(lambda f: f.update(url=f"{SITE}/dashboard/NVDA"))
    assert "never captured" in broken(lambda f: f.update(url=f"{SITE}/smart-money"))
    assert "never captured" in broken(lambda f: f.update(url=f"{SITE}/portfolio"))
    assert "phone is one of" in broken(lambda f: f.update(phone="swipe"))
    assert "key.also needs" in broken(lambda f: f["key"]["also"].update(at=1.0))
    assert "slot {seats} is not read" in broken(lambda f: f["key"]["also"].update(target="{seats}"))


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
    m["fact"]["inside_text"] += "\nMSFT\nMicrosoft Corporation\n+7.4% (SPY −4.0%)\n3 members buying"
    assert Q.feature_values(f, m)["ticker"] == "NVDA"           # a second row changes nothing


def test_missing_region_or_a_story_that_does_not_hold_stops(reg):
    f = Q.feature_by_id(reg, "smart-money")
    with pytest.raises(Q.FeatureError, match="below 2"):
        Q.feature_values(f, congress("1"))                      # "1 members buying" would never be on the page; a 1 breaks the hook
    m = congress()
    m["fact"]["inside_text"] = "Most bought stocks by Congress\nThe Congress tracker is unavailable right now"
    with pytest.raises(Q.FeatureError, match="no line 'Since first buy filing'"):
        Q.feature_values(f, m)
    m = congress()
    m["fact"]["inside_text"] = m["fact"]["inside_text"].replace("NVIDIA Corporation\n", "")     # no company name line
    with pytest.raises(Q.FeatureError):
        Q.feature_values(f, m)
    with pytest.raises(Q.FeatureError, match="not 'Concentrated'"):
        Q.feature_values(Q.feature_by_id(reg, "concentration"), concentration("Balanced"))
    with pytest.raises(Q.FeatureError, match="was not made"):
        Q.feature_values(f, {"head": congress()["head"]})


def test_values_come_from_what_is_inside_the_band_not_what_touches_it(reg):
    m = congress()
    assert "Sep 2, 2026" in m["key"]["visible_text"] and "Sep 2, 2026" not in Q.shown_text(m["key"])
    assert Q.shown_text({"visible_text": "old sidecar"}) == "old sidecar"            # no inside_text: the wide text
    # a number on a line that only touches a band is not an allowed number, and is not "on the capture"
    f, metas, story = story_for(reg, "concentration")
    item = Q.feature_item(f, story["feature"]["values"], metas, story["item_id"])
    assert {"33%", "9"} <= Q.allowed_set(item) and not {"57%", "39%", "500"} & Q.allowed_set(item)
    assert not Q.on_capture("Technology is 57% of your money.", metas["fact"])
    assert not Q.on_capture("40 stocks + VOO and QQQ.", metas["head"])


def test_market_values_follow_the_days_direction_and_name_the_session(reg):
    f = Q.feature_by_id(reg, "market-pictures")
    v = Q.feature_values(f, market("fell"))
    assert v == {"wd": "Mon", "mon": "Nov", "day": "9", "session_line": "Last session (Mon, Nov 9)", "total": "2,494",
                 "verb": "fell", "mid": "of 2,494 stocks fell —", "count": "2,061", "pct": "83%", "weekday": "Monday",
                 "session_date": "2026-11-09"}
    ln = Q.feature_lines(f, v)
    assert ln["hook"] == "83% of stocks fell Monday!" and ln["fact_a"] == "2,061 of 2,494 stocks fell:"
    assert ln["confused"] == "Out of how many? Checking RapidTradeView."


def test_market_refuses_a_session_that_is_not_the_last_closed_one(reg):
    f = Q.feature_by_id(reg, "market-pictures")
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
    f = Q.feature_by_id(reg, "market-pictures")
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


# ------------------------------------------------------------------------------------------------- the capture gate
def test_capture_gate_passes_todays_clean_captures(reg):
    for fid, make in METAS.items():
        ok, det = Q.feature_capture_gate(Q.feature_by_id(reg, fid), make(), NOW)
        assert ok, (fid, det["problems"])


def test_capture_gate_refuses_stale_foreign_broken_or_branded_captures(reg):
    f = Q.feature_by_id(reg, "smart-money")

    def why(change, now=NOW, resealed=True):
        m = congress()
        change(m)
        if resealed:
            for x in m.values():
                seal(x)
        ok, det = Q.feature_capture_gate(f, m, now)
        assert not ok
        return json.dumps(det["problems"])

    assert "capture it again today" in why(lambda m: None, NOW + dt.timedelta(hours=13))          # yesterday's capture
    assert "capture it again today" in why(lambda m: m["key"].update(captured_at="2026-11-10T10:00:00Z"))   # the future
    assert "is not https://www.rapidtradeview.trade/congress-trades" in why(lambda m: m["fact"].update(url=f"{SITE}/smart-money"))
    assert "provider names on screen" in why(lambda m: m["fact"].update(visible_text=m["fact"]["visible_text"] + "\nCompany logos by Elbstream"))
    assert "provider names on screen" in why(lambda m: m["head"].update(visible_text=HEADER + "\nREDDIT"))
    assert "error or loading state" in why(lambda m: m["fact"].update(visible_text="Most bought stocks by Congress\nLoading…"))
    for word in ("No data", "Unable to load", "Service unavailable", "NaN%"):
        assert "error or loading state" in why(lambda m, w=word: m["fact"].update(visible_text=m["fact"]["visible_text"] + "\n" + w))
    assert "the page says" in why(lambda m: m["head"].update(page_text="The Congress tracker is unavailable right now (the filings store did not answer)."))
    assert "the page lacks" in why(lambda m: m["head"].update(page_text="Congress stock trades tracker"))
    assert "capture missing" in why(lambda m: m.pop("key"))
    # the page the browser ended on is recorded and checked (a redirect to a sign-in page keeps the asked-for url)
    assert "the browser ended on" in why(lambda m: m["fact"].update(final_url=f"{SITE}/auth/signin"))
    assert "the browser ended on" in why(lambda m: m["fact"].pop("final_url"))
    assert "has no inside_text" in why(lambda m: m["fact"].pop("inside_text"))
    # a provider in the page's footer, far below the bands, is not on screen
    assert "Elbstream" in congress()["fact"]["page_text"]
    # `require` is matched without case: the page text has CSS upper-casing applied
    assert Q.feature_capture_gate(Q.feature_by_id(reg, "market-pictures"), market(), NOW)[0]


def test_the_market_page_is_the_home_pages_market_section(reg):
    f = Q.feature_by_id(reg, "market-pictures")
    assert f["lands_on"] == f"{SITE}/#market"
    m = market()
    assert Q.feature_capture_gate(f, m, NOW)[0]
    for x in m.values():
        seal(dict.update(x, final_url=f"{SITE}/market") or x)       # no redirect happened: not the page we describe
    ok, det = Q.feature_capture_gate(f, m, NOW)
    assert not ok and "the browser ended on" in json.dumps(det["problems"])


def test_an_edited_sidecar_no_longer_matches_its_seal(reg):
    f = Q.feature_by_id(reg, "smart-money")
    m = congress()
    for k in ("visible_text", "inside_text"):
        m["key"][k] = m["key"][k].replace("4 members buying", "40 members buying")
    m["key"]["targets"][2]["text"] = "40 members buying"
    ok, det = Q.feature_capture_gate(f, m, NOW)
    assert not ok and "seal does not match" in json.dumps(det["problems"])
    spec = importlib.util.spec_from_file_location("gv_cartoon_capture_seal", CART / "capture.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)                                 # capture.py cannot import cartoon_qa: the two must agree
    fresh = congress()["fact"]
    assert cap.seal(fresh) == Q.capture_seal(fresh) == fresh["seal"]


def test_provider_names_are_found_through_lookalikes_and_the_wider_list(reg):
    for name in ("Bloomberg", "Reuters", "Nasdaq", "Morningstar", "TradingView", "Twitter", "Wikipedia", "FRED", "MarketWatch",
                 "WSJ", "Fintel", "WhaleWisdom", "Dataroma", "OpenSecrets", "ProPublica", "Refinitiv", "LSEG", "S&P Global",
                 "Dow Jones", "Reddit", "StockTwits", "Yahoo", "Ya​hoo", "Yаhoo", "Υahoo", "Yahoo­ Finance"):
        assert Q.vendor_hits(f"Source: {name}"), name
    for clean in ("In the S&P 500 it's 39%.", "−18.3% (SPY −4.9%)", "Fred bought stocks", "Most bought stocks by Congress",
                  "SEC filing", "Form 4", "RapidTradeView", "Market breadth", "9 holdings"):
        assert not Q.vendor_hits(clean), clean
    f = Q.feature_by_id(reg, "smart-money")
    for name in ("Bloomberg", "Yаhoo", "Ya​hoo"):
        m = congress()
        m["fact"]["visible_text"] += "\nData: " + name
        seal(m["fact"])
        ok, det = Q.feature_capture_gate(f, m, NOW)
        assert not ok and "provider names on screen" in json.dumps(det["problems"]), name


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
    assert not F.story_drift(story, feature, metas)
    # every number the script says or draws is on a capture
    item = Q.feature_item(feature, story["feature"]["values"], metas, story["item_id"])
    said = {f"s{i}": s["vo"] for i, s in enumerate(shots) if s.get("vo")}
    said["chip"] = shots[0]["chip"]["text"]
    assert Q.numbers_gate(said, Q.allowed_set(item))[0]
    assert Q.spoken_numbers_gate(story["say"])[0]
    assert story["say"] == Q.feature_say(feature, story["feature"]["values"]) and not any(s.get("say") for s in shots)
    # the phone opens the page by a tap on its real link, it does not type a section name into the ticker search
    phone = shots[2]["els"][0]
    assert phone["mode"] == "tap" and phone["text"] == feature["lines"]["search"] and "rate" not in phone
    # the real header card is in the first payoff shot; the key is outlined in the second, and it is the only outline
    assert any(e.get("name") == "head" for e in shots[3]["els"])
    assert [e["target"] for s in shots for e in s.get("els", []) if e.get("t") == "highlight"] == [shots[4]["key_number"]]
    assert shots[4].get("lead", 0) >= 0.4 and not shots[4]["join"]       # the key lands before the voice names it
    assert shots[4]["hold"] <= 1.2                                        # no dead air after the last caption
    # the header leaves sideways: upwards it passed under the brand pill (two logos overlapping)
    head5 = next(e for e in shots[4]["els"] if e.get("name") == "head")
    assert head5["exit"]["to"][1] == 0 and head5["exit"]["to"][0] != 0


def test_filled_lines_come_from_the_capture(reg):
    _f, _m, s = story_for(reg, "smart-money")
    assert [x["vo"] for x in s["shots"] if x.get("vo")][:4] == [
        "4 in Congress bought the same stock!", "Which stock? Checking RapidTradeView.", "Most bought stocks by Congress.",
        "NVDA: 4 members buying."]
    assert s["say"]["NVDA:"] == "N V D A:" and s["say"]["4"] == "four"
    _f, _m, s = story_for(reg, "smart-money", congress("6", "PG", "The Procter & Gamble Company"))
    assert s["shots"][0]["vo"] == "6 in Congress bought the same stock!" and s["shots"][4]["vo"] == "PG: 6 members buying."
    assert s["shots"][0]["chip"]["text"] == "6" and s["shots"][4]["key_number"] == "PG"
    _f, _m, s = story_for(reg, "concentration")
    assert [x["vo"] for x in s["shots"] if x.get("vo")][:4] == [
        "Only 9 are chips. I'm diversified!", "Are you? Checking RapidTradeView.", "33% of your money is in 9 chip companies.",
        "33%: Concentrated."]
    _f, _m, s = story_for(reg, "portfolio")
    assert s["shots"][4]["vo"] == "Technology: 57%."                     # the slice is tied to its sector in the donut frame
    _f, _m, s = story_for(reg, "market-pictures")
    assert s["shots"][0]["vo"] == "83% of stocks rose Monday!" and s["say"]["2,494"] == "two thousand four hundred ninety-four"


def test_the_concentration_key_is_the_real_industry_row(reg):
    """The payoff is a visual from the card (the owner asked for concentration visuals), not the one-word verdict pill: the
    row "Chip companies  9 holdings  ▲ high  33%" of BIGGEST INDUSTRY GROUPS, with 33% outlined."""
    f, m, story = story_for(reg, "concentration")
    s5 = story["shots"][4]
    assert s5["key_number"] == "33%" and f["key"]["kind"] == "visual"
    key = next(e for e in s5["els"] if e.get("name") == "key")
    x0, y0, x1, y1 = key["crop"]
    for t in m["key"]["targets"]:                                # the title, the group, the flag and the share are in the crop
        bx, by, bw, bh = t["box"]
        assert x0 <= bx and bx + bw <= x1 and y0 <= by and by + bh <= y1, t["text"]
    assert s5["move"]["min_px"] is False                         # the row stays whole: no zoom until the figure is 64 px
    assert (key["w"] + 20) * s5["move"]["z"] * (1 + 4 * M.Z5_DRIFT) <= 1080 - 2 * 40 + 1
    # the fact card ends above the grey benchmark sentence (the portfolio short's fact, and three unspoken numbers)
    assert "S&P 500" not in Q.shown_text(m["fact"]) and "57%" not in Q.shown_text(m["fact"])
    # a day the row is not flagged high: the source text is not on the capture, no story
    with pytest.raises(Q.FeatureError, match="is not on the key capture"):
        Q.feature_item(f, story["feature"]["values"], concentration(flag="some"), story["item_id"])


def test_a_story_edited_by_hand_fails(reg):
    feature, metas, story = story_for(reg, "smart-money")
    assert Q.feature_story_gate(story, feature, metas)[0]

    def problems(change):
        s = copy.deepcopy(story)
        change(s)
        ok, det = Q.feature_story_gate(s, feature, metas)
        assert not ok
        assert F.story_drift(s, feature, metas)                  # the rebuild names it too
        return " | ".join(det["problems"])

    assert "voice lines" in problems(lambda s: s["shots"][0].update(vo="9 in Congress bought the same stock!"))
    assert "story values" in problems(lambda s: s["feature"]["values"].update(count="9"))
    assert "chips" in problems(lambda s: s["shots"][0]["chip"].update(text="40"))
    assert "the phone shows" in problems(lambda s: s["shots"][2]["els"][0].update(text="TSLA"))
    assert "ticker-like words" in problems(lambda s: s["shots"][2]["els"][0].update(text="TSLA"))
    assert "the phone's mode" in problems(lambda s: s["shots"][2]["els"][0].update(mode="type"))
    assert "key" in problems(lambda s: s["shots"][4].update(key_number="4 members buying"))
    assert "carries claim" in problems(lambda s: s["shots"][0].update(claim="heading"))
    assert "no bubble" in problems(lambda s: s["shots"][1].update(bubble={"text": "WOW", "x": 500, "y": 500}))
    # a second outline on another real text of the page is a second claim
    assert "outlines" in problems(lambda s: s["shots"][4]["els"].append({"t": "highlight", "target": "4 members buying", "at": 1.0}))
    # the post date is the capture day
    assert "post_date" in problems(lambda s: s.update(post_date="2026-11-20"))
    # the page changed after the story was written: the same story no longer matches the sidecars
    ok, det = Q.feature_story_gate(story, feature, congress("5"))
    assert not ok and "story values" in " ".join(det["problems"])


def test_the_voice_says_only_what_the_generator_makes_it_say(reg):
    """Review 2026-11-10: the say map was not gated, so a hand-edited story could make the voice say what no caption and no
    page shows, with every text gate green."""
    feature, metas, story = story_for(reg, "smart-money")

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
    # (b) the voice names another company over the NVDA row
    why = problems(lambda s: s["say"].update({"NVDA:": "Tesla:"}))
    assert "the say map is not the generator's" in why and "'NVDA:': 'Tesla:'" in why
    # another ticker, spelled out, and a figure with another value
    assert "ticker-like words" in problems(lambda s: s["say"].update({"NVDA:": "TSLA:"}))
    assert "spoken figures" in problems(lambda s: s["say"].update({"4": "forty"}))
    # number words the value parser does not read
    for words in ("a dozen", "hundreds", "half", "double"):
        why = problems(lambda s, w=words: s["say"].update({"stock!": f"{w} stock!"}))
        assert "spoken figures" in why and "adds a number" in why, words
    # a say map on one shot, and a dropped entry (the engine would read the digits its own way)
    assert "a say map of their own" in problems(lambda s: s["shots"][5].update(say={"Oh.": "Oh. Trust me."}))
    assert "missing ['4']" in problems(lambda s: s["say"].pop("4"))
    # the spoken text the gate reports is what the engine gets
    ok, det = Q.feature_story_gate(story, feature, metas)
    assert ok and det["spoken"].startswith("four in Congress bought the same stock! Which stock? Checking Rapid Trade View.")
    assert "N V D A: four members buying." in det["spoken"]


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
    assert "shot 5 differs from the generator's in ['els']" in drift(lambda s: s["shots"][4]["els"][2].update(w=400))
    assert "shot 5 differs from the generator's in ['hold']" in drift(lambda s: s["shots"][4].update(hold=4.0))
    assert "voices differs" in drift(lambda s: s["voices"]["dale"].update(speed=2.0))
    assert "say differs" in drift(lambda s: s["say"].update({"Oh.": "Oh no."}))
    assert "a key the generator does not write: bonus" in drift(lambda s: s.update(bonus=1))
    assert "screens ['head', 'key'] are not the captures" in drift(lambda s: s["screens"].pop("fact"))
    assert "6 shots" in drift(lambda s: s["shots"].pop(2))


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
    assert [c["line"] for c in det["needs_human_check"]] == ["4 in Congress bought the same stock!",
                                                             "Most bought stocks by Congress.", "NVDA: 4 members buying."]
    bad = [{"line": "MSFT: 4 members buying.", "claim": "row"}]
    assert not Q.claim_lines_gate(bad, {**item, "tickers": ["NVDA", "MSFT"]}, story["post_date"])[0]
    # a source text that is not on its capture stops the item
    f2 = copy.deepcopy(feature)
    f2["sources"]["heading"]["text"] = "Most sold stocks by Congress"
    with pytest.raises(Q.FeatureError, match="is not on the fact capture"):
        Q.feature_item(f2, story["feature"]["values"], metas, story["item_id"])


def test_the_market_hook_may_name_the_sessions_weekday_only(reg):
    feature, metas, story = story_for(reg, "market-pictures")
    item = Q.feature_item(feature, story["feature"]["values"], metas, story["item_id"])
    assert item["traded"] == ["2026-11-09"]
    said = {"hook": story["shots"][0]["vo"]}
    assert Q.weekday_gate(said, item, story["post_date"])[0]
    assert not Q.weekday_gate({"hook": "83% of stocks rose Friday!"}, item, story["post_date"])[0]
    lines = [{"line": s["vo"], "claim": s.get("claim")} for s in story["shots"][:-1] if s.get("vo")]
    assert Q.claim_lines_gate(lines, item, story["post_date"])[0]


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
    for fid in ("smart-money", "concentration"):
        _f, _m, story = story_for(reg, fid)
        s5 = story["shots"][4]
        cards = [e for e in s5["els"] if e.get("t") == "card"]
        widest = max(e["w"] for e in cards)
        assert (widest + 20) * s5["move"]["z"] * (1 + 4 * M.Z5_DRIFT) <= 1080 - 2 * 40 + 1, fid
        for key in (e for e in cards if e.get("name") == "key"):
            x0, y0, x1, y1 = key["crop"]
            assert 0 <= x0 < x1 <= _m["key"]["png_size"][0] and 0 <= y0 < y1 <= _m["key"]["png_size"][1]
        # the stack (fact card down to the last key card) fits the stage at the zoom, drift included
        fact = next(e for e in cards if e.get("name") == "fact")
        top = fact["y"] - (_m["fact"]["png_size"][1] * fact["w"] / _m["fact"]["png_size"][0] + 20) / 2
        last = cards[-1]
        bottom = last["y"] + ((last["crop"][3] - last["crop"][1]) * last["w"] / (last["crop"][2] - last["crop"][0]) + 20) / 2
        assert (bottom - top) * s5["move"]["z"] * (1 + 4 * M.Z5_DRIFT) <= M.STAGE_BOTTOM - M.STAGE_TOP + 1, fid


def test_key_crop_spans_ticker_and_name_and_the_count_lands_as_its_own_card(reg):
    _f, m, story = story_for(reg, "smart-money")
    s5 = story["shots"][4]
    key, also = [e for e in s5["els"] if e.get("name") == "key"]
    x0, y0, x1, y1 = key["crop"]
    assert key["main"] and x0 < 270 and x1 > 551.7 + 636.4       # NVDA ... NVIDIA Corporation
    assert y1 < 367.5                                            # the count line below stays out of this crop
    # "4 members buying": a second plain crop of the same capture, landing on the word "4" (the hook's number, big)
    x0, y0, x1, y1 = also["crop"]
    assert not also["main"] and x0 < 270 and 270 + 594 < x1 < 270 + 594 + 30 and y0 > 229.5 + 114 and y1 <= 510
    assert also["enter"]["at"] == "word:4" and also["y"] > key["y"]
    assert s5["key_number"] == "NVDA"                            # one key, one outline


def test_hero_layout_fills_the_stage_and_stays_inside_it(reg):
    for fid, min_w in (("portfolio", 700), ("market-pictures", 700)):
        _f, m, story = story_for(reg, fid)
        s5 = story["shots"][4]
        hero = next(e for e in s5["els"] if e.get("name") == "key")
        kw, kh = m["key"]["png_size"]
        assert hero["w"] >= min_w and "crop" not in hero, fid
        h = kh * hero["w"] / kw + 20
        f = 1 + F.HERO_DRIFT * F.HERO_SHOT_S
        assert 960 - (960 - (hero["y"] - h / 2)) * f >= M.STAGE_TOP - 1          # below the brand pill after the drift
        assert 960 + (hero["y"] + h / 2 - 960) * f <= M.STAGE_BOTTOM + 1         # above the caption band
        assert s5["move"]["z"] == 1.0 and s5["move"]["min_px"] is False
        assert all(e["exit"]["to"][1] == 0 for e in s5["els"] if e.get("name") in ("head", "fact"))     # both leave sideways
        label_h = next(t for t in m["key"]["targets"] if t["text"] == s5["key_number"])["box"][3] * hero["w"] / kw
        assert label_h >= Q.KEY_VISUAL_MIN_H, (fid, label_h)                     # the outlined label, at landing
    with pytest.raises(M.TemplateError, match="too small"):                      # a tall band: the chart would be a thumbnail
        story_for(reg, "portfolio", portfolio(key_size=(1584, 5200)))


def test_key_target_gate_figure_and_visual():
    def run(h, card_w, n=60, box=(300, 600, 700, 700)):
        return [{"t": i / 30, "h": h, "card_w": card_w, "box": list(box)} for i in range(n)]

    assert Q.key_target_gate(run(90, 700), 30, "figure")[0]
    assert not Q.key_target_gate(run(40, 900), 30, "figure")[0]              # a 40 px figure is too small
    assert Q.key_target_gate(run(42, 880), 30, "visual")[0]                  # a chart label: the chart is big
    assert not Q.key_target_gate(run(36, 880), 30, "visual")[0]              # the first render's 35 px donut label read small
    assert not Q.key_target_gate(run(42, 500), 30, "visual")[0]              # a small chart is not
    assert not Q.key_target_gate(run(90, 700, n=30), 30, "figure")[0]        # 1 s is too short
    assert not Q.key_target_gate(run(90, 700, box=(900, 600, 1070, 700)), 30, "figure")[0]   # under the action rail


def test_capture_specs_fill_slots_and_keep_whole_node_marks(reg):
    f = Q.feature_by_id(reg, "smart-money")
    v = Q.feature_values(f, congress("14", "V", "Visa Inc."))
    key = next(F.filled(c, v) for c in f["captures"] if c["name"] == "key")
    assert key["clip_to"] == "14 members buying" and key["targets"] == ["=V", "=Visa Inc.", "14 members buying"]
    assert [c["name"] for c in f["captures"] if not F.has_slots(c)] == ["head", "fact"]
    # a chart is captured as its own element, not as a full-width band with the page margins beside it
    donut = next(c for c in Q.feature_by_id(reg, "portfolio")["captures"] if c["name"] == "key")
    assert donut["clip_el"] and "clip_from" not in donut and F.has_slots(donut)
    # the market card's band ends at the chart's last axis label, which carries the session read from the card
    f = Q.feature_by_id(reg, "market-pictures")
    key = next(F.filled(c, Q.feature_values(f, market())) for c in f["captures"] if c["name"] == "key")
    assert key["clip_to"] == "Nov 9 (Mon)"


def test_capture_spec_parsing():
    spec = importlib.util.spec_from_file_location("gv_cartoon_capture", CART / "capture.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)                                 # playwright is imported inside main(), not here
    assert cap.split_spec("=V") == ("V", "1", True)
    assert cap.split_spec("first buy filing #1") == ("first buy filing ", "1", False)
    assert cap.split_spec("EPS#last") == ("EPS", "last", False)
    assert cap.split_spec("57%#2") == ("57%", "2", False)
    assert cap.split_spec("=57%#2") == ("57%", "2", True)


def test_two_long_numbers_do_not_share_one_caption():
    words = "2,061 of 2,494 stocks rose:".split()
    chunks = [" ".join(words[i] for i in g) for g in Q.chunk_words(words)]
    assert chunks == ["2,061", "of 2,494", "stocks rose:"]       # one caption sat 3.3 s while the voice read both numbers
    words = "4 in Congress bought the same stock!".split()
    assert [" ".join(words[i] for i in g) for g in Q.chunk_words(words)][0] == "4 in Congress"      # not a lone "4"


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


def _write_run(tmp_path, reg, fid, metas=None, edit=None, scale=10):
    """A run folder as make_feature_story leaves it: story.json + screens/<name>.png + sidecars (tiny real PNGs; scale=1
    for a test that draws the cards: their crops are in the capture's own pixels)."""
    from PIL import Image
    feature, metas, story = story_for(reg, fid, metas)
    (tmp_path / "screens").mkdir(exist_ok=True)
    for n, m in metas.items():
        png = tmp_path / "screens" / f"{n}.png"
        Image.new("RGB", (m["png_size"][0] // scale, m["png_size"][1] // scale), (12, 12, 16)).save(png)
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
    m["inside_text"] = m["inside_text"].replace("4 members buying", "1 members buying")
    side_.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(R.InputError, match="below 2"):
        R.Story(path)


def test_text_gates_fail_a_voice_that_says_what_the_captions_do_not(reg, tmp_path, monkeypatch):
    """The whole path the review used: Story -> Timeline -> Reel -> text_gates, with the two edits of the say map."""
    R = _reel()
    _fake_tts(monkeypatch, R)

    def gates(name, edit=None):
        run = tmp_path / name
        run.mkdir()
        st = R.Story(_write_run(run, reg, "smart-money", edit=edit, scale=1))
        tl = R.Timeline(st, run / "tts", "unused")
        return R.text_gates(st, tl, R.Reel(st, tl), NOW)

    s, d = gates("clean")
    for g in ("feature_story", "feature_capture", "no_provider_names", "no_advice", "banned_words", "numbers_verbatim",
              "spoken_numbers", "claim_lines", "caption_verbatim", "fact_phrase", "screen_numbers"):
        assert s[g], (g, d[g])
    assert d["feature_story"]["differs_from_generator"] == []

    s, d = gates("advice", lambda st: st["say"].update({"Oh.": "Oh. Reddit says buy it, it will go up."}))
    assert s["caption_verbatim"]                                  # the caption still reads "Oh."
    assert not s["feature_story"] and "say differs from the generator's" in d["feature_story"]["differs_from_generator"]
    assert not s["no_provider_names"] and d["no_provider_names"]["found"]["spoken"] == ["Reddit"]
    assert not s["no_advice"] and "spoken" in d["no_advice"]["found"]

    s, d = gates("tesla", lambda st: st["say"].update({"NVDA:": "Tesla:"}))
    assert not s["feature_story"] and "'NVDA:': 'Tesla:'" in " ".join(d["feature_story"]["problems"])

    s, d = gates("shot-say", lambda st: st["shots"][3].update(say={"Congress.": "Congress. Sell now."}))
    assert not s["feature_story"] and not s["banned_words"]


def test_lead_puts_the_key_on_screen_before_its_line(reg, tmp_path, monkeypatch):
    """Shot 5 starts `lead` seconds before its first word (the key lands, the camera settles, then the voice names it)."""
    R = _reel()
    _fake_tts(monkeypatch, R)
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


def test_the_second_key_card_waits_for_its_word(reg, tmp_path, monkeypatch):
    """smart-money: "4 members buying" lands on the word "4": hidden (and not counted against the pill) before it."""
    R = _reel()
    _fake_tts(monkeypatch, R)
    st = R.Story(_write_run(tmp_path, reg, "smart-money"))
    tl = R.Timeline(st, tmp_path / "tts", "unused")
    reel = R.Reel(st, tl)
    also = [e for e in st.shots[4]["els"] if e.get("name") == "key"][1]
    at = reel.enter_at(4, also)
    word = next(w for w in tl.words if w.shot == 4 and w.text == "4")
    assert at == pytest.approx(word.start - tl.starts[4], abs=1e-6) and at > F.LEAD5
    assert reel.el_pose(4, also, at - 0.1)[3] == 0.0 and reel.el_moving(4, also, at - 0.1)       # not drawn yet
    assert reel.el_pose(4, also, at + 0.6)[3] == 1.0 and not reel.el_moving(4, also, at + 0.6)
    assert reel.el_pose(4, also, at + 0.6)[0] == (also["x"], also["y"])                          # landed where planned
    # the phone taps once (one clack), it does not type
    taps = [e for e in reel.events if e[1] == "tap"]
    assert len(taps) == 1 and tl.starts[2] < taps[0][0] < tl.ends[2]
    assert "Congress trades tracker" in [x["text"] for x in reel.texts if x["role"] == "prop"]
    assert "Search" not in [x["text"] for x in reel.texts if x["role"] == "prop"]
