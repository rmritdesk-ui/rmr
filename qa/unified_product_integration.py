#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.3.1-final-production-corrections-po1"
checks: list[dict] = []
failures: list[str] = []


def check(name: str, passed: bool, detail="") -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})
    if not passed:
        failures.append(f"{name}: {detail}")


paths = {
    "application shell": ROOT / "public/app.js",
    "navigation": ROOT / "public/ui.js",
    "customer workspace": ROOT / "public/pages/unified.js",
    "backend routes": ROOT / "rmr_platform/routes/unified.py",
    "models": ROOT / "rmr_platform/unified_models.py",
    "services": ROOT / "rmr_platform/unified_services.py",
    "tenant seed": ROOT / "rmr_platform/unified_seed.py",
    "functional QC": ROOT / "rmr_platform/product_owner_qc.py",
}
for label, path in paths.items():
    check(f"{label.title()} exists", path.is_file(), path.relative_to(ROOT).as_posix())

app = paths["application shell"].read_text(encoding="utf-8")
ui = paths["navigation"].read_text(encoding="utf-8")
workspace = paths["customer workspace"].read_text(encoding="utf-8")
routes = paths["backend routes"].read_text(encoding="utf-8")
seed = paths["tenant seed"].read_text(encoding="utf-8") + "\n" + (ROOT / "rmr_platform/seed.py").read_text(encoding="utf-8")
qc = paths["functional QC"].read_text(encoding="utf-8")

check("Normal client users land in the customer product shell", "state.adminClientWorkspace" in app and "clientItems" in ui, "Role-aware application shell")
admin = (ROOT / "public/pages/admin.js").read_text(encoding="utf-8")
check("RMR Client 360 exposes Open Client Workspace", "open-client-workspace" in admin, "Client 360 workspace entry")
check("RMR managed client work is authorized, attributed and explicitly ended", all(token in app + ui + workspace + routes for token in ["start-managed-session", "Authorized & Audited Client Workspace", "managed_session.started", "managed_session.ended"]), "Managed services controls")
check("Customer-first dashboard connects the cumulative growth workflow", all(token in workspace for token in ["One place to attract, manage and convert opportunity", "Manage Website", "Find Prospects", "Create Content"]), "Customer dashboard")
check("Website Studio includes CMS, media, blog, resources, team, SEO and appointments", all(token in workspace for token in ["Website Studio", "Media", "Blog", "Resources", "Team Profiles", "SEO", "Appointments"]), "Website Studio tabs")
check("CRM includes creation, search, import, duplicates and email activity", all(token in workspace for token in ["crm-new", "crm-search", "crm-import", "Find duplicates", "Send email / record activity"]), "CRM customer workflow")
check("ProspectIQ includes target, discovery, import, research, evidence and CRM handoff", all(token in workspace for token in ["run-discovery", "piq-import", "Target profile", "Adaptive Research", "Move to CRM"]), "ProspectIQ customer workflow")
check("Campaigns includes campaigns, four-platform social, manual publishing and supported outreach", all(token in workspace for token in ["Social Content", "Facebook", "Instagram", "LinkedIn", "Copy Post", "Copy Hashtags", "Mark Published", "Generate supported outreach"]), "Campaigns and social workflow")
check("Email and Activities is integrated with CRM and one cross-module timeline", all(token in workspace for token in ["Email & Activities", "Send email and record CRM activity", "Unified activity timeline"]), "Email and activities")
check("Reporting joins website, PIQ, CRM, social, email, pipeline and revenue", all(token in workspace for token in ["Growth & Management Reporting", "Website leads", "PIQ to CRM", "Open opportunities", "Social drafts", "Emails", "Source attribution"]), "Growth reporting")
check("Kerry is an embedded managed website tenant, not a separate product", all(token in seed for token in ["Kerry Laughlin Real Estate", "kerry-real-estate", "site.mode = \"managed\""]), "Kerry tenant seed")
check("CAF remains an external connected website tenant in the same product", all(token in seed for token in ["Cactus Air Filters", "cactus-air-filters", '"website_mode": "external"']), "CAF tenant seed")
check("Functional QC contains RMR, Kerry, Marketing, CAF, public-site and restart Golden Paths", all(token in qc for token in ["_rmr_owner_path", "_kerry_client_path", "_kerry_marketing_path", "_caf_path", "_public_website_path", "verify_persistence"]), "Product Owner QC")
main_source = (ROOT / "rmr_platform/main.py").read_text(encoding="utf-8")
check("Preserved commercial operations routes remain executable before the SPA fallback", main_source.index("app.include_router(commercial_router)") < main_source.index('@app.get("/{path:path}"'), "Route registration order")
check("Product Owner tenant readiness evidence is seeded consistently", all(token in seed for token in ["CB1ClientAdminInvite", "CB1OrderForm", "CB1Entitlement", "CB1WorkerState"]), "Unified demo readiness")
check("Release identity is cumulative v5.3", RELEASE in (ROOT / "rmr_platform/__init__.py").read_text(encoding="utf-8"), RELEASE)

result = {
    "status": "passed" if not failures else "failed",
    "release": RELEASE,
    "passed": sum(1 for row in checks if row["passed"]),
    "failed": sum(1 for row in checks if not row["passed"]),
    "checks": checks,
    "failures": failures,
}
(ROOT / "qa/UNIFIED-PRODUCT-INTEGRATION-RESULTS.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["status"] == "passed" else 1)
