from dataclasses import dataclass
import math
import numpy as np
from app.navigation.controller import ControlConfig, classical_controller
from app.navigation.trajectory import Point, distance, tracking_errors
from app.navigation.coordinates import wrap_to_pi


@dataclass
class SimState:
    position: Point
    heading_rad: float
    speed_mps: float = 0.0
    angular_rps: float = 0.0


def run_episode(seed: int = 42, dt_s: float = .1, max_time_s: float = 180.0,
                noise_m: float = .02, goal_tolerance_m: float = 1.5,
                config: ControlConfig | None = None) -> dict:
    """Deterministic differential-drive simulation with optional seeded pose noise."""
    rng=np.random.default_rng(seed); config=config or ControlConfig()
    a=Point(0,0); b=Point(float(rng.uniform(15,35)),float(rng.uniform(-4,4)))
    state=SimState(Point(float(rng.uniform(-2,2)),float(rng.uniform(-4,4))),float(rng.uniform(-math.pi,math.pi)))
    samples=[]; arrived_count=0; previous_omega=0.0
    for tick in range(int(max_time_s/dt_s)):
        measured=Point(state.position.x+rng.normal(0,noise_m),state.position.y+rng.normal(0,noise_m))
        errors=tracking_errors(a,b,measured,state.heading_rad)
        command=classical_controller(errors["heading_error_rad"],errors["cross_track_error_m"],errors["distance_to_goal_m"],config,previous_omega,dt_s,previous_v_mps=state.speed_mps)
        state.speed_mps=command.linear_mps; state.angular_rps=command.angular_rps
        state.position=Point(state.position.x+state.speed_mps*math.cos(state.heading_rad)*dt_s,state.position.y+state.speed_mps*math.sin(state.heading_rad)*dt_s)
        state.heading_rad=wrap_to_pi(state.heading_rad+state.angular_rps*dt_s)
        previous_omega=state.angular_rps
        samples.append({"t_s":(tick+1)*dt_s,"x_m":measured.x,"y_m":measured.y,**errors,"linear_mps":state.speed_mps,"angular_rps":state.angular_rps})
        settled=errors["distance_to_goal_m"]<=goal_tolerance_m and abs(state.speed_mps)<=.08
        arrived_count=arrived_count+1 if settled else 0
        if arrived_count>=3: break
    lateral=np.asarray([x["cross_track_error_m"] for x in samples],dtype=float)
    success=arrived_count>=3
    return {"source":"SYNTHETIC_SIMULATION","seed":seed,"dt_s":dt_s,"origin":{"x_m":a.x,"y_m":a.y},"destination":{"x_m":b.x,"y_m":b.y},"arrived":success,"duration_s":samples[-1]["t_s"],"sample_count":len(samples),"rmse_lateral_m":float(np.sqrt(np.mean(lateral**2))),"max_lateral_error_m":float(np.max(np.abs(lateral))),"trace":samples}
