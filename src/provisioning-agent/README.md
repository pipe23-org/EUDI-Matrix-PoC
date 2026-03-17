# Provisioning Agent

Minimal [MSC3861](https://github.com/matrix-org/matrix-spec-proposals/pull/3861) OIDC provider and [OpenID4VP](https://openid.net/specs/openid-4-verifiable-presentations-1_0.html) verifier for wallet-based onboarding to Matrix. Synapse delegates authentication to this service. It accepts verifiable credential presentations from a wallet, provisions Synapse accounts, and registers phone numbers in the phonebook. It is a stateless notary: it verifies, provisions, and forgets. No persistent phone-to-identity correlation is stored.

This is NOT MAS (Matrix Authentication Service). It implements the minimum MSC3861 surface to make Synapse's delegated auth work for one flow: wallet credential presentation to account provisioning.

## MSC3861 endpoints

| Endpoint | Method | Notes |
|---|---|---|
| `/.well-known/openid-configuration` | GET | OIDC discovery document |
| `/authorize` | GET | Redirects to wallet via OpenID4VP request URI |
| `/oauth2/token` | POST | Authorization code exchange with PKCE (S256). Mints access token + signed ES256 id_token |
| `/oauth2/introspect` | POST | Token introspection (client_secret_basic auth from Synapse) |
| `/oauth2/userinfo` | GET | Returns `{sub}` for Bearer token |
| `/oauth2/revoke` | POST | Token/refresh token revocation (RFC 7009) |
| `/oauth2/keys.json` | GET | JWKS (ES256 signing key, generated on first run) |
| `/oauth2/registration` | POST | Stub, returns 501 |

**Not implemented:** refresh token rotation (returns `invalid_grant` to force re-auth), dynamic client registration, account management UI, consent screens. Two static clients are hardcoded (one for Synapse with `client_secret_basic`, one for Element Web with `auth_method: none`).

## OpenID4VP endpoints

| Endpoint | Method | Notes |
|---|---|---|
| `/openid4vp/request/{state}` | GET | Wallet fetches the authorization request (presentation_definition, nonce, client_id) |
| `/openid4vp/response` | POST | Wallet submits VP token. Accepts form or JSON. Returns `{redirect_uri}` for the wallet to complete the OIDC flow |

RP-initiated same-device flow only. The `client_id` uses a `mock:` prefix scheme (a spec-compliant wallet would reject this; production would use `x509_san_dns` or `verifier_attestation`).

## Verification pipeline

1. **Parse SD-JWT-VC** -- split `issuer_jwt~disclosure1~...~kb_jwt`
2. **Verify carrier signature** -- issuer JWT verified against carrier ES256 public key (RFC 9901)
3. **Validate selective disclosures** -- hash each disclosure, check against `_sd` array in issuer JWT
4. **Verify key binding JWT** -- KB-JWT signed by holder key (`cnf.jwk` in issuer JWT), audience and nonce checked
5. **Verify `sd_hash`** -- KB-JWT's `sd_hash` binds to the exact set of disclosed claims
6. **Extract claims** -- `msisdn` (carrier-attested phone number) and `pseudonym` (wallet-derived per-RP pseudonym)
7. **Provision Synapse account** -- PUT via admin API, localpart `w-{pseudonym[:12]}`, external_id is the full pseudonym
8. **Register in phonebook** -- fire-and-forget POST to phonebook `/v1/records` with carrier JWT for write-gate verification

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_BASE` | `http://localhost:8080` | Issuer URL (must match Synapse's `issuer` config) |
| `SYNAPSE_URL` | `http://synapse:8008` | Synapse admin API base URL |
| `SYNAPSE_SERVER_NAME` | `localhost` | Server name for constructing MXIDs |
| `SYNAPSE_ADMIN_TOKEN` | `homeserver-secret` | Synapse admin API bearer token |
| `PHONEBOOK_URL` | `http://host.docker.internal:8091` | Phonebook service URL |
| `WALLET_URL` | `http://localhost:8095` | Wallet authorize endpoint base URL |
| `CARRIER_KEY_PATH` | `/app/carrier-public.jwk.json` | Path to carrier ES256 public key (JWK) |

## Running

```
uv run uvicorn app:app --host 0.0.0.0 --port 8080
```

In the PoC stack, this runs in Docker. See `services/poc/` for the compose configuration.
