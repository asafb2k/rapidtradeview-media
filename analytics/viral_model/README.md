# Viral model kit (within-author)

A small, offline kit that learns which **content, format and timing** choices make an X post do better
**than the same author's usual post**, validates that honestly, and scores 2-3 draft variants of a post.

Built for a finance-X corpus (~17k posts, one or more snapshots per post) whose exact column names are
unknown: every column is mapped in a JSON config. Python 3 with pandas, numpy and scikit-learn only
(scipy, which scikit-learn installs, is used for the sparse text matrix). No network, no secrets.

| file | what it does |
|---|---|
| `train.py` | prepares the data, trains and validates the models, writes `report.json`, `report.md`, `predictions_oof.csv`, `model.pkl` |
| `score_drafts.py` | scores draft variants (text + media type + hour) with `model.pkl` and prints them ranked |
| `features.py` | derives text features from raw text; encodes features identically for training and drafts |
| `config.example.json` | the column map and every setting, with defaults |
| `drafts.example.json` | input format for `score_drafts.py` |
| `synthetic.py` | synthetic dataset with planted effects, for a dry run and the tests (`--age-window 12 36`: one snapshot per post at an age that correlates with the features) |
| `tests/test_viral_model.py` | recovery, leakage, chance-level and end-to-end tests |

## Run it

```bash
python -c "import sklearn, pandas, numpy; print(sklearn.__version__)"   # scikit-learn >= 1.6, pandas >= 2

cp config.example.json config.json          # then edit: data_path + every column name to YOUR names
python train.py --config config.json        # ~1-5 min on 17k posts; --quick for a smoke run
# read out/report.md (or out/report.json)
python score_drafts.py --model out/model.pkl --drafts drafts.json --author-median-views 1500
python score_drafts.py --model out/model.pkl \
    --text 'BREAKING: $NVDA insider bought $12M' --media video --hour 14 \
    --text '$NVDA insider bought $12M. Signal or noise?' --media image --hour 14

# wide age window (e.g. 24 h +/- 12 h, one snapshot per post): adjust for age, see "Wide age window"
python train.py --config config.json --age-adjust loglinear          # or spline
# is an effect carried by a few authors? re-estimate it without the K authors with most posts at that level
python train.py --config config.json --drop-top-authors 5 --drop-effect opener=number --drop-effect media_type=video
```

`--age-adjust`, `--drop-top-authors` and `--drop-effect` override `target.age_adjust`, `models.drop_top_authors`
and `models.drop_top_effects` in the config. Both are off by default, so a config without them reproduces earlier
results exactly.

Dry run without data:

```bash
python synthetic.py --out synthetic_posts.csv --config-out synthetic_config.json
python train.py --config synthetic_config.json
python score_drafts.py --model out_synthetic/model.pkl --drafts drafts.example.json
python -m pytest tests -q
```

Accepted data formats: `.csv`, `.tsv`, `.parquet` (needs pyarrow), `.jsonl`, `.json`, `.pkl`.

### Mapping columns (`config.json`)

`columns` maps kit roles to your column names (`null` = you do not have it):

- **required:** `author`, `views` (impressions), and the post age: `age_hours`, or `created_at` + `snapshot_utc`
- **strongly recommended:** `text`, `created_at` (hour, weekday and the time split come from it), `id` or `url`
- **used if present:** `likes`, `reposts`, `replies`, `quotes`, `bookmarks` or `engagement_rate` (secondary target),
  `followers` (only to build the small-author buckets, never a predictor), `found_via` (composition and per-source
  metrics), `media_type`, `poll`, `thread`, `is_quote`, `author_median_views` (only with
  `target.author_median_source = "column"`), `hour_utc` / `weekday` (only when `created_at` is missing)

Every predictor must be known **when the post is published**. `thread` is unmapped (`null`) in
`config.example.json` for that reason: map it only if it records that the author posted a thread. If it was read
from the conversation at scrape time, self-replies added after a post took off make it post-publication
information and its effect can run backwards. The report lists a warning whenever `thread` is mapped.

If your table already holds views at 24 h in one column (no snapshots), map it to `views` and set
`target.age_filter = false`. Timestamps may be ISO strings or epoch seconds/milliseconds; all times are UTC.

`feature_columns` lets you map your precomputed text features (length, cashtag count, ...). By default
(`text_feature_source = "derive"`) the kit derives them from `text` anyway, because `score_drafts.py` can only
derive them from draft text and training must see the same definitions. The report's "Derived vs supplied" table
shows how well your columns match ours; switch to `"columns"` only if they agree.

