# Phase 4 pre-change session / operations audit

Baselines verified clean: RMR e3ddbc8bb8646f8bc3e3faddf5bc09b355217343;
PIQ 050d8222d1d5570452b8b5ea495cc53875f2b15a. No AGENTS instructions found.

RMR: native login JWT defaults to 12 hours. A federation grant is currently
min(native JWT expiry, now + 5 minutes, managed-write session expiry).
Launch preparation lasts <=3 minutes; the authorized one-time code defaults
to 60 seconds (configured maximum 60). RS256 assertion lasts <=30 seconds.
Logout revokes grants matching that native browser cookie hash, not all users.
Every grant check rechecks active user, tenant access, PIQ entitlement, mapping
and managed-write session. Any capability reduction currently rejects the entire
grant; no renewal or downgrade-in-place exists.

PIQ: access JWT expires with the <=5-minute RMR grant. Its durable client-bound
session is checked on every request and every privileged worker attempt.
No access bearer or renewal credential is persisted in browser storage. Reload
therefore asks for a new RMR launch. Existing refresh contract has no handler.
Bridge logout revokes only that bridge row; native refresh/logout is separate.
Every API request currently contacts RMR: no read authorization cache.
Native PIQ accounts may have multiple clients, but bridge sessions bind one.
Ordinary RMR users have one tenant; multi-tenant proof must use existing global
managed sessions, not fabricated ordinary membership.

Phase 3 CRM: SQL outbox, three attempts, 30-second fenced lease, permanent errors
stop, unknown outcomes stay unknown. Stable instance/public prospect/event.
The Phase 0 GET receipt contract is STILL DORMANT (despite the request describing
a Phase 3 status endpoint): Phase 4 will activate a signed scoped GET lookup.
It will not create business records. Operator retry remains a separate action
and must pass current authority and immutable context checks.
RMR CRM HMAC already supports a key ring but no bounded overlap metadata.
Federation and grant-check HMAC currently each accept only one verification key.
Neither app has complete integration operations/retention/readiness tooling.

Chosen minimal lifecycle: 5-minute access tokens (configurable 5–10 minutes),
30-minute idle renewal window (configurable 30–60 minutes), grant maximum 8 hours
(configurable <=8h) and never beyond original native JWT / managed-write expiry.
Grant and session capability sets can only shrink, never expand without relaunch.
Per-session rotating opaque renewal cookies: Secure, HttpOnly, SameSite=Strict,
host-only __Host- prefix. The tab stores ONLY session UUID and safe return hint.
Refresh requires exact PIQ Origin + explicit request header + the matching cookie;
no RMR token, federation assertion or renewal secret is put in a URL or JS storage.
Concurrent stale refresh fails without revoking the winning or unrelated session.
Reload renews the same durable session. No global mutable current client.
Fresh authority on every API request, renewal and spending/CRM dispatch remains.
Idle is extended by successful foreground renewal, not a heartbeat without activity.

Operations: signed receipt-only lookup; restricted server-console CLI for inspect,
reconcile, guarded retry, revoke and maintenance; no new operator web permissions.
Fenced reconciliation shares outbox exclusion with delivery. Retry never changes
actor/client/grant/public/event/snapshot and is unavailable once authority expires.
Short-lived secrets/transient rows may be purged; referenced session/grant records
are compacted, not deleted; CRM receipts/events/external identity tombstones remain.
Health is local-only (DB/queue/config), with safe structured categories and counts.
Add indexes only for concrete session/retention/outbox queries.
Separate HTTPS hostnames remain mandatory. Enabled unsafe config fails startup;
disabled native startup remains unaffected.

All tests will use disposable databases/queues, ephemeral keys and private
hostnames with external networking blocked. No provider calls, installed runtime
changes, production config edits or deployment. Separate commits only after tests.
