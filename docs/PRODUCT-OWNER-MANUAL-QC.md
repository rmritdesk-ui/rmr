# Product Owner Manual QC

1. Preserve the existing v5.0 installation and data as the rollback baseline.
2. Extract this candidate to a new folder.
3. Start Docker Desktop and confirm Engine running.
4. Run `START-PRODUCT-OWNER-TEST.bat`.
5. Sign in as RMR Owner.
6. Confirm CAF and prior data are preserved after the approved upgrade path.
7. Open `/commercial`; verify version/status and social copy/paste scope.
8. Record an Order Form and activate EMAIL and SOCIAL_CONTENT for a test tenant.
9. Connect a MOCK mailbox, create a campaign, generate a message, edit/approve it, and send. Verify the message cannot send before approval.
10. Submit reply, bounce and unsubscribe webhook events; verify reply stops remaining drip messages and suppression blocks later send attempts.
11. Create a social draft and verify four platform-specific copy outputs and no native publish control.
12. Enroll RMR Owner MFA; open Secure Tenant Access with a reason; verify a non-owner cannot open it.
13. Export the tenant; inspect manifest and tenant-scoped CSV files. Confirm credentials/tokens are excluded.
14. Verify client users cannot access another tenant, Partner Economics or RMR Owner functions.
15. Verify module API calls are denied when the corresponding entitlement is inactive.
16. Enter direct, shared, API, labor, support and payment-processing cost records; verify policy-pending items remain identified.
17. Restart Docker and verify persistence.
18. Run backup/restore and upgrade/rollback gates.
19. Run `RUN-COMMERCIAL-ACCEPTANCE-TESTS.bat`.
20. Do not give the candidate to Hasan until the Windows/Docker, client-role, tenant-isolation, export and rollback gates pass.
