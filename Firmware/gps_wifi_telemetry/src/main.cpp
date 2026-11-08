#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <TinyGPSPlus.h>
#include <time.h>
#include <Preferences.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#if __has_include("secrets.wifi.h")
#include "secrets.wifi.h"
#endif
#include "sequence_reservation.h"
#ifndef RUTEA_WIFI_SSID
#define RUTEA_WIFI_SSID ""
#define RUTEA_WIFI_PASSWORD ""
#define RUTEA_DEVICE_TOKEN ""
#define RUTEA_API_BASE_URL ""
#define RUTEA_TLS_CA_CERT ""
#define RUTEA_ROBOT_ID "CAR_01"
#define RUTEA_DEVICE_ID "esp32-hector-01"
#define RUTEA_SEQUENCE_BASE 0ULL
#endif
#ifndef RUTEA_SEQUENCE_BASE
#define RUTEA_SEQUENCE_BASE 0ULL
#endif
#ifndef RUTEA_SEQUENCE_BASE_CONFIGURED
#define RUTEA_SEQUENCE_BASE_CONFIGURED 0
#endif

#ifndef RUTEA_ENABLE_TELEMETRY
#define RUTEA_ENABLE_TELEMETRY 0
#endif
#ifndef RUTEA_TELEMETRY_ONE_SHOT
#define RUTEA_TELEMETRY_ONE_SHOT 0
#endif

