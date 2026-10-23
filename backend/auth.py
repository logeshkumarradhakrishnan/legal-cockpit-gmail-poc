"""
Sign-in and roles for the Legal Cockpit.

Roles (from the workshop):
  super_admin  assigns tasks and deadlines to Admins; full visibility
  admin        assigns tasks and deadlines to their direct reports; sees own and reports' tasks
  user         works the tasks assigned to them

In production (AUTH_MODE=entra) the frontend signs in with Entra ID and sends an
access token. The role comes from the token's app roles (Legal.SuperAdmin,
Legal.Admin, Legal.User). Reporting lines come from the directory file; in a
later phase they can be read from Entra (Graph /users/{id}/manager).

In dev mode the frontend sends X-Dev-User with an address from the sample
directory, so a demo can switch between roles. Never deploy with AUTH_MODE=dev.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from config import get_settings

log = logging.getLogger("legal-cockpit.auth")

Role = Literal["super_admin", "admin", "user"]
ROLE_RANK = {"user": 1, "admin": 2, "super_admin": 3}
APP_ROLES = {"Legal.SuperAdmin": "super_admin", "Legal.Admin": "admin", "Legal.User": "user"}


class User(BaseModel):
    email: str
    name: str
    role: Role
    manager: Optional[str] = None


# Sample Legal team for dev mode and demos. Fictitious people.
DEV_DIRECTORY = [
    User(email="gc@example.com", name="Meera Nair", role="super_admin"),
    User(email="arjun.rao@example.com", name="Arjun Rao", role="admin", manager="gc@example.com"),
    User(email="sana.khan@example.com", name="Sana Khan", role="admin", manager="gc@example.com"),
    User(email="kavya.iyer@example.com", name="Kavya Iyer", role="user", manager="arjun.rao@example.com"),
    User(email="rohan.das@example.com", name="Rohan Das", role="user", manager="arjun.rao@example.com"),
    User(email="neha.pillai@example.com", name="Neha Pillai", role="user", manager="sana.khan@example.com"),
]

DIRECTORY: dict[str, User] = {}


def load_directory() -> None:
    s = get_settings()
    DIRECTORY.clear()
    path = Path(s.directory_path)
    if path.exists():
        for row in json.loads(path.read_text(encoding="utf-8")):
            u = User(**row)
            DIRECTORY[u.email.lower()] = u
    elif s.auth_mode == "dev":
        for u in DEV_DIRECTORY:
            DIRECTORY[u.email.lower()] = u
    log.info("directory loaded: %d people", len(DIRECTORY))


def direct_reports(email: str) -> list[User]:
    return [u for u in DIRECTORY.values() if (u.manager or "").lower() == email.lower()]


# ---------------------------------------------------------------------------
# Token validation (Entra ID)
# ---------------------------------------------------------------------------

_jwks_client = None


def _validate_entra(token: str) -> dict:
    import jwt  # PyJWT

    global _jwks_client
    s = get_settings()
    if not (s.entra_tenant_id and s.entra_api_audience):
        raise HTTPException(503, "Entra sign-in is not configured on the server")
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{s.entra_tenant_id}/discovery/v2.0/keys")
    try:
        key = _jwks_client.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token, key, algorithms=["RS256"],
            audience=s.entra_api_audience,
            issuer=f"https://login.microsoftonline.com/{s.entra_tenant_id}/v2.0",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid token: {exc}")


def current_user(request: Request) -> User:
    s = get_settings()
    if s.auth_mode == "dev":
        email = (request.headers.get("X-Dev-User") or "gc@example.com").lower()
        u = DIRECTORY.get(email)
        if not u:
            raise HTTPException(401, f"unknown dev user {email}")
        return u

    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "sign-in required")
    claims = _validate_entra(auth.split(" ", 1)[1])

    roles = [APP_ROLES[r] for r in claims.get("roles", []) if r in APP_ROLES]
    if not roles:
        raise HTTPException(403, "you are not assigned a Legal Cockpit role")
    role = max(roles, key=lambda r: ROLE_RANK[r])
    email = (claims.get("preferred_username") or claims.get("upn") or claims.get("email") or "").lower()
    known = DIRECTORY.get(email)
    return User(email=email, name=claims.get("name") or (known.name if known else email),
                role=role, manager=known.manager if known else None)


def require(*roles: Role):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "your role cannot do this")
        return user
    return dep
