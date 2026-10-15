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
| `synthetic.py` | synthetic dataset with planted effects, for a dry run and the tests |
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
```

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

If your table already holds views at 24 h in one column (no snapshots), map it to `views` and set
`target.age_filter = false`. Timestamps may be ISO strings or epoch seconds/milliseconds; all times are UTC.

`feature_columns` lets you map your precomputed text features (length, cashtag count, ...). By default
(`text_feature_source = "derive"`) the kit derives them from `text` anyway, because `score_drafts.py` can only
derive them from draft text and training must see the same definitions. The report's "Derived vs supplied" table
shows how well your columns match ours; switch to `"columns"` only if they agree.

`extra_numeric_features` / `extra_categorical_features` add your other content features as-is (for example
visual features that exist for a subset of posts: missing values are imputed with a missing-indicator for the
linear models and left as NaN for gradient boosting). `train.py` refuses any extra feature that is a mapped
label/author/follower column or whose name looks like one (`follower`, `impression`, `view`, `like`, ...); set
`allow_suspicious_feature_names = true` only if such a name really is a content feature.

## Design

**Target.** For each post keep the snapshot closest to 24 h, within 24 h +/- 3 h (`target.age_hours`,
`age_tolerance_hours`); posts with no snapshot in the window are dropped. Then

    y = log(views + 1) - log(author_median_views + 1)

The author median is the median views of that author's **other** posts at the same fixed age (leave-one-out),
so a post never sets its own baseline; or a supplied column (`author_median_source = "column"`, which must already
exclude the post). Authors with fewer than 5 posts at the fixed age are dropped (`min_posts_per_author`).
`y = 0` means "a typical post for this author"; `exp(y)` is "x the author's median views".

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

Never features: followers, the author median or any author baseline, engagement counts, snapshot age, author
identity. Categorical levels seen < 30 times collapse into `other`; the most common level is the reference.

**Within-author estimation.** Ridge and elastic net are fitted on author-demeaned features and target
(`models.within_author_demean`, a fixed-effects regression), so only differences between posts of the same author
identify an effect. Without it, author style leaks in: in the synthetic data big accounts use BREAKING more, and the
raw regression understates the planted effects by about 10-35 % (3 seeds checked). Predictions still use the raw features; the score
difference between two drafts of one author is the same either way.

**Models.** Ridge and elastic net (standardized features; alpha and l1 ratio chosen by GroupKFold inside the
training data; coefficients with 95 % CIs from an author-resampled bootstrap), HistGradientBoosting, and a text
model (TF-IDF word 1-2-grams stacked with the structured features, one ridge) as the stand-in for embeddings.
The binary label uses HistGradientBoosting with isotonic calibration fitted on 25 % of training authors held out
from the classifier. The primary model (`models.primary_model = "auto"`) is the one with the best GroupKFold
pairwise accuracy.

**Validation.**
- **GroupKFold by author** (5 folds): no author is ever in both train and test (checked; the report prints the
  overlap, which must be 0). This answers "does it work for authors it has never seen?".
- **Time split:** the last 4 weeks (`time_test_weeks`) are test. Authors appear on both sides; this answers "does
  it still work on newer posts?".
- **Metrics**, each with its N:
  - **within-author pairwise accuracy** (headline): over all same-author post pairs in the test set whose `y`
    differ by more than `pair_margin` (0.25, about 28 % more views), the share where the model ranks the better
    post higher. 0.5 = chance. Pair-weighted, with a 95 % CI from resampling authors; an author-macro version too.
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

1. **Headline line.** Primary-model pairwise accuracy with CI vs the shuffled control. The model is useful only if
   the CI's lower bound clears the control's maximum. On real X data expect modest numbers (0.55-0.65); 0.60 means
   that of two posts by the same author whose views differ by 28 % or more, the model picks the better one 60 % of
   the time.
2. **Corpus.** Check the funnel: how many posts survived the age window, how many authors were dropped, whether
   one `found_via` source dominates, and whether a few authors hold most posts.
3. **GroupKFold and time split tables.** Similar numbers on both = it generalizes to new authors and to newer
   posts. Per-fold spread shows stability. Small-author rows tell whether the effects hold for accounts like ours.
4. **Feature effects (ridge).** `per unit` is the change in `y` (log views vs the author's median) for one unit of
   the feature; `x views` = exp(per unit), e.g. `media_type=video 1.60` = +60 % views vs the author's median compared
   with the reference level (`none`), holding the other features fixed. Trust an effect when its CI excludes 0,
   `N posts nonzero` and `N authors` are large, and it also appears in the elastic net (selected in most bootstraps)
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

## Scoring drafts

`drafts.json` (see `drafts.example.json`) is a list of variants:

```json
[{"name": "A", "text": "BREAKING: ...", "media_type": "video", "hour_utc": 14},
 {"name": "B", "text": "...?", "media_type": "image", "hour_utc": 14, "weekday": "Tue"}]
```

Optional per draft: `weekday` (0 = Mon or `"Mon"`; without it the score is averaged over the 7 weekdays),
`post_time_utc` (ISO; sets hour and weekday), `poll`, `thread`, `is_quote`, `extra` (values for extra features).
Media types must use the training labels (unknown labels fall back to `other` or the reference level).

Output: rank, `score` (predicted `y`), `x median` = exp(score), `P(top 20%)` from the calibrated classifier, the
secondary ER score, and with `--author-median-views N` an estimated view count. Below the table: the largest
feature contributions per draft and the gap between #1 and #2; a gap under `pair_margin` is a tie. `--json`
prints machine-readable output. Rankings are what the model was validated on; the absolute level assumes the
author's usual post looks like the training average.

Synthetic run (planted: video +0.50, image +0.25, BREAKING +0.40, question -0.30, +0.10 per cashtag,
12-15 UTC +0.20; 4,242 posts / 112 authors after filters):

```
Primary model: elastic_net. Within-author pairwise accuracy (GroupKFold by author) 0.628 [0.618, 0.638],
N = 67,477 pairs from 112 authors; 0.5 = chance. Shuffled-target control (ridge, 5 permutations): mean 0.496,
range 0.483-0.504.

| feature          | per unit | 95% CI           | x views | CI excludes 0 | N posts nonzero |
| media_type=video | +0.4724  | [0.4016, 0.5491] | 1.604   | yes           | 1,212           |
| opener=breaking  | +0.3754  | [0.3079, 0.4509] | 1.456   | yes           | 953             |
| has_question     | -0.2430  | [-0.3462, -0.1364] | 0.784 | yes           | 947             |

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

Model hyper-parameters (`ridge_alphas`, `enet_alphas`, `enet_l1_ratios`, `hgb_params`, `tfidf`, `text_alphas`)
can be overridden under `models` too. `model.pkl` is a pickle: load it only with the same kit and scikit-learn
version (`score_drafts.py` warns on a version mismatch) and never load a pickle from an untrusted source.
