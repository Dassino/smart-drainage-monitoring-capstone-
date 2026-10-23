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
import csv
import io
import re
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
import pandas as pd
from flask import Flask, Response, jsonify, request, send_from_directory
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
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EVENT_TYPES = ["onset", "critical", "end"]   # event starts, critical level reached, event ends
GAP_S = 60         # a pause longer than this between readings is a recording gap
MERGE_S = 60       # alerts that restart within this many seconds count as one incident


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
        cur.execute("""
        CREATE TABLE IF NOT EXISTS trial_events (
            event_id    SERIAL PRIMARY KEY,
            node_id     VARCHAR(10)  NOT NULL,          -- '1', '2' or 'both'
            trial_id    VARCHAR(50)  NOT NULL,
            event_type  VARCHAR(20)  NOT NULL,          -- onset, critical or end
            occurred_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            note        VARCHAR(200)
        )""")


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

@app.route("/api/trials")
def trials():
    """Every recorded trial (per node) with its label, size and time span."""
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT node_id::text AS node, trial_id,
                   string_agg(DISTINCT label, ', ') AS label,
                   COUNT(*) AS rows, MIN(timestamp) AS started, MAX(timestamp) AS ended
            FROM sensor_readings
            GROUP BY node_id, trial_id
            ORDER BY MAX(timestamp) DESC""")
        out = []
        for r in cur.fetchall():
            out.append({"node": r["node"], "trial_id": r["trial_id"], "label": r["label"],
                        "rows": r["rows"], "started": r["started"].isoformat(),
                        "ended": r["ended"].isoformat(),
                        "duration_s": (r["ended"] - r["started"]).total_seconds()})
    return jsonify(out)


def rec_position(times, rec, t):
    """Position of time t on the recording clock (gaps removed)."""
    k = times.searchsorted(t, side="right") - 1
    if k < 0:
        return 0.0
    return rec[k] + min((t - times[k]).total_seconds(), GAP_S)


@app.route("/api/trial")
def trial_replay():
    """One trial on one node: readings, detector score, alert episodes and logged events."""
    node = request.args.get("node", "")
    trial = request.args.get("trial_id", "")
    if node not in NODES or not TRIAL_RE.match(trial):
        return jsonify({"error": "node must be 1 or 2 and trial_id must be valid"}), 400
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT timestamp, trial_id, water_level_cm, flow_rate_lpm, mq4_voltage, mq135_voltage
            FROM sensor_readings
            WHERE node_id::text = %s AND trial_id = %s
            ORDER BY timestamp LIMIT 30000""", (node, trial))
        rows = cur.fetchall()
        cur.execute("""
            SELECT event_id, event_type, occurred_at, note FROM trial_events
            WHERE trial_id = %s AND node_id IN (%s, 'both') ORDER BY occurred_at""", (trial, node))
        event_rows = cur.fetchall()
    if not rows:
        return jsonify({"error": "no readings for that trial"}), 404
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    times = pd.DatetimeIndex(df["timestamp"])
    t0 = times[0]
    scored, detector_error = {}, None
    try:
        s = score.score_frame(int(node), df)
        scored = {t: (sc, fl) for t, sc, fl in zip(s["timestamp"], s["score"], s["flag"])}
    except Exception as e:
        detector_error = str(e)

    series, rec_list, gaps = [], [], []
    rec, prev = 0.0, None
    streak, episodes, open_ep, run_start = 0, [], None, 0.0
    for r in df.itertuples():
        if prev is not None:
            dt = (r.timestamp - prev).total_seconds()
            if dt <= GAP_S:
                rec += dt
            else:
                gaps.append(rec)
                streak = 0
                if open_ep is not None:
                    open_ep["end_s"] = rec
                    open_ep = None
        prev = r.timestamp
        rec_list.append(rec)
        sc, fl = scored.get(r.timestamp, (None, None))
        if fl is not None:
                if fl:
                    streak += 1
                    if streak == 1:
                        run_start = rec
                    if streak == score.PERSIST:
                        open_ep = {"start_s": rec, "run_start_s": run_start, "end_s": rec}
                        episodes.append(open_ep)
                elif streak > score.PERSIST and open_ep is not None:
                    open_ep["end_s"] = rec
                else:
                    streak = 0
                    open_ep = None
        series.append({"rec_s": rec, "water": num(r.water_level_cm), "flow": num(r.flow_rate_lpm),
                       "mq4": num(r.mq4_voltage), "mq135": num(r.mq135_voltage),
                       "score": None if sc is None else float(sc),
                       "flag": None if fl is None else bool(fl)})

        merged = []
        for ep in episodes:
            if merged and ep["run_start_s"] - merged[-1]["end_s"] <= MERGE_S:
                merged[-1]["end_s"] = ep["end_s"]
            else:
                merged.append(dict(ep))
        episodes = merged

    events = []
    for e in event_rows:
        t = pd.Timestamp(e["occurred_at"]).tz_convert("UTC")
        events.append({"event_id": e["event_id"], "type": e["event_type"], "note": e["note"],
                       "rec_s": rec_position(times, rec_list, t), "at": t.isoformat()})
    onset = next((e for e in events if e["type"] == "onset"), None)
    critical = next((e for e in events if e["type"] == "critical"), None)
    detection_delay_s = lead_time_s = None
    false_before_onset = None
    if onset is not None:
        false_before_onset = sum(1 for ep in episodes if ep["end_s"] < onset["rec_s"])
        hit = next((ep for ep in episodes if ep["end_s"] >= onset["rec_s"]), None)
        if hit is not None:
            detection_delay_s = max(0.0, hit["start_s"] - onset["rec_s"])
            if critical is not None:
                lead_time_s = critical["rec_s"] - max(hit["start_s"], onset["rec_s"])
    m = score.load(int(node))
    return jsonify({
        "node": node, "trial_id": trial, "started": t0.isoformat(), "rows": len(series),
        "recording_s": rec, "wall_s": (times[-1] - t0).total_seconds(), "gaps": gaps,
        "scored_rows": sum(1 for p in series if p["flag"] is not None),
        "flagged_rows": sum(1 for p in series if p["flag"]),
        "episodes": episodes,
        "alerts_per_hour": (len(episodes) / (rec / 3600)) if rec > 0 else None,
        "events": events, "false_alerts_before_onset": false_before_onset,
        "detection_delay_s": detection_delay_s, "lead_time_s": lead_time_s,
        "threshold": float(m["thr"]), "percentile": m["pct"], "persist": score.PERSIST,
        "detector_error": detector_error, "series": series})


