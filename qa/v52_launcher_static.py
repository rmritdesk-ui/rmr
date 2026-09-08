#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa" / "V52-LAUNCHER-STATIC-RESULTS.json"
RELEASE = "5.3.1-final-production-corrections-po1"
checks: list[dict[str, object]] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "passed": bool(ok), "detail": detail})


def read(name: str) -> str:
    path = ROOT / name
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

bat = read("START-PRODUCT-OWNER-TEST.bat")
ps = read("START-PRODUCT-OWNER-TEST.ps1")
compose = read("docker-compose.product-owner.yml")
stop_ps = read("STOP-PRODUCT-OWNER-TEST.ps1")
reset_ps = read("RESET-PRODUCT-OWNER-DEMO.ps1")
diag_ps = read("COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1")
manifest_tool = read("qa/package-manifest.py")

required_files = [
    "START-PRODUCT-OWNER-TEST.bat", "START-PRODUCT-OWNER-TEST.ps1",
    "STOP-PRODUCT-OWNER-TEST.bat", "STOP-PRODUCT-OWNER-TEST.ps1",
    "RESET-PRODUCT-OWNER-DEMO.bat", "RESET-PRODUCT-OWNER-DEMO.ps1",
    "COLLECT-PRODUCT-OWNER-DIAGNOSTICS.bat", "COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1",
    "docker-compose.product-owner.yml", "PRODUCT-OWNER-DEMO-CREDENTIALS.txt",
]
check("All Product Owner launcher/control files exist", all((ROOT / x).is_file() for x in required_files), [x for x in required_files if not (ROOT / x).is_file()])
check("Batch launcher invokes exact PowerShell launcher", "START-PRODUCT-OWNER-TEST.ps1" in bat and "ExecutionPolicy Bypass" in bat and "pause" in bat.lower())
check("Launcher identifies exact release", f'$Release = "{RELEASE}"' in ps, RELEASE)
check("Launcher uses isolated Docker project", '$Project = "rmr-global-v531-product-owner"' in ps and '-p",$Project' in ps)
check("Launcher uses isolated local port 8084", "$Port = 8084" in ps and "RMR_PUBLIC_PORT=$Port" in ps)
check("Launcher verifies packaged SHA-256 manifest", all(x in ps for x in ["Verify-Manifest", "Get-FileHash", "PACKAGE-MANIFEST.json", "checksum mismatch"]))
check("Launcher checks Docker engine and Compose", all(x in ps for x in ['Get-Command docker.exe', '@("version")', '@("compose","version")']))
check("Launcher creates stable protected local secrets", all(x in ps for x in ["New-Secret", "RMR_SECRET_KEY=", "RMR_CREDENTIAL_ENCRYPTION_KEY=", "RMR_INTEGRATION_ENCRYPTION_KEY="]))
check("Launcher protects existing demo data by default", "Reusing the existing Product Owner configuration and demo data" in ps and "product-owner-data" in ps)
check("Launcher stops only its isolated project before startup", 'ComposeArgs @("down","--remove-orphans")' in ps)
check("Launcher detects port conflict before startup", "Test-Port" in ps and "already in use" in ps)
check("Launcher builds and starts final application", 'ComposeArgs @("up","-d","--build")' in ps)
check("Launcher enforces health/database/storage/version readiness", all(x in ps for x in ["$health.status -eq \"healthy\"", "$health.version -eq $Release", "$health.checks.database.ok", "$health.checks.storage.ok"]))
check("Launcher runs comprehensive in-container functional QC", "rmr_platform.product_owner_qc" in ps and "PRODUCT-OWNER-QC-LATEST.json" in ps)
check("Launcher performs controlled restart and persistence QC", all(x in ps for x in ['ComposeArgs @("restart","app")', "--verify-persistence", "PRODUCT-OWNER-PERSISTENCE-QC-LATEST.json"]))
check("Launcher automatically records machine-readable result", "LAST-PRODUCT-OWNER-START.json" in ps and "Write-Result" in ps)
check("Launcher automatically collects diagnostics on failure", "Collect-Failure" in ps and "COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1" in ps)
check("Launcher opens the product only after all gates pass", ps.rfind('Start-Process "http://localhost:$Port"') > ps.rfind("Restart persistence passed"))
check("Compose uses exact application release", RELEASE in compose and "RMR_APP_VERSION" in compose)
check("Compose uses isolated bind data directory", "./product-owner-data:/data" in compose)
check("Compose performs exact-release healthcheck", "api/health" in compose and RELEASE in compose and "healthy" in compose)
check("Stop command targets only isolated project", "rmr-global-v531-product-owner" in stop_ps and "docker compose" in stop_ps.lower())
check("Reset command archives rather than silently deletes demo data", "product-owner-data-archive" in reset_ps and "Move-Item" in reset_ps)
check("Diagnostic collector captures Docker, Compose, logs, health, env posture, and QC evidence", all(x.lower() in diag_ps.lower() for x in ["docker version", "docker compose", "ps -a", "logs --timestamps", "api/health", ".env.product-owner", "qc-results"]))
check("Package-manifest tool excludes runtime secrets and databases", all(x in manifest_tool for x in ["RUNTIME_FILES", '"data"', "rmr_platform.db"]))
check("PowerShell scripts contain only ASCII control characters", all(ord(ch) >= 32 or ch in "\r\n\t" for ch in ps + stop_ps + reset_ps + diag_ps))
# Basic structural guard that catches common accidental truncation/mismatched braces outside strings/comments.
brace_delta = ps.count("{") - ps.count("}")
paren_delta = ps.count("(") - ps.count(")")
check("Launcher has balanced structural delimiters", brace_delta == 0 and paren_delta == 0, {"brace_delta": brace_delta, "paren_delta": paren_delta})
check("No placeholder or unfinished launcher markers remain", not re.search(r"(?i)\bTODO\b|PLACEHOLDER|NOT IMPLEMENTED", ps + compose + diag_ps))

result = {
    "status": "passed" if all(row["passed"] for row in checks) else "failed",
    "release": RELEASE,
    "passed": sum(1 for row in checks if row["passed"]),
    "failed": sum(1 for row in checks if not row["passed"]),
    "checks": checks,
}
OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: result[k] for k in ("status", "passed", "failed")}, indent=2))
raise SystemExit(0 if result["status"] == "passed" else 1)
