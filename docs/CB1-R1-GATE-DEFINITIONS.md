# CB1-R1 Frozen Gate Definitions

Release: `5.1.0-commercial-cb1-r1`

These seven gates translate the approved CB1-R1 correction scope into objective pass/fail evidence. They do not add product scope.

## R1-01 - Controlled failure reproduction

PASS requires the unchanged CB1 migration command to be run against a disposable copy of a controlled predecessor v5.1 database containing CAF records. The command must fail with exit code 1 and preserve the exact Python error. The predecessor database copy must remain byte-for-byte unchanged by the failed command.

## R1-02 - Proven minimum correction

PASS requires the migration root cause to be identified from the preserved error, not inferred. The corrected `rmr_platform/db.py` must remove only the unused line that illegally preceded the mandatory `from __future__` header and must match the frozen predecessor file hash. Any additional source correction must be separately reproduced, minimal, and required only to preserve already-approved CB1 functionality.

## R1-03 - Corrected additive migration

PASS requires the predecessor v5.1 migration state to load successfully, the governed CB1 additive migration `005.002.000-commercial-correction-build-1` to complete with exit code 0, and the expected CB1 schema objects to exist.

## R1-04 - CAF data preservation

PASS requires exact before/after equality for the controlled CAF tenant, onboarding project and steps, onboarding notes/data, services, prices, cadence, status, and base migration state. The CB1 migration may add schema and CB1 records but may not rewrite the predecessor CAF business data.

## R1-05 - Pre-cleanup migration diagnostics

PASS requires the Windows/Docker upgrade path to run the one-off migration container without `--rm`; write migration stdout and stderr separately; capture safe container state, command, logs, container listing, Compose state, and a manifest; embed those files in the main diagnostic when migration fails; and only then remove the one-off container.

## R1-06 - Rollback preservation and evidence

PASS requires the existing automatic rollback architecture to remain intact: the predecessor is checked healthy and backed up before stop, the separate R1 attempt is stopped after failure, the untouched predecessor is restarted, and predecessor health/version is verified. Controlled rollback-model evidence must show the predecessor candidate can reopen a disposable predecessor state with CAF data unchanged. Exact Windows/Docker execution remains a Product Owner local gate.

## R1-07 - Separate candidate, boundaries, and regression integrity

PASS requires a separately named/versioned Product Owner artifact; no overwrite of the current candidate or CB1; no production action; no Hasan handoff artifact; no runtime `.env`, database, cache, or secret material in the ZIP; preserved frozen lineage hashes; and PASS results for all runnable CB1/v5.1 regression gates. Windows Docker Desktop and live PostgreSQL certification must be reported as pending local gates rather than silently marked passed.
