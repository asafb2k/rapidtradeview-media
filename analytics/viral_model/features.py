"""Feature derivation for the viral-model kit (pandas + numpy only).

Two jobs:
  1. derive_text_features(text): content/format features computed from the raw post text
     (length, words, line breaks, list lines, cashtags, hashtags, mentions, emoji, emoji position,
     opener type, numbers / $ / %, question, all-caps ratio, link present).
  2. build_raw_features(df, cfg) + FeatureSpec: turn a prepared posts table (or draft variants) into
     the numeric matrices the models use. The same code path scores drafts, so training and scoring
     see identical features.

Only content, format and timing features are produced. Followers, the author baseline, engagement
labels and snapshot age are never features (see FORBIDDEN_ROLES and check_no_forbidden).
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Text features
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
CASHTAG_RE = re.compile(r"(?<![\w$])\$[A-Za-z]{1,6}(?:\.[A-Za-z]{1,2})?(?![A-Za-z0-9_])")
DOLLAR_AMOUNT_RE = re.compile(r"\$\s?\d")
NUMBER_RE = re.compile(r"(?<![A-Za-z_])\d[\d,]*(?:\.\d+)?")
PERCENT_RE = re.compile(r"%")
HASHTAG_RE = re.compile(r"(?<![\w&#])#(?!\d+\b)\w+")
MENTION_RE = re.compile(r"(?<![\w.@])@\w{1,15}")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z']+")
EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flags come in pairs)
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F7FF"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "☀-⛿"
    "✀-➿"
    "⬅-⬇⬛⬜⭐⭕"
    "⏩-⏺"
    "‼⁉〰〽㊗㊙"
    "]"
)
REGIONAL_RE = re.compile("[\U0001F1E6-\U0001F1FF]")
LIST_LINE_RE = re.compile(
    "^\\s*(?:[-*•▪►▶➡✅✔☑·\U0001F539\U0001F538\U0001F449]|\\d{1,2}[.)])\\s*\\S"
)
INVISIBLE = "️‍​"
OPENER_WORD_RE = re.compile(r"^\W*(?:BREAKING|JUST[\s-]?IN)\b", re.I)

TEXT_NUMERIC = [
    "char_len",
    "word_count",
    "line_breaks",
    "list_lines",
    "cashtag_count",
    "hashtag_count",
    "mention_count",
    "emoji_count",
    "number_count",
    "dollar_count",
    "percent_count",
    "allcaps_ratio",
]
TEXT_BINARY = ["has_question", "link_present"]
TEXT_CATEGORICAL = ["opener", "emoji_position"]
TEXT_FEATURES = TEXT_NUMERIC + TEXT_BINARY + TEXT_CATEGORICAL

OPENERS = ["breaking", "just_in", "cashtag", "number", "question", "other"]


def _emoji_count(s: str) -> int:
    n = len(EMOJI_RE.findall(s))
    regional = len(REGIONAL_RE.findall(s))
    return n - regional // 2  # a flag is two regional indicators


def _opener(text: str) -> str:
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    s = EMOJI_RE.sub("", first)
    s = s.lstrip(" \t*_-:|>•\"'([" + INVISIBLE)
    upper = s.upper()
    if upper.startswith("BREAKING"):
        return "breaking"
    if upper.startswith("JUST IN") or upper.startswith("JUST-IN") or upper.startswith("JUSTIN:"):
        return "just_in"
    if re.match(r"\$[A-Za-z]", s):
        return "cashtag"
    if re.match(r"[$+\-]?\d", s):
        return "number"
    first_sentence = re.split(r"(?<=[.!?])\s", s, maxsplit=1)[0].rstrip()
    if first_sentence.endswith("?"):
        return "question"
    return "other"


def _emoji_position(text: str) -> str:
    s = text.strip().strip(INVISIBLE).strip()
    if not s or not EMOJI_RE.search(s):
        return "none"
    if EMOJI_RE.match(s):
        return "start"
    if EMOJI_RE.match(s.rstrip(INVISIBLE)[-1]):
        return "end"
    return "middle"


def derive_text_features(text) -> dict:
    """Content/format features of one post. Non-string input counts as empty text."""
    if not isinstance(text, str) or (isinstance(text, float) and math.isnan(text)):
        text = ""
    no_url = URL_RE.sub(" ", text)
    no_tags = CASHTAG_RE.sub(" ", no_url)
    words = WORD_RE.findall(OPENER_WORD_RE.sub(" ", no_tags))  # the opener keyword is its own feature
    caps = sum(1 for w in words if len(w) >= 2 and w.isupper())
    return {
        "char_len": len(text),
        "word_count": len(no_url.split()),
        "line_breaks": text.count("\n"),
        "list_lines": sum(1 for ln in text.splitlines() if LIST_LINE_RE.match(ln)),
        "cashtag_count": len(CASHTAG_RE.findall(no_url)),
        "hashtag_count": len(HASHTAG_RE.findall(no_url)),
        "mention_count": len(MENTION_RE.findall(no_url)),
        "emoji_count": _emoji_count(text),
        "number_count": len(NUMBER_RE.findall(no_tags)),
        "dollar_count": len(DOLLAR_AMOUNT_RE.findall(no_url)),
        "percent_count": len(PERCENT_RE.findall(no_url)),
        "allcaps_ratio": caps / len(words) if words else 0.0,
        "has_question": int("?" in no_url),
        "link_present": int(bool(URL_RE.search(text))),
        "opener": _opener(text),
        "emoji_position": _emoji_position(text),
    }


def text_feature_frame(texts: pd.Series) -> pd.DataFrame:
    rows = [derive_text_features(t) for t in texts.tolist()]
    return pd.DataFrame(rows, index=texts.index, columns=TEXT_FEATURES)


# ---------------------------------------------------------------------------
# Raw feature table (one row per post or draft)
# ---------------------------------------------------------------------------

# Config roles that may never be used as predictors.
FORBIDDEN_ROLES = [
    "id",
    "url",
    "author",
    "created_at",
    "snapshot_utc",
    "age_hours",
    "views",
    "likes",
    "reposts",
    "replies",
    "quotes",
    "bookmarks",
    "engagement_rate",
    "viral",
    "followers",
    "author_median_views",
    "found_via",
]
# Name hints for engagement / reach / post-publication columns. Substring hints are matched on the
# lower-cased name with separators removed ("quote_count" and "quoteCount" both become "quotecount");
# token hints only match a whole name token ("rt_count", "score_24h", "post_age"), so "image" or
# "percentage" do not trip "age". "is_quote" (a format flag) is exempt by name.
FORBIDDEN_NAME_HINTS = ["follower", "impression", "view", "like", "repost", "retweet", "reply", "replies",
                        "bookmark", "engagement", "viral", "median", "quotecount", "quotes", "click",
                        "expand", "share", "snapshot"]
FORBIDDEN_TOKEN_HINTS = ["rt", "score", "rank", "age"]
NAME_HINT_EXEMPT = {"is_quote", "isquote"}

STRUCT_BINARY = ["poll", "thread", "is_quote"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HOUR_BIN_HOURS = 4


def _name_tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name))
    return [t for t in re.split(r"[^a-z0-9]+", spaced.lower()) if t]


def suspicious_name(name: str) -> bool:
    """True if a column name looks like an engagement, reach, follower or post-publication column."""
    low = str(name).strip().lower()
    if low in NAME_HINT_EXEMPT:
        return False
    flat = re.sub(r"[^a-z0-9]+", "", low)
    if any(h in flat for h in FORBIDDEN_NAME_HINTS):
        return True
    return any(t in FORBIDDEN_TOKEN_HINTS for t in _name_tokens(name))


def check_no_forbidden(cfg: dict) -> None:
    """Raise if an extra feature column or a mapped feature_columns column is one of the label /
    author / follower columns, or its name looks like an engagement / reach column."""
    cols = cfg.get("columns", {})
    forbidden = {cols.get(r) for r in FORBIDDEN_ROLES if cols.get(r)}
    extras = list(cfg.get("extra_numeric_features", [])) + list(cfg.get("extra_categorical_features", []))
    mapped = [c for c in (cfg.get("feature_columns") or {}).values() if c]
    candidates = extras + mapped
    bad = [c for c in candidates if c in forbidden]
    if bad:
        raise ValueError(f"feature columns {bad} are label/author/follower columns; they cannot be predictors")
    hinted = [c for c in candidates if suspicious_name(c)]
    if hinted and not cfg.get("allow_suspicious_feature_names", False):
        raise ValueError(
            f"feature columns {hinted} look like engagement/reach/follower or post-publication columns; rename "
            "them or set allow_suspicious_feature_names=true if they really are content features known at "
            "posting time"
        )


def _as_binary(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.astype(int)
    lowered = s.astype("string").str.strip().str.lower()
    out = pd.Series(np.nan, index=s.index, dtype=float)
    out[lowered.isin(["1", "true", "t", "yes", "y", "1.0"])] = 1.0
    out[lowered.isin(["0", "false", "f", "no", "n", "0.0", "", "none", "nan"])] = 0.0
    num = pd.to_numeric(s, errors="coerce")
    out = out.fillna((num > 0).astype(float).where(num.notna()))
    return out.fillna(0.0).astype(int)


def _norm_cat(s: pd.Series, missing: str = "none") -> pd.Series:
    out = s.astype("string").str.strip().str.lower()
    out = out.fillna(missing).replace({"": missing, "nan": missing, "null": missing, "<na>": missing})
    return out.astype(object)


def hour_bin(h: float) -> str:
    if h is None or (isinstance(h, float) and math.isnan(h)):
        return "unknown"
    lo = int(h) // HOUR_BIN_HOURS * HOUR_BIN_HOURS
    return f"h{lo:02d}-{lo + HOUR_BIN_HOURS - 1:02d}"


def build_raw_features(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Raw (pre-encoding) features for every row of a prepared posts table.

    Expects the canonical columns produced by train.prepare(): text, created_at (UTC datetime) or
    hour_utc / weekday, media_type, poll, thread, is_quote, plus any configured extra feature columns.
    """
    out = pd.DataFrame(index=df.index)
    source = cfg.get("text_feature_source", "derive")
    tcol = cfg.get("feature_columns", {})
    have_text = "text" in df.columns and df["text"].notna().any()
    derived = text_feature_frame(df["text"]) if have_text else None
    for f in TEXT_FEATURES:
        mapped = tcol.get(f)
        use_col = mapped and mapped in df.columns and (source == "columns" or derived is None)
        if use_col:
            col = df[mapped]
            if f in TEXT_CATEGORICAL:
                out[f] = _norm_cat(col)
            elif f in TEXT_BINARY:
                out[f] = _as_binary(col)
            else:
                out[f] = pd.to_numeric(col, errors="coerce")
        elif derived is not None:
            out[f] = derived[f]
        # neither text nor a column: the feature is absent (dropped by FeatureSpec)

    out["media_type"] = _norm_cat(df["media_type"]) if "media_type" in df.columns else "none"
    for b in STRUCT_BINARY:
        out[b] = _as_binary(df[b]) if b in df.columns else 0

    if "created_at" in df.columns and df["created_at"].notna().any():
        ts = df["created_at"]
        hour = ts.dt.hour.astype(float)
        wd = ts.dt.weekday.astype(float)
    else:
        hour = pd.to_numeric(df.get("hour_utc", pd.Series(np.nan, index=df.index)), errors="coerce")
        wd = _weekday_num(df.get("weekday", pd.Series(np.nan, index=df.index)))
    out["hour_utc"] = hour
    out["weekday_num"] = wd
    out["hour_bin"] = [hour_bin(h) for h in hour.tolist()]
    out["weekday"] = [WEEKDAYS[int(w)] if pd.notna(w) else "unknown" for w in wd.tolist()]

    for c in cfg.get("extra_numeric_features", []):
        out[f"x_{c}"] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    for c in cfg.get("extra_categorical_features", []):
        out[f"xc_{c}"] = _norm_cat(df[c]) if c in df.columns else "none"
    return out


