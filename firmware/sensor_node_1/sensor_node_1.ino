/*
 * Smart Drainage Monitoring - Sensor Node Firmware
 * Reads: ultrasonic water level, flow rate (pulse counting), 2x gas sensors
 * Publishes JSON readings over MQTT every 10 seconds
 *
 * REQUIRED LIBRARY: install "PubSubClient" via Arduino IDE Library Manager
 * (Sketch -> Include Library -> Manage Libraries -> search "PubSubClient" by Nick O'Leary)
 */

#include <WiFi.h>
#include <PubSubClient.h>

// ---------- CONFIG: EDIT THESE ----------
const char* WIFI_SSID     = "NJENGAS 2";
const char* WIFI_PASSWORD = "simon1978";
const char* MQTT_BROKER   = "broker.hivemq.com";   // free public test broker - fastest to get running today
const int   MQTT_PORT     = 1883;
const char* MQTT_TOPIC    = "drainage/node1/readings";  // change to node2/readings for the second node
const char* NODE_ID       = "1";                         // change to "2" for the second node
// -----------------------------------------

// Pin assignments (from our wiring plan)
const int TRIG_PIN = 5;
const int ECHO_PIN = 18;
const int FLOW_PIN = 4;
const int MQ4_PIN  = 34;
const int MQ135_PIN = 35;

WiFiClient espClient;
PubSubClient mqttClient(espClient);

volatile unsigned long pulseCount = 0;
unsigned long lastSendTime = 0;
const unsigned long SEND_INTERVAL = 10000; // 10 seconds, matching our sampling plan

// Current label/trial info - update these manually before each staged trial
String currentLabel = "Normal";
String currentTrialId = "baseline_001";

void IRAM_ATTR onFlowPulse() {
  pulseCount++;
}

void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected. IP: " + WiFi.localIP().toString());
}

void connectMQTT() {
  while (!mqttClient.connected()) {
    Serial.print("Connecting to MQTT broker...");
    String clientId = "ESP32Node" + String(NODE_ID);
    if (mqttClient.connect(clientId.c_str())) {
      Serial.println(" connected!");
    } else {
      Serial.print(" failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" retrying in 2s");
      delay(2000);
    }
  }
}

float readWaterLevelCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 30000); // 30ms timeout
  if (duration == 0) return -1; // no echo received
  float distanceCm = duration * 0.0343 / 2.0;
  return distanceCm;
}

float readFlowRateLpm() {
  // Pulse-counting flow rate calculation
  // NOTE: the "7.5" pulses-per-second-per-L/min constant below is the TYPICAL
  // value for YF-S201-style sensors - once you have the real sensor's datasheet,
  // replace 7.5 with the exact calibration factor it specifies.
  noInterrupts();
  unsigned long pulses = pulseCount;
  pulseCount = 0;
  interrupts();

  float pulsesPerSecond = pulses / (SEND_INTERVAL / 1000.0);
  float flowRateLpm = pulsesPerSecond / 7.5;
  return flowRateLpm;
}

float readGasVoltage(int pin) {
  int raw = analogRead(pin);
  return (raw / 4095.0) * 3.3;
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(FLOW_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), onFlowPulse, FALLING);

  connectWiFi();
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
}

void loop() {
  if (!mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop();

  unsigned long now = millis();
  if (now - lastSendTime >= SEND_INTERVAL) {
    lastSendTime = now;

    float waterLevel = readWaterLevelCm();
    float flowRate = readFlowRateLpm();
    float mq4Voltage = readGasVoltage(MQ4_PIN);
    float mq135Voltage = readGasVoltage(MQ135_PIN);

    // Build JSON payload manually (no extra library needed for this simple structure)
    String payload = "{";
    payload += "\"node_id\":\"" + String(NODE_ID) + "\",";
    payload += "\"timestamp\":" + String(millis()) + ",";
    payload += "\"water_level_cm\":" + String(waterLevel, 2) + ",";
    payload += "\"flow_rate_lpm\":" + String(flowRate, 2) + ",";
    payload += "\"mq4_voltage\":" + String(mq4Voltage, 3) + ",";
    payload += "\"mq135_voltage\":" + String(mq135Voltage, 3) + ",";
    payload += "\"label\":\"" + currentLabel + "\",";
    payload += "\"trial_id\":\"" + currentTrialId + "\"";
    payload += "}";

    mqttClient.publish(MQTT_TOPIC, payload.c_str());
    Serial.println("Published: " + payload);
  }
}