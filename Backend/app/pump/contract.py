from dataclasses import asdict, dataclass
from typing import Literal

PumpWord = Literal["ON", "OFF"]


@dataclass(frozen=True)
class PumpInterlocks:
    gps_valid_and_fresh: bool = False
    forward_motion_confirmed: bool = False
    not_turning_in_place: bool = False
    motion_not_stopped: bool = False
    communication_healthy: bool = False
    estop_clear: bool = False
    physical_feedback_available: bool = False


def may_authorize_on(interlocks: PumpInterlocks) -> bool:
    """Pure authorization predicate. It never writes a GPIO or claims a pump state."""
    return all(asdict(interlocks).values())


def simulated_pump_exchange(robot_id: str, command: str) -> dict:
    if command not in ("ON", "OFF"):
        raise ValueError("La palabra Bluetooth debe ser exactamente ON u OFF")
    # There is intentionally no Bluetooth client, relay, GPIO, or physical state source.
    return {
        "robot_id": robot_id,
        "command": command,
        "wire_payload": command,
        "transport": "SIMULATED",
        "receipt": "SIMULATED_RECEIPT",
        "authorization": "NOT_AUTHORIZED_NO_PHYSICAL_INTERLOCKS",
        "confirmed_state": None,
        "physical_output_enabled": False,
    }
