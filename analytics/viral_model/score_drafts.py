"""Score 2-3 draft variants of one post with a model saved by train.py and print them ranked.

    python score_drafts.py --model out/model.pkl --drafts drafts.json
    python score_drafts.py --model out/model.pkl \
        --text "BREAKING: $NVDA ..." --media video --hour 14 \
        --text "$NVDA ... What is your take?" --media image --hour 14

drafts.json is a list of objects: {"name", "text", "media_type", "hour_utc"} plus optional
"weekday" (0=Mon..6=Sun or "Mon"), "post_time_utc" (ISO time; sets hour and weekday), "poll",
"thread", "is_quote" (true/false) and "extra" ({"<extra feature column>": value}).
Without a weekday the score is averaged over the 7 weekdays.

The score is the predicted y = log(views / author median views) at the model's fixed age, so
exp(score) reads as "x the author's median". Ranking between variants is what the model was
validated on (within-author pairwise accuracy); the absolute level assumes the author's usual
posts look like the training average.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F  # noqa: E402
import train  # noqa: E402,F401  (model classes for unpickling)


def load_bundle(path: str) -> dict:
    with open(path, "rb") as fh:
        b = pickle.load(fh)
    import sklearn

    if b.get("sklearn_version") != sklearn.__version__:
        print(f"warning: model saved with scikit-learn {b.get('sklearn_version')}, running {sklearn.__version__}",
              file=sys.stderr)
    return b


def _bool(v) -> int:
    if isinstance(v, str):
        return int(v.strip().lower() in ("1", "true", "yes", "y", "t"))
    return int(bool(v))


def drafts_frame(drafts: list[dict], cfg: dict) -> pd.DataFrame:
    """One row per (draft, weekday): drafts without a weekday expand to all 7 weekdays."""
    rows = []
    for i, dr in enumerate(drafts):
        if "text" not in dr:
            raise ValueError(f"draft {i} has no text")
        base = {
            "_draft": i,
            "text": dr["text"],
            "media_type": dr.get("media_type", "none"),
            "poll": _bool(dr.get("poll", False)),
            "thread": _bool(dr.get("thread", False)),
            "is_quote": _bool(dr.get("is_quote", False)),
        }
        for c, v in (dr.get("extra") or {}).items():
            base[c] = v
        hour, wd = dr.get("hour_utc"), dr.get("weekday")
        if dr.get("post_time_utc"):
            ts = pd.Timestamp(dr["post_time_utc"])
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            hour, wd = ts.hour, ts.weekday()
        if hour is None:
            raise ValueError(f"draft {i} needs hour_utc or post_time_utc")
        if isinstance(wd, str):
            wd = F.WEEKDAYS.index(wd[:3].title())
        for w in ([int(wd)] if wd is not None else range(7)):
            rows.append(dict(base, hour_utc=float(hour), weekday=float(w)))
    df = pd.DataFrame(rows)
    for c in cfg.get("extra_numeric_features", []) + cfg.get("extra_categorical_features", []):
        if c not in df.columns:
            df[c] = np.nan
    return df


def score(bundle: dict, drafts: list[dict]) -> list[dict]:
    cfg = bundle["config"]
    cfg_derive = dict(cfg, text_feature_source="derive")
    df = drafts_frame(drafts, cfg)
    raw = F.build_raw_features(df, cfg_derive)
    raw["__text"] = df["text"].fillna("").astype(str)
    did = df["_draft"].to_numpy()

    def per_draft(values):
        return pd.Series(values).groupby(did).mean().to_numpy()

    scores = {n: per_draft(m.predict(raw)) for n, m in bundle["models"].items()}
    primary = bundle["primary"]
    p_top = per_draft(bundle["binary"].predict(raw)) if bundle.get("binary") is not None else None
    er = per_draft(bundle["er_model"].predict(raw)) if bundle.get("er_model") is not None else None
    lin_name = primary if primary in ("ridge", "elastic_net") else (
        "ridge" if "ridge" in bundle["models"] else "elastic_net")
    lin = bundle["models"].get(lin_name)
    contrib = lin.contributions(raw).groupby(did).mean() if lin is not None else None

    out = []
    for i, dr in enumerate(drafts):
        s = float(scores[primary][i])
        r = {
            "name": dr.get("name") or f"draft {i + 1}",
            "text": dr["text"],
            "media_type": dr.get("media_type", "none"),
            "hour_utc": dr.get("hour_utc"),
            "score": s,
            "x_author_median": math.exp(s),
            "scores_by_model": {n: float(v[i]) for n, v in scores.items()},
        }
        if p_top is not None:
            r["p_top"] = float(p_top[i])
        if er is not None:
            r["er_score"] = float(er[i])
        if contrib is not None:
            c = contrib.loc[i].sort_values(key=np.abs, ascending=False)
            r["contributions_model"] = lin_name
            r["top_contributions"] = [{"feature": k, "value": float(v)} for k, v in c.head(4).items() if abs(v) > 1e-4]
        out.append(r)
    out.sort(key=lambda r: -r["score"])
    for k, r in enumerate(out):
        r["rank"] = k + 1
    return out


def render(bundle: dict, ranked: list[dict], author_median_views: float | None = None) -> str:
    cfg = bundle["config"]
    prim = bundle["primary"]
    v = bundle["validation_summary"].get(prim, {})
    ci = v.get("pairwise_accuracy_ci95")
    ci_txt = f"[{ci[0]:.3f}, {ci[1]:.3f}]" if ci else ""
    margin = bundle["pair_margin"]
    frac = cfg["target"]["binary_top_fraction"]
    L = [f"Model: {prim} (kit {bundle['kit_version']}, trained {bundle['created_utc']} on "
         f"{bundle['train_posts']:,} posts / {bundle['train_authors']:,} authors).",
         f"Validated within-author pairwise accuracy {v.get('pairwise_accuracy', float('nan')):.3f} "
         f"{ci_txt} on N = {v.get('n_pairs', 0):,} pairs with |dy| > {margin}; 0.5 = chance.",
         ""]
    hdr = f"{'rank':<5}{'score':>7}{'x median':>10}"
    if "p_top" in ranked[0]:
        hdr += f"{'P(top ' + format(frac, '.0%') + ')':>14}"
    if "er_score" in ranked[0]:
        hdr += f"{'ER score':>10}"
    if author_median_views:
        hdr += f"{'est. views':>12}"
    L.append(hdr + "  variant")
    for r in ranked:
        line = f"{r['rank']:<5}{r['score']:>+7.3f}{r['x_author_median']:>10.2f}"
        if "p_top" in r:
            line += f"{r['p_top']:>14.2f}"
        if "er_score" in r:
            line += f"{r['er_score']:>+10.3f}"
        if author_median_views:
            line += f"{author_median_views * r['x_author_median']:>12,.0f}"
        first = r["text"].strip().splitlines()[0] if r["text"].strip() else ""
        L.append(line + f"  {r['name']} [{r['media_type']}, {r['hour_utc']}h UTC]: {first[:70]}")
    L.append("")
    for r in ranked:
        if r.get("top_contributions"):
            L.append(f"{r['name']}: " + ", ".join(f"{c['feature']} {c['value']:+.3f}" for c in r["top_contributions"])
                     + f"  ({r['contributions_model']} contributions vs the average training post)")
    if len(ranked) > 1:
        gap = ranked[0]["score"] - ranked[1]["score"]
        verdict = "a clear gap" if gap > margin else "within the pair margin: treat #1 and #2 as a tie"
        L.append(f"Gap #1 vs #2: {gap:.3f} ({verdict}; margin {margin}).")
    other = {n: s for n, s in ranked[0]["scores_by_model"].items() if n != prim}
    if other:
        agree = []
        for n in other:
            order = sorted(ranked, key=lambda r: -r["scores_by_model"][n])
            agree.append(f"{n} {'agrees' if order[0]['name'] == ranked[0]['name'] else 'picks ' + order[0]['name']}")
        L.append("Other models on #1: " + ", ".join(agree) + ".")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=os.path.join("out", "model.pkl"))
    ap.add_argument("--drafts", help="JSON list of draft variants")
    ap.add_argument("--text", action="append", help="draft text (repeat per variant)")
    ap.add_argument("--media", action="append", help="media type per variant (none/image/video/...)")
    ap.add_argument("--hour", action="append", type=float, help="posting hour UTC per variant")
    ap.add_argument("--weekday", help="weekday for all inline variants (0=Mon or Mon); default: average")
    ap.add_argument("--author-median-views", type=float, help="print estimated views = median x score")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    a = ap.parse_args(argv)
    if a.drafts:
        with open(a.drafts, encoding="utf-8") as fh:
            drafts = json.load(fh)
    elif a.text:
        n = len(a.text)

        def at(lst, i, default):
            if not lst:
                return default
            return lst[i] if len(lst) == n else lst[0]

        drafts = [{"name": f"variant {chr(65 + i)}", "text": t, "media_type": at(a.media, i, "none"),
                   "hour_utc": at(a.hour, i, None), "weekday": a.weekday} for i, t in enumerate(a.text)]
    else:
        ap.error("give --drafts FILE or one or more --text")
    bundle = load_bundle(a.model)
    ranked = score(bundle, drafts)
    if a.json:
        print(json.dumps({"primary_model": bundle["primary"], "ranked": ranked}, indent=2, ensure_ascii=False))
    else:
        print(render(bundle, ranked, a.author_median_views))


if __name__ == "__main__":
    main()
