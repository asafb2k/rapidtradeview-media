---
name: cartoon-story-reel
description: Make a cartoon-story Reel / Short for RapidTradeView. Flat cartoon characters act out a relatable trader pain while the camera keeps moving, with word-by-word captions on a local voice. The payoff is a real screenshot of our page showing one real filing. Use it to turn one facts item into a 25-40 s vertical video.
---

# Cartoon-story Reel: how to make the next one

The format comes from indie-app shorts that got 4-8x the views of screen recordings. Flat cartoon characters land in an
absurd everyday situation, the camera never stops, captions change word by word, sound-effect words pop up, and the
payoff is the REAL app screen. We copy that method, not anyone's art. Our characters, sets and comic language are our
own (`cast.py`). The full measured spec is in `.ops/cartoon-pilot/work/format-spec.md`.

The lesson: **the story is fiction, the data is not.** Every number on screen or in the voice is copied verbatim from
today's facts item. The cartoon only sets up the moment when you look at the real record.

## Files

| File | What it is | Runs in |
|---|---|---|
| `cartoon_reel.py` | story.json -> `reel_9x16.mp4` + `reel.json` + `reel-qa.json` + `sheet.png` | conda env `rapidtradingview` |
| `cast.py` | the cast (Pip, Dale), props, sets, pulse rings, SFX bubbles, chips, search phone, receipt, phone frame | (imported) |
| `cartoon_qa.py` | the text gates (numbers, number words, weekdays, claim lines, screen numbers, providers, banned words, captions, occlusion) | (imported, unit-tested) |
| `capture.py` | captures our page (phone viewport or a cropped card) + sidecar with DOM boxes | `.ops/cache/shot-venv` |
| `tts.py` | local Kokoro-82M voice with engine word timings (Apache-2.0) | `.ops/cache/tts-venv` |

The music is `../v6cat/vsco_score.py` (VSCO 2 CE samples, CC0). The end card, the encoder and the fonts are reused from
`../v6cat/card_reel.py`. Tests are in `tools/tests/test_cartoon_qa.py`.

## 1. Pick the item

Use today's `v/<date>/facts.json`. A good item:
- Has a real person or company the viewer recognises and ONE clear figure: `form4_buy` (a big buy), `congress_trade` or
  `earnings_result`. In the pilot, the executive chairman of an S&P 500 company bought $14.99M.
- Is fresh (`viral_check.fresh` is not False), preferably `in_500`.
- Has a `phrasings` entry that reads well and uses "Nov 6"-style dates rather than ISO dates. That sentence is the only
  full data sentence in the video, copied verbatim (`fact_phrase`), and every other factual line is a tagged
  paraphrase of it (section 3).

## 2. Capture the real screen (on render day)

```
PY=.ops/cache/shot-venv/Scripts/python.exe
C=tools/gv/scripts/cartoon/capture.py
U=<item page_url without ?utm and #>
# a cropped card around the key row: keeps unrelated small print and its numbers off screen
$PY -I $C --url "$U" --out <run>/screens --name trade --clip-from "Disclosed trades" --clip-to "View filing" \
     --target '$14,994,200' --target "Traded" --target "2026-11-06#2" --target "View filing"
```

Each PNG gets a sidecar `<name>.json` with `url`, `captured_at`, `sha256`, `visible_text` and the target boxes taken from
the DOM (no OCR). `TEXT#2` selects the 2nd occurrence inside the captured area. Look at the PNGs yourself.

Then frame only what the story needs with the card's `"crop": [x0, y0, x1, y1]` (screenshot px; a plain rectangle of the
real capture, pixels untouched, recorded in `reel.json`). The pilot crops the trade row to its left column
`[84, 432, 436, 632]`: KMI BUY / Traded 2026-11-06 / $14,994,200 Officer, with no disclaimer paragraph, no table header
and no right-hand cell cut mid-word. Choose crop edges in the gaps between words. Skip the page header (`top`): it is
small text and empty tiles, a slideshow beat.

