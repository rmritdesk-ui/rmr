#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then echo "Usage: ./RESTORE.sh data/backups/<backup>.tar.gz" >&2; exit 2; fi
cd "$(dirname "$0")"
. ./scripts/common.sh
backup="$1"
case "$backup" in
  data/backups/*) container_path="/data/backups/$(basename "$backup")" ;;
  *) echo "Copy the backup into data/backups and pass that path." >&2; exit 2 ;;
esac
$COMPOSE stop app
$COMPOSE run --rm app python -m rmr_platform.cli restore "$container_path"
$COMPOSE up -d
if ! health_check 60; then echo "Restore completed but health validation failed." >&2; exit 1; fi
echo "Restore and health validation completed."
