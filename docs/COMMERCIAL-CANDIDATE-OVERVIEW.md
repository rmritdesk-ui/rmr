# RMR Software v5.1 Commercial Candidate

Version: `5.1.0-commercial-cb1`

This candidate implements the formally frozen pre-code baseline without changing its scope. It preserves the RC3 application and adds the controlled commercial layer for provider-neutral connected email, AI message approval, drip/event tracking, social copy/paste, RMR Owner secure tenant/data-custody access, tenant export/offboarding, Order Form entitlements, restricted-data controls, Partner Economics cost entries, and contract-to-product audit evidence.

## Frozen launch decisions

- Email integrates with Microsoft 365, Google Workspace/Gmail, and supported SMTP/IMAP providers. The customer mailbox/domain sends.
- Live provider credentials and provider approvals are not packaged; local Product Owner testing uses mock provider mode.
- Social content is generated for Facebook, Instagram, LinkedIn, and X, but the client copies/pastes it. Native social API publishing is post-launch.
- Human review is mandatory before AI-generated email is sent.
- One activity-event model links PIQ, CRM, campaign, message and outcome records.
- RMR Owner secure tenant access is RMR-only, MFA-gated, reason-required, time-limited, audited, and read-only by default.
- Customer-owned data can be exported without exposing RMR source code, provider secrets, internal security data, or another tenant.

## External activation dependencies

Microsoft/Google app registrations, OAuth client credentials, customer consent, SMTP/IMAP credentials, AI provider credentials, production DNS/mail configuration, and production infrastructure remain external activation dependencies. Adapter code and mock acceptance testing are included.
