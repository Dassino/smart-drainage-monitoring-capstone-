"""
Anomaly scoring for the Smart Drainage Monitoring system (Stage 1: Isolation Forest).

Uses the final per-node models trained in ml/01_isolation_forest.ipynb and repeats the
notebook's preprocessing exactly:
  1. -1 means "no reading"  -> missing
  2. physically impossible values -> missing (level > 100 cm, flow > 40 L/min, MQ-4 == 0)
  3. drop rows with a missing level, flow or MQ-4 value
  4. de-spike the water level with a trailing median of 5 readings (inside each trial_id)
  5. rolling mean / std / change over W readings (inside each trial_id)
Score = -score_samples(); a reading is flagged when score > the model's saved threshold.

Mounting modes (ml/mounting.json):
  legacy  raw sensor distance, the day 1 and day 2 models (iforest_final_node*.joblib)
  paused  the live detector is switched off (sensors are being remounted); replays still use the legacy models
  depth   depth = D_floor - distance, models retrained on depth (iforest_depth_node*.joblib).
          Readings before change_at use d_floor_old, readings from change_at on use d_floor_new.

Check that it reproduces the notebook (legacy mode, run from the repo root):
    py ml/score.py data/sensor_readings_export.csv
In depth mode pass the same CSV files that were given to ml/train_depth.py.
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
MODELS_DIR = HERE / "models"
CONFIG_PATH = HERE / "mounting.json"


def read_config():
    cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    cfg.setdefault("mode", "legacy")
    if cfg["mode"] not in ("legacy", "paused", "depth"):
        raise ValueError(f"mounting.json: mode must be legacy, paused or depth, not {cfg['mode']!r}")
    return cfg


def depth_settings(cfg):
    """(floor_old, floor_new, change_at) as used by clean(); None unless the mode is depth."""
    if cfg["mode"] != "depth":
        return None
    change_at = pd.Timestamp(cfg["change_at"])
    change_at = change_at.tz_localize("Africa/Nairobi") if change_at.tzinfo is None else change_at
    return {"old": {int(k): float(v) for k, v in cfg["d_floor_old"].items()},
            "new": {int(k): float(v) for k, v in cfg["d_floor_new"].items()},
            "change_at": change_at.tz_convert("UTC")}


CONFIG = read_config()
MODE = CONFIG["mode"]
DEPTH = depth_settings(CONFIG)
LEVEL = "depth_cm" if DEPTH else "water_level_cm"            # the level column the model sees
MODEL_PREFIX = "iforest_depth" if DEPTH else "iforest_final"


def sensors(node, level=None):
    level = level or LEVEL
    return [level, "flow_rate_lpm", "mq4_voltage"] + (["mq135_voltage"] if int(node) == 1 else [])   # node 2 has no MQ-135


SENSORS = {1: sensors(1), 2: sensors(2)}
ALL_SENSORS = ["water_level_cm", "flow_rate_lpm", "mq4_voltage", "mq135_voltage"]
REQUIRED = ["water_level_cm", "flow_rate_lpm", "mq4_voltage"]

FETCH_ROWS = 60   # latest readings of the current trial used for live scoring
EXPECTED_ROWS = {1: 9785, 2: 9766}   # rows the notebook used to fit the final models
WARMUP_ROWS = 12  # readings a trial needs before its first score (7-reading window + 5-reading median)
PERSIST = 6       # consecutive flagged readings (about 50 s) before a reading becomes an alert.
                  # Provisional: to be tuned on the Blockage and Flood trials.


def model_file(node):
    return f"{MODEL_PREFIX}_node{int(node)}.joblib"


@lru_cache(maxsize=None)
def load(node):
    m = joblib.load(MODELS_DIR / model_file(node))
    m["model"].n_jobs = 1          # small batches: threads only add overhead
    return m


MAX_DISTANCE_CM = 100   # a reading further than this is treated as missing


def clean(raw, node, depth=None):
    """depth: the settings from depth_settings(); defaults to the current mounting.json."""
    depth = DEPTH if depth is None else depth
    d = raw.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    d[ALL_SENSORS] = d[ALL_SENSORS].astype(float).replace(-1, np.nan)
    d.loc[d.water_level_cm > MAX_DISTANCE_CM, "water_level_cm"] = np.nan
    d.loc[d.flow_rate_lpm > 40, "flow_rate_lpm"] = np.nan
    d.loc[d.mq4_voltage == 0, "mq4_voltage"] = np.nan
    d = d.dropna(subset=REQUIRED)
    if depth:
        floor = np.where(d["timestamp"] >= depth["change_at"], depth["new"][int(node)], depth["old"][int(node)])
        d["depth_cm"] = floor - d["water_level_cm"]
    return d


def make_features(d, cols, w, level=None):
    """Same as make_features2 in the notebook (the level column is de-spiked first)."""
    level = level or LEVEL
    d = d.sort_values("timestamp").copy()
    g = d.groupby("trial_id")
    d[level] = g[level].transform(lambda s: s.rolling(5, min_periods=1).median())
    g = d.groupby("trial_id")
    feats = []
    for c in cols:
        d[f"{c}_mean"] = g[c].transform(lambda s: s.rolling(w).mean())
        d[f"{c}_std"] = g[c].transform(lambda s: s.rolling(w).std())
        d[f"{c}_chg"] = g[c].transform(lambda s: s - s.shift(w - 1))
        feats += [c, f"{c}_mean", f"{c}_std", f"{c}_chg"]
    return d.dropna(subset=feats), feats


def score_frame(node, raw):
    """raw: readings of ONE node with columns timestamp, trial_id and the four sensor columns."""
    m = load(node)
    d, feats = make_features(clean(raw, node), sensors(node), m["window"])
    if feats != m["feats"]:
        raise ValueError(f"feature mismatch for node {node}: {feats} != {m['feats']}")
    if d.empty:
        return d.assign(score=[], flag=[])[["timestamp", "trial_id", "score", "flag"]]
    d["score"] = -m["model"].score_samples(m["scaler"].transform(d[feats]))
    d["flag"] = d["score"] > m["thr"]
    return d[["timestamp", "trial_id", "score", "flag"]]


def assess(node, raw):
    """Live status of one node from its latest readings (newest rows of the current trial)."""
    m = load(node)
    out = {"threshold": float(m["thr"]), "percentile": m["pct"], "persist": PERSIST}
    if MODE == "paused":
        out.update(status="paused", score=None, flag=None, streak=0)
        return out
    s = score_frame(node, raw)
    if s.empty:
        out.update(status="warming_up", score=None, flag=None, streak=0)
        return out
    streak = 0
    for f in s["flag"].iloc[::-1]:
        if not f:
            break
        streak += 1
    last_flag = bool(s["flag"].iloc[-1])
    out.update(
        status="alert" if streak >= PERSIST else "anomalous" if last_flag else "normal",
        score=float(s["score"].iloc[-1]),
        flag=last_flag,
        streak=streak,
        latest_row_scored=bool(s["timestamp"].iloc[-1] == pd.to_datetime(raw["timestamp"], utc=True).max()),
    )
    return out


def detail(node, raw, top=5):
    """assess() plus the score history and the features furthest from Normal on the latest reading.

    The feature ranking is each feature's distance from the Normal average in standard deviations
    (the scaler fitted on the training data). It is a guide to which signals look least normal,
    not an exact explanation of the Isolation Forest's decision.
    """
    out = assess(node, raw)
    out.update(series=[], features=[])
    if out["status"] == "paused":
        return out
    m = load(node)
    d, feats = make_features(clean(raw, node), sensors(node), m["window"])
    if d.empty:
        return out
    X = d[feats]
    d = d.assign(score=-m["model"].score_samples(m["scaler"].transform(X)))
    d["flag"] = d["score"] > m["thr"]
    ages = d["age_s"] if "age_s" in d else pd.Series(np.nan, index=d.index)
    out["series"] = [
        {"age_s": None if pd.isna(a) else float(a), "score": float(s), "flag": bool(f)}
        for a, s, f in zip(ages, d["score"], d["flag"])
    ]
    last = X.iloc[-1].to_numpy()
    z = (last - m["scaler"].mean_) / m["scaler"].scale_
    for i in np.argsort(-np.abs(z))[:top]:
        out["features"].append({"name": feats[i], "value": float(last[i]),
                                "normal": float(m["scaler"].mean_[i]), "z": float(z[i])})
    return out


def check(csv_paths):
    """The final models were fitted on every training row, so the flag rate on that same data
    must equal 100 - percentile (1% for node 1, 5% for node 2) and the row counts must match.
    Legacy mode: the day 1 and day 2 Normal export. Depth mode: the CSV files given to train_depth.py."""
    df = pd.concat([pd.read_csv(p) for p in csv_paths], ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    ok = True
    for node in (1, 2):
        m = load(node)
        rows = df[df.node_id == node]
        if DEPTH:
            rows = rows[rows.trial_id.isin(m["trials"])]
        s = score_frame(node, rows)
        rate = s["flag"].mean()
        want = 1 - m["pct"] / 100
        expected = int(m["scaler"].n_samples_seen_) if DEPTH else EXPECTED_ROWS[node]
        rows_ok = len(s) == expected
        rate_ok = abs(rate - want) < 0.002
        ok &= rows_ok and rate_ok
        print(f"node {node}: scored rows {len(s)} (training {expected}) "
              f"{'OK' if rows_ok else 'MISMATCH'} | flagged {rate:.2%} (expected {want:.2%}) "
              f"{'OK' if rate_ok else 'MISMATCH'} | threshold {m['thr']:.4f}")
    print("PASS: scorer reproduces the training run" if ok else "FAIL: scorer does not match the training run")
    return ok


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: py ml/score.py path/to/normal_export.csv [more.csv ...]")
    print(f"mode: {MODE}")
    sys.exit(0 if check(sys.argv[1:]) else 1)
