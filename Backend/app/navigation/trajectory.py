from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def __add__(self, other): return Point(self.x + other.x, self.y + other.y)
    def __sub__(self, other): return Point(self.x - other.x, self.y - other.y)
    def __mul__(self, scalar: float): return Point(self.x * scalar, self.y * scalar)


def distance(a: Point, b: Point) -> float:
    return math.hypot(b.x-a.x, b.y-a.y)


def generate_waypoints(a: Point, b: Point, delta_m: float = 1.0, epsilon: float = 1e-6) -> list[Point]:
    if delta_m <= 0: raise ValueError("delta_m debe ser positivo")
    length = distance(a, b)
    if length < epsilon: raise ValueError("origen y destino coinciden")
    unit = Point((b.x-a.x)/length, (b.y-a.y)/length)
    points = [a + unit * s for s in [i * delta_m for i in range(int(length // delta_m) + 1)]]
    if distance(points[-1], b) > epsilon: points.append(b)
    else: points[-1] = b
    return points


def project_to_segment(a: Point, b: Point, p: Point) -> tuple[Point, float, float]:
    length = distance(a, b)
    if length < 1e-9: return a, 0.0, 0.0
    ux, uy = (b.x-a.x)/length, (b.y-a.y)/length
    s = min(length, max(0.0, (p.x-a.x)*ux + (p.y-a.y)*uy))
    q = Point(a.x+s*ux, a.y+s*uy)
    cross = (p.x-q.x)*(-uy) + (p.y-q.y)*ux
    return q, cross, s


def tracking_errors(a: Point, b: Point, p: Point, heading_rad: float | None) -> dict[str, float | None]:
    _, lateral, _ = project_to_segment(a, b, p)
    if heading_rad is None: heading_error = None
    elif distance(a, b) < 1e-9: heading_error = 0.0
    else: heading_error = wrap_to_pi(math.atan2(b.y-a.y, b.x-a.x)-heading_rad)
    return {"cross_track_error_m": lateral, "heading_error_rad": heading_error, "distance_to_goal_m": distance(p, b)}


def wrap_to_pi(angle: float) -> float:
    return (angle + math.pi) % (2*math.pi) - math.pi
