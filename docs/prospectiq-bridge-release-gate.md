# Joint release gate - one runbook, two repository gates

RMR entry: setup -> RMR gate -> shared browser proof.
PIQ entry: setup -> PIQ gate -> shared browser proof.
A joint release requires ALL sections. This composes maintained test helpers,
not a second harness. **Not executed in Phase 5A**; do not label this composed
runbook PASS merely from historical Phase 4 results.

Use a disposable LOCAL/CI Docker daemon, never the VPS. No installed Compose
stack, .env, database, credentials or host ports. Source is git archive of approved
SHAs, excluding ignored/private files. Builds can download dependencies; tests
use network none or an internal-only Docker network. Preload postgres:16,
redis:7, nginx:1.27-alpine separately if absent. Require Bash, git/tar, sufficient
RAM/disk and Docker volume-subpath support. Never enable shell tracing.

## Setup once (Bash)

Set RMR_SOURCE / PIQ_SOURCE to local clone roots, not live deployment roots.
~~~bash
set -euo pipefail
test -d "$RMR_SOURCE/.git"
test -d "$PIQ_SOURCE/.git"
RMR_SHA=5ff29bd876fe31950b253760578e9dc26c954179
PIQ_SHA=1663e832df859348596f638707c207cc545a468c
test "$(git -C "$RMR_SOURCE" rev-parse HEAD)" = "$RMR_SHA"
test "$(git -C "$PIQ_SOURCE" rev-parse HEAD)" = "$PIQ_SHA"
git -C "$RMR_SOURCE" diff --exit-code
git -C "$RMR_SOURCE" diff --cached --exit-code
git -C "$PIQ_SOURCE" diff --exit-code
git -C "$PIQ_SOURCE" diff --cached --exit-code
GATE_DIR=$(mktemp -d -t rmr-piq-gate-XXXXXXXX)
GATE_ID=$(basename "$GATE_DIR" | tr '[:upper:]' '[:lower:]')
mkdir "$GATE_DIR/rmr" "$GATE_DIR/piq"
git -C "$RMR_SOURCE" archive "$RMR_SHA" | tar -x -C "$GATE_DIR/rmr"
git -C "$PIQ_SOURCE" archive "$PIQ_SHA" | tar -x -C "$GATE_DIR/piq"
RMR_SRC="$GATE_DIR/rmr"
PIQ_SRC="$GATE_DIR/piq"
NET="$GATE_ID-net"
PROOF="$GATE_ID-proof"
PGDATA="$GATE_ID-pgdata"
RMR_IMAGE="$GATE_ID-rmr:test"
PIQ_IMAGE="$GATE_ID-backend:test"
WORKER_IMAGE="$GATE_ID-worker:test"
FRONT_IMAGE="$GATE_ID-frontend:build"
docker build --target test -t "$RMR_IMAGE" "$RMR_SRC"
docker build -t "$PIQ_IMAGE" "$PIQ_SRC/backend"
docker build -t "$WORKER_IMAGE" "$PIQ_SRC/worker"
docker build --target build --build-arg VITE_API_BASE_URL=/api \
  --build-arg VITE_STRIPE_PUBLISHABLE_KEY= -t "$FRONT_IMAGE" "$PIQ_SRC/frontend"
docker image inspect postgres:16 >/dev/null
docker image inspect redis:7 >/dev/null
docker image inspect nginx:1.27-alpine >/dev/null
docker network create --internal --label "rmr.release-gate=$GATE_ID" "$NET"
docker volume create --label "rmr.release-gate=$GATE_ID" "$PGDATA"
docker volume create --label "rmr.release-gate=$GATE_ID" "$PROOF"
docker run -d --name "$GATE_ID-pg" --label "rmr.release-gate=$GATE_ID" \
  --network "$NET" --network-alias phase41-postgres \
  --mount "type=volume,source=$PGDATA,target=/var/lib/postgresql/data" \
  -e POSTGRES_USER=phase41_test -e POSTGRES_DB=phase41_test \
  -e POSTGRES_PASSWORD=phase1-disposable-only postgres:16
for n in $(seq 1 60); do
  if docker exec "$GATE_ID-pg" pg_isready -h 127.0.0.1 -U phase41_test -d phase41_test >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$GATE_ID-pg" pg_isready -h 127.0.0.1 -U phase41_test -d phase41_test
