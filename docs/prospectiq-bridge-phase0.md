# RMR / standalone ProspectIQ bridge — Phase 0, v1

Status: durable foundation only. Both feature flags default OFF. No integration
routes, redirects, token issuance, provisioning, delivery workers, or network
clients are implemented. Setting a flag to true still activates nothing in this
phase. Existing native RMR PIQ and standalone login/generic CRM webhook remain
in place.

## Ownership

| Authority | Owned data and workflows |
| --- | --- |
| RMR | Users, tenants, roles/access, entitlements, canonical tenant/client mapping, accepted CRM lead and downstream CRM lifecycle |
| Standalone PIQ | Full PIQ UI, target profiles, discovery, matching/scoring, evidence, Adaptive Research, pre-CRM prospects, provider usage/history and outbound CRM handoff status |

Separate databases, cookies and services. No iframe, shared DB access, discovery
engine synchronization, or external identity provider. Remote IDs are immutable
references, not foreign keys into another database. Names and email addresses
never establish tenant or user identity.

## Durable records

RMR migration `005.009.000-prospectiq-bridge-foundation` registers four tables
through the existing SQLAlchemy/custom migration ledger:

- `prospectiq_client_mappings`: unique instance/client and instance/tenant,
  status pending/active/suspended, version and approval actors.
- `prospectiq_authorization_grants`: user, canonical context, mapping-version
  snapshot, SHA-256 code hash, expiry/consumption/revocation, S256 challenge,
  binding reference, capabilities and optional managed-session constraint.
- `prospectiq_crm_receipts`: unique instance/public prospect ID and instance/event
  ID; nullable accepted CRM ID, attribution and retained provenance.
- `prospectiq_replay_nonces`: unique instance/service/nonce hash across key
  rotation; key ID, signed request timestamp and expiry.

The instance/tenant uniqueness deliberately applies to pending and suspended
rows too: keep one canonical record, do not create competing mappings. Any later
remapping requires explicit governance, a version change and grant invalidation;
Phase 0 does not implement it. Composite foreign keys prevent grant/receipt
context from naming another tenant or PIQ client. Mapping-version snapshots are
not live foreign keys: later authorization must compare them with the current
mapping version. Grants and receipts retain their mapping; a removed CRM lead
does not delete its receipt.

PIQ follows its existing additive `ensure...Schema(pool)` startup convention,
using `backend/src/rmrIntegration/schema.js` (no new migration framework):

- `rmr_external_identities`: unique (RMR issuer, immutable RMR user UUID),
  references an existing PIQ user; no email key or JIT provisioning.
- `rmr_bridge_sessions`: identity/user composite FK, distinct client-bound
  context per launch, RMR grant/mapping/version, capabilities and absolute expiry.
  No user-global current tenant and no native role/admin assignment.
- `rmr_crm_handoffs`: one row per integration instance/public prospect UUID,
  immutable payload snapshot/hash, event, session/grant attribution, retry state,
  safe error and future RMR result. Composite FK prevents mismatched session
  context. Optional internal lead reference may be cleared without losing
  idempotency identity. No delivery loop is connected.

Schema stores are foundations, not authorization enforcement. Future write
services must validate UUIDs, digest encodings, transitions, immutable identity
bindings, context/version, capabilities and payload ownership before writes.
A hash-length constraint alone is not proof that input was hashed.

## Configuration

RMR: `RMR_PROSPECTIQ_BRIDGE_ENABLED=false`, `RMR_PROSPECTIQ_BASE_URL`,
`RMR_PROSPECTIQ_INTEGRATION_INSTANCE_ID`,
`RMR_PROSPECTIQ_AUTHORIZATION_CODE_TTL_SECONDS=60` (bounded 1–60),
`RMR_PROSPECTIQ_ASSERTION_ISSUER`, `RMR_PROSPECTIQ_ASSERTION_AUDIENCE`.

PIQ: `RMR_INTEGRATION_ENABLED=false`, `RMR_BASE_URL`,
`RMR_INTEGRATION_INSTANCE_ID`, `RMR_FEDERATION_ISSUER`,
`RMR_FEDERATION_AUDIENCE`.

All other values default empty. No secrets are needed or reused. The PIQ config
reader is lazy, matching the existing dotenv order. No new setting is required
for disabled startup. Schema upgrade remains the normal deployment prerequisite:
RMR's explicit-migration startup mode requires the new migration head; PIQ's
existing bootstrap creates its additive tables. No installed database was
migrated as part of this implementation.

## v1 contracts (descriptions only, NOT registered endpoints)

Both repositories contain identical wire shapes in native Pydantic/Zod forms.
Matching synthetic fixtures exercise all nine request/response pairs. Unknown
fields are rejected; v1 defaults to `version: "1"`. IDs are UUIDs except opaque
deployment instance/issuer/audience/callback/binding identifiers. Timestamps on
the wire are UTC Unix seconds; database timestamps are timezone-aware.

