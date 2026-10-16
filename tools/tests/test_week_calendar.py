"""Weekly earnings calendar image (tools/week_calendar.py): the render and its self-QA, short names, and the prepare / live state
that keeps the earnings_week_calendar item out of the facts until its image is live (no image, no item). Offline: Pages is
stubbed. Run: python -m pytest tools/tests -q"""
import copy
import datetime as dt
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import facts as fx  # noqa: E402
import grok_review as gr  # noqa: E402
import manifest as mf  # noqa: E402
import week_calendar as wc  # noqa: E402

FRI = "2026-10-16"
WEEK = json.loads((TOOLS / "tests" / "fixtures" / "earnings_week_2026-10-19.json").read_text(encoding="utf-8"))


def calendar_item() -> dict:
    (it,), _, why = fx.week_calendar_items(dt.date(2026, 10, 16), [WEEK["earnings"]], [], WEEK["names"])
    assert why is None
    it["rank"], it["rank_why"] = fx.rank(it, dt.date(2026, 10, 16), {})
    return it


ITEM = calendar_item()


@pytest.fixture(scope="module")
def rendered():
    return wc.render_calendar(ITEM)


# ---------------------------------------------------------------------------
# render + self-QA

def test_render_is_a_small_deterministic_4x5_png(rendered):
    png, report = rendered
    with Image.open(io.BytesIO(png)) as im:
        assert im.format == "PNG" and im.size == (1080, 1350)
    assert len(png) <= wc.MAX_BYTES == 400_000
    assert wc.render_calendar(ITEM)[0] == png                     # same item, same bytes
    assert report["pass"] and report["failures"] == []
    assert report["tiles"] == 44 == sum(len(e[s]["shown"]) for e in ITEM["calendar"] for s in ("bmo", "amc"))
    assert {c["id"]: c["more_drawn"] for c in report["cells"]}["2026-10-21:amc"] == "+47"
    sizes = {}
    for t in report["texts"]:
        sizes.setdefault(t["role"], set()).add(t["size"])
    assert sizes["ticker"] == {34} and sizes["more"] == {30} and sizes["name"] == {20}
    assert min(min(v) for v in sizes.values()) >= 20


def test_self_qa_records_every_text_inside_the_safe_area(rendered):
    _, report = rendered
    assert len(report["texts"]) > 44 and report["size"] == [1080, 1350]
    for t in report["texts"]:
        x0, y0, x1, y1 = t["box"]
        assert x0 >= wc.SAFE and y0 >= wc.SAFE and x1 <= 1080 - wc.SAFE and y1 <= 1350 - wc.SAFE, t
    for c in report["cells"]:
        x0, y0, x1, y1 = c["box"]
        assert x0 >= wc.SAFE and y0 >= wc.SAFE and x1 <= 1080 - wc.SAFE and y1 <= 1350 - wc.SAFE
        assert c["total"] == len(c["shown"]) + c["more"] and c["tiles"] == len(c["shown"])


@pytest.mark.parametrize("break_it, why", [
    (lambda it: it["calendar"][0]["amc"]["shown"].extend(["AAA", "BBB"]), "do not fit 6 slots"),
    (lambda it: it["calendar"][1]["bmo"].update(more=99), "!= 17 total"),
    (lambda it: it["calendar"][4]["bmo"]["shown"].__setitem__(2, "WWWWW.WW"), "leaves its tile"),
    (lambda it: it["calendar"][4]["bmo"]["shown"].__setitem__(0, "AB7"), "draws 7, not from the item"),
])
def test_self_qa_fails_the_render(break_it, why):
    bad = copy.deepcopy(ITEM)
    break_it(bad)
    with pytest.raises(wc.QAError) as e:
        wc.render_calendar(bad)
    assert why in str(e.value)


def test_render_cli(tmp_path, capsys):
    item_file = tmp_path / "item.json"
    item_file.write_text(json.dumps({"items": [ITEM], "reasons": {}}), encoding="utf-8")
    assert wc.main(["render", "--item", str(item_file), "--out", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "calendar_4x5.png").is_file() and json.loads(
        (tmp_path / "out" / "calendar-qa.json").read_text(encoding="utf-8"))["pass"] is True
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"items": [], "reasons": {"earnings_week_calendar": "Fridays only"}}), encoding="utf-8")
    assert wc.main(["render", "--item", str(empty), "--out", str(tmp_path / "out2")]) == 1
    assert "Fridays only" in capsys.readouterr().out


