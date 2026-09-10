from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_decimal(name: str, default: str, *, minimum: str, maximum: str) -> Decimal:
    try:
        value = Decimal(os.getenv(name, default))
    except (InvalidOperation, TypeError):
        value = Decimal(default)
    return max(Decimal(minimum), min(Decimal(maximum), value))


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    host: str
    port: int
    data_dir: Path
    database_url: str
    secret_key: str
    cookie_secure: bool
    session_hours: int
    base_url: str
    payment_provider: str
    allow_demo_credentials: bool
    auto_migrate: bool
    auto_seed: bool
    max_upload_mb: int
    setup_token: str
    install_profile: str
    invitation_hours: int
    password_reset_minutes: int
    local_recovery_mode: bool
    piq_live_discovery_enabled: bool
    piq_discovery_provider: str
    google_places_api_key: str
    piq_max_queries_per_run: int
    piq_max_results_per_run: int
    piq_max_candidates_per_run: int
    piq_discovery_timeout_seconds: int
    piq_live_research_enabled: bool
    piq_research_provider: str
    piq_research_web_search_enabled: bool
    piq_research_max_cost_usd: Decimal
    piq_research_timeout_seconds: int
    piq_research_model: str
    ai_api_key: str
    ai_base_url: str
    ai_model: str
    piq_worker_enabled: bool
    piq_worker_poll_seconds: int
    piq_job_max_attempts: int
    prospectiq_bridge_enabled: bool = False
    prospectiq_base_url: str = ""
    prospectiq_integration_instance_id: str = ""
    prospectiq_authorization_code_ttl_seconds: int = 60
    prospectiq_assertion_audience: str = ""
    prospectiq_assertion_issuer: str = ""


