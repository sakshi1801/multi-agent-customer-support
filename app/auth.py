"""Authentication helpers (standard library only).

Customers log in with email + password and get a signed, expiring token. The token is the ONLY
source of the customer's identity for /chat: the identity never comes from the message text or
from anything the LLM produces.

Human support agents use a shared API key (header X-API-Key). A real deployment would use SSO.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

PBKDF2_ITERATIONS = 120_000
TOKEN_TTL_SECONDS = 8 * 3600

# Used when TOKEN_SECRET is not configured: tokens then stop working when the process restarts.
_PROCESS_SECRET = secrets.token_bytes(32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. An unknown user (stored=None) still costs one hash, so response
    time does not reveal whether an email is registered."""
    salt_hex, _, digest_hex = (stored or f"{'00' * 16}${'00' * 32}").partition("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS)
    return stored is not None and hmac.compare_digest(digest.hex(), digest_hex)


def _secret() -> bytes:
    configured = os.getenv("TOKEN_SECRET")
    return configured.encode() if configured else _PROCESS_SECRET


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token(email: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    payload = _b64(json.dumps({"sub": email, "exp": int(time.time()) + ttl}).encode())
    signature = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_token(token: str) -> str | None:
    """Return the customer email if the token is genuine and unexpired, else None."""
    try:
        payload, signature = token.split(".")
        expected = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        claims = json.loads(_unb64(payload))
        if claims["exp"] < time.time():
            return None
        return str(claims["sub"])
    except (ValueError, KeyError, TypeError):
        return None


def agent_key_matches(provided: str | None) -> bool:
    configured = os.getenv("AGENT_API_KEY")
    return bool(configured and provided) and hmac.compare_digest(provided.encode(), configured.encode())
