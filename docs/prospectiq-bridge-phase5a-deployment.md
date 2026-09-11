# Phase 5A - production deployment preparation

Current preparation addendum: `prospectiq-predeployment.md`. It supersedes the
historical uncommitted-document status, return route and unresolved local proxy
work below; production server verification is still outstanding.

Date: 2026-09-10. PREPARATION ONLY. Commands describe future, separately approved
operator actions. Do not run fixture initializers, seed/reset commands, tests or
SQLite backup helpers against an installed application/database.

## A-B. Result and decision

Preparation completed from local tracked code/config and retained sanitized
Phase 4 proof. Verdict: **NOT READY**. Deployment prerequisites remain; this is
not a reversal of the Phase 4 integration tests.

1. Actual separate RMR/PIQ HTTPS hostnames, certificates, proxy routes and exact
   callback bindings are not supplied or verified.
2. Deployed SHAs/image digests, actual Compose projects/overrides/volume identities,
   native production configuration and schema state are unknown.
3. RMR production Compose passes no bridge settings and mounts no RSA key.
   Adding bridge values to host .env alone will not pass them to the container.
4. PIQ checked-in Compose overrides backend/.env with development DSNs and binds
   DB/Redis/Python/backend ports publicly. Actual VPS overrides/firewall unknown.
5. PIQ inner nginx replaces X-Forwarded-Proto with its HTTP $scheme. Node has
   no configured trust proxy. Trusted client-IP/rate limiting and HTTPS header
   preservation through the actual chain need a reviewed deployment solution.
6. Native production validation, backup/restore rehearsal, schema preflight,
   pilot UUIDs/entitlements/JIT collision approval, queue drain plan and
   monitoring/rollback ownership remain outstanding.
7. Approved immutable images must be available. No push/tag/publication is
   authorized here. These new docs are not part of the approved code SHAs.

Missing domains are deployment prerequisites, not code defects. If actual PIQ
native DB identifiers are rejected by its NODE_ENV=production validator, stop
for separate review: do not rename the database, rotate native secrets or use
development mode as an unreviewed workaround.

## C-D. Source manifest

Both repositories were clean on main before documentation additions. Each
Phase 0-4 range contains five commits and no merge commits.

| Repository | Approved HEAD | Local pre-bridge base, NOT proven deployed | Diff |
| --- | --- | --- | --- |
| RMR | 5ff29bd876fe31950b253760578e9dc26c954179 | 19a3ed36ff57ae4b46b677485bd014d9deff8d2a | 52 files; +4254/-3 |
| PIQ | 1663e832df859348596f638707c207cc545a468c | dc5a2e102ad1788226a14f65be5b0749034ccefd | 55 files; +4032/-59 |

RMR: 1aeb98e foundation -> ecb9f24 federation -> a4985ac capabilities ->
e3ddbc8 CRM -> 5ff29bd operations.
PIQ: 0b3ef2c foundation -> c182fcf federation -> 0c28702 capabilities ->
050d822 CRM -> 1663e83 operations.

RMR origin: https://github.com/rmritdesk-ui/rmr.git (five ahead of local
origin/main). PIQ origin: https://github.com/rmritdesk-ui/prospectiq.git
(no upstream displayed). No fetch performed. Local origin/main is not a
deployment record.

RMR changes: additive bridge schema/services, auth hooks, launch/CRM UI,
tests/docs. PIQ changes: Node session/jobs/outbox, native route integration,
worker authorization, React session/capability/CRM UI, tests/docs.
No PIQ Python discovery or Compose files changed in these Phase 0-4 ranges.

On deployment day, capture git status --short --branch, git rev-parse HEAD,
remotes, image IDs/digests and exact Compose project/service labels and files.
Once deployed SHAs are supplied, use git merge-base --is-ancestor <deployed>
<release>, git log <deployed>..<release> and git diff --stat. Review divergence;
do not assert that the five commits are the entire deployment delta.

## E. Exact RMR production variables

Examples are placeholders. Restart means recreate app with changed env/mounts;
docker restart does not apply changed Compose environment. Required means when
bridge ON; defaults are identified. Variables apply to app, not postgres.

