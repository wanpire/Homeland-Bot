#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

ENV_FILE=".env"

ask() {
  local prompt_text=$1 default_value=${2:-} input
  if [[ -n "$default_value" ]]; then
    printf '%s [%s]: ' "$prompt_text" "$default_value" >&2
  else
    printf '%s: ' "$prompt_text" >&2
  fi
  read -r input
  echo "${input:-$default_value}"
}

ask_secret() {
  local prompt_text=$1 input
  printf '%s: ' "$prompt_text" >&2
  read -rs input
  echo >&2
  echo "$input"
}

echo "=== Homeland Bot setup ===" >&2
echo >&2

if [[ -f "$ENV_FILE" ]]; then
  read -rp ".env already exists. Overwrite? [y/N]: " overwrite
  if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
    echo "Aborted. Existing .env left untouched." >&2
    exit 0
  fi
fi

echo "--- Telegram ---" >&2
BOT_TOKEN=$(ask_secret "Telegram Bot Token")
ADMIN_IDS=$(ask "Admin Telegram User ID(s), comma-separated")

echo "--- IBSng (XML-RPC, same server as AloBot, Homeland's own ISP/groups) ---" >&2
IBSNG_BASE_URL=$(ask "IBSng XML-RPC base URL, e.g. http://YOUR_HOST:1235")
IBSNG_USERNAME=$(ask "IBSng admin username" "admin")
IBSNG_PASSWORD=$(ask_secret "IBSng admin password")
IBSNG_ISP_NAME=$(ask "IBSng ISP name")
IBSNG_AUTH_REMOTEADDR=$(ask "IBSng auth_remoteaddr (must be in TRUSTED_CLIENTS if not localhost)" "127.0.0.1")

echo "--- Database (PostgreSQL) ---" >&2
POSTGRES_HOST=$(ask "PostgreSQL host" "db")
POSTGRES_PORT=$(ask "PostgreSQL port" "5432")
POSTGRES_DB=$(ask "PostgreSQL database name" "homeland")
POSTGRES_USER=$(ask "PostgreSQL user" "homeland")
POSTGRES_PASSWORD=$(ask_secret "PostgreSQL password")

echo "--- Redis ---" >&2
REDIS_HOST=$(ask "Redis host" "redis")
REDIS_PORT=$(ask "Redis port" "6379")
REDIS_DB=$(ask "Redis DB index" "0")

echo "--- App ---" >&2
ENVIRONMENT=$(ask "Environment (production/development)" "production")
LOG_LEVEL=$(ask "Log level" "INFO")
WEBHOOK_PORT=$(ask "Local port for the payment webhook server" "8090")

cat > "$ENV_FILE" <<EOF
# Telegram
BOT_TOKEN=$BOT_TOKEN
ADMIN_IDS=$ADMIN_IDS

# IBSng
IBSNG_BASE_URL=$IBSNG_BASE_URL
IBSNG_USERNAME=$IBSNG_USERNAME
IBSNG_PASSWORD=$IBSNG_PASSWORD
IBSNG_ISP_NAME=$IBSNG_ISP_NAME
IBSNG_AUTH_REMOTEADDR=$IBSNG_AUTH_REMOTEADDR

# Database
POSTGRES_HOST=$POSTGRES_HOST
POSTGRES_PORT=$POSTGRES_PORT
POSTGRES_DB=$POSTGRES_DB
POSTGRES_USER=$POSTGRES_USER
POSTGRES_PASSWORD=$POSTGRES_PASSWORD

# Redis
REDIS_HOST=$REDIS_HOST
REDIS_PORT=$REDIS_PORT
REDIS_DB=$REDIS_DB

# App
ENVIRONMENT=$ENVIRONMENT
LOG_LEVEL=$LOG_LEVEL
WEBHOOK_PORT=$WEBHOOK_PORT

# Stripe - leave blank until keys are provisioned (see docs/superpowers/specs)
STRIPE_API_KEY=
STRIPE_WEBHOOK_SECRET=

# Crypto gateway - leave blank until keys are provisioned
CRYPTO_GATEWAY_API_KEY=
CRYPTO_GATEWAY_IPN_SECRET=
CRYPTO_GATEWAY_IPN_CALLBACK_URL=
EOF

chmod 600 "$ENV_FILE"

echo >&2
echo ".env file generated." >&2
echo "Next steps:" >&2
echo "  make up       # docker compose up -d --build" >&2
echo "  make migrate  # apply database migrations" >&2
