# CB1-R2 Gate Definitions

## R2-01 — Actual field evidence reconciled

Prove the CB1-R1 wrapper reported exit `1` while the migration container exited `0`, emitted valid migration state, and preserved evidence before cleanup.

## R2-02 — Minimum wrapper correction

Prove only `Invoke-RmrCapturedMigration` changed functionally and now uses `Start-Process`, separate stdout/stderr redirection and `Process.ExitCode`.

## R2-03 — Success-with-stderr behavior

Model and statically verify that nonempty native stderr plus Docker exit `0` yields wrapper exit `0`.

## R2-04 — Genuine failure behavior

Model and statically verify that Docker exit greater than `0` remains a failure and still captures diagnostics before cleanup.

## R2-05 — Diagnostic preservation

Verify stdout, stderr, safe container evidence, manifest, summary and main diagnostic embedding remain present and pre-cleanup.

## R2-06 — Application/data/rollback preservation

Verify the sealed R1 parent hash, unchanged application payload except release labels, unchanged schema/migration sources, preserved CAF evidence and unchanged rollback sequencing.

## R2-07 — Artifact and authorization boundaries

Verify separate R2 name/root/version, manifest integrity, no runtime database or `.env`, no Hasan handoff and explicit Windows/Docker Product Owner retest status.
