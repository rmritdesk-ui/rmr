# RMR Global + integrated ProspectIQ

This repository contains the complete RMR application and native PIQ workflow:
target profiles, Google Places discovery, evidence/matching, Adaptive Research,
and Move to CRM. Standalone ProspectIQ, Node/Express, Redis and BullMQ are **not**
runtime dependencies.

## Stack

Python 3.13, FastAPI/Uvicorn, SQLAlchemy, psycopg, and same-origin HTML/CSS/ES-module
JavaScript served by RMR. Production target: dedicated PostgreSQL 16. SQLite is
supported for isolated local development and deterministic tests.

## Environment and local setup

Install Python 3.13 and create a virtual environment. Install dependencies:

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Use [.env.example](.env.example) as a reference, not a working secret file.
The Python application does not automatically load .env: export settings into
the process environment, or pass a private env file to Docker with --env-file.
Never use a Product Owner, standalone PIQ, or production database for development.

For a local empty install set RMR_ENVIRONMENT=development,
RMR_DATA_DIR to a new local directory, RMR_DATABASE_URL to an isolated SQLite
database, RMR_BASE_URL to the local URL and RMR_COOKIE_SECURE=false.
Supply a unique RMR_SECRET_KEY and RMR_SETUP_TOKEN. Keep providers/workers OFF.
With RMR_AUTO_MIGRATE=false:

```sh
python -m rmr_platform.cli migrate
python -m rmr_platform.server
```

Open the configured URL and complete first-owner setup. For explicit local demo
development only, use a separate DB with RMR_INSTALL_PROFILE=demo,
RMR_AUTO_SEED=true and RMR_ALLOW_DEMO_CREDENTIALS=true. Production rejects these
settings. Never copy an existing demo DB into production.

## Migrations

```sh
python -m rmr_platform.cli migrate
```

This is the single complete supported command: core/PIQ migrations through
005.008.000-piq-profile-collection, CB1 migration ledger, commercial tables and
governed reference catalogs. It creates no demo tenants or users and can be rerun.

RMR_AUTO_MIGRATE=true permits that same bootstrap during application lifespan.
With false, imports/startup/status/health perform no schema DDL. An incomplete
database fails startup with instructions to migrate explicitly. This is a custom
migration runner, not alembic upgrade head. Run one controlled migrator at a time.

## Tests (offline providers)

```sh
python -m playwright install chromium
python -m pytest tests -q -p no:cacheprovider
python -m pytest qa/test_piq_phase3_browser.py qa/test_piq_phase4_browser.py qa/test_piq_phase5_browser.py qa/test_piq_workflow_browser.py qa/test_piq_parity_browser.py qa/test_piq_contract_browser.py -q -p no:cacheprovider
```

Use isolated environment settings and no provider credentials. Docker is the
recommended reproducible/network-isolated gate:

```sh
docker build --target test -t rmr-release-test:local .
docker run --rm --network none rmr-release-test:local
docker run --rm --network none rmr-release-test:local python -m pytest qa/test_piq_phase3_browser.py qa/test_piq_phase4_browser.py qa/test_piq_phase5_browser.py qa/test_piq_workflow_browser.py qa/test_piq_parity_browser.py qa/test_piq_contract_browser.py -q -p no:cacheprovider
```

PostgreSQL gates are documented in
[production preparation](docs/PRODUCTION-PREPARATION.md).

Default tests exclude only the three legacy packaging checks that require private
PO archives/launchers, not application behavior. With those historical materials
present locally, run: python -m pytest tests/test_commercial_static.py tests/test_tenant_themes.py -m legacy_packaging.
They are intentionally unavailable in a clean production repository/image.

## Docker image

```sh
docker build --target runtime --build-arg RMR_VERSION=<release-tag> --build-arg RMR_REVISION=<commit-sha> -t rmr-global:<release-tag> .
```

The verification stage runs preserved build gates. The test stage adds pytest,
Chromium and test-only dependencies. The final runtime contains application
source/assets, not QA/tests/reports/local data, and runs as UID/GID 10001.
It listens on container port 8000 and stores application files under /data.

Existing Compose files are **local/pilot, certification, Product Owner or manual
acceptance definitions**, not production deployment approval. A production
Compose file is intentionally not created in this repository-preparation task.

## Repository hygiene

Keep source, maintained tests/fixtures, documentation and sanitized templates.
Keep populated env files, DB/WAL/SHM files, volume data, evidence, generated QA
reports, private demo credentials and historical control archives local/ignored.
No existing local material is deleted by these exclusions.

Run the offline candidate scanner before staging:

```sh
python scripts/scan_release_candidate.py
```

It prints paths/categories/status only, never matched credential values. Review
all findings; known demo/test literals are not production secrets. Git ignore
rules do not remove files already tracked: always inspect the eventual staged
list and scan again before any push.

Historical packaging instructions remain in
[legacy README](docs/archive/README-PRE-REPOSITORY-PREP.md); they are not the
production deployment procedure.
