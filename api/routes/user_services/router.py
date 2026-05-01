import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.database import get_session
from db.entities import User

from .schemas import LoginRequest, LoginResponse, RegisterRequest, RegisterResponse

router = APIRouter(prefix="/auth", tags=["auth"])

_SYSTEM_USER_ID = "system"
_JWT_SECRET = os.environ.get("JWT_SECRET", "meridian-dev-secret-change-in-prod")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_HOURS = 24


def _make_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=_JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(body: RegisterRequest) -> RegisterResponse:
    """Create a new user. Passwords are stored as bcrypt hashes.

    Returns 409 if the email is already registered.
    """
    hashed = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()

    user = User(
        user_id=str(uuid.uuid4()),
        email=body.email,
        display_name=body.display_name,
        github_username=body.github_username,
        password=hashed,
        role="member",
    )

    try:
        with get_session() as session:
            existing = session.execute(
                select(User).where(User.user_id == _SYSTEM_USER_ID)
            ).scalar_one_or_none()
            if existing and existing.email == body.email:
                raise HTTPException(status.HTTP_409_CONFLICT, detail="email already registered")

            session.add(user)
            session.commit()
            session.refresh(user)
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="email already registered")

    return RegisterResponse(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        github_username=user.github_username,
        role=user.role,
        created_at=user.created_at,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and receive a JWT token",
)
async def login(body: LoginRequest) -> LoginResponse:
    """Verify credentials and return a 24-hour JWT.

    Returns 401 for any credential mismatch — intentionally no distinction
    between unknown email and wrong password.
    """
    with get_session() as session:
        user = session.execute(
            select(User).where(User.email == body.email)
        ).scalar_one_or_none()

    _invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")

    if user is None:
        raise _invalid

    # Reject the system placeholder — it has no valid password hash
    if user.user_id == _SYSTEM_USER_ID:
        raise _invalid

    if not bcrypt.checkpw(body.password.encode(), user.password.encode()):
        raise _invalid

    return LoginResponse(
        access_token=_make_token(user.user_id),
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
    )
