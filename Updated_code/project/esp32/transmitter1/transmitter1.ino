#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <Wire.h>

#define SDA_PIN 8
#define SCL_PIN 9
#define MY_ID   1          // <-- only line that differs from transmitter2.ino

// ---------- Shared packet definitions (must match receiver) ----------
#define MSG_SYNC 0xAA
#define MSG_DATA 0xBB

typedef struct __attribute__((packed)) {
  uint8_t  msgType;
  uint32_t syncCount;
} SyncPacket;

typedef struct __attribute__((packed)) {
  uint8_t  msgType;
  uint8_t  id;
  uint32_t syncCount;
  int16_t  ax, ay, az;
  int16_t  gx, gy, gz;
} SensorData;

uint8_t receiverMAC[] = {0x10, 0x00, 0x3B, 0xCD, 0x77, 0xDC};

SensorData data;

// ---------- Send callback (data going back to receiver) ----------
void onDataSent(const wifi_tx_info_t *info, esp_now_send_status_t status) {
  // Optional debug; left blank to keep the receive->send path fast.
}

// ---------- Receive callback: this is the trigger ----------
// Fires whenever ANY ESP-NOW packet arrives, including the SYNC
// broadcast from the receiver. This is what replaces delay(20).
void onSync(const esp_now_recv_info_t *info, const uint8_t *incomingData, int len) {
  if (len != sizeof(SyncPacket)) return;

  SyncPacket pkt;
  memcpy(&pkt, incomingData, sizeof(pkt));

  if (pkt.msgType != MSG_SYNC) return;   // ignore anything that isn't a SYNC

  // ---- Immediately read the MPU6050 ----
  Wire.beginTransmission(0x68);
  Wire.write(0x3B);                      // ACCEL_XOUT_H
  Wire.endTransmission(false);

  if (Wire.requestFrom(0x68, 14) != 14) return;

  data.msgType   = MSG_DATA;
  data.id        = MY_ID;
  data.syncCount = pkt.syncCount;        // tag data with the sync round it belongs to

  data.ax = (Wire.read() << 8) | Wire.read();
  data.ay = (Wire.read() << 8) | Wire.read();
  data.az = (Wire.read() << 8) | Wire.read();

  Wire.read(); Wire.read();              // skip temperature

  data.gx = (Wire.read() << 8) | Wire.read();
  data.gy = (Wire.read() << 8) | Wire.read();
  data.gz = (Wire.read() << 8) | Wire.read();

  // ---- Send straight back to the receiver ----
  esp_now_send(receiverMAC, (uint8_t *)&data, sizeof(data));
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

  // Must match the receiver's channel exactly.
  esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE);

  // Disable power-save so the SYNC broadcast is received with
  // minimal, consistent delay instead of waiting on a sleep cycle.
  WiFi.setSleep(false);

  Serial.print("TX1 MAC: ");
  Serial.println(WiFi.macAddress());

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW Init Failed");
    while (1);
  }

  esp_now_register_send_cb(onDataSent);
  esp_now_register_recv_cb(onSync);   // now listening for SYNC packets

  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, receiverMAC, 6);
  peerInfo.channel = 1;
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Peer Add Failed");
    while (1);
  }

  Serial.println("TX1 Ready (waiting for SYNC)");
}

void loop() {
  // Nothing here. All work now happens inside onSync(), triggered
  // by the receiver's broadcast instead of a local delay(20).
}
