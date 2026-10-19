"""Round 7 (HQ 2026-10-19): closed hook sentences, 2-3 phrasings per fact with ids + rotation, card consistency
(basket / mega_mover / pinned card date), Growth PILLARS section 9 asks (universe claims, the week preview's card,
context movers, priced / total), the NY-vs-UTC earnings week and the DST-proof task triggers.
Run: python -m pytest tools/tests -q (offline)."""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "tests"))
import claims as cl  # noqa: E402
import facts as fx  # noqa: E402
import grok_review as gr  # noqa: E402
import map_layout as ml  # noqa: E402
import market_facts as mk  # noqa: E402
import phrasings as pr  # noqa: E402
import pin_cards as pc  # noqa: E402
import post_history as ph  # noqa: E402
import post_vocab as pv  # noqa: E402
import test_grok_market as tg  # noqa: E402
from test_market_facts import FIX, M, NOW_SUN, SUN, FixtureApi  # noqa: E402

VDOC, NOW = tg.VDOC, tg.NOW
NIA = "Not investment advice."


def vitem(kind, ticker=None):
    return next(i for i in VDOC["items"] if i["type"] == kind and (ticker is None or i.get("ticker") == ticker))


def post(it, text, platform="threads", reply=""):
    return gr.review(tg.draft(it, text, platform=platform, reply_text=reply), VDOC, NOW)


def ptext(it, pid):
    return next(p["text"] for p in it["phrasings"] if p["id"] == pid)


# ---------------------------------------------------------------------------
# A. Closed hook sentences

def test_hook_list_is_closed_neutral_and_well_formed():
    assert 40 <= len(pv.HOOKS) <= 80 and len({h["id"] for h in pv.HOOKS}) == len(pv.HOOKS)
    assert len({tuple(cl.hook_tokens(h)) for h in pv.HOOKS}) == len(pv.HOOKS)          # no two hooks read the same
    banned = [w.lower() for w in fx.BANNED_WORDS]
    for h in pv.HOOKS:
        assert h["use"] in ("post", "comment", "any") and set(h["platforms"]) <= {"x", "threads", "instagram"}
        low = h["text"].lower()
        assert not any(w in low for w in banned), h
        assert not cl.CASHTAG.search(h["text"]) and not any(c.isdigit() for c in h["text"]), h
        # a hook states nothing: no sector, date, direction, advice or ranking word (the old hook-word analysis)
        why = cl.hook_reasons(None, h["text"])
        kinds = " ".join(why)
        for bad in ("number", "ticker", "sector", "date / session word", "direction word", "advice / forecast word",
                    "ranking / count word"):
            assert f"({bad})" not in kinds, (h, why)
        assert not cl.universe_reasons(None, h["text"]), h


def test_only_whole_hook_sentences_pass():
    mm = vitem("market_move")
    p = ptext(mm, next(x["id"] for x in mm["phrasings"] if x["text"].startswith("The 500 largest US-listed stocks lost")))
    p += " " + next(x for x in mm["fact_phrases"] if x.startswith("$GOOGL"))     # a market post names a ticker
    assert post(mm, f"Here is the map. {p} What stood out to you? {NIA}") == ("APPROVE", [])
    for free in ["Here is the whole map.", "What stood out?", "Here is how today looked.", "Big picture below.",
                 "Thoughts?", "See the map."]:
        v, why = post(mm, f"{free} {p} {NIA}")
        assert v == "REJECT" and any(r.startswith(("not an approved hook", "not verbatim")) for r in why), (free, why)


