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
    assert it["source_url"] == "https://www.sec.gov/Archives/edgar/data/27904/000002790426000035/x.htm"
    # G-N1 holdout: the ticker page's earnings history and its card, never the report page
    assert it["page_url"].startswith("https://www.rapidtradeview.trade/dashboard/DAL?utm_source={platform}&")
    assert it["page_url"].endswith("#earnings-history")
    assert it["media"] == [{"url": "https://www.rapidtradeview.trade/dashboard/DAL/opengraph-image", "kind": "image",
                            "alt": it["facts_text"]}]
    assert "/earnings/reports/" not in json.dumps(f)  # no field of the published file, item or not


DAL_REPORT = {"id": "dal-2026-q3", "ticker": "DAL", "company_name": "Delta Air Lines, Inc.", "fiscal_label": "FY2026 (Q3)",
              "release_date": "2026-10-09", "filing_date": "2026-10-09", "tile_label": "Mixed vs estimates",
              "published_at": "2026-10-09T10:32:21+00:00", "results": {}}


def test_earnings_result_without_an_sec_source_has_no_source_url():
    """No report-page fallback (No Fallbacks): a non-SEC or missing source_url leaves source_url null."""
    for src in (None, "https://www.rapidtradeview.trade/earnings/reports/dal-2026-q3", "https://ir.delta.com/x"):
        f = build(**{"/earnings/reports/archive": {"reports": [dict(DAL_REPORT, summary_status="ready")]},
                     "/earnings/reports/dal-2026-q3": dict(DAL_REPORT, source_url=src)})
        r = [i for i in f["items"] if i["type"] == "earnings_result"]
        assert len(r) == 1 and r[0]["source_url"] is None, src
        assert "/earnings/reports/" not in json.dumps(f)


def test_g_n1_holdout_drops_any_item_with_a_report_url_until_11_21():
    """Before 2026-11-21 an item that carries /earnings/reports/ in any field is not built; the reason is recorded."""
    fact = "See https://www.rapidtradeview.trade/earnings/reports/dal-2026-q3 for more."
    f = build(**{"/earnings/reports/archive": {"reports": [dict(DAL_REPORT, summary_status="ready")]},
                 "/earnings/reports/dal-2026-q3": dict(DAL_REPORT, company_name=fact)})
    assert [i for i in f["items"] if i["type"] == "earnings_result"] == []
    assert f["counts"]["earnings_result"] == 0
    assert f["left_out"]["g_n1_holdout"]["dropped"] == 1
    assert "G-N1 holdout until 11-21" in f["left_out"]["g_n1_holdout"]["reasons"][0]
    assert any(e.startswith("not built: 2026-10-09-earnings-result-DAL-") for e in f["errors"])
    # each field the brief names, one at a time, and the percent-encoded form
    base = fx.make_item("2026-10-13", "earnings_result", "JPM", "report:jpm", "/dashboard/JPM", facts_text="JPM fact.")
    fx.assert_no_report_page(base, dt.date(2026, 10, 13))
    for field, val in (("page_url", "https://www.rapidtradeview.trade/earnings/reports/jpm-2026-q3?utm_source=x"),
                       ("source_url", "https://www.rapidtradeview.trade/Earnings/Reports/jpm-2026-q3"),
                       ("media", [{"url": "https://www.rapidtradeview.trade/earnings/reports/jpm-2026-q3/opengraph-image"}]),
                       ("facts_text", "Read it at rapidtradeview.trade%2Fearnings%2Freports%2Fjpm-2026-q3.")):
        bad = dict(base, **{field: val})
        with pytest.raises(fx.HoldoutLeak, match=field):
            fx.assert_no_report_page(bad, dt.date(2026, 11, 20))
        fx.assert_no_report_page(bad, dt.date(2026, 11, 21))  # the readout: the gate is off
        kept, dropped = fx.screen_holdout([base, bad], dt.date(2026, 10, 13))
        assert kept == [base] and len(dropped) == 1


