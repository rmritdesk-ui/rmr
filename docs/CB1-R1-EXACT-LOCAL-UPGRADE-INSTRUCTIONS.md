# Exact Windows/Docker Product Owner Upgrade Instructions - CB1-R1

This is a local Product Owner test candidate. Do not deploy it to production and do not send it to Hasan.

## 1. Preserve the current folders

Keep both of these existing folders unchanged:

- The current v5.1 Commercial Candidate folder that is running CAF.
- The prior CB1 folder, if present.

Extract CB1-R1 into a completely new folder. Do not extract over either existing folder.

## 2. Verify the ZIP checksum

Open PowerShell in the folder containing the downloaded ZIP and run:

```powershell
Get-FileHash .\RMR-Software-v5.1-Commercial-Candidate-Correction-Build-1-Revision-1-Product-Owner-Test.zip -Algorithm SHA256
```

Compare the result exactly with the companion `...-SHA256.txt` file. Stop if it does not match.

## 3. Confirm the predecessor before upgrade

1. Start Docker Desktop and wait for **Engine running**.
2. Open `http://localhost:8080`.
3. Sign in as RMR Owner.
4. Confirm the displayed version is `5.1.0-commercial-rc1`.
5. Confirm CAF is present and review at least one known onboarding note, service, and price.
6. Close the browser tab so no records are being edited.

## 4. Start the controlled upgrade

Use either method below.

### Double-click method

1. Open the extracted CB1-R1 folder.
2. Double-click `UPGRADE-FROM-V5.1-CANDIDATE.bat`.
3. When PowerShell requests `ExistingInstall`, paste the full path to the current v5.1 Commercial Candidate root folder. That folder must contain `.env`, `docker-compose.yml`, `data`, and `rmr_platform`.
4. Leave the command window open until it reports success or verified rollback.

### Explicit PowerShell method

From the extracted CB1-R1 root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\UPGRADE-FROM-V5.1-CANDIDATE.ps1 -ExistingInstall "C:\full\path\to\RMR-Software-v5.1-Commercial-Candidate-Product-Owner-Test"
```

The upgrade must:

- Verify predecessor health.
- Create a safety backup.
- Stop the predecessor only after those gates pass.
- Copy data into the separate R1 folder.
- Build R1.
- Capture additive migration stdout, stderr, and safe container evidence before cleanup.
- Start R1 and verify host/internal/container/version health.
- Automatically restart and verify the predecessor if R1 fails.

## 5. Verify success

A successful run must explicitly report `5.1.0-commercial-cb1-r1` healthy. Then:

1. Open `http://localhost:8080/api/health` and confirm `status` is `healthy` and `version` is `5.1.0-commercial-cb1-r1`.
2. Open `http://localhost:8080` and sign in as RMR Owner.
3. Confirm CAF is present.
4. Confirm the known CAF onboarding note, services, and prices remain unchanged.
5. Confirm the approved CB1 commercial pages and controls still load.
6. Review `data\LAST-UPGRADE-RESULT.json`.

## 6. Review migration evidence

Open the newest folder under:

```text
data\diagnostics\migration-evidence-<run-id>\
```

Confirm it contains migration stdout, stderr, container state, command, logs, container listing, Compose state, manifest, summary, and cleanup evidence.

## 7. Run local Product Owner gates

Run:

```text
RUN-CB1-AUTOMATED-QC.bat
```

Then complete the existing manual CB1 Product Owner sequence in `docs\CB1-PRODUCT-OWNER-MANUAL-QC.md`.

For PostgreSQL certification, use `POSTGRESQL-CERTIFY.bat` only in the isolated Product Owner test environment. It must not target production.

## 8. Controlled rollback test

To test rollback explicitly, run from the R1 folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\ROLLBACK-TO-V5.1-CANDIDATE.ps1 -PreviousInstall "C:\full\path\to\RMR-Software-v5.1-Commercial-Candidate-Product-Owner-Test"
```

Success must report that the previous v5.1 Commercial Candidate is healthy at `http://localhost:8080`. Confirm CAF again before any R1 retry.

## 9. Evidence to retain

Retain, but do not email publicly:

- `data\LAST-UPGRADE-RESULT.json`
- Newest `data\diagnostics\upgrade-console-*.txt`
- Newest `data\diagnostics\migration-evidence-*` folder
- Main deployment diagnostic, if created
- Automated QC output
- PostgreSQL certification output, if run
- Screenshots showing predecessor version/CAF before, R1 version/CAF after, and predecessor health after rollback
