"""
Stage 3: an LSTM that reads the last SEQ readings (about 3.4 minutes) of both nodes and names the
problem (Normal, Blockage or Flood). Evaluated exactly like the Random Forest: leave-one-trial-out.

Run from the repo root after ml/build_dataset.py:

    py ml/train_lstm.py data/labelled_readings.csv --events data/trial_events_2026-10-26.csv --floor-new 45.76 45.8

Per reading the inputs are de-spiked depth, flow and MQ-4 of node 1 and node 2 plus MQ-135 of node 1
(7 channels), standardised with the training statistics. Writes data/lstm_loto_report.csv and saves a
final model trained on every trial to ml/models/lstm_stage3.pt. Needs PyTorch (pip install torch).
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from sklearn.metrics import confusion_matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage2  # noqa: E402

SEQ = 24
EPOCHS = 40
HIDDEN = 32
CHANNELS = ["n1_depth_cm", "n1_flow_rate_lpm", "n1_mq4_voltage", "n1_mq135_voltage",
            "n2_depth_cm", "n2_flow_rate_lpm", "n2_mq4_voltage"]
RAW = ["timestamp", "trial_id", "water_level_cm", "flow_rate_lpm", "mq4_voltage", "mq135_voltage", "phase", "y"]
IDX = {c: i for i, c in enumerate(stage2.CLASSES)}
torch.set_num_threads(2)


class Net(nn.Module):
    def __init__(self, n_in):
        super().__init__()
        self.lstm = nn.LSTM(n_in, HIDDEN, batch_first=True)
        self.head = nn.Sequential(nn.Dropout(0.2), nn.Linear(HIDDEN, len(IDX)))

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out[:, -1])


def sequences(D):
    """Windows of SEQ consecutive readings inside one trial; the label belongs to the last reading.
    The first SEQ-1 readings of a trial are padded by repeating its first reading, so every reading gets a prediction."""
    X, y, rows = [], [], []
    for trial, g in D.groupby("trial_id"):
        g = g.sort_values("timestamp")
        v = g[CHANNELS].to_numpy(dtype=np.float32)
        v = np.vstack([np.repeat(v[:1], SEQ - 1, axis=0), v])
        for i in range(len(g)):
            X.append(v[i:i + SEQ])
            y.append(IDX[g["y"].iloc[i]])
            rows.append(g.index[i])
    return np.array(X), np.array(y), rows


def fit(X, y, seed=0):
    torch.manual_seed(seed)
    mean, std = X.reshape(-1, X.shape[2]).mean(0), X.reshape(-1, X.shape[2]).std(0) + 1e-6
    Xt, yt = torch.tensor((X - mean) / std), torch.tensor(y)
    w = torch.tensor(len(y) / (len(IDX) * np.maximum(np.bincount(y, minlength=len(IDX)), 1)), dtype=torch.float32)
    net, loss = Net(X.shape[2]), nn.CrossEntropyLoss(weight=w)
    opt = torch.optim.Adam(net.parameters(), lr=0.005)
    for _ in range(EPOCHS):
        net.train()
        for b in torch.randperm(len(yt)).split(64):
            opt.zero_grad()
            loss(net(Xt[b]), yt[b]).backward()
            opt.step()
    return net, mean, std


def predict(net, mean, std, X):
    net.eval()
    with torch.no_grad():
        return net(torch.tensor((X - mean) / std)).argmax(1).numpy()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labelled")
    ap.add_argument("--events", required=True)
    ap.add_argument("--floor-new", nargs=2, type=float, required=True, metavar=("N1", "N2"))
    ap.add_argument("--out", default="data/lstm_loto_report.csv")
    a = ap.parse_args()

    L = pd.read_csv(a.labelled)
    L["timestamp"] = pd.to_datetime(L["timestamp"], utc=True, format="ISO8601")
    L["node_id"] = L["node_id"].astype(int)
    ev = pd.read_csv(a.events)
    ev["occurred_at"] = pd.to_datetime(ev["occurred_at"], utc=True, format="ISO8601")
    D, _ = stage2.joint_features(L[L.node_id == 1][RAW], L[L.node_id == 2][RAW], stage2.depth_cfg_for_training(a.floor_new))
    D = D[D["y"].isin(stage2.CLASSES)].reset_index(drop=True)
    trials = sorted(t for t in D["trial_id"].unique() if t.startswith(("blockage", "flood")))
    print(f"{len(D)} readings, sequences of {SEQ}, {len(CHANNELS)} channels")

    rows, allp = [], []
    for T in trials:
        Xtr, ytr, _ = sequences(D[D.trial_id != T])
        Xte, yte, idx = sequences(D[D.trial_id == T])
        net, mean, std = fit(Xtr, ytr)
        te = D.loc[idx].assign(p=[stage2.CLASSES[i] for i in predict(net, mean, std, Xte)])
        allp.append(te[["trial_id", "phase", "y", "p"]])
        act, pre = te[te.phase.isin(["rise", "peak"])], te[te.phase == "pre"]
        e = ev[ev.trial_id == T]
        on, crit = e.loc[e.event_type == "onset", "occurred_at"].min(), e.loc[e.event_type == "critical", "occurred_at"].min()
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
        print(f"  {T} done", flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(a.out, index=False)
    A = pd.concat(allp)
    pos = A[A.phase.isin(["rise", "peak"])]
    print("\nLeave-one-trial-out report (LSTM):")
    print(R.to_string(index=False))
    print(f"\nreadings between onset and end: {len(pos)}")
    print(f"  classified correctly {(pos.p == pos.y).mean():.0%}, called Normal {(pos.p == 'Normal').mean():.0%}, "
          f"Blockage/Flood mix-up {((pos.p != pos.y) & (pos.p != 'Normal')).mean():.0%}")
    print(f"  pre-onset readings called Normal {(A[A.phase == 'pre'].p == 'Normal').mean():.0%}")
    print("  alert with the right class:", int((R.alert_class == R.true).sum()), "of", len(R))
    print("  lead time >= 5 min:", int((R.lead_min >= 5).sum()), "of", len(R))
    print("\nConfusion matrix, event readings (rows = true, columns = predicted):")
    print(pd.DataFrame(confusion_matrix(pos.y, pos.p, labels=stage2.CLASSES), index=stage2.CLASSES,
                       columns=stage2.CLASSES).to_string())

    X, y, _ = sequences(D)
    net, mean, std = fit(X, y)
    path = Path(__file__).resolve().parent / "models" / "lstm_stage3.pt"
    torch.save({"state": net.state_dict(), "mean": mean, "std": std, "channels": CHANNELS, "seq": SEQ,
                "hidden": HIDDEN, "classes": stage2.CLASSES, "floor_new": list(a.floor_new)}, path)
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()