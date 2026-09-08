# Phase 4 final regression/security gate — CLOSED

Date: 2026-09-07. Result: **PASS**.

This is a fresh re-run against the Phase 4.1 fixed code, not a restatement of its
previous results. The earlier failure in PIQ-PHASE4.md is historical; this final
gate supersedes that release decision. No new release-blocking defect was found.

**Phase 4 is closed. Adaptive Research may proceed as Phase 5.**
Phase 5 was not started.

## Production diff and scope

Production changes during this re-gate: **NONE**. Test changes: **NONE**.
The only new file is this closure report.

Current hashes were compared with the captured pre-Phase-4.1 WIP baseline. The
only Phase 4.1 production difference is rmr_platform/routes/piq.py. Inspection
confirmed it consists of the SQLAlchemy update import, tenant-scoped conditional
claim, authoritative reload, and explicit rollback around the unchanged Lead
mapping/audit/commit. No provider, matching, scoring, evidence, discovery-worker,
PIQ UI, CRM model/workflow, reporting, research, billing, email, or onboarding
production files changed. The sealed route retains SHA256
9217C7799DD0AF9780F9F49FFA3239C6B119340977BF6238F8D550562979D838.

All runtime databases were disposable. The WIP was mounted read-only into backend
test containers; no Product Owner database was opened, mounted, migrated, or
modified. No sealed-source edits, staging, commit, Google call, OpenAI call, or
real provider use occurred. Live discovery/worker remain OFF by default.

## Fresh test results

| Suite | Passed | Failed |
|---|---:|---:|
| Phase 0 foundation/static | 17 | 0 |
| Phase 1 backend | 47 | 0 |
| Phase 2 backend | 65 | 0 |
| Phase 3 backend | 10 | 0 |
| Original Phase 4 backend | 43 | 0 |
| Phase 4.1 concurrency/safety additions | 10 | 0 |
| Other project tests | 37 | 0 |
| Complete backend | 229 | 0 |
| Explicit SQLite concurrency rerun | 4 | 0 |
| PostgreSQL runtime concurrency/safety gate | 14 | 0 |
| Phase 3 browser | 55 | 0 |
| Phase 4 browser | 14 | 0 |
| Interaction preservation | 28 | 0 |
| Theme preservation | 14 | 0 |

The SQLite four-case rerun repeats a subset of the already-passing full backend
suite: 2, 3, 5 and 8 concurrent requests. Its 49 deselections are unrelated cases
already executed in the complete suite, not skipped gate requirements. The former
failing concurrency regression is a normal passing assertion, not skipped/xfail.
Browser combined run: 69 passed. PostgreSQL's 14 cases include four concurrent
batch sizes plus rollback, failed claimant/waiters, stale ORM and response loss.
The existing Starlette/anyio deprecation warning is non-blocking.

## Move to CRM, concurrency, and audit

| Scenario | Lead count | Move audit count |
|---|---:|---:|
| Single request | 1 | 1 |
| Sequential repeat | 1 | 1 |
| Already moved | 1 | 1 |
| Response lost after successful commit, then retry | 1 | 1 |
| Two overlapping requests | 1 | 1 |
| Three overlapping requests | 1 | 1 |
| Five overlapping requests | 1 | 1 |
| Eight overlapping requests | 1 | 1 |

Every successful concurrent batch has exactly one created=True response; the
remaining N-1 responses return created=False. All are HTTP 200 and report
moved_to_crm=True. Duplicate creation audits: zero. Actor, tenant, event action,
opportunity ID, lead_id and timestamp remain correct under the current audit shape.

SQLite runtime: PASS, isolated temporary files using current application settings.
PostgreSQL runtime: PASS, PostgreSQL 16.15, READ COMMITTED. A fresh dedicated
container/network was created with RAM-only PGDATA, no published ports and no
existing volumes. Per-test schemas were isolated. No unrelated Docker stack was
changed. The dedicated container/data/network were removed after verification.

Browser double action still dispatches two requests, as the unchanged UI permits.
Actual browser modules with mocked HTTP prove dispatch, refresh, retry and stable
display. Separately, authenticated HTTP requests against real SQLite/PostgreSQL
prove the server-side two-request result is one Lead/one audit. Browser tests are
not represented as an end-to-end browser-to-live-database test.

The claim predicates include both opportunity ID and authorized tenant ID, and
moved_to_crm IS false. Claim, Lead and audit share one transaction; losing sessions
reload authoritative state using populate_existing. Existing API shapes and
source='ProspectIQ' remain unchanged. This certifies the current conversion flow,
not cleanup of pre-existing inconsistent flags/duplicates or every custom database
isolation configuration. The historical-state boundary documented in Phase 4.1
is unchanged and is not a new regression.

## Transaction failures

Lead insert failure, audit-call failure, audit-insert failure and pre-commit
failure each leave moved=False, zero Leads and zero audits. The database-commit
failure test runs both INSERTs before injecting failure before actual COMMIT;
rollback leaves no partial conversion state. Retry creates one Lead/one audit,
and a subsequent retry adds none. After-successful-commit response loss likewise
retries idempotently. A failing first claimant releases the claim for a waiting
request, with exactly one eventual successful conversion.

