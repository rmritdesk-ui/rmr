# Final dynamic RMR / ProspectIQ deployment and rollback

This is the canonical Prompt 5 runbook for both repositories. It supersedes manual
mapping/profile-import instructions in the Phase 5A and predeployment documents.
It describes a future authorized deployment; no server operation was performed here.

## 1. Release and one-time prerequisites

Both repositories: `feature/dynamic-piq-workspace-provisioning`. Baselines reviewed:
RMR `d0a5445c993b05ed3b1bf043f64b1ce79984891f`; PIQ
`81941136e2dcf2d6ec12b1bde67f2eef65b550cc`. Deploy the **final Prompt 5 commits**
reported with this release, not those baselines. Record `git rev-parse HEAD` from
each clean checkout in the private release record, then build immutable images
from those exact SHAs. Never deploy a floating branch or overwrite an old tag.

Operator supplies once: two distinct HTTPS hostnames/certificates; existing Apache
SSL vhosts; exact trusted proxy peers; stable instance/audience; production-only
RSA >=2048-bit keypair and two different >=32-character random HMAC secrets;
existing database/storage identities, backups, image references and maintenance
window. Preserve existing native encryption/session/provider credentials.
Do not place credentials, expanded Compose output or DB dumps in Git/logs.

Topology: browser -> Apache TLS -> loopback RMR:18100 -> app:8000;
browser -> Apache TLS -> loopback PIQ:5173 -> Nginx:80 -> backend:4000.
PostgreSQL 16, Redis, Python and worker stay private. No shared DB/cookie/password.
Secure host-only cookies require separate hostnames, not merely separate ports.

## 2. Exact configuration contract

Use private copies of RMR `deploy/production.env.example`, `deploy/bridge.env.example`
and PIQ `deploy/backend.production.env.example`, `deploy/worker.production.env.example`.
Never substitute test fixture values. Environment files must be attached to services,
not merely exist beside Compose. Preserve native settings when adding bridge fields.

| RMR variable | Coordinated PIQ backend variable / rule |
|---|---|
| `RMR_BASE_URL` | `RMR_BASE_URL`: exact HTTPS RMR origin, no trailing slash |
| `RMR_COOKIE_SECURE=true` | Bridge renewal cookie is always Secure/HttpOnly/Strict |
| `RMR_PROSPECTIQ_BASE_URL` | `RMR_PIQ_ORIGIN`: exact separate HTTPS PIQ origin |
| `RMR_PROSPECTIQ_CALLBACK_URL` | `RMR_REGISTERED_CALLBACK_URL`: PIQ origin **plus `/`** |
| `RMR_PROSPECTIQ_ASSERTION_ISSUER` | `RMR_FEDERATION_ISSUER`: exactly RMR origin |
| `RMR_PROSPECTIQ_ASSERTION_AUDIENCE` | `RMR_FEDERATION_AUDIENCE`: identical stable audience |
| `RMR_PROSPECTIQ_INTEGRATION_INSTANCE_ID` | `RMR_INTEGRATION_INSTANCE_ID`: identical stable identity |
| `RMR_PROSPECTIQ_SIGNING_KEY_ID` | `RMR_FEDERATION_KEY_ID`: same key ID |
| `RMR_PROSPECTIQ_SIGNING_PRIVATE_KEY_FILE` | `RMR_FEDERATION_PUBLIC_KEY_FILE`: matching **public only** |
| `RMR_PROSPECTIQ_HMAC_KEY_ID`, `RMR_PROSPECTIQ_HMAC_SECRET` | `RMR_PARTNER_HMAC_KEY_ID`, `RMR_PARTNER_HMAC_SECRET`: same grant/check key |
| `RMR_PROSPECTIQ_HMAC_KEYS_JSON` | optional RMR receiver rotation ring, `{}` retains primary sender key |
| `RMR_PROSPECTIQ_CRM_KEYS_JSON` | JSON receiver ring containing `RMR_CRM_HMAC_KEY_ID`: `RMR_CRM_HMAC_SECRET` |
| `RMR_PROSPECTIQ_BRIDGE_ENABLED` | `RMR_INTEGRATION_ENABLED`: coordinated enable order below |
| `RMR_PROSPECTIQ_AUTHORIZATION_CODE_TTL_SECONDS=60` | short one-time code; PKCE, no replay |
| `RMR_PROSPECTIQ_GRANT_MAX_SECONDS=28800` | `RMR_BRIDGE_MAX_SECONDS=28800`; grant is authoritative upper bound |
| native `RMR_SESSION_HOURS=12` | `RMR_BRIDGE_ACCESS_SECONDS=300`, `RMR_BRIDGE_IDLE_SECONDS=1800` |

