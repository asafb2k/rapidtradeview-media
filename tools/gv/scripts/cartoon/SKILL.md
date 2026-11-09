---
name: cartoon-story-reel
description: Make a cartoon-story Reel / Short for RapidTradeView in the one-idea format. A cartoon character hears a news item in a confusing way, opens RapidTradeView, and our real page shows the real fact; the brand is on screen the whole time. Use it to turn one facts item into a 15-20 s vertical video, generated from the item by make_story.py.
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
| `cartoon_reel.py` | story.json -> `reel_9x16.mp4` + `reel.json` + `reel-qa.json` + `sheet.png` | conda env `rapidtradingview` |
| `cast.py` | the cast (Pip, Dale), the branded phones, sets, pulse rings, chips, receipt, card frame | (imported) |
| `cartoon_qa.py` | the text, brand and format gates (pure functions, unit-tested) | (imported) |
| `capture.py` | captures our page (a band between two texts) + sidecar with DOM boxes | `.ops/cache/shot-venv` |
| `tts.py` | local Kokoro-82M voice with engine word timings (Apache-2.0) | `.ops/cache/tts-venv` |

Music: `../v6cat/vsco_score.py` (VSCO 2 CE, CC0). End card, encoder, fonts and the brand pill: `../v6cat/card_reel.py`.
Tests: `tools/tests/test_cartoon_qa.py`, `tools/tests/test_cartoon_make_story.py`.

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
