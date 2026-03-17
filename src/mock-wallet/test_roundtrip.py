"""Standalone round-trip test for SD-JWT-VC issuance, presentation, and verification.

Run: cd src/mock-wallet && uv run python test_roundtrip.py
"""

import os
import sys
import secrets
import tempfile


# Add provisioning-agent to path for vp_verifier import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "provisioning-agent"))

from jwcrypto import jwk

from carrier import issue_credential, b64url_decode
from credential import build_vp_token
from vp_verifier import (
    verify_presentation,
    load_carrier_key_from_path,
)


def generate_test_key() -> jwk.JWK:
    """Generate a fresh ES256 key for testing."""
    return jwk.JWK.generate(kty="EC", crv="P-256", kid=secrets.token_hex(8))


def test_roundtrip():
    """Full round-trip: issue -> present -> verify (pseudonym from wallet)."""

    # Try loading keys from WALLET_KEYS_DIR, fall back to fresh generation
    keys_dir = os.environ.get("WALLET_KEYS_DIR")
    if keys_dir and os.path.exists(os.path.join(keys_dir, "carrier-key.jwk.json")):
        print(f"Loading keys from {keys_dir}")
        carrier_key = jwk.JWK.from_json(
            open(os.path.join(keys_dir, "carrier-key.jwk.json")).read()
        )
        holder_key = jwk.JWK.from_json(
            open(os.path.join(keys_dir, "holder-a-key.jwk.json")).read()
        )
    else:
        print("Generating fresh test keys")
        carrier_key = generate_test_key()
        holder_key = generate_test_key()

    # Write carrier public key to temp file for vp_verifier to load
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write(carrier_key.export_public())
        carrier_pub_path = f.name

    try:
        # Load carrier public key into verifier
        load_carrier_key_from_path(carrier_pub_path)

        # --- Step 1: Issue credential ---
        phone = "+358401234567"
        test_pseudonym = "a1b2c3" * 10 + "a1b2"  # 64-char hex
        print(f"\n1. Issuing SD-JWT-VC for {phone} with pseudonym {test_pseudonym[:16]}…")
        credential = issue_credential(carrier_key, holder_key, phone, test_pseudonym)
        parts = credential.split("~")
        print(f"   Credential parts: {len(parts)} (issuer JWT + {len(parts) - 2} disclosures + trailing)")
        assert len(parts) == 4, f"Expected 4 parts (JWT + 2 disclosures + trailing), got {len(parts)}"
        print(f"   Issuer JWT length: {len(parts[0])}")

        # Inspect disclosures
        for i, disc in enumerate(parts[1:-1], 1):
            disc_json = b64url_decode(disc).decode("utf-8")
            print(f"   Disclosure {i}: {disc_json}")

        # --- Step 2: Build VP token ---
        nonce = secrets.token_urlsafe(16)
        aud = "mock:auth-hs1.localhost"
        print("\n2. Building VP token")
        print(f"   Nonce: {nonce}")
        print(f"   Audience: {aud}")
        vp_token = build_vp_token(credential, holder_key, nonce, aud)
        vp_parts = vp_token.split("~")
        print(f"   VP token parts: {len(vp_parts)} (issuer JWT + disclosures + KB-JWT)")
        print(f"   KB-JWT length: {len(vp_parts[-1])}")

        # --- Step 3: Verify VP token ---
        print("\n3. Verifying VP token")
        result = verify_presentation(vp_token, nonce, aud)
        print(f"   msisdn: {result.msisdn}")
        print(f"   pseudonym: {result.pseudonym}")
        print(f"   raw_claims: {result.raw_claims}")

        # --- Step 4: Check extracted claims ---
        assert result.msisdn == phone, f"msisdn mismatch: {result.msisdn} != {phone}"
        print(f"\n4. msisdn matches: {result.msisdn}")

        assert result.pseudonym == test_pseudonym, f"pseudonym mismatch: {result.pseudonym} != {test_pseudonym}"
        print(f"   pseudonym matches: {result.pseudonym[:16]}…")

        assert "pseudonym" in result.raw_claims, "pseudonym not in raw_claims"
        assert "msisdn" in result.raw_claims, "msisdn not in raw_claims"
        print("   raw_claims contain both msisdn and pseudonym")

        assert result.issuer_jwt, "issuer_jwt should be populated"
        assert result.issuer_jwt == parts[0], "issuer_jwt should match original issuer JWT"
        print(f"   issuer_jwt populated ({len(result.issuer_jwt)} chars)")

        # --- Step 5: Verify error cases ---
        print("\n5. Testing error cases")

        # Wrong nonce
        try:
            verify_presentation(vp_token, "wrong-nonce", aud)
            assert False, "Should have raised ValueError for wrong nonce"
        except ValueError as e:
            print(f"   Wrong nonce: correctly rejected ({e})")

        # Wrong audience (PyJWT raises InvalidAudienceError, a subclass of InvalidTokenError)
        try:
            verify_presentation(vp_token, nonce, "mock:wrong.example.com")
            assert False, "Should have raised for wrong audience"
        except (ValueError, Exception) as e:
            print(f"   Wrong audience: correctly rejected ({type(e).__name__}: {e})")

        # Tampered token (flip a character in disclosure)
        tampered = vp_token.replace(vp_parts[1], vp_parts[1][:-1] + "X")
        try:
            verify_presentation(tampered, nonce, aud)
            assert False, "Should have raised for tampered disclosure"
        except (ValueError, Exception) as e:
            print(f"   Tampered disclosure: correctly rejected ({type(e).__name__}: {e})")

        print(f"\n{'='*50}")
        print("ALL TESTS PASSED")
        print(f"{'='*50}")

    finally:
        os.unlink(carrier_pub_path)


if __name__ == "__main__":
    test_roundtrip()
