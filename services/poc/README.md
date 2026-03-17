# services/poc/

Docker Compose layout for the demo environment. Three compose files, each
defining a separate stack with shared external networks.

## Compose files

### `docker-compose.traefik.yml`

Traefik v3.6 reverse proxy and a static demo frontpage (nginx).

- Listens on `:443`, terminates TLS with mkcert-generated wildcard cert.
- Routes subdomains to backend services via Docker provider labels.
- Frontpage served at `https://localhost/` with demo walkthrough and service links.

### `docker-compose.phonebook.yml`

Phone-to-MXID directory service (built from `src/phonebook/`).

- Write-gated: verifies carrier SD-JWT-VC signature before accepting entries.
- IS v2 read endpoints for Element Web compatibility; bulk `/dump` for target architecture.
- Receives carrier public key via volume mount from `docker-volumes/wallet/keys/`.
- Exposed at `phonebook.localhost` via Traefik.

### `docker-compose.homeservers.yml`

Two mirrored homeserver stacks. Each stack contains:

- **Synapse** (`matrixdotorg/synapse:v1.147.1`) -- stock image, config-only. MSC3861
  `experimental_features` block delegates all auth to the provisioning agent.
  Exposed at `synapse-hs{1,2}.localhost`.
- **Provisioning agent** (built from `src/provisioning-agent/`) -- MSC3861 OIDC
  provider and OpenID4VP verifier. Creates Synapse accounts and writes phonebook
  entries. Exposed at `auth-hs{1,2}.localhost`.
- **Element Web** (built from `src/element-web-patched/`) -- patched to detect
  phone numbers in the invite dialog and look them up via phonebook IS v2 API.
  Exposed at `element-hs{1,2}.localhost`.
- **Postgres** (`postgres:16-alpine`) -- Synapse database. Health-checked;
  Synapse waits for healthy status before starting.
- **Federation TLS sidecar** (nginx) -- terminates TLS on port 8448 with a
  self-signed cert and proxies to Synapse. Aliased as `hs{1,2}.matrix.local`
  on the federation network.

The two stacks are identical in structure, differing only in hostnames, network
names, and server names. HS2 exists to demonstrate federation.

## Network topology

| Network              | Scope                          | Members                                              |
|----------------------|--------------------------------|------------------------------------------------------|
| `traefik`            | External, all browser traffic  | Traefik, frontpage, both Synapses, both auth, both Element, phonebook |
| `matrix-federation`  | External, federation only      | Both Synapses, both federation TLS sidecars           |
| `hs1-matrix`         | Internal to HS1                | hs1-synapse, hs1-auth, hs1-postgres                  |
| `hs2-matrix`         | Internal to HS2                | hs2-synapse, hs2-auth, hs2-postgres                  |

External networks (`traefik`, `matrix-federation`) are created by `scripts/start.sh`
before any compose stack starts. Internal networks are defined per-compose-file.

## Configuration

Shared templates live in `configs/shared/`:

- `synapse/homeserver.yaml` -- Synapse config with `${VARIABLE}` placeholders for
  server name, Postgres host, and MSC3861 issuer endpoints.
- `element/config.json` -- Element Web config with placeholders for homeserver,
  auth issuer, and phonebook URLs.
- `federation-tls/nginx.conf` -- nginx reverse proxy config with Synapse host placeholder.
- `postgres/init-databases.sh` -- creates the `synapse` database on first run.
- `traefik/traefik.yml`, `traefik/dynamic.yml` -- static Traefik config and TLS cert paths.
- `demo-frontpage/index.html` -- landing page with auth flow explanation and demo walkthrough.

`scripts/generate-configs.sh` runs `envsubst` against these templates to produce
per-instance configs in `docker-volumes/hs{1,2}/`. It also generates Synapse
signing keys and federation TLS certs (self-signed, idempotent).

## Generated artifacts (gitignored)

`docker-volumes/` contains all generated and runtime files:

- `traefik/cert.pem`, `traefik/key.pem` -- mkcert TLS cert
- `wallet/keys/` -- EC P-256 keypairs (carrier + two holders)
- `hs{1,2}/synapse/` -- homeserver.yaml, signing.key
- `hs{1,2}/element/` -- config.json
- `hs{1,2}/federation-tls/` -- nginx.conf, self-signed cert + key
- `hs{1,2}/auth-data/` -- provisioning agent runtime data

All demo credentials (`homeserver-secret`, `pw`, `synapse-client-secret`,
`matrixrocks` pepper) are marked with `# PoC demo credential` comments in the
compose files and templates.
