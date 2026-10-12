"""Facts feed rules (tools/facts.py). Run: python -m pytest tools/tests -q (no network: a stub API)."""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import facts as fx  # noqa: E402

FAME = {"insiders": ["Warren Buffett"], "members": ["Nancy Pelosi"],
        "company_tiers_usd": {"mega": 200e9, "large": 10e9, "mid": 2e9}}
FRI = dt.date(2026, 10, 9)
NOW = dt.datetime(2026, 10, 9, 20, 0, tzinfo=dt.timezone.utc)
PTR = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035562.pdf"
EFD = "https://efdsearch.senate.gov/search/view/ptr/abc-123/"
NAMES = {"UNH": "UnitedHealth Group Incorporated", "MSFT": "Microsoft Corporation", "BPRE": "Bluerock Fund",
         "AAPL": "Apple Inc.", "DAL": "Delta Air Lines, Inc.", "XE": "X-Energy", "AMPX": "Amprius",
         "MARA": "MARA Holdings, Inc."}


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


def politician(name="Maria Elvira Salazar", slug="maria-elvira-salazar", chamber="house", party="Republican", state="FL"):
    return {"kind": "politician", "display_name": name, "slug": slug, "chamber": chamber, "party": party, "state": state}


def crow(ticker, side, traded, filed, low, high, src=PTR, fig=None, **kw):
    return {"trade_id": abs(hash((ticker, side, traded, filed, src))) % 10**6, "figure": fig or politician(), "ticker": ticker,
            "side": side, "owner": "self", "transaction_date": traded, "disclosure_date": filed,
            "amount": {"low": low, "high": high, "value_usd": None, "value_flag": None}, "source_url": src,
            "refiles_older_report": False, **kw}


def irow(tid, ticker, value, filed="2026-10-09", side="buy", name="Ramin Kamfar", slug="kamfar-ramin", plan="not_marked",
         acc="000139834426018110"):
    return {"trade_id": tid, "figure": {"kind": "insider", "display_name": name, "slug": slug, "role": "director", "title": None},
            "ticker": ticker, "side": side, "owner": "self", "transaction_date": "2026-10-07", "disclosure_date": filed,
            "trading_plan": {"status": plan},
            "amount": {"low": None, "high": None, "value_usd": value, "value_flag": None},
            "source_url": f"https://www.sec.gov/Archives/edgar/data/1551047/{acc}/index.json"}


def answers(**over):
    base = {
        "/tickers/names": {"names": NAMES},
        "/notable/feed?tab=congress": {"items": [], "has_more": False},
        "/notable/feed?tab=insiders": {"items": [], "has_more": False},
        "/snapshot/": None,
        "/earnings/reports/archive": {"reports": []},
        "/earnings?weeks_ahead=": {"days": []},
        "/tips/daily": {"status": "pending"},
        "/notable/pattern-showcase": {"v": 1, "status": "ok", "tile": None, "error": None},
        "/moves-like/": {"v": 1, "status": "not_covered", "ticker": "X", "session": None, "valid_through": None,
                         "window": 60, "baseline_same_dir": None, "subject": None, "peers": [], "error": None},
    }
    base.update(over)
    base["/moves-like/"] = base.pop("/moves-like/")  # the catch-all prefix goes last: a ticker's own answer wins
    return base


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(fx, "SLEEP", slept.append)
    return slept


def build(**over):
    return fx.build_facts(FRI, StubApi(answers(**over)), FAME, now=NOW)


# ---------------------------------------------------------------------------

def test_formats_match_our_pages():
    assert fx.usd_compact(1001) == "$1K"
    assert fx.usd_compact(15000) == "$15K"
    assert fx.usd_compact(50000) == "$50K"
    assert fx.usd_compact(2424164.52) == "$2.42M"
    assert fx.usd_compact(14_120_000) == "$14.12M"
    assert fx.trade_amount({"low": 15001, "high": 50000}) == "$15K–$50K"
    assert fx.trade_amount({"low": 15, "high": 15}) == "$15"
    assert fx.exact_range(15001, 50000) == "$15,001–$50,000"
    assert fx.money_compact(20_186_000_000) == "$20.19B"
    assert fx.money_compact(111_000_000) == "$111M"
    assert fx.money_compact(45_300_000) == "$45.3M"
    assert fx.eps_text(1.72) == "$1.72"
    assert fx.eps_text(-0.12) == "−$0.12"
    assert fx.js_fixed(0.125, 2) == "0.13"  # JS toFixed rounds an exact tie up, Python's format would not
    assert fx.date_forms("2026-10-07") == ["2026-10-07", "Oct 7, 2026", "Oct 7"]


