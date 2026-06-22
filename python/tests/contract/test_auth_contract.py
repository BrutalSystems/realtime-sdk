from __future__ import annotations

import jwt as pyjwt

from realtime_core import AUTH_CLAIM_KEYS, TokenMinter, bearer_subprotocol, compute_kid


def test_claim_keys_are_frozen():
    assert AUTH_CLAIM_KEYS == frozenset({"iss", "sub", "tenant_id", "iat", "exp"})


def test_minter_emits_expected_header_and_claims(rsa_keypair):
    private_pem, public_pem = rsa_keypair
    minter = TokenMinter(
        private_key=private_pem, issuer="example-api",
        subject="example-service", tenant_id="_org", ttl_seconds=300,
    )
    token = minter()

    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "RS256"
    assert header["kid"] == compute_kid(public_pem)

    # Verifies against the PUBLIC key (proves RS256 signing is correct).
    claims = pyjwt.decode(token, public_pem, algorithms=["RS256"])
    assert set(claims) == AUTH_CLAIM_KEYS
    assert claims["iss"] == "example-api"   # caller-supplied, NOT hardcoded
    assert claims["sub"] == "example-service"
    assert claims["tenant_id"] == "_org"
    assert claims["exp"] - claims["iat"] == 300


def test_kid_is_stable_for_a_key(rsa_keypair):
    private_pem, public_pem = rsa_keypair
    assert compute_kid(private_pem) == compute_kid(public_pem)
    assert len(compute_kid(public_pem)) == 16


def test_bearer_subprotocol_format():
    assert bearer_subprotocol("abc.def") == "Bearer.abc.def"