`extra_numeric_features` / `extra_categorical_features` add your other content features as-is (for example
visual features that exist for a subset of posts: missing values are imputed with a missing-indicator for the
linear models and left as NaN for gradient boosting). `train.py` refuses any extra feature or `feature_columns`
column that is a mapped label/author/follower column or whose name looks like an engagement, reach or
post-publication column: `follower`, `impression`, `view`, `like`, `repost`, `retweet`, `reply`, `bookmark`,
`engagement`, `viral`, `median`, `quote_count`, `quotes`, `click`, `expand`, `share`, `snapshot`, or a name token
`rt`, `score`, `rank`, `age` (`is_quote` is allowed). Set `allow_suspicious_feature_names = true` only if such a
name really is a content feature known at posting time.

## Design

**Target.** For each post keep the snapshot closest to 24 h, within 24 h +/- 3 h (`target.age_hours`,
`age_tolerance_hours`); posts with no snapshot in the window are dropped. Then

    y = log(views + 1) - log(author_median_views + 1)

The author median is the median views of that author's **other** posts at the same fixed age (leave-one-out),
so a post never sets its own baseline; or a supplied column (`author_median_source = "column"`, which must already
exclude the post). Authors with fewer than 5 posts at the fixed age are dropped (`min_posts_per_author`).
`y = 0` means "a typical post for this author"; `exp(y)` is "x the author's median views".
With `target.age_adjust` on, views are first moved to the fixed age (see "Wide age window") and `y` is built from
the adjusted views the same way.

Optional binary label: the top 20 % of `y` (`binary_top_fraction`), threshold taken from the training rows.
Secondary target: within-author engagement rate,
`log(ER + eps) - log(author leave-one-out median ER + eps)`, ER = your `engagement_rate` column, else
(likes + reposts + replies + quotes + bookmarks) / views, `eps` = 1 % of the median positive ER.

**Features** (content, format, timing only; `features.py`):

| feature | derived from text as |
|---|---|
| `char_len`, `word_count`, `line_breaks` | characters; whitespace words without URLs; `\n` count |
| `list_lines` | lines starting with `-`, `*`, `•`, `✅`, `👉`, `1.`, `2)` ... |
| `cashtag_count`, `hashtag_count`, `mention_count` | `$TICKER` (not `$5`), `#tag` (not `#1`), `@handle` (outside URLs) |
| `emoji_count`, `emoji_position` | Unicode emoji ranges (approximate; a flag counts once); none / start / middle / end |
| `opener` | first line after leading emoji: `breaking`, `just_in`, `cashtag`, `number`, `question`, `other` |
| `number_count`, `dollar_count`, `percent_count` | numbers outside tickers/handles; `$` followed by a digit; `%` |
| `has_question`, `allcaps_ratio`, `link_present` | `?` outside URLs; share of 2+ letter words in CAPS (cashtags and the BREAKING / JUST IN opener excluded); any URL |
| `media_type`, `poll`, `thread`, `is_quote` | your columns |
| `hour_bin` (4 h bins) and `weekday` (linear); `hour_utc`, `weekday_num` (trees) | `created_at` in UTC |

Caveat: X API text often ends with a `t.co` link for attached media, which would make `link_present` track media.
If your text has those, strip them before training or map your own `link_present` column.

Never features: followers, the author median or any author baseline, engagement counts, snapshot age (also not
with `age_adjust`: it changes the target, never the features, and drafts are scored without an age), author
identity. Categorical levels seen < 30 times collapse into `other`; the most common level is the reference.

**Within-author estimation.** Ridge and elastic net are fitted on author-demeaned features and target
(`models.within_author_demean`, a fixed-effects regression), so only differences between posts of the same author
identify an effect. Without it, author style leaks in: in the synthetic data big accounts use BREAKING more, and the
raw regression understates the planted effects by about 10-35 % (3 seeds checked). Predictions still use the raw features; the score
difference between two drafts of one author is the same either way.

**Models.** Ridge and elastic net (standardized features; alpha and l1 ratio chosen by GroupKFold inside the
training data), HistGradientBoosting, and a text
model (TF-IDF word 1-2-grams stacked with the structured features, one ridge) as the stand-in for embeddings.
The binary label uses HistGradientBoosting with isotonic calibration fitted on 25 % of training authors held out
from the classifier. The primary model (`models.primary_model = "auto"`) is the one with the best GroupKFold
pairwise accuracy.

