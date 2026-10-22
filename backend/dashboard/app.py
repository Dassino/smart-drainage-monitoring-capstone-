"""
Live dashboard for the Smart Drainage Monitoring system.

Reads sensor_readings from PostgreSQL and serves a web page that shows both nodes at once,
their health, and lets you set the label / trial_id that new readings are stored with.

Setup:   py -m pip install flask psycopg2-binary
Run:     set DB_PASSWORD=your_password        (PowerShell:  $env:DB_PASSWORD="your_password")
         py backend/dashboard/app.py
Open:    http://127.0.0.1:5000
"""
import os
import re
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))
import score  # noqa: E402

DB_NAME = os.environ.get("DB_NAME", "drainage_monitoring")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")

NODES = ["1", "2"]
LABELS = ["Normal", "Blockage", "Flood"]
ONLINE_S = 25      # readings arrive every ~10 s
STALE_S = 60
TRIAL_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")

app = Flask(__name__, static_folder="static", static_url_path="/static")


def db():
    return psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
                            host=DB_HOST, port=DB_PORT)


def ensure_tables():
    with db() as c, c.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS node_labels (
                node_id    VARCHAR(10) PRIMARY KEY,
                label      VARCHAR(30) NOT NULL DEFAULT 'Normal',
                trial_id   VARCHAR(50) NOT NULL DEFAULT 'baseline_001',
                updated_at TIMESTAMP   NOT NULL DEFAULT NOW()
            )""")
        for n in NODES:
            cur.execute("INSERT INTO node_labels (node_id) VALUES (%s) ON CONFLICT DO NOTHING", (n,))


def num(v):
    """Firmware sends -1 for 'no reading'. Show that as a gap, not as a value."""
    return None if v is None or v < 0 else float(v)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/status")
def status():
    out = {}
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for n in NODES:
            cur.execute("""
                SELECT water_level_cm, flow_rate_lpm, mq4_voltage, mq135_voltage, label, trial_id,
                       EXTRACT(EPOCH FROM (NOW() - timestamp)) AS age_s
                FROM sensor_readings WHERE node_id::text = %s
                ORDER BY timestamp DESC LIMIT 1""", (n,))
            last = cur.fetchone()
            cur.execute("""
                SELECT COUNT(*) AS rows_10min,
                       COUNT(*) FILTER (WHERE water_level_cm < 0 OR water_level_cm IS NULL) AS no_echo
                FROM sensor_readings
                WHERE node_id::text = %s AND timestamp > NOW() - INTERVAL '10 minutes'""", (n,))
            recent = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS total FROM sensor_readings WHERE node_id::text = %s", (n,))
            total = cur.fetchone()["total"]
            cur.execute("SELECT label, trial_id FROM node_labels WHERE node_id = %s", (n,))
            lab = cur.fetchone() or {"label": "Normal", "trial_id": "baseline_001"}

            if last is None:
                state, age = "NO DATA", None
            else:
                age = float(last["age_s"])
                state = "ONLINE" if age <= ONLINE_S else "STALE" if age <= STALE_S else "OFFLINE"
            out[n] = {
                "state": state,
                "age_s": age,
                "total_rows": total,
                "rows_10min": recent["rows_10min"],
                "no_echo_10min": recent["no_echo"],
                "set_label": lab["label"],
                "set_trial": lab["trial_id"],
                "latest": None if last is None else {
                    "water_level_cm": num(last["water_level_cm"]),
                    "flow_rate_lpm": num(last["flow_rate_lpm"]),
                    "mq4_voltage": num(last["mq4_voltage"]),
                    "mq135_voltage": num(last["mq135_voltage"]),
                    "label": last["label"], "trial_id": last["trial_id"],
                },
            }
    return jsonify(out)


@app.route("/api/series")
def series():
    minutes = max(1, min(int(request.args.get("minutes", 15)), 360))
    out = {n: [] for n in NODES}
    with db() as c, c.cursor() as cur:
        cur.execute("""
            SELECT node_id::text, EXTRACT(EPOCH FROM (NOW() - timestamp)) AS age_s,
                   water_level_cm, flow_rate_lpm, mq4_voltage, mq135_voltage
            FROM sensor_readings
            WHERE timestamp > NOW() - (%s || ' minutes')::interval
            ORDER BY timestamp""", (str(minutes),))
        for node, age, w, f, m4, m135 in cur.fetchall():
            if node in out:
                out[node].append({"age_s": float(age), "water": num(w), "flow": num(f),
                                  "mq4": num(m4), "mq135": num(m135)})
    return jsonify(out)


@app.route("/api/recent")
def recent():
    rows = []
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT node_id::text AS node_id, EXTRACT(EPOCH FROM (NOW() - timestamp)) AS age_s,
                   water_level_cm, flow_rate_lpm, mq4_voltage, mq135_voltage, label, trial_id
            FROM sensor_readings ORDER BY timestamp DESC LIMIT 14""")
        for r in cur.fetchall():
            rows.append({**r, "age_s": float(r["age_s"])})
    return jsonify(rows)

