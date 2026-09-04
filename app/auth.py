import logging
import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

logger = logging.getLogger("ledger.auth")

_LOCAL_DEV_SECRET = "local-dev-only-not-for-deployment"


def _resolve_secret() -> str:
    configured = os.getenv("JWT_SECRET_KEY")
    if configured:
        return configured
    # Fail closed in the deployed environment rather than fall back to a value
    # that is visible in source control. Local runs and tests use a throwaway.
    if os.getenv("ENVIRONMENT") == "production":
        raise RuntimeError(
            "JWT_SECRET_KEY must be set when ENVIRONMENT=production"
        )
    logger.warning("JWT_SECRET_KEY not set, using local development secret")
    return _LOCAL_DEV_SECRET


SECRET_KEY = _resolve_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def _hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_pw(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


class Role(str, Enum):
    customer = "customer"
    auditor = "auditor"
    admin = "admin"


class TokenData(BaseModel):
    username: str
    role: Role


USERS_DB: dict[str, dict] = {
    "admin": {
        "password_hash": _hash_pw("admin123"),
        "role": Role.admin,
    },
    "auditor": {
        "password_hash": _hash_pw("auditor123"),
        "role": Role.auditor,
    },
    "customer": {
        "password_hash": _hash_pw("customer123"),
        "role": Role.customer,
    },
}


def authenticate_user(username: str, password: str) -> TokenData | None:
    user = USERS_DB.get(username)
    if user is None:
        return None
    if not _verify_pw(password, user["password_hash"]):
        return None
    return TokenData(username=username, role=user["role"])


def create_access_token(data: TokenData) -> str:
    expire = datetime.now(tz=timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": data.username,
        "role": data.role.value,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None or role is None:
            raise credentials_exception
        return TokenData(username=username, role=Role(role))
    except JWTError:
        raise credentials_exception


def require_role(*allowed: Role):
    def checker(
        user: Annotated[TokenData, Depends(get_current_user)],
    ) -> TokenData:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' cannot access this resource",
            )
        return user
    return checker
