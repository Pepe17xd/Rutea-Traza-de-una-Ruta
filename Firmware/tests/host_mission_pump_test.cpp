#include <cassert>
#include <cmath>
#include "hector/mission_protocol.h"
#include "hector/reconnect_policy.h"
using namespace hector;
int main() {
  DestinationCommandV1 destination;
  const char valid[]="G:-12.04640000,-77.04280000\n";
  assert(parseDestinationLine(valid, sizeof(valid)-1, destination));
  assert(std::fabs(destination.latitude + 12.0464) < 1e-8);
  assert(std::fabs(destination.longitude + 77.0428) < 1e-8);
  const char no_newline[]="G:1.0,2.0";
  assert(!parseDestinationLine(no_newline, sizeof(no_newline)-1, destination));
  const char out_of_range[]="G:91,2\n";
  assert(!parseDestinationLine(out_of_range, sizeof(out_of_range)-1, destination));
  const char nan_value[]="G:nan,2\n";
  assert(!parseDestinationLine(nan_value, sizeof(nan_value)-1, destination));
  const char exponent[]="G:1e1,2\n";
  assert(!parseDestinationLine(exponent, sizeof(exponent)-1, destination));
  assert(inspectDestination(8,200,100,"mission-8","mission-7",7,valid,sizeof(valid)-1,destination)==DestinationDecision::ACCEPT_NEW);
  assert(inspectDestination(8,200,100,"mission-8","mission-8",8,valid,sizeof(valid)-1,destination)==DestinationDecision::ACK_IDEMPOTENT_DUPLICATE);
  assert(inspectDestination(8,99,100,"mission-8","mission-8",8,valid,sizeof(valid)-1,destination)==DestinationDecision::REJECT_EXPIRED);
  assert(inspectDestination(7,200,100,"mission-7","mission-8",8,valid,sizeof(valid)-1,destination)==DestinationDecision::REJECT_OBSOLETE);
  assert(inspectDestination(9,99,100,"mission-9","mission-8",8,valid,sizeof(valid)-1,destination)==DestinationDecision::REJECT_EXPIRED);
  bool on=false;
  assert(parsePumpWord("ON",2,on) && on);
  assert(parsePumpWord("OFF",3,on) && !on);
  assert(!parsePumpWord("on",2,on));
  assert(!parsePumpWord("ON\n",3,on));
  PumpInterlocks state;
  PumpDecision defaultPump{};
  assert(defaultPump.request==PumpRequest::OFF && !defaultPump.on_authorized && !defaultPump.state_confirmed);
  assert(!mayAuthorizePumpOn(state));
  state={true,true,true,true,true,true,true}; assert(mayAuthorizePumpOn(state));
  state.gps_valid_and_fresh=false; assert(!mayAuthorizePumpOn(state));
  state={true,false,true,true,true,true,true}; assert(!mayAuthorizePumpOn(state));
  state={true,true,false,true,true,true,true}; assert(!mayAuthorizePumpOn(state));
  state={true,true,true,false,true,true,true}; assert(!mayAuthorizePumpOn(state));
  state={true,true,true,true,false,true,true}; assert(!mayAuthorizePumpOn(state));
  state={true,true,true,true,true,false,true}; assert(!mayAuthorizePumpOn(state));
  state={true,true,true,true,true,true,false}; assert(!mayAuthorizePumpOn(state));
  const PumpDecision denied=assessPumpRequest(PumpRequest::ON,state,false,false);
  assert(denied.request==PumpRequest::ON && !denied.on_authorized && !denied.state_confirmed);
  const PumpInterlocks allReady{true,true,true,true,true,true,true};
  const PumpDecision authorizedButUnconfirmed=assessPumpRequest(PumpRequest::ON,allReady,false,false);
  assert(authorizedButUnconfirmed.on_authorized && !authorizedButUnconfirmed.state_confirmed && !authorizedButUnconfirmed.confirmed_on);
  const PumpDecision confirmedOff=assessPumpRequest(PumpRequest::OFF,allReady,true,false);
  assert(!confirmedOff.on_authorized && confirmedOff.state_confirmed && !confirmedOff.confirmed_on);
  ReconnectPolicy reconnect;
  assert(reconnect.due(0));
  assert(reconnect.schedule(0)==1000 && reconnect.nextAttempt()==1000);
  assert(!reconnect.due(999) && reconnect.due(1000));
  assert(reconnect.schedule(1000)==2000);
  assert(reconnect.schedule(3000)==4000);
  assert(reconnect.schedule(7000)==8000);
  assert(reconnect.schedule(15000)==16000);
  assert(reconnect.schedule(31000)==30000);
  reconnect.reset(); assert(reconnect.schedule(40000)==1000);
  return 0;
}
