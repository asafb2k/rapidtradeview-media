"""Card Reel (tools/card_reel.py): when it renders, which item, the state that keeps it to one a day with no substitute, the facts
media it adds (and that the validator then accepts), and the Publish-Facts wiring. Offline: render and Pages are stubbed.
Run: python -m pytest tools/tests -q"""
import datetime as dt
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import card_reel as cr  # noqa: E402
import facts as fx  # noqa: E402
import grok_review as gr  # noqa: E402
import manifest as mf  # noqa: E402

DATE = "2026-10-12"
SITE = "https://www.rapidtradeview.trade"


def item(kind, ticker, key, filed=None, **over):
    path = {"earnings_result": f"/earnings/reports/{ticker.lower()}-2026-q3", "chart_pattern": f"/dashboard/{ticker}"}.get(
        kind, f"/smart-money/figures/f-{ticker.lower()}")
    it = fx.make_item(DATE, kind, ticker, key, path, filed=filed, facts_text=f"{ticker} fact text, filed {filed}.",
                      allowed_numbers=fx.date_forms(filed) if filed else [])
    it.update(over)
    return it


CONG_OLD = item("congress_trade", "URI", "ptr:1:URI", filed="2026-10-07")
CONG_NEW = item("congress_trade", "AAPL", "ptr:2:AAPL", filed="2026-10-09")
CONG_NEW2 = item("congress_trade", "MSFT", "ptr:3:MSFT", filed="2026-10-09")
F4 = item("form4_buy", "BPRE", "form4:1:BPRE", filed="2026-10-10")
PAT = item("chart_pattern", "SPGI", "pattern:SPGI", scan_date="2026-10-09")
ER_SMALL = item("earnings_result", "FBK", "report:fbk", filed="2026-10-12")
ER_BIG = item("earnings_result", "JPM", "report:jpm", filed="2026-10-12")
ER_UNKNOWN = item("earnings_result", "ZZZ", "report:zzz", filed="2026-10-12")
UPCOMING = item("earnings_upcoming", "GS", "upcoming:GS")


def t(iso):
    return cr.now_utc(iso)


def test_when_it_renders():
    assert cr.due(t("2026-10-12T13:59:00Z")) and "before 10:00 ET" in cr.due(t("2026-10-12T13:59:00Z"))   # Mon 09:59 EDT
    assert cr.due(t("2026-10-12T14:00:00Z")) is None                                                     # Mon 10:00 EDT
    assert cr.due(t("2026-10-12T09:00:00Z"))                                                             # the 05:00 morning pass
    assert cr.due(t("2026-12-14T14:59:00Z")) and cr.due(t("2026-12-14T15:00:00Z")) is None               # EST: 10:00 = 15:00Z
    assert cr.due(t("2026-10-17T12:00:00Z")) is None                                                     # Sat: the weekend pass
    assert cr.now_utc("2026-10-12T14:05:00.1234567Z") == dt.datetime(2026, 10, 12, 14, 5, 0, 123456, tzinfo=dt.timezone.utc)


def test_the_order_earnings_then_congress_then_form4_then_pattern():
    caps = {"JPM": 8e11, "FBK": 2e9}
    assert cr.choose([CONG_NEW, ER_SMALL, F4, ER_BIG, PAT], caps)[0] is ER_BIG                 # largest market cap
    assert cr.choose([ER_UNKNOWN, ER_SMALL], {"FBK": 2e9})[0] is ER_SMALL                     # an unknown cap ranks last
    assert cr.choose([F4, CONG_OLD, CONG_NEW, CONG_NEW2, PAT], {})[0] is CONG_NEW             # freshest filing, ties: facts order
    assert cr.choose([PAT, F4, UPCOMING], {})[0] is F4
    assert cr.choose([UPCOMING, PAT], {})[0] is PAT
    none, why = cr.choose([UPCOMING], {})
    assert none is None and "no earnings_result" in why