**Effects table.** The per-feature effects come from the same within-author regression with a near-zero penalty
(`models.effects_alpha`, 1e-6), not from the predictive ridge: its cross-validated alpha (100-300 on the synthetic
data) shrank effects by 3-8 %. Over 30 synthetic seeds (120 authors each) the mean estimates are video +0.517,
image +0.258, BREAKING +0.423, question -0.309, per cashtag +0.107, 12-15 UTC +0.193 against the planted +0.50,
+0.25, +0.40, -0.30, +0.10, +0.20. The 95 % CIs are percentile intervals from an author-resampled bootstrap and are
approximate: over the same 30 seeds (200 bootstraps each) they covered the planted value 0.92 of the time on
average, 0.83 for `cashtag_count` and `hour_bin=h12-15`, and 0.93 for the zero-effect features. Read them as
a guide, not an exact 95 %.

The report prints, for this effects model:
- the bootstrap B in the section heading (`bootstrap B = 200`);
- `N posts nonzero` and `N authors nonzero` per row: how many posts and how many distinct authors have the
  feature (level) at all. An effect seen in 400 posts from 6 authors is mostly those 6 authors;
- its **own** within-author pairwise accuracy (GroupKFold by author, same folds and metric as the predictive
  models) next to a shuffled-target control of the same model (target permuted within author, 5 permutations).
  This checks that the model the effects come from ranks posts at all, not only the primary model;
- with `models.drop_top_authors = K` (`--drop-top-authors K`): for each effect named in `drop_top_effects`
  (`--drop-effect opener=number`, repeatable; empty = every effect whose CI excludes 0), the K authors with the
  most posts at that level (nonzero value) are removed and the same regression and bootstrap are rerun. The
  report shows both estimates side by side, with N posts / N authors nonzero and the dropped authors (posts at the
  level each). An effect that halves or loses its CI is carried by a few accounts. `--drop-effect` without
  `--drop-top-authors K` is an error; with K but nothing named and no CI excluding 0, the report warns.

**Validation.**
- **GroupKFold by author** (5 folds): no author is ever in both train and test (checked; the report prints the
  overlap, which must be 0). This answers "does it work for authors it has never seen?".
- **Time split:** the last 4 weeks (`time_test_weeks`) are test. Authors appear on both sides; this answers "does
  it still work on newer posts?".
- **Metrics**, each with its N:
  - **within-author pairwise accuracy** (headline): over all same-author post pairs in the test set whose `y`
    differ by more than `pair_margin` (0.25, about 28 % more views), the share where the model ranks the better
    post higher. 0.5 = chance. Pair-weighted, with a 95 % CI from resampling authors; the author-macro version
    (mean of per-author accuracies, authors with >= 10 pairs, each author weighted equally) is in every table and
    in the headline.
  - **Spearman** of prediction vs `y` overall, and the mean within-author Spearman.
  - **lift@top decile:** share of the top 10 % predicted posts that are real top-20 % posts, divided by the base rate;
    plus the median "x author median" of that decile.
  - the same metrics for **small authors** (median followers < 1k and < 100), and per `found_via` value.
- **Shuffled-target control:** `y` is permuted within each author and the whole GroupKFold pipeline is rerun 5
  times. It must land near 0.5; its spread is the noise floor for comparing models.
- **Corpus composition:** the drop funnel (loaded -> has views -> age window -> one snapshot per post -> authors with
  >= 5 posts), counts by `found_via`, media type, posts per author, authors by follower bucket.

Every rate in the report carries its N. Rows with fewer than 200 pairs or 10 authors are flagged
`LOW N: not a finding`.

## Reading the report (`out/report.md`)

1. **Headline line.** Primary-model pairwise accuracy with CI vs the shuffled control, and the author-macro accuracy.
   The model is useful only if the CI's lower bound clears the control's maximum. If the pair-weighted and
   author-macro numbers differ a lot, a few prolific authors drive the headline (see the tiny-account section). On real X data expect modest numbers (0.55-0.65); 0.60 means
   that of two posts by the same author whose views differ by 28 % or more, the model picks the better one 60 % of
   the time.
2. **Corpus.** Check the funnel: how many posts survived the age window, how many authors were dropped, whether
   one `found_via` source dominates, and whether a few authors hold most posts.
