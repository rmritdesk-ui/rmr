# Deployment Assumptions

- RMR controls or authorizes the target infrastructure.
- Step2 has sufficient server-administrator access to install Docker, configure DNS/TLS, and manage backups.
- One application instance runs against one local persistent data volume during the pilot.
- The target server provides reliable SSD storage and off-server backup capability.
- The reverse proxy handles HTTPS and forwards to the application port.
- The pilot is not horizontally scaled.
- External integrations remain disabled/mock until credentials and provider-specific validation are approved.
- RMR retains the authoritative source/release package; target-server files are not the development source of truth.
- Time is synchronized on the server because sessions, audit history, transactions, and backups depend on accurate timestamps.
- The customer is responsible for the accuracy of client-entered business records.
- RMR/Step2 support visibility is read-only for client operational data.