def test_g_n1_a_failed_report_read_names_the_ticker_never_the_report_path():
    """errors and reasons are published in facts.json: a failed archive or report read says the ticker + HTTP status."""
    f = build(**{"/earnings/reports/archive": None})
    assert "earnings report archive: HTTP 503" in f["errors"]
    assert "earnings report archive: HTTP 503" in f["reasons"]["earnings_result"]
    assert "earnings_result" in f["partial_sources"]
    assert "/earnings/reports/" not in json.dumps(f) and fx.holdout_doc_leaks(f, FRI) == []
    tile = {"id": "jpm-2026-q3", "ticker": "JPM", "release_date": "2026-10-09", "summary_status": "ready"}
    f = build(**{"/earnings/reports/archive": {"reports": [tile]}, "/earnings/reports/jpm-2026-q3": None})
    assert "earnings report JPM: HTTP 503" in f["errors"] and f["left_out"]["earnings_result"]["unreadable"] == 1
    assert "/earnings/reports/" not in json.dumps(f) and fx.holdout_doc_leaks(f, FRI) == []
    assert fx.api_status("/earnings/reports/jpm-2026-q3: HTTP 503", "/earnings/reports/jpm-2026-q3") == "HTTP 503"
    assert fx.api_status(None, "/x") is None


def test_g_n1_main_does_not_write_a_document_with_a_report_path(tmp_path, monkeypatch):
    """The whole document is screened before writing: any field (here an error and a reason) blocks the write (exit 5)."""
    monkeypatch.setattr(fx.ss, "Api", lambda base: StubApi(answers()))
    good = fx.build_facts(FRI, StubApi(answers()), FAME, now=NOW)
    leak = dict(good, errors=["/earnings/reports/jpm-2026-q3: HTTP 503"],
                reasons=dict(good["reasons"], earnings_result="see /Earnings%2FReports/jpm-2026-q3"))
    assert sorted(fx.holdout_doc_leaks(leak, FRI)) == ["errors[0]", "reasons.earnings_result"]
    monkeypatch.setattr(fx, "build_facts", lambda *a, **k: leak)
    out = tmp_path / "facts.json"
    assert fx.main(["--date", "2026-10-09", "--out", str(out)]) == fx.HOLDOUT_LEAK == 5
    assert not out.exists()
    out.write_text("{}", encoding="utf-8")                               # an earlier file stays as it was
    assert fx.main(["--date", "2026-11-20", "--out", str(out)]) == 5 and out.read_text(encoding="utf-8") == "{}"
    assert fx.main(["--date", "2026-11-21", "--out", str(out)]) == 0     # the readout: the gate is off
    assert fx.holdout_doc_leaks(leak, dt.date(2026, 11, 21)) == []


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
    assert "/dashboard/AAPL?utm_source={platform}" in u[0]["page_url"] and u[0]["page_url"].endswith("#earnings-history")
    assert u[0]["media"][0]["url"] == "https://www.rapidtradeview.trade/dashboard/AAPL/opengraph-image"


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
    # One filer per ticker: the per-filer cap keeps one congress_trade item per member a day.
    def member(t):
        return politician(f"Member {t}", f"member-{t.lower()}")
    rows = [crow(t, "buy", "2026-09-24", "2026-10-07", 15001, 50000, fig=member(t)) for t in ("UNH", "MSFT", "AAPL")]
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
    rows.append(crow("DAL", "buy", "2026-09-24", "2026-10-07", 15001, 50000, fig=member("DAL")))
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
    assert fx.page_url("/dashboard/DAL", "id4", "earnings_result").endswith("&utm_content=id4#earnings-history")
    assert fx.page_url("/dashboard/DAL", "id6", "earnings_upcoming").endswith("&utm_content=id6#earnings-history")
    assert fx.page_url("/earnings/tomorrow", "id7", "earnings_upcoming").endswith("&utm_content=id7")
    assert fx.page_url("/picks/2026-10-09", "id5", "picks_ready").endswith("&utm_content=id5")


# ---------------------------------------------------------------------------
# Rank, the per-filer cap and the roundups (Growth B1 2026-10-12)

