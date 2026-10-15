"""Tests for the viral-model kit on a synthetic dataset with a planted within-author effect.

    python -m pytest analytics/viral_model/tests -q
"""
import json
import os
import pickle
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KIT)

import features as F  # noqa: E402
import score_drafts as SD  # noqa: E402
import synthetic as S  # noqa: E402
import train as T  # noqa: E402


@pytest.fixture(scope="module")
def run_synth(tmp_path_factory):
    df = S.make_synthetic(n_authors=100, seed=7, mean_posts=35)
    cfg = T.load_config(None, S.synthetic_config("unused.csv"))
    cfg["models"]["bootstrap"] = 100
    cfg["models"]["bootstrap_enet"] = 0
    cfg["validation"]["metric_bootstrap"] = 300
    out = tmp_path_factory.mktemp("viral_model_out")
    rep = T.run(cfg, data=df, out_dir=str(out), verbose=False)
    return df, cfg, rep, out


def _effect(rep, name):
    return next(r for r in rep["effects"]["ridge"]["rows"] if r["feature"] == name)


# --- features -------------------------------------------------------------

def test_text_features_from_raw_text():
    t = ("\U0001F6A8 BREAKING: $NVDA up 12% to $950 after earnings\n"
         "- revenue beat\n- guidance raised\n"
         "What now? #stocks @someone https://t.co/abc")
    f = F.derive_text_features(t)
    assert f["opener"] == "breaking"
    assert f["emoji_position"] == "start" and f["emoji_count"] == 1
    assert f["cashtag_count"] == 1
    assert f["dollar_count"] == 1 and f["percent_count"] == 1
    assert f["number_count"] == 2
    assert f["hashtag_count"] == 1 and f["mention_count"] == 1
    assert f["line_breaks"] == 3 and f["list_lines"] == 2
    assert f["has_question"] == 1 and f["link_present"] == 1
    assert f["allcaps_ratio"] == 0  # the BREAKING opener is its own feature; $NVDA is a cashtag
    assert F.derive_text_features("JUST IN: Fed holds rates")["opener"] == "just_in"
    assert F.derive_text_features("Is $SPY topping here?")["opener"] == "question"
    assert F.derive_text_features("$TSLA deliveries beat")["opener"] == "cashtag"
    assert F.derive_text_features(None)["char_len"] == 0


def test_leave_one_out_median_never_uses_the_post_itself():
    v = np.array([1.0, 2, 3, 4, 100, 7, 8])
    g = np.array(["a", "a", "a", "a", "a", "b", "b"])
    med = T.loo_median(v, g)
    assert med[4] == 2.5  # median of 1,2,3,4
    assert med[0] == 3.5  # median of 2,3,4,100
    assert med[5] == 8 and med[6] == 7
    v2 = v.copy()
    v2[4] = 1e9  # changing a post's own views never changes its own baseline
    assert T.loo_median(v2, g)[4] == med[4]


def test_prepare_keeps_one_snapshot_in_the_age_window_and_drops_small_authors():
    df = S.make_synthetic(n_authors=30, seed=3, mean_posts=20)
    cfg = T.load_config(None, S.synthetic_config("unused.csv"))
    d, info = T.prepare(df, cfg)
    assert d["_post"].is_unique
    assert ((d["age_hours"] - 24).abs() <= 3).all()
    assert d.groupby("author").size().min() >= 5
    small = df.groupby("username")["post_id"].nunique()
    assert not set(small[small < 5].index) & set(d["author"])  # 3-post authors are gone
    stages = [s["stage"] for s in info["funnel"]]
    assert stages[0] == "loaded" and stages[-1].startswith("authors_with")


# --- leakage guards -------------------------------------------------------------

def test_no_author_in_both_train_and_test(run_synth):
    df, cfg, rep, _ = run_synth
    assert rep["group_kfold"]["author_overlap_total"] == 0
    d = rep["_prepared"]
    raw = T.build_raw(d, cfg)
    _, folds = T.group_kfold(raw, d["y"].to_numpy(), d["author"].to_numpy(), ["ridge"], cfg)
    authors = d["author"].to_numpy()
    for f in folds:
        assert not set(authors[f["train_idx"]]) & set(authors[f["test_idx"]])
    covered = np.concatenate([f["test_idx"] for f in folds])
    assert sorted(covered.tolist()) == list(range(len(d)))  # every post scored out of fold once


def test_no_follower_or_engagement_predictors(run_synth):
    _, _, rep, _ = run_synth
    cols = " ".join(rep["features"]["linear_columns"]).lower()
    for bad in ("follower", "impression", "favorite", "retweet", "reply_count", "bookmark", "age_hours", "median"):
        assert bad not in cols


def test_forbidden_extra_features_are_refused():
    over = S.synthetic_config("unused.csv")
    over["extra_numeric_features"] = ["followers_count"]
    with pytest.raises(ValueError):
        T.load_config(None, over)
    over["extra_numeric_features"] = ["log_impressions_lag"]
    with pytest.raises(ValueError):
        T.load_config(None, over)


# --- recovery and validation metrics ------------------------------------------------

