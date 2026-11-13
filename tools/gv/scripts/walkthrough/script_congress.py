"""The voice script of "How to track Congress stock trades (free)", built from today's captures.

Every number, date, name, ticker and amount in a sentence is read from a capture sidecar (capture_walkthrough.py) by a
rule below, never typed by hand; each read value carries its proof (the capture, the line as the page drew it, its box).
A rule that does not find its value raises ScriptError: the video is not built (No Fallbacks).

    build(screens_dir) -> {"sentences": [...], "facts": [...], "captures": {...}}

A sentence:
    id, section, text (the caption, as written on screen), say (what the voice reads: tickers spelled, months in full,
    ranges with "to"), facts (the ids of the facts it states), view (where the camera looks: capture, zoom, the box it
    centres on), outline (a box outlined in place, or None), cursor (a link the cursor goes to and clicks, or None),
    pause (s of silence after it).
Boxes are [x, y, w, h] in the capture's document CSS px.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MONTHS = {"Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April", "May": "May", "Jun": "June",
          "Jul": "July", "Aug": "August", "Sep": "September", "Oct": "October", "Nov": "November", "Dec": "December"}
MONTH_NUM = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]


class ScriptError(RuntimeError):
    pass


# ---------------------------------------------------------------- reading the captures

class Cap:
    def __init__(self, path: Path):
        self.path = path
        self.d = json.loads(path.read_text(encoding="utf-8"))
        self.name = self.d["name"]
        self.lines = sorted(self.d["lines"], key=lambda ln: (round(ln["y"]), ln["x"]))

    def find(self, text: str, *, exact: bool = True, y0: float = -1e9, y1: float = 1e9, x0: float = -1e9) -> dict:
        for ln in self.lines:
            if y0 <= ln["y"] <= y1 and ln["x"] >= x0 and (ln["t"] == text if exact else text in ln["t"]):
                return ln
        raise ScriptError(f"{self.name}: no line {'=' if exact else '~'}{text!r} in y {y0:.0f}..{y1:.0f}")

    def table(self, heading: str, headers: list[str], anchor: str, rows: int = 60, heading_exact: bool = True) -> list[dict]:
        """A table under `heading`: its header cells (found by text within 160 px under the heading) give the column
        x positions; a row starts at each line of the `anchor` column. Returns [{col: [lines]}]."""
        h = self.find(heading, exact=heading_exact)
        cols = []
        for name in headers:
            c = self.find(name, y0=h["y"], y1=h["y"] + 160)
            cols.append((name, c["x"], c["y"] + c["h"]))
        top = max(c[2] for c in cols)
        xs = sorted(cols, key=lambda c: c[1])

        def col_of(ln):
            best = None
            for name, x, _ in xs:
                if ln["x"] >= x - 3:
                    best = name
            return best

        body = [ln for ln in self.lines if ln["y"] > top + 2]
        ax = dict((c[0], c[1]) for c in cols)[anchor]
        nxt = [c[1] for c in xs if c[1] > ax + 3]
        ax1 = min(nxt) if nxt else 1e9
        anchors = [ln for ln in body if ax - 3 <= ln["x"] < ax1 - 3 and col_of(ln) == anchor]
        # one anchor per row: the first line of each new row (a second line of the same cell is within 26 px)
        starts = []
        for ln in anchors:
            if not starts or ln["y"] - starts[-1]["y"] > 26:
                starts.append(ln)
            if len(starts) > rows:
                break
        out = []
        for i, st in enumerate(starts[:rows]):
            y_a = st["y"] - 14
            y_b = starts[i + 1]["y"] - 14 if i + 1 < len(starts) else st["y"] + 40
            row = {name: [] for name in headers}
            for ln in body:
                if y_a <= ln["y"] < y_b:
                    c = col_of(ln)
                    if c:
                        row[c].append(ln)
            row["_box"] = union([ln for v in row.values() if isinstance(v, list) for ln in v])
            out.append(row)
        return out


def union(lines: list[dict], pad: float = 0.0) -> list[float]:
    if not lines:
        raise ScriptError("an empty box")
    x0 = min(ln["x"] for ln in lines) - pad
    y0 = min(ln["y"] for ln in lines) - pad
    x1 = max(ln["x"] + ln["w"] for ln in lines) + pad
    y1 = max(ln["y"] + ln["h"] for ln in lines) + pad
    return [round(x0, 1), round(y0, 1), round(x1 - x0, 1), round(y1 - y0, 1)]


def text_of(lines: list[dict]) -> str:
    return " ".join(ln["t"] for ln in lines).strip()


# ---------------------------------------------------------------- spoken forms

def say_date(s: str) -> str:
    """"Nov 11, 2026" -> "November 11, 2026"; "2026-10-07" -> "October 7, 2026"."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{MONTH_NUM[int(m.group(2)) - 1]} {int(m.group(3))}, {m.group(1)}"
    m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", s)
    if m and m.group(1) in MONTHS:
        return f"{MONTHS[m.group(1)]} {m.group(2)}, {m.group(3)}"
    raise ScriptError(f"not a date: {s!r}")