def test_rank_sorts_the_file_and_explains_every_point():
    pelosi = politician("Nancy Pelosi", "nancy-pelosi", "house", "Democratic", "CA")
    rows = [crow("UNH", "sell", "2026-09-24", "2026-10-05", 1001, 15000),                          # Salazar: a small, older sale
            crow("AAPL", "buy", "2026-09-30", "2026-10-08", 1000001, 5000000, fig=pelosi)]         # famous, $1M-$5M, fresh buy
    f = build(**{"/notable/feed?tab=congress": {"items": rows, "has_more": False}})
    ranks = [i["rank"] for i in f["items"]]
    assert ranks and all(isinstance(r, float) for r in ranks) and ranks == sorted(ranks, reverse=True)
    assert all(isinstance(i["rank_why"], str) and i["rank_why"] for i in f["items"])
    c = [i for i in f["items"] if i["type"] == "congress_trade"]
    assert [i["ticker"] for i in c] == ["AAPL", "UNH"]
    top, low = c
    assert "buy +2" in top["rank_why"] and "known name Nancy Pelosi (fame) +2" in top["rank_why"]
    assert "top $5M +3.7" in top["rank_why"] and "filed 2026-10-08 (age 1) +1.5" in top["rank_why"]
    assert "sale +0" in low["rank_why"] and "known name" not in low["rank_why"]
    assert top["rank"] > low["rank"]


def test_rank_factors():
    t = FRI
    base = {"type": "form4_buy", "side": "buy", "name": "Jane Roe", "office": "Director at Foo", "filed": "2026-10-09"}
    plain = dict(base, office="10% owner at Foo")
    assert fx.rank(base, t, FAME)[0] - fx.rank(plain, t, FAME)[0] == 2.0           # a director title is a known name
    assert "known name Director (title) +2" in fx.rank(base, t, FAME)[1]
    assert "known name Warren Buffett (fame)" in fx.rank(dict(plain, name="Warren E. Buffett"), t, FAME)[1]
    big = dict(plain, market_cap_usd=250e9)
    mid = dict(plain, market_cap_usd=5e9)
    small = dict(plain, market_cap_usd=1e9)
    assert fx.rank(big, t, FAME)[0] - fx.rank(small, t, FAME)[0] == 2.0 and "large cap $250B +2" in fx.rank(big, t, FAME)[1]
    assert fx.rank(mid, t, FAME)[0] - fx.rank(small, t, FAME)[0] == 1.0
    # buys over sales; the top of the range, summed over trades; freshness
    sale = {"type": "congress_trade", "side": "sell", "name": "X Y", "filed": "2026-10-09", "amount_top_usd": 15000}
    assert fx.rank(dict(sale, side="buy"), t, FAME)[0] - fx.rank(sale, t, FAME)[0] == 2.0
    assert fx.rank(dict(sale, amount_top_usd=1e6), t, FAME)[0] > fx.rank(sale, t, FAME)[0]
    assert fx.rank(dict(sale, filed="2026-10-05"), t, FAME)[0] == pytest.approx(fx.rank(sale, t, FAME)[0] - 2.0)  # age 4: +0
    assert fx.range_tops([{"amount": {"low": 1001, "high": 15000}}, {"amount": {"low": 15001, "high": 50000}}]) == 65000.0


GOTT = politician("Josh Gottheimer", "josh-gottheimer", "house", "Democratic", "NJ")
# An older row (filed before the window start, 2026-10-05 for Fri 10-09): the capped public read reaches past the window,
# so no row of a filing inside it can be cut off.
OLD_ROW = crow("MSFT", "buy", "2026-09-20", "2026-09-25", 1001, 15000, fig=GOTT)
SALAZAR_SALES = [crow(t, "sell", "2026-09-24", "2026-10-07", 1001, 15000) for t in ("UNH", "MSFT", "AAPL", "DAL", "XE")]


def congress_feed(rows):
    return {"/notable/feed?tab=congress": {"items": rows, "has_more": True}}


