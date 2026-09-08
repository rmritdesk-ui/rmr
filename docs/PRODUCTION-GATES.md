# RMR Platform v5.1 Production and Target-Server Gates

The candidate is not approved for broad production until RMR accepts the target evidence.

## Required gates

- exact ZIP checksum verified;
- clean Docker empty install;
- first-run exact owner credential login;
- setup token invalidation/removal;
- HTTPS, secure cookies and reverse-proxy headers;
- Client Administrator invitation/activation delivery;
- tenant isolation and global-admin read-only enforcement;
- onboarding access gate and completion;
- managed website routing;
- file-upload limits;
- backup, off-server copy and restore;
- host restart persistence;
- monitoring/log rotation/disk alerts;
- SMTP configuration or approved pilot exception;
- target manual QC sequence;
- upgrade/rollback rehearsal on a copy of v5.0 data.

## Deferred broader-production gates

- PostgreSQL certification;
- MFA;
- real payment provider;
- live ProspectIQ providers;
- object storage/CDN;
- social OAuth/publishing;
- accounting integrations;
- multi-node scaling and distributed workers.

## RC3 deployment-readiness gate

The exact target installation must prove bounded readiness across container state, Docker health, internal API, host API, exact application version, application status, diagnostic capture, and verified rollback to the untouched prior release. A single `container started` event is not acceptance evidence.


RC3 additionally corrects the field-proven v5.0 version-label mismatch (`5.0.0-rc1` versus `5.0.0-rc.1`) without weakening current-release version checks. The exact RC3 archive must pass the Windows Docker Desktop upgrade gate before partner handoff.
