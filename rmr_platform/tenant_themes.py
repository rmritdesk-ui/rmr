from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Tenant, User
from .permissions import is_global_admin, require_tenant_access
from .security import current_user, require_request_origin
from .services import audit
from .tenant_theme_models import TenantTheme

router = APIRouter(prefix="/api", tags=["tenant-themes"])

RELEASE = "5.4.1.2-interaction-regression-correction-po1"
WORKSPACE_STYLE_KEYS = (
    "classic-blue",
    "metallic-silver",
    "metallic-gold",
    "champagne-gold",
)
WORKSPACE_STYLES: dict[str, dict[str, object]] = {
    "classic-blue": {
        "label": "RMR Classic Blue",
        "short_label": "Classic Blue",
        "description": "The polished original soft-blue RMR Global workspace.",
        "preview_url": "/static/assets/workspace-themes/classic-blue.jpg",
        "defaults": {
            "primary_color": "#315EFB",
            "secondary_color": "#F4F7FB",
            "accent_color": "#7C5CFC",
            "font_family": "system",
        },
        "tokens": {
            "nav_background": "#07192F",
            "nav_background_end": "#0B2C52",
            "nav_text": "#E8F0FA",
            "nav_muted": "#9DB0C7",
            "nav_active": "#315EFB",
            "nav_active_text": "#FFFFFF",
            "canvas": "#F3F7FB",
            "surface": "#FFFFFF",
            "surface_alt": "#EAF1F8",
            "line": "#D7E2EE",
            "topbar": "#FFFFFF",
            "hero_start": "#FDFEFF",
            "hero_end": "#E4EFFA",
            "hero_text": "#142A43",
            "metallic": "#8DB6DC",
            "action": "#315EFB",
            "action_text": "#FFFFFF",
            "display_accent": "#315EFB",
            "chart": "#315EFB",
            "shadow": "rgba(22,62,102,.12)",
            "pattern_a": "rgba(49,94,251,.08)",
            "pattern_b": "rgba(255,255,255,.88)",
        },
    },
    "metallic-silver": {
        "label": "Metallic Silver",
        "short_label": "Metallic Silver",
        "description": "A refined silver-and-charcoal workspace with cool metallic depth.",
        "preview_url": "/static/assets/workspace-themes/metallic-silver.jpg",
        "defaults": {
            "primary_color": "#2457D6",
            "secondary_color": "#F1F3F6",
            "accent_color": "#8B96A8",
            "font_family": "system",
        },
        "tokens": {
            "nav_background": "#131C2A",
            "nav_background_end": "#1C2737",
            "nav_text": "#E4E9F0",
            "nav_muted": "#A5AFBD",
            "nav_active": "#6E7B8D",
            "nav_active_text": "#FFFFFF",
            "canvas": "#ECEFF3",
            "surface": "#FBFCFD",
            "surface_alt": "#E3E7EC",
            "line": "#C8CED7",
            "topbar": "#F8F9FB",
            "hero_start": "#FFFFFF",
            "hero_end": "#D6DBE3",
            "hero_text": "#142033",
            "metallic": "#AEB7C4",
            "action": "#2457D6",
            "action_text": "#FFFFFF",
            "display_accent": "#2457D6",
            "chart": "#2457D6",
            "shadow": "rgba(28,39,55,.16)",
            "pattern_a": "rgba(255,255,255,.72)",
            "pattern_b": "rgba(116,128,146,.16)",
        },
    },
    "metallic-gold": {
        "label": "Metallic Gold",
        "short_label": "Metallic Gold",
        "description": "A bold, high-contrast metallic-gold workspace with red action accents.",
        "preview_url": "/static/assets/workspace-themes/metallic-gold.jpg",
        "defaults": {
            "primary_color": "#D5A52A",
            "secondary_color": "#F4E4AD",
            "accent_color": "#C71420",
            "font_family": "system",
        },
        "tokens": {
            "nav_background": "#121B27",
            "nav_background_end": "#1D2B3A",
            "nav_text": "#F6E6B8",
            "nav_muted": "#C7B98E",
            "nav_active": "#D5A52A",
            "nav_active_text": "#16202A",
            "canvas": "#E7D29A",
            "surface": "#FFF8E5",
            "surface_alt": "#EAD28A",
            "line": "#C59A2A",
            "topbar": "#F8EBC4",
            "hero_start": "#F7E6B4",
            "hero_end": "#D5A52A",
            "hero_text": "#271D09",
            "metallic": "#E5C25E",
            "action": "#C71420",
            "action_text": "#FFFFFF",
            "display_accent": "#B20E18",
            "chart": "#C71420",
            "shadow": "rgba(89,63,11,.22)",
            "pattern_a": "rgba(255,255,255,.35)",
            "pattern_b": "rgba(170,120,10,.18)",
        },
    },
    "champagne-gold": {
        "label": "Champagne Gold",
        "short_label": "Champagne Gold",
        "description": "The recommended reduced-gold design with calm ivory surfaces and restrained luxury accents.",
        "preview_url": "/static/assets/workspace-themes/champagne-gold.jpg",
        "defaults": {
            "primary_color": "#204D74",
            "secondary_color": "#EFF5FA",
            "accent_color": "#C47A33",
            "font_family": "verdana",
        },
        "tokens": {
            "nav_background": "#102126",
            "nav_background_end": "#163036",
            "nav_text": "#E8CE98",
            "nav_muted": "#A99A7D",
            "nav_active": "#D6B56F",
            "nav_active_text": "#17242A",
            "canvas": "#FAF7F1",
            "surface": "#FFFFFF",
            "surface_alt": "#F6EEDC",
            "line": "#E2D0AD",
            "topbar": "#FFFDF9",
            "hero_start": "#FFFFFF",
            "hero_end": "#F2E3C2",
            "hero_text": "#342717",
            "metallic": "#E7C982",
            "action": "#C81421",
            "action_text": "#FFFFFF",
            "display_accent": "#A70F1B",
            "chart": "#D21B27",
            "shadow": "rgba(80,60,27,.12)",
            "pattern_a": "rgba(218,180,98,.18)",
            "pattern_b": "rgba(255,255,255,.80)",
        },
    },
}
DEFAULT_THEME = {
    "enabled": False,
    "workspace_style": "classic-blue",
    "brand_name": "",
    "primary_color": "#315EFB",
    "secondary_color": "#F4F7FB",
    "accent_color": "#7C5CFC",
    "font_family": "system",
}
FONT_LABELS = {
    "system": "RMR Global System",
    "arial": "Arial",
    "trebuchet": "Trebuchet MS",
    "georgia": "Georgia",
    "verdana": "Verdana",
}
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
LOGO_LIMIT_BYTES = 2 * 1024 * 1024
LOGO_TYPES = {
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
    "image/webp": (".webp", b"RIFF"),
}


