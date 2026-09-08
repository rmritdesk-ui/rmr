#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.4.0-tenant-themes-po1"
BASELINE_SHA = "d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf"
checks: list[dict[str, object]] = []

def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")

def check(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "passed": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")

init = text("rmr_platform/__init__.py")
main = text("rmr_platform/main.py")
migrations = text("rmr_platform/migrations.py")
models = text("rmr_platform/tenant_theme_models.py")
router = text("rmr_platform/tenant_themes.py")
app = text("public/app.js")
manager = text("public/pages/theme_manager.js")
theme_js = text("public/tenant-theme.js")
css = text("public/tenant-themes.css")
index = text("public/index.html")
admin = text("public/pages/admin.js")
client_admin = text("public/pages/client_admin_correction.js")
scope = text("V54-PRODUCT-OWNER-SCOPE-LOCK.md")
seal = json.loads(text("control/V531-PRODUCTION-BASELINE-SEAL.json"))

check("Exact v5.4 release identity is active", RELEASE in init and RELEASE in router)
check("Canonical v5.3.1 baseline is sealed unchanged", seal.get("canonical_sha256") == BASELINE_SHA and seal.get("status") == "sealed_unchanged", seal)
check("v5.4 scope lock is packaged", "RMR Global v5.4" in scope and "Tenant Themes" in scope)
check("Tenant themes are additive and authenticated-app only", "authenticated rmr global application workspace only" in scope.lower() and "website boundary" in scope.lower())
check("One additive tenant-theme migration is current", 'MIGRATION_VERSION = "005.006.000-tenant-themes"' in migrations and "_migration_005_006_000" in migrations)
check("Existing cumulative migration remains immediately prior", 'CUMULATIVE_PRODUCT_VERSION = "005.005.000-cumulative-product-repair"' in migrations)
check("Tenant theme model is tenant-primary-key scoped", '__tablename__ = "tenant_themes"' in models and "primary_key=True" in models and 'ForeignKey("tenants.id"' in models)
check("Theme router is registered", "tenant_themes_router" in main and "app.include_router(router)" in main)
check("Theme settings are bounded", all(token in router for token in ("primary_color", "secondary_color", "accent_color", "font_family", "LOGO_LIMIT_BYTES")))
check("Arbitrary fonts are excluded", 'Literal["system", "arial", "trebuchet", "georgia", "verdana"]' in router)
check("Arbitrary CSS and JavaScript fields are absent", "css_text" not in router.lower() + manager.lower() and "javascript" not in manager.lower())
check("Logo types and size are constrained", all(token in router for token in ("image/png", "image/jpeg", "image/webp", "2 * 1024 * 1024")))
check("RMR administrators may manage authorized tenants", "is_global_admin(user)" in router)
check("Client Administrator write access is own-tenant only", 'user.tenant_id == tenant_id and user.tenant_role == "CLIENT_ADMIN"' in router)
check("Cross-tenant reads use preserved tenant access control", "require_tenant_access(user, tenant_id)" in router)
check("Theme changes are audited", all(token in router for token in ("tenant.theme.updated", "tenant.theme.logo_uploaded", "tenant.theme.reset")))
check("Reset-to-default is implemented", '/tenants/{tenant_id}/theme/reset' in router and "DEFAULT_THEME" in router)
check("Kerry and CAF have distinct isolated PO demo themes", "#173F73" in router and "#146B52" in router)
check("Theme frontend loads per selected tenant", "/api/tenants/${state.selectedTenantId}/theme" in theme_js)
check("Theme applies only in client workspace", "!isGlobalAdmin() || state.adminClientWorkspace" in theme_js)
check("RMR Global identity remains visible", "Powered by RMR Global" in theme_js and "Powered by RMR Global" in manager)
check("Live preview is provided", "theme-live-preview" in manager and "Preview only" in manager)
check("Save/apply and reset controls are provided", "Save & Apply" in manager and "Reset to RMR Default" in manager)
check("RMR Client 360 exposes tenant branding management", "Manage Branding" in admin and "openThemeManager" in admin)
check("Client Administrator own-tenant settings expose branding", "enhanceThemeForClientAdmin" in client_admin)
check("Theme stylesheet is packaged and wired", "tenant-themes.css" in index and len(css) > 4000)
check("Existing Client Administrator route family remains intact", all(token in app for token in ("home", "crm", "forecast", "reports", "piq", "solutions", "campaigns", "email", "website", "organization", "training")))
check("Public website template was not given tenant-theme controls", all(token not in text("templates/public_site.html").lower() for token in ("tenant-theme.js", "tenant-themes.css", "/theme/reset", "/theme/logo")))
check("Mass-email boundary remains preserved", "bulk_email_delivery" in text("rmr_platform/client_admin_corrections.py"))
check("No automatic billing is introduced", "explicit exclusions" in scope.lower() and "automatic billing" in scope.lower())

status = "passed" if all(row["passed"] for row in checks) else "failed"
result = {"status": status, "release": RELEASE, "passed": sum(1 for r in checks if r["passed"]), "failed": sum(1 for r in checks if not r["passed"]), "checks": checks}
out = ROOT / "qa" / "V54-SCOPE-GATE.json"
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: result[k] for k in ("status", "passed", "failed")}, indent=2))
raise SystemExit(0 if status == "passed" else 1)
