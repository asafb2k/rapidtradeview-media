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
    # engagement / reach / post-publication names the first guard missed
    for bad in ("quote_count", "quoteCount", "url_clicks", "profile_clicks", "detail_expands", "rt_count",
                "share_count", "score_24h", "rank", "snapshot_age", "post_age"):
        over["extra_numeric_features"] = [bad]
        with pytest.raises(ValueError):
            T.load_config(None, over)
    # content names that only look similar stay allowed
    for ok in ("is_quote", "image_brightness", "percentage_terms", "vis_brightness", "start_hour"):
        over["extra_numeric_features"] = [ok]
        T.load_config(None, over)
    # feature_columns mappings get the same checks
    over["extra_numeric_features"] = []
    over["feature_columns"] = {"char_len": "detail_expands"}
    with pytest.raises(ValueError):
        T.load_config(None, over)
    over["feature_columns"] = {"char_len": "impressions"}  # the mapped views column
    with pytest.raises(ValueError):
        T.load_config(None, over)
    over["feature_columns"] = {"char_len": "length"}
    T.load_config(None, over)


def test_thread_is_unmapped_by_default_and_warned_when_mapped():
    ex = json.load(open(os.path.join(KIT, "config.example.json"), encoding="utf-8"))
    assert ex["columns"]["thread"] is None
    df = S.make_synthetic(n_authors=20, seed=5, mean_posts=10)
    cfg = T.load_config(None, S.synthetic_config("unused.csv"))
    _, info = T.prepare(df, cfg)
    assert any("'thread' is mapped" in w for w in info["warnings"])
    over = S.synthetic_config("unused.csv")
    over["columns"]["thread"] = None
    _, info = T.prepare(df, T.load_config(None, over))
    assert not any("'thread' is mapped" in w for w in info["warnings"])


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


def test_effects_table_is_not_shrunk_by_the_predictive_penalty(run_synth):
    _, cfg, rep, out = run_synth
    e = rep["effects"]["ridge"]
    assert e["alpha"] == cfg["models"]["effects_alpha"] == 1e-6
    assert e["predictive_ridge_alpha"] > 1  # the CV-chosen penalty is much larger
    bundle = SD.load_bundle(os.path.join(out, "model.pkl"))
    ridge = bundle["models"]["ridge"]
    shrunk = dict(zip(ridge.spec.names, ridge.per_unit()))
    for name in ("media_type=video", "opener=breaking", "media_type=image", "hour_bin=h12-15"):
        assert abs(_effect(rep, name)["per_unit"]) > abs(shrunk[name]), name


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
    prim = js["group_kfold"]["models"][js["primary_model"]]
    macro = f"{prim['pairwise_accuracy_author_macro']:.3f} ({prim['n_authors_macro']})"
    assert "author-macro acc" in md and macro in md  # in the tables
    assert md.split("## Corpus")[0].count("Author-macro") == 1  # and in the headline
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


def test_score_drafts_warns_on_untrained_media_labels(run_synth):
    _, _, _, out = run_synth
    bundle = SD.load_bundle(os.path.join(out, "model.pkl"))
    drafts = [{"name": "photo draft", "text": "BREAKING: $AMD stake raised", "media_type": "photo", "hour_utc": 13},
              {"name": "video draft", "text": "BREAKING: $AMD stake raised", "media_type": "video", "hour_utc": 13}]
    ranked = {r["name"]: r for r in SD.score(bundle, drafts)}
    w = ranked["photo draft"].get("warnings")
    assert w and len(w) == 1 and "'photo'" in w[0] and "never seen" in w[0] and "video" in w[0], w
    assert "warnings" not in ranked["video draft"]
    assert "WARNING photo draft" in SD.render(bundle, list(ranked.values()))


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


# --- wide age window: age adjustment ----------------------------------------------

AGE_EXP = 0.6
CONFOUNDED = ("media_type=video", "opener=breaking", "has_question")


@pytest.fixture(scope="module")
def wide_pair():
    # Same seed, same posts and noise; the twin has every snapshot at exactly 24 h (no age confounding),
    # so its unadjusted estimates are the target the age-adjusted wide-window estimates must hit.
    wide = S.make_synthetic(n_authors=150, seed=0, mean_posts=40, age_window=(12, 36), age_exponent=AGE_EXP)
    fixed = S.make_synthetic(n_authors=150, seed=0, mean_posts=40, age_window=(24, 24), age_exponent=AGE_EXP)
    return wide, fixed


