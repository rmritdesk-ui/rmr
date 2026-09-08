# Phase 3: existing PIQ UI and asynchronous discovery

This WIP-only phase connects both existing PIQ renderers to the Phase 1/2 backend.
CLIENT_ADMIN uses v53_client_experience.js cards. Sales roles and authorized RMR
managed workspaces use unified.js. Backend permissions remain authoritative.
Read-only managed views retain their existing absence of write controls.

No framework, CSS redesign, schema migration, provider/scoring change, Adaptive
Research change, or Move-to-CRM backend change is included. Migration remains
005.007.000-piq-integration-foundation. Live discovery/worker remain OFF by default.

## Shared controller and compatibility

piq_discovery_ui.js uses the existing API wrapper, cookies, request-origin header,
managed-session header and existing toast/notice styles. The wrapper returns JSON
rather than HTTP metadata, so a valid run_id plus a recognized backend status
identifies the 202 contract without changing the shared API wrapper. A created[]
response preserves each renderer's exact synchronous demo message and list refresh.
Provider failures never initiate demo discovery or fabricate replacement results.
Explicit demo rows are labelled Demonstration. Older rows without provenance remain
visible as Source not recorded (or Imported when their existing status proves it);
the UI does not invent provenance for legacy data.

Run Discovery disables immediately. A per-user/per-tenant pending-submission lock
prevents repeated clicks; an Idempotency-Key is retained across uncertain POST
failures. New submissions never replace a known active run. Target Profile controls
and saved profile data are not reset by completion.
An idempotency/profile conflict clears the obsolete request key and checks for an
active run before allowing another submission; it does not retry writes automatically.

## Polling and navigation

- GET status every 3 seconds, scheduled after the previous request finishes.
- Terminal states: completed, partial, failed, cancelled.
- Per-request timeout: 15 seconds. Overall polling window: 5 minutes per view/check.
- One transient polling failure is tolerated; three consecutive failures pause
  checking. 401/403 are never automatically retried. 404 clears a stale run reference.
- Polling timeout does not mark the backend failed or enable another active run.
  The notice says the run may still be processing and provides Check discovery status.
- Completion/partial refresh the existing PIQ list; partial remains an explicit warning.
- Hash navigation, detached views, tenant/user changes and page exit clean up GET
  requests, timers and observers. In-flight POST is bounded and allowed to settle
  so its run ID can survive in-app navigation without duplicate submission.
- Session state is keyed by user and tenant. Returning/reloading restores the known
  run, including its terminal outcome. Failed POST retries reuse the idempotency key.

## Minimal backend addition

GET /api/tenants/{tenant_id}/piq/discovery-runs/active returns at most the newest
Google discovery in queued/running/retry_wait, or run:null. This is necessary when
session state is absent or the submission response was lost. The literal active
route is registered before the run-ID route. Existing tenant read authorization
and PIQ entitlement checks apply, and the existing safe status projection is reused.
The endpoint is read-only: it never queues, retries, cancels, or changes providers.
Known IDs use the original status endpoint, so terminal runs can be restored too.

## Presentation

Existing cards/tables show source labels. Live zero/unknown deal values display
Not estimated; demo currency behavior is unchanged. Live detail sections show
match score, confidence and evidence completeness separately, with an explanation
that employee count and revenue remain unknown. Missing phone/site/metrics are
Unknown, never fabricated. Only http(s) links without URL credentials are rendered;
external links use noopener noreferrer.

Google evidence supports confirmed, inferred, unresolved and contradicted labels.
Inferred/unresolved evidence is never presented as verified even if an inconsistent
legacy verified flag is supplied. Raw JSON and provider internals are not rendered.
Adaptive Research and its action handlers remain the existing demonstration workflow;
no research provider, scoring or billing feature is activated by this phase.

## Verification

Backend (isolated temporary database; project dependencies plus pytest and Pillow):

    python -m pytest -q -p no:cacheprovider

Browser gate (pytest plus existing Playwright/Chromium):

    python -B -m pytest qa/test_piq_phase3_browser.py -q -p no:cacheprovider

The browser gate loads actual renderer modules and CSS, intercepts every HTTP
request and uses mock API responses with a controlled browser clock. It requires
no application server, production login, database, or real provider credentials.
Historical v52/v53 golden paths were reviewed and left unchanged; this focused
Phase 3 browser gate adds async coverage without weakening their demo assertions.

Preservation gates:

    python -B qa/v5412_interaction_regression_gate.py --root .
    python -B qa/v5412_theme_preservation_gate.py --root .

The backend regression verifies two sequential Move-to-CRM requests produce one
Lead with source ProspectIQ, no synthetic contact/business data, and intact PIQ
scores/reporting. It does not claim new concurrent Move-to-CRM guarantees.

Never use the Product Owner database or authorize real Google calls through this gate.
Phase 4's dedicated security/regression gate has not been started.
