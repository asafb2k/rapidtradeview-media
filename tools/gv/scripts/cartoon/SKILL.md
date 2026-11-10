---
name: cartoon-story-reel
description: Make a cartoon-story Reel / Short for RapidTradeView in the one-idea format. A cartoon character hears a news item in a confusing way, opens RapidTradeView, and our real page shows the real fact; the brand is on screen the whole time. Use it to turn one facts item into a 15-20 s vertical video, generated from the item by make_story.py, or to show what one feature of the site answers (Congress trades, insider trades, concentration, portfolio, market breadth) with the site's real card whole on screen, generated from a capture made now by make_feature_story.py.
---

# Cartoon-story Reel (format v4: one idea, brand always visible)

## The owner's verdict (binding)

On the v2 pilot (30 s, 23 shots, a gym story with a cat feed, a sock ad, tabs stacking like plates):

> "the pilot short is too complicated and it isnt clear what brand behind it"

So the format is now:
- **ONE situation, ONE punchline, 15-20 s (gate: 15-22 s), at most 7 shots.** No side gags. Nothing that does not serve
  the one idea.
- **The brand is unmistakable from frame 0 to the end.** A RapidTradeView pill (`card_reel.pill`: our mark + name on the
  brand gradient) is drawn over every frame, top-left at (54, 262), clear of the platform UI (not in the top 250 px, the
  bottom 18% or the right 12%). The voice says "RapidTradeView" in the first ~4 s and again at the end. The phone in the
  story shows our mark and our name. The payoff is our real page with its own header and logo.
- **The pattern, every day, from any facts item:** a character hears the news in a confusing way -> opens RapidTradeView
  -> the real screen shows the real fact clearly -> a one-word reaction -> end card "Search RapidTradeView" + "Not
  investment advice.".
- Kept from v2: the hook carries the real number in the first second, the camera always moves, word-by-word captions,
  the local Kokoro voice, the VSCO music bed, every QA gate.

**The story is fiction, the data is not.** Every number on screen or in the voice is the facts item's, verbatim. The
characters are ours and fictional; never draw a real person or another company's logo.

## Files

| File | What it is | Runs in |
|---|---|---|
| `make_story.py` | TEMPLATE mode: facts item -> `story.json` (captures the real pages with `--capture`) | conda env `rapidtradingview` |
| `make_feature_story.py` | FEATURE mode: a registry entry + a capture made now -> `story.json` (section Feature shorts) | conda env `rapidtradingview` |
| `features.json` | the feature registry: page, the card to capture whole (`site`), value rules, story lines with slots, the key | (data) |
| `cartoon_reel.py` | story.json -> `reel_9x16.mp4` + `reel.json` + `reel-qa.json` + `sheet.png` | conda env `rapidtradingview` |
| `cast.py` | the cast (Pip, Dale), the branded phones, sets, pulse rings, chips, receipt, card frame | (imported) |
| `cartoon_qa.py` | the text, brand and format gates (pure functions, unit-tested) | (imported) |
| `capture.py` | captures our page (a band between two texts; for a feature a strip of the page at phone width) + sidecar with DOM boxes | `.ops/cache/shot-venv` |
| `tts.py` | local Kokoro-82M voice with engine word timings (Apache-2.0) | `.ops/cache/tts-venv` |

Music: `../v6cat/vsco_score.py` (VSCO 2 CE, CC0). End card, encoder, fonts and the brand pill: `../v6cat/card_reel.py`.
Tests: `tools/tests/test_cartoon_qa.py`, `tools/tests/test_cartoon_make_story.py`, `tools/tests/test_cartoon_features.py`.

## 1. Pick the item

From today's `v/<date>/facts.json`, prefer `in_500` and fresh (`viral_check.fresh(item, now)` is not False):

```python
import sys, json, datetime as dt
sys.path.insert(0, "tools"); import viral_check as vc
```

Templates exist for:
- `earnings_result` with an EPS beat or miss against consensus (`results.eps.label` "Beat by $1.17"). The payoff page is
  the item's earnings report page (`/earnings/reports/<report_id>`): public, no guest view counted. The dashboard page
  counts guest views per IP and sends a used-up IP home, so do not capture it.
- `form4_buy` (an open-market buy with `amount_text`). The payoff page is the item's `page_url` (the insider's page).

Anything else: `make_story.py` exits 2. No template, no video (No Fallbacks).

## 2. Make the story (no hand-written creative)

