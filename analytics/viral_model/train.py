"""Train and validate the within-author virality model.

    python train.py --config config.json [--data posts.csv] [--out out] [--quick]

Reads a posts table (csv / parquet / jsonl / json), keeps one snapshot per post at a fixed age
(default 24 h +/- 3 h), builds the target

    y = log(views + 1) - log(author_median_views + 1)

where the author median comes from that author's OTHER posts (leave-one-out) or a supplied column,
fits ridge, elastic net, HistGradientBoosting and an optional TF-IDF text model on content / format /
timing features only, validates them with GroupKFold by author and a time split, and writes
report.json, report.md, predictions_oof.csv and model.pkl into the output folder.

Dependencies: Python 3, pandas, numpy, scikit-learn. No network access.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import os
import pickle
import sys
import warnings as pywarnings

import numpy as np
import pandas as pd
import sklearn
from scipy import sparse  # noqa: F401  (scikit-learn dependency; used for the text model stack)
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import ElasticNet, ElasticNetCV, Ridge, RidgeCV
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F  # noqa: E402

KIT_VERSION = "1.1.0"

ROLES = [
    "id", "url", "author", "text", "created_at", "snapshot_utc", "age_hours",
    "views", "likes", "reposts", "replies", "quotes", "bookmarks", "engagement_rate", "viral",
    "followers", "author_median_views", "found_via",
    "media_type", "poll", "thread", "is_quote", "hour_utc", "weekday",
]
ENGAGEMENT_ROLES = ["likes", "reposts", "replies", "quotes", "bookmarks"]

DEFAULTS = {
    "data_path": None,
    "output_dir": "out",
    "seed": 0,
    "columns": {r: None for r in ROLES},
    "feature_columns": {},
    "text_feature_source": "derive",
    "extra_numeric_features": [],
    "extra_categorical_features": [],
    "allow_suspicious_feature_names": False,
    "target": {
        "age_filter": True,
        "age_hours": 24.0,
        "age_tolerance_hours": 3.0,
        "min_posts_per_author": 5,
        "author_median_source": "leave_one_out",
        "binary": True,
        "binary_top_fraction": 0.2,
        "secondary_er": True,
        "age_adjust": "none",
        "age_adjust_controls": "features",
        "age_spline_df": 3,
    },
    "validation": {
        "group_folds": 5,
        "time_test_weeks": 4,
        "pair_margin": 0.25,
        "max_pairs_per_author": 1_000_000,
        "small_author_followers": [1000, 100],
        "min_pairs_for_rate": 200,
        "min_authors_for_rate": 10,
        "metric_bootstrap": 1000,
        "shuffle_control": True,
        "shuffle_control_repeats": 5,
        "permutation_repeats": 3,
    },
    "models": {
        "ridge": True,
        "elastic_net": True,
        "hgb": True,
        "text": True,
        "primary_model": "auto",
        "within_author_demean": True,
        "min_level_count": 30,
        "ridge_alphas": [0.1, 0.3, 1, 3, 10, 30, 100, 300, 1000, 3000, 10000],
        "enet_l1_ratios": [0.1, 0.5, 0.9, 1.0],
        "enet_alphas": [0.0001, 0.0003, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3],
        "hgb_params": {
            "max_iter": 250,
            "learning_rate": 0.05,
            "max_leaf_nodes": 15,
            "min_samples_leaf": 40,
            "l2_regularization": 1.0,
        },
        "tfidf": {"ngram_range": [1, 2], "min_df": 5, "max_features": 50000, "sublinear_tf": True},
        "text_alphas": [1, 3, 10, 30, 100],
        "bootstrap": 200,
        "bootstrap_enet": 100,
        "effects_alpha": 1e-6,
        "drop_top_authors": 0,
        "drop_top_effects": [],
    },
}


# ---------------------------------------------------------------------------
# Config and data loading
# ---------------------------------------------------------------------------

def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k.startswith("_"):
            continue  # "_comment" keys
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None, overrides: dict | None = None) -> dict:
    user = {}
    if path:
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
    cfg = _merge(DEFAULTS, user)
    cfg = _merge(cfg, overrides or {})
    unknown = [k for k in (cfg["columns"] or {}) if k not in ROLES]
    if unknown:
        raise ValueError(f"unknown column roles in config.columns: {unknown}; valid roles: {ROLES}")
    cfg["_config_dir"] = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
    F.check_no_forbidden(cfg)
    return cfg


def resolve_path(p: str, cfg: dict) -> str:
    if os.path.isabs(p) or os.path.exists(p):
        return p
    return os.path.join(cfg.get("_config_dir", os.getcwd()), p)


def load_table(path: str) -> pd.DataFrame:
    low = path.lower()
    if low.endswith(".parquet") or low.endswith(".pq"):
        return pd.read_parquet(path)
    if low.endswith(".jsonl") or low.endswith(".ndjson"):
        return pd.read_json(path, lines=True)
    if low.endswith(".json"):
        return pd.read_json(path)
    if low.endswith(".pkl") or low.endswith(".pickle"):
        return pd.read_pickle(path)
    if low.endswith(".tsv"):
        return pd.read_csv(path, sep="\t", low_memory=False)
    return pd.read_csv(path, low_memory=False)


def parse_ts(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, utc=True)
    if pd.api.types.is_numeric_dtype(s):
        med = s.dropna().abs().median() if s.notna().any() else 0
        unit = "ms" if med > 1e11 else "s"
        return pd.to_datetime(s, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(s, utc=True, errors="coerce", format="mixed")


# ---------------------------------------------------------------------------
# Preparation: fixed age, one snapshot per post, author filter, targets
# ---------------------------------------------------------------------------

def loo_median(values: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Median of each row's group with that row left out (NaN for groups of size 1)."""
    values = np.asarray(values, dtype=float)
    out = np.full(len(values), np.nan)
    for _, idx in pd.Series(np.arange(len(values))).groupby(np.asarray(groups)).indices.items():
        n = len(idx)
        if n < 2:
            continue
        v = values[idx]
        order = np.argsort(v, kind="mergesort")
        s = v[order]
        rank = np.empty(n, dtype=int)
        rank[order] = np.arange(n)
        m = n - 1
        k1, k2 = (m - 1) // 2, m // 2

        def pick(k):
            return np.where(k < rank, s[k], s[np.minimum(k + 1, n - 1)])

        out[idx] = (pick(k1) + pick(k2)) / 2.0
    return out


AGE_ADJUST_MODES = ("none", "loglinear", "spline")


class AgeBasis:
    """log(age_hours) (loglinear) or a natural cubic spline of log(age_hours) with df columns
    (spline: df + 1 knots, boundaries at the data range, interior knots at equal quantiles;
    linear beyond the boundaries). No intercept: author fixed effects absorb the level."""

    def __init__(self, kind: str, df: int = 3):
        self.kind, self.df = kind, int(df)

    def fit(self, age_hours) -> "AgeBasis":
        x = np.log(np.asarray(age_hours, dtype=float))
        if self.kind == "spline":
            if self.df < 1:
                raise ValueError("target.age_spline_df must be >= 1")
            self.knots = np.quantile(x, np.linspace(0, 1, self.df + 1))
            if len(np.unique(self.knots)) < len(self.knots):
                raise ValueError(f"age spline: {self.df + 1} knots on log(age_hours) are not distinct "
                                 "(too few distinct ages); use age_adjust='loglinear' or a smaller age_spline_df")
        return self

    def transform(self, age_hours) -> np.ndarray:
        x = np.log(np.asarray(age_hours, dtype=float))
        if self.kind == "loglinear":
            return x[:, None]
        k = self.knots
        K = len(k)

        def d(j):
            return (np.clip(x - k[j], 0, None) ** 3 - np.clip(x - k[K - 1], 0, None) ** 3) / (k[K - 1] - k[j])

        return np.column_stack([x] + [d(j) - d(K - 2) for j in range(K - 2)])

    def describe(self) -> dict:
        out = {"kind": self.kind, "variable": "log(age_hours)"}
        if self.kind == "spline":
            out.update({"df": self.df, "knots_age_hours": [float(math.exp(v)) for v in self.knots]})
        return out



