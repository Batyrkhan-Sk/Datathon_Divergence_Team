#!/usr/bin/env bash
# Expose the local service on a FIXED public URL via ngrok (free static dev domain).
# Needs NGROK_AUTHTOKEN and NGROK_DOMAIN in .env (project root). No root needed.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
BIN=deploy/ngrok
if [ ! -x "$BIN" ]; then
  curl -sL -o deploy/ngrok.tgz https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
  tar -xzf deploy/ngrok.tgz -C deploy && rm deploy/ngrok.tgz
fi
export NGROK_CONFIG="$PWD/deploy/ngrok.yml"   # keep ngrok's config inside the project folder
[ -f "$NGROK_CONFIG" ] || printf 'version: "3"\nagent:\n  authtoken: %s\n' "$NGROK_AUTHTOKEN" > "$NGROK_CONFIG"
exec "$BIN" http "${PORT:-8000}" --url "https://$NGROK_DOMAIN" --config "$NGROK_CONFIG" --log stdout