## Canonical fixture, provenance, and data honesty

The existing qa/piq_phase4_fixture.py candidate is used through the actual Phase 2
matcher and persistence. It has provider=google_places, fixture Place ID
phase4-place, source URL, observed address/category, phone and website, base/display
score 80, confidence 72%, completeness 67%, one PiqProfileMatch and four sourced
evidence rows. Browser values/facts are checked against the same persisted fixture.
Requested employee/revenue criteria are not fabricated company observations.

Move sets only intended moved state. Full PIQ snapshots, evidence facts and match
records remain intact: provider, external ID, URL, scores, confidence, completeness
and provenance do not become demonstration data. Lead company/tenant and existing
notes are preserved; Lead source stays ProspectIQ. Contact name/email/phone remain
empty under the existing mapping. No invented employee/revenue/decision-maker or
deal-estimate data is transferred. Initial CRM conversion value remains zero.

## Tenant, role, managed-session and entitlement security

Tenant A cannot list/view/move B's PIQ record, access its protected profile/evidence,
poll its run, or create B's Lead. Forged path/body identifiers cannot override
ownership. Foreign evidence IDs do not grant profile access; evidence is exposed
through the tenant-authorized opportunity profile, not an independent ID endpoint.

| Role/session | View PIQ | Discover | Move | View CRM Lead |
|---|---|---|---|---|
| CLIENT_ADMIN | Yes | Yes | Yes | Yes |
| VP_SALES | Yes | Yes | Yes | Yes |
| SALES_MANAGER | Yes | Yes | Yes | Team scope |
| SALES_REP | Yes | Yes | Yes | Assigned scope |
| EXECUTIVE_VIEWER | Yes | No | No | Yes |
| MARKETING_USER | Yes | No | No | Yes |
| RMR_OWNER / STEP2_ADMIN, valid managed_write | Yes | Bound tenant | Bound tenant | Yes |
| Either global role, missing/invalid/expired/ended/read-only/wrong-tenant/wrong-actor session | Yes | No for target | No for target | Yes |

Global read access is existing intentional policy. Client writes require current
operational permissions; managed writes are tenant-bound. Session termination
blocks subsequent writes. Both global roles were exercised.

PIQ list/move require active piq_access and piq_enhancement. Removing either blocks
them. Removing piq_access also blocks discovery and run status. Historical
same-tenant profile/evidence reads retain the explicitly deferred policy behavior.

## CRM, reporting, demo and browser compatibility

Verified existing flow: Lead -> tenant follow-up note -> conversion -> Account,
Contact and Opportunity -> linked follow-up/account 360 -> Discovery, Proposal,
Negotiation -> Closed Won or Closed Lost in separate cases. The current activity
schema has no lead_id; no new structured pre-conversion link was invented.

Reports verify one Lead, one Account, one Opportunity and ProspectIQ attribution.
An explicitly test-user-entered 120000-cent CRM value at 50% yields 60000 weighted
pipeline. Won reports one win/120000 cents; Lost reports no win/revenue. Both close
the open pipeline. Existing reports have no dedicated Lost-count field; the
terminal opportunity list and exclusion from pipeline were verified instead.

Legacy provider-null, explicit demo, imported and live-style Google PIQ rows all
remain movable and correctly labelled. Actual import and existing demo discovery
regressions pass. No historical migration/rescoring occurred. Browser gates cover
source/evidence, honest unknown values, Move, refresh/reload, already-moved state,
double action and response-loss retry. No frontend changes were needed.

## Explicitly deferred — unchanged, non-blocking for this gate

1. Managed-session ID missing from Move audit.
2. Same-tenant PIQ profile/evidence read-after-entitlement-removal policy.

Neither was modified. They remain outside this final gate per the approved scope.
No new release-blocking defect was found.

## Commands used

Inside a disposable backend container with RMR_DATA_DIR=/tmp/rmr-phase4-regate,
RMR_DATABASE_URL=sqlite:////tmp/rmr-phase4-regate/runtime.db,
RMR_AUTO_MIGRATE=false, RMR_AUTO_SEED=false, and the WIP mounted read-only:

```text
python -B -m pytest -q -rA --tb=short -p no:cacheprovider
python -B -m pytest tests/test_piq_phase4_crm_regression.py tests/test_piq_phase41_atomic_claim.py -k 'test_concurrent_move_maximum_one_lead or test_many_concurrent_moves' -q --tb=short -p no:cacheprovider
```

Other gates (PostgreSQL command requires the dedicated disposable environment,
never a user database):

```text
python -B -m pytest scripts/test_piq_phase41_postgres.py -q -rA --tb=short -p no:cacheprovider
python -B -m pytest qa/test_piq_phase3_browser.py qa/test_piq_phase4_browser.py -q --tb=short -p no:cacheprovider
python -B qa/v5412_interaction_regression_gate.py --root .
python -B qa/v5412_theme_preservation_gate.py --root .
```

Final decision: **Phase 4 CLOSED; Phase 5 READY, not started.**
