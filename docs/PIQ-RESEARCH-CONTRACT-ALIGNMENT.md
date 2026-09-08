# Adaptive Research contract alignment

Offline implementation, 2026-09-08. No migration or live provider validation.

## Planning and contract

The planner uses an allowlist of supported industry, geography, keyword, employee
and revenue criteria. Exclusions remain in the discovery match but never consume
one of the four research slots. Existing criterion order is preserved.

For Phoenix Home Buyers the next plan would be industry, geography, keyword:0
(relocation), keyword:1 (home buyer), replacing exclusion:0. Historical run
76c880b7-83f5-4b1f-bf4e-738aa5e07a96 is not rewritten or rerun.

The requested strict JSON contract is `task_results`, with exactly one entry per
planned criterion: criterion, found/not_found status, searched boolean, findings,
and a bounded search_summary. Found requires a nonempty findings list and searched
true. Not_found requires no findings. Four total findings remain the maximum.
Missing/duplicate/unplanned tasks or malformed claims fail closed.

The prompt describes the existing first-party, exact-identity/address, search
provenance, independent HTML fetch, literal quotation, requested-term and numeric
grammar requirements. No acceptance rule, score, cost cap, authorization or nonce
mechanism is relaxed. Model and provider configuration are unchanged.

## Persistence and compatibility

Existing receipt JSON stores diagnostic version/contract, aggregate returned,
entering_validation, accepted, rejected, source_fetches and reason counts.
Per-task diagnostics store criterion, provider_outcome, reporting, searched,
returned, entering_validation, accepted, rejected and reason counts.

Free-text model search summaries are deliberately discarded, not sanitized by
trying to guess which substrings are secrets. Neither reasoning, malformed values,
raw responses, source pages nor authentication headers are added to diagnostics.
Malformed output retains counts and fixed reason codes only.

Reason codes: missing_url, unsupported_provenance, entity_mismatch,
domain_mismatch, location_mismatch, source_fetch_failed, quotation_not_found,
unsupported_numeric_source, unsupported_criterion, duplicate, malformed_claim,
other_validation_failure, criterion_not_supported_by_quote.

Read-only API projections expose allowlisted counts/outcomes/reasons. Previous
aggregate claims responses remain readable with the same evidence checks. Old
receipts infer returned = accepted + rejected; missing per-task coverage remains
unknown, never invented. The Phoenix receipt therefore displays zero returned,
zero accepted, zero rejected without a data migration.

## Presentation

- Empty: Research completed, but no supporting findings were returned.
- Rejected: Research completed, but the findings did not pass RMR evidence validation.
- Accepted: Adaptive Research completed. / Research completed with partial results.
- Failure behavior and existing failure/retry/cancellation messages are preserved.

Lead intelligence displays the persisted task/finding summary, rejection reasons,
adaptive adjustment and final score. Historical coverage is labeled not recorded.
Low-evidence live candidates display Discovered prospect — fit unverified.
Stronger-evidence candidates display Discovered prospect — review profile evidence;
neither label asserts full qualification. Original scores, confidence, completeness
and underlying status values are preserved.

## Verification boundaries

Backend tests use fake HTTP/source pages and isolated temporary databases with
container networking disabled. Browser regression traffic is fully intercepted.
The unrelated image-theme tests require Pillow, absent from the offline test image.
Runtime verification is limited to normal Kerry CLIENT_ADMIN login and read-only
ProspectIQ views at localhost:8091. No discovery/research/CRM action is permitted.

Final results: 395 backend tests passed (including 99 existing Phase 5 and 35
contract tests); 132 PIQ browser tests passed (including 12 new contract/wording
checks). The six unrelated Pillow-dependent image-theme tests were excluded;
no dependency was downloaded. Existing Starlette/AnyIO deprecation warning only.

Only rmr-wip-manual-piq was restarted with docker-compose.piq-manual.yml; its
existing read-only WIP source mounts make an image rebuild unnecessary. It is
running and healthy. Normal Kerry CLIENT_ADMIN login, reload and a second fresh
browser session passed. Historical Phoenix research displays returned/accepted/
rejected 0/0/0, adjustment +0, final 35, and explicitly unknown historical task
coverage. Screenshot: evidence/piq-contract-client-admin.png.

Runtime browser traffic allowed local reads and normal login POSTs only, with
zero prohibited requests or page errors. Database run counts remained exactly
one completed discovery and one no_evidence research run. The historical receipt
was not rewritten. The WIP .env hash was unchanged. No provider calls, sealed
source, Product Owner database, standalone PIQ or credential changes occurred.
