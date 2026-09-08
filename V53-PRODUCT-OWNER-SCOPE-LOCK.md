# RMR Global v5.3 Product Owner Scope Lock

Release identity: `5.3.0-client-experience-crm-modernization-po1`

This release implements the frozen Product Owner Master Correction Register approved in the Kerry Website Project. It is a cumulative correction and client-experience modernization of the accepted v5.2.2 application. It is not an architecture rewrite or a replacement product.

## Mandatory outcomes

- Preserve all accepted v5.2.2 functionality, routes, APIs, database records, tenant isolation, permissions, Kerry functionality, and CAF functionality.
- Modernize the Client Administrator experience across Dashboard, CRM, ProspectIQ, Campaigns & Social, Email & Activities, Forecasting, Reporting, Training, Team & Settings, and Solutions.
- Keep Website functionality and external-site strategy intact without creating a universal website-builder project.
- Provide modern, actionable CRM record views, controlled lead conversion, connected opportunity/account/contact/activity/email context, and drill-down KPI behavior.
- Preserve ProspectIQ discovery, scoring, profile, Adaptive Research, enhancement, and move-to-CRM behavior while carrying intelligence into CRM context.
- Preserve platform-specific social generation, explicit clipboard actions, edit/regenerate/save behavior, content calendar, and provider-ready campaign exports.
- Keep bulk email delivery outside RMR Global. RMR Global creates segmented, provider-ready campaign packages and supports one-to-one client-mailbox communication with CRM capture.
- Make forecasting tenant-specific, source-transparent, properly formatted, visually useful, and compatible with real CSV/XLSX preview/validation/import.
- Keep Reporting action-oriented and tenant-scoped.
- Support client-managed training links and uploaded video/PDF/PowerPoint/Word resources, assignments, completion, and retrieval.
- Modernize Team & Sales Organization while preserving users, roles, teams, reporting relationships, assignments, and secure password-reset behavior.
- Keep Solutions requests as requests only. No automatic activation or billing. Never expose placeholder pricing as a real customer agreement.

## Explicit exclusions

- No full Salesforce, HubSpot, Wix, GoDaddy, Mailchimp, Hootsuite, or learning-management clone.
- No RMR Global bulk-email delivery engine.
- No full social-network publishing infrastructure unless an already approved provider integration exists.
- No complete official RMR training-video curriculum in this release.
- No replacement ProspectIQ engine; production PIQ provider wiring remains a deployment responsibility.
- No unapproved hard-coded customer pricing.
- No automatic service activation from a customer request.
- No destructive reset/reseed as an upgrade strategy.
- No uncontrolled redesign of RMR Owner, Step2 Admin, Sales Manager, Sales Representative, or Marketing User roles.

## Release gates

- Cumulative preservation and no silent feature loss.
- Kerry and CAF data preservation.
- Tenant-isolation and permission tests.
- Functional, browser, persistence/restart, migration/upgrade, rollback, Windows/Docker, package-manifest, integrity, and checksum verification.
- Product Owner acceptance remains the final release gate.