def test_congress_rules_and_item_shape():
    rows = [
        crow("UNH", "buy", "2026-09-24", "2026-10-07", 15001, 50000),                 # kept
        crow("UNH", "buy", "2026-09-25", "2026-10-07", 1001, 15000),                  # same PTR, ticker, side: one item
        crow("MSFT", "sell", "2026-05-01", "2026-10-07", 1001, 15000),                # traded 159 days before: left out
        crow("ZZZZ", "buy", "2026-09-24", "2026-10-07", 1001, 15000),                 # not listed
        crow("AAPL", "buy", "2026-09-10", "2026-09-25", 1001, 15000),                 # filed 10 weekdays ago
        crow("AAPL", "buy", "2026-09-30", "2026-10-06", 1001, 15000, refiles_older_report=True),
        crow("AAPL", "sell", "2026-09-30", "2026-10-08", 50001, 100000, src=EFD,
             fig=politician("Nancy Pelosi", "nancy-pelosi", "senate", "Democratic", "CA")),  # Senate: kept
        crow("AAPL", "buy", "2026-09-30", "2026-10-08", 1001, 15000, src="https://example.com/x.pdf"),
    ]
    f = build(**{"/notable/feed?tab=congress": {"items": rows, "has_more": False}})
    c = [i for i in f["items"] if i["type"] == "congress_trade"]
    assert sorted(i["ticker"] for i in c) == ["AAPL", "UNH"]
    left = f["left_out"]["congress_trade"]
    assert left["late_filing_over_90d"] == 1 and left["not_listed"] == 1 and left["out_of_window"] == 1
    assert left["refiles_older_report"] == 1 and left["no_official_source"] == 1
    unh = next(i for i in c if i["ticker"] == "UNH")
    assert unh["rows"] == 2 and unh["amount_text"] == "$15K–$50K; $1K–$15K"
    assert re.match(r"^2026-10-09-congress-trade-UNH-[0-9a-f]{6}$", unh["item_id"])
    assert unh["source_url"] == PTR
    assert unh["office"] == "U.S. Representative (R-FL)"
    assert unh["page_url"] == ("https://www.rapidtradeview.trade/smart-money/figures/maria-elvira-salazar?utm_source={platform}"
                               f"&utm_medium=social&utm_campaign=grok&utm_content={unh['item_id']}#trades")
    for n in ("$15K", "$50K", "$1K", "$15,001", "2026-10-07", "Oct 7", "2026-09-24", "2"):
        assert n in unh["allowed_numbers"]
    assert unh["must_include"] == ["Not investment advice."]
    sen = next(i for i in c if i["ticker"] == "AAPL")
    assert sen["office"] == "U.S. Senator (D-CA)" and sen["source_url"] == EFD
    # Stable ids: the same input gives the same item_id.
    again = build(**{"/notable/feed?tab=congress": {"items": rows, "has_more": False}})
    assert [i["item_id"] for i in again["items"]] == [i["item_id"] for i in f["items"]]


def test_form4_material_buys_only():
    rows = [
        irow(1, "BPRE", 2_424_164.52),                                                # $1M+: kept
        irow(2, "AAPL", 50_000, name="Small Director", slug="small-dir", acc="000139834426018111"),     # below minimum
        irow(3, "MSFT", 5_000_000, plan="pre_planned", name="Planner", slug="planner", acc="000139834426018112"),
        irow(4, "UNH", 3_000_000, side="sell", name="Seller", slug="seller", acc="000139834426018113"),
    ]
    f = build(**{"/notable/feed?tab=insiders": {"items": rows, "has_more": False}})
    items = [i for i in f["items"] if i["type"] == "form4_buy"]
    assert [i["ticker"] for i in items] == ["BPRE"]
    it = items[0]
    assert it["amount_text"] == "$2.42M"
    assert it["source_url"] == "https://www.sec.gov/Archives/edgar/data/1551047/000139834426018110/0001398344-26-018110-index.htm"
    assert it["office"] == "Director at Bluerock Fund"
    assert "$2.42M" in it["allowed_numbers"] and "2026-10-09" in it["allowed_numbers"]