def fit_age_adjustment(d: pd.DataFrame, cfg: dict, rng) -> tuple[np.ndarray, dict, object]:
    """Model log(views+1) on f(log age_hours) with author fixed effects, pooled across posts, and
    return (adjustment, info, refit) where adjustment = f(age) - f(target age) per post: subtracting it
    from log(views+1) moves every post to the fixed target age, and refit(rows) is the same adjustment
    with f refitted on those rows only (row indices into d; used by the effects bootstrap so its CIs
    carry the age-fit uncertainty). With age_adjust_controls='features' (default) the content features
    enter the same within-author regression as controls, so a feature mix that drifts with age does not
    leak into f; the features' own coefficients are not used here (the effects table re-estimates them
    on the adjusted target, which by Frisch-Waugh-Lovell approximately equals the joint estimate: the
    target also subtracts the author's leave-one-out median). f is fitted once on all posts, before
    GroupKFold. Age is never a model feature and is not used at scoring."""
    t = cfg["target"]
    kind, controls = t["age_adjust"], t.get("age_adjust_controls", "features")
    if controls not in ("features", "none"):
        raise ValueError("target.age_adjust_controls must be 'features' or 'none'")
    groups = d["author"].to_numpy()
    age = d["age_hours"].to_numpy(dtype=float)
    lv = np.log1p(d["views"].to_numpy(dtype=float))
    basis = AgeBasis(kind, t.get("age_spline_df", 3)).fit(age)
    G = basis.transform(age)
    p = G.shape[1]
    Z = G
    n_controls = 0
    if controls == "features":
        raw = F.build_raw_features(d, cfg)
        X = F.FeatureSpec("linear", cfg["models"]["min_level_count"]).fit(raw).transform(raw)
        Z = np.column_stack([G, X])
        n_controls = X.shape[1]
    # Author fixed effects: demean once; an author drawn twice in the bootstrap keeps the same rows.
    Zd = author_demean(Z, groups)
    lvd = author_demean(lv[:, None], groups)[:, 0]
    if np.allclose(Zd[:, :p], 0):
        raise ValueError("age_adjust: snapshot age does not vary within any author; nothing to fit")
    gamma = np.linalg.lstsq(Zd, lvd, rcond=None)[0][:p]
    ref_age = float(t["age_hours"])
    g_ref = basis.transform(np.array([ref_age]))[0]
    Gc = G - g_ref
    adjustment = Gc @ gamma

    def refit(rows):
        return Gc @ np.linalg.lstsq(Zd[rows], lvd[rows], rcond=None)[0][:p]

    # Curve on an age grid (data quantiles + the target age) and the average slope d f / d log(age).
    grid = sorted({round(float(v), 1) for v in np.quantile(age, [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])} | {ref_age})
    Ggrid = basis.transform(np.array(grid)) - g_ref
    h = 1e-3
    Dslope = (basis.transform(age * math.exp(h)) - basis.transform(age * math.exp(-h))) / (2 * h)

    def summaries(gm):
        return float(np.mean(Dslope @ gm)), Ggrid @ gm

    slope, curve = summaries(gamma)
    B = int(cfg["models"].get("bootstrap") or 0)
    slope_ci, curve_ci = None, None
    if B:
        uniq = np.unique(groups)
        pos = pd.Series(np.arange(len(lv))).groupby(groups).indices
        bs, bc = np.zeros(B), np.zeros((B, len(grid)))
        for b in range(B):
            rows = np.concatenate([pos[g] for g in rng.choice(uniq, len(uniq), replace=True)])
            gb = np.linalg.lstsq(Zd[rows], lvd[rows], rcond=None)[0][:p]
            bs[b], bc[b] = summaries(gb)
        slope_ci = [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))]
        curve_ci = np.quantile(bc, [0.025, 0.975], axis=0).T
    a_var = d.assign(_a=age).groupby("author")["_a"].nunique()
    info = {
        "method": kind,
        "controls": controls,
        "n_control_columns": int(n_controls),
        "basis": basis.describe(),
        "fit_scope": ("all posts, once, before GroupKFold (not refitted per fold; on synthetic data refitting "
                      "per fold moved pairwise accuracy by at most 0.0003)"),
        "effects_ci_include_age_fit": True,
        "reference_age_hours": ref_age,
        "outcome": "log(views+1) - [f(age) - f(reference age)], then the within-author target as usual",
        "slope_per_log_age": slope,
        "slope_ci95": slope_ci,
        "slope_note": ("coefficient on log(age_hours): views+1 scale as age ** slope" if kind == "loglinear" else
                       "average over posts of d f / d log(age_hours) of the spline"),
        "bootstrap": B,
        "n_posts": int(len(d)),
        "n_authors": int(len(np.unique(groups))),
        "n_authors_with_age_variation": int((a_var > 1).sum()),
        "age_hours": {"min": float(age.min()), "median": float(np.median(age)), "max": float(age.max())},
        "curve": [{"age_hours": a, "log_adjustment": float(c),
                   "ci95": [float(curve_ci[i, 0]), float(curve_ci[i, 1])] if curve_ci is not None else None,
                   "x_views_vs_reference": float(math.exp(c))} for i, (a, c) in enumerate(zip(grid, curve))],
        "adjustment_summary": {"p10": float(np.quantile(adjustment, 0.1)), "median": float(np.median(adjustment)),
                               "p90": float(np.quantile(adjustment, 0.9))},
    }
    return adjustment, info, refit


def adjusted_target(lv: np.ndarray, adjustment: np.ndarray, groups) -> np.ndarray:
    """y = log(views_adj+1) - log(leave-one-out author median views_adj+1), views_adj+1 = (views+1) moved
    to the target age by the adjustment."""
    views_t = np.expm1(lv - adjustment)
    return np.log1p(views_t) - np.log1p(loo_median(views_t, groups))


def _stage(df: pd.DataFrame, name: str, post_key: str | None = None) -> dict:
    posts = int(df[post_key].nunique()) if post_key and post_key in df.columns else len(df)
    return {"stage": name, "rows": int(len(df)), "posts": posts, "authors": int(df["author"].nunique())}


