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

Check that it reproduces the notebook (run from the repo root):
    py ml/score.py data/sensor_readings_export.csv
"""
import sys
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

MODELS_DIR = Path(__file__).resolve().parent / "models"
SENSORS = {
    1: ["water_level_cm", "flow_rate_lpm", "mq4_voltage", "mq135_voltage"],
    2: ["water_level_cm", "flow_rate_lpm", "mq4_voltage"],     # node 2 has no MQ-135
}
ALL_SENSORS = ["water_level_cm", "flow_rate_lpm", "mq4_voltage", "mq135_voltage"]
REQUIRED = ["water_level_cm", "flow_rate_lpm", "mq4_voltage"]

FETCH_ROWS = 60   # latest readings of the current trial used for live scoring
EXPECTED_ROWS = {1: 9785, 2: 9766}   # rows the notebook used to fit the final models
PERSIST = 6       # consecutive flagged readings (about 50 s) before a reading becomes an alert.
                  # Provisional: to be tuned on the Blockage and Flood trials.


@lru_cache(maxsize=None)
def load(node):
    m = joblib.load(MODELS_DIR / f"iforest_final_node{int(node)}.joblib")
    m["model"].n_jobs = 1          # small batches: threads only add overhead
    return m


def clean(raw):
    d = raw.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    d[ALL_SENSORS] = d[ALL_SENSORS].astype(float).replace(-1, np.nan)
    d.loc[d.water_level_cm > 100, "water_level_cm"] = np.nan
    d.loc[d.flow_rate_lpm > 40, "flow_rate_lpm"] = np.nan
    d.loc[d.mq4_voltage == 0, "mq4_voltage"] = np.nan
    return d.dropna(subset=REQUIRED)


def make_features(d, cols, w):
    """Same as make_features2 in the notebook."""
    d = d.sort_values("timestamp").copy()
    g = d.groupby("trial_id")
    d["water_level_cm"] = g["water_level_cm"].transform(lambda s: s.rolling(5, min_periods=1).median())
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
    d, feats = make_features(clean(raw), SENSORS[int(node)], m["window"])
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


def check(csv_path):
    """The final models were fitted on every Normal row, so the flag rate on that same data
    must equal 100 - percentile (1% for node 1, 5% for node 2) and the row counts must match."""
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    ok = True
    for node in (1, 2):
        m = load(node)
        s = score_frame(node, df[df.node_id == node])
        rate = s["flag"].mean()
        want = 1 - m["pct"] / 100
        rows_ok = len(s) == EXPECTED_ROWS[node]
        rate_ok = abs(rate - want) < 0.002
        ok &= rows_ok and rate_ok
        print(f"node {node}: scored rows {len(s)} (notebook {EXPECTED_ROWS[node]}) "
              f"{'OK' if rows_ok else 'MISMATCH'} | flagged {rate:.2%} (expected {want:.2%}) "
              f"{'OK' if rate_ok else 'MISMATCH'} | threshold {m['thr']:.4f}")
    print("PASS: scorer reproduces the notebook" if ok else "FAIL: scorer does not match the notebook")
    return ok


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: py ml/score.py path/to/sensor_readings_export.csv")
    sys.exit(0 if check(sys.argv[1]) else 1)