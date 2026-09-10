# Phase 4: bridge session and operations runbook

This phase hardens the existing RMR -> standalone PIQ bridge. It does not deploy,
enable integration by default, change provider algorithms, or replace either
native application. The pre-edit lifecycle audit is in
`docs/prospectiq-bridge-phase4-audit.md` in the RMR repository.

## Lifecycle and authority

RMR native login -> one-time code/PKCE -> <=30-second RS256 assertion -> one
durable PIQ session bound to issuer, user, tenant, mapping/version, client and grant.
The RMR login cookie is never sent to PIQ. PIQ access JWTs stay in memory.

| Limit | Default | Allowed configuration |
| --- | --- | --- |
| PIQ access JWT | 300 seconds | 300-600 seconds |
| PIQ idle renewal window | 1800 seconds | 1800-3600 seconds |
| RMR grant / PIQ maximum | 28800 seconds | 1800-28800 seconds |
| RMR authorization code | 60 seconds | Existing maximum 60 seconds |
| RS256 exchange assertion | <=30 seconds | Not extended |
| HMAC request freshness / nonce record | 30 seconds / 2 minutes | Existing policy |

Absolute expiry is the EARLIEST of original RMR login expiry, configured grant
maximum and managed-write expiry. Renewal cannot extend it. Align the PIQ
maximum with the RMR maximum; do not set PIQ lower than an RMR-issued grant.
Phase 3 sessions cannot acquire a refresh secret retroactively: relaunch once.

POST `/api/integrations/rmr/v1/session/refresh` takes only the session UUID in
JSON. The matching rotating 256-bit opaque credential is a host-only
`__Host-rmr-refresh-<session UUID>` Secure, HttpOnly, SameSite=Strict, Path=/
cookie. Exact PIQ Origin and `X-RMR-Bridge-Request: 1` are required. No Domain
attribute, URL credential or JavaScript-accessible refresh secret is used.
The compatibility `refresh_token` JSON field must be null/omitted, not a secret.

A tab stores only its UUID and safe RMR return hint in sessionStorage. Reload
renews that same session. Foreground API activity renews near short-token expiry;
there is no idle heartbeat. Inactive tabs expire after the idle window.
Concurrent refreshes serialize on the session row: one rotates, stale requests
get 409 without revoking the winner. The frontend retries once using the browser's
current cookie. If a refresh response/cookie is irretrievably lost, relaunch
rather than accepting an old renewal secret.

Logout is session-specific and does not touch native refresh tokens or another
bridge session. Frontend logout waits for in-flight renewal. The immediately
previous credential has a 30-second REVOKE-ONLY grace hash so logout wins a
refresh race. It can never refresh, read data or spend. Older credentials fail.
Operator revocation clears both hashes. This is not refresh-token replay grace.

Every bridge API request, renewal and queued provider/CRM dispatch uses current
RMR authority; there is NO read authorization cache. Active RMR user, tenant
access, PIQ entitlement, active/version-matching mapping, managed-write authority,
PIQ user/identity/client/membership and durable session are checked.
An already-authorized external request cannot be recalled; revocation blocks
subsequent checks/attempts, not an external call already in flight.

RMR logout revokes grants for that native browser login. User disablement,
removed tenant access/entitlement, suspended mapping, ended managed session,
disabled PIQ identity/user or explicit bridge revoke fail closed on the next
check. Temporary RMR/DB failures return unavailable, not a permissive fallback.
RMR definitive denial revokes the grant; renewed authority requires a new launch.

Capabilities are intersected with BOTH persisted grant and session permissions.
They only shrink. CLIENT_ADMIN -> SALES_REP removes research but retains allowed
discovery/CRM permissions. Restoring a role does not resurrect old session rights;
launch again for an upgrade. Response headers/session refresh update UI controls.
There is no global mutable current client. Ordinary RMR users remain single-tenant;
the two-tenant proof uses existing global managed-write sessions.

## Configuration and HTTPS

Integration flags remain false in examples. When explicitly enabled, unsafe or
incomplete configuration stops backend startup before schema/bootstrap work.
Disabled native startup is unchanged. PIQ also requires the dedicated CRM sender
configuration; partial enabled federation-only configuration is not ready.

