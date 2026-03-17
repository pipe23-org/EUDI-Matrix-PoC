"""MSC3861 OIDC provider endpoints for the provisioning agent."""

import base64
import hashlib
import logging
import os
import secrets
import time
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

import jwt
from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from store import (
    tokens, refresh_tokens, auth_codes,
    pending_vp_requests, PendingVPAuth,
    TokenRecord, generate_token, get_jwks,
    load_or_create_signing_key,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Static clients — PoC demo credentials, must match Synapse config
CLIENTS = {
    "0000000000000000000SYNAPSE": {
        "auth_method": "client_secret_basic",
        "secret": "synapse-client-secret",  # PoC demo credential — not for production
    },
    "0000000000000000000WEBAPPS": {
        "auth_method": "none",
    },
}

TOKEN_LIFETIME = 86400  # 24 hours

# Set from app.py on startup -- avoids passing Request through to helpers
PUBLIC_BASE: str = ""

WALLET_URL = os.environ.get("WALLET_URL", "http://localhost:8095")


def _append_params(url: str, params: dict) -> str:
    """Safely append query params to a URL that may already have params."""
    parsed = urlparse(url)
    existing = parse_qs(parsed.query, keep_blank_values=True)
    existing.update({k: [v] for k, v in params.items()})
    new_query = urlencode(existing, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


# --- Discovery ---

@router.get("/.well-known/openid-configuration")
async def discovery(request: Request):
    issuer = request.app.state.public_base.rstrip("/") + "/"
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}authorize",
        "token_endpoint": f"{issuer}oauth2/token",
        "jwks_uri": f"{issuer}oauth2/keys.json",
        "registration_endpoint": f"{issuer}oauth2/registration",
        "introspection_endpoint": f"{issuer}oauth2/introspect",
        "revocation_endpoint": f"{issuer}oauth2/revoke",
        "userinfo_endpoint": f"{issuer}oauth2/userinfo",
        "scopes_supported": [
            "openid",
            "urn:matrix:org.matrix.msc2967.client:api:*",
            "urn:matrix:org.matrix.msc2967.client:api:guest",
        ],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic", "client_secret_post", "none"
        ],
        "code_challenge_methods_supported": ["S256"],
        "subject_types_supported": ["public"],
        "prompt_values_supported": ["login", "create"],
    }


# --- JWKS ---

@router.get("/oauth2/keys.json")
async def jwks():
    return get_jwks()


# --- Registration (not supported) ---

@router.post("/oauth2/registration")
async def registration():
    return JSONResponse(
        status_code=501,
        content={"error": "registration_not_supported"},
    )


# --- Authorize (redirect to wallet via OpenID4VP) ---

@router.get("/authorize")
async def authorize(request: Request):
    params = dict(request.query_params)

    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    element_state = params.get("state", "")
    nonce = params.get("nonce")
    scope = params.get("scope", "openid")
    code_challenge = params.get("code_challenge", "")
    code_challenge_method = params.get("code_challenge_method", "S256")

    # Validate client
    if client_id not in CLIENTS:
        return JSONResponse(status_code=400, content={"error": "unknown_client"})

    our_state = secrets.token_urlsafe(32)

    vp_nonce = secrets.token_urlsafe(16)
    # Two input_descriptors: one per trust domain. The carrier attests the
    # phone number (routing/discovery). The wallet derives the pseudonym
    # (identity/account binding). Different issuers, different trust anchors.
    # In the mock, both claims travel in one SD-JWT-VC — that's a mock
    # simplification. The presentation_definition models the conceptual
    # reality: the RP needs two things from two sources.
    presentation_definition = {
        "id": "identity-request",
        "input_descriptors": [
            {
                "id": "carrier_msisdn",
                "name": "Phone number",
                "purpose": "Carrier-attested phone number for routing and discovery",
                "format": {"vc+sd-jwt": {"alg": ["ES256"]}},
                "constraints": {
                    "fields": [
                        {"path": ["$.vct"], "filter": {"const": "urn:eu.europa.ec.eudi:msisdn:1"}},
                        {"path": ["$.msisdn"]},
                    ]
                }
            },
            {
                "id": "wallet_pseudonym",
                "name": "Pseudonym",
                "purpose": "Wallet-derived per-service pseudonym for account binding",
                "format": {"vc+sd-jwt": {"alg": ["ES256"]}},
                "constraints": {
                    "fields": [
                        {"path": ["$.pseudonym"]},
                    ]
                }
            },
        ]
    }

    pending_vp_requests[our_state] = PendingVPAuth(
        element_redirect_uri=redirect_uri,
        element_state=element_state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        nonce=nonce,
        scope=scope,
        client_id=client_id,
        vp_nonce=vp_nonce,
        presentation_definition=presentation_definition,
    )

    request_uri = f"{PUBLIC_BASE.rstrip('/')}/openid4vp/request/{our_state}"
    wallet_redirect = f"{WALLET_URL}/authorize?request_uri={request_uri}&state={our_state}"
    return RedirectResponse(url=wallet_redirect, status_code=302)


