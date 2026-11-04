#include <unity.h>
#include <string>
#include <vector>
#include "gps_parser.h"
#include "hector/freshness.h"

using hector::GpsFix; using hector::GpsParser;
void setUp(void) {}
void tearDown(void) {}

static void feedLine(GpsParser &p, const std::string &body, uint32_t ms) {
  uint8_t cs=0; for(char c:body) cs^=uint8_t(c); char hex[8]; snprintf(hex,sizeof(hex),"*%02X\r\n",cs);
  const std::string line="$"+body+hex; for(uint8_t c:line) p.feed(c,ms);
}
static void put32(std::vector<uint8_t>&p,size_t i,uint32_t v) { for(int b=0;b<4;b++) p[i+b]=uint8_t(v>>(8*b)); }
static void put16(std::vector<uint8_t>&p,size_t i,uint16_t v) { p[i]=uint8_t(v);p[i+1]=uint8_t(v>>8); }
static void feedUbx(GpsParser &p,uint8_t cls,uint8_t id,const std::vector<uint8_t>&payload,uint32_t ms,bool valid=true) {
  std::vector<uint8_t> f={0xB5,0x62,cls,id,uint8_t(payload.size()),uint8_t(payload.size()>>8)}; f.insert(f.end(),payload.begin(),payload.end());
  uint8_t a=0,b=0; for(size_t i=2;i<f.size();i++){a=uint8_t(a+f[i]);b=uint8_t(b+a);} if(!valid) a++;
  f.push_back(a);f.push_back(b);for(uint8_t c:f)p.feed(c,ms);
}
static void test_valid_rmc_gga_and_units() {
  GpsParser p; feedLine(p,"GPRMC,120000.00,A,1202.7840,S,07702.5680,W,1.0,90.0,041126,,,A",100);
  feedLine(p,"GPGGA,120000.00,1202.7840,S,07702.5680,W,1,08,0.90,10.0,M,0.0,M,,",101);
  GpsFix f; TEST_ASSERT_TRUE(p.takeFix(f)); TEST_ASSERT_TRUE(f.fix_valid); TEST_ASSERT_TRUE(f.has_position);
  TEST_ASSERT_FLOAT_WITHIN(0.00001f,-12.0464,f.latitude); TEST_ASSERT_FLOAT_WITHIN(0.00001f,-77.0428,f.longitude);
  TEST_ASSERT_TRUE(f.has_speed); TEST_ASSERT_FLOAT_WITHIN(0.001f,0.514444f,f.speed_mps);
  TEST_ASSERT_TRUE(f.has_course); TEST_ASSERT_EQUAL_UINT8(8,f.satellites); TEST_ASSERT_FLOAT_WITHIN(0.01f,0.9f,f.hdop);
  TEST_ASSERT_FALSE(f.has_hacc); TEST_ASSERT_EQUAL_STRING("2026-11-04T12:00:00.00Z",f.timestamp.c_str());
}
static void test_nmea_bad_checksum_and_no_fix() {
  GpsParser p; const std::string bad="$GPRMC,120000.00,A,1202.7840,S,07702.5680,W,1.0,90.0,041126,,,A*00\r\n";
  for(uint8_t c:bad)p.feed(c,100); TEST_ASSERT_EQUAL_UINT32(1,p.nmeaChecksumErrors());
  feedLine(p,"GPRMC,120001.00,V,,,,,,,041126,,,N",200); GpsFix f;
  TEST_ASSERT_TRUE(p.takeFix(f)); TEST_ASSERT_FALSE(f.fix_valid); TEST_ASSERT_FALSE(f.has_position); TEST_ASSERT_FALSE(f.has_hacc);
}
static void test_ubx_checksum_and_matched_hacc_only() {
  GpsParser p; feedLine(p,"GPRMC,120000.00,A,1202.7840,S,07702.5680,W,1.0,90.0,041126,,,A",100);
  std::vector<uint8_t> pos(28); put32(pos,0,345000); put32(pos,4,uint32_t(int32_t(-770428000))); put32(pos,8,uint32_t(int32_t(-120464000))); put32(pos,20,1234);
  std::vector<uint8_t> utc(20); put32(utc,0,345000); put32(utc,4,100); put32(utc,8,0); put16(utc,12,2026); utc[14]=11;utc[15]=4;utc[16]=12;utc[17]=0;utc[18]=0;utc[19]=7;
  feedUbx(p,1,2,pos,110); feedUbx(p,1,0x21,utc,111); GpsFix f; TEST_ASSERT_TRUE(p.takeFix(f));
  TEST_ASSERT_TRUE(f.has_hacc); TEST_ASSERT_FLOAT_WITHIN(0.0001f,1.234f,f.hacc_m);
  TEST_ASSERT_EQUAL_STRING("UBX_NAV_POSLLH.hAcc",f.accuracy_source.c_str()); TEST_ASSERT_EQUAL_STRING("ESTIMATED",f.accuracy_status.c_str());
  feedLine(p,"GPRMC,120001.00,A,1202.7840,S,07702.5680,W,1.0,90.0,041126,,,A",120);
  feedUbx(p,1,2,pos,121); feedUbx(p,1,0x21,utc,122);
  feedLine(p,"GPGGA,120001.00,1202.7840,S,07702.5680,W,1,08,0.90,10.0,M,0.0,M,,",123);
  TEST_ASSERT_TRUE(p.takeFix(f)); TEST_ASSERT_FALSE(f.has_hacc); // old iTOW/UTC never leaks into the next fix
  feedUbx(p,1,2,pos,121,false); TEST_ASSERT_EQUAL_UINT32(1,p.ubxChecksumErrors());
}
static void test_invalid_coordinates_are_rejected() {
  GpsParser p; feedLine(p,"GPRMC,120000.00,A,9902.7840,N,07702.5680,W,1.0,90.0,041126,,,A",100);
  GpsFix f; TEST_ASSERT_TRUE(p.takeFix(f)); TEST_ASSERT_FALSE(f.fix_valid); TEST_ASSERT_FALSE(f.has_position);
}
static void test_sensor_freshness_and_millis_wrap() {
  TEST_ASSERT_TRUE(hector::sampleFresh(150,100,50)); TEST_ASSERT_FALSE(hector::sampleFresh(151,100,50));
  TEST_ASSERT_TRUE(hector::sampleFresh(20,UINT32_MAX-9,30));
}
static int runTests() { UNITY_BEGIN(); RUN_TEST(test_valid_rmc_gga_and_units); RUN_TEST(test_nmea_bad_checksum_and_no_fix); RUN_TEST(test_ubx_checksum_and_matched_hacc_only); RUN_TEST(test_invalid_coordinates_are_rejected); RUN_TEST(test_sensor_freshness_and_millis_wrap); return UNITY_END(); }
#ifdef ARDUINO
void setup() { runTests(); }
void loop() {}
#else
int main() { return runTests(); }
#endif
