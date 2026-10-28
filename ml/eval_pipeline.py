"""
Evaluate the whole pipeline the way the dashboard runs it, on trials it has never seen.

    py ml/eval_pipeline.py data/labelled_readings.csv --events data/trial_events_2026-10-26.csv --floor-new 45.76 45.8

Leave-one-trial-out. For each Blockage / Flood trial the two stages are trained WITHOUT it:
  Stage 1  Isolation Forest on node 1 (Normal readings of every other trial, new-mounting data only,
           alarm threshold at --pct, settings cloned from the saved notebook model). An alert is
           PERSIST readings in a row above the threshold.
  Stage 2  Random Forest on both nodes. When Stage 1 alerts, the class is the most frequent non-Normal
           prediction over the last PERSIST readings (Blockage or Flood). If all of them are Normal it is "Unclear".
Reported per trial: the first alert at or after the onset, the class, the delay after the onset, the lead time
before the first Critical press, and the Stage 1 alerts raised BEFORE the onset (false alerts).
Writes data/pipeline_loto_report.csv.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score  # noqa: E402
import stage2  # noqa: E402

RAW = ["timestamp", "trial_id", "water_level_cm", "flow_rate_lpm", "mq4_voltage", "mq135_voltage", "phase", "y"]
HERE = Path(__file__).resolve().parent


def forest():
    return RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced_subsample",
                                  random_state=0, n_jobs=-1)


def alerts_from(flags, times):
    """Times at which a run of PERSIST flagged readings is reached."""
    out, run = [], 0
    for t, f in zip(times, flags):
        run = run + 1 if f else 0
        if run == stage2.PERSIST:
            out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labelled")
    ap.add_argument("--events", required=True)
    ap.add_argument("--floor-new", nargs=2, type=float, required=True, metavar=("N1", "N2"))
    ap.add_argument("--pct", type=float, default=95, help="Stage 1 alarm threshold percentile (default 95)")
    ap.add_argument("--out", default="data/pipeline_loto_report.csv")
    a = ap.parse_args()

    L = pd.read_csv(a.labelled)
    L["timestamp"] = pd.to_datetime(L["timestamp"], utc=True, format="ISO8601")
    L["node_id"] = L["node_id"].astype(int)
    ev = pd.read_csv(a.events)
    ev["occurred_at"] = pd.to_datetime(ev["occurred_at"], utc=True, format="ISO8601")
    depth = stage2.depth_cfg_for_training(a.floor_new)
    old = joblib.load(HERE / "models" / "iforest_final_node1.joblib")

    L1, L2 = L[L.node_id == 1][RAW], L[L.node_id == 2][RAW]
    sens = score.sensors(1, "depth_cm")
    I, ifeats = score.make_features(score.clean(L1, 1, depth=depth), sens, old["window"], level="depth_cm")
    D, cols = stage2.joint_features(L1, L2, depth)
    D = D[D["y"].isin(stage2.CLASSES)]
    trials = sorted(t for t in D["trial_id"].unique() if t.startswith(("blockage", "flood")))

    rows = []
    for T in trials:
        tr_i = I[(I.trial_id != T) & (I.y == "Normal")]
        te_i = I[I.trial_id == T].sort_values("timestamp")
        sc = StandardScaler().fit(tr_i[ifeats])
        iso = clone(old["model"]).fit(sc.transform(tr_i[ifeats]))
        thr = np.percentile(-iso.score_samples(sc.transform(tr_i[ifeats])), a.pct)
        flags = (-iso.score_samples(sc.transform(te_i[ifeats])) > thr)
        s1 = alerts_from(flags, te_i["timestamp"])

        tr_d, te_d = D[D.trial_id != T], D[D.trial_id == T].sort_values("timestamp")
        pred = pd.Series(forest().fit(tr_d[cols], tr_d["y"]).predict(te_d[cols]), index=te_d["timestamp"])
        s2 = alerts_from((pred != "Normal").to_numpy(), pred.index)

        e = ev[ev.trial_id == T]
        on, en = e.loc[e.event_type == "onset", "occurred_at"].min(), e.loc[e.event_type == "end", "occurred_at"].max()
        crit = e.loc[e.event_type == "critical", "occurred_at"].min()
        true = "Blockage" if T.startswith("blockage") else "Flood"
        first = next((t for t in s1 if on <= t <= en), None)
        cls = None
        if first is not None:
            last = pred[pred.index <= first].iloc[-stage2.PERSIST:]
            votes = Counter(p for p in last if p != "Normal")
            cls = votes.most_common(1)[0][0] if votes else "Unclear"
        r2 = next((t for t in s2 if on <= t <= en), None)
        rows.append({"trial": T, "true": true,
                     "false_alerts_before_onset": sum(t < on for t in s1),
                     "stage1_delay_min": round((first - on).total_seconds() / 60, 1) if first is not None else None,
                     "stage1_lead_min": round((crit - first).total_seconds() / 60, 1) if first is not None else None,
                     "class_given": cls,
                     "rf_only_lead_min": round((crit - r2).total_seconds() / 60, 1) if r2 is not None else None,
                     "rf_only_false_alerts": sum(t < on for t in s2)})
        print(f"  {T} done", flush=True)

    R = pd.DataFrame(rows)
    R.to_csv(a.out, index=False)
    print("\nTwo-stage pipeline, leave-one-trial-out (Stage 1 = Isolation Forest p%g on node 1):" % a.pct)
    print(R.to_string(index=False))
    det = R["stage1_lead_min"].notna()
    print(f"\nStage 1 detected {int(det.sum())} of {len(R)} trials; false alerts before onset: {int(R.false_alerts_before_onset.sum())}")
    print(f"class correct in {int((R.class_given == R.true).sum())} of {int(det.sum())} detected trials")
    print(f"lead time >= 5 min: {int((R.stage1_lead_min >= 5).sum())} of {len(R)} (Stage 1 gate), "
          f"{int((R.rf_only_lead_min >= 5).sum())} of {len(R)} (Random Forest alone)")
    print(f"Random Forest alone: detected {int(R.rf_only_lead_min.notna().sum())} of {len(R)} trials; "
          f"false alerts before onset: {int(R.rf_only_false_alerts.sum())}")
    print(f"median lead among detected: {R.stage1_lead_min.median():.1f} min (gate), {R.rf_only_lead_min.median():.1f} min (RF alone)")


if __name__ == "__main__":
    main()