def test_tie_break_buys_first_then_largest_amount_then_freshest_filing_then_facts_order():
    def cong(tk, side, exact, filed):
        return item("congress_trade", tk, f"ptr:{tk}:{side}", filed=filed, side=side, amount_exact_text=exact)
    sale_big = cong("CSCO", "sell", "$1,001–$15,000; $15,001–$50,000; $1,001–$15,000", "2026-10-07")
    buy_small = cong("CVX", "buy", "$1,001–$15,000", "2026-10-07")
    buy_two = cong("META", "buy", "$1,001–$15,000; $1,001–$15,000", "2026-10-07")
    buy_big = cong("SNOW", "buy", "$1,001–$15,000; $15,001–$50,000", "2026-10-07")
    buy_big_newer = cong("OKTA", "buy", "$15,001–$50,000; $1,001–$15,000", "2026-10-08")
    buy_big_twin = cong("GLW", "buy", "$1,001–$15,000; $15,001–$50,000", "2026-10-07")
    assert [cr.amount_upper(i) for i in (sale_big, buy_small, buy_two, buy_big)] == [80000.0, 15000.0, 30000.0, 65000.0]
    assert cr.choose([sale_big, buy_small], {})[0] is buy_small                                # a buy beats a bigger sale
    assert cr.choose([sale_big, buy_small, buy_two, buy_big], {})[0] is buy_big                # then the largest amount
    assert cr.choose([buy_big, buy_big_newer], {})[0] is buy_big_newer                         # then the freshest filing
    assert cr.choose([buy_big, buy_big_twin], {})[0] is buy_big                                # then the facts order
    assert cr.choose([buy_big_twin, buy_big], {})[0] is buy_big_twin
    # Form 4 totals ("$2.42M") rank the same way
    f4 = [item("form4_buy", tk, f"form4:{tk}", filed=fd, side="buy", amount_text=amt)
          for tk, amt, fd in (("BPRE", "$2.42M", "2026-10-09"), ("COE", "$14.12M", "2026-10-08"), ("PRTA", "$1.05M", "2026-10-09"))]
    assert cr.amount_upper(f4[1]) == pytest.approx(14.12e6)
    assert cr.choose(f4, {})[0] is f4[1]
    # earnings_result keeps the largest market cap
    assert cr.choose([ER_SMALL, ER_BIG], {"JPM": 8e11, "FBK": 2e9})[0] is ER_BIG
    assert cr.amount_upper({"amount_text": None}) == 0


def test_only_items_with_a_facts_text_and_our_og_card_qualify():
    assert cr.eligible(CONG_NEW)
    assert not cr.eligible(dict(CONG_NEW, facts_text=" "))
    assert not cr.eligible(dict(CONG_NEW, media=[{"url": "https://evil.test/opengraph-image", "kind": "image", "alt": ""}]))
    assert not cr.eligible(dict(CONG_NEW, media=[]))
    assert cr.choose([dict(CONG_NEW, media=[]), CONG_OLD], {})[0] is CONG_OLD


def png(size=(1200, 630), colour=(13, 13, 13), fmt="PNG"):
    b = io.BytesIO()
    Image.new("RGB", size, colour).save(b, format=fmt)
    return b.getvalue()


def test_card_checks():
    generic = png(colour=(20, 20, 20))
    assert cr.card_problem(png(), "image/png", generic) is None
    assert "image/png" in cr.card_problem(png(), "text/html", generic)
    assert "1200x630 PNG" in cr.card_problem(png((1080, 1080)), "image/png", generic)
    assert "1200x630 PNG" in cr.card_problem(png(fmt="JPEG"), "image/png", generic)
    assert "generic card" in cr.card_problem(generic, "image/png", generic)
    assert "does not decode" in cr.card_problem(b"<html>", "image/png", generic)