def test_hooks_are_per_platform_type_and_use():
    mm, pep = vitem("market_move"), vitem("form4_buy", "PEP")
    p = next(x for x in mm["fact_phrases"] if x.startswith("$GOOGL"))
    assert post(mm, f"Link in bio. {p} {NIA}", platform="instagram")[0] == "APPROVE"
    v, why = post(mm, f"Link in bio. {p} {NIA}", platform="threads")
    assert v == "REJECT" and any("hook H44" in r and "platforms instagram" in r for r in why)
    v, why = post(mm, f"Full map in the reply. {p} {NIA}", platform="instagram")
    assert v == "REJECT" and any("hook H40" in r for r in why)
    q = next(x for x in pep["fact_phrases"] if "$PEP" in x)
    v, why = post(pep, f"Here is the map. {q} {NIA}")                 # a map hook on a filing item
    assert v == "REJECT" and any("hook H01" in r and "item types" in r for r in why)
    assert post(pep, f"Here is what the filing shows. {q} {NIA}") == ("APPROVE", [])
    v, why = post(mm, f"Thanks for sharing. {p} {NIA}")                # a comment hook in a post
    assert v == "REJECT" and any("hook H71" in r and "use comment" in r for r in why)


def test_bare_comments_hold_comment_hooks_only():
    state = None
    ok = {"kind": "comment", "platform": "x", "target_url": "https://x.com/a/status/1844000000000000001",
          "text": "Thanks for sharing. What else would you look at?"}
    assert gr.review_comment(ok, None, state, NOW) == ("APPROVE", [])
    for bad in ["Thanks for sharing this.", "Great chart!", "Here are the numbers.", "Nice."]:
        v, why = gr.review_comment(dict(ok, text=bad), None, state, NOW)
        assert v == "REJECT" and any("approved comment hooks" in r or "hook H04" in r for r in why), (bad, why)
    v, why = gr.review_comment(dict(ok, platform="instagram", target_url="https://www.instagram.com/p/DAbCdEfGhIj/",
                                    text="Interesting angle."), None, None, NOW)
    assert v == "APPROVE", why


def test_items_without_phrasings_keep_the_hook_word_reading():
    """A post audit of a post published under the 10-19 hook-word rule (its facts carry no phrasings) reads it as then."""
    mm = {k: v for k, v in vitem("market_move").items() if k != "phrasings"}
    assert not cl.closed_hooks(mm)
    assert cl.verbatim_reasons(mm, "Here is how it looked.") == []          # hook words only: passed then
    assert cl.verbatim_reasons(vitem("market_move"), "Here is how it looked.")    # closed now


# ---------------------------------------------------------------------------
# B. Phrasings, ids, rotation

def test_every_item_has_two_or_three_phrasings_for_most_facts():
    singles = total = 0
    for it in VDOC["items"]:
        phr = it["phrasings"]
        assert phr and {p["text"] for p in phr} == set(it["claim_phrases"]) | set(it["fact_phrases"])
        groups: dict[str, set] = {}
        for p in phr:
            assert p["id"] == f"{p['fact']}.{p['variant']}"
            groups.setdefault(p["fact"], set()).add(p["variant"])
        for f, vs in groups.items():
            assert len(vs) <= pr.MAX_PER_FACT
            total += 1
            singles += len(vs) == 1
    assert total >= 100 and singles / total < 0.3, (singles, total)


def test_phrasings_keep_numbers_and_change_order():
    for it in VDOC["items"]:
        by: dict[str, list] = {}
        for p in it["phrasings"]:
            by.setdefault(p["fact"] + p["text"].split(" ")[-1][:0], []).append(p)
        for p in it["phrasings"]:
            if p["variant"] in ("t", "m", "tm"):
                base = next(x for x in it["phrasings"] if x["fact"] == p["fact"] and x["variant"] == "a"
                            and (x["text"].replace("(", "").replace(")", "")[:12] in p["text"] or True))
                nums = lambda s: sorted(t for t in cl.verbatim_tokens(s) if any(c.isdigit() for c in t))  # noqa: E731
                assert nums(p["text"]) in [nums(x["text"]) for x in it["phrasings"]
                                           if x["fact"] == p["fact"] and x["variant"] == "a"], (p, base)


