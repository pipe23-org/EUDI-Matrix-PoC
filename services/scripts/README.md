# services/scripts/

Lifecycle scripts for the PoC stack. All scripts resolve paths relative to
their own location, so they can be called from anywhere.

## Scripts

### `start.sh`

Single entry point for the demo. Runs the full lifecycle:

1. Pre-flight checks: port 443 free, `mkcert` installed.
2. Generate wallet keys (EC P-256 via Docker), install mkcert local CA and
   generate TLS certs, and produce per-instance service configs -- each step
   calls its respective generate script. Idempotent: skips each step if
   artifacts already exist.
3. Create external Docker networks (`traefik`, `matrix-federation`).
4. Start compose stacks in order: Traefik, phonebook, homeservers.
5. Exec into the mock wallet (`src/mock-wallet/`) via `uv run uvicorn` on
   `localhost:8095`. The wallet runs on the host (not in Docker) because it
   needs terminal access for its TUI identity selector.

The script `exec`s into the wallet process, so stopping it (Ctrl-C) stops the
wallet but leaves the Docker stacks running.

### `teardown.sh`

Reverse of `start.sh`:

1. Stop all three compose stacks with `-v` (removes named volumes).
2. Remove external Docker networks.
3. Uninstall the mkcert local CA.
4. Prompt to remove `docker-volumes/` (requires sudo -- contains root-owned
   files created by containers).

### `generate-wallet-keys.sh`

Generates EC P-256 keypairs for the mock wallet using `jwcrypto` inside a
disposable Docker container. Produces four files in
`docker-volumes/wallet/keys/`:

- `carrier-key.jwk.json` / `carrier-public.jwk.json` -- carrier signing keypair
  (public key shared with phonebook and provisioning agents for signature
  verification).
- `holder-a-key.jwk.json` / `holder-b-key.jwk.json` -- private keys for the
  two test wallet identities.

### `generate-mkcert.sh`

Installs a local CA via `mkcert -install` and generates a TLS certificate
covering all `*.localhost` subdomains used by the stack. Certificate written
to `docker-volumes/traefik/cert.pem` and `key.pem`.

### `generate-configs.sh`

Generates per-instance service configs from shared templates in
`poc/configs/shared/` via `envsubst`. For each homeserver instance (hs1, hs2):

- Synapse `homeserver.yaml` with server name, Postgres host, and MSC3861 issuer
  endpoints substituted.
- Element Web `config.json` with homeserver, auth, and phonebook URLs.
- Federation TLS nginx config with upstream Synapse hostname.
- Synapse ed25519 signing key (random, generated once).
- Federation self-signed TLS certificate (generated once).

Output goes to `docker-volumes/hs{1,2}/`.
