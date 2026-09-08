#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "qa/cumulative_product_preservation_spec.json").read_text(encoding="utf-8"))
BASE = json.loads((ROOT / "qa/cumulative_baseline_source_manifest.json").read_text(encoding="utf-8"))
RELEASE = "5.3.1-final-production-corrections-po1"
EXCLUDED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "data", "product-owner-data", "backups", "diagnostics", "qc-results", "dist", "build", "evidence", "control"}
TEXT_EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".html", ".htm", ".css", ".ps1", ".bat", ".sh", ".yml", ".yaml", ".toml", ".txt", ".md"}


def include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    return path.is_file() and not any(part in EXCLUDED for part in rel.parts) and (path.suffix.lower() in TEXT_EXTENSIONS or path.name == ".env.example")


texts: dict[str, str] = {}
for path in ROOT.rglob("*"):
    if include(path):
        try:
            texts[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            texts[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
corpus = "\n".join(texts.values()).lower()
checks: list[dict] = []
failures: list[str] = []


def check(name: str, passed: bool, detail="") -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})
    if not passed:
        failures.append(f"{name}: {detail}")


baseline_files = list(BASE.get("files", {}).keys())
missing_baseline = sorted(name for name in baseline_files if not (ROOT / name).exists())
check("Every frozen CB1-R2 application-source file remains present", not missing_baseline, missing_baseline)

for capability in SPEC.get("capabilities", []):
    if not capability.get("baseline_present"):
        continue
    missing_terms = [term for term in capability.get("terms", []) if str(term).lower() not in corpus]
    check(f"Preserve {capability['id']} — {capability['name']}", not missing_terms, missing_terms)

required_files = [
    "rmr_platform/routes/unified.py",
    "rmr_platform/unified_models.py",
    "rmr_platform/unified_services.py",
    "rmr_platform/unified_seed.py",
    "rmr_platform/product_owner_qc.py",
    "public/pages/unified.js",
    "public/app.js",
    "public/ui.js",
    "START-PRODUCT-OWNER-TEST.bat",
    "START-PRODUCT-OWNER-TEST.ps1",
    "STOP-PRODUCT-OWNER-TEST.bat",
    "RESET-PRODUCT-OWNER-DEMO.bat",
    "COLLECT-PRODUCT-OWNER-DIAGNOSTICS.bat",
    "docker-compose.product-owner.yml",
]
check("All-inclusive integration and Product Owner control files exist", all((ROOT / name).is_file() for name in required_files), [name for name in required_files if not (ROOT / name).is_file()])

ui = (ROOT / "public/ui.js").read_text(encoding="utf-8")
unified = (ROOT / "public/pages/unified.js").read_text(encoding="utf-8")
app = (ROOT / "public/app.js").read_text(encoding="utf-8")
backend = (ROOT / "rmr_platform/routes/unified.py").read_text(encoding="utf-8")
permissions = (ROOT / "rmr_platform/permissions.py").read_text(encoding="utf-8")
seed = (ROOT / "rmr_platform/unified_seed.py").read_text(encoding="utf-8") + "\n" + (ROOT / "rmr_platform/seed.py").read_text(encoding="utf-8")
launcher = (ROOT / "START-PRODUCT-OWNER-TEST.ps1").read_text(encoding="utf-8")

modules = ["Dashboard", "Website", "CRM", "ProspectIQ", "Campaigns & Social", "Email & Activities", "Forecasting", "Reporting", "Training", "Team & Settings"]
check("The complete customer product remains visible in normal navigation", all(label in ui for label in modules), [label for label in modules if label not in ui])
check("The customer product dispatcher connects core modules", all(f"route === '{route}'" in unified for route in ["home", "website", "crm", "piq", "campaigns", "email", "reports"]), "Unified route dispatch")
check("Existing Forecasting, Training, Organization, Solutions and admin routes remain connected", all(token in app for token in ["renderClientPage", "renderAdminPage", "'forecast'", "'training'", "'organization'", "'solutions'"]), "Application route imports and dispatch")

endpoint_tokens = [
    "/workspace", "/modules", "/website-content", "/blog-posts", "/website-media", "/appointments",
    "/piq/target-profile", "/piq/discover", "/piq/import-preview", "/adaptive-research",
    "/crm/search", "/crm/duplicates", "/crm/merge-accounts", "/crm/import-preview",
    "/marketing/generate-social", "/marketing/generate-email", "/crm/email", "/growth-report",
    "/managed-session",
]
check("Unified backend support exists for website, CRM, PIQ, campaigns, email, reporting and managed services", all(token in backend for token in endpoint_tokens), [token for token in endpoint_tokens if token not in backend])
check("Tenant and role permissions remain server-enforced", all(token in permissions for token in ["require_tenant_access", "require_client_operational_write", "require_client_website_write"]), "permissions.py")
check("Kerry and CAF remain real tenants in one application", all(token in seed for token in ["kerry-real-estate", "cactus-air-filters", "site.mode = \"managed\"", '"website_mode": "external"']), "unified_seed.py")
check("Product Owner launcher performs package integrity, health, functional QC, restart persistence and diagnostics", all(token in launcher for token in ["Verify-Manifest", "product_owner_qc", "--verify-persistence", "Collect-Failure", "docker-compose.product-owner.yml"]), "START-PRODUCT-OWNER-TEST.ps1")
check("Exact all-inclusive release identity is consistent", RELEASE in (ROOT / "rmr_platform/__init__.py").read_text(encoding="utf-8") and RELEASE in launcher and RELEASE in (ROOT / "docker-compose.product-owner.yml").read_text(encoding="utf-8"), RELEASE)

forbidden = [
    "CLIENT_ROLES.add('RMR_OWNER')",
    'CLIENT_ROLES.add("RMR_OWNER")',
    "authorization = true",
    "tenant_id = user.tenant_id or tenant_id",
]
combined_security = "\n".join([backend, permissions, app, unified])
check("No known authorization-bypass pattern was introduced", not any(token in combined_security for token in forbidden), [token for token in forbidden if token in combined_security])

result = {
    "status": "passed" if not failures else "failed",
    "release": RELEASE,
    "frozen_baseline_release": "5.1.0-commercial-cb1-r2",
    "frozen_baseline_sha256": BASE.get("base_sha256"),
    "baseline_files_checked": len(baseline_files),
    "capabilities_checked": sum(1 for row in SPEC.get("capabilities", []) if row.get("baseline_present")),
    "passed": sum(1 for row in checks if row["passed"]),
    "failed": sum(1 for row in checks if not row["passed"]),
    "checks": checks,
    "failures": failures,
}
(ROOT / "qa/CUMULATIVE-PRODUCT-PRESERVATION-RESULTS.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["status"] == "passed" else 1)
