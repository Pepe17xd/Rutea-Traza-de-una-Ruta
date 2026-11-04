#pragma once
#include <Arduino.h>
#include "hector/config.h"
namespace hector {
enum class SafetyState { DISCONNECTED, CONNECTED, GPS_NO_FIX, READY, SENSOR_ERROR, ESTOP };
inline const char *stateName(SafetyState s) {
  switch(s) { case SafetyState::DISCONNECTED:return "DISCONNECTED"; case SafetyState::CONNECTED:return "CONNECTED";
    case SafetyState::GPS_NO_FIX:return "GPS_NO_FIX"; case SafetyState::READY:return "READY";
    case SafetyState::SENSOR_ERROR:return "SENSOR_ERROR"; default:return "ESTOP"; }
}
class SafetySupervisor {
 public:
  void setEstopActive(bool active) { estop_=active; }
  SafetyState evaluate(bool wifi, bool imuOk, bool gpsFix, uint32_t gpsAge, uint32_t imuAge) const {
    if(estop_) return SafetyState::ESTOP;
    if(!wifi) return SafetyState::DISCONNECTED;
    if(gpsAge==UINT32_MAX && imuAge==UINT32_MAX) return SafetyState::CONNECTED; // Wi-Fi up; first sensor samples not acquired yet.
    if(!imuOk || imuAge>HECTOR_IMU_MAX_AGE_MS) return SafetyState::SENSOR_ERROR;
    if(!gpsFix || gpsAge>HECTOR_GPS_MAX_AGE_MS) return SafetyState::GPS_NO_FIX;
    return SafetyState::READY; // Sensor readiness only. Never authorizes movement.
  }
  void feedWatchdog() { last_feed_=millis(); }
  bool watchdogExpired(uint32_t limit_ms=1500) const { return uint32_t(millis()-last_feed_)>limit_ms; }
 private: bool estop_=false; uint32_t last_feed_=0;
};
}
