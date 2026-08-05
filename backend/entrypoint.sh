#!/bin/sh
set -eu

if [ -n "${KALSHI_PRIVATE_KEY_B64:-}" ]; then
  printf '%s' "$KALSHI_PRIVATE_KEY_B64" | base64 -d > /app/arb.pem
  chmod 600 /app/arb.pem
fi

exec uv run main.py
