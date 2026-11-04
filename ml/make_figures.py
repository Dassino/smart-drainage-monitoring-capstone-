"""
Chapter 5 result figures from the evaluation reports.

    py ml/make_figures.py

Reads data/pipeline_loto_report.csv (eval_pipeline.py) and data/lstm_forecast_report.csv (train_lstm_forecast.py)
and writes docs/figures/fig_lead_time.png and docs/figures/fig_detection.png.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

P = pd.read_csv("data/pipeline_loto_report.csv").set_index("trial")
F = pd.read_csv("data/lstm_forecast_report.csv").set_index("trial")
trials = list(P.index)
out = Path("docs/figures")
out.mkdir(parents=True, exist_ok=True)
C = {"Isolation Forest": "#8C8C8C", "Random Forest": "#1B6AA5", "LSTM forecaster": "#D98A1E"}

lead = pd.DataFrame({
    "Isolation Forest": P["stage1_lead_min"],
    "Random Forest": P["rf_only_lead_min"],
    "LSTM forecaster": F["lead_min"].reindex(trials),
})

fig, ax = plt.subplots(figsize=(9, 4.6))
x = np.arange(len(trials))
w = 0.26
for k, (name, col) in enumerate(lead.items()):
    v = col.to_numpy(dtype=float)
    shown = np.where(np.isnan(v), 0, np.maximum(v, 0))
    ax.bar(x + (k - 1) * w, shown, w, label=name, color=C[name])
    for xi, vi in zip(x, v):
        if np.isnan(vi):
            ax.text(xi + (k - 1) * w, 0.1, "no\nalert", ha="center", va="bottom", fontsize=6, color="#555")
        elif vi < 0:
            ax.text(xi + (k - 1) * w, 0.1, "late", ha="center", va="bottom", fontsize=6, color="#555")
ax.axhline(5, color="#B3261E", ls="--", lw=1.2)
ax.text(-0.55, 5.12, "5-minute target", color="#B3261E", ha="left", fontsize=8)
ax.set_ylim(0, max(10.5, np.nanmax(lead.to_numpy(dtype=float)) + 1))
ax.set_xticks(x)
ax.set_xticklabels([t.replace("_", " ") for t in trials], rotation=35, ha="right", fontsize=8)
ax.set_ylabel("Warning lead time before Critical (minutes)")
ax.set_title("Lead time per staged trial (leave-one-trial-out)")
ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.32))
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(out / "fig_lead_time.png", dpi=200)

n = len(trials)
det = [lead[c].notna().sum() for c in lead]
ge5 = [(lead[c] >= 5).sum() for c in lead]
fig, ax = plt.subplots(figsize=(6.5, 3.8))
xx = np.arange(3)
ax.bar(xx - 0.19, det, 0.38, color=[C[c] for c in lead], alpha=0.55, label="Any alert raised")
ax.bar(xx + 0.19, ge5, 0.38, color=[C[c] for c in lead], label="Lead of 5 minutes or more")
for xi, a, b in zip(xx, det, ge5):
    ax.text(xi - 0.19, a + 0.15, str(a), ha="center", fontsize=9)
    ax.text(xi + 0.19, b + 0.15, str(b), ha="center", fontsize=9)
ax.set_xticks(xx)
ax.set_xticklabels(list(lead.columns))
ax.set_ylim(0, n + 1)
ax.set_ylabel(f"Trials (of {n})")
ax.set_title("Detection and lead time by method")
ax.legend(frameon=False, fontsize=8, loc="upper right")
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(out / "fig_detection.png", dpi=200)
print("saved", out / "fig_lead_time.png", "and", out / "fig_detection.png")