Grant/check HMAC secret **must differ** from CRM HMAC secret and native session keys.
RMR private directory mounts read-only at `/run/rmr-federation`; `signing.pem` must
be readable by UID 10001 without making it public. PIQ mounts a separate directory
containing only `verification.pem`, readable by its backend process. Use a secret
manager or protected files, not command-line secret arguments. Do not rotate an
existing working production identity/key merely to deploy this release.

Worker needs the same enabled flag, RMR/PIQ origins, instance and grant HMAC pair.
It performs live grant checks, not federation exchanges/CRM signing: do not give it
RSA private/public files, native session secrets or CRM HMAC. Issuer defaults to
RMR origin for its shared contract; backend alone needs callback/audience/key/session
settings. Preserve `DATABASE_URL`, Redis and Python settings in both private files.

PIQ Compose attaches `PIQ_BACKEND_ENV_FILE`, `PIQ_WORKER_ENV_FILE`,
`PIQ_POSTGRES_ENV_FILE`, `PIQ_PYTHON_ENV_FILE`; requires exact existing
`PIQ_POSTGRES_VOLUME`, `PIQ_REDIS_VOLUME`, `PIQ_PROJECT_NAME`, four `PIQ_*_IMAGE`
references and `PIQ_FEDERATION_PUBLIC_DIR`. Keep installed Redis authentication if
present; reconcile its command/URL privately rather than replacing it with defaults.

Proxy chain: Apache overwrites forwarded scheme and removes untrusted forwarding
headers (PIQ `deploy/apache-piq-ssl-include.conf.example`). Set `PIQ_TLS_PROXY_CIDR`
to Apache's exact peer at Nginx. The rebuilt image automatically selects its bundled
trusted template. Set `PIQ_FRONTEND_PEER_CIDR` to Nginx's exact backend peer; Compose
passes it as `TRUSTED_PROXY_IPS`. RMR `FORWARDED_ALLOW_IPS` trusts only its Apache
peer. Do not use wildcard, hop-count trust or an entire shared network. Reserve
stable peers in the site's network configuration or revalidate them after recreation.
Build frontend with relative `/api`; `CORS_ORIGINS` is the exact PIQ origin.
Back to RMR derives `RMR_BASE_URL + /#/prospectiq`; no production URL is hardcoded.

## 3. Preserve installed storage and define command contexts

Stop if installed database/volume identity is uncertain. Do not convert SQLite to
PostgreSQL as part of this release. For maintained RMR PostgreSQL Compose, use
`deploy/compose.existing-data.yml` and private `RMR_APP_VOLUME`/`RMR_POSTGRES_VOLUME`
set to the exact installed names; external volumes fail rather than create empty DBs.
For an existing SQLite installation use its **installed base Compose**, unchanged DB
URL and data mount, plus `deploy/compose.bridge.yml`. Do not substitute the PostgreSQL
base or start an unnecessary PostgreSQL service. Fresh installations explicitly create
their dedicated volumes/native foundation once; never run demo seed/init on installed DBs.

In a private Bash maintenance shell define these contexts using actual installed paths
and project names (placeholders below are deliberately not executable defaults):

