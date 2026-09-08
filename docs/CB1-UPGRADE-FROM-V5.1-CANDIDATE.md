# Windows / Docker Upgrade from the Current v5.1 Commercial Candidate

## Before starting

1. Keep the currently accepted `5.1.0-commercial-rc1` folder unchanged.
2. Confirm Docker Desktop says **Engine running**.
3. Open `http://localhost:8080`, sign in as RMR Owner and confirm CAF is present.
4. Close the browser tab so no records are being changed during the upgrade.
5. Extract Correction Build 1 into a completely separate folder. Do not extract it over the current candidate.

## Upgrade

1. In the Correction Build 1 folder, double-click `UPGRADE-FROM-V5.1-CANDIDATE.bat`.
2. When asked, select the root of the currently running v5.1 candidate containing `.env`, `docker-compose.yml`, `data`, `rmr_platform`, `START` and `STOP`.
3. Leave the command window open.
4. The process validates the source, creates safety evidence, stops the source only after preflight, copies persistent data, builds CB1, runs migrations, starts CB1 and polls container/internal/host/version health.
5. Success must explicitly report that `5.1.0-commercial-cb1` is healthy.

## After success

- Review `data/LAST-UPGRADE-RESULT.json`.
- Confirm the version on System Health and Commercial Readiness.
- Confirm CAF and its previous notes/services remain.
- Begin the Product Owner QC sequence in `docs/CB1-PRODUCT-OWNER-MANUAL-QC.md`.

## If the upgrade fails

Do not manually move database files or retry repeatedly. The process should capture diagnostics and restart the unchanged prior candidate. Upload:

- `data/LAST-UPGRADE-RESULT.json`
- the newest file in `data/diagnostics`
- the upgrade console transcript if present
