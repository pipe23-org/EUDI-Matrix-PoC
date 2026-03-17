"""SD-JWT-VC verification for OpenID4VP."""

import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass

import jwt as pyjwt  # PyJWT
from jwcrypto import jwk

logger = logging.getLogger(__name__)

CARRIER_KEY_PATH = os.environ.get(
    "CARRIER_KEY_PATH", "/app/carrier-public.jwk.json"
)

_carrier_public_pem = None  # cached on first use


# --- base64url helpers (no padding) ---

def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


# --- Key loading ---

def _load_carrier_key():
    """Load carrier ES256 public key from volume-mounted JWK file."""
    global _carrier_public_pem
    with open(CARRIER_KEY_PATH) as f:
        key_data = json.load(f)
    jwk_key = jwk.JWK(**key_data)
    _carrier_public_pem = jwk_key.export_to_pem()
    logger.info("Loaded carrier public key from %s", CARRIER_KEY_PATH)


def get_carrier_public_key():
    """Return cached carrier public key PEM, loading on first call."""
    if _carrier_public_pem is None:
        _load_carrier_key()
    return _carrier_public_pem


def is_configured() -> bool:
    """Check if carrier public key file exists."""
    return os.path.exists(CARRIER_KEY_PATH)


def load_carrier_key_from_path(path: str):
    """Load carrier key from an explicit path (for testing)."""
    global _carrier_public_pem
    with open(path) as f:
        key_data = json.load(f)
    jwk_key = jwk.JWK(**key_data)
    _carrier_public_pem = jwk_key.export_to_pem()


# --- Result type ---

@dataclass
class VerifiedCredential:
    msisdn: str          # phone number from disclosed claims
    pseudonym: str       # wallet-derived per-RP pseudonym from disclosed claims
    raw_claims: dict     # all disclosed claim name -> value pairs
    issuer_jwt: str      # carrier-signed JWT (for phonebook write-gate verification)


# --- Verification ---

def verify_presentation(
    vp_token: str,
    expected_nonce: str,
    expected_aud: str,
) -> VerifiedCredential:
    """Verify an SD-JWT-VC presentation (VP token) and extract claims.

    Args:
        vp_token: Full VP token string (issuer_jwt~disclosure1~...~kb_jwt).
        expected_nonce: Nonce the verifier sent in the authorization request.
        expected_aud: Expected audience (verifier's client_id / PUBLIC_BASE).

    Returns:
        VerifiedCredential with extracted claims.

    Raises:
        ValueError: If any verification step fails.
        jwt.InvalidTokenError: If JWT signature verification fails.
    """
    # 1. Split on ~
    parts = vp_token.split("~")
    if len(parts) < 3:
        raise ValueError(f"Invalid SD-JWT-VC: expected at least 3 parts, got {len(parts)}")

    issuer_jwt_str = parts[0]
    kb_jwt_str = parts[-1]

    # Disclosures are everything between the first and last part
    # If the last part is empty (trailing ~), there's no KB-JWT
    if not kb_jwt_str:
        raise ValueError("No KB-JWT found (trailing ~ with no content)")

    disclosures = parts[1:-1]
    # Filter out empty strings (from trailing ~ before KB-JWT)
    disclosures = [d for d in disclosures if d]

    # The presentation string for sd_hash is everything before the KB-JWT
    # i.e., issuer_jwt~disclosure1~...~ (including the trailing ~)
    presentation_string = "~".join(parts[:-1]) + "~"

    # 2. Decode and verify issuer JWT
    issuer_public_pem = get_carrier_public_key()
    issuer_claims = pyjwt.decode(
        issuer_jwt_str,
        issuer_public_pem,
        algorithms=["ES256"],
    )

    # 3. Verify disclosures against _sd array
    sd_hashes = issuer_claims.get("_sd", [])
    disclosed_claims = {}

    for disc_str in disclosures:
        # Hash the disclosure string (base64url string as ASCII bytes)
        disc_hash = b64url_encode(hashlib.sha256(disc_str.encode("ascii")).digest())

        if disc_hash not in sd_hashes:
            raise ValueError(
                f"Disclosure hash {disc_hash} not found in issuer _sd array"
            )

        # Decode disclosure: base64url-encoded JSON array [salt, name, value]
        disc_json = b64url_decode(disc_str).decode("utf-8")
        disc_arr = json.loads(disc_json)
        if not isinstance(disc_arr, list) or len(disc_arr) != 3:
            raise ValueError(f"Invalid disclosure format: {disc_arr}")

        _salt, claim_name, claim_value = disc_arr
        disclosed_claims[claim_name] = claim_value

    # 4. Extract holder public key from cnf.jwk
    cnf = issuer_claims.get("cnf")
    if not cnf or "jwk" not in cnf:
        raise ValueError("No cnf.jwk in issuer JWT")
    holder_jwk_dict = cnf["jwk"]

    # Convert holder JWK to PEM for PyJWT verification
    holder_jwk_obj = jwk.JWK(**holder_jwk_dict)
    holder_public_pem = holder_jwk_obj.export_to_pem()

    # 5. Verify KB-JWT signature with holder key
    # Pass audience to PyJWT so it validates the aud claim (PyJWT requires this
    # when aud is present in the token, otherwise it raises InvalidAudienceError)
    kb_claims = pyjwt.decode(
        kb_jwt_str,
        holder_public_pem,
        algorithms=["ES256"],
        audience=expected_aud,
    )

    # 6. Check KB-JWT claims
    if kb_claims.get("nonce") != expected_nonce:
        raise ValueError(
            f"KB-JWT nonce mismatch: got {kb_claims.get('nonce')!r}, expected {expected_nonce!r}"
        )

    # 7. Verify sd_hash in KB-JWT
    expected_sd_hash = b64url_encode(
        hashlib.sha256(presentation_string.encode("ascii")).digest()
    )
    if kb_claims.get("sd_hash") != expected_sd_hash:
        raise ValueError(
            f"KB-JWT sd_hash mismatch: got {kb_claims.get('sd_hash')!r}, "
            f"expected {expected_sd_hash!r}"
        )

    # 8. Check we got msisdn and pseudonym
    if "msisdn" not in disclosed_claims:
        raise ValueError("No msisdn disclosure found in presentation")
    if "pseudonym" not in disclosed_claims:
        raise ValueError("No pseudonym disclosure found in presentation")

    return VerifiedCredential(
        msisdn=disclosed_claims["msisdn"],
        pseudonym=disclosed_claims["pseudonym"],
        raw_claims=disclosed_claims,
        issuer_jwt=issuer_jwt_str,
    )
