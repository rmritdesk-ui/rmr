# CB1-R1 Rollback Evidence

## Architecture preserved

CB1-R1 preserves the established separate-folder rollback design:

1. Verify the current v5.1 Commercial Candidate is healthy.
2. Create a safety backup from the predecessor.
3. Stop the predecessor only after preflight and backup pass.
4. Copy persistent data into the separate CB1-R1 folder.
5. Build, migrate, start, and health-check CB1-R1.
6. On any failure after predecessor stop, capture diagnostics first, stop the unsuccessful R1 attempt, restart the untouched predecessor folder, and poll the predecessor health/version gate.

The predecessor folder is never overwritten by the R1 package.

## Controlled rollback model

A disposable copy of the controlled predecessor CAF state was reopened using the frozen v5.1 Commercial Candidate CLI. Results:

- Candidate status command exit code: `0`
- Current/required migration: `005.001.000-functional-client-experience`
- Tenants found: `1`
- CAF tenant exact comparison: `true`
- CAF onboarding exact comparison: `true`
- CAF services/prices exact comparison: `true`
- Base migration state exact comparison: `true`
- Controlled predecessor source files before/after model exercise: byte-for-byte identical

## Runtime qualification boundary

This build environment does not provide Windows PowerShell, Docker Desktop, or a live PostgreSQL service. Therefore the actual Windows/Docker automatic rollback and PostgreSQL execution are not marked passed here. They remain explicit Product Owner local gates using the exact instructions in `docs/CB1-R1-EXACT-LOCAL-UPGRADE-INSTRUCTIONS.md`.

## Evidence files

- `evidence/cb1-r1/rollback/candidate-status.*`
- `evidence/cb1-r1/rollback/rollback-snapshot.json`
- `evidence/cb1-r1/rollback/rollback-data-comparison.json`
- `evidence/cb1-r1/rollback/source-hash-comparison.txt`