def test_recovers_planted_within_author_effects(run_synth):
    _, _, rep, _ = run_synth
    for name, true in [("media_type=video", 0.50), ("opener=breaking", 0.40),
                       ("has_question", -0.30), ("media_type=image", 0.25)]:
        r = _effect(rep, name)
        assert r["ci_excludes_zero"], name
        assert abs(r["per_unit"] - true) < 0.12, (name, r["per_unit"], r["ci95"])
    c = _effect(rep, "cashtag_count")
    assert c["ci_excludes_zero"] and c["ci95"][0] <= 0.10 <= c["ci95"][1], c
    for name in S.NULL_FEATURES:  # planted zero: the 95% CI must cover 0
        r = _effect(rep, name)
        assert r["ci95"][0] <= 0 <= r["ci95"][1], (name, r["per_unit"], r["ci95"])


def test_pairwise_accuracy_beats_chance_and_shuffled_control_does_not(run_synth):
    _, _, rep, _ = run_synth
    gk = rep["group_kfold"]["models"]
    prim = gk[rep["primary_model"]]
    assert prim["pairwise_accuracy"] > 0.58, prim["pairwise_accuracy"]
    assert prim["pairwise_accuracy_ci95"][0] > 0.55
    assert prim["n_pairs"] > 10000 and not prim["low_n"]
    for n in ("ridge", "elastic_net", "hgb", "text"):
        assert gk[n]["pairwise_accuracy"] > 0.56, n
    ts = rep["time_split"]["models"]["ridge"]
    assert ts["pairwise_accuracy"] > 0.56
    ctrl = rep["shuffled_control"]["repeats"]
    assert abs(ctrl["mean"] - 0.5) < 0.02, ctrl
    assert max(abs(a - 0.5) for a in ctrl["pairwise_accuracy"]) < 0.04, ctrl
    assert prim["pairwise_accuracy"] - ctrl["max"] > 0.05


def test_pairwise_metric_definition():
    rng = np.random.default_rng(0)
    y = np.array([0.0, 1, 2, 3, 0, 1, 2])
    g = np.array(["a"] * 4 + ["b"] * 3)
    cfg = T._no_boot(T.load_config(None))
    assert T.evaluate(y, y, g, cfg, rng)["pairwise_accuracy"] == 1.0
    assert T.evaluate(y, -y, g, cfg, rng)["pairwise_accuracy"] == 0.0
    assert T.evaluate(y, np.zeros_like(y), g, cfg, rng)["pairwise_accuracy"] == 0.5
    # cross-author pairs never count: a model that only separates authors scores 0.5
    assert T.evaluate(y, (g == "a").astype(float), g, cfg, rng)["pairwise_accuracy"] == 0.5


def test_report_files_and_buckets(run_synth):
    _, _, rep, out = run_synth
    js = json.load(open(os.path.join(out, "report.json"), encoding="utf-8"))
    assert js["primary_model"] in ("ridge", "elastic_net", "hgb", "text")
    assert set(js["group_kfold"]["small_author_buckets"]) == {"followers<1000", "followers<100"}
    assert set(js["data"]["composition"]["by_found_via"]) == {"panel", "search"}
    assert js["group_kfold"]["binary_top"]["n_posts"] == js["data"]["composition"]["posts"]
    md = open(os.path.join(out, "report.md"), encoding="utf-8").read()
    assert "Shuffled-target control" in md and "N = " in md
    assert os.path.exists(os.path.join(out, "predictions_oof.csv"))


# --- drafts --------------------------------------------------------------------

def test_score_drafts_ranks_the_planted_better_variant_first(run_synth):
    _, _, _, out = run_synth
    bundle = SD.load_bundle(os.path.join(out, "model.pkl"))
    drafts = [
        {"name": "plain", "text": "Fund raised its $AMD stake in the latest 13F", "media_type": "none",
         "hour_utc": 22},
        {"name": "planted", "text": "BREAKING: Fund raised its $AMD stake in the latest 13F", "media_type": "video",
         "hour_utc": 13},
        {"name": "question", "text": "Fund raised its $AMD stake in the latest 13F. What is your take?",
         "media_type": "none", "hour_utc": 22, "weekday": "Tue"},
    ]
    ranked = SD.score(bundle, drafts)
    assert [r["name"] for r in ranked] == ["planted", "plain", "question"]
    assert ranked[0]["score"] - ranked[1]["score"] > 0.5
    text = SD.render(bundle, ranked, author_median_views=1000)
    assert "planted" in text.splitlines()[4]


def test_cli_end_to_end(tmp_path):
    py = sys.executable
    data, conf = tmp_path / "syn.csv", tmp_path / "syn_config.json"
    subprocess.run([py, os.path.join(KIT, "synthetic.py"), "--out", str(data), "--config-out", str(conf),
                    "--authors", "40"], check=True, cwd=tmp_path)
    r = subprocess.run([py, os.path.join(KIT, "train.py"), "--config", str(conf), "--out", str(tmp_path / "out"),
                        "--quick"], check=True, cwd=tmp_path, capture_output=True, text=True)
    assert "pairwise_accuracy=" in r.stdout
    r = subprocess.run([py, os.path.join(KIT, "score_drafts.py"), "--model", str(tmp_path / "out" / "model.pkl"),
                        "--drafts", os.path.join(KIT, "drafts.example.json")],
                       check=True, cwd=tmp_path, capture_output=True, text=True)
    assert "rank" in r.stdout and "A breaking + video" in r.stdout
    with open(tmp_path / "out" / "model.pkl", "rb") as fh:
        b = pickle.load(fh)
    assert type(b["models"]["ridge"]).__module__ == "train"
