#!/usr/bin/env bash
# Serve the library over HTTP so YouTube allows the embedded 30-second player.
cd "$(dirname "$0")"
PORT="${1:-8000}"
echo "Set-Piece Vault: http://localhost:${PORT}"
exec python3 -m http.server "$PORT" --bind 127.0.0.1
