"""Generic JWT minting for realtime-service connections.

The SDK ships the MECHANISM (kid derivation + RS256 signing), never an
identity. Each caller supplies its own `issuer` (and serves a matching JWKS
the server validates against). kid = first 16 chars of URL-safe base64
SHA-256 of the SubjectPublicKeyInfo DER — matching the server's JWKS."""
from __future__ import annotations

import base64
import hashlib
import time
from typing import Any

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization

AUTH_CLAIM_KEYS = frozenset({"iss", "sub", "tenant_id", "iat", "exp"})


def _public_der_from_pem(pem: str) -> bytes:
    data = pem.encode()
    try:
        priv = serialization.load_pem_private_key(data, password=None)
        pub = priv.public_key()
    except ValueError:
        pub = serialization.load_pem_public_key(data)
    return pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def compute_kid(pem: str) -> str:
    """Derive the JWKS key id from a public or private PEM."""
    digest = hashlib.sha256(_public_der_from_pem(pem)).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:16]


def bearer_subprotocol(token: str) -> str:
    """The WS subprotocol the server reads the JWT from: `Bearer.<jwt>`."""
    return f"Bearer.{token}"


class TokenMinter:
    """Zero-arg callable returning a fresh signed JWT each call."""

    def __init__(
        self, *, private_key: str, issuer: str, subject: str,
        tenant_id: str, ttl_seconds: int = 300,
    ) -> None:
        self._private_key = private_key
        self._issuer = issuer
        self._subject = subject
        self._tenant_id = tenant_id
        self._ttl_seconds = ttl_seconds
        self._kid = compute_kid(private_key)

    def __call__(self) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self._issuer,
            "sub": self._subject,
            "tenant_id": self._tenant_id,
            "iat": now,
            "exp": now + self._ttl_seconds,
        }
        return pyjwt.encode(claims, self._private_key, algorithm="RS256", headers={"kid": self._kid})
