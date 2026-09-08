from pathlib import Path

import pytest
from pydantic import ValidationError

from rmr_platform.tenant_theme_models import TenantTheme
from rmr_platform.tenant_themes import (
    DEFAULT_THEME,
    FONT_LABELS,
    WORKSPACE_STYLES,
    WORKSPACE_STYLE_KEYS,
    TenantThemeUpdate,
    _contrast_ratio,
    _on_color,
    _safe_download_name,
    _text_color_on_white,
)

ROOT = Path(__file__).resolve().parents[1]


def test_theme_model_is_tenant_primary_key_and_additive_style_field_exists():
    assert TenantTheme.__table__.primary_key.columns.keys() == ["tenant_id"]
    assert {
        "enabled", "workspace_style", "brand_name", "primary_color", "secondary_color",
        "accent_color", "font_family", "logo_filename", "revision"
    }.issubset(TenantTheme.__table__.columns.keys())


def test_four_frozen_workspace_styles_are_exact_and_ordered():
    assert WORKSPACE_STYLE_KEYS == (
        "classic-blue", "metallic-silver", "metallic-gold", "champagne-gold"
    )
    assert set(WORKSPACE_STYLES) == set(WORKSPACE_STYLE_KEYS)
    assert [WORKSPACE_STYLES[key]["short_label"] for key in WORKSPACE_STYLE_KEYS] == [
        "Classic Blue", "Metallic Silver", "Metallic Gold", "Champagne Gold"
    ]


def test_each_workspace_style_has_preview_defaults_and_distinct_tokens():
    signatures = set()
    for key in WORKSPACE_STYLE_KEYS:
        style = WORKSPACE_STYLES[key]
        assert str(style["preview_url"]).endswith(f"/{key}.jpg")
        assert set(style["defaults"]) == {"primary_color", "secondary_color", "accent_color", "font_family"}
        assert {"nav_background", "canvas", "surface", "hero_start", "hero_end", "action", "chart"}.issubset(style["tokens"])
        signatures.add(tuple(sorted(style["tokens"].items())))
    assert len(signatures) == 4


def test_preview_assets_and_visual_source_are_packaged():
    for key in WORKSPACE_STYLE_KEYS:
        path = ROOT / "public" / "assets" / "workspace-themes" / f"{key}.jpg"
        assert path.is_file() and path.stat().st_size > 20_000


@pytest.mark.legacy_packaging
def test_legacy_visual_source_is_retained_locally():
    source = ROOT / "evidence" / "v541-visual-source" / "RMR-Global-v541-four-workspace-themes-source.png"
    assert source.is_file() and source.stat().st_size > 1_000_000


def test_theme_payload_normalizes_safe_colors_brand_and_style():
    payload = TenantThemeUpdate(
        workspace_style="champagne-gold",
        brand_name="  Kerry   Laughlin  Real Estate ",
        primary_color="#173f73",
        secondary_color="#f3eee5",
        accent_color="#b78a5d",
        font_family="georgia",
    )
    assert payload.workspace_style == "champagne-gold"
    assert payload.brand_name == "Kerry Laughlin Real Estate"
    assert payload.primary_color == "#173F73"
    assert payload.secondary_color == "#F3EEE5"
    assert payload.accent_color == "#B78A5D"


def test_payload_rejects_unknown_theme_arbitrary_css_and_fonts():
    with pytest.raises(ValidationError):
        TenantThemeUpdate(workspace_style="custom-neon")
    with pytest.raises(ValidationError):
        TenantThemeUpdate(primary_color="red; background:url(https://bad.example)")
    with pytest.raises(ValidationError):
        TenantThemeUpdate(font_family="url(https://bad.example/font.woff)")


def test_default_and_font_boundaries_are_bounded():
    assert DEFAULT_THEME["enabled"] is False
    assert DEFAULT_THEME["workspace_style"] == "classic-blue"
    assert DEFAULT_THEME["primary_color"] == "#315EFB"
    assert set(FONT_LABELS) == {"system", "arial", "trebuchet", "georgia", "verdana"}


def test_computed_foregrounds_are_readable():
    assert _on_color("#000000") == "#FFFFFF"
    assert _on_color("#FFFFFF") == "#111827"
    adjusted = _text_color_on_white("#F7E7A1")
    assert _contrast_ratio(adjusted, "#FFFFFF") >= 4.5
    assert _text_color_on_white("#173F73") == "#173F73"


def test_frontend_contains_four_preview_cards_and_workspace_class_application():
    manager = (ROOT / "public/pages/theme_manager.js").read_text(encoding="utf-8")
    theme = (ROOT / "public/tenant-theme.js").read_text(encoding="utf-8")
    css = (ROOT / "public/tenant-themes.css").read_text(encoding="utf-8")
    assert "Choose Workspace Style" in manager
    assert "workspace-style-grid" in manager
    assert "STYLE_ORDER = ['classic-blue','metallic-silver','metallic-gold','champagne-gold']" in manager
    for key in WORKSPACE_STYLE_KEYS:
        assert key in manager
        assert f"workspace-style-{key}" in css
    assert "workspace_style:form.workspace_style.value" in manager
    assert "body.dataset.workspaceStyle" in theme
    assert "Powered by RMR Global" in theme
    assert "Reset to RMR Default" in manager
    assert "css_text" not in manager.lower()
    assert "javascript:" not in manager.lower()


def test_existing_branding_controls_remain_available():
    manager = (ROOT / "public/pages/theme_manager.js").read_text(encoding="utf-8")
    for label in ["Tenant brand name", "Approved typography", "Primary brand color", "Soft secondary color", "Accent color", "PNG, JPEG, or WebP"]:
        assert label in manager
    assert "Remove Logo" in manager
    assert "Save & Apply" in manager


def test_public_website_boundary_is_explicit():
    manager = (ROOT / "public/pages/theme_manager.js").read_text(encoding="utf-8")
    assert "does not redesign the client's public website" in manager
    assert "authenticated workspace" in manager


def test_logo_download_name_is_header_safe():
    assert _safe_download_name(r"C:\fakepath\tenant-logo.png", "logo.png") == "tenant-logo.png"
    assert "\r" not in _safe_download_name("bad\r\nname.png", "logo.png")
    assert '"' not in _safe_download_name('bad"name.png', "logo.png")
