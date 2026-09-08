#!/bin/sh
set -eu
cd "$(dirname "$0")"
. ./scripts/common.sh
$COMPOSE logs --tail=200 -f app
