# Phase 4.1 — atomic Move-to-CRM claim

Result: PASS. The confirmed concurrent conversion defect is corrected, with one
production file changed. Phase 5 was not started or authorized by this work.
`PIQ-PHASE4.md` records the historical pre-fix failure; this document records the
fix and subsequent regression results.

## Before-fix reproduction

The original, unmodified Phase 4 concurrency test was run before any edits:

```text
test_concurrent_move_maximum_one_lead: FAILED
2 concurrent requests -> 2 Leads, 2 audits, created=[True, True]
```

Route: POST `/api/piq/{opportunity_id}/move-to-crm`.
Function: `rmr_platform/routes/piq.py::move_piq_to_crm`.

The old flow used db.get(PiqOpportunity), checked authorization/entitlements and
the loaded moved_to_crm boolean, added/flushed a Lead INSERT, set the ORM boolean,
added an AuditEvent, then committed. The final commit flushed the pending PIQ
UPDATE/audit INSERT. Two sessions could both load false before either wrote.
Production SessionLocal uses expire_on_commit=False and autoflush=False.

## Production change

Only `rmr_platform/routes/piq.py` changed: import SQLAlchemy update, conditionally
claim the record, reload authoritative state, and explicitly roll back exceptions.
The existing Lead field mapping and audit call remain unchanged.

Conceptual SQL, compiled for SQLite and PostgreSQL by an automated test:

```sql
UPDATE piq_opportunities
SET moved_to_crm = true
WHERE id = :opportunity_id
  AND tenant_id = :authorized_tenant_id
  AND moved_to_crm IS false;
```

The primary key bounds the update to zero or one row. Authorization, managed-write
rules, and both PIQ entitlement checks execute before the claim. There is no
ID-only UPDATE and no application-process lock.

- Winner (one affected row): create the existing ProspectIQ Lead and move audit,
  then commit once.
- Loser (zero affected rows): reload by both opportunity ID and tenant ID, return
  the existing `{opportunity, created: false}` shape, without Lead or audit creation.
- Sequential already-moved requests retain the original fast path/response.
- Winner response remains `{opportunity, lead, created: true}`.

The SQL UPDATE uses synchronize_session=False. A tenant-scoped SELECT with
populate_existing=True reloads the same identity-map object afterward, for both
winner and loser. The stale-loaded-loser test proves it returns moved=True even
when its Session originally cached false. No stale ORM boolean elects the winner.

Claim -> Lead INSERT -> audit INSERT -> one COMMIT all share the request's
transaction. Exceptions explicitly call db.rollback() and propagate; request
cleanup also closes the Session. The losing request performs no commit or writes
beyond its zero-row claim; normal get_db cleanup ends its transaction.

No separate claim commit, migration, CRM uniqueness redesign, frontend change,
new response fields, or new audit payload was introduced.

## Regression and concurrency tests

The original Phase 4 test name and one-Lead invariant remain normal tests, not
skipped/xfail. Its scheduler barrier moved from Lead flush to just after the
unchanged entitlement check, where all requests have loaded moved=False. Waiting
for two Lead flushes would deadlock a correct one-winner implementation. Auth,
database statements, request sessions and transaction commits remain real.
The assertions were strengthened to require one audit, one true response, one
false response, and moved=True in every response and persisted state.

Additional tests in `tests/test_piq_phase41_atomic_claim.py` cover:

- 3, 5 and 8 concurrent authenticated requests against one canonical live record.
- Authoritative refresh of an already-loaded stale losing ORM object.
- Compilation of the actual executed claim for SQLite and PostgreSQL, including
  both ID and tenant predicates.
- First claimant failing at Lead insertion, audit insertion, or pre-commit while
  other requests wait: rollback releases the claim; another request succeeds once.
- Historical false moved flag alongside an existing ProspectIQ Lead (see below).
- Database commit failure after both Lead and audit INSERTs have executed:
  explicit rollback leaves moved=False, zero Leads, zero audits; retry creates one.

Existing Phase 4 tests also cover audit-call failure, sequential replays,
already-moved behavior, response discarded after successful commit, exact mapping,
provenance immutability, roles, managed sessions, tenant isolation, entitlement
removal, CRM conversion/activity/pipeline/Won/Lost and reporting.

The injected database-commit failure occurs before the driver's actual COMMIT.
It does not claim to simulate every network failure during commit acknowledgement.
Database transactions supply all-or-nothing persistence; a later request consults
the persisted moved flag. The after-successful-commit response-loss test verifies
the corresponding idempotent retry outcome.

## Runtime results

| Concurrent requests | Leads | Move audits | created=true | created=false |
|---:|---:|---:|---:|---:|
| 2 | 1 | 1 | 1 | 1 |
| 3 | 1 | 1 | 1 | 2 |
| 5 | 1 | 1 | 1 | 4 |
| 8 | 1 | 1 | 1 | 7 |

