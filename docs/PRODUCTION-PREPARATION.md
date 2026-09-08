# Production preparation (not deployment approval)

**Current VPS update:** use [CPANEL-PRODUCTION-DEPLOYMENT.md](CPANEL-PRODUCTION-DEPLOYMENT.md)
and docker-compose.production.yml. The inspected VPS uses cPanel/Apache on 80/443
and RMR loopback port 18100. The earlier generic Nginx/port-selection guidance
below is historical, not applicable to this VPS. A production Compose definition
now exists; no standalone Nginx service should be installed.

GitHub → separate VPS checkout → dedicated PostgreSQL 16 → RMR Docker → existing
Nginx/reverse proxy → HTTPS. Standalone ProspectIQ is never part of this chain.

## Repository/package boundary

Maintain application source, public/templates/static assets, dependency manifests,
Dockerfile, maintained scripts/tests/QA fixtures, docs and sanitized env examples.
Populated env files, data/, runtime-data/, product-owner-data*/, databases/backups,
evidence/, generated QA output, control archives and private demo credentials stay
local and ignored. No local data is deleted. Historical QA that replays sealed
artifacts needs separately retained private archives, not production runtime data.
The Docker context is an explicit input allowlist; QA runs in the verification
stage and does not enter the final runtime. Existing Compose files/PO launchers
remain local-only. Do not use the legacy installer as the production procedure.

## Controlled bootstrap

Create a dedicated RMR PostgreSQL 16 database/user/volume/network, never reusing
another application's resources. Build/tag the runtime image, provision private
env settings and invoke the image on that network with its command replaced by:

```sh
python -m rmr_platform.cli migrate
```

This creates core/PIQ schemas through 005.008.000-piq-profile-collection, CB1 schema
and its 005.002.000-commercial-correction-build-1 ledger, commercial metadata and
governed service/cost-category references. It creates no demo users or tenants.
Run one migrator at a time. Verify rerun/idempotency and then start the application
with RMR_AUTO_MIGRATE=false. Imports and status/health do no DDL; an incomplete
bootstrap fails startup with the explicit migration command in its error.
RMR_AUTO_MIGRATE=true retains the same approved automatic bootstrap for local use.

## Isolated PostgreSQL tests

Use a NEW disposable PostgreSQL 16 container on a NEW Docker --internal network,
without published ports and with temporary storage. Give it alias phase41-postgres
and test-only database/user phase41_test. Supply its private postgresql+psycopg URL
as RMR_PHASE41_POSTGRES_TEST_URL. Tests assert that exact hostname/database/user
before creating unique schemas. Set RMR_DATABASE_URL to the disposable PostgreSQL
instance too, so imports do not configure SQLite-specific engine events.
No populated local .env or installed database may be mounted. Keep live flags and
workers OFF and use /tmp application data. Run in the Docker test image:

```sh
python -m pytest scripts/test_piq_phase41_postgres.py scripts/test_piq_phase5_postgres.py scripts/test_piq_workflow_postgres.py scripts/test_release_postgres.py -q -p no:cacheprovider
```

Remove only the newly created disposable containers/network afterward. General
backend and browser suites run with --network none.

## Configuration and remaining deployment gates

Replace every placeholder in .env.example with privately provisioned values.
Production requires RMR_ENVIRONMENT=production, RMR_INSTALL_PROFILE=empty,
RMR_AUTO_SEED=false, RMR_ALLOW_DEMO_CREDENTIALS=false,
RMR_LOCAL_RECOVERY_MODE=false and RMR_COOKIE_SECURE=true. Unsafe demo overrides
are rejected. Preserve signing/encryption keys and remove the setup token after
creating the real owner. Never seed demo accounts into the production database.

Live Google discovery, OpenAI research and the PIQ worker are separate opt-ins.
Approve limits first: template references one discovery query, up to 50 retained
results/100 candidates, $0.05 research cap and one worker attempt. These settings
are not authorization to spend; more retries require recalculating the research
reservation bound. Configure transactional SMTP for invitations/password resets.
Mock payment and optional integrations must not be advertised as live features.

A dedicated production Compose file is still required in a separately authorized
task: versioned image, non-root user, independent volumes/network, explicit
migration job, DB readiness, resource/health/restart/log limits, no source mounts.
Production needs outbound HTTPS/DNS for authorized provider/evidence fetches;
only disposable testing uses a fully isolated network.

## Proxy, persistence and acceptance

Inspect the actual VPS services/proxy/ports first; do not assume any host port is
free. Keep container port 8000. For host Nginx, publish only
127.0.0.1:<verified-free-port>:8000. For containerized Nginx use the appropriate
proxy network and service-name upstream. Publish no PostgreSQL host port.
Add an RMR virtual host without replacing existing applications. Configure the
actual HTTPS subdomain in RMR_BASE_URL, TLS/renewal/HTTP redirect, forwarded Host,
client IP and scheme, trusted FORWARDED_ALLOW_IPS and consistent upload limits.
Keep frontend/API same-origin and verify Host/Origin/cookie behavior.

Persist dedicated PostgreSQL data and all RMR /data files (training, themes,
media, client training, exports); protect secrets separately. The built-in backup
command remains SQLite-only. Production needs PostgreSQL-aware backup/restore,
application-file backups, encrypted off-server retention and restore tests, not
raw copies of an active PostgreSQL volume. Configure Docker/proxy log rotation,
disk/backup-age alerts and worker queue/heartbeat monitoring. /api/health is core
readiness only, not provider certification; legacy email/payment wording remains.

Sequence: local cleanup → candidate/secret review → Git → GitHub → separate VPS
checkout → production env → PostgreSQL → explicit migrations → RMR application
container → Nginx → HTTPS → health/restart persistence → real owner login/tenant
authorization → separately approved bounded PIQ acceptance. No deployment or
provider call is authorized merely by this preparation document.
