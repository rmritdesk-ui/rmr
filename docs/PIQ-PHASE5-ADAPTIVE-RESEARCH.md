# Phase 5 — bounded Adaptive Research

Implementation date: 2026-09-07. Development working copy only. Live research
remains OFF. No real Google/OpenAI calls were made. No Product Owner database
was opened, migrated, seeded, or modified. No new migration is required.

## Flow and ownership

Qualified Google PIQ opportunity → POST estimate → explicit confirmation → 202
queued PiqResearchRun → existing DB worker → Responses/web search → independent
source validation → PiqEvidence → deterministic adjustment → existing PIQ UI.

Routes:

| Route | Behavior |
| --- | --- |
| POST `/api/piq/{id}/adaptive-research/estimate` | No provider call; immutable scope/config snapshot and 10-minute estimate |
| POST `/api/piq/{id}/adaptive-research` | Existing demo behavior when OFF; otherwise consumes confirmation and queues |
| GET `/api/piq/{id}/adaptive-research/{run_id}` | Tenant/entitlement checked safe state and cost metadata; no provider payload or nonce |

PIQ viewers may estimate/read results under existing tenant rules. Only
CLIENT_ADMIN may confirm live spend. Global administrators require a fresh,
active, actor/tenant-bound managed_write session. Sales roles cannot confirm.
Worker authorization is checked before external work and again before evidence
is saved. The existing profile/evidence read-policy gap is intentionally unchanged.

Confirmation uses a random 256-bit nonce; only its SHA-256 digest is persisted.
It is actor, tenant, opportunity and expiry bound, consumed by a conditional SQL
update, with an opportunity write lock serializing concurrent starts. Client cost
fields are rejected. Profile/scope/config changes require a new estimate. Only one
queued/running/retry_wait research run per opportunity can start through this API.

## Configuration and provider

All existing live flags retain their false defaults. Research provider retains
`demonstration`. The example environment includes a blank optional
`RMR_PIQ_RESEARCH_MODEL`; fallback is existing `RMR_AI_MODEL`. Credentials use
`RMR_AI_API_KEY`, never returned in status, UI, audit, or provider error messages.

For a separately authorized live validation, the supported configuration is:
provider `openai`, web search enabled, model `gpt-4.1-mini` or
`gpt-4.1-mini-2025-04-14`, and base URL `https://api.openai.com/v1`.
Unknown model rates or compatible gateways fail closed: their billing/tool
contracts have not been validated. The existing general AI default `gpt-5-mini`
is deliberately not silently replaced or assigned guessed rates.

The Python/httpx adapter uses Responses, strict JSON schema, `store:false`,
standard service tier, `web_search_preview` with low search context, source
metadata inclusion, at most one built-in call and 1,800 output tokens per
attempt. Maximum four unresolved/inferred/contradicted tasks; confirmed criteria
are skipped. Request serialization is limited to 24,000 bytes; the input pricing
envelope reserves 32,000 tokens. Responses are bounded to 512 KiB.

Timeout comes from the existing 10–900 second setting (default 120). Source GETs
use the remaining deadline and at most 10 seconds each. Stream reads enforce
size/deadline bounds. Research leases include a timeout margin; discovery lease
behavior is unchanged. Native DNS resolution is OS-governed; an overdue worker
cannot commit after losing its lease.

Official documentation informed the implementation, rather than copying the
standalone provider's older price assumption:

