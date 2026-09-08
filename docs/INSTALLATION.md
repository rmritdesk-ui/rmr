# RMR Platform v5.1 Commercial Candidate Installation Guide

## Installation objective

The supported experience is:

1. Extract one versioned RMR release.
2. Supply only target-environment configuration.
3. Run one supported installer entry point.
4. Let the installer build/start the application, migrate the database and validate health.
5. Complete first-run browser setup.

Hasan/Step2 should not edit application source or database schema during a normal installation.

## Pilot topology

v5.1 uses one application container and one persistent data directory. SQLite in WAL mode is suitable for controlled single-server pilot use. PostgreSQL certification is required before scaled/multi-node production.

Recommended pilot host:

- 64-bit Windows or Linux capable of current Docker/Compose
- 4 CPU cores
- 8 GB RAM
- 40 GB free SSD plus upload/backup capacity
- Administrator/root access
- Stable internet access during image build
- Reserved domain/subdomain for target-server validation

## Prerequisite

Install and start:

- Docker Desktop on Windows, or
- Docker Engine + Docker Compose v2 on Linux.

Verify:

```text
docker version
docker compose version
docker info
```

## Empty first-run install — recommended

### Windows

1. Extract the release.
2. Start Docker Desktop and wait for **Engine running**.
3. Double-click `INSTALL-PRODUCTION.bat`.

PowerShell alternative:

```powershell
.\INSTALL.ps1 -Profile empty
```

### Linux

```bash
./INSTALL.sh empty
```

### Installer actions

- verifies Docker, Compose and engine availability;
- creates persistent data/training/backup folders;
- creates `.env` from `.env.example` if needed;
- generates application secret and one-time setup token;
- selects empty profile and disables demo credentials;
- builds the pinned `5.1.0-commercial-cb1` image;
- starts the application and applies migrations;
- loads governed reference data;
- waits for `/api/health`;
- writes `data/INSTALLATION-STATUS.json`;
- writes `data/INITIAL-SETUP.txt` for one-time setup;
- opens the browser after health passes.

### First-run browser setup

Open the URL printed by the installer (default `http://localhost:8080`). Enter the one-time token and create:

- RMR Owner;
- optional Step2 Platform Administrator.

The system verifies the exact owner credentials, signs the owner in automatically, invalidates the token and removes `data/INITIAL-SETUP.txt`.

## Demo install

Windows: double-click `INSTALL-DEMO.bat`
Linux: `./INSTALL.sh demo`

The demo profile is only for product review. Never use demo credentials with real client data.

## Environment configuration

Review `.env` before any network-accessible deployment:

```text
RMR_ENVIRONMENT=production
RMR_BASE_URL=https://platform.example.com
RMR_COOKIE_SECURE=true
RMR_PUBLIC_PORT=8080
RMR_PAYMENT_PROVIDER=mock
RMR_LOCAL_RECOVERY_MODE=false
```

Do not commit or transmit `.env` with live secrets.

## Invitation/reset delivery

When SMTP is not configured and `RMR_LOCAL_RECOVERY_MODE=true`, the application can expose controlled local invitation/reset links and writes recovery artifacts within the protected data directory. This is pilot-only behavior.

Before public production:

- configure approved outbound email;
- set `RMR_LOCAL_RECOVERY_MODE=false`;
- confirm invitation/reset links use the public HTTPS base URL;
- restrict filesystem access to application operators.

## Domain, reverse proxy and TLS

The container listens on `RMR_PUBLIC_PORT`. The target administrator must:

- terminate HTTPS/TLS;
- forward to the local application port;
- preserve original host/forwarded headers;
- redirect HTTP to HTTPS;
- apply RMR firewall rules;
- configure file-size/timeouts appropriate for training uploads.

Then set `RMR_BASE_URL` and `RMR_COOKIE_SECURE=true`, restart and rerun health.

## Verify installation

Linux:

```bash
./HEALTH-CHECK.sh
./STATUS.sh
```

Windows:

```powershell
.\HEALTH-CHECK.ps1
.\STATUS.ps1
```

Also verify:

- owner exact credentials authenticate;
- setup token file is removed;
- first client creation/invitation works;
- client activation/login works;
- tenant isolation and RMR read-only support denials work;
- restart persistence works.

Use `docs/V5.1-MANUAL-QC-SEQUENCE.md`.

## Upgrade from v5.0

Use `UPGRADE-FROM-V5.0.ps1/.bat/.sh` from a separately extracted v5.1 folder. See `docs/UPGRADE-FROM-V5.0.md`.

## Backup

```bash
./BACKUP.sh
```

or:

```powershell
.\BACKUP.ps1
```

Backups include a consistent database snapshot, training uploads and manifest. Copy archives off-server for real disaster recovery.

## Restore

Linux:

```bash
./RESTORE.sh data/backups/<archive>.tar.gz
```

Windows:

```powershell
.\RESTORE.ps1 -BackupPath data\backups\<archive>.tar.gz
```

The restore stops the app, creates a pre-restore safety backup when possible, restores data, restarts and health-checks.

## Rollback

See `docs/V5.1-ROLLBACK.md`. Keep the prior installation folder and matching pre-upgrade backup until v5.1 is accepted.

## Installation failure policy

1. Capture full launcher output.
2. Capture `docker compose ps`.
3. Capture `docker compose logs --tail=200 app`.
4. Record OS/Docker/Compose/CPU/RAM/storage and exact command.
5. Do not edit source or schema.
6. Return the reproducible issue to RMR for a numbered correction.

## Diagnostic collection

Windows: double-click `COLLECT-DIAGNOSTICS.bat`. Linux: run `./COLLECT-DIAGNOSTICS.sh`. Send the generated file under `data/diagnostics` to RMR/ChatGPT.
