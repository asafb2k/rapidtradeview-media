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

Render on the capture day: the renderer refuses captures older than 12 hours (`feature_capture`), and the story's
`post_date` is the capture day.

### The registry: `features.json`

| id | Page (public, no guest view counted) | The question | Shot 5: the key |
|---|---|---|---|
| `smart-money` | `/congress-trades`, "Most bought stocks by Congress", top row | Which stock are the most members of Congress buying? | the row's ticker and company name outlined; "4 members buying" lands under it on the word "4" |
| `concentration` | `/sample-portfolio`, the Portfolio Concentration card | Am I actually diversified? | the real row of BIGGEST INDUSTRY GROUPS ("Chip companies  9 holdings  ▲ high  33%"), 33% outlined, under the card's headline and its "Concentrated" pill |
| `portfolio` | `/sample-portfolio`, the two-ring donut | Where is my money, really? | the donut alone (captured as its own element), its biggest slice's label outlined |
| `market-pictures` | `/market`, the Market breadth card | How much of the market moved? | the whole card with its 20-close chart, the share ("83%") outlined |

- `smart-money` is the public **Congress trades tracker**, not the members-only Smart Money feed: title and caption it as
  Congress trades. `/smart-money`, `/portfolio` and `/dashboard/<ticker>` are sign-in only or count a guest view: the
  registry refuses them as a `url`. Never sign in.
- `concentration` and `portfolio` read the same card of the **read-only sample portfolio** (the screen says READ-ONLY
  SAMPLE in shot 4, the phone opens "Sample portfolio"): say so in the post text, and do not post the two close together.
  If only one goes out, `portfolio` (the donut is the stronger picture).
- `market-pictures` is a **dated fact**: `/market` is a permanent redirect to the home page's Market section (`/#market`;
  the registry's `lands_on`), the card shows "Last session (Mon, Nov 9)", and the hook names that weekday ("83% of stocks
  rose Monday!"). The session must be the last US session that had closed when the page was captured, or the script
  stops (also the day after a market holiday: the gate does not know holidays). Post it before the next session closes,
  or capture and render again; never later.
- Each entry carries a `post_note` (copied into `reel.json`): read it before the video is posted.

One entry holds:
- `url`, `lands_on` (only when the page redirects), `viewport`, `require` (texts the page must have), `refuse_if` (texts
  that mean its data is missing).
- `captures`: the bands, as in the daily short (`head` with our logo, `fact`, `key` at 6x). A text that starts with `=`
  matches a whole text node (`={ticker}` is the ticker V, not the V of "View"). `clip_el` (a CSS selector) captures one
  element's own box instead of a full-width band (the donut without the page margins beside it). Bands whose texts use a
  `{slot}` are captured second, after the values are read.
