#pragma once
#include <stdint.h>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <cstring>
namespace hector {
// Versioned local contract. Destinations are accepted as data only; motors remain absent.
struct MissionEnvelopeV1 {
  uint16_t protocol_version=1;
  char mission_id[37]{};
  double origin_lat=0, origin_lon=0, destination_lat=0, destination_lon=0;
  float goal_tolerance_m=0, max_speed_mps=0;
  char controller_version[32]{};
  char model_version[32]{};
  char created_at_utc[25]{};
};

struct DestinationCommandV1 { double latitude=0.0, longitude=0.0; };

inline bool parseCoordinate(const char *begin, const char *end, double &value) {
  if (begin == end) return false;
  for (const char *p=begin; p<end; ++p) {
    if (!( (*p>='0' && *p<='9') || *p=='-' || *p=='.' )) return false;
  }
  char buffer[24]{};
  const size_t size=static_cast<size_t>(end-begin);
  if (size>=sizeof(buffer)) return false;
  memcpy(buffer,begin,size);
  char *parsedEnd=nullptr;
  value=strtod(buffer,&parsedEnd);
  return parsedEnd==buffer+size && std::isfinite(value);
}

// Exact wire format: G:<lat>,<lon>\n. Reject CRLF, suffixes and invalid ranges.
inline bool parseDestinationLine(const char *data, size_t length, DestinationCommandV1 &out) {
  if (!data || length<6 || length>52 || data[0]!='G' || data[1]!=':' || data[length-1]!='\n') return false;
  const char *comma=nullptr;
  for (size_t i=2; i+1<length; ++i) if (data[i]==',') {
    if (comma) return false;
    comma=data+i;
  }
  if (!comma) return false;
  double lat=0, lon=0;
  if (!parseCoordinate(data+2,comma,lat) || !parseCoordinate(comma+1,data+length-1,lon)) return false;
  if (lat < -90.0 || lat > 90.0 || lon < -180.0 || lon > 180.0) return false;
  out.latitude=lat; out.longitude=lon;
  return true;
}

enum class DestinationDecision { ACCEPT_NEW, ACK_IDEMPOTENT_DUPLICATE, REJECT_EXPIRED, REJECT_OBSOLETE, REJECT_INVALID };
inline DestinationDecision inspectDestination(uint64_t sequence, uint64_t expiresAt, uint64_t nowEpoch,
    const char *missionId, const char *lastMissionId, uint64_t lastSequence,
    const char *payload, size_t payloadLength, DestinationCommandV1 &out) {
  if (!missionId || !missionId[0] || !parseDestinationLine(payload,payloadLength,out)) return DestinationDecision::REJECT_INVALID;
  if (expiresAt<=nowEpoch) return DestinationDecision::REJECT_EXPIRED;
  if (sequence<lastSequence) return DestinationDecision::REJECT_OBSOLETE;
  if (sequence==lastSequence) return strcmp(missionId,lastMissionId?lastMissionId:"")==0
      ? DestinationDecision::ACK_IDEMPOTENT_DUPLICATE : DestinationDecision::REJECT_OBSOLETE;
  return DestinationDecision::ACCEPT_NEW;
}

inline bool parsePumpWord(const char *data, size_t length, bool &requestedOn) {
  if (!data) return false;
  if (length==2 && data[0]=='O' && data[1]=='N') { requestedOn=true; return true; }
  if (length==3 && data[0]=='O' && data[1]=='F' && data[2]=='F') { requestedOn=false; return true; }
  return false;
}

struct PumpInterlocks {
  bool gps_valid_and_fresh=false;
  bool forward_motion_confirmed=false;
  bool not_turning_in_place=false;
  bool motion_not_stopped=false;
  bool communication_healthy=false;
  bool estop_clear=false;
  bool physical_feedback_available=false;
};

// Predicate grants local authorization only; it has no hardware output side effect.
inline bool mayAuthorizePumpOn(const PumpInterlocks &s) {
  return s.gps_valid_and_fresh && s.forward_motion_confirmed && s.not_turning_in_place
      && s.motion_not_stopped && s.communication_healthy && s.estop_clear
      && s.physical_feedback_available;
}

enum class PumpRequest { OFF, ON };
struct PumpDecision {
  PumpRequest request=PumpRequest::OFF;
  bool on_authorized=false;
  bool state_confirmed=false;
  bool confirmed_on=false;
};
inline PumpDecision assessPumpRequest(PumpRequest request, const PumpInterlocks &interlocks,
    bool feedbackAvailable, bool feedbackSaysOn) {
  PumpDecision result{};
  result.request=request;
  result.on_authorized=request==PumpRequest::ON && mayAuthorizePumpOn(interlocks);
  result.state_confirmed=feedbackAvailable;
  result.confirmed_on=feedbackAvailable && feedbackSaysOn;
  return result;
}
}
