# RMR Platform v5.1 Operations Runbook

## Daily checks

- open System Health and review headline/action;
- inspect failed/degraded technical cards;
- review unread notifications and Service Requests;
- review onboarding/access status;
- confirm scheduled/off-server backup process;
- monitor disk usage for database, uploads, images and backups.

## Start / stop / status

Linux: `START.sh`, `STOP.sh`, `STATUS.sh`, `HEALTH-CHECK.sh`, `LOGS.sh`
Windows: matching `.ps1` files.

## Client access

Global administrators create/resend/revoke Client Administrator invitations. Clients set their own passwords. Do not create or retain client passwords.

## Password recovery

Users use Forgot Password. In pilot/no-email mode, authorized operators retrieve the local reset link. RMR Owner emergency recovery uses:

```bash
python -m rmr_platform.cli recover-owner --email owner@example.com
```

The CLI prompts without echoing the password.

## Backup / restore

Run `BACKUP` before upgrade and on the approved schedule. Copy archives off-server. Test restore periodically using a staging/copy environment.

## Incident rule

Capture version/checksum, steps, impact, logs and screenshots. Do not patch source/schema on the server. Escalate reproducible code issues to RMR for a versioned release.

## Deployment diagnostics

Windows operators can double-click `COLLECT-DIAGNOSTICS.bat`. Linux operators can run `./COLLECT-DIAGNOSTICS.sh`. Send the generated file under `data/diagnostics` to RMR. The collector omits secrets. Failed RC3 upgrades collect the same evidence automatically before rollback.
