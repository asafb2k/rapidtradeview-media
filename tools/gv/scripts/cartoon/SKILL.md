---
name: cartoon-story-reel
description: Make a cartoon-story Reel / Short for RapidTradeView. Flat cartoon characters act out a relatable trader pain while the camera keeps moving, with word-by-word captions on a local voice. The payoff is a real screenshot of our page showing one real filing. Use it to turn one facts item into a 30-45 s vertical video.
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
| `cast.py` | the cast (Pip, Dale), props, sets, pulse rings, SFX bubbles, chips, phone frame | (imported) |
| `cartoon_qa.py` | the text gates (numbers, spoken numbers, screen numbers, providers, banned words, captions) | (imported, unit-tested) |
| `capture.py` | captures our page (phone viewport or a cropped card) + sidecar with DOM boxes | `.ops/cache/shot-venv` |
| `tts.py` | local Kokoro-82M voice with engine word timings (Apache-2.0) | `.ops/cache/tts-venv` |

The music is `../v6cat/vsco_score.py` (VSCO 2 CE samples, CC0). The end card, the encoder and the fonts are reused from
`../v6cat/card_reel.py`. Tests are in `tools/tests/test_cartoon_qa.py`.

## 1. Pick the item

Use today's `v/<date>/facts.json`. A good item:
- Has a real person or company the viewer recognises and ONE clear figure: `form4_buy` (a big buy), `congress_trade` or
  `earnings_result`. In the pilot, the executive chairman of an S&P 500 company bought $14.99M.
- Is fresh (`viral_check.fresh` is not False), preferably `in_500`.
- Has a `fact_phrases` entry that reads well aloud and uses "Nov 6"-style dates rather than ISO dates. That sentence is
  the only data sentence in the video, and it is copied verbatim.

## 2. Capture the real screen (on render day)

```
PY=.ops/cache/shot-venv/Scripts/python.exe
C=tools/gv/scripts/cartoon/capture.py
U=<item page_url without ?utm and #>
# the phone screen (viewport 430x932 @3x): the payoff reveal
$PY -I $C --url "$U" --out <run>/screens --name top --target "<heading text>" --target "<role text>"
# a cropped card around the key row: keeps unrelated small print and its numbers off screen
$PY -I $C --url "$U" --out <run>/screens --name trade --clip-from "Disclosed trades" --clip-to "View filing" \
     --target '$14,994,200' --target "Traded" --target "2026-11-06#2" --target "View filing"
```

Each PNG gets a sidecar `<name>.json` with `url`, `captured_at`, `sha256`, `visible_text` and the target boxes taken from
the DOM (no OCR). `TEXT#2` selects the 2nd occurrence inside the captured area. Look at the PNGs yourself.