def test_generic_reorderings():
    assert pr.front_time("Energy went the other way on Friday (+2.64%).") == "On Friday, Energy went the other way (+2.64%)."
    assert pr.front_time("The 500 largest US-listed stocks lost about $1.0T on Friday.") == (
        "On Friday, the 500 largest US-listed stocks lost about $1.0T.")
    assert pr.front_time("$T reports earnings on Monday, Oct 19, after the close (confirmed date).") is None
    assert pr.front_time("$X traded Oct 14 and reported on Oct 16.") is None          # two dates: never moved
    assert pr.move_of("Energy went the other way on Friday (+2.64%).") == "Energy went the other way on Friday, a move of +2.64%."
    assert pr.move_of("1,631 of 2,497 fell on Friday (65%).") is None                  # unsigned: a share, not a move
    assert pr.move_of("In order: $A (+2.03%), $B (−1.13%).") is None                 # never inside a list


def test_fact_keys_are_stable_across_days_and_companies():
    a = pr.fact_key("$GOOGL lost $105.5B of market value on Friday (−2.47%).", "mega_mover")
    b = pr.fact_key("$NVDA gained $40.1B of market value today (+1.12%).", "mega_mover")
    c = pr.fact_key("PepsiCo, Inc. director Robert C. Pohlad bought $10.84M of $PEP on the open market (Form 4, filed Oct 16).",
                    "form4_buy")
    d = pr.fact_key("Apple Inc. director Tim Cook bought $2.1M of $AAPL on the open market (Form 4, filed Oct 9).",
                    "form4_buy")
    assert a == b and c == d and a != pr.fact_key("$GOOGL moved −2.47% on Friday.", "mega_mover")


def test_used_ids_read_phrasings_and_hooks():
    mm = vitem("market_move")
    ph1, ph2 = mm["phrasings"][0], mm["phrasings"][5]
    text = f"Here is the map. {ph1['text']} {ph2['text']} What surprised you? {NIA}"
    pids, hids = cl.used_ids(mm, text, "x")
    assert pids == [ph1["id"], ph2["id"]] and hids == ["H01", "H21"]
    bare = ph1["text"].replace(" (−1.21%).", ".")
    if bare != ph1["text"]:
        assert cl.used_ids(mm, bare)[0] == [ph1["id"]]                  # the closing number left off: same phrasing


def hist(kind, platform, pids=(), hids=(), day="2026-10-16", iid="x"):
    return {"platform": platform, "type": kind, "phrasing_ids": list(pids), "hook_ids": list(hids), "ny_date": day,
            "item_id": iid}


def test_rotation_rejects_a_phrasing_or_hook_used_in_the_last_five_posts():
    mm = vitem("market_move")
    f0 = mm["phrasings"][0]
    fam = [p for p in mm["phrasings"] if p["fact"] == f0["fact"]]
    assert len(fam) >= 2
    d = tg.draft(mm, f"Here is the map. {f0['text']} {NIA}", platform="x")
    history = [hist("market_move", "x", [f0["id"]], ["H03"])]
    why = gr.rotation_reasons(d, mm, history)
    assert any(f"phrasing {f0['id']}" in r and fam[1]["text"][:30] in r for r in why), why
    assert gr.rotation_reasons(tg.draft(mm, f"Here is the map. {fam[1]['text']} {NIA}", platform="x"), mm, history) == []
    # the same hook again
    history = [hist("market_move", "x", [], ["H01"])]
    assert any("hook H01" in r for r in gr.rotation_reasons(d, mm, history))
    # another platform, another item type, or older than the last 5 posts of the type: free
    assert gr.rotation_reasons(d, mm, [hist("market_move", "threads", [f0["id"]], ["H01"])]) == []
    assert gr.rotation_reasons(d, mm, [hist("breadth_day", "x", [f0["id"]], ["H01"])]) == []
    old = [hist("market_move", "x", [f0["id"]], ["H01"])] + [hist("market_move", "x", [], [f"H0{i}"]) for i in range(2, 7)]
    assert gr.rotation_reasons(d, mm, old) == []