3. **GroupKFold and time split tables.** Similar numbers on both = it generalizes to new authors and to newer
   posts. Per-fold spread shows stability. Small-author rows show how well the pooled model, trained mostly on
   bigger authors' pairs, ranks posts of the small authors in the corpus (count their authors: often a few dozen).
   They do not estimate the effects for small accounts, and they do not show that the effects hold for an account
   with 5-50 views a post (see below).
4. **Feature effects (within-author least squares).** First line: the effects model's own pairwise accuracy vs
   its shuffled control; if it does not clear the control, do not read the table. `per unit` is the change in `y` (log views vs the author's median) for one unit of
   the feature; `x views` = exp(per unit), e.g. `media_type=video 1.60` = +60 % views vs the author's median compared
   with the reference level (`none`), holding the other features fixed. Trust an effect when its CI excludes 0,
   `N posts nonzero` and `N authors nonzero` are large, it survives `--drop-top-authors`, and it also appears in the elastic net (selected in most bootstraps)
   and in the permutation table. With ~30 features expect one or two CIs to exclude 0 by chance (the synthetic run
   shows `is_quote` doing exactly that).
5. **Permutation importance.** How much pairwise accuracy drops when one feature is shuffled: the features the
   ranking actually relies on.
6. **Binary label.** AUC, Brier vs the base rate alone, and the calibration table: after isotonic calibration the
   predicted and observed rates per quintile should be close.
7. **Text terms.** Indicative only: words mix topic, tickers and author style; no CIs.
8. **Secondary ER.** Same tables for engagement rate; questions often help ER while hurting views.

These are observational estimates. Comparing within an author removes author size and style, not news flow: a
BREAKING post often rides a bigger story. Use the effects to choose between drafts, then test them on real posts.

## Wide age window

The target compares posts **at the same age**. With the default window (24 h +/- 3 h, closest snapshot per post)
age barely varies. A wide window (24 h +/- 12 h, one snapshot per post) lets views grow with age inside the window:
a post seen at 36 h has more views than the same post at 12 h. If the feature mix differs with age (for example
the scraper reached videos or BREAKING posts later), the age gap shows up as a feature effect. Author fixed effects
do not fix this: the age varies between posts of the same author.

`target.age_adjust` (default `"none"`):

- `"loglinear"`: `log(views+1) = author effect + slope * log(age_hours) + content features + noise`;
- `"spline"`: the same with a natural cubic spline of `log(age_hours)` (`age_spline_df`, default 3: knots at the
  data range and the 1/3 and 2/3 quantiles; linear beyond the range).

The regression is pooled across posts, with author fixed effects (demeaned within author), and with the content
features as controls (`age_adjust_controls = "features"`, default). Every post is then moved to the fixed age,
`log(views_adj+1) = log(views+1) - [f(age) - f(24 h)]`, and the within-author target is built from the adjusted
views as usual. Age is never a model feature and is not used at scoring. The report's "Age adjustment" section
prints the slope `d log(views+1) / d log(age)` (for the spline, its average over posts) with an author-bootstrap
95 % CI (B = `models.bootstrap`), and the fitted curve on an age grid (`x views vs ref`).

Why the features are controls: if the feature mix correlates with age, an age-only regression attributes the
features' effect to age and the adjustment over-corrects. `age_adjust_controls = "none"` gives that age-only
fit, for comparison. With the features as controls, the effects table on the adjusted target approximately
equals the effect estimates of one regression with age as a control (Frisch-Waugh-Lovell; only approximately,
because the target also subtracts the author's leave-one-out median of the adjusted views).

The age curve is fitted once on all posts, before GroupKFold, not refitted inside each fold, so test-fold views
help choose it. On synthetic data (4 seeds, null and planted effects) refitting it per fold moved pairwise
accuracy by at most 0.0003; the report states this. The effects-table bootstrap (and the elastic-net and
`--drop-top-authors` bootstraps) refits the age curve on every author resample, so the effects CIs include the
age-fit uncertainty; without that, CIs of features that correlate with age would be too narrow.

Synthetic check (`make_synthetic(age_window=(12, 36), age_exponent=0.6)`: views grow as age^0.6; videos are seen
6 h older, BREAKING 5 h older, questions 4 h younger; N = 10 seeds, 5,484-5,772 posts and 140 authors each after
filters). Mean estimate over seeds, (seeds whose 95 % CI, B = 100, covers the planted value; in the adjusted
columns each bootstrap draw also refits the age curve). The "fixed 24 h
twin" is the same data with every snapshot at exactly 24 h, i.e. what the wide window should reproduce:

| effect | planted | fixed 24 h twin | wide, unadjusted | wide, loglinear | wide, spline | wide, loglinear age-only |
|---|---|---|---|---|---|---|
| media_type=video | +0.50 | +0.516 (10/10) | +0.646 (0/10) | +0.512 (9/10) | +0.513 (9/10) | +0.407 (0/10) |
| opener=breaking | +0.40 | +0.419 (9/10) | +0.526 (0/10) | +0.417 (9/10) | +0.418 (9/10) | +0.332 (5/10) |
| has_question | -0.30 | -0.279 (10/10) | -0.370 (9/10) | -0.275 (8/10) | -0.275 (8/10) | -0.201 (4/10) |
| media_type=image (age-neutral) | +0.25 | +0.260 (9/10) | +0.261 (8/10) | +0.260 (9/10) | +0.260 (9/10) | +0.258 (9/10) |
| cashtag_count (age-neutral) | +0.10 | +0.124 (10/10) | +0.122 (10/10) | +0.123 (10/10) | +0.123 (10/10) | +0.125 (8/10) |
| age slope | +0.60 | - | - | +0.612 (10/10) | +0.596 (10/10) | +1.085 (0/10) |

What the adjustment assumes, and what it cannot fix:

- **One growth curve for all posts.** It removes the average age trend. If videos accrue views later than text
  posts (a different curve shape), a wide window still mixes that into the video effect. Compare the effects from
  a narrow window (`age_tolerance_hours = 3`, adjustment off) with the adjusted wide window: if they agree, the
  wide window only added posts; if they disagree, prefer the narrow one.
- **Age must vary within authors.** Authors whose posts were all seen at the same age add nothing to the slope;
  the report counts the authors with more than one distinct age.
- **Selection by age.** If posts seen late were found because they were already popular (search results), that
  is selection on the outcome, not growth with age; no age model removes it (see "Selection on the outcome").
- With several snapshots per post, the kit still keeps one per post (closest to the target age); the slope comes
  from differences between posts, not from a post's own growth.

## Transfer to a tiny account

The kit ranks drafts of one post against each other. It does not predict what a tiny account's post will get,
and nothing in the report proves the effects transfer to one. Specifically:

- **Count noise.** At 5-50 views a post, the difference between two posts is mostly noise. At 20 views the pair
  margin of 0.25 log units is about +/- 5 views, and one repost by a bigger account outweighs any format effect.
  The target is `log(views + 1)`, so `exp(per unit)` multiplies views + 1, not views: at single- and double-digit
  counts it is not a views multiplier, and an effect of +0.2 is smaller than the post-to-post noise.
- **The headline is pair-weighted.** An author with n posts adds n(n-1)/2 pairs, so a 200-post author outweighs
  ten 20-post authors about 10 to 1. `validation.max_pairs_per_author` defaults to 1,000,000, which in practice is
  no cap. Compare the author-macro column, or set `max_pairs_per_author` (for example 500; pairs are then sampled)
  and rerun.
- **Small-author rows are not small-account effects.** They score the pooled model on the few small authors in the
  corpus; the effects themselves are estimated mostly from larger authors' posts.
- **Selection on the outcome.** Posts collected via search (`found_via = search`), especially popular or Top
  results, were picked partly because they did well. That inflates whatever those posts have in common and biases
  the effects. Check the per-`found_via` rows, and rerun on the panel rows alone (filter the input file) to see
  whether an effect survives without them.

So: use `score_drafts.py` to choose between drafts, and treat the account's own A/B posts as the real check:
alternate the variants on comparable posts at the same hour, record views at the same fixed age, and decide only
after enough posts per arm to see a difference larger than the noise (report N, not rates from a handful of posts).

## Scoring drafts

`drafts.json` (see `drafts.example.json`) is a list of variants:

```json
[{"name": "A", "text": "BREAKING: ...", "media_type": "video", "hour_utc": 14},
 {"name": "B", "text": "...?", "media_type": "image", "hour_utc": 14, "weekday": "Tue"}]
```

Optional per draft: `weekday` (0 = Mon or `"Mon"`; without it the score is averaged over the 7 weekdays),
`post_time_utc` (ISO; sets hour and weekday), `poll`, `thread`, `is_quote`, `extra` (values for extra features).
Media types (and extra categorical values) must use the training labels: a label the model never saw, or saw
fewer than `min_level_count` times, is scored as `other` or the reference level, and `score_drafts.py` prints a
warning naming the trained levels.

Output: rank, `score` (predicted `y`), `x median` = exp(score), `P(top 20%)` from the calibrated classifier, the
secondary ER score, and with `--author-median-views N` an estimated view count. Below the table: the largest
feature contributions per draft and the gap between #1 and #2; a gap under `pair_margin` is a tie. `--json`
prints machine-readable output. Rankings are what the model was validated on; the absolute level assumes the
author's usual post looks like the training average.

Synthetic run (planted: video +0.50, image +0.25, BREAKING +0.40, question -0.30, +0.10 per cashtag,
12-15 UTC +0.20; 4,242 posts / 112 authors after filters):

```
Primary model: elastic_net. Within-author pairwise accuracy (GroupKFold by author) 0.628 [0.618, 0.638],
N = 67,477 pairs from 112 authors; 0.5 = chance. Author-macro: 0.626, N = 112 authors. Shuffled-target control
(ridge, 5 permutations): mean 0.496, range 0.483-0.504.

| feature          | per unit | 95% CI           | x views | CI excludes 0 | N posts nonzero |
| media_type=video | +0.4958  | [0.4204, 0.5763] | 1.642   | yes           | 1,212           |
| opener=breaking  | +0.3907  | [0.3095, 0.4734] | 1.478   | yes           | 953             |
| has_question     | -0.2548  | [-0.3753, -0.1297] | 0.775 | yes           | 947             |

rank   score  x median    P(top 20%)  ER score  variant
1     +0.768      2.16          0.24    +0.055  A breaking + video [video, 14h UTC]: BREAKING: $NVDA insider ...
2     -0.121      0.89          0.14    +0.072  B question + image [image, 14h UTC]: $NVDA insider bought ...
3     -0.214      0.81          0.14    -0.151  C plain text, evening [none, 22h UTC]: An $NVDA insider ...
```

## Settings (defaults in `train.py` `DEFAULTS`)

| key | default | meaning |
|---|---|---|
| `target.age_hours` / `age_tolerance_hours` | 24 / 3 | fixed age window; closest snapshot per post wins |
| `target.age_filter` | true | false = rows are already at a fixed age |
| `target.min_posts_per_author` | 5 | authors below this (at the fixed age) are dropped |
| `target.author_median_source` | `leave_one_out` | or `column` (`author_median_views`) |
| `target.binary`, `binary_top_fraction` | true, 0.2 | calibrated top-fraction classifier |
| `target.secondary_er` | true | within-author ER target |
| `validation.group_folds` | 5 | GroupKFold folds (by author) |
| `validation.time_test_weeks` | 4 | time-split test window |
| `validation.pair_margin` | 0.25 | min `|dy|` for a pair to count |
| `validation.small_author_followers` | [1000, 100] | small-author buckets (author median followers) |
| `validation.min_pairs_for_rate` / `min_authors_for_rate` | 200 / 10 | below this a row is flagged LOW N |
| `validation.shuffle_control_repeats` | 5 | permutations in the control |
| `models.ridge` / `elastic_net` / `hgb` / `text` | true | models to fit |
| `models.primary_model` | `auto` | or a model name |
| `models.within_author_demean` | true | fixed-effects estimation for linear models |
| `models.min_level_count` | 30 | rarer categorical levels -> `other` |
| `models.bootstrap` / `bootstrap_enet` | 200 / 100 | author-resampled bootstraps for CIs |
| `models.effects_alpha` | 1e-6 | penalty of the effects-table regression (near zero = unshrunk) |
| `target.age_adjust` | `none` | `loglinear` or `spline`: move every post to the fixed age first (wide age window) |
| `target.age_adjust_controls` | `features` | content features as controls in the age fit; `none` = age only |
| `target.age_spline_df` | 3 | natural-spline df for `age_adjust = "spline"` |
| `models.drop_top_authors` | 0 | K > 0: re-estimate effects without the K authors with most posts at that level |
| `models.drop_top_effects` | [] | effects to re-estimate (e.g. `opener=number`); empty = every effect whose CI excludes 0 |
| `validation.max_pairs_per_author` | 1,000,000 | pairs per author before sampling (effectively no cap) |

Model hyper-parameters (`ridge_alphas`, `enet_alphas`, `enet_l1_ratios`, `hgb_params`, `tfidf`, `text_alphas`)
can be overridden under `models` too. `model.pkl` is a pickle: load it only with the same kit and scikit-learn
version (`score_drafts.py` warns on a version mismatch) and never load a pickle from an untrusted source.
