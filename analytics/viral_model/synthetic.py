"""Synthetic X-post dataset with a planted within-author effect, for the tests and a dry run.

    python synthetic.py --out synthetic_posts.csv --config-out synthetic_config.json
    python train.py --config synthetic_config.json

Generative story (all effects in natural-log views, within author):
  log views_24h = author baseline (0.85 * ln followers + noise)  + PLANTED . features  + N(0, NOISE_SD)
Authors differ in style (big accounts use BREAKING more and ask fewer questions), so raw views mix
author size with format; the within-author target has to undo that. Columns use different names
from the kit roles on purpose, so the config column map is exercised.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

PLANTED = {
    "media_type=video": 0.50,
    "media_type=image": 0.25,
    "opener=breaking": 0.40,
    "has_question": -0.30,
    "cashtag_count": 0.10,   # per cashtag (0-3)
    "hour_bin=h12-15": 0.20,  # posted 12:00-15:59 UTC
}
NULL_FEATURES = ["hashtag_count", "emoji_count", "link_present", "poll"]
NOISE_SD = 0.8
ER_QUESTION_EFFECT = 0.30  # questions raise engagement rate (log ER), within author

TICKERS = ["NVDA", "AAPL", "TSLA", "AMD", "MSFT", "META", "AMZN", "SPY", "QQQ", "PLTR", "SMCI", "COIN"]
BODIES = [
    "{t} beats on revenue, guidance raised for next quarter",
    "{t} insider bought shares this week according to the latest filing",
    "Watching {t} into the close, volume is picking up",
    "{t} gap up after earnings, analysts move targets",
    "Senator disclosed a purchase of {t} last month",
    "{t} breaks resistance, momentum names leading today",
    "Fund raised its {t} stake in the latest 13F",
    "{t} options flow is heavy on calls today",
]
EMOJIS = ["\U0001F680", "\U0001F525", "\U0001F4C8", "\U0001F6A8", "✅"]


def make_synthetic(n_authors: int = 120, seed: int = 0, mean_posts: int = 40, weeks: int = 16,
                   effects: dict | None = None) -> pd.DataFrame:
    eff = dict(PLANTED, **(effects or {}))
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-06-01", tz="UTC")
    rows = []
    pid = 0
    for a in range(n_authors):
        log10_f = rng.uniform(1.3, 6.0)
        followers = int(10 ** log10_f)
        base = 0.85 * np.log(followers) + rng.normal(0, 0.5)
        big = (log10_f - 1.3) / 4.7  # 0..1
        p_video, p_image = rng.beta(2, 5), rng.beta(2, 3)
        p_break = np.clip(0.05 + 0.35 * big + rng.normal(0, 0.05), 0.01, 0.6)
        p_question = np.clip(0.35 - 0.25 * big + rng.normal(0, 0.05), 0.02, 0.6)
        cash_rate = rng.uniform(0.3, 2.0)
        p_emoji, p_hash, p_link = rng.uniform(0.05, 0.7), rng.uniform(0.05, 0.6), rng.uniform(0.05, 0.5)
        pref_hour = rng.integers(0, 24)
        er_base = rng.normal(np.log(0.02), 0.4)
        found_via = "panel" if rng.random() < 0.6 else "search"
        n_posts = 3 if a % 15 == 0 else max(5, int(rng.poisson(mean_posts)))
        for _ in range(n_posts):
            pid += 1
            created = start + pd.Timedelta(minutes=int(rng.integers(0, weeks * 7 * 24 * 60)))
            hour = int((pref_hour + rng.normal(0, 4)) % 24)
            created = created.normalize() + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 60)))
            u = rng.random()
            media = "video" if u < p_video else ("image" if u < p_video + p_image * (1 - p_video) else "none")
            breaking = rng.random() < p_break
            just_in = (not breaking) and rng.random() < 0.08
            question = rng.random() < p_question
            n_cash = int(min(3, rng.poisson(cash_rate)))
            n_hash = int(min(3, rng.poisson(0.8))) if rng.random() < p_hash else 0
            emoji = rng.random() < p_emoji
            link = rng.random() < p_link
            poll = rng.random() < 0.03
            tick = list(rng.choice(TICKERS, size=max(1, n_cash), replace=False))
            body = BODIES[rng.integers(0, len(BODIES))].format(t=tick[0])
            if n_cash:
                body = body.replace(tick[0], "$" + tick[0], 1)
                if n_cash > 1:
                    body += " also " + " ".join("$" + t for t in tick[1:n_cash])
            if rng.random() < 0.5:
                body += f" up {rng.integers(1, 30)}% to ${rng.integers(10, 900)}"
            text = ("BREAKING: " if breaking else "JUST IN: " if just_in else "") + body
            if rng.random() < 0.3:
                text = text.replace(", ", ".\n\n", 1).replace(" after ", ".\n\nAfter ", 1)
            if question:
                text += " What is your take?"
            if n_hash:
                text += "\n" + " ".join(f"#{w}" for w in ["stocks", "investing", "trading"][:n_hash])
            if emoji:
                text = (EMOJIS[rng.integers(0, len(EMOJIS))] + " " + text) if rng.random() < 0.5 else (
                    text + " " + EMOJIS[rng.integers(0, len(EMOJIS))])
            if link:
                text += " https://example.com/x" + str(pid)
            effect = (eff["media_type=video"] * (media == "video") + eff["media_type=image"] * (media == "image")
                      + eff["opener=breaking"] * breaking + eff["has_question"] * question
                      + eff["cashtag_count"] * n_cash + eff["hour_bin=h12-15"] * (12 <= hour <= 15))
            log_v24 = base + effect + rng.normal(0, NOISE_SD)
            v24 = float(np.expm1(max(log_v24, 0.0)))
            log_er = er_base + ER_QUESTION_EFFECT * question + rng.normal(0, 0.5)
            er = float(np.exp(log_er))
            # snapshots: most posts have one near 24 h; some also have an early one; some only a late one
            r = rng.random()
            ages = [rng.uniform(21.5, 26.5)]
            if r < 0.10:
                ages.append(rng.uniform(2, 8))
            elif r < 0.15:
                ages = [rng.uniform(40, 70)]
            for age in ages:
                views = v24 * (age / 24.0) ** 0.3
                eng = views * er
                rows.append({
                    "post_id": f"p{pid}",
                    "post_url": f"https://x.com/acct{a}/status/{pid}",
                    "username": f"acct{a}",
                    "full_text": text,
                    "created_at": created.isoformat(),
                    "snapshot_utc": (created + pd.Timedelta(hours=float(age))).isoformat(),
                    "age_hours": round(float(age), 3),
                    "impressions": int(round(views)),
                    "favorite_count": int(round(eng * 0.7)),
                    "retweet_count": int(round(eng * 0.15)),
                    "reply_count": int(round(eng * 0.1)),
                    "quote_count": int(round(eng * 0.02)),
                    "bookmark_count": int(round(eng * 0.03)),
                    "followers_count": followers,
                    "media": media,
                    "is_poll": poll,
                    "is_thread": rng.random() < 0.05,
                    "is_quote_tweet": rng.random() < 0.1,
                    "found_via": found_via,
                    "vis_brightness": float(rng.uniform(0, 1)) if media != "none" and rng.random() < 0.5 else np.nan,
                })
    return pd.DataFrame(rows)


def synthetic_config(data_path: str, output_dir: str = "out_synthetic") -> dict:
    return {
        "data_path": data_path,
        "output_dir": output_dir,
        "columns": {
            "id": "post_id", "url": "post_url", "author": "username", "text": "full_text",
            "created_at": "created_at", "snapshot_utc": "snapshot_utc", "age_hours": "age_hours",
            "views": "impressions", "likes": "favorite_count", "reposts": "retweet_count",
            "replies": "reply_count", "quotes": "quote_count", "bookmarks": "bookmark_count",
            "followers": "followers_count", "found_via": "found_via", "media_type": "media",
            "poll": "is_poll", "thread": "is_thread", "is_quote": "is_quote_tweet",
        },
        "extra_numeric_features": ["vis_brightness"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="synthetic_posts.csv")
    ap.add_argument("--config-out", default="synthetic_config.json")
    ap.add_argument("--authors", type=int, default=120)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    df = make_synthetic(n_authors=a.authors, seed=a.seed)
    df.to_csv(a.out, index=False)
    with open(a.config_out, "w", encoding="utf-8") as fh:
        json.dump(synthetic_config(a.out), fh, indent=2)
    print(f"wrote {len(df)} snapshot rows ({df['post_id'].nunique()} posts, {df['username'].nunique()} authors) "
          f"to {a.out}; config {a.config_out}")


if __name__ == "__main__":
    main()
