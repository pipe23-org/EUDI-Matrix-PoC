# services/

Orchestration layer for the PoC. Docker Compose stacks and shell scripts that
bring up two federated Matrix homeservers, a shared phonebook, and the
supporting infrastructure needed to demo wallet-based onboarding.

## Layout

### `poc/`

Docker Compose stacks and configuration templates for the demo environment.
Three compose files (Traefik, phonebook, homeservers), shared config templates
in `configs/shared/`, and generated per-instance configs in `docker-volumes/`
(gitignored). See [`poc/README.md`](poc/README.md) for the full layout.

### `scripts/`

Lifecycle management. `start.sh` is the single entry point: it runs pre-flight
checks, generates wallet keys and TLS certs and service configs if missing,
creates Docker networks, starts all stacks in order, then execs into the
host-side mock wallet TUI. `teardown.sh` reverses everything. See
[`scripts/README.md`](scripts/README.md) for per-script details.

## How it fits together

Each homeserver stack runs a provisioning agent (`src/provisioning-agent/`) as
its MSC3861 OIDC provider -- the same delegation protocol that MAS (Matrix
Authentication Service) implements. Synapse's `experimental_features.msc3861`
block points at the provisioning agent for all auth decisions: authorization,
token issuance, introspection.

The provisioning agent is the entry point for the demo flow. It accepts
wallet credentials via OpenID4VP, verifies the carrier-signed SD-JWT-VC,
provisions a Synapse account via the admin API, and writes a phonebook entry
mapping the attested phone number to the new Matrix ID.

The homeservers exist to enable the happy path: provision via wallet
credential, then chat across federation.

## Prerequisites

- Docker and Docker Compose
- `mkcert` and `libnss3-tools` (local CA for TLS)
- `uv` (Python package manager, for the mock wallet)
- Port 443 free
