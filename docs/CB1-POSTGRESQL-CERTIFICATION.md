# PostgreSQL Commercial-Production Certification

Correction Build 1 includes a PostgreSQL deployment path but does not claim it passed in the build environment.

Run `POSTGRESQL-CERTIFY.bat` on a Docker-capable machine. The process:

1. Starts PostgreSQL 16 and CB1 with `RMR_DATABASE_URL=postgresql+psycopg://...`.
2. Waits for database and application health.
3. Applies the governed CB1 migration.
4. Confirms the required commercial tables exist.
5. Writes and reads a certification marker.
6. Creates a `pg_dump` backup as evidence.

Production acceptance additionally requires v5.0/SQLite data migration to PostgreSQL, count/hash reconciliation, restore testing, upgrade and forced rollback. Those steps must be recorded in the Acceptance Matrix and cannot be inferred from the SQLite automated suite.