def test_picks_never_carry_the_number_one():
    tips = {"status": "ready", "trade_date": "2026-10-09", "valid_until": "2026-10-12T17:30:00+00:00",
            "publish_time_et": "1:30 PM ET",
            "tips": [{"rank": 1, "locked": True, "ticker": ""},
                     {"rank": 1, "locked": False, "ticker": "SECRET"},   # a #1 row that leaked its ticker: still dropped
                     {"rank": 2, "ticker": "XE", "direction": "bullish"},
                     {"rank": 3, "ticker": "AMPX", "direction": "bullish"}]}
    f = build(**{"/tips/daily": tips})
    p = [i for i in f["items"] if i["type"] == "picks_ready"]
    assert len(p) == 1 and p[0]["tickers"] == ["XE", "AMPX"] and p[0]["ticker"] is None
    assert "SECRET" not in json.dumps(f)
    assert "1" not in p[0]["allowed_numbers"]
    assert p[0]["page_url"].startswith("https://www.rapidtradeview.trade/picks/2026-10-09?utm_source={platform}")


def test_picks_not_ready_is_an_empty_reason():
    f = build(**{"/tips/daily": {"status": "pending"}})
    assert f["counts"]["picks_ready"] == 0 and "no published picks list" in f["reasons"]["picks_ready"]


def test_earnings_results_in_the_last_24_hours():
    archive = {"reports": [
        {"id": "dal-2026-q3", "ticker": "DAL", "release_date": "2026-10-09", "summary_status": "ready"},
        {"id": "old-2026-q3", "ticker": "AAPL", "release_date": "2026-10-08", "summary_status": "ready"},
    ]}
    dal = {"id": "dal-2026-q3", "ticker": "DAL", "company_name": "Delta Air Lines, Inc.", "fiscal_label": "FY2026 (Q3)",
           "fiscal_year": 2026, "fiscal_quarter": 3, "release_date": "2026-10-09", "filing_date": "2026-10-09",
           "tile_label": "Mixed vs estimates", "tile_state": "neutral", "published_at": "2026-10-09T10:32:21+00:00",
           "source_url": "https://www.sec.gov/Archives/edgar/data/27904/000002790426000035/x.htm",
           "results": {"revenue": {"reported": 20186000000.0, "consensus": 18920833850.0, "label": "Beat by $1.27B", "verdict": "beat"},
                       "eps_adjusted": {"reported": 1.72, "consensus": 1.86276, "label": "Missed by $0.14", "verdict": "miss",
                                        "basis_label": "Non-GAAP diluted EPS"}}}
    old = dict(dal, id="old-2026-q3", ticker="AAPL", published_at="2026-10-08T12:00:00+00:00")
    f = build(**{"/earnings/reports/archive": archive, "/earnings/reports/dal-2026-q3": dal, "/earnings/reports/old-2026-q3": old})
    r = [i for i in f["items"] if i["type"] == "earnings_result"]
    assert [i["ticker"] for i in r] == ["DAL"]
    it = r[0]
    assert it["results"]["revenue"] == {"reported": "$20.19B", "consensus": "$18.92B", "label": "Beat by $1.27B", "verdict": "beat"}
    assert it["results"]["eps"]["reported"] == "$1.72" and it["results"]["eps"]["consensus"] == "$1.86"
    for n in ("$20.19B", "$1.27B", "$0.14", "Q3", "FY2026", "2026-10-09"):
        assert n in it["allowed_numbers"]
    assert it["source_url"].startswith("https://www.sec.gov/")
    assert "/earnings/reports/dal-2026-q3?utm_source={platform}" in it["page_url"]


