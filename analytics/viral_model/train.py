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

KIT_VERSION = "1.0.0"

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
    if "age_hours" in d.columns:
        d["age_hours"] = pd.to_numeric(d["age_hours"], errors="coerce")
    elif "created_at" in d.columns and "snapshot_utc" in d.columns:
        d["age_hours"] = (d["snapshot_utc"] - d["created_at"]).dt.total_seconds() / 3600.0
    elif tcfg["age_filter"]:
        raise ValueError("cannot determine post age: map age_hours, or created_at + snapshot_utc, "
                         "or set target.age_filter=false if every row is already at the fixed age")
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

    src = tcfg["author_median_source"]
    if src == "column":
        if "author_median_views" not in d.columns:
            raise ValueError("author_median_source='column' but no author_median_views column is mapped")
        med = pd.to_numeric(d["author_median_views"], errors="coerce").to_numpy()
        warn.append("author median taken from the supplied column; it must exclude the post itself")
    elif src == "leave_one_out":
        med = loo_median(d["views"].to_numpy(), groups)
    else:
        raise ValueError("target.author_median_source must be 'leave_one_out' or 'column'")
    d["author_median_views_used"] = med
    d["y"] = np.log1p(d["views"].to_numpy(dtype=float)) - np.log1p(med)
    d = d[np.isfinite(d["y"])].reset_index(drop=True)

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
        self.name = "ridge" if kind == "ridge" else "elastic_net"

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
        if self.kind == "ridge":
            self.alpha = float(RidgeCV(alphas=m["ridge_alphas"], cv=cv).fit(Xs, y_fit).alpha_)
            self.l1_ratio = 0.0
        else:
            with pywarnings.catch_warnings():
                pywarnings.simplefilter("ignore")
                cvm = ElasticNetCV(l1_ratio=m["enet_l1_ratios"], alphas=m["enet_alphas"], cv=cv,
                                   max_iter=5000).fit(Xs, y_fit)
            self.alpha, self.l1_ratio = float(cvm.alpha_), float(cvm.l1_ratio_)
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
        if self.kind == "ridge":
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

    def bootstrap(self, raw, y, groups, B, rng):
        Xs, y = self._fit_space(self.design(raw), y, groups)
        uniq = np.unique(groups)
        pos = pd.Series(np.arange(len(y))).groupby(np.asarray(groups)).indices
        draws = np.zeros((B, Xs.shape[1]))
        with pywarnings.catch_warnings():
            pywarnings.simplefilter("ignore")
            for b in range(B):
                pick = rng.choice(uniq, len(uniq), replace=True)
                rows = np.concatenate([pos[g] for g in pick])
                draws[b] = self._estimator().fit(Xs[rows], y[rows]).coef_ / self.scaler.scale_
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


def effects_table(model: LinearModel, draws, raw, groups):
    names, sources = model.spec.names, model.spec.sources
    X = model.spec.transform(raw)
    point = model.per_unit()
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

    report = {
        "kit_version": KIT_VERSION,
        "generated_utc": t0.isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "target": {
            "definition": "y = log(views+1) - log(author_median_views+1) at a fixed age",
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
    if "ridge" in final and m["bootstrap"]:
        log(f"ridge bootstrap x{m['bootstrap']} (authors resampled)")
        draws = final["ridge"].bootstrap(raw, y, groups, int(m["bootstrap"]), rng)
        effects["ridge"] = {"alpha": final["ridge"].alpha, "bootstrap": int(m["bootstrap"]),
                            "rows": effects_table(final["ridge"], draws, raw, groups)}
    elif "ridge" in final:
        effects["ridge"] = {"alpha": final["ridge"].alpha, "rows": effects_table(final["ridge"], None, raw, groups)}
    if "elastic_net" in final:
        B = int(m.get("bootstrap_enet") or 0)
        log(f"elastic-net bootstrap x{B}")
        draws = final["elastic_net"].bootstrap(raw, y, groups, B, rng) if B else None
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
        draws = er_final.bootstrap(rer, yer, ger, B, rng) if B else None
        report["secondary_er"] = {
            "definition": "y_er = log(ER + eps) - log(author leave-one-out median ER + eps)",
            "er_source": info["er_source"],
            "group_kfold": {n: evaluate(yer, oof_er[n], ger, cfg, rng) for n in er_names},
            "ridge_effects": effects_table(er_final, draws, rer, ger)[:20],
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
    rows = ["| model | pairwise acc | 95% CI (authors resampled) | N pairs | N authors | Spearman | "
            "within-author Spearman | lift@top10% | N posts | note |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for n, r in models.items():
        rows.append(
            f"| {n} | {_f(r.get('pairwise_accuracy'))} | {_ci(r.get('pairwise_accuracy_ci95'))} | "
            f"{r.get('n_pairs', 0):,} | {r.get('n_authors_with_pairs', 0)} | {_f(r.get('spearman'))} | "
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
            f"N = {pm.get('n_pairs', 0):,} pairs from {pm.get('n_authors_with_pairs', 0)} authors; 0.5 = chance.")
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
        L += ["", "## Feature effects (ridge, within-author target)", "",
              f"alpha {e['alpha']:g}; 95% CIs from {e.get('bootstrap', 0)} author-resampled bootstraps. "
              "`per unit` is in log views vs the author median; `x views` = exp(per unit), e.g. 1.30 = +30% "
              "views vs the author's median for a one-unit change (0 -> 1 for flags and categories, vs the "
              "reference level). Sorted by |per SD|.",
              "References: " + ", ".join(f"{k}={v}" for k, v in r["features"]["linear_references"].items()), "",
              "| feature | per unit | 95% CI | x views | per SD | CI excludes 0 | N posts nonzero | N authors |",
              "|---|---|---|---|---|---|---|---|"]
        for row in e["rows"]:
            L.append(f"| {row['feature']} | {row['per_unit']:+.4f} | {_ci(row['ci95'], 4)} | "
                     f"{row['x_views_per_unit']:.3f} | {row['per_sd']:+.3f} | {'yes' if row['ci_excludes_zero'] else ''} | "
                     f"{row['n_posts_nonzero']:,} | {row['n_authors_nonzero']:,} |")
    if eff.get("elastic_net"):
        e = eff["elastic_net"]
        L += ["", f"## Elastic net (alpha {e['alpha']:g}, l1_ratio {e['l1_ratio']:g}, {e['bootstrap']} bootstraps)",
              "", "| feature | per unit | 95% CI | selected in share of bootstraps |", "|---|---|---|---|"]
        for row in e["rows"]:
            L.append(f"| {row['feature']} | {row['per_unit']:+.4f} | {_ci(row['ci95'], 4)} | "
                     f"{_f(row.get('selection_frequency'), 2)} |")
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
        L += ["", "| feature (ridge, ER) | per unit | 95% CI | CI excludes 0 |", "|---|---|---|---|"]
        for row in s["ridge_effects"]:
            L.append(f"| {row['feature']} | {row['per_unit']:+.4f} | {_ci(row['ci95'], 4)} | "
                     f"{'yes' if row['ci_excludes_zero'] else ''} |")
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
    a = ap.parse_args(argv)
    over = {}
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
