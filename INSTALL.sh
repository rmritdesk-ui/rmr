#!/bin/sh
set -eu
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker was not found. Install Docker Engine/Desktop with Compose and rerun this installer." >&2
  exit 1
fi
. ./scripts/common.sh

profile="${1:-empty}"
case "$profile" in
  demo|empty) ;;
  *) echo "Usage: ./INSTALL.sh [demo|empty]" >&2; exit 2 ;;
esac

mkdir -p data/training data/backups
if [ ! -f .env ]; then
  cp .env.example .env
fi

random_hex() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 48
  else od -An -N48 -tx1 /dev/urandom | tr -d ' \n'
  fi
}
replace_env() {
  key="$1"; value="$2"
  if grep -q "^${key}=" .env; then
    sed -i.bak "s#^${key}=.*#${key}=${value}#" .env && rm -f .env.bak
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

if grep -q '^RMR_SECRET_KEY=REPLACE_BY_INSTALLER$' .env; then replace_env RMR_SECRET_KEY "$(random_hex)"; fi
if grep -q '^RMR_SETUP_TOKEN=REPLACE_BY_INSTALLER$' .env; then replace_env RMR_SETUP_TOKEN "$(random_hex)"; fi
host_uid=$(id -u)
host_gid=$(id -g)
if [ "$host_uid" -eq 0 ]; then
  host_uid=10001
  host_gid=10001
  chown -R 10001:10001 data
fi
replace_env RMR_CONTAINER_UID "$host_uid"
replace_env RMR_CONTAINER_GID "$host_gid"
replace_env RMR_INSTALL_PROFILE "$profile"
replace_env RMR_APP_VERSION "5.4.1-four-workspace-themes-po1"
if [ "$profile" = "demo" ]; then
  replace_env RMR_AUTO_SEED true
  replace_env RMR_ALLOW_DEMO_CREDENTIALS true
else
  replace_env RMR_AUTO_SEED false
  replace_env RMR_ALLOW_DEMO_CREDENTIALS false
fi
chmod 600 .env 2>/dev/null || true

# shellcheck disable=SC2046
export $(grep -E '^(RMR_PUBLIC_PORT|RMR_APP_VERSION|RMR_IMAGE_REPOSITORY)=' .env | xargs)

echo "Building the certified RMR Platform application image..."
$COMPOSE build

echo "Starting RMR Platform..."
$COMPOSE up -d

if ! health_check 75; then
  echo "Installation did not pass the health check." >&2
  $COMPOSE ps >&2 || true
  $COMPOSE logs --tail=150 app >&2 || true
  exit 1
fi

$COMPOSE exec -T app python -m rmr_platform.cli status > data/INSTALLATION-STATUS.json
chmod 600 data/INSTALLATION-STATUS.json 2>/dev/null || true

printf '\nRMR Platform installation completed successfully.\n'
printf 'Open: http://localhost:%s\n' "${RMR_PUBLIC_PORT:-8080}"
if [ "$profile" = "demo" ]; then
  printf 'Demo RMR Owner: dave@rmr.local / RMR-Owner-2026!\n'
  printf 'Demo Step2 Admin: hasan@step2.local / Step2-Admin-2026!\n'
  printf 'Change or disable demo credentials before any real customer use.\n'
else
  token=$(grep '^RMR_SETUP_TOKEN=' .env | cut -d= -f2-)
  cat > data/INITIAL-SETUP.txt <<EOF
RMR Platform initial setup
URL: http://localhost:${RMR_PUBLIC_PORT:-8080}
Setup token: ${token}
Use this token once in the browser setup screen. The application removes this file after successful setup.
EOF
  chmod 600 data/INITIAL-SETUP.txt 2>/dev/null || true
  printf 'Open the URL and complete first-run setup using data/INITIAL-SETUP.txt.\n'
fi
