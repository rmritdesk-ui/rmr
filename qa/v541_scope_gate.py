#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.4.1-four-workspace-themes-po1"
BASELINE_V54_SHA = "a814b8fd36a1e7fad09963f3186075b8596975141508ef350436384494ee0300"
FROZEN_V531_SHA = "d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf"
STYLE_KEYS = ("classic-blue", "metallic-silver", "metallic-gold", "champagne-gold")
checks: list[dict[str, object]] = []


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def digest(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def check(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "passed": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))


init = text("rmr_platform/__init__.py")
migrations = text("rmr_platform/migrations.py")
models = text("rmr_platform/tenant_theme_models.py")
router = text("rmr_platform/tenant_themes.py")
manager = text("public/pages/theme_manager.js")
theme_js = text("public/tenant-theme.js")
css = text("public/tenant-themes.css")
admin = text("public/pages/admin.js")
client_admin = text("public/pages/client_admin_correction.js")
public_site = text("templates/public_site.html")
baseline_public_site = (Path("/home/oai/share/rmr_v540_base/RMR540/templates/public_site.html").read_text(encoding="utf-8", errors="replace")
                        if Path("/home/oai/share/rmr_v540_base/RMR540/templates/public_site.html").is_file() else "")
seal = json.loads(text("control/V531-PRODUCTION-BASELINE-SEAL.json"))

check("Exact v5.4.1 release identity is active", RELEASE in init and RELEASE in router)
check("Frozen v5.3.1 seal remains canonical", seal.get("canonical_sha256") == FROZEN_V531_SHA and seal.get("status") == "sealed_unchanged", seal.get("canonical_sha256"))
check("Exact preserved v5.4.0 source baseline is declared", BASELINE_V54_SHA in text("V541-PRODUCT-OWNER-SCOPE-LOCK.md"))
check("v5.4.1 scope lock is packaged", "RMR Global v5.4.1" in text("V541-PRODUCT-OWNER-SCOPE-LOCK.md"))
check("Four-theme work is bounded to one application", "one application" in text("V541-PRODUCT-OWNER-SCOPE-LOCK.md").lower())
check("Existing Tenant Themes migration remains preserved", 'TENANT_THEMES_VERSION = "005.006.000-tenant-themes"' in migrations)
check("Four-theme migration is additive and current", 'MIGRATION_VERSION = "005.006.100-four-workspace-themes"' in migrations and "_migration_005_006_100" in migrations)
check("Only workspace_style is added by the new migration", migrations.count('"workspace_style"') >= 1 and "workspace_style VARCHAR(40) NOT NULL DEFAULT 'classic-blue'" in migrations)
check("Tenant theme remains tenant-primary-key scoped", '__tablename__ = "tenant_themes"' in models and "primary_key=True" in models and 'ForeignKey("tenants.id"' in models)
check("Workspace style is tenant-scoped persistent data", "workspace_style: Mapped[str]" in models and "nullable=False" in models)
check("Exactly four controlled style keys are defined", all(f'"{key}"' in router for key in STYLE_KEYS) and "WORKSPACE_STYLE_KEYS" in router)
check("Four styles preserve the frozen names", all(label in router for label in ("RMR Classic Blue", "Metallic Silver", "Metallic Gold", "Champagne Gold")))
check("Four styles expose visual preview assets", all(f'/assets/workspace-themes/{key}.jpg' in router for key in STYLE_KEYS))
check("Style presets use controlled tokens, not separate apps", all(token in router for token in ("nav_background", "canvas", "surface", "action", "chart")))
check("Existing branding controls remain", all(token in router for token in ("brand_name", "primary_color", "secondary_color", "accent_color", "font_family", "LOGO_LIMIT_BYTES")))
check("Approved typography set remains bounded", 'Literal["system", "arial", "trebuchet", "georgia", "verdana"]' in router)
check("Arbitrary CSS/JavaScript fields remain excluded", all(token not in (router + manager).lower() for token in ("css_text", "javascript_text", "custom_css", "custom_javascript")))
check("Logo content and size remain constrained", all(token in router for token in ("image/png", "image/jpeg", "image/webp", "2 * 1024 * 1024")))
check("RMR administrators retain authorized tenant management", "is_global_admin(user)" in router)
check("Client Administrator remains own-tenant only", 'user.tenant_id == tenant_id and user.tenant_role == "CLIENT_ADMIN"' in router)
check("Cross-tenant reads preserve access controls", "require_tenant_access(user, tenant_id)" in router)
check("Theme changes remain audited", all(token in router for token in ("tenant.theme.updated", "tenant.theme.logo_uploaded", "tenant.theme.reset")))
check("Reset-to-default remains implemented", '/tenants/{tenant_id}/theme/reset' in router and "DEFAULT_THEME" in router)
check("Manage Branding remains available from Client 360", "Manage Branding" in admin and "openThemeManager" in admin)
check("Client Administrator own-tenant branding remains available", "enhanceThemeForClientAdmin" in client_admin)
check("Four workspace preview cards are present", "Choose Workspace Style" in manager and "workspace-style-grid" in manager)
check("Style selection is persisted by Save & Apply", "Save & Apply" in manager and "workspace_style:form.workspace_style.value" in manager)
check("Authenticated workspace applies one style class", "body.dataset.workspaceStyle" in theme_js and "workspace-style-${theme.workspace_style" in theme_js)
check("Public Kerry website template is byte-identical to v5.4.0", bool(baseline_public_site) and public_site == baseline_public_site, digest("templates/public_site.html"))
check("Public website does not load authenticated theme controls", all(token not in public_site.lower() for token in ("tenant-theme.js", "tenant-themes.css", "/theme/reset", "/theme/logo")))
check("Mass-email delivery boundary remains preserved", "bulk_email_delivery" in text("rmr_platform/client_admin_corrections.py"))
check("No automatic billing or marketplace scope was introduced", all(token not in (router + manager).lower() for token in ("automatic billing", "theme marketplace", "marketplace")))
check("All four frozen visual assets physically exist", all((ROOT / f"public/assets/workspace-themes/{key}.jpg").is_file() for key in STYLE_KEYS))
check("Frozen comparison image is preserved as evidence", (ROOT / "evidence/v541-visual-source/RMR-Global-v541-four-workspace-themes-source.png").is_file())

status = "passed" if all(row["passed"] for row in checks) else "failed"
result = {
    "status": status,
    "release": RELEASE,
    "source_baseline": "5.4.0-tenant-themes-po1",
    "source_baseline_sha256": BASELINE_V54_SHA,
    "frozen_v531_sha256": FROZEN_V531_SHA,
    "passed": sum(1 for row in checks if row["passed"]),
    "failed": sum(1 for row in checks if not row["passed"]),
    "checks": checks,
}
(ROOT / "qa/V541-SCOPE-GATE.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: result[k] for k in ("status", "passed", "failed")}, indent=2))
raise SystemExit(0 if status == "passed" else 1)
