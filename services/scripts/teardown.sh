#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_DIR="$(cd "$SCRIPTS_DIR/../poc" && pwd)"
cd "$STACK_DIR"

echo "=== Tearing down PoC stack ==="
echo ""

echo "Stopping homeservers (hs1, hs2, postgres, federation-tls, provisioning-agent, element)..."
docker compose -f docker-compose.homeservers.yml down -v 2>/dev/null || true

echo "Stopping phonebook..."
docker compose -f docker-compose.phonebook.yml down -v 2>/dev/null || true

echo "Stopping Traefik + frontpage..."
docker compose -f docker-compose.traefik.yml down -v 2>/dev/null || true

echo "Removing Docker networks..."
docker network rm matrix-federation traefik >/dev/null 2>&1 || true

echo "Uninstalling mkcert CA..."
mkcert -uninstall >/dev/null 2>&1 || true

echo ""

# docker-volumes/ contains files created by containers running as root
if [[ -d "docker-volumes" ]]; then
  echo "About to remove docker-volumes/ (requires sudo — contains root-owned files)."
  read -rp "Continue? [y/N] " confirm
  if [[ "$confirm" =~ ^[Yy]$ ]]; then
    sudo rm -rf docker-volumes/
    echo "Removed docker-volumes/"
  else
    echo "Skipped docker-volumes/ removal."
  fi
fi

echo ""
echo "Teardown complete."
