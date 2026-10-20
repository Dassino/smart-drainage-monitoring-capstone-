# Smart Drainage Monitoring and Flood Prediction System

Capstone project, ICS 4D, Strathmore University. A three-stage ML pipeline
(Isolation Forest, Random Forest, LSTM) detects blockage and flood risk in
urban drains from two ESP32 sensor nodes.

## Architecture
ESP32 nodes -> MQTT (Mosquitto) -> ingestion script -> PostgreSQL -> ML pipeline -> dashboard

## Hardware and tool choices
| Layer | Choice |
|---|---|
| Microcontroller | ESP32 (Arduino IDE) |
| Transport | MQTT via Mosquitto on the laptop (Windows Mobile Hotspot, 192.168.137.1) |
| Database | PostgreSQL (`sensor_readings`, `node_labels`) |
| Backend / dashboard | Python (paho-mqtt, Flask), Chart.js |
| ML | scikit-learn (Isolation Forest, Random Forest), LSTM |

## Pin assignments
| Signal | Sensor | Node 1 | Node 2 |
|---|---|---|---|
| Water level trigger | JSN-SR04T | GPIO5 | GPIO5 |
| Water level echo | JSN-SR04T | GPIO18 | GPIO18 |
| Flow | ZJ-S201 | GPIO4 | GPIO4 |
| Methane | MQ-4 | GPIO34 | GPIO34 |
| Air quality | MQ-135 | GPIO35 | not fitted |

MQTT topics: `drainage/node1/readings`, `drainage/node2/readings`.

## Repository structure
- `firmware/`: ESP32 sensor node code (copy `secrets.h.example` to `secrets.h` and add your Wi-Fi details)
- `backend/`: schema, MQTT-to-PostgreSQL ingestion, Flask dashboard
- `data/`: Normal baseline export
- `data-collection/`: gas calibration logging
- `ml/`: Isolation Forest notebook and models
- `docs/`: proposal source, diagrams, figures

## Current results (Isolation Forest, trained on day 1, tested on unseen day 2)
False-positive rate: node 1 4.5% (p99 threshold), node 2 3.3% (p95 threshold).
Random Forest and LSTM need the Blockage and Flood trials, which are in progress.

## Status
See Issues and Milestones.