#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_DIR="$(cd "$SCRIPTS_DIR/../poc" && pwd)"

generate_instance() {
  local instance=$1
  local server_name=$2
  local auth_host=$3
  local synapse_host=$4

  # --- homeserver.yaml ---
  export SYNAPSE_SERVER_NAME="$server_name"
  export SYNAPSE_POSTGRES_HOST="${instance}-postgres"
  export SYNAPSE_AUTH_HOST="${instance}-auth"
  export AUTH_PUBLIC_BASE="https://$auth_host"
  OUTPUT_DIR="$STACK_DIR/docker-volumes/$instance/synapse"
  mkdir -p "$OUTPUT_DIR"
  envsubst < "$STACK_DIR/configs/shared/synapse/homeserver.yaml" > "$OUTPUT_DIR/homeserver.yaml"
  echo "  $instance: homeserver.yaml"

  # --- Synapse signing key (ed25519, idempotent) ---
  if [[ ! -f "$OUTPUT_DIR/signing.key" ]]; then
    SEED=$(openssl rand 32 | base64 | tr '+/' '-_' | tr -d '=\n')
    echo "ed25519 auto $SEED" > "$OUTPUT_DIR/signing.key"
    echo "  $instance: signing.key (generated)"
  fi

  # --- element/config.json ---
  export SYNAPSE_HOST="$synapse_host"
  export AUTH_HOST="$auth_host"
  export PHONEBOOK_HOST="phonebook.localhost"
  ELEMENT_DIR="$STACK_DIR/docker-volumes/$instance/element"
  mkdir -p "$ELEMENT_DIR"
  envsubst < "$STACK_DIR/configs/shared/element/config.json" > "$ELEMENT_DIR/config.json"
  echo "  $instance: element config.json"

  # --- federation-tls/nginx.conf ---
  TLS_DIR="$STACK_DIR/docker-volumes/$instance/federation-tls"
  mkdir -p "$TLS_DIR"
  export SYNAPSE_FEDERATION_HOST="${instance}-synapse"
  envsubst '${SYNAPSE_FEDERATION_HOST}' < "$STACK_DIR/configs/shared/federation-tls/nginx.conf" > "$TLS_DIR/nginx.conf"
  echo "  $instance: federation nginx.conf"

  # --- federation self-signed cert (idempotent) ---
  if [[ ! -f "$TLS_DIR/cert.pem" ]]; then
    openssl req -x509 -newkey rsa:2048 \
      -keyout "$TLS_DIR/key.pem" -out "$TLS_DIR/cert.pem" \
      -days 3650 -nodes -subj "/CN=$server_name" 2>/dev/null
    echo "  $instance: federation TLS cert (generated)"
  fi
}

generate_instance hs1 "hs1.matrix.local:8448" "auth-hs1.localhost" "synapse-hs1.localhost"
generate_instance hs2 "hs2.matrix.local:8448" "auth-hs2.localhost" "synapse-hs2.localhost"