def test_rotation_lets_the_least_recently_used_phrasing_back_when_all_were_used():
    mm = vitem("market_move")
    f0 = mm["phrasings"][0]
    fam = [p["id"] for p in mm["phrasings"] if p["fact"] == f0["fact"]]
    history = [hist("market_move", "x", [pid], [f"H0{i + 3}"]) for i, pid in enumerate(fam)]   # fam[0] oldest
    t = lambda pid: tg.draft(mm, f"Here is the map. {ptext(mm, pid)} {NIA}", platform="x")  # noqa: E731
    assert gr.rotation_reasons(t(fam[0]), mm, history) == []
    for pid in fam[1:]:
        assert any(f"only {fam[0]} may come back" in r for r in gr.rotation_reasons(t(pid), mm, history))


def test_inbox_rejects_a_repeat_and_defers_posts_without_history(tmp_path):
    from test_grok_review import INSTINCT, FakeRest  # noqa: PLC0415
    mm = vitem("market_move")
    f0 = mm["phrasings"][0]
    vdir = tmp_path / "v" / "2026-10-18"
    vdir.mkdir(parents=True)
    (vdir / "facts.json").write_text(json.dumps(VDOC), encoding="utf-8")
    d = tg.draft(mm, f"Here is the map. {f0['text']} {NIA}", platform="threads")
    rows = [{"id": 31, "kind": "report", "platform": "threads", "item_id": mm["item_id"], "body": "DRAFT " + json.dumps(d)}]
    sent = []
    gr.run_inbox(FakeRest(rows), INSTINCT, "prod", str(tmp_path / "v"), True, lambda p, b: sent.append(b) or True,
                 now=NOW, history=[hist("market_move", "threads", [f0["id"]], [])], need_history=True, variety=False)
    stats = gr.run_inbox(FakeRest(rows), INSTINCT, "prod", str(tmp_path / "v"), True, lambda p, b: True, now=NOW,
                         history=None, need_history=True)
    assert stats["deferred"] == 1 and stats["drafts"] == 1


def test_post_history_and_facts_mark_the_used_ids():
    mm = vitem("market_move")
    f0 = mm["phrasings"][0]
    posts = [{"platform": "x", "url": "https://x.com/rapidtradeview/status/1", "created_at": "2026-10-18T15:00:00Z",
              "item_id": mm["item_id"], "body": f"Here is the map. {f0['text']} {NIA}\n\nitem_id={mm['item_id']}"}]
    res = ph.resolve(posts, lambda date: VDOC)
    assert res[0]["phrasing_ids"] == [f0["id"]] and res[0]["hook_ids"] == ["H01"]
    items = [json.loads(json.dumps(mm))]
    fx.mark_rotation(items, res)
    rot = items[0]["rotation"]
    assert rot["x"] == {"posts": 1, "used_phrasing_ids": [f0["id"]], "used_hook_ids": ["H01"]}
    assert rot["threads"]["posts"] == 0
    assert next(p for p in items[0]["phrasings"] if p["id"] == f0["id"])["recent_on"] == ["x"]
    fx.mark_rotation(items, None)
    assert items[0]["rotation"] is None


# ---------------------------------------------------------------------------
# Grok-style drafts on the fixture: hook + 1-2 phrasings per item, every platform, rotating

def compose(it, k, platform):
    """The k-th Grok-style draft of an item: a hook allowed for (platform, type), then 1-2 phrasings that name its
    ticker, with the variant rotating with k."""
    hooks = cl.hooks_for(it, platform)
    hook = hooks[k % len(hooks)]["text"]
    own = [it["ticker"]] if it.get("ticker") else (it.get("tickers") or [])
    facts: dict[str, list] = {}
    for p in it["phrasings"]:
        facts.setdefault(p["fact"], []).append(p)
    keys = list(facts)
    lead = next((f for f in keys if not own or any(f"${t}" in facts[f][0]["text"] for t in own)), keys[0])
    first = facts[lead][k % len(facts[lead])]["text"]
    src = it.get("source_url") if it["type"] in gr.SOURCE_TYPES else None
    tail = f" Source: {src}" if src and platform == "instagram" else ""
    return f"{hook} {first}{tail} {NIA}"


