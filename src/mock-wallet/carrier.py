"""Carrier credential issuance — loads carrier keys and mints SD-JWT-VC phone number credentials."""

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

import jwt  # PyJWT
from jwcrypto import jwk


# --- base64url helpers (no padding) ---

def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


# --- Key loading ---

def _default_keys_dir() -> Path:
    """Default: relative path from mock-wallet to docker-volumes."""
    return Path(__file__).parent / ".." / ".." / "services" / "poc" / "docker-volumes" / "wallet" / "keys"


def load_keys_dir() -> Path:
    env = os.environ.get("WALLET_KEYS_DIR")
    if env:
        return Path(env)
    return _default_keys_dir()


def load_jwk(path: Path) -> jwk.JWK:
    """Load a JWK from a JSON file."""
    return jwk.JWK.from_json(path.read_text())


def load_carrier_key(keys_dir: Path) -> jwk.JWK:
    return load_jwk(keys_dir / "carrier-key.jwk.json")


def load_holder_key(keys_dir: Path, holder: str) -> jwk.JWK:
    return load_jwk(keys_dir / f"holder-{holder}-key.jwk.json")


# --- SD-JWT-VC issuance ---

def _make_disclosure(salt: str, claim_name: str, claim_value: str) -> str:
    """Create a disclosure string (base64url-encoded JSON array)."""
    arr = json.dumps([salt, claim_name, claim_value], separators=(",", ":"))
    return b64url_encode(arr.encode("utf-8"))


def _hash_disclosure(disclosure: str) -> str:
    """SHA-256 hash of the disclosure string, base64url-encoded."""
    digest = hashlib.sha256(disclosure.encode("ascii")).digest()
    return b64url_encode(digest)


def issue_credential(carrier_key: jwk.JWK, holder_key: jwk.JWK, phone_number: str, pseudonym: str) -> str:
    """Issue an SD-JWT-VC with selectively-disclosable msisdn and pseudonym claims.

    Returns the SD-JWT-VC string: issuer_jwt~disc_msisdn~disc_pseudonym~ (trailing ~, no KB-JWT).
    """
    # Build disclosures
    salt1 = b64url_encode(secrets.token_bytes(16))
    disc_msisdn = _make_disclosure(salt1, "msisdn", phone_number)

    # Pseudonym as a selectively-disclosable claim, following the approach argued by
    # AltmannPeter in ARF Discussion #375 (https://github.com/eu-digital-identity-wallet/
    # eudi-doc-architecture-and-reference-framework/discussions/375): treating the
    # pseudonym as an attribute transmitted during presentation rather than a separate
    # authentication mechanism. In production, cryptographic binding (SGVP/BBS) would
    # replace the wallet's self-assertion.
    salt2 = b64url_encode(secrets.token_bytes(16))
    disc_pseudonym = _make_disclosure(salt2, "pseudonym", pseudonym)

    # Holder public key for cnf claim
    holder_pub = json.loads(holder_key.export_public())

    now = int(time.time())

    # Issuer JWT payload
    payload = {
        "iss": "https://mock-carrier.example.com",
        "iat": now,
        "exp": now + 365 * 24 * 3600,  # 1 year
        "vct": "urn:eu.europa.ec.eudi:msisdn:1",
        "cnf": {"jwk": holder_pub},
        "_sd": [_hash_disclosure(disc_msisdn), _hash_disclosure(disc_pseudonym)],
    }

    # Get PEM for PyJWT signing
    carrier_pem = carrier_key.export_to_pem(private_key=True, password=None)
    kid = carrier_key["kid"]

    signed_jwt = jwt.encode(
        payload,
        carrier_pem,
        algorithm="ES256",
        headers={"kid": kid, "typ": "vc+sd-jwt"},
    )

    # SD-JWT-VC format: issuer_jwt~disc1~disc2~ (trailing ~ means no KB-JWT)
    return f"{signed_jwt}~{disc_msisdn}~{disc_pseudonym}~"
