#include "gps_parser.h"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <vector>

namespace hector {
static uint16_t le16(const uint8_t *p) { return uint16_t(p[0]) | (uint16_t(p[1]) << 8); }
static uint32_t le32(const uint8_t *p) { return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24); }
static bool withinMs(uint32_t a,uint32_t b,uint32_t limit) { uint32_t d=a-b; if(d>UINT32_MAX/2) d=b-a; return d<=limit; }
static std::vector<std::string> split(const char *s) {
  std::vector<std::string> out; const char *start=s;
  for (const char *p=s;;++p) if (*p==',' || *p=='\0') { out.emplace_back(start, p-start); if (!*p) break; start=p+1; }
  return out;
}
static bool number(const std::string &s, double &v) { if (s.empty()) return false; char *end=nullptr; v=strtod(s.c_str(),&end); return end && *end=='\0' && std::isfinite(v); }
static bool coordinate(const std::string &raw, const std::string &hem, bool lat, double &out) {
  double n; if (!number(raw,n) || hem.size()!=1) return false;
  const double degrees=std::floor(n/100.0), minutes=n-degrees*100.0;
  if (minutes<0 || minutes>=60) return false;
  out=degrees+minutes/60.0;
  if ((lat && out>90) || (!lat && out>180)) return false;
  if (hem[0]=='S' || hem[0]=='W') out=-out; else if (hem[0]!='N' && hem[0]!='E') return false;
  return true;
}
static std::string isoUtc(const std::string &time, const std::string &date) {
  if (time.size()<6 || date.size()!=6) return {};
  const int day=atoi(date.substr(0,2).c_str()), month=atoi(date.substr(2,2).c_str());
  int year=atoi(date.substr(4,2).c_str()); year += year>=80 ? 1900 : 2000;
  if (day<1 || day>31 || month<1 || month>12) return {};
  for(size_t i=0;i<6;i++) if(time[i]<'0'||time[i]>'9'||date[i]<'0'||date[i]>'9') return {};
  const int hour=atoi(time.substr(0,2).c_str()), minute=atoi(time.substr(2,2).c_str()), second=atoi(time.substr(4,2).c_str());
  const int monthDays[]={31,28,31,30,31,30,31,31,30,31,30,31};
  const bool leap=(year%4==0 && (year%100!=0 || year%400==0));
  if(hour>23||minute>59||second>59||day>monthDays[month-1]+(month==2&&leap?1:0)) return {};
  if(time.size()>6) { if(time.size()<8 || time[6]!='.') return {}; for(size_t i=7;i<time.size();i++) if(time[i]<'0'||time[i]>'9') return {}; }
  const std::string hhmmss=time.substr(0,6);
  char out[40]; snprintf(out,sizeof(out),"%04d-%02d-%02dT%c%c:%c%c:%c%c",year,month,day,
      hhmmss[0],hhmmss[1],hhmmss[2],hhmmss[3],hhmmss[4],hhmmss[5]);
  size_t used=strlen(out);
  // Preserve measurement fractions; they are not inferred from receive time.
  if (time.size()>6 && time[6]=='.') { size_t n=std::min<size_t>(time.size()-7,6); out[used++]='.'; memcpy(out+used,time.data()+7,n); used+=n; }
  out[used++]='Z'; out[used]='\0';
  return out;
}
void GpsParser::feed(uint8_t c, uint32_t received_ms) {
  if (!in_nmea_ && !in_ubx_ && c=='$') { in_nmea_=true; nmea_len_=0; nmea_[nmea_len_++]=char(c); return; }
  if (!in_nmea_ && !in_ubx_ && c==0xB5) { in_ubx_=true; ubx_sync2_=false; ubx_len_=0; return; }
  if (in_nmea_) {
    if (c=='\n') { nmea_[nmea_len_]='\0'; handleNmea(nmea_,received_ms); in_nmea_=false; return; }
    if (nmea_len_+1>=sizeof(nmea_) || c=='\0') { ++malformed_; in_nmea_=false; return; }
    nmea_[nmea_len_++]=char(c); return;
  }
  if (in_ubx_) {
    if (!ubx_sync2_) { if (c==0x62) ubx_sync2_=true; else { in_ubx_=false; ++malformed_; } return; }
    if (ubx_len_>=sizeof(ubx_)) { in_ubx_=false; ++malformed_; return; }
    ubx_[ubx_len_++]=c;
    if (ubx_len_==4) { uint16_t plen=le16(ubx_+2); if (plen>64) { in_ubx_=false; ++malformed_; return; } ubx_expected_=size_t(plen)+6; }
    if (ubx_expected_ && ubx_len_==ubx_expected_) { handleUbx(received_ms); in_ubx_=false; ubx_len_=0; ubx_expected_=0; }
  }
}
void GpsParser::handleNmea(const char *line, uint32_t received_ms) {
  size_t n=strlen(line); while(n && (line[n-1]=='\r' || line[n-1]=='\n')) --n;
  const char *star=(const char*)memchr(line,'*',n); if (!star || star+2>=line+n) { ++nmea_errors_; return; }
  uint8_t cs=0; for (const char *p=line+1;p<star;++p) cs^=uint8_t(*p);
  auto hexDigit=[](char c)->int { if(c>='0'&&c<='9') return c-'0'; if(c>='A'&&c<='F') return c-'A'+10; if(c>='a'&&c<='f') return c-'a'+10; return -1; };
  const int hi=hexDigit(star[1]),lo=hexDigit(star[2]); if(hi<0||lo<0||uint8_t((hi<<4)|lo)!=cs) { ++nmea_errors_; return; }
  std::string payload(line+1,star); auto f=split(payload.c_str()); if (f.empty() || f[0].size()<3) { ++malformed_; return; }
  const std::string kind=f[0].substr(f[0].size()-3);
  if (kind=="RMC" && f.size()>=10) {
    GpsFix x=latest_; x.received_ms=received_ms; x.fix_valid=f[2]=="A"; x.has_position=false; x.has_speed=x.has_course=false;
    x.has_hacc=false; x.hacc_m=0; x.accuracy_source.clear(); x.accuracy_status="UNAVAILABLE"; x.itow_ms=0;
    x.timestamp=isoUtc(f[1],f[9]); rmc_timestamp_=x.timestamp;
    if(x.timestamp.empty()) x.fix_valid=false;
    if (x.fix_valid) {
      double lat,lon; if (coordinate(f[3],f[4],true,lat) && coordinate(f[5],f[6],false,lon)) { x.latitude=lat; x.longitude=lon; x.has_position=true; }
      else { x.fix_valid=false; ++malformed_; }
      double v; if (number(f[7],v) && v>=0 && v*0.514444444<=10.0) { x.speed_mps=float(v*0.514444444); x.has_speed=true; }
      if (number(f[8],v) && v>=0 && v<360) { x.course_deg=float(v); x.has_course=true; }
    }
    if (!x.fix_valid) { x.has_position=false; x.has_hacc=false; x.accuracy_status="UNAVAILABLE"; x.accuracy_source.clear(); }
    latest_=x; available_=true; attachHacc();
  } else if (kind=="GGA" && f.size()>=9) {
    GpsFix x=latest_; x.received_ms=received_ms; double q=0;
    const bool quality=number(f[6],q) && q>0; x.fix_valid=quality; x.has_position=false; x.has_satellites=false; x.has_hdop=false;
    x.timestamp.clear();
    // Pair GGA UTC with latest RMC date only when their time-of-day matches (within 1 s).
    const std::string rmc_tod=rmc_timestamp_.size()>=19
        ? rmc_timestamp_.substr(11,2)+rmc_timestamp_.substr(14,2)+rmc_timestamp_.substr(17,2) : std::string();
    if (!rmc_tod.empty() && f[1].size()>=6 && rmc_tod==f[1].substr(0,6)) x.timestamp=rmc_timestamp_;
    x.fix_valid=quality && !x.timestamp.empty();
    double lat,lon; if (x.fix_valid && coordinate(f[2],f[3],true,lat) && coordinate(f[4],f[5],false,lon)) { x.latitude=lat; x.longitude=lon; x.has_position=true; }
    else if (quality && !x.timestamp.empty()) { x.fix_valid=false; ++malformed_; }
    double v=0;
    if (f.size()>7 && number(f[7],v) && v>=0 && v<=99 && std::floor(v)==v) { x.satellites=uint8_t(v); x.has_satellites=true; }
    if (f.size()>8 && number(f[8],v) && v>=0 && v<=999) { x.hdop=float(v); x.has_hdop=true; }
    if (!x.fix_valid) { x.has_position=false; x.has_hacc=false; x.accuracy_status="UNAVAILABLE"; x.accuracy_source.clear(); }
    latest_=x; available_=true; attachHacc();
  }
}
void GpsParser::handleUbx(uint32_t received_ms) {
  // Frame buffer is class,id,lenLE,payload,CK_A,CK_B.
  uint8_t a=0,b=0; for(size_t i=0;i<ubx_len_-2;++i){a=uint8_t(a+ubx_[i]);b=uint8_t(b+a);}
  if(a!=ubx_[ubx_len_-2] || b!=ubx_[ubx_len_-1]) { ++ubx_errors_; return; }
  const uint8_t cls=ubx_[0], id=ubx_[1]; const uint8_t *p=ubx_+4; const size_t plen=le16(ubx_+2);
  if(cls==0x01 && id==0x02 && plen==28) {
    pos_itow_=le32(p); int32_t lon=int32_t(le32(p+4)), lat=int32_t(le32(p+8));
    pos_lon_=lon*1e-7; pos_lat_=lat*1e-7; pos_hacc_m_=le32(p+20)/1000.0f;
    pos_received_ms_=received_ms; pos_available_=std::isfinite(pos_lat_)&&std::isfinite(pos_lon_)&&std::abs(pos_lat_)<=90&&std::abs(pos_lon_)<=180&&pos_hacc_m_>0&&pos_hacc_m_<=10000;
    attachHacc();
  } else if(cls==0x01 && id==0x21 && plen==20) {
    const uint8_t valid=p[19]; const int year=le16(p+12),month=p[14],day=p[15],hour=p[16],minute=p[17],second=p[18];
    // validUTC (bit 2), validDate (bit 0), validTime (bit 1) must all be set.
    if((valid&0x07)==0x07 && year>=2000 && month>=1&&month<=12&&day>=1&&day<=31&&hour<24&&minute<60&&second<60) {
      char stamp[24]; snprintf(stamp,sizeof(stamp),"%04u-%02u-%02uT%02u:%02u:%02uZ",year,month,day,hour,minute,second);
      timeutc_timestamp_=stamp; timeutc_ms_=received_ms; timeutc_itow_=le32(p); attachHacc();
    }
  }
}
void GpsParser::attachHacc() {
  if (!available_ || !latest_.fix_valid || !latest_.has_position || !pos_available_ || timeutc_timestamp_.empty()) return;
  if (!withinMs(latest_.received_ms,pos_received_ms_,2000) || !withinMs(latest_.received_ms,timeutc_ms_,2000)) return;
  if (pos_itow_!=timeutc_itow_ || pos_hacc_m_<=0 || latest_.timestamp.size()<20 || timeutc_timestamp_.size()<20 || latest_.timestamp.compare(0,19,timeutc_timestamp_,0,19)!=0) return;
  const double dlat=(latest_.latitude-pos_lat_)*111320.0;
  const double dlon=(latest_.longitude-pos_lon_)*111320.0*std::cos(latest_.latitude*3.141592653589793/180.0);
  if (std::hypot(dlat,dlon)>25.0) return;
  if(latest_.has_hacc) return;
  latest_.has_hacc=true; latest_.hacc_m=pos_hacc_m_; available_=true;
  latest_.accuracy_source="UBX_NAV_POSLLH.hAcc"; latest_.accuracy_status="ESTIMATED"; latest_.itow_ms=pos_itow_;
}
bool GpsParser::takeFix(GpsFix &out) { if(!available_) return false; out=latest_; available_=false; return true; }
}
