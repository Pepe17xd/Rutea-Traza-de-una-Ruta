import secrets
from fastapi import Header, HTTPException
from app.core.config import get_settings


def require_device(x_device_token: str | None = Header(default=None)):
    expected = get_settings().device_token
    if expected and not secrets.compare_digest(x_device_token or "", expected):
        raise HTTPException(401, "Credencial de dispositivo inválida")


def require_operator(authorization: str | None = Header(default=None)):
    expected = get_settings().operator_token
    if expected:
        supplied = (authorization or "").removeprefix("Bearer ")
        if not secrets.compare_digest(supplied, expected): raise HTTPException(401, "Credencial de operador inválida")

