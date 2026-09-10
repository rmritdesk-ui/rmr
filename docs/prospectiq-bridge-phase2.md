# Phase 2: tenant-bound ProspectIQ capabilities

Scope: Phase 2 only, built on RMR ecb9f24 and PIQ c182fcf. Flags remain off by
default. No CRM delivery, provider algorithm changes, deployment or push.

## Capability policy

RMR is the maximum authority; PIQ independently checks client and resource
ownership. No RMR role becomes PIQ global admin.

| RMR role/context | Read | Create / update own | Manage mapped workspace profiles | Discovery | Research + cost confirmation | Export |
| --- | --- | --- | --- | --- | --- | --- |
| CLIENT_ADMIN | yes | yes | yes | yes | yes | yes |
| VP_SALES | yes | yes | no | own profiles | no | yes |
| SALES_MANAGER | yes | yes | no | own profiles | no | yes |
| SALES_REP | yes | yes | no | own profiles | no | yes |
| MARKETING_USER | yes | no | no | no | no | no |
| EXECUTIVE_VIEWER | yes | no | no | no | no | no |
| RMR_OWNER / STEP2_ADMIN, no managed session | yes, existing tenant-access rules | no | no | no | no | no |
| RMR_OWNER / STEP2_ADMIN, valid managed_write | yes | yes | mapped tenant only | yes | yes | yes |

Operational names:
- prospects.read
- profiles.create
- profiles.update_own
- profiles.manage_workspace
- discovery.run
- research.run
- research.confirm_cost
- prospects.export

The legacy contract enum still recognizes profiles.manage_own / crm.transfer
for compatibility with dormant Phase 0 contracts. Neither is granted here;
PIQ runtime capability validation rejects them.

Policy was checked against permissions.py (CLIENT_OPERATION_WRITERS,
require_tenant_access, require_client_operational_write) and the existing
native research access helper. No team hierarchy is invented. Marketing and
executive roles remain read-only. Native research spend remains client-admin
or valid tenant-bound managed-write authority.

Phase 1 required managed context even for global read entry. Phase 2 explicitly
allows read-only global entry where existing RMR tenant-access rules allow it,
as requested. An explicitly supplied invalid/wrong-user/wrong-tenant/expired
managed-write context still fails; it never silently becomes read access.

## Grant and recheck

capabilities_for derives the snapshot server-side at launch. No requested
frontend capability is trusted. Existing authorization grants persist the
snapshot; RS256 assertion and grant-check context carry that exact snapshot.
No new RMR database schema is needed.

Every grant check validates the active user, role, tenant, entitlement, mapping
status/version, absolute expiry and managed session, then derives current
maximum capabilities. Losing any snapshotted capability invalidates the grant.
Gaining authority cannot upgrade an old session; relaunch is required.

The existing one-time code, PKCE, nonce/replay checks, backend-only assertion
exchange, signature/HMAC checks and local logout remain unchanged. Maximum
bridge lifetime is five minutes, additionally bounded by managed-session expiry.
No refresh token or longer session was introduced.

## PIQ enforcement and background work

See the companion PIQ documents:
docs/rmr-bridge-phase2-route-audit.md and docs/rmr-bridge-phase2.md.

PIQ checks fresh RMR authority on every bridge request (no read cache), then
capability + exact client + resource ownership before its original handler.
Profile Intelligence, a prerequisite for original discovery, requires
discovery.run and repeats a fresh check before each of its two existing AI calls.

Bridge jobs persist the session, actor, client, profile, required capabilities
and canonical payload digest within the existing run transaction. At each
worker attempt they recheck local session/resource state and fresh RMR authority
before reaching the existing provider boundary. Native jobs keep native behavior.

Revocation stops new requests/worker attempts. An already-started provider
attempt can complete under existing worker timeouts; authorization is not checked
at every provider step. An expired browser must relaunch from RMR to read results.
Five-minute session UX and any production refresh design remain future work.

## Verification

Provider-safe proof uses disposable PostgreSQL 16, SQLite, Redis, a private
internal Docker network without host ports, separate HTTPS rmr.test / piq.test
origins, ephemeral keys and read-only source mounts. Never use installed data.
The fake Python discovery boundary returns explicit synthetic prospects; real
queues, workers, persistence and original UI are exercised. Existing mock
Adaptive Research remains unchanged and does not display mock findings as facts.

Commands inside the guarded test images:
- pytest tests -q --tb=short -p no:cacheprovider
- pytest scripts/test_prospectiq_capabilities_postgres.py
  scripts/test_prospectiq_federation_postgres.py
  scripts/test_prospectiq_bridge_postgres.py
  scripts/test_piq_workflow_postgres.py -q --tb=short -p no:cacheprovider
- python -B scripts/test_federation_workflow_browser.py

Full RMR suite: 483 passed, 3 historical legacy_packaging checks deselected,
one existing Starlette/AnyIO deprecation warning. Combined PostgreSQL suite:
53 passed, same warning. Focused SQLite capabilities/federation/bridge:
50 passed. PostgreSQL scripts require the existing guarded phase41-postgres /
phase41_test disposable host, username and database; never an installed DSN.

Proof helpers: scripts/federation_workflow_proof.py (init/rmr),
scripts/test_federation_workflow_browser.py, and PIQ backend/tests/federation_*
workflow/mock helpers. /proof must be a fresh dedicated volume. Init generates
private ephemeral fixture material; do not copy fixture.json or signing/TLS keys
into Git. The browser saves only sanitized results/screenshots alongside it.

No Phase 3 CRM endpoint or RMR Lead creation is implemented. Existing native
RMR PIQ, native standalone PIQ login and the generic native PIQ CRM webhook are
preserved.
