# RMR / standalone ProspectIQ federation - Phase 1

Status: implemented, disabled by default. This is a login and client-bound
**read-only** workspace bridge, not CRM handoff or spending authorization.

## Flow and trust boundaries

RMR login -> authorized tenant -> Open ProspectIQ -> original PIQ bootstrap
-> per-tab state, nonce and S256 PKCE -> same-origin RMR authorization landing
-> one-time code -> PIQ backend -> authenticated RMR exchange -> RS256 assertion
-> linked/JIT PIQ user -> PIQ-issued, single-client bridge session -> original UI.

The launch uses the same tab (no opener). RMR's Strict host-only cookie stays on
RMR. The landing page restores same-origin cookie eligibility without relaxing
cookie policy. The callback is exactly the configured PIQ HTTPS root; arbitrary
browser redirect URLs are not accepted. Codes travel in fragments, removed
immediately with history.replaceState. The signed assertion stays backend-only.

RMR checks active user, existing tenant authorization, both PIQ entitlements,
active canonical mapping and mapping version. Global RMR users additionally
need the existing active managed_write session for the same tenant and user.
Launch ownership is bound to both user ID and the initiating RMR cookie hash.

## Credentials, codes and assertions

- Separate HTTPS hostnames are mandatory; different ports on one host are rejected.
- Both feature flags remain false in the example configuration.
- Dedicated RSA signing key (minimum 2048 bits), RS256, explicit key ID and
  rmr-piq-federation-v1 header/payload type; exact issuer and audience.
- Dedicated backend HMAC-SHA256 credential, never either application's native
  session/password secret. Canonical request fields: instance, key ID, method,
  path, timestamp, nonce and SHA-256 raw-body digest, newline-separated.
  Timestamp tolerance is 30 seconds; a durable unique nonce blocks replay.
- Pending launch lifetime: up to 3 minutes. Issued code: random 32 bytes,
  SHA-256 hash only at rest, configured TTL capped at 60 seconds, S256 proof,
  state/nonce and context binding. Atomic conditional updates allow one winner.
- Assertion lifetime: at most 30 seconds; immutable RMR subject, tenant,
  client/mapping/version, grant, capabilities, authorization time, managed
  session limits, nonce hash and unique assertion ID are validated.
- No production secret or populated environment file is included.

RMR placeholders are in .env.example (RMR_PROSPECTIQ_*); PIQ placeholders are in
backend/.env.example (RMR_INTEGRATION_*, RMR_FEDERATION_*, RMR_PARTNER_HMAC_*,
RMR_BASE_URL, RMR_PIQ_ORIGIN and RMR_REGISTERED_CALLBACK_URL). Provision keys
outside Git, load their file paths, configure matching issuer/audience/instance,
and keep native authentication secrets separate. No real environments were edited.

## Identity, membership and authorization

The canonical identity is (RMR issuer, immutable RMR user ID), not email.
An existing explicit link is reused. Otherwise PIQ creates one externally
managed shadow user with an unusable local password; concurrent first access
is serialized by an advisory transaction lock plus unique constraints.
An unlinked email collision fails with identity_link_required; no silent merge.
Inactive identities/users/clients are rejected. Exact UUID client membership
is established; global RMR roles never become PIQ global admin.

A durable PIQ session records user, external identity, RMR tenant/grant,
mapping/version, client, capabilities, assertion ID, expiry and revocation.
PIQ signs its own distinct piq-rmr-bridge-v1 access token. Server-side middleware
validates it and the durable context, then rechecks the RMR grant on **every**
protected request, failing closed if RMR is unavailable or access changes.

Only prospects.read is granted. The central allowlist covers client list,
target profile/lead/profile-pull lists and owned object reads plus the narrowly
listed saved-intelligence suffixes. Lists receive the bound client, object IDs
and profile/run filters are checked against it, and arbitrary client switching
is denied. Unaudited routes and every non-GET action except PIQ logout are
denied before existing handlers. Existing profile ownership checks still run.
The playbook GET that can seed defaults is not invoked for bridge lead detail.

## UI, expiry and logout

The existing RMR PIQ UI retains all native functionality and gets an additive,
authorized Open ProspectIQ button only when configured/enabled. PIQ uses its
original shell, exact server-selected client and disabled client dropdown.
Native PIQ login and native multi-client behavior remain available.

Access tokens are in React memory only; there is no bridge refresh token.
Temporary state/nonce/PKCE material is tab-scoped and removed on exchange;
only a non-secret RMR return URL remains as a reload hint. Absolute bridge
lifetime is the earliest of five minutes from launch, RMR login expiry and
managed-session expiry. Reload/expiry requires returning through RMR.
UI Signout revokes this PIQ session and clears local authentication, without
logging out of RMR. RMR logout revokes grants for its current browser cookie.
There is no cross-app Single Logout network dependency.

