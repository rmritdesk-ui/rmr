# CB1-R1 Root-Cause Report

## Release and lineage

- Release: `5.1.0-commercial-cb1-r1`
- Frozen v5.1 Commercial Candidate ZIP SHA-256: `506042dff3170c2c2275fd76255f1730992728f5521b5f3d20e6c34e0db7a533`
- Parent CB1 ZIP SHA-256: `33a93d7ac3af3aec1b1ca106355d47143512645b854c41c1851fe8680d36d0ad`
- Frozen baseline SHA-256 retained from CB1 provenance: `edf38dcd1f0a4f573198a96850d97867915f2ee1c20616a9e9a8454c8fad2bfa`

## Field symptom

The Product Owner field run reported that additive database migrations failed with Docker exit code 1. The original diagnostic was collected after the one-off migration container had already been removed, so it showed `not-created`, no readiness attempts, and no migration stdout or stderr. That field diagnostic established the failure point but did not establish the cause.

## Controlled reproduction

A controlled predecessor v5.1 database was created from the frozen Commercial Candidate code and migration state. It contained a CAF fixture with:

- Tenant: `Cactus Air Filters, LLC`
- Tenant ID: `caf-controlled-predecessor-tenant`
- Onboarding note: `CAF CONTROLLED PREDECESSOR NOTE - preserve exactly through CB1-R1 migration.`
- CRM monthly price: 15,000 cents
- Managed Website monthly price: 12,500 cents
- Platform Core monthly price: 2,300 cents

The database was copied to an isolated CB1 reproduction directory. The unchanged parent CB1 migration command was then executed against that copy.

Observed result:

- Exit code: `1`
- Exact failure: `SyntaxError: from __future__ imports must occur at the beginning of the file`
- File: `rmr_platform/db.py`
- Database, WAL, and SHM hashes before and after the failed command: identical

## Actual root cause

The parent CB1 `rmr_platform/db.py` began with:

```python
import os
from __future__ import annotations
```

Python requires `from __future__` imports to appear before ordinary imports. The added `import os` was unused. The interpreter failed while importing the migration CLI, before the database migration code opened or modified the predecessor database.

## Minimum migration correction

CB1-R1 deletes only the unused first line:

```diff
-import os
 from __future__ import annotations
```

The corrected file SHA-256 is `a014ab80ab9762d76398fc9e61619cb0ce6760e51e1107bbec6f404e0b239664`, exactly matching the frozen v5.1 Commercial Candidate implementation. No migration business logic was changed.

## Separately reproduced preservation-only integration correction

After only the migration syntax correction was applied, importing the application exposed a separate pre-existing CB1 route-wiring typo:

```text
NameError: name 'get_current_user' is not defined. Did you mean: 'current_user'?
```

The approved CB1 commercial router was being constructed with an undefined dependency identifier even though `current_user` was already imported and used by the application. CB1-R1 changes that one identifier:

```diff
-app.include_router(_build_cb1_router(get_current_user))
+app.include_router(_build_cb1_router(current_user))
```

This is not the migration root cause. It is a one-token correction required to load and preserve the already-approved CB1 router after the migration blocker is removed. No route behavior or authorization policy was redesigned.

## Evidence

See:

- `evidence/cb1-r1/control-reproduction/`
- `evidence/cb1-r1/source-integrity.json`
- `evidence/cb1-r1/post-migration-integration/`
