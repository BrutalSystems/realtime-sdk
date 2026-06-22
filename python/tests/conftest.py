from __future__ import annotations

import json
from pathlib import Path

import pytest

_CONTRACT = Path(__file__).resolve().parents[2] / "contract"


@pytest.fixture(scope="session")
def frames_fixture() -> dict:
    return json.loads((_CONTRACT / "frames.json").read_text())


@pytest.fixture(scope="session")
def channels_fixture() -> dict:
    return json.loads((_CONTRACT / "channels.json").read_text())


@pytest.fixture(scope="session")
def rsa_keypair() -> tuple[str, str]:
    """(private_pem, public_pem) for a throwaway RSA key used in auth tests."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem
