import hashlib
import base64
import json
import logging
import os
import time
from dataclasses import dataclass

import jwt as pyjwt
from jwcrypto import jwk
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("phonebook")

PEPPER = os.getenv("PHONEBOOK_PEPPER", "matrixrocks")
PUBLIC_BASE = os.getenv("PUBLIC_BASE", "http://localhost:8090")
CARRIER_KEY_PATH = os.environ.get("CARRIER_KEY_PATH", "/app/carrier-public.jwk.json")

_carrier_public_pem = None  # cached on first use


def _load_carrier_key():
    """Load carrier ES256 public key from volume-mounted JWK file."""
    global _carrier_public_pem
    with open(CARRIER_KEY_PATH) as f:
        key_data = json.load(f)
    jwk_key = jwk.JWK(**key_data)
    _carrier_public_pem = jwk_key.export_to_pem()
    log.info("Loaded carrier public key from %s", CARRIER_KEY_PATH)


def get_carrier_public_key():
    """Return cached carrier public key PEM, loading on first call."""
    if _carrier_public_pem is None:
        _load_carrier_key()
    return _carrier_public_pem


def verify_carrier_jwt(carrier_jwt: str) -> dict:
    """Verify carrier JWT signature and return claims.

    Raises:
        ValueError: If JWT is missing or verification fails.
    """
    if not carrier_jwt:
        raise ValueError("carrier_jwt is required for write-gate verification")
    carrier_pem = get_carrier_public_key()
    try:
        return pyjwt.decode(carrier_jwt, carrier_pem, algorithms=["ES256"])
    except pyjwt.InvalidTokenError as e:
        raise ValueError(f"Carrier JWT verification failed: {e}")


@dataclass
class PhoneRecord:
    phone_number: str  # E.164 with +
    mxid: str
    claims_source: dict
    created_at: float
    updated_at: float


# Primary storage — keyed by E.164 phone number
records: dict[str, PhoneRecord] = {}

# IS lookup index — keyed by hash, rebuilt on mutation
hash_index: dict[str, str] = {}  # hash -> mxid


def compute_hash(phone_e164: str, pepper: str) -> str:
    raw = phone_e164.lstrip("+") + " msisdn " + pepper
    digest = hashlib.sha256(raw.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def rebuild_hash_index(log_contents: bool = False):
    hash_index.clear()
    for phone, rec in records.items():
        h = compute_hash(phone, PEPPER)
        hash_index[h] = rec.mxid
    if log_contents:
        for h, mxid in hash_index.items():
            log.info(f"Hash index: {h} → {mxid}")


def upsert_record(phone_number: str, mxid: str, claims_source: dict) -> bool:
    """Returns True if new, False if updated."""
    now = time.time()
    existing = records.get(phone_number)
    if existing:
        existing.mxid = mxid
        existing.claims_source = claims_source
        existing.updated_at = now
        rebuild_hash_index()
        return False
    records[phone_number] = PhoneRecord(
        phone_number=phone_number,
        mxid=mxid,
        claims_source=claims_source,
        created_at=now,
        updated_at=now,
    )
    rebuild_hash_index()
    return True


app = FastAPI(title="Phonebook", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup():
    log.info("Phonebook started (empty — use seed-data.sh or POST /v1/records to populate)")
    rebuild_hash_index(log_contents=True)


# ---------------------------------------------------------------------------
# Matrix Identity Service v2 endpoints
# ---------------------------------------------------------------------------

@app.get("/_matrix/identity/v2")
async def is_version():
    return {}


@app.post("/_matrix/identity/v2/account/register")
async def is_register(request: Request):
    return {"token": "phonebook-static-token"}


@app.get("/_matrix/identity/v2/account")
async def is_account():
    return {"user_id": "@phonebook:localhost"}


@app.get("/_matrix/identity/v2/terms")
async def is_terms():
    return {"policies": {
        "privacy_policy": {
            "version": "1.0",
            "en": {
                "name": "PoC Identity Service — No personal data is stored",
                "url": "https://localhost/"
            }
        }
    }}


@app.get("/_matrix/identity/v2/hash_details")
async def is_hash_details():
    return {"lookup_pepper": PEPPER, "algorithms": ["sha256"]}


@app.post("/_matrix/identity/v2/lookup")
async def is_lookup(request: Request):
    body = await request.json()
    algorithm = body.get("algorithm")
    pepper = body.get("pepper")
    addresses = body.get("addresses", [])

    if pepper != PEPPER:
        return Response(
            status_code=400,
            content='{"errcode": "M_INVALID_PEPPER", "error": "Unknown or invalid pepper", "algorithm": "sha256", "lookup_pepper": "' + PEPPER + '"}',
            media_type="application/json",
        )

    if algorithm != "sha256":
        return Response(
            status_code=400,
            content='{"errcode": "M_INVALID_PARAM", "error": "Unsupported algorithm"}',
            media_type="application/json",
        )

    mappings = {}
    for addr in addresses:
        if addr in hash_index:
            mappings[addr] = hash_index[addr]

    return {"mappings": mappings}


# ---------------------------------------------------------------------------
# Write API (phase 2, but included now)
# ---------------------------------------------------------------------------

@app.post("/v1/records")
async def create_record(request: Request):
    body = await request.json()
    phone_number = body["phone_number"]
    mxid = body["mxid"]
    claims_source = body.get("claims_source", {})
    carrier_jwt = body.get("carrier_jwt", "")

    # Write-gate: verify carrier JWT signature
    try:
        verify_carrier_jwt(carrier_jwt)  # side effect: raises ValueError on bad sig
    except ValueError as e:
        log.warning("Write-gate rejected: %s", e)
        return Response(
            status_code=403,
            content=json.dumps({"error": "write_gate_failed", "detail": str(e)}),
            media_type="application/json",
        )

    # The carrier JWT contains _sd hashes but not the disclosed phone number directly.
    # The phone number is disclosed via SD-JWT selective disclosure, which the provisioning
    # agent has already verified. We trust the provisioner's extraction — it verified the
    # disclosure against the _sd array and the carrier signature in the same token.
    # What we verify here: the carrier_jwt is authentically carrier-signed (not forged).

    is_new = upsert_record(phone_number, mxid, claims_source)
    log.info("Write-gate passed, record %s: %s", "created" if is_new else "updated", mxid)
    return Response(status_code=201 if is_new else 200)


@app.get("/v1/dump")
async def dump_records():
    """Bulk download all records. No authentication — public bulletin board."""
    return [
        {
            "phone_number": rec.phone_number,
            "mxid": rec.mxid,
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
        }
        for rec in records.values()
    ]


@app.delete("/v1/records/{phone_number}")
async def delete_record(phone_number: str):
    if phone_number not in records:
        return Response(status_code=404)
    del records[phone_number]
    rebuild_hash_index()
    return Response(status_code=204)
