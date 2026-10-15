"""Playbook v2 draft lint (tools/draft_lint.py) and its grok_review integration. Run: python -m pytest tools/tests -q."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import draft_lint as dl  # noqa: E402
import grok_review as gr  # noqa: E402

DATE = "2026-10-15"
NOW = dt.datetime(2026, 10, 15, 11, 0, tzinfo=dt.timezone.utc)
REEL = f"https://asafb2k.github.io/rapidtradeview-media/v/{DATE}/cards/x/reel_9x16.mp4"


def item(iid, kind, ticker, tickers=None, **kw):
    d = {"item_id": f"{DATE}-{iid}", "type": kind, "ticker": ticker, "tickers": tickers or ([ticker] if ticker else []),
         "media": [{"url": f"https://www.rapidtradeview.trade/dashboard/{ticker}/opengraph-image", "kind": "image"}]}
    d.update(kw)
    return d


BNY = item("earnings-result-BNY-1", "earnings_result", "BNY", published_at="2026-10-15T10:32:35.879510+00:00",
           filed="2026-10-15")
PLD = item("earnings-result-PLD-1", "earnings_result", "PLD", published_at="2026-10-15T10:40:00Z",
           media=[{"url": "https://www.rapidtradeview.trade/dashboard/PLD/opengraph-image", "kind": "image"},
                  {"url": REEL, "kind": "reel"}])
GME = item("form4-buy-GME-1", "form4_buy", "GME", filed="2026-10-13")
NXPI = item("moves-like-NXPI-1", "moves_like", "NXPI", ["NXPI", "ON", "ADI", "MCHP"],
            peers=[{"ticker": "ON"}, {"ticker": "ADI"}, {"ticker": "MCHP"}])
ROUNDUP = item("earnings-tomorrow-roundup-LIST-1", "earnings_tomorrow_roundup", None, ["TRV", "TFC", "MTB", "CFG"])
CONGRESS = item("congress-trade-NVDA-1", "congress_trade", "NVDA", filed="2026-10-14")
FACTS = {"date": DATE, "items": [BNY, PLD, GME, NXPI, ROUNDUP, CONGRESS]}

# A playbook-clean moves_like post: 4 cashtags, figures up front, 25-60 words.
GOOD = ("$NXPI fell 2.4% on Oct 14 while its closest movers $ON (-4.3%), $ADI (-2.7%) and $MCHP (-3.9%) slid with it. "
        "Over 60 sessions their Sync scores run 72 to 75 out of 100, so chip names keep trading as one group. "
        "Not investment advice.")


def draft(text=GOOD, it=NXPI, **kw):
    d = {"item_id": it["item_id"], "platform": "x", "text": text, "reply_text": "",
         "media_url": it["media"][0]["url"]}
    d.update(kw)
    return d


def run(d, history=None, now=NOW, facts=FACTS):
    return dl.lint(d, facts, history, now)


def rules(res, kind=None, level=None):
    return [f["rule"] for f in res["findings"] if (kind is None or f["kind"] == kind) and (level is None or f["level"] == level)]


def post(minutes_before, text="$ON fell 4.3% on Oct 14. Not investment advice.", platform="x", kind=None):
    r = {"platform": platform, "posted_at": (NOW - dt.timedelta(minutes=minutes_before)).isoformat(), "text": text}
    if kind:
        r["kind"] = kind
    return r


def test_good_draft_is_clean():
    res = run(draft(), history=[post(180)])
    assert res["findings"] == [] and res["score"] == 0 and res["skipped"] == []


# cashtags [real] -------------------------------------------------------------------------------------------------

def test_cashtag_count():
    assert "cashtags" in rules(run(draft("$NXPI fell 2.4% on Oct 14 " + "word " * 25)), "warn", "real")
    six = "$NXPI $ON $ADI $MCHP $TRV $TFC fell 2.4% on Oct 14 " + "word " * 25
    res = run(draft(six))
    assert any(f["rule"] == "cashtags" and f["kind"] == "warn" and "6 cashtags" in f["message"] for f in res["findings"])


def test_cashtag_count_under_the_compliance_cap_is_a_note():
    text = "$BNY beat Q3: revenue $5.68B vs $5.56B consensus, adjusted EPS $2.37 vs $2.26. " + "word " * 15
    res = run(draft(text, BNY))
    f = next(f for f in res["findings"] if f["rule"] == "cashtags")
    assert f["kind"] == "note" and "compliance allows only" in f["message"]
    assert "cashtags" not in rules(res, "warn")


def test_cashtags_only_mega_or_index():
    roundup = draft("$AAPL $MSFT $SPY reported 3 beats on Oct 14 and Oct 15 " + "word " * 25, ROUNDUP)
    res = run(roundup)
    assert any("only mega-caps and index/ETF" in f["message"] and f["kind"] == "warn" for f in res["findings"])
    res = run(draft("$SPY $QQQ moved 1% and 2% " + "word " * 25, ROUNDUP))
    assert any("only index/ETF" in f["message"] for f in res["findings"])
    # a single-ticker item held to its mega-cap by compliance: a note
    res = run(draft("$NVDA sale of $1K to $15K disclosed Oct 14 " + "word " * 25, CONGRESS))
    assert any("only mega-caps" in f["message"] and f["kind"] == "note" for f in res["findings"])


def test_cashtag_must_be_supported_by_the_facts():
    ok = draft("$NXPI fell 2.4% with $TRV and $GME up 1% " + "word " * 25)   # other items' tickers count
    assert not any("not supported" in f["message"] for f in run(ok)["findings"])
    bad = run(draft("$NXPI fell 2.4% with $ZZZZ up 1% " + "word " * 25))
    assert any("not supported by the facts: $ZZZZ" in f["message"] and f["kind"] == "warn" for f in bad["findings"])


# numbers [real] --------------------------------------------------------------------------------------------------

def test_numbers():
    res = run(draft("$NXPI $ON moved together. " + "word " * 25))
    msgs = [f["message"] for f in res["findings"] if f["rule"] == "numbers"]
    assert any(m.startswith("0 concrete figures") for m in msgs) and any("first line" in m for m in msgs)
    late = run(draft("$NXPI and $ON trade as a pair.\nOver 60 sessions Sync ran 75 out of 100. " + "word " * 20))
    msgs = [f["message"] for f in late["findings"] if f["rule"] == "numbers"]
    assert msgs == ["no figure in the first line; lead with the headline number"]
    # filing names and cashtags are not figures
    assert dl.figures("$BPRE insider buy (Form 4) and an 8-K") == []


# macro [real] ----------------------------------------------------------------------------------------------------

def test_macro_only_and_predictive():
    res = run(draft("CPI came in at 3.1% vs 3.0% and the Fed is likely to hold; $SPY fell 1%. " + "word " * 15))
    msgs = [f["message"] for f in res["findings"] if f["rule"] == "macro"]
    assert any("macro-only" in m for m in msgs) and any("predictive framing" in m and "likely" in m for m in msgs)
    tied = run(draft("Bank stocks after CPI: $NXPI fell 2.4% and $ON 4.3% on Oct 14. " + "word " * 15))
    assert "macro" not in rules(tied)
    assert "macro" not in rules(run(draft("FedEx $GME $NXPI shipped 2 and 3 " + "word " * 25)))


# spacing [real] --------------------------------------------------------------------------------------------------

def test_spacing():
    res = run(draft(), history=[post(300), post(70)])
    assert any(f["rule"] == "spacing" and "70 min" in f["message"] for f in res["findings"])
    assert "spacing" not in rules(run(draft(), history=[post(130)]))
    assert "spacing" not in rules(run(draft(), history=[post(130), post(0)]))     # the post itself (same time)
    assert "spacing" not in rules(run(draft(), history=[post(30, platform="instagram")]))
    assert "spacing" not in rules(run(draft(), history=[post(30, kind="self_reply")]))
    # planned_at wins over --now
    later = draft(planned_at=(NOW + dt.timedelta(hours=2)).isoformat())
    assert "spacing" not in rules(run(later, history=[post(70)]))
    assert "spacing, question, link-24h (no --history)" in run(draft())["skipped"]


# length [likely] -------------------------------------------------------------------------------------------------

def test_length():
    short_one = run(draft("$NXPI $ON fell 2.4% and 4.3% on Oct 14. Not investment advice."))
    assert any(f["rule"] == "length" and f["level"] == "likely" for f in short_one["findings"])
    long_text = "$NXPI $ON fell 2.4% and 4.3%. " + "word " * 70
    assert "length" not in rules(run(draft(long_text)))                       # moves_like is not niche
    assert "length" in rules(run(draft(long_text.replace("$NXPI $ON", "$BNY"), BNY)), "warn")


# link [likely] ---------------------------------------------------------------------------------------------------

def test_link():
    linked = draft(GOOD + " https://www.rapidtradeview.trade/dashboard/NXPI")
    res = run(linked, history=[post(300)])
    assert any(f["rule"] == "link" and f["kind"] == "note" and "E2 arm?" in f["message"] for f in res["findings"])
    assert "link" not in rules(res, "warn")
    res = run(linked, history=[post(300, text="$ON 4.3% https://example.com/a")])
    assert "link" in rules(res, "warn")
    old = run(linked, history=[post(60 * 25, text="$ON 4.3% https://example.com/a")])
    assert "link" not in rules(old, "warn")
    assert "link" not in rules(run(draft(reply_text="https://www.rapidtradeview.trade/dashboard/NXPI")))


# mention [likely] ------------------------------------------------------------------------------------------------

def test_mention():
    res = run(draft(GOOD + " h/t @someone"))
    assert any(f["rule"] == "mention" and "@someone" in f["message"] for f in res["findings"])
    assert "mention" in rules(run(draft(reply_text="via @someone")))
    assert "mention" not in rules(run(draft(GOOD + " contact@rapidtradeview.trade")))


# question [likely] -----------------------------------------------------------------------------------------------

def test_question():
    q = draft(GOOD.replace("as one group.", "as one group. Coincidence?"))
    assert "question" in rules(run(q, history=[post(400), post(300, text="$ON down 4.3%: noise or signal?")]))
    assert "question" not in rules(run(q, history=[post(500, text="Why 4.3%?"), post(400), post(300)]))
    assert "question" not in rules(run(draft(), history=[post(400, text="Why?"), post(300, text="Why?")]))


# breaking [likely] -----------------------------------------------------------------------------------------------

def test_breaking():
    text = "JUST IN: $BNY beat Q3, revenue $5.68B vs $5.56B consensus. " + "word " * 20
    fresh = run(draft(text, BNY), now=dt.datetime(2026, 10, 15, 11, 0, tzinfo=dt.timezone.utc))
    assert "breaking" not in rules(fresh)
    stale = run(draft(text, BNY), now=dt.datetime(2026, 10, 15, 13, 0, tzinfo=dt.timezone.utc))
    assert any(f["rule"] == "breaking" and "published_at is 147 min old" in f["message"] for f in stale["findings"])
    dated = run(draft("BREAKING: Ryan Cohen bought $20.98M of $GME on Oct 13. " + "word " * 20, GME))
    assert any(f["rule"] == "breaking" and "can't verify freshness" in f["message"] for f in dated["findings"])
    assert "breaking" not in rules(run(draft("$NXPI breakingly 2.4% 3.1 " + "word " * 25)))
    assert "breaking" not in rules(run(draft("$NXPI fell 2.4%, just in time for 3 reports " + "word " * 25)))
    assert "breaking" in rules(run(draft("Breaking: $NXPI fell 2.4% and 3.1 " + "word " * 25)))


# video [likely] --------------------------------------------------------------------------------------------------

def test_video():
    text = "$PLD published Q3 2026 results: GAAP EPS $0.86. " + "word " * 25
    still = run(draft(text, PLD))
    assert any(f["rule"] == "video" and f["kind"] == "note" and "E1 arm?" in f["message"] for f in still["findings"])
    assert "video" not in rules(run(draft(text, PLD, media_url=REEL)))
    assert "video" not in rules(run(draft(text, PLD, platform="instagram")))
    assert "video" not in rules(run(draft(text, BNY)))


# earnings speed [likely] -----------------------------------------------------------------------------------------

def test_earnings_speed():
    text = "$BNY beat Q3: revenue $5.68B vs $5.56B consensus, adjusted EPS $2.37 vs $2.26. " + "word " * 15
    assert "earnings_speed" not in rules(run(draft(text, BNY)))                     # 27 min after published_at
    late = run(draft(text, BNY), now=dt.datetime(2026, 10, 15, 14, 0, tzinfo=dt.timezone.utc))
    f = next(f for f in late["findings"] if f["rule"] == "earnings_speed")
    assert f["kind"] == "note" and f["message"].startswith("207 min since the report appeared")
    first_seen = dict(BNY, first_seen_at="2026-10-15T13:30:00Z")              # first_seen_at wins over published_at
    facts = {"date": DATE, "items": [first_seen]}
    at_14 = dt.datetime(2026, 10, 15, 14, 0, tzinfo=dt.timezone.utc)
    assert "earnings_speed" not in rules(dl.lint(draft(text, first_seen), facts, None, at_14))


# list [likely] ---------------------------------------------------------------------------------------------------

def test_list_lines_in_niche_posts():
    grid = ("Reporting tomorrow, Oct 16:\n$TRV before open\n$TFC before open\n$MTB before open\n$CFG before open\n"
            "4 banks, 1 morning. " + "word " * 10)
    assert "list" in rules(run(draft(grid, ROUNDUP)), "warn")
    bullets = "Moves Like Oct 14:\n- $ON 75\n- $ADI 74\n- $MCHP 72\n- $NXPI 2.4% " + "word " * 20
    assert "list" not in rules(run(draft(bullets)))                                # moves_like is not niche
    assert "list" not in rules(run(draft(grid.replace("$CFG before open\n", ""), ROUNDUP)))


# self-thread substance [likely] ----------------------------------------------------------------------------------

def test_self_thread_substance():
    ok = draft(reply_text="All six names: https://www.rapidtradeview.trade/dashboard/NXPI")
    assert "self_thread" not in rules(run(ok))
    extra = run(draft(reply_text="Also: Sync 99 for $TXN"))
    assert any(f["rule"] == "self_thread" and "99" in f["message"] for f in extra["findings"])
    longer = run(draft("$NXPI fell 2.4% and $ON 4.3%. " + "w " * 25, reply_text="x" * 400))
    assert any(f["rule"] == "self_thread" and "longer than the post" in f["message"] for f in longer["findings"])


# hashtags [stop] -------------------------------------------------------------------------------------------------

def test_hashtags_note_is_not_scored():
    res = run(draft(GOOD + " #stocks #semis"), history=[post(300)])
    assert [(f["rule"], f["kind"], f["level"]) for f in res["findings"]] == [("hashtags", "note", "stop")]
    assert res["score"] == 0
    assert "hashtags" not in rules(run(draft(GOOD + " #semis")))


# score, output, CLI ----------------------------------------------------------------------------------------------

def test_score_counts_real_and_likely_warnings_only():
    res = run(draft("BREAKING @x $AAPL", ROUNDUP))
    warns = [f for f in res["findings"] if f["kind"] == "warn" and f["level"] in ("real", "likely")]
    assert res["score"] == len(warns) > 3
    lines = dl.answer_lines(res)
    assert lines[0] == f"NOTES (playbook v2): score {res['score']}, advisory"
    assert all(ln.startswith("- [") for ln in lines[1:])
    assert dl.answer_lines(run(draft(), history=[post(300)])) == []


def test_item_missing_runs_text_rules():
    res = dl.lint(dict(draft(), item_id="2026-10-15-nope"), FACTS, None, NOW)
    assert "item rules (item not in the facts)" in res["skipped"]


def test_parse_time():
    assert dl.parse_time("2026-10-15") is None
    assert dl.parse_time("2026-10-15T10:32:35.879510+00:00").minute == 32
    assert dl.parse_time("2026-10-15T10:32:35.8795101Z").second == 35
    assert dl.parse_time("2026-10-15 10:32:35+0200").hour == 8


def test_cli(tmp_path, capsys):
    f = tmp_path / "facts.json"
    f.write_text(json.dumps(FACTS), encoding="utf-8")
    d = tmp_path / "draft.json"
    d.write_text(json.dumps([draft(), draft("$NXPI moved. @x")]), encoding="utf-8")
    h = tmp_path / "hist.json"
    h.write_text(json.dumps({"posts": [post(30)]}), encoding="utf-8")
    assert dl.main(["--facts", str(f), "--draft", str(d), "--history", str(h), "--now", NOW.isoformat(),
                    "--format", "json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["score"] for r in out][0] == 1 and out[1]["score"] > 1
    assert dl.main(["--facts", str(tmp_path / "missing.json"), "--draft", str(d)]) == 2
    assert dl.main(["--facts", str(f), "--draft", str(d), "--now", "yesterday"]) == 2


def test_pages_copy_is_identical():
    pages = REPO / "analytics" / "draft_lint" / "draft_lint.py"
    assert pages.read_bytes().replace(b"\r\n", b"\n") == (TOOLS / "draft_lint.py").read_bytes().replace(b"\r\n", b"\n")


# grok_review integration -----------------------------------------------------------------------------------------

def test_grok_review_draft_cli_prints_notes(tmp_path, capsys):
    f = tmp_path / "facts.json"
    f.write_text(json.dumps(FACTS), encoding="utf-8")
    d = tmp_path / "d.json"
    d.write_text(json.dumps(draft("BREAKING $NXPI @x")), encoding="utf-8")
    rc = gr.main(["--draft", str(d), "--facts", str(f)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["verdict"] == "REJECT"                        # compliance unchanged (no disclaimer, link...)
    assert out["notes"][0].startswith("NOTES (playbook v2): score ")
    assert any("WARN mention" in n for n in out["notes"]) and any("WARN breaking" in n for n in out["notes"])


def test_grok_review_reply_line_appends_notes():
    row = {"id": 7, "item_id": NXPI["item_id"]}
    notes = gr.playbook_notes(draft("$NXPI moved. @x"), FACTS, NOW)
    body = gr.reply_line(row, draft(), "APPROVE", [], notes)
    assert body.splitlines()[0] == f"APPROVE 7 {NXPI['item_id']}" and body.splitlines()[1] == notes[0]
    rej = gr.reply_line(row, draft(), "REJECT", ["no text"], notes).splitlines()
    assert rej[0] == f"REJECT 7 {NXPI['item_id']}: no text" and rej[1].startswith("NOTES (playbook v2)")
    assert gr.reply_line(row, draft(), "APPROVE", [], []) == f"APPROVE 7 {NXPI['item_id']}"


def test_grok_review_lint_crash_is_shown_not_hidden(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(gr.dl, "lint", boom)
    assert gr.playbook_notes(draft(), FACTS, NOW) == ["NOTES (playbook v2): lint failed (RuntimeError)"]
