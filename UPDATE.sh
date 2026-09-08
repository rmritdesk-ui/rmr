#!/bin/sh
set -eu
cd "$(dirname "$0")"
. ./scripts/common.sh
[ -f .env ] && set -a && . ./.env && set +a
$COMPOSE exec -T app python -m rmr_platform.cli backup || true
$COMPOSE build
$COMPOSE run --rm app python -m rmr_platform.cli migrate
$COMPOSE up -d
if ! health_check 75; then
  echo "Update health validation failed. Use ROLLBACK.sh with the prior image version and a backup." >&2
  exit 1
fi
echo "Update completed and health validation passed."
