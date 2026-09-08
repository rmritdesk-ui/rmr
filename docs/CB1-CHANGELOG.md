# RMR Software v5.1 Commercial Candidate Correction Build 1 — Change Log

Release: `5.1.0-commercial-cb1`

Baseline: RMR Software v5.1 Commercial Candidate `5.1.0-commercial-rc1`

Authority: Formally frozen v5.1 Pre-Code Baseline plus the approved Product Owner QC & Correction Matrix. No unrelated feature expansion is included.

## P0 corrections

1. **Frontend release integrity and cache invalidation**
   - Adds explicit release headers and no-store/no-cache behavior for application HTML/API responses.
   - Injects versioned CB1 assets so the browser loads the frontend matching the running backend release.
   - Adds runtime release evidence to Commercial Readiness.

2. **Commercial route repair**
   - Registers `/commercial` before the single-page-application catch-all.
   - Removes literal double-brace route parameters from commercial APIs.
   - Adds route/OpenAPI regression checks.

3. **Client Administrator provisioning and management**
   - Adds RMR Owner controls to invite, view status, resend, reset/recover, revoke/deactivate and audit Client Administrator access.
   - Activation assigns the administrator only to the selected tenant.
   - Adds a public activation flow without exposing the invitation secret after activation.

4. **Objective onboarding and go-live validation**
   - Tenant Provisioning & Client Access is calculated from actual activation evidence.
   - Go-live/readiness cannot reach 100% while required client access, Order Form or entitlement evidence is missing.
   - Any RMR-managed/no-client-login exception must be explicit and auditable rather than assumed.

5. **Order Form and entitlement integration**
   - Adds tenant Order Form records and backend module-entitlement enforcement.
   - Legal coverage remains in the MSA; commercial availability is driven by RMR-authorized Order Forms.

6. **RMR Owner Secure Tenant / Data Custody**
   - Adds a single RMR-controlled Data Custody authority, multi-factor authentication using time-based one-time passwords, step-up verification, mandatory reason, read-only tenant session, limited elevation, explicit exit and immutable audit events.
   - Adds tenant-scoped customer-data export ZIPs with CSV files and a manifest.
   - Excludes credentials, provider tokens, password hashes, internal session secrets, source code and other proprietary/security data.
   - Adds offboarding status and export evidence.

7. **Connected business email**
   - Adds provider-neutral connection records and adapters for Microsoft Graph, Gmail and supported SMTP/IMAP providers, plus a safe mock provider for local testing.
   - Adds encrypted secret/token storage, connect/test/reconnect/disconnect status, approved sender identity, physical postal address, audit events, suppression, bounce, unsubscribe and reply event handling.
   - Keeps RMR transactional messages logically separate from client campaigns.

8. **Executable drip engine**
   - Adds scheduled execution, worker heartbeat, retries, idempotency keys, duplicate-send protection, frequency controls, pause/resume, restart-safe state and stop-on-reply/bounce/unsubscribe.
   - Positive replies can create a sales task tied to the original tenant/campaign/record.

9. **AI messaging workflow**
   - Adds supported-fact context, draft generation, preview/edit, version history, explicit human approval, approved-content hashing, scheduling and shared activity/cost evidence.
   - Safety validation rejects unsupported factual assertions rather than silently inserting them.

10. **Fail-safe commercial security profile**
    - Adds controlled secrets, tenant-scoped APIs, audit records and release/readiness evidence.
    - Preserves the current candidate as the rollback source and never overwrites it.

## P1 corrections

11. **Social content copy/paste workflow**
    - Generates platform-specific drafts for Facebook, Instagram, LinkedIn and X.
    - Adds Copy Post, Copy Hashtags, manual Mark Published, post URL and timeline activity.
    - Does not add native social OAuth or publishing.

12. **Client and portfolio navigation**
    - Adds visible Client Access and Data Custody actions to Client 360.
    - Preserves Return to Portfolio and adds an explicit exit from privileged tenant access.

13. **System Health and Commercial Readiness**
    - Presents Healthy, Needs Configuration and Needs Attention in business language.
    - Keeps detailed diagnostics available separately.
    - Commercial Readiness now has a real page with passed, blocked and external-dependency gates.

14. **Password visibility**
    - Adds an accessible show/hide password control to login, activation and relevant password-entry screens.

## Production path

15. **PostgreSQL production path**
    - Adds a PostgreSQL Docker Compose override, governed CB1 migration, PostgreSQL certification test and backup evidence workflow.
    - PostgreSQL is not marked certified until the provided certification is executed successfully in Docker.

## Preserved boundaries

- Native social publishing remains post-launch.
- Live Microsoft, Google and SMTP/IMAP provider activation requires real provider credentials/permissions.
- Full payment-card data is not stored by RMR Software.
- Step2 does not receive RMR Owner Data Custody authority.
- No Hasan handoff is authorized until Product Owner and environment gates pass.