def latest_trial_rows(cur, node, limit):
    """Newest `limit` readings of the trial the node is currently in, newest first."""
    cur.execute("""
        SELECT timestamp, trial_id, water_level_cm, flow_rate_lpm, mq4_voltage, mq135_voltage,
               EXTRACT(EPOCH FROM (NOW() - timestamp)) AS age_s
        FROM sensor_readings
        WHERE node_id::text = %s
          AND trial_id = (SELECT trial_id FROM sensor_readings
                          WHERE node_id::text = %s ORDER BY timestamp DESC LIMIT 1)
        ORDER BY timestamp DESC LIMIT %s""", (node, node, limit))
    return cur.fetchall()


@app.route("/api/anomaly")
def anomaly():
    """Isolation Forest status of each node, from the latest readings of its current trial."""
    out = {}
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for n in NODES:
            rows = latest_trial_rows(cur, n, score.FETCH_ROWS)
            if not rows:
                out[n] = {"status": "no_data"}
                continue
            try:
                res = score.assess(int(n), pd.DataFrame(rows))
            except Exception as e:      # keep the dashboard alive if scoring fails
                res = {"status": "error", "detail": str(e)}
            age = float(rows[0]["age_s"])
            res["age_s"] = age
            res["trial_id"] = rows[0]["trial_id"]
            if age > STALE_S and res["status"] != "error":
                res["status"] = "no_live_data"
            out[n] = res
    return jsonify(out)


@app.route("/api/anomaly/detail")
def anomaly_detail():
    """Score history and the most unusual features of one node (Alert Detail screen)."""
    node = request.args.get("node", "1")
    if node not in NODES:
        return jsonify({"error": "node must be 1 or 2"}), 400
    try:
        minutes = max(5, min(int(request.args.get("minutes", 15)), 180))
    except ValueError:
        return jsonify({"error": "minutes must be a whole number"}), 400
    limit = int(minutes * 60 / 8) + score.WARMUP_ROWS
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        rows = latest_trial_rows(cur, node, limit)
    if not rows:
        return jsonify({"status": "no_data", "series": [], "features": []})
    try:
        res = score.detail(int(node), pd.DataFrame(rows))
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e), "series": [], "features": []})
    res["series"] = [p for p in res["series"] if p["age_s"] is None or p["age_s"] <= minutes * 60]
    res["age_s"] = float(rows[0]["age_s"])
    res["trial_id"] = rows[0]["trial_id"]
    if res["age_s"] > STALE_S and res["status"] != "error":
        res["status"] = "no_live_data"
    return jsonify(res)

def parse_target(body):
    target = str(body.get("node_id", ""))
    nodes = NODES if target == "both" else [target] if target in NODES else None
    label = body.get("label")
    trial = str(body.get("trial_id", "")).strip()
    if nodes is None:
        return None, None, None, "node_id must be 1, 2 or both"
    if label not in LABELS:
        return None, None, None, f"label must be one of {LABELS}"
    if not TRIAL_RE.match(trial):
        return None, None, None, "trial_id: 1-40 letters, digits, _ or -"
    return nodes, label, trial, None


@app.route("/api/label", methods=["POST"])
def set_label():
    """Label applied to NEW readings from now on."""
    nodes, label, trial, err = parse_target(request.get_json(force=True, silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    with db() as c, c.cursor() as cur:
        for n in nodes:
            cur.execute("""INSERT INTO node_labels (node_id, label, trial_id, updated_at)
                           VALUES (%s, %s, %s, NOW())
                           ON CONFLICT (node_id) DO UPDATE
                           SET label = EXCLUDED.label, trial_id = EXCLUDED.trial_id,
                               updated_at = NOW()""", (n, label, trial))
    return jsonify({"ok": True})


@app.route("/api/relabel", methods=["POST"])
def relabel():
    """Re-label readings already stored in the last N minutes (to correct a late label)."""
    body = request.get_json(force=True, silent=True) or {}
    nodes, label, trial, err = parse_target(body)
    if err:
        return jsonify({"error": err}), 400
    try:
        minutes = int(body.get("minutes"))
    except (TypeError, ValueError):
        return jsonify({"error": "minutes must be a whole number"}), 400
    if not 1 <= minutes <= 720:
        return jsonify({"error": "minutes must be 1 to 720"}), 400
    changed = 0
    with db() as c, c.cursor() as cur:
        for n in nodes:
            cur.execute("""UPDATE sensor_readings SET label = %s, trial_id = %s
                           WHERE node_id::text = %s
                             AND timestamp > NOW() - (%s || ' minutes')::interval""",
                        (label, trial, n, str(minutes)))
            changed += cur.rowcount
    return jsonify({"ok": True, "rows_changed": changed})


if __name__ == "__main__":
    ensure_tables()
    print("Dashboard running at http://127.0.0.1:5000  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5000, debug=False)