def prepare(raw_df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    """Canonical, filtered posts table with targets. Returns (df, info) where info carries the
    drop funnel, composition and warnings."""
    cols = cfg["columns"]
    warn = []
    d = pd.DataFrame(index=raw_df.index)
    for role in ROLES:
        c = cols.get(role)
        if not c:
            continue
        if c in raw_df.columns:
            d[role] = raw_df[c]
        else:
            warn.append(f"config maps role '{role}' to column '{c}', which is not in the data")
    carry = list(cfg.get("extra_numeric_features", [])) + list(cfg.get("extra_categorical_features", []))
    carry += [c for c in cfg.get("feature_columns", {}).values() if c]
    for c in carry:
        if c in raw_df.columns and c not in d.columns:
            d[c] = raw_df[c]
        elif c not in raw_df.columns:
            warn.append(f"feature column '{c}' is not in the data")
    for req in ("author", "views"):
        if req not in d.columns:
            raise ValueError(f"required role '{req}' is not mapped to a column present in the data")
    if "text" not in d.columns:
        warn.append("no text column: text features come only from mapped feature_columns; no text model")
    if "thread" in d.columns:
        warn.append(f"'thread' is mapped (column '{cols.get('thread')}') and used as a predictor: it must be known "
                    "when the post was published (posted as a thread), not read from the conversation at scrape "
                    "time, where self-replies added after a post took off make it post-publication information")

    d["author"] = d["author"].astype("string").str.strip().str.lower()
    d = d[d["author"].notna() & (d["author"] != "")]
    for tcol in ("created_at", "snapshot_utc"):
        if tcol in d.columns:
            d[tcol] = parse_ts(d[tcol])
    post_key = "id" if "id" in d.columns else ("url" if "url" in d.columns else None)
    if post_key is None:
        d["_row"] = np.arange(len(d))
        post_key = "_row"
        warn.append("no id/url column: every row is treated as a distinct post")
    d["_post"] = d[post_key].astype("string")

    funnel = [_stage(d, "loaded", "_post")]
    found_via_loaded = None
    if "found_via" in d.columns:
        d["found_via"] = F._norm_cat(d["found_via"], missing="unknown")
        found_via_loaded = d.drop_duplicates("_post").groupby("found_via").agg(
            posts=("_post", "nunique"), authors=("author", "nunique"))

    d["views"] = pd.to_numeric(d["views"], errors="coerce")
    d = d[d["views"].notna() & (d["views"] >= 0)]
    funnel.append(_stage(d, "has_views", "_post"))

    tcfg = cfg["target"]
    target_age = float(tcfg["age_hours"])
    age_adjust = tcfg.get("age_adjust", "none")
    if age_adjust not in AGE_ADJUST_MODES:
        raise ValueError(f"target.age_adjust must be one of {AGE_ADJUST_MODES}")
    if "age_hours" in d.columns:
        d["age_hours"] = pd.to_numeric(d["age_hours"], errors="coerce")
    elif "created_at" in d.columns and "snapshot_utc" in d.columns:
        d["age_hours"] = (d["snapshot_utc"] - d["created_at"]).dt.total_seconds() / 3600.0
    elif tcfg["age_filter"] or age_adjust != "none":
        raise ValueError("cannot determine post age: map age_hours, or created_at + snapshot_utc, "
                         "or set target.age_filter=false if every row is already at the fixed age"
                         + (" (target.age_adjust needs the age)" if age_adjust != "none" else ""))
    if age_adjust != "none":
        if tcfg["author_median_source"] != "leave_one_out":
            raise ValueError("target.age_adjust needs author_median_source='leave_one_out': a supplied "
                             "author median is not on the age-adjusted scale")
        d = d[np.isfinite(d["age_hours"]) & (d["age_hours"] > 0)]
        funnel.append(_stage(d, "age_known_and_positive", "_post"))
    if tcfg["age_filter"]:
        tol = float(tcfg["age_tolerance_hours"])
        d = d[(d["age_hours"] - target_age).abs() <= tol]
        funnel.append(_stage(d, f"age_{target_age:g}h_pm_{tol:g}h", "_post"))
        d = d.assign(_agegap=(d["age_hours"] - target_age).abs()).sort_values(["_post", "_agegap"])
    else:
        warn.append("target.age_filter=false: rows are assumed to be at a fixed age already")
        d = d.assign(_agegap=0.0)
    d = d.drop_duplicates("_post", keep="first").drop(columns="_agegap")
    funnel.append(_stage(d, "one_snapshot_per_post", "_post"))

    minp = int(tcfg["min_posts_per_author"])
    counts = d.groupby("author")["_post"].transform("count")
    d = d[counts >= minp].copy()
    funnel.append(_stage(d, f"authors_with_>={minp}_posts", "_post"))
    if len(d) == 0:
        raise ValueError("no posts left after the age window and author filter; check the column map")

    if "created_at" in d.columns:
        d = d.sort_values(["created_at", "_post"])
    d = d.reset_index(drop=True)
    groups = d["author"].to_numpy()

    views_t = d["views"].to_numpy(dtype=float)
    views_all = views_t
    age_info = None
    if age_adjust != "none":
        adjustment, age_info, age_refit = fit_age_adjustment(d, cfg, np.random.default_rng(int(cfg["seed"]) + 31337))
        views_t = np.expm1(np.log1p(views_t) - adjustment)  # views+1 moved to the target age
        d["views_age_adjusted"] = views_t
    elif tcfg["age_filter"] and float(tcfg["age_tolerance_hours"]) > 6:
        warn.append(f"wide age window (+/- {float(tcfg['age_tolerance_hours']):g} h) without target.age_adjust: "
                    "views grow with age inside the window, so a feature whose posts were seen older looks better; "
                    "set target.age_adjust to 'loglinear' or 'spline' (README: wide age window)")

    src = tcfg["author_median_source"]
    if src == "column":
        if "author_median_views" not in d.columns:
            raise ValueError("author_median_source='column' but no author_median_views column is mapped")
        med = pd.to_numeric(d["author_median_views"], errors="coerce").to_numpy()
        warn.append("author median taken from the supplied column; it must exclude the post itself")
    elif src == "leave_one_out":
        med = loo_median(views_t, groups)
    else:
        raise ValueError("target.author_median_source must be 'leave_one_out' or 'column'")
    d["author_median_views_used"] = med
    d["y"] = np.log1p(views_t) - np.log1p(med)
    ok = np.isfinite(d["y"]).to_numpy()
    d = d[ok].reset_index(drop=True)
    y_redraw = None
    if age_adjust != "none":
        lv_all, kept = np.log1p(views_all), np.flatnonzero(ok)

        def y_redraw(rows):
            """The target with the age curve refitted on these rows (indices into the returned df)."""
            return adjusted_target(lv_all, age_refit(kept[np.asarray(rows)]), groups)[kept]

    # Secondary: within-author engagement rate.
    d["er"] = np.nan
    if "engagement_rate" in d.columns:
        d["er"] = pd.to_numeric(d["engagement_rate"], errors="coerce")
        er_source = f"column '{cols.get('engagement_rate')}'"
    else:
        present = [r for r in ENGAGEMENT_ROLES if r in d.columns]
        if present:
            eng = sum(pd.to_numeric(d[r], errors="coerce").fillna(0) for r in present)
            d["er"] = eng / d["views"].clip(lower=1)
            er_source = "(" + " + ".join(present) + ") / views"
        else:
            er_source = None
    if er_source and d["er"].notna().sum() > 0:
        pos = d["er"][d["er"] > 0]
        eps = float(pos.median()) * 0.01 if len(pos) else 1e-4
        okr = d["er"].notna().to_numpy()
        er_med = np.full(len(d), np.nan)
        er_med[okr] = loo_median(d["er"].to_numpy(float)[okr], d["author"].to_numpy()[okr])
        d["y_er"] = np.log(d["er"] + eps) - np.log(er_med + eps)
    else:
        d["y_er"] = np.nan

    if "followers" in d.columns:
        d["followers"] = pd.to_numeric(d["followers"], errors="coerce")
        d["author_followers"] = d.groupby("author")["followers"].transform("median")

    info = {
        "funnel": funnel,
        "warnings": warn,
        "post_key": post_key,
        "er_source": er_source,
        "composition": composition(d, found_via_loaded),
        "age_adjustment": age_info,
        "y_redraw": y_redraw,
    }
    return d, info


def composition(d: pd.DataFrame, found_via_loaded) -> dict:
    ppa = d.groupby("author").size()
    out = {
        "posts": int(len(d)),
        "authors": int(d["author"].nunique()),
        "posts_per_author": {
            "min": int(ppa.min()), "median": float(ppa.median()),
            "p90": float(ppa.quantile(0.9)), "max": int(ppa.max()),
            "top10_authors_share_of_posts": float(ppa.sort_values(ascending=False).head(10).sum() / len(d)),
        },
    }
    if "created_at" in d.columns and d["created_at"].notna().any():
        out["created_at_range"] = [str(d["created_at"].min()), str(d["created_at"].max())]
    if "age_hours" in d.columns and d["age_hours"].notna().any():
        out["snapshot_age_hours"] = {
            "min": float(d["age_hours"].min()), "median": float(d["age_hours"].median()),
            "max": float(d["age_hours"].max())}
    if "media_type" in d.columns:
        out["media_type_posts"] = {str(k): int(v) for k, v in F._norm_cat(d["media_type"]).value_counts().items()}
    if "found_via" in d.columns:
        fin = d.groupby("found_via").agg(posts=("_post", "nunique"), authors=("author", "nunique"))
        rows = {}
        for k in sorted(set(fin.index) | set(found_via_loaded.index if found_via_loaded is not None else [])):
            rows[str(k)] = {
                "posts_loaded": int(found_via_loaded.loc[k, "posts"]) if found_via_loaded is not None
                and k in found_via_loaded.index else 0,
                "authors_loaded": int(found_via_loaded.loc[k, "authors"]) if found_via_loaded is not None
                and k in found_via_loaded.index else 0,
                "posts_final": int(fin.loc[k, "posts"]) if k in fin.index else 0,
                "authors_final": int(fin.loc[k, "authors"]) if k in fin.index else 0,
            }
        out["by_found_via"] = rows
    if "author_followers" in d.columns:
        af = d.groupby("author")["author_followers"].first()
        bins = [(-np.inf, 100, "<100"), (100, 1000, "100-1k"), (1000, 10000, "1k-10k"),
                (10000, 100000, "10k-100k"), (100000, np.inf, ">=100k")]
        out["authors_by_followers"] = {lab: int(((af >= lo) & (af < hi)).sum()) for lo, hi, lab in bins}
        out["authors_by_followers"]["unknown"] = int(af.isna().sum())
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _rank(a) -> np.ndarray:
    return pd.Series(np.asarray(a, dtype=float)).rank().to_numpy()


def spearman(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    ra, rb = _rank(a[ok]), _rank(b[ok])
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def pairwise_by_author(y, pred, groups, margin, max_pairs, rng) -> pd.DataFrame:
    """Per author: number of same-author pairs with |dy| > margin and how many the model orders
    correctly (prediction ties count 0.5)."""
    y, pred = np.asarray(y, dtype=float), np.asarray(pred, dtype=float)
    rows = []
    for g, idx in pd.Series(np.arange(len(y))).groupby(np.asarray(groups)).indices.items():
        n = len(idx)
        if n < 2:
            continue
        total = n * (n - 1) // 2
        if total <= max_pairs:
            i, j = np.triu_indices(n, 1)
        else:
            i = rng.integers(0, n, max_pairs)
            j = rng.integers(0, n, max_pairs)
            keep = i != j
            i, j = i[keep], j[keep]
        yy, pp = y[idx], pred[idx]
        dy = yy[i] - yy[j]
        sel = np.abs(dy) > margin
        if not sel.any():
            rows.append((g, 0, 0.0))
            continue
        s = np.sign(dy[sel]) * np.sign(pp[i][sel] - pp[j][sel])
        rows.append((g, int(sel.sum()), float((s > 0).sum() + 0.5 * (s == 0).sum())))
    return pd.DataFrame(rows, columns=["author", "pairs", "correct"])


def evaluate(y, pred, groups, cfg, rng, followers=None) -> dict:
    v = cfg["validation"]
    y, pred, groups = np.asarray(y, float), np.asarray(pred, float), np.asarray(groups)
    pw = pairwise_by_author(y, pred, groups, v["pair_margin"], v["max_pairs_per_author"], rng)
    pw = pw[pw["pairs"] > 0]
    n_pairs = int(pw["pairs"].sum())
    out = {
        "n_posts": int(len(y)),
        "n_authors": int(len(np.unique(groups))),
        "n_pairs": n_pairs,
        "n_authors_with_pairs": int(len(pw)),
    }
    if n_pairs:
        acc = float(pw["correct"].sum() / n_pairs)
        out["pairwise_accuracy"] = acc
        # author-cluster bootstrap of the pair-weighted accuracy
        B = int(v["metric_bootstrap"])
        if B and len(pw) > 1:
            P, C = pw["pairs"].to_numpy(float), pw["correct"].to_numpy(float)
            draws = rng.integers(0, len(pw), size=(B, len(pw)))
            boot = C[draws].sum(1) / np.maximum(P[draws].sum(1), 1)
            out["pairwise_accuracy_ci95"] = [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))]
        macro = pw[pw["pairs"] >= 10]
        if len(macro):
            out["pairwise_accuracy_author_macro"] = float((macro["correct"] / macro["pairs"]).mean())
            out["n_authors_macro"] = int(len(macro))
    out["spearman"] = spearman(y, pred)
    per = []
    for _, idx in pd.Series(np.arange(len(y))).groupby(groups).indices.items():
        if len(idx) >= 5:
            r = spearman(y[idx], pred[idx])
            if math.isfinite(r):
                per.append(r)
    out["spearman_within_author_mean"] = float(np.mean(per)) if per else float("nan")
    out["n_authors_spearman"] = len(per)
    if len(y) >= 20:
        top = pred >= np.quantile(pred, 0.9)
        hit = y >= np.quantile(y, 0.8)
        base = float(hit.mean())
        out["top_decile_n"] = int(top.sum())
        out["top_decile_hit_rate"] = float(hit[top].mean())
        out["base_hit_rate"] = base
        out["lift_top_decile"] = float(hit[top].mean() / base) if base > 0 else float("nan")
        out["top_decile_median_x_views"] = float(math.exp(np.median(y[top])))
        out["all_median_x_views"] = float(math.exp(np.median(y)))
    out["low_n"] = bool(n_pairs < v["min_pairs_for_rate"] or len(pw) < v["min_authors_for_rate"])
    return out


def evaluate_binary(label, p, groups, cfg, rng) -> dict:
    label, p = np.asarray(label, int), np.asarray(p, float)
    out = {"n_posts": int(len(label)), "n_positive": int(label.sum()), "base_rate": float(label.mean())}
    if 0 < label.sum() < len(label):
        out["auc"] = float(roc_auc_score(label, p))
    out["brier"] = float(brier_score_loss(label, p))
    out["brier_base_rate_only"] = float(brier_score_loss(label, np.full(len(label), label.mean())))
    bins = pd.qcut(pd.Series(p).rank(method="first"), q=min(5, len(p)), labels=False)
    rel = []
    for b in sorted(pd.unique(bins)):
        m = (bins == b).to_numpy()
        rel.append({"bin": int(b), "n": int(m.sum()), "mean_predicted": float(p[m].mean()),
                    "observed_rate": float(label[m].mean())})
    out["reliability"] = rel
    return out


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def inner_splits(groups, k, seed):
    uniq = np.unique(groups)
    k = max(2, min(k, len(uniq)))
    return list(GroupKFold(n_splits=k, shuffle=True, random_state=seed).split(
        np.zeros(len(groups)), groups=groups))


def author_demean(A: np.ndarray, groups) -> np.ndarray:
    """Subtract each author's mean (column-wise) from their rows."""
    A = np.asarray(A, dtype=float)
    out = A.copy()
    for _, idx in pd.Series(np.arange(len(A))).groupby(np.asarray(groups)).indices.items():
        out[idx] = A[idx] - A[idx].mean(axis=0)
    return out