def _weekday_num(s: pd.Series) -> pd.Series:
    num = pd.to_numeric(s, errors="coerce")
    names = s.astype("string").str[:3].str.title()
    by_name = names.map({d: i for i, d in enumerate(WEEKDAYS)})
    return num.where(num.notna(), by_name).astype(float)


def feature_roles(raw: pd.DataFrame) -> dict:
    """Split raw columns into numeric / binary / categorical for linear and tree models."""
    numeric = [c for c in TEXT_NUMERIC if c in raw.columns] + [c for c in raw.columns if c.startswith("x_")]
    binary = [c for c in TEXT_BINARY + STRUCT_BINARY if c in raw.columns]
    cats = [c for c in TEXT_CATEGORICAL if c in raw.columns] + ["media_type"] + [
        c for c in raw.columns if c.startswith("xc_")
    ]
    return {
        "linear": {"numeric": numeric, "binary": binary, "categorical": cats + ["hour_bin", "weekday"]},
        "tree": {"numeric": numeric + ["hour_utc", "weekday_num"], "binary": binary, "categorical": cats},
    }


class FeatureSpec:
    """Learns encodings on training rows and applies them to any rows (posts or drafts).

    linear: numeric (median-imputed, plus a missing indicator where training had gaps), binary,
            one-hot categoricals with the most common level as the dropped reference.
    tree:   numeric with NaN kept (HistGradientBoosting handles it), binary, one-hot categoricals
            with every level.
    Levels seen fewer than min_level_count times collapse into "other"; unseen levels at
    transform time map to "other" when that level exists, else to the reference level.
    """

    def __init__(self, kind: str, min_level_count: int = 30):
        assert kind in ("linear", "tree")
        self.kind = kind
        self.min_level_count = min_level_count

    def fit(self, raw: pd.DataFrame) -> "FeatureSpec":
        roles = feature_roles(raw)[self.kind]
        self.numeric = list(roles["numeric"])
        self.binary = list(roles["binary"])
        self.categorical = list(roles["categorical"])
        self.levels, self.reference, self.seen = {}, {}, {}
        for c in self.categorical:
            vc = raw[c].astype(object).value_counts()
            self.seen[c] = {str(lvl): int(n) for lvl, n in vc.items()}
            keep = [lvl for lvl, n in vc.items() if n >= self.min_level_count]
            if len(keep) < len(vc):
                keep.append("other")
            if not keep:
                keep = ["other"]
            self.levels[c] = keep
            self.reference[c] = keep[0]  # most common kept level
        self.medians = {c: float(raw[c].median()) if raw[c].notna().any() else 0.0 for c in self.numeric}
        self.missing_ind = [c for c in self.numeric if raw[c].isna().any()] if self.kind == "linear" else []
        X, names, sources = self._encode(raw)
        sd = np.nanstd(X, axis=0)
        self.keep = [i for i, s in enumerate(sd) if s > 0]
        self.names = [names[i] for i in self.keep]
        self.sources = [sources[i] for i in self.keep]
        return self

    def _map_levels(self, s: pd.Series, c: str) -> pd.Series:
        levels = set(self.levels[c])
        fallback = "other" if "other" in levels else self.reference[c]
        return s.astype(object).where(s.astype(object).isin(levels), fallback)

    def level_warnings(self, raw: pd.DataFrame, columns=None) -> list[dict]:
        """Categorical values that are not a trained level, so they are scored as another level:
        never seen in training, or seen fewer than min_level_count times (collapsed to "other")."""
        out = []
        for c in self.categorical:
            if (columns is not None and c not in columns) or c not in raw.columns:
                continue
            levels = set(self.levels[c])
            fallback = "other" if "other" in levels else self.reference[c]
            valid = [lvl for lvl in self.levels[c] if lvl != "other"]
            for row, v in raw[c].astype(object).items():
                if v in levels:
                    continue
                n_seen = getattr(self, "seen", {}).get(c, {}).get(str(v), 0)
                out.append({"row": row, "column": c, "value": v, "scored_as": fallback,
                            "seen_in_training": n_seen, "valid_levels": valid})
        return out

    def _encode(self, raw: pd.DataFrame):
        cols, names, sources = [], [], []
        for c in self.numeric:
            v = pd.to_numeric(raw[c], errors="coerce").astype(float) if c in raw.columns else pd.Series(
                np.nan, index=raw.index)
            if self.kind == "linear":
                cols.append(v.fillna(self.medians[c]).to_numpy())
            else:
                cols.append(v.to_numpy())
            names.append(c)
            sources.append(c)
        for c in self.missing_ind:
            v = raw[c] if c in raw.columns else pd.Series(np.nan, index=raw.index)
            cols.append(v.isna().astype(float).to_numpy())
            names.append(f"{c}__missing")
            sources.append(c)
        for c in self.binary:
            v = raw[c] if c in raw.columns else pd.Series(0, index=raw.index)
            cols.append(pd.to_numeric(v, errors="coerce").fillna(0).astype(float).to_numpy())
            names.append(c)
            sources.append(c)
        for c in self.categorical:
            v = raw[c] if c in raw.columns else pd.Series(self.reference[c], index=raw.index)
            mapped = self._map_levels(v, c)
            for lvl in self.levels[c]:
                if self.kind == "linear" and lvl == self.reference[c]:
                    continue
                cols.append((mapped == lvl).astype(float).to_numpy())
                names.append(f"{c}={lvl}")
                sources.append(c)
        X = np.column_stack(cols) if cols else np.zeros((len(raw), 0))
        return X, names, sources

    def transform(self, raw: pd.DataFrame) -> np.ndarray:
        X, _, _ = self._encode(raw)
        return X[:, self.keep]

    def describe(self) -> dict:
        return {
            "kind": self.kind,
            "columns": self.names,
            "references": dict(self.reference) if self.kind == "linear" else {},
            "imputed_medians": {k: v for k, v in self.medians.items() if k in self.missing_ind},
        }
