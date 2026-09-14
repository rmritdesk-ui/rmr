# Prompt 4: dynamic multi-tenant runtime acceptance

## Scope and authority

RMR remains authoritative for identity, tenant lifecycle, membership, entitlements,
capabilities and CRM destination. PIQ remains authoritative for profiles after
bootstrap, discovery, scoring, research and intelligence. RS256, one-time code,
PKCE/state, separate grant/CRM HMAC, separate databases and browser origins are
unchanged. No provider algorithm, production configuration or credential changes.

The shared bridge authorization now refreshes the tenant and accepts only the
existing operational statuses `onboarding`, `private`, `live` (the set already
used by `rmr_platform/routes/services.py`). Missing/other statuses fail closed.
Provisioning, bootstrap, launch, exchange and grant checks inherit this rule;
mapping checks also reject unavailable tenants. Existing browser, CRM actor and
queued-worker grant rechecks therefore enforce it without a second policy engine.
It is a recheck-boundary guarantee, not cancellation of a provider operation
already in flight. Both `piq_access` and `piq_enhancement` remain required: this is
the existing PIQ module contract, not a demonstrated accidental dependency.

## Runtime evidence

Three overlapping Chromium contexts against the original RMR app, original PIQ
frontend/backend, actual Redis worker and actual signed CRM outbox:

| Fixture | Initial state | Result |
| --- | --- | --- |
| Kerry Laughlin Real Estate | Existing canonical mapping, eligible source profile | Import recognized; full flow succeeds |
| Profound | No PIQ workspace/mapping; eligible source profile | Automatic workspace, mapping and bootstrap; full flow succeeds |
| Synthetic Dynamic Tenant | No workspace/mapping; zero RMR profiles | Automatic zero-profile bootstrap; native profile created/activated and mock intelligence generated in UI; full flow succeeds |

Each full flow performs fixture discovery, one complete mock research run,
Move to RMR CRM through the real HMAC/outbox path, exact/delayed retry, View Lead,
Back to `https://rmr.test/#/prospectiq`, relaunch and reload. Each tenant retains
exactly one CRM lead, bound to its canonical destination. Cross-tenant profile,
lead, discovery, research and CRM reads/mutations are denied. No normal happy-path
mapping/import/JIT SQL is performed by the test harness: fixture SQL/ORM only
defines initial RMR/native users and fault states, as in the existing proof suite.

Seven live fault/recovery cases: tenant disable, user disable, `piq_access`
removal, `piq_enhancement` removal, role downgrade, membership removal, mapping
suspension. Protected discovery/research/CRM actions deny access; restoring the
source authority does not expand the old grant. A fresh authorized launch works.

Existing-session browser reload survives RMR/backend/worker process restarts.
Mappings, profiles, research and CRM identity persist. Interrupted launches before
exchange and after PIQ session creation recover by reopening from RMR without
duplicate workspace/profile/lead. A consumed code is rejected; PIQ's existing
partner transport intentionally reports upstream exchange denial as sanitized 503.
Expired code/access token, idle/absolute deadlines and worker rechecks are also
covered by the existing federation/session/capability regression suites; no TTL
was relaxed. Startup outages deny authorization until RMR is ready.

## Identity collisions

The companion PIQ change adds explicit native administrator recovery under
Users & Access -> RMR identity links. A verified federation collision records a
pending request, not a link/session/membership. A current active native admin
assigned to the exact workspace must review both immutable IDs, arrange the
existing native user's workspace assignment using existing UI, and approve.
Fresh RMR grant/context validation is mandatory. Approval/revocation is audited
and idempotent; email is never proof. Normal JIT needs no administrator. Collision
recovery no longer needs developer SQL, but still requires a trusted human admin;
self-service ownership verification and reactivation of revoked links are not
introduced. PIQ documentation describes the endpoints and checks.

## Regression results (local fixture runs)

- RMR bridge/profile-export/provisioning/bootstrap/federation/capability/CRM/
  operations/lifecycle SQLite selection: **155 passed**.
- Corresponding bridge PostgreSQL 16 selection: **139 passed**.
- RMR launcher/bridge-off/tenant-navigation JavaScript suite: **11 passed**.
- PIQ complete `backend/tests/*.test.js`, serial, PostgreSQL enabled: **237 passed**.
- Frontend production build: passed. Existing duplicate `canConfirm` JSX warning
  in Leads is unchanged; Starlette emits an existing deprecation warning.
- Browser acceptance: three concurrent full journeys, seven revocation cases,
  explicit identity recovery, native login/draft profile/logout, restart plus two
  interrupted-launch cases. Fixture providers only; no external network route.

## Reproduce the browser acceptance

From this repository in Windows PowerShell, with Docker and the cached proof
images available:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_prompt4_runtime.ps1
```

Parameters `-PiqRepo`, `-ImagePrefix`, `-BrowserImage` select the sibling checkout
and existing dependency images. The defaults identify the local release-gate
images used for this acceptance. These image tags are test tooling, not production
runtime requirements. Current application source is mounted read-only; frontend
is rebuilt. The RMR proof image's Python 3.13 certifi path is explicit in the test
runner and must be adjusted if that dependency image changes.

The runner creates a randomly named internal-only network and isolated volume,
PostgreSQL tmpfs, Redis, fixture HTTP provider, original apps/worker, TLS proxy and
test-only authorization control service. No host ports, installed `.env` files,
manual/production data or production keys are used. Only test CA material is
installed inside these containers. Test fixture credentials are generated into
the Docker volume, never printed or committed. PIQ/worker receive only their
fixture credentials and the public federation key.

As in the existing proof helpers, RMR and PIQ use separate application schemas in
one disposable PostgreSQL database. This verifies application boundaries, not
production database-user/network isolation; deployment's separate database
configuration is unchanged and remains a Prompt 5 operational check.

The named disposable containers/volume are retained for inspection; failure does
not erase evidence. They are not the installed manual environment. The name is
printed at completion. Any cleanup must target that exact generated name, never
all containers or all Docker volumes. Results and failure screenshots live only
in the proof volume. This is runtime acceptance, not load/capacity certification.

## Prompt 5 decisions

Production deployment/credentials, live-provider acceptance and operational
monitoring remain separate authorized work. Existing native `profound_tax` offer
seeding/default legacy AI endpoints were reviewed: they are not used by these
profile-discovery/research/bridge paths, do not determine mapping or selected
tenant, and were left unchanged. No tenant names, fixed client IDs or server
addresses were introduced into production bridge logic. Fixtures alone use
named example tenants. Existing manual services, VPS and repositories outside
these two checkouts were not modified; no push/deployment was performed.
