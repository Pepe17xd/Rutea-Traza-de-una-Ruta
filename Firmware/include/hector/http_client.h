#pragma once
#include <Arduino.h>
#include "hector/mission_protocol.h"
namespace hector {
struct PostResult { bool accepted=false; int http_status=0; String message; };
struct DestinationPollResult { bool available=false; int http_status=0; uint64_t sequence=0; uint64_t expires_at_epoch_s=0; String mission_id; DestinationCommandV1 destination; String payload; String error; };
PostResult postTelemetry(const String &json);
DestinationPollResult pollNextDestination();
PostResult acknowledgeDestination(const String &missionId, uint64_t sequence, const String &payload, const String &status);
}
