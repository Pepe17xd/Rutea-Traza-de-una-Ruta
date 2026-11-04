from dataclasses import dataclass
from .trajectory import wrap_to_pi


@dataclass(frozen=True)
class ControlConfig:
    k_heading: float = 1.8
    k_lateral: float = 0.65
    k_speed: float = 0.7
    max_speed_mps: float = 0.5
    max_angular_rps: float = 1.2
    min_turn_speed_scale: float = 0.2


@dataclass(frozen=True)
class ControlCommand:
    linear_mps: float
    angular_rps: float


def classical_controller(heading_error_rad: float, cross_track_error_m: float,
                         distance_to_goal_m: float, config: ControlConfig = ControlConfig(),
                         previous_omega_rps: float = 0.0, dt_s: float | None = None,
                         max_angular_accel_rps2: float = 3.0, previous_v_mps: float = 0.0,
                         max_linear_accel_mps2: float = 0.8) -> ControlCommand:
    omega = max(-config.max_angular_rps, min(config.max_angular_rps,
        config.k_heading*wrap_to_pi(heading_error_rad)-config.k_lateral*cross_track_error_m))
    if dt_s is not None:
        bound = max_angular_accel_rps2 * max(0.0, dt_s)
        omega = max(previous_omega_rps-bound, min(previous_omega_rps+bound, omega))
    speed = min(config.max_speed_mps, max(0.0, config.k_speed * max(0.0, distance_to_goal_m)))
    speed *= max(config.min_turn_speed_scale, 1.0 - abs(wrap_to_pi(heading_error_rad))/3.141592653589793)
    if dt_s is not None:
        bound = max_linear_accel_mps2 * max(0.0, dt_s)
        speed = max(previous_v_mps-bound, min(previous_v_mps+bound, speed))
    speed = max(0.0, min(config.max_speed_mps, speed))
    return ControlCommand(speed, omega)


def ml_assisted_command(base: ControlCommand, correction_rps: float, ml_limit_rps: float,
                        omega_max_rps: float) -> ControlCommand:
    correction = max(-ml_limit_rps, min(ml_limit_rps, correction_rps))
    return ControlCommand(base.linear_mps, max(-omega_max_rps, min(omega_max_rps, base.angular_rps+correction)))
