# Role, Permission and Tenant-Isolation Test Summary

## Roles preserved or added

- **RMR Owner** — highest business/platform authority; customer approval, Order Forms, entitlements and the only role eligible to claim Data Custody authority.
- **RMR Administrator** — delegated portfolio/operations access without automatic Data Custody authority.
- **Step2 Administrator / contractor** — only delegated operational access; cannot approve itself as RMR Owner, claim Data Custody, or independently export a customer.
- **Client Administrator** — assigned to one tenant through invitation/activation; manages authorized client users and purchased functionality.
- **Client User** — tenant-scoped use according to role and entitlements.

## Automated evidence in this build environment

- Application imports with the CB1 router and governed migration.
- All route parameters are valid and no literal double-brace paths remain.
- Client Administrator invite/list/activation infrastructure executes in an isolated database.
- Order Form and entitlement APIs execute in an isolated database.
- Readiness does not falsely certify client access before objective activation evidence.
- RMR Data Custody code requires RMR Owner authority, multi-factor authentication, reason and time-limited session state.
- Export implementation is tenant-scoped and produces a manifest while excluding secret/security fields.
- Provider-neutral email, suppression and drip-state models execute in isolated tests.
- Existing v5.1 isolated acceptance suite remains passing.

## Required Product Owner / Windows evidence before acceptance

1. Invite a real CAF test Client Administrator.
2. Activate using the invitation link and create separate credentials.
3. Log in in an Incognito window as CAF.
4. Verify CAF sees only CAF and only activated modules.
5. Attempt direct access to another tenant identifier; expect 403/404 without disclosure.
6. Verify Step2 cannot see or invoke RMR Owner Data Custody controls.
7. Verify an RMR Owner Data Custody session is visibly bannered, read-only by default, expires and writes audit history.
8. Verify CAF export contains only CAF customer-owned data and a manifest.

Until those browser/session tests pass on the exact packaged artifact, tenant-isolation and Product Owner acceptance remain pending even though automated code tests pass.
