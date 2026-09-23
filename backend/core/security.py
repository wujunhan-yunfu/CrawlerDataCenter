"""安全原语: bcrypt 密码哈希 + JWT 签发/校验 + 敏感字段加密。"""

from __future__ import annotations

import base64
import time
import uuid

import bcrypt
import jwt
from cryptography.fernet import Fernet

from ..config import settings


# ---- 密码哈希 ----

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---- JWT ----

def _now() -> int:
    return int(time.time())


def create_access_token(subject: str, extra: dict | None = None) -> str:
    now = _now()
    payload = {
        "sub": subject,
        "iss": settings.token_issuer,
        "iat": now,
        "exp": now + settings.access_token_ttl,
        "type": "access",
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str) -> tuple[str, str, int]:
    """返回 (token, jti, expires_at)。jti 存 Redis 白名单, 支持撤销。"""
    now = _now()
    jti = uuid.uuid4().hex
    expires_at = now + settings.refresh_token_ttl
    payload = {
        "sub": subject,
        "iss": settings.token_issuer,
        "iat": now,
        "exp": expires_at,
        "type": "refresh",
        "jti": jti,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), jti, expires_at


def decode_token(token: str, expected_type: str | None = None) -> dict:
    """校验并解码 JWT; 非法/过期/类型不符抛 jwt.PyJWTError。"""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected token type={expected_type}")
    return payload


# ---- 敏感字段加密（Fernet, 便于旋转）----

def _fernet() -> Fernet | None:
    key = settings.field_encryption_key
    if not key:
        return None
    try:
        if key.startswith("base64:"):
            return Fernet(key[len("base64:"):].strip())
        return Fernet(base64.urlsafe_b64encode(key.encode("utf-8")[:32]).rstrip(b"="))
    except Exception:  # noqa: BLE001
        return None


def encrypt_field(plain: str) -> str | None:
    f = _fernet()
    if f is None or not plain:
        return plain
    return f.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_field(token: str) -> str | None:
    f = _fernet()
    if f is None or not token:
        return token
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception:  # noqa: BLE001
        return token