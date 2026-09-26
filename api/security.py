"""
CIPHER API — JWT session handling.
Tokens are short-lived and carry username + role only (no password data).
Works two ways: browser gets the token in an httpOnly cookie; API/Postman
clients can also send it as an Authorization: Bearer header.
"""

import os
from datetime import datetime, timedelta, timezone

from fastapi import Request, HTTPException, status, Depends
from jose import jwt, JWTError

from core.auth import get_user_by_username

SECRET_KEY = os.getenv("CIPHER_SECRET_KEY", "dev-only-change-me-before-demo")
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 8  # 8-hour session, fine for a demo/workday
COOKIE_NAME = "cipher_session"


def create_access_token(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def _extract_token(request: Request) -> str | None:
    # Prefer Authorization header (API clients), fall back to cookie (browser)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.removeprefix("Bearer ").strip()
    return request.cookies.get(COOKIE_NAME)


def get_current_user(request: Request) -> dict:
    """FastAPI dependency — raises 401 if not authenticated, else returns the user dict."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    user = get_user_by_username(payload["sub"])
    if user is None or not user.get("is_active", 1):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer active")

    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI dependency — same as get_current_user, but also requires Admin role."""
    if user.get("role") != "Admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user