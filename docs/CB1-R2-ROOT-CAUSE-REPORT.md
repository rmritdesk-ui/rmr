# CB1-R2 Root-Cause Report

Release: `5.2.1-client-admin-correction-po1`

## Executive finding

The CB1-R1 Windows/Docker test did **not** expose a database migration failure. It exposed a Windows PowerShell 5.1 deployment-wrapper false failure.

The preserved CB1-R1 evidence reported wrapper exit code `1`, while the retained one-off migration container showed all of the following:

- Docker container state `ExitCode: 0`.
- Container listing `Exited (0)`.
- The migration command was `python -m rmr_platform.cli migrate`.
- The container log returned the current and required migration state successfully.
- The prior v5.1 Commercial Candidate was restarted and independently reported healthy after the wrapper entered its failure branch.

The only content in the migration stderr capture was ordinary Docker Compose progress text for network creation, represented by Windows PowerShell as a `System.Management.Automation.RemoteException`.

## Actual failure mechanism

`UPGRADE-FROM-V5.1-CANDIDATE.ps1` intentionally sets:

```powershell
$ErrorActionPreference = 'Stop'
```

CB1-R1's `Invoke-RmrCapturedMigration` called Docker directly and redirected native stdout and stderr:

```powershell
& docker @arguments 1> $stdoutPath 2> $stderrPath
$exitCode = $LASTEXITCODE
```

In Windows PowerShell 5.1, native stderr can be represented on PowerShell's error stream. Under `ErrorActionPreference=Stop`, ordinary Docker Compose status text caused control to enter `catch` before `$LASTEXITCODE` was read. The catch block then assigned exit code `1`, even though Docker and the migration container completed successfully with exit code `0`.

## Minimum correction

CB1-R2 changes only `Invoke-RmrCapturedMigration` in `scripts/RmrDeployment.psm1`:

```powershell
$process = Start-Process -FilePath 'docker' -ArgumentList $arguments -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
$exitCode = [int]$process.ExitCode
```

This makes the native Docker process exit code authoritative and preserves raw stdout and stderr in separate files without allowing ordinary stderr text to become a terminating PowerShell error.

## Failure behavior preserved

The correction does not turn errors into successes:

- Docker exit code `0` is treated as success even when stderr contains nonfatal status text.
- Docker exit code greater than `0` remains a migration failure.
- Failure to launch Docker remains an exception and is recorded as exit code `1`.
- Migration evidence remains captured before one-off-container cleanup.
- Automatic rollback remains unchanged.

## Scope boundaries

CB1-R2 does not change:

- RMR application workflows or commercial functionality.
- Database schema or migration content.
- CAF data, onboarding, services, notes, pricing or history.
- Tenant isolation, security or permissions.
- Backup, readiness or rollback architecture.
- Production systems.

The exact Windows/Docker field evidence is preserved at:

`evidence/cb1-r2/windows-field-reproduction/CB1-R1-WINDOWS-MIGRATION-EVIDENCE-SUMMARY.txt`