RMR required settings:
`RMR_BASE_URL`, `RMR_COOKIE_SECURE=true`, `RMR_SECRET_KEY`,
`RMR_PROSPECTIQ_BASE_URL`, `RMR_PROSPECTIQ_INTEGRATION_INSTANCE_ID`,
`RMR_PROSPECTIQ_ASSERTION_ISSUER`, `RMR_PROSPECTIQ_ASSERTION_AUDIENCE`,
`RMR_PROSPECTIQ_CALLBACK_URL`, `RMR_PROSPECTIQ_SIGNING_PRIVATE_KEY_FILE`,
`RMR_PROSPECTIQ_SIGNING_KEY_ID`, `RMR_PROSPECTIQ_HMAC_KEY_ID`,
`RMR_PROSPECTIQ_HMAC_SECRET`, `RMR_PROSPECTIQ_CRM_KEYS_JSON`.
Optional rotation ring: `RMR_PROSPECTIQ_HMAC_KEYS_JSON`.
TTL: `RMR_PROSPECTIQ_GRANT_MAX_SECONDS`.

PIQ required settings:
`RMR_BASE_URL`, `RMR_PIQ_ORIGIN`, `RMR_INTEGRATION_INSTANCE_ID`,
`RMR_FEDERATION_ISSUER`, `RMR_FEDERATION_AUDIENCE`,
`RMR_REGISTERED_CALLBACK_URL`, `RMR_FEDERATION_PUBLIC_KEY_FILE`,
`RMR_FEDERATION_KEY_ID`, `RMR_PARTNER_HMAC_KEY_ID`,
`RMR_PARTNER_HMAC_SECRET`, `RMR_CRM_HMAC_KEY_ID`, `RMR_CRM_HMAC_SECRET`,
plus normal native production JWT/DB/Redis configuration.
Optional rotation ring: `RMR_FEDERATION_PUBLIC_KEYS_JSON`.
TTLs: `RMR_BRIDGE_ACCESS_SECONDS`, `RMR_BRIDGE_IDLE_SECONDS`,
`RMR_BRIDGE_MAX_SECONDS`.
Workers need the corresponding current grant-check HMAC sender, instance,
RMR URL and PIQ origin; authority is freshly checked before bridge jobs execute.

Use separate HTTPS HOSTNAMES, not different ports on one hostname. Exact issuer,
origin and registered root callback must agree at both ends. Browser API requests
must be same-origin under PIQ /api. An IP/HTTP/port-only production arrangement
is not supported. Proxies must preserve Origin and the signed full lookup path
and query; do not reorder/normalize its query or log authentication headers.
Production certificates must validate normally. No TLS-verification bypass
was added. Disposable proofs use private test names and an ephemeral trusted CA.

## RSA federation key rotation

1. Generate a dedicated RSA >=2048-bit signing key outside Git. Mount its private
   part ONLY at RMR. PIQ accepts public PEM only and rejects private PEM.
2. Add the NEXT public key at PIQ under a unique kid in
   `RMR_FEDERATION_PUBLIC_KEYS_JSON`. Entry shape:
   `{"next-id":{"file":"/run/keys/next-public.pem","not_after":<Unix seconds>}}`.
   The timestamp must be finite and no more than 24 hours ahead.
3. Restart/reload configured PIQ processes as necessary; verify local readiness.
   Then switch RMR signing file and kid together.
4. Promote the new PIQ primary file/kid and keep the previous public key as a
   bounded overlap entry. Never duplicate the primary kid in the ring.
5. After all old assertions expire (30s plus allowed clock skew/in-flight margin),
   remove the old entry/file. Unknown/expired/retired kids fail closed.

At most three overlap keys accompany the primary key. Existing bridge sessions
renew through HMAC/current RMR authority, not by replaying federation assertions;
RSA rotation does not extend or replace them. Keep clocks synchronized.

## Directional HMAC rotation

Grant exchange/check uses PIQ `RMR_PARTNER_HMAC_*` -> RMR
`RMR_PROSPECTIQ_HMAC_*`. CRM delivery/status uses separate PIQ
`RMR_CRM_HMAC_*` -> RMR `RMR_PROSPECTIQ_CRM_KEYS_JSON`.
Do not reuse native session, federation or the other service's secret.

RMR receiver rings accept one permanent active string secret plus up to three
bounded overlap entries shaped `{"secret":<secret>,"not_after":<Unix seconds>}`.
Never put real values in documentation, arguments visible to users, or Git.
Overlap is <=24h, expired entries are ignored, retired/unknown IDs are rejected.
For the grant-check ring the legacy active ID/secret is the fallback entry;
for CRM the active entry lives in the JSON ring itself.

