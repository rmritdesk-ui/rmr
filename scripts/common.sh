#!/bin/sh
set -eu
COMPOSE=""
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "Docker Compose was not found. Install Docker Engine/Desktop with Compose and retry." >&2
  exit 1
fi
export COMPOSE

rmr_env_value() {
  key=$1
  default_value=${2:-}
  if [ -f .env ]; then
    value=$(grep -E "^${key}=" .env | head -n 1 | cut -d= -f2- || true)
    if [ -n "$value" ]; then printf '%s' "$value"; return 0; fi
  fi
  printf '%s' "$default_value"
}

health_check() {
  attempts=${1:-120}
  port=$(rmr_env_value RMR_PUBLIC_PORT 8080)
  expected=$(rmr_env_value RMR_APP_VERSION '')
  count=1
  while [ "$count" -le "$attempts" ]; do
    cid=$($COMPOSE ps -a -q app 2>/dev/null | head -n 1 || true)
    if [ -n "$cid" ]; then
      state=$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || true)
      docker_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || true)
      if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
        return 1
      fi
      if [ "$state" = "running" ]; then
        host_json=''
        if command -v curl >/dev/null 2>&1; then
          host_json=$(curl -fsS --max-time 5 "http://127.0.0.1:${port}/api/health" 2>/dev/null || true)
        elif command -v wget >/dev/null 2>&1; then
          host_json=$(wget -qO- --timeout=5 "http://127.0.0.1:${port}/api/health" 2>/dev/null || true)
        fi
        internal_json=$($COMPOSE exec -T app python -c "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5))))" 2>/dev/null || true)
        if [ -n "$host_json" ] && [ -n "$internal_json" ]; then
          if python3 - "$host_json" "$internal_json" "$expected" "$docker_health" <<'PY'
import json,sys
try:
    host=json.loads(sys.argv[1]); internal=json.loads(sys.argv[2])
    expected=sys.argv[3]; docker_health=sys.argv[4]
    ok=(host.get('status')=='healthy' and internal.get('status')=='healthy')
    def comparable(value):
        value=(value or '').strip()
        return '5.0.0-rc1' if value in {'5.0.0-rc1','5.0.0-rc.1'} else value
    if expected:
        hv=comparable(host.get('version')); iv=comparable(internal.get('version')); ev=comparable(expected)
        ok=ok and hv==ev and iv==ev and hv==iv
    ok=ok and docker_health in {'healthy','none'}
    raise SystemExit(0 if ok else 1)
except Exception:
    raise SystemExit(1)
PY
          then
            return 0
          fi
        fi
      fi
    fi
    if [ $((count % 5)) -eq 1 ]; then
      echo "Waiting for RMR Platform readiness: attempt ${count}/${attempts}..."
    fi
    sleep 2
    count=$((count + 1))
  done
  return 1
}
