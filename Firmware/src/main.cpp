#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_task_wdt.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <math.h>
#include <time.h>
#include "hector/config.h"
#include "gps_parser.h"
#include "hector/imu_sensor.h"
#include "hector/wifi_manager.h"
#include "hector/time_sync.h"
#include "hector/http_client.h"
#include "hector/safety.h"
#include "hector/freshness.h"

using namespace hector;
static HardwareSerial gpsSerial(2);
static GpsParser gpsParser;
static Mpu6050Sensor imuSensor;
static WifiManager wifi;
static SafetySupervisor safety;
static Preferences prefs;
struct TelemetryFrame { char json[2048]; };
static QueueHandle_t telemetryQueue=nullptr;
static GpsFix gpsFix;
static ImuSample imuSample;
static bool gotGps=false, gotImu=false, imuReady=false;
static uint32_t lastImuRead=0, lastPublish=0, lastImuRetry=0, sequenceNo=0;
static bool sequenceStoreReady=false;
static uint64_t lastCommandSequence=0;
static String lastCommandMission;
static const float nominalPublishHz=1000.0f/HECTOR_HEARTBEAT_MS;

static String jsonNumber(double value,int decimals=6) { if(!isfinite(value)) return "null"; return String(value,decimals); }
static String isoOrNull(const String &value) { if(!value.length()) return String("null"); String quoted="\""; quoted+=value; quoted+="\""; return quoted; }
static String gpsMeasurementTime() { return gotGps&&gpsFix.timestamp.length()?String(gpsFix.timestamp.c_str()):String(); }
static String makePayload(uint32_t now,uint32_t sequence) {
  const bool gpsFresh=gotGps && gpsFix.fix_valid && gpsFix.has_position && sampleFresh(now,gpsFix.received_ms,HECTOR_GPS_MAX_AGE_MS);
  const bool gpsObservationFresh=gotGps && sampleFresh(now,gpsFix.received_ms,HECTOR_GPS_MAX_AGE_MS);
  const bool gpsQuality=gpsFresh && gpsFix.has_satellites && gpsFix.satellites>=HECTOR_GPS_MIN_SATELLITES
      && gpsFix.has_hdop && gpsFix.hdop<=HECTOR_GPS_MAX_HDOP;
  const bool imuFresh=gotImu && imuSample.valid && sampleFresh(now,imuSample.received_ms,HECTOR_IMU_MAX_AGE_MS);
  const SafetyState state=safety.evaluate(wifi.connected(),imuReady&&imuFresh,gpsQuality,
      gotGps?uint32_t(now-gpsFix.received_ms):UINT32_MAX,gotImu?uint32_t(now-imuSample.received_ms):UINT32_MAX);
  const String timestamp=utcNowIso();
  const bool hacc=gpsFresh&&gpsFix.has_hacc;
  const bool course=gpsFresh&&gpsFix.has_course&&gpsFresh&&gpsFix.has_speed&&gpsFix.speed_mps>=0.5f;
  String out="{";
  const String gpsStamp=gpsObservationFresh?gpsMeasurementTime():String();
  const String imuStamp=imuFresh?utcAtMillisIso(imuSample.received_ms):String();
  String sensorStamp=gpsStamp;
  if(sensorStamp.length()==0 || (imuStamp.length()>0 && imuStamp.compareTo(sensorStamp)>0)) sensorStamp=imuStamp;
  out+="\"robot_id\":\"" HECTOR_ROBOT_ID "\",\"device_id\":\"" HECTOR_DEVICE_ID "\",\"mission_id\":null,";
  out+="\"sequence\":"+String(sequence)+",\"timestamp\":\""+timestamp+"\",";
  out+="\"lat\":"+(gpsFresh?jsonNumber(gpsFix.latitude,8):String("null"))+",\"lon\":"+(gpsFresh?jsonNumber(gpsFix.longitude,8):String("null"))+",";
  out+="\"heading_deg\":"+(course?jsonNumber(gpsFix.course_deg,2):String("null"))+",\"speed_mps\":"+(gpsFresh&&gpsFix.has_speed?jsonNumber(gpsFix.speed_mps,3):String("null"))+",";
  out+="\"gps_accuracy_m\":"+(hacc?jsonNumber(gpsFix.hacc_m,3):String("null"))+",\"gps_accuracy_status\":\""+(hacc?String("ESTIMATED"):String("UNAVAILABLE"))+"\",";
  out+="\"gps_accuracy_source\":"+(hacc?String("\"UBX_NAV_POSLLH.hAcc\""):String("null"))+",\"gps_accuracy_is_bound\":"+(hacc?String("false"):String("null"))+",";
  out+="\"gps_fix_valid\":"+(gpsFresh?String("true"):String("false"))+",\"gps_satellites\":"+(gpsFresh&&gpsFix.has_satellites?String(gpsFix.satellites):String("null"))+",";
  out+="\"gps_hdop\":"+(gpsFresh&&gpsFix.has_hdop?jsonNumber(gpsFix.hdop,2):String("null"))+",\"gps_course_deg\":"+(course?jsonNumber(gpsFix.course_deg,2):String("null"))+",";
  out+="\"imu_accel_mps2\":"+(imuFresh?String("{\"x\":")+jsonNumber(imuSample.accel[0],4)+",\"y\":"+jsonNumber(imuSample.accel[1],4)+",\"z\":"+jsonNumber(imuSample.accel[2],4)+"}":String("null"))+",";
  out+="\"imu_gyro_rps\":"+(imuFresh?String("{\"x\":")+jsonNumber(imuSample.gyro[0],5)+",\"y\":"+jsonNumber(imuSample.gyro[1],5)+",\"z\":"+jsonNumber(imuSample.gyro[2],5)+"}":String("null"))+",";
  out+="\"heading_source\":\""+(course?String("gps_course"):String("unknown"))+"\",\"heading_quality\":\""+(course?String("COURSE_OVER_GROUND_NO_SLIP_ASSUMPTION"):String("UNAVAILABLE_NO_MAGNETOMETER"))+"\",";
  out+="\"gps_timestamp\":"+isoOrNull(gpsStamp)+",\"imu_timestamp\":"+isoOrNull(imuStamp)+",";
  out+="\"sensor_timestamp\":"+isoOrNull(sensorStamp)+",\"sensor_status\":{";
  out+="\"esp32\":\"CONNECTED\",\"wifi\":\""+(wifi.connected()?String("CONNECTED"):String("DISCONNECTED"))+"\",\"wifi_rssi_dbm\":\""+(wifi.connected()?String(WiFi.RSSI()):String("unavailable"))+"\",";
  out+="\"safety\":\""+String(stateName(state))+"\",\"gps\":\""+(gpsFresh?String("FIX_VALID"):gotGps?String(gpsFix.fix_valid?"STALE":"NO_FIX"):String("NO_DATA"))+"\",\"imu\":\""+(imuFresh?String("CONNECTED"):String(imuSensor.error()))+"\",\"imu_error\":\""+String(imuSensor.error())+"\",";
  out+="\"gps_nmea_checksum_errors\":\""+String(gpsParser.nmeaChecksumErrors())+"\",\"gps_ubx_checksum_errors\":\""+String(gpsParser.ubxChecksumErrors())+"\",\"gps_malformed_frames\":\""+String(gpsParser.malformedFrames())+"\",";
  out+="\"gps_accuracy_source\":\""+(hacc?String("UBX_NAV_POSLLH.hAcc"):String("UNAVAILABLE"))+"\",\"gps_quality\":\""+(gpsQuality?String("SUFFICIENT"):String("INSUFFICIENT_OR_UNKNOWN"))+"\",\"publish_hz\":\""+String(nominalPublishHz,2)+"\",\"publish_period_ms\":\""+String(HECTOR_HEARTBEAT_MS)+"\",\"api\":\"PENDING\"},";
  out+="\"data_source\":\"PHYSICAL\",\"status\":\"IDLE\"}";
  return out;
}

