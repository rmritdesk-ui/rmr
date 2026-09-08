# CB1-R1 Migration Diagnostic Collector

## Correction

The upgrade no longer runs the one-off migration container with `--rm`. `Invoke-RmrCapturedMigration` assigns a unique container name, executes the migration, and writes the following evidence before any cleanup:

- `migration.stdout.txt`
- `migration.stderr.txt`
- `container-state.json`
- `container-command.txt`
- `container-logs.txt`
- `container-ps.txt`
- `compose-ps.txt`
- `evidence-manifest.json`
- `migration-evidence-summary.txt`

The collector intentionally avoids unrestricted `docker inspect` output because that can expose environment secrets. It captures only the safe state, image/path/arguments, logs, and relevant container/Compose listings.

## Failure order

On migration failure, `UPGRADE-FROM-V5.1-CANDIDATE.ps1` now performs this order:

1. Preserve migration stdout/stderr and safe container evidence.
2. Build the main deployment diagnostic and embed the preserved files.
3. Remove the one-off migration container.
4. Stop the unsuccessful R1 stack attempt if necessary.
5. Restart and health-check the untouched predecessor candidate.
6. Write `data/LAST-UPGRADE-RESULT.json` with evidence paths and rollback status.

## Evidence location on Windows

After a local run, evidence is written under:

```text
data\diagnostics\migration-evidence-<run-id>\
```

The main failure diagnostic is also written in `data\diagnostics` and includes the migration evidence contents.
