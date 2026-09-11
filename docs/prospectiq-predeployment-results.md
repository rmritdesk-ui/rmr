# Local predeployment gate — 2026-09-11

Result: **PASS locally**. No push, VPS/DNS change, production certificate/secret
generation or real Google/OpenAI request. These results are not production acceptance.

| Gate | Observed result |
|---|---|
| Final RMR full regression | 540 passed; 3 existing legacy-packaging deselections |
| RMR PostgreSQL 16 bridge/federation/capability/CRM/operations/bootstrap | 105 passed |
| RMR exporter + packaging subset | 15 passed (overlaps full suite) |
| RMR launcher VM tests | 5 passed |
| PIQ Node offline/native/federation/bootstrap/readiness/navigation/Inspector/proxy | 49 passed test entries, including bundled offline research scripts |
| PIQ PostgreSQL 16 integration/session/capability/CRM/operations | 128 passed |
| PIQ Python discovery/source/evidence/geography suite | 356 passed |
| Actual API/queue/worker/Python provider fixtures | Native and imported discovery completed; one result each; foreign client/spoofed source/revoked capability denied |
| Chromium workflow/native CRM | CLIENT_ADMIN, SALES_REP, EXECUTIVE_VIEWER; native two-client login/generic CRM passed |
| Chromium operations | Refresh/reload, two-tab revocation, durable downgrade, outage fail-closed, restart recovery and CRM reconciliation passed |
| Final imported-profile Chromium flow | Actual PostgreSQL read-only RMR export; twice-imported one mapping; auto-selection; enabled mock pull; research authorization; one CRM lead/receipt per prospect; View Lead; Back to RMR; RMR login preserved; native PIQ logout passed |
| Production frontend build/image | Passed |
| RMR runtime image | Passed with included operator exporter |
| Real Nginx template fixture | Trusted HTTPS propagation, untrusted-header rejection, local HTTP fallback passed |
| Compose configuration | RMR production+bridge overlay, PIQ production, portable direct-discovery fixture all validate with placeholders |

All application tests ran network-none or on new internal-only Docker networks,
with disposable databases and no real provider configuration supplied to fixtures.
Image dependency installation used package registries; no application provider
workflow ran during builds. The manual seven-service stack and installed DBs were
not used for regression writes.

Harness corrections: mount all relative source/docs paths; replace the obsolete
inline-filter assertion with native shared-selector behavior; synchronize the
two-tab proof with that tab's exchange response; test bridge logout via its API
since UI now uses Back to RMR; allow repeat browser proofs to reuse a successful
CRM receipt rather than clicking its disabled already-moved button. No authorization
or duplicate-protection rule was weakened.

Warnings: existing AnyIO deprecation, Node VM/module warnings, duplicate JSX
`canConfirm` attribute, and Docker's heuristic warning on Stripe's **public** build
argument (blank for this build). These did not fail the gate. No unrelated UI fix
was included for the JSX warning.

## Secret/artifact review

Complete staged trees were scanned for Google/OpenAI/GitHub keys, private keys,
JWT literals, credential assignments and populated DSNs; private environments,
databases, certificates and bytecode were checked by path. No real secrets/private
artifacts were found. Heuristic hits were reviewed as public disposable PostgreSQL
fixture credentials, native development defaults in existing examples, invalid
password-hash sentinels, mock adapter/confirmation/outcome literals and assertion
syntax captured as strings. They are not production credentials; production guards
must remain enabled. No values are reproduced here. Scans are heuristic, not a
claim of formal absence of every possible secret.

85 previously tracked PIQ bytecode files were removed from the current index only;
local copies are retained/ignored and history is unchanged. Private manual env,
certificates, database copies, browser evidence, disposable logs and the machine-
specific `verify-transition-browser.py` remain outside both repositories. Reusable
tests live in the repositories. Disposable test resources are removed after gates;
manual services remain running.

Final source SHAs are reported by the accompanying local commits. No Phase 0–4
commit was amended/squashed. External prerequisites and future commands are in
`prospectiq-predeployment.md`; actual server inventory/TLS/live-pilot checks remain.
