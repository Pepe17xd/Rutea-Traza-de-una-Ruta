#include <unity.h>
#include "hector/mission_protocol.h"
#include "hector/reconnect_policy.h"
using namespace hector;

void setUp(void) {}
void tearDown(void) {}

void test_g_destination_line_is_exact_and_range_checked() {
  DestinationCommandV1 destination;
  const char wire[]="G:-12.04640000,-77.04280000\n";
  TEST_ASSERT_TRUE(parseDestinationLine(wire,sizeof(wire)-1,destination));
  TEST_ASSERT_FLOAT_WITHIN(0.00000001,-12.0464,destination.latitude);
  TEST_ASSERT_FLOAT_WITHIN(0.00000001,-77.0428,destination.longitude);
  const char crlf[]="G:1,2\r\n";
  const char invalid[]="G:91,2\n";
  TEST_ASSERT_FALSE(parseDestinationLine(crlf,sizeof(crlf)-1,destination));
  TEST_ASSERT_FALSE(parseDestinationLine(invalid,sizeof(invalid)-1,destination));
}
void test_command_expiry_duplicate_and_obsolete_sequence() {
  DestinationCommandV1 destination;
  const char wire[]="G:1,2\n";
  TEST_ASSERT_EQUAL(DestinationDecision::ACCEPT_NEW,inspectDestination(8,200,100,"m8","m7",7,wire,sizeof(wire)-1,destination));
  TEST_ASSERT_EQUAL(DestinationDecision::ACK_IDEMPOTENT_DUPLICATE,inspectDestination(8,200,100,"m8","m8",8,wire,sizeof(wire)-1,destination));
  TEST_ASSERT_EQUAL(DestinationDecision::REJECT_EXPIRED,inspectDestination(8,99,100,"m8","m8",8,wire,sizeof(wire)-1,destination));
  TEST_ASSERT_EQUAL(DestinationDecision::REJECT_OBSOLETE,inspectDestination(7,200,100,"m7","m8",8,wire,sizeof(wire)-1,destination));
  TEST_ASSERT_EQUAL(DestinationDecision::REJECT_EXPIRED,inspectDestination(9,99,100,"m9","m8",8,wire,sizeof(wire)-1,destination));
}
void test_pump_words_and_all_local_interlocks() {
  bool on=true;
  TEST_ASSERT_TRUE(parsePumpWord("OFF",3,on)); TEST_ASSERT_FALSE(on);
  TEST_ASSERT_TRUE(parsePumpWord("ON",2,on)); TEST_ASSERT_TRUE(on);
  TEST_ASSERT_FALSE(parsePumpWord("on",2,on));
  PumpInterlocks state;
  PumpDecision defaultPump{};
  TEST_ASSERT_EQUAL(PumpRequest::OFF,defaultPump.request);
  TEST_ASSERT_FALSE(defaultPump.on_authorized);
  TEST_ASSERT_FALSE(defaultPump.state_confirmed);
  TEST_ASSERT_FALSE(mayAuthorizePumpOn(state));
  state={true,true,true,true,true,true,true}; TEST_ASSERT_TRUE(mayAuthorizePumpOn(state));
  state={true,true,false,true,true,true,true}; TEST_ASSERT_FALSE(mayAuthorizePumpOn(state));
  state={true,true,true,false,true,true,true}; TEST_ASSERT_FALSE(mayAuthorizePumpOn(state));
  state={true,true,true,true,false,true,true}; TEST_ASSERT_FALSE(mayAuthorizePumpOn(state));
  state={true,true,true,true,true,false,true}; TEST_ASSERT_FALSE(mayAuthorizePumpOn(state));
  state={true,true,true,true,true,true,false}; TEST_ASSERT_FALSE(mayAuthorizePumpOn(state));
  state={false,true,true,true,true,true,true}; TEST_ASSERT_FALSE(mayAuthorizePumpOn(state));
  state={true,false,true,true,true,true,true}; TEST_ASSERT_FALSE(mayAuthorizePumpOn(state));
  PumpDecision denied=assessPumpRequest(PumpRequest::ON,state,false,false);
  TEST_ASSERT_FALSE(denied.on_authorized); TEST_ASSERT_FALSE(denied.state_confirmed);
  const PumpInterlocks allReady{true,true,true,true,true,true,true};
  PumpDecision allowedNoFeedback=assessPumpRequest(PumpRequest::ON,allReady,false,false);
  TEST_ASSERT_TRUE(allowedNoFeedback.on_authorized); TEST_ASSERT_FALSE(allowedNoFeedback.state_confirmed);
  PumpDecision offConfirmed=assessPumpRequest(PumpRequest::OFF,allReady,true,false);
  TEST_ASSERT_FALSE(offConfirmed.on_authorized); TEST_ASSERT_TRUE(offConfirmed.state_confirmed);
}
void test_wifi_reconnect_policy_backs_off_and_recovers() {
  ReconnectPolicy policy;
  TEST_ASSERT_TRUE(policy.due(0));
  TEST_ASSERT_EQUAL_UINT32(1000,policy.schedule(0));
  TEST_ASSERT_FALSE(policy.due(999));
  TEST_ASSERT_EQUAL_UINT32(2000,policy.schedule(1000));
  TEST_ASSERT_EQUAL_UINT32(4000,policy.schedule(3000));
  TEST_ASSERT_EQUAL_UINT32(8000,policy.schedule(7000));
  TEST_ASSERT_EQUAL_UINT32(16000,policy.schedule(15000));
  TEST_ASSERT_EQUAL_UINT32(30000,policy.schedule(31000));
  policy.reset();
  TEST_ASSERT_EQUAL_UINT32(1000,policy.schedule(40000));
}
int main() {
  UNITY_BEGIN();
  RUN_TEST(test_g_destination_line_is_exact_and_range_checked);
  RUN_TEST(test_command_expiry_duplicate_and_obsolete_sequence);
  RUN_TEST(test_pump_words_and_all_local_interlocks);
  RUN_TEST(test_wifi_reconnect_policy_backs_off_and_recovers);
  return UNITY_END();
}
