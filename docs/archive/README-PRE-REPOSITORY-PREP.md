# RMR Global v5.4.1.2 Interaction Regression Correction

**Release:** `5.4.1.2-interaction-regression-correction-po1`  
**Status:** Windows/Docker Product Owner candidate; not production approved.

## Exact source and preservation

The immediate source is the exact preserved v5.4.1.1 Product Owner artifact:

- Artifact: `RMR-Global-v5.4.1.1-Four-Workspace-Themes-Rendering-Correction-PO.zip`
- SHA-256: `1aa552533e5471ac70ffc2d82ab88551b748a7934e1e3ddbb89aa6405a9efed9`

Earlier baselines remain unchanged:

- v5.4.1 SHA-256: `bf519df3b2e67001ac69f8e81011bfcab23d6c113b87fcc0af08161a252a7a32`
- v5.4.0 SHA-256: `a814b8fd36a1e7fad09963f3186075b8596975141508ef350436384494ee0300`
- Approved v5.3.1 SHA-256: `d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf`

## Bounded correction

v5.4.1.2 corrects two Product Owner regressions without altering the four workspace themes:

1. Existing actionable route cards/tiles now use one capture-phase delegated navigation handler, so nested card content and dynamically rendered screens remain clickable.
2. Forecasting, Training, Team & Settings, and Solutions now dispatch to the preserved operational renderer from the unified RMR Owner client workspace instead of remaining on `Loading…`.

No CRM, route destination, workflow, permission, tenant isolation, data model, migration, theme token, or public website was redesigned.

## Windows Product Owner run

1. Verify the ZIP SHA-256.
2. Extract to `C:\RMR5412`, producing `C:\RMR5412\RMR5412`.
3. Start Docker Desktop.
4. Double-click `START-PRODUCT-OWNER-TEST.bat`.
5. Leave the launcher open while it builds, checks health, runs functional and interaction-regression QC, restarts, and verifies persistence.
6. Open `http://localhost:8088` if the browser does not open automatically.

### Credentials

- RMR Owner: `dave@rmr.local` / `RMR-Owner-2026!`
- Kerry Client Administrator: `admin@kerry-real-estate.demo` / `Client-Admin-2026!`
- Kerry Marketing: `marketing@kerry-real-estate.demo` / `Marketing-2026!`
- CAF Client Administrator: `admin@cactus-air-filters.demo` / `Client-Admin-2026!`

## Product Owner sequence

As Kerry Client Administrator, click every module tile on the dashboard and confirm it opens the correct existing destination. Confirm Forecasting renders its forecast content and does not remain on `Loading…`. Repeat the module-tile and Forecasting checks in the RMR Owner Kerry Client Workspace. Spot-check all four workspace themes and CAF isolation to confirm v5.4.1.1 rendering remains unchanged.

## Isolation

- Docker project: `rmr-global-v5412-product-owner`
- Port: `8088`
- Data directory: `product-owner-data-v5412`
- Environment file: `.env.product-owner-v5412`
- Migration: `005.006.100-four-workspace-themes`

v5.4.1.1 on port 8087, v5.4.1 on port 8086, v5.4.0 on port 8085, and v5.3.1 on port 8084 are not overwritten.

## Boundaries

No theme redesign, public Kerry website redesign, external website modification, architecture rewrite, CRM rewrite, data-model rewrite, or unrelated feature change is included. No Hasan/Hameer handoff is authorized until Dave completes and approves the Windows/Docker Product Owner test.
