#!/bin/sh
set -eu
cd "$(dirname "$0")"
. ./scripts/common.sh
$COMPOSE ps
$COMPOSE exec -T app python -m rmr_platform.cli status
