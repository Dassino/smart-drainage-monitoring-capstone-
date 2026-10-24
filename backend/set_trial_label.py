"""
Set the label of every stored reading of one trial (to fix a trial recorded with the wrong label).

    $env:DB_PASSWORD="your_password"
    py backend/set_trial_label.py blockage_01 Blockage

The label must be Normal, Blockage or Flood. Only readings whose trial_id matches exactly are
changed, so neighbouring trials are never touched. It shows the labels before and after.
"""
import os
import re
import sys

import psycopg2

LABELS = ["Normal", "Blockage", "Flood"]
TRIAL_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


def counts(cur, trial):
    cur.execute("""SELECT node_id::text, label, COUNT(*) FROM sensor_readings
                   WHERE trial_id = %s GROUP BY node_id, label ORDER BY node_id, label""", (trial,))
    return cur.fetchall()


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in LABELS or not TRIAL_RE.match(sys.argv[1]):
        sys.exit(f"usage: py backend/set_trial_label.py <trial_id> <{'|'.join(LABELS)}>")
    trial, label = sys.argv[1], sys.argv[2]
    con = psycopg2.connect(dbname=os.environ.get("DB_NAME", "drainage_monitoring"),
                           user=os.environ.get("DB_USER", "postgres"),
                           password=os.environ.get("DB_PASSWORD", "killstar"),
                           host=os.environ.get("DB_HOST", "localhost"),
                           port=os.environ.get("DB_PORT", "5432"))
    with con, con.cursor() as cur:
        before = counts(cur, trial)
        if not before:
            sys.exit(f"No readings found for trial '{trial}'. Nothing changed.")
        print(f"Before ({trial}):")
        for node, lab, n in before:
            print(f"  node {node}: {n} readings labelled {lab}")
        cur.execute("UPDATE sensor_readings SET label = %s WHERE trial_id = %s", (label, trial))
        print(f"Updated {cur.rowcount} readings to {label}.")
        print("After:")
        for node, lab, n in counts(cur, trial):
            print(f"  node {node}: {n} readings labelled {lab}")
    con.close()


if __name__ == "__main__":
    main()