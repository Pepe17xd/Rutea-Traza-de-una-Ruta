from pyproj import CRS, Transformer
from .trajectory import Point


class LocalFrame:
    """AEQD local en WGS84: coordenadas métricas x=este, y=norte."""
    def __init__(self, origin_lat: float, origin_lon: float):
        self.origin_lat, self.origin_lon = origin_lat, origin_lon
        local = CRS.from_proj4(f"+proj=aeqd +lat_0={origin_lat} +lon_0={origin_lon} +datum=WGS84 +units=m +no_defs")
        self.forward = Transformer.from_crs("EPSG:4326", local, always_xy=True)
        self.inverse = Transformer.from_crs(local, "EPSG:4326", always_xy=True)
        self.crs = local.to_string()

    def to_local(self, lat: float, lon: float) -> Point:
        x, y = self.forward.transform(lon, lat)
        return Point(float(x), float(y))

    def to_gps(self, point: Point) -> tuple[float, float]:
        lon, lat = self.inverse.transform(point.x, point.y)
        return float(lat), float(lon)


def compass_to_math(heading_deg: float) -> float:
    """Compass bearing (0=N, clockwise) to mathematical radians (0=E, CCW)."""
    import math
    return wrap_to_pi(math.pi / 2 - math.radians(heading_deg))


def wrap_to_pi(angle: float) -> float:
    import math
    return (angle + math.pi) % (2 * math.pi) - math.pi
