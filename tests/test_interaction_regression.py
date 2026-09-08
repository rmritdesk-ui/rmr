from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def test_actionable_tiles_use_capture_phase_route_delegation():
    source = text("public/ui.js")
    assert "[data-route],[data-v53-route]" in source
    assert "appRoot._rmrRouteDelegate" in source
    assert "addEventListener('click', routeDelegate, true)" in source
    assert "stopImmediatePropagation" in source
    assert "control.disabled" in source


def test_forecasting_and_preserved_modules_use_operational_fallback():
    source = text("public/pages/unified.js")
    assert "['forecast','training','organization','solutions'].includes(route)" in source
    assert "ctx.renderClientOperational(route, readOnly)" in source
    assert "Unsupported client workspace route" in source


def test_actionable_tile_destinations_remain_existing_routes():
    unified = text("public/pages/unified.js")
    v53 = text("public/pages/v53_client_experience.js")
    for route in ["website", "crm", "piq", "campaigns", "email", "forecast"]:
        assert f'data-route="{route}"' in unified or f"'{route}'" in unified
        assert f"'{route}'" in v53


def test_theme_rendering_is_preserved_and_interactions_are_not_blocked():
    css = text("public/tenant-themes.css")
    for key in ["classic-blue", "metallic-silver", "metallic-gold", "champagne-gold"]:
        assert f".workspace-style-{key}.tenant-theme-active .main-area" in css
    assert "v5.4.1.2 interaction-preservation guard" in css
    assert ".tenant-theme-active button[data-route]" in css
    assert "pointer-events:auto" in css
