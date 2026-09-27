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
