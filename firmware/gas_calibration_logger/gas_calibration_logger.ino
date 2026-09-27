// Gas Sensor Calibration Logger — for chamber session
// Reads MQ-4 (GPIO34) and MQ-135 (GPIO35), prints every 2 seconds

#include <Arduino.h>
const int MQ4_PIN = 34;
const int MQ135_PIN = 35;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("timestamp_ms,mq4_raw,mq4_voltage,mq135_raw,mq135_voltage");
}

void loop() {
  int mq4_raw = analogRead(MQ4_PIN);
  int mq135_raw = analogRead(MQ135_PIN);

  // ESP32 ADC: 12-bit (0-4095), reference ~3.3V (after your voltage divider)
  float mq4_voltage = (mq4_raw / 4095.0) * 3.3;
  float mq135_voltage = (mq135_raw / 4095.0) * 3.3;

  Serial.print(millis());
  Serial.print(",");
  Serial.print(mq4_raw);
  Serial.print(",");
  Serial.print(mq4_voltage, 3);
  Serial.print(",");
  Serial.print(mq135_raw);
  Serial.print(",");
  Serial.println(mq135_voltage, 3);

  delay(2000); // log every 2 seconds
}