"""Card Reel (tools/card_reel.py): when it renders, which items (slot 1, then slot 2: the next by the same order, another ticker
when one qualifies), the state that keeps it to two a day with no substitute (and reads a one-reel state file), the facts media it
adds (and that the validator then accepts), and the Publish-Facts wiring. Offline: render and Pages are stubbed.
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


def item(kind, ticker, key, filed=None, date=DATE, **over):
    path = {"earnings_result": f"/dashboard/{ticker}", "chart_pattern": f"/dashboard/{ticker}"}.get(
        kind, f"/smart-money/figures/f-{ticker.lower()}")
    it = fx.make_item(date, kind, ticker, key, path, filed=filed, facts_text=f"{ticker} fact text, filed {filed}.",
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


def test_slot_two_is_the_next_item_by_the_same_order_another_ticker_first():
    caps = {"JPM": 8e11, "FBK": 2e9}
    slot1 = {"item_id": ER_BIG["item_id"], "ticker": "JPM"}
    assert cr.choose_next([CONG_NEW, ER_SMALL, F4, ER_BIG, PAT], caps, [slot1])[0] is ER_SMALL   # the next earnings_result
    assert cr.choose_next([CONG_NEW, F4, ER_BIG, PAT], caps, [slot1])[0] is CONG_NEW             # then the next type
    # another ticker beats the same ticker's next item, even of a later type
    jpm_cong = item("congress_trade", "JPM", "ptr:9:JPM", filed="2026-10-11")
    assert cr.choose_next([ER_BIG, jpm_cong, PAT], caps, [slot1])[0] is PAT
    item2, why = cr.choose_next([ER_BIG, jpm_cong], caps, [slot1])                              # only JPM left: its next item
    assert item2 is jpm_cong and "no item of another ticker" in why
    none, why = cr.choose_next([ER_BIG, UPCOMING], caps, [slot1])                               # never slot 1's item again
    assert none is None and "besides the earlier slots' items" in why
    leak = dict(ER_SMALL, source_url=f"{SITE}/earnings/reports/fbk-2026-q3")                    # G-N1 holds for slot 2 too
    assert cr.choose_next([ER_BIG, leak, PAT], caps, [slot1])[0] is PAT


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


def prepare(env, facts, now="2026-10-12T14:05:00Z", push=False, date=DATE):
    argv = ["prepare", "--date", date, "--facts", str(facts), "--work", str(env.work), "--repo", str(env.repo), "--now", now]
    return cr.main(argv + ([] if push else ["--no-push"]))


def media_urls(facts, iid):
    return [m["url"] for m in next(i for i in json.loads(facts.read_text(encoding="utf-8"))["items"] if i["item_id"] == iid)["media"]]


def test_before_ten_nothing_happens(env, tmp_path):
    f = facts_file(tmp_path, [CONG_NEW])
    assert prepare(env, f, now="2026-10-12T09:00:00Z") == 0
    assert env.calls == [] and not (env.work / cr.STATE).exists()


def state_of(env):
    return json.loads((env.work / cr.STATE).read_text(encoding="utf-8"))


def test_dry_run_renders_two_and_adds_each_reel_to_its_item(env, tmp_path):
    f = facts_file(tmp_path, [UPCOMING, CONG_OLD, CONG_NEW, F4])
    assert prepare(env, f) == 0
    assert env.calls == [CONG_NEW["item_id"], CONG_OLD["item_id"]]           # slot 2: the next congress_trade, another ticker
    for it in (CONG_NEW, CONG_OLD):
        url = cr.reel_url(DATE, it["item_id"])
        assert url == f"{mf.PAGES_BASE}/v/{DATE}/cards/{it['item_id']}/reel_9x16.mp4"
        assert media_urls(f, it["item_id"]) == [it["media"][0]["url"], url]
        reel = next(i for i in json.loads(f.read_text(encoding="utf-8"))["items"] if i["item_id"] == it["item_id"])["media"][1]
        assert reel == {"url": url, "kind": "reel", "alt": it["facts_text"]}
    assert media_urls(f, F4["item_id"]) == [F4["media"][0]["url"]]            # never a third
    st = state_of(env)
    assert st["schema"] == cr.SCHEMA and [r["slot"] for r in st["reels"]] == [1, 2]
    assert [r["item_id"] for r in st["reels"]] == [CONG_NEW["item_id"], CONG_OLD["item_id"]]
    # a later facts build of the day: the same reels re-attached, no new render, and never another item
    f2 = facts_file(tmp_path, [CONG_OLD, CONG_NEW, F4])
    assert prepare(env, f2, now="2026-10-12T16:00:00Z") == 0
    assert media_urls(f2, CONG_NEW["item_id"])[-1] == cr.reel_url(DATE, CONG_NEW["item_id"])
    assert media_urls(f2, CONG_OLD["item_id"])[-1] == cr.reel_url(DATE, CONG_OLD["item_id"])
    assert env.calls == [CONG_NEW["item_id"], CONG_OLD["item_id"]]
    assert prepare(env, f2, now="2026-10-12T16:30:00Z") == 0
    assert media_urls(f2, CONG_NEW["item_id"]).count(cr.reel_url(DATE, CONG_NEW["item_id"])) == 1
    assert len(media_urls(f2, F4["item_id"])) == 1


def test_slot_two_is_chosen_on_a_later_build_when_no_second_item_qualifies_yet(env, tmp_path):
    assert prepare(env, facts_file(tmp_path, [CONG_NEW, UPCOMING])) == 0
    assert env.calls == [CONG_NEW["item_id"]] and len(state_of(env)["reels"]) == 1
    f = facts_file(tmp_path, [CONG_NEW, F4])                                    # a Form 4 buy arrives later in the day
    assert prepare(env, f, now="2026-10-12T15:05:00Z") == 0
    assert env.calls == [CONG_NEW["item_id"], F4["item_id"]]
    assert media_urls(f, F4["item_id"])[-1] == cr.reel_url(DATE, F4["item_id"])
    assert prepare(env, facts_file(tmp_path, [CONG_NEW, F4, PAT]), now="2026-10-12T15:35:00Z") == 0
    assert len(env.calls) == 2                                                  # two a day at most


def test_a_one_reel_state_file_is_read_as_slot_one(env, tmp_path):
    """A card-reel.json written before 2026-11-08 (schema /1, one reel, live) keeps its reel; slot 2 is added beside it."""
    env.work.mkdir(parents=True)
    url = cr.reel_url(DATE, CONG_NEW["item_id"])
    mf.write_json(env.work / cr.STATE, {"schema": "rtv-card-reel-state/1", "date": DATE, "status": "live", "attempts": 1,
                                        "log": ["2026-10-12T14:05:00Z chose it"], "item_id": CONG_NEW["item_id"], "type": "congress_trade",
                                        "ticker": "AAPL", "url": url, "alt": CONG_NEW["facts_text"],
                                        "files": [f"v/{DATE}/cards/{CONG_NEW['item_id']}/reel_9x16.mp4"]})
    f = facts_file(tmp_path, [CONG_NEW, CONG_NEW2, PAT])
    assert prepare(env, f, now="2026-10-12T15:05:00Z") == 0
    assert env.calls == [CONG_NEW2["item_id"]]                                 # slot 1 is not rendered again
    assert media_urls(f, CONG_NEW["item_id"])[-1] == url
    st = state_of(env)
    assert st["schema"] == cr.SCHEMA and st["reels"][0]["status"] == "live" and st["reels"][0]["log"] == ["2026-10-12T14:05:00Z chose it"]
    assert st["reels"][1]["item_id"] == CONG_NEW2["item_id"] and st["reels"][1]["slot"] == 2
    # a one-reel file of another date starts the day empty
    mf.write_json(env.work / cr.STATE, {"schema": "rtv-card-reel-state/1", "date": "2026-10-11", "status": "live", "item_id": "x"})
    assert cr.read_state(env.work, DATE) == {"schema": cr.SCHEMA, "date": DATE, "reels": []}


def test_push_mode_stages_both_slots_then_live_attaches_each_as_pages_serves_it(env, tmp_path, monkeypatch):
    f = facts_file(tmp_path, [CONG_NEW, PAT])
    assert prepare(env, f, push=True) == cr.EXIT_STAGED
    files = (env.work / cr.FILES).read_text(encoding="utf-8").split()
    assert files == [f"v/{DATE}/cards/{i}/{n}" for i in (CONG_NEW["item_id"], PAT["item_id"]) for n in ("reel_9x16.mp4", "music.json")]
    served = {cr.reel_url(DATE, CONG_NEW["item_id"])}
    monkeypatch.setattr(mf, "check_media_urls", lambda urls: [] if set(urls) <= served else ["HTTP 404"])
    live = ["live", "--date", DATE, "--facts", str(f), "--work", str(env.work), "--repo", str(env.repo), "--timeout", "0"]
    assert cr.main(live) == 1                                                   # slot 2 not served yet
    assert [r["status"] for r in state_of(env)["reels"]] == ["live", "staged"]
    assert media_urls(f, CONG_NEW["item_id"])[-1] == cr.reel_url(DATE, CONG_NEW["item_id"])
    assert len(media_urls(f, PAT["item_id"])) == 1
    f2 = facts_file(tmp_path, [CONG_NEW, PAT])                                  # the next build: slot 1 attached, slot 2 pushed again
    assert prepare(env, f2, now="2026-10-12T14:35:00Z", push=True) == cr.EXIT_STAGED
    assert (env.work / cr.FILES).read_text(encoding="utf-8").split() == files[2:]
    assert len(media_urls(f2, CONG_NEW["item_id"])) == 2 and env.calls == [CONG_NEW["item_id"], PAT["item_id"]]
    served.add(cr.reel_url(DATE, PAT["item_id"]))
    assert cr.main(live[:4] + [str(f2)] + live[5:]) == 0
    assert media_urls(f2, PAT["item_id"])[-1] == cr.reel_url(DATE, PAT["item_id"])
    assert cr.main(live) == 1                                                   # nothing staged any more


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
    f = facts_file(tmp_path, [CONG_NEW, CONG_OLD, F4])
    assert prepare(env, f) == 0
    assert len(media_urls(f, CONG_NEW["item_id"])) == 1
    for slot in state_of(env)["reels"]:
        assert slot["status"] == "failed" and slot["attempts"] == 1 and "QA failed" in slot["log"][-1]
    assert prepare(env, f, now="2026-10-12T14:35:00Z") == 0
    assert prepare(env, f, now="2026-10-12T15:05:00Z") == 0
    # each slot: the same item, twice, then nothing; F4 is never tried in their place
    assert env.calls == [CONG_NEW["item_id"], CONG_OLD["item_id"]] * cr.MAX_ATTEMPTS
    for i in json.loads(f.read_text(encoding="utf-8"))["items"]:
        assert all(m["kind"] == "image" for m in i["media"])                  # no reel anywhere, no fallback content


def test_a_failed_slot_one_is_not_replaced_and_slot_two_goes_on(env, tmp_path, monkeypatch):
    real = cr.render

    def fail_slot_one(state, it, rules, a, now):
        if it["item_id"] == CONG_NEW["item_id"]:
            env.calls.append(it["item_id"])
            cr.note(state, f"FAILED {it['item_id']}: QA failed: caption", now)
            return False
        return real(state, it, rules, a, now)

    monkeypatch.setattr(cr, "render", fail_slot_one)
    f = facts_file(tmp_path, [CONG_NEW, CONG_OLD, F4])
    for now in ("2026-10-12T14:05:00Z", "2026-10-12T14:35:00Z", "2026-10-12T15:05:00Z"):
        assert prepare(env, f, now=now) == 0
    assert env.calls == [CONG_NEW["item_id"], CONG_OLD["item_id"], CONG_NEW["item_id"]]
    assert [r["status"] for r in state_of(env)["reels"]] == ["failed", "staged"]
    assert media_urls(f, CONG_OLD["item_id"])[-1] == cr.reel_url(DATE, CONG_OLD["item_id"])
    assert len(media_urls(f, F4["item_id"])) == 1                              # no third item for the failed slot


def test_the_chosen_item_leaving_the_facts_is_not_replaced(env, tmp_path):
    env.fail = True
    assert prepare(env, facts_file(tmp_path, [CONG_NEW, CONG_OLD])) == 0
    env.fail = False
    assert prepare(env, facts_file(tmp_path, [CONG_OLD, F4]), now="2026-10-12T14:35:00Z") == 0
    assert env.calls == [CONG_NEW["item_id"], CONG_OLD["item_id"], CONG_OLD["item_id"]]   # slot 2 retried; F4 never used
    one, two = state_of(env)["reels"]
    assert one["attempts"] == cr.MAX_ATTEMPTS and "left the facts" in one["log"][-1] and two["status"] == "staged"


def test_weekend_pass_renders_two(env, tmp_path):
    sat = "2026-10-17"
    cong, pat, f4 = (item("congress_trade", "AAPL", "ptr:2:AAPL", filed="2026-10-16", date=sat),
                     item("chart_pattern", "SPGI", "pattern:SPGI", date=sat, scan_date="2026-10-16"),
                     item("form4_buy", "BPRE", "form4:1:BPRE", filed="2026-10-16", date=sat))
    f = facts_file(tmp_path, [cong, pat, f4])
    assert prepare(env, f, now="2026-10-17T12:05:00Z", date=sat) == 0
    assert env.calls == [cong["item_id"], f4["item_id"]]


def test_a_stale_item_is_never_the_reel(env, tmp_path):
    """2026-11-08: the weekend pass chose two earlier-week earnings_results (stale by VIRAL CHECK M8), and the validator
    rejects a stale item's post; the chooser takes only items fresh on the build's day."""
    sun = "2026-10-18"
    old_er = item("earnings_result", "JPM", "report:jpm", filed="2026-10-14", date=sun,
                  published_at="2026-10-14T11:00:00Z", session_date="2026-10-14")
    pat = item("chart_pattern", "SPGI", "pattern:SPGI", date=sun, scan_date="2026-10-17")
    stale_pat = item("chart_pattern", "MSFT", "pattern:MSFT", date="2026-10-16", scan_date="2026-10-15")
    assert cr.vc.fresh(old_er, "2026-10-18T13:05:00Z").get("ok") is False
    f = facts_file(tmp_path, [old_er, stale_pat, pat])
    assert prepare(env, f, now="2026-10-18T13:05:00Z", date=sun) == 0
    assert env.calls == [pat["item_id"]]


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


# ---------------------------------------------------------------------------
# G-N1 holdout (until 2026-11-21): the earnings_result Reel is the ticker page's card, never a report page

class _ReportApi:
    """The two report reads facts.result_items makes, for one JPM report published on 10-13."""
    REPORT = {"id": "jpm-2026-q3", "ticker": "JPM", "company_name": "JPMorgan Chase & Co.", "fiscal_label": "FY2026 (Q3)",
              "release_date": "2026-10-13", "filing_date": "2026-10-13", "tile_label": "Beat estimates",
              "summary_status": "ready", "published_at": "2026-10-13T11:00:00+00:00",
              "source_url": "https://www.sec.gov/Archives/edgar/data/19617/000001961726000099/ex99.htm", "results": {}}

    def get(self, path):
        if path == "/earnings/reports/archive":
            return {"reports": [self.REPORT]}, None
        if path == "/earnings/reports/jpm-2026-q3":
            return self.REPORT, None
        return None, f"{path}: HTTP 404"


def test_g_n1_a_report_page_item_never_becomes_the_reel():
    old_style = item("earnings_result", "JPM", "report:jpm-old", filed="2026-10-13")
    old_style.update(page_url=f"{SITE}/earnings/reports/jpm-2026-q3?utm_source={{platform}}",
                     media=[{"url": f"{SITE}/earnings/reports/jpm-2026-q3/opengraph-image", "kind": "image", "alt": "x"}])
    assert cr.report_leak(old_style) and not cr.eligible(old_style)
    assert cr.choose([old_style, CONG_NEW], {"JPM": 8e11})[0] is CONG_NEW
    after = dict(old_style, item_id="2026-11-23" + old_style["item_id"][10:])
    assert not cr.report_leak(after)                                       # the gate ends with the readout


def test_g_n1_a_chosen_item_that_carries_a_report_url_is_not_rendered(env, tmp_path):
    leak = item("earnings_result", "JPM", "report:jpm-old", filed="2026-10-12")
    env.work.mkdir(parents=True)
    mf.write_json(env.work / cr.STATE,
                  {"schema": "rtv-card-reel-state/1", "date": DATE, "status": "failed", "attempts": 1, "log": [],
                   "item_id": leak["item_id"]})
    leak["source_url"] = f"{SITE}/earnings/reports/jpm-2026-q3"
    assert prepare(env, facts_file(tmp_path, [leak, CONG_NEW])) == 0
    assert leak["item_id"] not in env.calls and env.calls == [CONG_NEW["item_id"]]     # slot 2 is its own item, not a substitute
    one, two = state_of(env)["reels"]
    assert one["attempts"] == cr.MAX_ATTEMPTS and "G-N1 holdout until 11-21" in one["log"][-1]
    assert two["item_id"] == CONG_NEW["item_id"]


def test_g_n1_reel_spec_carries_no_report_url(tmp_path, monkeypatch):
    """facts.result_items -> choose -> the real render() (download + renderer stubbed): the item handed to the renderer,
    the card it downloads, the staged music.json and the state carry no /earnings/reports/ URL."""
    items, _, errors = fx.result_items(_ReportApi(), dt.date(2026, 10, 13), dt.datetime(2026, 10, 13, 15, 0, tzinfo=dt.timezone.utc))
    assert errors == [] and len(items) == 1
    er = items[0]
    assert er["media"][0]["url"] == f"{SITE}/dashboard/JPM/opengraph-image"
    chosen, why = cr.choose([CONG_NEW, er], {"JPM": 8e11})
    assert chosen is er and why.startswith("earnings_result")              # earnings_result still goes first

    fetched = []
    card, generic = png(colour=(13, 13, 13)), png(colour=(20, 20, 20))

    def fake_fetch(url, timeout=60.0):
        fetched.append(url)
        return (generic if url == cr.GENERIC_CARD else card), "image/png"

    def fake_run(cmd, cwd=None, timeout=None):
        out = Path(cmd[cmd.index("--out") + 1])
        out.mkdir(parents=True)
        (out / "reel_9x16.mp4").write_bytes(b"mp4")
        spec = json.loads(Path(cmd[cmd.index("--item") + 1]).read_text(encoding="utf-8"))
        mf.write_json(out / "reel.json", {"qa_pass": True, "item_id": spec["item"]["item_id"], "music": {"bed": "x"},
                                          "files": {"reel_9x16.mp4": cr.sha256(out / "reel_9x16.mp4")},
                                          "card": {"sha256": cr.sha256(Path(cmd[cmd.index("--card") + 1])),
                                                   "url": spec["item"]["media"][0]["url"]}})
        mf.write_json(out / "reel-qa.json", {"pass": True, "summary": {}})
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(cr, "fetch", fake_fetch)
    monkeypatch.setattr(cr.subprocess, "run", fake_run)
    repo, work = tmp_path / "repo", tmp_path / "work"
    repo.mkdir()
    a = cr.argparse.Namespace(work=str(work), repo=str(repo), date="2026-10-13", gv=str(tmp_path), python="py")
    state = {"item_id": er["item_id"], "log": []}
    assert cr.render(state, er, {}, a, cr.now_utc("2026-10-13T14:05:00Z")) is True
    spec = (work / "card-reel" / er["item_id"] / "item.json").read_text(encoding="utf-8")
    staged = (repo / f"v/2026-10-13/cards/{er['item_id']}/music.json").read_text(encoding="utf-8")
    assert fetched[0] == f"{SITE}/dashboard/JPM/opengraph-image"
    for text in (spec, staged, json.dumps(state), json.dumps(fetched)):
        assert "/earnings/reports/" not in text
    assert "/dashboard/JPM" in spec and "#earnings-history" in spec
