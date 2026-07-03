#!/usr/bin/env bash
# Seed a demo account + channel against a running local api (default :8080;
# override with HTTP_PORT). Idempotent-ish: re-running logs in instead of
# re-registering. Demo credentials are for LOCAL DEVELOPMENT ONLY.
set -euo pipefail

API="http://localhost:${HTTP_PORT:-8080}/api/v1"
EMAIL="demo@vidra.local"
USERNAME="demo"
PASSWORD="demo-password-123"

echo "Seeding against ${API} ..."

register() {
  curl -sf -X POST "${API}/auth/register" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${USERNAME}\",\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}"
}

login() {
  curl -sf -X POST "${API}/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}"
}

AUTH_JSON=$(register 2>/dev/null || login)
TOKEN=$(printf '%s' "$AUTH_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')

# Create the demo channel if it doesn't exist yet.
if ! curl -sf "${API}/channels/demo" >/dev/null 2>&1; then
  curl -sf -X POST "${API}/channels" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' \
    -d '{"handle":"demo","display_name":"Demo Channel","description":"Seeded local demo channel"}' >/dev/null
  echo "Created channel @demo"
else
  echo "Channel @demo already exists"
fi

echo "Done. Sign in with ${EMAIL} / ${PASSWORD}"
