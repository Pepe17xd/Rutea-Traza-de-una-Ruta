// Portable smoke test for the in-tree parser; build with a host C++17 compiler.
#include "gps_parser.h"
#include "hector/freshness.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

static void feedNmea(hector::GpsParser &p,const std::string &body,uint32_t ms) {
  uint8_t cs=0; for(char c:body) cs^=uint8_t(c); char suffix[8]; std::snprintf(suffix,sizeof(suffix),"*%02X\r\n",cs);
  const std::string line="$"+body+suffix; for(uint8_t c:line)p.feed(c,ms);
}
static void put32(std::vector<uint8_t>&p,size_t i,uint32_t v) { for(int b=0;b<4;b++)p[i+b]=uint8_t(v>>(8*b)); }
static void put16(std::vector<uint8_t>&p,size_t i,uint16_t v) { p[i]=uint8_t(v);p[i+1]=uint8_t(v>>8); }
static void feedUbx(hector::GpsParser &p,uint8_t cls,uint8_t id,const std::vector<uint8_t>&payload,uint32_t ms,bool valid=true) {
  std::vector<uint8_t> f={0xB5,0x62,cls,id,uint8_t(payload.size()),uint8_t(payload.size()>>8)}; f.insert(f.end(),payload.begin(),payload.end());
  uint8_t a=0,b=0; for(size_t i=2;i<f.size();i++){a=uint8_t(a+f[i]);b=uint8_t(b+a);} if(!valid) a++; f.push_back(a);f.push_back(b);for(uint8_t c:f)p.feed(c,ms);
}
int main() {
  assert(hector::sampleFresh(150,100,50)); assert(!hector::sampleFresh(151,100,50));
  assert(hector::sampleFresh(20,UINT32_MAX-9,30)); // millis wrap
  hector::GpsParser parser;
  feedNmea(parser,"GPRMC,120000.00,A,1202.7840,S,07702.5680,W,1.0,90.0,041126,,,A",100);
  feedNmea(parser,"GPGGA,120000.00,1202.7840,S,07702.5680,W,1,08,0.90,10.0,M,0.0,M,,",101);
  hector::GpsFix fix; assert(parser.takeFix(fix)); assert(fix.fix_valid&&fix.has_position);
  assert(std::fabs(fix.latitude+12.0464)<1e-5); assert(std::fabs(fix.longitude+77.0428)<1e-5);
  assert(fix.has_speed&&std::fabs(fix.speed_mps-0.514444)<1e-3); assert(!fix.has_hacc);
  const std::string invalid="$GPRMC,120001.00,A,1202.7840,S,07702.5680,W,1.0,90.0,041126,,,A*00\r\n";
  for(uint8_t c:invalid) { parser.feed(c,200); }
  assert(parser.nmeaChecksumErrors()==1);
  hector::GpsFix f;
  feedNmea(parser,"GPRMC,120002.00,V,,,,,,,041126,,,N",300); assert(parser.takeFix(f));
  assert(!f.fix_valid&&!f.has_position);

  hector::GpsParser ubx;
  feedNmea(ubx,"GPRMC,120000.00,A,1202.7840,S,07702.5680,W,1.0,90.0,041126,,,A",100);
  std::vector<uint8_t> pos(28),utc(20); put32(pos,0,345000); put32(pos,4,uint32_t(int32_t(-770428000))); put32(pos,8,uint32_t(int32_t(-120464000))); put32(pos,20,1234);
  put32(utc,0,345000); put32(utc,4,100); put16(utc,12,2026); utc[14]=11;utc[15]=4;utc[16]=12;utc[19]=7;
  feedUbx(ubx,1,2,pos,110);feedUbx(ubx,1,0x21,utc,111);assert(ubx.takeFix(f));
  assert(f.has_hacc&&std::fabs(f.hacc_m-1.234)<1e-4);assert(f.accuracy_status=="ESTIMATED");
  feedNmea(ubx,"GPRMC,120001.00,A,1202.7840,S,07702.5680,W,1.0,90.0,041126,,,A",120);
  put32(pos,0,346000); feedUbx(ubx,1,2,pos,121); feedUbx(ubx,1,0x21,utc,122);
  feedNmea(ubx,"GPGGA,120001.00,1202.7840,S,07702.5680,W,1,08,0.90,10.0,M,0.0,M,,",123);
  assert(ubx.takeFix(f)); assert(!f.has_hacc); // old iTOW/UTC is not reused for the next position
  feedUbx(ubx,1,2,pos,124,false); assert(ubx.ubxChecksumErrors()==1);
  std::puts("host parser tests passed");
}