def test_one_congress_item_per_filer_and_the_ptr_summary():
    rows = SALAZAR_SALES + [crow("MSFT", "buy", "2026-09-25", "2026-10-08", 1001, 15000, fig=GOTT), OLD_ROW]
    f = build(**congress_feed(rows))
    c = [i for i in f["items"] if i["type"] == "congress_trade"]
    s = [i for i in f["items"] if i["type"] == "ptr_summary"]
    # Salazar's summary of 5 sales outranks each of her single sales: one Salazar post, the summary
    assert [(i["name"], i["ticker"]) for i in c] == [("Josh Gottheimer", "MSFT")]
    assert len(s) == 1 and s[0]["name"] == "Maria Elvira Salazar"
    assert f["left_out"]["per_filer_cap"] == {"dropped": 5, "filers": 2, "dropped_congress_trade": 5,
                                              "dropped_ptr_summary": 0}
    assert f["left_out"]["ptr_summary_incomplete"] == {"window_start": "2026-10-05", "oldest_row_read": "2026-09-25",
                                                       "skipped": 0, "reasons": []}
    it = s[0]
    assert it["ticker"] is None and len(it["tickers"]) == 4 and it["tickers_total"] == 5
    assert it["rows"] == 5 and it["buys"] == 0 and it["sales"] == 5 and it["filed"] == "2026-10-07"
    for n in ("5", "1", "2026-10-07", "Oct 7"):
        assert n in it["allowed_numbers"]
    assert it["source_url"] == PTR and it["source_urls"] == [PTR] and it["page_url"].startswith(
        "https://www.rapidtradeview.trade/smart-money/figures/maria-elvira-salazar?") and it["page_url"].endswith("#trades")
    assert it["media"][0]["url"] == "https://www.rapidtradeview.trade/smart-money/figures/maria-elvira-salazar/opengraph-image"
    assert it["facts_text"].startswith("U.S. Representative Maria Elvira Salazar (R-FL) disclosed 5 trades (5 sales)")
    assert "and 1 more" in it["facts_text"]
    assert f["counts"]["ptr_summary"] == 1 and f["counts"]["congress_trade"] == 1
    assert "ptr_summary" not in f["reasons"]
    assert not fx.holdout_doc_leaks(f, FRI)


def test_a_filer_with_a_trade_and_a_summary_keeps_only_the_higher_ranked():
    # Salazar: 5 small sales and a $15K-$50K buy. The buy outranks her summary: only the buy is posted.
    rows = SALAZAR_SALES + [crow("AMPX", "buy", "2026-09-24", "2026-10-07", 15001, 50000), OLD_ROW]
    f = build(**congress_feed(rows))
    sal = [i for i in f["items"] if i.get("figure_slug") == "maria-elvira-salazar"]
    assert [(i["type"], i["ticker"]) for i in sal] == [("congress_trade", "AMPX")]
    assert f["left_out"]["per_filer_cap"] == {"dropped": 6, "filers": 1, "dropped_congress_trade": 5,
                                              "dropped_ptr_summary": 1}
    assert f["counts"]["ptr_summary"] == 0
    assert "lost to a higher-ranked congress_trade" in f["reasons"]["ptr_summary"]
    # Two filing dates of one filer: two summaries, one post
    later = [crow(t, "sell", "2026-09-30", "2026-10-08", 15001, 50000, src=PTR.replace("20035562", "20035599"))
             for t in ("UNH", "DAL")]
    f = build(**congress_feed(SALAZAR_SALES + later + [OLD_ROW]))
    sal = [i for i in f["items"] if i.get("figure_slug") == "maria-elvira-salazar"]
    assert len(sal) == 1 and sal[0]["type"] == "ptr_summary"
    assert f["left_out"]["per_filer_cap"]["dropped_ptr_summary"] == 1


def test_ptr_summary_needs_the_feed_read_to_reach_past_the_window_start():
    f = build(**congress_feed(SALAZAR_SALES))   # newest 50 rows, all inside the window: the filing may be cut off
    assert f["counts"]["ptr_summary"] == 0
    inc = f["left_out"]["ptr_summary_incomplete"]
    assert inc["skipped"] == 1 and inc["oldest_row_read"] == "2026-10-07" and inc["window_start"] == "2026-10-05"
    assert inc["reasons"][0].startswith("maria-elvira-salazar filed 2026-10-07: the feed read")
    assert "not before the window start 2026-10-05" in inc["reasons"][0]
    assert "not whole filings" in f["reasons"]["ptr_summary"]
    # the trades are still posted one per filer
    assert f["counts"]["congress_trade"] == 1 and f["left_out"]["per_filer_cap"]["dropped_congress_trade"] == 4
    # an old row that is exactly the window start is not "before" it
    edge = crow("MSFT", "buy", "2026-09-20", "2026-10-05", 1001, 15000, fig=GOTT)
    assert build(**congress_feed(SALAZAR_SALES + [edge]))["counts"]["ptr_summary"] == 0
    # a failed feed read: nothing to summarise, the error is the reason for congress_trade
    failed = build(**{"/notable/feed?tab=congress": None})
    assert failed["counts"]["ptr_summary"] == 0 and "congress_trade" in failed["partial_sources"]