def _effects_ls(df, mode, controls="features", B=0):
    over = S.synthetic_config("unused.csv")
    over["target"] = {"age_tolerance_hours": 12, "age_adjust": mode, "age_adjust_controls": controls}
    over["models"] = {"bootstrap": 100}
    cfg = T.load_config(None, over)
    d, info = T.prepare(df, cfg)
    raw = T.build_raw(d, cfg)
    y, g = d["y"].to_numpy(float), d["author"].to_numpy()
    m = T.make_model("effects_ls", cfg).fit(raw, y, g)
    est = dict(zip(m.spec.names, m.per_unit()))
    ci = {}
    if B:
        draws = m.bootstrap(raw, y, g, B, np.random.default_rng(0), alpha=cfg["models"]["effects_alpha"],
                            y_redraw=info["y_redraw"])
        ci = {n: np.quantile(draws[:, k], [0.025, 0.975]) for k, n in enumerate(m.spec.names)}
    return est, ci, info.get("age_adjustment"), m


def test_age_adjust_removes_age_confounding(wide_pair):
    wide, fixed = wide_pair
    ref, _, _, _ = _effects_ls(fixed, "none")
    raw_est, raw_ci, _, _ = _effects_ls(wide, "none", B=100)
    # unadjusted: videos and BREAKING were seen older (more views), questions younger -> biased
    assert raw_est["media_type=video"] - ref["media_type=video"] > 0.08
    assert raw_est["opener=breaking"] - ref["opener=breaking"] > 0.08
    assert raw_est["has_question"] - ref["has_question"] < -0.05
    assert not raw_ci["media_type=video"][0] <= S.PLANTED["media_type=video"] <= raw_ci["media_type=video"][1]
    for mode in ("loglinear", "spline"):
        est, ci, age, m = _effects_ls(wide, mode, B=100)
        assert not [n for n in m.spec.names if "age" in n and not n.startswith("media_type")]  # never a feature
        for f in CONFOUNDED:
            assert abs(est[f] - ref[f]) < 0.03, (mode, f, est[f], ref[f])
            assert abs(est[f] - S.PLANTED[f]) < 0.12, (mode, f, est[f])
            assert ci[f][0] <= S.PLANTED[f] <= ci[f][1], (mode, f, ci[f])
        lo, hi = age["slope_ci95"]
        assert lo <= AGE_EXP <= hi, (mode, age["slope_per_log_age"], age["slope_ci95"])
        assert age["bootstrap"] == 100 and age["n_authors_with_age_variation"] > 100
    # age alone (no feature controls) absorbs the feature mix into the slope and over-corrects
    est, _, age, _ = _effects_ls(wide, "loglinear", controls="none")
    assert age["slope_ci95"][0] > AGE_EXP + 0.2
    assert est["media_type=video"] - ref["media_type=video"] < -0.05


def test_age_basis():
    age = np.linspace(12, 36, 200)
    ll = T.AgeBasis("loglinear").fit(age)
    assert np.allclose(ll.transform(age)[:, 0], np.log(age))
    sp = T.AgeBasis("spline", 3).fit(age)
    assert sp.transform(age).shape == (200, 3)
    assert np.allclose(np.exp(sp.knots[[0, -1]]), [12, 36])
    # natural spline: linear in log(age) beyond the boundary knots
    out = sp.transform(np.array([40.0, 50, 60, 70]))
    x = np.log([40.0, 50, 60, 70])
    for j in range(3):
        slope = np.diff(out[:, j]) / np.diff(x)
        assert np.allclose(slope, slope[0]), j
    with pytest.raises(ValueError):
        T.AgeBasis("spline", 3).fit(np.full(50, 24.0))


def test_age_adjust_is_off_by_default_and_validated():
    assert T.DEFAULTS["target"]["age_adjust"] == "none"
    ex = json.load(open(os.path.join(KIT, "config.example.json"), encoding="utf-8"))
    assert ex["target"]["age_adjust"] == "none" and ex["models"]["drop_top_authors"] == 0
    df = S.make_synthetic(n_authors=20, seed=5, mean_posts=10)
    cfg = T.load_config(None, S.synthetic_config("unused.csv"))
    d, info = T.prepare(df, cfg)
    assert info["age_adjustment"] is None and "views_age_adjusted" not in d.columns
    med = T.loo_median(d["views"].to_numpy(float), d["author"].to_numpy())
    assert np.allclose(d["y"], np.log1p(d["views"].to_numpy(float)) - np.log1p(med))
    for bad in ({"age_adjust": "quadratic"}, {"age_adjust": "loglinear", "author_median_source": "column"},
                {"age_adjust": "loglinear", "age_adjust_controls": "some"}):
        over = S.synthetic_config("unused.csv")
        over["columns"]["author_median_views"] = "impressions"
        over["target"] = bad
        with pytest.raises(ValueError):
            T.prepare(df, T.load_config(None, over))


