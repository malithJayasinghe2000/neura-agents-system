"""Envelope encryption for tenant store credentials.

A merchant's store API credentials are the highest-value asset we hold — keys to
someone else's business. They are never a plaintext column.

    KEK (env or KMS, never in the database)
     └─ decrypts DEK (per tenant, stored wrapped)
         └─ encrypts the credentials (AES-256-GCM ciphertext in Postgres)

The point of the indirection: rotating the KEK rewraps a handful of DEKs rather
than re-encrypting every credential row, and a stolen database dump is useless
without the KEK. See docs/architecture/security-model.md §5.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from neura_core.errors import ConfigurationError

_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # GCM standard


def generate_key() -> str:
    """A fresh base64-encoded 256-bit key, for a KEK or a DEK."""
    return base64.b64encode(os.urandom(_KEY_BYTES)).decode()


def _decode_key(key: str, *, label: str) -> bytes:
    try:
        raw = base64.b64decode(key, validate=True)
    except Exception as exc:
        raise ConfigurationError(f"{label} is not valid base64") from exc
    if len(raw) != _KEY_BYTES:
        raise ConfigurationError(f"{label} must decode to {_KEY_BYTES} bytes, got {len(raw)}")
    return raw


def encrypt(plaintext: str, key: str, *, aad: bytes | None = None) -> str:
    """Encrypt with AES-256-GCM. Returns base64 of ``nonce || ciphertext || tag``.

    ``aad`` binds the ciphertext to a context (typically the tenant ID), so a
    blob moved between tenant rows fails to decrypt rather than silently working.
    """
    aesgcm = AESGCM(_decode_key(key, label="key"))
    nonce = os.urandom(_NONCE_BYTES)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), aad)
    return base64.b64encode(nonce + ct).decode()


def decrypt(token: str, key: str, *, aad: bytes | None = None) -> str:
    aesgcm = AESGCM(_decode_key(key, label="key"))
    raw = base64.b64decode(token, validate=True)
    nonce, ct = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    return aesgcm.decrypt(nonce, ct, aad).decode()


def wrap_dek(dek: str, kek: str, *, tenant_id: str) -> str:
    """Encrypt a tenant's data key with the master key, bound to that tenant."""
    return encrypt(dek, kek, aad=tenant_id.encode())


def unwrap_dek(wrapped: str, kek: str, *, tenant_id: str) -> str:
    return decrypt(wrapped, kek, aad=tenant_id.encode())