```sh
umask 077
RMR_REPO=<absolute-rmr-checkout>
PIQ_REPO=<absolute-piq-checkout>
RMR_PROJECT=<installed-compose-project>
PIQ_PROJECT=<installed-compose-project>
RMR_COMPOSE_ENV=<private-compose-env-file>
PIQ_COMPOSE_ENV=<private-compose-env-file>
RMR_BASE_COMPOSE=<absolute-installed-base-compose>
RMR_STORAGE_OVERLAY=<absolute-compose-existing-data-yml> # PG branch only
rmr() { docker compose --project-directory "$RMR_REPO" -p "$RMR_PROJECT" --env-file "$RMR_COMPOSE_ENV" -f "$RMR_BASE_COMPOSE" -f "$RMR_STORAGE_OVERLAY" -f "$RMR_REPO/deploy/compose.bridge.yml" "$@"; }
piq() { docker compose --project-directory "$PIQ_REPO" -p "$PIQ_PROJECT" --env-file "$PIQ_COMPOSE_ENV" -f "$PIQ_REPO/docker-compose.production.yml" "$@"; }
# SQLite branch: define rmr() without the -f "$RMR_STORAGE_OVERLAY" pair.
rmr config --quiet
piq config --quiet
```

Retain installed service names if different and record the substitution once. Never
run `config` without `--quiet`, `down -v`, `db/init.sql`, demo seed scripts or test harnesses
on the server. Inspect image labels/mount destinations without dumping environments.

## 4. Backup, then additive upgrade with bridge OFF

1. Record old image digests/flags/schema versions and pending jobs/handoffs. Freeze new
   user writes in the maintenance window, stop RMR app, drain then stop PIQ worker and
   backend. Keep DB/Redis running. Back up native configuration, signing/encryption keys,
   all application/upload volumes, and Redis persistence using approved encrypted storage.
2. PostgreSQL backups (private `BACKUP_DIR`, neither Git nor public web storage):

```sh
piq exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$BACKUP_DIR/piq.dump"
# RMR PostgreSQL branch only:
rmr exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$BACKUP_DIR/rmr.dump"
# Existing RMR SQLite branch instead (offline app, same data mount/URL):
rmr run --rm --no-deps --entrypoint python app -m rmr_platform.cli backup --output /data/pre-upgrade-backup.tar.gz
```

   Check nonzero dump size and successful exit; restore/validate both DB backups on
   disposable clones before proceeding. SQLite archive must also be copied off the
   app volume. The CLI SQLite backup is NOT a PostgreSQL backup; separately preserve
   all uploaded/native files. No restoration over production during normal rollout.
3. Select final immutable images. Set RMR bridge OFF and PIQ backend/worker bridge OFF
   in their **attached** private env files. Native login/provider settings stay unchanged.
4. On existing PIQ foundation, initialize additive integration schema, then migrate RMR:

```sh
piq run --rm --no-deps --entrypoint node backend src/rmrIntegration/operationsCli.js schema-init --confirm
rmr run --rm --no-deps --entrypoint python app -m rmr_platform.cli migrate
```

   PIQ initializer uses one PostgreSQL transaction and advisory lock; repeats/concurrent
   runs preserve data. It requires existing native users/clients tables. A truly fresh
   PIQ installation must first establish the standalone native foundation in its empty
   database using its reviewed native installation path; normal app startup then extends
   that foundation (it does not create the base users/clients tables). Fresh installation
   is distinct from this existing-server upgrade; never replay demo initialization on an
   installed database.
   RMR migration includes governed reference data, not demo tenants/users. SQLite and PG
   use the same additive migration path. No destructive/down migration is required.
5. Validate both on the restored clone, then installed native startup: `piq up -d backend
   worker frontend` and `rmr up -d --no-deps app`. Verify native health/login with bridge
   disabled. Schema validation occurs again when bridge readiness is enabled below.

## 5. Controlled enablement and readiness

