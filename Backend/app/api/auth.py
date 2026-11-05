from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Header, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings
from app.db.auth_state import get_auth_state

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
COOKIE_NAME = "rutea_session"
_hasher = PasswordHasher()


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1024)


def csrf_for(session_id: str, signing_key: str) -> str:
    return hmac.new(signing_key.encode(), f"csrf:{session_id}".encode(), hashlib.sha256).hexdigest()


def _auth_configured() -> bool:
    settings = get_settings()
    return settings.require_auth and settings.operator_password_hash.startswith("$argon2id$") and len(settings.session_signing_key) >= 32


def _source_ip(request: Request) -> str:
    # X-Forwarded-For is caller-controlled and is deliberately not trusted here.
    return request.client.host if request.client else "unknown"


def _session_record(session_id: str):
    key = hashlib.sha256(session_id.encode()).hexdigest()
    return get_auth_state().get_session(key)


def valid_session(session_id: str | None) -> bool:
    if not session_id or not _auth_configured():
        return False
    record = _session_record(session_id)
    return bool(record and int(record.get("expires_at", 0)) > int(time.time()))


def _csrf_valid(request: Request, supplied: str | None, session_id: str) -> bool:
    settings = get_settings()
    expected = csrf_for(session_id, settings.session_signing_key)
    origin = request.headers.get("origin")
    origin_ok = origin_allowed(request, origin)
    return origin_ok and bool(supplied) and secrets.compare_digest(supplied, expected)


def origin_allowed(request: Request | WebSocket, origin: str | None) -> bool:
    if not origin:
        return True
    settings = get_settings()
    allowed_origins = {item.rstrip("/") for item in settings.cors_origins}
    same_origin = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
    return origin.rstrip("/") == same_origin or origin.rstrip("/") in allowed_origins


@router.post("/login", openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": {
    "type": "object", "required": ["password"], "properties": {"password": {"type": "string", "format": "password", "minLength": 1, "maxLength": 1024}}
}}}}})
async def login(request: Request, response: Response):
    settings = get_settings()
    try:
        body = LoginRequest.model_validate(await request.json())
    except (ValidationError, ValueError):
        # Avoid echoing the submitted password in validation responses.
        raise HTTPException(422, "Solicitud de acceso inválida") from None
    if not origin_allowed(request, request.headers.get("origin")):
        raise HTTPException(403, "Origen no permitido")
    if not _auth_configured():
        raise HTTPException(503, "Acceso no configurado en el servidor")
    now = int(time.time())
    window = now // settings.auth_login_window_s
    ip_digest = hmac.new(settings.session_signing_key.encode(), _source_ip(request).encode(), hashlib.sha256).hexdigest()
    try:
        allowed = get_auth_state().consume_login_attempt(ip_digest, window, settings.auth_login_window_s, settings.auth_login_attempts)
    except Exception as exc:
        raise HTTPException(503, "El servicio de acceso no está disponible") from exc
    if not allowed:
        retry = settings.auth_login_window_s - now % settings.auth_login_window_s
        raise HTTPException(429, "Demasiados intentos. Inténtalo más tarde.", headers={"Retry-After": str(retry)})
    encoded = settings.operator_password_hash
    try:
        password_ok = encoded.startswith("$argon2id$") and _hasher.verify(encoded, body.password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        password_ok = False
    if not password_ok:
        raise HTTPException(401, "Credenciales inválidas")
    session_id = secrets.token_urlsafe(32)
    expires_at = now + settings.session_ttl_s
    try:
        get_auth_state().create_session(hashlib.sha256(session_id.encode()).hexdigest(), expires_at)
    except Exception as exc:
        raise HTTPException(503, "No se pudo crear la sesión") from exc
    response.set_cookie(COOKIE_NAME, session_id, max_age=settings.session_ttl_s,
                        httponly=True, secure=settings.session_cookie_secure, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True, "csrf_token": csrf_for(session_id, settings.session_signing_key),
            "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat()}


@router.get("/session")
def session(request: Request, response: Response):
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    session_id = request.cookies.get(COOKIE_NAME)
    if not valid_session(session_id):
        return Response(content='{"authenticated":false}', media_type="application/json", headers={"Cache-Control": "no-store"})
    return {"authenticated": True, "csrf_token": csrf_for(session_id, settings.session_signing_key)}


@router.post("/logout")
def logout(request: Request, response: Response, x_csrf_token: str | None = Header(default=None)):
    settings = get_settings()
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id and not _csrf_valid(request, x_csrf_token, session_id):
        raise HTTPException(403, "Token CSRF inválido")
    if session_id:
        try:
            get_auth_state().delete_session(hashlib.sha256(session_id.encode()).hexdigest())
        except Exception as exc:
            raise HTTPException(503, "No se pudo cerrar la sesión") from exc
    response.delete_cookie(COOKIE_NAME, path="/", secure=settings.session_cookie_secure, httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}


async def require_operator(request: Request, x_csrf_token: str | None = Header(default=None)):
    settings = get_settings()
    if not settings.require_auth:
        raise HTTPException(503, "La autenticación de operador es obligatoria")
    session_id = request.cookies.get(COOKIE_NAME)
    if not valid_session(session_id):
        raise HTTPException(401, "Sesión requerida")
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"} and not _csrf_valid(request, x_csrf_token, session_id):
        raise HTTPException(403, "Token CSRF inválido")


def require_device(x_device_token: str | None = Header(default=None)):
    settings = get_settings()
    expected = settings.device_token
    if not settings.require_auth:
        raise HTTPException(503, "La autenticación de dispositivo es obligatoria")
    if not expected:
        raise HTTPException(503, "Autenticación de dispositivo no configurada")
    if not secrets.compare_digest(x_device_token or "", expected):
        raise HTTPException(401, "Credencial de dispositivo inválida")
