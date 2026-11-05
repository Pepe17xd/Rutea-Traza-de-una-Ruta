"""Persistent session and login-throttle storage shared across API instances."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class SQLiteAuthState:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS auth_sessions (session_hash TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS auth_attempts (ip_hash TEXT NOT NULL, window INTEGER NOT NULL, attempts INTEGER NOT NULL, expires_at INTEGER NOT NULL, PRIMARY KEY(ip_hash, window))")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_session(self, session_hash: str, expires_at: int) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO auth_sessions VALUES (?,?)", (session_hash, expires_at))

    def get_session(self, session_hash: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT expires_at FROM auth_sessions WHERE session_hash=?", (session_hash,)).fetchone()
            return dict(row) if row else None

    def delete_session(self, session_hash: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE session_hash=?", (session_hash,))

    def consume_login_attempt(self, ip_hash: str, window: int, window_s: int, maximum: int) -> bool:
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO auth_attempts VALUES (?,?,0,?)", (ip_hash, window, (window + 1) * window_s))
            changed = conn.execute("UPDATE auth_attempts SET attempts=attempts+1 WHERE ip_hash=? AND window=? AND attempts < ?", (ip_hash, window, maximum)).rowcount
            return changed == 1


class DynamoAuthState:
    """Stores auth rows in the existing telemetry table; no extra table/role needed."""
    def __init__(self, region: str, table_name: str, table: Any | None = None):
        if table is None:
            import boto3
            table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self.table = table

    def create_session(self, session_hash: str, expires_at: int) -> None:
        self.table.put_item(Item={"mission_id": f"AUTH_SESSION#{session_hash}", "sample_key": "SESSION", "expires_at": expires_at})

    def get_session(self, session_hash: str) -> dict[str, Any] | None:
        return self.table.get_item(Key={"mission_id": f"AUTH_SESSION#{session_hash}", "sample_key": "SESSION"}, ConsistentRead=True).get("Item")

    def delete_session(self, session_hash: str) -> None:
        self.table.delete_item(Key={"mission_id": f"AUTH_SESSION#{session_hash}", "sample_key": "SESSION"})

    def consume_login_attempt(self, ip_hash: str, window: int, window_s: int, maximum: int) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.table.update_item(
                Key={"mission_id": f"AUTH_LOGIN#{ip_hash}", "sample_key": f"WINDOW#{window}"},
                UpdateExpression="SET expires_at = :expiry ADD attempts :one",
                ConditionExpression="attribute_not_exists(attempts) OR attempts < :maximum",
                ExpressionAttributeValues={":one": 1, ":maximum": maximum, ":expiry": (window + 1) * window_s},
            )
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise


@lru_cache(maxsize=8)
def _sqlite_state(path: str):
    return SQLiteAuthState(path)


@lru_cache(maxsize=8)
def _dynamo_state(region: str, table_name: str):
    return DynamoAuthState(region, table_name)


def get_auth_state():
    settings = get_settings()
    if settings.storage.lower() == "dynamodb":
        return _dynamo_state(settings.aws_region, settings.telemetry_table)
    return _sqlite_state(settings.sqlite_path)
