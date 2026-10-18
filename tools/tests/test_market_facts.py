"""Market pillars (tools/market_facts.py, facts.py integration, pin_cards.py) on the real 2026-10-16 session.
Run: python -m pytest tools/tests -q (offline: the fixture is the API's own answers, read 2026-10-18)."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import facts as fx  # noqa: E402
import market_facts as mk  # noqa: E402
import pin_cards as pc  # noqa: E402

FIX = json.loads((TOOLS / "tests" / "fixtures" / "market-2026-10-16.json").read_text(encoding="utf-8"))
M = mk.Market(FIX["pictures"], FIX["flows"])
FRI, SAT, SUN, MON = (dt.date(2026, 10, d) for d in (16, 17, 18, 19))
FAME = {"insiders": [], "members": [], "company_tiers_usd": {"mega": 200e9, "large": 10e9, "mid": 2e9}}


def one(items):
    assert len(items) == 1, items
    return items[0]


# ---------------------------------------------------------------------------
# Computed numbers (PLAN §0, read from the cards and the API on 10-18)

def test_computed_figures_of_the_16th():
    assert M.session == "2026-10-16" and len(M.rows) == 500 and len(M.priced()) == 445
    assert mk.signed_pct(mk.median_move(M)) == "−0.03%"          # the typical company: flat
    assert mk.risers(M) == 221
    assert mk.js_fixed(mk.all_row(M, "5d"), 1) == "-2.7"              # the 500 this week (panels.ts allRow)
    b = mk.basket(M)
    assert mk.signed_pct(b["mean"]) == "−5.04%" and b["excluded"] == []
    lead = mk.lead_sector(M)
    assert lead[0] == "Technology" and mk.usd_text(lead[2]) == "$886B" and mk.signed_pct(lead[1]) == "−2.77%"
    assert mk.about_usd(FIX["pictures"]["totals"]["usd_change_sum"]) == "$1.0T"
    assert mk.breadth_prev_peak(FIX["pictures"]["breadth"]) == ("2026-10-15", 1212)


def test_number_formats():
    assert mk.usd_text(105.544e9) == "$105.5B" and mk.usd_text(885.6e9) == "$886B" and mk.usd_text(1.0065e12) == "$1.01T"
    assert mk.usd_text(649.96e6) == "$650M" and mk.usd_text(10.84e6) == "$10.8M"
    assert mk.pct_forms(-1.2084) == ["−1.21%", "1.21%", "−1.2%", "1.2%"]
    assert mk.pct_forms(2.64)[0] == "+2.64%"
    assert mk.ratio_forms(7.5) == ["7.5×", "7.5x", "7.5"] and mk.ratio_text(12.4) == "12"
    assert mk.norm_ticker("BRK-B") == "BRK.B" and mk.norm_ticker("GOOGL") == "GOOGL"
    assert [mk.tier_of(c) for c in (250e9, 50e9, 5e9, 1e9, 1e8, None)] == ["mega", "large", "mid", "small", "micro", "unknown"]


# ---------------------------------------------------------------------------
# Pillars and their triggers

def test_p1_market_move():
    it = one(mk.market_move(M, SUN)[0])
    assert it["pillar"] == "P1" and it["panel"] == "map" and it["key"] == "market_move:2026-10-16"
    assert it["facts_text"].startswith("The 500 largest US-listed stocks lost about $1.0T on Friday (−1.21%; 445 of 500 "
                                       "priced, 96.6% of market value).")
    assert [m["ticker"] for m in it["movers"]] == ["GOOGL", "MSFT", "NVDA", "AVGO"]
    for n in ("$1.0T", "−1.21%", "1.21%", "$105.5B", "−$105.5B", "−2.47%", "$886B", "+2.64%", "500", "445"):
        assert n in it["allowed_numbers"], n
    assert it["trigger"].startswith("|move| 1.21% >= 0.75%") and it["magnitude"] == pytest.approx(2.4168, abs=1e-3)
    assert "s&p 500" in it["banned_words"] and "crash" in it["banned_words"]
    assert mk.market_move(M, FRI)[0][0]["when"] == "today"


def test_p1_does_not_fire_on_a_quiet_day_or_thin_coverage():
    quiet = json.loads(json.dumps(FIX["pictures"]))
    quiet["totals"]["pct_change"] = -0.5
    items, why = mk.market_move(mk.Market(quiet, None), SUN)
    assert items == [] and "quiet day" in why
    thin = json.loads(json.dumps(FIX["pictures"]))
    thin["totals"]["priced_cap_share"] = 0.93
    items, why = mk.market_move(mk.Market(thin, None), SUN)
    assert items == [] and "priced cap share 0.930 < 0.95" in why
    items, why = mk.market_move(M, dt.date(2026, 10, 21))      # Wednesday: Friday's session is stale
    assert items == [] and "older than the last weekday session" in why


def test_p2_mega_movers():
    items, _ = mk.mega_movers(M, SUN)
    assert [i["ticker"] for i in items] == ["GOOGL", "PANW"]
    g, p = items
    assert g["rank_by_usd"] == 1 and g["tickers"] == ["GOOGL", "MSFT", "NVDA"] and "$105.5B" in g["allowed_numbers"]
    assert p["trigger"].startswith("top-100 name (#42 by cap) |1d| 7.63% >= 4.0%")
    assert "Biggest dollar drops" in p["facts_text"]


def test_p6_sector_rotation_day_and_week():
    items, _ = mk.sector_rotation(M, SUN)
    day, week = items
    assert day["window"] == "day" and day["spread_pp"] == pytest.approx(5.41, abs=0.01)
    assert [b["sector"] for b in week["best"]] == ["Consumer Defensive", "Energy"]
    assert [w["sector"] for w in week["worst"]] == ["Technology", "Industrials"]
    assert "This week: the 500 largest US-listed stocks moved −2.7%" in week["facts_text"]
    assert mk.sector_rotation(M, MON)[0][1]["when"] == "last week"


def test_p7_breadth_divergence_and_basket():
    b = one(mk.breadth_day(M, SUN)[0])
    assert b["signal"] == "divergence" and b["risers_500"] == 221 and b["priced_500"] == 445
    assert "1,631 of 2,497 US stocks" in b["facts_text"] and "+1,212 on Oct 15" in b["facts_text"]
    for n in ("1,631", "2,497", "65%", "−0.03%", "221", "445", "+1,212"):
        assert n in b["allowed_numbers"], n
    k = one(mk.basket_week(M, SUN)[0])
    assert k["mean_5d"] == pytest.approx(-5.0425, abs=1e-3) and k["risers"] == 1
    assert "−5.04%" in k["allowed_numbers"] and "$AAPL +2.03%" in k["facts_text"]


def test_p4_reddit_buzz():
    it = one(mk.reddit_buzz(M, SUN)[0])
    assert it["ticker"] == "NBIS" and it["lead"]["ratio"] == 7.5 and it["lead"]["mentions"] == 45
    assert [o["ticker"] for o in it["others"]] == ["SNDK", "NVDA"]
    assert "7.5×" in it["allowed_numbers"] and "45" in it["allowed_numbers"] and "−12.18%" in it["allowed_numbers"]
    assert it["fell"] == 10 and it["with_close"] == 10


def test_p3_flows_are_weekly_or_when_a_big_name_enters_the_top_5():
    assert mk.congress_flow(M, SUN, None)[0] == [] and mk.insider_flow(M, SUN, None)[0] == []
    c = one(mk.congress_flow(M, MON, None)[0])
    assert c["ticker"] == "HD" and c["leader"]["trades"] == 11 and c["trigger"] == "weekly (Monday facts)"
    for n in ("11", "4", "3", "8", "68", "182"):
        assert n in c["allowed_numbers"], n
    i = one(mk.insider_flow(M, MON, None)[0])
    assert [x["ticker"] for x in i["top_sellers_500"]] == ["DELL", "NVDA", "CRWD"]
    assert "$650M" in i["allowed_numbers"] and "$4.4B" in i["allowed_numbers"] and "$317M" in i["allowed_numbers"]
    assert "filed Sep 18 to Oct 16" in i["facts_text"]                 # the newest disclosure, not today
    before = {"congress_top5": ["DVN", "BSX", "LMT", "GLW", "XYZ"], "insider_sell_top5": ["DELL", "NVDA", "CRWD", "AVGO", "ANET"]}
    c2, why, _ = mk.congress_flow(M, dt.date(2026, 10, 20), before)
    assert one(c2)["trigger"] == "$HD entered the top 5"
    assert mk.insider_flow(M, dt.date(2026, 10, 20), before)[0] == []


def test_p5_week_preview_and_reaction():
    week = FIX["calendar_week_of_2026-10-19"]
    pv = one(mk.earnings_week_preview(M, SUN, week, MON)[0])
    assert pv["tickers"][:3] == ["SPCX", "META", "TSLA"] and pv["reporters_total"] >= 3
    assert mk.earnings_week_preview(M, SAT, week, MON)[0] == []
    rx = one(mk.earnings_reactions(M, SUN, FIX["calendar_week_of_2026-10-12"], FIX["archive_reports"])[0])
    assert rx["ticker"] == "IBKR" and rx["hour"] == "amc" and rx["report_date"] == "2026-10-15"
    assert "−3.88%" in rx["allowed_numbers"]


# ---------------------------------------------------------------------------
# facts.py integration (stub API serving the fixture)

class FixtureApi:
    def __init__(self, extra=None):
        self.requests = 0
        self.base = "stub"
        self.answers = {"/market/pictures": FIX["pictures"], "/market/flows": FIX["flows"],
                        "/earnings?weeks_ahead=0": FIX["calendar_week_of_2026-10-12"],
                        "/earnings?weeks_ahead=1": FIX["calendar_week_of_2026-10-19"],
                        "/earnings/reports/archive": {"reports": FIX["archive_reports"]}, **(extra or {})}

    def get(self, path):
        self.requests += 1
        for k, v in self.answers.items():
            if path.startswith(k):
                return v, None
        return None, f"{path}: HTTP 404"


NOW_SUN = dt.datetime(2026, 10, 18, 18, 0, tzinfo=dt.timezone.utc)


def test_market_items_become_facts_items_with_cards_and_anchors():
    items, left, reasons, errors, state, m = fx.market_items(FixtureApi(), SUN, NOW_SUN, None)
    kinds = sorted({i["type"] for i in items})
    assert kinds == ["basket_week", "breadth_day", "earnings_reaction", "earnings_week_preview", "market_move",
                     "mega_mover", "reddit_buzz", "sector_rotation"]
    assert errors == [] and state["congress_top5"][0] == "HD"
    mm = next(i for i in items if i["type"] == "market_move")
    assert mm["page_url"].startswith("https://www.rapidtradeview.trade/?utm_source={platform}&utm_medium=social")
    assert mm["page_url"].endswith("#map") and mm["media"] == [] and mm["card"]["url"] is None
    assert mm["card"]["live_url"] == "https://www.rapidtradeview.trade/market/card/map"
    assert mm["card"]["file"].startswith("market-map-2026-10-16-")
    maps = {i["card"]["file"] for i in items if i.get("card") and i["card"]["panel"] == "map"}
    assert len(maps) == 1                                   # one pinned file per panel and data
    pv = next(i for i in items if i["type"] == "earnings_week_preview")
    assert pv["media"][0]["url"] == "https://www.rapidtradeview.trade/earnings/opengraph-image" and "card" not in pv


def test_enrich_gates_and_rank_on_the_16th():
    items, *_ , m = fx.market_items(FixtureApi(), SUN, NOW_SUN, None)
    pep = fx.make_item("2026-10-18", "form4_buy", "PEP", "form4:a:PEP", "/smart-money/figures/pohlad", name="Robert C. Pohlad",
                       office="Director at PepsiCo, Inc.", side="buy", amount_top_usd=10.84e6, filed="2026-10-16",
                       figure_slug="pohlad", amount_text="$10.84M", facts_text="x", allowed_numbers=["$10.84M"])
    micro = fx.make_item("2026-10-18", "form4_buy", "FLSC", "form4:b:FLSC", "/smart-money/figures/x", name="A B",
                         office="Director at F", side="buy", amount_top_usd=2e6, filed="2026-10-16", market_cap_usd=80e6,
                         facts_text="y", allowed_numbers=[])
    old = fx.make_item("2026-10-18", "form4_buy", "MSFT", "form4:c:MSFT", "/smart-money/figures/y", name="C D",
                       office="CEO at Microsoft", side="buy", amount_top_usd=2e6, filed="2026-10-14", facts_text="z",
                       allowed_numbers=[])
    allit = items + [pep, micro, old]
    fx.enrich(allit, m)
    assert pep["market_cap_source"] == "market_map" and pep["cap_tier"] == "large" and pep["in_500"] is True
    assert pep["context"]["insiders_30d"] == {"bought": "$650M", "sold": "$4.4B"} and "$650M" in pep["context_numbers"]
    assert len(pep["angles"]) == 3
    kept, gates = fx.apply_gates(allit, SUN, FAME, None)
    assert micro not in kept and old not in kept and gates["small_cap"] == 1 and gates["weekend_replay"] == 1
    ranked = fx.rank_items(kept, SUN, FAME)
    assert ranked[0]["type"] in fx.MARKET_LEVEL
    assert next(i for i in ranked if i is pep)["rank"] == 9.5


def test_cooldowns_from_our_own_posts():
    it = fx.make_item("2026-10-18", "mega_mover", "GOOGL", "mega_mover:2026-10-16:GOOGL", "/", facts_text="g",
                      allowed_numbers=[], media=[])
    posted = [{"platform": p, "ny_date": "2026-10-17", "ticker": "GOOGL", "dedupe_key": "mega_mover:2026-10-16:GOOGL",
               "filer": None, "pillar": "P2"} for p in ("x", "instagram")]
    field, why = fx.cooldown(it, SUN, posted)
    assert why is None and field["same_item_posted_on"] == ["instagram", "x"]
    field, why = fx.cooldown(it, SUN, posted + [dict(posted[0], platform="threads")])
    assert why == "already posted on every platform"
    other = [dict(p, dedupe_key="other") for p in posted] + [dict(posted[0], platform="threads", dedupe_key="other")]
    assert fx.cooldown(it, SUN, other)[1].startswith("$GOOGL posted on every platform")
    er = dict(it, type="earnings_result")
    assert fx.cooldown(er, SUN, other)[1] is None           # earnings results are exempt from the ticker cooldown


def test_limit_small_keeps_one_small_cap_in_the_top_8():
    items = [{"item_id": str(n), "cap_tier": "small" if n in (1, 3) else "large"} for n in range(12)]
    out, moved = fx.limit_small(items)
    assert moved == 1 and [i["item_id"] for i in out[:8]].count("3") == 0 and out[8]["item_id"] == "3"


# ---------------------------------------------------------------------------
# Card pinning (offline)

def test_pin_cards_prepare_and_apply(tmp_path, monkeypatch):
    items, *_ = fx.market_items(FixtureApi(), SUN, NOW_SUN, None)
    facts = {"items": items, "counts": {}, "errors": [], "left_out": {}}
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(facts), encoding="utf-8")
    png = pc.PNG + b"0" * pc.MIN_BYTES
    calls = []

    def fetch(url):
        calls.append(url)
        if "buzz" in url:
            raise ValueError("down")
        return png
    monkeypatch.setattr(pc, "fetch_png", fetch)
    monkeypatch.setattr(pc, "SLEEP", lambda s: None)
    work = tmp_path / "work"
    assert pc.prepare(path, tmp_path, "2026-10-18", work) == 10
    files = (work / "pin-cards-files.txt").read_text(encoding="utf-8").split()
    assert sorted(Path(f).name.split("-")[1] for f in files) == ["breadth", "map", "sectors"]
    assert all(f.startswith("v/2026-10-18/cards/market-") for f in files)
    assert len(calls) == 2 * 3 + 1                            # warm-up + the kept GET per panel; buzz failed at warm-up
    monkeypatch.setattr(pc, "served", lambda url: True)
    assert pc.apply(path, work, 5, True) == 0
    out = json.loads(path.read_text(encoding="utf-8"))
    kinds = {i["type"] for i in out["items"]}
    assert "reddit_buzz" not in kinds and out["left_out"]["card_unpinned"]["dropped"] == 1
    mm = next(i for i in out["items"] if i["type"] == "market_move")
    assert mm["media"][0]["url"] == mm["card"]["url"] and mm["card"]["url"].startswith(
        "https://asafb2k.github.io/rapidtradeview-media/v/2026-10-18/cards/market-map-2026-10-16-")
    # a second pass reuses the pinned file: nothing new to commit, no download
    calls.clear()
    path.write_text(json.dumps(facts), encoding="utf-8")
    monkeypatch.setattr(pc, "fetch_png", lambda url: calls.append(url) or png)
    assert pc.prepare(path, tmp_path, "2026-10-19", work) == 10   # only the buzz card is new now
    assert [Path(f).name.split("-")[1] for f in (work / "pin-cards-files.txt").read_text(encoding="utf-8").split()] == ["buzz"]
