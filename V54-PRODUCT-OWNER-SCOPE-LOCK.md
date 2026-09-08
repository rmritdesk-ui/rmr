# RMR Global v5.4 Tenant Themes — Product Owner Scope Lock

**Release identity:** `5.4.0-tenant-themes-po1`  
**Source baseline:** exact, formally sealed RMR Global v5.3.1 Product Owner artifact.  
**Canonical v5.3.1 SHA-256:** `d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf`

## Authorized additive capability

v5.4 adds controlled, tenant-scoped branding for the authenticated RMR Global application workspace only:

1. Tenant logo upload, protected retrieval, replacement, and removal.
2. Primary, secondary, and accent colors with safe defaults and computed readable foreground colors.
3. Tenant brand name in the authenticated client workspace while preserving “Powered by RMR Global.”
4. A bounded list of application-safe typography choices; no arbitrary font upload.
5. Live preview before save.
6. Save/apply, logout/login persistence, and restart persistence.
7. Reset one tenant to the standard RMR Global default without affecting another tenant.
8. RMR Owner/Administrator management for authorized clients.
9. Client Administrator management for their own tenant only.
10. Explicit denial of cross-tenant theme reads/writes and denial of theme administration to non-authorized tenant roles.

## Preservation gate

All accepted v5.3.1 business behavior remains controlling. Kerry, CAF, tenant isolation, roles, Client 360, CRM, ProspectIQ boundaries, Campaigns & Social, Email & Activities, Forecasting, Reporting, Training, Team & Settings, Solutions, onboarding, service activation, Client Pricing, revenue share, Partner Economics, support auditing, websites, public lead capture, APIs, migrations, and restart behavior must remain present and functional.

The v5.4 implementation is additive. It introduces one tenant-scoped table and a bounded theme API/UI surface. It does not rewrite the database, CRM, navigation, website architecture, or accepted workflows.

## Website boundary

Tenant Themes affect only the authenticated RMR Global application workspace. Kerry’s managed public real-estate website, external website connections, and externally hosted websites are not redesigned or altered by this release.

## Explicit exclusions

No general UI redesign, arbitrary CSS or JavaScript injection, arbitrary font upload, theme marketplace, mass-email engine, automatic billing, new CRM architecture, new ProspectIQ provider work, new onboarding stages, new industries, or Hasan/Hameer production handoff.

## Acceptance boundary

This package is a Product Owner candidate. Automated pre-Windows validation may establish functional, isolation, preservation, persistence, static launcher, and package-integrity readiness. Only Dave’s actual Windows/Docker Product Owner run can approve v5.4.