@app.route("/api/event", methods=["POST"])
def add_event():
    """Log a trial event (event starts, critical level reached, event ends) at the current time."""
    body = request.get_json(force=True, silent=True) or {}
    node = str(body.get("node_id", ""))
    trial = str(body.get("trial_id", "")).strip()
    etype = body.get("type")
    note = str(body.get("note", ""))[:200]
    if node not in NODES + ["both"]:
        return jsonify({"error": "node_id must be 1, 2 or both"}), 400
    if not TRIAL_RE.match(trial):
        return jsonify({"error": "trial_id: 1-40 letters, digits, _ or -"}), 400
    if etype not in EVENT_TYPES:
        return jsonify({"error": f"type must be one of {EVENT_TYPES}"}), 400
    try:
        ago = int(body.get("seconds_ago", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "seconds_ago must be a whole number"}), 400
    if not 0 <= ago <= 900:
        return jsonify({"error": "seconds_ago must be 0 to 900"}), 400
    with db() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO trial_events (node_id, trial_id, event_type, occurred_at, note)
                       VALUES (%s, %s, %s, NOW() - make_interval(secs => %s), %s)
                       RETURNING event_id""", (node, trial, etype, ago, note))
        eid = cur.fetchone()[0]
    return jsonify({"ok": True, "event_id": eid})


@app.route("/api/events")
def list_events():
    """Most recent logged events, newest first. Optional filter: trial_id."""
    trial = request.args.get("trial_id", "")
    where, args = "", []
    if trial:
        if not TRIAL_RE.match(trial):
            return jsonify({"error": "invalid trial_id"}), 400
        where, args = "WHERE trial_id = %s", [trial]
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""SELECT event_id, node_id, trial_id, event_type, note, occurred_at,
                               EXTRACT(EPOCH FROM (NOW() - occurred_at)) AS age_s
                        FROM trial_events {where} ORDER BY occurred_at DESC LIMIT 20""", args)
        out = [{**r, "occurred_at": r["occurred_at"].isoformat(), "age_s": float(r["age_s"])}
               for r in cur.fetchall()]
    return jsonify(out)


@app.route("/api/event/<int:event_id>", methods=["DELETE"])
def delete_event(event_id):
    with db() as c, c.cursor() as cur:
        cur.execute("DELETE FROM trial_events WHERE event_id = %s", (event_id,))
        deleted = cur.rowcount
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/model_info")
def model_info():
    """Settings of the saved Isolation Forest models (System Administration screen)."""
    out = {}
    for n in NODES:
        try:
            m = score.load(int(n))
            out[n] = {"percentile": m["pct"], "threshold": float(m["thr"]), "window": m["window"],
                      "features": m["feats"], "trees": m["model"].n_estimators,
                      "trained_rows": int(m["scaler"].n_samples_seen_), "persist": score.PERSIST,
                      "file": f"iforest_final_node{n}.joblib"}
        except Exception as e:
            out[n] = {"error": str(e)}
    return jsonify(out)

@app.route("/api/export.csv")
def export_csv():
    """Download readings as CSV. Filters: node (1, 2 or all), trial_id, label, start and end (YYYY-MM-DD)."""
    where, args = [], []
    node = request.args.get("node", "all")
    if node != "all":
        if node not in NODES:
            return jsonify({"error": "node must be 1, 2 or all"}), 400
        where.append("node_id::text = %s")
        args.append(node)
    trial = request.args.get("trial_id", "")
    if trial:
        if not TRIAL_RE.match(trial):
            return jsonify({"error": "invalid trial_id"}), 400
        where.append("trial_id = %s")
        args.append(trial)
    label = request.args.get("label", "")
    if label:
        if label not in LABELS:
            return jsonify({"error": f"label must be one of {LABELS}"}), 400
        where.append("label = %s")
        args.append(label)
    start, end = request.args.get("start", ""), request.args.get("end", "")
    if start:
        if not DATE_RE.match(start):
            return jsonify({"error": "start must be YYYY-MM-DD"}), 400
        where.append("timestamp >= %s::date")
        args.append(start)
    if end:
        if not DATE_RE.match(end):
            return jsonify({"error": "end must be YYYY-MM-DD"}), 400
        where.append("timestamp < (%s::date + 1)")
        args.append(end)
    sql = ("SELECT reading_id, node_id, timestamp, water_level_cm, flow_rate_lpm, mq4_voltage, "
           "mq135_voltage, label, trial_id FROM sensor_readings"
           + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY timestamp, node_id")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["reading_id", "node_id", "timestamp", "water_level_cm", "flow_rate_lpm",
                "mq4_voltage", "mq135_voltage", "label", "trial_id"])
    with db() as c, c.cursor() as cur:
        cur.execute(sql, args)
        for row in cur.fetchall():
            w.writerow(row)
    name = "drainage_readings" + (f"_{trial}" if trial else "") + ".csv"
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})

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