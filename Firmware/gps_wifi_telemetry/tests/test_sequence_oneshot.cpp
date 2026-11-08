#include <cassert>
#include <cstdint>
#include "sequence_reservation.h"

struct FakeNvs { uint64_t next=0; bool present=false; bool failStore=false; };
static bool load(uint64_t &v, void *p) { auto &n=*static_cast<FakeNvs*>(p); if(!n.present)return false;v=n.next;return true; }
static bool save(uint64_t v, void *p) { auto &n=*static_cast<FakeNvs*>(p);if(n.failStore)return false;n.next=v;n.present=true;return true; }

int main() {
  FakeNvs empty;
  rutea::SequenceReservation initial;
  assert(initial.begin(0,load,save,&empty));
  uint64_t first=0;
  assert(initial.reserve(first)&&first==1&&empty.next==2);

  FakeNvs existing; existing.next=73; existing.present=true;
  rutea::SequenceReservation keepExisting;
  assert(keepExisting.begin(0,load,save,&existing));
  assert(keepExisting.reserve(first)&&first==73&&existing.next==74);

  FakeNvs nvs;
  rutea::SequenceReservation a;
  assert(a.begin(40,load,save,&nvs));
  uint64_t seq=0;
  assert(a.reserve(seq)&&seq==41&&nvs.next==42); // persisted before caller can POST
  rutea::SequenceReservation afterReboot;
  assert(afterReboot.begin(40,load,save,&nvs));
  assert(afterReboot.reserve(seq)&&seq==42&&nvs.next==43);

  nvs.failStore=true;
  assert(!afterReboot.reserve(seq)); // never returns an unpersisted sequence
  rutea::SequenceReservation storageFailure;
  assert(!storageFailure.begin(50,load,save,&nvs));

  rutea::OneShotGate gate;
  assert(!gate.claimAttempt(false));
  assert(gate.claimAttempt(true)); // first POST may succeed, fail, or timeout
  assert(gate.attempted());
  assert(!gate.claimAttempt(true)); // HTTP outcome cannot unlock a second POST
  rutea::OneShotGate rebootedGate;
  rebootedGate.restoreAttempted(true); // ONE_SHOT latch is stored before POST
  assert(!rebootedGate.claimAttempt(true));
  for (int outcome=-1; outcome<=1; ++outcome) { // timeout, HTTP error, HTTP success
    rutea::OneShotGate resultGate;
    assert(resultGate.claimAttempt(true));
    (void)outcome;
    assert(!resultGate.claimAttempt(true));
  }
}