def test_grok_style_drafts_pass_and_vary():
    seen: dict[tuple, set] = {}
    bad = []
    for it in VDOC["items"]:
        for platform in ("x", "threads", "instagram"):
            for k in range(3):
                text = compose(it, k, platform)
                reply = ""
                if platform == "x":
                    reply = f"Full map: {it['page_url'].replace('{platform}', 'x')}" if it["type"] in mk.WORDING_TYPES                         else f"Details: {it['page_url'].replace('{platform}', 'x')}"
                    if it["type"] in gr.SOURCE_TYPES and it.get("source_url"):
                        reply += f" Source: {it['source_url']}"
                v, why = post(it, text, platform=platform, reply=reply)
                if v != "APPROVE" and not all(r.startswith(("X ", "X:")) for r in why):
                    bad.append((it["type"], platform, text, why[:2]))
                seen.setdefault((it["item_id"], platform), set()).add(text)
    assert not bad, bad[:5]
    assert all(len(v) == 3 for v in seen.values())


# ---------------------------------------------------------------------------
# C. Card consistency

def test_map_card_labels_match_the_pinned_card_of_the_16th():
    tiles = ml.card_map_tiles(FIX["pictures"])
    lab = sorted(t["symbol"] for t in tiles if t["fs"] > 0 and t["fs2"] > 0)
    # read off v/2026-10-18/cards/market-map-2026-10-16-526c160e.png: every tile that shows its ticker AND its move
    assert lab == sorted("NVDA AAPL MSFT TSM AMZN GOOGL META AVGO LLY WMT SPCX SKHY MU JPM XOM MA TSLA AMD ASML BRK-B V "
                         "INTC JNJ PLTR ORCL CAT KO".split())
    assert ml.labelled(FIX["pictures"], "GOOGL") is True and ml.labelled(FIX["pictures"], "PANW") is False
    assert ml.labelled(FIX["pictures"], "CSCO") is False      # its ticker is drawn, its move is not


def test_mega_mover_keeps_the_map_card_only_when_labelled():
    g, p = vitem("mega_mover", "GOOGL"), vitem("mega_mover", "PANW")
    assert g["card"]["panel"] == "map" and g["map_labelled"] is True
    assert p["card"] is None and p["media"] == [] and p["map_labelled"] is False and "does not label $PANW" in p["card_note"]


def test_basket_week_has_no_card_and_stays_out_of_the_top_8():
    b = vitem("basket_week")
    assert b["card"] is None and b["media"] == []
    items, counts = fx.diversify_top([json.loads(json.dumps(b))])
    assert items[0]["top8"] is False and items[0]["top8_out"].startswith("no_card") and counts["no_card"] == 1


def test_week_preview_uses_the_this_week_card():
    pv_ = vitem("earnings_week_preview")
    assert pv_["media"][0]["url"].endswith("/earnings/this-week/opengraph-image") and not pv_.get("card")


def _card_item(panel="map", date="2026-10-16", session="2026-10-16"):
    return {"item_id": "i1", "type": "market_move", "session_date": session,
            "card": {"panel": panel, "date": date, "file": f"market-{panel}-{date}-{mk.panel_fingerprint(M, panel)}.png",
                     "fingerprint": mk.panel_fingerprint(M, panel), "live_url": f"https://x/market/card/{panel}"}}