These results were verified on BOTH isolated SQLite and PostgreSQL 16.15 runtimes,
not merely by SQL compilation. Normal losing requests return HTTP 200, not 409/500.
For three concurrent requests with an injected first-claimant failure, exactly one
request returns the intentional 500, one returns created=True, and one False;
the database still contains one Lead and one audit. Retrying the failed request
returns False without duplication.

SQLite uses the project's current driver/transaction configuration and temporary
test files only. PostgreSQL uses the existing local postgres:16-alpine image in a
new dedicated container and network, with RAM-only PGDATA, no published ports,
and no existing user volumes. Each test gets a fresh generated schema. The explicit
gate is `scripts/test_piq_phase41_postgres.py`, which rejects database URLs not
matching the dedicated phase41_test database/user and phase41-postgres hostname.
The PostgreSQL gate is run only against the task-created disposable server.
After verification, that container, its RAM-only test data, and its dedicated
network were removed. The disposable test data is not recoverable; no user data,
existing containers, stacks, or volumes were removed or modified.

PostgreSQL testing covers default READ COMMITTED behavior; no claim is made that
custom SERIALIZABLE/REPEATABLE READ deployments never need transaction retries.
Unusual lock timeouts or infrastructure failures remain normal database failures,
not a promise of unlimited availability. They cannot authorize a second successful
claim for the same still-moved row.

## Full regression counts

| Group | Passed | Failed |
|---|---:|---:|
| Phase 0 foundation/static | 17 | 0 |
| Phase 1 backend | 47 | 0 |
| Phase 2 backend | 65 | 0 |
| Phase 3 backend | 10 | 0 |
| Phase 4 backend | 43 | 0 |
| Phase 4.1 backend additions | 10 | 0 |
| Other backend/project | 37 | 0 |
| Complete backend/project | 229 | 0 |
| Dedicated PostgreSQL runtime gate | 14 | 0 |
| Phase 3 browser | 55 | 0 |
| Phase 4 browser | 14 | 0 |
| Interaction preservation | 28 | 0 |
| Theme preservation | 14 | 0 |

Existing Starlette/anyio deprecation warning remains unrelated. Browser tests use
actual existing modules with intercepted responses. The UI still dispatches two
Move requests on rapid double action; database safety is enforced by the backend,
not by a browser lock. The browser gates and frontend production files were not
edited in Phase 4.1.

## Historical state boundary

An inconsistent pre-existing state, moved_to_crm=False with an existing ProspectIQ
Lead, is NOT repaired: the next successful claim creates one new Lead (two total),
and subsequent requests add none. Lead has no reliable PIQ-opportunity foreign key;
matching company/source text cannot safely establish identity. Existing duplicates
are not deleted or merged, and flags are not retrospectively rewritten. This
historical reconciliation boundary is separate from future concurrent claim safety.

## Deferred findings — unchanged

1. Move audit events omit the managed-session ID.
2. Same-tenant PIQ profile/evidence reads remain available after entitlement removal.

Neither was changed in Phase 4.1. Their characterization tests still pass.

## Scope and reproduction

Modified production: `rmr_platform/routes/piq.py` only.
Modified test: `tests/test_piq_phase4_crm_regression.py`.
Added: `tests/test_piq_phase41_atomic_claim.py`,
`scripts/test_piq_phase41_postgres.py`, and this document.

Complete backend command in the disposable image:

```text
python -B -m pytest -q -rA --tb=short -p no:cacheprovider
```

Use a read-only WIP mount, RMR_DATA_DIR=/tmp/rmr-phase41-test,
RMR_DATABASE_URL=sqlite:////tmp/rmr-phase41-test/runtime.db,
RMR_AUTO_MIGRATE=false and RMR_AUTO_SEED=false. Per-test fixtures build only their
temporary databases. NEVER substitute the Product Owner database path.

Other commands:

```text
python -B -m pytest scripts/test_piq_phase41_postgres.py -q -p no:cacheprovider
python -B -m pytest qa/test_piq_phase3_browser.py qa/test_piq_phase4_browser.py -q -p no:cacheprovider
python -B qa/v5412_interaction_regression_gate.py --root .
python -B qa/v5412_theme_preservation_gate.py --root .
```

The first command requires the explicitly isolated PostgreSQL environment above;
it is not a general-purpose database test command.

No Product Owner database use/migration; no sealed-source changes; no real Google,
OpenAI or website calls; no provider/scoring/evidence/CRM-model/frontend/config
changes; no staging or commit. Live discovery/worker defaults remain OFF.
Ready to re-run/review the Phase 4 gate: YES. No Phase 5 work was performed.
