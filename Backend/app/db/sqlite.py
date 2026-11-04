import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from .repository import Repository


class SQLiteRepository(Repository):
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:": Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init(self):
        with self._connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("CREATE TABLE IF NOT EXISTS missions (mission_id TEXT PRIMARY KEY, robot_id TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL)")
            c.execute("CREATE INDEX IF NOT EXISTS mission_robot_created ON missions(robot_id, created_at DESC)")
            c.execute("CREATE TABLE IF NOT EXISTS telemetry (robot_id TEXT NOT NULL, sequence INTEGER NOT NULL, mission_id TEXT, timestamp TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(robot_id, sequence))")
            c.execute("CREATE INDEX IF NOT EXISTS telemetry_mission_time ON telemetry(mission_id, timestamp, sequence)")
            c.execute("CREATE TABLE IF NOT EXISTS device_bindings (robot_id TEXT PRIMARY KEY, device_id TEXT NOT NULL)")

    def create_mission(self, mission):
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            existing=c.execute("SELECT mission_id FROM missions WHERE robot_id=? AND status IN ('PENDING','ACTIVE') LIMIT 1",(mission["robot_id"],)).fetchone()
            if existing: raise ValueError("El robot ya tiene una misión pendiente o activa")
            c.execute("INSERT INTO missions VALUES(?,?,?,?,?)", (mission["mission_id"], mission["robot_id"], mission["created_at"], mission["status"], json.dumps(mission)))

    def get_mission(self, mission_id):
        with self._connect() as c:
            row = c.execute("SELECT data FROM missions WHERE mission_id=?", (mission_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def update_mission(self, mission):
        with self._connect() as c:
            c.execute("UPDATE missions SET status=?, data=? WHERE mission_id=?", (mission["status"], json.dumps(mission), mission["mission_id"]))

    def get_active_mission(self, robot_id):
        with self._connect() as c:
            row = c.execute(
                "SELECT data FROM missions WHERE robot_id=? AND status IN ('PENDING','ACTIVE') ORDER BY created_at DESC LIMIT 1",
                (robot_id,),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def latest_command_sequence(self, robot_id):
        with self._connect() as c:
            row = c.execute(
                "SELECT data FROM missions WHERE robot_id=? ORDER BY created_at DESC LIMIT 1",
                (robot_id,),
            ).fetchone()
            return int((json.loads(row[0]).get("command_sequence") or 0)) if row else 0

    def list_missions(self, robot_id, limit, cursor):
        offset=int(cursor or 0)
        with self._connect() as c:
            where, params = (" WHERE robot_id=?", [robot_id]) if robot_id else ("", [])
            rows = c.execute("SELECT data FROM missions" + where + " ORDER BY created_at DESC LIMIT ? OFFSET ?", [*params, limit+1, offset]).fetchall()
            has_more = len(rows) > limit
            return [json.loads(r[0]) for r in rows[:limit]], (str(offset+limit) if has_more else None)

    def latest_telemetry(self, robot_id):
        with self._connect() as c:
            row = c.execute("SELECT data FROM telemetry WHERE robot_id=? ORDER BY sequence DESC LIMIT 1", (robot_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def append_telemetry(self, data):
        with self._connect() as c:
            bind = c.execute("SELECT device_id FROM device_bindings WHERE robot_id=?", (data["robot_id"],)).fetchone()
            if bind and bind[0] != data["device_id"]:
                raise ValueError("device_id no coincide con el dispositivo vinculado al robot")
            if not bind:
                c.execute("INSERT INTO device_bindings VALUES(?,?)", (data["robot_id"], data["device_id"]))
            row = c.execute("SELECT MAX(sequence) FROM telemetry WHERE robot_id=?", (data["robot_id"],)).fetchone()
            if row[0] is not None and data["sequence"] <= row[0]: return False
            c.execute("INSERT INTO telemetry VALUES(?,?,?,?,?)", (data["robot_id"], data["sequence"], data.get("mission_id"), data["timestamp"], json.dumps(data)))
            return True

    def list_trace(self, mission_id, limit, cursor):
        offset=int(cursor or 0)
        with self._connect() as c:
            rows = c.execute("SELECT data FROM telemetry WHERE mission_id=? ORDER BY timestamp, sequence LIMIT ? OFFSET ?", (mission_id, limit+1, offset)).fetchall()
            more = len(rows) > limit
            return [json.loads(r[0]) for r in rows[:limit]], (str(offset+limit) if more else None)

