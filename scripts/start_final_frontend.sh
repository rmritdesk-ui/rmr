#!/bin/sh
set -eu
# Exercise the exact production image's configuration selector in the disposable proof.
sh /docker-entrypoint.d/19-rmr-proxy.sh
exec nginx -g 'daemon off;'
