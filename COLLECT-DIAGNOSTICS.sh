#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p data/diagnostics
stamp=$(date -u +%Y%m%d-%H%M%S)
out="data/diagnostics/manual-diagnostic-${stamp}.txt"
{
  echo "RMR PLATFORM DEPLOYMENT DIAGNOSTIC"
  echo "Generated UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Install path: $(pwd)"
  echo
  echo "SAFE ENVIRONMENT SUMMARY (secrets omitted)"
  if [ -f .env ]; then
    grep -E '^(RMR_APP_VERSION|RMR_IMAGE_REPOSITORY|RMR_PUBLIC_PORT|RMR_ENVIRONMENT|RMR_BASE_URL|RMR_INSTALL_PROFILE|RMR_AUTO_MIGRATE|RMR_AUTO_SEED|RMR_PAYMENT_PROVIDER|RMR_CONTAINER_UID|RMR_CONTAINER_GID)=' .env || true
  fi
  echo
  echo "DOCKER VERSION"
  docker version 2>&1 || true
  echo
  echo "DOCKER COMPOSE VERSION"
  docker compose version 2>&1 || true
  echo
  echo "DOCKER COMPOSE PS -A"
  docker compose ps -a 2>&1 || true
  echo
  echo "APPLICATION STATUS"
  docker compose exec -T app python -m rmr_platform.cli status 2>&1 || true
  echo
  echo "APPLICATION LOGS (last 400 lines)"
  docker compose logs --no-color --timestamps --tail=400 app 2>&1 || true
} > "$out"
echo "Diagnostic file created: $(pwd)/$out"