static void readGps(uint32_t now) {
  while(gpsSerial.available()) gpsParser.feed(uint8_t(gpsSerial.read()),now);
  GpsFix next; while(gpsParser.takeFix(next)) { gpsFix=next; gotGps=true; }
}
#if HECTOR_ENABLE_UBX_OUTPUTS
static void requestUbxMessage(uint8_t messageId) {
  // CFG-MSG for UART1: enable one message per navigation epoch on the GPS receiver's UART1.
  uint8_t frame[16]={0xB5,0x62,0x06,0x01,0x08,0x00,0x01,messageId,0x00,0x01,0x00,0x00,0x00,0x00,0x00,0x00};
  uint8_t a=0,b=0; for(int i=2;i<14;i++){a=uint8_t(a+frame[i]);b=uint8_t(b+a);} frame[14]=a;frame[15]=b;
  gpsSerial.write(frame,sizeof(frame)); gpsSerial.flush(); delay(40);
}
#endif
static void retryImu(uint32_t now) {
  if(imuReady || (lastImuRetry && uint32_t(now-lastImuRetry)<5000)) return;
  lastImuRetry=now; Wire.begin(HECTOR_IMU_SDA_PIN,HECTOR_IMU_SCL_PIN);
  if(imuSensor.begin(Wire,HECTOR_IMU_ADDRESS)) { imuReady=imuSensor.calibrateGyro(200,5); if(!imuReady) Serial.printf("IMU calibration failed: %s\n",imuSensor.error()); }
  else Serial.printf("IMU unavailable: %s\n",imuSensor.error());
}
static void networkTask(void *) {
  TelemetryFrame frame;
  uint32_t lastCommandPoll=millis()-HECTOR_COMMAND_POLL_MS;
  for(;;) {
    if(xQueueReceive(telemetryQueue,&frame,pdMS_TO_TICKS(HECTOR_COMMAND_POLL_MS))==pdTRUE) {
      PostResult result=postTelemetry(String(frame.json));
      Serial.printf("telemetry %s: %s\n",result.accepted?"accepted":"not accepted",result.message.c_str());
    }
    const uint32_t pollNow=millis();
    if(uint32_t(pollNow-lastCommandPoll)<HECTOR_COMMAND_POLL_MS) continue;
    if(!WiFi.isConnected() || !utcTimeReady()) continue;
    lastCommandPoll=pollNow;
    DestinationPollResult command=pollNextDestination();
    if(!command.available) { if(command.error.length()) Serial.printf("destination poll: %s\n",command.error.c_str()); continue; }
    DestinationCommandV1 validated{};
    const DestinationDecision decision=inspectDestination(command.sequence,command.expires_at_epoch_s,
      uint64_t(time(nullptr)),command.mission_id.c_str(),lastCommandMission.c_str(),lastCommandSequence,
      command.payload.c_str(),command.payload.length(),validated);
    String ackStatus="RECEIVED";
    if(decision==DestinationDecision::REJECT_OBSOLETE) ackStatus="REJECTED_DUPLICATE";
    else if(decision==DestinationDecision::REJECT_EXPIRED) ackStatus="REJECTED_EXPIRED";
    else if(decision==DestinationDecision::REJECT_INVALID) ackStatus="REJECTED_INVALID";
    else if(decision==DestinationDecision::ACCEPT_NEW) {
      lastCommandSequence=command.sequence; lastCommandMission=command.mission_id;
      const bool seqSaved=prefs.putULong64("cmd_seq",lastCommandSequence)==sizeof(uint64_t);
      const bool idSaved=prefs.putString("cmd_mission",lastCommandMission)==lastCommandMission.length();
      if(!(seqSaved&&idSaved)) { ackStatus="REJECTED_INVALID"; Serial.println("destination not acknowledged: local idempotency store failed"); }
      else Serial.printf("destination received for mission %s (not executed; motor control disabled)\n",command.mission_id.c_str());
    } else {
      Serial.printf("idempotent destination redelivery for mission %s; no re-application\n",command.mission_id.c_str());
    }
    PostResult ack=acknowledgeDestination(command.mission_id,command.sequence,command.payload,ackStatus);
    Serial.printf("destination receipt %s: %s (mission=%s, seq=%llu)\n",ack.accepted?"accepted":"not accepted",ack.message.c_str(),command.mission_id.c_str(),(unsigned long long)command.sequence);
  }
}