| Future owner/method/path | Request / response | Future authorization |
| --- | --- | --- |
| RMR POST /api/integrations/prospectiq/v1/launch | LaunchRequest / LaunchResponse | RMR session + CSRF + tenant entitlement |
| RMR POST /api/integrations/prospectiq/v1/authorize | AuthorizeRequest / AuthorizeResponse | Bound launch transaction + fresh RMR authorization |
| RMR POST /api/integrations/prospectiq/v1/exchange | ExchangeRequest / ExchangeResponse | PIQ service identity + one-time code + S256 |
| RMR POST /api/integrations/prospectiq/v1/grants/check | GrantCheckRequest / GrantCheckResponse | PIQ service identity |
| RMR POST /api/integrations/prospectiq/v1/crm/leads | CrmLeadRequest / CrmLeadResponse | PIQ service identity + valid actor grant |
| RMR GET /api/integrations/prospectiq/v1/crm/handoffs/{external_id} | HandoffLookupRequest / CrmLeadResponse | PIQ service identity + authorized mapping context |
| PIQ POST /api/integrations/rmr/v1/session/exchange | ExchangeRequest / SessionResponse | Server-bound launch transaction |
| PIQ POST /api/integrations/rmr/v1/session/refresh | SessionRefreshRequest / SessionResponse | Context-bound refresh proof + fresh grant check |
| PIQ POST /api/integrations/rmr/v1/crm/handoffs | HandoffRequest / HandoffResponse | PIQ context + crm.transfer + client access |

Code module names use PascalCase in RMR and camelCase in PIQ. The lookup
`external_id` is the stable PIQ public prospect UUID, never its event UUID.
Service identity determines the integration instance on GET; no tenant ID is
accepted as routing authority. Exact browser choreography will be implemented
and reviewed in Phase 1; there is no general redirect URL field.

Launch selects a mapping and allowlisted destination (`prospects` or
`target_profiles`). Authorize binds a registered callback ID, state, nonce and
S256 challenge. Exchange transports the code/verifier transiently; logging must
redact them. Only a SHA-256 digest is stored. The binding reference identifies
server-held state/nonce, not a URL. AssertionClaims specifies issuer, audience,
subject, unique ID, issue/expiry, nonce, type and grant context; it does NOT
verify signatures or authorize anything in Phase 0.

Session responses describe future PIQ credentials bound to a bridge session, not
RMR cookies or RMR native session tokens. Capabilities are a bounded allowlist;
no admin role exists. Later services must require assertion sub == rmr_user_id,
iat < exp <= absolute expiry, active grant context and current mapping version.
Response status/context/result consistency is likewise a future service
invariant; the current models validate wire structure only.

CRM input includes canonical mapping reference/version, PIQ client/public UUID,
event, actor grant and bounded prospect/evidence snapshot. No browser-supplied
RMR tenant/user ID, arbitrary destination URL, RMR score or overwrite switch.
RMR derives tenant and actor from trusted context and validates PIQ ownership.
PIQ scores are labeled provenance, not RMR qualification decisions. Email/phone
may be absent; do not fabricate contact details. Evidence URLs are data, not
permission to fetch them.

Later acceptance must atomically create one CRM destination and receipt;
retries return the original result. Never silently overwrite existing CRM data.
Deleted destinations must leave tombstones and never auto-recreate. The relative
CRM path is response-only and must be generated by RMR; PIQ resolves it against
the registered RMR origin, never an arbitrary browser redirect.

## Security boundary required before Phase 1 activation

- Provision distinct bridge signing keys (planned RS256) and per-direction
  service HMAC keys; never reuse RMR_SECRET_KEY or native PIQ JWT keys.
- Exact issuer/audience/type/algorithm/nonce validation, jti replay protection,
  atomic one-time code consumption and short expiry (at most 60 seconds).
- Server-held state/nonce binding, S256 verification and exact registered
  callback/origin allowlists; no open redirect or browser-chosen service origin.
- HMAC binds service, key ID, method, canonical path, timestamp, nonce and body
  digest. Enforce freshness and atomically consume service nonce; key rotation
  must not allow replay. No HMAC implementation exists yet.
- Recheck active user, entitlement, role/capability, mapping version/status and
  managed-session expiry. PIQ must enforce each action and client-bound context;
  never translate a federated user into native PIQ admin.
- Separate HTTPS hostnames for cookie isolation; ports alone do not isolate
  cookies. Decide session revocation/refresh and cross-tab behavior explicitly.
- Retention, tombstoning, retry leases and safe error redaction must be specified
  before enabling delivery. No payload/provenance should hold session secrets.

## Upgrade, rollback and tests

Only additive tables are created; no existing user/password/provider data is
rewritten. RMR migration helper can target a supplied engine and is idempotent.
PIQ schema helper is likewise idempotent. Both can be tested independently.

Rollback: disable the flags, roll back application code, leave the unused
additive tables and ledger row intact. Existing migration conventions are
forward-only; no destructive down migration is introduced. Do not drop a table
once it contains grant, replay or receipt history without a reviewed retention
plan. No deployment, Docker configuration, existing auth/UI or provider logic
is changed by this phase.

RMR: `tests/test_prospectiq_bridge.py`, full existing tests, plus
`scripts/test_prospectiq_bridge_postgres.py` and existing PostgreSQL suites.
PIQ: `node --test backend/tests/rmrIntegration.test.js` and guarded
`rmrIntegration.postgres.test.js`. PostgreSQL tests require a disposable PG16
service named `phase41-postgres`, user/database `phase41_test`; do not use an
installed database. Contract fixtures are synthetic and not login credentials.
