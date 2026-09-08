# Provider Activation Matrix

| Provider | Code | Local Mock Test | Live Requirement | Launch Classification |
|---|---|---|---|---|
| Microsoft 365 / Outlook | Included | PASS required | Azure app registration, OAuth credentials, tenant/user consent, webhook URL | Production activation / external dependency |
| Google Workspace / Gmail | Included | PASS required | Google Cloud app, OAuth consent/configuration, credentials, webhook/polling setup | Production activation / external dependency |
| SMTP / IMAP / iCloud-compatible | Included | PASS required | Customer provider permits authenticated SMTP/IMAP and supplies credentials/app password | Production activation / external dependency |
| AI provider | OpenAI-compatible adapter + safe template fallback | PASS required | API key/model approval and cost controls | Production activation / external dependency |
| Facebook / Instagram / LinkedIn / X publishing | Not included by frozen scope | N/A | Post-launch decision | Post-launch |
