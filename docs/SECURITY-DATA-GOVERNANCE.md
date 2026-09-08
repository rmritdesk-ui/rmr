# RMR Platform v5.1 Security and Data Governance

## Access model

- RMR Owner and Step2 Platform Administrator have shared operational portfolio access.
- RMR retains ownership and ultimate governance authority.
- Client users are tenant-bound.
- Global admins may inspect client operations for authorized support but cannot modify client-owned operating records.
- There is no break-glass client-data editing mode.

## Credentials and tokens

- Passwords are hashed.
- The first-run owner credential is verified before setup succeeds.
- Setup, invitation and password-reset tokens are single-use and time-bound.
- Only token hashes are stored in the database.
- `INITIAL-SETUP.txt` is removed after successful setup.
- Pilot recovery CLI uses masked input.

## Client data

Client-owned CRM, contact, forecast, activity, campaign and personnel records remain client-controlled. Support views are read-only and recorded in Support Access Audit.

## Administrative data

RMR/Step2 may administer tenants, access, onboarding, services, pricing, websites, training, system health and approved integrations.

## Current production gaps

MFA, production SMTP, live payment-provider security, object storage, PostgreSQL certification and external integration security reviews remain future/target gates.