def test_busy_weeks_still_fit():
    """Peak-season counts, untimed reporters, wide tickers and a range across months: wrapped labels, condensed tickers."""
    busy = copy.deepcopy(ITEM)
    busy.update(week_start="2026-11-30", week_end="2026-12-04", as_of_date="2026-11-27")
    for k, e in enumerate(busy["calendar"]):
        e["date"] = (dt.date(2026, 11, 30) + dt.timedelta(days=k)).isoformat()
    busy["calendar"][0].update(total=288, no_session=12)
    busy["calendar"][1].update(total=1166, no_session=3)
    busy["calendar"][2]["no_session"] = 123
    busy["calendar"][3]["bmo"]["shown"] = ["CMCSA", "GOOGL", "BRK.B", "WWWW", "MMMM"]
    busy["names"].update({"CMCSA": "Comcast Corporation", "GOOGL": "Alphabet Inc."})
    png, report = wc.render_calendar(busy)
    texts = {t["text"] for t in report["texts"]}
    assert {"288 confirmed", "12 time not set", "1166", "confirmed", "123 time", "not set", "Nov 30 – Dec 4, 2026"} <= texts
    assert {"CMCSA", "FCNCA"} <= set(report["condensed"]) and "Comcast" in report["names_shown"]
    busy["calendar"][1]["no_session"] = 1234                     # 1166 / confirmed / 1234 time / not set: 4 lines
    with pytest.raises(wc.QAError, match="needs 4 lines"):
        wc.render_calendar(busy)


@pytest.mark.parametrize("name, short", [
    ("Zions Bancorporation, National Association", "Zions Bancorporation"),
    ("Wells Fargo & Company", "Wells Fargo"),
    ("The Bank of New York Mellon Corporation", "Bank of New York Mellon"),
    ("W. R. Berkley Corporation", "W. R. Berkley"),
    ("Meta Platforms, Inc.", "Meta"),
    ("AT&T Inc.", "AT&T"),
    ("3M Company", "3M"),
    ("SLB N.V.", "SLB"),
    ("Chubb Limited", "Chubb"),
    ("Texas Instruments Incorporated", "Texas Instruments"),
    (None, None),
])
def test_short_names_never_cut(name, short):
    assert wc.short_name(name) == short
    assert short is None or ("…" not in short and not short.endswith((",", "&")))


def test_names_show_only_whole_and_with_air(rendered):
    _, report = rendered
    shown = report["names_shown"]
    assert "Tesla" in shown and "Netflix" in shown
    assert set(shown) <= {wc.short_name(n) for n in ITEM["names"].values()}
    assert not any("…" in n or n.endswith("...") for n in shown)


def test_alt_text_whole_entries_only():
    alt = wc.alt_text(ITEM)
    assert alt.startswith("Earnings calendar for next week, Oct 19–23, 2026:") and len(alt) <= wc.ALT_MAX
    assert "Wed Oct 21, after the close: META, TSLA, LRCX, TXN, IBM and 47 more." in alt
    assert alt.endswith(".")
    long = copy.deepcopy(ITEM)
    for e in long["calendar"]:
        e["bmo"]["shown"] = [f"{t}" for t in e["bmo"]["shown"]] * 30
    cut = wc.alt_text(long)
    assert len(cut) <= wc.ALT_MAX and cut.endswith(".")


# ---------------------------------------------------------------------------
# prepare / live: no image, no item

OTHER = fx.make_item(FRI, "earnings_upcoming", "TSLA", "upcoming:TSLA:2026-10-19", "/dashboard/TSLA", name="Tesla, Inc.",
                     facts_text="Tesla reports.")
OTHER["rank"] = 3.0


