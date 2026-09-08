# Upgrade RMR Platform v5.0 to v5.1 Commercial Candidate

## Purpose

Use this process only when an existing v5.0 installation is already running and its `data` folder contains records that must be preserved. RC3 is extracted into a separate folder. The v5.0 source folder and data are never overwritten.


## RC3 preflight correction

RC3 recognizes the known v5.0 metadata inconsistency where the v5.0 `.env` can declare `5.0.0-rc1` while the running health endpoint reports `5.0.0-rc.1`. Only that known v5.0 pair is treated as equivalent. RC3 itself must still report the exact `5.1.0-commercial-cb1` version before upgrade success can be certified.

## Windows Docker Desktop — recommended process

1. Leave the current v5.0 folder in place.
2. Download and extract the RC3 ZIP into a new folder.
3. Start Docker Desktop and wait for **Engine running**.
4. Close browser tabs actively changing data in v5.0.
5. In the RC3 folder, double-click:

```text
UPGRADE-FROM-V5.0.bat
```

6. Paste the full path to the existing v5.0 folder and press Enter.
7. Leave the command window open. The process can take several minutes while Docker builds and certifies readiness.

PowerShell alternative:

```powershell
.\UPGRADE-FROM-V5.0.ps1 -ExistingInstall "C:\full\path\to\RMR-Platform-v5.0-Functional-Production-Pilot-Candidate"
```

## What RC3 does

1. Confirms Docker and Compose are available.
2. Runs a bounded health check against v5.0 before touching it.
3. Creates a v5.0 safety backup.
4. Stops v5.0 cleanly.
5. Copies `.env` and persistent data into the separate RC3 folder.
6. Changes only the copied environment version to `5.1.0-commercial-cb1`.
7. Builds the RC3 image.
8. Applies additive migrations with an explicit Python entrypoint.
9. Starts RC3.
10. Polls readiness for up to four minutes.
11. Requires container, Docker health, internal API, host API and exact-version checks to pass.
12. Runs the application status command.
13. Writes `data\LAST-UPGRADE-RESULT.json`.
14. Opens the application after success.

## Successful result

The command window displays:

```text
UPGRADE COMPLETED SUCCESSFULLY
RMR Platform v5.1 Commercial Candidate is healthy and ready.
```

Your original v5.0 folder remains available but stopped. Keep it until RC3 completes manual QC.

## Failed result and automatic rollback

A failed readiness gate does not overwrite v5.0. RC3 automatically:

- writes a diagnostic file under `data\diagnostics`;
- stops/removes the unsuccessful RC3 container;
- restarts the untouched v5.0 installation;
- verifies v5.0 health with bounded polling;
- records the rollback result in `data\LAST-UPGRADE-RESULT.json`.

The command window displays the diagnostic path. Send that text file and `LAST-UPGRADE-RESULT.json` to RMR/ChatGPT. Do not patch source files or manually move database files.

## Linux

```bash
./UPGRADE-FROM-V5.0.sh /full/path/to/RMR-Platform-v5.0-installation
```

The same separation, backup, readiness and rollback principles apply.

## After a successful Windows upgrade

Follow `docs/V5.1-MANUAL-QC-SEQUENCE.md`. Confirm first that:

- your existing RMR Owner login works;
- CAF and other retained tenants are present;
- onboarding notes and client-specific pricing survived;
- Client Administrator invitation and tenant isolation work;
- Back/breadcrumb navigation and Client 360 actions work.

Do not give RC3 to Hasan until the external Windows/Docker upgrade and manual QC sequence pass.
