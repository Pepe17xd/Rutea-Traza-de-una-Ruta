import sqlite3

from fastapi.testclient import TestClient

from app import main
from app.core.config import get_settings
from app.db.sqlite import SQLiteRepository
from app.db.auth_state import DynamoAuthState, SQLiteAuthState


def make_client(tmp_path, monkeypatch):
    db = str(tmp_path / "auth-test.db")
    monkeypatch.setattr(get_settings(), "sqlite_path", db)
    monkeypatch.setattr(main, "repo", SQLiteRepository(db))
    return TestClient(main.app), db


def test_login_cookie_session_csrf_and_logout(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    with client:
        assert client.get("/api/v1/missions").status_code == 401
        login = client.post("/api/v1/auth/login", json={"password": "rutea-test-password"})
        assert login.status_code == 200
        cookie = login.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "rutea_session=" in cookie
        assert "Max-Age=28800" in cookie
        assert "Secure" not in cookie  # local test setting; production setting is asserted separately below
        assert "rutea_session" not in login.json()["csrf_token"]
        csrf = login.json()["csrf_token"]
        assert client.get("/api/v1/auth/session").json()["authenticated"] is True
        assert client.get("/api/v1/missions").status_code == 200
        assert client.post("/api/v1/missions", json={"robot_id": "CAR_TEST", "destination": {"lat": 0, "lon": 0}}).status_code == 403
        client.headers["X-CSRF-Token"] = csrf
        rejected_origin = client.post("/api/v1/auth/logout", headers={"Origin": "https://attacker.example"})
        assert rejected_origin.status_code == 403
        logged_out = client.post("/api/v1/auth/logout")
        assert logged_out.status_code == 200 and logged_out.json() == {"authenticated": False}
        assert client.get("/api/v1/missions").status_code == 401
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False


def test_wrong_password_and_rate_limit(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    with client:
        wrong_password = "valor-de-prueba-no-valido"
        wrong = client.post("/api/v1/auth/login", json={"password": wrong_password})
        assert wrong.status_code == 401 and wrong_password not in wrong.text
        detail = wrong.json()["detail"]
        assert isinstance(detail, str) and detail
        assert client.get("/api/v1/missions").status_code == 401
        for _ in range(get_settings().auth_login_attempts - 1):
            other_password = "otro-valor-de-prueba"
            response = client.post("/api/v1/auth/login", json={"password": other_password})
            assert response.status_code == 401
            assert response.json()["detail"] == detail and other_password not in response.text
        locked = client.post("/api/v1/auth/login", json={"password": "rutea-test-password"})
        assert locked.status_code == 429


def test_expired_server_session_is_rejected(tmp_path, monkeypatch):
    client, db = make_client(tmp_path, monkeypatch)
    with client:
        login = client.post("/api/v1/auth/login", json={"password": "rutea-test-password"})
        assert login.status_code == 200
        cookie_value = client.cookies.get("rutea_session")
        import hashlib
        digest = hashlib.sha256(cookie_value.encode()).hexdigest()
        with sqlite3.connect(db) as connection:
            connection.execute("UPDATE auth_sessions SET expires_at=0 WHERE session_hash=?", (digest,))
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False
        assert client.get("/api/v1/missions").status_code == 401


def test_https_configuration_marks_session_cookie_secure(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "session_cookie_secure", True)
    client, _ = make_client(tmp_path, monkeypatch)
    with client:
        response = client.post("/api/v1/auth/login", json={"password": "rutea-test-password"})
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]


def test_device_token_authentication_remains_independent(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    with client:
        assert client.post("/api/v1/telemetry", json={"robot_id": "CAR_TEST"}).status_code == 401
        accepted = client.post("/api/v1/telemetry", json={"robot_id": "CAR_TEST"}, headers={"X-Device-Token": "device-test-token-0123456789"})
        assert accepted.status_code == 422  # device credential passed; payload validation is independent


def test_sqlite_attempt_counter_is_shared_across_store_instances(tmp_path):
    database = str(tmp_path / "shared-auth.db")
    first = SQLiteAuthState(database)
    second = SQLiteAuthState(database)
    assert first.consume_login_attempt("ip-hmac", 123, 900, 2)
    assert second.consume_login_attempt("ip-hmac", 123, 900, 2)
    assert not first.consume_login_attempt("ip-hmac", 123, 900, 2)


def test_dynamodb_throttle_uses_atomic_conditional_update():
    class Table:
        captured = None
        def update_item(self, **kwargs):
            self.captured = kwargs
    table = Table()
    store = DynamoAuthState("us-east-1", "telemetry", table)
    assert store.consume_login_attempt("ip-hmac", 8, 900, 5)
    assert table.captured["Key"] == {"mission_id": "AUTH_LOGIN#ip-hmac", "sample_key": "WINDOW#8"}
    assert "attempts < :maximum" in table.captured["ConditionExpression"]
    assert "ADD attempts :one" in table.captured["UpdateExpression"]
