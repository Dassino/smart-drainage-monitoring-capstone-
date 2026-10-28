"""
Build the labelled dataset from the readings exports and the trial events.

Run from the repo root:

    py ml/build_dataset.py data/export_node1_2026-10-24.csv data/export_node2_2026-10-24.csv ^
        data/export_node1_2026-10-25.csv data/export_node2_2026-10-25.csv ^
        --events data/trial_events_2026-10-26.csv --floor-new 45.76 45.8 ^
        --drop baseline_d3_night "2026-10-24 00:00" "2026-10-25 00:00" ^
        --drop flood_02 "2026-10-25 16:30:00" "2026-10-25 16:36:40"

Labels are taken from the EVENT TIMES, not from the label stored with each reading:
  before onset                 -> Normal  (phase "pre")
  onset .. first critical      -> trial label (Blockage / Flood), phase "rise"
  first critical .. end        -> trial label, phase "peak"
  end .. end + --recovery-min  -> unlabelled (y empty), phase "post": the water is still draining
  later                        -> Normal (phase "post")
  trials with no events (baseline_*) -> Normal, phase "baseline"
Trials whose ID starts with setup, pilot or rest are left out (--exclude-prefix).
--drop TRIAL FROM TO removes that trial's readings between two clock times (Nairobi time),
for example while a sensor was being re-aimed.

Writes (folder of --out, default data/):
  labelled_readings.csv  every kept reading with depth_cm, phase, y, t_rel_critical_s (seconds from the first critical press)
  normal_d3.csv          Normal readings only (baselines; with --pre-in-normal also each trial's pre-onset readings), in the export format, for ml/train_depth.py
  critical_summary.csv   depth at every critical press (median of the readings within +-15 s), both nodes
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

TZ = "Africa/Nairobi"
LABEL_OF_PREFIX = {"blockage": "Blockage", "flood": "Flood"}


def ts(x):
    return pd.to_datetime(x, utc=True, format="ISO8601")


def local(x):
    return pd.Timestamp(x).tz_localize(TZ).tz_convert("UTC")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+", help="readings exports (any mix of nodes and days)")
    ap.add_argument("--events", required=True)
    ap.add_argument("--floor-new", nargs=2, type=float, required=True, metavar=("N1", "N2"))
    ap.add_argument("--drop", nargs=3, action="append", default=[], metavar=("TRIAL", "FROM", "TO"))
    ap.add_argument("--exclude-prefix", nargs="*", default=["setup", "pilot", "rest"])
    ap.add_argument("--recovery-min", type=float, default=5.0)
    ap.add_argument("--pre-in-normal", action="store_true",
                    help="also put the readings recorded BEFORE each trial's onset into normal_d3.csv (label Normal). "
                         "These are the only Normal readings with water flowing at the new mounting.")
    ap.add_argument("--out", default="data")
    a = ap.parse_args()
    floor = {1: a.floor_new[0], 2: a.floor_new[1]}

    df = pd.concat([pd.read_csv(p) for p in a.csv], ignore_index=True)
    df["timestamp"] = ts(df["timestamp"])
    df["node_id"] = df["node_id"].astype(int)
    df = df.drop_duplicates(subset=["node_id", "timestamp"]).sort_values(["node_id", "timestamp"])

    skip = df["trial_id"].str.startswith(tuple(a.exclude_prefix))
    print("Left out (prefix):", ", ".join(f"{t} ({n})" for t, n in df.loc[skip, "trial_id"].value_counts().items()) or "none")
    df = df[~skip]
    for trial, f, t in a.drop:
        m = (df["trial_id"] == trial) & (df["timestamp"] >= local(f)) & (df["timestamp"] <= local(t))
        print(f"Dropped {int(m.sum())} readings of {trial} between {f} and {t}")
        df = df[~m]

    ev = pd.read_csv(a.events)
    ev["occurred_at"] = ts(ev["occurred_at"])
    ev["event_type"] = ev["event_type"].str.strip()

    parts, crit_rows = [], []
    for trial, g in df.groupby("trial_id"):
        te = ev[ev["trial_id"] == trial]
        onset, end = te.loc[te.event_type == "onset", "occurred_at"], te.loc[te.event_type == "end", "occurred_at"]
        crit = te.loc[te.event_type == "critical", "occurred_at"].sort_values().tolist()
        g = g.copy()
        g["depth_cm"] = g["node_id"].map(floor) - g["water_level_cm"].where(g["water_level_cm"].between(0, 100))
        if onset.empty or end.empty:
            if (g["label"] != "Normal").any():
                sys.exit(f"{trial} has no onset/end events but non-Normal readings. Check trial_events.")
            g["phase"], g["y"], g["t_rel_critical_s"] = "baseline", "Normal", np.nan
            parts.append(g)
            continue
        on, en = onset.min(), end.max()
        kind = trial.split("_")[0]
        if kind not in LABEL_OF_PREFIX:
            sys.exit(f"Don't know the label for trial {trial}.")
        lab = LABEL_OF_PREFIX[kind]
        first = crit[0] if crit else None
        t = g["timestamp"]
        g["phase"] = np.select(
            [t < on, (t >= on) & ((t < first) if first is not None else True), (t >= on) & (t <= en),
             t > en], ["pre", "rise", "peak", "post"], default="pre")
        g["y"] = np.select(
            [g["phase"] == "pre", g["phase"].isin(["rise", "peak"]), t <= en + pd.Timedelta(minutes=a.recovery_min)],
            ["Normal", lab, ""], default="Normal")
        g["t_rel_critical_s"] = (t - first).dt.total_seconds() if first is not None else np.nan
        stored = g.loc[g["phase"].isin(["rise", "peak"]), "label"]
        bad = int((stored != lab).sum())
        if bad:
            print(f"  note: {trial}: {bad} of {len(stored)} readings between onset and end are stored as "
                  f"{sorted(stored[stored != lab].unique())}, not {lab}. The event-time label is used.")
        for i, c in enumerate(crit, 1):
            for node in (1, 2):
                w = g[(g["node_id"] == node) & ((g["timestamp"] - c).abs() <= pd.Timedelta(seconds=15))]
                crit_rows.append({"trial_id": trial, "press": i, "presses": len(crit), "node": node,
                                  "time": c.tz_convert(TZ).strftime("%H:%M:%S"),
                                  "min_after_onset": round((c - on).total_seconds() / 60, 2),
                                  "distance_cm": round(w["water_level_cm"].median(), 2) if len(w) else np.nan,
                                  "depth_cm": round(w["depth_cm"].median(), 2) if len(w) else np.nan,
                                  "readings": len(w)})
        parts.append(g)

    out = pd.concat(parts, ignore_index=True)
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    out.to_csv(outdir / "labelled_readings.csv", index=False)

    keep = (out["phase"] == "baseline") & (out["label"] == "Normal")
    if a.pre_in_normal:
        keep |= out["phase"] == "pre"
    normal = out[keep].assign(label="Normal")
    normal.drop(columns=["depth_cm", "phase", "y", "t_rel_critical_s"]).to_csv(outdir / "normal_d3.csv", index=False)
    crit = pd.DataFrame(crit_rows)
    crit.to_csv(outdir / "critical_summary.csv", index=False)

    print("\nReadings per trial, node and phase:")
    print(out.groupby(["trial_id", "node_id", "phase"]).size().unstack(fill_value=0).to_string())
    print(f"\nnormal_d3.csv: {len(normal)} Normal readings from {sorted(normal['trial_id'].unique())}")
    if len(crit):
        print("\nDepth at every critical press (median of the readings within 15 s):")
        print(crit.pivot_table(index=["trial_id", "press", "time", "min_after_onset"], columns="node",
                               values="depth_cm").round(2).to_string())
        n1 = crit[crit.node == 1]
        for kind in ("blockage", "flood"):
            d = n1[n1["trial_id"].str.startswith(kind)]
            if len(d):
                first = d[d.press == 1]["depth_cm"]
                print(f"{kind}: first press depth on node 1: median {first.median():.2f} cm, range {first.min():.2f} to "
                      f"{first.max():.2f} cm; all presses {d['depth_cm'].min():.2f} to {d['depth_cm'].max():.2f} cm")


if __name__ == "__main__":
    main()