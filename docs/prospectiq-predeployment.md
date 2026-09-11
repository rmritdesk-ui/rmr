# Final local preparation / future cPanel deployment

No deployment, push, DNS change, production certificate or production secret generation is authorized by this document. Use reviewed commit/image IDs, not historical Phase 4 SHAs. Phase 5A documents remain background inventories; this addendum supersedes their old UI/return/proxy preparation status.

## Established topology and placeholders

Existing repository deployment evidence identifies **cPanel/Apache** as the owner of ports 80/443. Confirm the actual account/vhosts/modules with the server administrator; do not install another public proxy. No final hostname is selected here.

* `https://<RMR_HOSTNAME>` -> Apache SSL vhost -> `127.0.0.1:18100` -> RMR app:8000.
* `https://<PIQ_HOSTNAME>` -> Apache SSL vhost -> `127.0.0.1:5173` -> PIQ frontend:80 -> same-origin `/api` -> backend:4000.
* PostgreSQL, Redis, worker and Python publish no ports. Private Docker networks still permit approved provider egress; only test networks are internal-only.

Do not run the development PIQ Compose on the server: it overrides DB credentials and publishes internal services. The new PIQ `docker-compose.production.yml` is a **standalone, reviewed template**, not an overlay or authorization to replace the installed stack. It names the installed PostgreSQL/Redis volumes explicitly; neither can be guessed. Preserve installed schema/data and any existing Redis authentication settings when reconciling the server configuration. Drain existing workers before switching; never start duplicate workers on the live queue.

Old IP:port URLs may later redirect at the existing host listener to the corresponding HTTPS origin. That requires a host-listener/routing decision because loopback-only containers no longer serve remote IP requests. Do not bind another process to an occupied port. No redirects are implemented here.

## Environment and immutable bindings

| Concern | RMR | PIQ |
|---|---|---|
| Public RMR origin | `RMR_BASE_URL` | `RMR_BASE_URL` |
| Public PIQ origin | `RMR_PROSPECTIQ_BASE_URL` | `RMR_PIQ_ORIGIN` |
| Issuer (exact RMR origin) | `RMR_PROSPECTIQ_ASSERTION_ISSUER` | `RMR_FEDERATION_ISSUER` |
| Shared audience | `RMR_PROSPECTIQ_ASSERTION_AUDIENCE` | `RMR_FEDERATION_AUDIENCE` |
| Stable instance | `RMR_PROSPECTIQ_INTEGRATION_INSTANCE_ID` | `RMR_INTEGRATION_INSTANCE_ID` |
| Exact callback root | `RMR_PROSPECTIQ_CALLBACK_URL` | `RMR_REGISTERED_CALLBACK_URL` |
| Flags | `RMR_PROSPECTIQ_BRIDGE_ENABLED` | `RMR_INTEGRATION_ENABLED` in backend AND worker |
| RSA key ID | `RMR_PROSPECTIQ_SIGNING_KEY_ID` | `RMR_FEDERATION_KEY_ID` |
| RSA material | `RMR_PROSPECTIQ_SIGNING_PRIVATE_KEY_FILE` | `RMR_FEDERATION_PUBLIC_KEY_FILE` (public only) |
| Grant/check HMAC | `RMR_PROSPECTIQ_HMAC_KEY_ID`, `RMR_PROSPECTIQ_HMAC_SECRET` | `RMR_PARTNER_HMAC_KEY_ID`, `RMR_PARTNER_HMAC_SECRET` in backend/worker |
| Independent CRM HMAC | `RMR_PROSPECTIQ_CRM_KEYS_JSON` receiver ring | `RMR_CRM_HMAC_KEY_ID`, `RMR_CRM_HMAC_SECRET` backend only |
| Cookies | `RMR_COOKIE_SECURE=true` | Renewal cookie always Secure/HttpOnly/Strict |
| CORS | Same-origin browser calls; retain Origin | `CORS_ORIGINS=https://<PIQ_HOSTNAME>`; no wildcard |
| Proxy trust | `FORWARDED_ALLOW_IPS`: actual Apache peer only | `PIQ_TLS_PROXY_CIDR`: Apache peer at Nginx; `PIQ_FRONTEND_PEER_CIDR` -> backend `TRUSTED_PROXY_IPS` |
| Frontend API | Native `/api` | Build `VITE_API_BASE_URL=/api` |