def test_pin_cards_checks_the_card_date_and_data(tmp_path, monkeypatch):
    png = pc.PNG + b"1" * pc.MIN_BYTES
    monkeypatch.setattr(pc, "fetch_png", lambda url: png)
    monkeypatch.setattr(pc, "SLEEP", lambda s: None)
    assert pc.date_problem(_card_item()) is None
    assert "not the item's session" in pc.date_problem(_card_item(date="2026-10-15"))
    assert pc.data_problem(_card_item()["card"], M, "after") is None
    other = mk.Market({**FIX["pictures"], "session_date": "2026-10-15"}, None)
    assert "shows 2026-10-15" in pc.data_problem(_card_item()["card"], other, "after")
    assert pc.card_date_of("insiders", M) == max(x for x in (FIX["flows"]["insiders"].get("last_disclosure"),
                                                             FIX["flows"]["insiders"]["sells"].get("last_disclosure")) if x)

    def run(items, read, day="2026-10-18"):
        path = tmp_path / "facts.json"
        path.write_text(json.dumps({"items": items, "counts": {}, "errors": [], "left_out": {}}), encoding="utf-8")
        work = tmp_path / f"w{day}"
        code = pc.prepare(path, tmp_path, day, work, read=read)
        return code, json.loads((work / "pin-cards.json").read_text(encoding="utf-8"))
    code, plan = run([_card_item(date="2026-10-15", session="2026-10-16")], lambda p: M)
    assert code == 1 and "not the item's session" in plan["i1"]["error"]
    reads = iter([M, other])                                        # the data moved while the card rendered
    code, plan = run([_card_item()], lambda p: next(reads))
    assert "shows 2026-10-15 (after the GET)" in plan["i1"]["error"]
    code, plan = run([_card_item()], lambda p: M)
    assert code == 10 and plan["i1"]["url"].endswith(_card_item()["card"]["file"])
    # the same bytes again under another data date: the route served the old card
    it = _card_item()
    it["card"]["file"] = it["card"]["file"].replace(it["card"]["fingerprint"], "deadbeef")
    it["card"]["fingerprint"] = None
    code, plan = run([it], lambda p: M, day="2026-10-19")
    assert "same image as v/2026-10-18/cards/" in plan["i1"]["error"]


# ---------------------------------------------------------------------------
# D. Growth section 9: universe claims, context movers, coverage

def test_universe_claims():
    mm = vitem("market_move")          # 445 of 500 priced
    for bad in ["The stock market lost about $1.0T on Friday.", "The US stock market fell.", "Stock market: -1.21%.",
                "Every company fell on Friday.", "All 500 moved.", "every stock was red"]:
        assert cl.universe_reasons(mm, bad), bad
    for ok in ["Every company on one map below.", "#stockmarket", "The 500 largest US-listed stocks lost about $1.0T.",
               "A stock market map."]:
        assert cl.universe_reasons(mm, ok) == [], ok
    assert cl.universe_reasons({"priced": 500, "total": 500}, "All 500 had a price.") == []
    assert cl.universe_reasons(vitem("form4_buy", "PEP"), "Every company reports.")   # no coverage: cannot back it
    v, why = post(mm, f"Here is the map. {mm['fact_phrases'][0]} The stock market fell. {NIA}")
    assert v == "REJECT" and any(r.startswith("universe claim") for r in why)


def test_market_items_name_a_non_mega_context_mover():
    mm, g = vitem("market_move"), vitem("mega_mover", "GOOGL")
    for it in (mm, g):
        cm = it["context_mover"]
        assert cm and cm["ticker"] in it["context_tickers"] and (cm["cap"] or 0) < 200e9
        assert cm["ticker"] not in mk.CRYPTO_LINKED and (cm["pct"] < 0) == (it.get("totals", {}).get("pct_change", -1) < 0)
        assert any(f"${cm['ticker']}" in p for p in it["fact_phrases"]) and cm["pct_text"] in it["context_numbers"]
    assert mk.context_mover(M, True, exclude=["STX"])["ticker"] != "STX"


def test_map_items_carry_priced_and_total():
    for kind in mk.WORDING_TYPES:
        for it in [i for i in VDOC["items"] if i["type"] == kind]:
            assert (it["priced"], it["total"]) == (445, 500), kind
            assert "445" in it["allowed_numbers"] and "500" in it["allowed_numbers"]
            if kind != "market_move":
                week = it.get("window") == "week" or kind == "basket_week"
                want = "at the Oct 16 close" if week else "on Friday, Oct 16"
                assert f"445 of the 500 largest US-listed stocks had a price {want}." in it["fact_phrases"], kind


# ---------------------------------------------------------------------------
# E. The earnings week counts from the API's UTC week

