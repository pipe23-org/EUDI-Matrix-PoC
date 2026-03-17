# Phonebook

Phone-to-MXID directory service. Maps E.164 phone numbers to Matrix user IDs so federated messaging users can find each other by phone number.

In-memory, no persistence. Data is lost on restart. This is intentional for the PoC.

## API surface

### Matrix Identity Service v2 (read — Element Web compatibility)

These endpoints exist because Element Web's invite dialog expects a standard IS v2 server for phone number lookup. They are the only IS v2 endpoints implemented.

| Endpoint | Purpose |
|---|---|
| `GET /_matrix/identity/v2` | Version check (returns `{}`) |
| `POST /_matrix/identity/v2/account/register` | Stub — returns static token |
| `GET /_matrix/identity/v2/account` | Stub — returns fixed user ID |
| `GET /_matrix/identity/v2/terms` | Stub terms response |
| `GET /_matrix/identity/v2/hash_details` | Returns pepper and supported hash algorithm (`sha256`) |
| `POST /_matrix/identity/v2/lookup` | Hash-based phone number lookup, returns `{hash: mxid}` mappings |

Not implemented: everything else in the IS v2 spec — no 3PID binding, no invitation storage, no key management, no email validation. This is a directory, not a full identity server.

### Write API (custom, not IS spec)

| Endpoint | Purpose |
|---|---|
| `POST /v1/records` | Write-gated record creation. Requires `carrier_jwt`. |
| `GET /v1/dump` | Bulk download all records. Public, no auth. |
| `DELETE /v1/records/{phone_number}` | Delete a record. No auth gate (PoC only). |

### Write-gate

`POST /v1/records` requires a `carrier_jwt` field — the issuer JWT from an SD-JWT-VC credential chain. The phonebook independently verifies the carrier's ES256 signature against a configured public key before accepting the write. The provisioning agent has already verified selective disclosures and extracted the phone number; the phonebook re-verifies the carrier signature to ensure the JWT is authentic, not forged.

### Why this architecture

The IS v2 lookup endpoints are a compatibility shim. The target architecture is the `/v1/dump` endpoint: a bulletin board you download in bulk, not a service you query per-number. Clients download the full directory and resolve locally. The write side requires carrier attestation so only carrier-verified phone numbers enter the directory.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PHONEBOOK_PEPPER` | `matrixrocks` | Pepper for IS v2 hash-based lookup |
| `CARRIER_KEY_PATH` | `/app/carrier-public.jwk.json` | Path to carrier ES256 public key (JWK format) |
| `PUBLIC_BASE` | `http://localhost:8090` | Base URL for the service |
