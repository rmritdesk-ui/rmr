from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="strict")


def test_phase0_has_no_google_or_openai_provider_calls():
    worker = source("rmr_platform/piq_worker.py")
    for forbidden in (
        "import httpx",
        "import requests",
        "urllib.request",
        "googleapis.com",
        "places.googleapis.com",
        "api.openai.com",
    ):
        assert forbidden not in worker


def test_live_flags_and_worker_default_off():
    config = source("rmr_platform/config.py")
    env_example = source(".env.example")
    assert '_env_bool("RMR_PIQ_LIVE_DISCOVERY_ENABLED", False)' in config
    assert '_env_bool("RMR_PIQ_LIVE_RESEARCH_ENABLED", False)' in config
    assert '_env_bool("RMR_PIQ_RESEARCH_WEB_SEARCH_ENABLED", False)' in config
    assert '_env_bool("RMR_PIQ_WORKER_ENABLED", False)' in config
    assert "RMR_PIQ_LIVE_DISCOVERY_ENABLED=false" in env_example
    assert "RMR_PIQ_LIVE_RESEARCH_ENABLED=false" in env_example
    assert "RMR_PIQ_WORKER_ENABLED=false" in env_example


def test_demo_discovery_and_adaptive_research_remain_in_place():
    unified = source("rmr_platform/routes/unified.py")
    assert "DEMO_COMPANIES = [" in unified
    assert "for company, signal, score, value in DEMO_COMPANIES:" in unified
    assert '"provider_mode":"demonstration"' in unified
    assert 'source_name="RMR Demonstration Research Provider"' in unified
    assert "row.score=min(100,(row.score or 0)+5)" in unified


def test_move_to_crm_and_prospectiq_attribution_remain_in_place():
    piq = source("rmr_platform/routes/piq.py")
    assert '@router.post("/piq/{opportunity_id}/move-to-crm")' in piq
    assert 'source="ProspectIQ"' in piq
    assert "if opportunity.moved_to_crm:" in piq
    assert 'return {"opportunity": model_dict(opportunity), "created": False}' in piq


def test_worker_lifespan_is_strictly_feature_gated():
    main = source("rmr_platform/main.py")
    assert "piq_worker.start() if settings.piq_worker_enabled else False" in main
    assert "if piq_worker_started:" in main
    assert "piq_worker.stop()" in main
