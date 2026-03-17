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

### Prototype API (custom, not IS spec)

| Endpoint | Purpose |
|---|---|
| `POST /v1/records` | Write-gated record creation. Requires `carrier_jwt`. |
| `GET /v1/dump` | Bulk download all records. Public, no auth. |
| `DELETE /v1/records/{phone_number}` | Delete a record. No auth gate (PoC only). |

### Write-gate

`POST /v1/records` requires a `carrier_jwt` field — the issuer JWT from an SD-JWT-VC credential chain. The phonebook independently verifies the carrier's ES256 signature against a configured public key before accepting the write. The provisioning agent has already verified selective disclosures and extracted the phone number; the phonebook re-verifies the carrier signature to ensure the JWT is authentic, not forged.

### Why this architecture

The IS v2 lookup endpoints are a compatibility shim. The target architecture is the `/v1/dump` endpoint: a bulletin board you download in bulk, not a service you query per-number. Clients download the full directory and resolve locally. The write side requires carrier attestation so only carrier-verified phone numbers enter the directory.

## Trust model

The phonebook verifies the carrier's ES256 signature on every write, rejecting entries without a valid carrier JWT. The provisioning agent has already verified the full SD-JWT-VC presentation (selective disclosures, key binding, nonce), but the phonebook does not trust the provisioner — it independently re-verifies the carrier signature and checks that the phone number in the verified claims matches the request.

In a production design, each phonebook entry should carry a three-signature envelope:

1. **Carrier** — attests the phone number is real and belongs to a credential holder (the SD-JWT-VC signature)
2. **Wallet** — proves pseudonym ownership (ideally via a zero-knowledge proof rather than a self-assertion)
3. **Provisioner** — attests that it verified both signatures and created the MXID binding at a specific time

With all three signatures, any reader who downloads the phonebook can independently verify every entry without trusting the phonebook operator. The three-signature envelope is described but not yet implemented.

The IS v2 per-number lookup endpoints (`/_matrix/identity/v2/lookup` etc.) are a compatibility shim. Element Web's invite dialog expects a standard IS v2 server for phone number search, so the phonebook speaks that protocol on the read side. The hashed lookup uses a public pepper, which provides no real privacy for phone numbers (the keyspace is small enough to enumerate in seconds). This is a known limitation of IS v2 itself, not something we can fix at this layer. The target read model is bulk download via `/dump` — clients take the whole dataset and resolve locally, so the phonebook never learns who you are looking for.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PHONEBOOK_PEPPER` | `matrixrocks` | Pepper for IS v2 hash-based lookup |
| `CARRIER_KEY_PATH` | `/app/carrier-public.jwk.json` | Path to carrier ES256 public key (JWK format) |
| `PUBLIC_BASE` | `http://localhost:8090` | Base URL for the service |
