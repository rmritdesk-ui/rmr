# CB1-R1 Test Report

Release: `5.1.0-commercial-cb1-r1`

Status: **PASS for all runnable build, migration-model, CAF-preservation, source, API, browser, backup/restore, and regression gates in this environment.**

Product status: **Windows/Docker Product Owner test candidate only. Not production-approved. No Hasan handoff.**

## R1-01 through R1-07

All seven frozen R1 gates passed:

- R1-01 Controlled failure reproduction: 6/6 checks passed.
- R1-02 Proven minimum correction: 7/7 checks passed.
- R1-03 Corrected additive migration: 7/7 checks passed.
- R1-04 CAF data preservation: 7/7 checks passed.
- R1-05 Pre-cleanup migration diagnostics: 8/8 checks passed.
- R1-06 Rollback preservation and evidence: 8/8 checks passed.
- R1-07 Separate candidate, boundaries, and regression integrity: 9/9 checks passed before final ZIP sealing.

## Existing CB1 and inherited v5.1 regression gates

- CB1 preflight: 29 passed, 0 failed.
- CB1 functional acceptance: 40 passed, 0 failed.
- CB1 release audit: 38 passed, 0 failed.
- Python test suite: 15 passed.
- v5.1 acceptance: 122 passed, 0 failed.
- v5.1 backup/restore: 13 passed, 0 failed.
- v5.1 health messaging: 6 passed, 0 failed.
- v5.1 static audit: 68 passed, 0 failed.
- v5.1 upgrade preservation: 17 passed, 0 failed.
- v5.1 RC3 upgrade reliability: 60 passed, 0 failed.
- v5.1 browser acceptance: 40 passed, 0 failed; duration 13.92 seconds.
- Python compile-all: passed.

Total named automated checks represented by the structured suites above: 485 (433 inherited CB1/v5.1 checks plus 52 R1 checks), plus 15 pytest tests and compile-all.

## Migration and data evidence

- Unchanged parent CB1 migration: reproduced exit code 1 with the exact future-import `SyntaxError`.
- Failed-command predecessor database/WAL/SHM hashes: unchanged.
- Corrected base migration/status command: exit code 0.
- Corrected CB1 additive migration: exit code 0.
- Approved migration marker: `005.002.000-commercial-correction-build-1`.
- CB1 tables detected: 22.
- CAF tenant, onboarding, services, notes, prices, and base migration state: exact before/after equality.

## Rollback evidence

- Frozen predecessor candidate status against disposable predecessor state: exit code 0.
- CAF rollback-model comparisons: all exact.
- Controlled predecessor source files: byte-for-byte unchanged.
- Upgrade and rollback script ordering/static contract: passed.

## Explicitly unexecuted gates

This build environment does not provide Windows PowerShell, Docker Desktop, or a live PostgreSQL server. Accordingly, the following are **pending**, not passed:

- Actual Windows 10/11 + Docker Desktop upgrade from Dave's current v5.1 Commercial Candidate.
- Actual one-off Docker migration evidence capture on Dave's machine.
- Actual automatic rollback/restart health proof on Dave's machine.
- Live PostgreSQL 16 certification and dump evidence.
- Final Product Owner visual/manual acceptance.

Those tests must be run locally using `docs/CB1-R1-EXACT-LOCAL-UPGRADE-INSTRUCTIONS.md`.

## Evidence

- `qa/CB1-R1-GATE-RESULTS.json`
- `qa/cb1_preflight_result.json`
- `qa/cb1_acceptance_result.json`
- `qa/cb1_release_audit_result.json`
- `qa/V51RC3-*.json`
- `evidence/cb1-r1/regression/REGRESSION-SUMMARY.json`
- `evidence/cb1-r1/regression/`
