#!/bin/sh
set -eu
cd "$(dirname "$0")"
. ./scripts/common.sh
[ -f .env ] || { echo "Run INSTALL.sh first." >&2; exit 1; }
$COMPOSE up -d
if ! health_check 60; then echo "RMR Platform did not become healthy." >&2; exit 1; fi
echo "RMR Platform is running."
