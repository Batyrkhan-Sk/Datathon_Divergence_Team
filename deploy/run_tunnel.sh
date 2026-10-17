#!/usr/bin/env bash
# Expose the local service on a public HTTPS URL via Cloudflare Tunnel (no root needed).
# Quick tunnel: prints a random https://*.trycloudflare.com URL (changes on restart).
# For a stable URL use a named tunnel: cloudflared tunnel login / create / route dns.
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=deploy/cloudflared
if [ ! -x "$BIN" ]; then
  curl -sL -o "$BIN" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  chmod +x "$BIN"
fi
exec "$BIN" tunnel --no-autoupdate --url "http://localhost:${PORT:-8000}"
