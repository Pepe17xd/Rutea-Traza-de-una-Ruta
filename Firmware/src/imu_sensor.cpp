#include "hector/imu_sensor.h"
#include <math.h>

namespace hector {
bool Mpu6050Sensor::readRegisters(uint8_t reg,uint8_t *data,size_t length) {
  if(!wire_) return false; wire_->beginTransmission(address_); wire_->write(reg);
  if(wire_->endTransmission(false)!=0 || wire_->requestFrom(address_,uint8_t(length))!=length) return false;
  for(size_t i=0;i<length;i++) data[i]=wire_->read(); return true;
}
bool Mpu6050Sensor::begin(TwoWire &wire,uint8_t address) {
  wire_=&wire; address_=address; uint8_t who=0;
  if(!readRegisters(0x75,&who,1) || (who!=0x68 && who!=0x69)) { connected_=false; snprintf(error_,sizeof(error_),"WHO_AM_I_INVALID"); return false; }
  // Wake device; use documented default full-scale ranges: +/-2g and +/-250 dps.
  wire_->beginTransmission(address_); wire_->write(0x6B); wire_->write(0x00);
  if(wire_->endTransmission()!=0) { connected_=false; snprintf(error_,sizeof(error_),"WAKEUP_FAILED"); return false; }
  delay(100); connected_=true; snprintf(error_,sizeof(error_),"OK"); return true;
}
bool Mpu6050Sensor::read(ImuSample &out) {
  uint8_t b[14]; out.received_ms=millis(); out.valid=false;
  if(!connected_ || !readRegisters(0x3B,b,sizeof(b))) { connected_=false; snprintf(error_,sizeof(error_),"I2C_READ_FAILED"); return false; }
  auto s16=[&b](size_t i){return int16_t((uint16_t(b[i])<<8)|b[i+1]);};
  const int16_t raw[6]={s16(0),s16(2),s16(4),s16(8),s16(10),s16(12)};
  for(int i=0;i<3;i++) { if(raw[i]==INT16_MIN||raw[i]==INT16_MAX||raw[i+3]==INT16_MIN||raw[i+3]==INT16_MAX) { snprintf(error_,sizeof(error_),"SATURATED"); return false; } }
  for(int i=0;i<3;i++) { out.accel[i]=(raw[i]/16384.0f)*9.80665f; out.gyro[i]=(raw[i+3]/131.0f)*(3.14159265358979323846f/180.0f)-bias_[i]; }
  const float norm=sqrtf(out.accel[0]*out.accel[0]+out.accel[1]*out.accel[1]+out.accel[2]*out.accel[2]);
  if(!isfinite(norm)||norm<2.0f||norm>20.0f) { snprintf(error_,sizeof(error_),"ACCEL_OUT_OF_RANGE"); return false; }
  for(int i=0;i<3;i++) if(!isfinite(out.gyro[i])||fabsf(out.gyro[i])>4.5f) { snprintf(error_,sizeof(error_),"GYRO_OUT_OF_RANGE"); return false; }
  out.valid=true; snprintf(error_,sizeof(error_),"OK"); return true;
}
bool Mpu6050Sensor::calibrateGyro(uint16_t samples,uint16_t interval_ms) {
  if(samples<20||samples>2000) { snprintf(error_,sizeof(error_),"CALIBRATION_SAMPLE_RANGE"); return false; }
  double sums[3]={},squares[3]={}; uint32_t start=millis();
  for(uint16_t n=0;n<samples;n++) { uint8_t b[14]; if(!readRegisters(0x3B,b,sizeof(b))) { connected_=false; snprintf(error_,sizeof(error_),"CALIBRATION_I2C_FAILURE"); return false; }
    double accel_norm_sq=0;
    for(int i=0;i<3;i++) { const int16_t accel=int16_t((uint16_t(b[i*2])<<8)|b[i*2+1]); const double a=(accel/16384.0)*9.80665; accel_norm_sq+=a*a;
      const int16_t raw=int16_t((uint16_t(b[8+i*2])<<8)|b[9+i*2]); const double v=(raw/131.0)*(3.14159265358979323846/180.0); sums[i]+=v; squares[i]+=v*v; }
    const double accel_norm=sqrt(accel_norm_sq); if(accel_norm<8.0||accel_norm>11.5) { snprintf(error_,sizeof(error_),"CALIBRATION_NOT_STATIONARY"); return false; }
    delay(interval_ms);
  }
  if(millis()-start<samples*interval_ms) { snprintf(error_,sizeof(error_),"CALIBRATION_TIMING_ERROR"); return false; }
  for(int i=0;i<3;i++) { const double mean=sums[i]/samples, variance=squares[i]/samples-mean*mean; if(!isfinite(mean)||variance>0.0025||fabs(mean)>0.25) { snprintf(error_,sizeof(error_),"CALIBRATION_NOT_STATIONARY"); return false; } bias_[i]=float(mean); }
  snprintf(error_,sizeof(error_),"OK_CALIBRATED"); return true;
}
}
