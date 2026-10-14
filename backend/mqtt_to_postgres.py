"""
MQTT -> PostgreSQL ingestion for the Smart Drainage Monitoring system.

Subscribes to drainage/+/readings and stores every message in sensor_readings.
The label and trial_id written to the database are NOT taken from the ESP32. They come from
the node_labels table, which you change from the dashboard. So you can label data while
the nodes keep running, with no re-upload.

Setup:   py -m pip install paho-mqtt psycopg2-binary
Run:     set DB_PASSWORD=your_password        (PowerShell:  $env:DB_PASSWORD="your_password")
         py backend/mqtt_to_postgres.py
"""
import json
import os
import sys
import time

import paho.mqtt.client as mqtt
import psycopg2

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC = "drainage/+/readings"

DB_NAME = os.environ.get("DB_NAME", "drainage_monitoring")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")

CREATE_LABELS = """
CREATE TABLE IF NOT EXISTS node_labels (
    node_id    VARCHAR(10) PRIMARY KEY,
    label      VARCHAR(30) NOT NULL DEFAULT 'Normal',
    trial_id   VARCHAR(50) NOT NULL DEFAULT 'baseline_001',
    updated_at TIMESTAMP   NOT NULL DEFAULT NOW()
);
"""

conn = None


def connect_db():
    global conn
    while True:
        try:
            conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
                                    host=DB_HOST, port=DB_PORT)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(CREATE_LABELS)
            print("Connected to PostgreSQL.")
            return
        except psycopg2.Error as e:
            print(f"Database not reachable ({e}). Retrying in 5 s...")
            time.sleep(5)


def current_label(node_id, fallback_label, fallback_trial):
    """Label and trial currently set for this node on the dashboard."""
    with conn.cursor() as cur:
        cur.execute("SELECT label, trial_id FROM node_labels WHERE node_id = %s", (node_id,))
        row = cur.fetchone()
        if row:
            return row[0], row[1]
        cur.execute(
            "INSERT INTO node_labels (node_id, label, trial_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (node_id) DO NOTHING",
            (node_id, "Normal", "baseline_001"),
        )
    return "Normal", "baseline_001"


def insert_reading(data):
    node_id = str(data["node_id"])
    label, trial_id = current_label(node_id, data.get("label"), data.get("trial_id"))
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO sensor_readings
               (node_id, water_level_cm, flow_rate_lpm, mq4_voltage, mq135_voltage, label, trial_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (node_id, data.get("water_level_cm"), data.get("flow_rate_lpm"),
             data.get("mq4_voltage"), data.get("mq135_voltage"), label, trial_id),
        )
    return label, trial_id


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f"Connected to MQTT broker, subscribing to {MQTT_TOPIC}")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"MQTT connection failed: {reason_code}")


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        label, trial_id = insert_reading(data)
        print(f"Stored node {data['node_id']}: level={data.get('water_level_cm')} "
              f"flow={data.get('flow_rate_lpm')} [{label} / {trial_id}]")
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        print("Lost the database connection, reconnecting...")
        connect_db()
    except Exception as e:  # bad JSON, missing field, etc.: skip the message, keep running
        print(f"Skipped a message ({e}): {msg.payload[:120]!r}")


def main():
    connect_db()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("Stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()