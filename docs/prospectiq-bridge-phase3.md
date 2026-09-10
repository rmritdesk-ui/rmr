# Phase 3 — secure standalone PIQ to native RMR CRM Lead handoff

Status: implemented, default OFF. No deployment or provider activation.
Baseline RMR a4985ac / standalone PIQ 0c28702. See the pre-change audit.

## Flow and capability
RMR login -> original one-time federation -> exact mapped PIQ client ->
existing prospect -> Move to RMR CRM -> committed PIQ outbox ->
backend dispatcher -> signed RMR receiver -> native Lead + receipt + audit ->
persisted PIQ success -> View Lead in the existing RMR session.

New runtime capability: `crm.move_to_rmr`.
CLIENT_ADMIN, VP_SALES, SALES_MANAGER and SALES_REP receive it through the
existing Phase 2 operational policy. RMR_OWNER / STEP2_ADMIN require a current
managed-write session for this tenant. MARKETING_USER, EXECUTIVE_VIEWER and
global read contexts do not receive it. Legacy `crm.transfer` is not used.
Existing discovery, research, export and native authorization stay unchanged.

## Endpoint contracts (strict v1 schemas)
PIQ browser POST `/api/integrations/rmr/v1/crm/handoffs`:
`{"prospect_public_id":"<public UUID>"}`; optional bridge_session_id is only
a consistency assertion. Arbitrary tenant, client, actor or intelligence fields
are rejected. Current Phase 2 middleware authorizes the request and scoped lead.
202 pending / 200 already succeeded. GET at the same path + /<public UUID>
returns null or handoff_id, status, integration_event_id, rmr_lead_id, crm_url,
safe_error, outcome_unknown. Status never contains credentials.

Service POST `/api/integrations/prospectiq/v1/crm/leads`:
version=1; integration_instance_id; mapping_id; mapping_version;
piq_client_id; prospect_public_id; integration_event_id; actor_grant_id;
prospect={company_name, contact_name, email, phone, website, address, industry,
piq_score, evidence, email_provenance, intelligence_snapshot}.
No RMR tenant or arbitrary actor field exists in the contract.
The browser never talks directly to this endpoint.
201 created / 200 already_exists, with version, receipt_id, prospect_public_id,
status, rmr_lead_id, integration_event_id, crm_url (legacy crm_path remains null).
403 current authorization/mapping failure, 409 conflict/replay, 410 tombstone,
422 invalid service payload, 401 invalid HMAC; sanitized errors.
The dormant Phase 0 RMR receipt-lookup contract is not exposed as a new route.

## HMAC and key rotation
Separate PIQ RMR_CRM_HMAC_KEY_ID / RMR_CRM_HMAC_SECRET.
RMR RMR_PROSPECTIQ_CRM_KEYS_JSON maps 1–4 active key IDs to directional secrets.
Examples are blank; no real secrets are committed. Secret reuse with the
known session/federation HMAC credentials is rejected.
Canonical UTF-8 text, newline-separated, no trailing newline:
```text
piq-crm
<integration instance>
<key ID>
POST
/api/integrations/prospectiq/v1/crm/leads
<Unix timestamp in seconds>
<fresh 64-hex nonce>
<SHA-256 hex of exact raw request body>
```
HMAC-SHA256 is sent as X-Bridge-Signature with X-Bridge-Service, Instance,
Key, Timestamp, Nonce. Exact method/path/service/instance/key, +/-30s skew,
body <=256 KiB, constant-time comparison. Nonce consumed before JSON parsing
in a separate transaction; reuse forbidden across key rotation.
HTTPS fixed configured origin/path; no redirects; 5s timeout, 32KiB response cap.
Rotation: add receiver key, change sender active key, retire old receiver key
after in-flight requests finish. Changing credentials/deploying is NOT part of
this phase. Signing key and authorization keys are never frontend configuration.

## Destination, actor and atomicity
RMR resolves instance + PIQ client through its canonical ACTIVE mapping.
Tenant is derived from that row. Mapping ID/version and consumed grant must
agree. Fresh checks cover active human user, tenant access, PIQ entitlement,
current capabilities, absolute grant expiry/revocation, managed-write context.
The exact checked actor object is retained for managed-write semantics.
PIQ rechecks session, membership, mapping/context, current remote grant,
CRM capability and DNC/domain/email/phone suppression before every attempt.

Unique(instance, PUBLIC prospect UUID) is the external business identity.
Unique(instance, integration event UUID) is the immutable handoff identity.
Nonce is only HTTP replay identity and changes for every attempt.
RMR INSERT ON CONFLICT RETURNING + locked receipt elect one winner on PG;
SQLite uses equivalent insert behavior. Lead, accepted receipt, event ledger,
human/service audit commit atomically. Every event is hash-checked. Same event
with changed canonical payload conflicts. A new event for an accepted public
identity returns the original Lead without overwriting its data. A conflicting
client/mapping cannot reuse the identity. Deleted Leads are tombstoned, never
recreated. PostgreSQL, not SQLite, is the authoritative concurrency proof.

