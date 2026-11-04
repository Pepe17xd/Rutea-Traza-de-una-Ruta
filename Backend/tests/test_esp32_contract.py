from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.schemas import TelemetryIn


def payload(**overrides):
    value = {
        "robot_id": "CAR_01", "device_id": "esp32-hector-01", "sequence": 7,
        "timestamp": datetime.now(timezone.utc).isoformat(), "lat": -12.0464, "lon": -77.0428,
        "gps_fix_valid": True, "gps_accuracy_m": 1.234, "gps_accuracy_status": "ESTIMATED",
        "gps_accuracy_source": "UBX_NAV_POSLLH.hAcc", "gps_accuracy_is_bound": False,
        "gps_satellites": 8, "gps_hdop": 0.9, "gps_course_deg": 90.0,
        "imu_accel_mps2": {"x": 0.0, "y": 0.0, "z": 9.80665},
        "imu_gyro_rps": {"x": 0.0, "y": 0.0, "z": 0.01},
        "heading_source": "gps_course", "heading_quality": "COURSE_OVER_GROUND_NO_SLIP_ASSUMPTION",
        "sensor_status": {"esp32": "CONNECTED", "wifi": "CONNECTED", "gps": "FIX_VALID", "imu": "CONNECTED"},
        "data_source": "PHYSICAL", "status": "IDLE",
    }
    return value | overrides


def test_esp32_telemetry_contract_keeps_hacc_provenance_and_bound_semantics():
    model = TelemetryIn.model_validate(payload())
    assert model.gps_accuracy_source == "UBX_NAV_POSLLH.hAcc"
    assert model.gps_accuracy_status == "ESTIMATED"
    assert model.gps_accuracy_is_bound is False
    assert model.sensor_status["esp32"] == "CONNECTED"


def test_invalid_fix_cannot_carry_coordinates():
    with pytest.raises(ValidationError):
        TelemetryIn.model_validate(payload(gps_fix_valid=False))


def test_accuracy_source_length_is_bounded():
    with pytest.raises(ValidationError):
        TelemetryIn.model_validate(payload(gps_accuracy_source="x" * 81))
