# Remaining External Activation Dependencies

These items are not application-code deferrals. They require credentials, provider authorization, production infrastructure or professional approval outside the build environment.

## Microsoft 365 / Outlook

- Microsoft Entra application registration
- Redirect URI and tenant configuration
- Required Microsoft Graph delegated permissions
- Customer authorization and consent
- Live send/reply/refresh/revocation testing

## Google Workspace / Gmail

- Google Cloud OAuth client
- Consent-screen configuration and any required verification
- Gmail scopes and redirect URI
- Customer authorization
- Live send/reply/refresh/revocation testing

## SMTP / IMAP

- Customer provider hostnames, ports and TLS requirements
- Provider-supported authentication or app-specific password/OAuth
- Live send, inbound synchronization, reconnect and credential-rotation testing

## Sending-domain readiness

- Customer-approved sender identity
- Physical postal address
- SPF, DKIM and DMARC status where applicable
- Suppression/unsubscribe policy and sender-volume controls

## AI provider

- Production AI-provider credential
- Tenant usage limits and cost policy
- Live output/cost monitoring

## PostgreSQL and hosting

- Execute `POSTGRESQL-CERTIFY.bat` in Docker
- Production secrets and backup destination
- TLS, DNS, reverse proxy, monitoring and restore testing

## Payment processing

- Approved third-party processor credentials and webhook verification
- No full card number or card verification value is stored by RMR Software

## Legal / commercial

- Final U.S. counsel approval of MSA/Order Form and privacy/security provisions
- RMR insurance, tax/accounting and customer pricing decisions

No external dependency may be silently reported as PASS. Commercial Readiness must show it as Pending External or Needs Configuration until evidence exists.
