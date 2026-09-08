#!/bin/sh
set -eu
cd "$(dirname "$0")"
. ./scripts/common.sh
$COMPOSE stop
echo "RMR Platform stopped."
