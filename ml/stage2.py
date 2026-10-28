"""
Stage 2 of the pipeline: a Random Forest that names the problem (Normal, Blockage or Flood).

It uses both nodes together. For each node the features are the ones the Isolation Forest uses
(depth, flow, MQ-4 and, on node 1, MQ-135, each with a 7-reading rolling mean, std and change)
plus one extra: the change in depth over the last 24 readings (about 3.4 minutes), which picks up
slow rises. Node 2's readings are matched to node 1's by time (within 10 s).

Used by ml/train_rf.py (training and the leave-one-trial-out report), ml/eval_pipeline.py and the
dashboard (score_latest).
"""
from collections import Counter
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import score

HERE = Path(__file__).resolve().parent
MODEL_FILE = HERE / "models" / "rf_stage2.joblib"
WINDOW = 7          # same rolling window as the Isolation Forest
LONG = 24           # readings for the slow-rise feature
MATCH = pd.Timedelta(seconds=10)
CLASSES = ["Normal", "Blockage", "Flood"]
PERSIST = score.PERSIST
FETCH_ROWS = 80     # latest readings of each node used for live scoring (the features need about 35)


def depth_cfg_for_training(floor_new):
    """Every reading is treated as new-mounting: depth = D_floor - distance."""
    return {"old": {1: floor_new[0], 2: floor_new[1]}, "new": {1: floor_new[0], 2: floor_new[1]},
            "change_at": pd.Timestamp("2000-01-01", tz="UTC")}


def node_features(raw, node, depth):
    """Features of one node. raw has timestamp, trial_id and the four sensor columns (plus anything else, kept)."""
    d = score.clean(raw, node, depth=depth)
    d, feats = score.make_features(d, score.sensors(node, "depth_cm"), WINDOW, level="depth_cm")
    d["depth_long"] = d["depth_cm"] - d.groupby("trial_id")["depth_cm"].shift(LONG)
    feats = feats + ["depth_long"]
    d = d.dropna(subset=["depth_long"])
    ren = {c: f"n{node}_{c}" for c in feats}
    return d.rename(columns=ren), [ren[c] for c in feats]


def joint_features(raw1, raw2, depth, keep=("phase", "y")):
    """One row per node 1 reading, with node 1 and node 2 features side by side."""
    d1, f1 = node_features(raw1, 1, depth)
    d2, f2 = node_features(raw2, 2, depth)
    keep = [c for c in keep if c in d1.columns]
    out = pd.merge_asof(d1[["timestamp", "trial_id"] + keep + f1].sort_values("timestamp"),
                        d2[["timestamp", "trial_id"] + f2].sort_values("timestamp"),
                        on="timestamp", by="trial_id", tolerance=MATCH, direction="nearest")
    cols = f1 + f2
    return out.dropna(subset=cols), cols


@lru_cache(maxsize=1)
def load():
    return joblib.load(MODEL_FILE)


def score_latest(raw1, raw2, m=None):
    """Diagnosis from the newest readings of both nodes.
    status: paused | warming_up | ok.  When ok: label (class of the newest reading), alert (PERSIST readings in a row
    that are not Normal), class (the most frequent non-Normal prediction of the last PERSIST readings, when alerting),
    streak and the class probabilities of the newest reading."""
    if score.MODE != "depth":
        return {"status": "paused", "label": None, "alert": False, "class": None, "proba": None, "streak": 0,
                "persist": PERSIST}
    m = m or load()
    d, cols = joint_features(raw1, raw2, score.DEPTH)
    if d.empty:
        return {"status": "warming_up", "label": None, "alert": False, "class": None, "proba": None, "streak": 0,
                "persist": PERSIST}
    d = d.sort_values("timestamp")
    X = d[m["cols"]]
    pred = m["model"].predict(X)
    proba = m["model"].predict_proba(X.iloc[[-1]])[0]
    streak = 0
    for p in pred[::-1]:
        if p == "Normal":
            break
        streak += 1
    alert = streak >= PERSIST
    votes = Counter(p for p in pred[-PERSIST:] if p != "Normal")
    return {"status": "ok", "label": str(pred[-1]), "alert": alert,
            "class": votes.most_common(1)[0][0] if alert and votes else None,
            "proba": {str(c): float(p) for c, p in zip(m["model"].classes_, proba)},
            "streak": streak, "persist": PERSIST}