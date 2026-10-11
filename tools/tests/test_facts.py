"""Facts feed rules (tools/facts.py). Run: python -m pytest tools/tests -q (no network: a stub API)."""
import datetime as dt
import json
import re
import sys
from pathlib import Path

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
         "AAPL": "Apple Inc.", "DAL": "Delta Air Lines, Inc.", "XE": "X-Energy", "AMPX": "Amprius"}


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
    }
    base.update(over)
    return base


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
    assert re.match(r"^2026-10-09-congress_trade-UNH-[0-9a-f]{6}$", unh["item_id"])
    assert unh["source_url"] == PTR
    assert unh["office"] == "U.S. Representative (R-FL)"
    assert unh["page_url"] == ("https://www.rapidtradeview.trade/smart-money/figures/maria-elvira-salazar?utm_source={platform}"
                               f"&utm_medium=social&utm_campaign=grok&utm_content={unh['item_id']}")
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
    assert f["rules"]["banned_words"] == ["insider trading", "guaranteed", "moon", "buy now", "will rise", "price target", "to the moon"]
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
