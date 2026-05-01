"""Shared FastAPI dependencies — JWT auth."""

from __future__ import annotations

import os

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_JWT_SECRET = os.environ.get("JWT_SECRET", "meridian-dev-secret-change-in-prod")
_JWT_ALGORITHM = "HS256"

_bearer = HTTPBearer()


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Validate the Bearer JWT and return the authenticated user_id.

    Raises 401 on any token problem (missing, expired, malformed).
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid token")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid token")