- `values`: how each slot is read from a capture's text: `{"from": capture, "after": line, "offset": n, "rx": regex with
  named groups, "as": name for the whole line, "prev"/"next": {name: regex}}`. `checks` stop a day that does not carry
  the story: `{"value", "min" | "max" | "equals"}`, `{"pct": p, "of": [count, total]}` (the page's own arithmetic holds;
  "0 of 0 stocks rose" and "3 of 4" are a page that did not load), `{"session": {...}, "sets": {"weekday", "date"}}`
  (the card's session label is the last closed session; sets the weekday the hook may name).
- `lines`: hook, hook_figure, confused, search, fact_a, fact_b. **A line never holds a number, a ticker or a name: those
  are slots.** `registry_problems` refuses a typed number, ticker or name (a capitalised word mid-sentence that is not in
  `proper_words`), a provider name, a banned word, advice or a prediction in any wording ("Buy it.", "It will go up."), a
  slot no rule reads. A name at the start of a sentence cannot be told from an ordinary word: read a registry diff.
- `phone`: `"tap"`. The phone in shot 3 shows one link with the text `search` and a thumb taps it. `search` is the text of
  the real link on our site ("Congress trades tracker" on the home page, the "Market" tab, "Sample portfolio"): a
  feature page is not reached by typing its name into the ticker search, so the phone does not type it.
- `fact_phrase`: the one data phrase; on a capture word for word, and read aloud word for word.
- `sources` and `claims`: the page text each factual line paraphrases (a text that is on its capture, or everything a
  capture shows). They are the phrasings the `claim_lines` gate checks, and they are listed in `reel.json`
  `claims_for_human_check`: read each line against its page text before the video ships. A source without a claim is a
  text that must be on the page for the story to hold (concentration: the row is flagged "high").
- `layout`: `stack` (header + fact card, then fact card + the key card) or `hero` (header + fact card, then both fly off
  sideways and the key capture, a chart or a whole card, fills the stage). `key.kind`: `figure` (a tag or a ticker, 64 px)
  or `visual` (a chart or a table row that stays whole: no zoom past the layout's scale). `key.also`: a second plain
  crop of the key capture that lands under the key card on a word of the line (smart-money's count).
- `hold4`, `lead5`, `hold5`: the still beats. Shot 5 starts `lead5` (0.5 s) before its line: the key lands and the camera
  settles, then the voice names it. `hold5` is about 1 s (1.6 s read as dead air).

### What a capture records (`capture.py`)

- `url` (asked for) and `final_url` (where the browser ended): both are gated.
- `visible_text`: every line that touches the captured area. A superset of the pixels; the provider, error and banned
  word checks read it (fail closed).
- `inside_text`: what the PNG really shows (the nodes, or the words of a node, whose boxes lie at least half inside).
  **Numbers, values, sources and the fact phrase are read from this one.** A line that only grazes a band's edge gives no
  allowed number.
- `seal`: a hash over the fields the gates trust. A sidecar edited after the capture fails `feature_capture`. It is not a
  signature: it catches a hand edit, not somebody who also recomputes it. Never edit a sidecar; capture again.

### When `make_feature_story.py` stops (exit 2, no story.json)

- a band or a value is missing, or a check fails (the page changed, or today's top row does not carry the story);
- the page says a `refuse_if` text, or a band shows an error, a loading word or a figure that did not compute;
- a provider or source brand is on what a band shows (the page's footer may name one; only the bands are checked);
- a capture is not from the feature's URL, did not end on its page, is not from today, or its sidecar was edited;
- the filled lines would fail the number, claim or spoken-figure gates.

No fallback and no explaining away: change the band in the registry, or do not make that video today.

### Gates that differ from the daily short

- **feature_capture** (new): our page (asked for and ended on), captured at most 12 h before the render, `require`
  present, no `refuse_if`, no error or loading state, no provider name on what is shown, the sidecar sealed.
- **feature_story** (new): the story is exactly the one `make_feature_story.py` writes from the registry and the
  sidecars now. Two checks: `cartoon_qa.feature_story_gate` (values, lines, claims, chip, phone, key, one outline on the
  key and no other, `post_date`, and the voice: the say map is the generator's and nothing else, no shot has its own say
  map, the spoken text names no provider, gives no advice, adds no number and no ticker) and
  `make_feature_story.story_drift` (the whole story is rebuilt and compared: a crop, a timing or a voice edited by hand
  is named). **A hand-edited say map was the hole found on 2026-11-10: the captions and every text gate stayed green
  while the voice said something else.**
- **no_provider_names**: the wider list (`cartoon_qa.VENDOR_EXTRA_WORDS`), look-alike letters and zero-width characters
  folded, on what is drawn, captioned, spoken and captured. **no_advice** (new): advice or a prediction in any wording, in
  the script, the drawn texts and the spoken text.
- **fact_phrase**: on a capture and read aloud, word for word (punctuation is not a word).
- **numbers_verbatim, claim_lines, hook, screen_numbers**: unchanged code, run against an item built from the sidecars
  at render time (`cartoon_qa.feature_item`): the allowed numbers are the numbers inside the captures.
- **spoken_numbers**: also refuses number words the value parser does not read ("a dozen", "hundreds", "half").
- **key_number**: a `figure` key is at least 64 px tall for 1.5 s (as before). A `visual` key (a chart, or a row that
  stays whole) needs the card at least 640 px wide with the outlined label at least 40 px tall for 1.5 s.
- **screenshot_real**: the capture's URL is the registry's URL.

Everything else (pill on every frame, brand spoken early and late, 15-22 s, at most 7 shots, payoff_brand, pill_clear,
captions, audio) gates exactly as for the daily short.

### Look at the frames (required, every render)

The provider check is a deny-list and a sidecar has only text. A source brand nobody listed, or a logo drawn as an image,
passes every gate. Before a feature short ships, open full frames of shots 4 and 5 (not only `sheet.png`) and check:
no provider or source name, no other company's logo, no crop cutting through a neighbouring line, the real card big and
legible, our logo readable, the key outlined. An index or ticker name on our own page ("S&P 500", "SPY") is a benchmark,
not a source credit; if the owner reads the rule wider, change the band.

### Adding a feature

1. Open the page as a logged-out guest at 390x844 and find one card that answers one question in two seconds. Prefer
   pages that count no guest view (server-rendered public pages; not `/dashboard/<ticker>`).
2. Capture the bands by hand with `capture.py` and look at them: nothing cut through, no provider name, no other
   company's logo, no real person as the hero. Compare `inside_text` with the PNG.
3. Add the entry. Write the lines so that they stay true whenever the page changes: only slots carry data. `search` is
   the text of the real link that opens the page.
4. `make_feature_story.py <id> --run <dir> --capture`, render, and look at `sheet.png` and full frames of shots 4 and 5
   (the list above).
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
