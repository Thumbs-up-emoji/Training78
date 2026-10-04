"""Milestone-5/6 API-key and JWT authentication dependencies.

Baseline security requirement: every route on the production API
(``app/production_api.py``) is protected by this dependency, which reads a
shared-secret key from the ``MILESTONE5_API_KEY`` environment variable and
compares it against the ``X-API-Key`` request header.

This is intentionally simple (a single static header check, not a session or
user model) because Milestone 5 is an observability/security/production
*wrapper* around the existing Milestone-3/4 engine, not new business logic.
Milestone 6 keeps the API-key gateway and adds a short-lived JWT requirement
to protected routes. ``POST /auth/token`` is still API-key protected, then
validates the configured demo credentials before issuing an HS256 token.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

API_KEY_ENV_VAR = "MILESTONE5_API_KEY"
API_KEY_HEADER_NAME = "X-API-Key"
JWT_SECRET_ENV_VAR = "MILESTONE5_JWT_SECRET"
JWT_EXPIRY_MINUTES_ENV_VAR = "MILESTONE6_JWT_EXPIRY_MINUTES"
DEMO_USERNAME_ENV_VAR = "MILESTONE6_DEMO_USERNAME"
DEMO_PASSWORD_ENV_VAR = "MILESTONE6_DEMO_PASSWORD"

bearer_scheme = HTTPBearer(auto_error=False)


def _expected_api_key() -> str | None:
    """Reads the expected API key from the environment on every call (rather
    than caching at import time) so tests can monkeypatch the environment
    variable freely without reloading this module.
    """
    return os.getenv(API_KEY_ENV_VAR)


async def verify_api_key(x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER_NAME)) -> str:
    """FastAPI dependency enforcing the ``X-API-Key`` header on every request.

    Raises ``HTTPException(401)`` when the header is missing, when no server
    key is configured (fail-closed, not fail-open), or when the key does not
    match. Returns the validated key on success so it can be used as a
    dependency return value if a route wants to log/echo it (never do this
    with the raw key in production; ``app/production_api.py`` never logs it).
    """
    expected = _expected_api_key()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server misconfiguration: {API_KEY_ENV_VAR} is not set.",
        )
    if not x_api_key or x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Provide it via the X-API-Key header.",
        )
    return x_api_key


def _jwt_secret(secret: str | None = None) -> str:
    resolved_secret = secret or os.getenv(JWT_SECRET_ENV_VAR)
    if not resolved_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server misconfiguration: {JWT_SECRET_ENV_VAR} is not set.",
        )
    return resolved_secret


def _jwt_expiry_minutes() -> int:
    raw_value = os.getenv(JWT_EXPIRY_MINUTES_ENV_VAR, "30")
    try:
        minutes = int(raw_value)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server misconfiguration: {JWT_EXPIRY_MINUTES_ENV_VAR} must be an integer.",
        ) from error
    if minutes <= 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server misconfiguration: {JWT_EXPIRY_MINUTES_ENV_VAR} must be positive.",
        )
    return minutes


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a short-lived HS256 access token for the configured demo user."""
    import jwt as pyjwt

    expires_at = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=_jwt_expiry_minutes()))
    return pyjwt.encode({"sub": subject, "exp": expires_at}, _jwt_secret(), algorithm="HS256")


def verify_jwt(token: str, secret: str | None = None, algorithms: tuple[str, ...] = ("HS256",)) -> dict[str, Any]:
    """Decode and validate a JWT, mapping invalid tokens to an HTTP 401."""
    import jwt as pyjwt

    try:
        payload = pyjwt.decode(token, _jwt_secret(secret), algorithms=list(algorithms))
    except pyjwt.InvalidTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing, invalid, or expired bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is missing its subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def verify_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency requiring an unexpired ``Authorization: Bearer`` JWT."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token. Provide Authorization: Bearer <token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_jwt(credentials.credentials)


def verify_demo_credentials(username: str, password: str) -> str:
    """Validate the M6 demo account used exclusively to mint a short-lived token."""
    expected_username = os.getenv(DEMO_USERNAME_ENV_VAR, "demo-user")
    expected_password = os.getenv(DEMO_PASSWORD_ENV_VAR)
    if not expected_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server misconfiguration: {DEMO_PASSWORD_ENV_VAR} is not set.",
        )
    if username != expected_username or password != expected_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid demo credentials.")
    return username