```
PY=C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe
$PY tools/gv/scripts/cartoon/make_story.py v/<date>/facts.json <item_id> --run .ops/cartoon/<date>-<ticker> --capture
```

It captures three real bands of our page into `<run>/screens/` (`head`: from our header's "RapidTradeView" to the company
or person name; `fact`: the fact card, e.g. from the last "EPS" down to just above the "Consensus captured <date>" small
print, whose date is not the item's; or a Form 4 trade's own two lines, "Traded ... / $1,287,400 Officer View filing";
`key`: the key figure alone at 6x, e.g. the page's "Beat by $1.17" tag, cropped tight around it) and writes
`<run>/story.json`:

| # | Kind | Picture | Voice (CEG example) |
|---|---|---|---|
| 1 | HOOK | Dale close-up, the figure pops into a chip | Dale: "CEG beat by $1.17!" |
| 2 | CLOSE | Pip close, phone up with our mark on it, puzzled | Pip: "Beat what? Checking RapidTradeView." |
| 3 | CLOSE | the phone close: our mark and name on top, the ticker typed letter by letter | (silent, key clacks) |
| 4 | PAYOFF | whip into our real page: header card with our logo above the fact card, a slow push; Pip's head peeks in, wide-eyed | "EPS $5.06 vs $3.89 consensus" |
| 5 | PAYOFF | the header flies off, the page's own key tag lands big under the fact card, outlined | "(beat by $1.17)." |
| 6 | CALLBACK | Pip, the phone with our mark: shock on the cut, happy on the word | Pip: "Oh." |
| 7 | END | the end card | "Search RapidTradeView. Not investment advice." |

What it fills in: the hook figure (the EPS difference or the buy amount), the confused line, the search, the fact phrase
(the item's own phrasing, verbatim, read in two halves), the claim tags (the phrasing each factual line paraphrases),
the say map (figures spelled for the voice, "C E G", "Rapid Trade View"; brackets are never voiced), the card layout,
and the screen acknowledgements. The layout keeps every standing card between the brand pill (y 333) and the caption
band, and each character's face below the pill and its held prop above the captions, at the largest scale of its push.
Only one page part may be acknowledged: the guest counter in our header, and only its own digits ("0/2" on its own line,
or "0", "/", "2" as three nodes); a number beside it is not the counter. Any other number on a capture that the item does
not carry stops the script: change the capture band, do not explain the number away. The earnings fact phrase is the
item's phrasing with "consensus" in it, so "Beat what?" is answered in the caption; the payoff lines must name and repeat
the hook's bare figure (EPS / bought) or the script stops. The form4 template had its first real run on PAM 2026-11-09
(QA pass); its hook is "Insider bought $1.29M!" (with the ticker it ran 3.4 s, over the 2.6 s hook limit).

To change the creative for every future video, change the template in `make_story.py`, not a single story.json.

## 3. Render

```
$PY tools/gv/scripts/cartoon/cartoon_reel.py --story <run>/story.json --out <run>
```

About 1.5 minutes. The voice is cached in `<run>/tts/`. To iterate on the picture without encoding, import
`cartoon_reel`, build `Story -> Timeline -> Reel`, call `text_gates(...)` and save `reel.frame(t)` for a few times.

Then look at `sheet.png` and several full frames yourself: the hook frame is a close-up with the number coming, the pill
is never covered, captions are off faces, the real header logo is readable in the first payoff shot, the key label is
outlined and large in the second. Read every line in `reel.json` `claims_for_human_check` against its phrasing before
the video ships ("CEG beat by $1.17!" is a paraphrase of "$CEG Q3 EPS $5.06, beat by $1.17.").

## 4. QA gates (exit 0 pass, 1 QA fail, 2 input or render error)

`reel-qa.json` holds every gate. New in v4:
- **pill_clear:** no real card that is standing still (not flying in or out) overlaps the brand pill's box, in any
  rendered payoff frame (v3: the pill sat on our page header, two logos colliding).
- **end_card_safe:** the end card's wordmark and search box, at their largest (pop and pulse), stay left of x 950 (the
  right 12% is the IG/YT action rail).

New in v3:
- **brand_pill:** the pill region of the decoded video matches the planned pill in every sampled frame (each second and
  the last frame; correlation >= 0.8, mean difference <= 24).
- **brand_spoken:** "RapidTradeView" starts within the first 5 s and again within the last 5 s.
- **one_idea:** 15-22 s, at most 7 shots, at most one SFX bubble, and only story elements (characters, the branded
  search phone, our real cards, their highlight, a receipt). A feed, cat, sock, tab burst or barbell fails it.
- **payoff_brand:** in the PAYOFF shots our real header's "RapidTradeView" (a capture target) is inside the shown crop,
  inside the frame and at least 24 px tall for at least 1 s.
- **duration** 15-22 s; **structure** 4-7 shots, 0.7-2.6 s each (PAYOFF up to 4.5 s), payoff window 2-8 s, at least 1.8 s
  of real screen, END exactly 3 s, voice onset <= 0.10 s, the end VO done by 2.7 s.
- **screenshot_real** accepts the item's page and, for earnings, its report page.

Kept: resolution, video_codec, file_size, audio_present, audio_not_silent, audio_not_clipping, loudness (-15 to -13
LUFS), voice_present, caption_verbatim, fact_phrase, numbers_verbatim (fiscal labels such as "Q3 2026" are one token),
weekdays, claim_lines, spoken_numbers, screen_numbers, no_provider_names, banned_words, disclaimer_text, glyphs,
safe_zones, key_number (>= 64 px for 1.5 s), hook (a character >= 50% of the width at frame 0, an item number by 2.5 s),
character_on_screen, caption_occlusion, caption_sync, first_frame_not_blank, motion_every_beat, no_static_run,
disclaimer_on_screen.

## Feature shorts (what one feature answers)

Owner request 2026-11-10: "create one for features like smart money, concentration visuals, portfolio visuals and such".
A feature short is not tied to a news item. It shows the one question a feature of the site answers, with our real screen
as the payoff. Same pattern, same 7 shots, same owner rules as the daily short (one situation, one punchline, 15-20 s, the
pill on every frame, "RapidTradeView" said in the first ~4 s and at the end).

### The owner's verdict on the first four (binding)

> "they arent good, only the last one show the visuals correctly as it shown on website"

Three of the four (smart-money, concentration, portfolio) had cut the real page into FRAGMENT cards: a thin headline
strip, one table row, the donut lifted out of its card onto a black box, values captured again at 6x. The fourth showed
the whole Market breadth card with its chart, as the site draws it: that is the standard. So the payoff is the **site
screen**, and these rules bind every feature short:

1. **The card WHOLE.** The payoff shows the site's real card or screen at phone width, exactly as the website renders it:
   its title, headline and the full chart together, pixels untouched, LARGE (the card 940-1010 px wide in the 1080
   frame; 900 is the gate's floor). No fragment card, no element lifted out of its card, no re-cropped enlargement.
2. **Scroll, never cut.** A card taller than the stage is scrolled like a thumb scroll over the one capture.
3. **The key in place.** The key value is outlined where it stands on that same screen.
4. **Nothing on the screen.** Captions sit in a band under the window, Pip's head is small and beside them.
5. **Chosen by its visual.** Pick each feature's screen for its chart, not for a text row.

There is no way left to ask for a fragment: the registry refuses `captures`, the `stack` and `hero` layouts and a key
`crop` / `also` / 6x capture; the capture gate refuses a sidecar that is not a strip of the page at phone width; the
story gate refuses a `card` or `screen` element and any `crop`.

**There is no facts item. The capture made on the render day is the truth.** Every number, ticker and name the video
shows or says is read from the capture's DOM sidecar by a rule in the registry, never typed by hand.

```
PY=C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe
$PY tools/gv/scripts/cartoon/make_feature_story.py --list
$PY tools/gv/scripts/cartoon/make_feature_story.py <feature-id> --run .ops/cartoon-features-v2/<feature-id> --capture
$PY tools/gv/scripts/cartoon/cartoon_reel.py --story .ops/cartoon-features-v2/<feature-id>/story.json --out .ops/cartoon-features-v2/<feature-id>
```

Render on the capture day: the renderer refuses a capture older than 12 hours (`feature_capture`), and the story's
`post_date` is the capture day. The run folder gets `reel_9x16.mp4`, `reel.json`, `reel-qa.json`, `sheet.png`,
`story.json`, `screens/page.png` + `page.json`, and **`compare.png`**: the site capture of the card on the left and the
decoded video frames that show it on the right (the card's top, the end of the scroll, the outlined key), at one scale.
Look at it: the card in the frames must be the card of the capture.

### The registry: `features.json` (schema `rtv-cartoon-features/2`)

| id | The card (page, all public, no guest view counted) | Hook / the question | How it is shown | The key, outlined in place |
|---|---|---|---|---|
| `congress` | CONGRESS TRADES, home Market section (`/market` -> `/#market`) | "Congress made 76 buys!" / "And sells?" | card 976 px; scroll to the "Most traded" row and back | the headline "130 sells, 76 buys" |
| `insiders` | INSIDER TRADES, same section | "Insiders bought $502M!" / "And sold?" | card 976 px; scroll through BOUGHT and SOLD and back | the headline "$502M bought, $3.6B sold by insiders" |
| `concentration` | Portfolio Concentration card of `/sample-portfolio`, title to donut | "Only 9 are chips. I'm diversified!" / "Are you?" | whole in one frame, card ~906 px, no scroll | the headline "33% of your money is in 9 chip companies." |
| `portfolio` | `/sample-portfolio` as a PAGE, header to the end of LARGEST HOLDINGS | "42 holdings. Spread all over!" / "Spread where?" | page 1040 px; one scroll from our header through the value, the donut, SECTORS, BIGGEST INDUSTRY GROUPS, LARGEST HOLDINGS, then back to SECTORS | the SECTORS row "Technology ▲ high 57%" |
| `market-breadth` | MARKET BREADTH, home Market section | "83% of stocks rose Monday!" / "Out of how many?" | whole in one frame, card ~947 px, no scroll | "83%" in the headline |

(The numbers are 2026-11-10's; every one is a slot.)

- `congress` and `insiders` hold only on a day the card shows more sells than buys / more sold than bought (a check):
  the hook says the smaller side, the page shows both. Other days: no video (No Fallbacks).
- `concentration` and `portfolio` read the **read-only sample portfolio**: say so in the post text, and do not post the
  two close together. They look different (one card held whole; one long page scroll that ends on the sector list).
- `market-breadth` is a **dated fact**: the card shows "Last session (Mon, Nov 9)" and the hook names that weekday. The
  session must be the last US session that had closed when the page was captured, or the script stops (also the day
  after a market holiday: the gate does not know holidays). Post it before the next session closes, or capture and
  render again; never later.
- `/smart-money`, `/portfolio` and `/dashboard/<ticker>` are sign-in only or count a guest view: the registry refuses
  them as a `url`. Never sign in.
- Not in the registry: the MARKET MAP (grey while the market is closed), the Reddit buzz panel (a source brand), and
  SECTOR ROTATION (its headline is a generated sentence whose shape changes with the day and reads as signed percentages
  aloud: add it only with value rules that hold on every shape).
- Each entry carries a `post_note` (copied into `reel.json`): read it before the video is posted.

One entry holds:
- `url`, `lands_on` (only when the page redirects), `viewport` (`390x<height>`: phone width), `require` (texts the page
  must have), `refuse_if` (texts that mean its data is missing).
- `site`: what is captured. `strip.top` / `strip.bottom` / `strip.pad` (the page from one box's top to another's
  bottom, plus `pad` CSS px), `card.box` (the element(s) whose box is the card; `card.bottom` ends it at another
  element's bottom, e.g. the concentration card's donut), `parts` (named boxes of the card: title, headline, chart, ...;
  each must be whole on screen at some time), `header` (true: the strip starts at our page header, which must then be
  readable for 1 s; false: the card stands far below the header), `top_hold` (seconds on the strip's top before the
  scroll). A box is `page`, `el:CSS` (the first drawn element), `all:CSS` (the union of all drawn ones) or `text:TEXT`
  (with the target marks: `=` whole text node, `#N` N-th occurrence).
- `values`: how each slot is read from the strip's text: `{"from": "page", "after": line, "offset": n, "rx": regex with
  named groups, "as": name for the whole line, "prev"/"next": {name: regex}}`. `checks` stop a day that does not carry
  the story: `{"value", "min" | "max" | "equals" | "more_than": other value}`, `{"pct": p, "of": [count, total]}`,
  `{"session": {...}, "sets": {"weekday", "date"}}`.
- `lines`: hook, hook_figure, confused, search, fact_a, fact_b. **A line never holds a number, a ticker or a name: those
  are slots.** `registry_problems` refuses a typed number, ticker or name (a capitalised word mid-sentence that is not in
  `proper_words`), a provider name, a banned word, advice or a prediction in any wording, a slot no rule reads.
  `fact_a` is read over the card's top and the scroll, `fact_b` over the outlined key. In these two lines a dollar
  figure is said without "dollars" (the screen shows the $).
- `phone`: `"tap"`. The phone in shot 3 shows one link with the text `search` and a thumb taps it (the real link on our
  site: the "Market" tab, "Sample portfolio").
- `fact_phrase`: the one data phrase; on the capture word for word, and read aloud word for word (it may run across
  fact_a and fact_b).
- `sources` and `claims`: the page text each factual line paraphrases. They are the phrasings the `claim_lines` gate
  checks, and they are listed in `reel.json` `claims_for_human_check`: read each line against its page text before the
  video ships.
- `key`: `targets` (the text(s) outlined together as one box: a headline's first and last text node, a row's label and
  value) and `top` (optional: the line the window opens on while the key is outlined, e.g. the SECTORS heading).

### How the site screen is laid out (`make_feature_story.site_layout`)

- The window is the page at its full phone width: 1040 px wide, 20 px from each edge, from y 342 (the pill ends at 333)
  to y 1380. The caption band is under it (y 1458, at most 640 px wide, right of Pip's 126 px head).
- A strip that fits the stage with the card at 900 px or more is shown whole, without a scroll (breadth, concentration).
  Otherwise the window is 1040 wide and the strip scrolls: shot 4 stands on the strip's top, then scrolls to its end at
  about 900 px/s (a tall page faster, so that shot 4 stays under 5 s); shot 5 scrolls back to the card's top (or
  `key.top`) and the outline is drawn when its line starts.
- The camera does not move and the screen never shakes; the scroll ticks softly.
- It stops (exit 2) when the card would be under 900 px wide, the key under 40 px tall, the key's targets not one line
  or headline (a `#N` that matched another place), or the key not on the card.

### What a capture records (`capture.py`, strip mode)

- `kind: "strip"`, `strip` (top, bottom, page height, CSS px), `viewport`, `dpr`, `boxes` (the card and its parts, strip
  px), `targets` (the key's texts, the header's brand), `url` and `final_url` (both gated).
- The page is scrolled through once first (lazy panels are drawn) and the screenshot is taken with the viewport parked
  off the strip, so the fixed bottom tab bar and the sticky bars are not painted into it; if one still lies on the strip
  the capture stops. The strip was checked against a plain viewport screenshot: the same pixels.
- `visible_text`: every line that touches the strip (the provider, error and banned word checks read it, fail closed).
  `inside_text`: what the PNG really shows. **Numbers, values, sources and the fact phrase are read from this one.**
- `seal`: a hash over the fields the gates trust, the boxes included. A sidecar edited after the capture fails
  `feature_capture`. It is not a signature. Never edit a sidecar; capture again.

### When `make_feature_story.py` stops (exit 2, no story.json)

- the card, one of its parts or a value is missing, or a check fails (the page changed, or today's data does not carry
  the story);
- the page says a `refuse_if` text, or the strip shows an error, a loading word or a figure that did not compute;
- a provider or source brand is on what the strip shows;
- the capture is not from the feature's URL, did not end on its page, is not from today, is not the page at phone
  width, or its sidecar was edited;
- the layout would not read (above), or the filled lines would fail the number, claim or spoken-figure gates.

No fallback and no explaining away: change the registry, or do not make that video today.

### Gates that differ from the daily short

New with the site screen (owner verdict 2026-11-10), all on the rendered payoff frames:
- **site_card_whole:** while the window stands, the card is never cut at its sides; the rows of the card shown over the
  payoff add up to its whole DOM box, top to bottom; a card that fits the window is whole in one frame for 1 s; each
  named part is whole on screen for 0.25 s (a part taller than the window, two charts one under the other, is scrolled
  through from its first row to its last).
- **card_width:** the card is at least 900 px wide in every standing frame, inside the frame, for at least 1.8 s.
- **no_overlap:** no caption (its plate included) and no Pip on the window, in any payoff frame.
- **key_in_place:** whenever the outline is drawn, the outlined text lies on the card inside the same window, at least
  40 px tall, for 1.5 s.
- **key_number:** the same key through the older gate's eyes (kind `site`: 40 px on a card of 900 px or more).
- **payoff_brand:** gated when `site.header` is true (portfolio: our header is readable for 1 s before the scroll);
  reported as not applicable when the card stands far below the header (the pill and the voice carry the brand).
- **structure:** a site shot may run 5 s and the payoff window 9.5 s (the scroll over the real card is the point).

Kept from the first version:
- **feature_capture:** our page (asked for and ended on), captured at most 12 h before the render, `require` present, no
  `refuse_if`, no error or loading state, no provider name on what is shown, the sidecar sealed; now also a strip at
  phone width with the card's and the parts' boxes.
- **feature_story:** the story is exactly the one `make_feature_story.py` writes from the registry and the sidecar now
  (`cartoon_qa.feature_story_gate` and `make_feature_story.story_drift`: a window, a scroll, a caption band or a voice
  edited by hand is named). **A hand-edited say map was the hole found on 2026-11-10: the captions and every text gate
  stayed green while the voice said something else.**
- **no_provider_names** (the wider list, look-alike letters folded, on what is drawn, captioned, spoken and captured),
  **no_advice**, **fact_phrase**, **numbers_verbatim, claim_lines, hook, screen_numbers** (against an item built from
  the sidecar at render time), **spoken_numbers**, **screenshot_real**.

Everything else (pill on every frame, brand spoken early and late, 15-22 s, at most 7 shots, pill_clear, captions,
audio) gates exactly as for the daily short.

### Look at the frames (required, every render)

The gates measure boxes; they do not see. Before a feature short ships, open `compare.png`, `sheet.png` and full frames
of shots 4 and 5 and check:
- the card in the video is the card of the capture: title, headline and chart together, big and legible;
- the key is outlined on the right text, nothing covers the screen, the window's edge does not cut a title in half
  while it stands;
- no provider or source name anywhere on the strip (the provider check is a deny-list, and a logo drawn as an image
  has no text at all). An index or ticker name on our own page ("S&P 500", "SPY") is a benchmark, not a source credit;
- **company logos:** the CONGRESS TRADES card's "Most traded" row and the INSIDER TRADES rows carry the small ticker
  logos the site draws (about 45 px in the frame). They are part of the card as the website renders it (rule 1) and no
  gate sees them: if the owner rules them out, drop the two features, do not mask the card.

### Adding a feature

1. Open the page as a logged-out guest at 390x844 and find the card whose CHART answers one question in two seconds.
   Prefer pages that count no guest view (server-rendered public pages; not `/dashboard/<ticker>`).
2. Capture the strip by hand with `capture.py --strip-top ... --strip-bottom ... --box card=...` and look at it: the
   card whole, no provider name, no real person as the hero. Compare `inside_text` with the PNG.
3. Add the entry: `site` (strip, card, parts), the value rules, the lines (only slots carry data), the key's targets.
4. `make_feature_story.py <id> --run <dir> --capture`, render, and look at `compare.png`, `sheet.png` and full frames of
   shots 4 and 5 (the list above).
5. Add its sidecar to `tools/tests/test_cartoon_features.py`.

## Writing rules (for template changes)

- Short, deadpan, dialogue between Dale (coral captions) and Pip (mint); the narrator (white) only reads the fact.
- A line with a number, the ticker, the name or a trade word carries `"claim": "<phrasing id>"`. Write figures as the item
  does ("$1.17"), never as words; the say map spells them, and `spoken_numbers` checks the value.
- Weekdays only as an item date's weekday or the post day's. No other tickers or names, no advice or predictions, none
  of the banned words, no data vendor names anywhere ("SEC filing" and "Form 4" are fine).
- Captions sit in one band at y 1230: faces, the phone and the real cards stay above about y 1150. A feature short's
  site screen takes the frame down to y 1380 and its captions sit under it, at y 1458 (the shot's `caption`).
- The cartoon phone is a cartoon (our mark and name, a search field). The only product UI is the real capture, a plain
  rectangle of it, pixels untouched. In a feature short that rectangle is the whole card, never a piece of it.

## What not to do

- No side stories, second gags or montages; no "leg day" setups. One situation.
- Never hide the brand: nothing is drawn over the pill, and the pill never fades.
- Do not capture the dashboard page as a guest (it counts views per IP); use the report page or the insider page.
- Do not reuse the reference videos' look (bean bodies, warm tan rooms, white starbursts, yellow tags, teal end card).
- Do not invent a number, a quote or a UI. If a capture fails, the video does not ship.
- Do not cut a feature's card into pieces, lift a chart out of its card or capture a value again to enlarge it (owner
  2026-11-10: "only the last one show the visuals correctly as it shown on website"). Show the card whole and scroll.
- Do not post. This tool only renders.
- Do not commit mp4 files, screenshots or voice files. They go in `.ops/` (untracked).
