#include <WiFi.h>
#include <esp_now.h>

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

void onReceive(const esp_now_recv_info_t *info,
               const uint8_t *incomingData,
               int len)
{
  memcpy(&data, incomingData, sizeof(data));

  Serial.print(data.id);
  Serial.print(",");

  Serial.print(millis());
  Serial.print(",");

  Serial.print(data.ax);
  Serial.print(",");

  Serial.print(data.ay);
  Serial.print(",");

  Serial.print(data.az);
  Serial.print(",");

  Serial.print(data.gx);
  Serial.print(",");

  Serial.print(data.gy);
  Serial.print(",");

  Serial.println(data.gz);
}

void setup()
{
  Serial.begin(115200);

  WiFi.mode(WIFI_STA);

  Serial.print("Receiver MAC: ");
  Serial.println(WiFi.macAddress());

  if (esp_now_init() != ESP_OK)
  {
    Serial.println("ESP-NOW Init Failed");
    while (1);
  }

  esp_now_register_recv_cb(onReceive);

  Serial.println("Receiver Ready");
}

void loop()
{
}