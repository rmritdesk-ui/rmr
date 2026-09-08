#!/bin/sh
set -eu
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "Usage: ./ROLLBACK.sh <prior-app-version> [data/backups/backup.tar.gz]" >&2
  exit 2
fi
cd "$(dirname "$0")"
. ./scripts/common.sh
prior="$1"
if ! docker image inspect "${RMR_IMAGE_REPOSITORY:-rmr-platform}:${prior}" >/dev/null 2>&1; then
  echo "Prior image ${RMR_IMAGE_REPOSITORY:-rmr-platform}:${prior} is not available locally." >&2
  exit 1
fi
if grep -q '^RMR_APP_VERSION=' .env; then
  sed -i.bak "s/^RMR_APP_VERSION=.*/RMR_APP_VERSION=${prior}/" .env && rm -f .env.bak
else
  printf 'RMR_APP_VERSION=%s\n' "$prior" >> .env
fi
if [ "$#" -eq 2 ]; then
  ./RESTORE.sh "$2"
else
  $COMPOSE up -d --no-build
fi
if ! health_check 75; then echo "Rollback health validation failed." >&2; exit 1; fi
echo "Rollback completed and health validation passed."
