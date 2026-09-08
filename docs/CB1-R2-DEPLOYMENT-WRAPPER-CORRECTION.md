# CB1-R2 Deployment-Wrapper Correction

## Changed functional file

`/scripts/RmrDeployment.psm1`

## Changed function

`Invoke-RmrCapturedMigration`

## Before

The wrapper invoked Docker directly, redirected stdout/stderr, and then attempted to read `$LASTEXITCODE`. Windows PowerShell 5.1 could terminate the statement on ordinary native stderr before the exit code assignment.

## After

The wrapper launches Docker with `Start-Process`, waits for completion, redirects stdout and stderr to their existing evidence files, and reads `[System.Diagnostics.Process].ExitCode`.

## Preserved controls

- Unique named one-off migration container.
- No `--rm` before evidence collection.
- Separate migration stdout and stderr files.
- Safe container state, command, logs and Compose evidence.
- Evidence manifest and combined summary.
- Main diagnostic embedding before cleanup on failure.
- Cleanup only after evidence capture.
- Real nonzero Docker exit codes still fail.
- Automatic verified rollback to the untouched v5.1 Commercial Candidate.

## No application change

No business route, model, service, schema, migration, tenant, UI workflow, permission or data-handling logic was changed for CB1-R2. Release-label updates exist only so the separate R2 artifact and running test candidate can be identified objectively.