Stage next verification entry at RMR, switch the ONE sender key at PIQ backend
AND worker, promote new permanent receiver key, retain old bounded overlap only
as long as needed for in-flight requests/retries, then explicitly retire it.
Signed method/path/body/instance/kid/timestamp/nonce stay bound. Nonce replay
protection is unchanged. Authenticated key IDs appear in RMR nonce/audit records
and structured integration logs, never values/signatures.

## Reconciliation and operator controls

The durable PIQ SQL outbox still sends three bounded attempts with a fenced
30-second lease. Its dispatcher runs in the backend process, not a new service.
UI states: Pending, Sending, Retrying, Moved to RMR CRM, Needs reconciliation,
Transfer failed. Success links to the stored Lead; unknown outcomes never offer
a new parallel handoff.

Signed GET `/api/integrations/prospectiq/v1/crm/handoffs/<public UUID>` verifies
service HMAC over the full raw query and empty body. It compares canonical
instance/mapping/version/client/original grant/event/payload hash and existing
receipt. It returns accepted, not_found, conflict or tombstoned, not prospect data.
An expired original session may reconcile an EXISTING accepted receipt; this
cannot create anything or restore authority. Suspended/remapped mappings deny lookup.

Trusted server-console commands, from the PIQ backend with its normal safe
environment/secret mounts (no identity/tenant/destination override):

```text
node src/rmrIntegration/operationsCli.js health
node src/rmrIntegration/operationsCli.js list
node src/rmrIntegration/operationsCli.js reconcile <handoff UUID>
node src/rmrIntegration/operationsCli.js retry <handoff UUID> --confirm
node src/rmrIntegration/operationsCli.js revoke <bridge-session UUID> --confirm
node src/rmrIntegration/operationsCli.js cleanup --confirm
```

List returns at most 100 recent scoped handoffs with status, attempts, safe error,
timestamps, stable prospect/event and RMR Lead IDs; no payload/evidence/secrets.
Reconcile takes a SQL lease also respected by delivery. Accepted stores the
original Lead/URL and succeeds. Not-found alone NEVER sends. Retry additionally
requires current ORIGINAL actor/session/grant/mapping/client/capability and lead
eligibility, then allows up to three more attempts with a hard total ceiling of
six. It never changes the public identity, event, actor, destination or snapshot.
Conflict/tombstone stops; no automatic replacement identity or record.

For RMR local maintenance:

```text
python -m rmr_platform.cli bridge-health
python -m rmr_platform.cli bridge-cleanup
```

These commands require trusted OS access, not browser roles. No new operator web
bypass or scheduler was introduced. Schedule explicit maintenance under the
existing deployment operator's controls only after approval.

## Readiness, logs and retention

Local-only health:
RMR `/api/integrations/prospectiq/v1/health`;
PIQ `/api/integrations/rmr/v1/health`.
States are disabled / ready / not_ready (503). RMR reports signing/HMAC config,
DB and mapping availability. PIQ reports endpoint/key/sender config, DB and
Redis ping (bounded queue wait). No remote RMR/provider call is made by health.
These are dependency/config checks, not a substitute for a controlled launch.

Privileged PIQ health CLI adds counts by handoff state, oldest age, unknown count,
reconciliation count and last safe failure category. Structured events cover
delivery, reconciliation and enabled-runtime DB disconnects. Configure the
`rmr.bridge` logger at INFO if grant-service authentication key-ID logs are wanted.
Never collect cookies, bearer/refresh tokens, codes, HMAC signatures or private
prospect payloads in operational logs.

Cleanup deletes expired replay nonces and pending grants whose code expired more
than one day ago. Consumed grants >30 days beyond absolute expiry retain identity/
attribution but lose PKCE/state/nonce/browser hashes. PIQ expires inactive sessions,
clears renewal/revoke-only hashes, and deletes >30-day-expired sessions ONLY when
unreferenced by handoffs/jobs/discovery/research runs. Successful handoff safe
error metadata is cleared after 90 days. Failed safe errors remain bounded current
fields, not an unbounded history table.
Durable CRM receipts, events, handoffs and external-identity tombstones are NEVER
aged out. Business evidence retention is unchanged.

RMR migration `005.012.000-prospectiq-operations` adds expiry and browser-logout
indexes. PIQ additive bootstrap adds refresh/idle/generation/revoke-grace columns,
reconciliation metadata, retry ceiling and idle/instance-status-due indexes.
Existing unique identity/code/grant/prospect/event/session indexes remain.
PostgreSQL index inspection covers actual lookup paths; no speculative tuning
or capacity claim is made.

