#pragma once
#include <Arduino.h>
#include <Wire.h>

namespace hector {
struct ImuSample { float accel[3]{}; float gyro[3]{}; uint32_t received_ms=0; bool valid=false; };
class Mpu6050Sensor {
 public:
  bool begin(TwoWire &wire, uint8_t address);
  bool calibrateGyro(uint16_t samples=200, uint16_t interval_ms=5);
  bool read(ImuSample &out);
  bool connected() const { return connected_; }
  const char *error() const { return error_; }
 private:
  bool readRegisters(uint8_t reg, uint8_t *data, size_t length);
  TwoWire *wire_=nullptr; uint8_t address_=0x68; bool connected_=false;
  float bias_[3]{}; char error_[48]="NOT_INITIALIZED";
};
}
