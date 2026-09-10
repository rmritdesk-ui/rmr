# Phase 3 pre-change CRM audit

Baselines: RMR a4985ac; PIQ 0c28702. Inspected before implementation.

## Reuse and boundaries

RMR models.Lead has company_name, contact_name, email, phone, source, status,
notes, assigned_user_id and tenant_id. It has no website/address/industry or PIQ
score columns. routes/crm.py manual creation uses require_client_operational_write,
defaults assignment to the human actor, writes crm.lead.created and commits.
The separate /leads/:id/convert creates Account/Contact/Opportunity; DO NOT call it.

Native routes/piq.py move-to-crm uses the same Lead model with source ProspectIQ,
status New, actor assignment and its own atomic opportunity claim. Leave it intact.
services.audit stores the human actor separately from JSON integration context.
CRM reads apply tenant checks plus salesperson assignment / manager team filtering.

RMR public/app.js supports #/crm?tenant=... query context but not an exact lead.
Both public/pages/unified.js and client.js have Leads tabs. The minimal addition
will select that tab and display the requested lead only if already returned by
the normal role-filtered CRM API. No authorization bypass or conversion changes.

Renderer follow-up: CLIENT_ADMIN actually uses v53_client_experience.js. Reuse
its existing openCrmRecord modal and existing role/tenant-guarded record API.
The compact role-filtered Leads focus applies to the other two renderers.

PIQ leads.id is internal; leads.prospectiq_id is the unique public UUID. Use the
latter for external identity. Existing /api/integrations/crm/push is a synchronous,
per-client configurable webhook with X-ProspectIQ-Secret and no RMR durable
idempotency semantics. Keep its native behavior; do NOT repurpose it.

PIQ LeadDetail already contains a native CRM/outreach card hidden for bridge
sessions. Add a dedicated bridge action in that existing screen. Canonical data
comes from PostgreSQL, never request fields beyond the public prospect identifier.

Phase 0 rmr_crm_handoffs provides durable context FK, unique instance/public UUID
and instance/event identity, snapshot/hash, retry fields and result identity.
RMR prospectiq_crm_receipts provides equivalent external identity uniqueness and
canonical mapping FK. Reuse them; add only delivery lease/outcome/completion
fields and a separate RMR event ledger to detect changed-event payloads even
when multiple event IDs refer to an already accepted public prospect.

PIQ source evidence, profile matches and research rows have explicit client/lead
keys. Snapshot only scoped records, preserve their PIQ labels, bound/sanitize JSON.
No score becomes RMR qualification. No rich CRM-column duplication.
Stored email alone is insufficient provenance: import only an exact stored email
supported by source-linked PIQ evidence; otherwise leave native CRM email empty
and retain a withheld-email explanation in the import snapshot.

## Chosen implementation

Dedicated crm.move_to_rmr capability for existing operational writers and valid
managed-write global users. Read-only roles get none. Native PIQ roles do not
supply bridge capabilities.

Dedicated HTTPS PIQ -> RMR CRM HMAC key, separate from federation/session keys.
Canonical bytes bind service identity, instance, key ID, method, exact path,
timestamp, nonce and raw-body SHA-256. Receiver key ring supports overlap rotation;
nonce uniqueness spans key rotation. Authenticate before parsing payload.

Durable PostgreSQL outbox dispatcher in the existing PIQ backend avoids a
commit/enqueue crash gap. Claim with SKIP LOCKED + fenced lease; recover abandoned
sending rows; three bounded attempts, fresh RMR authorization and current PIQ
suppression/client checks on every attempt. No per-provider business logic changes.
Timeout/5xx preserve unknown-outcome state and stable event/public UUID. Permanent
rejections do not retry. Exhaustion never permits a new duplicate handoff.

RMR resolves tenant from active instance/client mapping, verifies mapping/grant/
actor/current capability, then atomically inserts/locks the unique receipt and
event claim. Lead, receipt, event and human/service audit commit together.
Repeated accepted identity returns the original Lead, never overwrites it.
Deleted leads remain tombstoned, not recreated.

Only disposable test DBs/queues, internal HTTPS fixtures and synthetic records.
No real providers/email, installed data changes, deployment, push or default-on flags.
