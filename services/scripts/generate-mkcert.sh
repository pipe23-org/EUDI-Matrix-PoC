#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_DIR="$(cd "$SCRIPTS_DIR/../poc" && pwd)"

command -v mkcert >/dev/null 2>&1 || {
  echo "Error: mkcert not found. Install with: sudo apt install mkcert libnss3-tools" >&2
  exit 1
}

TRAEFIK_DIR="$STACK_DIR/docker-volumes/traefik"
mkdir -p "$TRAEFIK_DIR"

mkcert -install 2>&1 | sed 's/^/  /'

mkcert -cert-file "$TRAEFIK_DIR/cert.pem" -key-file "$TRAEFIK_DIR/key.pem" \
  localhost \
  synapse-hs1.localhost auth-hs1.localhost element-hs1.localhost \
  synapse-hs2.localhost auth-hs2.localhost element-hs2.localhost \
  phonebook.localhost 2>&1 | sed 's/^/  /'
