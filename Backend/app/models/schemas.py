from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator


class GeoPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class MissionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class DeviceStatus(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    ARRIVED = "ARRIVED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class MissionCreate(BaseModel):
    robot_id: str = Field(min_length=1, max_length=80)
    destination: GeoPoint
    goal_tolerance_m: float = Field(default=1.5, gt=0, le=20)
    max_speed_mps: float = Field(default=0.5, gt=0, le=2)
    controller: str = Field(default="classical", pattern="^classical$")


class Mission(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    mission_id: str
    robot_id: str
    created_at: datetime
    updated_at: datetime
    status: MissionStatus
    origin: GeoPoint
    destination: GeoPoint
    waypoints: list[GeoPoint]
    distance_m: float
    goal_tolerance_m: float
    max_speed_mps: float
    controller_version: str = "pd-1.0"
    model_version: str | None = None
    stop_requested_at: datetime | None = None
    stop_confirmed: bool = False
    command_sequence: int | None = None
    command_expires_at: datetime | None = None
    command_delivery_status: str | None = None
    command_acknowledged_at: datetime | None = None
    metrics: dict[str, Any] | None = None


class DestinationAck(BaseModel):
    sequence: int = Field(ge=1)
    status: str = Field(pattern="^(RECEIVED|REJECTED_EXPIRED|REJECTED_DUPLICATE|REJECTED_INVALID)$")
    payload: str = Field(min_length=5, max_length=64)


class PumpCommandRequest(BaseModel):
    command: str = Field(pattern="^(ON|OFF)$")


class TelemetryIn(BaseModel):
    robot_id: str = Field(min_length=1, max_length=80)
    device_id: str = Field(min_length=1, max_length=80)
    mission_id: str | None = None
    sequence: int = Field(ge=0)
    timestamp: datetime
    lat: FiniteFloat | None = Field(default=None, ge=-90, le=90)
    lon: FiniteFloat | None = Field(default=None, ge=-180, le=180)
    heading_deg: FiniteFloat | None = Field(default=None, ge=0, lt=360)
    heading_relative_rad: FiniteFloat | None = Field(default=None, ge=-6.284, le=6.284)
    speed_mps: FiniteFloat | None = Field(default=None, ge=-10, le=10)
    gps_accuracy_m: FiniteFloat | None = Field(default=None, gt=0, le=10000)
    gps_accuracy_status: str | None = Field(default=None, pattern="^(MEASURED|ESTIMATED|UNAVAILABLE|SOURCE_UNSPECIFIED)$")
    gps_accuracy_source: str | None = Field(default=None, max_length=80)
    gps_accuracy_is_bound: bool | None = None
    gps_fix_valid: bool | None = None
    gps_satellites: int | None = Field(default=None, ge=0, le=99)
    gps_hdop: FiniteFloat | None = Field(default=None, ge=0, le=999)
    gps_course_deg: FiniteFloat | None = Field(default=None, ge=0, lt=360)
    imu_accel_mps2: dict[str, FiniteFloat] | None = None
    imu_gyro_rps: dict[str, FiniteFloat] | None = None
    heading_source: str | None = Field(default=None, max_length=40)
    heading_quality: str | None = Field(default=None, max_length=80)
    heading_uncertainty_rad: FiniteFloat | None = Field(default=None, ge=0, le=6.284)
    gps_timestamp: datetime | None = None
    imu_timestamp: datetime | None = None
    sensor_timestamp: datetime | None = None
    sensor_status: dict[str, Any] | None = None
    data_source: str = Field(default="UNSPECIFIED", pattern="^(PHYSICAL|RECORDED|SYNTHETIC|UNSPECIFIED)$")
    status: DeviceStatus = DeviceStatus.IDLE
    linear_cmd_mps: float | None = Field(default=None, ge=0, le=2)
    angular_cmd_rps: float | None = Field(default=None, ge=-2, le=2)
    controller_version: str | None = Field(default=None, max_length=80)
    model_version: str | None = Field(default=None, max_length=80)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp debe incluir zona horaria")
        return value.astimezone(timezone.utc)

    @field_validator("sensor_timestamp", "gps_timestamp", "imu_timestamp")
    @classmethod
    def optional_timestamps_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamp del sensor debe incluir zona horaria")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def coordinate_pair_and_fix(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat y lon deben enviarse juntas")
        if self.gps_fix_valid is True and self.lat is None:
            raise ValueError("un fix GPS válido requiere latitud y longitud")
        if self.gps_fix_valid is False and self.lat is not None:
            raise ValueError("Invalid GPS fix cannot carry measured coordinates")
        if self.gps_accuracy_is_bound is True and self.gps_accuracy_m is None:
            raise ValueError("A guaranteed accuracy bound requires gps_accuracy_m")
        if self.gps_accuracy_source == "UBX_NAV_POSLLH.hAcc" and (self.gps_accuracy_status != "ESTIMATED" or self.gps_accuracy_is_bound is not False):
            raise ValueError("u-blox hAcc must be declared estimated and not a guaranteed bound")
        if self.imu_accel_mps2 is not None and set(self.imu_accel_mps2) != {"x", "y", "z"}:
            raise ValueError("imu_accel_mps2 requiere ejes x, y, z")
        if self.imu_gyro_rps is not None and set(self.imu_gyro_rps) != {"x", "y", "z"}:
            raise ValueError("imu_gyro_rps requiere ejes x, y, z")
        return self


class Telemetry(BaseModel):
    robot_id: str
    device_id: str
    mission_id: str | None
    sequence: int
    timestamp: datetime
    lat: float | None = None
    lon: float | None = None
    heading_deg: float | None = None
    heading_rad: float | None = None
    heading_relative_rad: float | None = None
    speed_mps: float | None = None
    gps_accuracy_m: float | None = None
    gps_accuracy_status: str | None = None
    gps_accuracy_source: str | None = None
    gps_accuracy_is_bound: bool | None = None
    gps_fix_valid: bool | None = None
    gps_satellites: int | None = None
    gps_hdop: float | None = None
    gps_course_deg: float | None = None
    imu_accel_mps2: dict[str, float] | None = None
    imu_gyro_rps: dict[str, float] | None = None
    heading_source: str | None = None
    heading_quality: str | None = None
    heading_uncertainty_rad: float | None = None
    gps_timestamp: datetime | None = None
    imu_timestamp: datetime | None = None
    sensor_timestamp: datetime | None = None
    sensor_status: dict[str, Any] | None = None
    data_source: str = "UNSPECIFIED"
    status: DeviceStatus
    linear_cmd_mps: float | None = None
    angular_cmd_rps: float | None = None
    controller_version: str | None = None
    model_version: str | None = None
    cross_track_error_m: float | None = None
    heading_error_rad: float | None = None
    distance_to_goal_m: float | None = None


class TracePage(BaseModel):
    items: list[Telemetry]
    next_cursor: str | None


class MissionPage(BaseModel):
    items: list[Mission]
    next_cursor: str | None


class StopResult(BaseModel):
    mission_id: str
    status: MissionStatus
    stop_requested: bool = True
    stop_confirmed: bool = False
    message: str = "Solicitud registrada; la detencion fisica requiere confirmacion del controlador local."

