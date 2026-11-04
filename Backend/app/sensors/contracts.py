from datetime import datetime, timezone
import math
from typing import Protocol
from app.models.schemas import TelemetryIn


class TelemetrySource(Protocol):
    """Adapter contract for a future GPS/IMU gateway or normalized network feed."""
    def read(self) -> TelemetryIn | None: ...


class NormalizedTelemetryAdapter:
    """Pass-through adapter for already normalized HECTOR telemetry."""
    def normalize(self, payload: dict) -> TelemetryIn:
        return TelemetryIn.model_validate(payload)


def estimate_to_telemetry(estimate, *, robot_id: str, device_id: str, sequence: int,
                          status="IDLE", timestamp: datetime | None = None) -> TelemetryIn:
    """Map an estimator snapshot into the public normalized ingestion contract.

    Gyro-only yaw stays in `heading_relative_rad`; heading_deg is populated only
    when the estimate has a GPS course reference. This adapter never promotes
    HDOP to a metric accuracy.
    """
    absolute = estimate.heading_source in ("gps_course", "gps_course+gyro")
    heading_deg = None
    if absolute and estimate.heading_rad is not None:
        heading_deg = (90.0 - math.degrees(estimate.heading_rad)) % 360.0
    sensor_status = dict(estimate.sensor_status)
    return TelemetryIn(
        robot_id=robot_id,
        device_id=device_id,
        sequence=sequence,
        timestamp=timestamp or datetime.now(timezone.utc),
        lat=estimate.latitude,
        lon=estimate.longitude,
        heading_deg=heading_deg,
        heading_relative_rad=estimate.heading_rad if not absolute else None,
        speed_mps=estimate.speed_mps,
        gps_accuracy_m=estimate.gps_accuracy_m,
        gps_accuracy_status=estimate.gps_accuracy_status,
        gps_fix_valid=estimate.gps_fix_valid,
        gps_satellites=estimate.gps_satellites,
        gps_hdop=estimate.gps_hdop,
        gps_course_deg=estimate.gps_course_deg,
        imu_accel_mps2=(dict(zip(("x", "y", "z"), estimate.imu_accel_mps2))
                        if estimate.imu_accel_mps2 is not None else None),
        imu_gyro_rps=(dict(zip(("x", "y", "z"), estimate.imu_gyro_rps))
                      if estimate.imu_gyro_rps is not None else None),
        heading_source=estimate.heading_source,
        heading_quality=estimate.heading_quality,
        heading_uncertainty_rad=estimate.heading_uncertainty_rad,
        gps_timestamp=estimate.gps_timestamp,
        imu_timestamp=estimate.imu_timestamp,
        sensor_timestamp=estimate.sensor_timestamp,
        sensor_status=sensor_status,
        data_source=estimate.data_source if estimate.data_source in ("PHYSICAL", "RECORDED", "SYNTHETIC") else "UNSPECIFIED",
        status=status,
    )
