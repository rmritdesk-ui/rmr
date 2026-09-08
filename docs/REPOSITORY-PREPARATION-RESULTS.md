# Repository/release preparation validation — 2026-09-08

Scope: this repository only. No Git initialization/push, VPS deployment, live
provider calls, sealed source change, Product Owner database change or standalone
PIQ change. Existing populated env files and local data were not modified.

## Implemented

- Git exclusions preserve source/maintained tests/docs while excluding private
  env/data/database/WAL/SHM files, evidence, generated QA reports, control archives,
  caches and local credentials. Maintained JSON QA fixtures are explicitly kept.
- Docker context is allowlisted. Verification/test stages remain available; the
  final non-root runtime contains only required application source/assets/deps.
- Production-oriented env reference is deduplicated and has no real credentials.
  Live features stay off pending explicit approval. Existing .env is unchanged.
- CLI migrate owns core/PIQ, CB1, commercial schema and reference catalog setup.
  Import, status, health and AUTO_MIGRATE=false startup perform no schema DDL.
  Uninitialized startup fails closed with the explicit migration instruction.
  AUTO_MIGRATE=true uses the same complete bootstrap. Production rejects demo
  profile/seeding/login/recovery overrides and demo seed/reset CLI commands.
- README and production preparation instructions replace legacy packaging advice;
  the prior README is retained under docs/archive/.
- The offline candidate scanner emits only paths/categories/status. Reviewed
  non-secret matches are recorded by exact path and fingerprint, not secret value.

## Final validation

| Gate | Result |
|---|---|
| Backend suite, including PIQ workflow/research/CRM and 10 new bootstrap/safety tests | 410 passed; 3 archive-only checks deselected |
| Six PIQ browser suites, fully intercepted requests | 132 passed |
| PostgreSQL PIQ concurrency/workflow/research | 21 passed |
| Fresh PostgreSQL 16 complete bootstrap/read-only startup/idempotency/FK checks | 3 passed |
| Preserved legacy packaging checks, private artifacts mounted read-only | 3 passed |
| Docker dependency / interaction / theme-preservation gates | 15 / 28 / 14 passed |
| Git inclusion/exclusion assertions | 19 passed |
| Env template duplicate-key check | Passed |
| Runtime image build and non-root UID 10001/content checks | Passed |
| Final image: explicit CLI migration, PostgreSQL boot, health/login/empty owner setup, hidden demo logins | Passed |
| Candidate credential scan after review | No unresolved matches; populated env/data excluded |

Initial backend failures were three legacy packaging expectations (PO launcher,
frozen ZIP and source screenshot). Runtime source/preview assertions remain in
the standard suite; the three archive-only assertions remain intact as explicit
legacy_packaging tests and were independently passed. No functional failure was
hidden or converted to an expected failure. One upstream TestClient deprecation
warning remains; it does not fail validation.

Backend/browser runs used network-none containers. PostgreSQL runs used a newly
created internal-only network, no published ports and disposable RAM-backed DB
storage. No populated local .env or existing DB was supplied to application tests.
Provider/worker switches were off for full-application boot tests. Test images
remain local; disposable app/PostgreSQL containers and their network were removed.

## Boundaries

Repository hygiene is ready for a future private Git initialization and staging
review; inspect the actual staged list and scan again before pushing. Ignore
rules are not protection against forced adds or already tracked secrets. Pattern
scanning plus reviewed fixtures cannot guarantee detection of every possible
secret format; no credential values are printed in the report.

VPS deployment is not approved by this gate. It still needs its dedicated Compose
definition, real production secrets/SMTP, approved provider limits, actual domain,
port/proxy inventory, HTTPS, backups/restore/logging/monitoring and target-server
acceptance. Built-in backups remain SQLite-only. See PRODUCTION-PREPARATION.md.
