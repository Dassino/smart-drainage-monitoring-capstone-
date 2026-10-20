/*
 * Smart Drainage Monitoring - Sensor Node 1
 * Reads: ultrasonic water level, flow rate (pulse counting), MQ-4 and MQ-135 gas sensors
 *
 * Every cycle runs the jsn_diagnostic.ino tests (A to E + verdict), then publishes one
 * JSON reading over MQTT using the distance from test B. One cycle takes about 9 to 10 s.
 * Serial Monitor shows only: the cycle header, line B, the VERDICT and the Published line.
 *
 * REQUIRED LIBRARY: PubSubClient by Nick O'Leary (Library Manager).
 *
 * Wiring: ultrasonic Trig/RX -> GPIO5, Echo/TX -> GPIO18 (as in your tested setup),
 *         flow sensor signal -> 10 kOhm -> GPIO4 (no divider to ground),
 *         MQ-4 analog out (via its divider) -> GPIO34,
 *         MQ-135 analog out (via its divider) -> GPIO35
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include "secrets.h"

// ---------- CONFIG: EDIT THESE ----------
const char* MQTT_BROKER   = "192.168.137.1";   // the laptop's address on the Windows hotspot
const int   MQTT_PORT     = 1883;
const char* MQTT_TOPIC    = "drainage/node1/readings";
const char* NODE_ID       = "1";
// -----------------------------------------

// Ultrasonic pins (same names as the diagnostic)
const int PIN_A = 5;     // sensor Trig / RX
const int PIN_B = 18;    // sensor Echo / TX

// Other pins
const int FLOW_PIN  = 4;
const int MQ4_PIN   = 34;
const int MQ135_PIN = 35;

// Flow calibration: pulses per second = FLOW_FACTOR x L/min.
// 7.5 is the typical value for this sensor type. Replace it with your measured
// value (pulses per litre / 60) after the 1-litre calibration run.
const float FLOW_FACTOR = 7.5;

// Must stay above all functions (Arduino auto-generates prototypes that use them).
struct PulseResult { int hits; long medianUs; };
struct SerialResult { bool gotAny; bool valid; int mm; };

WiFiClient espClient;
PubSubClient mqttClient(espClient);

volatile unsigned long pulseCount = 0;
unsigned long lastFlowMs = 0;

// Fixed for the baseline run. Staged trials need a way to change these (pending).
String currentLabel   = "Normal";
String currentTrialId = "baseline_001";

void IRAM_ATTR onFlowPulse() {
  pulseCount++;
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    if (millis() - t0 > 60000) {            // could not join for 60 s: reboot and retry
      ESP.restart();
    }
  }
}

void connectMQTT() {
  int attempts = 0;
  while (!mqttClient.connected()) {
    String clientId = "ESP32Node" + String(NODE_ID);
    if (!mqttClient.connect(clientId.c_str())) {
      if (++attempts >= 30) {               // about 60 s without the broker: reboot
        ESP.restart();
      }
      delay(2000);
    }
  }
}

// ======================= Diagnostic code, copied from jsn_diagnostic.ino =======================
int countEdges(int pin, unsigned long ms) {
  pinMode(pin, INPUT_PULLDOWN);          // pulldown so a floating pin doesn't fake activity
  int last = digitalRead(pin), edges = 0;
  unsigned long t0 = millis();
  while (millis() - t0 < ms) {
    int v = digitalRead(pin);
    if (v != last) { edges++; last = v; }
  }
  return edges;
}

long pulseShot(int trig, int echo) {
  pinMode(trig, OUTPUT);
  pinMode(echo, INPUT);
  digitalWrite(trig, LOW);
  delayMicroseconds(5);
  digitalWrite(trig, HIGH);
  delayMicroseconds(15);                 // datasheet minimum is 10 us
  digitalWrite(trig, LOW);
  return pulseIn(echo, HIGH, 40000);     // 0 means no echo within 40 ms
}

PulseResult pulseTest(int trig, int echo) {
  long vals[5];
  int n = 0;
  for (int i = 0; i < 5; i++) {
    long d = pulseShot(trig, echo);
    if (d > 0) vals[n++] = d;
    delay(300);
  }
  PulseResult r = {n, 0};
  if (n) {
    for (int i = 0; i < n; i++)
      for (int j = i + 1; j < n; j++)
        if (vals[j] < vals[i]) { long t = vals[i]; vals[i] = vals[j]; vals[j] = t; }
    r.medianUs = vals[n / 2];
  }
  return r;
}

SerialResult serialTest(int rxPin, int txPin) {
  SerialResult r = {false, false, 0};
  Serial2.begin(9600, SERIAL_8N1, rxPin, txPin);
  delay(50);
  while (Serial2.available()) Serial2.read();
  Serial2.write((uint8_t)0x55);          // request a reading (serial-controlled mode)
  uint8_t buf[8];
  int n = 0;
  unsigned long t0 = millis();
  while (millis() - t0 < 250 && n < 8) {
    if (Serial2.available()) buf[n++] = Serial2.read();
  }
  Serial2.end();
  r.gotAny = (n > 0);
  for (int i = 0; i + 3 < n; i++) {      // frame: 0xFF, high, low, checksum
    if (buf[i] == 0xFF) {
      uint8_t sum = (uint8_t)(0xFF + buf[i + 1] + buf[i + 2]);
      if (sum == buf[i + 3]) { r.valid = true; r.mm = buf[i + 1] * 256 + buf[i + 2]; break; }
    }
  }
  return r;
}

// One diagnostic cycle: all tests A to E run, but only the cycle header, line B (with any
// retries) and the VERDICT are printed. Returns the distance in cm from test B
// (probe to water surface), or -1. If B gets no echo it is repeated up to 2 more times.
float runDiagnosticCycle() {
  static int cycle = 0;
  Serial.printf("\n===== CYCLE %d =====\n", ++cycle);

  int eA = countEdges(PIN_A, 1500);
  int eB = countEdges(PIN_B, 1500);
  mqttClient.loop();

  PulseResult p1 = pulseTest(PIN_A, PIN_B);
  Serial.printf("B) Pulse mode, Trig=GPIO%d Echo=GPIO%d: hits=%d/5", PIN_A, PIN_B, p1.hits);
  if (p1.hits) Serial.printf("  median=%ldus  dist=%.1fcm", p1.medianUs, p1.medianUs * 0.0343 / 2.0);
  Serial.println();
  for (int retry = 1; retry <= 2 && p1.hits == 0; retry++) {
    mqttClient.loop();
    p1 = pulseTest(PIN_A, PIN_B);
    Serial.printf("B) retry %d: hits=%d/5", retry, p1.hits);
    if (p1.hits) Serial.printf("  median=%ldus  dist=%.1fcm", p1.medianUs, p1.medianUs * 0.0343 / 2.0);
    Serial.println();
  }
  mqttClient.loop();

  PulseResult p2 = pulseTest(PIN_B, PIN_A);       // C) swapped pulse mode
  mqttClient.loop();

  SerialResult s1 = serialTest(PIN_B, PIN_A);     // D) ESP32 RX on GPIO18, TX on GPIO5
  SerialResult s2 = serialTest(PIN_A, PIN_B);     // E) swapped

  Serial.print("VERDICT: ");
  if (p1.hits >= 4) {
    Serial.println("PULSE MODE WORKS with the current wiring.");
  } else if (p2.hits >= 4) {
    Serial.println("PULSE MODE WORKS but Trig and Echo are SWAPPED. Swap the two wires.");
  } else if (s1.valid) {
    Serial.println("Sensor answers in SERIAL mode (current wiring). Pulse mode is not active.");
  } else if (s2.valid) {
    Serial.println("Sensor answers in SERIAL mode with the wires SWAPPED.");
  } else if (p1.hits >= 1 || p2.hits >= 1) {
    int best = (p1.hits > p2.hits) ? p1.hits : p2.hits;
    Serial.printf("INTERMITTENT - echoes return only %d/5 of the time. Not reliable enough to use.\n", best);
  } else if (eA + eB > 0 || s1.gotAny || s2.gotAny) {
    Serial.println("Activity but no valid reading. Possibly an automatic output mode (check the mode pads).");
  } else {
    Serial.println("NO RESPONSE in any mode.");
  }

  // Leave the pins ready for the next cycle (Trig idle LOW, Echo as input)
  pinMode(PIN_A, OUTPUT);
  digitalWrite(PIN_A, LOW);
  pinMode(PIN_B, INPUT);

  return p1.hits ? (p1.medianUs * 0.0343 / 2.0) : -1;
}
// ===============================================================================================

// Flow in L/min, from the pulses counted since the last reading and the real elapsed time.
float readFlowRateLpm(unsigned long nowMs) {
  noInterrupts();
  unsigned long pulses = pulseCount;
  pulseCount = 0;
  interrupts();
  float seconds = (nowMs - lastFlowMs) / 1000.0;
  lastFlowMs = nowMs;
  if (seconds <= 0) return 0;
  return (pulses / seconds) / FLOW_FACTOR;
}

float readGasVoltage(int pin) {
  int raw = analogRead(pin);
  return (raw / 4095.0) * 3.3;
}

void setup() {
  Serial.begin(115200);
  delay(800);

  pinMode(PIN_A, OUTPUT);
  pinMode(PIN_B, INPUT);
  pinMode(FLOW_PIN, INPUT_PULLUP);
  digitalWrite(PIN_A, LOW);
  pulseCount = 0;
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), onFlowPulse, FALLING);

  connectWiFi();
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  lastFlowMs = millis();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();                          // reboots the board if it cannot rejoin
  }
  if (!mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop();

  float waterLevel = runDiagnosticCycle();  // returns cm or -1

  unsigned long now = millis();
  float flowRate     = readFlowRateLpm(now);
  float mq4Voltage   = readGasVoltage(MQ4_PIN);
  float mq135Voltage = readGasVoltage(MQ135_PIN);

  String payload = "{";
  payload += "\"node_id\":\"" + String(NODE_ID) + "\",";
  payload += "\"timestamp\":" + String(now) + ",";
  payload += "\"water_level_cm\":" + String(waterLevel, 2) + ",";
  payload += "\"flow_rate_lpm\":" + String(flowRate, 2) + ",";
  payload += "\"mq4_voltage\":" + String(mq4Voltage, 3) + ",";
  payload += "\"mq135_voltage\":" + String(mq135Voltage, 3) + ",";
  payload += "\"label\":\"" + currentLabel + "\",";
  payload += "\"trial_id\":\"" + currentTrialId + "\"";
  payload += "}";

  mqttClient.publish(MQTT_TOPIC, payload.c_str());
  Serial.println("Published: " + payload);
  delay(1500);                              // same pause as the diagnostic's loop()
}