class LinearModel:
    """Ridge or elastic net on standardized linear features.

    With models.within_author_demean (default) the coefficients are estimated on author-demeaned
    features and target (a fixed-effects regression): only variation between posts of the same
    author identifies an effect, so author style (big accounts using BREAKING more, say) cannot
    leak into a coefficient. Predictions use the raw features with those coefficients; the
    difference between two drafts of one author is coef . (x1 - x2) either way.
    """

    def __init__(self, cfg, kind="ridge"):
        self.cfg, self.kind = cfg, kind
        self.name = {"ridge": "ridge", "enet": "elastic_net", "effects": "effects_ls"}[kind]

    def design(self, raw):
        return self.scaler.transform(self.spec.transform(raw))

    def fit(self, raw, y, groups):
        m = self.cfg["models"]
        self.spec = F.FeatureSpec("linear", m["min_level_count"]).fit(raw)
        X = self.spec.transform(raw)
        self.scaler = StandardScaler().fit(X)
        Xs = self.scaler.transform(X)
        self.demean = bool(m.get("within_author_demean", True))
        Xs, y_fit = self._fit_space(Xs, y, groups)
        cv = inner_splits(groups, 3, self.cfg["seed"])
        if self.kind == "effects":  # the effects-table regression: fixed near-zero penalty, no CV
            self.alpha, self.l1_ratio = float(m.get("effects_alpha", 1e-6)), 0.0
        elif self.kind == "ridge":
            self.alpha = float(RidgeCV(alphas=m["ridge_alphas"], cv=cv).fit(Xs, y_fit).alpha_)
            self.l1_ratio = 0.0
        else:
            with pywarnings.catch_warnings():
                pywarnings.simplefilter("ignore")
                cvm = ElasticNetCV(l1_ratio=m["enet_l1_ratios"], alphas=m["enet_alphas"], cv=cv,
                                   max_iter=5000).fit(Xs, y_fit)
            self.alpha, self.l1_ratio = float(cvm.alpha_), float(cvm.l1_ratio_)
        with pywarnings.catch_warnings():
            if self.kind == "effects":  # near-singular at alpha 1e-6 is expected (LinAlgWarning)
                pywarnings.simplefilter("ignore")
            self.model = self._estimator().fit(Xs, y_fit)
        if self.demean:
            self.model.intercept_ = float(np.mean(y))  # raw design is centered by the scaler
        return self

    def _fit_space(self, Xs, y, groups):
        y = np.asarray(y, dtype=float)
        if not getattr(self, "demean", False):
            return Xs, y
        return author_demean(Xs, groups), author_demean(y[:, None], groups)[:, 0]

    def _estimator(self):
        if self.kind in ("ridge", "effects"):
            return Ridge(alpha=self.alpha)
        return ElasticNet(alpha=self.alpha, l1_ratio=self.l1_ratio, max_iter=5000)

    def predict(self, raw):
        return self.model.predict(self.design(raw))

    def per_unit(self):
        return self.model.coef_ / self.scaler.scale_

    def contributions(self, raw) -> pd.DataFrame:
        """Per raw feature: contribution to the score relative to the average training post."""
        C = self.design(raw) * self.model.coef_
        df = pd.DataFrame(C, columns=self.spec.names)
        return df.T.groupby(self.spec.sources).sum().T

    def effect_estimates(self, raw, y, groups, alpha):
        """Per-unit effects from the within-author regression with a near-zero penalty (alpha), so the
        effects table is not shrunk by the predictive model's cross-validated alpha."""
        Xs, yy = self._fit_space(self.design(raw), y, groups)
        with pywarnings.catch_warnings():
            pywarnings.simplefilter("ignore")
            return Ridge(alpha=alpha).fit(Xs, yy).coef_ / self.scaler.scale_

    def bootstrap(self, raw, y, groups, B, rng, alpha=None, y_redraw=None):
        """Author-resampled bootstrap of the per-unit coefficients; alpha overrides the model's
        penalty (ridge only). y_redraw(rows), if given (age-adjusted runs), rebuilds the target with the
        age curve refitted on the drawn rows, so the draws carry the age-fit uncertainty."""
        Xs, y = self._fit_space(self.design(raw), y, groups)
        uniq = np.unique(groups)
        pos = pd.Series(np.arange(len(y))).groupby(np.asarray(groups)).indices
        draws = np.zeros((B, Xs.shape[1]))
        with pywarnings.catch_warnings():
            pywarnings.simplefilter("ignore")
            for b in range(B):
                pick = rng.choice(uniq, len(uniq), replace=True)
                rows = np.concatenate([pos[g] for g in pick])
                yb = y
                if y_redraw is not None:
                    yr = np.asarray(y_redraw(rows), dtype=float)
                    yb = author_demean(yr[:, None], groups)[:, 0] if self.demean else yr
                est = Ridge(alpha=alpha) if alpha is not None else self._estimator()
                draws[b] = est.fit(Xs[rows], yb[rows]).coef_ / self.scaler.scale_
        return draws


class HGBModel:
    name = "hgb"

    def __init__(self, cfg):
        self.cfg = cfg

    def fit(self, raw, y, groups):
        self.spec = F.FeatureSpec("tree", self.cfg["models"]["min_level_count"]).fit(raw)
        self.model = HistGradientBoostingRegressor(
            early_stopping=False, random_state=self.cfg["seed"], **self.cfg["models"]["hgb_params"]
        ).fit(self.spec.transform(raw), y)
        return self

    def predict(self, raw):
        return self.model.predict(self.spec.transform(raw))