@pytest.mark.parametrize("bad,reason", [
    (crow("ZZZZ", "buy", "2026-09-24", "2026-10-07", 1001, 15000), "not_listed 1"),
    (crow("UNH", "exchange", "2026-09-24", "2026-10-07", 1001, 15000), "other_side 1"),
    (crow("MSFT", "sell", "2026-05-01", "2026-10-07", 1001, 15000), "late_filing_over_90d 1"),
    (dict(crow("AAPL", "sell", "2026-09-24", "2026-10-07", None, None)), "no_amount 1"),
    (crow("AAPL", "buy", "2026-09-30", "2026-10-07", 1001, 15000, refiles_older_report=True), "refiles_older_report 1"),
    (crow("DAL", "buy", "2026-09-24", "2026-10-07", 1001, 15000, src="https://example.com/x.pdf"), "no_official_source 1"),
    (crow("DAL", "buy", "2026-09-24", None, 1001, 15000), "out_of_window 1"),   # same PTR URL, no filing date
])
def test_ptr_summary_skipped_when_a_row_of_the_filing_was_left_out(bad, reason):
    f = build(**congress_feed(SALAZAR_SALES + [bad, OLD_ROW]))
    assert f["counts"]["ptr_summary"] == 0
    inc = f["left_out"]["ptr_summary_incomplete"]
    assert inc["skipped"] == 1 and inc["reasons"] == [
        f"maria-elvira-salazar filed 2026-10-07: rows of the filing were left out ({reason})"]
    # the same row of another member's filing does not touch Salazar's summary
    other = dict(bad, figure=GOTT, source_url=EFD if bad["source_url"] == PTR else bad["source_url"])
    g = build(**congress_feed(SALAZAR_SALES + [other, OLD_ROW]))
    assert g["counts"]["ptr_summary"] == 1 and g["left_out"]["ptr_summary_incomplete"]["skipped"] == 0


def test_multi_filing_ptr_summary_carries_every_official_url():
    second = PTR.replace("20035562", "20035570")
    rows = SALAZAR_SALES[:3] + [crow(t, "sell", "2026-09-24", "2026-10-07", 1001, 15000, src=second) for t in ("DAL", "XE")]
    f = build(**congress_feed(rows + [OLD_ROW]))
    s = [i for i in f["items"] if i["type"] == "ptr_summary"]
    assert len(s) == 1 and s[0]["source_url"] is None and sorted(s[0]["source_urls"]) == [PTR, second]
    assert "on 2 reports filed 2026-10-07" in s[0]["facts_text"] and "2" in s[0]["allowed_numbers"]


def test_earnings_tomorrow_roundup():
    rep = lambda sym, hour, cap, confirmed=True, uni=True: {"symbol": sym, "date": "2026-10-12", "hour": hour,
                                                             "date_confirmed": confirmed, "in_universe": uni, "market_cap": cap}
    week = {"days": [{"date": "2026-10-12", "count": 8, "reports": [
        rep("AAPL", "bmo", 3e12), rep("MSFT", "bmo", 2e12), rep("UNH", "bmo", 4e11), rep("DAL", "bmo", 3e10),
        rep("XE", "bmo", 5e9), rep("AMPX", "amc", 1e9), rep("BPRE", "bmo", 9e12, confirmed=False), rep("MARA", None, 4e9)]}]}
    f = build(**{"/earnings?weeks_ahead=": week})
    r = [i for i in f["items"] if i["type"] == "earnings_tomorrow_roundup"]
    assert len(r) == 1   # one after-the-close reporter only: no amc roundup
    it = r[0]
    assert it["tickers"] == ["AAPL", "MSFT", "UNH", "DAL"] and it["hour"] == "bmo" and it["reporters_in_session"] == 5
    assert it["allowed_numbers"] == ["2026-10-12", "Oct 12, 2026", "Oct 12", "before the open"]
    assert it["page_url"].startswith("https://www.rapidtradeview.trade/earnings/tomorrow?utm_source={platform}")
    assert "#" not in it["page_url"]
    assert it["media"][0]["url"] == "https://www.rapidtradeview.trade/earnings/opengraph-image"
    assert it["facts_text"].startswith("Reporting earnings on 2026-10-12, before the open (confirmed dates): $AAPL")
    assert f["left_out"]["earnings_tomorrow_roundup"] == {"bmo": 5, "amc": 1, "no_set_session": 1}
    assert "earnings_tomorrow_roundup" not in f["reasons"]
    empty = build()
    assert "earnings_tomorrow_roundup" in empty["reasons"] and "ptr_summary" in empty["reasons"]


