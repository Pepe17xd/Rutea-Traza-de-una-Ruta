import math
from app.navigation.coordinates import LocalFrame, compass_to_math, wrap_to_pi
from app.navigation.trajectory import Point, generate_waypoints, project_to_segment, tracking_errors
from app.navigation.controller import ControlConfig, classical_controller, ml_assisted_command
from app.navigation.safety import LocalSafetySupervisor, SafetyLimits
from datetime import datetime, timezone, timedelta

def test_coordinate_roundtrip_and_axes():
    frame=LocalFrame(-12.0,-77.0); p=frame.to_local(-11.999,-76.999); lat,lon=frame.to_gps(p)
    assert abs(lat+11.999)<1e-8 and abs(lon+76.999)<1e-8 and p.x>0 and p.y>0

def test_waypoints_and_same_point_rejection():
    pts=generate_waypoints(Point(0,0),Point(2.5,0),1)
    assert pts==[Point(0,0),Point(1,0),Point(2,0),Point(2.5,0)]
    try: generate_waypoints(Point(0,0),Point(0,0))
    except ValueError: pass
    else: assert False, "A=B debe rechazarse"

def test_signed_cross_track_and_endpoint_projection():
    a,b=Point(0,0),Point(10,0)
    assert tracking_errors(a,b,Point(5,2),0)["cross_track_error_m"]==2
    assert tracking_errors(a,b,Point(5,-2),0)["cross_track_error_m"]==-2
    q,err,s=project_to_segment(a,b,Point(13,3))
    assert q==Point(10,0) and s==10 and math.isclose(err,3)
    _,past,along=project_to_segment(a,b,Point(12,0)); assert past==0 and along==10

def test_angles_and_compass_convention():
    assert abs(wrap_to_pi(-math.pi+.1-(math.pi-.1)))<.21
    assert math.isclose(compass_to_math(90),0,abs_tol=1e-9)
    assert math.isclose(compass_to_math(0),math.pi/2,abs_tol=1e-9)

def test_controller_limits_and_lateral_sign():
    cfg=ControlConfig(max_speed_mps=.4,max_angular_rps=.7)
    right=classical_controller(0,2,10,cfg); left=classical_controller(0,-2,10,cfg)
    assert right.angular_rps<0<left.angular_rps and right.linear_mps<=.4 and abs(right.angular_rps)<=.7
    limited=ml_assisted_command(right,100,.15,.7)
    assert abs(limited.angular_rps)<=.7 and limited.angular_rps>right.angular_rps

def test_local_watchdog_fails_safe_on_missing_stale_or_bad_gps():
    safe=LocalSafetySupervisor(SafetyLimits(telemetry_timeout_s=1,max_gps_accuracy_m=5))
    now=datetime.now(timezone.utc)
    assert safe.evaluate(now,2,False,False,now).stop_required is False
    assert safe.evaluate(None,None,False,False,now).reason=="telemetry_missing"
    assert safe.evaluate(now-timedelta(seconds=2),2,False,False,now).reason=="telemetry_timeout"
    assert safe.evaluate(now,8,False,False,now).reason=="gps_quality_insufficient"
    assert safe.evaluate(now,2,True,False,now).reason=="local_emergency_stop"

