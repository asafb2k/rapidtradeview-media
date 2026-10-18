# RapidTradeView media

Public video files for RapidTradeView's social posts (https://www.rapidtradeview.trade). Not investment advice.

The Windows tasks run `tools/run_daily.ps1` to prepare media and publish the daily manifest. They do
not post to social accounts. Weekday picks preparation stays at 13:45 New York time; the picks post
is scheduled for 15:00. The existing tasks require the PC on and the user logged in.

Video packages carry the provenance of their actual muxed audio. The manifest preserves a present
`music` object unchanged, validating the original-score synthesis/sample fields, source, license and
sample-archive hash. Missing or null legacy package metadata stays omitted; omission grants no audio
permission. Deploy the web consumer's optional music schema before merging this producer change,
because older kit validators reject the new field. Do not retrofit music into a picks manifest after
its readiness deadline: provenance is part of the post's content binding, so that changes the proof.

From 2026-09-30, picks must finish a successful live preflight at least 60 minutes before their post
time. New picks generated after that deadline enter the manifest held. Preflight also holds picks
whose first successful live check finishes late, and the periodic check catches unverified picks
that missed its usual 60–90 minute window. It stores `readiness-4.json` beside the private preflight
report, bound to the exact caption, media and source data. Unchanged picks verified on time remain
eligible during later checks; changed content needs a new timely check. Local staging and `--now`
replays never create that live receipt. A held post needs explicit review; the runner does not invent
another story, move the posting time or send a text-only substitute.

Roll out a reviewed code change through a main-branch PR before the scheduled run. The existing runner
already does `git pull --ff-only`, so no task re-registration or time change is needed. Check the
private `preflight-4.json` and `readiness-4.json` by 14:00 New York time; media readiness is separate
from the posting agents' delivery receipt. Run the offline regression suite with the project conda
Python: `python -m pytest tools/tests -q`.

Instagram is Reels only (Growth decision 2026-10-10: a Reel is the only Instagram format non-followers see). From
`manifest.IG_REELS_ONLY_FROM` (2026-10-11) every Instagram post, weekday and weekend, is placement `reel` with its
`reel_9x16.mp4`; the weekday cap is 5 Reels (the old 1 Reel + 4 feed posts), no feed post, no Story. An image story
(earnings week / today) used to go out as a feed image: its render hook (`hook_v6cat.py`) now also runs growth-video
`scripts/v6cat/still_reel.py` (a ~9 s Reel made from the story's own approved image: slow push-in, the standard 3 s end
card, a VSCO bed with provenance; its QA must pass), `daily.py stage` puts `reel_9x16.mp4`, `still/reel_9x16.jpg|png` and
`music.json` (the Reel's provenance and file hash) beside the images, and the manifest post carries
`media: {"reel_9x16": url}` next to its `images`: Instagram posts the Reel, X / Threads / Pinterest keep the images. An
image story without a passing Reel is not staged (no feed-image fallback). Manifests of earlier days stay valid.
Deploy the kit change first (`tools/kit-patch/socialKitVideos-reels-only.patch`, applied to the app repo's
`frontend/src/lib/socialKitVideos.ts` and its test from a fresh worktree off origin/main: `git apply <patch>`): the kit
rejects a whole day whose manifest it does not understand, and the old kit takes neither a lone `reel_9x16` in `media`
nor more than one Reel on a weekday. Merge this branch only after that kit is on prod and before the first run on or after
2026-10-11 (or move `IG_REELS_ONLY_FROM` later with it).

Card Reel (Growth 2026-10-12: a second Instagram Reel a day). Every facts build (`Publish-Facts`) runs `tools/card_reel.py`
first. Weekdays from 10:00 New York time (the first facts build at or after it, normally the 10:00 intraday refresh) and
on the weekend pass, it picks ONE item a day, the first available of earnings_result (largest market cap), congress_trade,
form4_buy (both: buys before sales, then the largest amount at the top of its range, then the freshest filing),
chart_pattern; ties keep the facts order; renders its share card (media[0], our page's 1200x630 Open
Graph PNG, never the site's generic card) through growth-video `scripts/v6cat/card_reel.py` (the item's facts_text as the
caption, a slow push-in on a plain dark background, the standard end card, the VSCO bed, 13 s; its QA must pass), commits
`v/<date>/cards/<item_id>/reel_9x16.mp4` + `music.json` (provenance and file hash), waits for Pages, and then adds
`{"url": <that Pages URL>, "kind": "reel", "alt": <facts_text>}` to that item's `media` in facts.json (the compare counts
media URLs, so the file republishes). A failed download, card check, render or QA is logged in
`<work>/card-reel.json`; the same item gets one more try, never another item, and the facts and videos go on.

