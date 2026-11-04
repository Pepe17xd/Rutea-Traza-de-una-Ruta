#pragma once
#include <Arduino.h>
#include "hector/reconnect_policy.h"
namespace hector {
class WifiManager {
 public:
  void begin(); void tick(); bool connected() const;
 private: bool begun_=false; ReconnectPolicy reconnect_;
};
}