Phase 1 does not redesign original lead/profile screens: some native mutation
controls remain visible but the bridge server rejects them. The shell clearly
labels the session read-only. Capability-aware action presentation belongs
with the approved Phase 2 permission work, not new spending grants here.

## Minimal additive Phase 0 corrections

RMR migration 005.010.000-prospectiq-federation adds nullable browser/session,
state and nonce hashes, authorization timestamp, absolute expiry and destination.
Phase 0 did not contain enough browser binding/absolute lifetime information.
Old grants with missing context cannot become valid Phase 1 sessions.

PIQ's existing bootstrap adds users.externally_managed (false for existing
native users), session tenant/assertion/context columns and a unique assertion
ID index. Old incomplete sessions fail closed. No native account is relabeled.
The v1 contracts add missing binding/context fields and allow RSA assertions
up to 8192 characters instead of the Phase 0 512-character opaque-code limit;
session refresh is explicitly null. Shared fixture copies remain identical.

Disabling both flags restores native-only entry behavior and rejects bridge
credentials; additive schema can remain in place. Do not drop populated
integration tables or roll production databases back as part of this phase.

## Verification and reproducible test sources

All database tests used temporary SQLite or private PostgreSQL 16 schemas;
all keys/passwords were generated synthetic fixtures. No installed runtime,
Product Owner database, production database or real provider was used.

- RMR full suite: 467 passed, 3 legacy_packaging tests deselected by existing
  pyproject configuration; one existing Starlette/AnyIO deprecation warning.
- RMR Phase 1/foundation/release PostgreSQL gate: 37 passed.
- RMR existing PIQ concurrency/workflow PostgreSQL gate: 21 passed.
- PIQ 11 existing offline regression scripts plus unit/contracts: 27 Node
  test entries passed (the scripts contain additional internal assertions).
- PIQ PostgreSQL federation/foundation: 25 Node entries passed, including
  signature validation, JIT concurrency, isolation, revocation and expiry.
- Original Vite frontend built offline. Pre-existing duplicate canConfirm
  JSX warning in Leads.jsx remains unchanged.
- Actual Chromium proof: separate rmr.test / piq.test HTTPS origins, original
  applications, no second PIQ password, Client A only, rendered lead detail,
  Client B query/body/object/profile attempts rejected (403), mutation routes
  rejected before handlers, consumed callback rejected, UI Signout revocation,
  RMR login retained, safe reload, native password login with two memberships,
  no RMR cookie/assertion exposed to PIQ browser and no bearer in URLs/storage.

Sources: RMR tests/test_prospectiq_federation.py and
scripts/test_prospectiq_federation_postgres.py; PIQ
backend/tests/rmrFederation.test.js and rmrFederation.postgres.test.js.
RMR scripts/federation_proof_runtime.py and test_federation_browser.py plus
PIQ backend/tests/federation_proof_runtime.js implement disposable actual-app
fixtures and browser assertions.

Run pytest with -p no:cacheprovider and a temporary --basetemp; set RMR_DATA_DIR
and RMR_DATABASE_URL to disposable locations, disable auto seed/migrate/workers
and live providers except explicit fixture migrations. PostgreSQL test scripts
require host phase41-postgres, user/database phase41_test; set
RMR_PHASE41_POSTGRES_TEST_URL (and RMR_DATABASE_URL) on RMR, and
RMR_BRIDGE_TEST_DATABASE_URL on PIQ. Never substitute an installed database.

The browser harness requires a private Docker network, a fresh /proof volume,
PostgreSQL 16, Redis, the two actual applications and the generated nginx TLS
proxy. No host ports are needed. Build original frontend assets into
/proof/piq-dist with VITE_API_BASE_URL=/api and empty Stripe publishable key.
Generate fixtures with the RMR helper's init mode, start RMR helper rmr mode
and PIQ proof runtime, then run test_federation_browser.py in Chromium.
The browser aborts all non-test-host requests (including existing external
font/Stripe script attempts); the private network also has no provider egress.
Allocate at least 2 GB temporary PostgreSQL storage for repeated schema-heavy
runs. An earlier 512 MB test volume filled its WAL; the affected suite passed
after recreating that disposable database. This was not an application defect.
Remove only the private test containers/volume/network afterward; never archive
the generated signing keys, credentials or fixture.json into Git.

## Before Phase 2

Obtain approval for the final capability/role matrix, audit additional routes
and their side effects before allowlisting, and align UI mutation affordances.
Provider spending/research authorization is not extended. Decide longer-lived
session/refresh policy only with equivalent bounded authorization guarantees.
Mapping/link administration, operational key rotation and replay-record
retention need operational policy before rollout. Existing Phase 0 CRM
contracts/outbox/receipt foundations remain dormant; no CRM handoff, delivery,
provider calls, deployment changes or pushes are included in Phase 1.
