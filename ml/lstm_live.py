"""
Stage 3 live: the saved LSTM forecaster (ml/models/lstm_forecast.pt) applied to the newest readings.

It forecasts node 1's water depth HORIZON_S seconds ahead (300 s) and the time left before the Critical depth, from the
last SEQ readings of both nodes (and the Stage 2 class probabilities when the model was trained with --rf-input).
A warning needs the forecast depth to be at or above the Critical depth for PERSIST readings in a row, the same rule
the offline evaluation used (ml/train_lstm_forecast.py).

Used by the dashboard route /api/forecast. Check it on recorded data (needs the saved model and PyTorch):

    py ml/lstm_live.py data/labelled_readings.csv --floor-new 45.76 45.8
"""
import argparse
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

import score
import stage2

HERE = Path(__file__).resolve().parent
MODEL_FILE = HERE / "models" / "lstm_forecast.pt"
TTC_CAP = 600       # same cap as in training (seconds)
RAW = ["timestamp", "trial_id", "water_level_cm", "flow_rate_lpm", "mq4_voltage", "mq135_voltage", "phase", "y"]


def _net_class():
    import torch
    from torch import nn

    class Net(nn.Module):           # same layers and names as in train_lstm_forecast.py, so the saved weights fit
        def __init__(self, n_in, hidden):
            super().__init__()
            self.lstm = nn.LSTM(n_in, hidden, batch_first=True)
            self.drop = nn.Dropout(0.2)
            self.level = nn.Linear(hidden, 1)
            self.ttc = nn.Linear(hidden, 1)

        def forward(self, x):
            h = self.drop(self.lstm(x)[0][:, -1])
            return self.level(h).squeeze(-1), self.ttc(h).squeeze(-1)

    return torch, Net


@lru_cache(maxsize=1)
def load():
    torch, Net = _net_class()
    torch.set_num_threads(1)
    if not MODEL_FILE.exists():
        raise FileNotFoundError(f"{MODEL_FILE} not found. Run ml/train_lstm_forecast.py ... --rf-input")
    ck = torch.load(MODEL_FILE, map_location="cpu", weights_only=False)     # our own file, not downloaded
    nets = []
    for st in ck["states"]:
        net = Net(len(ck["channels"]), ck["hidden"])
        net.load_state_dict(st)
        net.eval()
        nets.append(net)
    return {"nets": nets, "mean": np.asarray(ck["mean"], dtype=np.float32), "std": np.asarray(ck["std"], dtype=np.float32),
            "channels": list(ck["channels"]), "seq": int(ck["seq"]), "horizon_s": int(ck["horizon_s"]),
            "threshold_cm": float(ck["threshold_cm"]), "torch": torch}


def channel_matrix(D, cols, channels):
    """Rows of D (oldest first) as the matrix the LSTM was trained on: sensor channels, then RF probabilities."""
    D = D.sort_values("timestamp").reset_index(drop=True)
    V = D[[c for c in channels if not c.startswith("p_")]].copy()
    for c in ("n1_depth_cm", "n2_depth_cm"):
        if c in V:
            V[c] = V[c].rolling(5, min_periods=1).median()          # causal median filter, as in training
    if any(c.startswith("p_") for c in channels):
        rf = stage2.load()
        proba = pd.DataFrame(rf["model"].predict_proba(D[rf["cols"]]), columns=[f"p_{c}" for c in rf["model"].classes_])
        for c in channels:
            if c.startswith("p_"):
                V[c] = proba[c].to_numpy() if c in proba else 0.0
    return D, V[channels].to_numpy(dtype=np.float32)


def forecast_rows(M, m, last):
    """Forecasts for the last `last` rows of M: (depth now, forecast depth, seconds to Critical)."""
    seq = m["seq"]
    pad = np.vstack([np.repeat(M[:1], seq - 1, axis=0), M])
    idx = range(len(M) - last, len(M))
    X = np.stack([pad[i:i + seq] for i in idx])
    X = (X - m["mean"]) / m["std"]
    torch = m["torch"]
    with torch.no_grad():
        outs = [net(torch.tensor(X, dtype=torch.float32)) for net in m["nets"]]
    dy = np.mean([o[0].numpy() for o in outs], 0)
    tt = np.mean([o[1].numpy() for o in outs], 0) * TTC_CAP
    now = M[list(idx), m["channels"].index("n1_depth_cm")].astype(float)
    return now, now + dy, np.clip(tt, 0, TTC_CAP)


def forecast_latest(raw1, raw2, m=None):
    """status: paused | warming_up | ok. When ok: depth_now_cm, forecast_cm (HORIZON_S ahead), threshold_cm (Critical
    depth), warn (forecast at or above the Critical depth for PERSIST readings in a row), streak, ttc_s."""
    persist = stage2.PERSIST
    if score.MODE != "depth":
        return {"status": "paused", "persist": persist}
    m = m or load()
    D, cols = stage2.joint_features(raw1, raw2, score.DEPTH)
    if len(D) < persist:
        return {"status": "warming_up", "persist": persist}
    D, M = channel_matrix(D, cols, m["channels"])
    now, fc, tt = forecast_rows(M, m, persist)
    over = fc >= m["threshold_cm"]
    streak = 0
    for f in over[::-1]:
        if not f:
            break
        streak += 1
    return {"status": "ok", "depth_now_cm": float(now[-1]), "forecast_cm": float(fc[-1]), "horizon_s": m["horizon_s"],
            "threshold_cm": m["threshold_cm"], "warn": bool(streak >= persist), "streak": int(streak), "persist": persist,
            "ttc_s": float(tt[-1])}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labelled")
    ap.add_argument("--floor-new", nargs=2, type=float, required=True, metavar=("N1", "N2"))
    a = ap.parse_args()
    m = load()
    print(f"model loaded: {len(m['nets'])} network(s), channels {m['channels']}")
    L = pd.read_csv(a.labelled)
    L["timestamp"] = pd.to_datetime(L["timestamp"], utc=True, format="ISO8601")
    L["node_id"] = L["node_id"].astype(int)
    cfg = stage2.depth_cfg_for_training(a.floor_new)
    for trial in sorted(t for t in L.trial_id.unique() if str(t).startswith(("blockage", "flood")))[:3]:
        g = L[L.trial_id == trial]
        D, cols = stage2.joint_features(g[g.node_id == 1][RAW], g[g.node_id == 2][RAW], cfg)
        D, M = channel_matrix(D, cols, m["channels"])
        now, fc, tt = forecast_rows(M, m, min(len(M), 40))
        print(f"{trial}: {len(D)} readings. Last: depth now {now[-1]:.1f} cm, forecast {fc[-1]:.1f} cm in "
              f"{m['horizon_s']} s, Critical depth {m['threshold_cm']:.1f} cm, time to Critical {tt[-1] / 60:.1f} min")
    print("OK")


if __name__ == "__main__":
    main()