Configure exact origins/keys/peers before enabling. Validate Apache/Nginx syntax and
TLS trust. Set PIQ backend **and worker** `RMR_INTEGRATION_ENABLED=true`; recreate
`piq up -d --force-recreate backend worker frontend`. Then set RMR
`RMR_PROSPECTIQ_BRIDGE_ENABLED=true`; recreate `rmr up -d --no-deps --force-recreate app`.
Do not allow user traffic during this short coordinated switch; restart alone does not
reload attached env files. No manual mapping/export/import is part of this sequence.

```sh
piq exec -T backend node src/rmrIntegration/operationsCli.js health
rmr exec -T app python -m rmr_platform.cli bridge-health
piq exec -T frontend nginx -t
curl --fail --silent --show-error "$RMR_BASE_URL/api/health"
curl --fail --silent --show-error "$RMR_PIQ_ORIGIN/api/integrations/rmr/v1/health"
```

Require enabled/ready, DB/mapping/schema/queue checks and both independent HMAC checks;
do not infer readiness from a disabled response or a generic native health check. Safe
failure categories distinguish origin/callback/key/CRM/grant, PG/schema and Redis problems.
Keys are parsed, never printed. Local readiness validates configuration/dependencies;
only coordinated SSO proves both sides actually hold matching keys and clocks.

## 6. Acceptance and observation

First entitled, collision-free B2B tenant: login -> launch -> automatic exact workspace
mapping -> one-time eligible profile bootstrap -> original PIQ. Zero profiles means
normal PIQ Create Target Profile, not an operator import. Existing/manual tenant must
retain its exact mapping/client UUID. Adoption checks signed RMR canonical mapping;
never name/email/fuzzy adoption. Deleted imported profile stays deleted; user creates
a normal replacement. PIQ edits remain authoritative after completion.

Verify SSO, selected client/profile, Back to RMR, native PIQ login/logout and tenant/
capability denials. Identity collisions remain fail-closed and use the existing native
administrator immutable-ID approval UI; this exceptional review is not routine tenant
provisioning. Run fixture Pull -> Research -> CRM on a disposable clone. Real provider
acceptance on production requires separate bounded authorization; inspect evidence,
cost and exactly one correct RMR lead, then repeat CRM handoff to confirm idempotency.

Observe safe `rmr_*` / `rmr.bridge` events: workspace provision/reuse/adoption, mapping
reuse, bootstrap completion/reuse, launch/exchange, identity pending/approval/rejected
decision, revocation. Existing CRM outbox/receipts and operations health/list/reconcile
record created/retried/reconciled outcomes and attempt counts. Never log assertions,
auth codes, tokens, private keys, full prospect payloads or provider credentials.

## 7. Non-destructive rollback

Freeze new launches/writes; set RMR bridge OFF and recreate app first. Drain/stop PIQ
worker, reconcile unknown CRM outcomes through existing signed receipt operations while
credentials remain available; never blindly replay POSTs. Set PIQ backend/worker bridge
OFF and recreate both. Native RMR/PIQ fallback remains available. If necessary select
previous immutable app images and recreate only affected services after clone compatibility
check. Keep all additive tables, mappings, profiles, identity audits, receipts, CRM leads,
outbox and idempotency state. Do not restore an old database over newer accepted actions,
drop tables or run destructive rollback. Database recovery needs separate approved
reconciliation/recovery plan. Re-enabling follows section 5, not manual re-provisioning.

## Executed local release evidence

Fresh and OLD/MANUAL stacks use separate disposable PostgreSQL/Redis, actual apps/worker,
production frontend build, TLS edge -> shipped trusted Nginx -> backend, three browser
journeys, revocation/native/restart tests and fixture-only discovery/research. Old-state
fixture lacks Prompt 2-4 ledgers, retains manual import tombstone; exact UUID adoption
and user replacement are asserted after upgrade. See `FINAL-LAUNCH-TEST-MATRIX.md`.
These prove code behavior, not current VPS configuration, production capacity or live
provider success. No VPS/deployment/push/provider action was performed by this release gate.
