"""
Stage 3 as documented: an LSTM that FORECASTS node 1's water depth HORIZON_S seconds ahead and the time left before
the Critical depth, from the last SEQ readings of both nodes (and, with --rf-input, the Stage 2 class probabilities).

    py ml/train_lstm_forecast.py data/labelled_readings.csv --floor-new 45.76 45.8 --rf-input --seeds 3

Leave-one-trial-out over the 10 Blockage / Flood trials. A warning is raised when the forecast depth reaches the
Critical depth for PERSIST readings in a row (PERSIST from stage2). Lead time = first Critical press - first warning.
Compared with two baselines: "depth stays as it is now" and straight-line extrapolation of the last minute.
Writes data/lstm_forecast_report.csv and ml/models/lstm_forecast.pt. Needs PyTorch.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import RandomForestClassifier
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage2  # noqa: E402

SEQ, EPOCHS, HIDDEN = 24, 40, 32
HORIZON_S, TTC_CAP = 300, 600
CHANNELS = ["n1_depth_cm", "n1_flow_rate_lpm", "n1_mq4_voltage", "n1_mq135_voltage",
            "n2_depth_cm", "n2_flow_rate_lpm", "n2_mq4_voltage"]
RAW = ["timestamp", "trial_id", "water_level_cm", "flow_rate_lpm", "mq4_voltage", "mq135_voltage", "phase", "y"]
torch.set_num_threads(1)


class Net(nn.Module):
    def __init__(self, n_in):
        super().__init__()
        self.lstm = nn.LSTM(n_in, HIDDEN, batch_first=True)
        self.drop = nn.Dropout(0.2)
        self.level = nn.Linear(HIDDEN, 1)      # change in node 1 depth after HORIZON_S
        self.ttc = nn.Linear(HIDDEN, 1)        # seconds to Critical / TTC_CAP

    def forward(self, x):
        h = self.drop(self.lstm(x)[0][:, -1])
        return self.level(h).squeeze(-1), self.ttc(h).squeeze(-1)


def rf_probs(D, train_trials, cols, fit_on):
    """Class probabilities of a Random Forest trained on `fit_on` rows, for every row of D."""
    f = RandomForestClassifier(n_estimators=100, min_samples_leaf=3, class_weight="balanced_subsample", random_state=0, n_jobs=1)
    t = fit_on[fit_on["y"].isin(stage2.CLASSES)]
    f.fit(t[cols], t["y"])
    P = pd.DataFrame(0.0, index=D.index, columns=[f"p_{c}" for c in stage2.CLASSES])
    P[[f"p_{c}" for c in f.classes_]] = f.predict_proba(D[cols])
    return P


def add_rf(D, cols, train_ids, test_id):
    """Out-of-fold RF probabilities for the training trials (inner leave-one-trial-out), and for the test trial
    from a forest trained on all training trials, so no row is scored by a forest that saw its own trial."""
    out = pd.DataFrame(index=D.index, columns=[f"p_{c}" for c in stage2.CLASSES], dtype=float)
    tr = D[D.trial_id.isin(train_ids)]
    for t in train_ids:
        out.loc[D.trial_id == t] = rf_probs(D[D.trial_id == t], None, cols, tr[tr.trial_id != t]).to_numpy()
    out.loc[D.trial_id == test_id] = rf_probs(D[D.trial_id == test_id], None, cols, tr).to_numpy()
    return out


def windows(D, crit_t, extra):
    X, dy, tt, now, info = [], [], [], [], []
    for trial, g in D.groupby("trial_id"):
        g = g.sort_values("timestamp")
        t = (g["timestamp"] - g["timestamp"].iloc[0]).dt.total_seconds().to_numpy()
        v = g[CHANNELS].copy()
        for c in ("n1_depth_cm", "n2_depth_cm"):
            v[c] = v[c].rolling(5, min_periods=1).median()        # causal median filter, removes flicker
        v = np.hstack([v.to_numpy(dtype=np.float32), g[extra].to_numpy(dtype=np.float32)]) if extra else v.to_numpy(dtype=np.float32)
        d = v[:, 0].astype(float)
        fut = np.interp(t + HORIZON_S, t, d)
        ok = t + HORIZON_S <= t[-1]
        if trial in crit_t.index:
            ttc = (crit_t[trial] - g["timestamp"]).dt.total_seconds().to_numpy()
            tok = ttc >= 0
            ttc = np.clip(ttc, 0, TTC_CAP) / TTC_CAP
        else:
            ttc, tok = np.ones(len(g)), np.ones(len(g), bool)
        pad = np.vstack([np.repeat(v[:1], SEQ - 1, axis=0), v])
        for i in range(len(g)):
            X.append(pad[i:i + SEQ])
            dy.append(fut[i] - d[i] if ok[i] else np.nan)
            tt.append(ttc[i] if tok[i] else np.nan)
            now.append(d[i]); info.append((trial, g["timestamp"].iloc[i]))
    return np.array(X), np.array(dy, dtype=np.float32), np.array(tt, dtype=np.float32), np.array(now), info


def fit(X, dy, tt, seed):
    torch.manual_seed(seed)
    mean, std = X.reshape(-1, X.shape[2]).mean(0), X.reshape(-1, X.shape[2]).std(0) + 1e-6
    Xt = torch.tensor((X - mean) / std)
    a, b = torch.tensor(np.nan_to_num(dy)), torch.tensor(np.nan_to_num(tt))
    ma, mb = torch.tensor(~np.isnan(dy)).float(), torch.tensor(~np.isnan(tt)).float()
    net = Net(X.shape[2])
    opt = torch.optim.Adam(net.parameters(), lr=0.005)
    sl1 = nn.SmoothL1Loss(reduction="none")
    for _ in range(EPOCHS):
        net.train()
        for i in torch.randperm(len(Xt)).split(64):
            opt.zero_grad()
            pa, pb = net(Xt[i])
            loss = (sl1(pa, a[i]) * ma[i]).sum() / ma[i].sum().clamp(min=1) + (sl1(pb, b[i]) * mb[i]).sum() / mb[i].sum().clamp(min=1)
            loss.backward(); opt.step()
    return net, mean, std


def predict(models, X):
    outs = []
    for net, mean, std in models:
        net.eval()
        with torch.no_grad():
            a, b = net(torch.tensor((X - mean) / std))
        outs.append((a.numpy(), b.numpy()))
    return np.mean([o[0] for o in outs], 0), np.mean([o[1] for o in outs], 0) * TTC_CAP


def runs(flags, times, need):
    out, run = [], 0
    for t, f in zip(times, flags):
        run = run + 1 if f else 0
        if run == need:
            out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labelled")
    ap.add_argument("--floor-new", nargs=2, type=float, required=True, metavar=("N1", "N2"))
    ap.add_argument("--rf-input", action="store_true", help="feed the Stage 2 class probabilities to the LSTM (as designed)")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--out", default="data/lstm_forecast_report.csv")
    a = ap.parse_args()

    L = pd.read_csv(a.labelled)
    L["timestamp"] = pd.to_datetime(L["timestamp"], utc=True, format="ISO8601")
    L["node_id"] = L["node_id"].astype(int)
    L1 = L[L.node_id == 1]
    crit_t = (L1.dropna(subset=["t_rel_critical_s"]).assign(c=lambda d: d.timestamp - pd.to_timedelta(d.t_rel_critical_s, unit="s"))
              .groupby("trial_id")["c"].median())
    D, cols = stage2.joint_features(L1[RAW], L[L.node_id == 2][RAW], stage2.depth_cfg_for_training(a.floor_new))
    D = D.reset_index(drop=True)
    trials = sorted(t for t in D["trial_id"].unique() if t.startswith(("blockage", "flood")))
    cd = {}
    for T in trials:
        g = D[D.trial_id == T].sort_values("timestamp")
        cd[T] = float(g.loc[(g.timestamp - crit_t[T]).abs().idxmin(), "n1_depth_cm"])
    print(f"{len(D)} readings; forecast {HORIZON_S // 60} min ahead; rf-input={a.rf_input}; seeds={a.seeds}", flush=True)

    rows, err = [], {"lstm": [], "stay": [], "line": []}
    ttc_err = []
    for T in trials:
        thr = float(np.median([v for k, v in cd.items() if k != T]))
        ids = [t for t in D.trial_id.unique() if t != T]
        E = D.copy()
        extra = []
        if a.rf_input:
            P = add_rf(E, cols, ids, T)
            E[P.columns] = P.to_numpy()
            extra = list(P.columns)
        Xtr, dtr, ttr, _, _ = windows(E[E.trial_id != T], crit_t, extra)
        Xte, dte, tte, now, info = windows(E[E.trial_id == T], crit_t, extra)
        models = [fit(Xtr, dtr, ttr, s) for s in range(a.seeds)]
        pd_, pt = predict(models, Xte)
        pred = now + pd_
        yte = now + dte
        k = 7
        line = now + (now - np.r_[np.repeat(now[:1], k), now[:-k]]) / (k * 8.5) * HORIZON_S
        m = ~np.isnan(dte)
        for n, q in (("lstm", pred), ("stay", now), ("line", line)):
            err[n].append(q[m] - yte[m])
        ts = pd.Series([i[1] for i in info])
        on = L[(L.trial_id == T) & (L.node_id == 1) & L.phase.isin(["rise", "peak"])]["timestamp"].min()
        w = runs(pred >= thr, ts, stage2.PERSIST)
        first = next((t for t in w if t >= on), None)
        fa = sum(t < on for t in w)
        c = crit_t[T]
        mt = (~np.isnan(tte)) & (ts >= on).to_numpy() & (ts <= c).to_numpy()
        ttc_err.append(np.abs(pt[mt] - tte[mt] * TTC_CAP))
        rows.append({"trial": T, "critical_depth_cm": round(cd[T], 2), "threshold_used": round(thr, 2),
                     "rmse_lstm": round(float(np.sqrt(np.mean((pred[m] - yte[m]) ** 2))), 2),
                     "rmse_stay": round(float(np.sqrt(np.mean((now[m] - yte[m]) ** 2))), 2),
                     "ttc_mae_min": round(float(np.mean(ttc_err[-1])) / 60, 1) if mt.any() else None,
                     "warn_delay_min": round((first - on).total_seconds() / 60, 1) if first is not None else None,
                     "lead_min": round((c - first).total_seconds() / 60, 1) if first is not None else None,
                     "false_warnings_before_onset": int(fa)})
        print(f"  {T} done", flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(a.out, index=False)
    print("\nLSTM forecast, leave-one-trial-out:")
    print(R.to_string(index=False))
    for n, label in (("lstm", "LSTM"), ("stay", "depth stays as now"), ("line", "straight-line extrapolation")):
        e = np.concatenate(err[n])
        print(f"  {label:30s} RMSE {np.sqrt(np.mean(e ** 2)):.2f} cm   MAE {np.mean(np.abs(e)):.2f} cm")
    print(f"  time to Critical (between onset and Critical): MAE {np.concatenate(ttc_err).mean() / 60:.1f} min")
    print(f"warned before the first Critical press: {int((R.lead_min > 0).sum())} of {len(R)} trials, "
          f"lead >= 5 min: {int((R.lead_min >= 5).sum())}, false warnings before onset: {int(R.false_warnings_before_onset.sum())}")
    print(f"median lead among warned: {R.lead_min.median():.1f} min")

    path = Path(__file__).resolve().parent / "models" / "lstm_forecast.pt"
    path.parent.mkdir(exist_ok=True)
    E = D.copy()
    extra = []
    if a.rf_input:
        P = rf_probs(E, None, cols, E)
        E[P.columns] = P.to_numpy(); extra = list(P.columns)
    X, d, t_, _, _ = windows(E, crit_t, extra)
    nets = [fit(X, d, t_, s) for s in range(a.seeds)]
    torch.save({"states": [n.state_dict() for n, _, _ in nets], "mean": nets[0][1], "std": nets[0][2], "channels": CHANNELS + extra,
                "seq": SEQ, "hidden": HIDDEN, "horizon_s": HORIZON_S, "threshold_cm": float(np.median(list(cd.values())))}, path)
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()