## Failure behavior and proof

RMR unavailable: renewal/privileged actions fail closed, credentials do not rotate
on failed authorization, and UI offers a safe return or reload after recovery.
PIQ restart: durable sessions/outbox remain; browser reload renews.
Sending lease lost at restart: fenced retry or explicit receipt reconciliation,
never duplicate identity. RMR restart after commit: same receipt/Lead survives.
Redis/BullMQ restart: native mock workflows recover; CRM SQL outbox does not
depend on Redis for delivery identity.
DB statement failure rolls back refresh. A targeted terminated idle connection
initially exposed an unhandled pg pool event. Phase 4 adds sanitized pool handlers
only for integration-enabled backend/workers; pg discards/replaces broken idle
clients. No business/provider algorithm changed. Actual disconnect/reconnect
and browser recovery were verified, not just mocked.

Concurrency tests cover ten refreshes, refresh vs operator AND cookie logout,
reconciliation vs delayed delivery, two dispatchers, and concurrent HMAC rotation.
No duplicate session/Lead/accepted handoff, stale overwrite or privilege increase.
Multi-tenant managed-session proof respects RMR's existing membership model.

### Verification executed

All source mounts readonly; tests used disposable PG16 schemas, an internal-only
Docker network, synthetic accounts/keys and private HTTPS names. No production
environment file, database, key or installed runtime was used.

- RMR full: `python -B -m pytest -q -p no:cacheprovider` -- 535 passed,
  3 existing legacy-packaging deselections, one Starlette/AnyIO deprecation warning.
- RMR PG: `scripts/test_prospectiq_federation_postgres.py`,
  `scripts/test_prospectiq_capabilities_postgres.py`,
  `scripts/test_prospectiq_crm_postgres.py`,
  `scripts/test_prospectiq_operations_postgres.py` (run together with pytest) -- 91 passed.
- PIQ PG: `node --test tests/rmrIntegration.postgres.test.js
  tests/rmrFederation.postgres.test.js tests/rmrCapabilities.postgres.test.js
  tests/rmrCrm.postgres.test.js tests/rmrOperations.postgres.test.js` -- 128 passed.
- PIQ offline: native target-profile-status + ten maintained adaptive
  research scripts selected for regression, `rmrFederation.test.js` and
  `rmrIntegration.test.js` -- 27 top-level tests passed (script subchecks included).
- Vite production build passed. Existing duplicate `canConfirm` JSX warning in
  native Leads.jsx was not changed in this phase.
- Actual browser: `test_federation_operations_browser.py before/outage/after`,
  `test_federation_workflow_browser.py`, `test_federation_crm_browser.py`.
  Native login/client selector and optional-secret generic webhook still work.
  Synthetic receiver count: ONE Lead, ONE receipt, ONE event; zero Account,
  Contact or CRM Opportunity conversion.

Phase 4 runtime fixtures:
RMR `federation_operations_proof.py init/rmr/public/inspect`;
PIQ `federation_operations_runtime.js`,
`federation_operations_worker.js`, `federation_operations_control.js`.
Use only private `phase41-postgres` / `phase41_test` and the hardcoded isolated
`rmr_operations_proof` / `piq_operations_proof` schemas. RMR restart seeds only
a new schema. Mount the PIQ/worker/mock provider at proof volume subpath `piq`;
that contains PUBLIC verification PEM/CA and PIQ-only synthetic credentials,
not the RMR private signing key or RMR browser password.
Generated browser state, keys, DBs and screenshots are never repository files.
Destroy only these disposable resources after exporting sanitized proof results.

Native generic CRM's pre-existing optional-secret column naming discrepancy
(`outcome_webhook_secret` vs legacy `outcome_secret`) remains outside this phase;
the native optional-secret path was tested. No claim is made about repairing it.

## Production prerequisites still pending approval / verification

No VPS or production configuration was inspected or changed in this phase.
Before pilot activation, separately provision/verify both distinct HTTPS DNS
names/certificates/proxy routes, exact callback/issuer/audience/instance bindings,
dedicated secret mounts and RSA/HMAC rotation procedures, production DB/Redis
durability/backups, explicit RMR migration and PIQ additive schema bootstrap,
canonical tenant-client mappings/entitlements/managed-role access, synchronized
clocks, maintenance/log monitoring ownership and recovery drills.
Supply correct native production security settings as well as bridge settings.
Then obtain explicit deployment/activation approval; flags remain OFF until then.
This document is not a deployment authorization or a capacity certification.