Authorization landing is `https://<RMR_HOSTNAME>/prospectiq-authorize`; callback is exactly `https://<PIQ_HOSTNAME>/` with fixed callback ID `piq-web`. No new return-URL variable exists: Back to RMR derives the configured RMR origin plus `/#/prospectiq`. Launch destination is `prospects`. Separate HTTPS hostnames and host-only cookies remain mandatory.

Use stable production UUIDs: integration instance + RMR tenant UUID -> PIQ client UUID, mapping ACTIVE. Identity links use issuer + immutable RMR user UUID -> immutable PIQ user UUID, with explicit collision approval where required. Never link by email alone or copy local demo UUIDs. Use the existing authorized mapping API/operations in the Phase 0/1/5A docs. Production issuer selection occurs **before** identity/profile bootstrap; do not casually change it afterward.

Profile mapping is `(issuer, tenant UUID, source profile UUID)` -> one deterministic PIQ profile UUID in `rmr_profile_bootstrap`. PIQ becomes authoritative. Default repeat imports are insert-only; optional explicit repair preserves user edits and rejects active/generated profiles. No bidirectional sync or implicit activation is added.

## Prepared files and exact future configuration commands

RMR: use existing `deploy/production.env.example` for private native settings, plus `deploy/bridge.env.example` for a separate private bridge file. `deploy/compose.bridge.yml` passes bridge settings/mounts into the app; merely placing them in a host env file was insufficient. Keep native keys unchanged.

```sh
# Placeholder paths below must be replaced privately. These are future commands.
docker compose --env-file <PRIVATE_RMR_COMPOSE_ENV> -f docker-compose.production.yml -f deploy/compose.bridge.yml config --quiet
docker compose --env-file <PRIVATE_PIQ_COMPOSE_ENV> -f docker-compose.production.yml config --quiet
```

The RMR Compose env additionally supplies `RMR_BRIDGE_ENV_FILE` and `RMR_FEDERATION_PRIVATE_DIR` (readable by app UID 10001). PIQ Compose env supplies `PIQ_PROJECT_NAME`, `PIQ_POSTGRES_VOLUME`, `PIQ_REDIS_VOLUME`, `PIQ_POSTGRES_ENV_FILE`, `PIQ_PYTHON_ENV_FILE`, `PIQ_BACKEND_ENV_FILE`, `PIQ_WORKER_ENV_FILE`, `PIQ_FEDERATION_PUBLIC_DIR`, `PIQ_TLS_PROXY_CIDR`, `PIQ_FRONTEND_PEER_CIDR` and all four `PIQ_*_IMAGE` references. Copy backend/worker example files privately, preserving other native/provider/queue settings. PostgreSQL env contains the **existing** POSTGRES_USER/DB/PASSWORD. Do not print expanded Compose output, DSNs or private exports. Image references must be immutable reviewed digests/tags, not `latest`.

## Stage 1: bridge OFF, native release

1. Approve release SHAs/images and maintenance window. Record installed revisions, project/volume names, native configuration, schema versions, queued jobs and resource headroom. Back up both PostgreSQL databases, application storage and protected encryption keys; verify a restore on a disposable clone. RMR's built-in SQLite backup is not a PostgreSQL backup.
2. After separate push/deploy approval, fetch/pull the selected commits and build immutable images (prefer off-server). Do not overwrite unrelated services or reuse local databases. Keep both bridge flags OFF; do not enable PIQ real providers for automated smoke tests.
3. Drain/stop only affected app/worker services. RMR: run `python -m rmr_platform.cli migrate` once using the reviewed production Compose context, AUTO_MIGRATE false. PIQ: apply the additive schema helper/preflight sequence in the Phase 5A PIQ runbook against a restored clone first; normal startup still performs native bootstrap. Do not run `db/init.sql` against an installed database or use fixture seed scripts. Keep durable CRM receipts/events.
4. Start only the reviewed native services with bridge OFF. Check internal health and native login/client/CRM behavior. Browser login for RMR still requires a trusted HTTPS origin: rehearse locally now; production HTTPS native smoke waits for Stage 2 if no existing safe HTTPS route exists. Do not temporarily disable Secure cookies to manufacture a pass.

