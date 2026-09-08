from pathlib import Path
from PIL import Image
from rmr_platform.tenant_themes import WORKSPACE_STYLES, WORKSPACE_STYLE_KEYS

ROOT = Path(__file__).resolve().parents[1]

def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")

def test_preview_urls_use_mounted_static_path():
    for key in WORKSPACE_STYLE_KEYS:
        assert WORKSPACE_STYLES[key]["preview_url"] == f"/static/assets/workspace-themes/{key}.jpg"

def test_rmr_owner_client_360_is_tenant_theme_context():
    source = text("public/tenant-theme.js")
    assert "ADMIN_TENANT_THEME_ROUTES = new Set(['client-360'])" in source
    assert "inTenantScopedAdminView" in source
    assert "inClientWorkspace || inTenantScopedAdminView" in source

def test_route_changes_reapply_or_reload_selected_tenant_theme():
    source = text("public/app.js")
    assert "routeTenantChanged" in source
    assert "await loadTenantTheme()" in source
    assert "applyTenantTheme();" in source

def test_shared_client_360_surfaces_are_theme_driven():
    css = text("public/tenant-themes.css")
    for selector in [".tenant-theme-active .main-area", ".tenant-theme-active .page-head h1", ".tenant-theme-active .action-card", ".tenant-theme-active .list-item", ".tenant-theme-active .hero-card", ".tenant-theme-active .kpi", ".tenant-theme-active .table-card"]:
        assert selector in css

def test_four_presets_have_materially_distinct_rendering_rules():
    css = text("public/tenant-themes.css")
    for key in WORKSPACE_STYLE_KEYS:
        assert f".workspace-style-{key}.tenant-theme-active .main-area" in css
    for marker in ["#E1E5EA", "#D3A83C", "#F2E6CE", "#D51C29"]:
        assert marker in css

def test_preview_assets_are_individual_landscape_cards():
    for key in WORKSPACE_STYLE_KEYS:
        with Image.open(ROOT / "public/assets/workspace-themes" / f"{key}.jpg") as image:
            assert image.size == (640, 360)
