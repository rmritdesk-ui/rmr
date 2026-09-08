#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: ./UPGRADE-FROM-V5.0.sh /full/path/to/RMR-Platform-v5.0-installation" >&2
  exit 2
fi

NEW_INSTALL=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OLD_INSTALL=$(CDPATH= cd -- "$1" && pwd)
RUN_ID=$(date -u +%Y%m%d-%H%M%S)
DIAG_DIR="$NEW_INSTALL/data/diagnostics"
mkdir -p "$DIAG_DIR"

if [ "$OLD_INSTALL" = "$NEW_INSTALL" ]; then
  echo "The existing v5.0 folder must be different from this v5.1 Commercial Candidate release folder." >&2
  exit 1
fi
[ -f "$OLD_INSTALL/.env" ] || { echo "The v5.0 .env file was not found." >&2; exit 1; }
[ -d "$OLD_INSTALL/data" ] || { echo "The v5.0 data folder was not found." >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker was not found." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker engine is not running." >&2; exit 1; }

set_env() {
  key=$1
  value=$2
  file="$NEW_INSTALL/.env"
  if grep -q "^${key}=" "$file"; then
    tmp="${file}.tmp.$$"
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k {$0=k"="v} {print}' "$file" > "$tmp"
    mv "$tmp" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

collect_new_diag() {
  reason=$1
  out="$DIAG_DIR/upgrade-v51rc3-${RUN_ID}.txt"
  {
    echo "RMR PLATFORM v5.1 Commercial Candidate UPGRADE DIAGNOSTIC"
    echo "Generated UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "Reason: $reason"
    echo
    (cd "$NEW_INSTALL" && ./COLLECT-DIAGNOSTICS.sh) || true
  } > "$out" 2>&1
  echo "$out"
}

OLD_STOPPED=0
rollback_old() {
  echo "Stopping the unsuccessful RC3 attempt and restarting the untouched v5.0 installation..." >&2
  (cd "$NEW_INSTALL" && docker compose down >/dev/null 2>&1 || true)
  (cd "$OLD_INSTALL" && docker compose up -d)
  if (cd "$OLD_INSTALL" && . "$NEW_INSTALL/scripts/common.sh" && [ -f .env ] && set -a && . ./.env && set +a && health_check 90); then
    echo "The previous v5.0 installation is running and healthy." >&2
  else
    echo "The previous v5.0 installation restarted but did not pass the health gate." >&2
  fi
}

on_exit() {
  code=$?
  if [ "$code" -ne 0 ] && [ "$OLD_STOPPED" -eq 1 ]; then
    rollback_old
  fi
  exit "$code"
}
trap on_exit EXIT INT TERM

# Use the RC3 readiness logic to ensure the source installation is healthy.
(
  cd "$OLD_INSTALL"
  . "$NEW_INSTALL/scripts/common.sh"
  [ -f .env ] && set -a && . ./.env && set +a
  health_check 45
) || { echo "The existing v5.0 installation is not healthy enough to upgrade safely." >&2; exit 1; }

echo "Creating a v5.0 safety backup..."
(
  cd "$OLD_INSTALL"
  docker compose exec -T app python -m rmr_platform.cli backup
  docker compose down
)
OLD_STOPPED=1

echo "Copying v5.0 environment and persistent data into the separate RC3 folder..."
cp "$OLD_INSTALL/.env" "$NEW_INSTALL/.env"
mkdir -p "$NEW_INSTALL/data"
find "$NEW_INSTALL/data" -mindepth 1 -maxdepth 1 ! -name diagnostics -exec rm -rf {} +
cp -a "$OLD_INSTALL/data/." "$NEW_INSTALL/data/"
mkdir -p "$DIAG_DIR"
set_env RMR_APP_VERSION 5.4.1-four-workspace-themes-po1

cd "$NEW_INSTALL"
echo "Building RMR Platform v5.1 Commercial Candidate..."
docker compose build
echo "Applying additive database migrations..."
docker compose run --rm --entrypoint python app -m rmr_platform.cli migrate
echo "Starting RMR Platform v5.1 Commercial Candidate..."
docker compose up -d

. ./scripts/common.sh
[ -f .env ] && set -a && . ./.env && set +a
if ! health_check 120; then
  diag=$(collect_new_diag "RC3 did not become ready before the bounded health deadline.")
  echo "RMR Platform v5.1 Commercial Candidate did not pass the health gate." >&2
  echo "Diagnostic file: $diag" >&2
  exit 1
fi

docker compose exec -T app python -m rmr_platform.cli status
printf '{\n  "release": "5.4.1-four-workspace-themes-po1",\n  "status": "success",\n  "completed_utc": "%s",\n  "existing_v5_path": "%s",\n  "rc3_path": "%s"\n}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$OLD_INSTALL" "$NEW_INSTALL" > data/LAST-UPGRADE-RESULT.json

echo "UPGRADE COMPLETED SUCCESSFULLY"
echo "RMR Platform v5.1 Commercial Candidate is healthy and ready. The original v5.0 folder was not overwritten."
OLD_STOPPED=0
trap - EXIT INT TERM