The renderer fails the `screenshot_real` gate when the sha256 differs, when the capture date is not the item's date, or
when the URL is not the item's page. It fails `screen_numbers` when a number visible on the screenshot is neither an item
number nor acknowledged in `screen_numbers_ack` with a reason (for example "2": the header's guest page counter). Prefer
cropped cards to acknowledging numbers.

## 3. Write the story (the recipe)

Shape (26 shots maximum, 18 minimum). The timings come from the voice, so you write words, not seconds:

| Act | Shots | What |
|---|---|---|
| HOOK | 1 | Frame 0 is a complete scene. Caption chunk 1 is on screen, a chip states the stakes (no digits), the camera POPs. The first line is 2-7 words |
| SETUP | 4-6 | The relatable pain, in the second person ("You did not see it. You saw a cat.") |
| ESCALATE | 4-7 | The same pain grows absurd. At least 2 SFX bubbles and at least 1 PUNCH (pulse rings) |
| TURN | 1 | One word or line on a green PUNCH, entered with `"transition_in": "smash"` ("Or.") |
| PAYOFF | 3-5 | The verbatim fact phrase, split at its own word boundaries over `PAYOFF` shots (`"join": true`): the phone enters, then a zoom to the key number with a highlight, then the filing date |
| CALLBACK | 1 | No voice. Same set and cast as the hook, a silent gag (`"dur": 1.7`) |
| END | 1 | VO `Search RapidTradeView. Not investment advice.` (the card is drawn for you) |

Writing rules:
- Use 85-125 words, short sentences, deadpan. The comedy is noise and hype versus a boring, real filing.
- The characters are fiction. Never draw or caricature the real person, and never draw a logo. A character never "is"
  the insider; "you" read about the trade.
- Outside the fact phrase, use no numbers at all ("LATER.", not "3 MIN LATER"), no other tickers or names, and no
  advice, predictions or "this will go up". Never use the item's `banned_words`.
- Name no data vendors anywhere. "Form 4" and "SEC filing" are fine.
- Add a `say` entry for every display word the voice must pronounce differently. Written numbers are spelled out, for
  example `"$14.99M": "fourteen point nine nine million dollars"`, `"$KMI": "K M I"`, `"Nov": "November"`, `"6).": "sixth."`.
  The `spoken_numbers` gate parses the words back and checks the value.

Shot fields (positions are in 1080x1920 frame pixels):
```json
{"kind": "SCENE|CLOSE|PUNCH|PAYOFF|CALLBACK|END", "set": "gym|gym_floor|screen|rings:<violet|cyan|green|red>|payoff",
 "vo": "display words", "voice": "narrator|dale|<role in voices>", "join": false, "hold": 0.2, "pause": 0.12,
 "caption_band": "mid|low|high|payoff|top", "stress": ["heavy."], "transition_in": "cut|whip|smash",
 "move": {"type": "pop|push|pull|pan|tilt|zoom_to", "amt": 0.16, "focus": [540, 900], "dx": 70, "dy": -160, "rot": 4,
          "target": "<sidecar target text or list>", "from_target": "...", "z": 1.5, "at": 0.35, "dur": 0.8, "land": [540, 900]},
 "chip": {"text": "LEG DAY", "x": 250, "y": 340, "at": 0.0},
 "bubble": {"text": "ding.", "fill": "lime|cyan|white", "x": 790, "y": 520, "at": "word:app.", "tail": 120},
 "key_number": "$14,994,200",
 "els": [{"t": "pip|dale", "x": 540, "y": 1660, "hu": 260, "pose": "...", "expr": "...", "hold": ["phone"], "rot": 0,
          "swap": {"at": "word:Leg", "expr": "side"}, "enter": {"from": [0, -260], "dur": 0.4}, "brow": true, "kick": true},
         {"t": "screen|card", "name": "top", "w": 732, "rot": -4, "enter": {"from": [0, 1100], "dur": 0.3}},
         {"t": "highlight", "target": "$14,994,200", "at": 1.15},
         {"t": "barbell|bench_top|bench_side|phone|feed|tabs_burst|search_bar|finger|confetti|cat|sock", "...": "..."}]}
```
- The cast: `pip` (you: mint squircle head, violet hoodie, lime headband) has the poses idle, phone_hold, press, strain,
  shrug, point, arms_up, sip, wave and flail. `dale` (the gym friend: tiny head, coral tank top, shaker) has idle, sip,
  lean, point, empty and shout. Expressions: deadpan, side, shock, smug, panic, strain, happy, sip.
- An element's `x, y` is its feet (characters) or its centre (props). `"y": [a, b]` animates the value across the shot.
  A character's head centre is at `y - 1.8*hu` for Pip and `y - 4.82*hu` for Dale.
- Every caption band must stay off faces. Use `high` (820) when a face sits at y 1100-1400.
- A good pilot to copy: `.ops/cartoon-pilot/v1/story_render.json`. The writer's original script is in
  `.ops/cartoon-pilot/work/story.json`.

## 4. Render

```
C:/Users/USER/anaconda3/envs/rapidtradingview/python.exe tools/gv/scripts/cartoon/cartoon_reel.py \
    --story <run>/story_render.json --out <run>
```
A render takes about 3 minutes (about 0.2 s a frame). The voice is cached in `<run>/tts/` by text, voice and speed, so
re-renders after picture changes are fast. To iterate on the picture, import `cartoon_reel`, build
`Story -> Timeline -> Reel`, and save `reel.frame(t)` for a few times (no encode).

Then open `sheet.png` (a frame every 1.5 s) and watch the mp4. Check that captions are off faces, bubbles do not cover
the key number, the zoom lands on the number, and the hook frame is complete.

## 5. QA gates (exit 0 pass, 1 QA fail, 2 input or render error)

The gates are in `reel-qa.json`:
- **Container:** resolution, video_codec, duration (25-50 s), file_size, audio_present.
- **Audio:** audio_not_silent, audio_not_clipping, loudness (-15 to -13 LUFS, TP <= -1 dBTP), voice_present.
- **Words:** caption_verbatim (the captions joined are exactly the VO script), fact_phrase (one of the item's own
  phrasings), numbers_verbatim (every number in the VO, the spoken text, captions, chips, bubbles and the end card is an
  item number), spoken_numbers, screen_numbers, no_provider_names, banned_words, disclaimer_text, glyphs, safe_zones.
- **Proof:** screenshot_real (sha256 + capture date + URL), key_number (at least 64 px tall and inside x 120-900, y 300-1400
  for at least 1.5 s, matching the item figure).
- **Pace:** structure (18-26 shots, 0.7-2.6 s each, PAYOFF up to 4 s, END exactly 3 s, voice onset <= 0.10 s, the end VO
  done by 2.7 s, at least 5 s of real screen), caption_sync, first_frame_not_blank, motion_every_beat,
  no_static_run (<= 8 still frame pairs), disclaimer_on_screen.

## What not to do

- Do not reuse the reference videos' look: no bean body with stick limbs and dot hands, no dash eyes, no warm tan rooms
  with an orange sofa, no white starburst SFX, no yellow tags, no teal sunburst end card, none of their props or gags.
- Do not invent a number, a quote or a UI. No mock screens: if the capture fails, the video does not ship.
- Do not loop the ending back to the opening. The disclaimer card closes the video.
- Do not post. This tool only renders. Posting belongs to the publishing pipeline and a human or agent who owns it.
- Do not commit mp4 files, screenshots or voice files. They go in `.ops/` (untracked).
