import json
import logging
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.core import ratelimit
from app.core.config import Settings, get_settings
from app.core.errors import RateLimitedError
from app.core.logging import JsonFormatter, request_id_var
from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    verify_password,
)

STRONG = "s" * 40


def test_production_rejects_insecure_defaults() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(environment="production")
    with pytest.raises(ValidationError, match="ENCRYPTION_KEY"):
        Settings(environment="production", jwt_secret=STRONG)
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings(
            environment="production",
            jwt_secret=STRONG,
            encryption_key="Zm9vYmFyYmF6cXV4cXV1eHF1dXhxdXV4cXV1eHF1dXg=",
        )
    ok = Settings(
        environment="production",
        jwt_secret=STRONG,
        cookie_secure=True,
        encryption_key="Zm9vYmFyYmF6cXV4cXV1eHF1dXhxdXV4cXV1eHF1dXg=",
    )
    assert ok.environment == "production"


def test_secret_encryption_roundtrip_and_tamper() -> None:
    token = encrypt_secret("sk-ant-secret")
    assert token != "sk-ant-secret" and decrypt_secret(token) == "sk-ant-secret"
    assert decrypt_secret(token[:-4] + "AAAA") is None


def test_access_token_rejects_wrong_type_and_bad_sub() -> None:
    uid = uuid4()
    assert decode_access_token(create_access_token(uid)) == uid
    s = get_settings()
    refresh_like = jwt.encode({"sub": str(uid), "exp": 9999999999, "typ": "refresh"}, s.jwt_secret)
    assert decode_access_token(refresh_like) is None
    bad_sub = jwt.encode({"sub": "nope", "exp": 9999999999, "typ": "access"}, s.jwt_secret)
    assert decode_access_token(bad_sub) is None
    forged = jwt.encode({"sub": str(uid), "exp": 9999999999, "typ": "access"}, "x" * 40)
    assert decode_access_token(forged) is None


def test_verify_password_handles_missing_and_corrupt_hash() -> None:
    assert verify_password("anything", None) is False
    assert verify_password("anything", "not-a-hash") is False


def test_json_formatter_includes_request_id_and_extras() -> None:
    token = request_id_var.set("req-123")
    try:
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("x",), None)
        record.path = "/p"
        out = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert out["msg"] == "hello x" and out["request_id"] == "req-123" and out["path"] == "/p"


async def test_memory_rate_limiter_blocks_after_limit() -> None:
    ratelimit.reset_rate_limiter()
    for _ in range(3):
        await ratelimit.enforce("k", limit=3)
    with pytest.raises(RateLimitedError):
        await ratelimit.enforce("k", limit=3)
    ratelimit.reset_rate_limiter()
