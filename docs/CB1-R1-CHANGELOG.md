# RMR Software v5.1 Commercial Candidate Correction Build 1 Revision 1 - Change Log

Release: `5.1.0-commercial-cb1-r1`

Parent: `5.1.0-commercial-cb1`

## Application corrections

1. Removed one unused `import os` line that illegally preceded `from __future__ import annotations` in `rmr_platform/db.py`. This is the proven additive migration failure root cause.
2. Corrected one undefined dependency identifier in `rmr_platform/main.py` from `get_current_user` to the already imported `current_user`. This separate one-token correction preserves the approved CB1 commercial router after the migration blocker is removed.

No migration business logic, schema intent, tenant policy, role policy, UI workflow, commercial functionality, or unrelated product behavior was redesigned.

## Diagnostic correction

- Runs the one-off migration container without `--rm`.
- Captures migration stdout and stderr separately.
- Captures safe container state, command, logs, container listing, and Compose state.
- Writes an evidence manifest and combined summary.
- Embeds preserved migration evidence in the main deployment diagnostic before cleanup.
- Records evidence paths in `data/LAST-UPGRADE-RESULT.json`.

## Release and test packaging

- Aligned the inherited CB1 PostgreSQL driver declaration from an open range to `psycopg[binary]==3.2.9` so the existing v5.1 dependency-pin regression gate remains enforceable. This is a deterministic packaging lock only; no application behavior or database logic was changed.
- Uses separate release identity `5.1.0-commercial-cb1-r1`.
- Preserves the current candidate and parent CB1 as separate artifacts.
- Adds R1-01 through R1-07 gates, root-cause evidence, CAF preservation evidence, rollback evidence, and exact local instructions.
- Removes the inherited Hasan handoff document from this Product Owner-only package.
- Does not touch production.