| VARIABLE | REQUIRED ENABLED? | SECRET? | SOURCE / GENERATION | FORMAT | ROTATABLE? | RESTART? |
| --- | --- | --- | --- | --- | --- | --- |
| RMR_PROSPECTIQ_BRIDGE_ENABLED | Yes | No | Operator | false Stage 1; true Stage 2 | Toggle | App |
| RMR_PROSPECTIQ_BASE_URL | Yes | No | Approved PIQ origin | https://<PIQ_HOST> | Coordinated topology | App |
| RMR_PROSPECTIQ_CALLBACK_URL | Yes | No | PIQ root callback | https://<PIQ_HOST>/ | Coordinated | App |
| RMR_PROSPECTIQ_INTEGRATION_INSTANCE_ID | Yes | No | Stable shared deployment identity | <PIQ_INSTANCE_ID>, max 120 chars | Not routine; durable namespace | App |
| RMR_PROSPECTIQ_ASSERTION_ISSUER | Yes | No | Exact RMR origin | https://<RMR_HOST> | Not routine; external identity key | App |
| RMR_PROSPECTIQ_ASSERTION_AUDIENCE | Yes | No | Exact shared audience | <PIQ_FEDERATION_AUDIENCE> | Coordinated | App |
| RMR_PROSPECTIQ_SIGNING_KEY_ID | Yes | No | RSA label | fed-rc1; A-Z/a-z/0-9/_/- max 80 | Yes | App |
| RMR_PROSPECTIQ_SIGNING_PRIVATE_KEY_FILE | Yes | Path no; contents YES | New RSA PEM, unencrypted, >=2048 bits | /run/rmr-bridge/federation-private.pem | Yes with kid/public key | App |
| RMR_PROSPECTIQ_HMAC_KEY_ID | Yes | No | Grant service label | grant-rc1 | Yes | App + PIQ sender |
| RMR_PROSPECTIQ_HMAC_SECRET | Yes | YES | New independent grant secret | <64_HEX_CHARACTERS> | Overlap rotation | App + PIQ backend/worker |
| RMR_PROSPECTIQ_HMAC_KEYS_JSON | Optional | YES | Grant receiver ring; active ID/secret fallback | {}; or {"old-id":{"secret":"<SECRET>","not_after":<UNIX_SECONDS>}} | Yes | App |
| RMR_PROSPECTIQ_CRM_KEYS_JSON | Yes | YES | Separate CRM receiver ring | {"crm-rc1":"<DIFFERENT_SECRET>"} | Overlap rotation | App + PIQ backend |
| RMR_PROSPECTIQ_AUTHORIZATION_CODE_TTL_SECONDS | Default 60 | No | Bounded code lifetime | 1-60 seconds | Policy | App |
| RMR_PROSPECTIQ_GRANT_MAX_SECONDS | Default 28800 | No | Absolute max; align PIQ | 1800-28800 seconds | Policy | App |
| RMR_BASE_URL | Yes/native | No | Exact approved origin | https://<RMR_HOST> | Coordinated | App |
| RMR_COOKIE_SECURE | Yes | No | Must be true | true | Do not weaken | App |
| RMR_SECRET_KEY | Yes/native | YES | Preserve native session key | <EXISTING_NATIVE_SECRET> | Separate operation; sessions affected | App |
| RMR_SESSION_HOURS | Native default 12 | No | Preserve native policy | 12 | Policy | App |
| FORWARDED_ALLOW_IPS | Production Compose | No | Actual trusted proxy peers | <VERIFIED_PEER_IPS>, never * | Topology review | App |

No RMR public-key overlap variable: RSA overlap verification is on PIQ.
No extra bridge CORS/origin list: browser launch/authorize requires exact RMR
Origin and X-RMR-Request: 1. No RMR bridge access/idle/queue/cleanup scheduler
env exists. Pending launch 3 minutes, assertion <=30 seconds, HMAC freshness
+/-30 seconds, nonce retention 2 minutes. Grant expiry is the minimum of native
login expiry, configured max and managed-write expiry.

### Native production dependencies to preserve

| VARIABLE | REQUIRED ENABLED? | SECRET? | SOURCE / GENERATION | FORMAT | ROTATABLE? | RESTART? |
| --- | --- | --- | --- | --- | --- | --- |
| RMR_RELEASE_TAG | Compose | No | Reviewed immutable image label | <RELEASE_LABEL> | Per release | App |
| RMR_RELEASE_REVISION | Provenance | No | Full reviewed SHA | <40_HEX_SHA> | Per release | Rebuild app |
| RMR_POSTGRES_DB / RMR_POSTGRES_USER | Compose | No | Existing DB/role | <EXISTING_DB> / <EXISTING_ROLE> | Not this rollout | No DB restart |
| RMR_POSTGRES_PASSWORD | Compose | YES | Preserve credential | <EXISTING_PASSWORD> | Separate DB operation | Coordinated |
| RMR_DATABASE_URL | Native app | YES | Compose builds private PostgreSQL DSN | postgresql+psycopg://<ROLE>:<PASSWORD>@postgres:5432/<DB> | Separate operation | App |
| DATABASE_URL | Fallback only | YES | Only if RMR_DATABASE_URL absent | Same DSN form | Avoid conflicting fallback | App |
| RMR_CREDENTIAL_ENCRYPTION_KEY | Compose | YES | Preserve encrypted-data key | <EXISTING_KEY> | Separate recovery/data plan | App |
| RMR_INTEGRATION_ENCRYPTION_KEY | Compose | YES | Preserve valid Fernet key | <EXISTING_FERNET_KEY> | Separate recovery/data plan | App |
| RMR_SETUP_TOKEN | Initial owner only | YES | Existing setup policy; blank after setup | blank or <SETUP_TOKEN> | Separate bootstrap | App |
| RMR_ENVIRONMENT | Production | No | Compose constant | production | No | App |
| RMR_HOST / RMR_PORT / RMR_DATA_DIR | Native | No | Compose constants | 0.0.0.0 / 8000 / /data | Preserve | App |
| RMR_AUTO_MIGRATE / RMR_AUTO_SEED / RMR_ALLOW_DEMO_CREDENTIALS / RMR_LOCAL_RECOVERY_MODE | Safeguards | No | Compose constants | false | Do not enable | App |
| RMR_INSTALL_PROFILE | Safeguard | No | Compose constant | empty | Do not seed | App |
| RMR_MAX_UPLOAD_MB | Native | No | Existing policy | 250 default | Policy | App |

