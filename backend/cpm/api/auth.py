"""JWT verification + identity. The role ALWAYS comes from public.profiles, never from token claims."""

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from cpm.core.config import get_settings
from cpm.core.db import one, user_tx
from cpm.core.errors import ApiError

bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    id: str
    email: str
    full_name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@lru_cache
def _jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True)


def decode_token(token: str) -> dict:
    s = get_settings()
    try:
        if s.supabase_jwt_secret:
            return jwt.decode(
                token, s.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated"
            )
        key = _jwks(
            f"{s.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        ).get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=["ES256", "RS256"], audience="authenticated")
    except jwt.PyJWTError:
        raise ApiError(401, "unauthorized", "Invalid or expired session") from None


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if creds is None:
        raise ApiError(401, "unauthorized", "Authentication required")
    sub = decode_token(creds.credentials).get("sub")
    if not sub:
        raise ApiError(401, "unauthorized", "Invalid session")
    with user_tx(sub) as c:
        row = one(c, "select id, email, full_name, role from public.profiles where id = %s", (sub,))
    if not row:
        raise ApiError(401, "unauthorized", "Unknown user")
    return Principal(
        id=str(row["id"]), email=row["email"], full_name=row["full_name"], role=row["role"]
    )


def require_admin(user: Annotated[Principal, Depends(current_user)]) -> Principal:
    if not user.is_admin:
        raise ApiError(403, "forbidden", "Administrator access required")
    return user


User = Annotated[Principal, Depends(current_user)]
Admin = Annotated[Principal, Depends(require_admin)]