def facts_file(tmp_path, items):
    f = tmp_path / "facts.json"
    mf.write_json(f, {"schema": fx.SCHEMA, "date": DATE, "rules": {"banned_words": fx.BANNED_WORDS, "disclaimer": fx.DISCLAIMER,
                      "max_len": fx.MAX_LEN, "platform_placeholder": "{platform}"}, "items": items})
    return f


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """prepare() with the network and the render stubbed: render() stages fake files like the real one."""
    calls = []

    def fake_render(state, it, rules, a, now):
        calls.append(it["item_id"])
        if env.fail:
            cr.note(state, f"FAILED {it['item_id']}: QA failed: caption", now)
            return False
        rel = f"v/{a.date}/cards/{it['item_id']}"
        (Path(a.repo) / rel).mkdir(parents=True, exist_ok=True)
        (Path(a.repo) / rel / "reel_9x16.mp4").write_bytes(b"mp4")
        (Path(a.repo) / rel / "music.json").write_text("{}", encoding="utf-8")
        state.update(status="staged", url=cr.reel_url(a.date, it["item_id"]), alt=it["facts_text"],
                     files=[f"{rel}/reel_9x16.mp4", f"{rel}/music.json"])
        return True

    monkeypatch.setattr(cr, "render", fake_render)
    monkeypatch.setattr(cr, "market_caps", lambda items: {})
    env.fail = False
    env.calls = calls
    env.work = tmp_path / "work"
    env.repo = tmp_path / "repo"
    env.repo.mkdir()
    return env


def prepare(env, facts, now="2026-10-12T14:05:00Z", push=False):
    argv = ["prepare", "--date", DATE, "--facts", str(facts), "--work", str(env.work), "--repo", str(env.repo), "--now", now]
    return cr.main(argv + ([] if push else ["--no-push"]))


def media_urls(facts, iid):
    return [m["url"] for m in next(i for i in json.loads(facts.read_text(encoding="utf-8"))["items"] if i["item_id"] == iid)["media"]]


def test_before_ten_nothing_happens(env, tmp_path):
    f = facts_file(tmp_path, [CONG_NEW])
    assert prepare(env, f, now="2026-10-12T09:00:00Z") == 0
    assert env.calls == [] and not (env.work / cr.STATE).exists()


def test_dry_run_renders_once_and_adds_the_reel_to_the_item(env, tmp_path):
    f = facts_file(tmp_path, [UPCOMING, CONG_OLD, CONG_NEW, F4])
    assert prepare(env, f) == 0
    url = cr.reel_url(DATE, CONG_NEW["item_id"])
    assert url == f"{mf.PAGES_BASE}/v/{DATE}/cards/{CONG_NEW['item_id']}/reel_9x16.mp4"
    assert media_urls(f, CONG_NEW["item_id"]) == [CONG_NEW["media"][0]["url"], url]
    reel = next(i for i in json.loads(f.read_text(encoding="utf-8"))["items"] if i["item_id"] == CONG_NEW["item_id"])["media"][1]
    assert reel == {"url": url, "kind": "reel", "alt": CONG_NEW["facts_text"]}
    # a later facts build of the day: the same reel re-attached, no second render, and never a second item
    f2 = facts_file(tmp_path, [CONG_OLD, CONG_NEW, F4])
    assert prepare(env, f2, now="2026-10-12T16:00:00Z") == 0
    assert media_urls(f2, CONG_NEW["item_id"])[-1] == url and env.calls == [CONG_NEW["item_id"]]
    assert prepare(env, f2, now="2026-10-12T16:30:00Z") == 0
    assert media_urls(f2, CONG_NEW["item_id"]).count(url) == 1


def test_push_mode_stages_then_live_attaches(env, tmp_path, monkeypatch):
    f = facts_file(tmp_path, [CONG_NEW])
    assert prepare(env, f, push=True) == cr.EXIT_STAGED
    files = (env.work / cr.FILES).read_text(encoding="utf-8").split()
    assert files == [f"v/{DATE}/cards/{CONG_NEW['item_id']}/reel_9x16.mp4", f"v/{DATE}/cards/{CONG_NEW['item_id']}/music.json"]
    assert len(media_urls(f, CONG_NEW["item_id"])) == 1                     # not attached before Pages serves it
    # Pages not serving yet: live fails, the next facts build asks to push / check again
    monkeypatch.setattr(mf, "check_media_urls", lambda urls: ["HTTP 404"])
    live = ["live", "--date", DATE, "--facts", str(f), "--work", str(env.work), "--repo", str(env.repo), "--timeout", "0"]
    assert cr.main(live) == 1
    assert prepare(env, f, now="2026-10-12T14:35:00Z", push=True) == cr.EXIT_STAGED and env.calls == [CONG_NEW["item_id"]]
    monkeypatch.setattr(mf, "check_media_urls", lambda urls: [])
    assert cr.main(live) == 0
    assert media_urls(f, CONG_NEW["item_id"])[-1] == cr.reel_url(DATE, CONG_NEW["item_id"])
    f2 = facts_file(tmp_path, [CONG_NEW])
    assert prepare(env, f2, now="2026-10-12T15:05:00Z", push=True) == 0      # live: attached, nothing to push
    assert len(media_urls(f2, CONG_NEW["item_id"])) == 2


