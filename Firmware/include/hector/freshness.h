#pragma once
#include <stdint.h>
namespace hector {
// Unsigned subtraction remains correct across the millis() counter wrap interval.
inline bool sampleFresh(uint32_t now_ms,uint32_t sample_ms,uint32_t max_age_ms) {
  return uint32_t(now_ms-sample_ms)<=max_age_ms;
}
}
