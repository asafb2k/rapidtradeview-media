"""Preflight gate rules. Run: python -m pytest tools/tests -q (no network: local-only media)."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import manifest as mf  # noqa: E402
import preflight as pf  # noqa: E402

REAL = TOOLS.parent / "v" / "2026-09-27" / "manifest.json"


@pytest.mark.parametrize("url,relative", [
    ("https://api.rapidtradeview.trade/earnings?weeks_ahead=1&scope=all", True),
    ("https://api.rapidtradeview.trade/earnings?weeks_ahead=1&week_start=2026-09-28", False),
    ("https://www.rapidtradeview.trade/earnings/this-week", True),
    ("https://www.rapidtradeview.trade/earnings/today", True),
    ("https://api.rapidtradeview.trade/earnings/reports/latest?ticker=GIS", True),
    ("https://api.rapidtradeview.trade/notable/congress?days=90", True),
    ("https://api.rapidtradeview.trade/notable/feed?tab=congress&limit=200", True),
    ("https://api.rapidtradeview.trade/tips/daily", True),
    ("https://api.rapidtradeview.trade/tips/daily/2026-09-25", False),
    ("https://www.sec.gov/Archives/edgar/data/1543151/000118423726000008/primarydocument.xml", False),
    ("https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035143.pdf", False),
])
def test_relative_sources(url, relative):
    assert (pf.relative_reason(url) is not None) == relative


def test_a_relative_source_passes_only_with_a_pinned_one_on_its_host():
    rel = "https://api.rapidtradeview.trade/earnings?weeks_ahead=0&scope=all"
    assert pf.source_failures([rel, "https://www.sec.gov/Archives/edgar/data/1/2/x.xml"])
    assert pf.source_failures([rel, "https://api.rapidtradeview.trade/earnings/reports/gis-2027-q1"]) == []


def post(texts, category="insider_trade"):
    return {"category": category, "title": texts.get("title", "t"), "alt_text": "",
            "platforms": {"x": {"text": texts.get("x", ""), "reply": None}, "threads": {"text": texts.get("threads", ""), "first_reply": None},
                          "pinterest": {"title": "", "description": texts.get("pin", "")}}}


def test_claims_lint():
    bad = pf.claims_failures(post({"x": "Confirmed dates only. Always beats the market, guaranteed. #InsiderTrading"}))
    joined = "\n".join(bad)
    for needle in ("Confirmed dates only", "Always", "beats the market", "guaranteed", "InsiderTrading"):
        assert needle in joined
    assert pf.claims_failures(post({"x": "Insider buying from a Form 4 filing."})) == []


def test_earnings_posts_say_where_dates_come_from():
    e = post({"x": "Micron reports Sep 30.", "threads": "Micron reports Sep 30 (third-party calendar).", "pin": "Dates: earnings calendar."}, "earnings_today")
    fails = pf.claims_failures(e)
    assert fails == ["(b) x: an earnings post must say where its dates come from (third-party calendar / company-confirmed)"]


def test_numbers_and_dates_come_from_the_data():
    facts = pf.DataFacts([{"shares": 141000, "price": 70.9642, "value_usd": 10005952.2, "pct": "11.5", "filed": "2026-09-10",
                           "note": "Form 4 filed Sep 10, 2026"}], 2026)
    ok = post({"x": "Bought 141,000 shares at $70.9642: $10,005,952.20, about $10.0M (+11.5%), filed Sep 10, 2026. Form 4 below."})
    assert pf.number_failures(ok, facts)[0] == []
    assert pf.date_failures(ok, facts, 2026)[0] == []
    bad = post({"x": "Bought 142,000 shares on Sep 11, 2026, about $12.0M."})
    nf = "\n".join(pf.number_failures(bad, facts)[0])
    assert "142,000" in nf and "12.0M" in nf
    assert pf.date_failures(bad, facts, 2026)[0] == ["(d) x.text: the date 2026-09-11 is not a date the data holds (stale or wrong story?)"]


def test_local_only_preflight_of_a_staged_plan(tmp_path):
    m = json.loads(REAL.read_text(encoding="utf-8"))
    media_dir = tmp_path / "work" / "uber-khosrowshahi"
    media_dir.mkdir(parents=True)
    for f in mf.FORMATS:
        (media_dir / f"{f}.mp4").write_bytes(b"x" * 10)
    work = tmp_path / "work"
    (work / "uber-khosrowshahi" / "data.json").write_text(json.dumps({"schema": "rtv-daily-story/1"}), encoding="utf-8")
    now = dt.datetime(2026, 9, 27, 14, 0, tzinfo=dt.timezone.utc)
    [r] = pf.preflight(m, "2026-09-27", TOOLS.parent, work, None, True, work, now)
    assert r["slot"] == 1 and r["minutes_before_post"] == 120
    assert all(v.startswith("local file present") for v in r["checks"]["media"].values())
    # The stub data holds none of the post's figures: the gate fails the post on them.
    assert r["result"] == "fail" and any(f.startswith("(c)") for f in r["failures"])


def test_held_status_rules():
    m = json.loads(REAL.read_text(encoding="utf-8"))
    m["posts"][0].update(status="held", held_reason="Preflight: (a) relative source")
    assert mf.validate_manifest(m, "2026-09-27") == []
    m["posts"][0]["status"] = "paused"
    assert any("status: must be held" in e for e in mf.validate_manifest(m, "2026-09-27"))
    del m["posts"][0]["status"]
    assert any("status: must be held" in e for e in mf.validate_manifest(m, "2026-09-27"))


def test_held_status_is_live_with_the_kit():
    assert mf.HELD_STATUS_LIVE is True  # the kit that shows "held" is on prod (main 786fc27a)


def test_exact_sums_and_differences_of_one_kind_pass_as_derived():
    # Pelosi PTR: 10,000 + 5,000 BE shares; Uber Form 4: held before = held after - bought.
    facts = pf.DataFacts([{"transactions": [{"shares": 10000, "description": "Purchased 10,000 shares."},
                                            {"shares": 5000}, {"shares": {"value": 10000}}]},
                          {"transactions": [{"shares": 141000, "holdings_after": 1367100, "value_usd": 10005952.2}]}], 2026)
    derived: list[str] = []
    ok = post({"x": "plus 15,000 BE shares; 1,226,100 held before; 25,000 shares in all"})
    fails, _ = pf.number_failures(ok, facts, derived)
    assert [f for f in fails if "25,000" not in f] == []  # 25,000 is a sum of three: not derived
    assert len(derived) == 2
    assert derived[0].startswith('"15,000" (x.text): 10000 + 5000 = 15000 (shares:')
    assert "1367100 - 141000 = 1226100" in derived[1]
    # Two fields of different kinds never add up (a value in dollars plus a share count).
    bad = post({"x": "10,146,952.2 dollars"})
    assert pf.number_failures(bad, facts)[0]


def test_derived_numbers_listed_in_the_data_count_as_data():
    facts = pf.DataFacts([{"derived_numbers": [{"value": 25000, "formula": "10,000 + 5,000 + 10,000 shares"}]}], 2026)
    assert pf.number_failures(post({"x": "25,000 shares"}), facts)[0] == []


def picks_fixture(tmp_path, monkeypatch):
    # Isolate readiness from caption/manifest rules; every media check is stubbed, never networked.
    monkeypatch.setattr(mf, "validate_manifest", lambda *_: [])
    monkeypatch.setattr(pf, "remote_check", lambda *_: None)
    repo, work = tmp_path / "repo", tmp_path / "work"
    media = repo / "v/2026-09-30/picks/feed_4x5.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"captured test media")
    data = work / "picks/data.json"
    data.parent.mkdir(parents=True)
    data.write_text("{}", encoding="utf-8")
    p = {"slot": 4, "story_id": "picks", "id": "video-picks", "time_et": "15:00", "category": "daily_picks",
         "title": "Today's picks", "platforms": {}, "media": {"feed_4x5": mf.PAGES_BASE + "/v/2026-09-30/picks/feed_4x5.mp4"}}
    return {"posts": [p]}, repo, work


def at(hhmmss):
    return dt.datetime.fromisoformat("2026-09-30T" + hhmmss + "+00:00")


@pytest.mark.parametrize("time,expected", [("18:00:00", "pass"), ("18:00:01", "fail"), ("18:10:00", "fail")])
def test_picks_live_readiness_requires_exact_t60_not_rounded_minutes(tmp_path, monkeypatch, time, expected):
    m, repo, work = picks_fixture(tmp_path, monkeypatch)
    [r] = pf.preflight(m, "2026-09-30", repo, work, None, False, None, at(time))
    assert r["result"] == expected
    assert (work / "readiness-4.json").exists() == (expected == "pass")
    if expected == "fail":
        assert any("(e) readiness" in f for f in r["failures"])


def test_picks_readiness_stamps_check_completion_not_start(tmp_path, monkeypatch):
    m, repo, work = picks_fixture(tmp_path, monkeypatch)
    # A remote check that ends a second after T-60 must not use its earlier invocation time.
    monkeypatch.setattr(pf, "utc_now", lambda: at("18:00:01"))
    [r] = pf.preflight(m, "2026-09-30", repo, work, None, False, None)
    assert r["result"] == "fail" and r["checked_at"] == "2026-09-30T18:00:01Z"


@pytest.mark.parametrize("change", [None, "post", "media", "data"])
def test_picks_timely_receipt_survives_recheck_only_for_identical_content(tmp_path, monkeypatch, change):
    m, repo, work = picks_fixture(tmp_path, monkeypatch)
    [first] = pf.preflight(m, "2026-09-30", repo, work, None, False, None, at("17:59:00"))
    assert first["result"] == "pass"
    if change == "post":
        m["posts"][0]["title"] = "Changed caption"
    elif change == "media":
        (repo / "v/2026-09-30/picks/feed_4x5.mp4").write_bytes(b"changed media")
    elif change == "data":
        (work / "picks/data.json").write_text('{"changed": true}', encoding="utf-8")
    [again] = pf.preflight(m, "2026-09-30", repo, work, None, False, None, at("18:10:00"))
    assert again["result"] == ("pass" if change is None else "fail")
    assert again["ready_at"] == (first["ready_at"] if change is None else None)


def test_local_staging_never_records_live_readiness(tmp_path, monkeypatch):
    m, repo, work = picks_fixture(tmp_path, monkeypatch)
    [r] = pf.preflight(m, "2026-09-30", repo, work, None, True, None, at("17:59:00"))
    assert r["result"] == "pass" and not (work / "readiness-4.json").exists()
    [late] = pf.preflight(m, "2026-09-30", repo, work, None, False, None, at("18:10:00"))
    assert late["result"] == "fail"


def test_clock_replay_cannot_create_a_live_readiness_receipt(tmp_path, monkeypatch):
    m, repo, work = picks_fixture(tmp_path, monkeypatch)
    [r] = pf.preflight(m, "2026-09-30", repo, work, None, False, None, at("17:59:00"), record_readiness=False)
    assert r["result"] == "pass" and r["ready_at"] is None
    assert not (work / "readiness-4.json").exists()


@pytest.mark.parametrize("time", ["18:10:00", "19:01:00"])
def test_periodic_preflight_catches_unverified_picks_that_missed_the_window(tmp_path, monkeypatch, time):
    m, repo, work = picks_fixture(tmp_path, monkeypatch)
    assert pf.due_slots(m, "2026-09-30", repo, work, at(time), 60, 90) == {4}
    # Once held, the item cannot be posted; periodic checks need not repeat the late check forever.
    m["posts"][0]["status"] = "held"
    assert pf.due_slots(m, "2026-09-30", repo, work, at(time), 60, 90) == set()


def test_periodic_preflight_does_not_reject_timely_verified_picks_after_window(tmp_path, monkeypatch):
    m, repo, work = picks_fixture(tmp_path, monkeypatch)
    pf.preflight(m, "2026-09-30", repo, work, None, False, None, at("17:59:00"))
    assert pf.due_slots(m, "2026-09-30", repo, work, at("18:10:00"), 60, 90) == set()
    m["posts"][0]["title"] = "Late replacement"
    assert pf.due_slots(m, "2026-09-30", repo, work, at("18:10:00"), 60, 90) == {4}
