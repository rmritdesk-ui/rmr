# RMR Global v5.4.1.1 Four Workspace Themes Rendering Correction — Product Owner Scope Lock

**Release identity:** `5.4.1.1-four-workspace-themes-rendering-correction-po1`

**Immediate source baseline:** exact RMR Global v5.4.1 Product Owner artifact with SHA-256 `bf519df3b2e67001ac69f8e81011bfcab23d6c113b87fcc0af08161a252a7a32`.

**Preserved earlier baselines:** v5.4.0 `a814b8fd36a1e7fad09963f3186075b8596975141508ef350436384494ee0300` and Product Owner-approved v5.3.1 `d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf` remain unchanged.

## Authorized correction only

The four preset names, selector, persistence, tenant isolation, and existing branding controls were already present in v5.4.1. Product Owner testing showed that the selected `workspace_style` saved, but RMR Owner Client 360 remained visually unchanged. This release corrects only that rendering/application defect by:

1. treating tenant-scoped Client 360 as an authenticated tenant theme context;
2. reapplying/loading the selected tenant theme when route or selected-tenant context changes;
3. extending the existing controlled style tokens across shared workspace surfaces;
4. repairing four preview-card asset URLs and replacing incorrect two-panel crops with four individual visual-source previews.

No CRM, data, workflow, route, permission, tenant-isolation, public website, onboarding, pricing, PIQ, email, campaign, forecasting, reporting, training, or business-logic behavior is authorized to change.

## Product Owner environment

- Docker project: `rmr-global-v5411-product-owner`
- Port: `8087`
- Environment file: `.env.product-owner-v5411`
- Data directory: `product-owner-data-v5411`
- Existing migration remains `005.006.100-four-workspace-themes`; no database migration is required.

**Status:** Not production approved. Dave's Windows/Docker visual Product Owner test is mandatory.