def test_a_failed_render_gets_one_retry_of_the_same_item_and_no_substitute(env, tmp_path):
    env.fail = True
    f = facts_file(tmp_path, [CONG_NEW, CONG_OLD])
    assert prepare(env, f) == 0
    assert len(media_urls(f, CONG_NEW["item_id"])) == 1
    state = json.loads((env.work / cr.STATE).read_text(encoding="utf-8"))
    assert state["status"] == "failed" and state["attempts"] == 1 and "QA failed" in state["log"][-1]
    assert prepare(env, f, now="2026-10-12T14:35:00Z") == 0
    assert prepare(env, f, now="2026-10-12T15:05:00Z") == 0
    assert env.calls == [CONG_NEW["item_id"]] * cr.MAX_ATTEMPTS               # the same item, twice, then nothing
    for i in json.loads(f.read_text(encoding="utf-8"))["items"]:
        assert all(m["kind"] == "image" for m in i["media"])                  # no reel anywhere, no fallback content


def test_the_chosen_item_leaving_the_facts_is_not_replaced(env, tmp_path):
    env.fail = True
    assert prepare(env, facts_file(tmp_path, [CONG_NEW, CONG_OLD])) == 0
    env.fail = False
    assert prepare(env, facts_file(tmp_path, [CONG_OLD]), now="2026-10-12T14:35:00Z") == 0
    assert env.calls == [CONG_NEW["item_id"]]
    state = json.loads((env.work / cr.STATE).read_text(encoding="utf-8"))
    assert state["attempts"] == cr.MAX_ATTEMPTS and "left the facts" in state["log"][-1]


def test_weekend_pass_renders_once(env, tmp_path):
    f = facts_file(tmp_path, [CONG_NEW, PAT])
    assert prepare(env, f, now="2026-10-17T12:05:00Z") == 0
    assert env.calls == [CONG_NEW["item_id"]]


def test_compare_sees_the_added_reel(tmp_path):
    a = facts_file(tmp_path, [CONG_NEW])
    before = fx.item_set(json.loads(a.read_text(encoding="utf-8")))
    cr.attach(a, {"item_id": CONG_NEW["item_id"], "url": cr.reel_url(DATE, CONG_NEW["item_id"]), "alt": "x"})
    after = fx.item_set(json.loads(a.read_text(encoding="utf-8")))
    assert before != after
    assert "not in this facts build" in cr.attach(a, {"item_id": "gone", "url": "u", "alt": "x"})


def test_the_validator_accepts_the_reel_as_item_media(tmp_path):
    f = facts_file(tmp_path, [CONG_NEW])
    url = cr.reel_url(DATE, CONG_NEW["item_id"])
    cr.attach(f, {"item_id": CONG_NEW["item_id"], "url": url, "alt": CONG_NEW["facts_text"]})
    it = json.loads(f.read_text(encoding="utf-8"))["items"][0]
    assert gr.media_reasons({"media_url": url}, it) == []
    assert url in [m["url"] for m in it["media"]]


def test_publish_facts_runs_the_card_reel_before_the_compare():
    ps = (TOOLS / "daily_common.ps1").read_text(encoding="utf-8")
    body = ps[ps.index("function Publish-Facts"):ps.index("function Update-FactsIfDue")]
    assert body.index("Invoke-CardReel $Date $Work $tmp $Push $NowIso") < body.index("'--compare-items', $dest, $tmp")
    assert "Publish-Facts $Date $Work $Push 420 ($NowUtc.ToString('o'))" in ps
    fn = ps[ps.index("function Invoke-CardReel"):ps.index("function Publish-Facts")]
    assert "Fail " not in fn and "Push-Repo" not in fn                       # never ends the run
    assert fn.index("'push', '--quiet'") < fn.index("'live'")                # pushed before Pages is checked and it is attached
