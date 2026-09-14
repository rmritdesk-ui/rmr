# Dynamic workspace provisioning (Prompt 2)

Availability GET stays read-only. For an authorized unprovisioned tenant it
returns `enabled:true,status:unprovisioned,can_provision:<boolean>`; the launcher
uses POST `/api/integrations/prospectiq/v1/provision` with
`{"version":"1","tenant_id":"<immutable RMR tenant UUID>"}`.

The POST requires the normal RMR session, exact browser Origin/X-RMR-Request,
bridge enabled, tenant access, both piq_access/piq_enhancement entitlements and
profiles.create capability. Existing managed-write authorization is preserved.
RMR reads the display name from its database. It signs a backend-only request to
PIQ with the existing grant/check HMAC, never the separate CRM secret.

Existing active mappings are returned untouched WITHOUT contacting PIQ. Pending,
suspended, unknown or conflicting mappings fail closed. No name/email matching,
adoption, mapping replacement or new native PIQ administrator privileges.

For new mappings PIQ owns the client UUID and idempotency ledger. After the
remote response, RMR rechecks authority under a tenant-row PostgreSQL lock or
SQLite BEGIN IMMEDIATE, then commits one canonical mapping and audit event.
Existing uniqueness constraints remain unchanged. No RMR migration is needed:
the PIQ ledger is the remote commit record, the canonical mapping the local one.
A lost response/local transaction failure is retried by resolving the same
external identity. Suspensions and cross-tenant client conflicts are not retried
as replacement creation. Automated mappings record their initiating RMR user
and authorized-first-use audit policy; they do not fabricate a human approver.

Deployment prerequisite: upgrade PIQ and apply its existing additive schema
initializer before enabling this RMR UI. The PIQ side adds external-workspace
and replay-nonce tables. Use existing configured origins/instance/issuer and
grant key ID/secret; no new credentials or production values in this change.
The provisioning endpoint accepts the currently configured grant key only;
coordinate rotation on both sides. Feature flags remain the rollback boundary.

Focused tests: `tests/test_prospectiq_provisioning.py` (SQLite) and
`scripts/test_prospectiq_provisioning_postgres.py` (PG16). For PostgreSQL set BOTH
RMR_DATABASE_URL and RMR_PHASE41_POSTGRES_TEST_URL to the guarded disposable
phase41-postgres / phase41_test database; do not combine database modes in one
test process. Optional RMR_WORKSPACE_FIXTURE_URL=http://workspace-fixture:4000
exercises the real PIQ HMAC endpoint and RS256/JIT service on an internal test
network. The fixture must never be deployed or exposed publicly.

Prompt 3 remains separate: profile bootstrap automation, completion tracking and
profile lifecycle improvements. This change does not import profiles, change
discovery/research/CRM or relax identity_link_required. Existing reviewed manual
mappings need no external-ledger adoption to keep working.