The renderer fails `screenshot_real` when the sha256 differs, when the capture date is not the item's date, or when the
URL is not the item's page. It fails `screen_numbers` when a number in a screen's `visible_text` is neither an item
number nor acknowledged for THAT screen: `"screen_numbers_ack": {"trade": {"0": "the SELLS tile"}}`. An acknowledgement
is refused when the number's value equals one the item carries (`$67.3B`, `30`, the amount): data is never explained
away. Prefer crops to acknowledgements.

## 3. Write the story (the recipe)

Shape (18-26 shots). The timings come from the voice, so you write words, not seconds:

| Act | Shots | What |
|---|---|---|
| HOOK | 1-3 | COLD OPEN ON THE NUMBER. Frame 0 is a medium close-up (a character 50% or more of the width, never top-down): a character says the stake with the item's figure ("A chairman just bought $14.99M of his own stock."), the figure pops into a chip, the other character reacts (spit-take, `SPLURT.`). Only then the setup line |
| SETUP | 3-5 | The relatable pain, second person ("Monday. Leg day." / Dale: "Kinder. KMI. Friday. You didn't see it?" / "You saw a cat."). Name the person or ticker here so the search later pays off |
| ESCALATE | 4-6 | About 6 s. The pain grows absurd, each beat a NEW image (tabs burst, tabs become plates, the bar bends, Dale spots and does not help). At least 2 SFX bubbles and 1 PUNCH |
| TURN | 1-2 | "Or." on a green PUNCH (`"transition_in": "smash"`), then the search: `search_phone` types the name letter by letter (a clack per letter) in Pip's hands |
| PAYOFF | 3 | 5-6 s in all. Whip into the real card (`zoom_to` + `highlight` on the key number, a PEEK head in a corner), cut to a character reaction, then the `receipt` card with the full fact phrase held about 2 s while the voice says a short line ("Form 4, filed Friday.") |
| CALLBACK | 1 | 1.2 s at most, WITH a line that resolves the hook (Pip: "Friday. Saw it." / Dale's jaw drops, `clank.`) |
| END | 1 | VO `Search RapidTradeView. Not investment advice.` (the card is drawn for you) |

Writing rules:
- 70-110 words, short sentences, deadpan. Let Dale carry the dialogue (it is a scene, not a narration): voices
  `narrator`, `dale`, `pip`. Captions are coloured by speaker (Dale coral, Pip mint, narrator white). Do not put quote
  marks or brackets in a line to mark speech; they are dropped from captions anyway.
- The characters are fiction. Never draw or caricature the real person, and never draw a logo. A character never "is"
  the insider; "you" read about the trade.
- **Factual lines.** Any line with a number, a weekday of the item's dates, the ticker, the person's or company's name, or
  a trade word (bought, sold, filed, chairman, ...) must carry `"claim": "<phrasing id>"`, the item phrasing it
  paraphrases. The `claim_lines` gate checks its numbers, weekday, ticker and name words against that phrasing, and
  `reel.json` lists every tagged line under `claims_for_human_check`. **A person reads those lines against the phrasing
  before the video ships** (a paraphrase like "his own stock" can still shift the meaning).
- Numbers: write figures exactly as the item does ("$14.99M"), never as words in `vo` ("fifteen million" fails
  `numbers_verbatim`); "one" as in "one app" is fine. The `say` map spells them for the voice, keyed by the exact display
  word with its punctuation (`"$14.99M.": "fourteen point nine nine million dollars."`), and `spoken_numbers` parses the
  value back.
- **Weekdays and dates are bound to the posting day.** A weekday must be the weekday of an item date ("Friday" for a Form 4
  filed 2026-11-06) or of the story's `post_date` (`"post_date": "2026-11-09"`, story time: "Monday. Leg day."). The
  `weekdays` gate fails "Monday" if `post_date` is not a Monday. If the video goes out a day later, the item is still
  usable through the next weekday, but change `post_date` and any story-time weekday line (or drop it) and re-render.
- Outside the facts: no other tickers or names, no advice, predictions or "this will go up", none of the item's
  `banned_words` (inflections count: "moons", "mooning"). Name no data vendors anywhere. "Form 4" and "SEC filing" are fine.

Framing rules (the `caption_occlusion` gate checks them; read its hits):
- Captions sit in ONE band at y 1230 (64% of the height) in every shot. Frame each shot around it: faces and held props
  (Pip's phone or shaker, Dale's shaker, the bar and its plates) above about y 1150 at the end of the camera move, legs
  and torsos under the band. Bubbles and chips off the band too.
- Medium and close shots (Pip `hu` 400-500, head 40-50% of the width; Dale `hu` 300-330). A wide two-shot only for the
  callback. No top-down shots except one gag at most.
- A character is never off screen for more than 2 s (`character_on_screen`): over a screen or feed, add a `peek` head.
- Pip's head centre is at `y - 1.8*hu` (minus `0.32*squat*hu` when squatting), Dale's at `y - 4.82*hu`.

Shot fields (positions are in 1080x1920 frame pixels):
```json
{"kind": "HOOK|SCENE|CLOSE|PUNCH|PAYOFF|CALLBACK|END", "set": "gym|gym_floor|screen|rings:<violet|cyan|green|red>|payoff",
 "vo": "display words", "voice": "narrator|dale|pip|end", "claim": "<phrasing id>", "join": false, "hold": 0.2,
 "pause": 0.12, "dur": 0.85, "stress": ["heavy."], "transition_in": "cut|whip|smash",
 "move": {"type": "pop|push|pull|pan|tilt|zoom_to", "amt": 0.16, "s0": 1.0, "focus": [540, 900], "dx": 70, "dy": -160,
          "rot": 4, "target": "<sidecar target text or list>", "from_target": "...", "z": 1.5, "at": 0.35, "dur": 0.8,
          "land": [540, 900], "drift": 0.03},
 "chip": {"text": "$14.99M", "x": 800, "y": 420, "at": "word:$14.99M", "size": 82},
 "bubble": {"text": "SPLURT.", "fill": "lime|cyan|white", "x": 830, "y": 430, "at": 0.05, "tail": 160},
 "peek": {"who": "pip|dale", "expr": "shock", "x": 170, "y": 1650, "hu": 250, "rot": 14, "at": 0.3, "from": [-320, 0]},
 "key_number": "$14,994,200",
 "els": [{"t": "pip|dale", "x": 540, "y": 1388, "hu": 460, "pose": "...", "expr": "...", "hold": ["phone"],
          "squat": 0.8 | [0.1, 0.35] | {"reps": 1, "depth": 0.8}, "bar": {"plates": 2, "tabs": [2, 16], "bend": [0, 0.45]},
          "swap": {"at": "word:Leg", "expr": "panic"}, "enter": {"from": [0, -260], "dur": 0.4}, "brow": true},
         {"t": "card", "name": "trade", "crop": [84, 432, 436, 632], "w": 900, "rot": -2, "enter": {"from": [0, 900], "dur": 0.3}},
         {"t": "highlight", "target": "$14,994,200", "at": 0.75},
         {"t": "receipt", "text": "$fact_phrase", "w": 900, "rot": -2, "enter": {"from": [0, 1300], "dur": 0.3}},
         {"t": "search_phone", "w": 500, "text": "Kinder", "at": "word:search", "rate": 0.075},
         {"t": "spray", "x": 420, "y": 725, "dir": -12, "n": 56},
         {"t": "feed|tabs_burst|confetti|barbell|bench_side|phone|cat|sock", "...": "..."}]}
```
- The cast: `pip` (you: mint squircle head, dot eyes with thick brows, lime headband, violet hoodie with lime cuffs and
  mitten hands) has the poses idle, phone_hold, rack (front-rack barbell, use with `squat` and `bar`), spit, sip, strain,
  shrug, point, arms_up, wave and flail; expressions deadpan, side, shock, smug, panic, strain, happy, sip, spit. `dale`
  (the gym friend: tiny head, coral tank top, shaker) has idle, sip, lean, point, empty and shout.
- Gym logic: "leg day" is a squat (`pose: rack` + `squat`), not a bench press. Spotting a squat is a real thing.
- An element's `x, y` is its feet (characters) or its centre (props). `[a, b]` animates a value across the shot.
- Text drawn by props (the feed's "SOCKS" and "ad", the search text, the receipt) goes through every text gate.
- The pilot to copy: `.ops/cartoon-pilot/v2/story_render.json`.

## 4. Render

```
C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe tools/gv/scripts/cartoon/cartoon_reel.py \
    --story <run>/story_render.json --out <run>
```
A render takes about 4 minutes. The voice is cached in `<run>/tts/` by text, voice and speed, so re-renders after
picture changes are fast. To iterate on the picture, import `cartoon_reel`, build `Story -> Timeline -> Reel`, call
`text_gates(...)` (it includes occlusion, hook and structure) and save `reel.frame(t)` for a few times (no encode).

Then open `sheet.png` (a frame every 1.5 s) and watch the mp4. Check that the hook frame is a close-up with the number
coming, captions are off faces, bubbles do not cover the key number, the card shows whole words, and read every line in
`reel.json` `claims_for_human_check` against its phrasing.

## 5. QA gates (exit 0 pass, 1 QA fail, 2 input or render error)

The gates are in `reel-qa.json`:
- **Container:** resolution, video_codec, duration (25-50 s), file_size, audio_present.
- **Audio:** audio_not_silent, audio_not_clipping, loudness (-15 to -13 LUFS, TP <= -1 dBTP), voice_present.
- **Words:** caption_verbatim (the captions joined are the VO script, quote marks and brackets dropped), fact_phrase
  (one of the item's own phrasings, read aloud or shown on a receipt for at least 1.8 s), numbers_verbatim (every number
  in the VO, captions, chips, bubbles, props, the receipt and the end card is an item number; no spelled-out numbers),
  weekdays, claim_lines, spoken_numbers, screen_numbers (per screen), no_provider_names, banned_words (with inflections),
  disclaimer_text, glyphs, safe_zones.
- **Proof:** screenshot_real (sha256 + capture date + URL), key_number (at least 64 px tall and inside x 60-960,
  y 300-1400 for at least 1.5 s, matching the item figure).
- **Pace and picture:** structure (18-26 shots, 0.7-2.6 s each, PAYOFF up to 4 s, payoff window 4-7 s from the first to
  the last PAYOFF shot, at least 1.8 s of real screen, END exactly 3 s, voice onset <= 0.10 s, the end VO done by
  2.7 s), hook (frame-0 character >= 50% of the width, not upside down, an item number on screen by 2.5 s),
  character_on_screen (no gap over 2 s), caption_occlusion, caption_sync, first_frame_not_blank, motion_every_beat,
  no_static_run (<= 8 still frame pairs), disclaimer_on_screen.

## What not to do

- Do not reuse the reference videos' look: no bean body with stick limbs and ball hands, no dash or half-lidded deadpan
  eyes on Pip, no warm tan rooms with an orange sofa, no white starburst SFX, no yellow tags, no teal sunburst end card,
  none of their props or gags.
- Do not open on the setup. The first 3 s carry the stake (the figure), not "Monday".
- Do not read the fact phrase aloud over a static screen: a 12 s corporate sentence is a retention cliff. Show it.
- Do not draw a pointing finger or any long shape reaching into frame; hands are mittens holding things.
- Do not invent a number, a quote or a UI. No mock screens of our product: the search phone is a cartoon phone, the real
  screen comes after the whip. If the capture fails, the video does not ship.
- Do not loop the ending back to the opening. The disclaimer card closes the video.
- Do not post. This tool only renders. Posting belongs to the publishing pipeline and a human or agent who owns it.
- Do not commit mp4 files, screenshots or voice files. They go in `.ops/` (untracked).