## Exact field mapping
| Stored PIQ value | RMR destination / treatment |
|---|---|
| public prospectiq_id; internal leads.id | External receipt identity; internal ID retained in immutable snapshot |
| company_name | Lead.company_name, trimmed, max 200 |
| contact_name | Lead.contact_name, max 160; empty if absent |
| phone | Lead.phone, max 80; empty if absent |
| source-linked stored email | Lead.email; otherwise empty, withheld reason/value in snapshot |
| website, location, industry | Labeled Lead.notes and imported snapshot; no new CRM columns |
| latest stored profile_match_score | Explicit PIQ profile match score in notes; not an RMR score |
| all selected profile matches, confidence/tier, fit/need/intent, ready_for_sales | Bounded immutable receipt snapshot, unchanged PIQ labels |
| scoped discovery source evidence, research evidence/runs | Receipt snapshot and source references; not independently RMR-verified |
| canonical mapped tenant, checked human actor | Lead.tenant_id; assigned_user_id |
| integration origin | source=ProspectIQ; status=New |

Source queries are scoped by client + internal lead. Snapshot limits: 20 matches,
20 source rows, 50 research evidence rows, 20 runs; nested data is depth/size
bounded and credential-like fields/URL query strings stripped. Dates retained.
No sources are fetched. Exact stored email must appear with a usable source URL;
Google/mock/demo provenance does not establish email. No guessed contact data.
Only Lead is created: no Account, Contact, Opportunity or conversion call.

## Durable delivery and outcomes
PostgreSQL outbox is committed before network work. A backend dispatcher starts
after schema bootstrap only when the bridge flag is enabled and keys valid.
It uses SKIP LOCKED + fenced lease, so parallel backend processes cannot own the
same attempt. This avoids a DB-commit/BullMQ-enqueue gap; existing PIQ queues and
native provider workers are unchanged.
pending -> sending -> succeeded / retry_wait / failed.
Three attempts total, backoff 5s then 30s, 30s abandoned-attempt lease.
Snapshot, hash, event, client/grant/actor/mapping and public identity persist.
Timeout/5xx/invalid remote success response keep outcome_unknown and reconcile
by resending the SAME event/identity with a fresh nonce and fresh authorization.
Permanent 4xx, revoked access, suppression, changed immutable context and malformed
local payload stop delivery. A later denial does not erase an earlier unknown
outcome. Final crash/exhaustion stays explicitly reconciliation-required.
No new handoff identity or unbounded retry is offered by the UI. Operator
reconciliation UI, manual replay and reverse SSO are intentionally deferred.

## UI / deep link / audit
Bridge LeadDetail shows one dedicated Move to RMR CRM card; native Push to CRM
remains unchanged and hidden for bridge sessions. Pending controls prevent
double-clicks; success persists across reads and shows View Lead / Back to RMR.
Only the configured RMR origin is allowed for links.
`/#/crm?tenant=<mapped tenant>&lead=<returned lead>` contains identifiers only.
CLIENT_ADMIN uses its existing v53 authorized record-detail modal. Other CRM
renderers select Leads and focus a row already returned by their normal
role-filtered API; this is a compact detail, not a CRM redesign.
Normal RMR login/tenant/assignment restrictions remain in force.
Receipt retains imported assertions; audit actor is the actual RMR user, while
event data separately names ProspectIQ, instance, client, mapping/version,
grant, public prospect/event, Lead ID, payload hash, result and timestamp.
PIQ lead_activity records request and delivery outcomes separately.

## Proof and boundaries
Tests run in private disposable PG16 / SQLite / Redis / HTTPS browser fixtures,
with readonly source mounts and blocked external networking. No installed DBs,
real environment credentials, sealed RMR, standalone provider algorithms or
default flags were changed.
- RMR receiver: 37 SQLite + 37 PG tests, including 10 simultaneous same-event
  requests and 10 distinct events for one identity: one Lead/receipt, same ID.
- RMR Phase 1/2/3 PG suites: 76 passed; original bridge/native PIQ PG: 14 passed.
- Full RMR regression: 520 passed, 3 historical packaging checks deselected;
  one existing Starlette/AnyIO deprecation warning. Bootstrap checks 12 migrations.
- PIQ combined Phase 1/2/3 PG: 87 passed; final expanded Phase 3: 29 passed
  (includes imported federation tests and malformed-payload coverage).
- PIQ offline regressions: 27 passed, including 11 business script suites.
- Frontend build passed; existing duplicate canConfirm JSX warning unchanged.
- Actual browser: CLIENT_ADMIN Move -> outbox -> signed RMR -> persisted success
  -> native authorized detail, repeat same Lead; read-only/foreign-client denied.
  Native login/client switching and generic webhook to a local double passed.
- Existing Phase 2 browser regression: CLIENT_ADMIN, SALES_REP, EXECUTIVE_VIEWER
  all passed; exactly two MOCK discovery calls, zero real Google/OpenAI calls.

Test entry points: tests/test_prospectiq_crm.py,
scripts/test_prospectiq_crm_postgres.py, scripts/federation_crm_proof.py,
scripts/test_federation_crm_browser.py; PIQ backend/tests/rmrCrm.postgres.test.js,
federation_crm_runtime.js, federation_crm_regression_worker.js.
The /proof fixture contains ephemeral secrets: never copy it wholesale into Git.
Only sanitized results/screenshots may be retained outside repositories.

Pre-existing native PIQ caveat found while preparing the fixture: bootstrap
creates outcome_webhook_secret but legacy configuration routes refer to
outcome_secret. This phase does not repair or alter native configuration code.
Native outbound webhook regression proves its optional-secret path, not that
legacy secret-configuration path. Separate follow-up approval is required.
