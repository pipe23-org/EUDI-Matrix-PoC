#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_DIR="$(cd "$SCRIPTS_DIR/../poc" && pwd)"
cd "$STACK_DIR"

# --- Pre-flight checks ---

if ss -tlnp 2>/dev/null | grep -q ':443 ' || lsof -iTCP:443 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Error: port 443 is already in use." >&2
  echo "  Another stack running? Try: services/scripts/teardown.sh" >&2
  exit 1
fi

command -v mkcert >/dev/null 2>&1 || {
  echo "Error: mkcert not found. Install with: sudo apt install mkcert libnss3-tools" >&2
  exit 1
}

# --- Generate keys and certificates ---

echo "=== Generating keys and certificates ==="
echo ""

WALLET_KEYS_DIR="$STACK_DIR/docker-volumes/wallet/keys"
if [[ ! -f "$WALLET_KEYS_DIR/carrier-public.jwk.json" ]] || \
   [[ ! -f "$WALLET_KEYS_DIR/carrier-key.jwk.json" ]] || \
   [[ ! -f "$WALLET_KEYS_DIR/holder-a-key.jwk.json" ]] || \
   [[ ! -f "$WALLET_KEYS_DIR/holder-b-key.jwk.json" ]]; then
  echo "Wallet keys:"
  "$SCRIPTS_DIR/generate-wallet-keys.sh"
else
  echo "Wallet keys:       ok"
fi

if [[ ! -f "$STACK_DIR/docker-volumes/traefik/cert.pem" ]]; then
  echo "TLS certificate:"
  "$SCRIPTS_DIR/generate-mkcert.sh"
else
  echo "TLS certificate:   ok"
fi

if [[ ! -f "$STACK_DIR/docker-volumes/hs1/synapse/homeserver.yaml" ]] || \
   [[ ! -f "$STACK_DIR/docker-volumes/hs2/synapse/homeserver.yaml" ]]; then
  echo "Service configs:"
  "$SCRIPTS_DIR/generate-configs.sh"
else
  echo "Service configs:   ok"
fi

echo ""

# --- Docker networks ---

echo "=== Creating Docker networks ==="
docker network create matrix-federation 2>/dev/null && echo "  matrix-federation: created" || echo "  matrix-federation: exists"
docker network create traefik 2>/dev/null && echo "  traefik: created" || echo "  traefik: exists"
echo ""

# --- Docker services ---

echo "=== Starting Traefik + frontpage ==="
docker compose -f docker-compose.traefik.yml up -d
echo ""

echo "=== Starting phonebook ==="
docker compose -f docker-compose.phonebook.yml up -d
echo ""

echo "=== Starting homeservers (hs1 + hs2) ==="
docker compose -f docker-compose.homeservers.yml up -d --build
echo ""

echo "=== Docker services ready ==="
echo "  Demo:     https://localhost/"
echo "  Auth HS1: https://auth-hs1.localhost/"
echo "  Auth HS2: https://auth-hs2.localhost/"
echo ""

# --- Mock wallet (runs on host, needs terminal for TUI) ---

WALLET_DIR="$(cd "$SCRIPTS_DIR/../../src/mock-wallet" && pwd)"
echo "=== Starting mock wallet ==="
echo "  Directory: $WALLET_DIR"
echo "  Listening: http://localhost:8095"
echo ""
cd "$WALLET_DIR"
exec uv run uvicorn wallet:app --host 0.0.0.0 --port 8095
