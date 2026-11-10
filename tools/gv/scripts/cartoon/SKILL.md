---
name: cartoon-story-reel
description: Make a cartoon-story Reel / Short for RapidTradeView in the one-idea format. A cartoon character hears a news item in a confusing way, opens RapidTradeView, and our real page shows the real fact; the brand is on screen the whole time. Use it to turn one facts item into a 15-20 s vertical video, generated from the item by make_story.py, or to show what one feature of the site answers (smart money, concentration, portfolio, market), generated from a capture made now by make_feature_story.py.
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
| `features.json` | the feature registry: page, capture bands, value rules, story lines with slots, the key | (data) |
| `cartoon_reel.py` | story.json -> `reel_9x16.mp4` + `reel.json` + `reel-qa.json` + `sheet.png` | conda env `rapidtradingview` |
| `cast.py` | the cast (Pip, Dale), the branded phones, sets, pulse rings, chips, receipt, card frame | (imported) |
| `cartoon_qa.py` | the text, brand and format gates (pure functions, unit-tested) | (imported) |
| `capture.py` | captures our page (a band between two texts) + sidecar with DOM boxes | `.ops/cache/shot-venv` |
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
pill on every frame, "RapidTradeView" said in the first ~4 s and at the end, the real screen with our logo as the hero).

**There is no facts item. The capture made on the render day is the truth.** Every number, ticker and name the video
shows or says is read from the capture's DOM sidecar by a rule in the registry, never typed by hand.

```
PY=C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe
$PY tools/gv/scripts/cartoon/make_feature_story.py --list
$PY tools/gv/scripts/cartoon/make_feature_story.py <feature-id> --run .ops/cartoon-features/<feature-id> --capture
$PY tools/gv/scripts/cartoon/cartoon_reel.py --story .ops/cartoon-features/<feature-id>/story.json --out .ops/cartoon-features/<feature-id>
```

Render on the capture day: the renderer refuses captures older than 12 hours (`feature_capture`).

### The registry: `features.json`

| id | Page (public, no guest view counted) | The question | The key |
|---|---|---|---|
| `smart-money` | `/congress-trades`, "Most bought stocks by Congress", top row | Which stock are the most members of Congress buying? | the row's ticker and company name |
| `concentration` | `/sample-portfolio`, the Portfolio Concentration card's top | Am I actually diversified? | the card's verdict pill ("Concentrated") |
| `portfolio` | `/sample-portfolio`, the two-ring donut | Where is my money, really? | the donut, its biggest slice's label outlined |
| `market-pictures` | `/market`, the Market breadth panel | How much of the market moved? | the share ("83%") |

`/smart-money` (the feed) and `/portfolio` are sign-in only: never capture them, never sign in. `concentration` and
`portfolio` read the same card of the read-only sample portfolio: do not post them close together.

One entry holds:
- `url`, `viewport`, `require` (texts the page must have), `refuse_if` (texts that mean its data is missing).
- `captures`: the bands, as in the daily short (`head` with our logo, `fact`, `key` at 6x). A text that starts with `=`
  matches a whole text node (`={ticker}` is the ticker V, not the V of "View"). Bands whose texts use a `{slot}` are
  captured second, after the values are read.
