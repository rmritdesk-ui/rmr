# Phase 4 regression, security, and integrity gate

Result: **FAIL — CONCURRENCY DEFECT CONFIRMED.** No production fix applied.
Phase 5 must not start on the strength of this gate.

## Scope and baseline

Only the integration WIP was edited/tested. Sealed RMR and standalone PIQ were
not edited. No Product Owner database was opened, mounted, seeded, or migrated.
Backend tests used disposable SQLite databases in a disposable Docker container,
with the WIP mounted read-only. Provider sockets were forbidden in Phase 4 tests;
browser requests were intercepted. No Google, OpenAI, or website retrieval occurred.

Before adding tests: backend 176 passed; browser 55 passed; interaction 28 passed;
theme 14 passed. `rmr_platform/routes/piq.py` matches sealed RMR byte-for-byte:
SHA256 `9217C7799DD0AF9780F9F49FFA3239C6B119340977BF6238F8D550562979D838`.

Production changes: NONE. Added:

- `tests/test_piq_phase4_crm_regression.py`
- `qa/piq_phase4_fixture.py`
- `qa/test_piq_phase4_browser.py`
- `qa/conftest.py`
- this document

The existing browser lifecycle was moved unchanged from
`qa/test_piq_phase3_browser.py` to `qa/conftest.py`, permitting both gates to run
in one pytest session. All 55 Phase 3 assertions/tests remain intact.

## Canonical live-style fixture

`qa/piq_phase4_fixture.py` defines one normalized Google-style record and immutable
Target Profile snapshot. It uses fixture Place ID `phase4-place`, company
`Local Mortgage Broker Company`, observed Phoenix address, mortgage/finance
categories, website, phone, operational listing and rating/review fields.
These are test observations, not a real Google lookup.

The backend calls the actual Phase 2 `persist_candidates` / `persist_match` path,
creating tenant-owned PiqOpportunity, PiqProfileMatch, and sourced PiqEvidence.
Browser fields/facts are derived from the same candidate and pure matcher. A backend
assertion compares browser scores, counts, source fields, and facts to persisted
values. Employee/revenue thresholds are requested profile criteria, never observed
company facts. No synthetic email, decision maker, employees, revenue, or deal
estimate is introduced; estimated_value_cents stays zero.

## Verified mapping and preservation

`rmr_platform/routes/piq.py::move_piq_to_crm` maps:

| Lead field | Existing mapping |
|---|---|
| tenant_id | PIQ owner tenant |
| company_name | PIQ company_name |
| source | Exactly `ProspectIQ` |
| status | `New` |
| assigned_user_id | Actual requesting user |
| contact_name, email, phone | Empty strings, including when PIQ has a phone |
| notes | `Signal: {signal}. Score: {score}. Evidence items: {evidence_count}.` |

`Lead` in `rmr_platform/models.py` has no PIQ employee/revenue/deal-value mapping.
The intended PIQ mutation is only moved_to_crm=True. Full opportunity snapshots
(excluding that flag), complete evidence rows and complete profile-match rows
remain equal after movement, replay, and CRM conversion. Another tenant's
matching Google record remains unchanged. Provider, external ID, URL, scores,
confidence, completeness, and evidence remain on PIQ; Google is not a new CRM
source taxonomy. The audit's opportunity ID and lead_id link the records.

## Idempotency and confirmed defect

- Initial move: 1 Lead, 1 move audit.
- Sequential repeats and already-moved replay: still 1 Lead, 1 move audit.
- Response discarded after successful commit (HTTP 503 at test middleware), retry:
  still 1 Lead, 1 audit; retry returns created=False.
- Actual browser double action: 2 POST requests dispatched by each renderer.
  Sequential mocked responses yield 1 simulated Lead. This is expressly NOT
  database-concurrency proof.
- Actual concurrent authenticated backend requests: **2 Leads, 2 audits**, both
  responses HTTP 200 / created=True, for a single PIQ opportunity.

### Reproduction and transaction cause

`test_concurrent_move_maximum_one_lead` uses two HTTP clients, two database
sessions, and one temporary SQLite database. A barrier at the existing Lead flush
allows both requests to pass the moved_to_crm check. Only thread scheduling is
controlled; auth, entitlement checks, reads, inserts, updates, audit, and commit
are real. The second write is released after the first finishes, demonstrating
that serial database writes do not serialize the preceding stale read/check.
Session autoflush=False and expire_on_commit=False match production settings.

