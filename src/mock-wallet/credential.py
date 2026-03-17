"""VP token building — adds Key Binding JWT to an SD-JWT-VC for presentation."""

import base64
import hashlib
import time

import jwt  # PyJWT
from jwcrypto import jwk


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_vp_token(sd_jwt_vc: str, holder_key: jwk.JWK, nonce: str, aud: str) -> str:
    """Build a VP token by appending a Key Binding JWT to the SD-JWT-VC.

    Args:
        sd_jwt_vc: The credential string from issuer (ends with ~).
        holder_key: Holder's private JWK for signing the KB-JWT.
        nonce: Verifier's nonce (from authorization request).
        aud: Verifier's client_id (from authorization request).

    Returns:
        Full VP token: issuer_jwt~disclosure~kb_jwt
    """
    # sd_hash: SHA-256 of everything before the KB-JWT (the sd_jwt_vc itself, including trailing ~)
    sd_hash = b64url_encode(hashlib.sha256(sd_jwt_vc.encode("ascii")).digest())

    now = int(time.time())

    kb_payload = {
        "nonce": nonce,
        "aud": aud,
        "iat": now,
        "sd_hash": sd_hash,
    }

    holder_pem = holder_key.export_to_pem(private_key=True, password=None)
    kid = holder_key["kid"]

    kb_jwt = jwt.encode(
        kb_payload,
        holder_pem,
        algorithm="ES256",
        headers={"typ": "kb+jwt", "kid": kid},
    )

    # sd_jwt_vc already ends with ~, so just append the KB-JWT
    return f"{sd_jwt_vc}{kb_jwt}"
