#!/bin/sh
set -eu
cd "$(dirname "$0")"
. ./scripts/common.sh
[ -f .env ] && set -a && . ./.env && set +a
if health_check 120; then
  $COMPOSE exec -T app python -m rmr_platform.cli status
  echo "RMR Platform health check passed."
else
  echo "RMR Platform health check failed." >&2
  ./COLLECT-DIAGNOSTICS.sh >&2 || true
  exit 1
fi
