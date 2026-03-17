"""In-memory data stores and signing key management for the provisioning agent."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import secrets

from jwcrypto import jwk

DATA_DIR = Path("/data")
KEYS_DIR = DATA_DIR / "keys"


@dataclass
class TokenRecord:
    access_token: str
    sub: str                    # pseudonym or upstream sub
    username: str               # Matrix localpart, e.g. "w-a1b2c3d4e5f6"
    scope: str                  # full scope string from Element
    device_id: str | None       # parsed from scope URN
    client_id: str              # which client (WEBAPPS or SYNAPSE)
    expires_at: float           # unix timestamp
    refresh_token: str | None   # dummy refresh token


@dataclass
class AuthCodeRecord:
    code: str
    sub: str
    username: str
    scope: str
    device_id: str | None
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    nonce: str | None
    expires_at: float           # short-lived: 60 seconds


@dataclass
class PendingVPAuth:
    """State stored between Element's /authorize and the wallet VP response."""
    element_redirect_uri: str
    element_state: str
    code_challenge: str
    code_challenge_method: str
    nonce: str | None           # Element's OIDC nonce (for id_token)
    scope: str
    client_id: str
    vp_nonce: str              # separate nonce for KB-JWT verification
    presentation_definition: dict


# In-memory stores (lost on restart -- users re-auth)
tokens: dict[str, TokenRecord] = {}
refresh_tokens: dict[str, str] = {}   # refresh_token -> access_token
auth_codes: dict[str, AuthCodeRecord] = {}
pending_vp_requests: dict[str, PendingVPAuth] = {}


def parse_device_id(scope: str) -> str | None:
    """Extract device_id from Element's scope URN.

    Element encodes: urn:matrix:org.matrix.msc2967.client:device:XXYYZZ
    """
    for part in scope.split():
        prefix = "urn:matrix:org.matrix.msc2967.client:device:"
        if part.startswith(prefix):
            return part[len(prefix):]
    return None


def generate_token() -> str:
    return secrets.token_urlsafe(32)


# --- Signing key management ---

SIGNING_KEY: jwk.JWK | None = None


def load_or_create_signing_key() -> jwk.JWK:
    """Load signing key from disk, or generate ES256 on first run."""
    global SIGNING_KEY
    signing_path = KEYS_DIR / "signing.jwk.json"

    KEYS_DIR.mkdir(parents=True, exist_ok=True)

    if signing_path.exists():
        SIGNING_KEY = jwk.JWK.from_json(signing_path.read_text())
    else:
        SIGNING_KEY = jwk.JWK.generate(kty="EC", crv="P-256", use="sig", kid=secrets.token_hex(8))
        signing_path.write_text(SIGNING_KEY.export())

    return SIGNING_KEY


def get_jwks() -> dict:
    """Return JWKS for /oauth2/keys.json -- public keys only."""
    if SIGNING_KEY is None:
        return {"keys": []}
    pub = json.loads(SIGNING_KEY.export_public())
    pub["use"] = "sig"
    pub["alg"] = "ES256"
    return {"keys": [pub]}


# Provisioning log (in-memory, recent events only)
provisioning_log: list[dict] = []


def log_provision(username: str, action: str, status_code: int, sources: dict):
    """Add a provisioning event to the log."""
    provisioning_log.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "username": username,
        "action": action,
        "status_code": status_code,
        "status": "ok" if status_code in (200, 201) else "error",
        "sources": sources,
    })
    # Keep last 50
    if len(provisioning_log) > 50:
        provisioning_log.pop(0)