class TenantThemeUpdate(BaseModel):
    enabled: bool = True
    workspace_style: Literal[
        "classic-blue",
        "metallic-silver",
        "metallic-gold",
        "champagne-gold",
    ] = "classic-blue"
    brand_name: str = Field(default="", max_length=160)
    primary_color: str = "#315EFB"
    secondary_color: str = "#F4F7FB"
    accent_color: str = "#7C5CFC"
    font_family: Literal["system", "arial", "trebuchet", "georgia", "verdana"] = "system"

    @field_validator("primary_color", "secondary_color", "accent_color")
    @classmethod
    def valid_hex(cls, value: str) -> str:
        value = value.strip().upper()
        if not HEX_RE.fullmatch(value):
            raise ValueError("Use a six-digit color such as #315EFB")
        return value

    @field_validator("brand_name")
    @classmethod
    def clean_brand_name(cls, value: str) -> str:
        return " ".join(value.strip().split())


def _require_theme_write(user: User, tenant_id: str) -> None:
    if is_global_admin(user):
        return
    if user.tenant_id == tenant_id and user.tenant_role == "CLIENT_ADMIN":
        return
    raise HTTPException(
        status_code=403,
        detail="Tenant branding can be changed only by an RMR administrator or this tenant's Client Administrator",
    )


def _theme_dir(tenant_id: str, *, create: bool = False) -> Path:
    path = settings.data_dir / "tenant-themes" / tenant_id
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _theme_row(db: Session, tenant_id: str, create: bool = False) -> TenantTheme | None:
    row = db.get(TenantTheme, tenant_id)
    if row or not create:
        return row
    row = TenantTheme(tenant_id=tenant_id, **DEFAULT_THEME)
    db.add(row)
    db.flush()
    return row


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _relative_luminance(hex_color: str) -> float:
    channels = []
    for value in _rgb(hex_color):
        v = value / 255.0
        channels.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _on_color(background: str) -> str:
    return "#FFFFFF" if _contrast_ratio(background, "#FFFFFF") >= _contrast_ratio(background, "#111827") else "#111827"


def _text_color_on_white(color: str) -> str:
    if _contrast_ratio(color, "#FFFFFF") >= 4.5:
        return color.upper()
    red, green, blue = _rgb(color)
    target = (17, 24, 39)
    for step in range(1, 21):
        factor = step / 20.0
        mixed = tuple(round(channel + (ink - channel) * factor) for channel, ink in zip((red, green, blue), target))
        candidate = "#" + "".join(f"{value:02X}" for value in mixed)
        if _contrast_ratio(candidate, "#FFFFFF") >= 4.5:
            return candidate
    return "#111827"