PG_URL=postgresql://phase41_test:phase1-disposable-only@phase41-postgres:5432/phase41_test
RMR_PG_URL=postgresql+psycopg://phase41_test:phase1-disposable-only@phase41-postgres:5432/phase41_test
~~~

The displayed password is a deliberately public disposable fixture, not a
production credential. PG tests enforce host/user/database guards. These new
volumes have no production data.

## RMR gate

~~~bash
rmr_py() {
  docker run --rm --network "$TEST_NET" --read-only --memory 1g --cpus 2 \
    --tmpfs /tmp:rw,size=512m --tmpfs /data:rw,size=128m \
    --mount "type=bind,source=$RMR_SRC,target=/app,readonly" -w /app \
    -e PYTHONDONTWRITEBYTECODE=1 -e RMR_DATA_DIR=/tmp/bridge-test \
    -e RMR_DATABASE_URL="$TEST_DB" -e RMR_PHASE41_POSTGRES_TEST_URL="$TEST_PG_URL" \
    -e RMR_AUTO_MIGRATE=false -e RMR_AUTO_SEED=false \
    -e RMR_ALLOW_DEMO_CREDENTIALS=false -e RMR_PIQ_WORKER_ENABLED=false \
    -e RMR_CB1_WORKER_ENABLED=false -e RMR_PIQ_LIVE_DISCOVERY_ENABLED=false \
    -e RMR_PIQ_LIVE_RESEARCH_ENABLED=false -e RMR_PROVIDER_MODE=mock \
    -e RMR_PAYMENT_PROVIDER=mock -e RMR_AI_MODE=safe-template \
    --entrypoint python "$RMR_IMAGE" -B "$@"
}
TEST_NET=none
TEST_PG_URL=""
TEST_DB=sqlite:////tmp/bridge-test/test.db
rmr_py -m pytest -q -p no:cacheprovider --basetemp=/tmp/pytest
TEST_NET="$NET"
TEST_DB="$RMR_PG_URL"
TEST_PG_URL="$RMR_PG_URL"
rmr_py -m pytest -q -p no:cacheprovider --basetemp=/tmp/pytest-pg \
  scripts/test_prospectiq_bridge_postgres.py \
  scripts/test_prospectiq_federation_postgres.py \
  scripts/test_prospectiq_capabilities_postgres.py \
  scripts/test_prospectiq_crm_postgres.py \
  scripts/test_prospectiq_operations_postgres.py scripts/test_release_postgres.py
~~~

Covers full native regression, contracts/federation/capability mapping, CRM
receiver/concurrency, operations/reconciliation/rotation, PG constraints/bootstrap.
Existing legacy_packaging deselections come from pyproject.toml; no new exclusions.

## PIQ gate

~~~bash
piq_node() {
  docker run --rm --network "$TEST_NET" --read-only --memory 1g --cpus 2 \
    --tmpfs /tmp:rw,size=256m \
    --mount "type=bind,source=$PIQ_SRC/backend/src,target=/app/src,readonly" \
    --mount "type=bind,source=$PIQ_SRC/backend/tests,target=/app/tests,readonly" \
    --mount "type=bind,source=$PIQ_SRC/backend/src,target=/app/backend/src,readonly" \
    --mount "type=bind,source=$PIQ_SRC/worker/src,target=/app/worker/src,readonly" \
    --mount "type=bind,source=$PIQ_SRC/frontend/src,target=/app/frontend/src,readonly" \
    --mount "type=bind,source=$PIQ_SRC/scripts,target=/app/scripts,readonly" \
    --mount "type=bind,source=$PIQ_SRC/db,target=/app/db,readonly" \
    --mount "type=bind,source=$PIQ_SRC/db,target=/db,readonly" \
    -e BRIDGE_WORKER_MODULE=file:///app/worker/src/rmrBridgeJobs.js \
    -e RMR_BRIDGE_TEST_DATABASE_URL="$PG_URL" --entrypoint node "$PIQ_IMAGE" "$@"
}
TEST_NET=none
piq_node --test scripts/test_target_profile_status.js \
  scripts/test_adaptive_research_validation_refresh.js \
  scripts/test_adaptive_research_summary.js scripts/test_adaptive_research_score_refresh.js \
  scripts/test_adaptive_research_openai.js scripts/test_adaptive_research_lead_summary.js \
  scripts/test_adaptive_research_fact_plan_observer.js scripts/test_adaptive_research_fact_planner.js \
  scripts/test_adaptive_research_attribution.js scripts/test_adaptive_research_ar2.js \
  scripts/test_adaptive_research.js tests/rmrFederation.test.js tests/rmrIntegration.test.js
