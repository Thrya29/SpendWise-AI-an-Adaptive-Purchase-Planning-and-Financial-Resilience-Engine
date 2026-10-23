from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.db import utcnow

_hasher = PasswordHasher()
# Pre-computed hash used to equalise timing when the user does not exist.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: UUID) -> str:
    s = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.access_token_minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> UUID | None:
    s = get_settings()
    try:
        payload = jwt.decode(
            token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub"]}
        )
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    try:
        return UUID(str(payload["sub"]))
    except ValueError:
        return None


def new_refresh_token() -> tuple[str, str]:
    """Return (raw token for the client, sha256 digest to store)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.encode())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str | None:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
