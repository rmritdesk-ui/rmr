# RMR Platform v5.1 Target-Server Acceptance Checklist

## Package and host

- [ ] ZIP checksum matches RMR-issued SHA-256.
- [ ] Host OS, CPU, RAM and disk recorded.
- [ ] Docker/Compose versions recorded.
- [ ] No source modifications made.

## Install/upgrade

- [ ] Empty install or v5.0 upgrade launcher completes with visible transcript.
- [ ] Application/container reports healthy.
- [ ] Host restart preserves application/data.
- [ ] First-run exact owner credentials work.
- [ ] Setup token file is removed.

## Security/access

- [ ] HTTPS and secure cookies enabled.
- [ ] RMR Owner and Step2 Admin separated.
- [ ] Client Admin invitation/activation works.
- [ ] Client sees only own tenant.
- [ ] RMR/Step2 client operational write attempts are denied.
- [ ] Support access is audited.

## Functional journey

- [ ] Create client with services/prices.
- [ ] Client appears everywhere immediately.
- [ ] Complete onboarding with access gate.
- [ ] Client creates CRM/forecast data.
- [ ] RMR opens Client 360/read-only support and returns to Portfolio.
- [ ] Website preview and public lead routing work.
- [ ] Solution request/notification/activation works.
- [ ] Client Pricing/training entitlement sync works.
- [ ] Partner Economics cost categories/allocations work.
- [ ] System Health is understandable to nontechnical operator.

## Operations

- [ ] Backup created and copied off-server.
- [ ] Restore proven on staging/copy.
- [ ] Log rotation and disk alerts configured.
- [ ] Rollback procedure rehearsed.
- [ ] Remaining integration exceptions documented and accepted by RMR.