class TextModel:
    """TF-IDF of the post text stacked with the standardized structured features, one ridge."""
    name = "text"

    def __init__(self, cfg):
        self.cfg = cfg

    def _X(self, raw):
        T = self.vec.transform(raw["__text"].fillna("").astype(str))
        S = sparse.csr_matrix(self.scaler.transform(self.spec.transform(raw)))
        return sparse.hstack([T, S]).tocsr()

    def fit(self, raw, y, groups):
        m = self.cfg["models"]
        t = dict(m["tfidf"])
        t["ngram_range"] = tuple(t.get("ngram_range", (1, 2)))
        min_df = t.pop("min_df", 5)
        self.vec = TfidfVectorizer(token_pattern=r"(?u)\$?[A-Za-z][A-Za-z0-9_']+|\d+%?",
                                   min_df=min(min_df, max(1, len(raw) // 50)), **t)
        self.vec.fit(raw["__text"].fillna("").astype(str))
        self.spec = F.FeatureSpec("linear", m["min_level_count"]).fit(raw)
        self.scaler = StandardScaler().fit(self.spec.transform(raw))
        X = self._X(raw)
        cv = inner_splits(groups, 3, self.cfg["seed"])
        self.alpha = float(RidgeCV(alphas=m["text_alphas"], cv=cv).fit(X, y).alpha_)
        self.model = Ridge(alpha=self.alpha).fit(X, y)
        return self

    def predict(self, raw):
        return self.model.predict(self._X(raw))

    def top_terms(self, k=20):
        vocab = np.array(self.vec.get_feature_names_out())
        coef = self.model.coef_[: len(vocab)]
        order = np.argsort(coef)
        return {
            "positive": [{"term": vocab[i], "coef": float(coef[i])} for i in order[::-1][:k]],
            "negative": [{"term": vocab[i], "coef": float(coef[i])} for i in order[:k]],
        }


class BinaryModel:
    """Top-fraction classifier (HistGradientBoosting) with isotonic calibration fitted on held-out
    training authors."""
    name = "binary_top"

    def __init__(self, cfg):
        self.cfg = cfg

    def fit(self, raw, y, groups):
        frac = float(self.cfg["target"]["binary_top_fraction"])
        self.threshold = float(np.quantile(y, 1 - frac))
        lab = (y >= self.threshold).astype(int)
        a, b = next(GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=self.cfg["seed"]).split(
            raw, lab, groups))
        self.spec = F.FeatureSpec("tree", self.cfg["models"]["min_level_count"]).fit(raw.iloc[a])
        self.clf = HistGradientBoostingClassifier(
            early_stopping=False, random_state=self.cfg["seed"], **self.cfg["models"]["hgb_params"]
        ).fit(self.spec.transform(raw.iloc[a]), lab[a])
        p_b = self.clf.predict_proba(self.spec.transform(raw.iloc[b]))[:, 1]
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(p_b, lab[b])
        return self

    def predict(self, raw):
        return self.iso.predict(self.clf.predict_proba(self.spec.transform(raw))[:, 1])


def make_model(name, cfg):
    if name == "ridge":
        return LinearModel(cfg, "ridge")
    if name == "elastic_net":
        return LinearModel(cfg, "enet")
    if name == "effects_ls":
        return LinearModel(cfg, "effects")
    if name == "hgb":
        return HGBModel(cfg)
    if name == "text":
        return TextModel(cfg)
    if name == "binary_top":
        return BinaryModel(cfg)
    raise ValueError(name)


# ---------------------------------------------------------------------------
# Validation runners
# ---------------------------------------------------------------------------

def group_kfold(raw, y, groups, names, cfg):
    k = min(int(cfg["validation"]["group_folds"]), len(np.unique(groups)))
    gkf = GroupKFold(n_splits=k, shuffle=True, random_state=cfg["seed"])
    oof = {n: np.full(len(y), np.nan) for n in names}
    folds = []
    for f, (tr, te) in enumerate(gkf.split(raw, y, groups)):
        overlap = len(set(groups[tr]) & set(groups[te]))
        if overlap:
            raise AssertionError(f"author leakage in fold {f}: {overlap} authors in train and test")
        folds.append({"fold": f, "train_posts": int(len(tr)), "test_posts": int(len(te)),
                      "train_authors": int(len(np.unique(groups[tr]))),
                      "test_authors": int(len(np.unique(groups[te]))), "author_overlap": overlap,
                      "train_idx": tr, "test_idx": te})
        for n in names:
            m = make_model(n, cfg).fit(raw.iloc[tr], y[tr], groups[tr])
            oof[n][te] = m.predict(raw.iloc[te])
    return oof, folds


def shuffle_within_author(y, groups, rng):
    y2 = np.array(y, dtype=float, copy=True)
    for _, idx in pd.Series(np.arange(len(y))).groupby(np.asarray(groups)).indices.items():
        y2[idx] = y2[rng.permutation(idx)]
    return y2


PERMUTE_GROUPS = {
    "hour": ["hour_utc", "hour_bin"],
    "weekday": ["weekday_num", "weekday"],
}


def permutation_pairwise(model, raw_te, y_te, g_te, cfg, rng):
    v = cfg["validation"]
    base = evaluate(y_te, model.predict(raw_te), g_te, _no_boot(cfg), rng)
    cols = [c for c in raw_te.columns if c not in sum(PERMUTE_GROUPS.values(), []) and c != "__text"]
    groups = {c: [c] for c in cols}
    groups.update({k: [c for c in vs if c in raw_te.columns] for k, vs in PERMUTE_GROUPS.items()})
    if isinstance(model, TextModel):
        groups["text_tokens"] = ["__text"]
    out = []
    for name, cs in groups.items():
        if not cs or raw_te[cs[0]].nunique(dropna=False) < 2:
            continue
        drops = []
        for _ in range(int(v["permutation_repeats"])):
            perm = rng.permutation(len(raw_te))
            r2 = raw_te.copy()
            for c in cs:
                r2[c] = raw_te[c].to_numpy()[perm]
            acc = evaluate(y_te, model.predict(r2), g_te, _no_boot(cfg), rng).get("pairwise_accuracy", np.nan)
            drops.append(base.get("pairwise_accuracy", np.nan) - acc)
        out.append({"feature": name, "pairwise_accuracy_drop": float(np.mean(drops)),
                    "sd": float(np.std(drops))})
    out.sort(key=lambda r: -r["pairwise_accuracy_drop"])
    return {"base_pairwise_accuracy": base.get("pairwise_accuracy"), "n_pairs": base["n_pairs"], "features": out}


def _no_boot(cfg):
    c = copy.deepcopy(cfg)
    c["validation"]["metric_bootstrap"] = 0
    return c


def effects_table(model: LinearModel, draws, raw, groups, point=None):
    names, sources = model.spec.names, model.spec.sources
    X = model.spec.transform(raw)
    point = model.per_unit() if point is None else np.asarray(point, dtype=float)
    rows = []
    for k, nm in enumerate(names):
        col = X[:, k]
        nz = col != 0
        lo, hi = (np.quantile(draws[:, k], [0.025, 0.975]) if draws is not None else (np.nan, np.nan))
        sd = float(model.scaler.scale_[k])
        r = {
            "feature": nm,
            "source": sources[k],
            "per_unit": float(point[k]),
            "ci95": [float(lo), float(hi)],
            "x_views_per_unit": float(math.exp(point[k])),
            "x_views_ci95": [float(math.exp(lo)), float(math.exp(hi))] if np.isfinite(lo) else None,
            "per_sd": float(point[k] * sd),
            "sd": sd,
            "ci_excludes_zero": bool(np.isfinite(lo) and (lo > 0 or hi < 0)),
            "n_posts_nonzero": int(nz.sum()),
            "n_authors_nonzero": int(len(np.unique(groups[nz]))),
        }
        if draws is not None and model.kind != "ridge":
            r["selection_frequency"] = float((np.abs(draws[:, k]) > 1e-12).mean())
        rows.append(r)
    rows.sort(key=lambda r: -abs(r["per_sd"]))
    return rows


def drop_top_authors_effects(model: LinearModel, rows: list, raw, y, groups, features, K, B, alpha, rng,
                             y_redraw=None) -> list:
    """For each named effect (a linear column such as 'opener=number' or 'cashtag_count'): drop the
    K authors with the most posts at that level (nonzero value) and re-estimate the effects-table
    regression (same encoding, within-author least squares at `alpha`, author bootstrap B) on the
    remaining posts. Returns one row per effect with the full-sample row and the re-estimate."""
    names = list(model.spec.names)
    unknown = [f for f in features if f not in names]
    if unknown:
        raise ValueError(f"drop-top-authors: unknown effect(s) {unknown}; valid names: {names}")
    full = {r["feature"]: r for r in rows}
    X = model.spec.transform(raw)
    groups = np.asarray(groups)
    out = []
    for feat in features:
        k = names.index(feat)
        nz = X[:, k] != 0
        at_level = pd.Series(nz.astype(int)).groupby(groups).sum()
        at_level = at_level[at_level > 0]
        top = sorted(at_level.items(), key=lambda kv: (-kv[1], str(kv[0])))[:K]
        dropped = {a for a, _ in top}
        keep = ~np.isin(groups, list(dropped))
        rk, yk, gk = raw[keep].reset_index(drop=True), y[keep], groups[keep]
        nzk = nz[keep]
        within = author_demean(X[keep][:, [k]], gk)[:, 0]
        r = {
            "feature": feat,
            "k": int(K),
            "full": {key: full[feat][key] for key in ("per_unit", "ci95", "n_posts_nonzero", "n_authors_nonzero")},
            "dropped_authors": [{"author": str(a), "posts_at_level": int(n)} for a, n in top],
            "posts_removed": int((~keep).sum()),
            "n_posts_nonzero": int(nzk.sum()),
            "n_authors_nonzero": int(len(np.unique(gk[nzk]))),
            "bootstrap": int(B),
        }
        if not np.any(np.abs(within) > 1e-12) or len(np.unique(gk)) < 2:
            r.update({"per_unit": None, "ci95": None,
                      "note": "not estimable: no within-author variation left at this level"})
        else:
            r["per_unit"] = float(model.effect_estimates(rk, yk, gk, alpha)[k])
            if B:
                kidx = np.flatnonzero(keep)
                yr = None if y_redraw is None else (lambda r, kidx=kidx: y_redraw(kidx[r])[kidx])
                draws = model.bootstrap(rk, yk, gk, B, rng, alpha=alpha, y_redraw=yr)[:, k]
                r["ci95"] = [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))]
            else:
                r["ci95"] = None
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_raw(d, cfg):
    raw = F.build_raw_features(d, cfg)
    raw["__text"] = d["text"].fillna("").astype(str) if "text" in d.columns else ""
    return raw


def feature_agreement(d, raw, cfg):
    """When both text and supplied feature columns exist, how well do our derived features match
    theirs? score_drafts.py always derives from text, so low agreement means a train/score mismatch
    if text_feature_source='columns'."""
    out = {}
    if "text" not in d.columns:
        return out
    derived = F.text_feature_frame(d["text"])
    for f, c in cfg.get("feature_columns", {}).items():
        if not c or c not in d.columns or f not in derived.columns:
            continue
        a, b = derived[f], d[c]
        if f in F.TEXT_CATEGORICAL:
            out[f] = {"column": c, "exact_match_share": float((a.astype(str) == F._norm_cat(b).astype(str)).mean())}
        else:
            bn = pd.to_numeric(b, errors="coerce")
            out[f] = {"column": c, "spearman": spearman(a.astype(float), bn),
                      "exact_match_share": float((a.astype(float) == bn).mean())}
    return out


def bucket_masks(d, cfg):
    out = {}
    if "author_followers" not in d.columns:
        return out
    for t in cfg["validation"]["small_author_followers"]:
        out[f"followers<{t:g}"] = (d["author_followers"] < t).to_numpy()
    return out