def test_earnings_upcoming_next_weekday_confirmed_universe_only():
    week = {"days": [{"date": "2026-10-12", "count": 3, "reports": [
        {"symbol": "AAPL", "date": "2026-10-12", "hour": "amc", "quarter": 4, "year": 2026, "date_confirmed": True, "in_universe": True, "market_cap": 3e12},
        {"symbol": "MSFT", "date": "2026-10-12", "hour": "bmo", "date_confirmed": False, "in_universe": True},
        {"symbol": "ZZZZ", "date": "2026-10-12", "hour": "bmo", "date_confirmed": True, "in_universe": False},
    ]}]}
    f = build(**{"/earnings?weeks_ahead=": week})
    u = [i for i in f["items"] if i["type"] == "earnings_upcoming"]
    assert [i["ticker"] for i in u] == ["AAPL"]
    assert u[0]["report_date"] == "2026-10-12" and u[0]["hour_text"] == "after the close"
    assert "Oct 12" in u[0]["allowed_numbers"] and "Q4" in u[0]["allowed_numbers"]
    assert "/earnings/tomorrow?utm_source={platform}" in u[0]["page_url"]


def test_empty_day_is_valid_with_reasons():
    f = build()
    assert f["items"] == [] and not f["errors"]
    assert set(f["reasons"]) == set(fx.TYPES)
    bw = f["rules"]["banned_words"]
    assert bw == fx.BANNED_WORDS
    for w in ("insider trading", "guaranteed", "price target", "breakout coming", "should buy", "load up", "bitcoin", "crypto"):
        assert w in bw
    assert f["rules"]["disclaimer"] == "Not investment advice." and f["rules"]["max_len"] == {"x": 270}


def test_a_failed_source_is_an_error_not_a_fallback():
    f = build(**{"/notable/feed?tab=congress": None, "/earnings/reports/archive": None})
    assert f["counts"]["congress_trade"] == 0 and f["counts"]["earnings_result"] == 0
    assert any("congress" in e for e in f["errors"]) and any("archive" in e for e in f["errors"])
    assert "did not load" in f["reasons"]["congress_trade"]


