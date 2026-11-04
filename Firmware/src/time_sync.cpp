#include "hector/time_sync.h"
#include <time.h>
namespace hector {
void beginTimeSync() { configTime(0,0,"pool.ntp.org","time.nist.gov"); }
bool utcTimeReady() { return time(nullptr)>1760000000; }
String utcNowIso() {
  if(!utcTimeReady()) return String(); time_t t=time(nullptr); struct tm tmv; gmtime_r(&t,&tmv);
  char b[25]; strftime(b,sizeof(b),"%Y-%m-%dT%H:%M:%SZ",&tmv); return String(b);
}
String utcAtMillisIso(uint32_t sample_ms) {
  if(!utcTimeReady()) return String(); const uint32_t age=millis()-sample_ms;
  time_t t=time(nullptr)-time_t(age/1000); struct tm tmv; gmtime_r(&t,&tmv);
  char b[25]; strftime(b,sizeof(b),"%Y-%m-%dT%H:%M:%SZ",&tmv); return String(b);
}
}