class _OneReportApi:
    """facts.result_items' two reads for one report published 2026-10-15 11:00Z."""
    def __init__(self, results):
        self.rep = {"id": "fhn-2026-q3", "ticker": "FHN", "company_name": "First Horizon Corporation",
                    "fiscal_label": "FY2026 (Q3)", "release_date": "2026-10-15", "filing_date": "2026-10-15",
                    "tile_label": "Missed estimates", "summary_status": "ready", "published_at": "2026-10-15T11:00:00+00:00",
                    "source_url": "https://www.sec.gov/Archives/edgar/data/36966/x/ex99.htm", "results": results}

    def get(self, path):
        if path == "/earnings/reports/archive":
            return {"reports": [self.rep]}, None
        if path == "/earnings/reports/fhn-2026-q3":
            return self.rep, None
        return None, f"{path}: HTTP 404"


def test_earnings_sanity_hold():
    """A reported figure > 40% away from consensus is a report-data mismatch (FHN $407M vs $890M): held, not a source
    failure; a normal surprise and a small-EPS-base swing still publish."""
    at = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.timezone.utc)
    held = {"revenue": {"reported": 407e6, "consensus": 890e6, "label": "Missed by $483M", "verdict": "miss"}}
    items, left, errors = fx.result_items(_OneReportApi(held), dt.date(2026, 10, 15), at)
    assert items == [] and errors == []
    assert left["consensus_mismatch_hold"] == 1 and left["held"][0].startswith("FHN: revenue")
    normal = {"revenue": {"reported": 5.68e9, "consensus": 5.56e9, "label": "Beat by $115M", "verdict": "beat"},
              "eps_adjusted": {"reported": 2.37, "consensus": 2.26, "label": "Beat by $0.11", "verdict": "beat"}}
    items, left, _ = fx.result_items(_OneReportApi(normal), dt.date(2026, 10, 15), at)
    assert len(items) == 1 and "consensus_mismatch_hold" not in left
    small = {"eps_adjusted": {"reported": 0.12, "consensus": 0.05, "label": "Beat by $0.07", "verdict": "beat"}}
    assert len(fx.result_items(_OneReportApi(small), dt.date(2026, 10, 15), at)[0]) == 1
    big_eps = {"eps_gaap": {"reported": 0.91, "consensus": 2.10, "label": "Missed by $1.19", "verdict": "miss"}}
    assert fx.sanity_mismatch(big_eps) == ["eps_gaap"]
    assert fx.sanity_mismatch({"revenue": {"reported": 1.0, "consensus": 0}}) == []


def test_not_compared_metric_is_dropped_and_eps_carries_the_item():
    """HQ 2026-10-16 contract (backend/src/earnings/model.rs): a not-comparable pair keeps its consensus but has no
    verdict/label and a per-metric not_compared. FHN shape: revenue basis_mismatch + an adjusted EPS beat -> the item
    publishes EPS only, no revenue numbers, and no tile headline (the tile may still count the dropped revenue)."""
    at = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.timezone.utc)
    res = {"revenue": {"reported": 407e6, "consensus": 890e6, "label": None, "verdict": None,
                       "not_compared": "basis_mismatch", "verification": "verified"},
           "eps_adjusted": {"reported": 0.53, "consensus": 0.45, "label": "Beat by $0.08", "verdict": "beat",
                            "basis_label": "Adjusted diluted EPS", "verification": "verified"},
           "eps_gaap": {"reported": 0.50, "prior_year": 0.41}}
    assert fx.sanity_mismatch(res) == []
    items, left, errors = fx.result_items(_OneReportApi(res), dt.date(2026, 10, 15), at)
    assert len(items) == 1 and errors == [] and "consensus_mismatch_hold" not in left
    assert left["not_compared_metrics"] == ["FHN: revenue (basis_mismatch)"]
    it = items[0]
    assert "revenue" not in it["results"] and it["results"]["eps"]["basis"] == "Adjusted diluted EPS"
    assert not {"$407M", "$890M", "$0.50"} & set(it["allowed_numbers"]) and "$0.53" in it["allowed_numbers"]
    assert "Revenue" not in it["facts_text"] and "Missed" not in it["facts_text"] and it["tile_label"] is None