Access policy (2026-10-09): the API and site answer non-browser clients with 403 unless they send the
private `X-RTV-Automated-QA` header. The runner's tools read it at run time through `tools/qa_header.py`
(the key lives in a local file outside the repo, is sent to our own hosts only, and is never printed,
logged or written to a manifest, evidence file or test fixture). A missing key sends no header and prints
one warning that names the file. The selector leaves out Congress rows traded more than 90 days before
their disclosure (re-filings and very late filings): they are counted as `late_filing_over_90d`.

Facts rank and IndexNow (Growth 2026-10-12, bets B1 / B3). `tools/facts.py` gives every item a `rank` (higher = more
newsworthy) and a `rank_why`, sorts the file by it, keeps one Congress item per filer a day (`congress_trade` or
`ptr_summary`, the higher-ranked; the rest counted in `left_out.per_filer_cap`), and adds two roundup kinds,
`earnings_tomorrow_roundup` and `ptr_summary`: the only posts `tools/grok_review.py` lets carry several cashtags (at most 4,
all from the item). A `ptr_summary` is built only for a whole filing (the capped feed read reaches past the window start
and no row of the filing was filtered out; otherwise `left_out.ptr_summary_incomplete` says why); it carries every
filing's official URL in `source_urls`, and an X post of it cites at least one in its self-reply. After
every facts build on a weekday the runner calls `tools/indexnow_facts.py` (`Invoke-IndexNowFacts`): it pings IndexNow with
the day's distinct landing pages (no UTM, no anchor, never an `/earnings/reports/` page), deduped over 7 days, at most
100 a day, paused 24 h after a 429 / 403 and 6 h after any other 4xx; each send's count and status go to
`D:\rtv-ops\tracks\growth\research\indexnow-facts.log`. The key is the site's own `<key>.txt` in the app repo's
`frontend/public` (never copied here). `-NoPush` / `-SelectOnly` make it a dry run.

Market pillars (HQ 2026-10-18, owner: "I keep seeing the same boring niche posts"; plan
`D:/rtv-ops/tracks/hq/social-content-2026-10-18/PLAN.md`). `tools/facts.py` also builds items about the whole market and
the names everyone knows from two GETs a pass on our API (`/market/pictures`, `/market/flows`; stored data, no Yahoo):
market_move, mega_mover, congress_flow, insider_flow, reddit_buzz, earnings_week_preview, earnings_reaction,
sector_rotation, breadth_day and basket_week (`tools/market_facts.py`; each only when its trigger fires). Items are ranked
by an audience rank (recognisability, magnitude, freshness, novelty from our own posts read through `tools/post_history.py`),
gated (weekend replay, small caps, cooldowns) and carry `pillar`, `context_numbers`, `context_tickers`, `angles` and
`cooldown`. A market item's image is its share card pinned to Pages by `tools/pin_cards.py` (`Invoke-PinCards` in
`Publish-Facts`): `v/<date>/cards/market-<panel>-<data date>-<fingerprint>.png`, downloaded once per panel and data with the
QA header; an item whose card is not served is left out. The preflight pass refreshes facts until 17:45 ET on weekdays
(the map publishes the session about 16:50 ET). `tools/grok_review.py` checks the new rules (cashtags and numbers from
tickers / allowed_numbers plus the context lists, the market-wording guard, the pinned card) and the variety lint (warn
first, reject a repeat the same day; state `D:/rtv-ops/tracks/growth/research/grok-variety-state.json`).

Market pillar review fixes (HQ 2026-10-18, before the first Monday pre-market posts). One content rule set,
`tools/claims.py`, runs in three places: the facts build checks each item's own facts_text and angles (an angle that fails
is dropped, an item whose text fails is not published), `tools/grok_review.py` checks every draft, and the Growth post audit
gets it through `grok_review.wording_reasons`. Rules, for every item type: our universe is never the S&P (S&P 500,
S&P500, SPX, "the index"; only a picks post may compare "vs SPY"), and "largest US-listed", not "largest US companies";
comparatives and superlatives (led, biggest, worst, most, only, first, ...) only as the item's `claims` back them
(`market_facts.py` computes them, e.g. `sector_leaders`: the best / worst % move inside each named sector), one claim's
companies / sectors per sentence; no company put in a sector its `ticker_sectors` entry does not show; the 30-day insider
totals say "open-market" and "officers and directors" (`scoped_numbers`); a 5-session item's window follows the build date
(`when`: "this week" only on a weekday of that week, "last week", else "in the week to Oct 16"); a breadth post never
contradicts its card (`card_message`: a card headlining a broad decline bars "narrow", "concentrated", "typical",
"median"). Variety in facts: the first 8 items (`top8`) hold at most 2 session-map items, at most one small cap, no lead
ticker or headline number twice (`headline`), and 4+ pillars when the day has them (`top8_out` says why an item is
below); the novelty term, the cooldown gate and the validator's rule 7 compare lead tickers across pillars
(`post_history` headline_tickers). Caps are map-first for every item type (`market_cap_feed_usd` keeps the feed's value).
