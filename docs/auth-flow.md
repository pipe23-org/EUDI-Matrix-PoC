# Auth Flow — How a User Gets From "Sign In" to Chatting

Four actors: the **browser** (running Element Web), the **provisioning agent** (the homeserver's auth service), the **wallet** (holds the user's credentials), and **Synapse** (the Matrix homeserver). The **phonebook** appears at the end.

## The redirect chain

The user opens Element and clicks Sign In. Element doesn't know about wallets — it just knows it has an OIDC provider (the provisioning agent) and starts a standard OIDC authorization code flow with PKCE.

The provisioning agent receives the authorization request, but instead of showing a login form, it redirects the browser to the wallet. The redirect carries a `request_uri` — a URL the wallet can call back to fetch the details of what's being requested.

The wallet (running on the host with a terminal UI) receives the browser redirect. It calls back to the provisioning agent to fetch the authorization request, which says: "I need a carrier-attested phone number and a wallet-derived pseudonym." The operator selects which identity to present (Wallet A or B) in the terminal.

The wallet then builds a credential presentation: the carrier's signed attestation of the phone number, with the phone number and pseudonym selectively disclosed, plus a proof that the wallet holds the private key. It POSTs this back to the provisioning agent.

## Verification and provisioning

The provisioning agent verifies the presentation:

1. The carrier's signature on the credential is valid (the phone number attestation is authentic)
2. The disclosed claims (phone number, pseudonym) match the hashes in the signed credential (nothing was tampered with)
3. The wallet's proof binds to this specific request (not a replay)

Once verified, two things happen:

- **Synapse account** — the provisioning agent creates (or updates) a Matrix account on Synapse, using the pseudonym as the account identifier. The phone number never reaches Synapse.
- **Phonebook entry** — the provisioning agent registers the phone number → Matrix ID mapping in the phonebook, forwarding the carrier's signed attestation so the phonebook can independently verify it. This is fire-and-forget; if it fails, the login still succeeds.

## Completing the OIDC flow

The provisioning agent generates an authorization code and tells the wallet where to send the browser (back to Element's callback URL, with the code). The wallet redirects the browser there.

Element exchanges the code for tokens (access token + signed ID token) with the provisioning agent, using PKCE to prove it's the same client that started the flow. Element is now logged in.

From this point, Element talks to Synapse normally. Synapse validates each request by calling back to the provisioning agent's introspection endpoint — standard OIDC token validation.

## Discovery

A second user, provisioned on a different homeserver, opens Element and types the first user's phone number in the invite dialog. Element queries the phonebook (via the Identity Service v2 API), gets back the Matrix ID, and starts a conversation. The message crosses homeservers via federation.

## Sequence diagram

```mermaid
sequenceDiagram
    actor User
    participant Browser
    participant Element as Element Web
    participant Auth as Provisioning Agent<br/>(MSC3861 + OpenID4VP)
    participant Wallet as Mock EUDI Wallet<br/>(host TUI)
    participant Synapse
    participant PB as Phonebook

    Note over User,PB: 1. User opens Element and clicks Sign In

    User->>Browser: Open element-hs1.localhost
    Browser->>Element: Load app
    Element->>Auth: GET /.well-known/openid-configuration
    Auth-->>Element: OIDC discovery (issuer, endpoints)
    Element->>Auth: GET /authorize<br/>(client_id, redirect_uri, state,<br/>code_challenge, nonce)

    Note over Auth,Wallet: 2. Provisioning agent creates OpenID4VP request

    Auth->>Auth: Generate state, store pending request<br/>(PKCE challenge, Element redirect_uri,<br/>nonce, presentation_definition)
    Auth-->>Browser: 302 → wallet /authorize<br/>(request_uri, state)

    Note over Browser,Wallet: 3. Wallet presents credentials

    Browser->>Wallet: GET /authorize?request_uri=...&state=...
    Wallet->>Auth: GET /openid4vp/request/{state}
    Auth-->>Wallet: Authorization request<br/>(nonce, client_id, response_uri,<br/>presentation_definition)

    Note over Wallet: TUI: operator selects Wallet A or B

    Wallet->>Wallet: Derive pseudonym:<br/>SHA256(SHA256(holder_key) || client_id)
    Wallet->>Wallet: Issue SD-JWT-VC<br/>(carrier key signs, selective disclosures:<br/>msisdn + pseudonym)
    Wallet->>Wallet: Build KB-JWT<br/>(holder key signs, nonce + aud + sd_hash)

    Wallet->>Auth: POST /openid4vp/response<br/>(vp_token, state)

    Note over Auth: 4. Verification pipeline

    Auth->>Auth: Parse SD-JWT-VC:<br/>issuer_jwt ~ disclosures ~ kb_jwt
    Auth->>Auth: Verify carrier ES256 signature
    Auth->>Auth: Validate disclosure hashes<br/>against _sd array
    Auth->>Auth: Verify KB-JWT signature<br/>(cnf.jwk from issuer JWT)
    Auth->>Auth: Check nonce, aud, sd_hash
    Auth->>Auth: Extract msisdn + pseudonym

    Note over Auth,Synapse: 5. Provision Matrix account

    Auth->>Synapse: PUT /_synapse/admin/v2/users/<br/>@w-{pseudonym[:12]}:hs1.matrix.local<br/>(external_id = full pseudonym)
    Synapse-->>Auth: 200/201 (user created or exists)

    Note over Auth,PB: 6. Register in phonebook (fire-and-forget)

    Auth->>PB: POST /v1/records<br/>(phone_number, mxid,<br/>carrier_jwt for write-gate)
    PB->>PB: Verify carrier ES256 signature<br/>(independent re-verification)
    PB-->>Auth: 201 Created

    Note over Auth: 7. Complete OIDC flow

    Auth->>Auth: Generate auth code<br/>(bound to pseudonym, PKCE, nonce)
    Auth-->>Wallet: {redirect_uri: element callback + code}
    Wallet-->>Browser: 302 → Element callback

    Browser->>Element: Callback with auth code
    Element->>Auth: POST /oauth2/token<br/>(code, code_verifier)
    Auth->>Auth: Verify PKCE S256
    Auth->>Auth: Mint access_token + id_token (ES256)
    Auth-->>Element: {access_token, id_token, token_type}

    Element->>Synapse: Authenticated API calls<br/>(Bearer token)
    Synapse->>Auth: POST /oauth2/introspect<br/>(token validation)
    Auth-->>Synapse: {active: true, sub, username, scope}

    Note over User,PB: User is logged in. Account provisioned. Phone registered.
```

## What to read next

- [`src/provisioning-agent/README.md`](../src/provisioning-agent/README.md) — MSC3861 endpoints, OpenID4VP endpoints, verification pipeline
- [`src/mock-wallet/README.md`](../src/mock-wallet/README.md) — credential format, pseudonym derivation, what's mocked
- [`src/phonebook/README.md`](../src/phonebook/README.md) — write-gate mechanism, IS v2 compatibility