def _safe_download_name(value: str, fallback: str) -> str:
    raw = Path((value or fallback).replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", raw).strip(" .")
    return (cleaned or fallback)[:120]


def _workspace_style_payload(style_key: str) -> dict[str, object]:
    style = WORKSPACE_STYLES.get(style_key) or WORKSPACE_STYLES["classic-blue"]
    return {
        "value": style_key if style_key in WORKSPACE_STYLES else "classic-blue",
        "label": style["label"],
        "short_label": style["short_label"],
        "description": style["description"],
        "preview_url": style["preview_url"],
        "defaults": dict(style["defaults"]),
        "tokens": dict(style["tokens"]),
    }


def _serialize(tenant: Tenant, row: TenantTheme | None, can_manage: bool) -> dict[str, object]:
    values = dict(DEFAULT_THEME)
    if row:
        values.update(
            {
                "enabled": row.enabled,
                "workspace_style": row.workspace_style or "classic-blue",
                "brand_name": row.brand_name,
                "primary_color": row.primary_color,
                "secondary_color": row.secondary_color,
                "accent_color": row.accent_color,
                "font_family": row.font_family,
            }
        )
    style_key = str(values.get("workspace_style") or "classic-blue")
    if style_key not in WORKSPACE_STYLES:
        style_key = "classic-blue"
        values["workspace_style"] = style_key
    style = WORKSPACE_STYLES[style_key]
    brand_name = str(values["brand_name"] or tenant.name)
    has_logo = bool(row and row.logo_filename and (_theme_dir(tenant.id) / row.logo_filename).is_file())
    revision = row.revision if row else 0
    return {
        "release": RELEASE,
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "theme": {
            **values,
            "brand_name": brand_name,
            "workspace_style_label": style["label"],
            "workspace_tokens": dict(style["tokens"]),
            "has_logo": has_logo,
            "logo_url": f"/api/tenants/{tenant.id}/theme/logo?v={revision}" if has_logo else "",
            "on_primary": _on_color(str(values["primary_color"])),
            "on_secondary": _on_color(str(values["secondary_color"])),
            "on_accent": _on_color(str(values["accent_color"])),
            "primary_text": _text_color_on_white(str(values["primary_color"])),
            "accent_text": _text_color_on_white(str(values["accent_color"])),
            "revision": revision,
            "updated_at": row.updated_at.isoformat() if row else None,
        },
        "defaults": {**DEFAULT_THEME, "brand_name": tenant.name},
        "workspace_styles": [_workspace_style_payload(key) for key in WORKSPACE_STYLE_KEYS],
        "allowed_fonts": [{"value": key, "label": label} for key, label in FONT_LABELS.items()],
        "can_manage": can_manage,
        "scope": "authenticated_application_only",
    }


def _get_tenant(db: Session, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client tenant not found")
    return tenant


@router.get("/tenants/{tenant_id}/theme")
def get_tenant_theme(
    tenant_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_tenant_access(user, tenant_id)
    tenant = _get_tenant(db, tenant_id)
    can_manage = is_global_admin(user) or (user.tenant_id == tenant_id and user.tenant_role == "CLIENT_ADMIN")
    return _serialize(tenant, _theme_row(db, tenant_id), can_manage)


@router.patch("/tenants/{tenant_id}/theme")
def update_tenant_theme(
    tenant_id: str,
    payload: TenantThemeUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    _require_theme_write(user, tenant_id)
    tenant = _get_tenant(db, tenant_id)
    row = _theme_row(db, tenant_id, create=True)
    assert row is not None
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    row.updated_by_user_id = user.id
    row.revision = max(row.revision, 0) + 1
    row.updated_at = datetime.now(timezone.utc)
    audit(
        db,
        user,
        "tenant.theme.updated",
        tenant_id=tenant_id,
        entity_type="tenant_theme",
        entity_id=tenant_id,
        data={
            "enabled": row.enabled,
            "workspace_style": row.workspace_style,
            "brand_name": row.brand_name,
            "primary_color": row.primary_color,
            "secondary_color": row.secondary_color,
            "accent_color": row.accent_color,
            "font_family": row.font_family,
            "revision": row.revision,
        },
    )
    db.commit()
    return _serialize(tenant, row, True)


@router.post("/tenants/{tenant_id}/theme/logo")
async def upload_tenant_logo(
    tenant_id: str,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    _require_theme_write(user, tenant_id)
    tenant = _get_tenant(db, tenant_id)
    content_type = (file.content_type or "").lower()
    if content_type not in LOGO_TYPES:
        raise HTTPException(status_code=415, detail="Logo must be a PNG, JPEG, or WebP image")
    data = await file.read(LOGO_LIMIT_BYTES + 1)
    if len(data) > LOGO_LIMIT_BYTES:
        raise HTTPException(status_code=413, detail="Logo must be 2 MB or smaller")
    extension, signature = LOGO_TYPES[content_type]
    if not data.startswith(signature) or (content_type == "image/webp" and data[8:12] != b"WEBP"):
        raise HTTPException(status_code=422, detail="The uploaded file does not match the selected image format")
    row = _theme_row(db, tenant_id, create=True)
    assert row is not None
    folder = _theme_dir(tenant_id, create=True)
    filename = f"logo{extension}"
    destination = folder / filename
    temporary = folder / f".{filename}.{secrets.token_hex(6)}.tmp"
    temporary.write_bytes(data)
    temporary.replace(destination)
    for old in folder.glob("logo.*"):
        if old != destination:
            old.unlink(missing_ok=True)
    row.logo_filename = filename
    row.logo_content_type = content_type
    row.logo_original_name = _safe_download_name(file.filename or filename, filename)
    row.enabled = True
    row.updated_by_user_id = user.id
    row.revision = max(row.revision, 0) + 1
    row.updated_at = datetime.now(timezone.utc)
    audit(
        db,
        user,
        "tenant.theme.logo_uploaded",
        tenant_id=tenant_id,
        entity_type="tenant_theme",
        entity_id=tenant_id,
        data={"content_type": content_type, "bytes": len(data), "revision": row.revision},
    )
    db.commit()
    return _serialize(tenant, row, True)


@router.get("/tenants/{tenant_id}/theme/logo")
def tenant_logo(
    tenant_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_tenant_access(user, tenant_id)
    _get_tenant(db, tenant_id)
    row = _theme_row(db, tenant_id)
    path = _theme_dir(tenant_id) / row.logo_filename if row and row.logo_filename else None
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Tenant logo not found")
    return FileResponse(
        path,
        media_type=row.logo_content_type or "application/octet-stream",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{_safe_download_name(row.logo_original_name, path.name)}"',
        },
    )


@router.delete("/tenants/{tenant_id}/theme/logo")
def delete_tenant_logo(
    tenant_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    _require_theme_write(user, tenant_id)
    tenant = _get_tenant(db, tenant_id)
    row = _theme_row(db, tenant_id, create=True)
    assert row is not None
    if row.logo_filename:
        (_theme_dir(tenant_id) / row.logo_filename).unlink(missing_ok=True)
    row.logo_filename = ""
    row.logo_content_type = ""
    row.logo_original_name = ""
    row.updated_by_user_id = user.id
    row.revision = max(row.revision, 0) + 1
    row.updated_at = datetime.now(timezone.utc)
    audit(
        db,
        user,
        "tenant.theme.logo_removed",
        tenant_id=tenant_id,
        entity_type="tenant_theme",
        entity_id=tenant_id,
        data={"revision": row.revision},
    )
    db.commit()
    return _serialize(tenant, row, True)


@router.post("/tenants/{tenant_id}/theme/reset")
def reset_tenant_theme(
    tenant_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    _require_theme_write(user, tenant_id)
    tenant = _get_tenant(db, tenant_id)
    row = _theme_row(db, tenant_id, create=True)
    assert row is not None
    if row.logo_filename:
        (_theme_dir(tenant_id) / row.logo_filename).unlink(missing_ok=True)
    for field, value in DEFAULT_THEME.items():
        setattr(row, field, value)
    row.logo_filename = ""
    row.logo_content_type = ""
    row.logo_original_name = ""
    row.updated_by_user_id = user.id
    row.revision = max(row.revision, 0) + 1
    row.updated_at = datetime.now(timezone.utc)
    audit(
        db,
        user,
        "tenant.theme.reset",
        tenant_id=tenant_id,
        entity_type="tenant_theme",
        entity_id=tenant_id,
        data={"workspace_style": row.workspace_style, "revision": row.revision},
    )
    db.commit()
    return _serialize(tenant, row, True)


def seed_tenant_themes(db: Session) -> None:
    """Create distinct Product Owner themes without touching existing rows."""
    demo_themes = {
        "kerry-real-estate": {
            "enabled": True,
            "workspace_style": "classic-blue",
            "brand_name": "Kerry Laughlin Real Estate",
            "primary_color": "#315EFB",
            "secondary_color": "#F4F7FB",
            "accent_color": "#7C5CFC",
            "font_family": "system",
        },
        "cactus-air-filters": {
            "enabled": True,
            "workspace_style": "metallic-silver",
            "brand_name": "Cactus Air Filters",
            "primary_color": "#2457D6",
            "secondary_color": "#F1F3F6",
            "accent_color": "#8B96A8",
            "font_family": "system",
        },
    }
    for slug, values in demo_themes.items():
        tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
        if tenant and not db.get(TenantTheme, tenant.id):
            db.add(TenantTheme(tenant_id=tenant.id, **values))