def show_date(s: str) -> str:
    """The caption form of a date: as the page writes it, ISO dates as "Oct 7, 2026"."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{MONTH_NUM[int(m.group(2)) - 1][:3]} {int(m.group(3))}, {m.group(1)}"
    return s


def short(s: str, year: str) -> str:
    """A date as the caption shows it, without the year when it is the recording's year: "Oct 7" / "Dec 24, 2025"."""
    d = show_date(s)
    return d[:-6] if d.endswith(f", {year}") else d


def say_short(s: str, year: str) -> str:
    d = say_date(s)
    return d[:-6] if d.endswith(f", {year}") else d


def say_day(s: str) -> str:
    """"Nov 12" -> "November 12"."""
    m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{1,2})", s)
    if not m or m.group(1) not in MONTHS:
        raise ScriptError(f"not a day: {s!r}")
    return f"{MONTHS[m.group(1)]} {m.group(2)}"


def say_ticker(t: str) -> str:
    return " ".join(t.replace(".", " "))


def say_amount(a: str) -> str:
    """"$1,001–$15,000" -> "$1,001 to $15,000" (the engine reads dollar figures well)."""
    if not re.fullmatch(r"\$[\d,]+(–\$[\d,]+)?", a):
        raise ScriptError(f"not an amount range: {a!r}")
    return a.replace("–", " to ")


def say_name(n: str) -> str:
    return re.sub(r",? Jr\.$", " Junior", n).replace(" III", " the third")


# ---------------------------------------------------------------- the script

SECTIONS = [  # (id, chapter title)
    ("answer", "The free Congress trades tracker"),
    ("latest", "How to read a disclosed trade"),
    ("lists", "Most active members and most bought stocks"),
    ("member", "One member's trades"),
    ("stock", "Open a stock: price and Smart Money"),
    ("alerts", "Get a push for your own stocks"),
    ("close", "Recap"),
]