namespace {
constexpr int GPS_RX = 16, GPS_TX = 17;
constexpr uint32_t GPS_BAUD = 9600, REPORT_MS = 2000, GPS_MAX_AGE_MS = 5000;
HardwareSerial gpsSerial(2);
TinyGPSPlus gps;
uint32_t lastNmea = 0, lastReport = 0, lastPost = 0, lastPass = 0;
uint64_t sequenceNo = 0;
bool gotNmea = false;
Preferences preferences;
rutea::SequenceReservation sequenceReservation;
rutea::OneShotGate oneShotGate;
bool sequenceReady = false;
struct TelemetryFrame { char json[1536]; };
QueueHandle_t telemetryQueue = nullptr;
String isoNow() {
  time_t t = time(nullptr);
  if (t < 1760000000) return "";
  struct tm u; gmtime_r(&t, &u); char out[25];
  strftime(out, sizeof(out), "%Y-%m-%dT%H:%M:%SZ", &u); return String(out);
}
bool wifiReady() { return WiFi.status() == WL_CONNECTED; }
void report(uint32_t now) {
  const bool connected = gotNmea && uint32_t(now-lastNmea) <= GPS_MAX_AGE_MS;
  const bool fix = connected && gps.location.isValid() && gps.location.age() <= GPS_MAX_AGE_MS;
  Serial.printf("Wi-Fi: %s", wifiReady() ? "CONNECTED" : "DISCONNECTED");
  if (wifiReady()) Serial.printf(" RSSI=%d dBm IP=%s", WiFi.RSSI(), WiFi.localIP().toString().c_str());
  Serial.println();
  Serial.printf("GPS: %s | NMEA validos=%lu checksum errados=%lu\n",
    !connected ? "SIN COMUNICACION" : fix ? "POSICION VALIDA" : "CONECTADO SIN FIX",
    gps.passedChecksum(), gps.failedChecksum());
  if (fix) Serial.printf("lat=%.6f lon=%.6f alt_m=%.2f sat=%lu\n",
    gps.location.lat(), gps.location.lng(), gps.altitude.isValid()?gps.altitude.meters():NAN,
    gps.satellites.isValid()?gps.satellites.value():0UL);
}
String payload(const String &stamp) {
  const bool fix = gps.location.isValid() && gps.location.age() <= GPS_MAX_AGE_MS;
  String j="{";
  j += "\"robot_id\":\"" + String(RUTEA_ROBOT_ID) + "\",\"device_id\":\"" + String(RUTEA_DEVICE_ID) + "\",\"mission_id\":null,";
  j += "\"sequence\":"+String((unsigned long long)sequenceNo)+",\"timestamp\":\""+stamp+"\",";
  j += "\"lat\":"+(fix?String(gps.location.lat(),8):String("null"))+",\"lon\":"+(fix?String(gps.location.lng(),8):String("null"))+",";
  const bool course = gps.course.isValid() && gps.course.age() <= GPS_MAX_AGE_MS;
  j += "\"heading_deg\":"+(course?String(gps.course.deg(),2):String("null"))+",\"speed_mps\":"+(gps.speed.isValid() && gps.speed.age()<=GPS_MAX_AGE_MS?String(gps.speed.mps(),3):String("null"))+",";
  j += "\"gps_accuracy_m\":null,\"gps_accuracy_status\":\"UNAVAILABLE\",\"gps_accuracy_source\":null,\"gps_accuracy_is_bound\":null,";
  j += "\"gps_fix_valid\":"+String(fix?"true":"false")+",\"gps_satellites\":"+(gps.satellites.isValid()?String(gps.satellites.value()):String("null"))+",\"gps_hdop\":"+(gps.hdop.isValid()?String(gps.hdop.hdop(),2):String("null"))+",\"gps_course_deg\":null,";
  j += "\"imu_accel_mps2\":null,\"imu_gyro_rps\":null,\"heading_source\":\""+(course?String("gps_course"):String("unknown"))+"\",\"heading_quality\":\""+(course?String("COURSE_OVER_GROUND"):String("UNAVAILABLE_NO_MAGNETOMETER"))+"\",";
  char gpsStamp[32];
  String gpsStampJson="null";
  if(gps.date.isValid() && gps.time.isValid()) {
    snprintf(gpsStamp,sizeof(gpsStamp),"%04u-%02u-%02uT%02u:%02u:%02uZ",gps.date.year(),gps.date.month(),gps.date.day(),gps.time.hour(),gps.time.minute(),gps.time.second());
    gpsStampJson=String("\"")+gpsStamp+"\"";
  }
  j += "\"gps_timestamp\":"+gpsStampJson;
  j += ",\"imu_timestamp\":null,\"sensor_timestamp\":\""+stamp+"\",\"sensor_status\":{\"esp32\":\"CONNECTED\",\"wifi\":\"CONNECTED\",\"safety\":\"GPS_ONLY_TEST\",\"gps\":\"FIX_VALID\",\"imu\":\"NOT_TESTED\"},\"data_source\":\"PHYSICAL\",\"status\":\"IDLE\"}";
  return j;
}
bool postTelemetry(const String &json) {
  if (!wifiReady() || !RUTEA_API_BASE_URL[0] || !RUTEA_DEVICE_TOKEN[0]) { Serial.println("POST omitido: Wi-Fi, URL o token no configurado"); return false; }
  String base=RUTEA_API_BASE_URL; while(base.endsWith("/")) base.remove(base.length()-1);
  const String url=base.endsWith("/api/v1")?base+"/telemetry":base+"/api/v1/telemetry";
  // HTTPClient retains a pointer to its NetworkClient. Keep the secure client
  // alive until after http.end() disconnects and clears that pointer.
  WiFiClientSecure client;
  HTTPClient http; http.setConnectTimeout(3000); http.setTimeout(3000);
  int code=0;
  if(url.startsWith("https://")) {
    if(!RUTEA_TLS_CA_CERT[0]) { Serial.println("POST omitido: falta CA TLS"); return false; }
    client.setCACert(RUTEA_TLS_CA_CERT);
    if(!http.begin(client,url)) return false;
    http.addHeader("Content-Type","application/json"); http.addHeader("X-Device-Token",RUTEA_DEVICE_TOKEN); code=http.POST(json);
  } else { Serial.println("POST error: HTTPS requerido"); return false; }
  http.end(); Serial.printf("POST telemetry HTTP %d\n",code); return code>=200&&code<300;
}
bool loadSequence(uint64_t &next, void*) {
  if (!preferences.isKey("seq_next")) return false;
  next=preferences.getULong64("seq_next",0); return next!=0;
}
bool storeSequence(uint64_t next, void*) { return preferences.putULong64("seq_next",next)==sizeof(uint64_t); }
void networkTask(void*) {
  TelemetryFrame frame;
  Serial.println("RED: networkTask ejecutandose; esperando cola.");
  for (;;) {
    if (xQueueReceive(telemetryQueue,&frame,portMAX_DELAY)==pdTRUE) {
      Serial.println("RED: frame recibido; iniciando intento HTTPS.");
      const bool accepted=postTelemetry(String(frame.json));
      if (accepted) Serial.println("Telemetria aceptada por API.");
      else Serial.println("Intento finalizado; no se reintenta esta lectura.");
    }
  }
}
}
void setup() {
  Serial.begin(115200); gpsSerial.begin(GPS_BAUD,SERIAL_8N1,GPS_RX,GPS_TX);
  Serial.println("RUTEA GPS+Wi-Fi; UART2 9600 8N1; sin comandos ni actuadores.");
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  if (RUTEA_WIFI_SSID[0]) { WiFi.begin(RUTEA_WIFI_SSID,RUTEA_WIFI_PASSWORD); }
  else Serial.println("Configure credenciales locales; valores no se imprimen.");
  const bool sequenceBaseConfigured = RUTEA_SEQUENCE_BASE_CONFIGURED == 1;
  const bool nvsReady = preferences.begin("rutea-gps",false);
  if (!nvsReady) Serial.println("NVS no disponible; telemetria bloqueada.");
  else if (!sequenceBaseConfigured) Serial.println("Falta base sequence validada; telemetria bloqueada.");
  else sequenceReady=sequenceReservation.begin(RUTEA_SEQUENCE_BASE,loadSequence,storeSequence,nullptr);
  const bool oneShotKeyPresent = nvsReady && preferences.isKey("oneshot_done");
  const bool oneShotConsumed = oneShotKeyPresent && preferences.getBool("oneshot_done",false);
  if (RUTEA_TELEMETRY_ONE_SHOT && oneShotKeyPresent)
    oneShotGate.restoreAttempted(oneShotConsumed);
  if (RUTEA_TELEMETRY_ONE_SHOT) {
    const char *nvsState = !nvsReady ? "NVS_NO_DISPONIBLE" :
      !oneShotKeyPresent ? "CLAVE_AUSENTE" : oneShotConsumed ? "CONSUMIDO" : "PENDIENTE";
    Serial.printf("ONE_SHOT NVS: %s\n", nvsState);
  }
  if (!sequenceReady) Serial.println("Reserva de sequence no disponible; telemetria bloqueada.");
  telemetryQueue=xQueueCreate(1,sizeof(TelemetryFrame));
  if (!telemetryQueue) { Serial.println("No se pudo crear cola de red; POST permanece inactivo."); }
  else {
    const BaseType_t taskResult = xTaskCreatePinnedToCore(networkTask,"rutea_network",8192,nullptr,1,nullptr,0);
    Serial.printf("RED: tarea %s\n", taskResult == pdPASS ? "CREADA" : "NO CREADA");
  }
  Serial.printf("GATE: telemetry=%s sequence=%s one_shot=%s queue=%s\n",
    RUTEA_ENABLE_TELEMETRY ? "ON" : "OFF", sequenceReady ? "READY" : "BLOCKED",
    (!RUTEA_TELEMETRY_ONE_SHOT || !oneShotGate.attempted()) ? "READY" : "CONSUMED",
    telemetryQueue ? "READY" : "MISSING");
  Serial.printf("Publicacion compilada: %s\n", RUTEA_ENABLE_TELEMETRY ? "HABILITADA" : "DESHABILITADA");
}
void loop() {
  while(gpsSerial.available()) { gps.encode(char(gpsSerial.read())); if(gps.passedChecksum()!=lastPass) {lastPass=gps.passedChecksum(); lastNmea=millis(); gotNmea=true;} }
  const uint32_t now=millis();
  static int8_t lastClockState = -1;
  const bool clockReady = time(nullptr) >= 1760000000;
  if (lastClockState != static_cast<int8_t>(clockReady)) {
    Serial.printf("SNTP: %s\n", clockReady ? "HORA_VALIDA" : "PENDIENTE");
    lastClockState = static_cast<int8_t>(clockReady);
  }
  static bool sntpConfigured = false;
  if (wifiReady() && !sntpConfigured) {
    configTime(0,0,"pool.ntp.org","time.nist.gov");
    sntpConfigured = true;
    Serial.println("SNTP configurado; esperando sincronizacion de hora.");
  }
  if(now-lastReport>=REPORT_MS) {lastReport=now; report(now);}
  const bool sendingEnabled = RUTEA_ENABLE_TELEMETRY && sequenceReady &&
    (!RUTEA_TELEMETRY_ONE_SHOT || !oneShotGate.attempted());
  const uint32_t readinessCheckMs = RUTEA_TELEMETRY_ONE_SHOT ? 1000U : 10000U;
  if(sendingEnabled && wifiReady() && now-lastPost>=readinessCheckMs) {
    lastPost=now; const String ts=isoNow();
    const bool recentNmea = gotNmea && now-lastNmea<=GPS_MAX_AGE_MS;
    const bool recentFix = recentNmea && gps.location.isValid() && gps.location.age()<=GPS_MAX_AGE_MS;
    if(!ts.length()) Serial.println("POST omitido: hora SNTP aun no sincronizada");
    else if(!recentFix) Serial.println("POST omitido: fix GPS no reciente o invalido");
    if(ts.length() && recentFix) {
      TelemetryFrame frame{};
      uint64_t reserved=0;
      if (!sequenceReservation.reserve(reserved)) { Serial.println("Reserva NVS fallida; telemetria detenida."); return; }
      sequenceNo=reserved;
      String json=payload(ts);
      if (telemetryQueue && json.length()<sizeof(frame.json)) {
        json.toCharArray(frame.json,sizeof(frame.json));
        if (RUTEA_TELEMETRY_ONE_SHOT) {
          if (!oneShotGate.claimAttempt(true)) return;
          if (preferences.putBool("oneshot_done",true)!=1) { Serial.println("No se pudo persistir ONE_SHOT; POST bloqueado."); return; }
        }
        if (xQueueSend(telemetryQueue,&frame,0)!=pdTRUE) Serial.println("Cola de red ocupada; envio detenido.");
      } else if (json.length() >= sizeof(frame.json)) Serial.println("POST omitido: payload excede el buffer.");
    } else Serial.println("POST omitido: falta hora valida o fix GPS reciente");
  }
  delay(1);
}
