# RMR Platform v5.1 Architecture

## Product layers

1. **RMR/Step2 portfolio administration** — tenants, access, onboarding, services, pricing, Partner Economics, training administration, system health and read-only support.
2. **Client tenant operations** — tenant-specific CRM, forecasting, website/content, campaigns, training, Solutions Center and ProspectIQ entitlements.
3. **Public managed websites** — server-rendered tenant websites and public lead-form routing.
4. **Application API** — authenticated FastAPI endpoints with tenant/role checks.
5. **Persistence** — SQLAlchemy models, versioned additive migration, SQLite/WAL pilot database and persistent training/backup directories.
6. **Deployment** — Docker/Compose, non-root container, health checks, install/upgrade/backup/restore/rollback tooling.

## Runtime

- Python 3.13
- FastAPI / Uvicorn
- SQLAlchemy
- server-rendered static HTML/CSS/JavaScript client
- SQLite/WAL pilot database
- Docker/Compose single application container

## Authentication and access

- server-side sessions;
- hashed passwords;
- first-run owner verification;
- expiring hashed invitation tokens;
- expiring hashed password-reset tokens;
- optional local pilot recovery links;
- tenant-aware role checks;
- global admin versus client shell separation;
- server-enforced RMR/Step2 read-only support for client-owned operations.

## Tenant lifecycle

1. Global admin creates tenant, website configuration, onboarding project and services.
2. Primary Client Administrator invitation is created.
3. Client sets their own password and activates.
4. Eight-stage onboarding progresses through go-live gates.
5. Tenant becomes live only after active Client Administrator and required stages.
6. Client operates tenant records; RMR/Step2 monitors relationship/adoption and supports read-only.

## Data and migration

Migration `005.001.000-functional-client-experience` adds invitations, password resets, cost categories/rules/entries and notification deep-link fields. It renames the existing stage-2 label without overwriting existing onboarding notes or structured data.

## Cost architecture

Partner Economics distinguishes:

- transaction direct costs;
- additional direct tenant/service costs;
- allocated shared operating costs;
- unallocated policy-pending costs;
- contribution after allocated costs;
- existing RMR/Step2 transaction allocations.

Cost allocation policy is effective-dated and controlled by RMR.

## Current scaling boundary

The release is a controlled single-server pilot. PostgreSQL, distributed workers, object storage, external cache/queue, multi-node deployment and full production observability require later certification.
