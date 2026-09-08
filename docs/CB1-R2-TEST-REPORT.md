# CB1-R2 Test Report

Release: `5.2.1-client-admin-correction-po1`

Status: **PASS for every runnable source, application, migration-model, CAF-preservation, browser, backup/restore and deployment-wrapper gate in this build environment.**

Product status: **Windows/Docker Product Owner test candidate only. Not accepted for production. No Hasan handoff.**

## Actual CB1-R1 Windows field evidence used

The preserved field evidence established the real defect before R2 was changed:

- CB1-R1 wrapper reported migration exit code `1`.
- The retained Docker migration container reported `ExitCode: 0` and `Exited (0)`.
- The migration container returned valid current/required migration status.
- The only captured stderr was ordinary Docker Compose network-creation progress represented as a PowerShell `RemoteException`.
- The inherited rollback path restored the prior v5.1 Commercial Candidate and verified it healthy.

This evidence is packaged under `evidence/cb1-r2/windows-field-reproduction/`.

## CB1-R2 correction gates

- R2-01 Actual Windows field evidence reconciled: passed.
- R2-02 Minimum deployment-wrapper correction: passed.
- R2-03 Success with nonfatal native stderr: passed.
- R2-04 Genuine failure and rollback behavior preserved: passed.
- R2-05 Pre-cleanup diagnostics preserved: passed.
- R2-06 Application, CAF, lineage and rollback preservation: passed.
- R2-07 Separate artifact and authorization boundaries: passed before final sealing.

R2 source/package-preparation total: **7/7 gates and 47/47 checks passed.** The sealed ZIP is rechecked separately after clean extraction; the returned external validation report is authoritative for final artifact integrity.

## Deployment-wrapper behavior model

- Start-Process/native exit-code contract: passed.
- Successful Docker exit `0` with nonempty stderr remains success: passed.
- Genuine Docker exit `1` remains failure: passed.
- Docker launch exception remains failure: passed.
- Separate stdout/stderr and pre-cleanup evidence contract: passed.

Wrapper model: **10/10 checks passed.** This is a static/behavioral model, not a substitute for the exact Windows PowerShell 5.1 field retest.

## Existing CB1 and inherited v5.1 regression suites

- v5.1 acceptance: 122 passed, 0 failed.
- CB1 preflight: 29 passed, 0 failed.
- CB1 functional acceptance: 40 passed, 0 failed.
- CB1 release audit: 38 passed, 0 failed.
- v5.1 backup/restore: 13 passed, 0 failed.
- v5.1 browser acceptance: 40 passed, 0 failed.
- v5.1 health messaging: 6 passed, 0 failed.
- v5.1 static audit: 68 passed, 0 failed.
- v5.1 upgrade preservation: 17 passed, 0 failed.
- v5.1 upgrade reliability: 60 passed, 0 failed.
- Python tests: 15 passed.
- Python compile-all: passed.

Inherited structured checks: **433 passed, 0 failed**, plus 15 pytest tests and compile-all.

## Application and data integrity

- All application files are byte-identical to CB1-R1 except six explicit release-label files.
- `rmr_platform/db.py`, `main.py`, `migrations.py`, `cb1_migration.py`, `models.py` and `cb1_models.py` are byte-identical to CB1-R1.
- No schema or migration-content change was made.
- Historical R1 CAF before/after comparison remains passed.
- Parent CB1-R1 artifact SHA-256 is locked to `458f53319c20f5bf494b806b22ea9a61c16a8776c1764db9771a477286000878`.

## Explicitly pending

This build environment does not provide Windows PowerShell 5.1, Docker Desktop or a live PostgreSQL 16 service. The following are pending and are **not** represented as passed:

- Exact CB1-R2 upgrade on Dave's Windows/Docker environment.
- Proof that nonfatal Compose stderr no longer creates a false wrapper failure.
- Exact CAF preservation after the packaged R2 upgrade.
- Controlled automatic/manual rollback against the packaged R2 artifact.
- Re-upgrade after rollback.
- Live PostgreSQL certification and dump evidence.
- Final Product Owner acceptance/freeze decision.

Use `docs/CB1-R2-EXACT-LOCAL-UPGRADE-INSTRUCTIONS.md` for the next test.
