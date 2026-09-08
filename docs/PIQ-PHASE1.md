# Phase 1: Google Places candidate discovery

This successor working copy is not a production-approved v5.4.1.2 release.
The Phase 0 migration remains `005.007.000-piq-integration-foundation`.
No Phase 1 schema migration is required.

## Configuration and API mode

Defaults remain demonstration mode, live discovery OFF, worker OFF, live research OFF.
For a separately authorized test environment only, Google discovery needs:

- `RMR_PIQ_LIVE_DISCOVERY_ENABLED=true`
- `RMR_PIQ_DISCOVERY_PROVIDER=google_places`
- `RMR_GOOGLE_PLACES_API_KEY` supplied outside source control
- `RMR_PIQ_WORKER_ENABLED=true`

The adapter follows the standalone reference's Places Web Service Legacy API:
Text Search `/maps/api/place/textsearch/json`, then Place Details
`/maps/api/place/details/json` on `maps.googleapis.com`.
The Google project must have access to that API; a Places API (New)-only key is
not interchangeable. No real provider smoke test is run automatically.

The total discovery deadline defaults to 30 seconds, including details and page
delays. Each query uses at most three pages, with 2.2 seconds before the next page.
Up to eight industry/location combinations and 25 results are allowed by default.
No extra billing/charging logic is added to RMR.

## Query planning and records

An active profile with at least one industry and location is required. Queries
combine those fields in saved order, with at most two bounded keyword refinements.
Employee and revenue requirements are preserved in the snapshot but are not
Google filters or confirmed qualifications. Exclusions are carried forward only.
Changes to the live Target Profile do not rewrite queued snapshots.

Candidate opportunities have `provider=google_places`, `status=Discovered`, and
only observed identity/address/category/phone/website fields. Legacy non-null
score, evidence count, enhancement price and estimated value use neutral zero;
these are not computed scores or estimates. Separate match/confidence fields
remain NULL. There are no synthesized emails or evidence records.

Bounded normalized observations, including Google status, ratings, coordinates,
and retrieval time, are retained in the run's diagnostics JSON. The public run
status response returns operational counts/errors, not raw provider metadata.
Unknown data remains NULL. Closed business status is retained for later
qualification; Phase 1 does not implement the qualification engine.

Persistence deduplicates only within a tenant and Google provider: Place ID,
then normalized website domain, then normalized name plus observed address.
Legacy/demo rows are not merged or rewritten. Same-tenant persistence is
serialized in a short SQLAlchemy transaction after HTTP finishes.

## API and lifecycle

The existing discovery route's default demo path is preserved. When explicitly
enabled, it validates existing permissions and PIQ entitlement and returns 202
with `run_id`, `status`, `provider_mode`, and `requested_count`.
Optional `Idempotency-Key` is tenant-scoped; conflicting input reuse returns 409.
GET `/api/tenants/{tenant_id}/piq/discovery-runs/{run_id}` uses existing read
permissions and never returns another tenant's run. Global administrators still
need an active tenant-bound managed-write session to queue work.

The worker checks current requester access, entitlement, tenant/profile ownership
and managed-session validity. HTTP runs outside database transactions. Completion
is fenced by run, tenant, lease owner, expiry and attempt generation. Transient
timeouts, 429/quota limits and 5xx failures retry within the attempt limit.
Credential/configuration/profile failures do not retry. Some malformed optional
details may yield `partial` with genuine Text Search data and explicit errors.
Zero results complete with zero candidates; live failures never insert demos.

## Verification

Run from the WIP root with the project dependencies plus pytest and Pillow:

```text
python -m pytest -q -p no:cacheprovider
```

Use an isolated `RMR_DATA_DIR` and `RMR_DATABASE_URL`, auto-seeding/migration OFF,
and temporary SQLite fixtures. Phase 1 tests block network connections and use
`httpx.MockTransport`; cookie-authenticated API tests run in process. Never run
tests or successor migrations against the Product Owner database.

Phase 2 scoring, qualification and sourced evidence are deliberately deferred.
