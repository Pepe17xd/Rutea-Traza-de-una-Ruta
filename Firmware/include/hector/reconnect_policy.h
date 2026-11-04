#pragma once
#include <algorithm>
#include <cstdint>
namespace hector {
class ReconnectPolicy {
 public:
  bool due(uint32_t now) const { return static_cast<int32_t>(now-next_attempt_) >= 0; }
  uint32_t schedule(uint32_t now) {
    next_attempt_=now+delay_ms_;
    const uint32_t scheduled=delay_ms_;
    delay_ms_=std::min<uint32_t>(delay_ms_*2,30000);
    return scheduled;
  }
  void reset() { delay_ms_=1000; next_attempt_=0; }
  uint32_t nextAttempt() const { return next_attempt_; }
 private:
  uint32_t delay_ms_=1000;
  uint32_t next_attempt_=0;
};
}
