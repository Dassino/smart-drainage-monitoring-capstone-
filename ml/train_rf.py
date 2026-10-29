"""
Train Stage 2 (Random Forest) and report how well it works on trials it has never seen.

Run from the repo root after ml/build_dataset.py:

    py ml/train_rf.py data/labelled_readings.csv --events data/trial_events_2026-10-26.csv --floor-new 45.76 45.8

1. Leave-one-trial-out: for each Blockage / Flood trial, a Random Forest is trained on all the other
   trials and then predicts every reading of the held-out one. The report shows, per trial, how many
   readings between onset and end were classified correctly, how many were called Normal, how many
   of the pre-onset readings were called Normal, the class of the first alert (PERSIST readings in a
   row that are not Normal) and the lead time before the first Critical press.
2. A final model is trained on every trial and saved to ml/models/rf_stage2.joblib.
Also writes data/rf_loto_report.csv.
"""
import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score  # noqa: E402
import stage2  # noqa: E402

RAW = ["timestamp", "trial_id", "water_level_cm", "flow_rate_lpm", "mq4_voltage", "mq135_voltage", "phase", "y"]


def forest():
    return RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced_subsample",
                                  random_state=0, n_jobs=-1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labelled")
    ap.add_argument("--events", required=True)
    ap.add_argument("--floor-new", nargs=2, type=float, required=True, metavar=("N1", "N2"))
    ap.add_argument("--out", default="data/rf_loto_report.csv")
    a = ap.parse_args()

    L = pd.read_csv(a.labelled)
    L["timestamp"] = pd.to_datetime(L["timestamp"], utc=True, format="ISO8601")
    L["node_id"] = L["node_id"].astype(int)
    ev = pd.read_csv(a.events)
    ev["occurred_at"] = pd.to_datetime(ev["occurred_at"], utc=True, format="ISO8601")
    depth = stage2.depth_cfg_for_training(a.floor_new)

    D, cols = stage2.joint_features(L[L.node_id == 1][RAW], L[L.node_id == 2][RAW], depth)
    D = D[D["y"].isin(stage2.CLASSES)]
    print(f"{len(D)} readings, {len(cols)} features; classes: {D['y'].value_counts().to_dict()}")

    trials = sorted(t for t in D["trial_id"].unique() if t.startswith(("blockage", "flood")))
    rows, allp = [], []
    for T in trials:
        tr, te = D[D.trial_id != T], D[D.trial_id == T].sort_values("timestamp")
        te = te.assign(p=forest().fit(tr[cols], tr["y"]).predict(te[cols]))
        allp.append(te[["trial_id", "phase", "y", "p"]])
        act, pre = te[te.phase.isin(["rise", "peak"])], te[te.phase == "pre"]
        e = ev[ev.trial_id == T]
        on = e.loc[e.event_type == "onset", "occurred_at"].min()
        crit = e.loc[e.event_type == "critical", "occurred_at"].min()
        run, first, cls = 0, None, None
        for t, p in zip(te["timestamp"], te["p"]):
            run = run + 1 if p != "Normal" else 0
            if run == stage2.PERSIST and t >= on and first is None:
                first, cls = t, p
        rows.append({"trial": T, "true": act["y"].iloc[0], "event_rows": len(act),
                     "correct": round((act.p == act.y).mean(), 2), "called_normal": round((act.p == "Normal").mean(), 2),
                     "pre_rows": len(pre), "pre_normal": round((pre.p == "Normal").mean(), 2) if len(pre) else np.nan,
                     "alert_class": cls, "delay_min": round((first - on).total_seconds() / 60, 1) if first is not None else None,
                     "lead_min": round((crit - first).total_seconds() / 60, 1) if first is not None else None})
    R = pd.DataFrame(rows)
    R.to_csv(a.out, index=False)
    A = pd.concat(allp)
    pos = A[A.phase.isin(["rise", "peak"])]
    print("\nLeave-one-trial-out report:")
    print(R.to_string(index=False))
    print(f"\nreadings between onset and end: {len(pos)}")
    print(f"  classified correctly {(pos.p == pos.y).mean():.0%}, called Normal {(pos.p == 'Normal').mean():.0%}, "
          f"Blockage/Flood mix-up {((pos.p != pos.y) & (pos.p != 'Normal')).mean():.0%}")
    print(f"  pre-onset readings called Normal {(A[A.phase == 'pre'].p == 'Normal').mean():.0%}")
    print("  alert with the right class:", int((R.alert_class == R.true).sum()), "of", len(R))
    print("  lead time >= 5 min:", int((R.lead_min >= 5).sum()), "of", len(R))
    cm = confusion_matrix(pos.y, pos.p, labels=stage2.CLASSES)
    print("\nConfusion matrix, event readings (rows = true, columns = predicted):")
    print(pd.DataFrame(cm, index=stage2.CLASSES, columns=stage2.CLASSES).to_string())

    m = forest().fit(D[cols], D["y"])
    imp = pd.Series(m.feature_importances_, index=cols).sort_values(ascending=False).head(8)
    print("\nMost important features (final model):")
    print(imp.round(3).to_string())
    stage2.MODEL_FILE.parent.mkdir(exist_ok=True)
    joblib.dump({"model": m, "cols": cols, "floor_new": list(a.floor_new), "window": stage2.WINDOW,
                 "long": stage2.LONG, "trials": sorted(D.trial_id.unique().tolist())}, stage2.MODEL_FILE)
    print(f"\nsaved {stage2.MODEL_FILE}")


if __name__ == "__main__":
    main()