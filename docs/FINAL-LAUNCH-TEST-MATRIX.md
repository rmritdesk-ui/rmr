# Prompt 5 executed launch matrix

All automated provider paths use fixtures; Docker test networks are internal-only.
These are scenario results, not a substitute for the exact test-runner totals in the
release report. `RMR tests` means `tests/test_prospectiq_*.py` plus corresponding
`scripts/test_prospectiq_*postgres.py`; `PIQ tests` means `backend/tests/*.test.js`.
The Windows runner `scripts/run_prompt4_runtime.ps1 -Final` uses fresh generated names,
keys and data; `-Final -Upgrade` constructs OLD/MANUAL state before final app startup.

| # | Scenario | Executed evidence | Result |
|---|---|---|---|
| 1 | New tenant, one source profile | fresh three-tenant browser; provisioning/bootstrap PG tests | PASS |
| 2 | New tenant, zero profiles | fresh browser creates normal PIQ replacement/profile | PASS |
| 3 | Existing manual mapping | upgrade browser + manualUpgrade.inspect.mjs | PASS |
| 4 | Existing manual profile ledger | initialProfiles PG: edits preserved before completion | PASS |
| 5 | Deleted imported profile before upgrade | old fixture tombstone + user replacement + inspector | PASS |
| 6 | Repeated first launch | workspace/bootstrap repeat and browser reload | PASS |
| 7 | Concurrent first launch 2/5/8 | RMR provisioning PG; PIQ workspace/bootstrap PG | PASS |
| 8 | Concurrent tenants | fresh browser + same-name distinct-client PG cases | PASS |
| 9 | Inactive PIQ client | workspace/bootstrap and capability PG tests | PASS |
| 10 | Suspended mapping | browser revocation + RMR lifecycle | PASS |
| 11 | Inactive tenant | browser revocation + lifecycle SQLite/PG | PASS |
| 12 | Disabled user | browser revocation + capabilities | PASS |
| 13 | Entitlement removed | two independent entitlement browser revocations | PASS |
| 14 | Role downgraded | browser revocation + capabilities | PASS |
| 15 | Identity collision | identity browser + identityRecovery PG | PASS |
| 16 | Approved identity recovery | native administrator browser approval + PG | PASS |
| 17 | Rejected identity recovery | foreign/nonadmin/stale/mismatched authority PG denials | PASS |
| 18 | Expired auth code | RMR federation SQLite/PG | PASS |
| 19 | Replayed auth code | federation tests + interrupted-exchange browser | PASS |
| 20 | Expired bridge session | rmrOperations PG absolute/idle expiry | PASS |
| 21 | RMR restart | actual process restart browser reload/reopen | PASS |
| 22 | Backend restart | actual process restart browser reload/reopen | PASS |
| 23 | Worker restart | actual process restart with durable completed job state | PASS |
| 24 | Redis interruption | test_final_dependencies.ps1: pause/readiness/recover | PASS |
| 25 | PostgreSQL interruption | same actual pause/readiness/recover proof | PASS |
| 26 | Lost workspace response | RMR provisioning SQLite/PG retry identity | PASS |
| 27 | Lost bootstrap response | RMR bootstrap + PIQ initialProfiles PG | PASS |
| 28 | Pull Leads fixture | all six fresh/upgrade tenant browser flows | PASS |
| 29 | Adaptive Research fixture | all six flows, actual job/authorization paths | PASS |
| 30 | CRM first handoff | all six flows, signed ingestion and exact tenant lead | PASS |
| 31 | CRM retry | delayed response/browser retry; receipt reconciliation PG | PASS |
| 32 | Conflicting CRM event | RMR CRM and PIQ CRM/operations PG fail-closed tests | PASS |
| 33 | Back to RMR | all browser flows, authenticated prospectiq destination | PASS |
| 34 | Native PIQ login | native browser + recovery native logout | PASS |
| 35 | Native profile lifecycle | native browser draft create/persist/delete/readiness | PASS |
| 36 | RMR bridge OFF | 11 launcher tests incl explicit native fallback | PASS |
| 37 | HTTPS/proxy preservation | actual TLS -> trusted Nginx -> backend browser; spoof tests; nginx -t | PASS |
| 38 | Missing/unreadable/invalid key | safe category/startup denial tests on both apps | PASS |
| 39 | Bad grant HMAC | config and authenticated partner tamper/rotation tests | PASS |
| 40 | Bad CRM HMAC | separate-key config failure and signed ingestion tests | PASS |

**40 PASS / 0 FAIL.** Broader regression totals are recorded in the final release report.
Additional schema tests: DDL failure rolls back new tables preserving existing native
rows; 2/5/8 concurrent initializers serialize safely. Repeated RMR migration preserves
existing CRM lead/receipt/event on SQLite and PostgreSQL.

Final executions: RMR bridge SQLite **162/162**, bridge PostgreSQL **162/162**,
launcher **11/11**; complete PIQ backend **256/256**. Broader RMR run: **600 passed,
1 documentation-contract failure, 3 historical packaging tests deselected**. The sole
failure was a missing exact runbook safety sentence, corrected in documentation;
the final deployment suite rerun passed **24/24**, including that assertion. Thus all
601 applicable RMR cases are covered by passing executions; no application regression
remains. The three default-excluded tests require private historical packaging artifacts.
Fresh and upgrade acceptance each passed three complete tenant flows, seven revocation
journeys, native profile/auth and identity recovery, and RMR/backend/worker restarts.
The rebuilt production frontend image passed; its actual startup selector and Nginx
configuration passed separately. Documented schema-init/health commands also executed
successfully against the upgraded disposable stack and retained its imported tombstone.

Non-blocking pre-existing warnings: AnyIO deprecated alias; Node experimental VM
modules in launcher tests; duplicate JSX `canConfirm`; Docker's generic warning about
the intentionally public Stripe publishable-key build argument. npm audit reports two
existing frontend build/development-tool dependency findings (Vite high, esbuild
moderate); no dependency upgrade was made in this integration task. The production
frontend is the Nginx static stage, not an exposed Vite/esbuild development server.
Native legacy Profound features remain outside this task. Real provider acceptance,
server backup/restore execution and actual VPS capacity are not inferred from fixtures.

Reproduction prerequisites: the documented cached dependency/test images (runner
parameters), Docker, PowerShell, internal Docker networks. Test images do not embed
current source: runner mounts current maintained code read-only and builds frontend.
No installed `.env`, manual-service volume or production data is used. Unit PG runs
must set both RMR_DATABASE_URL and RMR_PHASE41_POSTGRES_TEST_URL to the guarded
`phase41-postgres` / `phase41_test` fixture; PIQ sets RMR_BRIDGE_TEST_DATABASE_URL.
Mount worker under `/app/worker` with BRIDGE_WORKER_MODULE pointing to its source,
so Node resolves dependencies from the cached test image. Test keys are ephemeral.

No integration routing/authorization/tenant logic contains pilot UUIDs, server IPs or
nip.io names. Existing native PIQ legacy `profound_tax` UI/AI endpoints and demo copy
remain outside this integration path; they were not redesigned or silently relabelled.
