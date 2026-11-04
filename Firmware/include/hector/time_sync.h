#pragma once
#include <Arduino.h>
namespace hector {
void beginTimeSync(); bool utcTimeReady(); String utcNowIso(); String utcAtMillisIso(uint32_t sample_ms);
}
