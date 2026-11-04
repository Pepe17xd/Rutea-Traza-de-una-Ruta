"""Platform-independent MPU-6050 register reader with an injectable I2C bus."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import statistics
import time
from typing import Callable


G = 9.80665
ACCEL_LSB_PER_G = 16384.0       # +/-2 g full scale
GYRO_LSB_PER_DPS = 131.0        # +/-250 degrees/s full scale
DEG_TO_RAD = math.pi / 180.0


class ImuError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImuReading:
    accel_mps2: tuple[float, float, float] | None
    gyro_rps: tuple[float, float, float] | None
    sensor_timestamp: datetime
    received_monotonic: float
    valid: bool
    connected: bool
    status: str
    error: str | None = None
    source: str = "PHYSICAL"

    def is_stale(self, now_monotonic: float, max_age_s: float) -> bool:
        return now_monotonic - self.received_monotonic > max_age_s


@dataclass(frozen=True)
class GyroCalibration:
    bias_rps: tuple[float, float, float]
    standard_deviation_rps: tuple[float, float, float]
    sample_count: int
    calibrated_at: datetime


@dataclass(frozen=True)
class Mpu6050Config:
    bus_number: int = 1
    address: int = 0x68
    reconnect_delay_s: float = 2.0
    max_age_s: float = 0.5
    calibration_max_std_rps: float = 0.05

    def __post_init__(self):
        if self.bus_number < 0 or not 0x03 <= self.address <= 0x77:
            raise ValueError("Invalid I2C bus number or 7-bit address")
        if self.reconnect_delay_s < 0 or self.max_age_s <= 0 or self.calibration_max_std_rps <= 0:
            raise ValueError("Invalid MPU-6050 timing/calibration limits")


class Mpu6050Adapter:
    PWR_MGMT_1 = 0x6B
    ACCEL_XOUT_H = 0x3B
    WHO_AM_I = 0x75

    def __init__(self, config: Mpu6050Config = Mpu6050Config(), *, bus=None, bus_factory=None,
                 monotonic: Callable[[], float] = time.monotonic,
                 utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 sleeper: Callable[[float], None] = time.sleep):
        self.config=config; self._monotonic=monotonic; self._utcnow=utcnow; self._sleeper=sleeper
        self._provided_bus=bus; self._bus_factory=bus_factory; self._bus=None
        self._retry_at=0.0; self.connected=False; self.status="DISCONNECTED"; self.last_error: str | None=None
        self.gyro_bias_rps=(0.0,0.0,0.0); self.calibration: GyroCalibration | None=None

    def _open_bus(self):
        if self._bus is not None: return True
        if self._monotonic() < self._retry_at: return False
        try:
            if self._provided_bus is not None:
                bus=self._provided_bus
            elif self._bus_factory is not None:
                bus=self._bus_factory(self.config.bus_number)
            else:
                from smbus2 import SMBus
                bus=SMBus(self.config.bus_number)
            identity=bus.read_byte_data(self.config.address,self.WHO_AM_I)
            if identity not in (0x68,0x69):
                try: bus.close()
                except Exception: pass
                raise ImuError(f"Unexpected WHO_AM_I value 0x{identity:02x}")
            bus.write_byte_data(self.config.address,self.PWR_MGMT_1,0x00)
            self._bus=bus; self.connected=True; self.status="CONNECTED"; self.last_error=None
            return True
        except Exception as exc:
            self._bus=None; self.connected=False; self.status="DISCONNECTED"; self.last_error=str(exc)
            self._retry_at=self._monotonic()+self.config.reconnect_delay_s
            return False

    @staticmethod
    def _i16(high: int, low: int) -> int:
        value=(high << 8) | low
        return value-65536 if value & 0x8000 else value

    def _read_raw(self) -> tuple[tuple[int,int,int],tuple[int,int,int]]:
        if not self._open_bus(): raise ImuError(self.last_error or "I2C bus unavailable")
        data=self._bus.read_i2c_block_data(self.config.address,self.ACCEL_XOUT_H,14)
        if len(data)!=14: raise ImuError(f"Expected 14 MPU-6050 bytes, got {len(data)}")
        raw=[self._i16(data[i],data[i+1]) for i in range(0,14,2)]
        if all(x == 0 for x in data) or all(x == 255 for x in data):
            raise ImuError("Sensor returned an all-zero/all-ones register block")
        accel=tuple(raw[:3])
        gyro=tuple(raw[4:7])
        if any(abs(x)>=32760 for x in (*accel,*gyro)):
            raise ImuError("MPU-6050 reading is saturated")
        return accel,gyro

    @staticmethod
    def _convert(accel_raw,gyro_raw):
        accel=tuple(float(x)*G/ACCEL_LSB_PER_G for x in accel_raw)
        gyro=tuple(float(x)/GYRO_LSB_PER_DPS*DEG_TO_RAD for x in gyro_raw)
        return accel,gyro

    def read(self) -> ImuReading:
        stamp=self._utcnow().astimezone(timezone.utc); received=self._monotonic()
        try:
            ar,gr=self._read_raw(); accel,raw_gyro=self._convert(ar,gr)
            gyro=tuple(raw_gyro[i]-self.gyro_bias_rps[i] for i in range(3))
            if not all(math.isfinite(x) for x in (*accel,*gyro)):
                raise ImuError("Non-finite MPU-6050 measurement")
            self.status="CONNECTED"
            return ImuReading(accel,gyro,stamp,received,True,True,self.status,source="PHYSICAL")
        except ImuError as exc:
            disconnected=not self.connected
            self.status="DISCONNECTED" if disconnected else "INVALID_READING"
            self.last_error=str(exc)
            if disconnected or isinstance(exc.__cause__,OSError): self._disconnect()
            return ImuReading(None,None,stamp,received,False,not disconnected,self.status,str(exc),"PHYSICAL")
        except Exception as exc:
            self.last_error=str(exc); self._disconnect()
            return ImuReading(None,None,stamp,received,False,False,"DISCONNECTED",str(exc),"PHYSICAL")

    def calibrate_gyro(self, samples: int = 200, interval_s: float = 0.01) -> GyroCalibration:
        if samples < 3 or interval_s < 0: raise ValueError("Calibration needs at least 3 samples and non-negative interval")
        readings=[]
        for index in range(samples):
            ar,gr=self._read_raw(); accel,gyro=self._convert(ar,gr)
            magnitude=math.sqrt(sum(v*v for v in accel))
            if not 0.75*G <= magnitude <= 1.25*G:
                raise ImuError("Calibration requires a stationary sensor under gravity")
            readings.append(gyro)
            if index+1<samples and interval_s: self._sleeper(interval_s)
        means=tuple(statistics.fmean(row[i] for row in readings) for i in range(3))
        stds=tuple(statistics.stdev(row[i] for row in readings) for i in range(3))
        if max(stds)>self.config.calibration_max_std_rps:
            raise ImuError("Gyroscope moved during bias calibration; no bias was applied")
        calibration=GyroCalibration(means,stds,samples,self._utcnow().astimezone(timezone.utc))
        self.gyro_bias_rps=means; self.calibration=calibration
        return calibration

    def _disconnect(self):
        bus=self._bus; self._bus=None; self.connected=False; self.status="DISCONNECTED"
        if bus is not None:
            try: bus.close()
            except Exception: pass
        self._retry_at=self._monotonic()+self.config.reconnect_delay_s

    def close(self): self._disconnect()
