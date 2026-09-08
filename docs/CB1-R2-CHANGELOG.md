# CB1-R2 Change Log

Release: `5.2.1-client-admin-correction-po1`

Parent: `5.1.0-commercial-cb1-r1`

Parent artifact SHA-256: `458f53319c20f5bf494b806b22ea9a61c16a8776c1764db9771a477286000878`

## Functional correction

- Corrected only the Windows PowerShell migration-process wrapper in `Invoke-RmrCapturedMigration`.
- Replaced direct native invocation plus `$LASTEXITCODE` with `Start-Process -Wait -PassThru` and the native process `ExitCode`.
- Preserved separate stdout/stderr redirection and all pre-cleanup container evidence.
- Preserved true nonzero failure handling.

## Supporting release work

- Added CB1-R2 release identity, scope lock, provenance, QA gates and checksum controls.
- Added the exact CB1-R1 Windows field evidence that proved the migration container exited `0` while the wrapper reported `1`.
- Added application-payload and predecessor-lineage integrity comparisons.
- Updated local upgrade instructions to use the script's actual `-ExistingInstall` parameter.

## Explicitly unchanged

- Approved CB1 product functionality.
- Application business logic.
- Database schema and migration content.
- CAF data handling.
- Backup/readiness/rollback architecture.
- Production environment.
- Hasan handoff status.
