import pytest
from argon2 import PasswordHasher
from app.core.config import get_settings

# Credential values exist only in the isolated test suite and are never configured by the app.
_TEST_PASSWORD = "rutea-test-password"
_TEST_HASH = PasswordHasher().hash(_TEST_PASSWORD)


@pytest.fixture(autouse=True)
def secure_test_auth(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "require_auth", True)
    monkeypatch.setattr(settings, "operator_password_hash", _TEST_HASH)
    monkeypatch.setattr(settings, "session_signing_key", "test-signing-key-0123456789-abcdefgh")
    monkeypatch.setattr(settings, "device_token", "device-test-token-0123456789")
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "storage", "sqlite")