The route reads an ORM boolean, inserts a Lead, changes that boolean, and commits.
It has no atomic conditional claim, row lock, or unique PIQ-to-Lead key. SQLite's
current driver/transaction setup permits both requests to retain moved=False
before starting their writes. WAL/busy_timeout do not establish business
idempotency. Both writes can succeed even though SQLite serializes writers.

PostgreSQL was NOT executed. Source-based assessment: an ordinary unlocked read
followed by an insert/unconditional update supplies no duplicate-prevention
guarantee there either. A different deployment isolation level might abort one
transaction, but the current route does not establish a portable invariant.

Severity: **HIGH — tenant CRM data integrity / release blocker**. The same race
applies to live, legacy, imported, and demo PIQ records. Browser double actions
provide a reachable trigger. Two Leads from one moved PIQ record also make the
PIQ moved-record funnel diverge from CRM Lead count.

Minimum proposed correction, NOT implemented: in this route, after authorization
and entitlement checks, atomically claim the same tenant-owned unmoved record with
a conditional UPDATE. Only the successful claimant may insert the Lead; claim,
Lead and audit must share one transaction. A losing/retried request must re-read
current state and return the existing created=False contract. Rollback must undo
the claim on insertion/audit failure. Handle database-specific transaction retry
conditions deliberately; verify SQLite and PostgreSQL before declaring safety.
An in-process lock or disabling the browser button alone is not a sufficient fix.

Likely minimum production file: `rmr_platform/routes/piq.py`; regression file:
`tests/test_piq_phase4_crm_regression.py`. Risk: transaction ordering, stale ORM
state, losing-request response behavior, and database lock/retry handling.
No schema or CRM redesign is proposed for the minimal claim approach.

The test is a normal failing invariant assertion, not skipped, xfailed, or changed
to accept two Leads. Production implementation is intentionally paused.

## Tenant and permission findings

Authenticated requests use real cookie JWT decoding and a fresh Session per request,
without overriding current_user. Existing permissions are in `permissions.py`;
managed session validation is in `security.py::current_user`.

| Role / session | View PIQ | Discover | Move | View resulting Lead |
|---|---|---|---|---|
| CLIENT_ADMIN | Yes | Yes | Yes | Yes |
| VP_SALES | Yes | Yes | Yes | Yes |
| SALES_MANAGER | Yes | Yes | Yes | Team scope |
| SALES_REP | Yes | Yes | Yes | Assigned scope |
| EXECUTIVE_VIEWER | Yes | No | No | Yes |
| MARKETING_USER | Yes | No | No | Yes |
| RMR_OWNER / STEP2_ADMIN, valid managed_write | Yes | Yes, bound tenant | Yes, bound tenant | Yes |
| Global, missing/invalid/expired/ended/read-only/wrong-actor/wrong-tenant session | Yes | No for tested target | No for tested target | Yes |

Global cross-tenant READ is intentional existing policy; managed sessions restrict
writes, not global read authority. A session valid for A cannot move B. Ending an
active session immediately blocks subsequent requests. Both global roles tested.
Client managers/reps can see their created Lead because assignment uses the actor;
the manager fixture has a real nonempty team. An empty team can yield an empty
manager list under existing team filtering.

Tenant A cannot list/view/profile/move B's PIQ record, or read B's discovery run.
Forging an A path for a B run returns 404; the B tenant path returns 403. A foreign
evidence ID substituted for an opportunity ID returns 404. No independent
evidence-ID endpoint exists: evidence is returned through the authorized profile.
Own profile evidence excludes B's IDs. A forged tenant/company/email body cannot
override the actual opportunity ownership or mapping. Missing/malformed IDs return
404, unauthenticated requests 401, missing request-origin marker 400.

`piq.py::_require_piq_access` requires both active piq_access and piq_enhancement
for list/move. Removing either blocks list/move; removing piq_access also blocks
discovery and run status. **Existing policy gap:** `unified.py::piq_profile` checks
tenant ownership only, so same-tenant profile/evidence remains readable after
entitlement removal (200). This is not cross-tenant leakage; whether subscription
revocation should also deny historical profile reads needs a policy decision.

