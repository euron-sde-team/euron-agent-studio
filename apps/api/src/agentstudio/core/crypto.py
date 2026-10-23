"""Encryption at rest and webhook signatures.

- Workspace secrets and webhook signing keys are encrypted with AES-256-GCM under
  `ENCRYPTION_KEY`, with a random 96-bit nonce per value. The associated data binds each
  ciphertext to the row it belongs to (`secret:<workspace id>:<name>`), so a ciphertext copied
  into another row or another workspace fails to decrypt instead of leaking.
- Webhook deliveries are signed like Stripe's: `t=<unix seconds>,v1=<hex HMAC-SHA256 of
  "<t>.<raw body>">`. The timestamp is inside the MAC, so a captured request cannot be
  replayed later with a fresh timestamp.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agentstudio.core.errors import UnauthorizedError

_FORMAT_VERSION = bytes([1])
_NONCE_BYTES = 12

SIGNATURE_HEADER = "x-agentstudio-signature"
WEBHOOK_SECRET_PREFIX = "whsec_"  # noqa: S105 (a public prefix, not a secret)


class DecryptionError(Exception):
    """The ciphertext was tampered with, moved, or encrypted under another key."""


class Cipher:
    def __init__(self, key_b64: str) -> None:
        key = base64.b64decode(key_b64, validate=True)
        if len(key) != 32:
            raise ValueError("ENCRYPTION_KEY must decode to exactly 32 bytes")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str, *, context: str) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode(), context.encode())
        return _FORMAT_VERSION + nonce + sealed

    def decrypt(self, blob: bytes, *, context: str) -> str:
        if len(blob) < 1 + _NONCE_BYTES + 16 or blob[:1] != _FORMAT_VERSION:
            raise DecryptionError("unrecognised ciphertext")
        nonce = blob[1 : 1 + _NONCE_BYTES]
        try:
            return self._aead.decrypt(nonce, blob[1 + _NONCE_BYTES :], context.encode()).decode()
        except InvalidTag as exc:
            raise DecryptionError("ciphertext does not match its key or context") from exc


def secret_context(workspace_id: object, name: str) -> str:
    return f"secret:{workspace_id}:{name}"


def webhook_context(flow_id: object) -> str:
    return f"webhook:{flow_id}"


def new_webhook_secret() -> str:
    return WEBHOOK_SECRET_PREFIX + secrets.token_urlsafe(32)


def new_hook_id() -> str:
    # 24 URL-safe characters: unguessable enough that the hook URL is not itself a secret,
    # while the signature remains the actual authentication.
    return secrets.token_urlsafe(18)


def sign_webhook(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify_webhook(
    secret: str, header: str | None, body: bytes, *, now: int, tolerance_s: int
) -> int:
    """Check a signature header; return its timestamp or raise `UnauthorizedError`."""
    if not header:
        raise UnauthorizedError("Missing webhook signature.", code="signature_missing")
    timestamp: int | None = None
    candidates: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t" and value.isdigit():
            timestamp = int(value)
        elif key == "v1" and value:
            candidates.append(value)
    if timestamp is None or not candidates:
        raise UnauthorizedError("Malformed webhook signature.", code="signature_invalid")
    if abs(now - timestamp) > tolerance_s:
        raise UnauthorizedError(
            "The webhook timestamp is outside the allowed window.", code="signature_expired"
        )
    expected = sign_webhook(secret, timestamp, body).split("v1=", 1)[1]
    if not any(hmac.compare_digest(expected, candidate) for candidate in candidates):
        raise UnauthorizedError("The webhook signature does not match.", code="signature_invalid")
    return timestamp
