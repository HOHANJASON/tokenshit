"""API identity. Mirrors NexToken's HS256 JWT (role + subject) and adds a
``cid`` (customer_id) claim, so a token issued by the NexToken backend validates
here unchanged. A dev-header fallback (X-Role / X-Customer-Id) is available when
``COPILOT_DEV_AUTH=1`` for local use without minting tokens.

This is the seam the backend developer owns: swap ``decode`` for the platform's
own validator and nothing else changes.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Header, HTTPException

from .principal import Principal, Role

APP_SECRET = os.getenv("COPILOT_APP_SECRET", "dev-secret-change-me-in-production-0123456789abcdef")
DEV_AUTH = os.getenv("COPILOT_DEV_AUTH", "1") == "1"


def create_token(role: Role, customer_id: int | None = None, email: str = "", hours: int = 12) -> str:
    payload = {
        "sub": str(customer_id) if customer_id is not None else role.value,
        "role": role.value,
        "cid": customer_id,
        "email": email,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
    }
    return jwt.encode(payload, APP_SECRET, algorithm="HS256")


# The seam: NexToken's backend issues role="customer"/"staff"/"admin" with the
# customer id in `sub`; the copilot's roles are client/support/admin with the id
# in `cid`. Map them so a real NexToken session JWT validates here unchanged
# (Option A in integration/INTEGRATION.md — copilot shares the backend APP_SECRET).
_ROLE_MAP = {"customer": "client", "staff": "support", "support": "support",
             "admin": "admin", "client": "client"}


def _principal_from_payload(payload: dict) -> Principal:
    raw_role = str(payload.get("role", "")).lower()
    role = _ROLE_MAP.get(raw_role, raw_role)
    # customer id: prefer `cid`; fall back to `sub` when it's the numeric customer id.
    cid = payload.get("cid")
    if cid is None and role == "client":
        sub = payload.get("sub")
        cid = sub if (isinstance(sub, int) or str(sub).isdigit()) else None
    try:
        return Principal(
            role=Role(role),
            customer_id=int(cid) if cid is not None else None,
            email=payload.get("email", ""),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Bad identity: {exc}") from exc


def principal_from_request(
    authorization: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_customer_id: str | None = Header(default=None),
) -> Principal:
    if authorization and authorization.startswith("Bearer "):
        try:
            payload = jwt.decode(authorization[7:].strip(), APP_SECRET, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
        return _principal_from_payload(payload)

    if DEV_AUTH and x_role:
        cid = int(x_customer_id) if (x_customer_id or "").isdigit() else None
        return _principal_from_payload({"role": x_role, "cid": cid, "email": "dev@local"})

    raise HTTPException(status_code=401, detail="Authentication required")
