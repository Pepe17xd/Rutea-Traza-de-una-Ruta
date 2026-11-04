"""Timestamped GPS/IMU estimator for a mostly planar, forward-moving cart.

GPS course is observable only while moving and is treated as vehicle heading
under a no-side-slip assumption. The MPU-6050 gyro has no absolute yaw reference.
The small complementary correction below is a model, not a calibrated accuracy
claim; position accuracy remains unavailable unless an upstream sensor supplies it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
import time
from typing import Callable

from app.sensors.nmea import GpsFix
from app.sensors.mpu6050 import ImuReading


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def _course_to_math(course_deg: float) -> float:
    return _wrap(math.pi / 2 - math.radians(course_deg))


@dataclass(frozen=True)
class OdometrySample:
    speed_mps: float
    sensor_timestamp: datetime
    received_monotonic: float
    source: str = "PHYSICAL"


@dataclass(frozen=True)
class StateEstimate:
    latitude: float | None
    longitude: float | None
    speed_mps: float | None
    gps_course_deg: float | None
    heading_rad: float | None
    heading_source: str
    heading_quality: str
    heading_uncertainty_rad: float | None
    gps_fix_valid: bool
    gps_satellites: int | None
    gps_hdop: float | None
    gps_accuracy_m: float | None
    gps_accuracy_status: str
    imu_accel_mps2: tuple[float, float, float] | None
    imu_gyro_rps: tuple[float, float, float] | None
    sensor_timestamp: datetime | None
    gps_timestamp: datetime | None
    imu_timestamp: datetime | None
    sensor_status: dict[str, str]
    data_source: str


@dataclass(frozen=True)
class EstimatorConfig:
    gps_max_age_s: float = 3.5
    imu_max_age_s: float = 0.5
    max_imu_gap_s: float = 0.5
    min_course_speed_mps: float = 0.5
    gyro_bias_uncertainty_rps: float = 0.01
    gyro_noise_variance_rps2: float = 0.0004
    course_heading_sigma_rad: float = math.radians(20.0)
    course_correction_gain: float = 0.08

    def __post_init__(self):
        if min(self.gps_max_age_s,self.imu_max_age_s,self.max_imu_gap_s)<=0:
            raise ValueError("Estimator freshness and gap limits must be positive")
        if self.min_course_speed_mps<0 or self.gyro_bias_uncertainty_rps<0 or self.gyro_noise_variance_rps2<0:
            raise ValueError("Estimator rates/noise must be non-negative")
        if not 0<self.course_correction_gain<=1 or not 0<self.course_heading_sigma_rad<=math.pi:
            raise ValueError("Invalid complementary heading correction configuration")


class StateEstimator:
    def __init__(self,config:EstimatorConfig=EstimatorConfig(),*,monotonic:Callable[[],float]=time.monotonic):
        self.config=config; self._monotonic=monotonic
        self._gps:GpsFix|None=None; self._imu:ImuReading|None=None; self._odometry:OdometrySample|None=None
        self._heading=0.0                    # arbitrary local reference until course initializes it
        self._heading_initialized=False
        self._absolute_heading=False
        self._heading_source="gyro_relative"
        self._heading_quality="RELATIVE_DRIFTING"
        self._heading_variance=math.pi**2
        self._last_imu_timestamp:datetime|None=None
        self._last_status={"gps":"NOT_SEEN","imu":"NOT_SEEN","odometry":"NOT_SEEN"}
        self._last_rejection: str|None=None
        self._source: str="UNSPECIFIED"

    def ingest_gps(self,fix:GpsFix)->bool:
        if fix.stale or fix.is_stale(self._monotonic(),self.config.gps_max_age_s):
            self._last_status["gps"]="STALE"; self._last_rejection="gps_stale"; return False
        if fix.sensor_timestamp is None:
            self._last_status["gps"]="TIME_UNKNOWN"; self._last_rejection="gps_timestamp_missing"; return False
        if self._gps and self._gps.sensor_timestamp and fix.sensor_timestamp < self._gps.sensor_timestamp:
            self._last_status["gps"]="OUT_OF_ORDER"; self._last_rejection="gps_timestamp_not_increasing"; return False
        if ((self._imu is not None and fix.source != self._imu.source)
                or (self._odometry is not None and fix.source != self._odometry.source)):
            self._last_status["gps"]="SOURCE_MISMATCH"; self._last_rejection="sensor_source_mismatch"; return False
        if self._gps and self._gps.sensor_timestamp == fix.sensor_timestamp:
            prior=self._gps
            # RMC and GGA often describe the same UTC second. Merge their fields
            # so GGA quality/satellites are retained without treating it as a
            # new position sample. Conflicting/no-fix sentences fail closed.
            coordinates_consistent=(prior.latitude is None or fix.latitude is None
                                    or (abs(prior.latitude-fix.latitude)<1e-6 and abs(prior.longitude-fix.longitude)<1e-6))
            latitude=fix.latitude if fix.latitude is not None else prior.latitude
            longitude=fix.longitude if fix.longitude is not None else prior.longitude
            valid=prior.fix_valid and fix.fix_valid and coordinates_consistent and latitude is not None and longitude is not None
            fix=replace(fix,
                fix_valid=valid,
                latitude=latitude if valid else None,
                longitude=longitude if valid else None,
                speed_mps=fix.speed_mps if fix.speed_mps is not None else prior.speed_mps,
                course_deg=fix.course_deg if fix.course_deg is not None else prior.course_deg,
                satellites=fix.satellites if fix.satellites is not None else prior.satellites,
                hdop=fix.hdop if fix.hdop is not None else prior.hdop,
                fix_quality=fix.fix_quality if fix.fix_quality is not None else prior.fix_quality,
                received_monotonic=max(prior.received_monotonic,fix.received_monotonic),
                status=f"{prior.status}+{fix.status}")
        self._gps=fix; self._source=fix.source
        self._last_status["gps"]="FIX_VALID" if fix.fix_valid else "NO_FIX"
        if not fix.fix_valid or fix.latitude is None or fix.longitude is None:
            self._last_rejection="gps_fix_invalid"; return False
        self._last_rejection=None
        if fix.course_deg is not None and fix.speed_mps is not None and fix.speed_mps>=self.config.min_course_speed_mps:
            course=_course_to_math(fix.course_deg)
            if not self._absolute_heading:
                self._heading=course; self._heading_initialized=True; self._absolute_heading=True
                self._heading_source="gps_course"; self._heading_quality="COURSE_OVER_GROUND_NO_SLIP_ASSUMPTION"
                self._heading_variance=self.config.course_heading_sigma_rad**2
            else:
                delta=_wrap(course-self._heading)
                gain=self.config.course_correction_gain
                self._heading=_wrap(self._heading+gain*delta)
                self._heading_source="gps_course+gyro"
                self._heading_quality="COMPLEMENTARY_MODEL_ESTIMATE"
                self._heading_variance=max(0.0,(1-gain)*self._heading_variance+gain*self.config.course_heading_sigma_rad**2)
        return True

    def ingest_imu(self,reading:ImuReading)->bool:
        if not reading.valid or not reading.connected:
            self._last_status["imu"]="INVALID_OR_DISCONNECTED"; self._last_rejection="imu_invalid"; return False
        if reading.is_stale(self._monotonic(),self.config.imu_max_age_s):
            self._last_status["imu"]="STALE"; self._last_rejection="imu_stale"; return False
        if self._gps is not None and reading.source!=self._gps.source:
            self._last_status["imu"]="SOURCE_MISMATCH"; self._last_rejection="sensor_source_mismatch"; return False
        if reading.gyro_rps is None:
            self._last_status["imu"]="INVALID_READING"; self._last_rejection="imu_gyro_missing"; return False
        stamp=reading.sensor_timestamp.astimezone(timezone.utc)
        if self._last_imu_timestamp is not None:
            dt=(stamp-self._last_imu_timestamp).total_seconds()
            if dt<=0:
                self._last_status["imu"]="OUT_OF_ORDER"; self._last_rejection="imu_timestamp_not_increasing"; return False
            if dt>self.config.max_imu_gap_s:
                self._last_imu_timestamp=stamp; self._imu=reading; self._source=reading.source
                self._last_status["imu"]="GAP_RESET"; self._last_rejection="imu_gap_reset"
                return False
            self._heading=_wrap(self._heading+reading.gyro_rps[2]*dt)
            self._heading_initialized=True
            self._heading_variance=min(math.pi**2,self._heading_variance+(self.config.gyro_bias_uncertainty_rps*dt)**2+self.config.gyro_noise_variance_rps2*dt)
            if self._absolute_heading:
                self._heading_source="gps_course+gyro"; self._heading_quality="COMPLEMENTARY_MODEL_ESTIMATE"
            else:
                self._heading_source="gyro_relative"; self._heading_quality="RELATIVE_DRIFTING_NO_MAGNETOMETER"
        else:
            self._heading_initialized=True
            if not self._absolute_heading:
                self._heading_source="gyro_relative"; self._heading_quality="RELATIVE_DRIFTING_NO_MAGNETOMETER"
        self._last_imu_timestamp=stamp; self._imu=reading; self._source=reading.source
        self._last_status["imu"]="CONNECTED"; self._last_rejection=None
        return True

    def ingest_odometry(self,sample:OdometrySample)->bool:
        if not math.isfinite(sample.speed_mps) or abs(sample.speed_mps)>20:
            self._last_status["odometry"]="INVALID"; self._last_rejection="odometry_out_of_range"; return False
        if self._odometry and sample.sensor_timestamp<=self._odometry.sensor_timestamp:
            self._last_status["odometry"]="OUT_OF_ORDER"; self._last_rejection="odometry_timestamp_not_increasing"; return False
        if self._gps and sample.source!=self._gps.source:
            self._last_status["odometry"]="SOURCE_MISMATCH"; self._last_rejection="sensor_source_mismatch"; return False
        self._odometry=sample; self._last_status["odometry"]="CONNECTED"; self._source=sample.source
        return True

    def mark_sensor_status(self,sensor: str,status: str)->None:
        if sensor not in self._last_status:
            raise ValueError(f"Unknown estimator sensor: {sensor}")
        self._last_status[sensor]=status

    def mark_data_source(self,source: str)->None:
        if source not in ("PHYSICAL","RECORDED","SYNTHETIC"):
            raise ValueError("Unsupported sensor data source")
        if self._source not in ("UNSPECIFIED",source):
            raise ValueError("Sensor data sources cannot be mixed")
        self._source=source

    def estimate(self)->StateEstimate:
        now_mono=self._monotonic(); gps=self._gps; imu=self._imu
        gps_fresh=bool(gps and gps.fix_valid and not gps.stale and not gps.is_stale(now_mono,self.config.gps_max_age_s))
        imu_fresh=bool(imu and imu.valid and imu.connected and not imu.is_stale(now_mono,self.config.imu_max_age_s))
        status=dict(self._last_status)
        if gps and not gps_fresh and status["gps"]=="FIX_VALID": status["gps"]="STALE"
        if imu and not imu_fresh and status["imu"]=="CONNECTED": status["imu"]="STALE"
        odom_fresh=bool(self._odometry and now_mono-self._odometry.received_monotonic<=self.config.imu_max_age_s)
        speed=gps.speed_mps if gps_fresh and gps and gps.speed_mps is not None else None
        if speed is None and odom_fresh and self._odometry: speed=self._odometry.speed_mps
        stamps=[x for x in (gps.sensor_timestamp if gps_fresh and gps else None, imu.sensor_timestamp if imu_fresh and imu else None, self._odometry.sensor_timestamp if odom_fresh and self._odometry else None) if x]
        return StateEstimate(
            latitude=gps.latitude if gps_fresh and gps else None,
            longitude=gps.longitude if gps_fresh and gps else None,
            speed_mps=speed,
            gps_course_deg=gps.course_deg if gps_fresh and gps else None,
            heading_rad=self._heading if self._heading_initialized else None,
            heading_source=self._heading_source if self._heading_initialized else "unknown",
            heading_quality=self._heading_quality if self._heading_initialized else "UNAVAILABLE",
            heading_uncertainty_rad=math.sqrt(self._heading_variance) if self._heading_initialized else None,
            gps_fix_valid=gps_fresh,
            gps_satellites=gps.satellites if gps_fresh and gps else None,
            gps_hdop=gps.hdop if gps_fresh and gps else None,
            gps_accuracy_m=gps.accuracy_m if gps_fresh and gps else None,
            gps_accuracy_status=gps.accuracy_status if gps_fresh and gps else "UNAVAILABLE",
            imu_accel_mps2=imu.accel_mps2 if imu_fresh and imu else None,
            imu_gyro_rps=imu.gyro_rps if imu_fresh and imu else None,
            sensor_timestamp=max(stamps) if stamps else None,
            gps_timestamp=gps.sensor_timestamp if gps_fresh and gps else None,
            imu_timestamp=imu.sensor_timestamp if imu_fresh and imu else None,
            sensor_status=status,
            data_source=self._source)