@pytest.fixture(scope="module")
def run_wide(tmp_path_factory):
    df = S.make_synthetic(n_authors=60, seed=4, mean_posts=30, age_window=(12, 36), age_exponent=AGE_EXP)
    over = S.synthetic_config("unused.csv")
    over["target"] = {"age_tolerance_hours": 12, "age_adjust": "spline"}
    over["models"] = {"bootstrap": 40, "bootstrap_enet": 0, "text": False, "drop_top_authors": 3,
                      "drop_top_effects": ["opener=breaking", "cashtag_count"]}
    over["validation"] = {"metric_bootstrap": 100, "shuffle_control_repeats": 2, "permutation_repeats": 1}
    cfg = T.load_config(None, over)
    out = tmp_path_factory.mktemp("viral_model_wide")
    return cfg, T.run(cfg, data=df, out_dir=str(out), verbose=False), out


def test_age_adjusted_run_reports_slope_and_scores_drafts_without_age(run_wide):
    cfg, rep, out = run_wide
    ag = rep["age_adjustment"]
    assert ag["method"] == "spline" and ag["basis"]["df"] == 3 and ag["bootstrap"] == 40
    assert ag["slope_ci95"][0] < ag["slope_per_log_age"] < ag["slope_ci95"][1]
    assert any(c["age_hours"] == 24 and abs(c["log_adjustment"]) < 1e-9 for c in ag["curve"])
    assert not [c for c in rep["features"]["linear_columns"] if "age" in c and not c.startswith("media")]
    md = open(os.path.join(out, "report.md"), encoding="utf-8").read()
    assert "## Age adjustment (spline)" in md and "**Age slope**" in md and "bootstrap B = 40" in md
    assert rep["target"]["age_adjust"] == "spline" and "f(age)" in rep["target"]["definition"]
    bundle = SD.load_bundle(os.path.join(out, "model.pkl"))
    ranked = SD.score(bundle, [{"name": "a", "text": "BREAKING: $AMD stake raised", "media_type": "video",
                                "hour_utc": 13},
                               {"name": "b", "text": "$AMD stake raised. Thoughts?", "media_type": "none",
                                "hour_utc": 22}])
    assert ranked[0]["name"] == "a"


def test_drop_top_authors_reestimates_named_effects(run_wide):
    cfg, rep, out = run_wide
    e = rep["effects"]["ridge"]
    rows = {r["feature"]: r for r in e["drop_top_authors"]}
    assert set(rows) == {"opener=breaking", "cashtag_count"}
    d = rep["_prepared"]
    raw = T.build_raw(d, cfg)
    brk = (raw["opener"] == "breaking").groupby(d["author"]).sum().sort_values(ascending=False)
    r = rows["opener=breaking"]
    full = next(x for x in e["rows"] if x["feature"] == "opener=breaking")
    assert r["full"]["per_unit"] == full["per_unit"] and r["k"] == 3 and r["bootstrap"] == 40
    assert [a["posts_at_level"] for a in r["dropped_authors"]] == brk.head(3).tolist()
    dropped = [a["author"] for a in r["dropped_authors"]]
    assert r["posts_removed"] == int(d["author"].isin(dropped).sum())
    assert r["n_authors_nonzero"] == full["n_authors_nonzero"] - 3
    assert r["n_posts_nonzero"] == full["n_posts_nonzero"] - int(brk.head(3).sum())
    assert r["ci95"][0] <= r["per_unit"] <= r["ci95"][1]
    md = open(os.path.join(out, "report.md"), encoding="utf-8").read()
    assert "### Without the top 3 authors at each level" in md
    final = SD.load_bundle(os.path.join(out, "model.pkl"))["models"]["ridge"]
    with pytest.raises(ValueError):
        T.drop_top_authors_effects(final, e["rows"], raw, d["y"].to_numpy(float), d["author"].to_numpy(),
                                   ["opener=nope"], 3, 0, 1e-6, np.random.default_rng(0))


def test_effects_model_has_its_own_validation_and_control(run_synth):
    _, _, rep, out = run_synth
    e = rep["effects"]["ridge"]
    v = e["validation"]
    assert v["group_kfold"]["pairwise_accuracy"] > 0.58 and v["group_kfold"]["n_pairs"] > 10000
    sc = v["shuffled_control"]
    assert sc["n"] == 5 and abs(sc["mean"] - 0.5) < 0.03
    assert v["group_kfold"]["pairwise_accuracy"] - sc["max"] > 0.05
    assert all("n_authors_nonzero" in r for r in e["rows"])
    md = open(os.path.join(out, "report.md"), encoding="utf-8").read()
    assert "Effects model's own within-author pairwise accuracy" in md
    assert "bootstrap B = 100" in md and "N authors nonzero" in md


