# RMR Global v5.4.1 Four Workspace Themes - Product Owner Scope Lock

**Release identity:** `5.4.1-four-workspace-themes-po1`

**Immediate source baseline:** exact preserved RMR Global v5.4.0 Tenant Themes Product Owner Candidate.

**Source artifact:** `RMR-Global-v5.4-Tenant-Themes-Product-Owner-Candidate.zip`

**Source SHA-256:** `a814b8fd36a1e7fad09963f3186075b8596975141508ef350436384494ee0300`

**Frozen production baseline:** RMR Global v5.3.1 Final Production Corrections remains unchanged with SHA-256 `d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf`.

## Authorized correction

v5.4.1 adds the missing four-option RMR-controlled workspace-style selector to the working v5.4.0 tenant-branding infrastructure. The four frozen styles are:

1. RMR Classic Blue / Original Soft Blue
2. Metallic Silver
3. Metallic Gold / Original Gold
4. Champagne Gold / Reduced Gold 15-20%

The preserved comparison image in `evidence/v541-visual-source/` is the visual source of truth. These are four visual presets for **one application**. Screens, routes, APIs, workflows, permissions, CRM, data, navigation, business logic, and tenant boundaries remain shared and unchanged.

## Preserved v5.4.0 functionality

- Tenant brand name
- Tenant logo upload, retrieval, replacement, and removal
- Primary, secondary, and accent colors
- Approved typography choices
- Preview, Save & Apply, and reset-to-default
- RMR Administrator management of authorized tenants
- Client Administrator management of their own tenant only
- Tenant isolation and restart persistence
- All inherited v5.3.1 functionality and product boundaries

## Explicit boundaries

- No separate application or dashboard per theme
- No public Kerry website redesign
- No externally hosted website changes
- No arbitrary CSS or JavaScript injection
- No theme marketplace
- No architecture, CRM, database, navigation, or role rewrite
- No destructive reset/reseed upgrade method
- No unrelated feature changes

## Product Owner environment

- Docker project: `rmr-global-v541-product-owner`
- Port: `8086`
- Environment file: `.env.product-owner-v541`
- Data directory: `product-owner-data-v541`
- Additive migration: `005.006.100-four-workspace-themes`

## Approval boundary

This package is a Product Owner candidate only. It is not production approved and is not authorized for Hasan/Hameer handoff. Dave's actual Windows/Docker run and visual comparison of all four styles is the final approval gate.
