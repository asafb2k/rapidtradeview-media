# Draft lint (playbook v2)

One Python file, standard library only (Python 3.8+). It reads a post draft and that day's `facts.json` and lists
where the draft departs from **RTV Social Playbook v2** (owner approved 2026-10-15). It is **advisory**: it never
approves or rejects. Compliance (numbers, cashtags per item, links, disclaimer, banned words, media) stays with the
validator's APPROVE / REJECT answer, which now carries the same findings as `NOTES (playbook v2)` lines.

```bash
curl -sO https://asafb2k.github.io/rapidtradeview-media/analytics/draft_lint/draft_lint.py
python draft_lint.py --facts https://asafb2k.github.io/rapidtradeview-media/v/2026-10-15/facts.json \
    --draft draft.json --history recent_posts.json
```

| flag | meaning |
|---|---|
| `--facts` | the day's facts.json, URL or local path (the only network read) |
| `--draft` | local path: one draft object or a list of them |
| `--history` | optional local path: our own recent posts, for the spacing, question and link-per-day rules (platform matched case-insensitively) |
| `--now` | optional ISO time to lint at (default: now, UTC); a draft's `planned_at` wins |
| `--format` | `text`, `json` or `both` (default) |

Exit code 0 after a lint (whatever it finds), 2 when an input cannot be read.

## Inputs

Draft, the same object the validator takes, plus an optional planned time:

```json
{"item_id": "2026-10-15-earnings-result-BNY-b982b0", "platform": "x",
 "text": "Bank of New York Mellon beat Q3 estimates: ... $BNY Not investment advice.",
 "reply_text": "Full results: https://www.rapidtradeview.trade/dashboard/BNY?...", "link": "...",
 "media_url": "https://www.rapidtradeview.trade/dashboard/BNY/opengraph-image",
 "planned_at": "2026-10-15T12:34:43Z"}
```

History, our own posts only (a list, or `{"posts": [...]}`); rows with `kind` `reply`, `self_reply` or `comment`
are skipped, so a deliberate self-thread does not count for spacing:

```json
[{"platform": "x", "posted_at": "2026-10-15T11:04:09Z", "text": "Travelers, Truist, ... $TRV $TFC $MTB $CFG $RF ..."}]
```

## Output

Each finding is `[level] WARN|NOTE rule: message`:

- **level** is the playbook's evidence: `real` (TIER 1, measured within author), `likely` (TIER 2, adopt and log),
  `stop` (no reach effect).
- **WARN** is a playbook rule the draft breaks; **NOTE** is information: an experiment arm (E1 video, E2 link,
  E3 earnings speed), a rule compliance overrides today, or a hashtag count with no reach effect.
- **score** = the number of `real` + `likely` WARNs. Lower is better; 0 means nothing to fix.

## Rules

| rule | level | fires when |
|---|---|---|
| cashtags | real | fewer than 2 or more than 5 distinct cashtags; only mega-caps / only index-ETFs; a cashtag the facts do not support (the item's tickers, other items' tickers in the same facts, moves_like peers). For item types compliance holds to ONE cashtag today (everything but the earnings roundup, PTR summary, moves_like and picks), the count and mega-only findings are NOTEs |
| numbers | real | fewer than 2 concrete figures, or none in the first line (filing names such as Form 4, fiscal-period labels such as Q3 2026 / FY26, and cashtags are not figures) |
| macro | real | Fed / FOMC / CPI / PPI / yields / Treasury / oil / jobs report / GDP / inflation with no stock cashtag; predictive words (will, expect, likely, set to, poised) in a macro post; "vs $5.56B expected" / "than expected" is results wording and does not count |
| spacing | real | `--history`: our last post on that platform went out less than 2 h before the planned time |
| length | likely | under 25 words; over 60 words on a niche item (congress, Form 4, earnings) |
| link | likely | NOTE for any link in the body ("E2 arm?"); WARN when `--history` shows another body-link post on that platform in the last 24 h |
| mention | likely | an @mention in the post or its self-reply |
| question | likely | `--history`: the draft asks a question and one of our last 2 posts did too |
| breaking | likely | the BREAKING / JUST IN label (upper case anywhere, or "Breaking:" / "Just in -" leading a line; "Just in time", "Breaking down" are not it) unless the item's event time (published_at, updated, filed ...) is under 60 min old; a date without a time cannot be verified |
| video | likely | NOTE on X when the item has a Reel but the draft's media is not video ("E1 arm?") |
| earnings_speed | likely | NOTE when an earnings result first appeared (first_seen_at, else published_at) more than 60 min before the planned time |
| list | likely | 4+ list lines (bullet, numbered, emoji- or cashtag-led) in a niche post |
| self_thread | likely | the self-reply is longer than the post, or carries numbers the post lacks |
| hashtags | stop | NOTE for more than 1 hashtag. Emoji and caps are not linted |

Words are counted on the text without links. Mega-cap and index/ETF lists are the EDA's fixed lists
(`MEGACAP`, `INDEX_ETF` in the file).