Existing RMR_PIQ_*, RMR_GOOGLE_PLACES_API_KEY, RMR_AI_*, SMTP/campaign/billing/
website variables are native integrations, not federation settings. Preserve
approved values/budgets; never replace them from local/demo .env. Their native
inventory remains docker-compose.production.yml and deploy/production.env.example.
No real environment file was read in Phase 5A.

## F. PIQ variables

Exact table, worker subset, native dependencies, fixed queue policies and schema
procedure: PIQ repository docs/rmr-integration-phase5a-deployment.md.

## G. Key-material plan - NOT executed

Distinct identities: native RMR session secret; native RMR encryption keys;
new federation RSA pair; new PIQ->RMR grant HMAC; new PIQ->RMR CRM HMAC;
native PIQ JWT/billing keys. No reverse RMR->PIQ service-HMAC is implemented.
RMR authenticates the federation response with RS256.

Future Linux generation, only inside a verified private absolute directory
outside Git; run in a fail-fast shell, no tracing, no existing files:

~~~sh
set -eu
test -n "$BRIDGE_KEY_DIR"
case "$BRIDGE_KEY_DIR" in /*) ;; *) exit 1 ;; esac
test ! -e "$BRIDGE_KEY_DIR"
test ! -L "$BRIDGE_KEY_DIR"
umask 077
install -d -m 0700 "$BRIDGE_KEY_DIR"
test ! -e "$BRIDGE_KEY_DIR/federation-private.pem"
test ! -e "$BRIDGE_KEY_DIR/federation-public.pem"
test ! -e "$BRIDGE_KEY_DIR/grant-hmac.secret"
test ! -e "$BRIDGE_KEY_DIR/crm-hmac.secret"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$BRIDGE_KEY_DIR/federation-private.pem"
openssl pkey -in "$BRIDGE_KEY_DIR/federation-private.pem" -pubout -out "$BRIDGE_KEY_DIR/federation-public.pem"
openssl rand -hex 32 > "$BRIDGE_KEY_DIR/grant-hmac.secret"
openssl rand -hex 32 > "$BRIDGE_KEY_DIR/crm-hmac.secret"
chmod 0600 "$BRIDGE_KEY_DIR"/*
~~~

The HMAC file newline is NOT part of the value; install its single line privately,
without CR/LF. No HMAC *_FILE loader exists. Use private 0600 environment storage/
approved secret management, never build args or command-line literal secrets.

RMR app alone gets read-only private PEM, readable by UID/GID 10001 (e.g.
root:10001, 0440, narrowly traversable directory). PIQ backend gets public PEM
only; worker needs no RSA key. Do not mount the private directory into PIQ.
Existing PIQ Compose shares backend/.env with worker; a least-privilege split is
a reviewed env wiring change, not permission to rotate unrelated credentials.

HMAC receiver ring <=4 IDs, at most one permanent active string; overlap
{secret,not_after} finite <=24h ahead. PIQ RSA primary plus <=3 bounded public
overlaps {file,not_after}. Stage receiver, switch sender, retire old keys after
in-flight lifetime. Backend AND worker switch grant sender together; CRM sender
is backend. Preserve instance/issuer. Synchronize clocks. Never reuse secrets
previously exposed locally/in chat; unrelated native rotation is a separate task.

## H. Hostnames, callback and proxy contract

| Purpose | Exact relationship/path |
| --- | --- |
| RMR origin | https://<RMR_HOST>, no path/query/fragment/userinfo |
| PIQ origin | https://<PIQ_HOST>, different hostname, not only different port |
| Callback | https://<PIQ_HOST>/ exactly; callback ID piq-web |
| RMR authorization landing | https://<RMR_HOST>/prospectiq-authorize |
| Return to RMR | https://<RMR_HOST>/#/prospectiq; derived from origin, no RMR_RETURN_URL config exists |
| View accepted Lead | https://<RMR_HOST>/#/crm?tenant=<TENANT_UUID>&lead=<LEAD_UUID> |
| Launch destinations | prospects or target_profiles, not arbitrary URLs |

PIQ /#rmr-start=..., RMR landing fragment and PIQ /#rmr-callback=... carry
transient transaction/code data removed immediately from history. Disable
location-fragment capture in analytics/error tooling. Never log headers,
cookies, codes, verifiers, HMAC signatures/nonces or raw bodies. Honor no-store.
Preserve signed receipt lookup path and raw query order without normalization.

PIQ browser API stays same-origin /api. CORS_ORIGINS in production contains
exact PIQ origin plus only independently necessary existing native UI origins;
RMR origin is not needed for server-to-server exchange. No wildcard CORS.
RMR browser actions remain same-origin; preserve Origin unchanged.

RMR cookie: host-only Secure/HttpOnly/SameSite=Strict. PIQ refresh cookie:
__Host-rmr-refresh-<session UUID>, Secure/HttpOnly/SameSite=Strict, Path=/,
no Domain. Bridge access JWT in memory; sessionStorage only UUID/return hint
after exchange. No shared parent cookie, iframe or TLS bypass.

Use existing cPanel/Apache vhosts. RMR loopback 127.0.0.1:18100 -> app:8000;
maintained deploy/apache-rmr-ssl-include.conf.example applies, not old generic
nginx port 8080. PIQ HTTPS vhost reaches existing frontend loopback upstream;
frontend /api proxies Node. Preserve Host, set HTTPS scheme at the trusted TLS
edge, strip spoofed forwarded chains, trust only actual peers and preserve
/.well-known/. Any shared Apache reload requires separate approval/config test.

PIQ frontend/nginx.conf currently overwrites scheme with HTTP. Review the full
edge->nginx->Node chain rather than trusting public headers. No env-driven
Express trust-proxy setting exists. Real per-client rate-limit behavior must be
verified; a required narrow correction is a separate reviewed change. Preserve
unrelated Corvee/PTS listeners/vhosts.

## I. RMR migration sequence

1. 005.009.000-prospectiq-bridge-foundation
2. 005.010.000-prospectiq-federation
3. 005.011.000-prospectiq-crm-handoff
4. 005.012.000-prospectiq-operations

Tables: prospectiq_client_mappings, prospectiq_authorization_grants,
prospectiq_crm_receipts, prospectiq_replay_nonces, prospectiq_crm_events.
005.010 adds nullable browser/state/nonce hashes, authorized/absolute expiry,
destination. 005.011 ensures current bridge tables including CRM events.
005.012 adds ix_bridge_grant_absolute and ix_bridge_browser_logout.

Current metadata can create the latest full table shape during 005.009; do not
expect historical intermediate shapes on a clean DB. Unique mapping/client/
tenant/code/nonce/prospect/event keys and composite context FKs protect history.
Bridge changes are additive, forward-only and PostgreSQL-tested.

Supported command: python -m rmr_platform.cli migrate, NOT Alembic.
It also creates metadata, runs missing historical migrations and CB1/commercial
bootstrap, and seeds governed references. It is not an atomic bridge-only
transaction and has no target-version option. No demo accounts are seeded.
Preflight actual ledger/schema and rehearse on a restored clone. Missing older
migrations need their own review (e.g. earlier profile uniqueness changes).
Start new app only after schema is current. AUTO_MIGRATE remains false.
Rollback normally retains additive tables/indexes/ledger; no down migration.

## J-K. Schema compatibility and preflight

Use PIQ companion helper procedure, not index.js or db/init.sql as a migration
CLI. Normal PIQ startup still performs broad native bootstrap after bridge DDL.

Use trusted local PG access, BEGIN READ ONLY, and do not print hashes, DSNs,
credentials or payloads. Nothing below was run against live databases.

~~~sql
BEGIN READ ONLY;
SELECT current_database(),current_user,version();
SHOW search_path;
SELECT table_name,column_name,data_type,is_nullable,column_default
FROM information_schema.columns WHERE table_schema=current_schema()
ORDER BY table_name,ordinal_position;
SELECT conrelid::regclass,conname,contype,convalidated,pg_get_constraintdef(oid)
FROM pg_constraint WHERE connamespace=current_schema()::regnamespace;
SELECT tablename,indexname,indexdef FROM pg_indexes
WHERE schemaname=current_schema() ORDER BY tablename,indexname;
SELECT pid,state,wait_event_type,wait_event
FROM pg_stat_activity WHERE datname=current_database();
ROLLBACK;
~~~

RMR (run bridge queries only if those tables exist):
~~~sql
BEGIN READ ONLY;
SELECT version,applied_at FROM schema_migrations ORDER BY applied_at;
SELECT migration_id FROM cb1_schema_migrations;
SELECT id,name,slug,status FROM tenants ORDER BY name;
SELECT id,email,active,global_role,tenant_id,tenant_role,must_change_password
FROM users WHERE id=:'pilot_rmr_user_uuid';
SELECT tenant_id,service_code,status FROM tenant_services
WHERE tenant_id=:'rmr_tenant_uuid'
AND service_code IN ('piq_access','piq_enhancement');
SELECT id,integration_instance_id,tenant_id,piq_client_id,status,mapping_version
FROM prospectiq_client_mappings;
SELECT integration_instance_id,tenant_id,count(*) FROM prospectiq_client_mappings
GROUP BY 1,2 HAVING count(*)>1;
SELECT integration_instance_id,piq_client_id,count(*) FROM prospectiq_client_mappings
GROUP BY 1,2 HAVING count(*)>1;
SELECT status,count(*) FROM prospectiq_authorization_grants GROUP BY status;
SELECT status,count(*) FROM prospectiq_crm_receipts GROUP BY status;
ROLLBACK;
~~~

Keep identity checks private. Compare actual column/constraint/index definitions,
not just table existence: IF NOT EXISTS/create_all do not repair schema drift.
Check FK targets, duplicates, ledger gaps, sizes/free disk/WAL and long locks.
Ordinary CREATE INDEX can block; choose a maintenance window. Conflicts mean
STOP, not automatic cleanup.

No bridge-only rewrite of native users/passwords/CRM rows is required. Existing
PIQ users stay externally_managed=false; native refresh tokens and generic CRM
remain separate. Incomplete old grants/sessions fail closed and need relaunch.
Old workers must not consume bridge jobs. Assess/drain native queues without
purging before restart; preserve their existing provider/email permissions.

## L. Canonical mapping and JIT operator procedure

There is no mapping/link administration CLI or API in the current bridge.
Use a separately approved, audited DBA transaction; never a browser API bypass.
Obtain RMR tenant/user UUIDs from its authorized UI/read-only queries and PIQ
client/user UUIDs independently from its native admin UI/read-only queries.
Confirm each organization through its business owner; names/email are display
checks, never the join key. Record environment, instance, UUIDs and approvers.
Both piq_access and piq_enhancement must be active. Normal CLIENT_ADMIN has
read/profile/discovery/export/CRM/research capabilities; sales writers lack
research; MARKETING_USER and EXECUTIVE_VIEWER have bridge read only. Global
RMR_OWNER/STEP2_ADMIN need an existing managed_write session for that tenant.
Do not invent a role or grant PIQ native global-admin access.

Future psql procedure: use -X -v ON_ERROR_STOP=1 with trusted socket/credential
storage; set quoted psql variables via prompts, not secret-bearing shell args.
Required variables: instance_id, rmr_tenant_uuid, piq_client_uuid,
creator_rmr_user_uuid. Validate all UUIDs and the <=120-character instance first.
Creation explicitly supplies SQLAlchemy's application-side default fields:

~~~sql
BEGIN;
SET LOCAL lock_timeout='5s';
SELECT id,name,slug FROM tenants WHERE id=:'rmr_tenant_uuid' FOR UPDATE;
SELECT id,email,active,global_role FROM users
WHERE id=:'creator_rmr_user_uuid' AND active IS TRUE;
SELECT id,tenant_id,piq_client_id,status,mapping_version
FROM prospectiq_client_mappings
WHERE integration_instance_id=:'instance_id'
AND (tenant_id=:'rmr_tenant_uuid' OR piq_client_id=:'piq_client_uuid') FOR UPDATE;
INSERT INTO prospectiq_client_mappings
(id,created_at,updated_at,integration_instance_id,tenant_id,piq_client_id,
 status,mapping_version,created_by_user_id,approved_by_user_id)
VALUES(gen_random_uuid()::text,NOW(),NOW(),:'instance_id',:'rmr_tenant_uuid',
 :'piq_client_uuid','pending',1,:'creator_rmr_user_uuid',NULL)
RETURNING id,tenant_id,piq_client_id,status,mapping_version;
-- COMMIT only after exactly one intended row; otherwise ROLLBACK.
~~~

STOP before INSERT if identities are not exactly the approved active creator,
tenant and independent PIQ client, or any mapping already exists. Never use
ON CONFLICT UPDATE. Unique violations abort; investigate competing identity,
do not delete old rows. Both uniqueness rules include suspended mappings.

Have a second approved operator re-verify the UUID pair, active PIQ client,
pilot user's access and entitlements. Activate with matching immutable values:
~~~sql
BEGIN;
SET LOCAL lock_timeout='5s';
UPDATE prospectiq_client_mappings
SET status='active',approved_by_user_id=:'approver_rmr_user_uuid',updated_at=NOW()
WHERE id=:'mapping_uuid' AND integration_instance_id=:'instance_id'
AND tenant_id=:'rmr_tenant_uuid' AND piq_client_id=:'piq_client_uuid'
AND status='pending' AND mapping_version=:'expected_mapping_version'::integer
RETURNING id,status,mapping_version;
-- Verify approver exists/active first; exactly one row, then COMMIT.
~~~

Set expected_mapping_version from the locked pending row (1 for a newly
created mapping), not an assumed version after any reviewed correction.

Suspend: stop new pilot use, lock the exact mapping, set status='suspended',
updated_at=NOW(); leave UUID context/version intact, and revoke its pending/
consumed grants (status='revoked',revoked_at=NOW()) in the same transaction.
Revoke associated PIQ sessions using the existing operations CLI if needed.
Already in-flight calls cannot be recalled; reconcile outcomes after containment.
Unsuspension of the SAME identity requires approval/new launches; do not revive
revoked grants. Version bump is not required just to suspend.

Remap: referenced grants/receipts use RESTRICT composite FKs. Even expired/
revoked history can prohibit changing client/tenant. One mapping per instance/
tenant and instance/client includes suspended rows. Therefore remapping with
history is NOT a supported routine operation. Stop for an explicit migration
design; never delete history, disable FKs, change instance to evade uniqueness
or create a second destination for a completed prospect.

Only an unused erroneous pending mapping with ZERO grants and ZERO receipts
may be corrected under separate approval: lock it, re-verify destination, set
pending, clear approval, increment mapping_version, retain audit record, then
repeat activation review. Do not silently rebind an active mapping.

Mapping rollback = suspend/revoke and retain row/history, not deletion.

JIT behavior (PIQ service.js):
- No email match/link: creates externally_managed shadow user, unusable local
  password, native role user, explicit identity and exact client membership.
- Same case-insensitive email but no explicit link: identity_link_required;
  no merge, password change or role promotion.
- Existing active (issuer,RMR user UUID) identity: uses its PIQ user UUID,
  requires active PIQ user/client; idempotently adds exact client membership.
- Disabled PIQ user or suspended/pending identity: deny. Disabled RMR user,
  lost entitlement, mapping suspension or invalid managed session: deny.
- Native PIQ password/role/refresh tokens of an explicitly linked user remain
  unchanged; bridge credentials still have role user and bound capabilities.

Collision recovery requires proof that the immutable RMR subject and existing
PIQ user belong to the same person plus explicit owner approval. In a trusted
transaction create rmr_external_identities with the exact issuer/RMR UUID/PIQ
UUID and status pending, review then activate. Supply no email-based automatic
link, do not alter native password/role or externally_managed flag. Query both
existing links by RMR subject AND PIQ user before linking; unexpected many-to-one
links require review (the DB does not prohibit all such cases). There is no
self-service linking tool. Wrong link: suspend it and revoke its bridge sessions;
do not rewrite an identity with session/handoff history.

## M-N. Minimum runtime impact

| Component | Code rebuild/recreate? | Stage 2 configuration recreate? |
| --- | --- | --- |
| RMR app (FastAPI + its static UI) | Yes | Yes, env/key mount |
| RMR PostgreSQL | No restart/rebuild; explicit DDL only | No |
| PIQ frontend (Vite build + nginx) | Yes | Only if proxy/build config changes |
| PIQ Node backend | Yes | Yes, env/public key/HMAC |
| PIQ Node worker | Yes | Yes, current grant-check env |
| PIQ Python discovery | NO Phase 0-4 changes | No bridge reason |
| PIQ PostgreSQL / Redis | No restart/rebuild for bridge code | No |

Actual deployed revisions may add unrelated changes: assess them once known.
RMR Compose project name is rmr-production in source; volumes postgres-data
and app-data mount PG storage and /data. Names must match ACTUAL live project.
PIQ Compose has no fixed project name; db_data name depends on actual project.
Redis has no explicit persistent named volume in this file. Never assume its
durability or delete/recreate it for this release.

RMR app binds 127.0.0.1:18100:8000; no public PG port. PIQ checked-in mappings:
frontend 5173:80, backend 4000:4000, Python 8000:8000, DB 5433:5432, Redis
6379:6379. These are NOT permission to expose internals. Preserve internal
service names/ports and current volumes. Final public entry is approved HTTPS
vhosts only. Bind necessary upstreams to loopback and remove public internal
exposure through a separately reviewed override/firewall plan. Port hardening
may itself require affected containers to recreate; keep that action separate
from the minimal code rollout, with dependency/drain review. Corvee/PTS unchanged.

Required future RMR wiring: explicit pass-through of every bridge env row and
read-only private PEM mount into app. PIQ: actual production DSN override,
exact CORS/native env, public-key backend mount, worker grant env, safe port/
proxy configuration. Do not expose secrets by printing expanded Compose config;
use config --quiet. No topology/Compose file was changed in Phase 5A.

## O. Backup and recovery

Before any write: record SHAs, image digests, exact Compose project/files,
volume IDs, native config/key recovery references, schema ledger and row counts.
Quiesce app writes/scheduled work and drain bounded in-flight jobs; preserve
queues and authoritative SQL history. Keep a private pre-change dump and a
tested off-host copy. Do not use the RMR SQLite backup CLI.

Define operator shell functions rmr_compose and piq_compose to invoke ONLY the
verified existing project/files/private env (do not paste guessed project names).
With app writers quiesced and a new private backup directory:

~~~sh
set -eu
umask 077
test -d "$BACKUP_DIR"
test ! -e "$BACKUP_DIR/rmr-pre-bridge.dump"
test ! -e "$BACKUP_DIR/piq-pre-bridge.dump"
rmr_compose exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$BACKUP_DIR/rmr-pre-bridge.dump"
piq_compose exec -T db sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$BACKUP_DIR/piq-pre-bridge.dump"
test -s "$BACKUP_DIR/rmr-pre-bridge.dump"
test -s "$BACKUP_DIR/piq-pre-bridge.dump"
~~~

Use pg_dump compatible with actual server (source targets PG16). If socket auth
requires credentials, use a protected pgpass/approved container env, not literal
password arguments. A nonzero exit/empty dump is a STOP. Verify pg_restore --list
inside a trusted PG16 tool environment, then RESTORE TO A NEW ISOLATED DB and
run checks with providers/email disabled. A TOC list alone is not restore proof.

Back up RMR /data with app stopped, including uploads/training and any generated
site assets. Use the previously verified exact app-data volume read-only:
~~~sh
test -n "$RMR_APP_DATA_VOLUME"
test ! -e "$BACKUP_DIR/rmr-app-data.tar"
docker run --rm --network none --read-only \
  --mount "type=volume,source=$RMR_APP_DATA_VOLUME,target=/source,readonly" \
  --entrypoint tar "$RMR_PREVIOUS_IMAGE" -C /source -cf - . > "$BACKUP_DIR/rmr-app-data.tar"
test -s "$BACKUP_DIR/rmr-app-data.tar"
~~~

Confirm the volume exists/identity matches first (Docker otherwise creates a
new empty named volume). Verify archive contents privately, checksums, encryption,
access/retention and off-host copy. Preserve native encryption keys separately;
a database dump without those keys may be unusable. Native PIQ extra bind mounts/
uploads, if present in actual deployment overrides, also require backup.

CRM identity is SQL: PIQ rmr_crm_handoffs stores stable prospect/event/hash/
result; RMR receipts/events/Lead store acceptance. Redis is not the completed
handoff authority. Losing Redis can still lose native queued work; do not purge.

Recovery order: contain both flags and writers, snapshot failure state, preserve
receipts/outbox, restore compatible app revisions first with additive schema
left intact. Only if necessary and separately approved, restore PG into verified
replacement DBs plus consistent RMR app-data, then backend/app, then compatible
worker/frontend. Reconcile uncertain handoffs before new delivery. Never restore
one side to an earlier identity history while the other continues accepting.

## P. Stage 1 - code/schema with bridge OFF

Prerequisites: verified production config/ports, exact previous/new images and
volumes, successful release gate/restore rehearsal, explicit change window.

1. Inspect actual revision delta and native configuration; flags false in RMR,
   PIQ backend AND worker. Do not alter native provider/billing/SMTP settings.
2. Build/pin new RMR runtime, PIQ backend, worker and frontend images without
   replacing running containers. Preserve previous images and config.
3. Quiesce affected writes, pause scheduled dispatch via approved operational
   controls, drain queues/in-flight work, and take/verify backups.
4. Stop only RMR app; keep its PostgreSQL running. Using the new app image and
   same production DB/data env: rmr_compose run --rm --no-deps app
   python -m rmr_platform.cli migrate. Do not publish migration container ports.
5. Require migration success/current schema. Recreate only app:
   rmr_compose up -d --no-deps --wait app. (App definition must now reference
   approved new image; no database/network/volume replacement.)
6. PIQ: stop backend/worker after drain; keep DB/Redis/Python running. Apply
   companion transactional helper from new backend image. Then recreate only
   backend, worker and frontend via piq_compose up -d --no-deps --wait
   backend worker frontend. Its normal native bootstrap still runs.
7. Verify core health plus bridge health reports disabled at both apps.
8. Complete Stage 1 native smoke checklist below. Record results and approve
   Stage 1 separately. Do not proceed automatically into Stage 2.

No docker compose down, down -v, prune, blanket up --build or new production
project name. Do not run db/init.sql or demo/bootstrap test helpers.

## Q. Stage 2 - separate bridge activation

1. Obtain explicit activation approval after Stage 1 passes.
2. Provision fresh bridge keys privately; install mounts/env and exact origins,
   issuer/audience/instance/callback. Keep native keys/DSNs unchanged.
3. Complete hostname/TLS/proxy/clock checks. Create/review pending UUID mapping,
   resolve JIT collision, verify entitlements/roles, then approve activation.
4. Ensure no stale bridge jobs exist for the selected instance. Reconcile
   historical uncertain outcomes before enabling a dispatcher.
5. Enable RMR first and recreate app; require bridge readiness. Then enable
   PIQ backend AND worker and recreate only those. Enabled PIQ backend requires
   BOTH grant/federation AND CRM config. Do not leave partial enabled config.
6. Restrict pilot access to reviewed mapping/users. Run no-provider federation
   smoke first. Production-safe CRM fixture requires explicit approval; absent
   that fixture, defer the mutation rather than inventing a production test lead.
7. Only with further explicit budget/workflow approval run one bounded live
   discovery/research/CRM flow. No provider action is implied by activation.
8. On failed gate, contain flags/mapping; retain SQL identities and reconcile.

## R. Deployment-day smoke checklist

Stage 1 OFF, native users and approved pilot records only:
1. RMR native login, tenant/navigation.
2. Native CRM read and approved test-record write; avoid downstream automation.
3. Existing integrated RMR PIQ renders; no provider request needed.
4. Standalone native PIQ login, existing client selection and screens.
5. Worker process/log/queue health (the /api/worker/health endpoint alone is just
   a backend proxy response, not a proof that a worker is alive).
6. Generic PIQ CRM optional-secret path only if safe approved receiver/fixture
   exists. Existing outcome_secret vs outcome_webhook_secret naming discrepancy
   is not fixed by this bridge; required production use needs its own verification.

Stage 2 ON, NO providers first:
1. Pilot RMR login and correct tenant; Open ProspectIQ without second login.
2. Correct PIQ client; foreign client/object/query denied.
3. Capability matrix for client admin/sales/read-only/managed role.
4. Reload/short-token renewal; idle/absolute expiry; logout and fresh relaunch.
5. Mapping/user revocation denies further access; restored role does not expand
   old session. Re-launch for new capabilities.
6. Synthetic handoff only with approved production-safe fixture; otherwise
   rely on isolated gate and mark production handoff smoke deferred.

Then ONLY with explicit live authorization:
1. One bounded Pull New Leads, approved quantity/budget/attempt limits.
2. One eligible Adaptive Research with cost confirmation.
3. One Move to RMR CRM.
4. Verify one Lead + one receipt/event identity, correct tenant/actor/provenance.
5. View in RMR; repeat same transfer returns SAME Lead, no Account/Contact/
   Opportunity conversion. No email/website/customer billing action.

## S. Monitoring and maintenance

Read-only operational commands using verified Compose wrappers:
~~~sh
rmr_compose ps
piq_compose ps
rmr_compose exec -T app python -m rmr_platform.cli bridge-health
piq_compose exec -T backend node src/rmrIntegration/operationsCli.js health
piq_compose exec -T backend node src/rmrIntegration/operationsCli.js list
~~~

HTTP GET /api/health; RMR /api/integrations/prospectiq/v1/health;
PIQ /api/integrations/rmr/v1/health. Bridge health is local config/dependency
readiness, not remote federation proof. RMR mapping_subsystem means queryable
table, NOT confirmation that the pilot mapping is active/correct.

Native PIQ admin-authenticated GET /api/admin/queues/status provides queue/
profile-run counts; it does not enumerate every adaptive-research queue.
Use existing SQL run-status counts/worker logs for the latter. Watch CPU/RAM/
disk/WAL, DB errors, stuck queues, provider-job failures and worker restarts.

RMR: auth/exchange denials, nonce replay, missing/versioned/suspended mapping,
receipt acceptance, duplicate/conflict/tombstone and DB errors. Some failures
have no dedicated counter: aggregate sanitized HTTP statuses/structured events;
do not invent a metrics endpoint. INFO rmr.bridge logs key IDs, not keys.
PIQ: bridge/renewal/grant-check failures, handoff pending/sending/retry_wait/
failed/succeeded, oldest age, unknown outcomes/reconciliation count and safe
failure categories from health/list. Restrict console data to operators.
Do not stream unrestricted raw production logs into tickets/chat.

Explicit operator MUTATIONS, not routine monitoring:
PIQ operationsCli.js reconcile <handoff UUID> performs signed RMR lookup and
updates local state; retry <UUID> --confirm can SEND; revoke <session UUID>
--confirm and cleanup --confirm write SQL. RMR bridge-cleanup also writes.
Reconcile unknown receipt before retry; not_found is not permission by itself.
Do not delete nonces, receipts, events, handoffs or sessions to solve errors.

## T. Rollback matrix

| Failure | Containment and recovery |
| --- | --- |
| RMR code fails | Flags OFF; keep PG/data; restore recorded previous app image/config; schema stays |
| PIQ code fails | Flags OFF backend/worker; drain/stop dispatch; restore compatible backend/worker/frontend set; DB/Redis/Python stay |
| RMR migration fails | Do not start new app; inspect ledger/partial DDL; native-compatible old image if verified; no blind down-DDL |
| PIQ helper/bootstrap fails | Stop new backend/worker; helper transaction rolls back; normal bootstrap may have partial commits; compare schema and use verified old images |
| Federation fails | Disable pilot/flags; verify exact origin/callback/key/clock; never bypass auth |
| Wrong client/context | IMMEDIATE suspend mapping, revoke grants/sessions, halt bridge mutations; preserve audit evidence; investigate identity exposure |
| Move to CRM fails | Preserve same prospect/event/hash; reconcile signed receipt before approved retry; never create a replacement identity |
| Session renewal fails | Safe return/relaunch; verify RMR availability/expiry/cookie/proxy; do not relax cookie or replay rules |
| HMAC fails | Stop affected dispatch; verify IDs, instance, clock, exact path and active/overlap ring; no unsigned retry |
| Invalid key config | Enabled startup must fail; flags OFF to retain native service or restore last known valid configuration; never reuse native keys |

Prefer flags OFF + application revision rollback with additive schema retained.
A DB restore is a separately approved recovery with both sides' identity history
reconciled. Native business writes since backup must not be discarded casually.
In-flight external calls cannot be undone by flipping a flag.

## U. Release/tag recommendation

RMR existing annotated tags:
rmr-piq-integration-rc1 -> 6eef90d3c0cad04ae05f13364b99572816586301
rmr-piq-integration-rc2 -> 19a3ed36ff57ae4b46b677485bd014d9deff8d2a
These predate federation. PIQ has no local tags.

Recommend NEW annotated tags only after review/gates:
RMR rmr-piq-federation-rc1 at approved 5ff29bd...
PIQ rmr-integration-rc1 at approved 1663e83...
If production config/code is subsequently corrected, review/test/tag the new
descendant instead. Never move old tags or imply Phase 5A docs are in these SHAs.
No tags/commits/push performed in Phase 5A.

## V-W. Remaining gates and GO/NO-GO

**NO-GO for VPS deployment or activation now.** Close A-B prerequisites,
complete the exact deployed-to-release diff, review missing env/mount/proxy/
port wiring, verify native production startup and restored DB compatibility,
approve mappings/JIT, backups, monitoring and change window.

Release-test entry: docs/prospectiq-bridge-release-gate.md. It composes existing
tests rather than new test infrastructure. Historical Phase 4 evidence:
RMR full 535 pass (3 existing legacy-packaging deselections), PG 91 pass;
PIQ PG 128 pass, offline 27 top-level pass; frontend build and actual browser
native/federated/CRM/restart proofs passed. Existing duplicate canConfirm JSX
warning and Starlette/AnyIO warning remain. Retained sanitized browser JSON was
re-inspected in Phase 5A. These are NOT a new Phase 5A test execution or proof
of production NODE_ENV/proxy configuration.

## X. Integrity

Phase 5A changed documentation only. No VPS connection/change, deployment,
migration, database inspection/write, DNS/certificate operation, service restart,
production key generation, Google/OpenAI/email request, tag, commit or push.
No live .env/credentials, sealed RMR, Product Owner DB, Corvee/PTS or standalone
PIQ application code changed. Standalone PIQ receives its companion docs only.

Evidence sources: docker-compose.production.yml; Dockerfile;
deploy/apache-rmr-ssl-include.conf.example; docs/CPANEL-PRODUCTION-DEPLOYMENT.md;
rmr_platform/config.py, migrations.py, cli.py, prospectiq_bridge/{config,keys,
models,service,routes,crm,operations,capabilities}.py; public/prospectiq-authorize.js;
PIQ docker-compose.yml, frontend/nginx.conf, backend/src/index.js,
backend/src/rmrIntegration/*, worker/src/rmrBridgeJobs.js.
