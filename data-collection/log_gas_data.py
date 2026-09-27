import serial
import csv
import os
import threading
from datetime import datetime
from collections import deque

PORT = 'COM3'          # <-- CHANGE THIS to your ESP32's port (check Arduino IDE: Tools > Port)
BAUD = 115200
OUTPUT_FILE = 'gas_calibration_log.csv'

# How much the last 10 readings are allowed to vary (in volts) to count as "stable"
STABILITY_THRESHOLD = 0.02
WINDOW_SIZE = 10

current_label = "warmup"
stop_flag = False

mq4_window = deque(maxlen=WINDOW_SIZE)
mq135_window = deque(maxlen=WINDOW_SIZE)


def is_stable(window):
    if len(window) < WINDOW_SIZE:
        return False
    return (max(window) - min(window)) <= STABILITY_THRESHOLD


def label_listener():
    global current_label, stop_flag
    while True:
        new_label = input()
        if new_label.strip().lower() == 'q':
            stop_flag = True
            break
        current_label = new_label.strip()
        mq4_window.clear()
        mq135_window.clear()
        print(f"--- Now logging as: {current_label} (stability windows reset) ---")


ser = serial.Serial(PORT, BAUD, timeout=2)

# Append mode: if the file already exists (e.g. from an earlier run today),
# new readings are added to it instead of erasing what's already there.
file_exists = os.path.isfile(OUTPUT_FILE)

print(f"Connected to {PORT}. Logging to {OUTPUT_FILE}")
if file_exists:
    print("(Existing file found — new readings will be ADDED to it, nothing erased.)")
print("Type a label (e.g. methane_50ppm) and press Enter to switch phase.")
print("Type 'q' and Enter to stop.\n")

listener = threading.Thread(target=label_listener, daemon=True)
listener.start()

with open(OUTPUT_FILE, 'a', newline='') as f:
    writer = csv.writer(f)
    if not file_exists:
        writer.writerow([
            'pc_timestamp', 'label', 'esp32_millis',
            'mq4_raw', 'mq4_voltage', 'mq4_stable',
            'mq135_raw', 'mq135_voltage', 'mq135_stable'
        ])

    while not stop_flag:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line and ',' in line and not line.startswith('timestamp'):
            parts = line.split(',')
            if len(parts) == 5:
                esp32_millis, mq4_raw, mq4_voltage, mq135_raw, mq135_voltage = parts
                mq4_v = float(mq4_voltage)
                mq135_v = float(mq135_voltage)

                mq4_window.append(mq4_v)
                mq135_window.append(mq135_v)

                mq4_stable = is_stable(mq4_window)
                mq135_stable = is_stable(mq135_window)

                row = [
                    datetime.now().isoformat(), current_label, esp32_millis,
                    mq4_raw, mq4_voltage, mq4_stable,
                    mq135_raw, mq135_voltage, mq135_stable
                ]
                writer.writerow(row)
                f.flush()

                flag = ""
                if mq4_stable and mq135_stable:
                    flag = "  <-- BOTH STABLE"
                elif mq4_stable:
                    flag = "  <-- MQ4 stable"
                elif mq135_stable:
                    flag = "  <-- MQ135 stable"

                print(f"{current_label} | MQ4={mq4_v:.3f}V  MQ135={mq135_v:.3f}V{flag}")

print("Logging stopped. File saved:", OUTPUT_FILE)