def facts_doc(item=ITEM) -> dict:
    items = [i for i in (item, OTHER) if i is not None]
    items.sort(key=lambda i: -i["rank"])
    return {"schema": fx.SCHEMA, "date": FRI, "rules": {"banned_words": fx.BANNED_WORDS, "disclaimer": fx.DISCLAIMER,
                                                        "max_len": fx.MAX_LEN, "platform_placeholder": "{platform}"},
            "counts": {k: sum(1 for i in items if i["type"] == k) for k in fx.TYPES},
            "reasons": {} if item else {"earnings_week_calendar": "the earnings calendar ... did not load (x)"},
            "items": copy.deepcopy(items)}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = type("Env", (), {})()
    e.repo, e.work, e.facts = tmp_path / "repo", tmp_path / "work", tmp_path / "facts.json"
    e.repo.mkdir()
    e.served = []
    monkeypatch.setattr(mf, "check_media_urls", lambda urls: (e.served.append(dict(urls)), [])[1])
    monkeypatch.setattr(wc.time, "sleep", lambda s: None)
    e.write = lambda doc: mf.write_json(e.facts, doc)
    e.read = lambda: json.loads(e.facts.read_text(encoding="utf-8"))
    return e


def prepare(env, date=FRI, push=True):
    argv = ["prepare", "--date", date, "--facts", str(env.facts), "--work", str(env.work), "--repo", str(env.repo),
            "--now", f"{date}T09:05:00Z"]
    return wc.main(argv + ([] if push else ["--no-push"]))


def live(env):
    return wc.main(["live", "--date", FRI, "--facts", str(env.facts), "--work", str(env.work), "--repo", str(env.repo)])


def calendar_items(doc):
    return [i for i in doc["items"] if i["type"] == "earnings_week_calendar"]


def test_first_build_freezes_stages_and_keeps_the_item_out_until_live(env):
    env.write(facts_doc())
    assert prepare(env) == wc.EXIT_STAGED
    doc = env.read()
    assert calendar_items(doc) == [] and doc["counts"]["earnings_week_calendar"] == 0
    assert "staged, not yet live" in doc["reasons"]["earnings_week_calendar"]
    assert [i["item_id"] for i in doc["items"]] == [OTHER["item_id"]]
    rel = f"v/{FRI}/cards/{ITEM['item_id']}/calendar_4x5.png"
    assert (env.repo / rel).is_file() and (env.work / wc.FILES).read_text(encoding="utf-8").split() == [rel]
    state = json.loads((env.work / wc.STATE).read_text(encoding="utf-8"))
    assert state["status"] == "staged" and state["attempts"] == 1 and state["item"]["item_id"] == ITEM["item_id"]
    # live: Pages serves it -> the item comes back with its image as media[0]
    assert live(env) == 0
    assert env.served == [{f"{mf.PAGES_BASE}/{rel}": env.repo / rel}]
    doc = env.read()
    (it,) = calendar_items(doc)
    assert it["media"] == [{"url": f"{mf.PAGES_BASE}/{rel}", "kind": "image", "alt": wc.alt_text(ITEM)}]
    assert doc["counts"]["earnings_week_calendar"] == 1 and "earnings_week_calendar" not in doc["reasons"]
    assert doc["items"][0]["item_id"] == ITEM["item_id"]               # rank order kept (6.5 before 3.0)
    # the validator accepts a post with that image
    text = ("Biggest earnings next week, Oct 19–23 (confirmed dates):\n$META $TSLA $PG $LRCX $GE $PM $NFLX $TXN $RTX $TMO "
            "$IBM $AXP\nEvery day, before the open and after the close, is in the image.\nNot investment advice.")
    lk = it["page_url"].replace("{platform}", "x")
    draft = {"item_id": it["item_id"], "platform": "x", "text": text, "link": lk, "media_url": it["media"][0]["url"],
             "reply_text": f"Next week's full table, Oct 19 – Oct 23, with every confirmed date: {lk}"}
    assert gr.review(draft, doc) == ("APPROVE", [])
    assert fx.item_set(doc) != fx.item_set(facts_doc())                 # the compare publishes the attached image


def test_later_builds_get_the_frozen_item_back(env, monkeypatch):
    env.write(facts_doc())
    assert prepare(env) == wc.EXIT_STAGED and live(env) == 0
    renders = []
    monkeypatch.setattr(wc, "render_calendar", lambda item: renders.append(item) or (_ for _ in ()).throw(AssertionError))
    changed = copy.deepcopy(ITEM)
    changed.update(facts_text="a later build with other numbers", reporters_total=999)
    env.write(facts_doc(changed))
    assert prepare(env) == 0
    (it,) = calendar_items(env.read())
    assert it["facts_text"] == ITEM["facts_text"] and it["reporters_total"] == 205 and it["media"][0]["kind"] == "image"
    env.write(facts_doc(None))                                          # a build whose calendar read failed
    assert prepare(env) == 0
    doc = env.read()
    assert [i["item_id"] for i in calendar_items(doc)] == [ITEM["item_id"]] and "earnings_week_calendar" not in doc["reasons"]
    assert renders == []                                                # never rendered again


