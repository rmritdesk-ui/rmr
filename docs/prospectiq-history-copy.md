# Previous RMR Profiles: explicit copy, not restoration

Bridge mode defaults to a clean ProspectIQ launcher. `Previous RMR Profiles` is a
secondary, lazily loaded section with historical/source wording. It does not query or
claim current PIQ existence. Bridge-OFF/native RMR behavior is unchanged.

`Create New PIQ Profile From This` sends only source UUID and action/request UUID.
RMR derives the source tenant, checks current user/tenant/capability/origin and active
canonical mapping, and signs server-read source values with the existing partner HMAC.
PIQ verifies the signature, rechecks the live canonical mapping, validates its active
workspace and resolves the actor by immutable issuer/RMR-user ID plus PIQ membership.
No email/name matching or JIT changes are involved. If that identity is not yet active,
the user is told to Open ProspectIQ normally first, then return to copy; collisions use
the existing identity-review flow. Copies are owned by the linked PIQ user, including
users with own-profile rather than workspace-wide permissions.

The existing `prepareProfileBootstrap` converter is reused for targeting fields only.
A fresh random PIQ UUID is inserted as a **normal draft**. The minimal-readiness import
exception is tied to the original immutable bootstrap ledger; the copy never enters or
modifies that ledger. Users complete normal PIQ questionnaire/activation requirements.
No scoring, discovery, research, provider, CRM, capability or native lifecycle rules change.

One additive PIQ table, `rmr_historical_profile_copies`, records provenance and durable
idempotency: issuer + instance + actor UUID + request UUID, with immutable source,
tenant, mapping/version, client and new profile UUID. It deliberately has no cascading
profile FK: deleting a copy retains the receipt, so retry returns deleted rather than
resurrecting it. Creation and receipt commit in one transaction under an action lock.
Reusing a request for another binding fails closed; later explicit actions use new UUIDs.
No RMR schema change, source update or continuous synchronization is introduced.

The UI disables in-flight copying and stores the pending UUID in localStorage before
sending. Reload/browser restart/lost-response retry reuses it. After confirmed success,
another copy requires an explicit confirmation. Clearing browser storage loses
the client-side pending-action identifier; do not start a fresh action to troubleshoot an
unknown outcome without checking PIQ first. Server receipts remain durable.

Success offers `Open PIQ Target Profiles` through the existing federation destination,
without a second login. It does not alter SSO to add a new deep-link contract.

Verification is fixture-only: SQLite/PG coordinator checks; authenticated PIQ PG tests
including eight concurrent requests, old/new tombstones, preserved edits, ownership,
binding and inactive-user/workspace denials; launcher tests; actual Chromium lost-response
copy/SSO/reopen proof; existing native PIQ profile/auth regression. No server data/env,
installed manual stack, provider request, push or deployment is part of this change.

Apply the existing additive PIQ schema initializer/normal startup on a future authorized
release before accepting copy requests. Preserve the copy receipts during rollback.

Executed results: 171 RMR SQLite bridge tests, 23 targeted RMR PostgreSQL tests,
12 launcher/history UI tests, and all 279 PIQ backend tests passed. Actual Chromium
history/copy/lost-response/SSO/reopen proof and native PIQ login/profile/logout proof
passed on the disposable OLD/MANUAL fixture. No real provider calls were made.
