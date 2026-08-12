#include <WiFi.h>
#include <esp_now.h>
#include <Wire.h>

#define SDA_PIN 8
#define SCL_PIN 9

uint8_t receiverMAC[] = {0x00, 0x10, 0x3B, 0xCD, 0x77, 0xDC};

typedef struct {
  uint8_t id;
  int16_t ax;
  int16_t ay;
  int16_t az;
  int16_t gx;
  int16_t gy;
  int16_t gz;
} SensorData;

SensorData data;

void onDataSent(const wifi_tx_info_t *info,
                esp_now_send_status_t status)
{
  if (status == ESP_NOW_SEND_SUCCESS)
    Serial.println("SENT");
  else
    Serial.println("FAILED");
}

void setup() {

  Serial.begin(115200);

  Wire.begin(SDA_PIN, SCL_PIN);

  // Wake up MPU6050
  Wire.beginTransmission(0x68);
  Wire.write(0x6B);
  Wire.write(0x00);
  Wire.endTransmission();

  delay(100);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  Serial.print("TX1 MAC: ");
  Serial.println(WiFi.macAddress());

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW Init Failed");
    while (1);
  }

  esp_now_register_send_cb(onDataSent);

  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, receiverMAC, 6);

  peerInfo.channel = 0;
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Peer Add Failed");
    while (1);
  }

  Serial.println("TX1 Ready");
}

void loop() {

  Wire.beginTransmission(0x68);
  Wire.write(0x3B);      // ACCEL_XOUT_H
  Wire.endTransmission(false);

  if (Wire.requestFrom(0x68, 14) == 14) {

    data.id = 1;   // Transmitter 1

    data.ax = (Wire.read() << 8) | Wire.read();
    data.ay = (Wire.read() << 8) | Wire.read();
    data.az = (Wire.read() << 8) | Wire.read();

    // Skip temperature
    Wire.read();
    Wire.read();

    data.gx = (Wire.read() << 8) | Wire.read();
    data.gy = (Wire.read() << 8) | Wire.read();
    data.gz = (Wire.read() << 8) | Wire.read();

    esp_now_send(
      receiverMAC,
      (uint8_t *)&data,
      sizeof(data)
    );

    Serial.print("ID=");
    Serial.print(data.id);

    Serial.print(" AX=");
    Serial.print(data.ax);

    Serial.print(" AY=");
    Serial.print(data.ay);

    Serial.print(" AZ=");
    Serial.print(data.az);

    Serial.print(" GX=");
    Serial.print(data.gx);

    Serial.print(" GY=");
    Serial.print(data.gy);

    Serial.print(" GZ=");
    Serial.println(data.gz);
  }

  delay(20);   // ~50 Hz
}
