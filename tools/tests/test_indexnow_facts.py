"""IndexNow ping of the facts landing pages (tools/indexnow_facts.py). Offline: a fake HTTP POST."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import indexnow_facts as ix  # noqa: E402

DATE = "2026-10-12"
NOW = dt.datetime(2026, 10, 12, 15, 0, tzinfo=dt.timezone.utc)
KEY = "0123456789abcdef0123456789abcdef"
SITE = "https://www.rapidtradeview.trade"


def page(path, iid="x", anchor=""):
    return f"{SITE}{path}?utm_source={{platform}}&utm_medium=social&utm_campaign=grok&utm_content={iid}{anchor}"


def facts(*paths, date=DATE):
    return {"date": date, "items": [{"item_id": f"i{n}", "page_url": p} for n, p in enumerate(paths)]}


class FakePost:
    def __init__(self, status=202, raise_=None):
        self.status, self.raise_, self.calls = status, raise_, []

    def __call__(self, url, body):
        self.calls.append((url, json.loads(body.decode("utf-8"))))
        if self.raise_:
            raise self.raise_
        return self.status, ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    keydir = tmp_path / "public"
    keydir.mkdir()
    (keydir / f"{KEY}.txt").write_text(KEY, encoding="utf-8")
    (keydir / "llms.txt").write_text("not a key", encoding="utf-8")
    post = FakePost()
    monkeypatch.setattr(ix, "POST", post)

    def run(doc, dry=False, now=NOW, status=None, raise_=None):
        if status is not None:
            post.status = status
        post.raise_ = raise_
        f = tmp_path / "facts.json"
        f.write_text(json.dumps(doc), encoding="utf-8")
        return ix.run(doc["date"], f, tmp_path / "state.json", tmp_path / "indexnow.log", None, dry, now=now, key_dir=keydir)

    return run, post, tmp_path


def test_landing_strips_utm_and_anchor_and_excludes_reports():
    assert ix.landing(page("/smart-money/figures/josh-gottheimer", anchor="#trades")) == f"{SITE}/smart-money/figures/josh-gottheimer"
    assert ix.landing(page("/dashboard/JPM", anchor="#earnings-history")) == f"{SITE}/dashboard/JPM"
    assert ix.landing(page("/earnings/tomorrow")) == f"{SITE}/earnings/tomorrow"
    assert ix.landing(page("/earnings/reports/jpm-q3-2026")) is None
    assert ix.landing(f"{SITE}/Earnings/Reports/abc") is None
    assert ix.landing(f"{SITE}/earnings/reports") is None
    assert ix.landing(f"{SITE}/") is None and ix.landing(SITE) is None
    assert ix.landing("https://example.com/dashboard/JPM") is None
    assert ix.landing("http://www.rapidtradeview.trade/dashboard/JPM") is None
    assert ix.landing(f"https://evil.test@{SITE[8:]}/x") is None


def test_send_dedupe_and_receipt(env):
    run, post, tmp = env
    doc = facts(page("/dashboard/JPM", "a", "#moves-like"), page("/dashboard/JPM", "b", "#pattern"),
                page("/smart-money/figures/josh-gottheimer", "c", "#trades"), page("/earnings/reports/jpm-q3"),
                page("/earnings/tomorrow", "d"))
    assert run(doc) == 0
    assert len(post.calls) == 1
    url, body = post.calls[0]
    assert url == "https://api.indexnow.org/indexnow"
    assert body["host"] == "www.rapidtradeview.trade" and body["key"] == KEY
    assert body["keyLocation"] == f"{SITE}/{KEY}.txt"
    assert body["urlList"] == [f"{SITE}/dashboard/JPM", f"{SITE}/smart-money/figures/josh-gottheimer", f"{SITE}/earnings/tomorrow"]
    assert not any("/earnings/reports/" in u for u in body["urlList"])
    log = (tmp / "indexnow.log").read_text(encoding="utf-8")
    assert "2026-10-12 count=3 status=202 sent=3" in log and KEY not in log
    state = json.loads((tmp / "state.json").read_text(encoding="utf-8"))
    assert state["days"] == {"2026-10-12": 3} and state["sent"][f"{SITE}/dashboard/JPM"] == "2026-10-12"
    # Same file again (the next facts refresh): nothing new, no POST.
    assert run(doc) == 0 and len(post.calls) == 1
    # Six days later the URL is still deduped; seven days later it goes again.
    later = facts(page("/dashboard/JPM"), date="2026-10-18")
    assert run(later, now=NOW + dt.timedelta(days=6)) == 0 and len(post.calls) == 1
    later = facts(page("/dashboard/JPM"), date="2026-10-19")
    assert run(later, now=NOW + dt.timedelta(days=7)) == 0 and len(post.calls) == 2


def test_daily_cap_of_100(env):
    run, post, tmp = env
    doc = facts(*[page(f"/dashboard/T{n}") for n in range(130)])
    assert run(doc) == 0
    assert len(post.calls[0][1]["urlList"]) == 100
    assert run(doc) == 0 and len(post.calls) == 1   # today's room is used up
    assert run(dict(doc, date="2026-10-13"), now=NOW + dt.timedelta(days=1)) == 0
    assert len(post.calls[1][1]["urlList"]) == 30


@pytest.mark.parametrize("status", [429, 403])
def test_pause_on_429_and_403(env, status):
    run, post, tmp = env
    doc = facts(page("/dashboard/JPM"), page("/dashboard/GS"))
    assert run(doc, status=status) == 3
    state = json.loads((tmp / "state.json").read_text(encoding="utf-8"))
    assert state["sent"] == {} and state["paused_until"] == "2026-10-13T15:00:00Z"
    assert f"status={status} sent=0 paused_until=2026-10-13T15:00:00Z" in (tmp / "indexnow.log").read_text(encoding="utf-8")
    assert run(doc, status=202, now=NOW + dt.timedelta(hours=23)) == 3 and len(post.calls) == 1   # still paused
    assert run(doc, status=202, now=NOW + dt.timedelta(hours=25)) == 0 and len(post.calls) == 2


@pytest.mark.parametrize("status", [400, 404, 422])
def test_other_4xx_pause_6_hours(env, status):
    run, post, tmp = env
    doc = facts(page("/dashboard/JPM"))
    assert run(doc, status=status) == 3
    state = json.loads((tmp / "state.json").read_text(encoding="utf-8"))
    assert state["sent"] == {} and state["paused_until"] == "2026-10-12T21:00:00Z"
    assert state["pause_reason"] == f"HTTP {status} at 2026-10-12T15:00Z"
    assert f"status={status} sent=0 paused_until=2026-10-12T21:00:00Z" in (tmp / "indexnow.log").read_text(encoding="utf-8")
    # the next facts refreshes inside the 6 hours do not re-POST the rejected request
    for h in (1, 3, 5.9):
        assert run(doc, status=202, now=NOW + dt.timedelta(hours=h)) == 3
    assert len(post.calls) == 1
    assert run(doc, status=202, now=NOW + dt.timedelta(hours=6, minutes=1)) == 0 and len(post.calls) == 2


def test_other_failures_retry_next_run(env):
    run, post, tmp = env
    doc = facts(page("/dashboard/JPM"))
    assert run(doc, status=500) == 1
    assert run(doc, raise_=OSError("down")) == 1
    assert not (tmp / "state.json").exists()
    assert run(doc, status=200) == 0 and len(post.calls) == 3
    log = (tmp / "indexnow.log").read_text(encoding="utf-8").splitlines()
    assert [l.split(" ", 2)[2] for l in log] == ["count=1 status=500 sent=0", "count=1 status=network-error sent=0",
                                                 "count=1 status=200 sent=1"]


def test_dry_run_sends_and_writes_nothing(env, capsys):
    run, post, tmp = env
    assert run(facts(page("/dashboard/JPM", anchor="#pattern"), page("/earnings/reports/x")), dry=True) == 0
    out = capsys.readouterr().out
    assert "DRY RUN: would POST 1 URLs" in out and f"  {SITE}/dashboard/JPM" in out and KEY not in out
    assert "report pages 1" in out
    assert not post.calls and not (tmp / "state.json").exists() and not (tmp / "indexnow.log").exists()


def test_no_key_no_send(env, tmp_path):
    run, post, tmp = env
    (tmp / "public" / f"{KEY}.txt").write_text("something else", encoding="utf-8")   # name and content disagree
    assert run(facts(page("/dashboard/JPM"))) == 2 and not post.calls
    with pytest.raises(ix.NoKey):
        ix.find_key(None, tmp / "public")


def test_wrong_date_or_unreadable_facts(env):
    run, post, tmp = env
    f = tmp / "facts.json"
    f.write_text(json.dumps(facts(page("/dashboard/JPM"), date="2026-10-09")), encoding="utf-8")
    assert ix.run(DATE, f, tmp / "s.json", tmp / "l.log", None, False, now=NOW, key_dir=tmp / "public") == 2
    f.write_text("{", encoding="utf-8")
    assert ix.run(DATE, f, tmp / "s.json", tmp / "l.log", None, False, now=NOW, key_dir=tmp / "public") == 2
    assert not post.calls


def test_wired_after_publish_facts_on_weekdays():
    ps = (TOOLS / "daily_common.ps1").read_text(encoding="utf-8")
    run_daily = (TOOLS / "run_daily.ps1").read_text(encoding="utf-8")
    fn = ps[ps.index("function Invoke-IndexNowFacts"):]
    fn = fn[:fn.index("\n}\n") if "\n}\n" in fn else fn.index("\r\n}\r\n")]
    assert "DayOfWeek" in fn and "'--dry-run'" in fn and "indexnow_facts.py" in fn and "catch" in fn
    refresh = ps[ps.index("function Update-FactsIfDue"):ps.index("function Invoke-Preflight")]
    assert refresh.index("Publish-Facts $Date $Work $Push 420") < refresh.index("Invoke-IndexNowFacts $Date $Push")
    assert run_daily.index("Publish-Facts $Date $Work (-not ($NoPush -or $SelectOnly))") < run_daily.index(
        "Invoke-IndexNowFacts $Date (-not ($NoPush -or $SelectOnly))")
