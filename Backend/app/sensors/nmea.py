"""u-blox NEO-6M NMEA RMC/GGA parser and UART/file adapters.

No accuracy in metres is inferred from HDOP. NMEA sources do not provide a
metric accuracy field in these sentences, so `accuracy_m` remains None.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import math
import time as time_module
from typing import Callable, Literal


DataSource = Literal["PHYSICAL", "RECORDED"]


class NmeaError(ValueError):
    pass


@dataclass(frozen=True)
class GpsFix:
    fix_valid: bool
    latitude: float | None
    longitude: float | None
    speed_mps: float | None
    course_deg: float | None
    sensor_timestamp: datetime | None
    fix_quality: int | None
    satellites: int | None
    hdop: float | None
    accuracy_m: float | None
    accuracy_status: str
    received_monotonic: float
    source: DataSource
    status: str
    stale: bool = False

    def is_stale(self, now_monotonic: float, max_age_s: float) -> bool:
        return now_monotonic - self.received_monotonic > max_age_s


def validate_checksum(sentence: str) -> str:
    """Return the NMEA payload between `$` and `*HH`; reject bad checksums."""
    line = sentence.strip()
    if not line.startswith("$") or "*" not in line:
        raise NmeaError("NMEA requires '$' and '*HH' checksum")
    payload, check = line[1:].rsplit("*", 1)
    if len(check) != 2:
        raise NmeaError("NMEA checksum must have two hexadecimal digits")
    try:
        expected = int(check, 16)
    except ValueError as exc:
        raise NmeaError("NMEA checksum is not hexadecimal") from exc
    calculated = 0
    for byte in payload.encode("ascii", errors="strict"):
        calculated ^= byte
    if calculated != expected:
        raise NmeaError("NMEA checksum mismatch")
    return payload


def _number(value: str) -> float | None:
    if value == "":
        return None
    try:
        result = float(value)
    except ValueError as exc:
        raise NmeaError(f"Invalid numeric field: {value!r}") from exc
    if not math.isfinite(result):
        raise NmeaError("NMEA numeric field is not finite")
    return result


def parse_coordinate(value: str, hemisphere: str, latitude: bool) -> float:
    """Convert NMEA ddmm.mmmm / dddmm.mmmm to signed decimal degrees."""
    raw = _number(value)
    if raw is None or raw < 0:
        raise NmeaError("Coordinate is missing or negative")
    degrees = int(raw // 100)
    minutes = raw - degrees * 100
    bound = 90 if latitude else 180
    if minutes >= 60 or degrees > bound or (degrees == bound and minutes != 0):
        raise NmeaError("Coordinate outside WGS84 bounds")
    allowed = ("N", "S") if latitude else ("E", "W")
    if hemisphere not in allowed:
        raise NmeaError("Invalid coordinate hemisphere")
    result = degrees + minutes / 60
    return -result if hemisphere in ("S", "W") else result


def _parse_tod(value: str) -> time:
    try:
        hour = int(value[0:2]); minute = int(value[2:4]); seconds = float(value[4:])
        whole = int(seconds); microseconds = round((seconds - whole) * 1_000_000)
        if microseconds == 1_000_000:
            whole += 1; microseconds = 0
        base = datetime(2000, 1, 1, hour, minute, whole, microseconds, tzinfo=timezone.utc)
        return base.timetz()
    except (ValueError, IndexError) as exc:
        raise NmeaError("Invalid UTC time field") from exc


def _parse_rmc_date(value: str) -> date:
    if len(value) != 6 or not value.isdigit():
        raise NmeaError("RMC date must be ddmmyy")
    day, month, year = int(value[:2]), int(value[2:4]), int(value[4:])
    year += 1900 if year >= 80 else 2000
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise NmeaError("Invalid RMC calendar date") from exc


def _combine(day: date | None, tod: time | None) -> datetime | None:
    if day is None or tod is None:
        return None
    return datetime.combine(day, tod, tzinfo=timezone.utc)


class NmeaParser:
    def __init__(self, *, source: DataSource = "RECORDED", min_course_speed_mps: float = 0.5,
                 monotonic: Callable[[], float] = time_module.monotonic):
        if min_course_speed_mps < 0:
            raise ValueError("min_course_speed_mps must be non-negative")
        self.source = source
        self.min_course_speed_mps = min_course_speed_mps
        self._monotonic = monotonic
        self._date: date | None = None
        self._last_timestamp: datetime | None = None
        self._latest_by_tod: dict[time, GpsFix] = {}
        self.bad_checksums = 0
        self.invalid_sentences = 0

    def parse(self, sentence: str) -> GpsFix | None:
        try:
            payload = validate_checksum(sentence)
            fields = payload.split(",")
            kind = fields[0][-3:]
            if kind == "RMC":
                fix = self._parse_rmc(fields)
            elif kind == "GGA":
                fix = self._parse_gga(fields)
            else:
                return None
            if fix.sensor_timestamp is not None:
                if self._last_timestamp and fix.sensor_timestamp < self._last_timestamp - timedelta(hours=12):
                    self._date = self._date + timedelta(days=1) if self._date else None
                    fix = replace(fix, sensor_timestamp=_combine(self._date, fix.sensor_timestamp.timetz()))
                self._last_timestamp = fix.sensor_timestamp
            if fix.sensor_timestamp:
                self._latest_by_tod[fix.sensor_timestamp.timetz()] = fix
                if len(self._latest_by_tod) > 4:
                    oldest = min(self._latest_by_tod, key=lambda t: _combine(self._date, t) or datetime.min.replace(tzinfo=timezone.utc))
                    self._latest_by_tod.pop(oldest, None)
            return fix
        except NmeaError as exc:
            if "checksum" in str(exc).lower():
                self.bad_checksums += 1
            else:
                self.invalid_sentences += 1
            return None
        except (UnicodeEncodeError, IndexError, OverflowError):
            self.invalid_sentences += 1
            return None

    def _parse_rmc(self, fields: list[str]) -> GpsFix:
        if len(fields) < 10:
            raise NmeaError("RMC requires at least 10 fields")
        tod = _parse_tod(fields[1])
        status = fields[2]
        if status not in ("A", "V"):
            raise NmeaError("RMC status must be A or V")
        self._date = _parse_rmc_date(fields[9])
        stamp = _combine(self._date, tod)
        valid = status == "A"
        lat = lon = None
        if valid:
            lat = parse_coordinate(fields[3], fields[4], True)
            lon = parse_coordinate(fields[5], fields[6], False)
        knots = _number(fields[7])
        speed = knots * 0.5144444444444445 if knots is not None else None
        course = _number(fields[8])
        if not valid:
            speed = None
            course = None
        if course is not None and not 0 <= course < 360:
            raise NmeaError("RMC course outside [0, 360)")
        if speed is None or speed < self.min_course_speed_mps:
            course = None
        return GpsFix(valid, lat, lon, speed, course, stamp, None, None, None,
                      None, "UNAVAILABLE", self._monotonic(),
                      self.source, "RMC_VALID" if valid else "RMC_VOID")

    def _parse_gga(self, fields: list[str]) -> GpsFix:
        if len(fields) < 10:
            raise NmeaError("GGA requires at least 10 fields")
        tod = _parse_tod(fields[1])
        try:
            quality = int(fields[6])
            satellites = int(fields[7]) if fields[7] else None
        except ValueError as exc:
            raise NmeaError("Invalid GGA fix quality or satellite count") from exc
        hdop = _number(fields[8])
        if quality < 0 or (satellites is not None and satellites < 0) or (hdop is not None and hdop < 0):
            raise NmeaError("Negative GGA quality metadata")
        stamp = _combine(self._date, tod)
        valid = quality > 0
        lat = lon = None
        if valid:
            lat = parse_coordinate(fields[2], fields[3], True)
            lon = parse_coordinate(fields[4], fields[5], False)
        prior = self._latest_by_tod.get(tod)
        return GpsFix(valid, lat, lon,
                      prior.speed_mps if prior else None,
                      prior.course_deg if prior else None,
                      stamp, quality, satellites, hdop, None,
                      "UNAVAILABLE", self._monotonic(),
                      self.source, "GGA_FIX" if valid else "GGA_NO_FIX")


@dataclass(frozen=True)
class Neo6mConfig:
    port: str
    baudrate: int = 9600
    nominal_frequency_hz: float = 1.0
    max_age_s: float = 3.5
    read_timeout_s: float = 0.25
    reconnect_delay_s: float = 2.0
    min_course_speed_mps: float = 0.5

    def __post_init__(self):
        if not self.port or self.baudrate <= 0 or self.nominal_frequency_hz <= 0:
            raise ValueError("UART port, baudrate and nominal frequency must be valid")
        if self.max_age_s <= 0 or self.read_timeout_s <= 0 or self.reconnect_delay_s < 0:
            raise ValueError("Invalid NEO-6M timeout configuration")


class Neo6mAdapter:
    """Configurable UART driver; serial transport is imported only on use."""
    def __init__(self, config: Neo6mConfig, *, serial_factory=None,
                 monotonic: Callable[[], float] = time_module.monotonic):
        self.config = config
        self._serial_factory = serial_factory
        self._monotonic = monotonic
        self.parser = NmeaParser(source="PHYSICAL", min_course_speed_mps=config.min_course_speed_mps, monotonic=monotonic)
        self._serial = None
        self._retry_at = 0.0
        self.status = "DISCONNECTED"
        self.last_error: str | None = None
        self.reconnect_count = 0
        self._latest: GpsFix | None = None

    def _connect(self) -> bool:
        if self._serial is not None:
            return True
        if self._monotonic() < self._retry_at:
            return False
        try:
            factory = self._serial_factory
            if factory is None:
                import serial
                factory = serial.Serial
            self._serial = factory(self.config.port, self.config.baudrate, timeout=self.config.read_timeout_s)
            self.status = "CONNECTED_NO_FIX"
            self.last_error = None
            self.reconnect_count += 1
            return True
        except Exception as exc:
            self._serial = None
            self.status = "DISCONNECTED"
            self.last_error = str(exc)
            self._retry_at = self._monotonic() + self.config.reconnect_delay_s
            return False

    def read(self) -> GpsFix | None:
        if not self._connect():
            return self._current()
        try:
            raw = self._serial.readline()
            if raw:
                try:
                    line = raw.decode("ascii", errors="strict") if isinstance(raw, bytes) else str(raw)
                except UnicodeDecodeError:
                    self.parser.invalid_sentences += 1
                    return self._current()
                fix = self.parser.parse(line)
                if fix is not None:
                    self._latest = fix
                    self.status = "FIX_VALID" if fix.fix_valid else "NO_FIX"
            return self._current()
        except Exception as exc:
            self.last_error = str(exc)
            self.status = "DISCONNECTED"
            self._close_serial()
            self._retry_at = self._monotonic() + self.config.reconnect_delay_s
            return self._current()

    def _current(self) -> GpsFix | None:
        if self._latest is None:
            return None
        stale = self._latest.is_stale(self._monotonic(), self.config.max_age_s)
        if stale:
            self.status = "STALE"
        return replace(self._latest, stale=stale)

    def _close_serial(self):
        if self._serial is not None:
            try: self._serial.close()
            except Exception: pass
        self._serial = None

    def close(self):
        self._close_serial()
        self.status = "DISCONNECTED"


class NmeaRecordingSource:
    """Replay a captured NMEA file; every returned fix is labeled RECORDED."""
    def __init__(self, path: str | Path, *, min_course_speed_mps: float = 0.5,
                 monotonic: Callable[[], float] = time_module.monotonic):
        self.path = Path(path)
        self.parser = NmeaParser(source="RECORDED", min_course_speed_mps=min_course_speed_mps, monotonic=monotonic)
        self._file = self.path.open("r", encoding="ascii")

    def read(self) -> GpsFix | None:
        for line in self._file:
            fix = self.parser.parse(line)
            if fix is not None:
                return fix
        return None

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
