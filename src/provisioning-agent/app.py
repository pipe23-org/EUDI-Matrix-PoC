"""Provisioning Agent — MSC3861 OIDC provider + wallet credential auto-provisioning for Matrix."""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import vp_verifier
from store import load_or_create_signing_key
from oidc_provider import router as oidc_router
from openid4vp import router as vp_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Provisioning Agent")

# CORS — Element (browser) calls agent from a different origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store public base URL for issuer construction
app.state.public_base = os.environ.get("PUBLIC_BASE", "http://localhost:8080")

# Mount OIDC routes
app.include_router(oidc_router)

# Mount OpenID4VP routes
app.include_router(vp_router)


@app.on_event("startup")
async def startup():
    load_or_create_signing_key()
    # Wire PUBLIC_BASE into oidc_provider and openid4vp modules
    import oidc_provider
    import openid4vp
    oidc_provider.PUBLIC_BASE = app.state.public_base
    openid4vp.PUBLIC_BASE = app.state.public_base
    # Log wallet config
    wallet_url = os.environ.get("WALLET_URL", "http://localhost:8095")
    logger.info("WALLET_URL: %s", wallet_url)
    logger.info("Carrier key configured: %s", vp_verifier.is_configured())


@app.get("/")
async def health():
    """Health check — start-homeservers.sh hits this."""
    return {"status": "ok"}
