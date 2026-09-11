# RMR production preparation: cPanel/Apache VPS

For the current standalone ProspectIQ integration use `prospectiq-predeployment.md`
alongside this native deployment reference. The native PIQ example flags now default
OFF; the historical live-native configuration description below is not an instruction
to enable a second discovery application during the standalone bridge rollout.

This is a future deployment runbook, not authorization to deploy. The inspected
target runs AlmaLinux 9.8, Docker 29.3.1 and Compose 5.1.1. cPanel/Apache already
owns ports 80/443. Do not install another public Nginx service or change existing
ProspectIQ, Corvee or PTS services, ports, volumes, networks or databases.

## Architecture and resources

HTTPS RMR subdomain -> existing cPanel/Apache vhost -> 127.0.0.1:18100 -> app:8000
-> postgres:5432 on a dedicated RMR bridge. PostgreSQL publishes no host port.
Use only docker-compose.production.yml, not the pilot/manual/PO Compose files.
The default project is rmr-production; no fixed container names or external
networks/volumes collide with other applications. It has exactly two services.

Named volumes rmr-production_postgres-data and rmr-production_app-data persist
PostgreSQL and all /data files. Neither mounts local SQLite, source code, evidence
or smoke artifacts. The application runs as UID/GID 10001. A new Docker volume
inherits /data ownership from the image. Never use down -v in production.

App memory is capped at 640 MiB and 1 CPU; PostgreSQL at 512 MiB and 0.5 CPU,
with 128 MiB shared buffers and 40 connections. Combined memory caps are about
1.125 GiB, leaving headroom within the reported ~2 GiB available, but not a load
capacity guarantee. Start with one app process/replica. Logs rotate at 10 MiB x 3
per service. Allow 150 seconds for app shutdown, and monitor worker jobs/disk/RAM.
Building on a 3.6 GiB VPS can temporarily consume additional resources; consider
building off-server if monitored headroom is inadequate. Production bridge egress
is needed for approved HTTPS provider/evidence requests. Only tests make it internal.

## Environment

Copy deploy/production.env.example to private .env.production, mode 0600; never
reuse the populated local smoke .env. Always pass --env-file .env.production.
Do not print docker compose config (without --quiet) on a real environment: its
expanded output contains secrets. Shell variables override env-file values;
use a clean deployment shell with no stale RMR_* exports.

Required: release tag/source SHA, HTTPS base URL, dedicated PostgreSQL DB/user/
password, stable signing/encryption keys and trusted proxy source addresses.
Use simple DB/user identifiers and a unique URL-safe password, preferably 64 hex
characters (for example generated privately with openssl rand -hex 32). The same
password is used verbatim by PostgreSQL and in the private service-name DSN; do
not put URL-reserved characters in it. Generate the integration key as a valid
Fernet key; preserve encryption keys with protected recovery material.

RMR_SETUP_TOKEN is required for first-owner setup but can be blank after bootstrap.
Remove it from the private env and recreate app after the real owner is created.
Production demo/seed/local-recovery settings are forced OFF, Secure cookies ON,
and AUTO_MIGRATE=false in Compose regardless of a developer env-file override.

The reference enables live PIQ switches. Provision Google Places/OpenAI keys and
approved budgets privately before enabling them. Compose defaults the switches
OFF when absent. It fixes providers to google_places/openai, research model to
gpt-4.1-mini-2025-04-14, and attempts to one. The initial reference caps are one
query, 50 retained results/100 candidates and $0.05 research. Supply SMTP settings
for invitation/password-reset delivery. Campaign workers, mock billing and other
integrations are not activated by this deployment. Never use the production live
env for tests: the offline overlay forcibly clears keys and disables all workers.

## Exact future commands (NOT executed on the VPS during preparation)

First review, commit and push the production configuration in a separately
authorized step. The existing rc1 commit predates these files. Select the future
reviewed commit explicitly; do not retag or assume the old rc1 already includes it.