TEST_NET="$NET"
piq_node --test tests/rmrIntegration.postgres.test.js tests/rmrFederation.postgres.test.js \
  tests/rmrCapabilities.postgres.test.js tests/rmrCrm.postgres.test.js \
  tests/rmrOperations.postgres.test.js
docker run --rm --network none --memory 1g --cpus 2 \
  --mount "type=volume,source=$PROOF,target=/proof" \
  -e VITE_API_BASE_URL=/api -e VITE_STRIPE_PUBLISHABLE_KEY= --entrypoint node \
  "$FRONT_IMAGE" /app/node_modules/vite/bin/vite.js build --outDir /proof/piq-dist
~~~

The OpenAI-named script tests mocked output/contract behavior, with network none.
Record pre-existing duplicate canConfirm warning separately; new failures block.

## Shared actual-browser/native/CRM/operations proof

Existing Phase 4 fixtures only. Private schemas, network aliases and mock
services; no published ports. Full proof volume contains synthetic secrets:
PIQ/worker/provider receive only its piq subpath, not RMR private material.

~~~bash
docker run --rm --network none --read-only --tmpfs /tmp:rw,size=256m \
  --mount "type=bind,source=$RMR_SRC,target=/app,readonly" \
  --mount "type=volume,source=$PROOF,target=/proof" --entrypoint python \
  "$RMR_IMAGE" -B /app/scripts/federation_operations_proof.py init
docker run -d --name "$GATE_ID-redis" --label "rmr.release-gate=$GATE_ID" \
  --network "$NET" --network-alias rmr-federation-phase4-redis redis:7
docker run -d --name "$GATE_ID-rmr" --label "rmr.release-gate=$GATE_ID" \
  --network "$NET" --network-alias rmr-federation-phase4-rmr --read-only \
  --tmpfs /tmp:rw,size=512m --mount "type=bind,source=$RMR_SRC,target=/app,readonly" \
  --mount "type=volume,source=$PROOF,target=/proof,readonly" --entrypoint python \
  "$RMR_IMAGE" -B /app/scripts/federation_operations_proof.py rmr
piq_fixture_start() {
  local name=$1
  local script=$2
  docker run -d --name "$GATE_ID-$name" --label "rmr.release-gate=$GATE_ID" \
    --network "$NET" --network-alias "rmr-federation-phase4-$name" \
    --read-only --tmpfs /tmp:rw,size=256m -w /tmp \
    --mount "type=bind,source=$PIQ_SRC/backend/src,target=/app/src,readonly" \
    --mount "type=bind,source=$PIQ_SRC/backend/tests,target=/app/tests,readonly" \
    --mount "type=bind,source=$PIQ_SRC/db,target=/db,readonly" \
    --mount "type=volume,source=$PROOF,target=/proof,volume-subpath=piq" \
    -e NODE_EXTRA_CA_CERTS=/proof/tls.crt --entrypoint node "$PIQ_IMAGE" "/app/tests/$script"
}
piq_fixture_start piq federation_operations_runtime.js
piq_fixture_start provider federation_mock_discovery.js
for n in $(seq 1 60); do
  if docker exec "$GATE_ID-piq" test -f /proof/piq-ready; then break; fi
  sleep 1
done
docker exec "$GATE_ID-piq" test -f /proof/piq-ready
docker run -d --name "$GATE_ID-worker" --label "rmr.release-gate=$GATE_ID" \
  --network "$NET" --read-only --tmpfs /tmp:rw,size=256m -w /tmp \
  --mount "type=bind,source=$PIQ_SRC/worker/src,target=/app/src,readonly" \
  --mount "type=bind,source=$PIQ_SRC/backend/tests,target=/app/tests,readonly" \
  --mount "type=volume,source=$PROOF,target=/proof,volume-subpath=piq,readonly" \
  -e NODE_EXTRA_CA_CERTS=/proof/tls.crt --entrypoint node "$WORKER_IMAGE" \
  /app/tests/federation_operations_worker.js