# --- Token exchange ---

@router.post("/oauth2/token")
async def token_exchange(
    grant_type: str = Form(...),
    code: str = Form(None),
    redirect_uri: str = Form(None),
    code_verifier: str = Form(None),
    client_id: str = Form(None),
    refresh_token_param: str = Form(None, alias="refresh_token"),
):
    if grant_type == "authorization_code":
        return await _handle_auth_code(code, redirect_uri, code_verifier, client_id)
    elif grant_type == "refresh_token":
        return await _handle_refresh(refresh_token_param)
    else:
        return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})


async def _handle_auth_code(
    code: str | None,
    redirect_uri: str | None,
    code_verifier: str | None,
    client_id: str | None,
):
    if not code or code not in auth_codes:
        return JSONResponse(status_code=400, content={"error": "invalid_grant"})

    record = auth_codes.pop(code)

    # Check expiry
    if time.time() > record.expires_at:
        return JSONResponse(status_code=400, content={"error": "invalid_grant"})

    # PKCE S256 verification
    if record.code_challenge and code_verifier:
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")

        if challenge != record.code_challenge:
            return JSONResponse(status_code=400, content={"error": "invalid_grant",
                                "error_description": "PKCE verification failed"})

    # Mint access token
    access_token = generate_token()
    rt = f"rt_{generate_token()}"
    now = time.time()

    tokens[access_token] = TokenRecord(
        access_token=access_token,
        sub=record.sub,
        username=record.username,
        scope=record.scope,
        device_id=record.device_id,
        client_id=record.client_id,
        expires_at=now + TOKEN_LIFETIME,
        refresh_token=rt,
    )
    refresh_tokens[rt] = access_token

    # Mint id_token (signed JWT)
    signing_key = load_or_create_signing_key()
    issuer = PUBLIC_BASE.rstrip("/") + "/"  # trailing slash!

    id_token_payload = {
        "iss": issuer,
        "sub": record.sub,
        "aud": record.client_id,
        "iat": int(now),
        "exp": int(now) + TOKEN_LIFETIME,
    }
    if record.nonce:
        id_token_payload["nonce"] = record.nonce

    # Sign with ES256
    private_pem = signing_key.export_to_pem(private_key=True, password=None)
    id_token = jwt.encode(
        id_token_payload,
        private_pem,
        algorithm="ES256",
        headers={"kid": signing_key.key_id},
    )

    return JSONResponse(content={
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": TOKEN_LIFETIME,
        "refresh_token": rt,
        "id_token": id_token,
    })


async def _handle_refresh(refresh_token_value: str | None):
    """Dummy refresh -- return error to force re-auth."""
    return JSONResponse(status_code=400, content={
        "error": "invalid_grant",
        "error_description": "Refresh tokens not supported, please re-authenticate",
    })


# --- Introspection ---

@router.post("/oauth2/introspect")
async def introspect(request: Request, token: str = Form(...)):
    # Validate client_secret_basic auth from Synapse
    auth_header = request.headers.get("authorization", "")
    if not _validate_basic_auth(auth_header):
        return JSONResponse(status_code=401, content={"error": "invalid_client"})

    record = tokens.get(token)
    if not record or time.time() > record.expires_at:
        return {"active": False}

    return {
        "active": True,
        "sub": record.sub,
        "username": record.username,
        "scope": record.scope,
        "client_id": record.client_id,
        "token_type": "access_token",
        "exp": int(record.expires_at),
    }


def _validate_basic_auth(auth_header: str) -> bool:
    """Validate Authorization: Basic header against static Synapse client."""
    if not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        client_id, client_secret = decoded.split(":", 1)
        client = CLIENTS.get(client_id)
        if not client or client["auth_method"] != "client_secret_basic":
            return False
        return client.get("secret") == client_secret
    except Exception:
        return False


# --- Userinfo ---

@router.get("/oauth2/userinfo")
async def userinfo(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "invalid_token"})

    token_str = auth[7:]
    record = tokens.get(token_str)
    if not record or time.time() > record.expires_at:
        return JSONResponse(status_code=401, content={"error": "invalid_token"})

    return {"sub": record.sub}


# --- Revocation ---

@router.post("/oauth2/revoke")
async def revoke(token: str = Form(...)):
    # Remove token if it exists
    record = tokens.pop(token, None)
    if record and record.refresh_token:
        refresh_tokens.pop(record.refresh_token, None)
    # Also check if it's a refresh token
    access = refresh_tokens.pop(token, None)
    if access:
        tokens.pop(access, None)
    # Always return 200 per RFC 7009
    return Response(status_code=200)