- `values`: how each slot is read from a capture's visible text: `{"from": capture, "after": line, "offset": n, "rx":
  regex with named groups, "as": name for the whole line, "prev"/"next": {name: regex}}`. `checks` stop a day that does
  not carry the story (`{"value": "count", "min": 2}`: one member buying breaks "4 in Congress bought one stock!").
- `lines`: hook, hook_figure, confused, search, fact_a, fact_b. **A line never holds a number, a ticker or a name: those
  are slots.** `registry_problems` refuses a typed number, a provider name, a banned word, a slot no rule reads.
- `fact_phrase`: the one data phrase; on a capture word for word, and read aloud word for word.
- `sources` and `claims`: the page text each factual line paraphrases (a text that is on its capture, or everything a
  capture shows). They are the phrasings the `claim_lines` gate checks, and they are listed in `reel.json`
  `claims_for_human_check`: read each line against its page text before the video ships.
- `layout`: `stack` (header + fact card, then fact card + the key tag) or `hero` (header + fact card, then both fly off
  and the key capture, a chart, fills the stage). `key.kind`: `figure` or `visual`.
- `hold4`, `lead5`, `hold5`: the still beats. Shot 5 starts `lead5` (0.5 s) before its line: the key lands and the camera
  settles, then the voice names it.

### When `make_feature_story.py` stops (exit 2, no story.json)

- a band or a value is missing, or a check fails (the page changed, or today's top row does not carry the story);
- the page says a `refuse_if` text, or a band shows an error or loading word;
- a provider or source brand is on what a band shows (the page's footer may name one; only the bands are checked);
- a capture is not from the feature's URL, or not from today;
- the filled lines would fail the number, claim or spoken-figure gates.

No fallback and no explaining away: change the band in the registry, or do not make that video today.

### Gates that differ from the daily short

- **feature_capture** (new): our page, captured at most 12 h before the render, `require` present, no `refuse_if`, no
  error or loading state, no provider name on what is shown.
- **feature_story** (new): the story's values are the ones read from the sidecars now, and its voice lines, chip, typed
  search, fact phrase and key target are the registry's templates filled with them. A story edited by hand fails.
- **fact_phrase**: on a capture and read aloud, word for word (punctuation is not a word).
- **numbers_verbatim, claim_lines, hook, screen_numbers**: unchanged code, run against an item built from the sidecars
  at render time (`cartoon_qa.feature_item`): the allowed numbers are the numbers the captures show.
- **key_number**: a `figure` key is at least 64 px tall for 1.5 s (as before). A `visual` key (a chart: its labels cannot
  be 64 px while the chart stays whole) needs the chart at least 640 px wide with the outlined label at least 30 px tall
  for 1.5 s.
- **screenshot_real**: the capture's URL is the registry's URL.

Everything else (pill on every frame, brand spoken early and late, 15-22 s, at most 7 shots, payoff_brand, pill_clear,
captions, audio) gates exactly as for the daily short.

### Adding a feature

1. Open the page as a logged-out guest at 390x844 and find one card that answers one question in two seconds. Prefer
   pages that count no guest view (server-rendered public pages; not `/dashboard/<ticker>`).
2. Capture the bands by hand with `capture.py` and look at them: nothing cut through, no provider name, no other
   company's logo, no real person as the hero.
3. Add the entry. Write the lines so that they stay true whenever the page changes: only slots carry data.
4. `make_feature_story.py <id> --run <dir> --capture`, render, and look at `sheet.png` and full frames of shots 4 and 5:
   the real card big and legible, our logo readable, the key outlined, no sliver of a neighbouring line at a crop's edge
   (tighten `pad`), the pill clear.
5. Add its sidecar texts to `tools/tests/test_cartoon_features.py`.

## Writing rules (for template changes)

- Short, deadpan, dialogue between Dale (coral captions) and Pip (mint); the narrator (white) only reads the fact.
- A line with a number, the ticker, the name or a trade word carries `"claim": "<phrasing id>"`. Write figures as the item
  does ("$1.17"), never as words; the say map spells them, and `spoken_numbers` checks the value.
- Weekdays only as an item date's weekday or the post day's. No other tickers or names, no advice or predictions, none
  of the banned words, no data vendor names anywhere ("SEC filing" and "Form 4" are fine).
- Captions sit in one band at y 1230: faces, the phone and the real cards stay above about y 1150.
- The cartoon phone is a cartoon (our mark and name, a search field). The only product UI is the real capture, a plain
  rectangle of it, pixels untouched.

## What not to do

- No side stories, second gags or montages; no "leg day" setups. One situation.
- Never hide the brand: nothing is drawn over the pill, and the pill never fades.
- Do not capture the dashboard page as a guest (it counts views per IP); use the report page or the insider page.
- Do not reuse the reference videos' look (bean bodies, warm tan rooms, white starbursts, yellow tags, teal end card).
- Do not invent a number, a quote or a UI. If a capture fails, the video does not ship.
- Do not post. This tool only renders.
- Do not commit mp4 files, screenshots or voice files. They go in `.ops/` (untracked).
