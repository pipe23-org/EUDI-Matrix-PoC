"""OpenID4VP endpoints — wallet credential presentation and verification."""

import asyncio
import logging
import time
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import vp_verifier
from oidc_provider import _append_params
from provisioning import provision_wallet_user, register_phone, SYNAPSE_SERVER_NAME
from store import (
    pending_vp_requests,
    auth_codes,
    AuthCodeRecord,
    parse_device_id,
    generate_token,
    log_provision,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/openid4vp", tags=["openid4vp"])

# Set from app.py on startup
PUBLIC_BASE: str = ""


def _client_id():
    """Stable RP identifier for OpenID4VP, decoupled from response endpoint URL."""
    return f"mock:{urllib.parse.urlparse(PUBLIC_BASE).hostname}"


# --- Request endpoint (wallet fetches authorization request) ---

@router.get("/request/{our_state}")
async def vp_request(our_state: str):
    pending = pending_vp_requests.get(our_state)
    if not pending:
        return JSONResponse(status_code=404, content={"error": "request_not_found"})

    return {
        "response_type": "vp_token",
        "nonce": pending.vp_nonce,
        # OpenID4VP 1.0 Client Identifier Prefix scheme. "mock:" is a custom prefix for
        # the PoC — a spec-compliant wallet would reject it (unknown prefix). In production,
        # this would be x509_san_dns:{domain} backed by an RPAC, or verifier_attestation:{id}
        # backed by a Verifier Attestation JWT. The hostname decouples RP identity from
        # response endpoint routing, so pseudonyms survive infrastructure changes.
        # The client is the provisioning agent, not the homeserver.
        "client_id": _client_id(),
        "response_uri": f"{PUBLIC_BASE.rstrip('/')}/openid4vp/response",
        "presentation_definition": pending.presentation_definition,
    }


# --- Response endpoint (wallet POSTs VP token) ---

@router.post("/response")
async def vp_response(request: Request):
    # Accept both form and JSON body
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    vp_token = body.get("vp_token", "")
    state = body.get("state", "")

    # Look up and consume pending request
    pending = pending_vp_requests.pop(state, None)
    if not pending:
        return JSONResponse(status_code=400, content={
            "error": "invalid_state",
            "error_description": "No pending VP request for this state.",
        })

    # Verify the presentation
    try:
        credential = vp_verifier.verify_presentation(
            vp_token, pending.vp_nonce, _client_id()
        )
    except Exception as e:
        logger.warning("VP verification failed: %s", e)
        return JSONResponse(status_code=401, content={
            "error": "invalid_presentation",
            "error_description": str(e),
        })

    msisdn = credential.msisdn
    pseudonym_hex = credential.pseudonym

    # Provision Synapse user
    try:
        username, status_code, _resp = await provision_wallet_user(
            pseudonym_hex, displayname=None
        )
        log_provision(username, "synapse_wallet_provision", status_code,
                      {"source": "wallet", "pseudonym": pseudonym_hex[:12]})
    except Exception as e:
        log_provision(f"w-{pseudonym_hex[:12]}", "synapse_wallet_provision_failed", 500,
                      {"source": "wallet", "error": str(e)})
        return JSONResponse(status_code=502, content={
            "error": "provisioning_failed",
            "error_description": f"Synapse provisioning failed: {e}",
        })

    # Register phone in phonebook (fire-and-forget)
    mxid = f"@{username}:{SYNAPSE_SERVER_NAME}"
    asyncio.create_task(register_phone(
        msisdn, mxid, {"source": "wallet", "pseudonym": pseudonym_hex[:12]},
        issuer_jwt=credential.issuer_jwt,
    ))

    # Mint auth code for Element
    code = generate_token()
    device_id = parse_device_id(pending.scope)

    auth_codes[code] = AuthCodeRecord(
        code=code,
        sub=pseudonym_hex,
        username=username,
        scope=pending.scope,
        device_id=device_id,
        client_id=pending.client_id,
        redirect_uri=pending.element_redirect_uri,
        code_challenge=pending.code_challenge,
        code_challenge_method=pending.code_challenge_method,
        nonce=pending.nonce,
        expires_at=time.time() + 60,
    )

    # Log auth event
    log_provision(username, "wallet_auth", 200, {
        "pseudonym": pseudonym_hex[:12],
    })

    # Build redirect URL for the wallet to send the browser to
    redirect_url = _append_params(pending.element_redirect_uri, {
        "code": code,
        "state": pending.element_state,
    })

    return {"redirect_uri": redirect_url}