## Audit, transaction failures, and downstream CRM

Move audit contains actor, tenant, event_type=piq.moved_to_crm,
entity_type=piq_opportunity, opportunity ID, data.lead_id, and timestamp. Payload
contains no provider body or secrets. **Existing audit limitation:** managed Move
events do not contain a managed-session ID, although the real global actor is
retained. `services.py::audit` stores only supplied data; Move passes only lead_id.
This limits exact session attribution and was not silently extended.

Lead insertion, audit invocation, audit insertion, and pre-commit failures were
injected separately. Each produced HTTP 500, with 0 persisted Leads, 0 audits,
moved=False, and preserved PIQ history after request-session close. Retrying after
removing the failure created exactly 1 Lead; another retry stayed at 1. The route
has one final commit; request-session cleanup rolls back uncommitted writes.
These results do not negate the independent concurrency defect.

`routes/crm.py` existing steps verified: Lead -> tenant follow-up note -> conversion
to Account/Contact/Opportunity -> linked follow-up -> account 360 -> stage movement
(Discovery, Proposal, Negotiation) -> Closed Won and Closed Lost in separate cases.
ActivityCreate has no lead_id; pre-conversion follow-up is a tenant note, not a
structured Lead-linked activity. Conversion preserves ProspectIQ source and starts
with blank contact data and zero value. A test user explicitly enters 120000 cents
and 50% probability later; this is not a PIQ-derived estimate.

`crm_summary`, `unified_services.workspace_summary`, `cross_channel_report`, and
`/growth-report` verified: 1 Lead, 1 Account, 1 Opportunity; 60000 weighted pipeline;
120000 open pipeline; PIQ-to-CRM=1. Won yields 1 won opportunity and 120000 revenue;
Lost yields 0 won/revenue. Both terminal stages remove open/weighted pipeline.
Source attribution reports 1 ProspectIQ opportunity. Existing reporting has no
dedicated lost-count key or separate ProspectIQ-source Lead metric; Lead list
source, overall Lead count, terminal opportunity list and opportunity attribution
were checked without inventing new reports.

Historical provider-null, explicit demonstration, imported, and new Google rows
remain movable and render with existing source labels. The real import API was
also exercised. Existing demo discovery/research behavior remains covered by the
unchanged Phase 0/3 gates. No historical migration/rescoring was performed.

## Verification results

| Group | Passed | Failed |
|---|---:|---:|
| Phase 0 foundation + static | 17 | 0 |
| Phase 1 | 47 | 0 |
| Phase 2 | 65 | 0 |
| Phase 3 backend | 10 | 0 |
| Phase 4 backend | 42 | 1 |
| Other backend/project tests | 37 | 0 |
| Complete backend | 218 | 1 |
| Phase 3 browser | 55 | 0 |
| Phase 4 browser | 14 | 0 |
| Interaction preservation | 28 | 0 |
| Theme preservation | 14 | 0 |

Browser coverage uses actual ES modules/CSS, not a real server/DB connection;
database assertions belong to the backend tests. Double-click browser tests
characterize the current two-request behavior, not certify idempotency.
The only failing backend assertion is maximum one concurrent Lead. Existing
Starlette/anyio deprecation warning remains unrelated.

Reproduction commands from WIP (with installed test dependencies and isolated DB
environment):

```text
python -B -m pytest -q -rA --tb=short -p no:cacheprovider
python -B -m pytest qa/test_piq_phase3_browser.py qa/test_piq_phase4_browser.py -q -p no:cacheprovider
python -B qa/v5412_interaction_regression_gate.py --root .
python -B qa/v5412_theme_preservation_gate.py --root .
```

Do not run the backend command against Product Owner data. This gate used
RMR_DATA_DIR=/tmp/rmr-phase4-test,
RMR_DATABASE_URL=sqlite:////tmp/rmr-phase4-test/runtime.db,
RMR_AUTO_MIGRATE=false, RMR_AUTO_SEED=false in the disposable test container.
The per-test fixtures create/migrate only pytest temporary databases.

Live discovery and worker defaults remain OFF, provider mode demonstration.
No production configuration, schema, provider, scoring, research, CRM, billing,
email, website, or onboarding code changed. No staging or commit. Phase 5 not started.
