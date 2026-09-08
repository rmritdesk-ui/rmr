# Exact Windows/Docker Local Upgrade Instructions — CB1-R2

Release: `5.2.1-client-admin-correction-po1`

These instructions are for Dave's local Windows/Docker Product Owner test only. Do not use them on production and do not send the package to Hasan.

## 1. Preserve the current state

- Leave the existing v5.1 Commercial Candidate folder unchanged.
- Do not delete the CB1-R1 folder or its diagnostics.
- Confirm Docker Desktop shows **Engine running**.
- Confirm the current v5.1 Commercial Candidate opens at `http://localhost:8080` and CAF is present.
- Close the application browser tab so records are not changed during the upgrade.

## 2. Extract CB1-R2 separately

Extract the R2 ZIP into a new folder. Do not extract over the current candidate, CB1 or CB1-R1.

The application root is the folder containing:

- `UPGRADE-FROM-V5.1-CANDIDATE.ps1`
- `docker-compose.yml`
- `scripts`
- `rmr_platform`

## 3. Open PowerShell at the R2 application root

In File Explorer, open the R2 application root, click the address bar, type `powershell`, and press Enter.

## 4. Run the controlled upgrade

Verified predecessor path from the CB1-R1 field test:

```text
C:\Users\davel\Desktop\v5.1 Commercial Candidate ZIP\RMR-Software-v5.1\RMR-Software-v5.1-Commercial-Candidate-Product-Owner-Test
```

Run exactly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\UPGRADE-FROM-V5.1-CANDIDATE.ps1 -ExistingInstall "C:\Users\davel\Desktop\v5.1 Commercial Candidate ZIP\RMR-Software-v5.1\RMR-Software-v5.1-Commercial-Candidate-Product-Owner-Test"
```

Leave the window open. Do not run another command while it is working.

## 5. Required success result

The command must explicitly report:

```text
UPGRADE COMPLETED SUCCESSFULLY
RMR Software v5.1 Correction Build 1 Revision 2 is healthy and ready.
```

The health endpoint and System Health page must identify:

```text
5.2.1-client-admin-correction-po1
```

## 6. Evidence to preserve immediately

Do not delete or move the folders. Preserve:

- `data\LAST-UPGRADE-RESULT.json`
- `data\diagnostics\upgrade-console-*.txt`
- the newest `data\diagnostics\migration-evidence-*` folder
- the newest deployment diagnostic, if any

The migration evidence must show:

- wrapper exit code `0`
- one-off migration container `Exited (0)`
- separate stdout and stderr files
- `captured_before_cleanup: true`

Nonfatal Docker Compose status text may remain in stderr; it must no longer create a false migration failure.

## 7. CAF preservation check

After success, confirm CAF still has its prior:

- tenant identity
- onboarding notes and progress
- services and pricing
- client/contact information
- CRM or operational records already present

Do not create unrelated test changes until preservation is confirmed.

## 8. Automated QC

From the R2 application root, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\RUN-CB1-AUTOMATED-QC.ps1
```

Preserve the report path printed by the script.

## 9. Controlled rollback

After the successful upgrade and preservation checks, run one controlled rollback:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ROLLBACK-TO-V5.1-CANDIDATE.ps1 -PreviousInstall "C:\Users\davel\Desktop\v5.1 Commercial Candidate ZIP\RMR-Software-v5.1\RMR-Software-v5.1-Commercial-Candidate-Product-Owner-Test"
```

The script must verify the predecessor as healthy and version `5.1.0-commercial-rc1`.

Then rerun the R2 upgrade once and reconfirm CAF preservation.

## 10. Stop conditions

Stop and send the evidence before doing anything else when:

- Docker returns a real nonzero exit code.
- The migration container does not show `Exited (0)`.
- CAF data is missing or changed unexpectedly.
- R2 fails health/version readiness.
- Automatic rollback does not restore the predecessor as healthy.

Do not repeatedly retry, manually move database files or alter the scripts.
