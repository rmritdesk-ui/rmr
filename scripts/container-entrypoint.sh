#!/bin/sh
set -eu
# Schema initialization belongs exclusively to the explicit migration command
# or the application's RMR_AUTO_MIGRATE-controlled lifespan. No DDL on entry.
exec "$@"
