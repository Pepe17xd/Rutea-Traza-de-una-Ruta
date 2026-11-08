#pragma once
#include <stdint.h>

namespace rutea {
// Store/load callbacks persist the NEXT sequence value. A failed store never
// returns a sequence, so a POST cannot reuse a value after reboot.
class SequenceReservation {
 public:
  using Load = bool (*)(uint64_t &next, void *context);
  using Store = bool (*)(uint64_t next, void *context);

  bool begin(uint64_t acceptedBase, Load load, Store store, void *context) {
    if (!load || !store) return false;
    uint64_t saved = 0;
    const bool hasSaved = load(saved, context);
    next_ = hasSaved && saved > acceptedBase ? saved : acceptedBase + 1;
    if (next_ == 0 || next_ <= acceptedBase) return false;
    if (!hasSaved || saved < next_) {
      if (!store(next_, context)) return false;
    }
    store_ = store; context_ = context; ready_ = true;
    return true;
  }

  bool reserve(uint64_t &sequence) {
    if (!ready_ || next_ == UINT64_MAX) return false;
    const uint64_t reserved = next_;
    if (!store_(reserved + 1, context_)) { ready_ = false; return false; }
    next_ = reserved + 1;
    sequence = reserved;
    return true;
  }

 private:
  uint64_t next_ = 0;
  Store store_ = nullptr;
  void *context_ = nullptr;
  bool ready_ = false;
};

class OneShotGate {
 public:
  void restoreAttempted(bool attempted) { attempted_ = attempted; }
  bool claimAttempt(bool enabled) {
    if (!enabled || attempted_) return false;
    attempted_ = true;
    return true;
  }
  bool attempted() const { return attempted_; }
 private:
  bool attempted_ = false;
};
}  // namespace rutea
