from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class EmergencyStopSource(Protocol):
    """Local GPIO/controller adapter to be supplied when hardware is identified."""
    def is_engaged(self) -> bool: ...


@dataclass(frozen=True)
class SafetyDecision:
    stop_required: bool
    reason: str | None


@dataclass(frozen=True)
class SafetyLimits:
    telemetry_timeout_s: float = 1.0
    max_gps_accuracy_m: float = 25.0


class LocalSafetySupervisor:
    """Deterministic local watchdog policy; it does not drive a motor itself."""
    def __init__(self, limits: SafetyLimits = SafetyLimits()): self.limits=limits

    def evaluate(self, received_at: datetime | None, gps_accuracy_m: float | None,
                 emergency_stop: bool, stop_requested: bool,
                 now: datetime | None = None) -> SafetyDecision:
        if emergency_stop: return SafetyDecision(True,"local_emergency_stop")
        if stop_requested: return SafetyDecision(True,"stop_requested")
        if received_at is None: return SafetyDecision(True,"telemetry_missing")
        current=now or datetime.now(timezone.utc)
        if received_at.tzinfo is None: return SafetyDecision(True,"timestamp_without_timezone")
        age=(current-received_at.astimezone(timezone.utc)).total_seconds()
        if age < -1: return SafetyDecision(True,"telemetry_from_future")
        if age > self.limits.telemetry_timeout_s: return SafetyDecision(True,"telemetry_timeout")
        if gps_accuracy_m is None or gps_accuracy_m > self.limits.max_gps_accuracy_m:
            return SafetyDecision(True,"gps_quality_insufficient")
        return SafetyDecision(False,None)
