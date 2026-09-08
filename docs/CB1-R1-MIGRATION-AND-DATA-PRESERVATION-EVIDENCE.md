# CB1-R1 Migration and CAF Data-Preservation Evidence

## Controlled predecessor state

The controlled database began at:

- Current/required migration: `005.001.000-functional-client-experience`
- Applied migrations:
  - `005.000.000-initial-production-pilot`
  - `005.001.000-functional-client-experience`
- CAF tenant, onboarding, notes, services, and prices populated with fixed test values.

The full non-secret snapshot is stored at `evidence/cb1-r1/control-reproduction/predecessor-snapshot.json`.

## Corrected migration execution

1. The frozen v5.1 base migration/status command completed with exit code 0.
2. The governed CB1 additive migration completed with exit code 0.
3. Returned marker: `005.002.000-commercial-correction-build-1`.
4. Twenty-two CB1 tables were detected after migration.

## Exact preservation comparisons

The automated comparison reported:

- `tenant_exact: true`
- `onboarding_exact: true`
- `services_exact: true`
- `base_migrations_preserved: true`
- `cb1_migration_applied: true`
- `cb1_tables_created: true`
- Overall status: `passed`

The exact CAF onboarding note, all eight onboarding steps, data JSON, tenant fields, service records, monthly prices, cadence, and status remained unchanged.

## Hash interpretation

The failed unchanged-CB1 reproduction left the database, WAL, and SHM files byte-for-byte unchanged because Python stopped at import time. During the successful migration, SQLite WAL/SHM hashes changed as expected while schema changes were committed. Therefore successful preservation is established by exact row-level before/after comparisons, not by requiring the complete SQLite file set to remain byte-identical after an additive schema migration.

## Evidence files

- `evidence/cb1-r1/corrected-migration/cli-migrate.*`
- `evidence/cb1-r1/corrected-migration/cb1-migration.*`
- `evidence/cb1-r1/corrected-migration/post-migration-snapshot.json`
- `evidence/cb1-r1/corrected-migration/data-preservation-comparison.json`