- [Responses API contract](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [Web search and source metadata](https://developers.openai.com/api/docs/guides/tools-web-search)
- [Current tool pricing](https://developers.openai.com/api/docs/pricing)
- [GPT-4.1 mini pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini)

## Evidence policy: first-party-literal-v1

This deliberately conservative first version favors rejecting uncertain results.
It is not broad enrichment and does not guarantee finding employee/revenue data.

Every accepted claim must:

- Match a requested unresolved criterion and exact normalized target name/location.
- Have a usable public HTTPS URL present in completed search source/citation metadata.
- Use the known target website's exact hostname (www-equivalent allowed), not a
  directory, parent-network domain, unrelated company or arbitrary third-party site.
- Provide a fact identical to its quoted source passage; that passage and the
  known location must independently occur on the fetched page.

Page retrieval resolves and pins a public address, preserves hostname TLS SNI,
disables proxies and redirects, sends no API credentials, accepts HTML only, and
limits each page to 256 KiB. Private/link-local addresses, unusable URLs,
unavailable/paywalled/redirecting pages, script-only claims and uncorroborated
quotes produce no accepted evidence. At most four distinct pages are fetched.

Numeric verification supports explicit English first-party statements such as
`Company has 60 employees` / `Company employs 60 staff` and
`Company reports USD 100000 annual revenue`. The requested bounds come from the
recorded match criterion, not an AI score or a later unrelated profile edit.
Indirect, negated, vague or unsupported numeric claims remain unresolved.
Other literal requested-term matches are inferred, never marked verified solely
on model confidence. Semantic/exclusion contradictions without deterministic
proof remain unresolved. This narrow format intentionally limits recall.

`verified` means the attributed first-party statement was observed and, for
numeric criteria, compared deterministically; it is not a guarantee the business
reported a true or current value. Facts are literal quotations, so
`is_synthesized=false`. Model confidence is capped independently of match score.

Evidence hashes include opportunity, criterion, normalized quote and canonical
URL. Repeated attempts/runs cannot insert the same evidence twice or stack its
criterion contribution. Google evidence is never overwritten. Contradictory
accepted numeric evidence is retained alongside previous evidence.

## Deterministic score policy

Per criterion: confirmed +3, inferred +1, contradicted −4. Multiple positive
sources contribute only the strongest effect; any accepted contradiction wins
for that criterion. Sum is clamped to [−8,+10]. Across research runs, the
opportunity adjustment is recomputed from accepted research evidence, not added
again to its previous score. `score=clamp(base_match_score+adjustment,0,100)`.

Base score, original match record, confidence and discovery completeness are not
rewritten. A run with no accepted evidence is `no_evidence` with run delta 0 and
does not change the opportunity or erase previous research. UI distinguishes
base, research adjustment and final score, and separates discovery/research
evidence. The original discovery uncertainty statement remains explicitly about
the discovery baseline.

## Operational cost ledger — no customer billing

Pricing version: `openai-standard-preview-nonreasoning-2026-09-07-v1`.
Integer microUSD / Decimal arithmetic, rounded upward for incurred cost and
downward for configured caps:

- Input: $0.40/million; cached input: $0.10/million; output: $1.60/million.
- Non-reasoning web_search_preview: $25/1,000 calls; search-content tokens free.
- Conservative attempt reservation: 40,680 microUSD ($0.040680).
- Default three-attempt estimate/reservation envelope: $0.122040, within the
  existing $0.20 cap. The estimate is deliberately conservative, not a quote to
  charge the customer.

The cap is checked at estimate, confirmation, before each attempt and after
execution. Unknown model/service-tier usage is not assigned a false zero cost.
Each committed attempt reservation is retained until known usage settles it.
Timeouts, lost responses and expired leases retain worst-case exposure. The run
records per-attempt token/cached/output/search usage, known calculated costs,
reserved exposure, pricing version and completeness. Aggregate actual cost is
null when any attempt's actual usage is unknown; known partial cost is retained.

If returned usage exceeds the requested envelope/cap, usage is recorded and the
run fails without publishing evidence or starting further research. These are
application-side operational bounds under the documented provider contract, not
a claim that software can undo a provider charge or guarantee its invoice if
that external contract is violated. Price changes require versioned review.

No EconomicTransaction customer charge, invoice, payment, Stripe operation, or
automatic billing is created by this flow.

## Worker, recovery and UI

Existing queued/running/retry_wait lease recovery is reused. Network activity is
outside write transactions. Lease-owner/attempt/expiry checks fence every result
write. Retry only timeouts, HTTP 429 and 5xx; not auth/config/schema/attribution or
cost-cap failures. Attempt reservations prevent duplicate invocation of the same
attempt. A durable sanitized receipt allows a recovered worker to finish without
another provider call. A crash before receipt persistence may require another
bounded attempt; external exactly-once execution is not claimed.

UI uses the existing vanilla modules/modal controls: estimate → confirm/cancel →
202 → bounded polling with safe messages → refresh. Run IDs (not nonces) are
stored per user/tenant/managed context for navigation/lost-response recovery.
Polling stops on terminal states, changed context, access denial, repeated
transport errors, or its five-minute budget. Cancellation of the estimate dialog
does not queue/spend; the unused server estimate expires. No cancellation API or
ability to stop an already-dispatched provider request is introduced.

Feature OFF retains the existing canned demo route, including its existing role
policy; no legacy demo records are converted. Live failure never invokes demo.

## Scope and deferred findings

The Move-to-CRM route, CRM, billing, Google adapter/discovery logic and pure base
matcher remain unchanged. The only shared worker changes are research dispatch
and a research-specific lease timeout. No staging or commit occurred.

Deferred unchanged:

1. Move audit missing managed-session ID.
2. PIQ profile/evidence read-after-entitlement-removal policy.

## Smoke readiness

NOT READY in the inspected development environment: no configured research key
or research model override was found. Live research remains OFF. No real smoke
test was executed; separate authorization is still required.

## Final regression results

| Suite | Passed | Failed |
| --- | ---: | ---: |
| Phase 0 backend | 17 | 0 |
| Phase 1 backend | 47 | 0 |
| Phase 2 backend | 65 | 0 |
| Phase 3 backend/UI source | 10 | 0 |
| Phase 4 backend | 43 | 0 |
| Phase 4.1 backend/concurrency | 10 | 0 |
| Phase 5 backend | 99 | 0 |
| Other preserved backend | 37 | 0 |
| **Complete backend** | **328** | **0** |
| Phase 3 browser | 55 | 0 |
| Phase 4 browser | 14 | 0 |
| Phase 5 browser | 21 | 0 |
| **Combined browser** | **90** | **0** |
| Move PostgreSQL concurrency | 14 | 0 |
| Research PostgreSQL transactions/recovery | 4 | 0 |
| Interaction preservation | 28 | 0 |
| Theme preservation | 14 | 0 |

Before editing: 229 backend / 69 browser passed. Final complete backend run:
328 passed in 140.12 seconds; combined browser: 90 passed in 97.81 seconds.
The combined PostgreSQL gate passed 18 in 59.70 seconds. A pre-existing
Starlette/AnyIO deprecation warning remains; no failing or skipped regression
tests. An initial PostgreSQL harness launch used the wrong SQLite runtime
setting; re-running with the required disposable PostgreSQL URL passed, without
changing database implementation or the existing Move gate.

Execution used disposable containers with the working copy mounted read-only,
temporary SQLite databases and a separately labelled tmpfs PostgreSQL container
with no exposed host port. Provider HTTP and source pages were mocked; socket
network was forbidden in backend tests. Browser HTTP was fully intercepted.
The PostgreSQL test container/network were removed after completion; no user
database or application container was changed.

Final inventory against the pre-edit 731-file working-copy snapshot: 724
unchanged files, seven modified files, eight added files, zero removed files.
Hashes confirm the Move route, CRM route, pure matcher, discovery persistence
and Google provider are unchanged. Protected Product Owner database content
was excluded from inspection/hashing. No staging or commit was performed.