def run(cfg: dict, data: pd.DataFrame | None = None, out_dir: str | None = None, quick: bool = False,
        verbose: bool = True) -> dict:
    t0 = dt.datetime.now(dt.timezone.utc)
    rng = np.random.default_rng(cfg["seed"])
    if quick:
        cfg = _merge(cfg, {"models": {"bootstrap": 30, "bootstrap_enet": 0, "text": False},
                           "validation": {"metric_bootstrap": 200, "permutation_repeats": 1}})

    def log(msg):
        if verbose:
            print(f"[{(dt.datetime.now(dt.timezone.utc) - t0).total_seconds():6.1f}s] {msg}", flush=True)

    if data is None:
        if not cfg.get("data_path"):
            raise ValueError("no data: set data_path in the config or pass --data")
        path = resolve_path(cfg["data_path"], cfg)
        log(f"loading {path}")
        data = load_table(path)
    out_dir = out_dir or resolve_path(cfg.get("output_dir") or "out", cfg)
    os.makedirs(out_dir, exist_ok=True)

    d, info = prepare(data, cfg)
    log(f"prepared {len(d)} posts / {d['author'].nunique()} authors")
    raw = build_raw(d, cfg)
    y = d["y"].to_numpy(float)
    groups = d["author"].to_numpy()
    m = cfg["models"]
    names = [n for n in ("ridge", "elastic_net", "hgb", "text") if m.get(n)]
    if "text" in names and not raw["__text"].str.strip().astype(bool).any():
        names.remove("text")
        info["warnings"].append("text model skipped: no text")
    if not names:
        raise ValueError("no models enabled")
    probe = F.FeatureSpec("linear", m["min_level_count"]).fit(raw)
    if len(np.unique(groups)) < 4:
        raise ValueError("need at least 4 authors for GroupKFold validation")
    K_drop = int(m.get("drop_top_authors") or 0)
    if K_drop < 0:
        raise ValueError("models.drop_top_authors (--drop-top-authors) must be >= 0")
    if m.get("drop_top_effects") and K_drop == 0:
        raise ValueError("models.drop_top_effects (--drop-effect) needs models.drop_top_authors "
                         "(--drop-top-authors K) > 0")
    if K_drop and "ridge" not in names:
        info["warnings"].append("drop_top_authors ignored: it re-estimates the ridge effects table and "
                                "models.ridge is off")
    y_redraw = info.get("y_redraw")

    age_info = info.get("age_adjustment")
    report = {
        "kit_version": KIT_VERSION,
        "generated_utc": t0.isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "target": {
            "definition": ("y = log(views+1) - log(author_median_views+1) at a fixed age" if not age_info else
                           f"y = log(views_adj+1) - log(author_median views_adj+1), log(views_adj+1) = log(views+1) "
                           f"- [f(age) - f({float(cfg['target']['age_hours']):g} h)], f = {age_info['method']} "
                           "in log(age_hours) with author fixed effects"),
            "age_adjust": cfg["target"].get("age_adjust", "none"),
            "age_filter": cfg["target"]["age_filter"],
            "age_hours": cfg["target"]["age_hours"],
            "age_tolerance_hours": cfg["target"]["age_tolerance_hours"],
            "author_median_source": cfg["target"]["author_median_source"],
            "min_posts_per_author": cfg["target"]["min_posts_per_author"],
            "y_summary": {"mean": float(y.mean()), "sd": float(y.std()), "p10": float(np.quantile(y, 0.1)),
                          "median": float(np.median(y)), "p90": float(np.quantile(y, 0.9))},
            "pair_margin": cfg["validation"]["pair_margin"],
        },
        "data": {"funnel": info["funnel"], "composition": info["composition"]},
        "age_adjustment": age_info,
        "features": {
            "text_feature_source": cfg.get("text_feature_source", "derive"),
            "linear_columns": probe.names,
            "linear_references": probe.reference,
            "excluded_by_design": ["followers", "author median / baseline", "engagement labels",
                                   "snapshot age", "author identity"],
            "agreement_with_supplied_columns": feature_agreement(d, raw, cfg),
        },
        "warnings": info["warnings"],
    }

    # --- GroupKFold by author ---------------------------------------------
    log(f"GroupKFold by author: {names}")
    run_names = names + (["binary_top"] if cfg["target"]["binary"] else [])
    oof, folds = group_kfold(raw, y, groups, run_names, cfg)
    gk = {"folds": [{k: v for k, v in f.items() if not k.endswith("_idx")} for f in folds],
          "author_overlap_total": int(sum(f["author_overlap"] for f in folds)), "models": {}}
    for n in names:
        res = evaluate(y, oof[n], groups, cfg, rng)
        res["fold_pairwise_accuracy"] = [
            evaluate(y[f["test_idx"]], oof[n][f["test_idx"]], groups[f["test_idx"]], _no_boot(cfg), rng
                     ).get("pairwise_accuracy") for f in folds]
        gk["models"][n] = res
    if cfg["target"]["binary"]:
        lab_rows = []
        for f in folds:
            thr = float(np.quantile(y[f["train_idx"]], 1 - cfg["target"]["binary_top_fraction"]))
            lab_rows.append((f["test_idx"], (y[f["test_idx"]] >= thr).astype(int)))
        label = np.zeros(len(y), int)
        for idx, lab in lab_rows:
            label[idx] = lab
        gk["binary_top"] = evaluate_binary(label, oof["binary_top"], groups, cfg, rng)
        gk["binary_top"]["ranking"] = evaluate(y, oof["binary_top"], groups, cfg, rng)
    primary = m.get("primary_model", "auto")
    if primary == "auto":
        primary = max(names, key=lambda n: gk["models"][n].get("pairwise_accuracy", -1))
    gk["primary_model"] = primary
    gk["small_author_buckets"] = {
        b: evaluate(y[mask], oof[primary][mask], groups[mask], cfg, rng)
        for b, mask in bucket_masks(d, cfg).items() if mask.sum() > 1}
    if "found_via" in d.columns:
        fv = {}
        for val, idx in pd.Series(np.arange(len(y))).groupby(d["found_via"].to_numpy()).indices.items():
            if len(idx) > 1:
                fv[str(val)] = evaluate(y[idx], oof[primary][idx], groups[idx], cfg, rng)
        gk["by_found_via"] = fv
    report["group_kfold"] = gk
    report["primary_model"] = primary

    # The effects-table model itself (within-author least squares, effects_alpha) through the same
    # GroupKFold; its own rng so the other numbers in the report do not move.
    eff_val = None
    if "ridge" in names:
        rng_e = np.random.default_rng(int(cfg["seed"]) + 7919)
        oof_e, _ = group_kfold(raw, y, groups, ["effects_ls"], cfg)
        eff_val = {"group_kfold": evaluate(y, oof_e["effects_ls"], groups, cfg, rng_e)}
        if cfg["validation"]["shuffle_control"]:
            log("shuffled-target control for the effects model")
            reps_e = max(1, int(cfg["validation"]["shuffle_control_repeats"]))
            accs_e = []
            for k in range(reps_e):
                ys = shuffle_within_author(y, groups, np.random.default_rng(cfg["seed"] + 1 + k))
                oc, _ = group_kfold(raw, ys, groups, ["effects_ls"], cfg)
                accs_e.append(evaluate(ys, oc["effects_ls"], groups, _no_boot(cfg), rng_e).get("pairwise_accuracy"))
            accs_e = np.array([a for a in accs_e if a is not None], dtype=float)
            eff_val["shuffled_control"] = {
                "n": int(len(accs_e)), "pairwise_accuracy": accs_e.tolist(), "mean": float(accs_e.mean()),
                "sd": float(accs_e.std(ddof=1)) if len(accs_e) > 1 else None,
                "min": float(accs_e.min()), "max": float(accs_e.max())}

    # --- shuffled-target control --------------------------------------------
    if cfg["validation"]["shuffle_control"]:
        log("shuffled-target control")
        ctrl_names = [n for n in ("ridge", "hgb") if n in names] or names[:1]
        reps = max(1, int(cfg["validation"]["shuffle_control_repeats"]))
        accs = []
        for k in range(reps):
            ys = shuffle_within_author(y, groups, np.random.default_rng(cfg["seed"] + 1 + k))
            run_c = ctrl_names if k == 0 else ctrl_names[:1]
            oof_c, _ = group_kfold(raw, ys, groups, run_c, cfg)
            if k == 0:
                first = {n: evaluate(ys, oof_c[n], groups, cfg, rng) for n in run_c}
                accs.append(first[run_c[0]].get("pairwise_accuracy"))
            else:
                accs.append(evaluate(ys, oof_c[run_c[0]], groups, _no_boot(cfg), rng).get("pairwise_accuracy"))
        accs = np.array([a for a in accs if a is not None], dtype=float)
        report["shuffled_control"] = {
            "note": "target permuted within author, full pipeline rerun; pairwise accuracy should be ~0.5",
            "models": first,
            "repeats": {"model": ctrl_names[0], "n": int(len(accs)), "pairwise_accuracy": accs.tolist(),
                        "mean": float(accs.mean()), "sd": float(accs.std(ddof=1)) if len(accs) > 1 else None,
                        "min": float(accs.min()), "max": float(accs.max())}}

    # --- time split ------------------------------------------------------------
    if "created_at" in d.columns and d["created_at"].notna().all():
        weeks = float(cfg["validation"]["time_test_weeks"])
        cut = d["created_at"].max() - pd.Timedelta(weeks=weeks)
        te = (d["created_at"] > cut).to_numpy()
        tr = ~te
        ts = {"test_from_utc": str(cut), "test_weeks": weeks, "train_posts": int(tr.sum()),
              "test_posts": int(te.sum()),
              "authors_in_both": int(len(set(groups[tr]) & set(groups[te]))),
              "note": "temporal holdout; authors may appear on both sides (GroupKFold covers new authors)",
              "models": {}}
        if tr.sum() >= 100 and te.sum() >= 50 and len(np.unique(groups[tr])) >= 4:
            log("time split")
            for n in names:
                mod = make_model(n, cfg).fit(raw[tr].reset_index(drop=True), y[tr], groups[tr])
                ts["models"][n] = evaluate(y[te], mod.predict(raw[te].reset_index(drop=True)), groups[te], cfg, rng)
            if te.sum() < 500:
                report["warnings"].append(f"time-split test set is small ({int(te.sum())} posts)")
        else:
            report["warnings"].append("time split skipped: too few posts before or after the cut")
        report["time_split"] = ts
    else:
        report["warnings"].append("time split skipped: created_at missing or unparseable for some rows")

    # --- final models on all data + effects ------------------------------------
    log("final fits on all data")
    final = {n: make_model(n, cfg).fit(raw, y, groups) for n in names}
    effects = {}
    ea = float(m.get("effects_alpha", 1e-6))
    within = bool(m.get("within_author_demean", True))
    if "ridge" in final:
        B = int(m["bootstrap"] or 0)
        log(f"effects: {'within-author ' if within else ''}least squares, bootstrap x{B} (authors resampled)")
        point = final["ridge"].effect_estimates(raw, y, groups, ea)
        draws = final["ridge"].bootstrap(raw, y, groups, B, rng, alpha=ea, y_redraw=y_redraw) if B else None
        effects["ridge"] = {
            "method": ("within-author (author-demeaned) " if within else "") + f"least squares, ridge alpha {ea:g}; "
                      "not the predictive ridge, whose cross-validated penalty shrinks coefficients",
            "alpha": ea, "predictive_ridge_alpha": final["ridge"].alpha, "bootstrap": B,
            "age_fit_refitted_in_bootstrap": y_redraw is not None,
            "rows": effects_table(final["ridge"], draws, raw, groups, point),
            "validation": eff_val}
        K = K_drop
        if K > 0:
            feats = list(m.get("drop_top_effects") or []) or [
                r["feature"] for r in effects["ridge"]["rows"] if r["ci_excludes_zero"]]
            if not feats:
                report["warnings"].append(
                    f"drop_top_authors = {K} did nothing: no effect named (drop_top_effects / --drop-effect) and no "
                    "effect's CI excludes 0" + (" (models.bootstrap = 0: no CIs)" if not B else ""))
            else:
                log(f"drop-top-{K}-authors re-estimates: {feats} (bootstrap x{B})")
                effects["ridge"]["drop_top_authors"] = drop_top_authors_effects(
                    final["ridge"], effects["ridge"]["rows"], raw, y, groups, feats, K, B, ea,
                    np.random.default_rng(int(cfg["seed"]) + 104729), y_redraw=y_redraw)
    if "elastic_net" in final:
        B = int(m.get("bootstrap_enet") or 0)
        log(f"elastic-net bootstrap x{B}")
        draws = final["elastic_net"].bootstrap(raw, y, groups, B, rng, y_redraw=y_redraw) if B else None
        effects["elastic_net"] = {"alpha": final["elastic_net"].alpha, "l1_ratio": final["elastic_net"].l1_ratio,
                                  "bootstrap": B, "rows": effects_table(final["elastic_net"], draws, raw, groups)}
    if "text" in final:
        effects["text_terms"] = final["text"].top_terms()
    # permutation importance (drop in pairwise accuracy) on GroupKFold fold 0
    f0 = folds[0]
    log("permutation importance (fold 0)")
    pm = make_model(primary, cfg).fit(raw.iloc[f0["train_idx"]].reset_index(drop=True), y[f0["train_idx"]],
                                      groups[f0["train_idx"]])
    effects["permutation_pairwise"] = permutation_pairwise(
        pm, raw.iloc[f0["test_idx"]].reset_index(drop=True), y[f0["test_idx"]], groups[f0["test_idx"]], cfg, rng)
    report["effects"] = effects

    binary_final = BinaryModel(cfg).fit(raw, y, groups) if cfg["target"]["binary"] else None

    # --- secondary: within-author ER -------------------------------------------
    er_final = None
    if cfg["target"]["secondary_er"] and np.isfinite(d["y_er"]).sum() > 50:
        log("secondary target: within-author ER")
        ok = np.isfinite(d["y_er"].to_numpy(float))
        rer, yer, ger = raw[ok].reset_index(drop=True), d["y_er"].to_numpy(float)[ok], groups[ok]
        er_names = [n for n in ("ridge", "hgb") if n in names] or names[:1]
        oof_er, _ = group_kfold(rer, yer, ger, er_names, cfg)
        er_final = LinearModel(cfg, "ridge").fit(rer, yer, ger)
        B = min(int(m["bootstrap"]), 100)
        draws = er_final.bootstrap(rer, yer, ger, B, rng, alpha=ea) if B else None
        report["secondary_er"] = {
            "definition": "y_er = log(ER + eps) - log(author leave-one-out median ER + eps)",
            "er_source": info["er_source"],
            "group_kfold": {n: evaluate(yer, oof_er[n], ger, cfg, rng) for n in er_names},
            "ridge_effects": effects_table(er_final, draws, rer, ger, er_final.effect_estimates(rer, yer, ger, ea))[:20],
        }
    elif cfg["target"]["secondary_er"]:
        report["warnings"].append("secondary ER target skipped: no engagement rate or engagement counts")

    # --- save -----------------------------------------------------------------
    bundle = {
        "kit_version": KIT_VERSION,
        "sklearn_version": sklearn.__version__,
        "created_utc": t0.isoformat(timespec="seconds"),
        "config": {k: v for k, v in cfg.items() if not k.startswith("_")},
        "models": final,
        "primary": primary,
        "binary": binary_final,
        "er_model": er_final,
        "pair_margin": cfg["validation"]["pair_margin"],
        "validation_summary": {n: {k: gk["models"][n].get(k) for k in
                                   ("pairwise_accuracy", "pairwise_accuracy_ci95", "n_pairs",
                                    "n_authors_with_pairs", "spearman")} for n in names},
        "train_posts": int(len(d)),
        "train_authors": int(d["author"].nunique()),
    }
    model_path = os.path.join(out_dir, "model.pkl")
    with open(model_path, "wb") as fh:
        pickle.dump(bundle, fh)
    pred = pd.DataFrame({"post": d["_post"], "author": d["author"], "y": y})
    if "created_at" in d.columns:
        pred["created_at"] = d["created_at"].astype(str)
    for n in oof:
        pred[f"oof_{n}"] = oof[n]
    pred.to_csv(os.path.join(out_dir, "predictions_oof.csv"), index=False)
    report["outputs"] = {"model": model_path, "report_json": os.path.join(out_dir, "report.json"),
                         "report_md": os.path.join(out_dir, "report.md"),
                         "predictions_oof": os.path.join(out_dir, "predictions_oof.csv")}
    report["runtime_seconds"] = round((dt.datetime.now(dt.timezone.utc) - t0).total_seconds(), 1)
    clean = _jsonable(report)
    with open(report["outputs"]["report_json"], "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=2)
    with open(report["outputs"]["report_md"], "w", encoding="utf-8") as fh:
        fh.write(render_markdown(clean))
    log(f"wrote {out_dir}")
    report["_oof"] = oof
    report["_prepared"] = d
    return report


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else round(f, 6)
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def _f(x, nd=3):
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _ci(c, nd=3):
    return f"[{c[0]:.{nd}f}, {c[1]:.{nd}f}]" if c and c[0] is not None and c[1] is not None else "-"


def _metric_rows(models: dict) -> list[str]:
    rows = ["| model | pairwise acc | 95% CI (authors resampled) | N pairs | N authors | author-macro acc "
            "(N authors >= 10 pairs) | Spearman | within-author Spearman | lift@top10% | N posts | note |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, r in models.items():
        rows.append(
            f"| {n} | {_f(r.get('pairwise_accuracy'))} | {_ci(r.get('pairwise_accuracy_ci95'))} | "
            f"{r.get('n_pairs', 0):,} | {r.get('n_authors_with_pairs', 0)} | "
            f"{_f(r.get('pairwise_accuracy_author_macro'))} ({r.get('n_authors_macro', 0)}) | {_f(r.get('spearman'))} | "
            f"{_f(r.get('spearman_within_author_mean'))} | {_f(r.get('lift_top_decile'), 2)} | "
            f"{r.get('n_posts', 0):,} | {'LOW N: not a finding' if r.get('low_n') else ''} |")
    return rows


def render_markdown(r: dict) -> str:
    L = []
    gk = r["group_kfold"]
    prim = r["primary_model"]
    pm = gk["models"][prim]
    L += [f"# Viral model report (kit {r['kit_version']})", "",
          f"Generated {r['generated_utc']} UTC. Target: `{r['target']['definition']}` "
          f"(age {r['target']['age_hours']} h +/- {r['target']['age_tolerance_hours']} h, author median: "
          f"{r['target']['author_median_source']}). Pair margin |dy| > {r['target']['pair_margin']}.", ""]
    line = (f"**Primary model: {prim}.** Within-author pairwise accuracy (GroupKFold by author) "
            f"{_f(pm.get('pairwise_accuracy'))} {_ci(pm.get('pairwise_accuracy_ci95'))}, "
            f"N = {pm.get('n_pairs', 0):,} pairs from {pm.get('n_authors_with_pairs', 0)} authors; 0.5 = chance. "
            f"Author-macro (each author weighted equally, authors with >= 10 pairs): "
            f"{_f(pm.get('pairwise_accuracy_author_macro'))}, N = {pm.get('n_authors_macro', 0)} authors.")
    ctrl = r.get("shuffled_control", {}).get("repeats")
    if ctrl:
        line += (f" Shuffled-target control ({ctrl['model']}, {ctrl['n']} permutations): mean "
                 f"{_f(ctrl['mean'])}, range {_f(ctrl['min'])}-{_f(ctrl['max'])}.")
    L += [line, ""]

    L += ["## Corpus", "", "| stage | rows | posts | authors |", "|---|---|---|---|"]
    for s in r["data"]["funnel"]:
        L.append(f"| {s['stage']} | {s['rows']:,} | {s['posts']:,} | {s['authors']:,} |")
    comp = r["data"]["composition"]
    ppa = comp["posts_per_author"]
    L += ["", f"Posts per author: min {ppa['min']}, median {ppa['median']:.0f}, p90 {ppa['p90']:.0f}, "
          f"max {ppa['max']}; top-10 authors hold {ppa['top10_authors_share_of_posts']:.1%} of posts."]
    if comp.get("created_at_range"):
        L.append(f"Created: {comp['created_at_range'][0]} to {comp['created_at_range'][1]}.")
    if comp.get("by_found_via"):
        L += ["", "| found_via | posts loaded | authors loaded | posts final | authors final |", "|---|---|---|---|---|"]
        for k, v in comp["by_found_via"].items():
            L.append(f"| {k} | {v['posts_loaded']:,} | {v['authors_loaded']:,} | {v['posts_final']:,} | "
                     f"{v['authors_final']:,} |")
    if comp.get("media_type_posts"):
        L += ["", "Media type (posts): " + ", ".join(f"{k} {v:,}" for k, v in comp["media_type_posts"].items())]
    if comp.get("authors_by_followers"):
        L += ["Authors by followers: " + ", ".join(f"{k} {v:,}" for k, v in comp["authors_by_followers"].items())]

    ag = r.get("age_adjustment")
    if ag:
        ctl = ("with the content features as within-author controls" if ag["controls"] == "features"
               else "age only (no feature controls)")
        L += ["", f"## Age adjustment ({ag['method']})", "",
              f"log(views+1) modelled on {ag['basis']['variable']}"
              + (f" (natural spline, df {ag['basis']['df']}, knots at "
                 + ", ".join(f"{k:.1f}" for k in ag["basis"]["knots_age_hours"]) + " h)"
                 if ag["method"] == "spline" else "")
              + f", author fixed effects, {ctl}; pooled over N = {ag['n_posts']:,} posts from {ag['n_authors']:,} "
              f"authors ({ag['n_authors_with_age_variation']:,} with more than one distinct age). Snapshot age "
              f"{ag['age_hours']['min']:.1f}-{ag['age_hours']['max']:.1f} h (median {ag['age_hours']['median']:.1f}). "
              f"Every post is moved to {ag['reference_age_hours']:g} h before the within-author target is built. "
              "Age is not a model feature and is not used at scoring. The curve is fitted once on all posts, "
              "before GroupKFold (not per fold; on synthetic data refitting it per fold moved pairwise accuracy "
              "by at most 0.0003). Effects CIs refit the curve in every bootstrap draw, so they include its "
              "uncertainty.", "",
              f"**Age slope** (d log(views+1) / d log(age)): {ag['slope_per_log_age']:+.3f} "
              f"{_ci(ag.get('slope_ci95'))}, bootstrap B = {ag['bootstrap']} (authors resampled); {ag['slope_note']}.",
              "", "| age (h) | f(age) - f(ref) | 95% CI | x views vs ref |", "|---|---|---|---|"]
        for c in ag["curve"]:
            L.append(f"| {c['age_hours']:g} | {c['log_adjustment']:+.3f} | {_ci(c.get('ci95'))} | "
                     f"{c['x_views_vs_reference']:.3f} |")

    L += ["", "## Validation: GroupKFold by author (no author in both train and test)", "",
          f"Folds: {len(gk['folds'])}; author overlap across all folds: {gk['author_overlap_total']}.", ""]
    L += _metric_rows(gk["models"])
    L += ["", "Per-fold pairwise accuracy: " + "; ".join(
        f"{n} " + ", ".join(_f(a) for a in m["fold_pairwise_accuracy"]) for n, m in gk["models"].items())]
    if gk.get("small_author_buckets"):
        L += ["", f"### Small-author buckets ({prim}, GroupKFold)", ""] + _metric_rows(gk["small_author_buckets"])
    if gk.get("by_found_via"):
        L += ["", f"### By found_via ({prim}, GroupKFold)", ""] + _metric_rows(gk["by_found_via"])
    if gk.get("binary_top"):
        b = gk["binary_top"]
        L += ["", "### Binary top-fraction label (HGB + isotonic calibration, GroupKFold)", "",
              f"N = {b['n_posts']:,} posts, {b['n_positive']:,} positive (base rate {b['base_rate']:.3f}). "
              f"AUC {_f(b.get('auc'))}; Brier {_f(b['brier'])} vs {_f(b['brier_base_rate_only'])} for the base "
              f"rate alone; within-author pairwise accuracy of the probability "
              f"{_f(b['ranking'].get('pairwise_accuracy'))} (N = {b['ranking'].get('n_pairs', 0):,} pairs).", "",
              "| predicted-p quintile | N | mean predicted | observed rate |", "|---|---|---|---|"]
        for q in b["reliability"]:
            L.append(f"| {q['bin'] + 1} | {q['n']:,} | {q['mean_predicted']:.3f} | {q['observed_rate']:.3f} |")
    if r.get("shuffled_control"):
        L += ["", "## Shuffled-target control", "", r["shuffled_control"]["note"] + ".", ""]
        L += _metric_rows(r["shuffled_control"]["models"])
        rp = r["shuffled_control"].get("repeats")
        if rp:
            L += ["", f"{rp['model']} over {rp['n']} permutations: " + ", ".join(_f(a) for a in rp["pairwise_accuracy"])
                  + f" (mean {_f(rp['mean'])}, sd {_f(rp.get('sd'))}). This spread is the noise floor for "
                  "comparing models; the bootstrap CIs above cover author sampling only, not refit variance."]
    if r.get("time_split"):
        ts = r["time_split"]
        L += ["", "## Validation: time split", "",
              f"Test = posts after {ts['test_from_utc']} (last {ts['test_weeks']:g} weeks): train {ts['train_posts']:,} "
              f"posts, test {ts['test_posts']:,}; {ts['authors_in_both']} authors on both sides ({ts['note']}).", ""]
        if ts["models"]:
            L += _metric_rows(ts["models"])
    eff = r.get("effects", {})
    if eff.get("ridge"):
        e = eff["ridge"]
        L += ["", f"## Feature effects (within-author least squares, bootstrap B = {e.get('bootstrap', 0)})", ""]
        ev = e.get("validation")
        if ev:
            g = ev["group_kfold"]
            vline = (f"Effects model's own within-author pairwise accuracy (GroupKFold by author): "
                     f"{_f(g.get('pairwise_accuracy'))} {_ci(g.get('pairwise_accuracy_ci95'))}, "
                     f"N = {g.get('n_pairs', 0):,} pairs from {g.get('n_authors_with_pairs', 0)} authors; author-macro "
                     f"{_f(g.get('pairwise_accuracy_author_macro'))} (N = {g.get('n_authors_macro', 0)} authors)")
            sc = ev.get("shuffled_control")
            if sc:
                vline += (f". Shuffled-target control, same model ({sc['n']} permutations): mean {_f(sc['mean'])}, "
                          f"range {_f(sc['min'])}-{_f(sc['max'])}")
            L += [vline + (". LOW N: not a finding." if g.get("low_n") else "."), ""]
        L += [f"{e.get('method', '')}. Approximate 95% CIs from {e.get('bootstrap', 0)} author-resampled bootstraps "
              "(percentile; on synthetic data they cover the true value somewhat less than 95% of the time). "
              "`per unit` is in log views vs the author median; `x views` = exp(per unit), e.g. 1.30 = +30% "
              "views vs the author's median for a one-unit change (0 -> 1 for flags and categories, vs the "
              "reference level). Sorted by |per SD|.",
              "References: " + ", ".join(f"{k}={v}" for k, v in r["features"]["linear_references"].items()), "",
              "| feature | per unit | 95% CI | x views | per SD | CI excludes 0 | N posts nonzero | N authors nonzero |",
              "|---|---|---|---|---|---|---|---|"]
        for row in e["rows"]:
            L.append(f"| {row['feature']} | {row['per_unit']:+.4f} | {_ci(row['ci95'], 4)} | "
                     f"{row['x_views_per_unit']:.3f} | {row['per_sd']:+.3f} | {'yes' if row['ci_excludes_zero'] else ''} | "
                     f"{row['n_posts_nonzero']:,} | {row['n_authors_nonzero']:,} |")
        if e.get("drop_top_authors"):
            dk = e["drop_top_authors"][0]["k"]
            L += ["", f"### Without the top {dk} authors at each level (re-estimated, bootstrap B = "
                  f"{e['drop_top_authors'][0]['bootstrap']})", "",
                  f"For each effect, the {dk} authors with the most posts at that level (nonzero value) are removed "
                  "and the same within-author regression is refitted. A big move means a few authors carry the effect.",
                  "", "| feature | per unit (all) | 95% CI | N posts nonzero | N authors nonzero | per unit (drop top "
                  f"{dk}) | 95% CI | N posts nonzero | N authors nonzero | authors dropped (posts at level) |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
            for dd in e["drop_top_authors"]:
                fu = dd["full"]
                pu = f"{dd['per_unit']:+.4f}" if dd.get("per_unit") is not None else dd.get("note", "-")
                L.append(f"| {dd['feature']} | {fu['per_unit']:+.4f} | {_ci(fu['ci95'], 4)} | "
                         f"{fu['n_posts_nonzero']:,} | {fu['n_authors_nonzero']:,} | {pu} | {_ci(dd.get('ci95'), 4)} | "
                         f"{dd['n_posts_nonzero']:,} | {dd['n_authors_nonzero']:,} | "
                         + ", ".join(f"{a['author']} ({a['posts_at_level']})" for a in dd["dropped_authors"]) + " |")
    if eff.get("elastic_net"):
        e = eff["elastic_net"]
        L += ["", f"## Elastic net (alpha {e['alpha']:g}, l1_ratio {e['l1_ratio']:g}, {e['bootstrap']} bootstraps)",
              "", "| feature | per unit | 95% CI | selected in share of bootstraps | N authors nonzero |",
              "|---|---|---|---|---|"]
        for row in e["rows"]:
            L.append(f"| {row['feature']} | {row['per_unit']:+.4f} | {_ci(row['ci95'], 4)} | "
                     f"{_f(row.get('selection_frequency'), 2)} | {row['n_authors_nonzero']:,} |")
    if eff.get("permutation_pairwise"):
        p = eff["permutation_pairwise"]
        L += ["", f"## Permutation importance ({prim}, GroupKFold fold 0)", "",
              f"Drop in within-author pairwise accuracy when one feature is shuffled across test posts "
              f"(base {_f(p['base_pairwise_accuracy'])}, N = {p['n_pairs']:,} pairs).", "",
              "| feature | accuracy drop | sd |", "|---|---|---|"]
        for row in p["features"]:
            L.append(f"| {row['feature']} | {row['pairwise_accuracy_drop']:+.4f} | {row['sd']:.4f} |")
    if eff.get("text_terms"):
        t = eff["text_terms"]
        L += ["", "## Text model terms (indicative only: topics and author style mix in; no CIs)", "",
              "Positive: " + ", ".join(f"`{x['term']}`" for x in t["positive"]),
              "", "Negative: " + ", ".join(f"`{x['term']}`" for x in t["negative"])]
    if r.get("secondary_er"):
        s = r["secondary_er"]
        L += ["", "## Secondary target: within-author engagement rate", "",
              f"`{s['definition']}`; ER source: {s['er_source']}.", ""] + _metric_rows(s["group_kfold"])
        L += ["", "| feature (ridge, ER) | per unit | 95% CI | CI excludes 0 | N authors nonzero |",
              "|---|---|---|---|---|"]
        for row in s["ridge_effects"]:
            L.append(f"| {row['feature']} | {row['per_unit']:+.4f} | {_ci(row['ci95'], 4)} | "
                     f"{'yes' if row['ci_excludes_zero'] else ''} | {row['n_authors_nonzero']:,} |")
    agree = r["features"].get("agreement_with_supplied_columns")
    if agree:
        L += ["", "## Derived vs supplied feature columns", "",
              f"text_feature_source = {r['features']['text_feature_source']}. score_drafts.py always derives "
              "features from draft text, so low agreement + source 'columns' means train/score mismatch.", "",
              "| feature | column | Spearman | exact match |", "|---|---|---|---|"]
        for k, v in agree.items():
            L.append(f"| {k} | {v['column']} | {_f(v.get('spearman'))} | {_f(v.get('exact_match_share'))} |")
    if r.get("warnings"):
        L += ["", "## Warnings", ""] + [f"- {w}" for w in r["warnings"]]
    L += ["", f"Runtime {r.get('runtime_seconds')} s; scikit-learn {r['sklearn_version']}.", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="JSON config (see config.example.json)")
    ap.add_argument("--data", help="override data_path")
    ap.add_argument("--out", help="override output_dir")
    ap.add_argument("--quick", action="store_true", help="fewer bootstraps, no text model (smoke run)")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--age-adjust", choices=AGE_ADJUST_MODES, help="override target.age_adjust")
    ap.add_argument("--drop-top-authors", type=int, metavar="K",
                    help="re-estimate effects without the K authors with the most posts at that level")
    ap.add_argument("--drop-effect", action="append", metavar="NAME",
                    help="effect for --drop-top-authors, e.g. opener=number (repeatable; default: every "
                         "effect whose CI excludes 0)")
    a = ap.parse_args(argv)
    over = {}
    if a.age_adjust:
        over["target"] = {"age_adjust": a.age_adjust}
    if a.drop_top_authors is not None:
        over.setdefault("models", {})["drop_top_authors"] = a.drop_top_authors
    if a.drop_effect:
        over.setdefault("models", {})["drop_top_effects"] = a.drop_effect
    if a.data:
        over["data_path"] = os.path.abspath(a.data)
    if a.seed is not None:
        over["seed"] = a.seed
    cfg = load_config(a.config, over)
    out = os.path.abspath(a.out) if a.out else None
    rep = run(cfg, out_dir=out, quick=a.quick)
    pm = rep["group_kfold"]["models"][rep["primary_model"]]
    print(f"primary={rep['primary_model']} pairwise_accuracy={pm.get('pairwise_accuracy'):.3f} "
          f"ci95={pm.get('pairwise_accuracy_ci95')} n_pairs={pm.get('n_pairs')} -> {rep['outputs']['report_md']}")


if __name__ == "__main__":
    # Run through the importable module so pickled model classes resolve as train.* in score_drafts.py.
    import train as _train

    _train.main()
