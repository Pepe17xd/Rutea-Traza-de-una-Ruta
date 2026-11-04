#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string>

namespace hector {
struct GpsFix {
  bool has_position = false;
  bool fix_valid = false;
  double latitude = 0, longitude = 0;
  bool has_speed = false, has_course = false;
  float speed_mps = 0, course_deg = 0;
  bool has_satellites = false, has_hdop = false;
  uint8_t satellites = 0;
  float hdop = 0;
  bool has_hacc = false;
  float hacc_m = 0;
  std::string accuracy_source;
  std::string accuracy_status = "UNAVAILABLE";
  // UTC ISO-8601 from the sensor (not host receive time).
  std::string timestamp;
  uint32_t received_ms = 0;
  uint32_t itow_ms = 0;
  std::string source = "PHYSICAL";
};

class GpsParser {
 public:
  void feed(uint8_t byte, uint32_t received_ms);
  bool takeFix(GpsFix &out);
  uint32_t nmeaChecksumErrors() const { return nmea_errors_; }
  uint32_t ubxChecksumErrors() const { return ubx_errors_; }
  uint32_t malformedFrames() const { return malformed_; }
 private:
  void handleNmea(const char *line, uint32_t received_ms);
  void handleUbx(uint32_t received_ms);
  void attachHacc();
  char nmea_[128]{}; size_t nmea_len_ = 0;
  uint8_t ubx_[96]{}; size_t ubx_len_ = 0, ubx_expected_ = 0;
  bool in_nmea_ = false, in_ubx_ = false, ubx_sync2_ = false;
  GpsFix latest_{}; bool available_ = false;
  uint32_t nmea_errors_ = 0, ubx_errors_ = 0, malformed_ = 0;
  std::string rmc_timestamp_;
  uint32_t timeutc_ms_ = 0, timeutc_itow_ = 0; std::string timeutc_timestamp_;
  uint32_t pos_itow_ = 0; double pos_lat_ = 0, pos_lon_ = 0;
  float pos_hacc_m_ = 0; uint32_t pos_received_ms_ = 0; bool pos_available_ = false;
};
}
