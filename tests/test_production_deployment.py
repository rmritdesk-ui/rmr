"""Offline release-definition contract; no Docker, DB or provider calls."""
from pathlib import Path
import re
import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "docker-compose.production.yml").read_text()
OFFLINE = (ROOT / "tests/production-offline.compose.yml").read_text()


def test_only_app_and_postgres_services():
    section = COMPOSE.split("services:\n", 1)[1].split("\nnetworks:", 1)[0]
    assert re.findall(r"^  ([a-z-]+):$", section, re.M) == ["postgres", "app"]
    assert "image: postgres:16\n" in section


def test_loopback_binding_and_no_database_publication():
    postgres, app = COMPOSE.split("  postgres:\n", 1)[1].split("\n  app:\n", 1)
    assert not re.search(r"^    ports:", postgres, re.M)
    assert re.findall(r'^      - "([^"\n]+:\d+)"$', app, re.M) == ["127.0.0.1:18100:8000"]


def test_private_dsn_and_required_password_without_fallback():
    assert "@postgres:5432/${RMR_POSTGRES_DB:?Required}" in COMPOSE
    assert "${RMR_POSTGRES_PASSWORD:?" in COMPOSE
    assert "${RMR_POSTGRES_PASSWORD:-" not in COMPOSE
    assert "env_file:" not in COMPOSE


def test_persistent_named_volumes_and_no_source_bind_mounts():
    assert "postgres-data:/var/lib/postgresql/data" in COMPOSE
    assert "app-data:/data" in COMPOSE
    assert "./data:" not in COMPOSE and "./rmr_platform:" not in COMPOSE
    assert "external:" not in COMPOSE


@pytest.mark.parametrize("key,value", [
    ("RMR_ENVIRONMENT", "production"), ("RMR_COOKIE_SECURE", '"true"'),
    ("RMR_INSTALL_PROFILE", "empty"), ("RMR_AUTO_MIGRATE", '"false"'),
    ("RMR_AUTO_SEED", '"false"'), ("RMR_ALLOW_DEMO_CREDENTIALS", '"false"'),
    ("RMR_LOCAL_RECOVERY_MODE", '"false"'),
])
def test_production_safety_cannot_be_overridden_by_local_env(key, value):
    assert f"      {key}: {value}\n" in COMPOSE


@pytest.mark.parametrize("key", ["RMR_SECRET_KEY", "RMR_CREDENTIAL_ENCRYPTION_KEY",
                                 "RMR_INTEGRATION_ENCRYPTION_KEY", "FORWARDED_ALLOW_IPS"])
def test_required_production_security_configuration(key):
    assert "${" + key + ":?" in COMPOSE


def test_bounded_resources_and_restart_health():
    assert COMPOSE.count("restart: unless-stopped") == 2
    assert COMPOSE.count("healthcheck:") == 2
    assert "condition: service_healthy" in COMPOSE
    assert "mem_limit: 640m" in COMPOSE and "mem_limit: 512m" in COMPOSE
    assert 'user: "10001:10001"' in COMPOSE and "cap_drop: [ALL]" in COMPOSE


@pytest.mark.parametrize("key", ["RMR_PIQ_WORKER_ENABLED", "RMR_PIQ_LIVE_DISCOVERY_ENABLED",
                                 "RMR_PIQ_LIVE_RESEARCH_ENABLED", "RMR_PIQ_RESEARCH_WEB_SEARCH_ENABLED"])
def test_live_flags_environment_driven_but_offline_overlay_forces_off(key):
    assert "${" + key + ":-false}" in COMPOSE
    assert f'{key}: "false"' in OFFLINE


def test_offline_overlay_clears_keys_and_blocks_external_network():
    assert "internal: true" in OFFLINE
    assert 'RMR_GOOGLE_PLACES_API_KEY: ""' in OFFLINE
    assert 'RMR_AI_API_KEY: ""' in OFFLINE


def test_migrations_remain_explicit():
    entrypoint = (ROOT / "scripts/container-entrypoint.sh").read_text()
    assert 'exec "$@"' in entrypoint
    assert not re.search(r"^python .*migrate", entrypoint, re.M)
    doc = (ROOT / "docs/CPANEL-PRODUCTION-DEPLOYMENT.md").read_text()
    assert "run --rm --no-deps app python -m rmr_platform.cli migrate" in doc


def test_cpanel_proxy_example_preserves_host_and_sets_https():
    text = (ROOT / "deploy/apache-rmr-ssl-include.conf.example").read_text()
    for expected in ['ProxyRequests Off', 'ProxyPreserveHost On', 'ProxyAddHeaders On',
                     'RequestHeader set X-Forwarded-Proto "https"', 'http://127.0.0.1:18100/']:
        assert expected in text
