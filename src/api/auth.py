"""JWT Bearer authentication, Role-Based Access Control (RBAC), and multi-tenant isolation."""

from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from src.config.settings import settings
from src.observability.logger import get_logger

logger = get_logger("api.auth")

RoleType = Literal["merchant", "operator", "admin"]
ALLOWED_ROLES: tuple[RoleType, ...] = ("merchant", "operator", "admin")
AUTH_COOKIE_NAME = "getnet_access_token"

_bearer_scheme = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    """Authenticated caller identity extracted from a verified Bearer JWT."""

    user_id: str
    role: RoleType = "merchant"
    token_id: str = ""


class TokenIssueRequest(BaseModel):
    """Payload for POST /auth/token to mint a scoped Bearer JWT."""

    user_id: str = Field(..., min_length=1, max_length=128)
    role: RoleType = Field(default="merchant")
    expires_in_seconds: int | None = Field(default=None, ge=60, le=86400)


class TokenIssueResponse(BaseModel):
    """Response returned by POST /auth/token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    role: RoleType


def create_access_token(
    user_id: str,
    role: RoleType = "merchant",
    expires_in_seconds: int | None = None,
) -> str:
    """Create a signed HS256 JWT access token for the given subject and role."""
    clean_uid = (user_id or "").strip()
    if not clean_uid:
        raise ValueError("user_id cannot be empty when issuing an access token.")
    if role not in ALLOWED_ROLES:
        raise ValueError(f"Unsupported role '{role}'.")

    ttl = int(expires_in_seconds or settings.auth_token_ttl_seconds)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": clean_uid,
        "role": role,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(
        payload,
        settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
    )


def decode_access_token(token: str) -> Principal:
    """Decode and validate a signed Bearer JWT, returning a Principal or raising HTTP 401."""
    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
            options={"require": ["sub", "role", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = str(payload.get("sub") or "").strip()
    role = payload.get("role")
    if not sub or role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing valid subject or role claim.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return Principal(
        user_id=sub,
        role=role,
        token_id=str(payload.get("jti") or ""),
    )


def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> Principal:
    """FastAPI dependency requiring a valid Bearer JWT (Authorization header or HttpOnly session cookie)."""
    token = ""
    if credentials is not None and credentials.scheme.lower() == "bearer" and credentials.credentials:
        token = credentials.credentials
    else:
        token = (request.cookies.get(AUTH_COOKIE_NAME) or "").strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(token)


def require_roles(*allowed_roles: RoleType) -> Callable[[Principal], Principal]:
    """Build a FastAPI dependency enforcing that the authenticated caller holds one of allowed_roles."""

    def _dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role not in allowed_roles:
            logger.warning(
                "auth_rbac_forbidden",
                user_id=principal.user_id,
                role=principal.role,
                required_roles=list(allowed_roles),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{principal.role}' is not authorized for this resource.",
            )
        return principal

    return _dependency


def assert_user_access(principal: Principal, target_user_id: str) -> None:
    """Ensure merchants can only access their own user_id while operators/admins may inspect any."""
    clean_target = (target_user_id or "").strip()
    if principal.role in ("operator", "admin"):
        return
    if principal.user_id != clean_target:
        logger.warning(
            "auth_tenant_isolation_denied",
            actor_user_id=principal.user_id,
            target_user_id=clean_target,
            role=principal.role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: merchants may only access resources belonging to their own user_id.",
        )


def verify_bootstrap_issuance(
    requested_role: RoleType,
    bootstrap_key: str | None = Header(default=None, alias="X-Bootstrap-Key"),
) -> None:
    """Validate whether token issuance is permitted for the requested role."""
    if not settings.auth_allow_dev_token_endpoint:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token issuance endpoint is disabled.",
        )

    requires_bootstrap = settings.app_env == "production" or requested_role in ("operator", "admin")
    if requires_bootstrap:
        expected = (settings.auth_bootstrap_api_key or "").strip()
        provided = (bootstrap_key or "").strip()
        if not expected or not provided or not hmac.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Valid X-Bootstrap-Key header is required to issue elevated or production tokens.",
            )
