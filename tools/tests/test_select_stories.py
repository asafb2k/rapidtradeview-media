"""Story selection rules. Run: python -m pytest tools/tests -q (no network: a stub API)."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import select_stories as ss  # noqa: E402

D = dt.date


class StubApi:
    def __init__(self, answers):
        self.answers = answers
        self.base = "stub"
        self.requests = 0

    def get(self, path):
        self.requests += 1
        for prefix, data in self.answers.items():
            if path.startswith(prefix):
                return (data, None) if data is not None else (None, f"{path}: HTTP 503")
        return None, f"{path}: HTTP 404"


@pytest.mark.parametrize("filed,target,age", [
    (D(2026, 9, 25), D(2026, 9, 28), 1),   # Fri -> Mon
    (D(2026, 9, 23), D(2026, 9, 28), 3),   # Wed -> Mon
    (D(2026, 9, 22), D(2026, 9, 28), 4),   # Tue -> Mon: out of the 3-weekday window
    (D(2026, 9, 28), D(2026, 9, 28), 0),
    (D(2026, 9, 25), D(2026, 9, 27), 0),   # Fri -> Sun
])
def test_weekday_age(filed, target, age):
    assert ss.weekday_age(filed, target) == age


@pytest.mark.parametrize("name,slug", [
    ("Dara Khosrowshahi", "khosrowshahi"),
    ("Berkshire Hathaway Inc", "berkshire-hathaway"),
    ("Lewis H. Titterton Jr.", "titterton"),
    ("Durable Capital Partners Lp", "durable-capital"),
])
def test_name_slug(name, slug):
    assert ss.name_slug(name) == slug


def test_fame_matches_formal_names():
    fame = json.loads((TOOLS / "fame.json").read_text(encoding="utf-8"))
    assert ss.matches_any("Warren E. Buffett", fame["insiders"])
    assert ss.matches_any("William H. Gates III", fame["insiders"])
    assert ss.matches_any("Berkshire Hathaway Inc", fame["insiders"])
    assert ss.matches_any("Nancy Pelosi", fame["members"])
    assert not ss.matches_any("Lewis H. Titterton Jr.", fame["insiders"])


def test_novelty():
    prior = [ss.Posted(D(2026, 9, 27), "form4:0001184237-26-000008:UBER", ["UBER"], ["Dara Khosrowshahi"])]
    assert ss.novelty("form4:0001184237-26-000008:UBER", ["UBER"], ["Dara Khosrowshahi"], D(2026, 9, 28), prior)[0] == 0.0
    assert ss.novelty("form4:other:UBER", ["UBER"], ["Dara Khosrowshahi"], D(2026, 9, 28), prior)[0] == 0.0
    assert ss.novelty("form4:x:UBER", ["UBER"], ["Someone Else"], D(2026, 9, 28), prior)[0] == 0.5
    assert ss.novelty("form4:y:LEN", ["LEN"], ["Berkshire Hathaway Inc"], D(2026, 9, 28), prior)[0] == 1.0


def test_pick_distinct_skips_same_person_and_ticker():
    t = lambda name, ticker, score: ss.Trade("insider", name, name.lower(), ticker, "buy", D(2026, 9, 25), score=score)  # noqa: E731
    ranked = [t("A B", "AAA", 0.9), t("A B", "BBB", 0.8), t("C D", "AAA", 0.7), t("E F", "CCC", 0.6), t("G H", "DDD", 0.0)]
    assert [x.ticker for x in ss.pick_distinct(ranked, 3)] == ["AAA", "CCC"]


def daily(valid_until="2026-09-28T17:30:00+00:00", tips=None):
    return {"trade_date": "2026-09-25", "status": "ready", "valid_until": valid_until, "publish_time_et": "1:30 PM ET",
            "tips": tips if tips is not None else [{"ticker": "", "rank": 1, "locked": True},
                                                   {"ticker": "HBM", "direction": "bullish", "signal_labels": [{"label": "Near support"}]}]}


def test_picks_never_name_the_locked_first_pick():
    s = ss.picks_slot(StubApi({"/tips/daily": daily()}), D(2026, 9, 28), "12:45")
    assert [p["ticker"] for p in s["story"]["picks"]] == ["HBM"]
    assert "before today's list" in s["story"]["note"]


def test_picks_expired_before_the_slot_is_empty():
    s = ss.picks_slot(StubApi({"/tips/daily": daily()}), D(2026, 9, 29), "12:45")
    assert "empty" in s and "expires" in s["empty"]


def test_picks_only_locked_is_empty():
    s = ss.picks_slot(StubApi({"/tips/daily": daily(tips=[{"ticker": "", "rank": 1, "locked": True}])}), D(2026, 9, 28), "12:45")
    assert "no public picks" in s["empty"]


def week(rows):
    return [{"week_start": "2026-09-28", "week_end": "2026-10-02",
             "days": [{"date": f"2026-09-{d}" if d < 31 else f"2026-10-0{d - 30}", "count": 1,
                       "reports": [r for r in rows if r["date"] == (f"2026-09-{d}" if d < 31 else f"2026-10-0{d - 30}")]}
                      for d in (28, 29, 30, 31, 32)]}]


def test_earnings_keeps_only_confirmed_large_companies():
    rows = [
        {"symbol": "MU", "date": "2026-09-30", "hour": "amc", "date_confirmed": True, "in_universe": True, "market_cap": 1.2e12},
        {"symbol": "CAG", "date": "2026-09-29", "hour": None, "date_confirmed": False, "in_universe": True, "market_cap": 7e9},
        {"symbol": "JEF", "date": "2026-09-30", "hour": None, "date_confirmed": False, "in_universe": True, "market_cap": 9.4e10},
        {"symbol": "TINY", "date": "2026-09-28", "hour": "bmo", "date_confirmed": True, "in_universe": True, "market_cap": 1e8},
    ]
    s = ss.earnings_slot(StubApi({}), D(2026, 9, 28), week(rows), {"MU": "Micron Technology, Inc."}, "week")
    assert [c["symbol"] for c in s["story"]["companies"]] == ["MU"]
    today = ss.earnings_slot(StubApi({}), D(2026, 9, 28), week(rows), {}, "today")
    assert "no confirmed-date reporter" in today["empty"]


def feed_item(tid, name, slug, ticker, filed, value, role=None, acc="000000000026000001"):
    return {"trade_id": tid, "figure": {"kind": "insider", "display_name": name, "slug": slug, "title": role, "role": "officer"},
            "ticker": ticker, "side": "buy", "trading_plan": {"status": "not_marked"}, "owner": "self",
            "transaction_date": filed, "disclosure_date": filed,
            "amount": {"value_usd": value, "shares": 1000.0, "price": 1.0, "value_flag": None},
            "source_url": f"https://www.sec.gov/Archives/edgar/data/1/{acc}/index.json"}


def test_weak_recent_trades_give_way_to_the_famous_backlog():
    fame = json.loads((TOOLS / "fame.json").read_text(encoding="utf-8"))
    items = [
        feed_item(1, "Joe Small", "small-joe-1", "AAA", "2026-09-25", 1_500_000, "Director", "000000000026000001"),
        feed_item(2, "Ryan Cohen", "cohen-ryan-1", "GME", "2026-09-10", 20_000_000, "President, CEO and Chairman", "000092189526002531"),
        feed_item(3, "Dara Khosrowshahi", "khosrowshahi-dara-1", "UBER", "2026-09-10", 10_000_000, "Chief Executive Officer", "000118423726000008"),
        feed_item(4, "Old Famous", "old-1", "OLD", "2026-08-20", 50_000_000, "CEO", "000000000026000009"),
    ]
    api = StubApi({
        "/notable/feed?tab=insiders": {"items": items, "has_more": False},
        "/notable/feed?tab=congress": {"items": [], "has_more": False},
        "/snapshot/AAA": {"company_name": "Small Co", "profile": {"stats": {"market_cap": 1e9}}},
        "/snapshot/GME": {"company_name": "GameStop", "profile": {"stats": {"market_cap": 1.2e10}}},
        "/snapshot/UBER": {"company_name": "Uber", "profile": {"stats": {"market_cap": 1.5e11}}},
        "/snapshot/OLD": {"company_name": "Old", "profile": {"stats": {"market_cap": 1e9}}},
    })
    names = {"AAA": "Small Co", "GME": "GameStop", "UBER": "Uber", "OLD": "Old"}
    prior = [ss.Posted(D(2026, 9, 27), "form4:0001184237-26-000008:UBER", ["UBER"], ["Dara Khosrowshahi"])]
    chosen, ranked, backlog, _, errors = ss.choose_trades(api, D(2026, 9, 28), 3, names, fame, prior, 3)
    assert errors == []
    assert [t.ticker for t in ranked] == ["AAA"] and ranked[0].score < ss.MIN_TRADE_SCORE
    assert [(t.ticker, t.source) for t in chosen] == [("GME", "backlog")]  # UBER already posted, OLD past 30 days, AAA too weak
    story = ss.trade_story(chosen[0])
    assert story["selected_from"] == "backlog" and "never call this the total" in story["amount"]["note"]


def ptr_item(tid, name, slug, ticker, filed, low, high, pdf="20035326"):
    return {"trade_id": tid, "figure": {"kind": "politician", "display_name": name, "slug": slug, "party": "Republican",
                                        "chamber": "house", "state": "FL"},
            "ticker": ticker, "side": "sell", "disclosure_date": filed, "transaction_date": "2026-08-11", "owner": "spouse",
            "amount": {"low": low, "high": high},
            "source_url": f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/{pdf}.pdf"}


def test_congress_minimum_binds_famous_members_too():
    """A famous member's $1K-$15K trade never takes a slot (2026-09-29 dry run: Byron Donalds $PH, two $1,001-$15,000
    rows); fame only ranks Congress trades that pass the $15K range-low minimum."""
    fame = json.loads((TOOLS / "fame.json").read_text(encoding="utf-8"))
    assert ss.matches_any("Byron Donalds", fame["members"]) and ss.matches_any("Kevin Hern", fame["members"])
    items = [
        ptr_item(1, "Byron Donalds", "byron-donalds", "PH", "2026-09-25", 1001, 15000, "20035001"),
        ptr_item(2, "Byron Donalds", "byron-donalds", "PH", "2026-09-25", 1001, 15000, "20035001"),
        ptr_item(3, "Kevin Hern", "kevin-hern", "PG", "2026-09-25", 50001, 100000, "20035326"),
        ptr_item(4, "Joe Nobody", "joe-nobody", "KO", "2026-09-25", 15001, 50000, "20035400"),
    ]
    api = StubApi({
        "/notable/feed?tab=insiders": {"items": [], "has_more": False},
        "/notable/feed?tab=congress": {"items": items, "has_more": False},
        "/snapshot/PH": {"company_name": "Parker-Hannifin", "profile": {"stats": {"market_cap": 8e10}}},
        "/snapshot/PG": {"company_name": "Procter & Gamble", "profile": {"stats": {"market_cap": 3.5e11}}},
        "/snapshot/KO": {"company_name": "Coca-Cola", "profile": {"stats": {"market_cap": 3e11}}},
    })
    names = {"PH": "Parker-Hannifin", "PG": "Procter & Gamble", "KO": "Coca-Cola"}
    chosen, ranked, backlog, dropped, errors = ss.choose_trades(api, D(2026, 9, 28), 3, names, fame, [], 3)
    assert errors == []
    assert "PH" not in [t.ticker for t in ranked + backlog + chosen]
    assert dropped["below_minimum"] == 1
    by = {t.ticker: t for t in ranked}
    assert set(by) == {"PG", "KO"} and by["PG"].famous_person and not by["KO"].famous_person
    assert by["PG"].parts["fame"] > by["KO"].parts["fame"]          # fame still ranks the trades that pass
    assert all(t.low >= ss.CONGRESS_MIN_LOW for t in chosen)
    # the backlog path too: an old famous $1K-$15K trade stays out
    old = [ptr_item(5, "Byron Donalds", "byron-donalds", "PH", "2026-09-10", 1001, 15000, "20034000")]
    api2 = StubApi({"/notable/feed?tab=insiders": {"items": [], "has_more": False},
                    "/notable/feed?tab=congress": {"items": old, "has_more": False},
                    "/snapshot/PH": {"company_name": "Parker-Hannifin", "profile": {"stats": {"market_cap": 8e10}}}})
    chosen2, _, backlog2, _, _ = ss.choose_trades(api2, D(2026, 9, 28), 3, names, fame, [], 3)
    assert chosen2 == [] and backlog2 == []


def test_recency_keeps_falling_for_the_backlog():
    assert [ss.recency(a) for a in (0, 3, 5, 6, 15, 40)] == [1.0, 0.55, 0.35, 0.34, 0.25, 0.15]


def test_novelty_matches_any_accession_of_a_program():
    prior = [ss.Posted(D(2026, 9, 28), "form4:0000921895-26-002608:GME", ["GME"], ["Ryan Cohen"])]
    key = "form4:0000921895-26-002531+0000921895-26-002608:GME"
    nov, why = ss.novelty(key, ["GME"], ["Someone Else"], D(2026, 11, 20), prior)
    assert nov == 0.0 and "0000921895-26-002608" in why
    ptr = [ss.Posted(D(2026, 9, 28), "ptr:20035143:BE+INTC", ["BE", "INTC"], ["Nancy Pelosi"])]
    assert ss.novelty("ptr:20035143:INTC:buy", ["INTC"], ["X Y"], D(2026, 11, 20), ptr)[0] == 0.0
    assert ss.novelty("ptr:20035143:NVDA:buy", ["NVDA"], ["X Y"], D(2026, 11, 20), ptr)[0] == 1.0


def test_programs_merge_form4s_and_skip_posted_filings():
    def t(acc, filed, v):
        return ss.Trade("insider", "Berkshire Hathaway Inc", "bh", "LEN", "buy", filed, value_usd=v, rows=1,
                        filings=[{"accession": acc, "index_url": "u", "filed": filed.isoformat(), "value_usd": v, "rows": 1}])
    a, b = t("0001193125-26-397059", D(2026, 9, 21), 212.4e6), t("0001193125-26-403089", D(2026, 9, 25), 136.4e6)
    (p,) = ss.merge_programs([b, a], [])
    assert p.story_key == "form4:0001193125-26-397059+0001193125-26-403089:LEN" and p.filed == D(2026, 9, 25)
    assert round(p.value_usd / 1e6, 1) == 348.8
    (q,) = ss.merge_programs([b, a], [ss.Posted(D(2026, 9, 22), "form4:0001193125-26-397059:LEN", ["LEN"], ["Berkshire Hathaway Inc"])])
    assert q.story_key == "form4:0001193125-26-403089:LEN"


def test_multi_class_trading_symbol():
    assert ss.primary_ticker("LEN, LEN.B", {"LEN": "Lennar"}) == "LEN"


def test_senate_trades_are_not_renderable():
    item = {"trade_id": 1, "figure": {"kind": "politician", "display_name": "Mitch McConnell", "slug": "mcconnell"}, "ticker": "WFC",
            "side": "buy", "disclosure_date": "2026-09-25", "transaction_date": "2026-09-01", "owner": "spouse",
            "amount": {"low": 15001, "high": 50000}, "source_url": "https://efdsearch.senate.gov/search/view/ptr/x/"}
    api = StubApi({"/notable/feed?tab=insiders": {"items": [], "has_more": False}, "/notable/feed?tab=congress": {"items": [item], "has_more": False}})
    fame = json.loads((TOOLS / "fame.json").read_text(encoding="utf-8"))
    trades, dropped, _ = ss.gather_trades(api, D(2026, 9, 28), 3, {"WFC": "Wells Fargo"}, fame)
    assert trades == [] and dropped["not_renderable"] == 1


def test_the_big_tech_theme_waits_a_week():
    prior = [ss.Posted(D(2026, 9, 28), "theme:congress_bigtech:2026-09-28", [], [], "congress_theme")]
    s = ss.congress_theme_slot(StubApi({}), D(2026, 9, 29), "congress_30d", prior)
    assert "at most one in 7 days" in s["empty"]


def test_congress_last_week_has_no_template():
    s = ss.theme_slot(StubApi({}), D(2026, 10, 5), "congress_week", [], {}, Path("x"), {}, [], [])
    assert "shortest window is 30 days" in s["empty"]