def build(screens: Path, member_name: str = "Nancy Pelosi", ticker: str = "NVDA") -> dict:
    caps = {p.stem: Cap(p) for p in sorted(screens.glob("*.json"))}
    for need in ("congress", "member", "stock_top", "stock_smart"):
        if need not in caps:
            raise ScriptError(f"missing capture {need}.json in {screens}")
        if caps[need].d.get("problems"):
            raise ScriptError(f"capture {need} has problems: {caps[need].d['problems']}")
    C, M, ST, SM = caps["congress"], caps["member"], caps["stock_top"], caps["stock_smart"]
    yr = C.d["captured_at"][:4]
    facts: dict[str, dict] = {}

    def fact(fid: str, value: str, cap: Cap, lines: list[dict], note: str = "") -> str:
        facts[fid] = {"id": fid, "value": value, "capture": cap.name, "url": cap.d["final_url"],
                      "captured_at": cap.d["captured_at"], "page_lines": [ln["t"] for ln in lines],
                      "box_css": union(lines), "note": note}
        return value

    # ---- 1. the summary of /congress-trades
    head = C.find("Congress stock trades tracker")
    summ = C.find("trades disclosed by", exact=False)
    summ_lines = [ln for ln in C.lines if summ["y"] - 1 <= ln["y"] <= summ["y"] + summ["h"] + 30 and ln["x"] >= 633
                  and ln["y"] < summ["y"] + 60]
    m = re.search(r"([\d,]+) trades disclosed by (\d+) members of Congress across ([\d,]+) tickers in the (\d+) days since "
                  r"([A-Z][a-z]{2} \d{1,2}, \d{4})\. ([\d,]+) were purchases and ([\d,]+) were sales\.", C.d["page_text"])
    if not m:
        raise ScriptError("congress: the summary sentence changed shape")
    n_trades = fact("trades_90d", m.group(1), C, [summ], "trades disclosed in the window")
    n_members = fact("members_90d", m.group(2), C, [summ])
    n_days = fact("window_days", m.group(4), C, [summ])
    n_buys = fact("purchases_90d", m.group(6), C, [ln for ln in summ_lines if ln["t"] == m.group(6)] or [summ])
    n_sells = fact("sales_90d", m.group(7), C, [ln for ln in summ_lines if ln["t"] == m.group(7)] or [summ])
    summ_box = union(summ_lines, 6)

    # ---- 2. Latest disclosures, row 1
    lat = C.table("Latest disclosures", ["Disclosed", "Member", "Trade", "Amount", "Traded · lag", "Since disclosure", "Filing"],
                  anchor="Disclosed", rows=3)
    r = lat[0]
    l_date = fact("latest_disclosed", text_of(r["Disclosed"]), C, r["Disclosed"])
    l_member = fact("latest_member", text_of(r["Member"]), C, r["Member"])
    trade = [ln["t"] for ln in r["Trade"]]
    if len(trade) < 2 or trade[1] not in ("Buy", "Sell"):
        raise ScriptError(f"latest row 1: trade cell {trade}")
    l_ticker = fact("latest_ticker", trade[0], C, r["Trade"][:1])
    l_side = fact("latest_side", trade[1], C, r["Trade"][1:2])
    if any(t in ("(", "spouse", "joint", "child") for t in trade[2:]):
        raise ScriptError("latest row 1 carries an owner note the script does not read")
    l_amount = fact("latest_amount", text_of(r["Amount"]), C, r["Amount"])
    say_amount(l_amount)
    tl = [ln["t"] for ln in r["Traded · lag"]]
    if len(tl) < 3 or not re.fullmatch(r"\d+", tl[1]) or tl[2] != "d lag":
        raise ScriptError(f"latest row 1: traded cell {tl}")
    l_traded = fact("latest_traded", tl[0], C, r["Traded · lag"][:1])
    l_lag = fact("latest_lag_days", tl[1], C, r["Traded · lag"][1:3])
    if not r["Filing"] or r["Filing"][0]["t"] != "PDF":
        raise ScriptError("latest row 1: no PDF link")
    lat_head = C.find("Latest disclosures")

    # ---- 3. Most active members, row 1
    act = C.table("Most active members of Congress", ["#", "Member", "Trades ·", "Buys", "Sells", "Tickers", "Last filing"],
                  anchor="#", rows=2)
    a = act[0]
    if text_of(a["#"]) != "1":
        raise ScriptError("most active: row 1 is not #1")
    a_name = fact("active1_name", a["Member"][0]["t"], C, a["Member"][:1])
    a_trades = fact("active1_trades", text_of(a["Trades ·"]), C, a["Trades ·"])
    a_buys = fact("active1_buys", text_of(a["Buys"]), C, a["Buys"])
    a_sells = fact("active1_sells", text_of(a["Sells"]), C, a["Sells"])
    act_head = C.find("Most active members of Congress")

    # ---- 4. Most bought, row 1
    bought = C.table("Most bought stocks by Congress", ["Ticker", "Members buying", "Buy filings", "Sell filings",
                                                        "Since first buy filing"], anchor="Ticker", rows=2)
    b = bought[0]
    b_ticker = fact("bought1_ticker", b["Ticker"][0]["t"], C, b["Ticker"][:1])
    b_members = fact("bought1_members", text_of(b["Members buying"]), C, b["Members buying"])
    b_buyf = fact("bought1_buy_filings", text_of(b["Buy filings"]), C, b["Buy filings"])
    b_sellf = fact("bought1_sell_filings", text_of(b["Sell filings"]), C, b["Sell filings"])
    b_head = C.find("Most bought stocks by Congress")
    b_move = b["Since first buy filing"]
    if not b_move or "SPY" not in text_of(b_move):
        raise ScriptError("most bought: the move column does not show SPY beside the stock")

    # ---- 5. the member link (Frequently searched members) and the member page
    fs_head = C.find("Frequently searched members")
    fs_link = C.find(member_name, y0=fs_head["y"], y1=fs_head["y"] + 120)
    if not any(lk["href"] == M.d["final_url"].replace("https://www.rapidtradeview.trade", "") and
               abs(lk["box"][1] - fs_link["y"]) < 6 for lk in C.d["links"]):
        raise ScriptError("the member's link on /congress-trades does not lead to the captured member page")
    m_title = M.find(f"{member_name}: stock trades")
    m_sum = M.find("member of Congress.", exact=False)
    mm = re.search(r"(\d+) disclosed trades across (\d+) tickers, latest filing (\d{4}-\d{2}-\d{2})", m_sum["t"])
    if not mm:
        raise ScriptError("member: the summary line changed shape")
    m_n = fact("member_trades", mm.group(1), M, [m_sum])
    m_tk = fact("member_tickers", mm.group(2), M, [m_sum])
    m_last = fact("member_latest_filing", mm.group(3), M, [m_sum])
    lb, ls = M.find("Buys"), M.find("Sells")
    vb = [ln for ln in M.lines if abs(ln["x"] - lb["x"]) < 2 and lb["y"] < ln["y"] < lb["y"] + 60][0]
    vs = [ln for ln in M.lines if abs(ln["x"] - ls["x"]) < 2 and ls["y"] < ln["y"] < ls["y"] + 60][0]
    m_buys = fact("member_buys", vb["t"], M, [lb, vb])
    m_sells = fact("member_sells", vs["t"], M, [ls, vs])
    tab = M.table("Disclosed trades", ["Traded", "Disclosed", "Ticker", "Side", "Since filing vs SPY", "Amount", "Owner · lag"],
                  anchor="Traded", rows=40)
    t0 = tab[0]
    sides = {"sell": "sale", "buy": "buy"}

    def row_facts(prefix: str, row: dict) -> dict:
        side = text_of(row["Side"]).lower()
        if side not in sides:
            raise ScriptError(f"member row {prefix}: side {side!r}")
        return {"traded": fact(f"{prefix}_traded", text_of(row["Traded"]), M, row["Traded"]),
                "disclosed": fact(f"{prefix}_disclosed", text_of(row["Disclosed"]), M, row["Disclosed"]),
                "ticker": fact(f"{prefix}_ticker", text_of(row["Ticker"]), M, row["Ticker"]),
                "side": fact(f"{prefix}_side", side, M, row["Side"]),
                "amount": fact(f"{prefix}_amount", text_of(row["Amount"]), M, row["Amount"]),
                "box": row["_box"]}

    newest = row_facts("member_newest", t0)
    owner = [ln for ln in t0["Owner · lag"] if ln["t"] in ("spouse", "joint", "self", "child", "dependent")]
    if not owner:
        raise ScriptError("member newest row: no owner badge")
    m_owner = fact("member_newest_owner", owner[0]["t"], M, owner[:1])
    trows = [rw for rw in tab if text_of(rw["Ticker"]) == ticker]
    tbuys = [rw for rw in trows if text_of(rw["Side"]).lower() == "buy"]
    tsells = [rw for rw in trows if text_of(rw["Side"]).lower() == "sell"]
    if len(tbuys) != 1 or len(tsells) != 1:
        raise ScriptError(f"member page: {ticker} has {len(tbuys)} buy and {len(tsells)} sell rows (the script reads one each)")
    tb, ts = row_facts("member_tbuy", tbuys[0]), row_facts("member_tsell", tsells[0])
    note = M.find("Members of Congress report trades in dollar ranges", exact=False)
    if "may file up to 45 days after" not in note["t"]:
        raise ScriptError("member note changed")
    fact("filing_window_45d", "45", M, [note])
    tlink = [lk for lk in M.d["links"] if lk["href"] == f"/dashboard/{ticker}"]
    tlink = min(tlink, key=lambda lk: abs(lk["box"][1] - tbuys[0]["Ticker"][0]["y"]))
    if abs(tlink["box"][1] - tbuys[0]["Ticker"][0]["y"]) > 8:
        raise ScriptError("the ticker link is not on the buy row")

    # ---- 6. the stock page
    if not ST.d["final_url"].endswith(f"/dashboard/{ticker}"):
        raise ScriptError("stock capture is not the ticker's page")
    st_t = ST.find(ticker, y0=60, y1=140)
    close_l = next((ln for ln in ST.lines if 150 <= ln["y"] <= 330 and re.match(r"Close [A-Z][a-z]{2} \d", ln["t"])), None)
    if close_l is None:
        raise ScriptError("stock: no 'Close <day>:' line under the price")
    close_v = [ln for ln in ST.lines if abs(ln["y"] - close_l["y"]) < 3 and ln["x"] > close_l["x"]]
    cm = re.fullmatch(r"Close ([A-Z][a-z]{2} \d{1,2}):", close_l["t"])
    if not cm or not close_v:
        raise ScriptError(f"stock: close line {close_l['t']!r}")
    close_val = "".join(ln["t"] for ln in close_v)
    if not re.fullmatch(r"\$[\d,]+\.\d\d", close_val):
        raise ScriptError(f"stock: close value {close_val!r}")
    s_close = fact("stock_close", close_val, ST, [close_l] + close_v)
    s_close_day = fact("stock_close_day", cm.group(1), ST, [close_l])
    price_lines = [ln for ln in ST.lines if 150 < ln["y"] < 300 and 780 < ln["x"] < 1200]
    chart_top = ST.find("1D", y0=500, y1=700)
    sm_head = SM.find("Smart Money", y0=140, y1=400)
    sm_line = SM.find("notable figures disclosed trades in", exact=False)
    sm = re.fullmatch(rf"(\d+) notable figures disclosed trades in {ticker} in the last (\d+) days", sm_line["t"])
    if not sm:
        raise ScriptError(f"stock: smart money line {sm_line['t']!r}")
    s_figs = fact("stock_figures", sm.group(1), SM, [sm_line])
    s_days = fact("stock_figures_days", sm.group(2), SM, [sm_line])
    sm_row = [ln for ln in SM.lines if sm_line["y"] + 60 < ln["y"] < sm_line["y"] + 140]
    sm_card_bottom = SM.find("Congress disclosures arrive up to 45 days late", exact=False)

    # ---- 7. the app card on /congress-trades
    app_h = C.find("Free Android app")
    app_t = C.find("Get a push when Congress or insiders make large trades in your stocks")
    app_b = C.find("You get a push when a member of Congress or a company insider discloses a large trade", exact=False,
                   y0=app_t["y"], y1=app_t["y"] + 200)
    am = re.search(r"You set the minimum \((\$\d+M) by default\)", app_b["t"])
    if "Sign in to the free RapidTradeView app, add your stocks to your portfolio and turn on alerts" not in app_b["t"] or not am:
        raise ScriptError("the app card's wording changed: read frontend/src/lib/appHandoff.ts and rewrite the alert lines")
    app_min = fact("alert_default_minimum", am.group(1), C, [app_b])
    app_btn = C.find("Get the free app", y0=app_b["y"])
    app_box = union([app_h, app_t, app_b, app_btn], 14)
    if app_min != "$1M":
        raise ScriptError(f"say form for {app_min} not written")
    say_min = "1 million dollars"

    # ---- the sentences
    S: list[dict] = []

    def add(section, text, say=None, facts_=(), view=None, outline=None, cursor=None, pause=0.3):
        S.append({"id": f"s{len(S) + 1:02d}", "section": section, "text": text, "say": say or text,
                  "facts": list(facts_), "view": view, "outline": outline, "cursor": cursor, "pause": pause})

    def V(cap, box=None, zoom=2.1, cx=960.0, at=470.0, cy=None):
        return {"cap": cap, "box": box, "zoom": zoom, "cx": cx, "at": at, "cy": cy}

    B = "RapidTradeView"
    title_box = union([head], 8)
    add("answer", f"Here's how to track Congress stock trades for free, with {B}.",
        view=V("congress", zoom=1.0, cy=502))
    add("answer", "Members of Congress publicly report their stock trades.", view=V("congress", title_box, 1.9, at=330),
        outline=None)
    add("answer", "This free page collects them: the Congress stock trades tracker.", view=V("congress", title_box, 2.0, at=330),
        outline=title_box)
    add("answer", f"Right now it shows {n_trades} trades, disclosed by {n_members} members of Congress, in the last {n_days} days.",
        facts_=["trades_90d", "members_90d", "window_days"], view=V("congress", summ_box, 2.0, at=420), outline=summ_box)
    add("answer", f"{n_buys} were purchases, and {n_sells} were sales.", facts_=["purchases_90d", "sales_90d"],
        view=V("congress", summ_box, 2.05, at=420), outline=summ_box)
    add("answer", "Here's how to read every trade, follow one member, and get a push for the stocks you hold.",
        view=V("congress", union([act_head], 4), 1.5, at=300), pause=0.6)

    row1 = r["_box"]
    rowpad = [row1[0] - 8, row1[1] - 8, row1[2] + 16, row1[3] + 16]
    lat_view = lambda z=2.5: V("congress", rowpad, z, at=430)  # noqa: E731
    add("latest", "Scroll down to Latest disclosures. The newest filings are at the top.",
        view=V("congress", union([lat_head], 6), 2.1, at=260), outline=union([lat_head], 8))
    add("latest", "Each row is one trade. Read it from left to right.", view=lat_view(2.4), outline=rowpad)
    add("latest", f"Disclosed is the day the filing came out: {short(l_date, yr)}.",
        f"Disclosed is the day the filing came out: {say_short(l_date, yr)}.",
        ["latest_disclosed"], lat_view(), union(r["Disclosed"], 8))
    add("latest", f"Member: {l_member}.", f"Member: {say_name(l_member)}.", ["latest_member"], lat_view(),
        union(r["Member"], 8))
    add("latest", f"Trade: the ticker, {l_ticker}, and the side, a {l_side.lower()}.",
        f"Trade: the ticker, {say_ticker(l_ticker)}, and the side, a {l_side.lower()}.",
        ["latest_ticker", "latest_side"], lat_view(), union(r["Trade"][:2], 8))
    add("latest", f"Amount is a range, not an exact figure: {l_amount}.",
        f"Amount is a range, not an exact figure: {say_amount(l_amount)}.", ["latest_amount"], lat_view(),
        union(r["Amount"], 8))
    add("latest", f"Traded is the day of the trade itself, {short(l_traded, yr)}.",
        f"Traded is the day of the trade itself, {say_short(l_traded, yr)}.", ["latest_traded"], lat_view(),
        union(r["Traded · lag"][:1], 8))
    add("latest", f"So it was filed {l_lag} days later. The page calls that the lag.", facts_=["latest_lag_days"],
        view=lat_view(), outline=union(r["Traded · lag"][1:3], 8))
    add("latest", "And PDF opens the original filing.", "And P D F opens the original filing.", view=lat_view(),
        outline=union(r["Filing"], 8), pause=0.6)

    a_box = a["_box"]
    a_row = [a_box[0] - 8, a_box[1] - 8, a_box[2] + 16, a_box[3] + 16]
    add("lists", f"Back at the top, Most active members of Congress ranks members by trades disclosed in the last "
                 f"{n_days} days.", facts_=["window_days"], view=V("congress", union([act_head], 6), 2.0, at=250),
        outline=union([act_head], 8))
    add("lists", f"Number one right now is {a_name}, with {a_trades} trades: {a_buys} buys and {a_sells} sells.",
        f"Number one right now is {say_name(a_name)}, with {a_trades} trades: {a_buys} buys and {a_sells} sells.",
        ["active1_name", "active1_trades", "active1_buys", "active1_sells"], V("congress", a_row, 2.3, at=330), a_row)
    add("lists", "Every name is a link to that member's full filing history.", view=V("congress", a_row, 1.9, at=300),
        cursor={"box": union(a["Member"][:1]), "click": False}, pause=0.5)
    b_box = b["_box"]
    b_row = [b_box[0] - 8, b_box[1] - 8, b_box[2] + 16, b_box[3] + 16]
    add("lists", "Further down, Most bought stocks by Congress ranks stocks by how many members bought them.",
        view=V("congress", union([b_head], 6), 2.0, at=250), outline=union([b_head], 8))
    add("lists", f"{b_ticker} is first: {b_members} members bought it, in {b_buyf} buy filings. The table also shows "
                 f"{b_sellf} sell filings.",
        f"{say_ticker(b_ticker)} is first: {b_members} members bought it, in {b_buyf} buy filings. The table also shows "
        f"{b_sellf} sell filings.",
        ["bought1_ticker", "bought1_members", "bought1_buy_filings", "bought1_sell_filings"], V("congress", b_row, 2.3, at=330),
        b_row, pause=0.6)

    fs_box = union([fs_head], 8)
    add("member", "To follow one member, open their page. Frequently searched members is a good place to start.",
        view=V("congress", fs_box, 2.1, at=300), outline=fs_box)
    add("member", f"I'll click {member_name}.", view=V("congress", fs_box, 2.2, at=300),
        cursor={"box": union([fs_link]), "click": True}, pause=0.5)
    msum = union([m_sum], 6)
    add("member", f"The page lists {m_n} disclosed trades across {m_tk} tickers. The latest filing is from "
                  f"{short(m_last, yr)}.",
        f"The page lists {m_n} disclosed trades across {m_tk} tickers. The latest filing is from {say_short(m_last, yr)}.",
        ["member_trades", "member_tickers", "member_latest_filing"], V("member", union([m_title, m_sum], 6), 2.0, at=330), msum)
    add("member", f"{m_buys} buys and {m_sells} sells.", facts_=["member_buys", "member_sells"],
        view=V("member", union([lb, vb, ls, vs], 16), 2.0, at=380), outline=union([lb, vb, ls, vs], 16))
    th = union(tab[0]["Traded"] + [M.find("Owner · lag")], 0)
    hdr = union([M.find(h_) for h_ in ("Traded", "Owner · lag")] + [M.find("Disclosed", y0=1050)], 8)
    add("member", "The table lists every trade: both dates, the ticker, buy or sell, and the amount.", view=V("member", hdr, 2.2, at=300), outline=hdr)
    nb = newest["box"]
    nrow = [nb[0] - 8, nb[1] - 8, nb[2] + 16, nb[3] + 16]
    add("member", f"The newest: a {sides[newest['side']]} of {newest['ticker']}, {newest['amount']}, traded "
                  f"{short(newest['traded'], yr)}, disclosed {short(newest['disclosed'], yr)}.",
        f"The newest: a {sides[newest['side']]} of {say_ticker(newest['ticker'])}, {say_amount(newest['amount'])}, traded "
        f"{say_short(newest['traded'], yr)}, disclosed {say_short(newest['disclosed'], yr)}.",
        ["member_newest_side", "member_newest_ticker", "member_newest_traded", "member_newest_disclosed",
         "member_newest_amount"], V("member", nrow, 2.3, at=380), nrow)
    add("member", f"The owner column says whose account it was: here, the {m_owner}.", facts_=["member_newest_owner"],
        view=V("member", nrow, 2.3, at=380), outline=union(owner[:1], 8), pause=0.5)
    tbr = [tb["box"][0] - 8, tb["box"][1] - 8, tb["box"][2] + 16, tb["box"][3] + 16]
    tsr = [ts["box"][0] - 8, ts["box"][1] - 8, ts["box"][2] + 16, ts["box"][3] + 16]
    both = union([{"x": tbr[0], "y": min(tbr[1], tsr[1]), "w": tbr[2], "h": 1},
                  {"x": tsr[0], "y": max(tbr[1] + tbr[3], tsr[1] + tsr[3]) - 1, "w": tsr[2], "h": 1}])
    add("member", f"Further down, {ticker} shows up twice.", f"Further down, {say_ticker(ticker)} shows up twice.",
        view=V("member", both, 2.1, at=420), outline=None)
    add("member", f"A buy of {tb['amount']}, traded {short(tb['traded'], yr)}.",
        f"A buy of {say_amount(tb['amount'])}, traded {say_short(tb['traded'], yr)}.",
        ["member_tbuy_side", "member_tbuy_amount", "member_tbuy_traded"], V("member", both, 2.1, at=420), tbr)
    add("member", f"And a sale of {ts['amount']}, traded {short(ts['traded'], yr)}.",
        f"And a sale of {say_amount(ts['amount'])}, traded {say_short(ts['traded'], yr)}.",
        ["member_tsell_side", "member_tsell_amount", "member_tsell_traded"], V("member", both, 2.1, at=420), tsr)
    nbox = [note["x"] - 8, note["y"] - 8, note["w"] + 16, note["h"] + 16]
    add("member", "The note under the table says why: members report trades in dollar ranges, and may file up to 45 days "
                  "after the trade.", facts_=["filing_window_45d"], view=V("member", nbox, 2.1, at=380), outline=nbox,
        pause=0.5)
    add("member", f"Let's open {ticker}. Click the ticker, and you land on its stock page.",
        f"Let's open {say_ticker(ticker)}. Click the ticker, and you land on its stock page.",
        view=V("member", tbr, 2.2, at=380), cursor={"box": [tlink["box"][0], tlink["box"][1], tlink["box"][2], tlink["box"][3]],
                                                     "click": True}, pause=0.5)

    price_box = union(price_lines, 10)
    add("stock", "It shows the latest price and the chart.", view=V("stock_top", None, 1.12, cx=1000, cy=72 + 1004 / 1.12 / 2),
        outline=None)
    add("stock", f"{ticker} closed at {s_close} on {s_close_day}.",
        f"{say_ticker(ticker)} closed at {s_close} on {say_day(s_close_day)}.",
        ["stock_close", "stock_close_day"], V("stock_top", price_box, 2.4, cx=None, at=360), union([close_l] + close_v, 8),
        pause=0.5)
    smh = union([sm_head], 8)
    sm_card = union([sm_head, sm_card_bottom], 4)
    add("stock", "Scroll down to Smart Money. It lists who disclosed trades in this stock.",
        view=V("stock_smart", None, 2.2, cx=960, cy=150 + 1004 / 2.2 / 2), outline=smh)
    add("stock", f"{s_figs} notable figures disclosed trades in {ticker} in the last {s_days} days.",
        f"{s_figs} notable figures disclosed trades in {say_ticker(ticker)} in the last {s_days} days.",
        ["stock_figures", "stock_figures_days"], V("stock_smart", None, 2.2, cx=960, cy=150 + 1004 / 2.2 / 2),
        union([sm_line], 8))
    add("stock", "Each line shows who traded, the buys or sells, about how much, and when.",
        view=V("stock_smart", None, 2.25, cx=960, cy=150 + 1004 / 2.25 / 2), outline=union(sm_row, 8), pause=0.6)

    add("alerts", "Checking pages by hand works. But you can also get alerts.", view=V("congress", app_box, 1.9, at=470),
        outline=None)
    add("alerts", f"The free {B} Android app sends a push when a member of Congress or a company insider discloses a large "
                  f"trade in one of your stocks.", view=V("congress", app_box, 2.0, at=470), outline=union([app_h, app_t], 8))
    add("alerts", "Sign in, add your stocks to your portfolio, and turn on alerts.", view=V("congress", app_box, 2.0, at=470),
        outline=union([app_b], 8))
    add("alerts", f"You set the minimum: {app_min} by default.", f"You set the minimum: {say_min} by default.",
        ["alert_default_minimum"], V("congress", app_box, 2.05, at=470), union([app_b], 8), pause=0.6)

    add("close", f"To recap: search {B}, and open the Congress stock trades tracker.",
        view=V("congress", title_box, 1.6, at=330), outline=title_box, pause=0.5)
    add("close", f"Search {B}. Link in the description. Not investment advice.", view={"cap": "endcard"}, pause=0.8)

    # every figure in a caption is a fact this script read (or the 45-day rule it read from the member page)
    num = r"\$?\d(?:[\d,]*\d)?(?:\.\d+)?(?:–\$\d(?:[\d,]*\d)?)?M?"
    known = set()
    for f in facts.values():
        v = f["value"]
        forms = [v]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2} \d{1,2}, \d{4}", v):
            forms.append(show_date(v))
        for form in forms:
            known.update(re.findall(num, form))
    for s in S:
        for tok in re.findall(num, s["text"]):
            if tok not in known:
                raise ScriptError(f"{s['id']}: the figure {tok!r} is not a read fact")
        for fid in s["facts"]:
            if fid not in facts:
                raise ScriptError(f"{s['id']}: unknown fact {fid}")
    return {"sentences": S, "facts": list(facts.values()), "sections": SECTIONS,
            "captures": {k: {"url": c.d["final_url"], "captured_at": c.d["captured_at"], "tiles": c.d["tiles"],
                             "page_height": c.d["page_height"], "dpr": c.d["dpr"]} for k, c in caps.items()}}


if __name__ == "__main__":
    import sys
    out = build(Path(sys.argv[1]))
    for s in out["sentences"]:
        print(s["id"], s["section"], "|", s["text"], "|", s["say"] if s["say"] != s["text"] else "")