def test_main_exit_codes(tmp_path, monkeypatch):
    monkeypatch.setattr(fx.ss, "Api", lambda base: StubApi(answers()))
    out = tmp_path / "facts.json"
    assert fx.main(["--date", "2026-10-09", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == "rtv-facts/1"
    monkeypatch.setattr(fx.ss, "Api", lambda base: StubApi(answers(**{"/tickers/names": None})))
    assert fx.main(["--date", "2026-10-09", "--out", str(out)]) == fx.PARTIAL == 4


# ---------------------------------------------------------------------------
# chart_pattern / moves_like

def mara_tile(**over):
    cp = {"v": 1, "type": "rising_wedge", "name": "Rising wedge", "status": "confirmed", "in_window": True,
          "direction": "down", "start": "2026-07-31", "end": "2026-09-21", "as_of": "2026-10-08",
          "confirmed_on": "2026-09-28", "bars_since_breakout": 8,
          "pivots": [{"d": "2026-07-31", "p": 12.07, "at": "high"}, {"d": "2026-08-19", "p": 8.68, "at": "low"}],
          "breakout": {"d": "2026-09-28", "close": 12.11, "level": 12.217, "high": 12.74, "low": 12.09},
          "key_level": {"name": "lower line", "price": 12.217, "flat": False}, "cancel_level": None,
          "text": {"pill": "Rising wedge · Confirmed Sep 28", "chip": "Confirmed Sep 28", "callout": "Confirmed Sep 28",
                   "what": "Price climbing between two rising lines that come together.",
                   "detail": "confirmed by the Sep 28 close of $12.11, clearly below the lower line",
                   "key": ["Confirmed Sep 28: closed $12.11, clearly below the lower line at $12.22.",
                           "Shows for 10 trading days after the breakout."],
                   "points": [{"n": None, "t": "Highs $12.07 (Jul 31) → $13.98 (Sep 21)"},
                              {"n": None, "t": "Lows $8.68 (Aug 19) → $9.99 (Sep 2)"}]},
          "record": {"n": 1204, "years": "2022–2026", "pattern_pct": 49, "ordinary_pct": 47,
                     "pattern_label": "past rising wedge breakdowns fell over the next 5 trading days"}}
    tile = {"ticker": "MARA", "yours": False, "scan_date": "2026-10-09", "chart_pattern": cp, "bars": []}
    tile.update(over)
    return {"v": 1, "status": "ok", "tile": tile, "error": None}


def ml(ticker, peers, session="2026-10-09", status="ok"):
    return {"v": 1, "status": status, "ticker": ticker, "session": session, "valid_through": "2026-10-12", "window": 60,
            "baseline_same_dir": 31, "error": None,
            "subject": {"ticker": ticker, "name": NAMES.get(ticker), "day_pct": -1.1, "from": "2026-07-15", "closes": []},
            "peers": [{"ticker": t, "name": f"{t} Corp", "sync": s, "band": b, "same_dir": 37, "days": 58, "beta": 0.4,
                       "day_pct": d, "thr_pct": 3, "big_today": False, "event": None} for t, s, b, d in peers]}


def test_chart_pattern_item():
    f = build(**{"/notable/pattern-showcase": mara_tile()})
    [it] = [i for i in f["items"] if i["type"] == "chart_pattern"]
    assert it["ticker"] == "MARA" and it["tickers"] == ["MARA"] and it["scan_date"] == "2026-10-09"
    assert it["pattern"]["name"] == "Rising wedge" and it["pattern"]["start_text"] == "Jul 31, 2026"
    assert it["levels"] == {"key_level_name": "lower line", "key_level": "$12.22", "breakout_close": "$12.11"}
    assert it["page_url"] == ("https://www.rapidtradeview.trade/dashboard/MARA?utm_source={platform}&utm_medium=social"
                              f"&utm_campaign=grok&utm_content={it['item_id']}#pattern")
    assert it["source_url"] == "https://www.rapidtradeview.trade/dashboard/MARA"
    assert it["facts_text"].startswith("Automatic technical analysis flagged a rising wedge on $MARA (MARA Holdings, Inc.) "
                                       "(scan 2026-10-09): pattern 2026-07-31 to 2026-09-21. Confirmed Sep 28: closed $12.11")
    for n in ("$12.11", "$12.22", "$12.07", "$8.68", "Sep 28", "2026-07-31", "Jul 31, 2026", "2026-09-21"):
        assert n in it["allowed_numbers"], n
    for n in ("49%", "49", "1204", "10"):              # the history record and page mechanics are not facts to post
        assert n not in it["allowed_numbers"], n
    assert "record" not in it and "will" in it["banned_words"]
    assert "chart_pattern" not in f["reasons"] and not f["errors"]


@pytest.mark.parametrize("over, tips, why", [
    ({"ticker": "ZZZZ"}, {"status": "pending"}, "not in our names list"),
    ({"scan_date": "2026-10-12"}, {"status": "pending"}, "after 2026-10-09"),
    ({"scan_date": "2026-09-25"}, {"status": "pending"}, "older than the last 5 weekdays"),
    ({}, {"status": "ready", "trade_date": "2026-10-09", "valid_until": "2026-10-12T17:30:00+00:00",
          "tips": [{"rank": 1, "locked": False, "ticker": "MARA"}]}, "is a #1 pick"),
])
def test_chart_pattern_skips(over, tips, why):
    f = build(**{"/notable/pattern-showcase": mara_tile(**over), "/tips/daily": tips})
    assert f["counts"]["chart_pattern"] == 0 and why in f["reasons"]["chart_pattern"]
    if "#1" in why:
        assert "MARA" not in json.dumps(f["reasons"]) and "MARA" not in json.dumps(f["items"])


def test_chart_pattern_hidden_number_one_is_noted():
    tips = {"status": "ready", "trade_date": "2026-10-09", "valid_until": "2026-10-12T17:30:00+00:00",
            "publish_time_et": "1:30 PM ET", "tips": [{"rank": 1, "locked": True, "ticker": ""}, {"rank": 2, "ticker": "XE"}]}
    f = build(**{"/notable/pattern-showcase": mara_tile(), "/tips/daily": tips})
    [it] = [i for i in f["items"] if i["type"] == "chart_pattern"]
    assert "hidden" in it["top_pick_check"]


def test_chart_pattern_failures_are_errors():
    f = build(**{"/notable/pattern-showcase": None})
    assert f["counts"]["chart_pattern"] == 0 and any("pattern-showcase" in e for e in f["errors"])
    f = build(**{"/notable/pattern-showcase": {"v": 1, "status": "unavailable", "tile": None, "error": {"code": "pattern_timeout"}}})
    assert any("pattern_timeout" in e for e in f["errors"]) and "did not load" in f["reasons"]["chart_pattern"]
    f = build(**{"/notable/pattern-showcase": {"v": 1, "status": "disabled", "tile": None, "error": None}})
    assert not f["errors"] and "'disabled'" in f["reasons"]["chart_pattern"]
    f = build(**{"/notable/pattern-showcase": mara_tile(), "/tips/daily": None})
    assert f["counts"]["chart_pattern"] == 0 and "#1 guard cannot run" in f["reasons"]["chart_pattern"]


def test_moves_like_items(no_sleep):
    rows = [crow("UNH", "buy", "2026-09-24", "2026-10-07", 15001, 50000)]
    f = build(**{"/notable/feed?tab=congress": {"items": rows, "has_more": False},
                 "/notable/pattern-showcase": mara_tile(),
                 "/moves-like/UNH": ml("UNH", [("TU", 82, "tight", -4.0), ("WU", 70, "close", -3.3),
                                               ("DIN", 64, "loose", 1.0), ("HLN", 65, "close", 0.6),
                                               ("UNH", 99, "tight", 0.0)]),
                 "/moves-like/MARA": ml("MARA", [], status="not_covered")})
    m = [i for i in f["items"] if i["type"] == "moves_like"]
    assert [i["ticker"] for i in m] == ["UNH"]
    it = m[0]
    assert it["tickers"] == ["UNH", "TU", "WU", "HLN"] and it["session"] == "2026-10-09" and it["window_sessions"] == 60
    assert it["peers"][0] == {"ticker": "TU", "name": "TU Corp", "sync": 82, "band": "Tight",
                              "sync_text": "Sync 82 · Tight", "day_move": "−4.0%"}
    assert it["peers"][2]["day_move"] == "+0.6%" and it["subject_day_move"] == "−1.1%"
    assert "64" not in it["allowed_numbers"] and "DIN" not in it["tickers"]   # below the Sync 65 floor
    for n in ("82", "70", "65", "60", "2026-10-09", "Oct 9, 2026", "Oct 9", "−4.0%", "4.0%", "+0.6%", "0.6%"):
        assert n in it["allowed_numbers"], n
    assert "/dashboard/UNH?utm_source={platform}" in it["page_url"] and it["item_id"] in it["page_url"]
    assert it["facts_text"].startswith("Moves Like: over the 60 sessions before Oct 9, 2026, $UNH "
                                       "(UnitedHealth Group Incorporated) moved most like $TU (Sync 82, Tight)")
    assert f["left_out"]["moves_like"]["not_covered"] == 1 and f["left_out"]["moves_like"]["requested"] == 2
    assert no_sleep == [0.5]                       # two GETs, one 0.5 s gap


def test_moves_like_subjects_round_robin_and_cap():
    items = ([{"type": "congress_trade", "ticker": t} for t in ("A", "B", "C", "A")]
             + [{"type": "form4_buy", "ticker": t} for t in ("B", "D")]
             + [{"type": "earnings_upcoming", "ticker": t} for t in ("E", "F", "G")]
             + [{"type": "chart_pattern", "ticker": "H"}, {"type": "picks_ready", "ticker": None}])
    assert fx.moves_subjects(items) == (["A", "B", "E", "H", "D"], 8)


def test_moves_like_failures_and_empty():
    rows = [crow("UNH", "buy", "2026-09-24", "2026-10-07", 15001, 50000)]
    feed = {"/notable/feed?tab=congress": {"items": rows, "has_more": False}}
    f = build(**feed, **{"/moves-like/UNH": None})
    assert f["counts"]["moves_like"] == 0 and any("/moves-like/UNH" in e for e in f["errors"])
    f = build(**feed, **{"/moves-like/UNH": dict(ml("UNH", []), status="unavailable", session=None, subject=None,
                                                 error={"code": "moves_like_timeout"})})
    assert any("moves_like_timeout" in e for e in f["errors"]) and "did not load" in f["reasons"]["moves_like"]
    f = build(**feed, **{"/moves-like/UNH": ml("UNH", [])})
    assert not f["errors"] and f["left_out"]["moves_like"]["no_peer"] == 1
    f = build(**feed, **{"/moves-like/UNH": ml("UNH", [("TU", 75, "close", -4.0)], session="2026-10-12")})
    assert f["counts"]["moves_like"] == 0 and f["left_out"]["moves_like"]["stale"] == 1


def test_moves_like_floor_and_partial_exit():
    rows = [crow("UNH", "buy", "2026-09-24", "2026-10-07", 15001, 50000)]
    feed = {"/notable/feed?tab=congress": {"items": rows, "has_more": False}}
    f = build(**feed, **{"/moves-like/UNH": ml("UNH", [("TU", 64, "loose", -4.0), ("WU", 50, "loose", -3.3)])})
    assert f["counts"]["moves_like"] == 0 and f["left_out"]["moves_like"]["below_floor"] == 1
    assert "Sync 65+" in f["reasons"]["moves_like"] and f["moves_like_checked"] == {"UNH": "below_floor"}
    # A failed Moves Like or pattern read is an error, not a partial file: only core sources make exit 4.
    f = build(**feed, **{"/moves-like/UNH": None, "/notable/pattern-showcase": None})
    assert f["errors"] and f["partial_sources"] == []
    f = build(**{"/notable/feed?tab=congress": None})
    assert "congress_trade" in f["partial_sources"]   # (gather_trades also reads the congress feed: form4_buy too)


def test_main_exit_0_when_only_moves_like_failed(tmp_path, monkeypatch):
    rows = [crow("UNH", "buy", "2026-09-24", "2026-10-07", 15001, 50000)]
    over = {"/notable/feed?tab=congress": {"items": rows, "has_more": False}, "/moves-like/UNH": None}
    monkeypatch.setattr(fx.ss, "Api", lambda base: StubApi(answers(**over)))
    out = tmp_path / "facts.json"
    assert fx.main(["--date", "2026-10-09", "--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert any("/moves-like/UNH" in e for e in written["errors"]) and written["counts"]["moves_like"] == 0


def test_previous_answers_are_carried_over_without_a_get(no_sleep):
    rows = [crow(t, "buy", "2026-09-24", "2026-10-07", 15001, 50000) for t in ("UNH", "MSFT", "AAPL")]
    over = {"/notable/feed?tab=congress": {"items": rows, "has_more": False},
            "/moves-like/UNH": ml("UNH", [("TU", 82, "tight", -4.0)]),
            "/moves-like/MSFT": ml("MSFT", [("WU", 60, "loose", -1.0)]),
            "/moves-like/AAPL": ml("AAPL", [], status="not_covered")}
    first = build(**over)
    assert first["moves_like_checked"] == {"UNH": "item", "MSFT": "below_floor", "AAPL": "not_covered"}
    api = StubApi(answers(**over))
    again = fx.build_facts(FRI, api, FAME, now=NOW, previous=json.loads(json.dumps(first)))
    asked = []
    assert fx.item_set(again) == fx.item_set(first)
    assert again["left_out"]["moves_like"]["carried_over"] == 3 and again["left_out"]["moves_like"]["requested"] == 0
    # No GET for a ticker answered earlier today; a new ticker still gets one (5 a day at most).
    rows.append(crow("DAL", "buy", "2026-09-24", "2026-10-07", 15001, 50000))
    api = StubApi(answers(**over, **{"/moves-like/DAL": ml("DAL", [("UAL", 92, "tight", 0.0)])}))
    api.get = lambda path, _g=api.get: (asked.append(path), _g(path))[1]
    third = fx.build_facts(FRI, api, FAME, now=NOW, previous=first)
    assert [p for p in asked if p.startswith("/moves-like/")] == ["/moves-like/DAL"]
    assert sorted(i["ticker"] for i in third["items"] if i["type"] == "moves_like") == ["DAL", "UNH"]
    # Another day's file is ignored.
    other = dict(first, date="2026-10-08")
    assert fx.previous_moves(other, FRI) == ({}, [])


def test_compare_items(tmp_path, capsys):
    a = {"date": "2026-10-09", "generated_at": "x", "items": [{"item_id": "i1", "dedupe_key": "k1", "facts_text": "a"}]}
    b = dict(a, generated_at="y", items=[{"item_id": "i1", "dedupe_key": "k1", "facts_text": "changed wording"}])
    c = dict(a, items=[*a["items"], {"item_id": "i2", "dedupe_key": "k2"}])
    for name, v in (("a", a), ("b", b), ("c", c)):
        (tmp_path / f"{name}.json").write_text(json.dumps(v), encoding="utf-8")
    assert fx.main(["--compare-items", str(tmp_path / "a.json"), str(tmp_path / "b.json")]) == 0
    assert fx.main(["--compare-items", str(tmp_path / "a.json"), str(tmp_path / "c.json")]) == 1
    assert "1 new, 0 gone" in capsys.readouterr().out
    assert fx.main(["--compare-items", str(tmp_path / "a.json"), str(tmp_path / "missing.json")]) == 2


def test_old_archive_tiles_are_not_fetched():
    archive = {"reports": [
        {"id": "new-q3", "ticker": "DAL", "release_date": "2026-10-09", "summary_status": "ready",
         "updated_at": "2026-10-09T10:32:21+00:00"},
        {"id": "old-q3", "ticker": "AAPL", "release_date": "2026-10-07", "summary_status": "ready",
         "updated_at": "2026-10-07T12:00:00+00:00"},
    ]}
    api = StubApi(answers(**{"/earnings/reports/archive": archive}))
    seen = []
    api.get = lambda path, _g=api.get: (seen.append(path), _g(path))[1]
    f = fx.build_facts(FRI, api, FAME, now=NOW)
    assert "/earnings/reports/new-q3" in seen and "/earnings/reports/old-q3" not in seen
    assert f["left_out"]["earnings_result"]["outside_24h"] >= 1


def test_one_calendar_week_is_read():
    api = StubApi(answers())
    seen = []
    api.get = lambda path, _g=api.get: (seen.append(path), _g(path))[1]
    fx.build_facts(FRI, api, FAME, now=NOW)
    assert [p for p in seen if p.startswith("/earnings?")] == ["/earnings?weeks_ahead=1&scope=all"]   # Fri -> Mon


def test_item_ids_survive_the_analytics_sanitizer():
    """HQ stores utm_content as [A-Za-z0-9._:~-] only (PR #465); an id with other characters would not join back."""
    for kind in ("congress_trade", "form4_buy", "earnings_result", "earnings_upcoming", "picks_ready", "chart_pattern", "moves_like"):
        iid = fx.item_id("2026-10-13", kind, "BRK.B", "k")
        assert re.fullmatch(r"[A-Za-z0-9._:~-]{1,64}", iid), iid


def test_page_url_anchors_after_the_query():
    """HQ PR #466: #trades on figure pages, #moves-like / #pattern on /dashboard, fragment after the UTM query."""
    fig = fx.page_url("/smart-money/figures/maria-elvira-salazar", "id1", "congress_trade")
    assert fig.endswith("&utm_content=id1#trades") and "utm_medium=social" in fig
    assert fx.page_url("/dashboard/NVDA", "id2", "moves_like").endswith("&utm_content=id2#moves-like")
    assert fx.page_url("/dashboard/MARA", "id3", "chart_pattern").endswith("&utm_content=id3#pattern")
    assert fx.page_url("/earnings/reports/dal-2026-q3", "id4", "earnings_result").endswith("&utm_content=id4")
    assert fx.page_url("/picks/2026-10-09", "id5", "picks_ready").endswith("&utm_content=id5")