def test_suspect_releases_are_held_not_published():
    """Review 2026-10-16: shapes the backend really sends. Nothing a dropped release keeps may be published unchecked."""
    at = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.timezone.utc)
    day = dt.date(2026, 10, 15)
    # PGR: monthly report (revenue basis_mismatch, no adjusted EPS, GAAP EPS = September's) -> held
    pgr = {"revenue": {"reported": 7.43e9, "consensus": 22.51e9, "verdict": None, "label": None,
                       "not_compared": "basis_mismatch"}, "eps_gaap": {"reported": 1.08, "prior_year": 0.52}}
    items, left, _ = fx.result_items(_OneReportApi(pgr), day, at)
    assert items == [] and "nothing else compared" in left["held"][0]
    # AENT: Q4 with full-year adjusted EPS (not compared) and full-year GAAP EPS -> no GAAP fallback; nothing compared -> held
    aent = {"revenue": {"reported": 268e6, "consensus": None, "verdict": None},
            "eps_adjusted": {"reported": 0.46, "consensus": 0.01, "verdict": None, "label": None, "period": "full_year",
                             "not_compared": "full_year_only"},
            "eps_gaap": {"reported": 0.26, "period": "full_year"}}
    items, left, _ = fx.result_items(_OneReportApi(aent), day, at)
    assert items == [] and left["consensus_mismatch_hold"] == 1
    # GAAP-basis adjusted EPS the SEC check disputes; eps_gaap is the same number -> never republished as GAAP EPS
    sec = {"revenue": {"reported": 2.4e9, "consensus": 2.3e9, "label": "Beat by $100M", "verdict": "beat"},
           "eps_adjusted": {"reported": 3.17, "consensus": 3.0, "verdict": None, "label": None, "basis_label": "GAAP EPS",
                            "not_compared": "sec_disagrees"},
           "eps_gaap": {"reported": 3.17}}
    it = fx.result_items(_OneReportApi(sec), day, at)[0][0]
    assert "eps" not in it["results"] and "$3.17" not in it["allowed_numbers"] and "$2.4B" in it["allowed_numbers"]
    # an unverified figure with a consensus next to it: never offered as a comparison
    unv = {"revenue": {"reported": 11.536e9, "consensus": 11.25e9, "verdict": None, "label": None,
                       "verification": "unverified"},
           "eps_adjusted": {"reported": 1.2, "consensus": 1.1, "label": "Beat by $0.10", "verdict": "beat"}}
    it = fx.result_items(_OneReportApi(unv), day, at)[0][0]
    assert "revenue" not in it["results"] and "$11.25B" not in it["allowed_numbers"]
    # a six-month report allows no quarter tokens
    rep = _OneReportApi({"period_basis": "half_year", "revenue": {"reported": 26.1e6, "consensus": None}})
    rep.rep.update(fiscal_label="H1 2026", fiscal_quarter=2, fiscal_year=2026)
    it = fx.result_items(rep, day, at)[0][0]
    assert "Q2" not in it["allowed_numbers"] and "Q2 2026" not in it["allowed_numbers"] and "H1 2026" in it["allowed_numbers"]
    # no consensus anywhere and nothing dropped (BAC 10-14 shape): published as before, with its tile
    bac = {"eps_gaap": {"reported": 0.91}}
    it = fx.result_items(_OneReportApi(bac), day, at)[0][0]
    assert it["results"]["eps"]["basis"] == "GAAP EPS" and it["tile_label"] == "Missed estimates"


def test_sanity_hold_skips_a_verified_surprise():
    """NRIX 10-13: revenue $673M vs $480M consensus is real (provider actual + SEC filing agree): published, not held;
    the same gap on an unreferenced fresh release is still held."""
    nrix = {"revenue": {"reported": 673064000.0, "consensus": 479521500.0, "verdict": "beat", "label": "Beat by $194M",
                        "verification": "verified"}}
    assert fx.sanity_mismatch(nrix) == []
    fresh = {"revenue": dict(nrix["revenue"], verification="unreferenced")}
    assert fx.sanity_mismatch(fresh) == ["revenue"]