## Stage 2: HTTPS integration pilot

1. Administrator supplies distinct hostnames/DNS and installs TLS using existing cPanel workflows. Apply the RMR Apache include and PIQ `deploy/apache-piq-ssl-include.conf.example` only to their SSL vhosts. Preserve AutoSSL paths; validate Apache syntax and approve graceful reload. Review any CDN/SELinux interaction narrowly.
2. Supply exact trusted proxy peers, not `*`, boolean/hop-count trust or broad shared Docker networks. Opt into PIQ's `frontend/nginx.trusted-proxy.conf.template`; the local default remains unchanged. Apache strips inbound forwarded headers and establishes HTTPS/client address. Nginx only preserves HTTPS from the configured peer; Node only trusts the configured frontend peer. Verify forged public headers cannot alter scheme/client-IP/rate-limit identity. Backend and frontend must not be publicly bypassable.
3. Generate/place production-only RSA and two independent HMAC secrets privately under approved custody. Never reuse local keys. Align both origins, issuer, audience, instance, callback, key IDs and clocks. Preserve native credentials/provider settings. Recreate affected services to apply env/mount changes; restart alone does not reload Compose environment.
4. Establish ACTIVE canonical tenant/client and explicit immutable identity mappings. With bridge settings validated, enable the bridge only for the approved pilot mapping (other mappings remain inactive). Export/import the existing source profile using the operator commands below. No provider request is made by import.
5. No-provider acceptance: native login still works; CLIENT_ADMIN opens original PIQ without second login; correct client/profile selected; RMR launcher has no duplicate discovery controls; Back to RMR returns to `/#/prospectiq` with RMR session intact; verify tenant/capability denials and host-only Secure cookies.
6. Only with separate bounded live approval: one controlled Pull Leads, inspect matching/evidence; explicitly authorize/cost-confirm Adaptive Research; Move to RMR CRM; repeat handoff proves same lead/receipt; View Lead opens native RMR CRM. Monitor queue/cost/egress and stop on failures. Do not equate mock regression with production provider acceptance.

### PostgreSQL profile bootstrap (future operator action)

RMR exporter now supports read-only PostgreSQL repeatable-read and the existing read-only SQLite snapshot path. The DSN stays in the container environment. Example command structure (substitute approved Compose context and UUIDs):

```sh
umask 077
docker compose <RMR_COMPOSE_ARGUMENTS> exec -T app python scripts/export_piq_profiles.py --database-url-env RMR_DATABASE_URL --tenant-id <RMR_TENANT_UUID> --instance <STABLE_INSTANCE_ID> --issuer https://<RMR_HOSTNAME> > <PRIVATE_PROFILE_EXPORT_JSON>
docker compose <PIQ_COMPOSE_ARGUMENTS> exec -T backend node scripts/import-rmr-profiles.mjs <RMR_TENANT_UUID> <PIQ_CLIENT_UUID> --apply < <PRIVATE_PROFILE_EXPORT_JSON>
```

The destination importer requires bridge ON and validates issuer/instance/client/tenant. Do not run it against an unreviewed export; remove the private transfer file under the approved retention policy. Repeat default import must create zero new profiles. Missing targeting is completed in PIQ, never fabricated.

## Rollback

Set RMR bridge OFF and PIQ backend/worker bridge OFF; recreate only affected services, stop/drain in-flight work and reconcile durable handoffs before retry. Restore previous reviewed app images/revisions if needed. Keep additive schema, mappings, receipts, outbox/idempotency records and native data; no destructive down migrations or `down -v`. Do not restore an old DB over accepted live CRM actions without a separately approved recovery/reconciliation plan.

## External inputs still needed

Final two hostnames and DNS access; cPanel account/vhost/modules and trusted-peer confirmation; TLS issuance; actual installed Compose/volume/native-schema inventory; production key placement and canonical tenant/client/user UUID approval; release publication and backup/restart/proxy-reload/live-pilot authorization. Local preparation does not verify current VPS state or production capacity.