def test_staged_but_not_yet_served_stays_out(env, monkeypatch):
    env.write(facts_doc())
    assert prepare(env) == wc.EXIT_STAGED
    monkeypatch.setattr(mf, "check_media_urls", lambda urls: ["HTTP 404"])
    assert wc.main(["live", "--date", FRI, "--facts", str(env.facts), "--work", str(env.work), "--repo", str(env.repo),
                    "--timeout", "0"]) == 1
    assert calendar_items(env.read()) == []
    env.write(facts_doc())                                              # the next build: push + check again
    assert prepare(env) == wc.EXIT_STAGED and calendar_items(env.read()) == []


def test_two_failed_renders_mean_no_item_and_no_substitute(env, monkeypatch):
    calls = []

    def fail(item):
        calls.append(item["item_id"])
        raise wc.QAError("names 'A' and 'B' run together")

    monkeypatch.setattr(wc, "render_calendar", fail)
    env.write(facts_doc())
    assert prepare(env) == 0
    doc = env.read()
    assert calendar_items(doc) == [] and doc["reasons"]["earnings_week_calendar"] == (
        "calendar image failed: QA: names 'A' and 'B' run together (one more try on the next build)")
    env.write(facts_doc())
    assert prepare(env) == 0
    assert env.read()["reasons"]["earnings_week_calendar"] == "calendar image failed: QA: names 'A' and 'B' run together"
    env.write(facts_doc())
    assert prepare(env) == 0 and len(calls) == 2 == wc.MAX_ATTEMPTS     # no third render
    assert calendar_items(env.read()) == [] and not list(env.repo.rglob("*.png"))


def test_no_push_attaches_at_once(env):
    env.write(facts_doc())
    assert prepare(env, push=False) == 0
    (it,) = calendar_items(env.read())
    assert it["media"][0]["url"] == wc.png_url(FRI, ITEM["item_id"]) and not (env.work / wc.FILES).exists()
    assert prepare(env, push=False) == 0 and len(calendar_items(env.read())) == 1


def test_other_days_and_builds_without_the_item_leave_the_file_alone(env):
    thursday = facts_doc()
    thursday["date"] = "2026-10-15"
    env.write(thursday)
    before = env.facts.read_bytes()
    assert prepare(env, date="2026-10-15") == 0 and env.facts.read_bytes() == before
    env.write(facts_doc(None))
    before = env.facts.read_bytes()
    assert prepare(env) == 0 and env.facts.read_bytes() == before
    assert not (env.work / wc.STATE).exists()


def test_a_crash_takes_the_item_out(env, monkeypatch):
    env.write(facts_doc())
    monkeypatch.setattr(wc, "read_state", lambda work, date: (_ for _ in ()).throw(RuntimeError("disk")))
    assert prepare(env) == 0
    doc = env.read()
    assert calendar_items(doc) == [] and doc["reasons"]["earnings_week_calendar"].startswith("calendar image failed")
    env.write(facts_doc())
    assert wc.main(["strip", "--date", FRI, "--facts", str(env.facts)]) == 0 and calendar_items(env.read()) == []



def test_the_runner_hook():
    ps = (TOOLS / "daily_common.ps1").read_text(encoding="utf-8")
    body = ps[ps.index("function Publish-Facts"):ps.index("function Update-FactsIfDue")]
    assert (body.index("Invoke-WeekCalendar $Date $Work $tmp $Push $NowIso")
            < body.index("Invoke-CardReel $Date $Work $tmp $Push $NowIso") < body.index("'--compare-items', $dest, $tmp"))
    fn = ps[ps.index("function Invoke-WeekCalendar"):ps.index("function Invoke-CardReel")]
    assert "Fail " not in fn and "Push-Repo" not in fn                   # never ends the run
    assert "'week-calendar-files.txt'" in fn and f'"Week calendar $Date"' in fn
    assert fn.index("'push', '--quiet'") < fn.index("'live'")            # pushed before Pages is checked
    assert fn.index("$code -ne 10") < fn.index("'strip'")                # a crash takes the item out
