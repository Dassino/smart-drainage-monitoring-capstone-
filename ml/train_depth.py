"""
Retrain the per-node Isolation Forest on DEPTH (D_floor - distance) so that readings from the old
and the new sensor mounting line up. Same recipe as the notebook: Normal data only, StandardScaler,
the saved models' own settings, threshold = the same percentile of the training scores (p99 node 1,
p95 node 2), window of 7 readings, de-spiked level.

Run from the repo root, giving every Normal export (old and new) and the new D_floor values:

    py ml/train_depth.py data/sensor_readings_export.csv data/normal_d3.csv --floor-new 58.4 57.9

  --floor-new N1 N2   empty-channel sensor reading at the NEW mounting, node 1 then node 2 (cm)
  --floor-old N1 N2   same for the OLD mounting (default: d_floor_old in ml/mounting.json, else 22.67 22.67)
  --change-at TIME    when the new mounting starts. Default: the first reading of baseline_d3_check.
  --exclude IDS       extra trial IDs to leave out
  --exclude-prefix P  every trial whose ID starts with one of these is left out
                      (default: setup pilot rest, so setup_d3, pilot_01, pilot_02, rest_d3 ... never train)
  --activate          also write ml/mounting.json in depth mode, so the dashboard uses the new models

The CSV files must contain Normal rows only (the script stops if it sees another label).
Writes ml/models/iforest_depth_node1.joblib and iforest_depth_node2.joblib.
"""
import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score  # noqa: E402

HERE = Path(__file__).resolve().parent
OLD_MODEL = "iforest_final_node{}.joblib"
NEW_MODEL = "iforest_depth_node{}.joblib"
CHECK_TRIAL = "baseline_d3_check"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--floor-new", nargs=2, type=float, required=True, metavar=("N1", "N2"))
    ap.add_argument("--floor-old", nargs=2, type=float, metavar=("N1", "N2"))
    ap.add_argument("--change-at")
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--exclude-prefix", nargs="*", default=["setup", "pilot", "rest"])
    ap.add_argument("--activate", action="store_true")
    a = ap.parse_args()

    df = pd.concat([pd.read_csv(p) for p in a.csv], ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df["node_id"] = df["node_id"].astype(int)
    if "label" in df and (df["label"].dropna() != "Normal").any():
        bad = sorted(df.loc[df["label"] != "Normal", "label"].dropna().unique())
        sys.exit(f"These files contain labels other than Normal: {bad}. Export Normal rows only.")
    skip = df["trial_id"].isin(a.exclude) | df["trial_id"].str.startswith(tuple(a.exclude_prefix))
    if skip.any():
        print("Left out:", ", ".join(f"{t} ({n} rows)" for t, n in df.loc[skip, "trial_id"].value_counts().items()))
    df = df[~skip]
    df = df.drop_duplicates(subset=["node_id", "timestamp"])

    if a.change_at:
        change_at = pd.Timestamp(a.change_at)
    else:
        t = df.loc[df["trial_id"] == CHECK_TRIAL, "timestamp"]
        if t.empty:
            sys.exit(f"No rows for trial {CHECK_TRIAL}. Include its export or pass --change-at.")
        change_at = t.min()
    if change_at.tzinfo is None:
        change_at = change_at.tz_localize("Africa/Nairobi")

    old_cfg = score.read_config()
    floor_old = a.floor_old or [float(old_cfg.get("d_floor_old", {}).get(str(n), 22.67)) for n in (1, 2)]
    cfg = {"old": {1: floor_old[0], 2: floor_old[1]},
           "new": {1: a.floor_new[0], 2: a.floor_new[1]},
           "change_at": change_at.tz_convert("UTC")}
    print(f"D_floor old {floor_old} cm, new {a.floor_new} cm, new mounting from {cfg['change_at']}")

    for node in (1, 2):
        old = joblib.load(HERE / "models" / OLD_MODEL.format(node))
        raw = df[df.node_id == node]
        before = raw[raw.timestamp < cfg["change_at"]]
        if len(before):
            p99 = before["water_level_cm"].where(before["water_level_cm"].between(0, 100)).quantile(0.99)
            print(f"node {node}: old-mounting distance, 99th percentile {p99:.2f} cm (D_floor old {floor_old[node - 1]})")
        d, feats = score.make_features(score.clean(raw, node, depth=cfg), score.sensors(node, "depth_cm"),
                                       old["window"], level="depth_cm")
        scaler = StandardScaler().fit(d[feats])
        X = scaler.transform(d[feats])
        model = clone(old["model"]).fit(X)
        s = -model.score_samples(X)
        thr = float(np.percentile(s, old["pct"]))
        flag = s > thr
        after = (d["timestamp"] >= cfg["change_at"]).to_numpy()
        print(f"node {node}: trained on {len(d)} rows ({after.sum()} at the new mounting), "
              f"threshold p{old['pct']} = {thr:.4f}, flagged {flag.mean():.2%} overall, "
              f"{flag[~after].mean() if (~after).any() else float('nan'):.2%} old mounting, "
              f"{flag[after].mean() if after.any() else float('nan'):.2%} new mounting")
        joblib.dump({"scaler": scaler, "model": model, "thr": thr, "feats": feats, "pct": old["pct"],
                     "window": old["window"], "trials": sorted(d["trial_id"].unique().tolist()),
                     "d_floor_old": floor_old[node - 1], "d_floor_new": a.floor_new[node - 1],
                     "change_at": str(cfg["change_at"])},
                    HERE / "models" / NEW_MODEL.format(node))
        print(f"node {node}: saved ml/models/{NEW_MODEL.format(node)}")

    if a.activate:
        conf = {"mode": "depth",
                "d_floor_old": {"1": floor_old[0], "2": floor_old[1]},
                "d_floor_new": {"1": a.floor_new[0], "2": a.floor_new[1]},
                "change_at": str(cfg["change_at"])}
        (HERE / "mounting.json").write_text(json.dumps(conf, indent=2) + "\n")
        print("ml/mounting.json set to depth mode. Restart the dashboard backend (py backend/dashboard/app.py).")
    else:
        print("Models saved but not active. Add --activate (or edit ml/mounting.json) to use them.")


if __name__ == "__main__":
    main()