def get_settings() -> Settings:
    data_dir = Path(os.getenv("RMR_DATA_DIR", str(Path.cwd() / "data"))).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "training").mkdir(parents=True, exist_ok=True)
    (data_dir / "backups").mkdir(parents=True, exist_ok=True)
    (data_dir / "tenant-themes").mkdir(parents=True, exist_ok=True)

    database_url = os.getenv("RMR_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        database_url = f"sqlite:///{data_dir / 'rmr_platform.db'}"

    secret_key = os.getenv("RMR_SECRET_KEY", "").strip()
    if not secret_key:
        # Local development only. The installer always writes a stable secret.
        secret_key = secrets.token_urlsafe(48)

    environment = os.getenv("RMR_ENVIRONMENT", "development").lower()
    if environment == "production":
        if (os.getenv("RMR_INSTALL_PROFILE", "empty").strip().lower() != "empty"
                or _env_bool("RMR_AUTO_SEED")
                or _env_bool("RMR_ALLOW_DEMO_CREDENTIALS")
                or _env_bool("RMR_LOCAL_RECOVERY_MODE")):
            raise ValueError("Production requires an empty install profile with demo seeding, demo credentials and local recovery disabled")
    return Settings(
        app_name="RMR Global",
        environment=environment,
        host=os.getenv("RMR_HOST", "0.0.0.0"),
        port=int(os.getenv("RMR_PORT", "8000")),
        data_dir=data_dir,
        database_url=database_url,
        secret_key=secret_key,
        cookie_secure=os.getenv("RMR_COOKIE_SECURE", "false").lower() == "true",
        session_hours=int(os.getenv("RMR_SESSION_HOURS", "12")),
        base_url=os.getenv("RMR_BASE_URL", "http://localhost:8000").rstrip("/"),
        payment_provider=os.getenv("RMR_PAYMENT_PROVIDER", "mock").lower(),
        allow_demo_credentials=os.getenv("RMR_ALLOW_DEMO_CREDENTIALS", "false").lower() == "true",
        auto_migrate=os.getenv("RMR_AUTO_MIGRATE", "true").lower() == "true",
        auto_seed=os.getenv("RMR_AUTO_SEED", "false").lower() == "true",
        max_upload_mb=int(os.getenv("RMR_MAX_UPLOAD_MB", "250")),
        setup_token=os.getenv("RMR_SETUP_TOKEN", "").strip(),
        install_profile=os.getenv("RMR_INSTALL_PROFILE", "empty").strip().lower(),
        invitation_hours=int(os.getenv("RMR_INVITATION_HOURS", "168")),
        password_reset_minutes=int(os.getenv("RMR_PASSWORD_RESET_MINUTES", "30")),
        local_recovery_mode=os.getenv("RMR_LOCAL_RECOVERY_MODE", "true" if environment != "production" else "false").lower() == "true",
        piq_live_discovery_enabled=_env_bool("RMR_PIQ_LIVE_DISCOVERY_ENABLED", False),
        piq_discovery_provider=os.getenv("RMR_PIQ_DISCOVERY_PROVIDER", "demonstration").strip().lower(),
        google_places_api_key=os.getenv("RMR_GOOGLE_PLACES_API_KEY", "").strip(),
        piq_max_queries_per_run=_env_int("RMR_PIQ_MAX_QUERIES_PER_RUN", 8, minimum=1, maximum=25),
        piq_max_results_per_run=_env_int("RMR_PIQ_MAX_RESULTS_PER_RUN", 50, minimum=1, maximum=50),
        piq_max_candidates_per_run=_env_int("RMR_PIQ_MAX_CANDIDATES_PER_RUN", 100, minimum=1, maximum=100),
        piq_discovery_timeout_seconds=_env_int("RMR_PIQ_DISCOVERY_TIMEOUT_SECONDS", 30, minimum=5, maximum=300),
        piq_live_research_enabled=_env_bool("RMR_PIQ_LIVE_RESEARCH_ENABLED", False),
        piq_research_provider=os.getenv("RMR_PIQ_RESEARCH_PROVIDER", "demonstration").strip().lower(),
        piq_research_web_search_enabled=_env_bool("RMR_PIQ_RESEARCH_WEB_SEARCH_ENABLED", False),
        piq_research_max_cost_usd=_env_decimal("RMR_PIQ_RESEARCH_MAX_COST_USD", "0.20", minimum="0", maximum="100"),
        piq_research_timeout_seconds=_env_int("RMR_PIQ_RESEARCH_TIMEOUT_SECONDS", 120, minimum=10, maximum=900),
        piq_research_model=os.getenv("RMR_PIQ_RESEARCH_MODEL", "").strip(),
        ai_api_key=os.getenv("RMR_AI_API_KEY", "").strip(),
        ai_base_url=os.getenv("RMR_AI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
        ai_model=os.getenv("RMR_AI_MODEL", "gpt-5-mini").strip(),
        piq_worker_enabled=_env_bool("RMR_PIQ_WORKER_ENABLED", False),
        piq_worker_poll_seconds=_env_int("RMR_PIQ_WORKER_POLL_SECONDS", 5, minimum=1, maximum=300),
        piq_job_max_attempts=_env_int("RMR_PIQ_JOB_MAX_ATTEMPTS", 3, minimum=1, maximum=10),
        prospectiq_bridge_enabled=_env_bool("RMR_PROSPECTIQ_BRIDGE_ENABLED", False),
        prospectiq_base_url=os.getenv("RMR_PROSPECTIQ_BASE_URL", "").strip().rstrip("/"),
        prospectiq_integration_instance_id=os.getenv("RMR_PROSPECTIQ_INTEGRATION_INSTANCE_ID", "").strip(),
        prospectiq_authorization_code_ttl_seconds=_env_int("RMR_PROSPECTIQ_AUTHORIZATION_CODE_TTL_SECONDS", 60, minimum=1, maximum=60),
        prospectiq_assertion_audience=os.getenv("RMR_PROSPECTIQ_ASSERTION_AUDIENCE", "").strip(),
        prospectiq_assertion_issuer=os.getenv("RMR_PROSPECTIQ_ASSERTION_ISSUER", "").strip(),
    )


settings = get_settings()
