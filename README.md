# RapidTradeView media

Public video files for RapidTradeView's social posts (https://www.rapidtradeview.trade). Not investment advice.

The Windows tasks run `tools/run_daily.ps1` to prepare media and publish the daily manifest. They do
not post to social accounts. Weekday picks preparation stays at 13:45 New York time; the picks post
is scheduled for 15:00. The existing tasks require the PC on and the user logged in.

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