docker run -d --name "$GATE_ID-proxy" --label "rmr.release-gate=$GATE_ID" \
  --network "$NET" --network-alias rmr.test --network-alias piq.test \
  --mount "type=volume,source=$PROOF,target=/proof,readonly" nginx:1.27-alpine \
  nginx -c /proof/nginx.conf -g 'daemon off;'
browser_gate() {
  docker run --rm --network "$NET" --read-only --memory 1g --cpus 2 \
    --tmpfs /tmp:rw,size=512m --shm-size=256m \
    --mount "type=bind,source=$RMR_SRC,target=/app,readonly" \
    --mount "type=volume,source=$PROOF,target=/proof" --entrypoint python \
    "$RMR_IMAGE" -B "/app/scripts/$1" "$2"
}
rmr_fixture() {
  docker run --rm --network "$NET" --read-only --tmpfs /tmp:rw,size=256m \
    --mount "type=bind,source=$RMR_SRC,target=/app,readonly" \
    --mount "type=volume,source=$PROOF,target=/proof" --entrypoint python \
    "$RMR_IMAGE" -B /app/scripts/federation_operations_proof.py "$1"
}
piq_control() {
  docker run --rm --network "$NET" --read-only --tmpfs /tmp:rw,size=256m -w /tmp \
    --mount "type=bind,source=$PIQ_SRC/backend/src,target=/app/src,readonly" \
    --mount "type=bind,source=$PIQ_SRC/backend/tests,target=/app/tests,readonly" \
    --mount "type=volume,source=$PROOF,target=/proof,volume-subpath=piq" \
    -e NODE_EXTRA_CA_CERTS=/proof/tls.crt --entrypoint node "$PIQ_IMAGE" \
    /app/tests/federation_operations_control.js "$1"
}
health_ready() {
  docker exec "$GATE_ID-rmr" python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2).read()" >/dev/null 2>&1 \
  && docker exec "$GATE_ID-piq" node -e \
    "fetch('http://127.0.0.1:4000/api/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))" >/dev/null 2>&1
}
wait_ready() {
  for n in $(seq 1 60); do if health_ready; then return 0; fi; sleep 1; done
  return 1
}
wait_ready
browser_gate test_federation_workflow_browser.py ""
browser_gate test_federation_crm_browser.py ""
rmr_fixture public
browser_gate test_federation_operations_browser.py before
docker stop "$GATE_ID-rmr"
browser_gate test_federation_operations_browser.py outage
piq_control unknown
docker stop "$GATE_ID-worker" "$GATE_ID-piq"
docker restart "$GATE_ID-redis"
docker start "$GATE_ID-rmr" "$GATE_ID-piq" "$GATE_ID-worker"
wait_ready
piq_control reconcile
browser_gate test_federation_operations_browser.py after
rmr_fixture inspect
~~~

Required: native RMR/PIQ login; native PIQ two-client/generic-CRM fixture;
admin/sales/viewer capability and foreign-client denials; mock discovery/research;
one RMR Lead/receipt/event and no conversion; same Lead on repeat/reconcile;
renewal/reload, cookie/CSRF/two-tab logout, downgrade without resurrection,
outage fail-closed and same-session restart recovery. PG tests cover additional
concurrency, key rotation and failure cases.

Fixture uses development/test mode and private TLS names. It is NOT a test of
native NODE_ENV=production configuration or the actual public proxy. Those
require separate restored-environment and deployment-day checks. Do not copy
test keys, hostname overrides or TLS bypasses into production.

## Capture and safe cleanup

Any nonzero build/test/browser exit, missing expected result or unexpected egress
blocks release. Record actual counts/warnings and SHAs, not historical expected
counts. Export only sanitized phase2-browser-result.json,
phase3-browser-result.json and phase4-browser-*.json. Never export fixture.json,
private keys, browser state, SQL dumps or the complete proof volume.

Verify exact container/volume/network names and label rmr.release-gate=$GATE_ID
before deletion. Remove ONLY this newly created gate's pg/redis/rmr/piq/provider/
worker/proxy containers, PGDATA/PROOF volumes and NET. No broad globs, system
prune, installed-stack down -v or automatic production retries. Keep sanitized
results, then privately dispose of the verified generated GATE_DIR export
(not either source repository). On failure, contain only these test resources.
