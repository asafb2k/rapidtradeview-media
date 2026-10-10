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

Access policy (2026-10-09): the API and site answer non-browser clients with 403 unless they send the
private `X-RTV-Automated-QA` header. The runner's tools read it at run time through `tools/qa_header.py`
(the key lives in a local file outside the repo, is sent to our own hosts only, and is never printed,
logged or written to a manifest, evidence file or test fixture). A missing key sends no header and prints
one warning that names the file. The selector leaves out Congress rows traded more than 90 days before
their disclosure (re-filings and very late filings): they are counted as `late_filing_over_90d`.
