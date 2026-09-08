# RMR Platform v5.1 Pilot Data Model

## Major domains

- identity/session/user/role;
- tenant and client access;
- user invitations and password resets;
- service catalog and tenant service schedules;
- onboarding projects and eight onboarding steps;
- CRM accounts, contacts, leads, opportunities and activities;
- sales hierarchy and assignments;
- forecast versions, monthly forecast values and historical sales imports;
- managed websites, pages, sections and form submissions;
- training resources, assignments and completion;
- solutions interest, requests and entitlements;
- campaigns/content records;
- ProspectIQ opportunities, enhancements and CRM transfer;
- economic transactions, partner rules and client-specific overrides;
- cost categories, cost entries and cost-allocation rules;
- notifications, audit events and support-access records.

## v5.1 additions

- `user_invitations`
- `password_reset_tokens`
- `cost_categories`
- `cost_entries`
- `cost_allocation_rules`
- notification action/entity columns

## Data ownership

- Tenant operational data belongs to the client and is editable only by authorized client roles.
- RMR/Step2 relationship/configuration, pricing, entitlement and portfolio data is administered by global roles.
- RMR/Step2 client operational support access is read-only and auditable.

## Migration and preservation

v5.1 applies additive migration `005.001.000-functional-client-experience`. The upgrade-preservation suite proves exact v5.0 onboarding notes, structured data, tenant and negotiated service pricing survive.

Generated references:

- `docs/sqlite-schema-v5.1.sql`
- `docs/openapi-v5.1.json`
