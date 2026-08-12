#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

// ---------- Shared packet definitions ----------
// msgType lets us tell SYNC packets and DATA packets apart on the wire.
// syncCount is a rolling counter so the receiver can match a data
// packet back to the specific SYNC round that triggered it.

#define MSG_SYNC 0xAA
#define MSG_DATA 0xBB

typedef struct __attribute__((packed)) {
  uint8_t  msgType;   // MSG_SYNC
  uint32_t syncCount; // increments every broadcast
} SyncPacket;

typedef struct __attribute__((packed)) {
  uint8_t  msgType;   // MSG_DATA
  uint8_t  id;        // 1 or 2, identifies which transmitter
  uint32_t syncCount; // which SYNC round this reading belongs to
  int16_t  ax, ay, az;
  int16_t  gx, gy, gz;
} SensorData;

// Broadcast MAC: every ESP-NOW peer on the channel receives this.
uint8_t broadcastMAC[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

const uint32_t SYNC_PERIOD_MS = 20;   // 50 Hz sync rate
uint32_t syncCounter = 0;
uint32_t lastSyncMillis = 0;

// ---------- Send callback (for the SYNC broadcast) ----------
void onDataSent(const wifi_tx_info_t *info, esp_now_send_status_t status) {
  // Not essential, kept only for debugging broadcast delivery.
  // (Broadcast "success" just means it left the radio, not that
  // every peer received it — that's normal for ESP-NOW broadcasts.)
}

// ---------- Small ring buffer: holds packets between arrival and printing ----------
// WHY THIS EXISTS: printing directly inside onReceive() used to cause garbled
// serial output. Two transmitters can reply within 1-2ms of each other (that's
// good — it means sync is working), and if a second packet arrives while the
// first one's multi-part Serial.print() sequence is still flushing out over
// USB, the two print sequences interleave and corrupt each other on the wire.
// The fix: onReceive() just stores the packet (fast, no printing). Only
// loop() — which is single-threaded and never runs concurrently with itself —
// is allowed to call Serial.print(). That makes corruption impossible.
#define DATA_QUEUE_SIZE 16
SensorData dataQueue[DATA_QUEUE_SIZE];
volatile uint8_t queueHead = 0;   // next slot onReceive() will write to
volatile uint8_t queueTail = 0;   // next slot loop() will read from

// ---------- Receive callback (sensor data from TX1 / TX2) ----------
void onReceive(const esp_now_recv_info_t *info, const uint8_t *incomingData, int len) {
  if (len != sizeof(SensorData)) return;      // ignore malformed packets

  SensorData d;
  memcpy(&d, incomingData, sizeof(d));

  if (d.msgType != MSG_DATA) return;          // ignore anything that isn't sensor data

  // Store into the ring buffer. No Serial calls here — kept intentionally fast.
  uint8_t nextHead = (queueHead + 1) % DATA_QUEUE_SIZE;
  if (nextHead != queueTail) {                // guard against buffer full
    dataQueue[queueHead] = d;
    queueHead = nextHead;
  }
  // If the buffer is full, we drop the packet rather than corrupt output.
  // With SIZE=16 and only 2 transmitters at 50Hz, this should never happen.
}

// ---------- Print one queued packet as a single, uninterrupted line ----------
void printQueuedData() {
  while (queueTail != queueHead) {
    SensorData d = dataQueue[queueTail];
    queueTail = (queueTail + 1) % DATA_QUEUE_SIZE;

    // Build the full line first, then send it with ONE Serial call.
    // A single call can't be split by another packet arriving mid-print.
    char buf[96];
    snprintf(buf, sizeof(buf), "%u,%lu,%lu,%d,%d,%d,%d,%d,%d",
             d.id, (unsigned long)d.syncCount, millis(),
             d.ax, d.ay, d.az, d.gx, d.gy, d.gz);
    Serial.println(buf);
  }
}

void setup() {
  Serial.begin(115200);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  // Lock the WiFi channel explicitly so it can't drift or differ
  // between boards. All 3 devices MUST use the same channel.
  esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE);

  // Turn off WiFi modem sleep. Power-save mode delays how quickly
  // the radio wakes to process incoming/outgoing ESP-NOW packets,
  // which adds jitter to the sync timing. This is important.
  WiFi.setSleep(false);

  Serial.print("Receiver MAC: ");
  Serial.println(WiFi.macAddress());

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW Init Failed");
    while (1);
  }

  esp_now_register_send_cb(onDataSent);
  esp_now_register_recv_cb(onReceive);

  // Add the broadcast address as a peer so we're allowed to send to it.
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, broadcastMAC, 6);
  peerInfo.channel = 1;        // must match esp_wifi_set_channel above
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Broadcast Peer Add Failed");
    while (1);
  }

  Serial.println("id,syncCount,recvMillis,ax,ay,az,gx,gy,gz");
  Serial.println("Receiver Ready (sync master)");
}

void loop() {
  uint32_t now = millis();

  if (now - lastSyncMillis >= SYNC_PERIOD_MS) {
    lastSyncMillis = now;

    SyncPacket pkt;
    pkt.msgType   = MSG_SYNC;
    pkt.syncCount = syncCounter++;

    esp_now_send(broadcastMAC, (uint8_t *)&pkt, sizeof(pkt));
  }

  // Print any packets that arrived since we last checked. This is the
  // ONLY place Serial.print() for sensor data happens now — see the
  // comment above the ring buffer for why.
  printQueuedData();
}