# Initial Target Profile onboarding (Prompt 3)

## Runtime contract and authority

The normal bridge page first resolves/provisions the workspace using Prompt 2,
then POSTs `/api/integrations/prospectiq/v1/profiles/bootstrap` with only
`tenant_id` (and optional version `1`). The authenticated RMR user, same-origin
request, tenant access, operational role/managed session and PIQ entitlements are
checked using existing bridge authorization. Initial import requires
`profiles.create`; read-only users can re-enter an already completed workspace.
The browser cannot supply a PIQ client, mapping, source profiles, issuer or URL.

RMR signs a status request to PIQ `/api/integrations/rmr/v1/profiles/bootstrap`.
Only if the durable result is not completed does it read eligible RMR profiles
and sign an import request. PIQ calls the signed RMR `/mappings/check` endpoint to
verify the current active mapping UUID/version, tenant UUID, client UUID and
instance. Both directions use existing method/path/body-bound HMAC and durable
nonce replay protection. Responses are no-store; errors do not echo raw payloads,
secrets, database details or stack traces. Request size is capped at 64 KiB;
larger exports fail visibly, never silently truncate.

The profile serializer is shared with `scripts/export_piq_profiles.py`. The PIQ
converter/importer is the existing `profileBootstrap.js`; no second conversion
implementation or temporary runtime files are introduced. The low-level existing
federation launch/authorize/exchange contracts remain unchanged; the normal RMR
launcher gates its Open action on preparation completing.

## Eligibility and authority after completion

`PiqTargetProfile.active` is the real domain status: the native RMR archive action
sets it false. Automatic bootstrap selects only `active=true` rows belonging to
the authorized tenant. PIQ rechecks this policy and stores imported rows as
drafts. Missing questionnaire answers are not fabricated. The operator exporter
retains its historical all-profile behavior for explicit recovery work.

PIQ owns completion, keyed by `(issuer, integration instance, RMR tenant UUID)`,
bound to the immutable canonical mapping/client. No row means never attempted;
`failed` is retryable; `completed` is terminal, including zero eligible profiles.
Transactions serialize concurrent initialization and atomically commit profile
rows, the existing import ledger and completion. A crash before commit leaves
nothing partially imported; a lost response is recovered by the next status read.
An import failure rolls back its writes and persists a sanitized failed state.
No in-progress lease is needed for this synchronous transactional operation.

After completion RMR no longer reads profiles for bootstrap. PIQ edits, deliberate
clears and deletions remain authoritative. Later RMR additions/edits do not sync.
The existing immutable source ledger maps `(issuer, tenant UUID, source profile
UUID)` to the deterministic PIQ profile UUID and survives destination deletion.
Legacy manual mappings are adopted only after live canonical mapping verification,
not by email or name; legacy imported/deleted rows are recognized without
duplicates. Explicit operator repair remains narrow and is never exposed by the
runtime endpoint. No Kerry-specific identities are embedded.

## UI findings and scope

Baseline original UI/API tests reproduced delete-last -> New Profile -> draft
save -> reload -> edit -> delete -> recreate successfully for CLIENT_ADMIN and
native users. No backend creation defect was reproduced, and Dave's exact server
failure cannot be inferred from that observation. The confirmed clarity problems
were discarded API validation details and unclear native setup requirements.

New PIQ profiles remain native: name for a draft, twelve required questionnaire
answers for activation, then Generate Profile Summary to produce Profile
Intelligence and Discovery Strategy before Pull New Leads is enabled. No imported
ledger/provenance/readiness is forged. Final browser proof used the existing mock
AI provider for generation and never clicked Pull or Adaptive Research.

Target Profiles is first in PIQ navigation. Empty bridge workspaces land there;
existing profiles retain Leads landing. Late reads do not override user navigation.
Save failures expose only allowlisted field labels and actionable status guidance.

No RMR schema change. PIQ adds `rmr_initial_profile_bootstraps` through its existing
additive initializer. Deploying these changes later requires coordinated RMR/PIQ
versions and schema initialization; no deployment/configuration change was made
during this implementation. Prompt 4 and any further rollout/provider acceptance
remain a separate explicitly authorized scope.

## Verification

Final relevant regression results: 145 RMR SQLite tests, 129 RMR PostgreSQL tests,
11 launcher tests, and 218 PIQ offline/PostgreSQL tests passed. Browser acceptance
covered two baseline lifecycle journeys, two final lifecycle/readiness journeys,
and two fresh-tenant onboarding journeys. Frontend production build passed.
One parallel PIQ rerun hung in an existing HTTP test teardown; the complete serial
rerun exited cleanly. The build retains a pre-existing duplicate `canConfirm`
attribute warning in unrelated Leads bulk-outreach UI; it was not changed here.

- RMR: focused coordinator, active/archived/foreign eligibility, strict route
  contract, live mapping-check HMAC/replay and existing bridge regressions on
  disposable SQLite and PostgreSQL 16.
- PIQ: 2/5/8 concurrency, zero/one/multiple profiles, lost-response retry,
  edit/deletion preservation, legacy import ledger, mid-insert rollback and a
  fresh pool recovering durable completion; full existing offline/PG regressions.
- Browser: `test_initial_profiles_browser.py` verifies baseline and final native/
  bridge lifecycle using original apps, not a CRUD mock. Final mode additionally
  verifies mock-generated native readiness. `test_initial_onboarding_browser.py`
  verifies newly seeded RMR tenants with one/zero eligible profiles through real
  provisioning, signed bootstrap, JIT SSO and correct workspace/landing.
- `seed_initial_profiles_proof.py` and PIQ's `initialProfiles.browser.fixture.mjs`
  require `PROFILE_BROWSER_FIXTURE=disposable` and fixed guarded proof DBs. Use
  existing disposable federation proof TLS/config helpers, never installed data.
- Tests run on an internal-only Docker network with source mounts read-only,
  provider credentials empty and no external access. Generated secrets, databases,
  screenshots and build output live solely in disposable Docker storage.

The local/manual seven-service environment, production data and sealed sources
are outside this test fixture and were not modified. No push, deployment, B2C,
continuous synchronization, discovery/scoring/research engine or CRM changes.
