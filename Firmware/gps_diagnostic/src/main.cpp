#include <Arduino.h>
#include <TinyGPSPlus.h>

namespace {
constexpr int GPS_RX = 16;
constexpr int GPS_TX = 17;
constexpr uint32_t GPS_BAUD = 9600;
constexpr uint32_t REPORT_MS = 2000;
constexpr uint32_t FRESH_MS = 5000;
HardwareSerial gpsSerial(2);
TinyGPSPlus gps;
uint32_t lastReport = 0;
uint32_t lastSentence = 0;
uint32_t lastValidCount = 0;
bool seenSentence = false;

void report(uint32_t now) {
  const bool communicating = seenSentence && uint32_t(now - lastSentence) <= FRESH_MS;
  const bool position = communicating && gps.location.isValid() && gps.location.age() <= FRESH_MS;
  Serial.print("Estado: ");
  Serial.println(!communicating ? "SIN COMUNICACION NMEA VALIDA" :
                 position ? "POSICION VALIDA" : "CONECTADO SIN POSICION VALIDA");
  Serial.printf("Bytes: %lu | frases validas: %lu | checksum fallidos: %lu\n",
                gps.charsProcessed(), gps.passedChecksum(), gps.failedChecksum());
  if (position) {
    Serial.printf("Latitud: %.6f | Longitud: %.6f\n", gps.location.lat(), gps.location.lng());
  } else {
    Serial.println("Latitud: -- | Longitud: --");
  }
  if (communicating && gps.altitude.isValid() && gps.altitude.age() <= FRESH_MS)
    Serial.printf("Altitud: %.2f m\n", gps.altitude.meters());
  else Serial.println("Altitud: --");
  if (communicating && gps.satellites.isValid() && gps.satellites.age() <= FRESH_MS)
    Serial.printf("Satelites: %lu\n", gps.satellites.value());
  else Serial.println("Satelites: --");
}
}

void setup() {
  Serial.begin(115200);
  gpsSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX, GPS_TX);
  Serial.println("Diagnostico GPS: UART2 RX=16 TX=17 9600 8N1; sin Wi-Fi.");
}

void loop() {
  while (gpsSerial.available()) {
    gps.encode(static_cast<char>(gpsSerial.read()));
    const uint32_t count = gps.passedChecksum();
    if (count != lastValidCount) {
      lastValidCount = count;
      lastSentence = millis();
      seenSentence = true;
    }
  }
  const uint32_t now = millis();
  if (uint32_t(now - lastReport) >= REPORT_MS) {
    lastReport = now;
    report(now);
  }
  delay(1);
}
