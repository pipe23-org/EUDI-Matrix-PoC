# EUDI Wallet → Matrix Provisioning

Account provisioning and phone number discovery for federated Matrix homeservers using verifiable credentials from a mock EU Digital Identity Wallet.

This proof of concept uses a mock EUDI wallet to provision Matrix accounts with pseudonymous identities and carrier-attested phone numbers. The phone numbers are registered in a shared phonebook service that enables cross-homeserver discovery. The wallet presents credentials via OpenID4VP; the provisioning agent verifies them and creates accounts accordingly. The carrier attestation is mocked (the wallet acts as both carrier and wallet), but the credential format, the verification pipeline, the selective disclosure, and the trust model are real.

## Consequences

- Phone number is attested by carrier signature, not SMS OTP
- Account identity is a wallet-derived pseudonym, separated from the phone number
- Phone number lifecycle (portability, recycling, carrier changes) does not affect the account
- Real identity never enters the system — Synapse sees the pseudonym, not the phone number
- Phonebook is a bulk-download bulletin board with no query interface — no contact list disclosure
- Same OpenID4VP infrastructure provides for EU/EEA residency attestation, with potential consequences for OTT interop under the DMA

## Stack

Two homeserver stacks, each running:

- Synapse (Matrix homeserver)
- Provisioning agent (MSC3861 OIDC provider + OpenID4VP verifier)
- Element Web (patched for phone number search via phonebook)

Shared services: a phonebook (phone → MXID mapping) and Traefik (subdomain routing, TLS termination with mkcert certificates). Federation between homeservers runs through nginx TLS sidecars with self-signed certificates on an internal Docker network.

The mock wallet runs on the host with a terminal UI for identity selection. It holds two test identities with distinct phone numbers and holder keys.

## Auth flow

When signing in to Element, the provisioning agent redirects the browser to the mock wallet via OpenID4VP. The wallet presents an SD-JWT-VC containing a carrier-signed phone number and a wallet-signed per-service pseudonym derived from the wallet's holder key and the service's client ID.

The provisioning agent verifies the credential: it checks the carrier's ES256 signature on the issuer JWT, validates each disclosure hash against the signed `_sd` array, verifies the holder's key binding JWT signature, and confirms the nonce and `sd_hash` match the authorization request. After verification, it creates a Synapse account bound to the pseudonym and writes a phonebook entry mapping the phone number to the new Matrix ID.

```
Wallet (SD-JWT-VC) → OpenID4VP → Provisioning agent (verify + provision) → Synapse (account) + Phonebook (phone → MXID)
```

The patched Element Web searches the phonebook by phone number. Once both users are provisioned, they can find each other by phone number and start a federated conversation.

See [docs/auth-flow.md](docs/auth-flow.md) for the full flow description and sequence diagram.

## Running the demo

Prerequisites: Docker, mkcert (`sudo apt install mkcert libnss3-tools`), uv.

```bash
services/scripts/start.sh     # brings up everything, starts wallet in foreground
services/scripts/teardown.sh   # tears down everything
```

### Walkthrough

1. **Provision hs1 via Wallet A** — Open [Element (hs1)](https://element-hs1.localhost/). Click *Sign in*. Select **Wallet A** (+358401234567) in the terminal.
2. **Provision hs2 via Wallet B** — Open [Element (hs2)](https://element-hs2.localhost/) in a new browser tab. Select **Wallet B** (+358501234567).
3. **Find by phone number** — In Wallet B's Element tab, click **+** to start a new DM. Type `+358401234567`. Element queries the phonebook; Wallet A's account appears. Start the conversation.
4. **Federated chat** — Switch to Wallet A's Element tab. The message from Wallet B is there. Reply. The conversation crosses homeservers via federation.

### Services

| Service | URL |
|---------|-----|
| Element (hs1) | https://element-hs1.localhost/ |
| Element (hs2) | https://element-hs2.localhost/ |
| Provisioning agent (hs1) | https://auth-hs1.localhost/ |
| Provisioning agent (hs2) | https://auth-hs2.localhost/ |
| Synapse API (hs1) | https://synapse-hs1.localhost/ |
| Synapse API (hs2) | https://synapse-hs2.localhost/ |
| Phonebook | https://phonebook.localhost/ |

All browser-facing services routed via Traefik on :443 with locally-trusted TLS (mkcert). The mock wallet runs on the host at localhost:8095.

## Identified gaps

- **Pseudonym binding via `cnf`.** This PoC uses the `cnf` claim in the issuer JWT to bind the holder's key and verify the key binding JWT. This approach has known limitations around unlinkability and holder privacy, and has been discussed in the Architecture and Reference Framework. Alternative mechanisms (e.g. self-generated verifiable pseudonyms, BBS+ signatures) have been proposed but are not yet specified.

- **No carrier attestation rulebook.** No attestation rulebook exists for carrier issuance of phone number credentials into EUDI wallets. The EU reference wallet implementation does include an MSISDN credential type (`urn:eu.europa.ec.eudi:msisdn:1`), and the GSMA has called for a rulebook governing carrier attestation into digital identity wallets, but the specification work has not been done.

- **Phonebook trust model is incomplete.** The phonebook is a write-gated bulletin board: every write must include the carrier's SD-JWT-VC issuer JWT, which the phonebook independently verifies against the carrier's public key before accepting the entry. The provisioning agent forwards the carrier JWT after its own verification, but the phonebook does not trust the provisioner — it re-verifies the carrier signature and checks that the phone number in the verified claims matches the request. Reads are bulk download (`/dump`); the IS v2 per-number lookup endpoints are retained only for Element Web compatibility. In a production design, phonebook entries should carry a three-signature envelope: carrier attesting the phone number, wallet proving pseudonym ownership (ideally via a zero-knowledge proof rather than a self-assertion), and provisioner attesting the binding. This would make entries independently verifiable by any reader, removing trust in the phonebook operator entirely. The three-signature envelope is described but not yet implemented.

## Project structure

```
src/mock-wallet/          — Mock EUDI wallet (host-side, terminal UI)
src/provisioning-agent/   — Provisioning agent (MSC3861 + OpenID4VP)
src/phonebook/            — Phone number → MXID directory
src/element-web-patched/  — Element Web with phonebook search
services/poc/             — Docker Compose stacks and configuration
services/scripts/         — Startup, teardown, key generation
```
