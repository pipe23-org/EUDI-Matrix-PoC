"""Synapse user provisioning + phonebook registration."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

SYNAPSE_URL = os.environ.get("SYNAPSE_URL", "http://synapse:8008")
SYNAPSE_SERVER_NAME = os.environ.get("SYNAPSE_SERVER_NAME", "localhost")
SYNAPSE_ADMIN_TOKEN = os.environ.get("SYNAPSE_ADMIN_TOKEN", "homeserver-secret")  # PoC default
PHONEBOOK_URL = os.environ.get("PHONEBOOK_URL", "http://host.docker.internal:8091")


async def provision_wallet_user(
    pseudonym_hex: str,
    displayname: str | None = None,
) -> tuple[str, int, dict]:
    """Create or update a wallet-provisioned user.

    Localpart: w-{first 12 hex chars of pseudonym}.
    external_id: full pseudonym hex (64 chars).

    Returns (username, status_code, response_dict).
    """
    username = f"w-{pseudonym_hex[:12]}"
    user_id = f"@{username}:{SYNAPSE_SERVER_NAME}"

    body = {
        "displayname": displayname or username,
        "external_ids": [
            {
                "auth_provider": "oauth-delegated",
                "external_id": pseudonym_hex,
            }
        ],
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.put(
            f"{SYNAPSE_URL}/_synapse/admin/v2/users/{user_id}",
            json=body,
            headers={"Authorization": f"Bearer {SYNAPSE_ADMIN_TOKEN}"},
        )
        resp.raise_for_status()
        logger.info("Synapse wallet user %s: %d", user_id, resp.status_code)
        return username, resp.status_code, resp.json()


async def register_phone(phone_number: str, mxid: str, sources: dict, issuer_jwt: str = ""):
    """Register phone->MXID in the phonebook. Fire-and-forget.

    Phone number MUST include + prefix (E.164 format).
    Phonebook returns empty body (201/200), do NOT call .json().

    Args:
        phone_number: E.164 phone number, e.g. "+358401234567"
        mxid: full Matrix user ID, e.g. "@fi-440397400:hs1.matrix.local:8448"
        sources: claim provenance dict for audit trail
        issuer_jwt: carrier-signed JWT for phonebook write-gate verification
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{PHONEBOOK_URL}/v1/records",
                json={
                    "phone_number": phone_number,
                    "mxid": mxid,
                    "claims_source": sources,
                    "carrier_jwt": issuer_jwt,
                },
            )
            # Do NOT call resp.json() — response has no body
            logger.info(
                "Phonebook registered %s: %d", mxid, resp.status_code
            )
    except Exception as e:
        # Fire-and-forget: log but don't fail the login
        logger.warning("Phonebook write failed: %s", e)