void setup() {
  Serial.begin(115200); delay(200);
  esp_task_wdt_config_t watchdogConfig{}; watchdogConfig.timeout_ms=5000;
  watchdogConfig.idle_core_mask=(1U<<portNUM_PROCESSORS)-1; watchdogConfig.trigger_panic=true;
  esp_err_t watchdogResult=esp_task_wdt_init(&watchdogConfig);
  if(watchdogResult==ESP_ERR_INVALID_STATE) esp_task_wdt_reconfigure(&watchdogConfig);
  esp_task_wdt_add(nullptr);
  Serial.println("HECTOR ESP32 firmware V1.2; motor outputs are not implemented.");
  gpsSerial.begin(HECTOR_GPS_BAUD,SERIAL_8N1,HECTOR_GPS_RX_PIN,HECTOR_GPS_TX_PIN);
  if(prefs.begin("hector",false)) {
    const uint32_t limit=prefs.getUInt("sequence_limit",0);
    if(limit<=UINT32_MAX-2048) { sequenceNo=limit+1; sequenceStoreReady=prefs.putUInt("sequence_limit",limit+1024)==sizeof(uint32_t); }
    lastCommandSequence=prefs.getULong64("cmd_seq",0); lastCommandMission=prefs.getString("cmd_mission","");
  }
  if(!sequenceStoreReady) Serial.println("FATAL: sequence storage unavailable; telemetry is disabled to protect idempotency.");
  telemetryQueue=xQueueCreate(1,sizeof(TelemetryFrame));
  if(!telemetryQueue) { Serial.println("FATAL: telemetry queue allocation failed"); while(true) delay(1000); }
  xTaskCreate(networkTask,"hector_network",8192,nullptr,1,nullptr);
  wifi.begin(); beginTimeSync(); retryImu(millis()); safety.feedWatchdog();
#if HECTOR_ENABLE_UBX_OUTPUTS
  requestUbxMessage(0x02); // NAV-POSLLH (includes hAcc)
  requestUbxMessage(0x21); // NAV-TIMEUTC (UTC validity and epoch association)
  Serial.println("Requested UBX NAV-POSLLH and NAV-TIMEUTC on GPS UART; verify receiver support via telemetry hAcc.");
#endif
}
void loop() {
  const uint32_t now=millis(); readGps(now); wifi.tick(); retryImu(now);
  if(imuReady && uint32_t(now-lastImuRead)>=50) { lastImuRead=now; ImuSample next; if(imuSensor.read(next)) { imuSample=next; gotImu=true; } else { imuReady=false; gotImu=false; Serial.printf("IMU read failed: %s\n",imuSensor.error()); } }
  safety.feedWatchdog(); esp_task_wdt_reset();
  if(sequenceStoreReady && wifi.connected() && utcTimeReady() && uint32_t(now-lastPublish)>=HECTOR_HEARTBEAT_MS) {
    lastPublish=now;
    String payload=makePayload(now,sequenceNo); TelemetryFrame frame{};
    if(payload.length()<sizeof(frame.json)) { payload.toCharArray(frame.json,sizeof(frame.json)); xQueueOverwrite(telemetryQueue,&frame); ++sequenceNo; }
    else Serial.println("telemetry dropped: payload exceeds fixed queue frame");
  }
  delay(2);
}
