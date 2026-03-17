#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_DIR="$(cd "$SCRIPTS_DIR/../poc" && pwd)"

KEYS_DIR="$STACK_DIR/docker-volumes/wallet/keys"
mkdir -p "$KEYS_DIR"

docker run --rm -v "$KEYS_DIR:/out" ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
  sh -c 'uv pip install --system -q jwcrypto && python3 -W ignore::DeprecationWarning -c "
from jwcrypto import jwk
import secrets, json

def gen_key(name):
    k = jwk.JWK.generate(kty=\"EC\", crv=\"P-256\", kid=secrets.token_hex(8))
    return k

carrier = gen_key(\"carrier\")
open(\"/out/carrier-key.jwk.json\", \"w\").write(carrier.export())
open(\"/out/carrier-public.jwk.json\", \"w\").write(carrier.export_public())
print(f\"  Carrier keypair: kid={carrier.key_id}\")

holder_a = gen_key(\"holder-a\")
open(\"/out/holder-a-key.jwk.json\", \"w\").write(holder_a.export())
print(f\"  Holder A:        kid={holder_a.key_id}\")

holder_b = gen_key(\"holder-b\")
open(\"/out/holder-b-key.jwk.json\", \"w\").write(holder_b.export())
print(f\"  Holder B:        kid={holder_b.key_id}\")
"'