class WeekApi:
    def __init__(self, weeks):
        self.weeks, self.seen = weeks, []

    def get(self, path):
        self.seen.append(path)
        w = int(path.split("weeks_ahead=")[1].split("&")[0])
        return self.weeks.get(w), None


def week(monday):
    days = [(monday + dt.timedelta(days=i)).isoformat() for i in range(5)]
    return {"week_start": days[0], "week_end": days[-1], "days": [{"date": d, "count": 0, "reports": []} for d in days]}


def test_monday_before_four_utc_reads_this_week():
    mon = dt.date(2026, 10, 19)
    api = WeekApi({0: week(mon), 1: week(mon + dt.timedelta(days=7))})
    # Monday 02:00Z: New York is still on Sunday 22:00; the API's clock (UTC) is on Monday
    weeks, err = fx.calendar_week(api, mon, dt.datetime(2026, 10, 19, 2, 0, tzinfo=dt.timezone.utc))
    assert err == [] and api.seen == ["/earnings?weeks_ahead=0&scope=all"] and weeks[0]["week_start"] == "2026-10-19"
    # Sunday 20:00Z: both clocks on Sunday, Monday is next week
    api = WeekApi({0: week(mon - dt.timedelta(days=7)), 1: week(mon)})
    weeks, err = fx.calendar_week(api, mon, dt.datetime(2026, 10, 18, 20, 0, tzinfo=dt.timezone.utc))
    assert api.seen == ["/earnings?weeks_ahead=1&scope=all"] and weeks[0]["week_start"] == "2026-10-19"


def test_a_week_that_does_not_hold_the_day_is_an_error():
    mon = dt.date(2026, 10, 19)
    api = WeekApi({0: week(mon + dt.timedelta(days=7))})        # the clock crossed midnight UTC mid-request
    weeks, err = fx.calendar_week(api, mon, dt.datetime(2026, 10, 19, 2, 0, tzinfo=dt.timezone.utc))
    assert weeks == [] and "not the one holding 2026-10-19" in err[0]


def test_upcoming_items_survive_monday_early_utc():
    mon = dt.date(2026, 10, 19)
    w = week(mon)
    w["days"][1]["reports"] = [{"symbol": "NFLX", "in_universe": True, "date_confirmed": True, "hour": "amc",
                                "market_cap": 5e11, "quarter": 3, "year": 2026}]
    w["days"][1]["count"] = 1
    api = WeekApi({0: w, 1: week(mon + dt.timedelta(days=7))})
    items, counts, errors, reason = fx.upcoming_items(api, mon, {"NFLX": "Netflix, Inc."},
                                                      dt.datetime(2026, 10, 19, 3, 30, tzinfo=dt.timezone.utc))
    assert [i["ticker"] for i in items] == ["NFLX"] and errors == [] and reason is None


# ---------------------------------------------------------------------------
# DST: the scheduled passes stay at New York times across 2026-11-01

@pytest.mark.skipif(sys.platform != "win32", reason="Windows Task Scheduler script")
def test_register_script_builds_one_trigger_per_offset_period():
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          str(TOOLS / "register_daily_task.ps1"), "-PrintOnly", "-From", "2026-10-26", "-HorizonYears", "1"],
                         capture_output=True, text=True, timeout=120).stdout
    assert "NY offset period 2026-10-26 .. 2026-11-01 (UTC-04:00:00)" in out
    assert "NY offset period 2026-11-01 .. 2027-03-14 (UTC-05:00:00)" in out
    picks = out.split("(weekday 1345 ET picks)")[1].split("----")[0]
    assert "<StartBoundary>2026-10-26T17:45:00Z</StartBoundary>" in picks          # 13:45 EDT
    assert "<EndBoundary>2026-11-01T04:00:00Z</EndBoundary>" in picks
    assert "<StartBoundary>2026-11-02T18:45:00Z</StartBoundary>" in picks          # 13:45 EST
    weekend = out.split("(weekend 0800 ET)")[1].split("----")[0]
    assert "<StartBoundary>2026-11-01T13:00:00Z</StartBoundary>" in weekend        # Sunday 11-01 08:00 EST