```sh
cd /home/deploy
git clone https://github.com/rmritdesk-ui/rmr.git rmr
cd rmr
git checkout <reviewed-commit-containing-production-compose>
umask 077
cp deploy/production.env.example .env.production
chmod 600 .env.production
vi .env.production
# Fill real values privately. Set RMR_RELEASE_REVISION to git rev-parse HEAD.
docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
docker compose --env-file .env.production -f docker-compose.production.yml build app
docker compose --env-file .env.production -f docker-compose.production.yml up -d --wait postgres
docker network inspect rmr-production_rmr --format '{{(index .IPAM.Config 0).Gateway}}'
vi .env.production
# Append the inspected bridge gateway to FORWARDED_ALLOW_IPS, retaining loopback.
docker compose --env-file .env.production -f docker-compose.production.yml run --rm --no-deps app python -m rmr_platform.cli migrate
docker compose --env-file .env.production -f docker-compose.production.yml up -d --wait app
docker compose --env-file .env.production -f docker-compose.production.yml ps
curl --fail http://127.0.0.1:18100/api/health
```

The one-shot migration command creates all core/PIQ/CB1/commercial schemas and
reference catalogs without demo accounts; it does not run the application worker
or publish app ports. Do not start app before migration succeeds. Re-running the
command is idempotent; run only one migrator at a time. No implicit DDL is restored.
For upgrades, back up first, stop app, run migrations, then start the new image.

## cPanel/Apache integration (administrator action later)

Create the real RMR subdomain/account and AutoSSL certificate using supported
cPanel workflows. An administrator should install the reviewed contents of
deploy/apache-rmr-ssl-include.conf.example in only this HTTPS vhost's userdata
include, normally /etc/apache2/conf.d/userdata/ssl/2_4/<cpanel-user>/<domain>/rmr.conf.
Do not edit cPanel-managed httpd.conf directly or apply the example server-wide.
The cPanel account name is not necessarily the Linux deploy username.

Preserve Host, have mod_proxy supply X-Forwarded-For, and set X-Forwarded-Proto
to https at the SSL vhost. The example discards untrusted inbound forwarded-for
values; a CDN requires separately reviewed mod_remoteip configuration. Ensure
the backend trusts only the actual proxy peer (usually the RMR bridge gateway),
not '*'. Verify the observed peer after deployment; topology may change it.
Keep /.well-known/ local for cPanel/AutoSSL. Configure HTTP-to-HTTPS redirection
in the supported domain/vhost workflow and verify it after adding includes.

The administrator must use the cPanel rebuild procedure, validate Apache syntax
and perform an approved graceful reload. This affects a shared server and is not
part of the automated RMR Compose commands. Never disable SELinux globally; if
Apache loopback proxying is denied, have the administrator inspect AVC logs and
approve the narrow required policy change. Check public HTTPS login and Secure/
HttpOnly/SameSite cookie behavior only after proxy/TLS is installed; local HTTP
health is testable, but Secure-cookie browser login requires HTTPS.

Official references:
- https://docs.cpanel.net/ea4/apache/modify-apache-virtual-hosts-with-include-files/
- https://httpd.apache.org/docs/2.4/mod/mod_proxy.html

## Local validation and remaining gates

Use a unique -p rmr-production-validation-* project with test-only environment,
the production Compose file plus tests/production-offline.compose.yml. That
overlay disables PIQ/campaign workers and live flags, clears provider/SMTP keys
and makes the dedicated network internal. It preserves the real port binding,
named volumes, resource settings and migration command. Never mount any existing
database or use an existing Compose project. Remove only those test resources
afterward; real runtime data must always be preserved.

Local preparation validation (2026-09-08): production image build and its 57
source gates passed; deployment/bootstrap pytest checks passed 33/33. Dedicated
PostgreSQL 16 bootstrap and repeat migration passed, with 9 core ledger entries,
1 CB1 ledger entry, 14 service references, zero users/tenants and zero PIQ rows.
Secure/HttpOnly/SameSite=strict cookie generation passed without storing a user.
Docker Desktop blocked host publication on the internal-only test network; a
second, dedicated standard-bridge check passed host health/frontend at the exact
127.0.0.1:18100 binding. All workers/live flags stayed OFF and keys blank in both
checks. Named database storage survived container/network recreation. These are
local preparation results, not VPS, Apache or live-provider acceptance.

Before go-live, configure PostgreSQL-aware and application-file backups, off-host
retention, restore tests, host restart persistence, resource/queue monitoring and
bounded separately authorized PIQ acceptance. Built-in RMR backups remain SQLite-
only. Core health is not proof of SMTP/provider readiness. No public proxy, live
provider, VPS database or existing stack is changed by this preparation task.
