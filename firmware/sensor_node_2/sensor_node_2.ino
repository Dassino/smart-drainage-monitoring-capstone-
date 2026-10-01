/*
 * Smart Drainage Monitoring - Sensor Node 2 Firmware
 * Reads: ultrasonic water level, flow rate (pulse counting), MQ-4 only
 * (Node 2 has no MQ-135 sensor fitted)
 * Publishes JSON readings over MQTT every 10 seconds
 *
 * REQUIRED LIBRARY: install "PubSubClient" via Arduino IDE Library Manager
 */

#include <WiFi.h>
#include <PubSubClient.h>

// ---------- CONFIG: EDIT THESE ----------
const char* WIFI_SSID     = "NJENGAS 2";
const char* WIFI_PASSWORD = "simon1978";
const char* MQTT_BROKER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;
const char* MQTT_TOPIC    = "drainage/node2/readings";
const char* NODE_ID       = "2";
// -----------------------------------------

// Pin assignments
const int TRIG_PIN = 5;
const int ECHO_PIN = 18;
const int FLOW_PIN = 4;
const int MQ4_PIN  = 34;
// NOTE: no MQ135_PIN - this node does not have that sensor fitted

WiFiClient espClient;
PubSubClient mqttClient(espClient);

volatile unsigned long pulseCount = 0;
unsigned long lastSendTime = 0;
const unsigned long SEND_INTERVAL = 10000;

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

  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return -1;
  float distanceCm = duration * 0.0343 / 2.0;
  return distanceCm;
}

float readFlowRateLpm() {
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

    // mq135_voltage is sent as -1 to flag "sensor not fitted on this node"
    // rather than omitting the field entirely - keeps every node's JSON
    // structure identical, which matters once this feeds into one shared
    // database table with fixed columns.
    String payload = "{";
    payload += "\"node_id\":\"" + String(NODE_ID) + "\",";
    payload += "\"timestamp\":" + String(millis()) + ",";
    payload += "\"water_level_cm\":" + String(waterLevel, 2) + ",";
    payload += "\"flow_rate_lpm\":" + String(flowRate, 2) + ",";
    payload += "\"mq4_voltage\":" + String(mq4Voltage, 3) + ",";
    payload += "\"mq135_voltage\":-1,";
    payload += "\"label\":\"" + currentLabel + "\",";
    payload += "\"trial_id\":\"" + currentTrialId + "\"";
    payload += "}";

    mqttClient.publish(MQTT_TOPIC, payload.c_str());
    Serial.println("Published: " + payload);
  }
}