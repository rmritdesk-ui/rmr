# Phase 2: deterministic Google candidate qualification

Only the WIP Google discovery path uses `piq-match-v1`. Demo discovery, demo
Adaptive Research, CRM, Move to CRM, frontend and feature defaults are unchanged.
No live API calls, new dependencies, schema changes, or migrations are required.
The Phase 0 migration remains `005.007.000-piq-integration-foundation`.

## Matching and qualification

Matching uses the queued immutable Target Profile snapshot. Industry comparisons
normalize case, punctuation/underscores and simple plurals, with explicit realtor/
real-estate-agent aliases. Exact categories confirm; related family/token evidence
is inferred. Only conflicts between explicitly mapped disjoint category families
hard-reject. Unknown categories and generic Google types remain unresolved.

Geography compares observed structured components and comma-delimited address
components against requested locations, with explicit US state/country aliases.
Structured city/state outrank formatted-address conflicts. A comparable explicit
conflict with every requested area rejects. Unsupported region hierarchies stay
unresolved. Search-area inference is allowed only with no observed location and
the actual executed query location recorded by the discovery service.

Exclusions reject only exact normalized source categories or observed geography.
Optional `category:`/`industry:` and `location:`/`geography:` prefixes disambiguate
scope; bare exact terms also work. Ambiguous text (e.g. large competitors) is not
interpreted as fact. Unproven exclusions remain unresolved, not confirmed compliance.
Google closed-permanently, closed-temporarily, or inactive status rejects.

Keywords use provider-returned company name/categories only, never query text.
Missing keywords, contacts, decision makers, employees and revenue do not reject.
Employee/revenue requirements are explicitly unresolved and receive no fit points.
`qualified` means eligible discovery opportunity, NOT a fully verified sales lead.
Rejected candidates are not inserted as visible opportunities: full criterion
diagnostics stay on the run, and tenant-safe GET status exposes a rejection summary.

## Exact score policy

| Component | Points |
|---|---|
| Geography | Confirmed 20; query-only inferred 6; otherwise 0 |
| Industry | Exact/normalized 25; related inferred 15; otherwise 0 |
| Contactability | Phone + website 15; either 8; neither 0 |
| Public listing | OPERATIONAL 10; additional 10 if rating 1–5 and review count > 0 |
| Keywords | 5 per observed keyword among the first four; maximum 20 |

Scores are not renormalized when a profile has no keywords. Apply the lowest cap:
unconfirmed geography 55; unresolved industry 40; related industry 65; unconfirmed
operational status 65; no contacts 60; hard rejection 0. Final score is bounded
0–100. Each cap records a reason and criterion references; the breakdown records
raw score, component points, cap adjustment and final score. Unsupported employee/
revenue requirements neither add points nor impose a fit-score cap. No adaptive
delta, buying-intent points or estimated deal value are introduced.

## Confidence and completeness are different metrics

Confidence is `round(90 * mean(evidence strength))` over assessable criteria,
including contactability/listing quality and requested keywords/exclusions.
Confirmed or source-backed contradicted = 1; inferred = .35; unresolved = 0.
The 90 ceiling reflects one provider, not independent corroboration. Requested
unsupported employee/revenue criteria are omitted from this mean but cap confidence
at 80. Strong evidence can confidently establish a bad fit: confidence is not score.

Completeness uses policy B: exclude unsupported employee/revenue from the assessable
denominator, while retaining their unresolved results and names in the breakdown.
Denominator: industry, geography, each keyword and each exclusion (not optional
contactability/listing metrics). Confirmed/contradicted count 1, inferred .5,
unresolved 0. Return rounded percentage. Thus 100% means complete *assessable*
evidence, not confirmed employees/revenue or universally verified qualification.

## Persistence, evidence and idempotency

Pipeline: normalized Google candidates → tenant/provider dedupe → immutable profile
matching → rejection or qualification → opportunity + profile match + evidence.
All writes remain in the worker's short lease-fenced transaction after HTTP finishes.
Existing same-tenant Google duplicates remain skip-only, including across runs;
Phase 2 does not retroactively rescore prior rows or merge demo/legacy records.

Qualified rows get `score = base_match_score`, confidence and completeness. Required
legacy monetary fields remain neutral zero; adaptive delta remains NULL. One
PiqProfileMatch per run/opportunity stores version, breakdown, criterion states,
qualification explanation, scores and timestamps, using the existing unique key.

Evidence records have tenant/run/opportunity ownership, provider, observed facts,
source URL/title/domain where returned, observation time and stable hashes.
Every point-bearing criterion references its persisted evidence hash. Confirmed
facts are verified; inferred facts are not. Verified means observed in Google,
not independently corroborated. No synthesized contact or unresolved factual row
is created. Negative source facts remain traceable in rejected-run diagnostics.
Phase 0 has no dedicated evidence `score_effect` column: it is stored in bounded
`raw_json.score_effect` and in the match breakdown, without expanding the schema.
The normalized provider contract and bounded profile terms bound evidence payloads;
raw HTTP responses and arbitrary raw provider metadata are never copied to evidence.

Hashes include tenant, run, opportunity, version and criterion content; timestamps
are excluded so replay cannot create duplicates. Tenant serialization, fingerprint
uniqueness, match uniqueness and evidence-hash uniqueness protect persistence.
Opportunity/evidence/match writes roll back together on failure. Worker lease/retry
behavior is unchanged. Status diagnostics distinguish received, duplicate, rejected,
qualified, persisted and provider-error counts. `persisted` counts newly created
opportunities, not existing skipped identities.

## Verification

Run `python -m pytest -q -p no:cacheprovider` with project dependencies plus pytest
and Pillow, WIP mounted read-only, isolated temporary SQLite data, auto-migration/
seeding disabled. Tests mock Google responses and block network connections.
Never use the Product Owner database. PostgreSQL SQL compilation checks are not
a substitute for an actual PostgreSQL deployment test.

No Phase 3 polling/UI work is included.
