"""
Why does a retrained depth model flag so many Normal readings at the new mounting?

Run from the repo root with the same CSV files that were given to ml/train_depth.py:

    py ml/diag_depth.py data/sensor_readings_export.csv data/normal_d3.csv

For each node it compares the features of the old-mounting rows with the new-mounting rows
(the model's own training rows), shows which features have moved the most, and shows how the flag
rate at the new mounting splits by trial. Read-only: it changes no files.
"""
import sys
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score  # noqa: E402


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: py ml/diag_depth.py normal_export.csv [more.csv ...]")
    df = pd.concat([pd.read_csv(p) for p in sys.argv[1:]], ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df["node_id"] = df["node_id"].astype(int)
    df = df.drop_duplicates(subset=["node_id", "timestamp"])
    pd.set_option("display.width", 200)

    for node in (1, 2):
        m = joblib.load(score.MODELS_DIR / score.model_file(node).replace("final", "depth"))
        cfg = {"old": {node: m["d_floor_old"]}, "new": {node: m["d_floor_new"]},
               "change_at": pd.Timestamp(m["change_at"]).tz_convert("UTC")}
        rows = df[(df.node_id == node) & df.trial_id.isin(m["trials"])]
        d, feats = score.make_features(score.clean(rows, node, depth=cfg), score.sensors(node, "depth_cm"),
                                       m["window"], level="depth_cm")
        X = m["scaler"].transform(d[feats])
        d = d.assign(score=-m["model"].score_samples(X))
        d["flag"] = d["score"] > m["thr"]
        new = (d["timestamp"] >= cfg["change_at"]).to_numpy()
        print(f"\n===== node {node}: {int((~new).sum())} old-mounting rows, {int(new.sum())} new-mounting rows =====")
        print(f"flag rate: old {d.flag[~new].mean():.1%}, new {d.flag[new].mean():.1%} (threshold {m['thr']:.4f})")

        z = pd.DataFrame(X, columns=feats, index=d.index)
        t = pd.DataFrame({
            "old mean": d.loc[~new, feats].mean(), "old std": d.loc[~new, feats].std(),
            "new mean": d.loc[new, feats].mean(), "new std": d.loc[new, feats].std()})
        t["shift (old std)"] = (t["new mean"] - t["old mean"]) / t["old std"]
        t["new rows |z|>3"] = (z[new].abs() > 3).mean()
        print("\nFeatures, biggest shift first (old vs new mounting):")
        print(t.reindex(t["shift (old std)"].abs().sort_values(ascending=False).index).round(3).head(10).to_string())

        print("\nNew-mounting flag rate by trial:")
        g = d[new].groupby("trial_id").agg(rows=("flag", "size"), flagged=("flag", "mean"),
                                           depth=("depth_cm", "median"), flow=("flow_rate_lpm", "median"))
        print(g.round(3).to_string())


if __name__ == "__main__":
    main()