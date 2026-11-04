# Smart Drainage Monitoring and Flood Prediction System for Urban Areas in Kenya

Capstone project, ICS 4D, Strathmore University.
Student: Njenga Martin Njuguna (ID 165852). Supervisor: Mr. Ouma Kelvin.

Two ESP32 sensor nodes measure water level, flow and gas voltage along a model drainage channel and publish readings over MQTT. The readings are stored in PostgreSQL, scored by a machine-learning pipeline, and shown on a web dashboard that reports whether the drain is Normal, Blockage or Flood.

## Architecture

```
ESP32 node 1 ─┐
              ├─ Wi-Fi hotspot ─> Mosquitto (MQTT) ─> mqtt_to_postgres.py ─> PostgreSQL ─> Flask API ─> React dashboard
ESP32 node 2 ─┘                                                                    └─> ML pipeline (ml/)
```

## Machine-learning pipeline

| Stage | Model | Role in the system |
|---|---|---|
| 1 | Isolation Forest (one per node) | Flags readings that differ from the Normal baseline of the new mounting. Shown beside the diagnosis as a second opinion; it does not gate Stage 2. |
| 2 | Random Forest (30 features, 300 trees) | Main alert. Classifies the current state as Normal, Blockage or Flood; the alert is raised after 6 consecutive non-Normal predictions. |
| 3 | LSTM (PyTorch, CPU) | Evaluated as a classifier and as a forecaster of the next water level and the time to Critical. Reported honestly in Chapter 5; it did not beat simple baselines and is not part of the live dashboard. |

All models are evaluated with leave-one-trial-out validation over 10 labelled trials (5 Blockage, 5 Flood), because neighbouring readings from one trial are not independent.

## Results (leave-one-trial-out, 10 trials)

| Model | Trials detected | Correct class | Lead time of at least 5 min | False alerts |
|---|---|---|---|---|
| Isolation Forest alone | 4 / 10 | n/a | 2 / 10 | 4 |
| Random Forest alone (main alert) | 10 / 10 | 10 / 10 | 3 / 10 (median 4.2 min) | 2 |
| Isolation Forest gate then Random Forest | 4 / 10 | 3 of 4 | 2 / 10 | not used |
| LSTM classifier | 7 / 10 | n/a | 2 / 10 | not used |
| LSTM forecaster | 3 / 10 warned | n/a | 1 / 10 | 0 |

Random Forest classifies 81% of event readings correctly. A 5-minute warning was physically possible on only 6 of the 10 trials, because on the others the water reached the Critical depth sooner. The LSTM forecaster's level error (RMSE 1.24 cm) is no better than assuming the level stays as it is (1.23 cm). Full tables and discussion are in Chapter 5 of the report.

## Hardware

| Part | Model |
|---|---|
| Microcontroller | ESP32 38-pin development board (ESP32-WROOM, CP2102), Arduino IDE |
| Water level | JSN-SR04T waterproof ultrasonic module |
| Flow | ZJ-S201 Hall-effect flow sensor |
| Methane | MQ-4 (both nodes) |
| Air quality | MQ-135 (node 1 only) |
| Server | Windows laptop: hotspot, Mosquitto broker, PostgreSQL, backend, frontend |

### Pin assignments (both nodes)

| Signal | Sensor | Pin | Note |
|---|---|---|---|
| Ultrasonic trigger | JSN-SR04T | GPIO5 | Direct |
| Ultrasonic echo | JSN-SR04T | GPIO18 | Through 3.3 kΩ / 3.3 kΩ divider |
| Flow pulse | ZJ-S201 | GPIO4 | Through divider |
| Methane | MQ-4 | GPIO34 | Through divider |
| Air quality | MQ-135 | GPIO35 | Node 1 only; through divider |

MQTT topics: `drainage/node1/readings`, `drainage/node2/readings`.
Gas outputs are stored as voltages because the sensors were not calibrated against a reference.

## Repository structure

- `firmware/`: sensor node sketches (copy `secrets.h.example` to `secrets.h` and fill in your Wi-Fi details; `secrets.h` is not committed)
- `backend/`: database schema, `mqtt_to_postgres.py` (MQTT to PostgreSQL), `dashboard/app.py` (Flask API)
- `frontend/`: React dashboard
- `data/`: Normal baseline, labelled readings and evaluation reports
- `data-collection/`: gas calibration logging
- `ml/`: training, evaluation and scoring scripts, saved models in `ml/models/`
- `docs/`: proposal source, diagrams, figures, and `docs/evidence/` (photographs, screenshots, logs)

## Running the system

Requires PostgreSQL, Mosquitto, Python 3.12, Node.js 22, and the nodes powered and connected to the laptop hotspot.

```powershell
py -m pip install flask psycopg2-binary pandas numpy joblib scikit-learn==1.6.1 paho-mqtt torch matplotlib
```

scikit-learn must be 1.6.1, the version the models were saved with.

Start each of these in its own terminal. Each program reads the database password from the `DB_PASSWORD` environment variable and asks for it if the variable is not set. Do not put the password in a file or in the repository.

```powershell
py backend/mqtt_to_postgres.py
py backend/dashboard/app.py
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The health check is `/api/status`; if the backend is not running the dashboard shows "Cannot reach the API".

To label a trial for training, use `backend/set_trial_label.py`.

## Reproducing the results

The scripts in `ml/` read `data/labelled_readings.csv`. For example, the LSTM forecaster:

```powershell
py ml/train_lstm_forecast.py data/labelled_readings.csv --floor-new 45.76 45.8 --rf-input --seeds 3
```

The result charts are drawn from the evaluation reports:

```powershell
py ml/make_figures.py
```

Run each script with `--help` for its options. Results vary slightly between runs and between library versions.

## Known limitations

- The Mosquitto broker has no authentication; it runs on a private laptop hotspot only.
- Gas sensors are uncalibrated (voltages, not ppm). The flow sensor uses the datasheet factor and was not checked against a measured volume.
- The Normal baseline is shorter than the 48 hours planned.
- Only ten trials were recorded in one laboratory channel model; results are not evidence of performance in a real drain.
- The system runs on one laptop and is not hosted publicly.

## Future work

- Restyle the dashboard (colour palette, typography, sidebar). Layout and content follow the wireframes; styling is open to change.
- Calibrate the gas sensors and the flow sensor.
- Add authentication to the broker.
- Collect more trials and a longer Normal baseline.