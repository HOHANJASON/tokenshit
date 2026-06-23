import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet
from fastapi import HTTPException


APP_SECRET = os.getenv("APP_SECRET", "change-this-secret-before-production")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt_text, digest_text = encoded.split("$", 3)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_text), int(rounds))
        return hmac.compare_digest(base64.b64encode(digest).decode(), digest_text)
    except (ValueError, TypeError):
        return False


def create_token(subject: str, role: str, hours: int = 12) -> str:
    payload = {
        "sub": subject,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, APP_SECRET, algorithm="HS256")


def decode_token(token: str, role: str):
    try:
        payload = jwt.decode(token, APP_SECRET, algorithms=["HS256"])
        if payload.get("role") != role:
            raise HTTPException(status_code=403, detail="Permission denied")
        return payload
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


def api_key_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_customer_key() -> str:
    return "nxt_live_" + secrets.token_urlsafe(26)


def _fernet() -> Fernet:
    raw = hashlib.sha256(APP_SECRET.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
