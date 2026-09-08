# Exact Product Owner Manual QC Sequence — Correction Build 1

Use the exact CB1 ZIP and do not modify source files during QC.

## A. Upgrade and preservation

1. Confirm current `5.1.0-commercial-rc1` is healthy and CAF is present.
2. Run `UPGRADE-FROM-V5.1-CANDIDATE.bat`.
3. Confirm success explicitly names `5.1.0-commercial-cb1`.
4. Refresh with a normal browser refresh; confirm the CB1 release UI appears without manually clearing cache.
5. Confirm CAF, prior onboarding notes, services and pricing survived.

## B. RMR Owner and navigation

6. Sign in as RMR Owner.
7. Confirm password show/hide works.
8. Open CAF Client 360 from the portfolio and return without browser Back.
9. Confirm **Manage Client Access**, **Data Custody / Export** and **Commercial Readiness** are visible to RMR Owner.
10. Confirm Commercial Readiness opens a real page and identifies passed, blocked and external gates.
11. Confirm System Health uses plain-English business status with separate technical details.

## C. Client Administrator and onboarding

12. Open CAF > Manage Client Access.
13. Invite a designated CAF test administrator.
14. Verify Pending status, tenant assignment and audit event.
15. Resend once and verify status/history; do not create duplicate users.
16. Open the activation link in Incognito, set a password and activate.
17. Verify Stage 2 **Tenant Provisioning & Client Access** changes only after activation evidence exists.
18. Verify Go-Live/100% readiness remains blocked if Order Form or required entitlements are missing.
19. Test reset/recovery, then confirm revoke/deactivate prevents login.

## D. Client login and tenant isolation

20. Reactivate/create the CAF test administrator as necessary and sign in in Incognito.
21. Confirm the client sees CAF only and cannot access the Portfolio Command Center.
22. Confirm only entitled modules are shown and direct API/URL attempts to another tenant return 403/404.
23. Confirm the client can exit/log out without entering RMR administration.

## E. RMR Data Custody and export

24. As RMR Owner, claim/setup Data Custody authority and multi-factor authentication.
25. Start CAF Data Custody access with a required reason.
26. Confirm a persistent privileged-access banner and read-only default.
27. Confirm Step2 and ordinary RMR Administrators cannot invoke Data Custody.
28. Export CAF data. Inspect the ZIP and manifest.
29. Confirm CAF data is present and other-tenant data, source code, passwords, provider tokens and internal secrets are absent.
30. Exit explicitly and verify the session expires and audit history remains.
31. Exercise offboarding status without deleting CAF; verify export/retention/integration-revocation steps are visible.

## F. Email, AI and drip using the mock provider

32. Connect the Mock provider to CAF with an approved sender and physical postal address.
33. Create a CRM/PIQ-linked campaign and recipient.
34. Generate an AI-assisted message from supported facts.
35. Attempt to add an unsupported factual assertion; confirm it is rejected or flagged before approval.
36. Preview, edit and approve; verify version history and approved hash.
37. Schedule a two-step drip. Confirm the worker sends only the approved version.
38. Simulate a reply; verify later messages stop and a sales task/activity is created.
39. Repeat for bounce and unsubscribe; verify suppression and no future send.
40. Restart Docker and verify pending jobs are not duplicated.

## G. Social copy/paste

41. Generate Facebook, Instagram, LinkedIn and X drafts.
42. Verify Copy Post and Copy Hashtags.
43. Confirm no native Publish/OAuth action exists.
44. Mark one draft Published manually, store a test post URL and verify the shared activity timeline.

## H. Recovery gates

45. Run the CB1 automated QC/acceptance runner supplied in the package.
46. Create a backup and verify evidence.
47. Run the PostgreSQL certification separately before production acceptance.
48. Perform one controlled rollback to the previous candidate and confirm it becomes healthy.
49. Re-run the CB1 upgrade and confirm CAF remains intact.
50. Record Product Owner PASS/FAIL for every pending row in the 301-row matrix.

Do not authorize Hasan handoff until all non-external launch gates pass and every remaining external dependency is clearly marked rather than hidden.
