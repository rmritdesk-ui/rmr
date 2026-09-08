#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORT = Path(os.getenv("RMR_V51_STATIC_REPORT", ROOT / "qa" / "V51RC3-STATIC-AUDIT-RESULTS.json"))
checks: list[dict[str, object]] = []


def record(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        raise AssertionError(f"{name}: {detail}")


def run(name: str, command: list[str]) -> None:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    record(name, result.returncode == 0, (result.stdout + result.stderr)[-3000:])


def main() -> int:
    started = time.time()
    run("Python source and v5.1 QA compile", [sys.executable, "-m", "compileall", "-q", "rmr_platform", "qa/v51-acceptance.py", "qa/v51-browser.py", "qa/v51-upgrade-preservation.py", "qa/v51-static.py", "qa/v51rc3-upgrade-reliability.py"])

    js_files = sorted((ROOT / "public").rglob("*.js"))
    for path in js_files:
        run(f"JavaScript syntax: {path.relative_to(ROOT)}", ["node", "--check", str(path)])
    record("Expected JavaScript source inventory", len(js_files) >= 6, len(js_files))

    shell_files = sorted([*ROOT.glob("*.sh"), *(ROOT / "scripts").glob("*.sh")])
    for path in shell_files:
        run(f"Shell syntax: {path.relative_to(ROOT)}", ["sh", "-n", str(path)])
    record("Operational shell scripts present", len(shell_files) >= 11, [p.name for p in shell_files])

    version = (ROOT / "rmr_platform" / "__init__.py").read_text(encoding="utf-8")
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
    record("Application version is v5.3.1-final-production-corrections-po1", '5.3.1-final-production-corrections-po1' in version, version)
    record("Compose defaults to v5.3.1-final-production-corrections-po1", '5.3.1-final-production-corrections-po1' in compose_text, compose_text)
    record("Environment template defaults to v5.3.1-final-production-corrections-po1", 'RMR_APP_VERSION=5.3.1-final-production-corrections-po1' in env_text, env_text)
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    record("Project metadata is v5.3.1 Final Production Corrections", 'version = "5.3.1+final.production.corrections.po1"' in pyproject_text and 'RMR Global v5.3.1 Final Production Corrections Product Owner Candidate' in pyproject_text, pyproject_text[:400])

    compose = yaml.safe_load(compose_text)
    record("Docker Compose parses", isinstance(compose, dict) and "app" in compose.get("services", {}), compose)
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    record("Docker uses pinned base and non-root runtime", "FROM python:3.13-slim-bookworm" in dockerfile and "USER rmr" in dockerfile, dockerfile[:600])
    record("Docker health check included", "HEALTHCHECK" in dockerfile and "healthcheck:" in compose_text, "Dockerfile + compose")

    requirements = [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
    record("Python dependencies are pinned", all("==" in line for line in requirements), requirements)

    install_bat = (ROOT / "INSTALL.bat").read_text(encoding="utf-8", errors="replace")
    install_ps = (ROOT / "INSTALL.ps1").read_text(encoding="utf-8", errors="replace")
    install_sh = (ROOT / "INSTALL.sh").read_text(encoding="utf-8", errors="replace")
    record("Windows double-click installer preserves console", "pause" in install_bat.lower() and "INSTALL.ps1" in install_bat, install_bat)
    record("Windows installer verifies Docker engine", "docker info" in install_ps and "docker compose version" in install_ps, "INSTALL.ps1")
    record("Windows installer opens browser after robust health gate", "Start-Process" in install_ps and "HEALTH-CHECK.ps1" in install_ps and "MaxWaitSeconds 240" in install_ps, "INSTALL.ps1")
    record("Linux installer defaults to empty profile", 'profile="${1:-empty}"' in install_sh and "RMR_AUTO_SEED false" in install_sh, "INSTALL.sh")
    record("Separate demo and production Windows launchers", (ROOT / "INSTALL-DEMO.bat").exists() and (ROOT / "INSTALL-PRODUCTION.bat").exists(), "launchers")
    record("Windows v5.0 upgrade script included", (ROOT / "UPGRADE-FROM-V5.0.ps1").exists() and "safety backup" in (ROOT / "UPGRADE-FROM-V5.0.ps1").read_text(encoding="utf-8").lower(), "UPGRADE-FROM-V5.0.ps1")
    upgrade_ps = (ROOT / "UPGRADE-FROM-V5.0.ps1").read_text(encoding="utf-8")
    deployment_module = (ROOT / "scripts" / "RmrDeployment.psm1").read_text(encoding="utf-8")
    record("RC3 bounded readiness polling included", "Wait-RmrPlatformReady" in deployment_module and "MaxWaitSeconds" in deployment_module and "Test-RmrHostHealth" in deployment_module and "Test-RmrInternalHealth" in deployment_module, "scripts/RmrDeployment.psm1")
    record("RC3 diagnostics and machine-readable result included", "Write-RmrDiagnostics" in deployment_module and "LAST-UPGRADE-RESULT.json" in upgrade_ps and (ROOT / "COLLECT-DIAGNOSTICS.bat").exists(), "upgrade diagnostics")
    record("RC3 rollback verifies restored v5.0 health", "rollback-v50" in upgrade_ps and "MaxWaitSeconds 180" in upgrade_ps, "UPGRADE-FROM-V5.0.ps1")
    record("Linux v5.0 upgrade script included", (ROOT / "UPGRADE-FROM-V5.0.sh").exists(), "UPGRADE-FROM-V5.0.sh")
    common_sh = (ROOT / "scripts" / "common.sh").read_text(encoding="utf-8")
    record("Known v5.0 version alias is supported on Linux readiness too", "5.0.0-rc.1" in common_sh and "5.0.0-rc1" in common_sh and "def comparable(value)" in common_sh, "scripts/common.sh")
    record("Known v5.0 version alias is narrowly scoped on Windows", "ConvertTo-RmrComparableVersion" in deployment_module and "5.0.0-rc.1" in deployment_module and "5.0.0-rc1" in deployment_module, "scripts/RmrDeployment.psm1")

    setup_source = (ROOT / "rmr_platform" / "routes" / "setup.py").read_text(encoding="utf-8")
    auth_source = (ROOT / "rmr_platform" / "routes" / "auth.py").read_text(encoding="utf-8")
    access_source = (ROOT / "rmr_platform" / "access.py").read_text(encoding="utf-8")
    permission_source = (ROOT / "rmr_platform" / "permissions.py").read_text(encoding="utf-8")
    onboarding_source = (ROOT / "rmr_platform" / "routes" / "onboarding.py").read_text(encoding="utf-8")
    record("First-run setup verifies password and removes token file", "verify_password" in setup_source and "INITIAL-SETUP.txt" in setup_source and "unlink" in setup_source, "setup.py")
    record("Forgot password and one-time reset APIs exist", all(value in auth_source for value in ["/password-reset/request", "/password-reset/complete", "complete_password_reset"]), "auth.py")
    record("Client invitation activation exists", all(value in auth_source for value in ["/invitations/{token}", "/invitations/accept"]), "auth.py")
    record("Invitation and reset tokens are hashed and expiring", all(value in access_source for value in ["token_hash", "expires_at", "used_at"]), "access.py")
    record("Global admins require an authorized audited managed session for client writes", all(token in permission_source for token in ["_require_global_managed_write", "_managed_tenant_id", "managed_write", "authorized, audited client workspace session"]), "permissions.py")
    record("Go-live requires active Client Administrator", "active_client_admins" in onboarding_source and "client_admin_access" in onboarding_source, "onboarding.py")

    models = (ROOT / "rmr_platform" / "models.py").read_text(encoding="utf-8")
    record("Invitation/reset/cost models exist", all(name in models for name in ["class UserInvitation", "class PasswordResetToken", "class CostCategory", "class CostEntry", "class CostAllocationRule"]), "models.py")
    migration = (ROOT / "rmr_platform" / "migrations.py").read_text(encoding="utf-8")
    record("v5.1 additive migration is versioned", "005.001.000-functional-client-experience" in migration and "create_all" in migration, "migrations.py")
    record("Migration preserves v5.0 onboarding rows", "UPDATE onboarding_steps" in migration and "Tenant provisioning & client access" in migration, "migrations.py")

    portfolio_source = (ROOT / "rmr_platform" / "routes" / "portfolio.py").read_text(encoding="utf-8")
    service_source = (ROOT / "rmr_platform" / "routes" / "services.py").read_text(encoding="utf-8")
    system_source = (ROOT / "rmr_platform" / "routes" / "system.py").read_text(encoding="utf-8")
    record("Canonical tenant list endpoint supports selector", '@router.get("/tenants")' in portfolio_source, "portfolio.py")
    record("Client 360 includes access, website, onboarding and actions", all(value in portfolio_source for value in ['"access"', '"website"', '"onboarding"', '"actions"']), "portfolio.py")
    record("Partner Economics supports direct/shared/policy-pending costs", all(value in service_source for value in ["additional_direct_costs_cents", "allocated_shared_operating_costs_cents", "unallocated_policy_pending_cents"]), "services.py")
    record("System Health includes plain-language business status", "business_status" in system_source and "Recommended action" not in system_source, "system.py")

    cli_source = (ROOT / "rmr_platform" / "cli.py").read_text(encoding="utf-8")
    record("Masked owner recovery CLI exists", "recover-owner" in cli_source and "getpass" in cli_source, "cli.py")

    ui_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in [ROOT / "public" / "app.js", ROOT / "public" / "ui.js", ROOT / "public" / "pages" / "admin.js", ROOT / "public" / "pages" / "client.js"])
    forbidden = [
        r"break[- ]?glass",
        r"Exploration is not activation",
        r"RMR/Step2 review required",
        r"commercial review",
        r"Data ownership and allowed use",
        r"isolated workspace",
        r"Ownership Authority",
        r"Production-Readiness Gates",
        r"Client Value Demo",
        r"temporary[_ ]password",
    ]
    hits = [pattern for pattern in forbidden if re.search(pattern, ui_text, re.I)]
    record("Obsolete and internal prototype copy absent from active UI", not hits, hits)
    record("Client-facing shell separates global and tenant roles", "Portfolio operations" in ui_text and "Client operations" in ui_text, "UI shell")
    record("Global Back control and breadcrumbs implemented", "app-back" in ui_text and "breadcrumbs" in ui_text, "UI navigation")
    record("Add-client validation keeps modal open by default", "closeOnBackdrop=false" in (ROOT / "public" / "ui.js").read_text(encoding="utf-8") and "applyFieldErrors" in ui_text, "UI forms")
    record("First-run auth uses wider responsive layout", ".login-shell.auth-wide" in (ROOT / "public" / "styles.css").read_text(encoding="utf-8"), "styles.css")

    prohibited = [ROOT / ".env", *ROOT.rglob("*.db"), *ROOT.rglob("*.sqlite"), *ROOT.rglob("*.db-wal"), *ROOT.rglob("*.db-shm")]
    existing = [str(path.relative_to(ROOT)) for path in prohibited if path.exists()]
    record("No runtime database or live environment file", not existing, existing)

    table_count = len(re.findall(r"__tablename__\s*=", models))
    route_count = sum(1 for path in (ROOT / "rmr_platform" / "routes").glob("*.py") for line in path.read_text().splitlines() if line.lstrip().startswith("@router."))
    record("Substantive domain schema", table_count >= 30, table_count)
    record("Substantive API surface", route_count >= 85, route_count)

    required_docs = [
        "V5.0-QC-FINDINGS-V5.1-ACCEPTANCE-MATRIX.md",
        "V5.1-COMPLETED-QC-ACCEPTANCE-MATRIX.md",
        "V5.1-CHANGELOG.md",
        "V5.1-ROLE-PERMISSIONS-TEST-SUMMARY.md",
        "V5.1-KNOWN-ISSUES-AND-SERVER-DEPENDENT-TESTS.md",
        "V5.1-MANUAL-QC-SEQUENCE.md",
        "UPGRADE-FROM-V5.0.md",
        "V5.1-ROLLBACK.md",
        "V5.1-RC2-CHANGELOG.md",
        "V5.1-RC2-WINDOWS-UPGRADE-FAILURE-AND-CORRECTION.md",
        "V5.1-RC2-DIAGNOSTICS.md",
        "V5.1-RC2-MANUAL-WINDOWS-UPGRADE-QC.md",
        "V5.1-RC3-CHANGELOG.md",
        "V5.1-RC3-WINDOWS-PREFLIGHT-VERSION-CORRECTION.md",
        "V5.1-RC3-MANUAL-WINDOWS-UPGRADE-QC.md",
    ]
    missing_docs = [name for name in required_docs if not (ROOT / "docs" / name).exists()]
    record("Required v5.1 release documents exist", not missing_docs, missing_docs)

    result = {
        "status": "passed",
        "release": "5.3.1-final-production-corrections-po1",
        "passed": sum(1 for item in checks if item["ok"]),
        "failed": sum(1 for item in checks if not item["ok"]),
        "duration_seconds": round(time.time() - started, 2),
        "inventory": {"javascript_files": len(js_files), "shell_files": len(shell_files), "tables": table_count, "api_routes": route_count},
        "checks": checks,
    }
    REPORT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ["status", "passed", "failed", "duration_seconds", "inventory"]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        REPORT.write_text(json.dumps({"status": "failed", "error": str(exc), "checks": checks}, indent=2, default=str), encoding="utf-8")
        raise