def test_cli_age_adjust_and_drop_top_authors(tmp_path):
    py = sys.executable
    data, conf = tmp_path / "syn.csv", tmp_path / "syn_config.json"
    subprocess.run([py, os.path.join(KIT, "synthetic.py"), "--out", str(data), "--config-out", str(conf),
                    "--authors", "40", "--age-window", "12", "36", "--age-exponent", "0.6"], check=True, cwd=tmp_path)
    assert json.load(open(conf, encoding="utf-8"))["target"]["age_tolerance_hours"] == 12
    subprocess.run([py, os.path.join(KIT, "train.py"), "--config", str(conf), "--out", str(tmp_path / "out"),
                    "--quick", "--age-adjust", "loglinear", "--drop-top-authors", "2", "--drop-effect",
                    "media_type=video"], check=True, cwd=tmp_path, capture_output=True, text=True)
    js = json.load(open(tmp_path / "out" / "report.json", encoding="utf-8"))
    assert js["age_adjustment"]["method"] == "loglinear" and js["age_adjustment"]["bootstrap"] == 30
    assert [r["feature"] for r in js["effects"]["ridge"]["drop_top_authors"]] == ["media_type=video"]


def test_effects_bootstrap_refits_the_age_curve(wide_pair):
    wide, _ = wide_pair
    over = S.synthetic_config("unused.csv")
    over["target"] = {"age_tolerance_hours": 12, "age_adjust": "loglinear"}
    cfg = T.load_config(None, over)
    d, info = T.prepare(wide, cfg)
    raw = T.build_raw(d, cfg)
    y, g = d["y"].to_numpy(float), d["author"].to_numpy()
    redraw = info["y_redraw"]
    assert np.allclose(redraw(np.arange(len(d))), y)  # all rows -> the full-sample target exactly
    m = T.make_model("effects_ls", cfg).fit(raw, y, g)
    ea = cfg["models"]["effects_alpha"]
    fixed = m.bootstrap(raw, y, g, 200, np.random.default_rng(1), alpha=ea)
    refit = m.bootstrap(raw, y, g, 200, np.random.default_rng(1), alpha=ea, y_redraw=redraw)
    ratio = {n: np.std(refit[:, k]) / np.std(fixed[:, k]) for k, n in enumerate(m.spec.names)}
    assert ratio["media_type=video"] > 1.04, ratio  # seen 6 h older: correlates with age, wider CI (~1.10)
    for n in ("media_type=image", "cashtag_count"):  # age-neutral: same spread
        assert 0.97 < ratio[n] < 1.03, (n, ratio[n])
    df0 = S.make_synthetic(n_authors=20, seed=5, mean_posts=10)
    assert T.prepare(df0, T.load_config(None, S.synthetic_config("unused.csv")))[1]["y_redraw"] is None


def test_drop_top_authors_flags_are_validated(tmp_path):
    df = S.make_synthetic(n_authors=30, seed=2, mean_posts=20)
    over = S.synthetic_config("unused.csv")
    over["models"] = {"bootstrap": 0, "bootstrap_enet": 0, "text": False, "drop_top_effects": ["opener=breaking"]}
    with pytest.raises(ValueError, match="drop_top_authors"):
        T.run(T.load_config(None, over), data=df, out_dir=str(tmp_path / "a"), verbose=False)
    over["models"].update({"drop_top_effects": [], "drop_top_authors": 2})
    over["validation"] = {"metric_bootstrap": 50, "shuffle_control": False, "permutation_repeats": 1}
    rep = T.run(T.load_config(None, over), data=df, out_dir=str(tmp_path / "b"), verbose=False)
    assert "drop_top_authors" not in rep["effects"]["ridge"]
    assert any("did nothing" in w for w in rep["warnings"])
    py = sys.executable
    data, conf = tmp_path / "syn.csv", tmp_path / "syn_config.json"
    subprocess.run([py, os.path.join(KIT, "synthetic.py"), "--out", str(data), "--config-out", str(conf),
                    "--authors", "20"], check=True, cwd=tmp_path)
    r = subprocess.run([py, os.path.join(KIT, "train.py"), "--config", str(conf), "--out", str(tmp_path / "c"),
                        "--quick", "--drop-effect", "opener=breaking"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode != 0 and "--drop-top-authors" in r.stderr
